from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "collect_p12_holder_structure.sh"


class P12HolderStructureCollectorTests(unittest.TestCase):
    def test_collector_is_pinned_to_forensic_baseline(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertIn("d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9", text)
        self.assertIn("628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de", text)
        self.assertIn("HOLDER_SOURCE_PIN=PASS", text)
        self.assertIn("HOLDER_BINARY_PIN=PASS", text)

    def test_collector_declares_no_execution_or_network(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertIn("SOURCE_EXECUTED=false", text)
        self.assertIn("BINARY_EXECUTED=false", text)
        self.assertIn("ACTIVE_COMELIT_NETWORK_PROBES=false", text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertNotIn("/root/.config/comelit", text)
        self.assertNotIn("curl ", text)
        self.assertNotIn("wget ", text)
        self.assertIsNone(re.search(r'^\s*"\$BINARY"(?:\s|$)', text, re.MULTILINE))

    def test_collector_scans_sanitized_output_for_sensitive_shapes(self):
        text = COLLECTOR.read_text(encoding="utf-8")
        self.assertIn("P12_HOLDER_STRUCTURE_SECRET_SCAN=PASS", text)
        self.assertIn("P12_HOLDER_STRUCTURE_IPV4_SCAN=PASS", text)
        self.assertIn("P12_HOLDER_STRUCTURE_32HEX_SCAN=PASS", text)


if __name__ == "__main__":
    unittest.main()
