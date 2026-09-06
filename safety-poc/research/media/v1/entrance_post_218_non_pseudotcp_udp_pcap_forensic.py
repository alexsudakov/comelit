#!/usr/bin/env python3
"""Offline framing inventory for selected-flow UDP datagrams after packet 218.

P53 proved that the selected ViP UDP 4-tuple continues for thousands of packets
and about 1.55 MB after packet 218. P54 proved that only a small amount of that
traffic is valid PseudoTCP application data. This analyzer reconciles those two
observations without interpreting opaque payload contents.

Each selected-flow UDP datagram after packet 218 is classified only as:
- PSEUDOTCP_SHAPED: accepted by the existing conversation-0 PseudoTCP parser;
- STUN_LIKE: structural STUN header shape already used by P53;
- OPAQUE_NON_PSEUDOTCP: neither of the above.

For the opaque class it reports only packet/byte totals, directionality, payload
length buckets and a short packet/timing/length timeline. It never emits payload
bytes, sequence values, endpoints, ports, hashes, media signatures, RTP/H264
classification or codec information.

No network I/O is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_218_udp_transition_pcap_forensic import STUN_MAGIC_COOKIE
from pseudotcp_pcap_handshake_forensic import (
    Endpoint,
    _ipv4_udp,
    _pcap_format,
    _pseudotcp_segment,
    load_capture,
    select_vip_flow,
)


BOUNDARY_PACKET = 218
TIMELINE_LIMIT = 20


@dataclass(frozen=True)
class SelectedDatagram:
    packet_number: int
    timestamp: float
    source: Endpoint
    target: Endpoint
    payload: bytes


@dataclass(frozen=True)
class OpaqueMeta:
    packet_number: int
    delta_ms: float
    direction: str
    payload_length: int


@dataclass(frozen=True)
class Result:
    boundary_timestamp: float
    selected_udp_count: int
    selected_udp_bytes: int
    pseudotcp_count: int
    pseudotcp_bytes: int
    stun_count: int
    stun_bytes: int
    opaque_count: int
    opaque_bytes: int
    opaque_client_count: int
    opaque_client_bytes: int
    opaque_device_count: int
    opaque_device_bytes: int
    opaque_min_len: int
    opaque_max_len: int
    opaque_buckets: tuple[tuple[str, int], ...]
    first_opaque_packet: int | None
    first_opaque_delta_ms: float | None
    last_opaque_packet: int | None
    timeline: tuple[OpaqueMeta, ...]


def _stun_like(payload: bytes) -> bool:
    return bool(
        len(payload) >= 20
        and (payload[0] & 0xC0) == 0
        and payload[4:8] == STUN_MAGIC_COOKIE
    )


def _bucket_name(length: int) -> str:
    if length <= 31:
        return "0_31"
    if length <= 127:
        return "32_127"
    if length <= 511:
        return "128_511"
    if length <= 1023:
        return "512_1023"
    if length <= 1400:
        return "1024_1400"
    return "GT_1400"


def _read_selected_datagrams(
    path: Path,
    *,
    client: Endpoint,
    device: Endpoint,
) -> tuple[SelectedDatagram, ...]:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise ValueError("PCAP file is shorter than global header")

    endian, timestamp_scale = _pcap_format(blob[:4])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", blob[:24])
    if linktype != 101:
        raise ValueError(f"unsupported linktype: {linktype}")

    selected_key = tuple(sorted((client, device)))
    packet_number = 0
    offset = 24
    result: list[SelectedDatagram] = []

    while offset < len(blob):
        if len(blob) - offset < 16:
            raise ValueError("truncated PCAP packet header")
        ts_sec, ts_frac, captured_len, _original_len = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if captured_len > len(blob) - offset:
            raise ValueError("truncated PCAP packet body")

        packet_number += 1
        frame = blob[offset : offset + captured_len]
        offset += captured_len

        parsed = _ipv4_udp(frame)
        if parsed is None:
            continue
        source, target, payload = parsed
        if tuple(sorted((source, target))) != selected_key:
            continue

        result.append(
            SelectedDatagram(
                packet_number=packet_number,
                timestamp=ts_sec + ts_frac / timestamp_scale,
                source=source,
                target=target,
                payload=payload,
            )
        )

    return tuple(result)


def analyze(
    datagrams: tuple[SelectedDatagram, ...],
    *,
    client: Endpoint,
    device: Endpoint,
    boundary_packet: int = BOUNDARY_PACKET,
) -> Result:
    boundary = [item for item in datagrams if item.packet_number == boundary_packet]
    if len(boundary) != 1:
        raise ValueError(
            f"expected exactly one selected-flow UDP datagram at packet {boundary_packet}, "
            f"found {len(boundary)}"
        )
    boundary_timestamp = boundary[0].timestamp

    post = tuple(item for item in datagrams if item.packet_number > boundary_packet)
    pseudotcp: list[SelectedDatagram] = []
    stun: list[SelectedDatagram] = []
    opaque: list[SelectedDatagram] = []

    for item in post:
        if _pseudotcp_segment(
            item.packet_number,
            item.timestamp,
            item.source,
            item.target,
            item.payload,
        ) is not None:
            pseudotcp.append(item)
        elif _stun_like(item.payload):
            stun.append(item)
        else:
            opaque.append(item)

    def direction(item: SelectedDatagram) -> str:
        if item.source == client and item.target == device:
            return "CLIENT_TO_DEVICE"
        if item.source == device and item.target == client:
            return "DEVICE_TO_CLIENT"
        raise ValueError("selected-flow datagram direction is inconsistent")

    opaque_client = [item for item in opaque if direction(item) == "CLIENT_TO_DEVICE"]
    opaque_device = [item for item in opaque if direction(item) == "DEVICE_TO_CLIENT"]

    bucket_order = (
        "0_31",
        "32_127",
        "128_511",
        "512_1023",
        "1024_1400",
        "GT_1400",
    )
    buckets = {name: 0 for name in bucket_order}
    for item in opaque:
        buckets[_bucket_name(len(item.payload))] += 1

    timeline = tuple(
        OpaqueMeta(
            packet_number=item.packet_number,
            delta_ms=(item.timestamp - boundary_timestamp) * 1000.0,
            direction=direction(item),
            payload_length=len(item.payload),
        )
        for item in opaque[:TIMELINE_LIMIT]
    )

    lengths = [len(item.payload) for item in opaque]
    return Result(
        boundary_timestamp=boundary_timestamp,
        selected_udp_count=len(post),
        selected_udp_bytes=sum(len(item.payload) for item in post),
        pseudotcp_count=len(pseudotcp),
        pseudotcp_bytes=sum(len(item.payload) for item in pseudotcp),
        stun_count=len(stun),
        stun_bytes=sum(len(item.payload) for item in stun),
        opaque_count=len(opaque),
        opaque_bytes=sum(len(item.payload) for item in opaque),
        opaque_client_count=len(opaque_client),
        opaque_client_bytes=sum(len(item.payload) for item in opaque_client),
        opaque_device_count=len(opaque_device),
        opaque_device_bytes=sum(len(item.payload) for item in opaque_device),
        opaque_min_len=min(lengths) if lengths else 0,
        opaque_max_len=max(lengths) if lengths else 0,
        opaque_buckets=tuple((name, buckets[name]) for name in bucket_order),
        first_opaque_packet=opaque[0].packet_number if opaque else None,
        first_opaque_delta_ms=(opaque[0].timestamp - boundary_timestamp) * 1000.0 if opaque else None,
        last_opaque_packet=opaque[-1].packet_number if opaque else None,
        timeline=timeline,
    )


def report(result: Result) -> str:
    reconciled_count = result.pseudotcp_count + result.stun_count + result.opaque_count
    reconciled_bytes = result.pseudotcp_bytes + result.stun_bytes + result.opaque_bytes
    lines = [
        "=== COMELIT ENTRANCE POST-218 NON-PSEUDOTCP UDP PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"POST218_SELECTED_UDP_COUNT={result.selected_udp_count}",
        f"POST218_SELECTED_UDP_BYTES={result.selected_udp_bytes}",
        f"POST218_PSEUDOTCP_SHAPED_COUNT={result.pseudotcp_count}",
        f"POST218_PSEUDOTCP_SHAPED_BYTES={result.pseudotcp_bytes}",
        f"POST218_STUN_LIKE_COUNT={result.stun_count}",
        f"POST218_STUN_LIKE_BYTES={result.stun_bytes}",
        f"POST218_OPAQUE_NON_PSEUDOTCP_COUNT={result.opaque_count}",
        f"POST218_OPAQUE_NON_PSEUDOTCP_BYTES={result.opaque_bytes}",
        f"POST218_CLASS_COUNT_RECONCILED={'true' if reconciled_count == result.selected_udp_count else 'false'}",
        f"POST218_CLASS_BYTES_RECONCILED={'true' if reconciled_bytes == result.selected_udp_bytes else 'false'}",
        f"POST218_OPAQUE_CLIENT_COUNT={result.opaque_client_count}",
        f"POST218_OPAQUE_CLIENT_BYTES={result.opaque_client_bytes}",
        f"POST218_OPAQUE_DEVICE_COUNT={result.opaque_device_count}",
        f"POST218_OPAQUE_DEVICE_BYTES={result.opaque_device_bytes}",
        f"POST218_OPAQUE_LEN_MIN={result.opaque_min_len}",
        f"POST218_OPAQUE_LEN_MAX={result.opaque_max_len}",
        f"FIRST_POST218_OPAQUE_PACKET={result.first_opaque_packet if result.first_opaque_packet is not None else 'NONE'}",
        f"FIRST_POST218_OPAQUE_DELTA_MS={result.first_opaque_delta_ms:.3f}" if result.first_opaque_delta_ms is not None else "FIRST_POST218_OPAQUE_DELTA_MS=NONE",
        f"LAST_POST218_OPAQUE_PACKET={result.last_opaque_packet if result.last_opaque_packet is not None else 'NONE'}",
    ]

    for name, count in result.opaque_buckets:
        lines.append(f"POST218_OPAQUE_LEN_BUCKET_{name}={count}")

    for ordinal, item in enumerate(result.timeline, start=1):
        lines.append(
            "POST218_OPAQUE_DATAGRAM_META "
            f"ordinal={ordinal} "
            f"packet={item.packet_number} "
            f"delta_ms={item.delta_ms:.3f} "
            f"direction={item.direction} "
            f"payload_len={item.payload_length}"
        )

    lines.extend(
        [
            "PAYLOAD_CONTENT_INSPECTED=false",
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
            "=== END COMELIT ENTRANCE POST-218 NON-PSEUDOTCP UDP PCAP FORENSIC ===",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    blob_sha256 = hashlib.sha256(args.pcap.read_bytes()).hexdigest()
    if blob_sha256 != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    analysis = select_vip_flow(capture)
    try:
        datagrams = _read_selected_datagrams(
            args.pcap,
            client=analysis.client,
            device=analysis.device,
        )
        result = analyze(
            datagrams,
            client=analysis.client,
            device=analysis.device,
        )
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
