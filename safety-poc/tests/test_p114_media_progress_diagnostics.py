#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "custom_components" / "comelit" / "media_diagnostics.py"

spec = importlib.util.spec_from_file_location("comelit_media_diagnostics", MODULE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
MediaProgressDiagnostics = module.MediaProgressDiagnostics


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class P114MediaProgressDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.progress = MediaProgressDiagnostics(clock=self.clock)

    def test_valid_markers_advance_independent_monotonic_counters(self) -> None:
        self.assertTrue(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=1"))
        self.assertEqual(self.progress.video_packet_count, 1)
        self.assertEqual(self.progress.last_video_progress_monotonic, 100.0)

        self.clock.now = 101.0
        self.assertTrue(self.progress.update_marker("P80_AUDIO_RTP_PACKETS=50"))
        self.assertEqual(self.progress.audio_packet_count, 50)
        self.assertEqual(self.progress.last_audio_progress_monotonic, 101.0)

        self.clock.now = 102.0
        self.assertTrue(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=50"))
        self.assertEqual(self.progress.video_packet_count, 50)
        self.assertEqual(self.progress.last_video_progress_monotonic, 102.0)

    def test_guint64_maximum_is_accepted(self) -> None:
        maximum = (1 << 64) - 1
        self.assertTrue(
            self.progress.update_marker(f"P80_VIDEO_RTP_PACKETS={maximum}")
        )
        self.assertEqual(self.progress.video_packet_count, maximum)

    def test_repeat_or_regression_does_not_refresh_last_progress(self) -> None:
        self.assertTrue(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=50"))
        self.clock.now = 110.0
        self.assertFalse(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=50"))
        self.assertFalse(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=49"))
        self.assertEqual(self.progress.video_packet_count, 50)
        self.assertEqual(self.progress.last_video_progress_monotonic, 100.0)
        self.assertEqual(self.progress.video_last_packet_age_seconds, 10.0)

    def test_malformed_or_unsafe_markers_are_ignored(self) -> None:
        for marker in (
            "P80_VIDEO_RTP_PACKETS=-1",
            "P80_VIDEO_RTP_PACKETS=18446744073709551616",
            "P80_VIDEO_RTP_PACKETS=1 secret",
            "P80_VIDEO_RTP_PACKETS=1=2",
            "P80_VIDEO_RTP_PACKETS=",
            "P80_GATE_RTP_PACKETS=50",
            "P80_AUDIO_RTP_PACKETS=PASS",
            "TOKEN=123",
        ):
            with self.subTest(marker=marker):
                self.assertFalse(self.progress.update_marker(marker))
        self.assertEqual(self.progress.video_packet_count, 0)
        self.assertEqual(self.progress.audio_packet_count, 0)

    def test_ages_use_monotonic_clock_and_never_go_negative(self) -> None:
        self.assertIsNone(self.progress.video_last_packet_age_seconds)
        self.assertTrue(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=1"))
        self.clock.now = 104.25
        self.assertEqual(self.progress.video_last_packet_age_seconds, 4.25)
        self.clock.now = 99.0
        self.assertEqual(self.progress.video_last_packet_age_seconds, 0.0)

    def test_reset_starts_a_new_media_cycle(self) -> None:
        self.assertTrue(self.progress.update_marker("P80_VIDEO_RTP_PACKETS=50"))
        self.assertTrue(self.progress.update_marker("P80_AUDIO_RTP_PACKETS=50"))
        self.progress.reset()
        self.assertEqual(self.progress.video_packet_count, 0)
        self.assertEqual(self.progress.audio_packet_count, 0)
        self.assertIsNone(self.progress.last_video_progress_monotonic)
        self.assertIsNone(self.progress.last_audio_progress_monotonic)
        self.assertIsNone(self.progress.video_last_packet_age_seconds)
        self.assertIsNone(self.progress.audio_last_packet_age_seconds)


if __name__ == "__main__":
    unittest.main()
