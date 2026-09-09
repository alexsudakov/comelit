#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p91_media_rx_stage_diagnostics_transform import transform  # noqa: E402


class P91MediaRxStageDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from entrance_p88_disarm_v4_listener_timeout_transform import DEFAULT_SOURCE

        cls.candidate = transform(DEFAULT_SOURCE.read_text(encoding="utf-8"))

    def test_composes_p88_lifetime_and_signaling_fixes(self) -> None:
        self.assertIn("P80_SIGNALING_WATCHDOG_DISARMED=true", self.candidate)
        self.assertIn("P80_V4_LISTENER_TIMEOUT_DISARMED=true", self.candidate)
        self.assertNotIn(
            "g_timeout_add_seconds(\n        45,\n        absolute_timeout_cb,",
            self.candidate,
        )

    def test_receive_classifier_counts_each_stage_without_payload_output(self) -> None:
        self.assertIn("p91_media_rx_total++;", self.candidate)
        self.assertIn("p91_media_wrapper_len_match++;", self.candidate)
        self.assertIn("p91_media_inner_rtp_v2++;", self.candidate)
        self.assertIn("p91_media_pt99++;", self.candidate)
        self.assertIn("p91_media_pt8++;", self.candidate)
        for forbidden in (
            'printf("%02x',
            'fprintf(stderr, "%02x',
            "RAW_PAYLOAD=",
            "MEDIA_PAYLOAD=",
        ):
            self.assertNotIn(forbidden, self.candidate)

    def test_diagnostic_timeout_is_armed_only_after_media_active_gate(self) -> None:
        start = self.candidate.index("static gboolean\nentrance_signal_begin_media_observation")
        method = self.candidate[start : start + 2200]
        self.assertIn("p78_rtpc_stage != P78_RTPC_COMPLETE", method)
        enabled = method.index("p80_media_forwarding_enabled = TRUE;")
        timer = method.index(
            "g_timeout_add_seconds(10, p91_media_rx_diagnostic_timeout_cb, NULL);"
        )
        active = method.index('printf("P80_MEDIA_ACTIVE=true\\n");')
        self.assertLess(enabled, timer)
        self.assertLess(timer, active)

    def test_timeout_does_not_interrupt_if_forwarding_started(self) -> None:
        start = self.candidate.index("p91_media_rx_diagnostic_timeout_cb")
        callback = self.candidate[start : start + 1800]
        self.assertIn(
            "if (p80_video_rtp_packets > 0 || p80_audio_rtp_packets > 0)",
            callback,
        )
        self.assertIn("P80_MEDIA_DIAGNOSTIC_FORWARDING_ALREADY=true", callback)
        success = callback.index("P80_MEDIA_DIAGNOSTIC_FORWARDING_ALREADY=true")
        fail = callback.index("failed = TRUE;")
        self.assertLess(success, fail)

    def test_no_forwarding_emits_only_safe_numeric_stage_counts_then_fails_closed(self) -> None:
        for marker in (
            "P80_MEDIA_RX_TOTAL=%llu",
            "P80_MEDIA_WRAPPER_LEN_MATCH=%llu",
            "P80_MEDIA_INNER_RTP_V2=%llu",
            "P80_MEDIA_PT99=%llu",
            "P80_MEDIA_PT8=%llu",
            "P80_MEDIA_DIAGNOSTIC_TIMEOUT=true",
        ):
            self.assertIn(marker, self.candidate)
        self.assertIn("failed = TRUE;", self.candidate)
        self.assertIn("g_main_loop_quit(loop);", self.candidate)

    def test_safety_invariants_remain_explicit(self) -> None:
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", self.candidate)
        self.assertIn("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", self.candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)


if __name__ == "__main__":
    unittest.main()
