#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p77_offset8_h264_extraction_contract as p77
import entrance_p78_capture_verifier as p78v


CLIENT_IP = b"\x0a\x00\x00\x01"
DEVICE_IP = b"\x0a\x00\x00\x02"
CLIENT_PORT = 40000
DEVICE_PORT = 50000


def rtp(
    seq: int,
    ts: int,
    ssrc: int,
    pt: int,
    media: bytes,
    marker: bool = False,
) -> bytes:
    return (
        bytes([0x80, pt | (0x80 if marker else 0)])
        + seq.to_bytes(2, "big")
        + ts.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + media
    )


def wrapped(
    inner: bytes,
    *,
    profile: bytes = b"\x01\x02\x10\x20\x30\x40\x50\x60",
) -> bytes:
    prefix = bytearray(profile)
    prefix[2:4] = len(inner).to_bytes(2, "little")
    return bytes(prefix) + inner


def packet(
    number: int,
    pt: int,
    media: bytes,
    *,
    marker: bool = True,
) -> p77.WrappedRtpPacket:
    return p77.parse_wrapped_rtp(
        wrapped(rtp(number, 90000, 0xAABBCCDD, pt, media, marker)),
        packet_number=number,
        direction="DEVICE_TO_CLIENT",
    )


def pseudotcp_with_anchor(anchor: bytes = b"UAUT") -> bytes:
    return b"\x00" * 24 + anchor


def ipv4_udp(
    payload: bytes,
    *,
    src: bytes,
    dst: bytes,
    sport: int,
    dport: int,
) -> bytes:
    udp_len = 8 + len(payload)
    total_len = 20 + udp_len
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = total_len.to_bytes(2, "big")
    ip[8] = 64
    ip[9] = 17
    ip[12:16] = src
    ip[16:20] = dst
    udp = (
        sport.to_bytes(2, "big")
        + dport.to_bytes(2, "big")
        + udp_len.to_bytes(2, "big")
        + b"\x00\x00"
    )
    return bytes(ip) + udp + payload


def capture_frame(ip: bytes, linktype: int) -> bytes:
    if linktype == p78v.PCAP_LINKTYPE_RAW:
        return ip
    if linktype == p78v.PCAP_LINKTYPE_LINUX_SLL:
        return struct.pack(
            "!HHH8sH",
            0,
            1,
            6,
            b"\x00" * 8,
            p78v.ETH_P_IP,
        ) + ip
    if linktype == p78v.PCAP_LINKTYPE_LINUX_SLL2:
        return struct.pack(
            "!HHIHBB8s",
            p78v.ETH_P_IP,
            0,
            1,
            1,
            0,
            6,
            b"\x00" * 8,
        ) + ip
    return ip


def write_pcap(path: Path, linktype: int, frames: list[bytes]) -> None:
    blob = bytearray(
        struct.pack(
            "<IHHIIII",
            0xA1B2C3D4,
            2,
            4,
            0,
            0,
            65535,
            linktype,
        )
    )
    for index, frame in enumerate(frames, start=1):
        blob += struct.pack("<IIII", index, 0, len(frame), len(frame))
        blob += frame
    path.write_bytes(blob)


