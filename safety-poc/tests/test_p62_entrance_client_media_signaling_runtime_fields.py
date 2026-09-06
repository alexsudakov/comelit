#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_client_media_signaling_runtime_fields_pcap_forensic import analyze, report
from entrance_device_video_ack_pcap_forensic import VipFrame


def make_body(length: int, *, sequence: int, action: int, flags: int) -> bytearray:
    body = bytearray(length)
    body[0:2] = (0x1840).to_bytes(2, "little")
    body[2:6] = sequence.to_bytes(4, "little")
    body[6:8] = action.to_bytes(2, "big")
    body[8:10] = flags.to_bytes(2, "big")
    return body


class P62RuntimeFieldTests(unittest.TestCase):
    def frame(self, direction: str, packet: int, ts: float, request_id: int, body: bytes) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, request_id, body)

    def fixture(self, *, resolve: bool = True):
        ctpp_id = 0x1234
        cspb_id = 0x5678
        role_a = b"00000643\x00"
        role_b = b"000401177"

        anchor_body = make_body(40, sequence=1, action=0x0008, flags=0x0003)
        anchor_body[20:29] = role_a
        anchor_body[30:39] = role_b
        anchor = self.frame("DEVICE_TO_CLIENT", 200, 1.000, ctpp_id, bytes(anchor_body))

        cspb = self.frame("CLIENT_TO_DEVICE", 180, 0.800, cspb_id, b"\x00\x00OPEN-CSPB-CHANNEL")

        c000a = make_body(44, sequence=2, action=0x000A, flags=0x0011)
        d000a = make_body(44, sequence=3, action=0x000A, flags=0x0011)
        c001a = make_body(60, sequence=4, action=0x001A, flags=0x0011)

        if resolve:
            c000a[10:12] = cspb_id.to_bytes(2, "little")
            d000a[10:12] = cspb_id.to_bytes(2, "little")
            c001a[10:12] = ctpp_id.to_bytes(2, "little")
            c001a[24:33] = role_b[:8] + b"\x00"
        else:
            c000a[10:12] = b"\xaa\xbb"
            d000a[10:12] = b"\xaa\xbb"
            c001a[10:12] = b"\xcc\xdd"
            c001a[24:33] = b"UNKNFIELD"

        frames = (
            cspb,
            anchor,
            self.frame("CLIENT_TO_DEVICE", 206, 1.300, ctpp_id, bytes(c000a)),
            self.frame("DEVICE_TO_CLIENT", 209, 1.500, ctpp_id, bytes(d000a)),
            self.frame("CLIENT_TO_DEVICE", 212, 1.600, ctpp_id, bytes(c001a)),
        )
        return anchor, frames

    def test_runtime_relations_resolve_all_target_fields(self) -> None:
        anchor, frames = self.fixture(resolve=True)
        with patch(
            "entrance_client_media_signaling_runtime_fields_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)

        relations = {item.label: item.relation for item in result.relations}
        self.assertEqual(relations["CLIENT_000A_10_11"], "CSPB_REQUEST_ID_LOW16_LE")
        self.assertEqual(relations["CLIENT_001A_10_11"], "CTPP_REQUEST_ID_LOW16_LE")
        self.assertEqual(
            relations["CLIENT_001A_24_32"],
            "APARTMENT_ADDRESS_FROM_FULL_ROLE_B",
        )
        self.assertTrue(result.c000a_mirrors_device_000a)
        self.assertEqual(result.unresolved_labels, ())

        text = report(result)
        self.assertIn("LIVE_BODY_GENERATION_CONTRACT=PASS", text)
        self.assertIn("REQUEST_ID_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertNotIn("4660", text)
        self.assertNotIn("22136", text)

    def test_unknown_fields_fail_closed(self) -> None:
        anchor, frames = self.fixture(resolve=False)
        with patch(
            "entrance_client_media_signaling_runtime_fields_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)

        self.assertEqual(len(result.unresolved_labels), 3)
        self.assertIn("LIVE_BODY_GENERATION_CONTRACT=NOT_PROVEN", report(result))


if __name__ == "__main__":
    unittest.main()
