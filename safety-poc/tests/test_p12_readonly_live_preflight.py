from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_readonly_live_preflight.sh"


class P12ReadonlyLivePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_candidate_identity_is_exactly_pinned(self):
        self.assertIn("EXPECTED_BUILD_HEAD=150d594072aa1d999c99679d5451772e65c6554f", self.text)
        self.assertIn("EXPECTED_BUILD_TREE=16531cebda2d407b157056dfd5a9836c211a89ec", self.text)
        self.assertIn("EXPECTED_SOURCE_SHA=b8215df5008133c38fa57a31aae63f7cbf734710fa322aa641de2da08b8015ab", self.text)
        self.assertIn("EXPECTED_BINARY_SHA=bae10046aa4a449e0e1bb56315308592aaf06b82049c80291871d6485b55668c", self.text)
        self.assertIn("EXPECTED_WRAPPER_SHA=7eb9c4e8999dc6c6f15ac03344abd155a042482158352fadbca58a3f4fd91ce1", self.text)

    def test_preflight_is_non_executing_and_non_networking(self):
        self.assertIn("P12_READONLY_LIVE_RUN_PERFORMED=false", self.text)
        self.assertIn("CANDIDATE_EXECUTED=false", self.text)
        self.assertIn("WRAPPER_EXECUTED=false", self.text)
        self.assertIn("SECRETS_CONTENT_READ=false", self.text)
        self.assertIn("ACTIVE_COMELIT_NETWORK_PROBES=false", self.text)
        self.assertNotIn('timeout "$WRAPPER"', self.text)
        self.assertNotIn('"$WRAPPER" >', self.text)
        self.assertNotIn('"$BINARY" >', self.text)

    def test_readonly_and_actuator_guards_are_present(self):
        self.assertIn("P12_READONLY_TRANSACTION=PASS", self.text)
        self.assertIn("P12_VIP_TOKEN_VALUE_EMITTED=false", self.text)
        self.assertIn("CREDENTIAL_MATERIAL_EMITTED=false", self.text)
        self.assertIn("AUTO_RETRY_OBSERVED=false", self.text)
        self.assertIn("CTPP|OPEN_DOOR|open_door|create_door_message", self.text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_EFFECT_ASSERTED=false", self.text)

    def test_credential_check_is_metadata_only(self):
        self.assertIn("SECRETS_FILE=/root/.config/comelit/secrets.env", self.text)
        self.assertIn("stat -c '%a' \"$SECRETS_FILE\"", self.text)
        self.assertIn("stat -c '%u' \"$SECRETS_FILE\"", self.text)
        self.assertNotIn('cat "$SECRETS_FILE"', self.text)
        self.assertNotIn('source "$SECRETS_FILE"', self.text)

    def test_live_approval_remains_separate(self):
        self.assertIn("P12_READONLY_LIVE_APPROVAL_REQUIRED=true", self.text)
        self.assertIn("P12_READONLY_LIVE_APPROVED=false", self.text)
        self.assertIn("READONLY_TRANSPORT_READY=false", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)
        self.assertIn("P12_READONLY_LIVE_PREFLIGHT=PASS", self.text)


if __name__ == "__main__":
    unittest.main()
