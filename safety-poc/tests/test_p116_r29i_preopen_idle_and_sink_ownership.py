from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29i_preopen_idle_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29i_preopen_idle_and_sink_ownership.sh"
BASE_RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29i_preopen_idle_transform as r29i


class WaitingForRingModel:
    """Deterministic model of the R29I timeout ownership predicate."""

    def __init__(self) -> None:
        self.listener_ready = True
        self.registered = True
        self.registered_idle = True
        self.call_created = False
        self.call_active = False
        self.open_sent = False
        self.alive = True
        self.suppressed = 0

    def inherited_timeout(self) -> None:
        idle_wait = (
            self.listener_ready
            and self.registered
            and self.registered_idle
            and not self.call_created
            and not self.call_active
            and not self.open_sent
        )
        if idle_wait:
            self.suppressed += 1
            return
        self.alive = False

    def call_init(self) -> None:
        if not self.alive:
            raise RuntimeError("candidate already dead")
        self.call_created = True
        self.call_active = True
        self.registered_idle = False


class P116R29IPreopenIdleAndSinkOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29i.transform(SOURCE.read_text(encoding="utf-8"))
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.base_runner = BASE_RUNNER.read_text(encoding="utf-8")

    def test_waiting_for_ring_survives_inherited_timeout_and_late_call_init(self) -> None:
        model = WaitingForRingModel()
        # Model the stale inherited timer at ~30 s, then a human CALL_INIT at 60 s.
        model.inherited_timeout()
        self.assertTrue(model.alive)
        self.assertEqual(model.suppressed, 1)
        model.call_init()
        self.assertTrue(model.alive)
        self.assertTrue(model.call_created)

        # A second signaling timeout after the call begins is not an idle wait
        # and therefore remains fail-closed.
        model.inherited_timeout()
        self.assertFalse(model.alive)

    def test_waiting_for_ring_90s_is_owned_by_runner_not_stale_signaling_timer(self) -> None:
        self.assertIn('source "$BASE_RUNNER"', self.runner)
        self.assertIn("R29C_RING_MAX_SECONDS=${R29C_RING_MAX_SECONDS:-90}", self.base_runner)
        self.assertIn("R29I_WAITING_FOR_RING_BOUNDED_BY_RUNNER=true", self.generated)
        self.assertIn("R29I_WAITING_FOR_RING_TIMEOUT_SUPPRESSED=true", self.generated)

    def test_generated_timeout_guard_is_narrow_and_fail_closed_after_idle(self) -> None:
        start = self.generated.index("entrance_signal_timeout_cb")
        end = self.generated.index("static void\np12_tx_completed", start)
        callback = self.generated[start:end]

        required_guard = (
            "r29_listener_registered_ready &&",
            "v4_registered &&",
            "r29_attached_media_state == R29_LISTENER_REGISTERED_READY",
            "!r29_call_transaction_created",
            "!r29_call_transaction_active",
            "!r29c_registered_ctpp_mediareq26_open_sent",
        )
        for marker in required_guard:
            self.assertIn(marker, callback)

        idle = callback.index("R29I_WAITING_FOR_RING_TIMEOUT_SUPPRESSED=true")
        inherited = callback.index("r29h_defer_inherited_main_loop_quit", idle)
        fail_closed = callback.index("failed = TRUE;", inherited)
        quit_loop = callback.index("g_main_loop_quit(loop);", fail_closed)
        self.assertLess(idle, inherited)
        self.assertLess(inherited, fail_closed)
        self.assertLess(fail_closed, quit_loop)

    def test_real_registration_loss_does_not_match_idle_suppression_predicate(self) -> None:
        model = WaitingForRingModel()
        model.registered = False
        model.inherited_timeout()
        self.assertFalse(model.alive)
        self.assertEqual(model.suppressed, 0)

    def test_mediareq26_and_forbidden_action_semantics_are_unchanged(self) -> None:
        for marker in (
            "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
            "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
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

    @staticmethod
    def _free_udp_port() -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return int(port)

    def _run_sink_case(self, datagrams: int) -> str:
        video_port = self._free_udp_port()
        audio_port = self._free_udp_port()
        with tempfile.TemporaryDirectory() as tmp:
            script = textwrap.dedent(
                r'''
                set -euo pipefail
                export R29I_UNIT_TEST=1
                source "$1"
                RUN_ROOT="$2"
                R29C_OUTER_TIMEOUT_SECONDS=20
                R29I_SINK_JOIN_TIMEOUT_SECONDS=5
                VIDEO_SINK_PID="$(start_udp_sink "$3" "$RUN_ROOT/video.count" "$RUN_ROOT/video.first" VIDEO)"
                AUDIO_SINK_PID="$(start_udp_sink "$4" "$RUN_ROOT/audio.count" "$RUN_ROOT/audio.first" AUDIO)"
                VIDEO_SINK_STARTED=true
                AUDIO_SINK_STARTED=true
                sleep 0.4
                python3 - "$3" "$5" <<'PY'
import socket
import sys
port = int(sys.argv[1])
count = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for i in range(count):
    sock.sendto((b"rtp" + bytes([i % 251])), ("127.0.0.1", port))
sock.close()
PY
                sleep 0.2
                finalize_sinks
                printf 'VIDEO=%s\n' "$VIDEO_FINAL_DATAGRAM_COUNT"
                printf 'AUDIO=%s\n' "$AUDIO_FINAL_DATAGRAM_COUNT"
                printf 'VIDEO_FINALIZED=%s\n' "$VIDEO_SINK_FINALIZED"
                printf 'AUDIO_FINALIZED=%s\n' "$AUDIO_SINK_FINALIZED"
                printf 'SINKS_FINALIZED=%s\n' "$SINKS_FINALIZED"
                if sink_process_active "$VIDEO_SINK_PID"; then exit 71; fi
                if sink_process_active "$AUDIO_SINK_PID"; then exit 72; fi
                '''
            )
            proc = subprocess.run(
                [
                    "bash",
                    "-c",
                    script,
                    "r29i-sink-test",
                    str(RUNNER),
                    tmp,
                    str(video_port),
                    str(audio_port),
                    str(datagrams),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )
            return proc.stdout

    def test_zero_datagram_sink_is_joined_and_materializes_zero(self) -> None:
        output = self._run_sink_case(0)
        self.assertIn("VIDEO_SINK_JOIN=PASS", output)
        self.assertIn("AUDIO_SINK_JOIN=PASS", output)
        self.assertIn("VIDEO=0", output)
        self.assertIn("AUDIO=0", output)
        self.assertIn("VIDEO_FINALIZED=true", output)
        self.assertIn("AUDIO_FINALIZED=true", output)
        self.assertIn("SINKS_FINALIZED=true", output)
        self.assertIn("R29I_FINAL_COUNTERS_READ_AFTER_JOIN=true", output)

    def test_nonzero_datagram_sink_is_joined_and_materializes_exact_count(self) -> None:
        output = self._run_sink_case(5)
        self.assertIn("VIDEO_SINK_JOIN=PASS", output)
        self.assertIn("AUDIO_SINK_JOIN=PASS", output)
        self.assertIn("VIDEO=5", output)
        self.assertIn("AUDIO=0", output)
        self.assertIn("SINKS_FINALIZED=true", output)

    def test_runner_no_longer_relies_on_wait_for_non_child_sink_pids(self) -> None:
        start = self.runner.index("finalize_sinks()")
        end = self.runner.index("# Override only the polling wrapper", start)
        finalizer = self.runner[start:end]
        self.assertNotIn('wait "$VIDEO_SINK_PID"', finalizer)
        self.assertNotIn('wait "$AUDIO_SINK_PID"', finalizer)
        self.assertIn("terminate_and_join_sink", finalizer)
        self.assertIn("/proc/$pid/stat", self.runner)
        self.assertIn("R29I_FINAL_COUNTERS_READ_AFTER_JOIN=true", finalizer)

    def test_ring_evidence_semantics_do_not_infer_physical_press(self) -> None:
        for marker in (
            "RING_PROMPT_ISSUED_COUNT=",
            "PHYSICAL_RING_REPORTED_BY_USER=",
            "CALL_INIT_OBSERVED_COUNT=",
            "RING_BUDGET_MEANING=CALL_INIT_ACCEPTED_NOT_PHYSICAL_PRESS",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("R29I_PHYSICAL_RING_REPORTED_BY_USER:-UNKNOWN", self.runner)

    def test_exact_r29i_lineage_allowlist_is_fail_closed(self) -> None:
        for path in (
            "^$RUNNER_REL$",
            "^$TRANSFORM_REL$",
            "^$R29I_DOC_REL$",
            "^$R29I_TEST_REL$",
        ):
            self.assertIn(path, self.runner)
        self.assertIn("R29I_MAIN_LINEAGE_GATE=FAIL", self.runner)
        self.assertIn("R29I_MAIN_LINEAGE_GATE=PASS", self.runner)
        self.assertNotIn("safety-poc/research/media/v1/.*", self.runner)
        self.assertNotIn("custom_components/", self.runner)

    def test_parse_and_compile(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
