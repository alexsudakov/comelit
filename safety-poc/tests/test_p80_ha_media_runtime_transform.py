#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p80_ha_media_runtime_transform as p80

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P80HaMediaRuntimeTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = p80.transform(SOURCE.read_text(encoding="utf-8"))

    def test_uses_separate_media_run_directory(self) -> None:
        self.assertIn('#define RUN_DIR     "/run/comelit-media"', self.candidate)
        self.assertNotIn('#define RUN_DIR     "/run/comelit-p2p"', self.candidate)
        self.assertIn('printf("P80_RUN_DIR=/run/comelit-media\\n")', self.candidate)

    def test_door_signal_entrypoint_is_disabled(self) -> None:
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false", self.candidate)
        self.assertIn('printf("P80_DOOR_SIGNAL_ENTRYPOINT=false\\n")', self.candidate)

    def test_p78_three_second_media_autoclose_is_not_started(self) -> None:
        self.assertNotIn(
            "g_timeout_add(\n            ENTRANCE_MEDIA_OBSERVE_MS,\n            entrance_media_observation_finish_cb",
            self.candidate,
        )
        self.assertIn('printf("P80_MEDIA_AUTO_CLOSE_3000MS=false\\n")', self.candidate)
        self.assertIn('printf("P80_MEDIA_ACTIVE=true\\n")', self.candidate)

    def test_observation_discard_path_is_removed(self) -> None:
        self.assertNotIn("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d", self.candidate)
        self.assertNotIn("memset(buf, 0, (gsize)n);\n                fflush(stdout);\n                continue;", self.candidate)

    def test_wrapped_rtp_is_intercepted_before_pseudotcp(self) -> None:
        intercept = self.candidate.index("p80_try_forward_wrapped_rtp")
        notify = self.candidate.index("pseudo_tcp_socket_notify_packet", intercept)
        self.assertLess(intercept, notify)
        self.assertIn("inner_len + 8u != len", self.candidate)
        self.assertIn("(packet[0] >> 6) != 2", self.candidate)
        self.assertIn("payload_type != 99u && payload_type != 8u", self.candidate)

    def test_only_loopback_rtp_targets_are_generated(self) -> None:
        self.assertIn("INADDR_LOOPBACK", self.candidate)
        self.assertIn("P80_VIDEO_RTP_PORT 17899", self.candidate)
        self.assertIn("P80_AUDIO_RTP_PORT 17808", self.candidate)
        self.assertIn("P80_VIDEO_RTP_FORWARDING=PASS", self.candidate)
        self.assertIn("P80_AUDIO_RTP_FORWARDING=PASS", self.candidate)

    def test_rtp_progress_markers_are_numeric_and_bounded(self) -> None:
        self.assertIn("#define P80_RTP_PROGRESS_CADENCE 50u", self.candidate)
        self.assertIn("P80_VIDEO_RTP_PACKETS=%", self.candidate)
        self.assertIn("P80_AUDIO_RTP_PACKETS=%", self.candidate)
        self.assertIn("p80_video_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u", self.candidate)
        self.assertIn("p80_audio_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u", self.candidate)
        self.assertNotIn("P80_VIDEO_RTP_PACKETS=%s", self.candidate)
        self.assertNotIn("P80_AUDIO_RTP_PACKETS=%s", self.candidate)

    def test_wrapper_profile_is_frozen_per_media_payload_type(self) -> None:
        self.assertIn("p80_video_profile_seen", self.candidate)
        self.assertIn("p80_audio_profile_seen", self.candidate)
        self.assertIn("P80_WRAPPER_PROFILE_MISMATCH=true", self.candidate)
        self.assertIn("memcmp(expected, profile, sizeof(profile)) == 0", self.candidate)

    def test_p78_signaling_safety_invariants_are_preserved(self) -> None:
        self.assertIn("P78_CTPP_REGISTERED_REUSED=true", self.candidate)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("P78_RTPC_SIGNALING_RESULT=PASS", self.candidate)
        self.assertNotIn("P80_DOOR_ACTION_SENT=true", self.candidate)

    def test_report_is_offline_only(self) -> None:
        text = p80.report()
        self.assertIn("P80_RTP_OUTPUT_SCOPE=LOOPBACK_ONLY", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)
        self.assertIn("DOOR_ACTION_SENT=false", text)


if __name__ == "__main__":
    unittest.main()
