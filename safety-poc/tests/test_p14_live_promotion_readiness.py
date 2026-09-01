import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMOTE = ROOT / "deploy" / "promote_p14_live.sh"


class P14LivePromotionReadinessTests(unittest.TestCase):
    def test_live_promotion_waits_for_application_readiness(self):
        text = PROMOTE.read_text()
        for marker in (
            "HEALTH_READY_ATTEMPTS=20",
            "HEALTH_PROBE_TIMEOUT_SECONDS=0.25",
            "HEALTH_READY_INTERVAL_SECONDS=0.25",
            "wait_for_live_health()",
            'systemctl is-active --quiet "$BRIDGE_SERVICE"',
            'sleep "$HEALTH_READY_INTERVAL_SECONDS"',
            "P14_LIVE_BRIDGE_READINESS_TIMEOUT_ATTEMPTS=",
        ):
            self.assertIn(marker, text)

        restart = text.index('systemctl restart "$BRIDGE_SERVICE"')
        # The first restart occurrence belongs to rollback; the live promotion
        # restart is the final one before readiness verification.
        restart = text.rindex('systemctl restart "$BRIDGE_SERVICE"')
        readiness = text.index("wait_for_live_health", restart)
        self.assertLess(restart, readiness)

    def test_live_readiness_checks_service_before_http_probe(self):
        text = PROMOTE.read_text()
        start = text.index("wait_for_live_health()")
        end = text.index('[[ "${EUID}"', start)
        readiness = text[start:end]
        active = readiness.index('systemctl is-active --quiet "$BRIDGE_SERVICE"')
        curl = readiness.index("curl --fail --silent --show-error")
        self.assertLess(active, curl)

    def test_live_health_contract_requires_runner_identity_pass(self):
        text = PROMOTE.read_text()
        start = text.index("wait_for_live_health()")
        end = text.index('[[ "${EUID}"', start)
        readiness = text[start:end]
        for marker in (
            'obj.get("ok") is True',
            'obj.get("protocol_version") == 1',
            'obj.get("live_enabled") is True',
            'obj.get("runner_identity") == "pass"',
        ):
            self.assertIn(marker, readiness)

    def test_firewall_is_confirmed_active_before_live_bridge_restart(self):
        text = PROMOTE.read_text()
        firewall_enable = text.index(
            "systemctl enable --now comelit-p14-firewall.service"
        )
        firewall_active = text.index(
            "systemctl is-active --quiet comelit-p14-firewall.service"
        )
        firewall_table = text.index("nft list table inet comelit_p14", firewall_active)
        live_restart = text.rindex('systemctl restart "$BRIDGE_SERVICE"')
        self.assertLess(firewall_enable, firewall_active)
        self.assertLess(firewall_active, firewall_table)
        self.assertLess(firewall_table, live_restart)

    def test_startup_diagnostics_precede_rollback_and_are_non_actuating(self):
        text = PROMOTE.read_text()
        diagnostics = text.index("startup_diagnostics()")
        rollback = text.index("rollback()")
        self.assertLess(diagnostics, rollback)
        self.assertIn('systemctl status "$BRIDGE_SERVICE" --no-pager -l', text)
        self.assertIn(
            'journalctl -u "$BRIDGE_SERVICE" --no-pager -n 100 -o short-iso-precise',
            text,
        )
        self.assertNotIn("/v1/open-door", text)
        self.assertNotIn("P13_APPROVAL=", text)
        self.assertIn("P14_OPEN_DOOR_REQUEST_SENT=false", text)
        self.assertIn("P14_RUNNER_INVOCATION_ATTEMPTED=false", text)


if __name__ == "__main__":
    unittest.main()
