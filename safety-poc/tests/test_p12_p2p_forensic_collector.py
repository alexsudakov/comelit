from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "collect_p12_p2p_forensic.sh"


class P12P2PForensicCollectorTests(unittest.TestCase):
    def test_collector_declares_no_execution_or_network(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertIn("SOURCE_EXECUTED=false", text)
        self.assertIn("BINARY_EXECUTED=false", text)
        self.assertIn("WRAPPER_EXECUTED=false", text)
        self.assertIn("ACTIVE_COMELIT_NETWORK_PROBES=false", text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)

    def test_collector_does_not_read_secret_store_or_execute_probe(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertNotIn("/root/.config/comelit", text)
        self.assertNotIn("curl ", text)
        self.assertNotIn("wget ", text)
        self.assertNotIn("source /root", text)
        self.assertNotIn("eval ", text)
        self.assertNotIn('"$WRAPPER" ', text)
        self.assertNotIn('"$BINARY" ', text)

    def test_public_output_is_marker_or_identity_only(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertIn("MATCHING_SOURCE_LINES_EMITTED=false", text)
        self.assertIn("MATCHING_BINARY_STRINGS_EMITTED=false", text)
        self.assertIn("WRAPPER_LINES_EMITTED=false", text)
        self.assertIn("PROCESS_ARGUMENTS_EMITTED=false", text)
        self.assertIn("BACKUP_CONTENT_EMITTED=false", text)


if __name__ == "__main__":
    unittest.main()
