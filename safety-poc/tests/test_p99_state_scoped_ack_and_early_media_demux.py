#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p99_state_scoped_ack_and_early_media_demux_transform import transform


SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P99StateScopedAckAndEarlyMediaDemuxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"))

    def test_ack_binding_is_state_scoped_and_structural(self) -> None:
        text = self.candidate
        self.assertIn("p99_state_scoped_structural_ack", text)
        self.assertIn("request_id != v4_ctpp_channel_id", text)
        self.assertIn("body_len != 32u", text)
        self.assertIn("read_le16(body + 0u) == 0x1800u", text)
        self.assertIn("P80_DEVICE_ACK_000A_BINDING=STATE_SCOPED_STRUCTURAL", text)
        self.assertIn("P80_DEVICE_ACK_001A_BINDING=STATE_SCOPED_STRUCTURAL", text)
        self.assertIn("P80_DEVICE_ACK_000A_TAIL_RELATION=%s", text)
        self.assertIn("P80_DEVICE_ACK_001A_TAIL_RELATION=%s", text)

    def test_early_media_is_demuxed_but_not_forwarded(self) -> None:
        text = self.candidate
        self.assertIn("p99_preactive_media_demux_armed = TRUE", text)
        self.assertIn("P80_PREACTIVE_MEDIA_DEMUX_ARMED=true", text)
        self.assertIn("P80_PREACTIVE_MEDIA_DEMUX=PASS", text)
        self.assertIn("P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=%u", text)
        self.assertIn("P80_PREACTIVE_MEDIA_PAYLOAD_EMITTED=false", text)
        self.assertIn("if (!p99_active_forward)", text)
        self.assertIn("return TRUE;", text)
        self.assertIn("P80_VIDEO_RTP_FORWARDING=PASS", text)
        self.assertIn("P80_AUDIO_RTP_FORWARDING=PASS", text)

    def test_existing_post_ack_and_safety_contracts_remain(self) -> None:
        text = self.candidate
        for marker in (
            "P80_CLIENT_000A_SEQUENCE_REBOUND=PASS",
            "P80_DEVICE_000A_VALIDATION=PASS",
            "P80_DEVICE_ACK_000A_OBSERVED=PASS",
            "P80_CLIENT_001A_SEQUENCE_REBOUND=PASS",
            "P80_DEVICE_ACK_001A_OBSERVED=PASS",
            "P80_POST_001A_ACK_GATE=PASS",
            "P78_RTPC_SIGNALING_RESULT=PASS",
            "P80_MEDIA_ACTIVE=true",
            "P80_DOOR_SIGNAL_ENTRYPOINT=false",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", text)


if __name__ == "__main__":
    unittest.main()
