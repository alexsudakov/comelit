from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "safety-poc/research/media/v1/pseudotcp_local_syn_forensic.c"
RUNNER = ROOT / "safety-poc/research/media/v1/ct120_run_pseudotcp_local_syn_forensic.sh"


class P24PseudoTcpLocalSynForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_source_is_local_only(self):
        for forbidden in (
            "nice_agent_new",
            "nice_agent_send",
            "nice_agent_gather_candidates",
            "curl",
            "http://",
            "https://",
            "SIGUSR1",
            "V4_DOOR_RESULT",
        ):
            self.assertNotIn(forbidden, self.source)

        for required in (
            'printf("NETWORK_IO_PERFORMED=false\\n")',
            'printf("HOME_ASSISTANT_TOUCHED=false\\n")',
            'printf("DOOR_ACTION_SENT=false\\n")',
            'printf("SELF_ACTIVATION_SENT=false\\n")',
            'printf("MEDIA_SIGNALING_SENT=false\\n")',
        ):
            self.assertIn(required, self.source)

    def test_source_uses_real_libnice_pseudotcp_api(self):
        for required in (
            "#include <nice/pseudotcp.h>",
            "pseudo_tcp_socket_new(",
            "pseudo_tcp_socket_notify_mtu(tcp, EXPECTED_MTU)",
            "pseudo_tcp_socket_connect(tcp)",
            ".WritePacket = write_packet_cb",
            "PSEUDO_TCP_LISTEN",
            "PSEUDO_TCP_SYN_SENT",
        ):
            self.assertIn(required, self.source)

    def test_official_first_client_signature_is_pinned(self):
        for required in (
            "len == 31u",
            "conversation == EXPECTED_CONVERSATION",
            "sequence == 0u",
            "acknowledgment == 0u",
            "control == 0u",
            "flags == PSEUDOTCP_FLAG_CTL",
            "data_len == 7u",
            '"LOCAL_SYN_OFFICIAL_STRUCTURAL_MATCH=%s\\n"',
        ):
            self.assertIn(required, self.source)

    def test_raw_payload_is_not_emitted(self):
        self.assertIn('printf("LOCAL_SYN_RAW_PAYLOAD_EMITTED=false\\n")', self.source)
        self.assertNotIn("%02x%02x%02x%02x%02x%02x%02x", self.source)

    def test_runner_is_offline_and_ct120_scoped(self):
        self.assertIn("CT120_IP=192.168.1.85", self.runner)
        self.assertIn("pkg-config --exists nice glib-2.0 gobject-2.0", self.runner)
        self.assertIn("-Werror", self.runner)
        self.assertNotIn("curl ", self.runner)
        self.assertNotIn("wget ", self.runner)
        self.assertNotIn("nc ", self.runner)
        self.assertNotIn("HA_WEBHOOK_URL", self.runner)

    def test_runner_pins_official_structural_expectation(self):
        for required in (
            'echo "OFFICIAL_FIRST_CLIENT_WIRE_LEN=31"',
            'echo "OFFICIAL_FIRST_CLIENT_SEQUENCE=0"',
            'echo "OFFICIAL_FIRST_CLIENT_ACKNOWLEDGMENT=0"',
            'echo "OFFICIAL_FIRST_CLIENT_CONTROL=0x00"',
            'echo "OFFICIAL_FIRST_CLIENT_FLAGS=0x02"',
            'echo "OFFICIAL_FIRST_CLIENT_DATA_LEN=7"',
            'echo "NETWORK_IO_PERFORMED=false"',
        ):
            self.assertIn(required, self.runner)


if __name__ == "__main__":
    unittest.main()
