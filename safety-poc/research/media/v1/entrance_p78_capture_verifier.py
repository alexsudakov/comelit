#!/usr/bin/env python3
"""P78 semantic verifier for a caller-supplied live-capture PCAP.

This verifier imports the P77 offset-8 RTP helpers but intentionally does not
apply P77's frozen-capture SHA gate.  It performs strict structural
classification, writes reconstructed H264 only to caller scratch with mode
0600, and emits semantic markers only.  Optional decode probing is disabled by
default and runs only when `--decode` is explicitly supplied and ffprobe exists.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

import entrance_p77_offset8_h264_extraction_contract as p77
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import _read_selected_datagrams
from pseudotcp_pcap_handshake_forensic import load_capture, select_vip_flow


class P78RejectedInput(ValueError):
    """Raised for malformed or non-classifiable live-capture input."""


@dataclass(frozen=True)
class VerificationResult:
    status: str
    wrapped_rtp_packets: int
    pt99_h264_packets: int
    pt8_audio_packets: int
    unknown_pt_packets: int
    residual_packets: int
    wrapper_profile_count: int
    wrapper_profile_consistent: bool
    h264_status: str
    h264_access_units: int
    h264_rejected_units: int
    h264_bytes: int
    h264_sha256: str
    decode_requested: bool
    decode_status: str


def _classify_packets(
    packets: tuple[p77.WrappedRtpPacket, ...],
    *,
    residual_packets: int,
    output_dir: Path,
    decode: bool = False,
) -> VerificationResult:
    profiles = {packet.wrapper_profile for packet in packets}
    unknown = tuple(packet for packet in packets if packet.payload_type not in (p77.PT_H264, p77.PT_PCMA))
    if residual_packets:
        raise P78RejectedInput("REJECTED_INPUT_RESIDUAL_WRAPPED_RTP_SHAPE")
    if unknown:
        raise P78RejectedInput("UNKNOWN_PAYLOAD_TYPE")
    if not packets:
        raise P78RejectedInput("REJECTED_INPUT_NO_OFFSET8_RTP")
    if len(profiles) != 1:
        raise P78RejectedInput("REJECTED_INPUT_WRAPPER_PROFILE_INCONSISTENT")

    extraction = p77.extract_from_packets(
        packets,
        output_dir=output_dir,
        basename="p78_live_capture",
        residual_packets=residual_packets,
        extract_audio=False,
    )
    decode_status = _decode_probe(extraction.output_path, enabled=decode)
    status = "PASS" if extraction.status == "PROVEN_OFFLINE" else "NOT_PROVEN"
    return VerificationResult(
        status=status,
        wrapped_rtp_packets=len(packets),
        pt99_h264_packets=sum(1 for packet in packets if packet.payload_type == p77.PT_H264),
        pt8_audio_packets=sum(1 for packet in packets if packet.payload_type == p77.PT_PCMA),
        unknown_pt_packets=0,
        residual_packets=residual_packets,
        wrapper_profile_count=len(profiles),
        wrapper_profile_consistent=True,
        h264_status=extraction.status,
        h264_access_units=extraction.access_units,
        h264_rejected_units=extraction.rejected_units,
        h264_bytes=extraction.emitted_bytes,
        h264_sha256=extraction.emitted_sha256 if extraction.emitted_bytes else "NONE",
        decode_requested=decode,
        decode_status=decode_status,
    )


def _decode_probe(path: Path | None, *, enabled: bool) -> str:
    if not enabled:
        return "NOT_REQUESTED"
    if path is None or not path.exists() or path.stat().st_size == 0:
        return "NOT_PROVEN"
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return "UNAVAILABLE"
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    return "PASS" if completed.returncode == 0 and "h264" in completed.stdout.lower() else "NOT_PROVEN"


def verify_packets(
    packets: tuple[p77.WrappedRtpPacket, ...],
    *,
    output_dir: Path,
    residual_packets: int = 0,
    decode: bool = False,
) -> VerificationResult:
    return _classify_packets(packets, residual_packets=residual_packets, output_dir=output_dir, decode=decode)


def verify_pcap(path: Path, *, output_dir: Path, decode: bool = False) -> VerificationResult:
    try:
        capture = load_capture(path)
        analysis = select_vip_flow(capture)
        datagrams = _read_selected_datagrams(path, client=analysis.client, device=analysis.device)
        packets, residual = p77.packets_from_datagrams(datagrams, client=analysis.client, device=analysis.device)
    except Exception as exc:
        raise P78RejectedInput(f"REJECTED_INPUT_{type(exc).__name__}") from exc
    return _classify_packets(packets, residual_packets=residual, output_dir=output_dir, decode=decode)


def report(result: VerificationResult) -> str:
    return "\n".join(
        (
            "=== COMELIT P78 LIVE CAPTURE VERIFIER ===",
            f"P78_H264_ORACLE={result.status}",
            f"P78_OFFSET8_RTP_PRESENT={'true' if result.wrapped_rtp_packets else 'false'}",
            f"P78_WRAPPED_RTP_PACKETS={result.wrapped_rtp_packets}",
            f"P78_PT99_H264_PACKETS={result.pt99_h264_packets}",
            f"P78_PT8_AUDIO_PACKETS={result.pt8_audio_packets}",
            f"P78_UNKNOWN_PT_PACKETS={result.unknown_pt_packets}",
            f"P78_OFFSET8_RESIDUAL_PACKETS={result.residual_packets}",
            f"P78_WRAPPER_PROFILE_COUNT={result.wrapper_profile_count}",
            f"P78_WRAPPER_PROFILE_CONSISTENT={'true' if result.wrapper_profile_consistent else 'false'}",
            f"P78_H264_ACCESS_UNITS={result.h264_access_units}",
            f"P78_H264_REJECTED_ACCESS_UNITS={result.h264_rejected_units}",
            f"P78_H264_ANNEXB_BYTES={result.h264_bytes}",
            f"P78_H264_ANNEXB_SHA256={result.h264_sha256}",
            f"P78_DECODE_REQUESTED={'true' if result.decode_requested else 'false'}",
            f"P78_DECODE_STATUS={result.decode_status}",
            "P78_RAW_PAYLOAD_EMITTED=false",
            "P78_HEX_PAYLOAD_EMITTED=false",
            "P78_BASE64_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "=== END COMELIT P78 LIVE CAPTURE VERIFIER ===",
        )
    )


def rejected_report(reason: str) -> str:
    return "\n".join(
        (
            "=== COMELIT P78 LIVE CAPTURE VERIFIER ===",
            f"P78_H264_ORACLE=REJECTED_INPUT reason={reason}",
            "P78_OFFSET8_RTP_PRESENT=false",
            "P78_WRAPPED_RTP_PACKETS=0",
            "P78_UNKNOWN_PT_PACKETS=UNKNOWN",
            "P78_RAW_PAYLOAD_EMITTED=false",
            "P78_HEX_PAYLOAD_EMITTED=false",
            "P78_BASE64_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "=== END COMELIT P78 LIVE CAPTURE VERIFIER ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".p78-work/media-out"))
    parser.add_argument("--decode", action="store_true")
    args = parser.parse_args(argv)

    if args.pcap is None:
        print("P78_H264_ORACLE=NOT_PROVIDED")
        print("P78_DECODE_REQUESTED=false")
        print("P78_RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 0
    if not args.pcap.exists():
        print("P78_H264_ORACLE=REJECTED_INPUT reason=PCAP_NOT_FOUND")
        print("P78_RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 2
    try:
        result = verify_pcap(args.pcap, output_dir=args.output_dir, decode=args.decode)
    except P78RejectedInput as exc:
        print(rejected_report(str(exc)))
        return 2
    print(report(result))
    return 0 if result.status == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
