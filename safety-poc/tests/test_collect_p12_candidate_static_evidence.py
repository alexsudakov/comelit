from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect_p12_candidate_static_evidence.sh"


class P12CandidateStaticEvidenceCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_candidate_identity_is_pinned(self):
        self.assertIn("EXPECTED_BUILD_HEAD=150d594072aa1d999c99679d5451772e65c6554f", self.text)
        self.assertIn("EXPECTED_BUILD_TREE=16531cebda2d407b157056dfd5a9836c211a89ec", self.text)
        self.assertIn("EXPECTED_BIN_SHA=bae10046aa4a449e0e1bb56315308592aaf06b82049c80291871d6485b55668c", self.text)
        self.assertIn("EXPECTED_WRAP_SHA=7eb9c4e8999dc6c6f15ac03344abd155a042482158352fadbca58a3f4fd91ce1", self.text)

    def test_collector_remains_static_only(self):
        self.assertIn("CANDIDATE_EXECUTED=false", self.text)
        self.assertIn("WRAPPER_EXECUTED=false", self.text)
        self.assertIn("ACTIVE_COMELIT_NETWORK_PROBES=false", self.text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.text)
        self.assertNotIn('"$BIN"\n', self.text)
        self.assertNotIn('"$WRAP"\n', self.text)

    def test_static_validation_tools_and_scans_are_present(self):
        self.assertIn('readelf -h "$BIN" >/dev/null', self.text)
        self.assertIn('bash -n "$WRAP"', self.text)
        self.assertIn('strings -a "$BIN"', self.text)
        self.assertIn("P12_ACTUATOR_SURFACE_SCAN=PASS", self.text)
        self.assertIn("P12_WRAPPER_EXACT_BINDING=PASS", self.text)
        self.assertIn("P12_BASELINE_STILL_PINNED=PASS", self.text)

    def test_evidence_is_public_safe_and_readiness_stays_closed(self):
        self.assertIn("PUBLIC_SAFE=true", self.text)
        self.assertIn("READONLY_TRANSPORT_READY=false", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)
        self.assertIn("P12_CANDIDATE_STATIC_EVIDENCE=PASS", self.text)


if __name__ == "__main__":
    unittest.main()
