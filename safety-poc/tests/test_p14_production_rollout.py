import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/'scripts'/'p14_production_runner.sh'
INSTALL=ROOT/'deploy'/'install_p14_production_release.sh'
PROMOTE=ROOT/'deploy'/'promote_p14_live.sh'
DISABLE=ROOT/'deploy'/'disable_p14_live.sh'
FIREWALL=ROOT/'deploy'/'p14_firewall.sh'

class P14ProductionRolloutTests(unittest.TestCase):
    def test_runner_is_pinned_to_final_immutable_p13(self):
        text=RUNNER.read_text()
        for marker in ('p13-415edb4525e4-50c0a916f73e-b6a10c68773a','0dace902d2cef1478cddea0f9d4cd36fcddb3837','415edb4525e46601cd0ef1249fc0965927b1ac29','P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false','P13_AUTO_RETRY_ALLOWED=false','P14_P13_PHYSICAL_VALIDATION_GATES_RETIRED=PASS','P13_G1B_GATE_STATE=CONSUMED_BEFORE_LIVE_ENTRYPOINT'):
            self.assertIn(marker,text)
        self.assertIn('/usr/bin/env -i', text); self.assertIn('P13_APPROVAL="$P13_APPROVAL_TOKEN"', text); self.assertEqual(text.count('/usr/bin/python3 -m comelit_safety_poc.p13_one_shot_physical'),1); self.assertNotIn('feat/p13-one-shot-actuation', text)

    def test_runner_public_cli_is_operation_id_only(self):
        text=RUNNER.read_text(); self.assertIn('[[ $# -eq 2 && "$1" == \'--operation-id\' ]]', text)
        for forbidden in ('--target-fingerprint)', '--runner)', '--retry)', '--approval)'): self.assertNotIn(forbidden,text)

    def test_installer_is_immutable_and_non_actuating(self):
        text=INSTALL.read_text(); self.assertIn('P14_PRODUCTION_INSTALL_NON_ACTUATING=true',text); self.assertIn('RELEASE_CONTENT.sha256',text); self.assertIn('P14_HA_RESPONSE_REQUIRED=true',text); self.assertIn('COMELIT_P14_LIVE_ENABLED=false',text); self.assertIn('COMELIT_P14_BIND_HOST=127.0.0.1',text); self.assertIn('P14_OPEN_DOOR_REQUEST_SENT=false',text); self.assertNotIn('I_APPROVE_P14_ENABLE_REUSABLE_DOOR_SERVICE',text)

    def test_failed_install_restarts_restored_bridge_state(self):
        text=INSTALL.read_text(); self.assertIn('systemctl is-enabled comelit-p14-ha-bridge.service', text); self.assertIn('systemctl restart comelit-p14-ha-bridge.service', text); self.assertIn('failed release in memory', text)

    def test_live_promotion_requires_explicit_boundary_and_sends_no_post(self):
        text=PROMOTE.read_text(); self.assertIn('I_APPROVE_P14_ENABLE_REUSABLE_DOOR_SERVICE',text); self.assertIn('P14_LIVE_ENABLE_APPROVAL',text); self.assertIn('COMELIT_P14_LIVE_ENABLED":"true"',text); self.assertIn('P14_OPEN_DOOR_REQUEST_SENT=false',text); self.assertIn('P14_LIVE_PROMOTION_DISABLED_HEALTH=PASS', text); self.assertNotIn('/v1/open-door',text); self.assertNotIn('P13_APPROVAL=',text)

    def test_firewall_is_persistent_dependency_before_live_bridge(self):
        p=PROMOTE.read_text(); f=FIREWALL.read_text(); self.assertIn('Before=comelit-p14-ha-bridge.service',p); self.assertIn('Requires=comelit-p14-firewall.service',p); self.assertIn('ip saddr != $P14_HA_CLIENT_IP drop',f); self.assertIn('tcp dport $P14_BRIDGE_PORT',f)

    def test_disable_is_always_non_actuating_and_removes_live_surface(self):
        text=DISABLE.read_text(); self.assertIn('COMELIT_P14_LIVE_ENABLED":"false"',text); self.assertIn('COMELIT_P14_BIND_HOST":"127.0.0.1"',text); self.assertIn('P14_OPEN_DOOR_REQUEST_SENT=false',text); self.assertNotIn('I_APPROVE_P14_ENABLE_REUSABLE_DOOR_SERVICE',text)

if __name__=='__main__': unittest.main()
