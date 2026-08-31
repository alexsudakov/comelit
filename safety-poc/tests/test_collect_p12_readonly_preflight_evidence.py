from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect_p12_readonly_preflight_evidence.sh"


class P12ReadonlyPreflightEvidenceCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_collector_requires_complete_successful_preflight(self):
        for marker in (
            "P12_PREFLIGHT_SERVICE_PAYLOAD_START=true",
            "P12_PREFLIGHT_BUILD_IDENTITY=PASS",
            "P12_PREFLIGHT_ARTIFACT_SHAPE=PASS",
            "P12_PREFLIGHT_CONTROL_PLANE=PASS",
            "P12_PREFLIGHT_CREDENTIAL_METADATA=PASS",
            "P12_PREFLIGHT_NO_ACTIVE_CANDIDATE=PASS",
            "P12_READONLY_LIVE_PREFLIGHT=PASS",
            "P12_PREFLIGHT_EXIT_RC=0",
            "P12_PREFLIGHT_LAST_STEP=COMPLETE",
            "P12_PREFLIGHT_SERVICE_PAYLOAD_END=true",
        ):
            self.assertIn(marker, self.text)
        self.assertIn('[[ "$RC" == "0" ]]', self.text)

    def test_raw_or_sensitive_values_are_not_copied(self):
        self.assertIn("RAW_PREFLIGHT_LOG_COPIED=false", self.text)
        self.assertIn("CREDENTIAL_VALUES_COLLECTED=false", self.text)
        self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", self.text)
        self.assertNotIn('cp "$LOG"', self.text)
        self.assertNotIn('cat "$LOG" >', self.text)
        self.assertNotIn('cat "$SECRETS_FILE"', self.text)
        self.assertNotIn('source "$SECRETS_FILE"', self.text)

    def test_live_and_actuator_gates_remain_closed(self):
        for marker in (
            "P12_READONLY_LIVE_APPROVED=false",
            "P12_READONLY_LIVE_RUN_PERFORMED=false",
            "ACTIVE_COMELIT_NETWORK_PROBES=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "PHYSICAL_EFFECT_ASSERTED=false",
            "READONLY_TRANSPORT_READY=false",
            "LIVE_TEST_READY=false",
        ):
            self.assertIn(marker, self.text)

    def test_run_identity_and_collector_identity_are_separate(self):
        self.assertIn("PREFLIGHT_RUN_HEAD=$RUN_HEAD", self.text)
        self.assertIn("PREFLIGHT_RUN_TREE=$RUN_TREE", self.text)
        self.assertIn("COLLECTOR_SOURCE_HEAD=$COLLECTOR_HEAD", self.text)
        self.assertIn("COLLECTOR_SOURCE_TREE=$COLLECTOR_TREE", self.text)
        self.assertIn('rev-parse "$RUN_HEAD^{tree}"', self.text)
        self.assertIn('merge-base --is-ancestor "$RUN_HEAD" "$COLLECTOR_HEAD"', self.text)
        self.assertIn("P12_PREFLIGHT_RUN_TREE_BINDING=FAIL", self.text)
        self.assertIn("P12_PREFLIGHT_RUN_NOT_ANCESTOR_OF_COLLECTOR=true", self.text)

    def test_intervening_drift_is_collector_only(self):
        self.assertIn('git -C "$REPO_ROOT" diff --name-only "$RUN_HEAD..$COLLECTOR_HEAD"', self.text)
        self.assertIn("collect_p12_readonly_preflight_evidence", self.text)
        self.assertIn("test_collect_p12_readonly_preflight_evidence", self.text)
        self.assertIn("P12_PREFLIGHT_TO_COLLECTOR_DRIFT_SCOPE=FAIL", self.text)
        self.assertIn("P12_PREFLIGHT_TO_COLLECTOR_DRIFT_SCOPE=PASS", self.text)

    def test_evidence_is_hash_bound_and_scope_limited(self):
        self.assertIn("PREFLIGHT_LOG_SHA256", self.text)
        self.assertIn("PREFLIGHT_RC_SHA256", self.text)
        self.assertIn("PREFLIGHT_META_SHA256", self.text)
        self.assertIn("P12_PREFLIGHT_EVIDENCE_SCOPE_CHECK=FAIL", self.text)
        self.assertIn("P12_PREFLIGHT_PUBLIC_EVIDENCE_SECRET_SCAN=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_PUBLIC_EVIDENCE_SAFETY_SCAN=PASS", self.text)


if __name__ == "__main__":
    unittest.main()
