#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p77_offset8_h264_extraction_contract as p77
import entrance_p78_capture_verifier as p78v


def rtp(seq: int, ts: int, ssrc: int, pt: int, media: bytes, marker: bool = False) -> bytes:
    return (
        bytes([0x80, pt | (0x80 if marker else 0)])
        + seq.to_bytes(2, "big")
        + ts.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + media
    )


def wrapped(inner: bytes, *, profile: bytes = b"\x01\x02\x10\x20\x30\x40\x50\x60") -> bytes:
    prefix = bytearray(profile)
    prefix[2:4] = len(inner).to_bytes(2, "little")
    return bytes(prefix) + inner


def packet(number: int, pt: int, media: bytes, *, marker: bool = True) -> p77.WrappedRtpPacket:
    return p77.parse_wrapped_rtp(
        wrapped(rtp(number, 90000, 0xAABBCCDD, pt, media, marker)),
        packet_number=number,
        direction="DEVICE_TO_CLIENT",
    )


class P78CaptureVerifierTests(unittest.TestCase):
    def test_synthetic_offset8_rtp_happy_path(self) -> None:
        packets = (
            packet(1, p77.PT_H264, b"\x65\x01", marker=True),
            packet(2, p77.PT_PCMA, b"\x01\x02", marker=True),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = p78v.verify_packets(packets, output_dir=Path(directory))
            text = p78v.report(result)
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.pt99_h264_packets, 1)
            self.assertEqual(result.pt8_audio_packets, 1)
            self.assertEqual(result.h264_access_units, 1)
            self.assertIn("P78_OFFSET8_RTP_PRESENT=true", text)
            self.assertIn("P78_DECODE_REQUESTED=false", text)
            self.assertIn("P78_RAW_PAYLOAD_EMITTED=false", text)
            self.assertNotIn("6501", text)

    def test_malformed_truncated_and_unknown_pt_fail_closed(self) -> None:
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(b"\x00" * 7)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(p78v.P78RejectedInput, "UNKNOWN_PAYLOAD_TYPE"):
                p78v.verify_packets((packet(1, 100, b"\x65"),), output_dir=Path(directory))
            with self.assertRaisesRegex(p78v.P78RejectedInput, "RESIDUAL"):
                p78v.verify_packets((packet(1, p77.PT_H264, b"\x65"),), output_dir=Path(directory), residual_packets=1)
            with self.assertRaisesRegex(p78v.P78RejectedInput, "NO_OFFSET8_RTP"):
                p78v.verify_packets((), output_dir=Path(directory))

    def test_wrapper_profile_inconsistency_rejects(self) -> None:
        first = packet(1, p77.PT_H264, b"\x65", marker=True)
        second = p77.parse_wrapped_rtp(
            wrapped(
                rtp(2, 90000, 0xAABBCCDD, p77.PT_H264, b"\x65", True),
                profile=b"\x09\x09\x10\x20\x30\x40\x50\x60",
            ),
            packet_number=2,
            direction="DEVICE_TO_CLIENT",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(p78v.P78RejectedInput, "WRAPPER_PROFILE"):
                p78v.verify_packets((first, second), output_dir=Path(directory))

    def test_default_cli_is_safe_offline(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p78v.main([]), 0)
        text = out.getvalue()
        self.assertIn("P78_H264_ORACLE=NOT_PROVIDED", text)
        self.assertIn("P78_DECODE_REQUESTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_decode_path_only_runs_when_enabled(self) -> None:
        packets = (packet(1, p77.PT_H264, b"\x65\x01", marker=True),)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(p78v.subprocess, "run") as run:
                p78v.verify_packets(packets, output_dir=Path(directory), decode=False)
                run.assert_not_called()
            with mock.patch.object(p78v.shutil, "which", return_value="/usr/bin/ffprobe"), mock.patch.object(
                p78v.subprocess,
                "run",
                return_value=type("Completed", (), {"returncode": 0, "stdout": "h264\n"})(),
            ) as run:
                result = p78v.verify_packets(packets, output_dir=Path(directory), decode=True)
                self.assertEqual(result.decode_status, "PASS")
                run.assert_called_once()

    def test_module_safety_statics(self) -> None:
        source = Path(p78v.__file__).read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "ct120_launch_", "ct120_run_"):
            self.assertNotIn(forbidden, source)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", source)
        self.assertNotIn("EXPECTED_PCAP_SHA256", source)


if __name__ == "__main__":
    unittest.main()
