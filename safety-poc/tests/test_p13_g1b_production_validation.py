from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

RUNNER = ROOT / "deploy" / "p13_g1b_production_validation_runner.sh"
GATE = ROOT / "deploy" / "p13_g1b_production_validation_gate.sh"
AUTH = ROOT / "scripts" / "install_p13_g1b_hermes_authority.sh"
INSTALLER = ROOT / "deploy" / "install_p13_production_release.sh"


class P13G1BProductionValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.gate = GATE.read_text(encoding="utf-8")
        cls.auth = AUTH.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_runner_is_immutable_release_bound_not_git_worktree_bound(self):
        self.assertIn(
            "RELEASE_ROOT=",
            self.runner,
        )
        self.assertIn(
            "sha256sum -c RELEASE_CONTENT.sha256",
            self.runner,
        )
        self.assertNotIn("/root/comelit-git", self.runner)
        self.assertNotIn("git -C", self.runner)

    def test_runner_has_exactly_one_real_python_handoff(self):
        self.assertEqual(
            self.runner.count(
                "python3 -m comelit_safety_poc.p13_one_shot_physical"
            ),
            1,
        )
        self.assertIn(
            "P13_G1B_AUTO_RETRY_ALLOWED=false",
            self.runner,
        )

    def test_gate_consumes_before_single_execute_handoff(self):
        consumed = self.gate.index(
            "P13_G1B_GATE_STATE=CONSUMED_BEFORE_LIVE_ENTRYPOINT"
        )
        execute = self.gate.index(
            'bash "$RUNNER" execute "$OPERATION_ID"'
        )
        self.assertLess(consumed, execute)
        self.assertEqual(
            self.gate.count(
                'bash "$RUNNER" execute "$OPERATION_ID"'
            ),
            1,
        )
        self.assertNotIn('rm -f "$STATE"', self.gate)
        self.assertNotIn("reset", self.gate.lower())

    def test_gate_has_non_actuating_readiness(self):
        self.assertIn("readiness)", self.gate)
        self.assertIn(
            "P13_G1B_NON_ACTUATING_PREFLIGHT=PASS",
            self.runner,
        )
        self.assertIn(
            "PHYSICAL_DOOR_ACTION=false",
            self.runner,
        )

    def test_g1b_uses_new_external_approval_identity(self):
        approval = (
            "I_APPROVE_P13_G1B_IMMUTABLE_PRODUCTION_DOOR_TEST"
        )
        self.assertIn(approval, self.gate)
        self.assertIn(approval, self.auth)

    def test_authority_exposes_only_exact_g1b_commands(self):
        self.assertIn(
            "comelit-p13-g1b-readiness",
            self.auth,
        )
        self.assertIn(
            "comelit-p13-g1b-open",
            self.auth,
        )
        self.assertIn(
            "P13_G1B_HERMES_ARBITRARY_SHELL=false",
            self.auth,
        )
        self.assertIn(
            "P13_G1B_HERMES_ARBITRARY_ROOT=false",
            self.auth,
        )

    def test_authority_installer_is_non_actuating(self):
        self.assertIn(
            "P13_G1B_NETWORK_DOOR_ACTION_PERFORMED=false",
            self.auth,
        )
        self.assertIn(
            "P13_G1B_PHYSICAL_DOOR_ACTION=false",
            self.auth,
        )
        self.assertNotIn(
            ' "$G1B_GATE" open ',
            self.auth.split("cat >")[0],
        )

    def test_release_manifest_records_g1b_target_identity(self):
        self.assertIn(
            "P13_G1B_VALIDATION_SCHEMA=1",
            self.installer,
        )
        self.assertIn(
            "P13_TARGET_FINGERPRINT="
            "832e5c09cf5f8ef79b9af83ba34b38a0"
            "a29847570ea37158310369850e2500ce",
            self.installer,
        )

    def test_previous_reporting_checks_symlink_existence(self):
        self.assertIn(
            'if [[ -L "$PREVIOUS" ]]; then',
            self.installer,
        )
        self.assertIn(
            "PREVIOUS_REAL=none",
            self.installer,
        )


if __name__ == "__main__":
    unittest.main()
