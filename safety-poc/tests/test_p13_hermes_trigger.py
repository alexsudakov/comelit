from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_hermes_one_shot.sh"
TARGET = "832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce"


class P13HermesTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_operator_action_is_required(self):
        self.assertIn("ACTION_PHRASE=OPEN_72K4_3_ONCE", self.text)
        self.assertIn("P13_HERMES_ACTION=REJECTED", self.text)
        self.assertIn('[[ "${1:-}" == "$ACTION_PHRASE" && $# -eq 1 ]]', self.text)

    def test_target_is_fixed_to_pinned_fingerprint(self):
        self.assertIn(f"TARGET_FINGERPRINT={TARGET}", self.text)
        self.assertIn('--target-fingerprint "$TARGET_FINGERPRINT"', self.text)

    def test_fresh_operation_id_and_concurrency_lock(self):
        self.assertIn("uuid.uuid4()", self.text)
        self.assertIn("p13-hermes-", self.text)
        self.assertIn("flock -n 9", self.text)
        self.assertIn("P13_HERMES_CONCURRENT_INVOCATION=true", self.text)

    def test_exactly_one_runner_handoff_and_no_retry_loop(self):
        self.assertEqual(self.text.count('bash "$RUNNER"'), 1)
        self.assertIn('exec env P13_APPROVAL="$INTERNAL_APPROVAL"', self.text)
        self.assertNotIn("for attempt", self.text)
        self.assertNotIn("while true", self.text.lower())
        self.assertIn("P13_HERMES_ONE_SHOT_MAX_INVOCATIONS=1", self.text)
        self.assertIn("P13_HERMES_AUTO_RETRY_ALLOWED=false", self.text)

    def test_physical_warning_is_emitted_before_handoff(self):
        warning = "P13_HERMES_WARNING=PHYSICAL_DOOR_MAY_OPEN"
        self.assertIn(warning, self.text)
        self.assertLess(self.text.index(warning), self.text.index('exec env P13_APPROVAL='))


if __name__ == "__main__":
    unittest.main()
