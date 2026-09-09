#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p92_wait_device_000a_before_001a_transform import (  # noqa: E402
    DEFAULT_SOURCE,
    transform,
)


class P92WaitDevice000ABefore001ATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source_path = DEFAULT_SOURCE
        if not source_path.exists():
            source_path = ROOT / source_path
        cls.candidate = transform(source_path.read_text(encoding="utf-8"))

    def test_composes_p91_diagnostics_and_prior_lifetime_fixes(self) -> None:
        for marker in (
            "P80_SIGNALING_WATCHDOG_DISARMED=true",
            "P80_V4_LISTENER_TIMEOUT_DISARMED=true",
            "P80_MEDIA_RX_TOTAL=%llu",
            "P80_MEDIA_DIAGNOSTIC_TIMEOUT=true",
        ):
            self.assertIn(marker, self.candidate)

    def test_client_000a_completion_no_longer_unconditionally_sends_001a(self) -> None:
        start = self.candidate.index("case P78_TX_RTPC_CLIENT_000A:")
        block = self.candidate[start : start + 900]
        self.assertIn("p78_rtpc_client_000a_sent = TRUE;", block)
        self.assertIn("if (p92_device_000a_observed)", block)
        self.assertIn("P92_WAIT_DEVICE_000A=true", block)
        unconditional = "fflush(stdout);\n            (void)p78_queue_rtpc_client_001a();"
        self.assertNotIn(unconditional, block)

    def test_gate_is_armed_before_client_000a_is_queued(self) -> None:
        start = self.candidate.index("static gboolean\np83_queue_client_media_after_responses")
        block = self.candidate[start : start + 2600]
        armed = block.index("p92_wait_device_000a = TRUE;")
        timer = block.index(
            "g_timeout_add_seconds(3, p92_device_000a_timeout_cb, NULL);"
        )
        queue = block.index("P78_TX_RTPC_CLIENT_000A" )
        self.assertLess(armed, timer)
        self.assertLess(timer, queue)
        self.assertIn("P92_DEVICE_000A_GATE_ARMED=true", block)

    def test_device_000a_match_is_structural_and_dynamic(self) -> None:
        start = self.candidate.index("p92_device_000a_is_valid")
        block = self.candidate[start : start + 1800]
        self.assertIn("request_id != v4_ctpp_channel_id", block)
        self.assertIn("body_len != 44u", block)
        self.assertIn("body[0] != 0x40u", block)
        self.assertIn("body[1] != 0x18u", block)
        self.assertIn("body[6] != 0x00u", block)
        self.assertIn("body[7] != 0x0au", block)
        self.assertIn(
            "memcmp(body + 10u, p78_rtpc_client_000a + 10u, 8u)", block
        )
        self.assertNotIn("CAPTURE_TARGET_ID", block)

    def test_frame_hook_consumes_valid_device_000a(self) -> None:
        hook = """        } else if (p92_wait_device_000a) {
            if (p92_handle_device_000a(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""
        self.assertIn(hook, self.candidate)
        self.assertIn("P92_DEVICE_000A_OBSERVED=PASS", self.candidate)

    def test_001a_requires_both_observation_and_tx_completion(self) -> None:
        start = self.candidate.index(
            "static gboolean\n"
            "p92_handle_device_000a(guint16 request_id, const guint8 *body, guint body_len)\n"
            "{"
        )
        handler = self.candidate[start : start + 1800]
        self.assertIn("p92_device_000a_observed = TRUE;", handler)
        self.assertIn("if (!p78_rtpc_client_000a_sent)", handler)
        self.assertIn("P92_DEVICE_000A_BEFORE_TX_COMPLETE=true", handler)
        self.assertIn("P92_DEVICE_000A_GATE=PASS", handler)
        self.assertIn("p78_queue_rtpc_client_001a", handler)

    def test_missing_device_000a_fails_closed_after_three_seconds(self) -> None:
        start = self.candidate.index("p92_device_000a_timeout_cb")
        callback = self.candidate[start : start + 1000]
        self.assertIn("if (!p92_wait_device_000a || p92_device_000a_observed)", callback)
        self.assertIn('p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true")', callback)
        self.assertIn("#define P92_DEVICE_000A_TIMEOUT_SECONDS 3", self.candidate)

    def test_safety_invariants_remain_explicit(self) -> None:
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", self.candidate)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", self.candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)


if __name__ == "__main__":
    unittest.main()
