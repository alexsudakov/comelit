#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"
HELPER_TRANSFORM = (
    ROOT
    / "safety-poc"
    / "research"
    / "media"
    / "v1"
    / "entrance_p80_ha_media_runtime_transform.py"
)
BINARY = ROOT / "custom_components" / "comelit" / "native" / "comelit-media"


class P116HandoffAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport = TRANSPORT.read_text(encoding="utf-8")
        cls.helper = HELPER_TRANSFORM.read_text(encoding="utf-8")
        cls.binary = BINARY.read_bytes()

    def test_local_sdp_shape_is_static_loopback_recvonly_without_ssrc(self) -> None:
        for expected in (
            'c=IN IP4 127.0.0.1\\r',
            'm=video {MEDIA_VIDEO_HA_RTP_PORT} RTP/AVP 99\\r',
            'a=rtpmap:99 H264/90000\\r',
            'a=fmtp:99 packetization-mode=1\\r',
            'a=recvonly\\r',
            'm=audio {MEDIA_AUDIO_RTP_PORT} RTP/AVP 8\\r',
            'a=rtpmap:8 PCMA/8000/1\\r',
            '_LOCAL_RTP_SDP.encode("ascii")',
        ):
            self.assertIn(expected, self.transport)
        self.assertNotIn("a=ssrc:", self.transport)

    def test_helper_forwards_matching_pt_to_matching_loopback_ports(self) -> None:
        for expected in (
            "VIDEO_RTP_PORT = 17899",
            "AUDIO_RTP_PORT = 17808",
            "#define P80_VIDEO_RTP_PORT {VIDEO_RTP_PORT}",
            "#define P80_AUDIO_RTP_PORT {AUDIO_RTP_PORT}",
            "target->sin_port = htons(port);",
            "target->sin_addr.s_addr = htonl(INADDR_LOOPBACK);",
            "payload_type != 99u && payload_type != 8u",
            "payload_type == 99u ? &p80_video_rtp_fd : &p80_audio_rtp_fd",
            "payload_type == 99u\n        ? P80_VIDEO_RTP_PORT : P80_AUDIO_RTP_PORT",
            "ssize_t sent = sendto(",
        ):
            self.assertIn(expected, self.helper)

    def test_installed_binary_contains_local_sink_marker_strings(self) -> None:
        for marker in (
            b"P80_VIDEO_RTP_PORT=%u",
            b"P80_AUDIO_RTP_PORT=%u",
            b"P80_VIDEO_RTP_FORWARDING=PASS",
            b"P80_AUDIO_RTP_FORWARDING=PASS",
            b"P80_MEDIA_ACTIVE=true",
            b"P116_%s_PT_SET=",
        ):
            self.assertIn(marker, self.binary)


if __name__ == "__main__":
    unittest.main()
