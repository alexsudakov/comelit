import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEGACY=ROOT/'deploy'/'install_p14_ha_bridge_disabled.sh'
INSTALL=ROOT/'deploy'/'install_p14_production_release.sh'

class P14DisabledInstallerTests(unittest.TestCase):
    def test_legacy_entrypoint_routes_to_production_installer(self):
        text=LEGACY.read_text()
        self.assertIn('P14_LEGACY_DISABLED_INSTALLER_SUPERSEDED=true',text)
        self.assertIn('install_p14_production_release.sh',text)

    def test_production_installer_is_disabled_loopback_and_non_actuating(self):
        text=INSTALL.read_text()
        self.assertIn('COMELIT_P14_LIVE_ENABLED=false',text)
        self.assertIn('COMELIT_P14_BIND_HOST=127.0.0.1',text)
        self.assertIn('http://127.0.0.1:18014/healthz',text)
        self.assertIn('P14_RUNNER_INVOCATION_ATTEMPTED=false',text)
        self.assertIn('PHYSICAL_DOOR_ACTION=false',text)
        self.assertNotIn('/v1/open-door',text)

    def test_installer_uses_immutable_p13_not_p13_worktree(self):
        text=INSTALL.read_text()
        self.assertIn('p13-415edb4525e4-50c0a916f73e-b6a10c68773a',text)
        self.assertIn('RELEASE_CONTENT.sha256',text)
        self.assertNotIn('EXPECTED_P13_BRANCH=feat/p13-one-shot-actuation',text)

    def test_secret_is_root_only_and_never_printed(self):
        text=INSTALL.read_text()
        self.assertIn('chmod 600 "$ENV_FILE.tmp"',text)
        self.assertIn('P14_SHARED_SECRET_EMITTED=false',text)
        self.assertNotIn('echo "$SHARED_SECRET"',text)

    def test_existing_live_runtime_must_be_explicitly_disabled_before_upgrade(self):
        text=INSTALL.read_text()
        self.assertIn('P14_EXISTING_RUNTIME_MUST_BE_DISABLED_BEFORE_INSTALL=true',text)
        self.assertIn("grep -qx 'COMELIT_P14_LIVE_ENABLED=false'",text)

if __name__=='__main__': unittest.main()
