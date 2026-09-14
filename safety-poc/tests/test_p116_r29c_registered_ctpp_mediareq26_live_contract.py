"""Contract tests for the P116/R29C registered-CTPP mediareq26 live runner.

The runner is the bounded live-execution half of the R29C lane: one authorised handoff,
one inbound CALL_INIT, exactly one registered-CTPP mediareq26 OPEN, <=10 s video RTP
observation, exactly one mediareq26 STOP, listener survival check, research session close,
production listener restore.  These tests pin the fail-closed properties only; they never
execute a live phase and never touch the network.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"
PROBE_TRANSFORM = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"
BUILDER = MEDIA / "ct120_build_p80_haos_media_helper.sh"


class P116R29CRegisteredCtppMediaReq26LiveRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_runner_exists_and_parses(self) -> None:
        self.assertTrue(RUNNER.exists(), RUNNER)
        subprocess.run(["bash", "-n", str(RUNNER)], check=True)

    def test_runner_reuses_the_r29c_probe_transform_and_builder(self) -> None:
        for needle in (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py",
            "BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh",
            'P80_BUILD_TRANSFORM="$TRANSFORM_REL"',
            "P80_BUILD_INCLUDE_P116=1",
            'P80_BUILD_EXPECTED_SOURCE_SHA="$R29C_EXPECTED_GENERATED_SOURCE_SHA"',
        ):
            self.assertIn(needle, self.text)
        self.assertTrue(PROBE_TRANSFORM.exists(), PROBE_TRANSFORM)
        self.assertTrue(BUILDER.exists(), BUILDER)

    def test_arm_is_the_default_phase_and_arm_never_authorises_live(self) -> None:
        self.assertIn("R29C_PHASE=${R29C_PHASE:-ARM}", self.text)
        self.assertIn('if [ "$R29C_PHASE" != LIVE ]; then', self.text)
        self.assertIn("R29C_LIVE_PREFLIGHT_REFUSED=ARM_ONLY_MODE", self.text)
        self.assertIn("LIVE_RUN=NOT_RUN", self.text)
        arm_start = self.text.index('if [ "$R29C_PHASE" != LIVE ]; then')
        arm_end = self.text.index("R29C_LIVE_PREFLIGHT_REFUSED=ARM_ONLY_MODE")
        arm_body = self.text[arm_start:arm_end]
        self.assertNotIn("post_control stop", arm_body)
        self.assertNotIn("timeout --signal=TERM", arm_body)

    def test_legacy_r29_live_run_cannot_authorise_live(self) -> None:
        self.assertIn("R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN", self.text)
        self.assertIn(
            'if [ "$LIVE_RUN" != YES ] || [ "$R29C_LIVE_AUTHORIZED" != authorized ]; then',
            self.text,
        )
        self.assertIn("R29C_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN", self.text)
        # R29_LIVE_RUN must never appear inside an authorisation predicate.
        for line in self.text.splitlines():
            if "R29_LIVE_RUN" in line and not line.strip().startswith("#"):
                self.assertNotIn("== YES", line)
                self.assertNotIn("=authorized", line)

    def test_budgets_are_declared_and_consumed_exactly_once(self) -> None:
        for needle in (
            "LIVE_ATTEMPT_BUDGET_USED=0",
            "RING_BUDGET_USED=0",
            "OPEN_BUDGET_USED=0",
            "STOP_BUDGET_USED=0",
            "LIVE_ATTEMPT_BUDGET_USED=1",
            "RING_BUDGET_USED=1",
            "OPEN_BUDGET_USED=1",
            "STOP_BUDGET_USED=1",
        ):
            self.assertIn(needle, self.text)

    def test_ring_watchdog_and_media_timers_are_bounded(self) -> None:
        self.assertIn("R29C_RING_MAX_SECONDS=${R29C_RING_MAX_SECONDS:-90}", self.text)
        self.assertIn("R29C_RTP_OBSERVATION_SECONDS=${R29C_RTP_OBSERVATION_SECONDS:-10}", self.text)
        self.assertIn("R29C_POST_STOP_OBSERVATION_SECONDS=${R29C_POST_STOP_OBSERVATION_SECONDS:-10}", self.text)
        self.assertIn("R29C_OPEN_MAX_SECONDS=${R29C_OPEN_MAX_SECONDS:-10}", self.text)
        self.assertIn("R29C_STOP_MAX_SECONDS=${R29C_STOP_MAX_SECONDS:-10}", self.text)
        self.assertIn("wait_for_call_init", self.text)
        self.assertIn("NO_CALL_INIT_TIMEOUT", self.text)
        self.assertIn("WRONG_CALL_SOURCE", self.text)

    def test_single_media_only_stop_request_and_no_retry(self) -> None:
        stop_requests = re.findall(r"kill -USR2", self.text)
        self.assertEqual(len(stop_requests), 1, "exactly one mediareq26 STOP request site")
        self.assertIn("REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT 1", self.text)
        for forbidden in ("call_release", "REFRESH_LOOP_STARTED_COUNT=1", "0x1a", "0x1A"):
            self.assertNotIn(forbidden, self.text)

    def test_stop_is_attempted_for_bounded_cleanup_even_without_rtp(self) -> None:
        open_site = self.text.index("OPEN_SENT=true\n    OPEN_BUDGET_USED=1")
        rtp_decision = self.text.index("FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=RESPONSE_NOT_OBSERVED")
        stop_site = self.text.index("kill -USR2")
        self.assertLess(open_site, rtp_decision)
        self.assertLess(rtp_decision, stop_site)
        self.assertIn("STOP_SENT=true\n        STOP_BUDGET_USED=1", self.text)

    def test_classification_cases_are_present_and_distinct(self) -> None:
        for needle in (
            "RESULT=REGISTERED_CTPP_MEDIAREQ26_NOT_PROVEN",
            "RESULT=REGISTERED_CTPP_MEDIAREQ26_OPEN_STOP_LIVE_SUPPORTED",
            "RESULT=REGISTERED_CTPP_MEDIAREQ26_OPEN_SUPPORTED_STOP_BREAKS_LISTENER",
            "RESULT=INCONCLUSIVE_CLEANUP_FAILURE",
            "INCONCLUSIVE_OPEN_NOT_SENT",
            "INCONCLUSIVE_CANDIDATE_BOOTSTRAP_FAILURE",
        ):
            self.assertIn(needle, self.text)
        self.assertIn("REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true", self.text)

    def test_research_candidate_runs_through_the_musl_holder_shim(self) -> None:
        self.assertIn("R29C_SHIM_MUSL_EXEC_GATE=PASS", self.text)
        self.assertIn('CANDIDATE="${R29C_CANDIDATE_PATH:?R29C_CANDIDATE_PATH}"', self.text)
        self.assertIn('RUNTIME_ROOT="${R29C_RUNTIME_ROOT:?R29C_RUNTIME_ROOT}"', self.text)
        self.assertIn('R29C_EXPECTED_CANDIDATE_SHA256="$CANDIDATE_SHA256"', self.text)
        self.assertIn('exec "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$CANDIDATE"', self.text)
        self.assertIn("R29C_SHIM_CANDIDATE_SHA_GATE=FAIL", self.text)
        self.assertIn('"$BASE/bin/comelit_ice_offer_holder"', self.text)
        self.assertNotIn("aiohttp", self.text)

    def test_generated_shim_watchdog_and_reports_do_not_embed_raw_paths_or_secrets(self) -> None:
        self.assertIn('URL="${R29C_WATCHDOG_URL:?R29C_WATCHDOG_URL}"', self.text)
        self.assertIn('LOG="${R29C_WATCHDOG_LOG:?R29C_WATCHDOG_LOG}"', self.text)
        self.assertIn('R29C_WATCHDOG_URL="$HA_WEBHOOK_URL" R29C_WATCHDOG_LOG="$log" setsid "$watchdog"', self.text)
        self.assertIn('echo "R29C_RUN_ROOT=REDACTED"', self.text)
        self.assertIn('echo "RUNTIME_ROOT=REDACTED"', self.text)
        self.assertIn('echo "R29C_RUNTIME_ROOT=SELECTED"', self.text)
        self.assertIn('echo "R29C_RUNTIME_LOADER=SELECTED"', self.text)
        self.assertIn('echo "CANDIDATE_WRAPPER_STARTED=true"', self.text)
        self.assertIn('echo "RESEARCH_LISTENER_PID_OBSERVED=$([ -n "$CANDIDATE_PID" ] && echo true || echo false)"', self.text)
        for forbidden in (
            'CANDIDATE="__CANDIDATE__"',
            'RUNTIME_ROOT="__RUNTIME_ROOT__"',
            'URL="__URL__"',
            'LOG="__LOG__"',
            'echo "R29C_RUN_ROOT=$RUN_ROOT"',
            'echo "R29C_RUNTIME_ROOT=$RUNTIME_ROOT"',
            'echo "R29C_RUNTIME_LOADER=$RUNTIME_LOADER"',
            'echo "WATCHDOG_PID=$WATCHDOG_PID"',
            'echo "CANDIDATE_WRAPPER_PID=$WRAPPER_PID"',
            'echo "RESEARCH_LISTENER_PID=$CANDIDATE_PID"',
            'echo "R29C_SHIM_PID=$$"',
        ):
            self.assertNotIn(forbidden, self.text)

    def test_live_sequence_requires_inactive_production_before_candidate_start(self) -> None:
        stop_site = self.text.index("post_control stop")
        inactive_gate = self.text.index('[ "$UPSTREAM_OWNERSHIP_RELEASED" = true ] || exit 1')
        candidate_site = self.text.index('timeout --signal=TERM --kill-after=5s "$R29C_OUTER_TIMEOUT_SECONDS"')
        self.assertLess(stop_site, inactive_gate)
        self.assertLess(inactive_gate, candidate_site)
        self.assertIn("UPSTREAM_OWNERSHIP_RELEASED=true", self.text)
        self.assertIn("PRODUCTION_LISTENER_INACTIVE=true", self.text)

    def test_restore_path_and_watchdog_exist_without_ha_core_actions(self) -> None:
        self.assertIn("restore_listener()", self.text)
        self.assertIn("arm_autorestore_watchdog()", self.text)
        self.assertIn("AUTO_RESTORE_ARMED", self.text)
        self.assertIn("PRODUCTION_RESTORE_RESULT=PASS", self.text)
        for forbidden in ("ha core restart", "ha core stop", "ha deploy", "homeassistant.restart"):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("HA_DEPLOY_COUNT=0", self.text)
        self.assertIn("HA_RESTART_COUNT=0", self.text)
        self.assertIn("HA_RELOAD_COUNT=0", self.text)

    def test_forbidden_action_surfaces_are_absent(self) -> None:
        for forbidden in (
            "DOOR_ACTIONS_SENT=1",
            "GATE_ACTIONS_SENT=1",
            "SELF_ACTIVATION_001A_SENT_COUNT=1",
            "R27_REPEAT_001A_SENT_COUNT=1",
            "PUBLISH_PRODUCTION",
            "MEDIA_NATIVE_BINARY_SHA256",
        ):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("SELF_ACTIVATION_001A_SENT_COUNT=0", self.text)
        self.assertIn("R27_REPEAT_001A_SENT_COUNT=0", self.text)
        self.assertIn("DOOR_ACTIONS_SENT=0", self.text)
        self.assertIn("GATE_ACTIONS_SENT=0", self.text)

    def test_mandatory_report_fields_are_emitted(self) -> None:
        for field in (
            "MAIN_SHA=",
            "CANDIDATE_SOURCE_SHA256=",
            "CANDIDATE_BINARY_SHA256=",
            "PREP_READY=",
            "USER_READY_RECEIVED=",
            "PRODUCTION_HANDOFF=",
            "UPSTREAM_OWNERSHIP_RELEASED=",
            "RESEARCH_LISTENER_READY=",
            "RESEARCH_LISTENER_PID_STABLE=",
            "REGISTRATION_GENERATION_STABLE=",
            "PSEUDOTCP_GENERATION_STABLE=",
            "CALL_INIT_OBSERVED=",
            "CALL_SOURCE=",
            "RING_BUDGET_USED=",
            "OPEN_SENT=",
            "OPEN_BUDGET_USED=",
            "VIDEO_RTP_STARTED=",
            "VIDEO_RTP_PACKETS=",
            "RTP_OBSERVATION_SECONDS=",
            "FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=",
            "STOP_SENT=",
            "STOP_BUDGET_USED=",
            "LISTENER_SURVIVED_STOP=",
            "REGISTRATION_SURVIVED_STOP=",
            "PSEUDOTCP_SURVIVED_STOP=",
            "NEW_ICE_AFTER_READY_COUNT=",
            "NEW_CLOUD_AFTER_READY_COUNT=",
            "NEW_PSEUDOTCP_AFTER_READY_COUNT=",
            "NEW_REGISTRATION_AFTER_READY_COUNT=",
            "MEDIA_ONLY_STOP_RESULT=",
            "FINAL_RESEARCH_SESSION_CLEANUP=",
            "PRODUCTION_RESTORE_RESULT=",
            "PRODUCTION_LISTENER_RUNNING=",
            "PRODUCTION_LISTENER_READY=",
            "LIVE_ATTEMPT_BUDGET_USED=",
            "RESULT=",
            "R29_MEDIA_OPEN_MODEL=",
            "R29_MEDIA_ONLY_TEARDOWN_MODEL=",
        ):
            self.assertIn(field, self.text)

    def test_selfcheck_gates_match_the_merged_probe_contract(self) -> None:
        for needle in (
            "CANDIDATE_HELPER_EXECUTED=true",
            "NETWORK_WRITES_INTERCEPTED=true",
            "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=1",
            "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=1",
            "SELF_ACTIVATION_001A_SENT_COUNT=0",
            "R27_REPEAT_001A_SENT_COUNT=0",
            "REGISTRATION_STATE_UNCHANGED=true",
            "LISTENER_STOP_COUNT=0",
            "R29C_PROBE_READY=true",
        ):
            self.assertIn(needle, self.text)
        self.assertIn("--r29-selfcheck", self.text)


if __name__ == "__main__":
    unittest.main()
