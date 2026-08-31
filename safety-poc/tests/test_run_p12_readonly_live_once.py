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

    def test_runner_uses_deterministic_one_shot_supervisor_once(self):
        self.assertEqual(self.text.count('python3 "$SCRIPT_DIR/p12_one_shot_exec.py"'), 1)
        self.assertIn("P12_ONE_SHOT_PROCESS_INVOCATIONS=1", self.text)
        self.assertIn("P12_ONE_SHOT_AUTO_RETRY=false", self.text)
        self.assertIn("P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true", self.text)
        self.assertIn("P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1", self.text)
        self.assertNotIn("timeout --signal", self.text)
        self.assertNotIn("for attempt", self.text)
        self.assertNotIn("while true", self.text.lower())

    def test_raw_log_is_not_printed_and_safe_allowlist_is_used(self):
        self.assertIn('chmod 600 "$RAW" "$EXEC_STATUS"', self.text)
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
        self.assertIn("REAL_TRANSPORT_READONLY_SESSION_PROOF=PASS", self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)

    def test_auth_session_lifetime_requires_exact_same_invocation_sequence(self):
        for marker in (
            "P2_VIP_UAUT_AUTH=PASS",
            "VIP_UAUT_CLOSE_RESPONSE=PASS",
            "VIP_UCFG_OPEN_RESPONSE=PASS",
            "UCFG_RECEIVED=true",
            "VIP_UCFG_CLOSE_RESPONSE=PASS",
            "P12_READONLY_TRANSACTION=PASS",
        ):
            self.assertIn(marker, self.text)
        self.assertIn("P12_AUTH_SESSION_LIFETIME_SEQUENCE=PASS", self.text)
        self.assertIn("AUTH_SESSION_LIFETIME_VERIFIED=PASS", self.text)
        self.assertIn("len(hits) != 1", self.text)
        self.assertIn("positions != sorted(positions)", self.text)

    def test_target_binding_must_be_fresh_and_public_safe(self):
        self.assertIn("UCFG_CAPTURE=/run/comelit-p2p/p12-ucfg-response.json", self.text)
        self.assertIn('rm -f -- "$UCFG_CAPTURE"', self.text)
        self.assertEqual(self.text.count('python3 "$SCRIPT_DIR/p12_verify_target_binding.py"'), 1)
        self.assertIn("TARGET_BINDING_VERIFIED=PASS", self.text)
        self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", self.text)
        self.assertIn("P12_TARGET_BINDING_PROOF=FAIL", self.text)

    def test_all_readonly_live_gates_are_emitted_but_aggregate_waits_for_repository_evaluator(self):
        for marker in (
            "REAL_TRANSPORT_IMPLEMENTED=true",
            "REAL_TRANSPORT_READONLY_SESSION_PROOF=PASS",
            "READONLY_SCOPE_ENFORCED=PASS",
            "TARGET_BINDING_VERIFIED=PASS",
            "AUTH_SESSION_LIFETIME_VERIFIED=PASS",
            "TIMEOUT_MAPPING_VERIFIED=PASS",
            "CREDENTIAL_MATERIAL_EMITTED=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "P12_READONLY_LIVE_GATES=PASS",
        ):
            self.assertIn(marker, self.text)
        self.assertIn('echo "READONLY_TRANSPORT_READY=false"', self.text)
        self.assertNotIn('echo "READONLY_TRANSPORT_READY=true"', self.text)
        self.assertIn("LIVE_TEST_READY=false", self.text)


if __name__ == "__main__":
    unittest.main()
