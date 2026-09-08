#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "listener" / "v1"))

import p79_cloud_concurrency_classifier as p79


def sample(reconnect_count: int, ready: bool = True) -> dict[str, object]:
    return {
        "supervisor_running": True,
        "running": True,
        "listener_ready": ready,
        "reconnect_count": reconnect_count,
        "last_native_exit_code": 0,
        "last_native_failure_markers": [],
    }


class P79CloudConcurrencyClassifierTests(unittest.TestCase):
    def test_success_unchanged_reconnect_is_proven_and_rc_zero(self) -> None:
        result = p79.classify(
            p2p_result="SUCCESS",
            remote_sdp_present=True,
            listener_samples=[sample(7), sample(7), sample(7)],
        )
        self.assertEqual(result.P79_CLOUD_CONCURRENCY, "PROVEN")
        self.assertEqual(result.P79_LISTENER_STABILITY, "PROVEN")
        self.assertEqual(result.P79_RUN_RESULT, "PASS")
        self.assertEqual(result.process_rc, 0)

    def test_success_reconnect_or_ready_loss_is_partial(self) -> None:
        reconnect = p79.classify(
            p2p_result="SUCCESS",
            remote_sdp_present=True,
            listener_samples=[sample(7), sample(8)],
        )
        ready_loss = p79.classify(
            p2p_result="SUCCESS",
            remote_sdp_present=True,
            listener_samples=[sample(7), sample(7, ready=False)],
        )
        self.assertEqual(reconnect.P79_CLOUD_CONCURRENCY, "PARTIAL")
        self.assertEqual(ready_loss.P79_CLOUD_CONCURRENCY, "PARTIAL")
        self.assertEqual(reconnect.P79_LISTENER_STABILITY, "NOT_PROVEN")
        self.assertEqual(reconnect.P79_RUN_RESULT, "PARTIAL")
        self.assertEqual(reconnect.process_rc, 1)

    def test_timeout_unchanged_reconnect_is_transient_inconclusive(self) -> None:
        result = p79.classify(
            p2p_result="TIMEOUT",
            remote_sdp_present=False,
            listener_samples=[sample(3), sample(3)],
        )
        self.assertEqual(
            result.P79_CLOUD_CONCURRENCY,
            "INCONCLUSIVE_TRANSIENT_TIMEOUT",
        )
        self.assertEqual(result.P79_TIMEOUT_RECONNECT_ASSOCIATION, "NOT_OBSERVED")
        self.assertEqual(result.P79_RUN_RESULT, "INCONCLUSIVE_TRANSIENT_TIMEOUT")
        self.assertEqual(result.process_rc, 1)

    def test_timeout_reconnect_is_association_only(self) -> None:
        result = p79.classify(
            p2p_result="TIMEOUT",
            remote_sdp_present=False,
            listener_samples=[sample(3), sample(4)],
        )
        self.assertEqual(result.P79_CLOUD_CONCURRENCY, "INCONCLUSIVE")
        self.assertEqual(result.P79_TIMEOUT_RECONNECT_ASSOCIATION, "OBSERVED")
        self.assertEqual(result.P79_RUN_RESULT, "INCONCLUSIVE")
        self.assertEqual(result.process_rc, 1)

    def test_unknown_fail_and_blocked_are_nonzero(self) -> None:
        cases = (
            p79.classify(
                p2p_result=None,
                remote_sdp_present=False,
                listener_samples=[sample(1), sample(1)],
                terminal_marker_present=False,
            ),
            p79.classify(
                p2p_result="FAIL",
                remote_sdp_present=False,
                listener_samples=[sample(1), sample(1)],
            ),
            p79.classify(
                p2p_result=None,
                remote_sdp_present=False,
                listener_samples=[],
                preflight_blocked=True,
            ),
        )
        self.assertEqual(cases[0].P79_RUN_RESULT, "UNKNOWN_OUTCOME")
        self.assertEqual(cases[1].P79_RUN_RESULT, "FAIL")
        self.assertEqual(cases[2].P79_RUN_RESULT, "BLOCKED")
        self.assertTrue(all(case.process_rc != 0 for case in cases))
        self.assertEqual(cases[2].process_rc, 2)

    def test_marker_helpers_redact_payload_like_values(self) -> None:
        self.assertEqual(
            p79.marker_line("P79_P2P_RESULT", "SUCCESS"),
            "P79_P2P_RESULT=SUCCESS",
        )
        self.assertEqual(
            p79.marker_line("P79_RAW", "line-one\nline-two"),
            "P79_RAW=<redacted>",
        )
        summary = p79.marker_summary(["P79_P2P_RESULT=SUCCESS"])
        self.assertEqual(summary["P79_NATIVE_MARKER_COUNT"], "1")
        self.assertEqual(len(summary["P79_NATIVE_MARKER_SHA256"]), 64)


if __name__ == "__main__":
    unittest.main()
