#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (
    ROOT
    / "research"
    / "listener"
    / "v1"
    / "ct120_run_p79_cloud_concurrency_probe.sh"
)


class P79LauncherStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = LAUNCHER.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_executable_bash_launcher(self) -> None:
        self.assertTrue(os.access(LAUNCHER, os.X_OK))
        self.assertTrue(self.text.startswith("#!/bin/bash\n"))
        self.assertIn("set -uo pipefail", self.text)
        self.assertNotIn("set -e", self.text)

    def test_listener_is_status_only_with_no_control_actions(self) -> None:
        self.assertIn("P79_LISTENER_CONTROL_MODE=STATUS_ONLY", self.text)
        self.assertIn('-d \'{"action":"status"}\'', self.text)
        self.assertIn("status_only \"$status_preflight\"", self.text)
        self.assertIn("status_only \"$status_before\"", self.text)
        self.assertIn("status_only \"$status_after\"", self.text)
        self.assertIn("collect_post_result_status", self.text)
        self.assertNotRegex(
            self.text,
            r'-d\s+[\'"]\{"action":"(?:start|stop|restart)"\}[\'"]',
        )
        for forbidden in (
            "post_control start",
            "post_control stop",
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "async_start",
            "async_stop",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_exactly_one_p2p_invocation_no_retry(self) -> None:
        invocation = 'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
        self.assertEqual(self.text.count(invocation), 1)
        self.assertIn("P79_LIVE_INVOCATION_LIMIT=1", self.text)
        self.assertIn("P79_WRAPPER_INVOCATIONS=1", self.text)
        self.assertIn("AUTOMATIC_RETRY=false", self.text)
        self.assertIn("P79_AUTO_RETRY=false", self.text)
        for forbidden in ("for attempt", "while true", "sleep 1 &&", "401"):
            self.assertNotIn(forbidden, self.text)

    def test_atomic_sentinel_and_pre_live_failure_order(self) -> None:
        self.assertIn("SENTINEL=/root/.comelit-p79-live-consumed", self.text)
        self.assertIn("os.O_CREAT | os.O_EXCL", self.text)
        self.assertIn("CONSUMED_BEFORE_P79_CLOUD_INVOCATION", self.text)
        self.assertIn("os.fsync(fd)", self.text)
        self.assertIn("os.fsync(parent)", self.text)
        self.assertIn("P79_SENTINEL_PREEXISTING=true", self.text)
        self.assertIn("P79_SENTINEL_CONSUMED=true", self.text)
        self.assertNotRegex(self.text, r"rm\s+.*SENTINEL")

        sentinel = self.text.index("\nconsume_sentinel\n")
        invocation = self.text.index(
            'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
        )
        preflight_pass = self.text.index("P79_PREFLIGHT=PASS")
        self.assertLess(preflight_pass, sentinel)
        self.assertLess(sentinel, invocation)
        self.assertIn("P79_SENTINEL_CONSUMED=false", self.text[:sentinel])

    def test_existing_sentinel_blocks_before_p2p_network_call(self) -> None:
        existing = self.text.index('if [[ -e "$SENTINEL" ]]; then')
        sentinel = self.text.index("\nconsume_sentinel\n")
        invocation = self.text.index(
            'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
        )
        self.assertLess(existing, sentinel)
        self.assertLess(existing, invocation)
        self.assertIn("blocked 'P79_SENTINEL_PREEXISTING=true'", self.text[existing:])

    def test_cloud_only_wrapper_derivation_stops_after_cloud_result(self) -> None:
        self.assertIn("P79_P2P_WRAPPER_SOURCE=/usr/local/sbin/comelit-p2p-cloud-probe", self.text)
        self.assertIn('RUN="$P79_NATIVE_RUN_DIR"', self.text)
        self.assertIn("=== WAIT SAME NICEAGENT / ICE ===", self.text)
        self.assertIn("P79_CLOUD_ONLY_EXIT_AFTER_REMOTE_SDP=true", self.text)
        self.assertIn("touch \"$RUN/stop\"", self.text)
        for marker in (
            "ICE_CONNECTIVITY_SKIPPED=true",
            "PSEUDOTCP_SKIPPED=true",
            "CTPP_APPLICATION_SIGNALING_SKIPPED=true",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "RAW_SDP_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
        ):
            self.assertIn(marker, self.text)

    def test_cloud_only_wrapper_anchor_failure_is_clean(self) -> None:
        self.assertIn("P79_CLOUD_ONLY_WRAPPER_ANCHOR=FAIL", self.text)
        self.assertIn("if anchor not in text:", self.text)
        self.assertIn("raise SystemExit(3)", self.text)
        self.assertNotIn("text.index('echo \"=== WAIT SAME NICEAGENT / ICE ===\"')", self.text)

    def test_not_reached_success_fallback_precedes_timeout(self) -> None:
        fallback = self.text.split('if [[ "$p2p_result" == "NOT_REACHED" ]]; then', 1)[1]
        success = '[[ "$wrapper_rc" -eq 0 && "$remote_sdp_present" == "true" ]]'
        timeout = '[[ "$wrapper_rc" -eq 124 ]]'
        self.assertIn(success, fallback)
        self.assertIn("p2p_result=SUCCESS", fallback)
        self.assertLess(fallback.index(success), fallback.index(timeout))

    def test_bounded_status_observation_window(self) -> None:
        match = re.search(r"POST_RESULT_OBSERVATION_SECONDS=(\d+)", self.text)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertLessEqual(int(match.group(1)), 30)
        self.assertIn("STATUS_POLL_INTERVAL_SECONDS=5", self.text)
        self.assertIn("seq 1 \"$POST_RESULT_STATUS_SAMPLES\"", self.text)

    def test_terminal_markers_are_parsed_not_unconditional(self) -> None:
        self.assertIn("detail_marker_value() {", self.text)
        self.assertIn("'NOT_REACHED'", self.text)
        for marker in ("P79_P2P_HTTP_STATUS", "P79_P2P_RESULT", "REMOTE_SDP_PRESENT"):
            self.assertIn(f"detail_marker_value '{marker}'", self.text)
        self.assertNotIn("echo 'P79_CLOUD_CONCURRENCY=PROVEN'", self.text)
        self.assertNotIn("echo 'P79_RUN_RESULT=PASS'", self.text)

    def test_process_rc_mapping_has_explicit_exit_per_branch(self) -> None:
        final_block = self.text.split("case \"$process_rc\" in", 1)[1]
        self.assertIn('0) exit 0 ;;', final_block)
        self.assertIn('1) exit 1 ;;', final_block)
        self.assertIn('2) exit 2 ;;', final_block)
        self.assertIn('*) exit 1 ;;', final_block)
        self.assertRegex(final_block, r"esac\s*$")

    def test_no_live_application_or_payload_surfaces(self) -> None:
        lower = self.text.lower()
        forbidden = (
            "action\":\"start",
            "action\":\"stop",
            "action\":\"restart",
            "/run/comelit-p2p\"",
            "raw_sdp_emitted=true",
            "raw_payload_emitted=true",
            "door_action_sent=true",
            "self_activation_sent=true",
            "media_signaling_sent=true",
        )
        for token in forbidden:
            self.assertNotIn(token, lower)

    def test_existing_p78_sentinel_is_never_modified(self) -> None:
        p78_sentinel = ".comelit-" + "p78-live-consumed"
        self.assertNotIn(p78_sentinel, self.text)

    def test_required_markers_exist(self) -> None:
        for marker in (
            "P79_SENTINEL_PREEXISTING",
            "P79_SENTINEL_CONSUMED",
            "P79_LIVE_INVOCATION_LIMIT=1",
            "P79_WRAPPER_INVOCATIONS",
            "AUTOMATIC_RETRY=false",
            "P79_AUTO_RETRY=false",
            "P79_P2P_HTTP_STATUS",
            "P79_P2P_RESULT",
            "REMOTE_SDP_PRESENT",
            "P79_RECONNECT_COUNT_BEFORE",
            "P79_RECONNECT_COUNT_AFTER",
            "P79_LISTENER_READY_BEFORE",
            "P79_LISTENER_READY_AFTER",
            "P79_CLOUD_CONCURRENCY",
            "P79_LISTENER_STABILITY",
            "P79_TIMEOUT_RECONNECT_ASSOCIATION",
            "P79_RUN_RESULT",
            "P79_INSTALLED_WRAPPER_SHA_GATE",
        ):
            self.assertIn(marker, self.text)


if __name__ == "__main__":
    unittest.main()
