from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c
from entrance_p116_r29h_lifetime_model import R29HLifetimeModel, reproduce_r29g_sequence


class P116R29HLifetimeAndEvidenceHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29c.transform(SOURCE.read_text(encoding="utf-8"))
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_r29g_sequence_defers_inherited_timeout_until_stop(self) -> None:
        evidence = reproduce_r29g_sequence()
        self.assertEqual(evidence["before_end"]["OPEN_SENT"], 1)
        self.assertFalse(evidence["before_end"]["MAIN_LOOP_EXIT_BEFORE_OBSERVATION_END"])
        self.assertEqual(evidence["before_end"]["DEFERRED_PATHS"], ("ENTRANCE_SIGNALING_TIMEOUT",))
        self.assertTrue(evidence["at_end"]["R29C_RTP_OBSERVATION_ENDED"])
        self.assertTrue(evidence["at_end"]["RTP_WINDOW_FULLY_OBSERVED"])
        self.assertTrue(evidence["at_end"]["R29C_WAITING_FOR_STOP"])
        self.assertEqual(evidence["final"]["STOP_SENT_COUNT"], 1)
        self.assertTrue(evidence["final"]["PROCESS_REMAINS_VALID_THROUGH_STOP"])
        self.assertTrue(evidence["final"]["CONTROLLED_EXIT"])

    def test_negative_timeout_before_call_init_and_before_open_fail_closed(self) -> None:
        before_call = R29HLifetimeModel()
        before_call.ready()
        before_call.inherited_signaling_timeout()
        self.assertEqual(before_call.terminal_reason, "ENTRANCE_SIGNALING_TIMEOUT_BEFORE_OPEN")
        self.assertFalse(before_call.process_valid)

        before_open = R29HLifetimeModel()
        before_open.ready()
        before_open.entrance_call_init()
        before_open.inherited_signaling_timeout()
        self.assertEqual(before_open.terminal_reason, "ENTRANCE_SIGNALING_TIMEOUT_BEFORE_OPEN")
        self.assertFalse(before_open.process_valid)

    def test_negative_post_open_failures_attempt_single_stop_when_possible(self) -> None:
        for method, abort_class in (
            ("transport_hard_failure", "TRANSPORT_HARD_FAILURE_AFTER_OPEN"),
            ("observation_timer_failure", "OBSERVATION_TIMER_CALLBACK_FAILURE"),
        ):
            model = R29HLifetimeModel()
            model.ready()
            model.entrance_call_init()
            model.send_open()
            getattr(model, method)()
            self.assertEqual(model.abort_class, abort_class)
            self.assertEqual(model.stop_sent_count, 1)
            self.assertTrue(model.controlled_exit)

        stop_fail = R29HLifetimeModel()
        stop_fail.ready()
        stop_fail.entrance_call_init()
        stop_fail.send_open()
        stop_fail.advance_to_observation_end()
        stop_fail.send_stop(send_ok=False)
        self.assertEqual(stop_fail.stop_sent_count, 1)
        self.assertEqual(stop_fail.abort_class, "STOP_SEND_FAILURE")

        unexpected = R29HLifetimeModel()
        unexpected.ready()
        unexpected.entrance_call_init()
        unexpected.send_open()
        unexpected.unexpected_exit()
        self.assertEqual(unexpected.terminal_reason, "UNEXPECTED_EARLY_CANDIDATE_EXIT")
        self.assertFalse(unexpected.process_valid)

    def test_generated_candidate_owns_post_open_lifetime(self) -> None:
        for marker in (
            "r29h_defer_inherited_main_loop_quit",
            "R29H_INHERITED_MAIN_LOOP_QUIT_DEFERRED=true",
            "MAIN_LOOP_EXIT_BEFORE_OBSERVATION_END=false",
            "r29h_lifetime_phase = R29H_LIFETIME_OBSERVING;",
            "r29h_lifetime_phase = R29H_LIFETIME_WAITING_FOR_STOP;",
            "r29h_lifetime_phase = R29H_LIFETIME_POST_STOP;",
            "r29h_controlled_exit_after_stop = TRUE;",
        ):
            self.assertIn(marker, self.generated)
        timeout_cb = self.generated[
            self.generated.index("entrance_signal_timeout_cb") :
            self.generated.index("static void\np12_tx_completed", self.generated.index("entrance_signal_timeout_cb"))
        ]
        self.assertIn("r29h_defer_inherited_main_loop_quit", timeout_cb)
        self.assertIn('"ENTRANCE_SIGNALING_TIMEOUT"', timeout_cb)
        self.assertLess(timeout_cb.index("r29h_defer_inherited_main_loop_quit"), timeout_cb.index("failed = TRUE;"))

    def test_runner_measures_liveness_and_blocks_pass_on_contradiction(self) -> None:
        for marker in (
            "process_running_state()",
            "PROCESS_RUNNING_AFTER_OPEN=",
            "PROCESS_RUNNING_AT_OBSERVATION_END=",
            "PROCESS_RUNNING_BEFORE_STOP=",
            "PROCESS_RUNNING_AFTER_STOP=",
            "PROCESS_EXIT_STATUS=",
            "LIVENESS_EVIDENCE=CONTRADICTION",
            "RESULT=INCONCLUSIVE_TOOLING_FAILURE",
        ):
            self.assertIn(marker, self.runner)
        self.assertNotIn("PROCESS_ALIVE_AFTER_OBSERVATION=true\n", self.runner)
        self.assertNotIn("PROCESS_ALIVE_BEFORE_STOP=\"$PROCESS_ALIVE_AFTER_OBSERVATION\"", self.runner)

    def test_runner_finalizes_sinks_and_does_not_materialize_missing_as_zero(self) -> None:
        for marker in (
            "VIDEO_SINK_STARTED=",
            "VIDEO_SINK_FINALIZED=",
            "VIDEO_FINAL_DATAGRAM_COUNT=",
            "AUDIO_SINK_STARTED=",
            "AUDIO_SINK_FINALIZED=",
            "AUDIO_FINAL_DATAGRAM_COUNT=",
            "tmp.replace(count_file)",
            'read_sink_count "$RUN_ROOT/video.count" UNKNOWN',
            'read_sink_count "$RUN_ROOT/audio.count" UNKNOWN',
        ):
            self.assertIn(marker, self.runner)
        self.assertNotRegex(self.runner, re.compile(r"read_sink_count .* 0[)\" ]"))

    def test_runner_separates_clock_domains_and_duration_source(self) -> None:
        for marker in (
            "RUNNER_MONOTONIC_OPEN_OBSERVED_AT_MS=",
            "RUNNER_MONOTONIC_RTP_OBSERVATION_STARTED_AT_MS=",
            "RUNNER_MONOTONIC_RTP_OBSERVATION_ENDED_AT_MS=",
            "RUNNER_MONOTONIC_STOP_ATTEMPT_AT_MS=",
            "RTP_OBSERVATION_DURATION_MS=",
            "now_mono_ms()",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn(
            "RTP_OBSERVATION_DURATION_MS=\"$((RUNNER_MONOTONIC_RTP_OBSERVATION_ENDED_AT_MS - RUNNER_MONOTONIC_RTP_OBSERVATION_STARTED_AT_MS))\"",
            self.runner,
        )

    def test_generated_source_safety_invariants_remain(self) -> None:
        for marker in (
            "SELF_ACTIVATION_001A_SENT_COUNT=%u",
            "R27_REPEAT_001A_SENT_COUNT=%u",
            "DOOR_ACTIONS_SENT=%u",
            "GATE_ACTIONS_SENT=%u",
            "REFRESH_LOOP_STARTED_COUNT=%u",
            "ONE_SHOT_OPEN_GATE=%s",
            "ONE_SHOT_STOP_GATE=%s",
        ):
            self.assertIn(marker, self.generated)
        self.assertNotIn("p78_queue_rtpc_client_001a();", self.generated)

    def test_parse_and_compile(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(MEDIA / "entrance_p116_r29h_lifetime_model.py")],
            cwd=REPO,
            check=True,
        )
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)
