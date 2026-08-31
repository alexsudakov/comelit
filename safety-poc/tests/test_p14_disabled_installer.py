import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "install_p14_ha_bridge_disabled.sh"


class P14DisabledInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = INSTALLER.read_text(encoding="utf-8")

    def test_installer_is_explicitly_disabled_and_loopback_only(self):
        self.assertIn("COMELIT_P14_LIVE_ENABLED=false", self.text)
        self.assertNotIn("COMELIT_P14_LIVE_ENABLED=true", self.text)
        self.assertIn("COMELIT_P14_BIND_HOST=127.0.0.1", self.text)
        self.assertIn("http://127.0.0.1:18014/healthz", self.text)
        self.assertNotIn("/v1/open-door", self.text)

    def test_installer_never_maps_physical_approval_or_invokes_runner(self):
        self.assertNotIn("P13_APPROVAL=", self.text)
        self.assertNotIn("I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST", self.text)
        self.assertNotIn("OPEN_72K4_3_ONCE", self.text)
        self.assertIn("P14_RUNNER_INVOCATION_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.text)

    def test_installer_requires_separate_clean_p13_runtime(self):
        self.assertIn("EXPECTED_P13_BRANCH=feat/p13-one-shot-actuation", self.text)
        self.assertIn("P14_P13_RUNTIME_WORKTREE_CLEAN=false", self.text)
        self.assertIn("P13_RUNNER=", self.text)
        self.assertIn("COMELIT_P14_RUNNER=$P13_RUNNER", self.text)

    def test_secret_is_root_only_and_never_printed(self):
        self.assertIn("chmod 0600 \"$ENV_FILE\"", self.text)
        self.assertIn("P14_SHARED_SECRET_EMITTED=false", self.text)
        self.assertNotIn("echo \"$SHARED_SECRET\"", self.text)

    def test_existing_env_cannot_be_silently_changed_from_live_to_disabled(self):
        self.assertIn("P14_ENV_EXISTING_NOT_DISABLED=true", self.text)
        self.assertIn("grep -qx 'COMELIT_P14_LIVE_ENABLED=false'", self.text)


if __name__ == "__main__":
    unittest.main()
