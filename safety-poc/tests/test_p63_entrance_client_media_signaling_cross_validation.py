#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_client_media_signaling_cross_validation_pcap_forensic import analyze, report
from entrance_device_video_ack_pcap_forensic import VipFrame


class P63CrossValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctpp = 77
        self.role_a = b"ADDRROLEA"
        self.role_b = b"ADDRROLEB"
        self.rtpc1 = b"\x34\x12"
        self.rtpc2 = b"\x78\x56"

    def frame(self, direction: str, packet: int, ts: float, request_id: int, body: bytes) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, request_id, body)

    @staticmethod
    def base_body(length: int, *, prefix: int, sequence: int, action: int, flags: int = 0) -> bytearray:
        data = bytearray(length)
        data[0:2] = prefix.to_bytes(2, "little")
        data[2:6] = sequence.to_bytes(4, "little")
        data[6:8] = action.to_bytes(2, "big")
        if length >= 10:
            data[8:10] = flags.to_bytes(2, "big")
        return data

    def anchor(self) -> VipFrame:
        data = self.base_body(40, prefix=0x1840, sequence=0x11000000, action=0x0008, flags=0x0003)
        data[20:29] = self.role_a
        data[30:39] = self.role_b
        return self.frame("DEVICE_TO_CLIENT", 200, 1.000, self.ctpp, bytes(data))

    def previous_ack(self) -> VipFrame:
        data = self.base_body(32, prefix=0x1800, sequence=0x22000000, action=0x0000)
        return self.frame("CLIENT_TO_DEVICE", 204, 1.220, self.ctpp, bytes(data))

    def control_open(self, ts: float, request_bytes: bytes) -> VipFrame:
        data = bytearray(15)
        data[0:2] = (0xABCD).to_bytes(2, "little")
        data[8:12] = b"RTPC"
        data[12:14] = request_bytes
        return self.frame("CLIENT_TO_DEVICE", 206, ts, 0, bytes(data))

    def c000a(self) -> VipFrame:
        data = self.base_body(44, prefix=0x1840, sequence=0x22000000, action=0x000A, flags=0x0011)
        data[10:16] = bytes((0x18, 0x02, 0, 0, 0, 0))
        data[16:18] = self.rtpc1
        data[18:20] = b"\x00\x00"
        data[20:24] = b"\xff" * 4
        data[24:33] = self.role_b
        data[33] = 0
        data[34:43] = self.role_a
        data[43] = 0
        return self.frame("CLIENT_TO_DEVICE", 206, 1.330, self.ctpp, bytes(data))

    def c001a(self, *, geometry=(800, 480, 320, 240, 16), bad_tag: bool = False) -> VipFrame:
        data = self.base_body(60, prefix=0x1840, sequence=0x22010000, action=0x001A, flags=0x0011)
        data[10:16] = bytes((0x15 if bad_tag else 0x14, 0x32, 0, 0, 0, 0))
        data[16:18] = self.rtpc2
        data[18:24] = b"\xff\xff\x00\x00\x00\x00"
        offset = 24
        for value in geometry:
            data[offset:offset + 2] = value.to_bytes(2, "little")
            offset += 2
        data[34:36] = b"\x00\x00"
        data[36:40] = b"\xff" * 4
        data[40:49] = self.role_b
        data[49] = 0
        data[50:59] = self.role_a
        data[59] = 0
        return self.frame("CLIENT_TO_DEVICE", 212, 1.640, self.ctpp, bytes(data))

    def frames(self, *, geometry=(800, 480, 320, 240, 16), bad_tag: bool = False):
        anchor = self.anchor()
        return anchor, (
            anchor,
            self.previous_ack(),
            self.control_open(1.320, self.rtpc1),
            self.control_open(1.321, self.rtpc2),
            self.c000a(),
            self.c001a(geometry=geometry, bad_tag=bad_tag),
        )

    def test_full_cross_validation_passes(self) -> None:
        anchor, frames = self.frames()
        with patch(
            "entrance_client_media_signaling_cross_validation_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)
        self.assertTrue(result.generation_contract_ok)
        self.assertEqual(result.rtpc_open_count, 2)
        self.assertEqual(result.c000a_rtpc_open_ordinal, 1)
        self.assertEqual(result.c001a_rtpc_open_ordinal, 2)
        self.assertEqual((result.width, result.height, result.secondary_width, result.secondary_height, result.fps), (800, 480, 320, 240, 16))
        text = report(result)
        self.assertIn("LIVE_BODY_GENERATION_CONTRACT=PASS", text)
        self.assertIn("REQUEST_ID_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_wrong_tag_fails_closed(self) -> None:
        anchor, frames = self.frames(bad_tag=True)
        with patch(
            "entrance_client_media_signaling_cross_validation_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)
        self.assertFalse(result.generation_contract_ok)
        self.assertFalse(result.c001a_tag_ok)

    def test_wrong_geometry_fails_closed(self) -> None:
        anchor, frames = self.frames(geometry=(640, 480, 320, 240, 16))
        with patch(
            "entrance_client_media_signaling_cross_validation_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)
        self.assertFalse(result.generation_contract_ok)
        self.assertFalse(result.geometry_reference_match)

    def test_missing_second_rtpc_open_fails_closed(self) -> None:
        anchor, frames = self.frames()
        frames = tuple(frame for frame in frames if not (frame.request_id == 0 and frame.timestamp == 1.321))
        with patch(
            "entrance_client_media_signaling_cross_validation_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames)
        self.assertFalse(result.generation_contract_ok)
        self.assertEqual(result.rtpc_open_count, 1)


if __name__ == "__main__":
    unittest.main()
