from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_p12_readonly_live_once.sh"


class P12ReadonlyLiveOnceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_explicit_approval_is_required(self):
        self.assertIn("APPROVAL_EXPECTED=I_APPROVE_P12_READONLY_LIVE_ONCE", self.text)
        self.assertIn("P12_READONLY_LIVE_APPROVAL=FAIL", self.text)

    def test_wrapper_is_invoked_exactly_once(self):
        invocation = '75s "$WRAPPER" >"$RAW" 2>&1'
        self.assertEqual(self.text.count(invocation), 1)
        self.assertIn("P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1", self.text)
        self.assertNotIn("for attempt", self.text)
        self.assertNotIn("while true", self.text.lower())

    def test_raw_log_is_not_printed_and_safe_allowlist_is_used(self):
        self.assertIn('chmod 600 "$RAW"', self.text)
        self.assertIn('cat "$SAFE"', self.text)
        self.assertNotIn('cat "$RAW"', self.text)
        self.assertIn("UAUT_RESPONSE_CODE=200", self.text)
        self.assertIn("UCFG_RESPONSE_SHA256=", self.text)

    def test_readonly_proof_requires_clean_close_and_safety_markers(self):
        for marker in (
            "P2_VIP_UAUT_AUTH=PASS",
            "VIP_UAUT_CLOSE_RESPONSE_WORD=0",
            "UCFG_RECEIVED=true",
            "VIP_UCFG_CLOSE_RESPONSE_WORD=0",
            "P12_READONLY_TRANSACTION=PASS",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "AUTO_RETRY_OBSERVED=false",
            "PHYSICAL_DOOR_ACTION=false",
        ):
            self.assertIn(marker, self.text)
        self.assertIn("READONLY_TRANSPORT_READY=true", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)


if __name__ == "__main__":
    unittest.main()
