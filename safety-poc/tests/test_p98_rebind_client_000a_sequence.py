from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p98_rebind_client_000a_sequence_transform import transform

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P98Client000ASequenceRebindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"))

    def test_p95_ack_sequence_is_saved_as_live_state(self) -> None:
        text = self.candidate
        self.assertIn("static guint32 p98_device_0002_ack_sequence = 0;", text)
        self.assertIn("p98_device_0002_ack_sequence_valid = TRUE;", text)
        self.assertIn("write_le32(body + 2, p98_device_0002_ack_sequence);", text)

    def test_client_000a_generation_uses_latest_p95_ack_sequence(self) -> None:
        text = self.candidate
        self.assertIn(
            "status = p76_generate_client_exchange(\n"
            "        &p78_rtpc_runtime,\n"
            "        p98_device_0002_ack_sequence,\n"
            "        p98_device_0002_ack_sequence,",
            text,
        )
        self.assertNotIn(
            "status = p76_generate_client_exchange(\n"
            "        &p78_rtpc_runtime,\n"
            "        entrance_video_event_sequence,\n"
            "        entrance_video_event_sequence + 0x00010000u,",
            text,
        )
        self.assertIn("P80_CLIENT_000A_SEQUENCE_REBOUND=PASS", text)
        self.assertIn("P80_CLIENT_000A_SEQUENCE_SOURCE=DEVICE_0002_ACK", text)
        self.assertIn("P80_CLIENT_000A_SEQUENCE_EMITTED=false", text)

    def test_p97_post_000a_ack_cycle_remains(self) -> None:
        text = self.candidate
        for marker in (
            "P80_DEVICE_000A_ACK_QUEUED=PASS",
            "P80_DEVICE_000A_ACK_SENT=PASS",
            "P80_DEVICE_ACK_000A_OBSERVED=PASS",
            "P80_CLIENT_001A_SEQUENCE_REBOUND=PASS",
            "P80_DEVICE_ACK_001A_OBSERVED=PASS",
            "P80_POST_001A_ACK_GATE=PASS",
            "P78_RTPC_SIGNALING_RESULT=PASS",
            "P80_MEDIA_ACTIVE=true",
        ):
            self.assertIn(marker, text)

    def test_sequence_chain_is_runtime_derived_not_capture_replay(self) -> None:
        text = self.candidate
        self.assertIn("P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK", text)
        self.assertIn("P97_CLIENT_ACK_000A_SEQUENCE_DELTA 0x01000000u", text)
        self.assertIn("P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u", text)
        for forbidden in (
            "packet_first=204",
            "packet_first=206",
            "packet_first=210",
            "0x13000000",
            "0x13010000",
            "payload.hex()",
            "import socket",
            "import requests",
        ):
            self.assertNotIn(forbidden, text)

    def test_safety_invariants_remain(self) -> None:
        text = self.candidate
        self.assertIn("P78_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", text)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", text)


if __name__ == "__main__":
    unittest.main()
