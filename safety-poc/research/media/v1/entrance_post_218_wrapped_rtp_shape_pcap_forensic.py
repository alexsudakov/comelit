#!/usr/bin/env python3
"""Offline wrapped-RTP structural forensic for opaque UDP after packet 218.

P56 proved that the opaque selected-flow traffic is not direct RTP-v2. This
analyzer checks whether RTP-v2 is present behind a short fixed prefix and
specifically whether RFC5766 TURN ChannelData framing explains the traffic.

It reports only structural metadata: candidate offset counts, anonymized
sequence-continuity totals, TURN ChannelData shape counts and inner RTP header
metadata. It never emits payload bytes, channel numbers, sequence values,
timestamps, SSRC values, endpoints or ports and performs no codec/H264/NAL
inspection. No network I/O is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    BOUNDARY_PACKET,
    SelectedDatagram,
    _read_selected_datagrams,
    _stun_like,
)
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape
from pseudotcp_pcap_handshake_forensic import _pseudotcp_segment, load_capture, select_vip_flow

MAX_RTP_OFFSET = 16
TIMELINE_LIMIT = 20
TURN_CHANNEL_MIN = 0x4000
TURN_CHANNEL_MAX = 0x7FFF


@dataclass(frozen=True)
class OffsetSummary:
    offset: int
    shaped_count: int
    shaped_bytes: int
    anon_stream_count: int
    seq_plus1: int
    seq_gap: int
    seq_duplicate: int


@dataclass(frozen=True)
class PacketMeta:
    packet_number: int
    delta_ms: float
    direction: str
    udp_len: int
    wrapper: str
    rtp_offset: int
    payload_type: int
    marker: bool
    header_len: int
    media_data_len: int


@dataclass(frozen=True)
class Result:
    opaque_count: int
    opaque_bytes: int
    offsets: tuple[OffsetSummary, ...]
    best_offset: int | None
    best_offset_count: int
    best_offset_seq_plus1: int
    turn_shaped_count: int
    turn_shaped_bytes: int
    turn_inner_rtp_count: int
    turn_inner_rtp_bytes: int
    turn_inner_rtp_seq_plus1: int
    turn_inner_rtp_seq_gap: int
    turn_inner_rtp_seq_duplicate: int
    timeline: tuple[PacketMeta, ...]


def _direction(item: SelectedDatagram, client, device) -> str:
    if item.source == client and item.target == device:
        return "CLIENT_TO_DEVICE"
    if item.source == device and item.target == client:
        return "DEVICE_TO_CLIENT"
    raise ValueError("selected-flow direction mismatch")


def _opaque(datagrams: tuple[SelectedDatagram, ...], boundary_packet: int) -> tuple[SelectedDatagram, ...]:
    out: list[SelectedDatagram] = []
    for item in datagrams:
        if item.packet_number <= boundary_packet:
            continue
        if _pseudotcp_segment(item.packet_number, item.timestamp, item.source, item.target, item.payload) is not None:
            continue
        if _stun_like(item.payload):
            continue
        out.append(item)
    return tuple(out)


def _sequence_totals(items: list[tuple[str, object]]) -> tuple[int, int, int, int]:
    grouped: dict[tuple[str, int, int], list[object]] = {}
    for direction, meta in items:
        grouped.setdefault((direction, meta.ssrc, meta.payload_type), []).append(meta)

    plus1 = gaps = duplicates = 0
    stream_count = 0
    for metas in grouped.values():
        if len(metas) >= 2:
            stream_count += 1
        previous: int | None = None
        for meta in metas:
            if previous is not None:
                delta = (meta.sequence - previous) & 0xFFFF
                if delta == 1:
                    plus1 += 1
                elif delta == 0:
                    duplicates += 1
                else:
                    gaps += 1
            previous = meta.sequence
    return stream_count, plus1, gaps, duplicates


def _turn_channeldata(payload: bytes) -> tuple[bytes, int] | None:
    if len(payload) < 4:
        return None
    channel = int.from_bytes(payload[0:2], "big")
    if not (TURN_CHANNEL_MIN <= channel <= TURN_CHANNEL_MAX):
        return None
    declared = int.from_bytes(payload[2:4], "big")
    remaining = len(payload) - 4
    if declared <= 0 or declared > remaining:
        return None
    trailing = remaining - declared
    if trailing > 3:
        return None
    return payload[4 : 4 + declared], trailing


def analyze(
    datagrams: tuple[SelectedDatagram, ...],
    *,
    client,
    device,
    boundary_packet: int = BOUNDARY_PACKET,
) -> Result:
    boundary = [item for item in datagrams if item.packet_number == boundary_packet]
    if len(boundary) != 1:
        raise ValueError("expected exactly one selected-flow boundary datagram")
    boundary_ts = boundary[0].timestamp
    opaque = _opaque(datagrams, boundary_packet)

    offset_summaries: list[OffsetSummary] = []
    offset_items: dict[int, list[tuple[str, object, SelectedDatagram]]] = {}
    for offset in range(MAX_RTP_OFFSET + 1):
        found: list[tuple[str, object, SelectedDatagram]] = []
        for item in opaque:
            if len(item.payload) <= offset:
                continue
            meta = _parse_rtp_v2_shape(item.payload[offset:])
            if meta is None:
                continue
            found.append((_direction(item, client, device), meta, item))
        offset_items[offset] = found
        streams, plus1, gaps, duplicates = _sequence_totals([(d, m) for d, m, _ in found])
        offset_summaries.append(
            OffsetSummary(
                offset=offset,
                shaped_count=len(found),
                shaped_bytes=sum(len(item.payload) for _, _, item in found),
                anon_stream_count=streams,
                seq_plus1=plus1,
                seq_gap=gaps,
                seq_duplicate=duplicates,
            )
        )

    ranked = sorted(
        offset_summaries,
        key=lambda x: (x.seq_plus1, x.anon_stream_count, x.shaped_count, -x.offset),
        reverse=True,
    )
    best = ranked[0] if ranked and ranked[0].shaped_count else None

    turn_shaped: list[SelectedDatagram] = []
    turn_inner: list[tuple[str, object, SelectedDatagram]] = []
    for item in opaque:
        parsed = _turn_channeldata(item.payload)
        if parsed is None:
            continue
        inner, _trailing = parsed
        turn_shaped.append(item)
        rtp = _parse_rtp_v2_shape(inner)
        if rtp is not None:
            turn_inner.append((_direction(item, client, device), rtp, item))

    _turn_streams, turn_plus1, turn_gaps, turn_duplicates = _sequence_totals(
        [(d, m) for d, m, _ in turn_inner]
    )

    timeline_source: list[PacketMeta] = []
    if turn_inner:
        for direction, meta, item in turn_inner[:TIMELINE_LIMIT]:
            timeline_source.append(
                PacketMeta(
                    packet_number=item.packet_number,
                    delta_ms=(item.timestamp - boundary_ts) * 1000.0,
                    direction=direction,
                    udp_len=len(item.payload),
                    wrapper="TURN_CHANNELDATA",
                    rtp_offset=4,
                    payload_type=meta.payload_type,
                    marker=meta.marker,
                    header_len=meta.header_length,
                    media_data_len=meta.media_data_length,
                )
            )
    elif best is not None:
        for direction, meta, item in offset_items[best.offset][:TIMELINE_LIMIT]:
            timeline_source.append(
                PacketMeta(
                    packet_number=item.packet_number,
                    delta_ms=(item.timestamp - boundary_ts) * 1000.0,
                    direction=direction,
                    udp_len=len(item.payload),
                    wrapper="FIXED_PREFIX",
                    rtp_offset=best.offset,
                    payload_type=meta.payload_type,
                    marker=meta.marker,
                    header_len=meta.header_length,
                    media_data_len=meta.media_data_length,
                )
            )

    return Result(
        opaque_count=len(opaque),
        opaque_bytes=sum(len(item.payload) for item in opaque),
        offsets=tuple(offset_summaries),
        best_offset=best.offset if best else None,
        best_offset_count=best.shaped_count if best else 0,
        best_offset_seq_plus1=best.seq_plus1 if best else 0,
        turn_shaped_count=len(turn_shaped),
        turn_shaped_bytes=sum(len(item.payload) for item in turn_shaped),
        turn_inner_rtp_count=len(turn_inner),
        turn_inner_rtp_bytes=sum(len(item.payload) for _, _, item in turn_inner),
        turn_inner_rtp_seq_plus1=turn_plus1,
        turn_inner_rtp_seq_gap=turn_gaps,
        turn_inner_rtp_seq_duplicate=turn_duplicates,
        timeline=tuple(timeline_source),
    )


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE POST-218 WRAPPED RTP SHAPE PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"OPAQUE_INPUT_COUNT={result.opaque_count}",
        f"OPAQUE_INPUT_BYTES={result.opaque_bytes}",
    ]
    for item in result.offsets:
        lines.append(
            "RTP_OFFSET_CANDIDATE "
            f"offset={item.offset} shaped_count={item.shaped_count} shaped_bytes={item.shaped_bytes} "
            f"anon_stream_count={item.anon_stream_count} seq_plus1={item.seq_plus1} "
            f"seq_gap={item.seq_gap} seq_duplicate={item.seq_duplicate}"
        )
    lines.extend(
        [
            f"BEST_RTP_OFFSET={result.best_offset if result.best_offset is not None else 'NONE'}",
            f"BEST_RTP_OFFSET_SHAPED_COUNT={result.best_offset_count}",
            f"BEST_RTP_OFFSET_SEQ_PLUS1={result.best_offset_seq_plus1}",
            f"TURN_CHANNELDATA_SHAPED_COUNT={result.turn_shaped_count}",
            f"TURN_CHANNELDATA_SHAPED_BYTES={result.turn_shaped_bytes}",
            f"TURN_CHANNELDATA_INNER_RTP_COUNT={result.turn_inner_rtp_count}",
            f"TURN_CHANNELDATA_INNER_RTP_BYTES={result.turn_inner_rtp_bytes}",
            f"TURN_CHANNELDATA_INNER_RTP_SEQ_PLUS1={result.turn_inner_rtp_seq_plus1}",
            f"TURN_CHANNELDATA_INNER_RTP_SEQ_GAP={result.turn_inner_rtp_seq_gap}",
            f"TURN_CHANNELDATA_INNER_RTP_SEQ_DUPLICATE={result.turn_inner_rtp_seq_duplicate}",
        ]
    )
    for ordinal, item in enumerate(result.timeline, start=1):
        lines.append(
            "WRAPPED_RTP_PACKET_META "
            f"ordinal={ordinal} packet={item.packet_number} delta_ms={item.delta_ms:.3f} "
            f"direction={item.direction} udp_len={item.udp_len} wrapper={item.wrapper} "
            f"rtp_offset={item.rtp_offset} payload_type={item.payload_type} "
            f"marker={'true' if item.marker else 'false'} header_len={item.header_len} "
            f"media_data_len={item.media_data_len}"
        )
    lines.extend(
        [
            "TURN_CHANNEL_VALUES_EMITTED=false",
            "SEQUENCE_VALUES_EMITTED=false",
            "TIMESTAMP_VALUES_EMITTED=false",
            "SSRC_VALUES_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PORTS_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "H264_INSPECTION_PERFORMED=false",
            "NAL_INSPECTION_PERFORMED=false",
            "CODEC_IDENTIFICATION_PERFORMED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE POST-218 WRAPPED RTP SHAPE PCAP FORENSIC ===",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    analysis = select_vip_flow(capture)
    try:
        datagrams = _read_selected_datagrams(args.pcap, client=analysis.client, device=analysis.device)
        result = analyze(datagrams, client=analysis.client, device=analysis.device)
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