def valid_pcap(path: Path, linktype: int, *, residual: bool = False) -> None:
    client_signal = ipv4_udp(
        pseudotcp_with_anchor(),
        src=CLIENT_IP,
        dst=DEVICE_IP,
        sport=CLIENT_PORT,
        dport=DEVICE_PORT,
    )
    media = ipv4_udp(
        wrapped(rtp(1, 90000, 0xAABBCCDD, p77.PT_H264, b"\x65\x01", True)),
        src=DEVICE_IP,
        dst=CLIENT_IP,
        sport=DEVICE_PORT,
        dport=CLIENT_PORT,
    )
    frames = [
        capture_frame(client_signal, linktype),
        capture_frame(media, linktype),
    ]
    if residual:
        opaque = ipv4_udp(
            b"\xff" * 12,
            src=DEVICE_IP,
            dst=CLIENT_IP,
            sport=DEVICE_PORT,
            dport=CLIENT_PORT,
        )
        frames.append(capture_frame(opaque, linktype))
    write_pcap(path, linktype, frames)


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
            self.assertEqual(result.h264_access_units, 1)
            self.assertIn("P78_OFFSET8_RTP_PRESENT=true", text)
            self.assertIn("P78_DECODE_REQUESTED=false", text)
            self.assertNotIn("6501", text)

    def test_raw_sll_and_sll2_pcaps_are_accepted_at_low_packet_numbers(self) -> None:
        for linktype in (
            p78v.PCAP_LINKTYPE_RAW,
            p78v.PCAP_LINKTYPE_LINUX_SLL,
            p78v.PCAP_LINKTYPE_LINUX_SLL2,
        ):
            with self.subTest(linktype=linktype), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "capture.pcap"
                valid_pcap(path, linktype)
                result = p78v.verify_pcap(path, output_dir=Path(directory) / "out")
                self.assertEqual(result.status, "PASS")
                self.assertEqual(result.pcap_linktype, linktype)
                self.assertEqual(result.pt99_h264_packets, 1)

    def test_unsupported_linktype_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            write_pcap(path, 1, [])
            with self.assertRaisesRegex(p78v.P78RejectedInput, "UNSUPPORTED_PCAP_LINKTYPE"):
                p78v.verify_pcap(path, output_dir=Path(directory) / "out")

    def test_runtime_parser_has_no_frozen_packet_boundary(self) -> None:
        source = Path(p78v.__file__).read_text(encoding="utf-8")
        self.assertNotIn("BOUNDARY_PACKET", source)
        self.assertNotIn("packets_from_datagrams", source)
        self.assertNotIn("EXPECTED_PCAP_SHA256", source)

    def test_residual_selected_flow_udp_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            valid_pcap(path, p78v.PCAP_LINKTYPE_LINUX_SLL2, residual=True)
            with self.assertRaisesRegex(p78v.P78RejectedInput, "RESIDUAL_SELECTED_FLOW_UDP"):
                p78v.verify_pcap(path, output_dir=Path(directory) / "out")

    def test_decode_success_requires_probe_decode_and_one_jpeg(self) -> None:
        packets = (packet(1, p77.PT_H264, b"\x65\x01", marker=True),)

        def which(name: str) -> str:
            return f"/usr/bin/{name}"

        def run(command, **_kwargs):
            if command[0].endswith("ffprobe"):
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "h264\n", "stderr": ""},
                )()
            if command[-1] == "-":
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "", "stderr": ""},
                )()
            Path(command[-1]).write_bytes(b"jpeg")
            return type(
                "Completed",
                (),
                {"returncode": 0, "stdout": "", "stderr": ""},
            )()

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            p78v.shutil, "which", side_effect=which
        ), mock.patch.object(p78v.subprocess, "run", side_effect=run):
            result = p78v.verify_packets(
                packets,
                output_dir=Path(directory),
                decode=True,
            )
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.ffprobe_status, "PASS")
            self.assertEqual(result.ffmpeg_decode_status, "PASS")
            self.assertEqual(result.decode_status, "PASS")
            self.assertTrue(result.scratch_jpeg_created)
            self.assertEqual(result.scratch_jpeg_count, 1)
            jpeg = Path(directory) / "p78_live_capture.jpg"
            self.assertTrue(jpeg.exists())
            self.assertEqual(jpeg.stat().st_mode & 0o777, 0o600)

    def test_ffprobe_failure_fails_decode_gate(self) -> None:
        packets = (packet(1, p77.PT_H264, b"\x65\x01", marker=True),)
        failed = type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": ""},
        )()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            p78v.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"
        ), mock.patch.object(p78v.subprocess, "run", return_value=failed):
            result = p78v.verify_packets(
                packets,
                output_dir=Path(directory),
                decode=True,
            )
            self.assertEqual(result.status, "NOT_PROVEN")
            self.assertEqual(result.ffprobe_status, "NOT_PROVEN")
            self.assertEqual(result.decode_status, "NOT_PROVEN")

    def test_ffmpeg_decode_failure_fails_decode_gate(self) -> None:
        packets = (packet(1, p77.PT_H264, b"\x65\x01", marker=True),)

        def run(command, **_kwargs):
            if command[0].endswith("ffprobe"):
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "h264\n", "stderr": ""},
                )()
            return type(
                "Completed",
                (),
                {"returncode": 1, "stdout": "", "stderr": ""},
            )()

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            p78v.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"
        ), mock.patch.object(p78v.subprocess, "run", side_effect=run):
            result = p78v.verify_packets(
                packets,
                output_dir=Path(directory),
                decode=True,
            )
            self.assertEqual(result.status, "NOT_PROVEN")
            self.assertEqual(result.ffprobe_status, "PASS")
            self.assertEqual(result.ffmpeg_decode_status, "NOT_PROVEN")
            self.assertEqual(result.scratch_jpeg_count, 0)

    def test_no_h264_cannot_pass_decode(self) -> None:
        packets = (packet(1, p77.PT_PCMA, b"\x01\x02", marker=True),)
        with tempfile.TemporaryDirectory() as directory:
            result = p78v.verify_packets(
                packets,
                output_dir=Path(directory),
                decode=True,
            )
            self.assertEqual(result.status, "NOT_PROVEN")
            self.assertEqual(result.decode_status, "NOT_PROVEN")
            self.assertEqual(result.scratch_jpeg_count, 0)

    def test_malformed_and_unknown_pt_fail_closed(self) -> None:
        with self.assertRaises(p77.RejectedInput):
            p77.parse_wrapped_rtp(b"\x00" * 7)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(p78v.P78RejectedInput, "UNKNOWN_PAYLOAD_TYPE"):
                p78v.verify_packets(
                    (packet(1, 100, b"\x65"),),
                    output_dir=Path(directory),
                )
            with self.assertRaisesRegex(p78v.P78RejectedInput, "RESIDUAL"):
                p78v.verify_packets(
                    (packet(1, p77.PT_H264, b"\x65"),),
                    output_dir=Path(directory),
                    residual_packets=1,
                )
            with self.assertRaisesRegex(p78v.P78RejectedInput, "NO_OFFSET8_RTP"):
                p78v.verify_packets((), output_dir=Path(directory))

    def test_default_cli_is_safe_offline(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p78v.main([]), 0)
        text = out.getvalue()
        self.assertIn("P78_H264_ORACLE=NOT_PROVIDED", text)
        self.assertIn("P78_DECODE_REQUESTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_module_never_emits_raw_payload(self) -> None:
        source = Path(p78v.__file__).read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "ct120_launch_", "ct120_run_"):
            self.assertNotIn(forbidden, source)
        self.assertIn("P78_RAW_PAYLOAD_EMITTED=false", source)
        self.assertIn("P78_HEX_PAYLOAD_EMITTED=false", source)
        self.assertIn("P78_BASE64_PAYLOAD_EMITTED=false", source)


if __name__ == "__main__":
    unittest.main()
