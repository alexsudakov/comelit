from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_readonly_live_preflight.sh"


class P12ReadonlyLivePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.lines = [line.strip() for line in cls.text.splitlines()]

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
        self.assertNotIn('"$WRAPPER"', self.lines)
        self.assertNotIn('"$BINARY"', self.lines)
        self.assertNotIn('exec "$WRAPPER"', self.text)
        self.assertNotIn('exec "$BINARY"', self.text)

    def test_readonly_and_actuator_guards_are_present(self):
        self.assertIn("P12_READONLY_TRANSACTION=PASS", self.text)
        self.assertIn("P12_VIP_TOKEN_VALUE_EMITTED=false", self.text)
        self.assertIn("CREDENTIAL_MATERIAL_EMITTED=false", self.text)
        self.assertIn("AUTO_RETRY_OBSERVED=false", self.text)
        self.assertIn("CTPP|OPEN_DOOR|open_door|create_door_message", self.text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_EFFECT_ASSERTED=false", self.text)

    def test_diagnostic_trap_preserves_exit_status_and_reports_last_step(self):
        self.assertIn("P12_PREFLIGHT_DIAGNOSTIC_TRAP=ARMED", self.text)
        self.assertIn("P12_PREFLIGHT_EXIT_RC=$rc", self.text)
        self.assertIn("P12_PREFLIGHT_LAST_STEP=$STEP", self.text)
        self.assertIn("trap - EXIT", self.text)
        self.assertIn('exit "$rc"', self.text)
        for step in (
            "SOURCE_ACTUATOR_SCAN",
            "BINARY_ACTUATOR_SCAN",
            "WRAPPER_ACTUATOR_SCAN",
            "READONLY_SURFACE",
            "WRAPPER_BINDING",
            "CONTROL_PLANE_PARSE",
            "CREDENTIAL_METADATA",
            "PROCESS_CHECK",
            "COMPLETE",
        ):
            self.assertIn(f"STEP={step}", self.text)
        self.assertIn("P12_PREFLIGHT_SOURCE_ACTUATOR_SCAN=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_BINARY_ACTUATOR_SCAN=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_WRAPPER_ACTUATOR_SCAN=PASS", self.text)

    def test_control_plane_is_parsed_and_checked_without_execution(self):
        for name in (
            "p12_one_shot_exec.py",
            "p12_verify_target_binding.py",
            "run_p12_readonly_live_once.sh",
            "p12_finalize_readonly_readiness.py",
        ):
            self.assertIn(name, self.text)
        self.assertIn("ast.parse", self.text)
        self.assertIn("P12_PREFLIGHT_ONE_SHOT_CONTROL=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_TARGET_HASH_PROFILE=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_LIVE_RUNNER_CONTRACT=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_FINALIZER_CONTRACT=PASS", self.text)
        self.assertIn("P12_PREFLIGHT_CONTROL_PLANE=PASS", self.text)
        self.assertIn("subprocess.Popen(", self.text)
        self.assertIn("start_new_session=True", self.text)
        self.assertIn("os.killpg(proc.pid, sig)", self.text)
        self.assertIn('echo "READONLY_TRANSPORT_READY=false"', self.text)
        self.assertIn('echo "READONLY_TRANSPORT_READY=true"', self.text)

    def test_target_profile_checks_hashes_without_emitting_identity_values(self):
        self.assertIn('{"model", "version", "apt-address", "apt-subaddress"}', self.text)
        self.assertIn(r'[0-9a-f]{64}', self.text)
        self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", self.text)

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
