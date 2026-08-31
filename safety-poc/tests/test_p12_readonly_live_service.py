from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "scripts" / "start_p12_readonly_live_service.sh"
COLLECT = ROOT / "scripts" / "collect_p12_readonly_live_service.sh"


class P12ReadonlyLiveServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = START.read_text(encoding="utf-8")
        cls.collect = COLLECT.read_text(encoding="utf-8")

    def test_start_is_systemd_detached_and_explicitly_approved(self):
        self.assertIn("systemd-run", self.start)
        self.assertIn("Type=oneshot", self.start)
        self.assertIn("KillMode=control-group", self.start)
        self.assertIn("TimeoutStartSec=120", self.start)
        self.assertIn("I_APPROVE_P12_READONLY_LIVE_ONCE", self.start)
        self.assertIn('P12_READONLY_LIVE_APPROVAL="$approval"', self.start)
        self.assertIn("P12_LIVE_SERVICE_PAYLOAD_START=true", self.start)
        self.assertIn("P12_LIVE_SERVICE_PAYLOAD_END=true", self.start)

    def test_start_runs_only_readonly_runner_once(self):
        self.assertEqual(self.start.count('/bin/bash "$runner"'), 1)
        self.assertIn("run_p12_readonly_live_once.sh", self.start)
        self.assertIn("P12_LIVE_SERVICE_AUTO_RETRY=false", self.start)
        self.assertIn("P12_LIVE_SERVICE_DOOR_CTPP_ALLOWED=false", self.start)
        self.assertNotIn("for attempt", self.start)
        self.assertNotIn("while true", self.start.lower())
        self.assertNotIn("open_door", self.start)
        self.assertNotIn("OPEN_DOOR", self.start)

    def test_collector_waits_only_for_local_result(self):
        self.assertIn("P12_LIVE_COLLECT_WAIT_ONLY=true", self.collect)
        self.assertIn('[[ -s "$RCFILE" ]] && break', self.collect)
        self.assertIn("sleep 1", self.collect)
        self.assertNotIn("run_p12_readonly_live_once.sh", self.collect)
        self.assertNotIn("P12_READONLY_LIVE_APPROVAL=", self.collect)

    def test_collector_reports_functional_poc_status(self):
        self.assertIn("POC_P2P_CONNECTION=PASS", self.collect)
        self.assertIn("POC_AUTHENTICATION=PASS", self.collect)
        self.assertIn("POC_DEVICE_IDENTIFICATION=PASS", self.collect)
        self.assertIn("POC_P2P_CONNECTION=NOT_PROVEN", self.collect)
        self.assertIn("POC_AUTHENTICATION=NOT_PROVEN", self.collect)
        self.assertIn("P2_VIP_UAUT_AUTH=PASS", self.collect)
        self.assertIn("UAUT_RESPONSE_CODE=200", self.collect)

    def test_collector_requires_one_shot_and_closed_actuator_surface(self):
        for marker in (
            "P12_ONE_SHOT_PROCESS_INVOCATIONS=1",
            "P12_ONE_SHOT_AUTO_RETRY=false",
            "P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true",
            "P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1",
            "P12_READONLY_LIVE_WRAPPER_OUTCOME=COMPLETED",
            "P12_READONLY_LIVE_WRAPPER_RC=0",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "PHYSICAL_EFFECT_ASSERTED=false",
            "READONLY_TRANSPORT_READY=false",
            "LIVE_TEST_READY=false",
        ):
            self.assertIn(marker, self.collect)

    def test_collector_fails_closed_on_missing_or_nonzero_result(self):
        self.assertIn("P12_LIVE_LOG_NONEMPTY=false", self.collect)
        self.assertIn("P12_LIVE_RC_NONEMPTY=false", self.collect)
        self.assertIn('if [[ "$RC" != "0" ]]', self.collect)
        self.assertIn("P12_LIVE_SERVICE_REQUIRED_MARKER_MISSING=", self.collect)
        self.assertIn("P12_LIVE_SERVICE_RESULT=FAIL", self.collect)


if __name__ == "__main__":
    unittest.main()
