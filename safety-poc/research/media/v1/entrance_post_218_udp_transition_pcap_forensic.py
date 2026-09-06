#!/usr/bin/env python3
"""Offline UDP-flow inventory after the entrance packet-218 signaling boundary.

This analyzer reads only the frozen ``self_activation.pcap``. P52 proved that
no reconstructed ViP application frame follows packet 218 in the selected
PseudoTCP flow through packet 360. This forensic therefore steps one layer down
and inventories UDP transport flows after packet 218 without interpreting media
payloads.

It reports only anonymized flow ordinals, packet ranges/timing, whether a flow
existed before packet 218, coarse relation to the already selected ViP client
or device host, packet/byte counts, payload-length bounds, and STUN-header
counts. It never emits addresses, ports, payload bytes, credentials, request
ids, RTP/H264 classification, codec information, or media contents.

No network I/O is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Iterable

from pseudotcp_pcap_handshake_forensic import (
    Endpoint,
    _ipv4_udp,
    _pcap_format,
    load_capture,
    select_vip_flow,
)
from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256


POST_SIGNAL_PACKET = 218
STUN_MAGIC_COOKIE = b"\x21\x12\xa4\x42"


@dataclass(frozen=True)
class UdpDatagram:
    packet_number: int
    timestamp: float
    source: Endpoint
    target: Endpoint
    payload_length: int
    stun_like: bool


@dataclass(frozen=True)
class FlowSummary:
    ordinal: int
    relation: str
    existed_before_boundary: bool
    first_packet: int
    last_packet: int
    first_delta_ms: float
    packet_count: int
    total_payload_bytes: int
    min_payload_bytes: int
    max_payload_bytes: int
    stun_like_packets: int
    from_vip_client_host_packets: int
    from_vip_device_host_packets: int


@dataclass(frozen=True)
class ForensicResult:
    packet_count: int
    boundary_timestamp: float
    post_boundary_udp_packets: int
    flows: tuple[FlowSummary, ...]


def _flow_key(datagram: UdpDatagram) -> tuple[Endpoint, Endpoint]:
    return tuple(sorted((datagram.source, datagram.target)))  # type: ignore[return-value]


def _stun_like(payload: bytes) -> bool:
    return bool(
        len(payload) >= 20
        and (payload[0] & 0xC0) == 0
        and payload[4:8] == STUN_MAGIC_COOKIE
    )


def _read_udp_datagrams(path: Path) -> tuple[int, tuple[UdpDatagram, ...]]:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise ValueError("PCAP file is shorter than global header")

    endian, timestamp_scale = _pcap_format(blob[:4])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", blob[:24])
    if linktype != 101:
        raise ValueError(f"unsupported linktype: {linktype}")

    packet_number = 0
    offset = 24
    datagrams: list[UdpDatagram] = []

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
        datagrams.append(
            UdpDatagram(
                packet_number=packet_number,
                timestamp=ts_sec + ts_frac / timestamp_scale,
                source=source,
                target=target,
                payload_length=len(payload),
                stun_like=_stun_like(payload),
            )
        )

    return packet_number, tuple(datagrams)


def _relation(
    key: tuple[Endpoint, Endpoint],
    *,
    vip_client: Endpoint,
    vip_device: Endpoint,
) -> str:
    vip_key = tuple(sorted((vip_client, vip_device)))
    if key == vip_key:
        return "SELECTED_VIP_FLOW"

    addresses = {endpoint.address for endpoint in key}
    has_client_host = vip_client.address in addresses
    has_device_host = vip_device.address in addresses
    if has_client_host and has_device_host:
        return "SAME_VIP_HOSTS_NEW_PORTS"
    if has_client_host:
        return "SHARES_VIP_CLIENT_HOST"
    if has_device_host:
        return "SHARES_VIP_DEVICE_HOST"
    return "OTHER"


def analyze(
    datagrams: Iterable[UdpDatagram],
    *,
    packet_count: int,
    vip_client: Endpoint,
    vip_device: Endpoint,
    boundary_packet: int = POST_SIGNAL_PACKET,
) -> ForensicResult:
    ordered = tuple(sorted(datagrams, key=lambda item: item.packet_number))
    boundary_candidates = [
        item for item in ordered if item.packet_number == boundary_packet
    ]
    if len(boundary_candidates) != 1:
        raise ValueError(
            f"expected exactly one UDP datagram at boundary packet, found {len(boundary_candidates)}"
        )
    boundary_timestamp = boundary_candidates[0].timestamp

    before_keys = {
        _flow_key(item) for item in ordered if item.packet_number <= boundary_packet
    }
    post = tuple(item for item in ordered if item.packet_number > boundary_packet)

    by_key: dict[tuple[Endpoint, Endpoint], list[UdpDatagram]] = {}
    for item in post:
        by_key.setdefault(_flow_key(item), []).append(item)

    first_seen_order = sorted(
        by_key.items(),
        key=lambda pair: (
            min(item.packet_number for item in pair[1]),
            pair[0],
        ),
    )

    summaries: list[FlowSummary] = []
    for ordinal, (key, items) in enumerate(first_seen_order, start=1):
        payload_lengths = [item.payload_length for item in items]
        summaries.append(
            FlowSummary(
                ordinal=ordinal,
                relation=_relation(
                    key,
                    vip_client=vip_client,
                    vip_device=vip_device,
                ),
                existed_before_boundary=key in before_keys,
                first_packet=min(item.packet_number for item in items),
                last_packet=max(item.packet_number for item in items),
                first_delta_ms=(
                    min(item.timestamp for item in items) - boundary_timestamp
                )
                * 1000.0,
                packet_count=len(items),
                total_payload_bytes=sum(payload_lengths),
                min_payload_bytes=min(payload_lengths),
                max_payload_bytes=max(payload_lengths),
                stun_like_packets=sum(1 for item in items if item.stun_like),
                from_vip_client_host_packets=sum(
                    1 for item in items if item.source.address == vip_client.address
                ),
                from_vip_device_host_packets=sum(
                    1 for item in items if item.source.address == vip_device.address
                ),
            )
        )

    return ForensicResult(
        packet_count=packet_count,
        boundary_timestamp=boundary_timestamp,
        post_boundary_udp_packets=len(post),
        flows=tuple(summaries),
    )


def report(result: ForensicResult) -> str:
    new_flows = [item for item in result.flows if not item.existed_before_boundary]
    non_vip = [
        item for item in result.flows if item.relation != "SELECTED_VIP_FLOW"
    ]
    lines = [
        "=== COMELIT ENTRANCE POST-218 UDP TRANSITION PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"PCAP_PACKET_COUNT={result.packet_count}",
        f"BOUNDARY_PACKET={POST_SIGNAL_PACKET}",
        f"POST_BOUNDARY_UDP_PACKET_COUNT={result.post_boundary_udp_packets}",
        f"POST_BOUNDARY_FLOW_COUNT={len(result.flows)}",
        f"NEW_POST_BOUNDARY_FLOW_COUNT={len(new_flows)}",
        f"NON_VIP_POST_BOUNDARY_FLOW_COUNT={len(non_vip)}",
    ]

    for item in result.flows:
        lines.append(
            "POST218_UDP_FLOW "
            f"ordinal={item.ordinal} "
            f"relation={item.relation} "
            f"existed_before_boundary={'true' if item.existed_before_boundary else 'false'} "
            f"first_packet={item.first_packet} "
            f"last_packet={item.last_packet} "
            f"first_delta_ms={item.first_delta_ms:.3f} "
            f"packet_count={item.packet_count} "
            f"total_payload_bytes={item.total_payload_bytes} "
            f"min_payload_bytes={item.min_payload_bytes} "
            f"max_payload_bytes={item.max_payload_bytes} "
            f"stun_like_packets={item.stun_like_packets} "
            f"from_vip_client_host_packets={item.from_vip_client_host_packets} "
            f"from_vip_device_host_packets={item.from_vip_device_host_packets}"
        )

    if new_flows:
        first = new_flows[0]
        lines.append(
            "FIRST_NEW_POST218_FLOW "
            f"ordinal={first.ordinal} "
            f"relation={first.relation} "
            f"first_packet={first.first_packet} "
            f"first_delta_ms={first.first_delta_ms:.3f} "
            f"packet_count={first.packet_count} "
            f"total_payload_bytes={first.total_payload_bytes} "
            f"max_payload_bytes={first.max_payload_bytes} "
            f"stun_like_packets={first.stun_like_packets}"
        )
    else:
        lines.append("FIRST_NEW_POST218_FLOW=NONE")

    lines.extend(
        [
            "ENDPOINTS_EMITTED=false",
            "PORTS_EMITTED=false",
            "ICE_CREDENTIALS_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "RTP_CLASSIFICATION_PERFORMED=false",
            "H264_INSPECTION_PERFORMED=false",
            "CODEC_INSPECTION_PERFORMED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE POST-218 UDP TRANSITION PCAP FORENSIC ===",
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
        packet_count, datagrams = _read_udp_datagrams(args.pcap)
        result = analyze(
            datagrams,
            packet_count=packet_count,
            vip_client=analysis.client,
            vip_device=analysis.device,
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
