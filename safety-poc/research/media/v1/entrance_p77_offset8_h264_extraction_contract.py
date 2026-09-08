#!/usr/bin/env python3
"""P77 offline offset-8 RTP/H264 extraction contract.

This module is intentionally offline-only. It can depacketize synthetic
fixtures by default and can optionally consume the SHA-gated frozen capture.
Extracted media is written only to a caller supplied
scratch directory, never to the repository, and reports contain semantic
counts/hashes only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    BOUNDARY_PACKET,
    SelectedDatagram,
    _read_selected_datagrams,
)
from entrance_post_218_rtp_v2_shape_pcap_forensic import RtpHeaderMeta, _parse_rtp_v2_shape
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _direction, _opaque
from pseudotcp_pcap_handshake_forensic import load_capture, select_vip_flow

RTP_OFFSET = 8
PT_PCMA = 8
PT_H264 = 99
ANNEX_B_START = b"\x00\x00\x00\x01"


class RejectedInput(ValueError):
    """Raised when a packet shape would require guessing media bytes."""


@dataclass(frozen=True)
class WrappedRtpPacket:
    packet_number: int
    direction: str
    wrapper_profile: tuple[int, int, int, int, int, int]
    payload_type: int
    marker: bool
    sequence: int
    timestamp: int
    ssrc: int
    media: bytes


@dataclass(frozen=True)
class AccessUnit:
    timestamp: int
    nal_count: int
    annexb: bytes
    marker_closed: bool
    split_after_gap: bool


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    input_packets: int
    h264_packets: int
    audio_packets: int
    residual_packets: int
    access_units: int
    rejected_units: int
    sequence_gaps: int
    timestamp_discontinuities: int
    emitted_bytes: int
    emitted_sha256: str
    output_path: Path | None
    audio_bytes: int
    audio_sha256: str
    audio_output_path: Path | None


def _wrapper_profile(prefix: bytes) -> tuple[int, int, int, int, int, int]:
    if len(prefix) != RTP_OFFSET:
        raise RejectedInput("WRAPPER_TRUNCATED")
    return (prefix[0], prefix[1], prefix[4], prefix[5], prefix[6], prefix[7])


def parse_wrapped_rtp(
    payload: bytes,
    *,
    packet_number: int = 0,
    direction: str = "UNKNOWN",
    expected_profile: tuple[int, int, int, int, int, int] | None = None,
) -> WrappedRtpPacket:
    if len(payload) < RTP_OFFSET:
        raise RejectedInput("WRAPPER_TRUNCATED")
    prefix = payload[:RTP_OFFSET]
    claimed_inner_len = int.from_bytes(prefix[2:4], "little")
    inner = payload[RTP_OFFSET:]
    if claimed_inner_len != len(inner):
        raise RejectedInput("WRAPPER_LENGTH_MISMATCH")
    profile = _wrapper_profile(prefix)
    if expected_profile is not None and profile != expected_profile:
        raise RejectedInput("WRAPPER_PROFILE_MISMATCH")

    meta = _parse_rtp_v2_shape(inner)
    if meta is None:
        raise RejectedInput("RTP_HEADER_REJECTED")
    media_end = meta.header_length + meta.media_data_length
    return WrappedRtpPacket(
        packet_number=packet_number,
        direction=direction,
        wrapper_profile=profile,
        payload_type=meta.payload_type,
        marker=meta.marker,
        sequence=meta.sequence,
        timestamp=int.from_bytes(inner[4:8], "big"),
        ssrc=meta.ssrc,
        media=inner[meta.header_length:media_end],
    )


def _stap_a_nals(media: bytes) -> list[bytes]:
    pos = 1
    nals: list[bytes] = []
    while pos < len(media):
        if pos + 2 > len(media):
            raise RejectedInput("STAP_A_LENGTH_TRUNCATED")
        size = int.from_bytes(media[pos:pos + 2], "big")
        pos += 2
        if size <= 0 or pos + size > len(media):
            raise RejectedInput("STAP_A_NAL_TRUNCATED")
        nal = media[pos:pos + size]
        if not 1 <= (nal[0] & 0x1F) <= 23:
            raise RejectedInput("STAP_A_INNER_NAL_REJECTED")
        nals.append(nal)
        pos += size
    if not nals:
        raise RejectedInput("STAP_A_EMPTY")
    return nals


def _append_annexb(nals: Iterable[bytes]) -> bytes:
    out = bytearray()
    for nal in nals:
        out += ANNEX_B_START
        out += nal
    return bytes(out)


def reconstruct_h264_access_units(packets: Iterable[WrappedRtpPacket]) -> tuple[AccessUnit, int, int, int]:
    ordered = sorted((p for p in packets if p.payload_type == PT_H264), key=lambda p: p.packet_number)
    units: list[AccessUnit] = []
    current_nals: list[bytes] = []
    current_ts: int | None = None
    fu_parts: list[bytes] = []
    fu_started = False
    fu_header_byte: int | None = None
    rejected_units = 0
    sequence_gaps = 0
    timestamp_discontinuities = 0
    previous_seq: int | None = None

    def reject_current() -> None:
        nonlocal current_nals, current_ts, fu_parts, fu_started, fu_header_byte, rejected_units
        if current_nals or fu_parts or fu_started:
            rejected_units += 1
        current_nals = []
        current_ts = None
        fu_parts = []
        fu_started = False
        fu_header_byte = None

    def reject_packet_or_current() -> None:
        nonlocal rejected_units
        had_open = bool(current_nals or fu_parts or fu_started)
        reject_current()
        if not had_open:
            rejected_units += 1

    def close_current(marker_closed: bool, split_after_gap: bool = False) -> None:
        nonlocal current_nals, current_ts
        if current_ts is None or not current_nals:
            return
        units.append(
            AccessUnit(
                timestamp=current_ts,
                nal_count=len(current_nals),
                annexb=_append_annexb(current_nals),
                marker_closed=marker_closed,
                split_after_gap=split_after_gap,
            )
        )
        current_nals = []
        current_ts = None

    for packet in ordered:
        if previous_seq is not None and ((packet.sequence - previous_seq) & 0xFFFF) != 1:
            sequence_gaps += 1
            reject_current()
        previous_seq = packet.sequence

        if current_ts is not None and packet.timestamp != current_ts:
            timestamp_discontinuities += 1
            reject_current()
        if current_ts is None:
            current_ts = packet.timestamp

        media = packet.media
        if not media:
            reject_current()
            continue
        nal_type = media[0] & 0x1F

        try:
            if 1 <= nal_type <= 23:
                if fu_started:
                    raise RejectedInput("SINGLE_NAL_DURING_OPEN_FU")
                current_nals.append(media)
            elif nal_type == 24:
                if fu_started:
                    raise RejectedInput("STAP_A_DURING_OPEN_FU")
                current_nals.extend(_stap_a_nals(media))
            elif nal_type == 28:
                if len(media) < 3:
                    raise RejectedInput("FU_A_TRUNCATED")
                fu_indicator = media[0]
                fu_header = media[1]
                original_type = fu_header & 0x1F
                start = bool(fu_header & 0x80)
                end = bool(fu_header & 0x40)
                if not 1 <= original_type <= 23:
                    raise RejectedInput("FU_A_ORIGINAL_TYPE_REJECTED")
                if start:
                    if fu_started:
                        raise RejectedInput("FU_A_START_DURING_OPEN_FU")
                    fu_header_byte = (fu_indicator & 0xE0) | original_type
                    fu_parts = [bytes([fu_header_byte]), media[2:]]
                    fu_started = True
                else:
                    if not fu_started:
                        raise RejectedInput("FU_A_MISSING_START")
                    fu_parts.append(media[2:])
                if end:
                    if not fu_started or fu_header_byte is None:
                        raise RejectedInput("FU_A_END_WITHOUT_START")
                    current_nals.append(b"".join(fu_parts))
                    fu_parts = []
                    fu_started = False
                    fu_header_byte = None
            else:
                raise RejectedInput("H264_PACKETIZATION_UNKNOWN")
        except RejectedInput:
            reject_packet_or_current()
            continue

        if packet.marker:
            if fu_started:
                reject_current()
            else:
                close_current(marker_closed=True)

    if fu_started:
        reject_current()
    elif current_nals:
        rejected_units += 1

    return tuple(units), rejected_units, sequence_gaps, timestamp_discontinuities


def packets_from_datagrams(datagrams: tuple[SelectedDatagram, ...], *, client, device) -> tuple[WrappedRtpPacket, int]:
    packets: list[WrappedRtpPacket] = []
    residual = 0
    profiles: dict[tuple[str, int, int], tuple[int, int, int, int, int, int]] = {}
    for item in _opaque(datagrams, BOUNDARY_PACKET):
        direction = _direction(item, client, device)
        try:
            first = parse_wrapped_rtp(item.payload, packet_number=item.packet_number, direction=direction)
            key = (first.direction, first.ssrc, first.payload_type)
            packet = parse_wrapped_rtp(
                item.payload,
                packet_number=item.packet_number,
                direction=direction,
                expected_profile=profiles.setdefault(key, first.wrapper_profile),
            )
        except RejectedInput:
            residual += 1
            continue
        packets.append(packet)
    return tuple(packets), residual


def write_h264_annexb(units: Iterable[AccessUnit], output_path: Path) -> tuple[int, str]:
    blob = b"".join(unit.annexb for unit in units)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    output_path.chmod(0o600)
    return len(blob), hashlib.sha256(blob).hexdigest()


def write_pcma_payload(packets: Iterable[WrappedRtpPacket], output_path: Path) -> tuple[int, str]:
    blob = b"".join(packet.media for packet in sorted(packets, key=lambda p: p.packet_number) if packet.payload_type == PT_PCMA)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    output_path.chmod(0o600)
    return len(blob), hashlib.sha256(blob).hexdigest()


def extract_from_packets(
    packets: tuple[WrappedRtpPacket, ...],
    *,
    output_dir: Path,
    basename: str = "p77_self_activation",
    residual_packets: int = 0,
    extract_audio: bool = False,
) -> ExtractionResult:
    video = tuple(p for p in packets if p.payload_type == PT_H264 and p.direction == "DEVICE_TO_CLIENT")
    audio = tuple(p for p in packets if p.payload_type == PT_PCMA and p.direction == "DEVICE_TO_CLIENT")
    units, rejected, gaps, ts_disc = reconstruct_h264_access_units(video)
    h264_path = output_dir / f"{basename}.h264"
    emitted_bytes, emitted_sha = write_h264_annexb(units, h264_path)
    audio_bytes = 0
    audio_sha = "NOT_EXTRACTED"
    audio_path = None
    if extract_audio:
        audio_path = output_dir / f"{basename}.d2c.alaw"
        audio_bytes, audio_sha = write_pcma_payload(audio, audio_path)
    status = "PROVEN_OFFLINE" if units and emitted_bytes else "NOT_PROVEN"
    return ExtractionResult(
        status=status,
        input_packets=len(packets) + residual_packets,
        h264_packets=len(video),
        audio_packets=len(audio),
        residual_packets=residual_packets,
        access_units=len(units),
        rejected_units=rejected,
        sequence_gaps=gaps,
        timestamp_discontinuities=ts_disc,
        emitted_bytes=emitted_bytes,
        emitted_sha256=emitted_sha,
        output_path=h264_path,
        audio_bytes=audio_bytes,
        audio_sha256=audio_sha,
        audio_output_path=audio_path,
    )


def report(result: ExtractionResult) -> str:
    lines = [
        "=== COMELIT P77 OFFSET8 RTP H264 EXTRACTION CONTRACT ===",
        f"H264_EXTRACTION={result.status}",
        f"WRAPPED_RTP_INPUT_PACKETS={result.input_packets}",
        f"PT99_H264_PACKETS={result.h264_packets}",
        f"PT8_D2C_AUDIO_PACKETS={result.audio_packets}",
        f"OFFSET8_RESIDUAL_OR_REJECTED_PACKETS={result.residual_packets}",
        f"H264_ACCESS_UNITS={result.access_units}",
        f"H264_REJECTED_ACCESS_UNITS={result.rejected_units}",
        f"RTP_SEQUENCE_GAPS={result.sequence_gaps}",
        f"RTP_TIMESTAMP_DISCONTINUITIES={result.timestamp_discontinuities}",
        f"H264_ANNEXB_BYTES={result.emitted_bytes}",
        f"H264_ANNEXB_SHA256={result.emitted_sha256 if result.emitted_bytes else 'NONE'}",
        f"H264_OUTPUT_WRITTEN={'true' if result.output_path else 'false'}",
        f"PT8_D2C_ALAW_BYTES={result.audio_bytes}",
        f"PT8_D2C_ALAW_SHA256={result.audio_sha256 if result.audio_bytes else 'NONE'}",
        "RAW_PAYLOAD_EMITTED=false",
        "HEX_PAYLOAD_EMITTED=false",
        "BASE64_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "LIVE_TRANSMISSION_AUTHORIZED=false",
        "DOOR_ACTION_SENT=false",
        "SELF_ACTIVATION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "ACK_SIGNALING_SENT=false",
        "=== END COMELIT P77 OFFSET8 RTP H264 EXTRACTION CONTRACT ===",
    ]
    return "\n".join(lines)


def extract_from_pcap(path: Path, output_dir: Path, *, extract_audio: bool = False) -> ExtractionResult:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_PCAP_SHA256:
        raise RejectedInput("PCAP_SHA256_GATE_FAIL")
    capture = load_capture(path)
    analysis = select_vip_flow(capture)
    datagrams = _read_selected_datagrams(path, client=analysis.client, device=analysis.device)
    packets, residual = packets_from_datagrams(datagrams, client=analysis.client, device=analysis.device)
    return extract_from_packets(packets, output_dir=output_dir, residual_packets=residual, extract_audio=extract_audio)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".p77-work/media-out"))
    parser.add_argument("--extract-audio", action="store_true")
    args = parser.parse_args(argv)

    if args.pcap is None:
        print("PCAP_SHA256_GATE=NOT_PROVIDED")
        print("H264_EXTRACTION=NOT_PROVIDED")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 0
    if not args.pcap.exists():
        print("PCAP_SHA256_GATE=NOT_PROVIDED")
        print("H264_EXTRACTION=NOT_PROVIDED")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 0
    try:
        result = extract_from_pcap(args.pcap, args.output_dir, extract_audio=args.extract_audio)
    except RejectedInput as exc:
        print(f"H264_EXTRACTION=REJECTED_INPUT reason={exc}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 2
    print("PCAP_SHA256_GATE=PASS")
    print(report(result))
    return 0 if result.status == "PROVEN_OFFLINE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
