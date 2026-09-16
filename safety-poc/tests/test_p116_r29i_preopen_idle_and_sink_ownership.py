from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29i_preopen_idle_transform.py"
MODEL = MEDIA / "entrance_p116_r29i_preopen_idle_model.py"
RUNNER = MEDIA / "ct120_run_p116_r29i_preopen_idle_sink_live.sh"
SINK = MEDIA / "r29i_udp_sink.py"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29i_preopen_idle_model as r29i_model
import entrance_p116_r29i_preopen_idle_transform as r29i


class P116R29IPreopenIdleAndSinkOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29i.transform(SOURCE.read_text(encoding="utf-8"))
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_waiting_for_ring_idle_timeout_survives_pre_call(self) -> None:
        timeout_start = self.generated.index("entrance_signal_timeout_cb")
        timeout_end = self.generated.index(
            "static void\np12_tx_completed",
            timeout_start,
        )
        timeout_cb = self.generated[timeout_start:timeout_end]

        waiting_gate = """r29_listener_registered_ready &&
        !r29_call_transaction_created &&
        !r29_call_transaction_active &&
        !r29c_registered_ctpp_mediareq26_open_sent &&
        r29h_lifetime_phase == R29H_LIFETIME_PRE_OPEN"""
        self.assertIn(waiting_gate, timeout_cb)
        self.assertIn("R29I_WAITING_FOR_RING_IDLE_TIMEOUT_DEFERRED=true", timeout_cb)
        self.assertIn("return G_SOURCE_CONTINUE;", timeout_cb)
        self.assertLess(
            timeout_cb.index("R29I_WAITING_FOR_RING_IDLE_TIMEOUT_DEFERRED=true"),
            timeout_cb.index("failed = TRUE;"),
        )

    def test_call_transaction_remains_strictly_fail_closed_before_open(self) -> None:
        timeout_start = self.generated.index("entrance_signal_timeout_cb")
        timeout_end = self.generated.index(
            "static void\np12_tx_completed",
            timeout_start,
        )
        timeout_cb = self.generated[timeout_start:timeout_end]

        self.assertIn("!r29_call_transaction_created", timeout_cb)
        self.assertIn("!r29_call_transaction_active", timeout_cb)
        self.assertNotIn("R29I_PREOPEN_CALL_GRACE_ACTIVE", timeout_cb)
        self.assertIn("failed = TRUE;", timeout_cb)
        self.assertIn("g_main_loop_quit(loop);", timeout_cb)

    def test_virtual_30s_and_60s_idle_timeouts_survive_then_call_is_fail_closed(self) -> None:
        events, post_call = r29i_model.simulate_idle_then_call(
            ring_window_seconds=90,
            inherited_timeout_seconds=30,
            call_at_seconds=90,
        )
        self.assertEqual([t for t, _ in events], [30, 60])
        self.assertTrue(
            all(
                action is r29i_model.Action.CONTINUE_WAITING_FOR_RING
                for _, action in events
            )
        )
        self.assertIs(post_call, r29i_model.Action.FAIL_CLOSED)

    def test_virtual_call_at_60s_after_long_idle_is_accepted_by_lifetime_model(self) -> None:
        events, post_call = r29i_model.simulate_idle_then_call(
            ring_window_seconds=90,
            inherited_timeout_seconds=30,
            call_at_seconds=60,
        )
        self.assertEqual(events, [(30, r29i_model.Action.CONTINUE_WAITING_FOR_RING)])
        self.assertIs(post_call, r29i_model.Action.FAIL_CLOSED)

    def test_transport_and_registration_failures_remain_fail_closed_while_idle(self) -> None:
        self.assertIs(
            r29i_model.entrance_signaling_timeout(
                r29i_model.State(transport_healthy=False)
            ),
            r29i_model.Action.FAIL_CLOSED,
        )
        self.assertIs(
            r29i_model.entrance_signaling_timeout(
                r29i_model.State(registration_healthy=False)
            ),
            r29i_model.Action.FAIL_CLOSED,
        )

    def test_post_open_r29h_bounded_section_is_preserved(self) -> None:
        for marker in (
            "r29h_defer_inherited_main_loop_quit",
            "R29H_INHERITED_MAIN_LOOP_QUIT_DEFERRED=true",
            "R29H_LIFETIME_OBSERVING",
            "R29H_LIFETIME_WAITING_FOR_STOP",
            "R29H_LIFETIME_POST_STOP",
        ):
            self.assertIn(marker, self.generated)
        self.assertIs(
            r29i_model.entrance_signaling_timeout(
                r29i_model.State(open_sent=True, post_open_bounded_section=True)
            ),
            r29i_model.Action.DEFER_TO_R29H_BOUNDED_SECTION,
        )

    def test_mediareq26_and_safety_surfaces_unchanged(self) -> None:
        for marker in (
            "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
            "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
            "ONE_SHOT_OPEN_GATE=%s",
            "ONE_SHOT_STOP_GATE=%s",
            "SELF_ACTIVATION_001A_SENT_COUNT=%u",
            "R27_REPEAT_001A_SENT_COUNT=%u",
            "DOOR_ACTIONS_SENT=%u",
            "GATE_ACTIONS_SENT=%u",
            "REFRESH_LOOP_STARTED_COUNT=%u",
        ):
            self.assertIn(marker, self.generated)
        self.assertNotIn("p78_queue_rtpc_client_001a();", self.generated)

    @staticmethod
    def _free_udp_port() -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def test_zero_datagram_finalization_materializes_zero_after_join(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            count_file = root / "video.count"
            first_file = root / "video.first"
            done_file = root / "video.done"
            port = self._free_udp_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(SINK),
                    "--port",
                    str(port),
                    "--count-file",
                    str(count_file),
                    "--first-file",
                    str(first_file),
                    "--done-file",
                    str(done_file),
                    "--timeout-seconds",
                    "10",
                ],
                cwd=REPO,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.25)
            proc.terminate()
            self.assertEqual(proc.wait(timeout=3), 0)
            self.assertTrue(done_file.exists())
            self.assertEqual(count_file.read_text(encoding="utf-8").strip(), "0")
            self.assertFalse(first_file.exists())

    def test_nonzero_datagram_finalization_materializes_exact_count_after_join(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            count_file = root / "video.count"
            first_file = root / "video.first"
            done_file = root / "video.done"
            port = self._free_udp_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(SINK),
                    "--port",
                    str(port),
                    "--count-file",
                    str(count_file),
                    "--first-file",
                    str(first_file),
                    "--done-file",
                    str(done_file),
                    "--timeout-seconds",
                    "10",
                ],
                cwd=REPO,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.25)
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                for idx in range(5):
                    sender.sendto(f"pkt-{idx}".encode(), ("127.0.0.1", port))
            finally:
                sender.close()
            time.sleep(0.25)
            proc.terminate()
            self.assertEqual(proc.wait(timeout=3), 0)
            self.assertEqual(count_file.read_text(encoding="utf-8").strip(), "5")
            self.assertTrue(done_file.exists())
            self.assertTrue(first_file.exists())

    def test_runner_uses_done_marker_join_contract_not_wait_builtin(self) -> None:
        for marker in (
            "SINK_HELPER_REL=",
            "wait_for_sink_done()",
            "video.done",
            "audio.done",
            "SINK_FINALIZATION_CONTRACT=COUNT_THEN_DONE_MARKER",
            "PHYSICAL_RING_REPORTED_BY_USER=UNAVAILABLE_TO_RUNNER",
            "RING_PROMPT_ISSUED_COUNT=",
            "CALL_INIT_OBSERVED_COUNT=",
        ):
            self.assertIn(marker, self.runner)
        finalize_start = self.runner.index("finalize_sinks()")
        finalize_end = self.runner.index("# This function is called exactly once", finalize_start)
        finalize_body = self.runner[finalize_start:finalize_end]
        self.assertNotIn('wait "$VIDEO_SINK_PID"', finalize_body)
        self.assertNotIn('wait "$AUDIO_SINK_PID"', finalize_body)
        self.assertIn('wait_for_sink_done "$VIDEO_SINK_PID"', finalize_body)
        self.assertIn('wait_for_sink_done "$AUDIO_SINK_PID"', finalize_body)

    def test_runner_has_exact_r29i_lineage_gate(self) -> None:
        for marker in (
            "R29I_BASE_MAIN_SHA",
            "r29i_lineage_gate()",
            "R29I_MAIN_LINEAGE_GATE=PASS",
            "R29I_MAIN_LINEAGE_GATE=FAIL",
            "SINK_HELPER_REL",
            "MODEL_REL",
            "DOC_REL",
            "TEST_REL",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn('R29C_MAIN_SHA=""', self.runner)
        self.assertNotIn("grep -v '^safety-poc/'", self.runner)

    def test_runner_wrapper_parses_and_python_files_compile(self) -> None:
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)
        for path in (TRANSFORM, MODEL, SINK):
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(path)],
                cwd=REPO,
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
