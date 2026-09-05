#!/usr/bin/env python3
"""Offline, public-safe PseudoTCP handshake forensic for Comelit captures.

The analyzer reads classic PCAP files with RAW IP link type (101), extracts
IPv4/UDP datagrams which carry libnice PseudoTCP conversation 0, identifies the
ViP client direction from channel-name anchors in later application bytes, and
prints only protocol metadata. IP addresses, ports, ICE credentials and raw
payloads are never emitted.

No network I/O is performed by this module.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Iterable


PCAP_LINKTYPE_RAW = 101
PSEUDOTCP_HEADER = 24
PSEUDOTCP_FLAG_FIN = 1 << 0
PSEUDOTCP_FLAG_CTL = 1 << 1
PSEUDOTCP_FLAG_RST = 1 << 2
CLIENT_ANCHORS = (b"UAUT", b"UCFG", b"INFO", b"CTPP", b"CSPB", b"PUSH")


@dataclass(frozen=True, order=True)
class Endpoint:
    address: bytes
    port: int


@dataclass(frozen=True)
class PseudoTcpSegment:
    packet_number: int
    timestamp: float
    source: Endpoint
    target: Endpoint
    wire_length: int
    sequence: int
    acknowledgment: int
    control: int
    flags: int
    window: int
    data: bytes

    @property
    def data_length(self) -> int:
        return len(self.data)

    @property
    def is_application_candidate(self) -> bool:
        return bool(self.data) and not (
            self.flags & (PSEUDOTCP_FLAG_CTL | PSEUDOTCP_FLAG_RST)
        )


@dataclass(frozen=True)
class CaptureInfo:
    sha256: str
    linktype: int
    packet_count: int
    pseudotcp_segments: tuple[PseudoTcpSegment, ...]


@dataclass(frozen=True)
class FlowAnalysis:
    segments: tuple[PseudoTcpSegment, ...]
    client: Endpoint
    device: Endpoint
    anchor_hits_client: int
    anchor_hits_device: int


def _pcap_format(magic: bytes) -> tuple[str, float]:
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000.0),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000.0),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000.0),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000.0),
    }
    try:
        return formats[magic]
    except KeyError as exc:
        raise ValueError("unsupported PCAP magic") from exc


def _ipv4_udp(frame: bytes) -> tuple[Endpoint, Endpoint, bytes] | None:
    if len(frame) < 20 or frame[0] >> 4 != 4:
        return None

    ihl = (frame[0] & 0x0F) * 4
    if ihl < 20 or len(frame) < ihl + 8:
        return None

    total_length = int.from_bytes(frame[2:4], "big")
    if total_length < ihl + 8:
        return None
    total_length = min(total_length, len(frame))

    if frame[9] != 17:  # UDP
        return None

    fragment = int.from_bytes(frame[6:8], "big")
    if fragment & 0x1FFF:  # non-zero fragment offset
        return None

    udp = frame[ihl:total_length]
    if len(udp) < 8:
        return None

    source_port = int.from_bytes(udp[0:2], "big")
    target_port = int.from_bytes(udp[2:4], "big")
    udp_length = int.from_bytes(udp[4:6], "big")
    if udp_length < 8:
        return None
    udp_length = min(udp_length, len(udp))

    source = Endpoint(frame[12:16], source_port)
    target = Endpoint(frame[16:20], target_port)
    return source, target, udp[8:udp_length]


def _pseudotcp_segment(
    packet_number: int,
    timestamp: float,
    source: Endpoint,
    target: Endpoint,
    payload: bytes,
) -> PseudoTcpSegment | None:
    if len(payload) < PSEUDOTCP_HEADER:
        return None

    conversation = int.from_bytes(payload[0:4], "big")
    if conversation != 0:
        return None

    return PseudoTcpSegment(
        packet_number=packet_number,
        timestamp=timestamp,
        source=source,
        target=target,
        wire_length=len(payload),
        sequence=int.from_bytes(payload[4:8], "big"),
        acknowledgment=int.from_bytes(payload[8:12], "big"),
        control=payload[12],
        flags=payload[13],
        window=int.from_bytes(payload[14:16], "big"),
        data=payload[PSEUDOTCP_HEADER:],
    )


def load_capture(path: Path) -> CaptureInfo:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise ValueError("PCAP file is shorter than global header")

    endian, timestamp_scale = _pcap_format(blob[:4])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", blob[:24])
    if linktype != PCAP_LINKTYPE_RAW:
        raise ValueError(f"unsupported linktype: {linktype}")

    packet_number = 0
    offset = 24
    segments: list[PseudoTcpSegment] = []

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
        source, target, udp_payload = parsed

        segment = _pseudotcp_segment(
            packet_number,
            ts_sec + ts_frac / timestamp_scale,
            source,
            target,
            udp_payload,
        )
        if segment is not None:
            segments.append(segment)

    return CaptureInfo(
        sha256=hashlib.sha256(blob).hexdigest(),
        linktype=linktype,
        packet_count=packet_number,
        pseudotcp_segments=tuple(segments),
    )


def _flow_key(segment: PseudoTcpSegment) -> tuple[Endpoint, Endpoint]:
    return tuple(sorted((segment.source, segment.target)))  # type: ignore[return-value]


def _anchor_hits(segments: Iterable[PseudoTcpSegment], sender: Endpoint) -> int:
    hits = 0
    for segment in segments:
        if segment.source != sender or not segment.data:
            continue
        hits += sum(anchor in segment.data for anchor in CLIENT_ANCHORS)
    return hits


def select_vip_flow(capture: CaptureInfo) -> FlowAnalysis:
    flows: dict[tuple[Endpoint, Endpoint], list[PseudoTcpSegment]] = defaultdict(list)
    for segment in capture.pseudotcp_segments:
        flows[_flow_key(segment)].append(segment)

    ranked: list[tuple[int, int, tuple[Endpoint, Endpoint], list[PseudoTcpSegment]]] = []
    for key, segments in flows.items():
        first, second = key
        first_hits = _anchor_hits(segments, first)
        second_hits = _anchor_hits(segments, second)
        ranked.append((max(first_hits, second_hits), len(segments), key, segments))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not ranked or ranked[0][0] == 0:
        raise ValueError("no PseudoTCP flow with ViP client-direction anchors")

    _score, _length, key, segments = ranked[0]
    first, second = key
    first_hits = _anchor_hits(segments, first)
    second_hits = _anchor_hits(segments, second)
    if first_hits == second_hits:
        raise ValueError("client direction is ambiguous")

    client, device = (first, second) if first_hits > second_hits else (second, first)
    ordered = tuple(sorted(segments, key=lambda item: (item.timestamp, item.packet_number)))
    return FlowAnalysis(
        segments=ordered,
        client=client,
        device=device,
        anchor_hits_client=max(first_hits, second_hits),
        anchor_hits_device=min(first_hits, second_hits),
    )


def flag_name(flags: int) -> str:
    names: list[str] = []
    if flags & PSEUDOTCP_FLAG_FIN:
        names.append("FIN")
    if flags & PSEUDOTCP_FLAG_CTL:
        names.append("CTL")
    if flags & PSEUDOTCP_FLAG_RST:
        names.append("RST")
    unknown = flags & ~(PSEUDOTCP_FLAG_FIN | PSEUDOTCP_FLAG_CTL | PSEUDOTCP_FLAG_RST)
    if unknown:
        names.append(f"UNKNOWN_0x{unknown:02x}")
    return "+".join(names) if names else "NONE"


def direction(segment: PseudoTcpSegment, analysis: FlowAnalysis) -> str:
    if segment.source == analysis.client:
        return "CLIENT_TO_DEVICE"
    if segment.source == analysis.device:
        return "DEVICE_TO_CLIENT"
    raise AssertionError("segment endpoint is outside selected flow")


def _first_index(
    analysis: FlowAnalysis,
    *,
    sender: Endpoint | None = None,
    required_flags: int | None = None,
    zero_data: bool | None = None,
    application: bool = False,
) -> int | None:
    for index, segment in enumerate(analysis.segments):
        if sender is not None and segment.source != sender:
            continue
        if required_flags is not None and not (segment.flags & required_flags):
            continue
        if zero_data is not None and (segment.data_length == 0) != zero_data:
            continue
        if application and not segment.is_application_candidate:
            continue
        return index
    return None


def report(capture: CaptureInfo, analysis: FlowAnalysis, label: str, limit: int) -> str:
    segments = analysis.segments
    if not segments:
        raise ValueError("selected flow is empty")

    first_time = segments[0].timestamp
    first_client_ctl = _first_index(
        analysis, sender=analysis.client, required_flags=PSEUDOTCP_FLAG_CTL
    )
    first_device_ctl = _first_index(
        analysis, sender=analysis.device, required_flags=PSEUDOTCP_FLAG_CTL
    )
    first_application = _first_index(analysis, application=True)
    first_client_ack = None
    if first_client_ctl is not None and first_device_ctl is not None:
        after = max(first_client_ctl, first_device_ctl) + 1
        for index in range(after, len(segments)):
            segment = segments[index]
            if (
                segment.source == analysis.client
                and segment.data_length == 0
                and not (segment.flags & (PSEUDOTCP_FLAG_CTL | PSEUDOTCP_FLAG_RST))
            ):
                first_client_ack = index
                break

    pre_app_end = first_application if first_application is not None else len(segments)
    pre_app_rst = [
        segment
        for segment in segments[:pre_app_end]
        if segment.flags & PSEUDOTCP_FLAG_RST
    ]
    all_rst = [segment for segment in segments if segment.flags & PSEUDOTCP_FLAG_RST]

    first_ctl = None
    for index, segment in enumerate(segments):
        if segment.flags & PSEUDOTCP_FLAG_CTL:
            first_ctl = index
            break

    if first_ctl is None:
        initiator = "UNKNOWN"
    else:
        initiator = (
            "CLIENT" if segments[first_ctl].source == analysis.client else "DEVICE"
        )

    handshake_pass = bool(
        first_client_ctl is not None
        and first_device_ctl is not None
        and first_client_ack is not None
        and first_client_ctl < first_device_ctl < first_client_ack
        and not pre_app_rst
    )

    lines = [
        f"CAPTURE_LABEL={label}",
        f"PCAP_SHA256={capture.sha256}",
        f"PCAP_LINKTYPE={capture.linktype}",
        f"PCAP_PACKET_COUNT={capture.packet_count}",
        f"PSEUDOTCP_SEGMENT_COUNT={len(capture.pseudotcp_segments)}",
        f"SELECTED_FLOW_SEGMENT_COUNT={len(segments)}",
        f"CLIENT_DIRECTION_ANCHOR_HITS={analysis.anchor_hits_client}",
        f"DEVICE_DIRECTION_ANCHOR_HITS={analysis.anchor_hits_device}",
        "CLIENT_DIRECTION_ANCHOR=PASS",
        "ENDPOINTS_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        f"PSEUDOTCP_INITIATOR={initiator}",
        f"PSEUDOTCP_PRE_APP_RST_COUNT={len(pre_app_rst)}",
        f"PSEUDOTCP_TOTAL_RST_COUNT={len(all_rst)}",
        f"PSEUDOTCP_INITIAL_HANDSHAKE={'PASS' if handshake_pass else 'NOT_PROVEN'}",
    ]

    def packet_value(index: int | None) -> str:
        return "NONE" if index is None else str(segments[index].packet_number)

    lines.extend(
        [
            f"FIRST_CLIENT_CTL_PACKET={packet_value(first_client_ctl)}",
            f"FIRST_DEVICE_CTL_PACKET={packet_value(first_device_ctl)}",
            f"FIRST_CLIENT_ZERO_DATA_ACK_PACKET={packet_value(first_client_ack)}",
            f"FIRST_APPLICATION_PACKET={packet_value(first_application)}",
            f"FIRST_RST_PACKET={all_rst[0].packet_number if all_rst else 'NONE'}",
            f"TIMELINE_LIMIT={limit}",
        ]
    )

    for ordinal, segment in enumerate(segments[: max(0, limit)], start=1):
        lines.append(
            "TIMELINE "
            f"ordinal={ordinal} "
            f"pcap_packet={segment.packet_number} "
            f"rel_time={segment.timestamp - first_time:.6f} "
            f"direction={direction(segment, analysis)} "
            f"wire_len={segment.wire_length} "
            f"seq={segment.sequence} "
            f"ack={segment.acknowledgment} "
            f"control=0x{segment.control:02x} "
            f"flags={flag_name(segment.flags)} "
            f"data_len={segment.data_length}"
        )

    lines.extend(
        [
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--label", default="capture")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--timeline-limit", type=int, default=32)
    args = parser.parse_args()

    capture = load_capture(args.pcap)
    if args.expected_sha256 and capture.sha256 != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    if args.expected_sha256:
        print("PCAP_SHA256_GATE=PASS")

    analysis = select_vip_flow(capture)
    print(report(capture, analysis, args.label, args.timeline_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
