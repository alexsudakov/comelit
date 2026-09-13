#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "custom_components" / "comelit" / "h264_recovery.py"
OFFICIAL_PCAP_SHA256 = "3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f"
EXPECTED_VIDEO_RTP_PACKETS = 2720
EXPECTED_RECOVERY_INSERTIONS = 14


def load_rewriter_module():
    spec = importlib.util.spec_from_file_location("h264_recovery_verify", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pcap_records(blob: bytes):
    if len(blob) < 24:
        raise ValueError("pcap_too_short")
    magic = blob[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    else:
        raise ValueError("unsupported_pcap_magic")
    linktype = struct.unpack(endian + "I", blob[20:24])[0]
    if linktype != 1:
        raise ValueError("unsupported_linktype")
    pos = 24
    while pos + 16 <= len(blob):
        _ts_sec, _ts_usec, incl_len, _orig_len = struct.unpack(
            endian + "IIII", blob[pos : pos + 16]
        )
        pos += 16
        if pos + incl_len > len(blob):
            raise ValueError("truncated_pcap_record")
        yield blob[pos : pos + incl_len]
        pos += incl_len


def udp_payloads(blob: bytes):
    for frame in pcap_records(blob):
        if len(frame) < 14:
            continue
        eth_type = struct.unpack("!H", frame[12:14])[0]
        offset = 14
        if eth_type == 0x8100 and len(frame) >= 18:
            eth_type = struct.unpack("!H", frame[16:18])[0]
            offset = 18
        if eth_type != 0x0800 or len(frame) < offset + 20:
            continue
        version_ihl = frame[offset]
        if version_ihl >> 4 != 4:
            continue
        ihl = (version_ihl & 0x0F) * 4
        if len(frame) < offset + ihl + 8 or frame[offset + 9] != 17:
            continue
        total_len = struct.unpack("!H", frame[offset + 2 : offset + 4])[0]
        ip_end = min(len(frame), offset + total_len)
        udp_offset = offset + ihl
        udp_len = struct.unpack("!H", frame[udp_offset + 4 : udp_offset + 6])[0]
        payload_start = udp_offset + 8
        payload_end = min(ip_end, udp_offset + udp_len)
        if payload_start <= payload_end:
            yield frame[payload_start:payload_end]


def strip_known_capture_wrapper(payload: bytes) -> bytes:
    if len(payload) >= 20 and payload[0] >> 6 != 2:
        for offset in (4, 8, 12):
            if len(payload) > offset + 12 and payload[offset] >> 6 == 2:
                return payload[offset:]
    return payload


def is_pt99_rtp(payload: bytes) -> bool:
    return len(payload) >= 12 and payload[0] >> 6 == 2 and (payload[1] & 0x7F) == 99


def rtp_payload(packet: bytes) -> bytes:
    offset = 12 + (packet[0] & 0x0F) * 4
    if packet[0] & 0x10:
        words = struct.unpack_from("!H", packet, offset + 2)[0]
        offset += 4 + words * 4
    end = len(packet)
    if packet[0] & 0x20:
        end -= packet[-1]
    return packet[offset:end]


def seq(packet: bytes) -> int:
    return struct.unpack_from("!H", packet, 2)[0]


def depacketize_annexb(packets: list[bytes]) -> bytes:
    out = bytearray()
    fu_buffer: bytearray | None = None
    for packet in packets:
        payload = rtp_payload(packet)
        if not payload:
            continue
        nal_type = payload[0] & 0x1F
        if 1 <= nal_type <= 23:
            out.extend(b"\x00\x00\x00\x01")
            out.extend(payload)
        elif nal_type == 24:
            pos = 1
            while pos + 2 <= len(payload):
                nal_len = struct.unpack_from("!H", payload, pos)[0]
                pos += 2
                if nal_len == 0 or pos + nal_len > len(payload):
                    break
                out.extend(b"\x00\x00\x00\x01")
                out.extend(payload[pos : pos + nal_len])
                pos += nal_len
        elif nal_type == 28 and len(payload) >= 2:
            start = bool(payload[1] & 0x80)
            end = bool(payload[1] & 0x40)
            if start:
                fu_buffer = bytearray()
                fu_buffer.append((payload[0] & 0xE0) | (payload[1] & 0x1F))
                fu_buffer.extend(payload[2:])
            elif fu_buffer is not None:
                fu_buffer.extend(payload[2:])
            if end and fu_buffer is not None:
                out.extend(b"\x00\x00\x00\x01")
                out.extend(fu_buffer)
                fu_buffer = None
    return bytes(out)


def frame_md5(path: Path) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    with tempfile.NamedTemporaryFile() as output:
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-err_detect",
                "explode",
                "-i",
                str(path),
                "-f",
                "framemd5",
                output.name,
            ],
            check=True,
        )
        return hashlib.sha256(Path(output.name).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path)
    args = parser.parse_args()

    if args.pcap is None or not args.pcap.is_file():
        print("CAPTURE_RUNTIME_VALIDATION=UNAVAILABLE")
        print("OFFICIAL_PCAP_FOUND=false")
        return 0
    actual_sha = sha256_file(args.pcap)
    if actual_sha != OFFICIAL_PCAP_SHA256:
        print("CAPTURE_RUNTIME_VALIDATION=UNAVAILABLE")
        print("OFFICIAL_PCAP_FOUND=false")
        print("OFFICIAL_PCAP_SHA256_MATCH=false")
        return 0

    module = load_rewriter_module()
    rewriter = module.H264RecoveryRewriter()
    input_packets = [
        stripped
        for payload in udp_payloads(args.pcap.read_bytes())
        if is_pt99_rtp(stripped := strip_known_capture_wrapper(payload))
    ]
    output_packets: list[bytes] = []
    expected_output_sequences: list[int] = []
    original_output_sequences: list[int] = []
    original_payloads_preserved = True
    injections_before_packet = 0
    for packet in input_packets:
        rewritten = rewriter.rewrite_rtp_packet(packet)
        output_packets.extend(rewritten)
        input_sequence = seq(packet)
        if len(rewritten) == 2:
            expected_output_sequences.append(
                (input_sequence + injections_before_packet) & 0xFFFF
            )
            injections_before_packet += 1
        expected_original_sequence = (input_sequence + injections_before_packet) & 0xFFFF
        expected_output_sequences.append(expected_original_sequence)
        original = rewritten[-1]
        original_output_sequences.append(seq(original))
        original_payloads_preserved = (
            original_payloads_preserved and rtp_payload(original) == rtp_payload(packet)
        )

    input_sequences = [seq(packet) for packet in input_packets]
    preexisting_gaps_preserved = True
    for before_in, after_in, before_out, after_out in zip(
        input_sequences,
        input_sequences[1:],
        original_output_sequences,
        original_output_sequences[1:],
        strict=False,
    ):
        preexisting_gaps_preserved = preexisting_gaps_preserved and (
            (after_in - before_in) & 0xFFFF == (after_out - before_out) & 0xFFFF
        )
    output_sequences = [seq(packet) for packet in output_packets]
    new_sequence_gaps = abs(len(expected_output_sequences) - len(output_sequences))
    for expected, actual in zip(
        expected_output_sequences, output_sequences, strict=False
    ):
        if expected != actual:
            new_sequence_gaps += 1

    original_annexb = depacketize_annexb(input_packets)
    recovery_annexb = depacketize_annexb(output_packets)
    decode_identity = "UNAVAILABLE"
    if shutil.which("ffmpeg") is not None:
        with tempfile.TemporaryDirectory() as tmp:
            original_path = Path(tmp) / "original.h264"
            recovery_path = Path(tmp) / "recovery.h264"
            original_path.write_bytes(original_annexb)
            recovery_path.write_bytes(recovery_annexb)
            decode_identity = str(frame_md5(original_path) == frame_md5(recovery_path)).lower()

    print("OFFICIAL_PCAP_FOUND=true")
    print("OFFICIAL_PCAP_SHA256_MATCH=true")
    print(f"INPUT_VIDEO_RTP_PACKETS={len(input_packets)}")
    print(f"EXPECTED_INPUT_VIDEO_RTP_PACKETS={EXPECTED_VIDEO_RTP_PACKETS}")
    print(f"RECOVERY_SEI_INSERTIONS={rewriter.injected_count}")
    print(f"EXPECTED_RECOVERY_SEI_INSERTIONS={EXPECTED_RECOVERY_INSERTIONS}")
    print(f"ORIGINAL_PAYLOADS_PRESERVED={str(original_payloads_preserved).lower()}")
    print(f"NEW_SEQUENCE_GAPS={new_sequence_gaps}")
    print(f"PREEXISTING_GAPS_PRESERVED={str(preexisting_gaps_preserved).lower()}")
    print(f"FFMPEG_DECODE_FRAME_IDENTITY={decode_identity}")
    ok = (
        len(input_packets) == EXPECTED_VIDEO_RTP_PACKETS
        and rewriter.injected_count == EXPECTED_RECOVERY_INSERTIONS
        and original_payloads_preserved
        and new_sequence_gaps == 0
        and preexisting_gaps_preserved
    )
    print(f"CAPTURE_RUNTIME_VALIDATION={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
