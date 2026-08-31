from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "scripts" / "start_p12_readonly_preflight_service.sh"
COLLECT = ROOT / "scripts" / "collect_p12_readonly_preflight_service.sh"


class P12ReadonlyPreflightServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = START.read_text(encoding="utf-8")
        cls.collect = COLLECT.read_text(encoding="utf-8")

    def test_service_runs_only_preflight_and_survives_console_disconnect(self):
        self.assertIn("/usr/bin/systemd-run", self.start)
        self.assertIn("--property=KillMode=control-group", self.start)
        self.assertIn("--property=TimeoutStartSec=120", self.start)
        self.assertIn('PREFLIGHT="$SCRIPT_DIR/p12_readonly_live_preflight.sh"', self.start)
        self.assertNotIn("run_p12_readonly_live_once.sh", self.start)
        self.assertIn("P12_PREFLIGHT_LIVE_RUN_PERFORMED=false", self.start)
        self.assertIn("ACTIVE_COMELIT_NETWORK_PROBES=false", self.start)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", self.start)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.start)

    def test_service_payload_has_start_end_and_rc_evidence(self):
        self.assertIn("P12_PREFLIGHT_SERVICE_PAYLOAD_START=true", self.start)
        self.assertIn("P12_PREFLIGHT_SERVICE_PAYLOAD_END=true", self.start)
        self.assertIn('printf "P12_PREFLIGHT_RC=%s\\n" "$rc"', self.start)
        self.assertIn("P12_PREFLIGHT_SERVICE_REPOSITORY_HEAD=", self.start)
        self.assertIn("P12_PREFLIGHT_SERVICE_REPOSITORY_TREE=", self.start)

    def test_collector_fails_closed_on_empty_or_incomplete_evidence(self):
        self.assertIn('[[ -s "$LOG" ]]', self.collect)
        self.assertIn('[[ -s "$RCFILE" ]]', self.collect)
        self.assertIn("P12_PREFLIGHT_SERVICE_START_MARKER=FAIL", self.collect)
        self.assertIn("P12_PREFLIGHT_SERVICE_END_MARKER=FAIL", self.collect)
        self.assertIn("P12_PREFLIGHT_RC_PARSE=FAIL", self.collect)
        self.assertIn("P12_PREFLIGHT_SERVICE_REQUIRED_MARKER_MISSING=", self.collect)

    def test_collector_requires_complete_safe_preflight(self):
        for marker in (
            "P12_PREFLIGHT_BUILD_IDENTITY=PASS",
            "P12_PREFLIGHT_ARTIFACT_SHAPE=PASS",
            "P12_PREFLIGHT_SOURCE_ACTUATOR_SCAN=PASS",
            "P12_PREFLIGHT_BINARY_ACTUATOR_SCAN=PASS",
            "P12_PREFLIGHT_WRAPPER_ACTUATOR_SCAN=PASS",
            "P12_PREFLIGHT_READONLY_SURFACE=PASS",
            "P12_PREFLIGHT_CONTROL_PLANE=PASS",
            "P12_PREFLIGHT_CREDENTIAL_METADATA=PASS",
            "P12_PREFLIGHT_NO_ACTIVE_CANDIDATE=PASS",
            "P12_READONLY_LIVE_PREFLIGHT=PASS",
            "P12_PREFLIGHT_EXIT_RC=0",
            "P12_PREFLIGHT_LAST_STEP=COMPLETE",
            "P12_READONLY_LIVE_RUN_PERFORMED=false",
            "ACTIVE_COMELIT_NETWORK_PROBES=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "READONLY_TRANSPORT_READY=false",
            "LIVE_TEST_READY=false",
        ):
            self.assertIn(marker, self.collect)
        self.assertIn("P12_PREFLIGHT_SERVICE_RESULT=PASS", self.collect)


if __name__ == "__main__":
    unittest.main()
