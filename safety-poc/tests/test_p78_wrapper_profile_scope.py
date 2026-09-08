#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p77_offset8_h264_extraction_contract as p77
import entrance_p78_capture_verifier as p78v


def wrapped_rtp(
    *,
    packet_number: int,
    payload_type: int,
    ssrc: int,
    profile: bytes,
    media: bytes,
) -> p77.WrappedRtpPacket:
    rtp = (
        bytes([0x80, payload_type | 0x80])
        + packet_number.to_bytes(2, "big")
        + (90000 + packet_number).to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + media
    )
    prefix = bytearray(profile)
    prefix[2:4] = len(rtp).to_bytes(2, "little")
    return p77.parse_wrapped_rtp(
        bytes(prefix) + rtp,
        packet_number=packet_number,
        direction="DEVICE_TO_CLIENT",
    )


class P78WrapperProfileScopeTests(unittest.TestCase):
    def test_distinct_profiles_across_distinct_streams_are_allowed(self) -> None:
        video = wrapped_rtp(
            packet_number=1,
            payload_type=p77.PT_H264,
            ssrc=0x01020304,
            profile=b"\x01\x02\x00\x00\x10\x20\x30\x40",
            media=b"\x65\x01",
        )
        audio = wrapped_rtp(
            packet_number=2,
            payload_type=p77.PT_PCMA,
            ssrc=0x05060708,
            profile=b"\x01\x02\x00\x00\x10\x20\x30\x41",
            media=b"\x01\x02",
        )

        with tempfile.TemporaryDirectory() as directory:
            result = p78v.verify_packets(
                (video, audio),
                output_dir=Path(directory),
            )

        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.wrapper_profile_consistent)
        self.assertEqual(result.wrapper_profile_count, 2)
        self.assertIn("P78_WRAPPER_PROFILE_SCOPE=PER_STREAM", p78v.report(result))

    def test_profile_change_inside_one_stream_is_rejected(self) -> None:
        first = wrapped_rtp(
            packet_number=1,
            payload_type=p77.PT_H264,
            ssrc=0x01020304,
            profile=b"\x01\x02\x00\x00\x10\x20\x30\x40",
            media=b"\x65\x01",
        )
        second = wrapped_rtp(
            packet_number=2,
            payload_type=p77.PT_H264,
            ssrc=0x01020304,
            profile=b"\x01\x02\x00\x00\x10\x20\x30\x41",
            media=b"\x65\x02",
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                p78v.P78RejectedInput,
                "WRAPPER_PROFILE_INCONSISTENT_WITHIN_STREAM",
            ):
                p78v.verify_packets(
                    (first, second),
                    output_dir=Path(directory),
                )


if __name__ == "__main__":
    unittest.main()
