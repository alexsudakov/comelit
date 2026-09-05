from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ANALYZER = ROOT / "safety-poc/research/media/v1/pseudotcp_teardown_forensic.py"
RUNNER = ROOT / "safety-poc/research/media/v1/ct120_run_pseudotcp_teardown_forensic.sh"


class P25PseudoTcpTeardownForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = ANALYZER.read_text(encoding="utf-8")
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_runner_is_ct120_offline_only(self):
        self.assertIn("CT120_IP=192.168.1.85", self.runner)
        self.assertIn('echo "NETWORK_IO_PERFORMED=false"', self.runner)
        self.assertIn('echo "HOME_ASSISTANT_TOUCHED=false"', self.runner)
        self.assertIn('echo "DOOR_ACTION_SENT=false"', self.runner)
        self.assertIn('echo "SELF_ACTIVATION_SENT=false"', self.runner)
        self.assertIn('echo "MEDIA_SIGNALING_SENT=false"', self.runner)

        forbidden = (
            "curl ",
            "wget ",
            "nc ",
            "socat ",
            "ha core",
            "button.press",
            "SIGUSR1",
            "/api/webhook/",
        )
        lowered = self.runner.lower()
        for token in forbidden:
            self.assertNotIn(token.lower(), lowered)

    def test_both_official_pcaps_are_pinned(self):
        self.assertIn(
            "SELF_SHA=f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
            self.runner,
        )
        self.assertIn(
            "RTSP_SHA=62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3",
            self.runner,
        )
        self.assertIn("SELF_ACTIVATION_IDENTITY=PASS", self.runner)
        self.assertIn("P2P_RTSP_IDENTITY=PASS", self.runner)

    def test_analyzer_reports_first_ctl_deep_signature(self):
        for marker in (
            "FIRST_CLIENT_CTL_WINDOW=",
            "FIRST_CLIENT_CTL_DATA_SHA256=",
            "FIRST_CLIENT_CTL_WIRE_LEN=",
            "FIRST_CLIENT_CTL_FLAGS=",
            "OFFICIAL_FIRST_CTL_WINDOW_MATCH=",
            "OFFICIAL_FIRST_CTL_CONTROL_SHA_MATCH=",
        ):
            self.assertIn(marker, self.analyzer)

    def test_analyzer_reports_teardown_direction_and_kind(self):
        for marker in (
            "PSEUDOTCP_RST_COUNT=",
            "PSEUDOTCP_FIN_COUNT=",
            "FIRST_TERMINATION_KIND=",
            "FIRST_TERMINATION_DIRECTION=",
            "TERMINATION_AFTER_LAST_APP_SECONDS=",
            "OFFICIAL_FIRST_TERMINATION_SIGNATURE_MATCH=",
        ):
            self.assertIn(marker, self.analyzer)

    def test_analyzer_checks_current_stop_semantics(self):
        self.assertIn('_function_body(source, "stop_check_cb")', self.analyzer)
        self.assertIn('"pseudo_tcp_socket_close" in body', self.analyzer)
        self.assertIn('"pseudo_tcp_socket_shutdown" in body', self.analyzer)
        self.assertIn("CURRENT_STOP_EXPLICIT_PSEUDOTCP_CLOSE=", self.analyzer)
        self.assertIn("CURRENT_STOP_EXPLICIT_PSEUDOTCP_SHUTDOWN=", self.analyzer)

    def test_analyzer_never_emits_endpoints_or_raw_payload(self):
        self.assertIn('print("ENDPOINTS_EMITTED=false")', self.analyzer)
        self.assertIn('print("RAW_PAYLOAD_EMITTED=false")', self.analyzer)
        self.assertNotIn("segment.source.address", self.analyzer)
        self.assertNotIn("segment.target.address", self.analyzer)
        self.assertNotIn("first.data.hex", self.analyzer)


if __name__ == "__main__":
    unittest.main()
