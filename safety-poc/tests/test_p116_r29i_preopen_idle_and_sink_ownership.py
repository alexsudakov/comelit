from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29i_preopen_idle_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29i_preopen_idle_live.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29i_preopen_idle_transform as r29i
from entrance_p116_r29i_preopen_idle_model import R29IPreOpenIdleModel


class P116R29IPreOpenIdleAndSinkOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29i.transform(SOURCE.read_text(encoding="utf-8"))
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_waiting_for_ring_survives_inherited_timeout_and_long_idle(self) -> None:
        model = R29IPreOpenIdleModel()
        model.ready()
        model.advance_waiting_for_ring(30_000)
        model.inherited_signaling_timeout()
        self.assertTrue(model.process_valid)
        self.assertTrue(model.waiting_for_ring)
        self.assertEqual(model.idle_timeout_deferred_count, 1)
        model.advance_waiting_for_ring(60_000)
        self.assertEqual(model.now_ms, 90_000)
        self.assertTrue(model.process_valid)
        model.entrance_call_init()
        self.assertTrue(model.call_init)
        self.assertFalse(model.waiting_for_ring)
        model.send_open()
        self.assertEqual(model.open_sent_count, 1)

    def test_real_preopen_transport_failure_still_fails_closed(self) -> None:
        model = R29IPreOpenIdleModel()
        model.ready()
        model.transport_hard_failure()
        self.assertFalse(model.process_valid)
        self.assertTrue(model.controlled_exit)
        self.assertEqual(model.abort_class, "TRANSPORT_HARD_FAILURE_PRE_OPEN")

    def test_call_transaction_timeout_before_open_still_fails_closed(self) -> None:
        model = R29IPreOpenIdleModel()
        model.ready()
        model.entrance_call_init()
        model.inherited_signaling_timeout()
        self.assertFalse(model.process_valid)
        self.assertEqual(model.terminal_reason, "ENTRANCE_SIGNALING_TIMEOUT_BEFORE_OPEN")

    def test_generated_callback_defers_only_registered_ready_idle(self) -> None:
        start = self.generated.index("entrance_signal_timeout_cb")
        end = self.generated.index("static void\np12_tx_completed", start)
        callback = self.generated[start:end]
        for marker in (
            "r29_listener_registered_ready",
            "r29_attached_media_state == R29_LISTENER_REGISTERED_READY",
            "!r29_call_transaction_created",
            "!r29_call_transaction_active",
            "!r29c_registered_ctpp_mediareq26_open_sent",
            "R29I_WAITING_FOR_RING_SIGNALING_TIMEOUT_DEFERRED=true",
            "r29h_defer_inherited_main_loop_quit",
            "failed = TRUE;",
        ):
            self.assertIn(marker, callback)
        self.assertLess(
            callback.index("R29I_WAITING_FOR_RING_SIGNALING_TIMEOUT_DEFERRED=true"),
            callback.index("r29h_defer_inherited_main_loop_quit"),
        )
        self.assertLess(
            callback.index("r29h_defer_inherited_main_loop_quit"),
            callback.index("failed = TRUE;"),
        )

    def test_mediareq26_semantics_are_inherited_unchanged(self) -> None:
        base = __import__("entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform")
        base_generated = base.transform(SOURCE.read_text(encoding="utf-8"))
        for marker in (
            "MEDIAREQ26_OPEN_STRUCTURAL_LAYOUT=PASS",
            "MEDIAREQ26_STOP_STRUCTURAL_LAYOUT=PASS",
            "ONE_SHOT_OPEN_GATE=%s",
            "ONE_SHOT_STOP_GATE=%s",
        ):
            self.assertEqual(self.generated.count(marker), base_generated.count(marker))

    def _run_sink_case(self, datagrams: int) -> dict[str, str]:
        script = f'''set -euo pipefail
export R29I_UNIT_TEST=1
source "{RUNNER}"
RUN_ROOT="$(mktemp -d)"
R29C_OUTER_TIMEOUT_SECONDS=30
VIDEO_SINK_PID="$(start_udp_sink 18991 "$RUN_ROOT/video.count" "$RUN_ROOT/video.first" VIDEO)"
VIDEO_SINK_STARTED=true
AUDIO_SINK_PID=""
AUDIO_SINK_STARTED=false
for i in $(seq 1 50); do
  sink_bound 18991 && break
  sleep 0.05
done
sink_bound 18991
'''
        if datagrams:
            script += f'''python3 - <<'SEND'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for i in range({datagrams}):
    s.sendto(b"rtp" + bytes([i]), ("127.0.0.1", 18991))
s.close()
SEND
sleep 0.2
'''
        script += '''finalize_sinks
printf 'GATE=%s\n' "$R29I_SINK_FINALIZATION_GATE"
printf 'FINAL=%s\n' "$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
printf 'FILE=%s\n' "$(cat "$RUN_ROOT/video.count")"
rm -rf "$RUN_ROOT"
'''
        completed = subprocess.run(
            ["bash", "-lc", script],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )
        values: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return values

    def test_zero_datagram_sink_materializes_final_counter_after_exit(self) -> None:
        values = self._run_sink_case(0)
        self.assertEqual(values["GATE"], "PASS")
        self.assertEqual(values["FINAL"], "0")
        self.assertEqual(values["FILE"], "0")

    def test_nonzero_datagram_sink_materializes_final_counter_after_exit(self) -> None:
        values = self._run_sink_case(3)
        self.assertEqual(values["GATE"], "PASS")
        self.assertEqual(values["FINAL"], "3")
        self.assertEqual(values["FILE"], "3")

    def test_runner_reports_ring_evidence_without_inferring_physical_action(self) -> None:
        for marker in (
            "RING_PROMPT_ISSUED_COUNT=",
            "PHYSICAL_RING_REPORTED_BY_USER=EXTERNAL_EVIDENCE_REQUIRED",
            "CALL_INIT_OBSERVED_COUNT=",
        ):
            self.assertIn(marker, self.runner)
        self.assertNotIn("PHYSICAL_RING_REPORTED_BY_USER=true", self.runner)

    def test_lineage_gate_is_exact_and_fail_closed(self) -> None:
        for path in (
            "ct120_run_p116_r29i_preopen_idle_live.sh",
            "entrance_p116_r29i_preopen_idle_transform.py",
            "entrance_p116_r29i_preopen_idle_model.py",
            "test_p116_r29i_preopen_idle_and_sink_ownership.py",
            "P116_R29I_PREOPEN_IDLE_AND_SINK_OWNERSHIP_HARDENING.md",
        ):
            self.assertIn(path, self.runner)
        self.assertIn("R29I_MAIN_LINEAGE_GATE=FAIL", self.runner)
        self.assertNotIn("grep -v -e '^safety-poc/research/media/v1/.*'", self.runner)

    def test_parse(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(MEDIA / "entrance_p116_r29i_preopen_idle_model.py")],
            cwd=REPO,
            check=True,
        )
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
