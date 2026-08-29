from pathlib import Path
import re
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_p12_readonly_candidate.sh"


class PrepareP12ReadonlyCandidateTests(unittest.TestCase):
    def test_prepare_script_pins_baseline_and_does_not_run_candidate(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("EXPECTED_SOURCE_SHA=d8c3bd50", text)
        self.assertIn("EXPECTED_BINARY_SHA=628b9c020b", text)
        self.assertIn("EXPECTED_WRAPPER_SHA=a564535dff", text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("SECRETS_READ=false", text)
        self.assertIsNone(re.search(r'^\s*"\$CANDIDATE_BINARY"(?:\s|$)', text, re.MULTILINE))
        self.assertIsNone(re.search(r'^\s*"\$CANDIDATE_WRAPPER"(?:\s|$)', text, re.MULTILINE))

    def test_candidate_is_isolated_from_baseline_paths(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("BUILD_DIR=/root/comelit-p12-readonly-candidate", text)
        self.assertIn("BASELINE_FILES_MUTATED=false", text)
        self.assertIn("P12_BASELINE_SOURCE_MUTATED=true", text)
        self.assertIn("P12_BASELINE_BINARY_MUTATED=true", text)
        self.assertIn("P12_BASELINE_WRAPPER_MUTATED=true", text)

    def test_actuator_surface_is_scanned_from_source_binary_and_wrapper(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("CTPP|OPEN_DOOR|open_door|create_door_message"), 3)
        self.assertIn("P12_CANDIDATE_SOURCE_ACTUATOR_SCAN=PASS", text)
        self.assertIn("P12_CANDIDATE_BINARY_ACTUATOR_SCAN=PASS", text)
        self.assertIn("P12_CANDIDATE_WRAPPER_ACTUATOR_SCAN=PASS", text)

    def test_wrapper_binding_matches_real_base_variable_invocation(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("needle = '\"$BASE/bin/comelit_ice_offer_holder\"'", text)
        self.assertIn("P12_CANDIDATE_WRAPPER_BINDING=PASS", text)
        self.assertIn("P12_CANDIDATE_WRAPPER_BASELINE_HOLDER_REMAINS=true", text)


if __name__ == "__main__":
    unittest.main()
