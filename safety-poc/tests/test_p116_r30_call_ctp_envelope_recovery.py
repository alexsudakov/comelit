from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
P76_SOURCE = MEDIA / "entrance_rtpc_control_media_runtime_transform.py"
R29C_SOURCE = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"

sys.path.insert(0, str(MEDIA))
from entrance_p116_r30_call_ctp_envelope_model import (
    FLAG_SYN,
    OP_INVITE,
    OP_MEDIA_REQUEST,
    build_call_bound_media_packet,
    build_ctp_envelope,
    is_inbound_invite,
    parse_ctp_envelope,
)


class P116R30CallCtpEnvelopeRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.door_source = DOOR_SOURCE.read_text(encoding="utf-8")
        cls.p76_source = P76_SOURCE.read_text(encoding="utf-8")
        cls.r29c_source = R29C_SOURCE.read_text(encoding="utf-8")

    def test_inbound_invite_exposes_call_connection_inside_ctpp_payload(self) -> None:
        invite = (
            struct.pack(">H", OP_INVITE)
            + b"ENTRANCE\x00\x00"
            + b"CLIENT\x00\x00\x00\x00"
            + b"\x01\x20"
            + b"CALL"
            + b"ENTRANCE\x00\x00"
            + b"PP"
        )
        self.assertEqual(len(invite), 40)
        packet = build_ctp_envelope(
            flags=FLAG_SYN,
            connection=b"\x12\x34",
            sequence=0x56,
            acknowledgement=0x78,
            inner_body=invite,
            source_raw=b"ENTRANCE\x00\x00",
            destination_raw=b"CLIENT\x00\x00\x00\x00",
        )
        parsed = parse_ctp_envelope(packet)
        self.assertTrue(is_inbound_invite(parsed))
        self.assertEqual(parsed.connection, b"\x12\x34")
        self.assertEqual(parsed.peer_connection, b"\x92\x34")
        self.assertEqual(parsed.sequence, 0x56)
        self.assertEqual(parsed.acknowledgement, 0x78)
        self.assertEqual(parsed.opcode, OP_INVITE)
        self.assertEqual(parsed.inner_body[24:28], b"CALL")

    def test_call_id_and_ctp_connection_are_distinct_fields(self) -> None:
        invite = bytearray(40)
        struct.pack_into(">H", invite, 0, OP_INVITE)
        invite[24:28] = b"ABCD"
        packet = build_ctp_envelope(
            flags=FLAG_SYN,
            connection=b"\x01\x02",
            sequence=3,
            acknowledgement=4,
            inner_body=bytes(invite),
            source_raw=b"SRC\x00\x00\x00\x00\x00\x00\x00",
            destination_raw=b"DST\x00\x00\x00\x00\x00\x00\x00",
        )
        parsed = parse_ctp_envelope(packet)
        self.assertEqual(parsed.connection, b"\x01\x02")
        self.assertEqual(parsed.inner_body[24:28], b"ABCD")
        self.assertNotEqual(parsed.connection, parsed.inner_body[24:26])

    def test_current_ring_parser_is_reading_ctp_header_fields(self) -> None:
        self.assertIn("read_le16(\n                    body + 0", self.door_source)
        self.assertIn("((guint16)body[6]) <<", self.door_source)
        self.assertIn("((guint16)body[7])", self.door_source)
        self.assertIn("prefix ==\n                    0x18C0", self.door_source)
        self.assertIn("action ==\n                    0x0028", self.door_source)
        # 0x18C0 is bytes C0 18: CTP SYN + version 0x18.
        self.assertEqual(bytes((0xC0, 0x18)), struct.pack("<H", 0x18C0))
        # 0x0028 is the big-endian inner body length 40.
        self.assertEqual(struct.pack(">H", 40), b"\x00\x28")

    def test_p76_client_001a_is_a_full_60_byte_ctp_media_packet(self) -> None:
        for marker in (
            "p76_write_le16(out + 0, 0x1840u);",
            "p76_write_be16(out + 6, 0x001au);",
            "p76_write_be16(out + 8, 0x0011u);",
            "out[10] = 0x14; out[11] = 0x32;",
            "out[36] = 0xff; out[37] = 0xff; out[38] = 0xff; out[39] = 0xff;",
            "return 60u;",
        ):
            self.assertIn(marker, self.p76_source)

    def test_26_byte_mediareq_requires_60_byte_ctp_envelope(self) -> None:
        mediareq = bytearray(26)
        struct.pack_into(">H", mediareq, 0, OP_MEDIA_REQUEST)
        mediareq[2] = 0x14
        mediareq[3] = 0x32
        packet = build_call_bound_media_packet(
            local_connection=b"\x92\x34",
            sequence=0x11,
            acknowledgement=0x57,
            mediareq26=bytes(mediareq),
            source_raw=b"CLIENT\x00\x00\x00\x00",
            destination_raw=b"ENTRANCE\x00\x00",
        )
        self.assertEqual(len(packet), 60)
        parsed = parse_ctp_envelope(packet)
        self.assertEqual(parsed.opcode, OP_MEDIA_REQUEST)
        self.assertEqual(len(parsed.inner_body), 26)
        self.assertEqual(parsed.connection, b"\x92\x34")

    def test_r29c_live_hypothesis_sent_inner_mediareq_without_ctp_envelope(self) -> None:
        self.assertIn(
            "p12_queue_vip_frame(v4_ctpp_channel_id, body, 26u, kind)",
            self.r29c_source,
        )

    def test_no_network_or_live_behavior_in_model(self) -> None:
        model = (MEDIA / "entrance_p116_r30_call_ctp_envelope_model.py").read_text(encoding="utf-8")
        for forbidden in ("socket.", "curl ", "R29C_LIVE_AUTHORIZED=authorized", "LIVE_RUN=YES"):
            self.assertNotIn(forbidden, model)


if __name__ == "__main__":
    unittest.main()
