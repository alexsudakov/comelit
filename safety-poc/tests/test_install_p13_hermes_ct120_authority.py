from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_p13_hermes_ct120_authority.sh"
RUNTIME = ROOT / "deploy" / "p13_hermes_ct120_runtime_dispatch.sh"


class HermesCt120AuthorityInstallerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = INSTALLER.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_runtime_exposes_only_two_modes(self) -> None:
        self.assertIn("readiness)", self.runtime)
        self.assertIn("observed-open)", self.runtime)
        self.assertIn("P13_HERMES_RUNTIME_DISPATCH_ALLOWED=readiness|observed-open", self.runtime)
        self.assertNotIn("eval ", self.runtime)
        self.assertNotIn("bash -c", self.runtime)

    def test_runtime_uses_fixed_repo_and_pinned_children(self) -> None:
        self.assertIn("REPO_ROOT=/root/comelit-git", self.runtime)
        self.assertIn("EXPECTED_PREFLIGHT_BLOB=302ebda51439bdfe8b09782e80b0cd531daad237", self.runtime)
        self.assertIn("EXPECTED_GATE_BLOB=f1e40090b6dc458e90a7e662eee2d20d880f2d4d", self.runtime)
        self.assertIn("git -C \"$REPO_ROOT\" hash-object \"$PREFLIGHT\"", self.runtime)
        self.assertIn("git -C \"$REPO_ROOT\" hash-object \"$GATE\"", self.runtime)

    def test_readiness_strips_live_environment(self) -> None:
        self.assertIn('exec env -u P13_APPROVAL -u P13_OPERATION_ID bash "$PREFLIGHT"', self.runtime)

    def test_observed_open_requires_exact_approval_and_one_gate_exec(self) -> None:
        self.assertIn("I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST", self.runtime)
        self.assertEqual(self.runtime.count('exec bash "$GATE" "$ACTION_PHRASE"'), 1)
        self.assertNotIn("while ", self.runtime)
        self.assertNotIn("until ", self.runtime)

    def test_installer_preserves_existing_front_and_does_not_change_sshd_or_keys(self) -> None:
        self.assertIn("EXPECTED_OLD_FRONT_SHA256=e4bb63d7939a67344eedbfaf9f01a8a0a9e1578a74665e4b84f169466eb62e63", self.installer)
        self.assertIn("hermes-comelit-dispatch.pre-p13-observed-v1", self.installer)
        self.assertNotIn("sshd_config", self.installer)
        self.assertNotIn("authorized_keys", self.installer)
        self.assertNotIn("systemctl restart ssh", self.installer)

    def test_front_accepts_only_exact_logical_commands(self) -> None:
        self.assertIn("comelit-p13-readiness)", self.installer)
        self.assertIn('"comelit-p13-observed-open $APPROVAL")', self.installer)
        self.assertIn('exec sudo -n "$RUNTIME" readiness', self.installer)
        self.assertIn('exec sudo -n "$RUNTIME" observed-open "$APPROVAL"', self.installer)
        self.assertIn('exec "$BACKUP"', self.installer)
        self.assertNotIn("$SSH_ORIGINAL_COMMAND\"", self.installer)

    def test_sudoers_is_exact_and_no_general_root_shell(self) -> None:
        self.assertIn("NOPASSWD: $RUNTIME_DST readiness", self.installer)
        self.assertIn("NOPASSWD: $RUNTIME_DST observed-open $APPROVAL", self.installer)
        self.assertNotIn("NOPASSWD: ALL", self.installer)
        self.assertNotIn("/bin/bash", self.installer)
        self.assertNotIn("/bin/sh", self.installer)

    def test_installer_performs_no_door_action(self) -> None:
        self.assertNotIn("OPEN_72K4_3_ONCE", self.installer)
        self.assertNotIn("P13_APPROVAL=", self.installer)
        self.assertIn("P13_HERMES_AUTHORITY_PHYSICAL_ACTION=false", self.installer)
        self.assertIn("P13_HERMES_AUTHORITY_SEND_ARMED=false", self.installer)


if __name__ == "__main__":
    unittest.main()
