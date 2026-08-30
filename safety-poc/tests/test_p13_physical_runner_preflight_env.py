from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "p13_one_shot_physical_runner.sh"


class P13PhysicalRunnerPreflightEnvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_live_approval_is_not_inherited_by_non_actuating_preflight(self):
        self.assertIn("env -u P13_APPROVAL -u P13_OPERATION_ID", self.text)
        self.assertIn('bash "$SCRIPT_DIR/p13_actuation_preflight.sh"', self.text)

    def test_approval_gate_still_precedes_preflight(self):
        approval = self.text.index("P13_ONE_SHOT_APPROVAL=GRANTED")
        sanitized_preflight = self.text.index("env -u P13_APPROVAL -u P13_OPERATION_ID")
        execute = self.text.index("STEP=EXECUTE")
        self.assertLess(approval, sanitized_preflight)
        self.assertLess(sanitized_preflight, execute)


if __name__ == "__main__":
    unittest.main()
