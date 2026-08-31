import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "set_p14_bridge_private_bind_disabled.sh"


class P14PrivateBindDisabledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_transition_requires_existing_disabled_runtime(self):
        self.assertIn("grep -qx 'COMELIT_P14_LIVE_ENABLED=false'", self.text)
        self.assertIn("P14_PRIVATE_BIND_ENV_NOT_DISABLED=true", self.text)
        self.assertNotIn("COMELIT_P14_LIVE_ENABLED=true", self.text)

    def test_only_private_ipv4_is_accepted(self):
        self.assertIn("ipaddress.ip_address", self.text)
        self.assertIn("addr.version != 4", self.text)
        self.assertIn("not addr.is_private", self.text)
        self.assertIn("addr.is_loopback", self.text)
        self.assertIn("addr.is_unspecified", self.text)
        self.assertIn("addr.is_multicast", self.text)

    def test_transition_contains_no_actuation_request_or_approval(self):
        self.assertNotIn("/v1/open-door", self.text)
        self.assertNotIn("P13_APPROVAL=", self.text)
        self.assertNotIn("I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST", self.text)
        self.assertNotIn("OPEN_72K4_3_ONCE", self.text)
        self.assertIn("P14_OPEN_DOOR_REQUEST_SENT=false", self.text)
        self.assertIn("P14_RUNNER_INVOCATION_ATTEMPTED=false", self.text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.text)

    def test_health_probe_targets_selected_private_address(self):
        self.assertIn('http://$BIND_HOST:$PORT/healthz', self.text)
        self.assertNotIn('http://127.0.0.1:$PORT/healthz', self.text)
        self.assertIn('assert obj.get("live_enabled") is False', self.text)

    def test_env_rewrite_only_changes_bind_host(self):
        self.assertIn('lines[bind_idx] = f"COMELIT_P14_BIND_HOST={bind_host}"', self.text)
        self.assertIn('if lines[live_idx] != "COMELIT_P14_LIVE_ENABLED=false"', self.text)
        self.assertIn('tmp.chmod(0o600)', self.text)


if __name__ == "__main__":
    unittest.main()
