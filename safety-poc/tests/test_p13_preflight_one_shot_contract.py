from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_actuation_preflight.sh"


class P13PreflightOneShotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_retry_gate_checks_behavior_not_retry_words(self):
        self.assertIn("P13_PYTHON_ONE_SHOT_SOURCE=PASS", self.text)
        self.assertIn("P13_ONE_SHOT_SOURCE_CONTRACT=PASS", self.text)
        self.assertIn('attr_calls(execute, "send_once") == 1', self.text)
        self.assertIn('attr_calls(open_ctpp, "_run_wrapper_once") == 1', self.text)
        self.assertIn("P13_WRAPPER_SINGLE_EXEC=PASS", self.text)
        self.assertNotIn('grep -rn "retry\\|RETRY"', self.text)

    def test_one_shot_gate_rejects_loops_and_retry_named_methods(self):
        self.assertIn("ast.For, ast.AsyncFor, ast.While", self.text)
        self.assertIn('"retry" in item.name.lower()', self.text)
        self.assertIn("P13_RETRY_SURFACE_DETECTED=true", self.text)
        self.assertIn("P13_RETRY_SURFACE_DETECTED=false", self.text)

    def test_conflict_check_uses_full_command_line(self):
        self.assertIn("pgrep -f --", self.text)
        self.assertNotIn('pgrep -x "comelit_ice_offer_holder"', self.text)
        self.assertNotIn('pgrep -x "comelit-p13-door-wrapper"', self.text)


if __name__ == "__main__":
    unittest.main()
