from __future__ import annotations

import json
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
BASE_RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"
LAUNCHER = MEDIA / "ct120_run_p116_r29i_registered_ctpp_mediareq26_live.sh"
SINK = MEDIA / "entrance_p116_r29i_udp_sink.py"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29i_live_runner_transform as runner_transform
import entrance_p116_r29i_preopen_idle_transform as r29i
from entrance_p116_r29i_preopen_idle_model import (
    R29IPreopenIdleModel,
    reproduce_long_idle_call_sequence,
)


class P116R29IPreopenIdleAndSinkOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29i.transform(SOURCE.read_text(encoding="utf-8"))
        cls.runner = runner_transform.transform(BASE_RUNNER.read_text(encoding="utf-8"))

    def test_waiting_for_ring_survives_inherited_timeout(self) -> None:
        model = R29IPreopenIdleModel()
        model.ready()
        model.advance(30_000)
        model.inherited_signaling_timeout()
        self.assertTrue(model.process_valid)
        self.assertTrue(model.waiting_for_ring)
        self.assertEqual(model.inherited_idle_timeouts_suppressed, 1)
        self.assertIsNone(model.terminal_reason)

    def test_waiting_for_ring_90s_model(self) -> None:
        model = R29IPreopenIdleModel()
        model.ready()
        for _ in range(3):
            model.advance(30_000)
            model.inherited_signaling_timeout()
        self.assertEqual(model.now_ms, 90_000)
        self.assertTrue(model.process_valid)
        self.assertTrue(model.waiting_for_ring)
        self.assertEqual(model.inherited_idle_timeouts_suppressed, 3)
        self.assertEqual(model.open_sent_count, 0)

    def test_call_init_after_long_idle_reaches_open_capable_state(self) -> None:
        evidence = reproduce_long_idle_call_sequence()
        self.assertTrue(evidence["after_30s"]["alive"])
        self.assertTrue(evidence["after_30s"]["waiting_for_ring"])
        self.assertEqual(evidence["after_call"]["now_ms"], 60_000)
        self.assertTrue(evidence["after_call"]["call_init"])
        self.assertEqual(evidence["after_call"]["open_sent_count"], 1)

    def test_call_transaction_timeout_before_open_remains_fail_closed(self) -> None:
        model = R29IPreopenIdleModel()
        model.ready()
        model.entrance_call_init()
        model.inherited_signaling_timeout()
        self.assertFalse(model.process_valid)
        self.assertEqual(
            model.terminal_reason,
            "ENTRANCE_SIGNALING_TIMEOUT_DURING_CALL_TRANSACTION",
        )
        self.assertEqual(model.open_sent_count, 0)
        self.assertEqual(model.inherited_idle_timeouts_suppressed, 0)

    def test_real_transport_and_registration_failures_still_fail_closed(self) -> None:
        for method, reason in (
            ("transport_failure", "TRANSPORT_FAILURE"),
            ("registration_failure", "REGISTRATION_FAILURE"),
        ):
            model = R29IPreopenIdleModel()
            model.ready()
            getattr(model, method)()
            self.assertFalse(model.process_valid)
            self.assertEqual(model.terminal_reason, reason)

    def test_generated_candidate_suppresses_only_waiting_for_ring_timeout(self) -> None:
        timeout_start = self.generated.index("entrance_signal_timeout_cb")
        timeout_end = self.generated.index("static void\np12_tx_completed", timeout_start)
        timeout_cb = self.generated[timeout_start:timeout_end]
        for marker in (
            "r29_listener_registered_ready &&",
            "!r29_call_transaction_created &&",
            "!r29c_registered_ctpp_mediareq26_open_sent",
            "R29I_WAITING_FOR_RING=true",
            "R29I_PREOPEN_IDLE_SIGNALING_TIMEOUT_SUPPRESSED=true",
            "r29h_defer_inherited_main_loop_quit",
            "failed = TRUE;",
        ):
            self.assertIn(marker, timeout_cb)
        self.assertLess(
            timeout_cb.index("R29I_PREOPEN_IDLE_SIGNALING_TIMEOUT_SUPPRESSED=true"),
            timeout_cb.index("failed = TRUE;"),
        )
        self.assertNotIn("p78_queue_rtpc_client_001a();", self.generated)
        self.assertIn("ONE_SHOT_OPEN_GATE=%s", self.generated)
        self.assertIn("ONE_SHOT_STOP_GATE=%s", self.generated)

    def test_runner_uses_direct_child_sinks_and_join_gate(self) -> None:
        self.assertNotIn('VIDEO_SINK_PID="$(start_udp_sink', self.runner)
        self.assertNotIn('AUDIO_SINK_PID="$(start_udp_sink', self.runner)
        self.assertIn("VIDEO VIDEO_SINK_PID", self.runner)
        self.assertIn("AUDIO AUDIO_SINK_PID", self.runner)
        self.assertIn('wait "$pid"', self.runner)
        self.assertIn("SINK_FINALIZATION_GATE=PASS", self.runner)
        self.assertIn("SINK_FINALIZATION_GATE=FAIL", self.runner)
        self.assertIn("RESULT=INCONCLUSIVE_TOOLING_FAILURE", self.runner)

    def _run_lineage_filter(self, paths: list[str]) -> list[str]:
        start = self.runner.index("r29c_main_lineage_unexpected_paths() {")
        end = self.runner.index("\n}\n\narm_autorestore_watchdog()", start) + 2
        function = self.runner[start:end]
        script = "\n".join(
            (
                "set -euo pipefail",
                "RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh",
                "TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py",
                function,
                "r29c_main_lineage_unexpected_paths",
            )
        )
        proc = subprocess.run(
            ["bash", "-c", script],
            input="\n".join(paths) + "\n",
            text=True,
            capture_output=True,
            cwd=REPO,
            check=True,
        )
        return [line for line in proc.stdout.splitlines() if line]

    def test_lineage_filter_allows_exact_r29i_delta_and_rejects_unknown(self) -> None:
        known = [
            "safety-poc/research/media/v1/P116_R29I_PREOPEN_IDLE_AND_SINK_OWNERSHIP_HARDENING.md",
            "safety-poc/research/media/v1/ct120_run_p116_r29i_registered_ctpp_mediareq26_live.sh",
            "safety-poc/research/media/v1/entrance_p116_r29i_live_runner_transform.py",
            "safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_model.py",
            "safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py",
            "safety-poc/research/media/v1/entrance_p116_r29i_udp_sink.py",
            "safety-poc/tests/test_p116_r29i_preopen_idle_and_sink_ownership.py",
        ]
        self.assertEqual(self._run_lineage_filter(known), [])
        unknown = "custom_components/comelit/runtime.py"
        self.assertEqual(self._run_lineage_filter(known + [unknown]), [unknown])

    def test_ring_prompt_and_call_init_evidence_are_separate(self) -> None:
        for marker in (
            "RING_PROMPT_ISSUED_COUNT=0",
            "CALL_INIT_OBSERVED_COUNT=0",
            "PHYSICAL_RING_REPORTED_BY_USER=UNKNOWN",
            "RING_PROMPT_ISSUED_COUNT=1",
            "CALL_INIT_OBSERVED_COUNT=1",
            "COMELIT R29I RING NOW",
        ):
            self.assertIn(marker, self.runner)
        prompt_site = self.runner.index("RING_PROMPT_ISSUED_COUNT=1")
        call_site = self.runner.index("CALL_INIT_OBSERVED_COUNT=1")
        self.assertLess(prompt_site, call_site)

    @staticmethod
    def _free_udp_port() -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
        finally:
            sock.close()

    def _run_sink_case(self, datagrams: int) -> tuple[int, dict[str, object]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            count_file = root / "count"
            first_file = root / "first"
            status_file = root / "status.json"
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
                    "--status-file",
                    str(status_file),
                    "--deadline-seconds",
                    "10",
                ],
                cwd=REPO,
            )
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if status_file.exists():
                        status = json.loads(status_file.read_text(encoding="utf-8"))
                        if status.get("started") is True:
                            break
                    time.sleep(0.05)
                else:
                    self.fail("sink did not report STARTED")

                sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    for index in range(datagrams):
                        sender.sendto(f"pkt-{index}".encode(), ("127.0.0.1", port))
                finally:
                    sender.close()
                if datagrams:
                    time.sleep(0.2)
                proc.terminate()
                self.assertEqual(proc.wait(timeout=5), 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)

            self.assertTrue(count_file.exists(), "final count must materialize after join")
            final_count = int(count_file.read_text(encoding="utf-8").strip())
            final_status = json.loads(status_file.read_text(encoding="utf-8"))
            return final_count, final_status

    def test_zero_datagram_sink_finalization_after_real_join(self) -> None:
        count, status = self._run_sink_case(0)
        self.assertEqual(count, 0)
        self.assertTrue(status["started"])
        self.assertTrue(status["finalized"])
        self.assertEqual(status["count"], 0)

    def test_nonzero_datagram_sink_finalization_after_real_join(self) -> None:
        count, status = self._run_sink_case(3)
        self.assertEqual(count, 3)
        self.assertTrue(status["finalized"])
        self.assertEqual(status["count"], 3)

    def test_generated_runner_and_new_python_files_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner_path = Path(tmp) / "r29i-runner.sh"
            runner_path.write_text(self.runner, encoding="utf-8")
            subprocess.run(["bash", "-n", str(runner_path)], cwd=REPO, check=True)
        subprocess.run(["bash", "-n", str(LAUNCHER)], cwd=REPO, check=True)
        for path in (
            MEDIA / "entrance_p116_r29i_preopen_idle_model.py",
            MEDIA / "entrance_p116_r29i_preopen_idle_transform.py",
            MEDIA / "entrance_p116_r29i_live_runner_transform.py",
            SINK,
        ):
            subprocess.run([sys.executable, "-m", "py_compile", str(path)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
