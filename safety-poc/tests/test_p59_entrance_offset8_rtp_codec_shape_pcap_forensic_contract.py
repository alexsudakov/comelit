#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_offset8_rtp_codec_shape_pcap_forensic import (
    _parse_h264_shape,
    analyze,
    report,
)
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import SelectedDatagram
from pseudotcp_pcap_handshake_forensic import Endpoint


def rtp_media(seq: int, timestamp: int, ssrc: int, pt: int, media: bytes, marker: bool = False) -> bytes:
    second = pt | (0x80 if marker else 0)
    return (
        bytes([0x80, second])
        + seq.to_bytes(2, "big")
        + timestamp.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + media
    )


def wrapped(prefix: bytes, *args, **kwargs) -> bytes:
    if len(prefix) != 8:
        raise ValueError("prefix must be eight bytes")
    return prefix + rtp_media(*args, **kwargs)


class P59ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Endpoint(b"\x01\x01\x01\x01", 1000)
        self.device = Endpoint(b"\x02\x02\x02\x02", 2000)
        self.prefix = b"CM01ABCD"

    def dgram(self, packet: int, ts: float, source: Endpoint, target: Endpoint, payload: bytes) -> SelectedDatagram:
        return SelectedDatagram(packet, ts, source, target, payload)

    def test_h264_shape_parser_accepts_single_stap_and_fua(self) -> None:
        single = _parse_h264_shape(b"\x65\xaa\xbb")
        self.assertIsNotNone(single)
        self.assertEqual(single.kind, "SINGLE_NAL")
        self.assertEqual(single.nal_type, 5)

        stap = _parse_h264_shape(b"\x78\x00\x02\x67\xaa\x00\x02\x68\xbb")
        self.assertIsNotNone(stap)
        self.assertEqual(stap.kind, "STAP_A")
        self.assertEqual(stap.stap_nal_count, 2)

        fu_start = _parse_h264_shape(b"\x7c\x85\xaa")
        fu_end = _parse_h264_shape(b"\x7c\x45\xbb")
        self.assertEqual(fu_start.kind, "FU_A")
        self.assertTrue(fu_start.fu_start)
        self.assertFalse(fu_start.fu_end)
        self.assertEqual(fu_start.fu_original_nal_type, 5)
        self.assertEqual(fu_end.kind, "FU_A")
        self.assertFalse(fu_end.fu_start)
        self.assertTrue(fu_end.fu_end)

    def test_codec_inventory_classifies_pt8_and_pt99(self) -> None:
        base = 1000.0
        audio = bytes([0x55]) * 160
        stap = b"\x78\x00\x02\x67\xaa\x00\x02\x68\xbb"
        datagrams = (
            self.dgram(218, base, self.device, self.client, b"boundary"),
            self.dgram(219, base + 0.020, self.device, self.client, wrapped(self.prefix, 1, 160, 1, 8, audio)),
            self.dgram(220, base + 0.040, self.client, self.device, wrapped(self.prefix, 2, 320, 2, 8, audio)),
            self.dgram(221, base + 0.041, self.device, self.client, wrapped(self.prefix, 10, 90000, 3, 99, b"\x65\xaa")),
            self.dgram(222, base + 0.042, self.device, self.client, wrapped(self.prefix, 11, 90000, 3, 99, stap)),
            self.dgram(223, base + 0.043, self.device, self.client, wrapped(self.prefix, 12, 90000, 3, 99, b"\x7c\x85\xaa")),
            self.dgram(224, base + 0.044, self.device, self.client, wrapped(self.prefix, 13, 90000, 3, 99, b"\x7c\x05\xbb")),
            self.dgram(225, base + 0.045, self.device, self.client, wrapped(self.prefix, 14, 90000, 3, 99, b"\x7c\x45\xcc", True)),
            self.dgram(226, base + 0.046, self.client, self.device, b"opaque-residual"),
        )

        result = analyze(datagrams, client=self.client, device=self.device)
        self.assertEqual(result.opaque_count, 8)
        self.assertEqual(result.offset8_rtp_count, 7)
        self.assertEqual(result.residual_count, 1)
        self.assertEqual(result.pt8_packet_count, 2)
        self.assertEqual(result.pt99_packet_count, 5)
        self.assertEqual(result.pt99_h264_shaped_count, 5)
        self.assertEqual(result.pt99_h264_unrecognized_count, 0)
        self.assertEqual(len(result.streams), 3)

        video = next(stream for stream in result.streams if stream.payload_type == 99)
        self.assertEqual(video.codec_class, "H264_RTP_PACKETIZATION_SHAPED")
        self.assertEqual(video.h264_single_nal_count, 1)
        self.assertEqual(video.h264_stap_a_count, 1)
        self.assertEqual(video.h264_fu_a_count, 3)
        self.assertEqual(video.h264_fu_start_count, 1)
        self.assertEqual(video.h264_fu_end_count, 1)
        self.assertEqual(video.h264_stap_total_inner_nals, 2)
        self.assertIn((5, 1), video.h264_single_nal_types)
        self.assertIn((5, 3), video.h264_fu_original_nal_types)

    def test_report_is_codec_metadata_only(self) -> None:
        base = 1000.0
        datagrams = (
            self.dgram(218, base, self.device, self.client, b"boundary"),
            self.dgram(219, base + 0.020, self.device, self.client, wrapped(self.prefix, 1, 160, 1, 8, bytes([0x55]) * 160)),
            self.dgram(220, base + 0.040, self.device, self.client, wrapped(self.prefix, 2, 90000, 3, 99, b"\x65\xaa")),
        )
        text = report(analyze(datagrams, client=self.client, device=self.device))
        self.assertIn("PT8_STATIC_RTP_AVP_MAPPING=PCMA_8000_MONO", text)
        self.assertIn("PT99_ALL_PACKETS_H264_SHAPED=true", text)
        self.assertIn("CODEC_IDENTIFICATION_PERFORMED=true", text)
        self.assertIn("H264_PACKETIZATION_INSPECTION_PERFORMED=true", text)
        self.assertIn("VIDEO_FRAMES_DECODED=false", text)
        self.assertIn("MEDIA_FILES_WRITTEN=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("CM01ABCD", text)

    def test_invalid_h264_shapes_are_rejected(self) -> None:
        self.assertIsNone(_parse_h264_shape(b""))
        self.assertIsNone(_parse_h264_shape(b"\x7c\x80"))
        self.assertIsNone(_parse_h264_shape(b"\x78\x00\x10\x67"))
        self.assertIsNone(_parse_h264_shape(b"\x79\x00"))

    def test_boundary_is_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            analyze((), client=self.client, device=self.device)


if __name__ == "__main__":
    unittest.main()
