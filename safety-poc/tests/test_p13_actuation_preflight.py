from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_actuation_preflight.sh"


class P13ActuationPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_preflight_is_non_actuating(self):
        self.assertIn("P13_ACTUATOR_COMMAND_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.text)
        self.assertIn("P13_NON_ACTUATING_PREFLIGHT=PASS", self.text)
        self.assertIn("EXPLICIT_LIVE_TEST_APPROVAL=false", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)

    def test_actuation_transport_and_audit_markers_present(self):
        self.assertIn("ACTUATION_TRANSPORT_IMPLEMENTED=true", self.text)
        self.assertIn("AUDIT_SINK_VERIFIED=PASS", self.text)

    def test_one_shot_and_no_retry_contract(self):
        self.assertIn("P13_ONE_SHOT_MAX_INVOCATIONS=1", self.text)
        self.assertIn("P13_AUTO_RETRY_ALLOWED=false", self.text)
        self.assertIn("P13_RETRY_SURFACE_DETECTED=false", self.text)
        self.assertIn("P13_TARGET_BINDING_REQUIRED=true", self.text)

    def test_exact_identity_and_clean_worktree_required(self):
        self.assertIn('EXPECTED_BRANCH=feat/p13-one-shot-actuation', self.text)
        self.assertIn("P13_PREFLIGHT_HEAD=$HEAD", self.text)
        self.assertIn("P13_PREFLIGHT_TREE=$TREE", self.text)
        self.assertIn("P13_PREFLIGHT_WORKTREE_CLEAN=false", self.text)

    def test_payload_requires_mode_0600(self):
        self.assertIn('[[ "$PAYLOAD_MODE" == "600" ]]', self.text)
        self.assertIn("P13_PAYLOAD_MODE=FAIL", self.text)

    def test_no_network_or_physical_commands(self):
        for forbidden in ("curl ", "wget ", "nc ", "door ", "open_door", "systemctl start"):
            self.assertNotIn(forbidden, self.text)

    def test_conflicting_process_check(self):
        self.assertIn("P13_CONFLICTING_PROCESS=false", self.text)
        self.assertIn('pgrep -x "comelit_ice_offer_holder"', self.text)


if __name__ == "__main__":
    unittest.main()
