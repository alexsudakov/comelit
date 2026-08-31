from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_capture_runtime_identity.sh"


class P13RuntimeIdentityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_capability_matches_no_argument_holder_contract(self):
        self.assertIn("P13_HOLDER_CAPABILITY_METHOD=STATIC_P13_MARKERS_NOARG", self.text)
        self.assertIn("P13_HOLDER_ENTRYPOINT=NO_ARGUMENTS", self.text)
        self.assertIn('"entrypoint": "NO_ARGUMENTS"', self.text)
        self.assertNotIn("P13_HOLDER_REQUIRED_FLAG_MISSING", self.text)

    def test_capability_requires_real_session_markers_without_execution(self):
        for marker in (
            "P13_CTPP_OPEN_OUTCOME",
            "P13_DOOR_WRITE_COUNT",
            "P13_TEARDOWN=PASS",
            "P13_ONE_SHOT_MAX_INVOCATIONS=1",
            "P13_AUTO_RETRY_ALLOWED=false",
            "PHYSICAL_DOOR_ACTION=false",
        ):
            self.assertIn(marker, self.text)
        self.assertIn("P13_HOLDER_EXECUTED=false", self.text)
        self.assertIn("grep -aFq", self.text)

    def test_payload_and_runtime_identity_checks_remain_required(self):
        self.assertIn('[[ "$PAYLOAD_WRITE_COUNT" == "6" ]]', self.text)
        self.assertIn('[[ "$PAYLOAD_UCFG_SHA" == "$EXPECTED_UCFG_SHA256" ]]', self.text)
        self.assertIn("P13_PAYLOAD_UCFG_BINDING=PASS", self.text)
        self.assertIn("RUNTIME_IDENTITY_POC", self.text)


if __name__ == "__main__":
    unittest.main()
