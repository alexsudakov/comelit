#!/usr/bin/env python3
"""P78 semantic verifier for a caller-supplied live-capture PCAP.

Unlike P77 frozen-capture forensics, this verifier is runtime-oriented:
it does not use historical packet-number boundaries or frozen-capture SHA gates.
It accepts classic PCAP with RAW, Linux SLL, or Linux SLL2 link types, identifies
the ViP flow from structural PseudoTCP client anchors, classifies remaining
selected-flow UDP structurally, reconstructs offset-8 RTP/H264 through P77's
low-level packet/H264 helpers, and optionally performs bounded ffprobe/ffmpeg
decode validation plus one scratch JPEG.

No network I/O is performed and no raw/hex/base64 media payload is emitted.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import subprocess

import entrance_p77_offset8_h264_extraction_contract as p77
from pseudotcp_pcap_handshake_forensic import (
    CaptureInfo,
    Endpoint,
    _ipv4_udp,
    _pcap_format,
    _pseudotcp_segment,
    select_vip_flow,
)


PCAP_LINKTYPE_RAW = 101
PCAP_LINKTYPE_LINUX_SLL = 113
PCAP_LINKTYPE_LINUX_SLL2 = 276
ETH_P_IP = 0x0800
STUN_MAGIC_COOKIE = b"\x21\x12\xa4\x42"
DECODE_TIMEOUT_SECONDS = 15


class P78RejectedInput(ValueError):
    """Raised for malformed or non-classifiable live-capture input."""


@dataclass(frozen=True)
class CapturedDatagram:
    packet_number: int
    timestamp: float
    source: Endpoint
    target: Endpoint
    payload: bytes


@dataclass(frozen=True)
class VerificationResult:
    status: str
    pcap_linktype: int | None
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
    ffprobe_status: str
    ffmpeg_decode_status: str
    scratch_jpeg_created: bool
    scratch_jpeg_count: int
    decode_status: str


def _stun_like(payload: bytes) -> bool:
    return bool(
        len(payload) >= 20
        and (payload[0] & 0xC0) == 0
        and payload[4:8] == STUN_MAGIC_COOKIE
    )


def _ipv4_from_capture_frame(frame: bytes, linktype: int) -> bytes | None:
    if linktype == PCAP_LINKTYPE_RAW:
        return frame

    if linktype == PCAP_LINKTYPE_LINUX_SLL:
        if len(frame) < 16:
            raise P78RejectedInput("SLL_HEADER_TRUNCATED")
        protocol = int.from_bytes(frame[14:16], "big")
        if protocol != ETH_P_IP:
            return None
        return frame[16:]

    if linktype == PCAP_LINKTYPE_LINUX_SLL2:
        if len(frame) < 20:
            raise P78RejectedInput("SLL2_HEADER_TRUNCATED")
        protocol = int.from_bytes(frame[0:2], "big")
        if protocol != ETH_P_IP:
            return None
        return frame[20:]

    raise P78RejectedInput(f"UNSUPPORTED_PCAP_LINKTYPE_{linktype}")


def _read_udp_datagrams(path: Path) -> tuple[int, int, tuple[CapturedDatagram, ...]]:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise P78RejectedInput("PCAP_GLOBAL_HEADER_TRUNCATED")

    try:
        endian, timestamp_scale = _pcap_format(blob[:4])
        _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", blob[:24])
    except Exception as exc:
        raise P78RejectedInput("PCAP_GLOBAL_HEADER_REJECTED") from exc

    if linktype not in (
        PCAP_LINKTYPE_RAW,
        PCAP_LINKTYPE_LINUX_SLL,
        PCAP_LINKTYPE_LINUX_SLL2,
    ):
        raise P78RejectedInput(f"UNSUPPORTED_PCAP_LINKTYPE_{linktype}")

    packet_number = 0
    offset = 24
    datagrams: list[CapturedDatagram] = []

    while offset < len(blob):
        if len(blob) - offset < 16:
            raise P78RejectedInput("PCAP_PACKET_HEADER_TRUNCATED")

        ts_sec, ts_frac, captured_len, _original_len = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16

        if captured_len > len(blob) - offset:
            raise P78RejectedInput("PCAP_PACKET_BODY_TRUNCATED")

        packet_number += 1
        frame = blob[offset : offset + captured_len]
        offset += captured_len

        ip_frame = _ipv4_from_capture_frame(frame, linktype)
        if ip_frame is None:
            continue

        parsed = _ipv4_udp(ip_frame)
        if parsed is None:
            continue

        source, target, payload = parsed
        datagrams.append(
            CapturedDatagram(
                packet_number=packet_number,
                timestamp=ts_sec + ts_frac / timestamp_scale,
                source=source,
                target=target,
                payload=payload,
            )
        )

    return linktype, packet_number, tuple(datagrams)


def _select_vip_datagrams(
    datagrams: tuple[CapturedDatagram, ...],
    *,
    linktype: int,
    packet_count: int,
) -> tuple[Endpoint, Endpoint, tuple[CapturedDatagram, ...]]:
    segments = []
    for item in datagrams:
        segment = _pseudotcp_segment(
            item.packet_number,
            item.timestamp,
            item.source,
            item.target,
            item.payload,
        )
        if segment is not None:
            segments.append(segment)

    capture = CaptureInfo(
        sha256="NOT_EMITTED",
        linktype=linktype,
        packet_count=packet_count,
        pseudotcp_segments=tuple(segments),
    )
    try:
        analysis = select_vip_flow(capture)
    except Exception as exc:
        raise P78RejectedInput("VIP_FLOW_NOT_PROVEN") from exc

    selected_key = tuple(sorted((analysis.client, analysis.device)))
    selected = tuple(
        item
        for item in datagrams
        if tuple(sorted((item.source, item.target))) == selected_key
    )
    if not selected:
        raise P78RejectedInput("VIP_FLOW_EMPTY")

    return analysis.client, analysis.device, selected


def _direction(item: CapturedDatagram, client: Endpoint, device: Endpoint) -> str:
    if item.source == client and item.target == device:
        return "CLIENT_TO_DEVICE"
    if item.source == device and item.target == client:
        return "DEVICE_TO_CLIENT"
    raise P78RejectedInput("VIP_FLOW_DIRECTION_MISMATCH")


def _runtime_packets_from_datagrams(
    datagrams: tuple[CapturedDatagram, ...],
    *,
    client: Endpoint,
    device: Endpoint,
) -> tuple[tuple[p77.WrappedRtpPacket, ...], int]:
    packets: list[p77.WrappedRtpPacket] = []
    residual = 0
    profiles: dict[tuple[str, int, int], tuple[int, int, int, int, int, int]] = {}

    for item in datagrams:
        if (
            _pseudotcp_segment(
                item.packet_number,
                item.timestamp,
                item.source,
                item.target,
                item.payload,
            )
            is not None
        ):
            continue
        if _stun_like(item.payload):
            continue

        direction = _direction(item, client, device)
        try:
            first = p77.parse_wrapped_rtp(
                item.payload,
                packet_number=item.packet_number,
                direction=direction,
            )
            key = (first.direction, first.ssrc, first.payload_type)
            packet = p77.parse_wrapped_rtp(
                item.payload,
                packet_number=item.packet_number,
                direction=direction,
                expected_profile=profiles.setdefault(key, first.wrapper_profile),
            )
        except p77.RejectedInput:
            residual += 1
            continue

        packets.append(packet)

    return tuple(packets), residual


def _run_command(
    command: list[str],
    *,
    timeout: int = DECODE_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _decode_probe(
    path: Path | None,
    *,
    output_dir: Path,
    enabled: bool,
) -> tuple[str, str, bool, int, str]:
    if not enabled:
        return "NOT_REQUESTED", "NOT_REQUESTED", False, 0, "NOT_REQUESTED"

    if path is None or not path.exists() or path.stat().st_size == 0:
        return "NOT_PROVEN", "NOT_PROVEN", False, 0, "NOT_PROVEN"

    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if ffprobe is None:
        return "UNAVAILABLE", "NOT_REACHED", False, 0, "NOT_PROVEN"
    if ffmpeg is None:
        return "NOT_REACHED", "UNAVAILABLE", False, 0, "NOT_PROVEN"

    probe = _run_command(
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
        ]
    )
    if (
        probe is None
        or probe.returncode != 0
        or "h264" not in probe.stdout.lower().split()
    ):
        return "NOT_PROVEN", "NOT_REACHED", False, 0, "NOT_PROVEN"

    decode = _run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-f",
            "h264",
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ]
    )
    if decode is None or decode.returncode != 0:
        return "PASS", "NOT_PROVEN", False, 0, "NOT_PROVEN"

    output_dir.mkdir(parents=True, exist_ok=True)
    jpeg_path = output_dir / "p78_live_capture.jpg"
    try:
        jpeg_path.unlink()
    except FileNotFoundError:
        pass

    jpeg = _run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-f",
            "h264",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(jpeg_path),
        ]
    )
    jpeg_ok = bool(
        jpeg is not None
        and jpeg.returncode == 0
        and jpeg_path.exists()
        and jpeg_path.stat().st_size > 0
    )
    if jpeg_ok:
        jpeg_path.chmod(0o600)
        return "PASS", "PASS", True, 1, "PASS"

    try:
        jpeg_path.unlink()
    except FileNotFoundError:
        pass
    return "PASS", "PASS", False, 0, "NOT_PROVEN"


def _classify_packets(
    packets: tuple[p77.WrappedRtpPacket, ...],
    *,
    residual_packets: int,
    output_dir: Path,
    pcap_linktype: int | None = None,
    decode: bool = False,
) -> VerificationResult:
    profiles = {packet.wrapper_profile for packet in packets}
    unknown = tuple(
        packet
        for packet in packets
        if packet.payload_type not in (p77.PT_H264, p77.PT_PCMA)
    )

    if residual_packets:
        raise P78RejectedInput("RESIDUAL_SELECTED_FLOW_UDP")
    if unknown:
        raise P78RejectedInput("UNKNOWN_PAYLOAD_TYPE")
    if not packets:
        raise P78RejectedInput("NO_OFFSET8_RTP")
    if len(profiles) != 1:
        raise P78RejectedInput("WRAPPER_PROFILE_INCONSISTENT")

    extraction = p77.extract_from_packets(
        packets,
        output_dir=output_dir,
        basename="p78_live_capture",
        residual_packets=residual_packets,
        extract_audio=False,
    )

    (
        ffprobe_status,
        ffmpeg_decode_status,
        jpeg_created,
        jpeg_count,
        decode_status,
    ) = _decode_probe(
        extraction.output_path,
        output_dir=output_dir,
        enabled=decode,
    )

    structural_ok = extraction.status == "PROVEN_OFFLINE"
    decode_ok = (not decode) or decode_status == "PASS"
    status = "PASS" if structural_ok and decode_ok else "NOT_PROVEN"

    return VerificationResult(
        status=status,
        pcap_linktype=pcap_linktype,
        wrapped_rtp_packets=len(packets),
        pt99_h264_packets=sum(
            1 for packet in packets if packet.payload_type == p77.PT_H264
        ),
        pt8_audio_packets=sum(
            1 for packet in packets if packet.payload_type == p77.PT_PCMA
        ),
        unknown_pt_packets=0,
        residual_packets=residual_packets,
        wrapper_profile_count=len(profiles),
        wrapper_profile_consistent=True,
        h264_status=extraction.status,
        h264_access_units=extraction.access_units,
        h264_rejected_units=extraction.rejected_units,
        h264_bytes=extraction.emitted_bytes,
        h264_sha256=(
            extraction.emitted_sha256 if extraction.emitted_bytes else "NONE"
        ),
        decode_requested=decode,
        ffprobe_status=ffprobe_status,
        ffmpeg_decode_status=ffmpeg_decode_status,
        scratch_jpeg_created=jpeg_created,
        scratch_jpeg_count=jpeg_count,
        decode_status=decode_status,
    )


def verify_packets(
    packets: tuple[p77.WrappedRtpPacket, ...],
    *,
    output_dir: Path,
    residual_packets: int = 0,
    decode: bool = False,
) -> VerificationResult:
    return _classify_packets(
        packets,
        residual_packets=residual_packets,
        output_dir=output_dir,
        decode=decode,
    )


def verify_pcap(
    path: Path,
    *,
    output_dir: Path,
    decode: bool = False,
) -> VerificationResult:
    try:
        linktype, packet_count, datagrams = _read_udp_datagrams(path)
        client, device, selected = _select_vip_datagrams(
            datagrams,
            linktype=linktype,
            packet_count=packet_count,
        )
        packets, residual = _runtime_packets_from_datagrams(
            selected,
            client=client,
            device=device,
        )
    except P78RejectedInput:
        raise
    except Exception as exc:
        raise P78RejectedInput(
            f"RUNTIME_PCAP_REJECTED_{type(exc).__name__}"
        ) from exc

    return _classify_packets(
        packets,
        residual_packets=residual,
        output_dir=output_dir,
        pcap_linktype=linktype,
        decode=decode,
    )


def report(result: VerificationResult) -> str:
    return "\n".join(
        (
            "=== COMELIT P78 LIVE CAPTURE VERIFIER ===",
            f"P78_H264_ORACLE={result.status}",
            (
                "P78_PCAP_LINKTYPE="
                f"{result.pcap_linktype if result.pcap_linktype is not None else 'DIRECT_PACKETS'}"
            ),
            f"P78_OFFSET8_RTP_PRESENT={'true' if result.wrapped_rtp_packets else 'false'}",
            f"P78_WRAPPED_RTP_PACKETS={result.wrapped_rtp_packets}",
            f"P78_PT99_H264_PACKETS={result.pt99_h264_packets}",
            f"P78_PT8_AUDIO_PACKETS={result.pt8_audio_packets}",
            f"P78_UNKNOWN_PT_PACKETS={result.unknown_pt_packets}",
            f"P78_OFFSET8_RESIDUAL_PACKETS={result.residual_packets}",
            f"P78_WRAPPER_PROFILE_COUNT={result.wrapper_profile_count}",
            (
                "P78_WRAPPER_PROFILE_CONSISTENT="
                f"{'true' if result.wrapper_profile_consistent else 'false'}"
            ),
            f"P78_H264_ACCESS_UNITS={result.h264_access_units}",
            f"P78_H264_REJECTED_ACCESS_UNITS={result.h264_rejected_units}",
            f"P78_H264_ANNEXB_BYTES={result.h264_bytes}",
            f"P78_H264_ANNEXB_SHA256={result.h264_sha256}",
            f"P78_DECODE_REQUESTED={'true' if result.decode_requested else 'false'}",
            f"P78_FFPROBE_STATUS={result.ffprobe_status}",
            f"P78_FFMPEG_DECODE_STATUS={result.ffmpeg_decode_status}",
            (
                "P78_SCRATCH_JPEG_CREATED="
                f"{'true' if result.scratch_jpeg_created else 'false'}"
            ),
            f"P78_SCRATCH_JPEG_COUNT={result.scratch_jpeg_count}",
            f"P78_DECODE_STATUS={result.decode_status}",
            "P78_RAW_PAYLOAD_EMITTED=false",
            "P78_HEX_PAYLOAD_EMITTED=false",
            "P78_BASE64_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "=== END COMELIT P78 LIVE CAPTURE VERIFIER ===",
        )
    )


def rejected_report(reason: str, *, decode_requested: bool) -> str:
    return "\n".join(
        (
            "=== COMELIT P78 LIVE CAPTURE VERIFIER ===",
            f"P78_H264_ORACLE=REJECTED_INPUT reason={reason}",
            "P78_OFFSET8_RTP_PRESENT=false",
            "P78_WRAPPED_RTP_PACKETS=0",
            "P78_UNKNOWN_PT_PACKETS=UNKNOWN",
            f"P78_DECODE_REQUESTED={'true' if decode_requested else 'false'}",
            "P78_FFPROBE_STATUS=NOT_REACHED",
            "P78_FFMPEG_DECODE_STATUS=NOT_REACHED",
            "P78_SCRATCH_JPEG_CREATED=false",
            "P78_SCRATCH_JPEG_COUNT=0",
            "P78_DECODE_STATUS=NOT_PROVEN",
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".p78-work/media-out"),
    )
    parser.add_argument("--decode", action="store_true")
    args = parser.parse_args(argv)

    if args.pcap is None:
        print("P78_H264_ORACLE=NOT_PROVIDED")
        print(f"P78_DECODE_REQUESTED={'true' if args.decode else 'false'}")
        print("P78_RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 0

    if not args.pcap.exists():
        print(
            rejected_report(
                "PCAP_NOT_FOUND",
                decode_requested=args.decode,
            )
        )
        return 2

    try:
        result = verify_pcap(
            args.pcap,
            output_dir=args.output_dir,
            decode=args.decode,
        )
    except P78RejectedInput as exc:
        print(
            rejected_report(
                str(exc),
                decode_requested=args.decode,
            )
        )
        return 2

    print(report(result))
    return 0 if result.status == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
