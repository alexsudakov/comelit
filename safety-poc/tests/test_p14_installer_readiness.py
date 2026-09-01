import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "deploy" / "install_p14_production_release.sh"


class P14InstallerReadinessTests(unittest.TestCase):
    def test_installer_waits_for_application_readiness(self):
        text = INSTALL.read_text()
        self.assertIn("HEALTH_READY_ATTEMPTS=40", text)
        self.assertIn("HEALTH_READY_INTERVAL_SECONDS=0.25", text)
        self.assertIn("wait_for_bridge_health()", text)
        self.assertIn('systemctl is-active --quiet "$UNIT_NAME"', text)
        self.assertIn('curl --fail --silent --show-error --max-time 1 "$HEALTH_URL"', text)
        self.assertIn('sleep "$HEALTH_READY_INTERVAL_SECONDS"', text)
        self.assertIn('P14_BRIDGE_READINESS_TIMEOUT_ATTEMPTS=', text)

        start = text.index("wait_for_bridge_health()")
        verify = text.index("STEP=VERIFY")
        verify_call = text.index("wait_for_bridge_health", verify)
        self.assertLess(start, verify)
        self.assertLess(verify, verify_call)

    def test_readiness_checks_service_before_each_health_probe(self):
        text = INSTALL.read_text()
        start = text.index("wait_for_bridge_health()")
        end = text.index("restore_prior_service_state()", start)
        readiness = text[start:end]
        active = readiness.index('systemctl is-active --quiet "$UNIT_NAME"')
        curl = readiness.index('curl --fail --silent --show-error --max-time 1 "$HEALTH_URL"')
        self.assertLess(active, curl)

    def test_startup_failure_diagnostics_are_captured_before_rollback(self):
        text = INSTALL.read_text()
        self.assertIn("startup_diagnostics()", text)
        self.assertIn('systemctl status "$UNIT_NAME" --no-pager -l', text)
        self.assertIn('journalctl -u "$UNIT_NAME" --no-pager -n 100 -o short-iso-precise', text)
        readiness = text.index("wait_for_bridge_health()")
        cleanup = text.index("cleanup()")
        self.assertLess(readiness, cleanup)

    def test_health_contract_remains_disabled_only(self):
        text = INSTALL.read_text()
        for marker in (
            'obj.get("ok") is True',
            'obj.get("protocol_version") == 1',
            'obj.get("live_enabled") is False',
            'obj.get("runner_identity") == "disabled"',
        ):
            self.assertIn(marker, text)
        self.assertIn("P14_OPEN_DOOR_REQUEST_SENT=false", text)
        self.assertIn("P14_RUNNER_INVOCATION_ATTEMPTED=false", text)


if __name__ == "__main__":
    unittest.main()
