#!/usr/bin/env python3
"""Offline PseudoTCP stream characterization after entrance packet 218.

P53 proved that the selected ViP UDP flow continues after packet 218 with a
large amount of traffic while P52 proved that no additional ViP application
frame is reconstructed after that boundary. This analyzer stays at the
PseudoTCP transport layer and characterizes data-bearing segments only.

It reports counts, byte totals, directionality, payload-length buckets,
transport flags, exact retransmission counts and a short length/timing timeline.
It never emits sequence values, endpoints, ports, payload bytes, hashes of
payload bytes, media signatures, RTP/H264 classification or codec information.

No network I/O is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from pseudotcp_pcap_handshake_forensic import (
    FlowAnalysis,
    PSEUDOTCP_FLAG_CTL,
    PSEUDOTCP_FLAG_FIN,
    PSEUDOTCP_FLAG_RST,
    PseudoTcpSegment,
    direction,
    load_capture,
    select_vip_flow,
)


BOUNDARY_PACKET = 218
TIMELINE_LIMIT = 20


@dataclass(frozen=True)
class SegmentMeta:
    packet_number: int
    delta_ms: float
    direction: str
    data_length: int
    flags: int
    exact_retransmit: bool


@dataclass(frozen=True)
class StreamResult:
    boundary_timestamp: float
    post_segment_count: int
    app_segment_count: int
    app_bytes_wire: int
    unique_app_segment_count: int
    unique_app_bytes: int
    retransmit_segment_count: int
    retransmit_bytes: int
    client_app_segments: int
    client_app_bytes: int
    device_app_segments: int
    device_app_bytes: int
    zero_data_segments: int
    ctl_segments: int
    rst_segments: int
    fin_segments: int
    min_app_len: int
    max_app_len: int
    length_buckets: tuple[tuple[str, int], ...]
    first_app_packet: int | None
    first_app_delta_ms: float | None
    last_app_packet: int | None
    timeline: tuple[SegmentMeta, ...]
    post_boundary_vip_frame_count: int


def _bucket_name(length: int) -> str:
    if length <= 31:
        return "1_31"
    if length <= 127:
        return "32_127"
    if length <= 511:
        return "128_511"
    if length <= 1023:
        return "512_1023"
    if length <= 1400:
        return "1024_1400"
    return "GT_1400"


def _flag_text(flags: int) -> str:
    names: list[str] = []
    if flags & PSEUDOTCP_FLAG_FIN:
        names.append("FIN")
    if flags & PSEUDOTCP_FLAG_CTL:
        names.append("CTL")
    if flags & PSEUDOTCP_FLAG_RST:
        names.append("RST")
    return "+".join(names) if names else "NONE"


def _exact_retransmit_key(segment: PseudoTcpSegment, flow_direction: str) -> tuple[str, int, int, bytes]:
    # Digest is used only in memory to distinguish an exact retransmission.
    # It is never returned or emitted.
    return (
        flow_direction,
        segment.sequence,
        segment.data_length,
        hashlib.sha256(segment.data).digest(),
    )


def analyze(
    analysis: FlowAnalysis,
    *,
    boundary_packet: int = BOUNDARY_PACKET,
    vip_frames: Iterable[object] = (),
) -> StreamResult:
    boundary_candidates = [
        segment for segment in analysis.segments if segment.packet_number == boundary_packet
    ]
    if len(boundary_candidates) != 1:
        raise ValueError(
            f"expected exactly one selected-flow boundary segment at packet {boundary_packet}, "
            f"found {len(boundary_candidates)}"
        )
    boundary_timestamp = boundary_candidates[0].timestamp

    post = tuple(
        segment for segment in analysis.segments if segment.packet_number > boundary_packet
    )
    app = tuple(segment for segment in post if segment.is_application_candidate)

    seen: set[tuple[str, int, int, bytes]] = set()
    retransmit_segments = 0
    retransmit_bytes = 0
    unique: list[tuple[PseudoTcpSegment, str]] = []
    timeline: list[SegmentMeta] = []

    for segment in app:
        flow_direction = direction(segment, analysis)
        key = _exact_retransmit_key(segment, flow_direction)
        repeated = key in seen
        if repeated:
            retransmit_segments += 1
            retransmit_bytes += segment.data_length
        else:
            seen.add(key)
            unique.append((segment, flow_direction))

        if len(timeline) < TIMELINE_LIMIT:
            timeline.append(
                SegmentMeta(
                    packet_number=segment.packet_number,
                    delta_ms=(segment.timestamp - boundary_timestamp) * 1000.0,
                    direction=flow_direction,
                    data_length=segment.data_length,
                    flags=segment.flags,
                    exact_retransmit=repeated,
                )
            )

    client_unique = [item for item in unique if item[1] == "CLIENT_TO_DEVICE"]
    device_unique = [item for item in unique if item[1] == "DEVICE_TO_CLIENT"]

    bucket_order = (
        "1_31",
        "32_127",
        "128_511",
        "512_1023",
        "1024_1400",
        "GT_1400",
    )
    bucket_counts = {name: 0 for name in bucket_order}
    for segment, _flow_direction in unique:
        bucket_counts[_bucket_name(segment.data_length)] += 1

    post_vip_frames = [
        frame
        for frame in vip_frames
        if getattr(frame, "first_packet", 0) > boundary_packet
    ]

    app_lengths = [segment.data_length for segment in app]
    return StreamResult(
        boundary_timestamp=boundary_timestamp,
        post_segment_count=len(post),
        app_segment_count=len(app),
        app_bytes_wire=sum(segment.data_length for segment in app),
        unique_app_segment_count=len(unique),
        unique_app_bytes=sum(segment.data_length for segment, _ in unique),
        retransmit_segment_count=retransmit_segments,
        retransmit_bytes=retransmit_bytes,
        client_app_segments=len(client_unique),
        client_app_bytes=sum(segment.data_length for segment, _ in client_unique),
        device_app_segments=len(device_unique),
        device_app_bytes=sum(segment.data_length for segment, _ in device_unique),
        zero_data_segments=sum(1 for segment in post if segment.data_length == 0),
        ctl_segments=sum(1 for segment in post if segment.flags & PSEUDOTCP_FLAG_CTL),
        rst_segments=sum(1 for segment in post if segment.flags & PSEUDOTCP_FLAG_RST),
        fin_segments=sum(1 for segment in post if segment.flags & PSEUDOTCP_FLAG_FIN),
        min_app_len=min(app_lengths) if app_lengths else 0,
        max_app_len=max(app_lengths) if app_lengths else 0,
        length_buckets=tuple((name, bucket_counts[name]) for name in bucket_order),
        first_app_packet=app[0].packet_number if app else None,
        first_app_delta_ms=(app[0].timestamp - boundary_timestamp) * 1000.0 if app else None,
        last_app_packet=app[-1].packet_number if app else None,
        timeline=tuple(timeline),
        post_boundary_vip_frame_count=len(post_vip_frames),
    )


def report(result: StreamResult) -> str:
    lines = [
        "=== COMELIT ENTRANCE POST-218 PSEUDOTCP STREAM PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"POST218_SELECTED_PSEUDOTCP_SEGMENT_COUNT={result.post_segment_count}",
        f"POST218_APP_SEGMENT_COUNT={result.app_segment_count}",
        f"POST218_APP_BYTES_WIRE={result.app_bytes_wire}",
        f"POST218_UNIQUE_APP_SEGMENT_COUNT={result.unique_app_segment_count}",
        f"POST218_UNIQUE_APP_BYTES={result.unique_app_bytes}",
        f"POST218_EXACT_RETRANSMIT_SEGMENT_COUNT={result.retransmit_segment_count}",
        f"POST218_EXACT_RETRANSMIT_BYTES={result.retransmit_bytes}",
        f"POST218_CLIENT_APP_SEGMENTS={result.client_app_segments}",
        f"POST218_CLIENT_APP_BYTES={result.client_app_bytes}",
        f"POST218_DEVICE_APP_SEGMENTS={result.device_app_segments}",
        f"POST218_DEVICE_APP_BYTES={result.device_app_bytes}",
        f"POST218_ZERO_DATA_SEGMENTS={result.zero_data_segments}",
        f"POST218_CTL_SEGMENTS={result.ctl_segments}",
        f"POST218_RST_SEGMENTS={result.rst_segments}",
        f"POST218_FIN_SEGMENTS={result.fin_segments}",
        f"POST218_APP_LEN_MIN={result.min_app_len}",
        f"POST218_APP_LEN_MAX={result.max_app_len}",
        f"FIRST_POST218_APP_PACKET={result.first_app_packet if result.first_app_packet is not None else 'NONE'}",
        f"FIRST_POST218_APP_DELTA_MS={result.first_app_delta_ms:.3f}" if result.first_app_delta_ms is not None else "FIRST_POST218_APP_DELTA_MS=NONE",
        f"LAST_POST218_APP_PACKET={result.last_app_packet if result.last_app_packet is not None else 'NONE'}",
        f"POST218_RECONSTRUCTED_VIP_FRAME_COUNT={result.post_boundary_vip_frame_count}",
        f"POST218_PSEUDOTCP_APP_DATA_PRESENT={'true' if result.unique_app_bytes > 0 else 'false'}",
    ]

    for name, count in result.length_buckets:
        lines.append(f"POST218_APP_LEN_BUCKET_{name}={count}")

    for ordinal, item in enumerate(result.timeline, start=1):
        lines.append(
            "POST218_APP_SEGMENT_META "
            f"ordinal={ordinal} "
            f"packet={item.packet_number} "
            f"delta_ms={item.delta_ms:.3f} "
            f"direction={item.direction} "
            f"data_len={item.data_length} "
            f"flags={_flag_text(item.flags)} "
            f"exact_retransmit={'true' if item.exact_retransmit else 'false'}"
        )

    lines.extend(
        [
            "SEQUENCE_VALUES_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PORTS_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_SIGNATURE_INSPECTION_PERFORMED=false",
            "RTP_CLASSIFICATION_PERFORMED=false",
            "H264_INSPECTION_PERFORMED=false",
            "CODEC_INSPECTION_PERFORMED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE POST-218 PSEUDOTCP STREAM PCAP FORENSIC ===",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    capture = load_capture(args.pcap)
    if capture.sha256 != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    analysis = select_vip_flow(capture)
    try:
        frames = collect_extended_vip_frames(analysis)
        result = analyze(analysis, vip_frames=frames)
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
