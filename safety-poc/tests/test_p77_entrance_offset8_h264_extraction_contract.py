#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p77_offset8_h264_extraction_contract as p77


def rtp(seq: int, ts: int, ssrc: int, pt: int, media: bytes, marker: bool = False) -> bytes:
    return (
        bytes([0x80, pt | (0x80 if marker else 0)])
        + seq.to_bytes(2, "big")
        + ts.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + media
    )


def wrapped(inner: bytes, *, profile: bytes = b"\x01\x02\x10\x20\x30\x40\x50\x60") -> bytes:
    if len(profile) != 8:
        raise ValueError("profile must be eight bytes")
    prefix = bytearray(profile)
    prefix[2:4] = len(inner).to_bytes(2, "little")
    return bytes(prefix) + inner


def packet(number: int, seq: int, ts: int, media: bytes, marker: bool = False) -> p77.WrappedRtpPacket:
    return p77.parse_wrapped_rtp(
        wrapped(rtp(seq, ts, 0xAABBCCDD, 99, media, marker)),
        packet_number=number,
        direction="DEVICE_TO_CLIENT",
    )


class P77H264ExtractionContractTests(unittest.TestCase):
    def test_single_nal_stap_a_and_fu_a_are_reconstructed_to_annexb(self) -> None:
        packets = (
            packet(1, 1, 90000, b"\x67\x11", False),
            packet(2, 2, 90000, b"\x78\x00\x02\x68\x22\x00\x02\x65\x33", True),
            packet(3, 3, 93000, b"\x7c\x85\xaa", False),
            packet(4, 4, 93000, b"\x7c\x05\xbb", False),
            packet(5, 5, 93000, b"\x7c\x45\xcc", True),
        )
        units, rejected, gaps, ts_disc = p77.reconstruct_h264_access_units(packets)
        self.assertEqual(rejected, 0)
        self.assertEqual(gaps, 0)
        self.assertEqual(ts_disc, 0)
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0].nal_count, 3)
        self.assertIn(p77.ANNEX_B_START + b"\x67\x11", units[0].annexb)
        self.assertIn(p77.ANNEX_B_START + b"\x68\x22", units[0].annexb)
        self.assertIn(p77.ANNEX_B_START + b"\x65\x33", units[0].annexb)
        self.assertEqual(units[1].annexb, p77.ANNEX_B_START + b"\x65\xaa\xbb\xcc")

    def test_extraction_writes_only_to_caller_scratch_path(self) -> None:
        packets = (packet(1, 1, 90000, b"\x65\x01", True),)
        with tempfile.TemporaryDirectory() as directory:
            result = p77.extract_from_packets(packets, output_dir=Path(directory), basename="fixture")
            self.assertEqual(result.status, "PROVEN_OFFLINE")
            self.assertEqual(result.access_units, 1)
            self.assertTrue(result.output_path)
            self.assertEqual(result.output_path.parent, Path(directory))
            self.assertEqual(result.output_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result.emitted_bytes, len((p77.ANNEX_B_START + b"\x65\x01")))
            text = p77.report(result)
            self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
            self.assertIn("NETWORK_IO_PERFORMED=false", text)
            self.assertNotIn("6501", text)

    def test_malformed_rtp_header_wrong_version_and_unknown_pt_fail_closed(self) -> None:
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(wrapped(b"\x80"))
        bad_version = bytes([0x40, 99]) + b"\x00" * 10 + b"\x65"
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(wrapped(bad_version))

        unknown = p77.parse_wrapped_rtp(wrapped(rtp(1, 1, 1, 100, b"\x65", True)))
        result = p77.extract_from_packets((unknown,), output_dir=Path(tempfile.mkdtemp()))
        self.assertEqual(result.status, "NOT_PROVEN")
        self.assertEqual(result.access_units, 0)

    def test_wrapper_truncated_profile_mismatch_and_impossible_length_reject(self) -> None:
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(b"\x00" * 7)
        inner = rtp(1, 1, 1, 99, b"\x65", True)
        payload = wrapped(inner)
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(payload, expected_profile=(9, 9, 9, 9, 9, 9))
        impossible = bytearray(payload)
        impossible[2:4] = (len(inner) + 1).to_bytes(2, "little")
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(bytes(impossible))

    def test_h264_truncated_payload_shapes_reject_without_guessing(self) -> None:
        packets = (
            packet(1, 1, 90000, b"\x7c\x85", False),
            packet(2, 2, 93000, b"\x78\x00\x04\x67", True),
        )
        units, rejected, _gaps, _ts_disc = p77.reconstruct_h264_access_units(packets)
        self.assertEqual(units, ())
        self.assertEqual(rejected, 2)

    def test_fu_a_missing_start_rejects_mid_fragment(self) -> None:
        packets = (packet(1, 1, 90000, b"\x7c\x05\xaa", True),)
        units, rejected, _gaps, _ts_disc = p77.reconstruct_h264_access_units(packets)
        self.assertEqual(units, ())
        self.assertEqual(rejected, 1)

    def test_sequence_gap_in_middle_of_au_splits_by_rejection_not_guessing(self) -> None:
        packets = (
            packet(1, 1, 90000, b"\x7c\x85\xaa", False),
            packet(2, 3, 90000, b"\x7c\x45\xbb", True),
            packet(3, 4, 93000, b"\x65\x01", True),
        )
        units, rejected, gaps, _ts_disc = p77.reconstruct_h264_access_units(packets)
        self.assertEqual(gaps, 1)
        self.assertEqual(rejected, 2)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].annexb, p77.ANNEX_B_START + b"\x65\x01")

    def test_timestamp_discontinuity_mid_au_rejects_open_unit(self) -> None:
        packets = (
            packet(1, 1, 90000, b"\x65\xaa", False),
            packet(2, 2, 93000, b"\x61\xbb", True),
        )
        units, rejected, _gaps, ts_disc = p77.reconstruct_h264_access_units(packets)
        self.assertEqual(units, (p77.AccessUnit(93000, 1, p77.ANNEX_B_START + b"\x61\xbb", True, False),))
        self.assertEqual(rejected, 1)
        self.assertEqual(ts_disc, 1)

    def test_default_cli_skips_optional_pcap_when_not_provided(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p77.main([]), 0)
        text = out.getvalue()
        self.assertIn("PCAP_SHA256_GATE=NOT_PROVIDED", text)
        self.assertIn("H264_EXTRACTION=NOT_PROVIDED", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_module_safety_statics(self) -> None:
        source = Path(p77.__file__).read_text()
        forbidden = ("socket", "requests", "urllib", "ct120_launch_", "ct120_run_")
        for token in forbidden:
            self.assertNotIn(token, source)
        self.assertNotIn("self_activation.pcap", source)
        self.assertNotIn("f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a", source)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", source)


if __name__ == "__main__":
    unittest.main()
