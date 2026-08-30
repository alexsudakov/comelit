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

    def test_actuation_transport_is_runtime_derived_not_hardcoded(self):
        # Blocker 4: the marker must be emitted only after manifest-derived
        # identity and dry-init proofs, and must be false when artifacts absent.
        self.assertIn("P13_REAL_WRAPPER_PRESENT=false", self.text)
        self.assertIn('echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"', self.text)
        self.assertIn("ACTUATION_TRANSPORT_IMPLEMENTED=true", self.text)
        self.assertIn("P13_WRAPPER_MANIFEST_NOT_BUILT=true", self.text)
        dry_init = self.text.index("STEP=REAL_ADAPTER_DRY_INIT")
        true_marker = self.text.index('echo "ACTUATION_TRANSPORT_IMPLEMENTED=true"')
        self.assertGreater(true_marker, dry_init)

    def test_wrapper_identity_pinned(self):
        # Expected identity comes from the Git-reviewed build manifest.
        self.assertIn("p13_wrapper_manifest.json", self.text)
        self.assertIn("P13_WRAPPER_MANIFEST_ABSENT=true", self.text)
        self.assertIn("P13_WRAPPER_MANIFEST_NOT_BUILT=true", self.text)
        self.assertIn('json.load(open(sys.argv[1]))["wrapper_sha256"]', self.text)
        self.assertIn("P13_REAL_WRAPPER_SHA256=FAIL", self.text)
        self.assertIn("P13_REAL_WRAPPER_MODE=FAIL", self.text)
        self.assertIn('stat -c \'%a\' "$WRAPPER"', self.text)
        self.assertIn("P13_REAL_WRAPPER_SHA256=$WRAPPER_SHA", self.text)

    def test_ownership_checks_fail_closed(self):
        self.assertIn("P13_REAL_WRAPPER_OWNER=FAIL", self.text)
        self.assertIn("P13_PAYLOAD_OWNER=FAIL", self.text)
        self.assertIn('stat -c \'%u\' "$WRAPPER"', self.text)
        self.assertIn('stat -c \'%u\' "$PAYLOAD_FILE"', self.text)
        self.assertIn("P13_REAL_WRAPPER_OWNER=root", self.text)

    def test_build_procedure_and_template_exist(self):
        build = Path(__file__).resolve().parents[1] / "scripts" / "build_p13_wrapper.sh"
        template = Path(__file__).resolve().parents[1] / "deploy" / "p13_wrapper_template.sh"
        manifest = Path(__file__).resolve().parents[1] / "deploy" / "p13_wrapper_manifest.json"
        self.assertTrue(build.is_file())
        self.assertTrue(template.is_file())
        self.assertTrue(manifest.is_file())
        body = build.read_text(encoding="utf-8")
        self.assertIn("P13_BUILD_COMPLETE=true", body)
        self.assertIn("p13_wrapper_manifest.json", body)
        self.assertIn("chown root:root", body)
        tmpl = template.read_text(encoding="utf-8")
        self.assertIn("P13_CTPP_OPEN_OUTCOME", tmpl)
        self.assertIn("P13_TEARDOWN=PASS", tmpl)
        m = manifest.read_text(encoding="utf-8")
        self.assertIn('"status": "NOT_BUILT"', m)

    def test_audit_durability_proof_required(self):
        self.assertIn("p13_audit_durability_proof.py", self.text)
        self.assertIn("--audit \"$AUDIT_FILE\"", self.text)
        self.assertIn("P13_AUDIT_DURABILITY_PROOF=FAIL", self.text)
        self.assertIn("AUDIT_SINK_VERIFIED=FAIL", self.text)
        self.assertIn("AUDIT_SINK_VERIFIED=PASS", self.text)

    def test_audit_proof_script_uses_real_sink_api(self):
        proof = Path(__file__).resolve().parents[1] / "scripts" / "p13_audit_durability_proof.py"
        body = proof.read_text(encoding="utf-8")
        self.assertIn("from comelit_safety_poc.audit import AuditEntry, AuditSink", body)
        self.assertIn('event_type="preflight"', body)
        self.assertIn("P13_AUDIT_APPEND_FSYNC_REOPEN=PASS", body)
        self.assertIn("sink.record_raw(", body)
        self.assertIn("verify_durable()", body)

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
        for forbidden in ("curl ", "wget ", "netcat", "door ", "open_door", "systemctl start"):
            self.assertNotIn(forbidden, self.text)

    def test_conflicting_process_check(self):
        self.assertIn("P13_CONFLICTING_PROCESS=false", self.text)
        self.assertIn('pgrep -x "comelit_ice_offer_holder"', self.text)
        self.assertIn('pgrep -x "comelit-p13-door-wrapper"', self.text)

    def test_readonly_readiness_and_approval_markers(self):
        self.assertIn("READONLY_TRANSPORT_READY=true", self.text)
        self.assertIn("P13_ONE_SHOT_MAX_INVOCATIONS=1", self.text)
        self.assertIn("EXPLICIT_LIVE_TEST_APPROVAL=false", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)


