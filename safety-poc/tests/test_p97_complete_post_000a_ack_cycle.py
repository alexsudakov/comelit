from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p97_complete_post_000a_ack_cycle_transform import transform

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P97Post000AAckCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"))

    def test_restores_full_capture_order_before_media_active(self) -> None:
        text = self.candidate
        for marker in (
            "P80_DEVICE_000A_ACK_QUEUED=PASS",
            "P80_DEVICE_000A_ACK_SENT=PASS",
            "P80_DEVICE_ACK_000A_OBSERVED=PASS",
            "P80_CLIENT_001A_SEQUENCE_REBOUND=PASS",
            "P78_RTPC_CLIENT_001A_SENT=PASS",
            "P80_DEVICE_ACK_001A_OBSERVED=PASS",
            "P80_POST_001A_ACK_GATE=PASS",
            "P78_RTPC_SIGNALING_RESULT=PASS",
            "P80_MEDIA_ACTIVE=true",
        ):
            self.assertIn(marker, text)

        self.assertLess(text.index("P80_DEVICE_000A_ACK_SENT=PASS"), text.index("P80_WAIT_DEVICE_ACK_000A=true"))
        self.assertIn("return p78_queue_rtpc_client_001a();", text)
        self.assertIn("p97_finish_after_device_ack_001a", text)

    def test_001a_sequence_is_rebound_from_client_ack(self) -> None:
        text = self.candidate
        self.assertIn("P97_CLIENT_ACK_000A_SEQUENCE_DELTA 0x01000000u", text)
        self.assertIn("P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u", text)
        self.assertIn("read_le32(p78_rtpc_client_000a + 2u)", text)
        self.assertIn("write_le32(\n        p78_rtpc_client_001a + 2u", text)
        self.assertIn("p97_client_ack_000a_sequence +", text)

    def test_old_early_media_completion_is_removed(self) -> None:
        old = '''        case P78_TX_RTPC_CLIENT_001A:\n            p78_rtpc_client_001a_sent = TRUE;\n            p78_rtpc_stage = P78_RTPC_COMPLETE;\n            printf("P78_RTPC_CLIENT_001A_SENT=PASS\\n");\n            printf("P78_RTPC_SIGNALING_RESULT=PASS\\n");'''
        self.assertNotIn(old, self.candidate)
        self.assertEqual(self.candidate.count('printf("P78_RTPC_SIGNALING_RESULT=PASS\\n");'), 1)

    def test_ack_binding_is_structural_and_live_role_based(self) -> None:
        text = self.candidate
        self.assertIn("read_le16(body + 0u) != 0x1800u", text)
        self.assertIn("memcmp(body + 12u, source + second, 9u) == 0", text)
        self.assertIn("memcmp(body + 22u, source + first, 9u) == 0", text)
        self.assertIn("memcpy(p97_device_000a_first_role, body + 24u, 9u)", text)
        self.assertIn("memcpy(p97_device_000a_second_role, body + 34u, 9u)", text)

    def test_existing_safety_and_p95_p96_fixes_remain(self) -> None:
        text = self.candidate
        self.assertIn("P80_DEVICE_0002_GATE=PASS", text)
        self.assertIn("P80_DEVICE_000A_PEER_TARGET_MATCH=PASS", text)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", text)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", text)

    def test_no_capture_values_or_payload_logging_added(self) -> None:
        text = self.candidate
        for forbidden in (
            "packet_first=210",
            "packet_first=211",
            "packet_first=218",
            "0x13000000",
            "0x13010000",
            "print(frame.body",
            "payload.hex()",
            "import socket",
            "import requests",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
