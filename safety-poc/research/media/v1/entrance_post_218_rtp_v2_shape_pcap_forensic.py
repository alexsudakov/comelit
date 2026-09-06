#!/usr/bin/env python3
"""Offline RTP-v2 structural classification for opaque selected-flow UDP after packet 218.

P55 proved that almost all selected-flow bytes after packet 218 are opaque
non-PseudoTCP UDP datagrams. This analyzer examines only RTP header structure:
version, CSRC count, extension length, padding validity, payload type, marker bit,
and sequence progression inside anonymized direction/SSRC/PT groups.

It never emits sequence numbers, timestamps, SSRC values, endpoints, ports,
payload bytes, media signatures, H264/NAL information or codec identities.
No network I/O is performed.
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
from pseudotcp_pcap_handshake_forensic import _pseudotcp_segment, load_capture, select_vip_flow

TIMELINE_LIMIT = 20


@dataclass(frozen=True)
class RtpHeaderMeta:
    payload_type: int
    marker: bool
    header_length: int
    media_data_length: int
    sequence: int
    ssrc: int


@dataclass(frozen=True)
class PacketMeta:
    packet_number: int
    delta_ms: float
    direction: str
    payload_length: int
    payload_type: int
    marker: bool
    header_length: int
    media_data_length: int


@dataclass(frozen=True)
class StreamMeta:
    ordinal: int
    direction: str
    payload_type: int
    packet_count: int
    udp_bytes: int
    media_data_bytes: int
    marker_count: int
    sequence_plus1_count: int
    sequence_gap_count: int
    sequence_duplicate_count: int


@dataclass(frozen=True)
class Result:
    opaque_count: int
    opaque_bytes: int
    rtp_count: int
    rtp_bytes: int
    rtp_media_data_bytes: int
    non_rtp_count: int
    non_rtp_bytes: int
    client_rtp_count: int
    client_rtp_bytes: int
    device_rtp_count: int
    device_rtp_bytes: int
    marker_count: int
    streams: tuple[StreamMeta, ...]
    timeline: tuple[PacketMeta, ...]


def _parse_rtp_v2_shape(payload: bytes) -> RtpHeaderMeta | None:
    if len(payload) < 12 or payload[0] >> 6 != 2:
        return None

    padding = bool(payload[0] & 0x20)
    extension = bool(payload[0] & 0x10)
    csrc_count = payload[0] & 0x0F
    header_length = 12 + 4 * csrc_count
    if header_length > len(payload):
        return None

    if extension:
        if header_length + 4 > len(payload):
            return None
        extension_words = int.from_bytes(payload[header_length + 2 : header_length + 4], "big")
        header_length += 4 + 4 * extension_words
        if header_length > len(payload):
            return None

    padding_length = payload[-1] if padding else 0
    if padding and (padding_length == 0 or padding_length > len(payload) - header_length):
        return None

    media_data_length = len(payload) - header_length - padding_length
    if media_data_length <= 0:
        return None

    return RtpHeaderMeta(
        payload_type=payload[1] & 0x7F,
        marker=bool(payload[1] & 0x80),
        header_length=header_length,
        media_data_length=media_data_length,
        sequence=int.from_bytes(payload[2:4], "big"),
        ssrc=int.from_bytes(payload[8:12], "big"),
    )


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

    def direction(item: SelectedDatagram) -> str:
        if item.source == client and item.target == device:
            return "CLIENT_TO_DEVICE"
        if item.source == device and item.target == client:
            return "DEVICE_TO_CLIENT"
        raise ValueError("selected-flow direction mismatch")

    opaque: list[SelectedDatagram] = []
    for item in datagrams:
        if item.packet_number <= boundary_packet:
            continue
        if _pseudotcp_segment(item.packet_number, item.timestamp, item.source, item.target, item.payload) is not None:
            continue
        if _stun_like(item.payload):
            continue
        opaque.append(item)

    shaped: list[tuple[SelectedDatagram, str, RtpHeaderMeta]] = []
    non_rtp: list[SelectedDatagram] = []
    for item in opaque:
        parsed = _parse_rtp_v2_shape(item.payload)
        if parsed is None:
            non_rtp.append(item)
        else:
            shaped.append((item, direction(item), parsed))

    grouped: dict[tuple[str, int, int], list[tuple[SelectedDatagram, RtpHeaderMeta]]] = {}
    for item, flow_direction, parsed in shaped:
        grouped.setdefault((flow_direction, parsed.ssrc, parsed.payload_type), []).append((item, parsed))

    streams: list[StreamMeta] = []
    ordered_groups = sorted(grouped.items(), key=lambda pair: min(x[0].packet_number for x in pair[1]))
    for ordinal, ((flow_direction, _ssrc, payload_type), items) in enumerate(ordered_groups, start=1):
        items = sorted(items, key=lambda x: x[0].packet_number)
        plus1 = gaps = duplicates = 0
        previous: int | None = None
        for _item, parsed in items:
            if previous is not None:
                delta = (parsed.sequence - previous) & 0xFFFF
                if delta == 1:
                    plus1 += 1
                elif delta == 0:
                    duplicates += 1
                else:
                    gaps += 1
            previous = parsed.sequence
        streams.append(
            StreamMeta(
                ordinal=ordinal,
                direction=flow_direction,
                payload_type=payload_type,
                packet_count=len(items),
                udp_bytes=sum(len(item.payload) for item, _ in items),
                media_data_bytes=sum(parsed.media_data_length for _, parsed in items),
                marker_count=sum(1 for _, parsed in items if parsed.marker),
                sequence_plus1_count=plus1,
                sequence_gap_count=gaps,
                sequence_duplicate_count=duplicates,
            )
        )

    timeline = tuple(
        PacketMeta(
            packet_number=item.packet_number,
            delta_ms=(item.timestamp - boundary_ts) * 1000.0,
            direction=flow_direction,
            payload_length=len(item.payload),
            payload_type=parsed.payload_type,
            marker=parsed.marker,
            header_length=parsed.header_length,
            media_data_length=parsed.media_data_length,
        )
        for item, flow_direction, parsed in shaped[:TIMELINE_LIMIT]
    )

    client_items = [(item, meta) for item, d, meta in shaped if d == "CLIENT_TO_DEVICE"]
    device_items = [(item, meta) for item, d, meta in shaped if d == "DEVICE_TO_CLIENT"]
    return Result(
        opaque_count=len(opaque),
        opaque_bytes=sum(len(item.payload) for item in opaque),
        rtp_count=len(shaped),
        rtp_bytes=sum(len(item.payload) for item, _, _ in shaped),
        rtp_media_data_bytes=sum(meta.media_data_length for _, _, meta in shaped),
        non_rtp_count=len(non_rtp),
        non_rtp_bytes=sum(len(item.payload) for item in non_rtp),
        client_rtp_count=len(client_items),
        client_rtp_bytes=sum(len(item.payload) for item, _ in client_items),
        device_rtp_count=len(device_items),
        device_rtp_bytes=sum(len(item.payload) for item, _ in device_items),
        marker_count=sum(1 for _, _, meta in shaped if meta.marker),
        streams=tuple(streams),
        timeline=timeline,
    )


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE POST-218 RTP-V2 SHAPE PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"OPAQUE_INPUT_COUNT={result.opaque_count}",
        f"OPAQUE_INPUT_BYTES={result.opaque_bytes}",
        f"RTP_V2_SHAPED_COUNT={result.rtp_count}",
        f"RTP_V2_SHAPED_BYTES={result.rtp_bytes}",
        f"RTP_V2_MEDIA_DATA_BYTES={result.rtp_media_data_bytes}",
        f"NON_RTP_V2_SHAPED_COUNT={result.non_rtp_count}",
        f"NON_RTP_V2_SHAPED_BYTES={result.non_rtp_bytes}",
        f"RTP_CLASS_COUNT_RECONCILED={'true' if result.rtp_count + result.non_rtp_count == result.opaque_count else 'false'}",
        f"RTP_CLASS_BYTES_RECONCILED={'true' if result.rtp_bytes + result.non_rtp_bytes == result.opaque_bytes else 'false'}",
        f"CLIENT_RTP_V2_SHAPED_COUNT={result.client_rtp_count}",
        f"CLIENT_RTP_V2_SHAPED_BYTES={result.client_rtp_bytes}",
        f"DEVICE_RTP_V2_SHAPED_COUNT={result.device_rtp_count}",
        f"DEVICE_RTP_V2_SHAPED_BYTES={result.device_rtp_bytes}",
        f"RTP_MARKER_COUNT={result.marker_count}",
        f"RTP_ANON_STREAM_COUNT={len(result.streams)}",
    ]
    for stream in result.streams:
        lines.append(
            "RTP_ANON_STREAM "
            f"ordinal={stream.ordinal} direction={stream.direction} payload_type={stream.payload_type} "
            f"packet_count={stream.packet_count} udp_bytes={stream.udp_bytes} "
            f"media_data_bytes={stream.media_data_bytes} marker_count={stream.marker_count} "
            f"seq_plus1={stream.sequence_plus1_count} seq_gap={stream.sequence_gap_count} "
            f"seq_duplicate={stream.sequence_duplicate_count}"
        )
    for ordinal, item in enumerate(result.timeline, start=1):
        lines.append(
            "RTP_V2_PACKET_META "
            f"ordinal={ordinal} packet={item.packet_number} delta_ms={item.delta_ms:.3f} "
            f"direction={item.direction} udp_len={item.payload_length} payload_type={item.payload_type} "
            f"marker={'true' if item.marker else 'false'} header_len={item.header_length} "
            f"media_data_len={item.media_data_length}"
        )
    lines.extend([
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
        "=== END COMELIT ENTRANCE POST-218 RTP-V2 SHAPE PCAP FORENSIC ===",
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
