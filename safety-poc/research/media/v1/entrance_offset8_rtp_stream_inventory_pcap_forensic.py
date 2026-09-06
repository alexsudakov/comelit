#!/usr/bin/env python3
"""Offline inventory for the fixed 8-byte wrapper and inner RTP streams.

P57 proved that almost every opaque post-218 datagram contains a structurally
valid RTP-v2 packet at byte offset 8 with strong sequence continuity. This
analyzer treats offset 8 as the frozen forensic candidate and reports only:
wrapper byte-position cardinality, anonymous RTP stream metadata, sequence and
timestamp-delta continuity, timing/length statistics, and residual datagrams.

It does not emit wrapper byte values, RTP sequence/timestamp/SSRC values,
endpoints, ports, payload bytes, codec identities, H264 or NAL information.
No network I/O is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
from statistics import median

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    BOUNDARY_PACKET,
    SelectedDatagram,
    _read_selected_datagrams,
)
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _direction, _opaque
from pseudotcp_pcap_handshake_forensic import load_capture, select_vip_flow

RTP_OFFSET = 8
RESIDUAL_TIMELINE_LIMIT = 12


@dataclass(frozen=True)
class WrapperByteStat:
    position: int
    unique_values: int


@dataclass(frozen=True)
class StreamStat:
    ordinal: int
    direction: str
    payload_type: int
    packet_count: int
    udp_bytes: int
    media_data_bytes: int
    marker_count: int
    first_packet: int
    last_packet: int
    first_delta_ms: float
    last_delta_ms: float
    udp_len_min: int
    udp_len_max: int
    media_len_min: int
    media_len_max: int
    interarrival_median_ms: float
    seq_plus1: int
    seq_gap: int
    seq_duplicate: int
    ts_delta_mode: int | None
    ts_delta_mode_count: int
    ts_delta_distinct: int


@dataclass(frozen=True)
class ResidualMeta:
    packet_number: int
    delta_ms: float
    direction: str
    udp_len: int


@dataclass(frozen=True)
class Result:
    opaque_count: int
    opaque_bytes: int
    shaped_count: int
    shaped_bytes: int
    shaped_media_bytes: int
    residual_count: int
    residual_bytes: int
    wrapper_distinct_prefixes: int
    wrapper_stats: tuple[WrapperByteStat, ...]
    streams: tuple[StreamStat, ...]
    residual_client_count: int
    residual_device_count: int
    residual_timeline: tuple[ResidualMeta, ...]


def _sequence_counts(metas) -> tuple[int, int, int]:
    plus1 = gaps = duplicates = 0
    previous = None
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
    return plus1, gaps, duplicates


def _timestamp_delta_stats(timestamps: list[int]) -> tuple[int | None, int, int]:
    deltas: list[int] = []
    previous: int | None = None
    for value in timestamps:
        if previous is not None:
            deltas.append((value - previous) & 0xFFFFFFFF)
        previous = value
    if not deltas:
        return None, 0, 0
    counts = Counter(deltas)
    mode_delta, mode_count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return mode_delta, mode_count, len(counts)


def _rtp_timestamp(payload: bytes) -> int:
    start = RTP_OFFSET + 4
    end = RTP_OFFSET + 8
    if len(payload) < end:
        raise ValueError("offset8 RTP timestamp field is truncated")
    return int.from_bytes(payload[start:end], "big")


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

    shaped: list[tuple[SelectedDatagram, str, object, int]] = []
    residual: list[SelectedDatagram] = []
    for item in opaque:
        if len(item.payload) <= RTP_OFFSET:
            residual.append(item)
            continue
        meta = _parse_rtp_v2_shape(item.payload[RTP_OFFSET:])
        if meta is None:
            residual.append(item)
            continue
        shaped.append((item, _direction(item, client, device), meta, _rtp_timestamp(item.payload)))

    wrapper_stats = tuple(
        WrapperByteStat(position=pos, unique_values=len({item.payload[pos] for item, _, _, _ in shaped}))
        for pos in range(RTP_OFFSET)
    )
    wrapper_distinct_prefixes = len({item.payload[:RTP_OFFSET] for item, _, _, _ in shaped})

    grouped: dict[tuple[str, int, int], list[tuple[SelectedDatagram, object, int]]] = {}
    for item, flow_direction, meta, rtp_timestamp in shaped:
        grouped.setdefault((flow_direction, meta.ssrc, meta.payload_type), []).append(
            (item, meta, rtp_timestamp)
        )

    ordered_groups = sorted(
        grouped.items(),
        key=lambda pair: min(item.packet_number for item, _, _ in pair[1]),
    )
    streams: list[StreamStat] = []
    for ordinal, ((flow_direction, _ssrc, payload_type), pairs) in enumerate(ordered_groups, start=1):
        pairs = sorted(pairs, key=lambda pair: pair[0].packet_number)
        items = [item for item, _, _ in pairs]
        metas = [meta for _, meta, _ in pairs]
        rtp_timestamps = [value for _, _, value in pairs]
        plus1, gaps, duplicates = _sequence_counts(metas)
        ts_mode, ts_mode_count, ts_distinct = _timestamp_delta_stats(rtp_timestamps)
        interarrival = [
            (items[index].timestamp - items[index - 1].timestamp) * 1000.0
            for index in range(1, len(items))
        ]
        udp_lengths = [len(item.payload) for item in items]
        media_lengths = [meta.media_data_length for meta in metas]
        streams.append(
            StreamStat(
                ordinal=ordinal,
                direction=flow_direction,
                payload_type=payload_type,
                packet_count=len(items),
                udp_bytes=sum(udp_lengths),
                media_data_bytes=sum(media_lengths),
                marker_count=sum(1 for meta in metas if meta.marker),
                first_packet=items[0].packet_number,
                last_packet=items[-1].packet_number,
                first_delta_ms=(items[0].timestamp - boundary_ts) * 1000.0,
                last_delta_ms=(items[-1].timestamp - boundary_ts) * 1000.0,
                udp_len_min=min(udp_lengths),
                udp_len_max=max(udp_lengths),
                media_len_min=min(media_lengths),
                media_len_max=max(media_lengths),
                interarrival_median_ms=float(median(interarrival)) if interarrival else 0.0,
                seq_plus1=plus1,
                seq_gap=gaps,
                seq_duplicate=duplicates,
                ts_delta_mode=ts_mode,
                ts_delta_mode_count=ts_mode_count,
                ts_delta_distinct=ts_distinct,
            )
        )

    residual_client = [item for item in residual if _direction(item, client, device) == "CLIENT_TO_DEVICE"]
    residual_device = [item for item in residual if _direction(item, client, device) == "DEVICE_TO_CLIENT"]
    residual_timeline = tuple(
        ResidualMeta(
            packet_number=item.packet_number,
            delta_ms=(item.timestamp - boundary_ts) * 1000.0,
            direction=_direction(item, client, device),
            udp_len=len(item.payload),
        )
        for item in residual[:RESIDUAL_TIMELINE_LIMIT]
    )

    return Result(
        opaque_count=len(opaque),
        opaque_bytes=sum(len(item.payload) for item in opaque),
        shaped_count=len(shaped),
        shaped_bytes=sum(len(item.payload) for item, _, _, _ in shaped),
        shaped_media_bytes=sum(meta.media_data_length for _, _, meta, _ in shaped),
        residual_count=len(residual),
        residual_bytes=sum(len(item.payload) for item in residual),
        wrapper_distinct_prefixes=wrapper_distinct_prefixes,
        wrapper_stats=wrapper_stats,
        streams=tuple(streams),
        residual_client_count=len(residual_client),
        residual_device_count=len(residual_device),
        residual_timeline=residual_timeline,
    )


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE OFFSET8 RTP STREAM INVENTORY PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"RTP_OFFSET={RTP_OFFSET}",
        f"OPAQUE_INPUT_COUNT={result.opaque_count}",
        f"OPAQUE_INPUT_BYTES={result.opaque_bytes}",
        f"OFFSET8_RTP_COUNT={result.shaped_count}",
        f"OFFSET8_RTP_UDP_BYTES={result.shaped_bytes}",
        f"OFFSET8_RTP_MEDIA_DATA_BYTES={result.shaped_media_bytes}",
        f"OFFSET8_RESIDUAL_COUNT={result.residual_count}",
        f"OFFSET8_RESIDUAL_BYTES={result.residual_bytes}",
        f"OFFSET8_COUNT_RECONCILED={'true' if result.shaped_count + result.residual_count == result.opaque_count else 'false'}",
        f"OFFSET8_BYTES_RECONCILED={'true' if result.shaped_bytes + result.residual_bytes == result.opaque_bytes else 'false'}",
        f"WRAPPER_DISTINCT_PREFIX_COUNT={result.wrapper_distinct_prefixes}",
        f"RTP_ANON_STREAM_COUNT={len(result.streams)}",
        f"RESIDUAL_CLIENT_COUNT={result.residual_client_count}",
        f"RESIDUAL_DEVICE_COUNT={result.residual_device_count}",
    ]
    for stat in result.wrapper_stats:
        lines.append(
            "WRAPPER_BYTE_POSITION "
            f"position={stat.position} unique_values={stat.unique_values} "
            f"constant={'true' if stat.unique_values == 1 else 'false'}"
        )
    for stream in result.streams:
        ts_mode = stream.ts_delta_mode if stream.ts_delta_mode is not None else "NONE"
        lines.append(
            "RTP_ANON_STREAM "
            f"ordinal={stream.ordinal} direction={stream.direction} payload_type={stream.payload_type} "
            f"packet_count={stream.packet_count} udp_bytes={stream.udp_bytes} "
            f"media_data_bytes={stream.media_data_bytes} marker_count={stream.marker_count} "
            f"first_packet={stream.first_packet} last_packet={stream.last_packet} "
            f"first_delta_ms={stream.first_delta_ms:.3f} last_delta_ms={stream.last_delta_ms:.3f} "
            f"udp_len_min={stream.udp_len_min} udp_len_max={stream.udp_len_max} "
            f"media_len_min={stream.media_len_min} media_len_max={stream.media_len_max} "
            f"interarrival_median_ms={stream.interarrival_median_ms:.3f} "
            f"seq_plus1={stream.seq_plus1} seq_gap={stream.seq_gap} seq_duplicate={stream.seq_duplicate} "
            f"timestamp_delta_mode={ts_mode} timestamp_delta_mode_count={stream.ts_delta_mode_count} "
            f"timestamp_delta_distinct={stream.ts_delta_distinct}"
        )
    for ordinal, item in enumerate(result.residual_timeline, start=1):
        lines.append(
            "OFFSET8_RESIDUAL_META "
            f"ordinal={ordinal} packet={item.packet_number} delta_ms={item.delta_ms:.3f} "
            f"direction={item.direction} udp_len={item.udp_len}"
        )
    lines.extend([
        "WRAPPER_BYTE_VALUES_EMITTED=false",
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
        "=== END COMELIT ENTRANCE OFFSET8 RTP STREAM INVENTORY PCAP FORENSIC ===",
    ])
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