class Ct120ManualPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path(__file__).resolve().parents[1] / "scripts" / "ct120_p13_preflight_manual.sh"

    def test_manual_script_is_non_actuating(self):
        body = self.text.read_text(encoding="utf-8")
        self.assertIn("P13_NON_ACTUATING_PREFLIGHT=PASS", body)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", body)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", body)
        self.assertIn("EXPLICIT_LIVE_TEST_APPROVAL=false", body)
        self.assertIn("LIVE_TEST_READY=false", body)
        for forbidden in ("curl ", "wget ", "nc ", "open_door"):
            self.assertNotIn(forbidden, body)

    def test_manual_script_collects_only_public_safe_evidence(self):
        body = self.text.read_text(encoding="utf-8")
        self.assertIn('EVIDENCE_BRANCH="evidence/p13-preflight-$STAMP"', body)
        self.assertIn('EVIDENCE_REL="evidence/p13-preflight/$STAMP"', body)
        self.assertIn("P13_PREFLIGHT_SOURCE_HEAD=$SOURCE_HEAD", body)
        self.assertIn("P13_PREFLIGHT_SOURCE_TREE=$SOURCE_TREE", body)
        self.assertIn("P13_PREFLIGHT_PAYLOAD_SHA256", body)
        self.assertIn("CREDENTIAL_VALUES_COLLECTED=false", body)
        self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", body)
        self.assertIn("RAW_PAYLOAD_BODIES_COLLECTED=false", body)
        self.assertNotIn("apt-address", body)
        self.assertNotIn("password", body)
        self.assertNotIn("token_value", body)

    def test_manual_script_requires_root(self):
        body = self.text.read_text(encoding="utf-8")
        self.assertIn("CT120_P13_MANUAL_REQUIRES_ROOT=true", body)
        self.assertIn('[[ "${EUID}" -eq 0 ]]', body)

    def test_manual_script_syncs_exact_remote_head_before_preflight(self):
        body = self.text.read_text(encoding="utf-8")
        self.assertIn('git fetch origin --prune', body)
        self.assertIn('git checkout -q -B "$EXPECTED_BRANCH" "origin/$EXPECTED_BRANCH"', body)
        self.assertIn('REMOTE_HEAD="$(git rev-parse "origin/$EXPECTED_BRANCH")"', body)
        self.assertIn('[[ "$SOURCE_HEAD" == "$REMOTE_HEAD" ]]', body)
        self.assertIn("CT120_P13_MANUAL_REMOTE_IDENTITY=PASS", body)

    def test_manual_script_creates_dedicated_evidence_branch_before_push(self):
        body = self.text.read_text(encoding="utf-8")
        create_pos = body.index('git checkout -q -b "$EVIDENCE_BRANCH" "$SOURCE_HEAD"')
        commit_pos = body.index('git -c user.name="hermes"')
        push_pos = body.index('git push -u origin "$EVIDENCE_BRANCH"')
        self.assertLess(create_pos, commit_pos)
        self.assertLess(commit_pos, push_pos)
        self.assertIn("P13_PREFLIGHT_EVIDENCE_PUSH=PASS", body)
        self.assertIn("P13_PREFLIGHT_EVIDENCE_PUSH=REQUIRED", body)


if __name__ == "__main__":
    unittest.main()
