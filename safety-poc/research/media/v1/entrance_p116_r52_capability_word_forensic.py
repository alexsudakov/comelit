#!/usr/bin/env python3
"""P116/R52 offline CAPABILITIES-word extractor.

The analyzer reads classic pcap files only, reconstructs PseudoTCP application
bytes for the selected ViP flow, parses CTP envelopes, and emits sanitized
scalar metadata for CTP inner opcode 0x0003.  It never emits endpoints, raw
payload bytes, protocol addresses, hostnames, ports, SDP, tokens, or media.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Iterable

from entrance_p116_r30_call_ctp_envelope_model import (
    FLAG_DATA,
    CtpEnvelope,
    build_ctp_envelope,
    parse_ctp_envelope,
)


LINKTYPE_ETHERNET = 1
LINKTYPE_RAW_IP = 101
LINKTYPE_LINUX_SLL2 = 276
PSEUDOTCP_HEADER = 24
PSEUDOTCP_FLAG_CTL = 1 << 1
PSEUDOTCP_FLAG_RST = 1 << 2
CLIENT_ANCHORS = (b"UAUT", b"UCFG", b"INFO", b"CTPP", b"CSPB", b"PUSH")
MAX_VIP_BODY_LEN = 4096
OP_CAPABILITIES = 0x0003
CAPABILITIES_BODY_LEN = 8


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
    sequence: int
    data: bytes
    flags: int


@dataclass(frozen=True)
class CaptureInfo:
    sha256: str
    linktype: int
    packet_count: int
    segments: tuple[PseudoTcpSegment, ...]


@dataclass(frozen=True)
class FlowAnalysis:
    segments: tuple[PseudoTcpSegment, ...]
    client: Endpoint
    device: Endpoint
    anchor_hits_client: int
    anchor_hits_device: int


@dataclass(frozen=True)
class StreamByte:
    value: int
    packet_number: int
    timestamp: float


@dataclass(frozen=True)
class VipFrame:
    direction: str
    first_packet: int
    last_packet: int
    timestamp: float
    request_id: int
    body: bytes


@dataclass(frozen=True)
class CapabilityFrame:
    capture_label: str
    session_label: str
    direction: str
    outer_channel: str
    ctp_connection: str
    ctp_sequence: int
    ctp_ack: int
    inner_length: int
    call_type: int
    reserved_byte: int
    capability_word: int
    relative_time: float
    first_packet: int
    peer_connection_match: str


def build_capabilities_body(*, call_type: int, capability_word: int, reserved: int = 0) -> bytes:
    if not 0 <= call_type <= 0xFF:
        raise ValueError("call_type must fit in one byte")
    if not 0 <= reserved <= 0xFF:
        raise ValueError("reserved must fit in one byte")
    if not 0 <= capability_word <= 0xFFFFFFFF:
        raise ValueError("capability_word must fit in uint32")
    return b"\x00\x03" + bytes((call_type, reserved)) + struct.pack("<I", capability_word)


def parse_capabilities_body(body: bytes) -> tuple[int, int, int]:
    if len(body) != CAPABILITIES_BODY_LEN:
        raise ValueError("CAPABILITIES body must be exactly 8 bytes")
    if body[:2] != b"\x00\x03":
        raise ValueError("CAPABILITIES opcode prefix mismatch")
    return body[2], body[3], struct.unpack_from("<I", body, 4)[0]


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


def _ipv4_udp_from_ip(frame: bytes) -> tuple[Endpoint, Endpoint, bytes] | None:
    if len(frame) < 20 or frame[0] >> 4 != 4:
        return None
    ihl = (frame[0] & 0x0F) * 4
    if ihl < 20 or len(frame) < ihl + 8:
        return None
    total_length = int.from_bytes(frame[2:4], "big")
    if total_length < ihl + 8:
        return None
    total_length = min(total_length, len(frame))
    if frame[9] != 17:
        return None
    fragment = int.from_bytes(frame[6:8], "big")
    if fragment & 0x1FFF:
        return None
    udp = frame[ihl:total_length]
    udp_length = int.from_bytes(udp[4:6], "big")
    if udp_length < 8:
        return None
    udp_length = min(udp_length, len(udp))
    return (
        Endpoint(frame[12:16], int.from_bytes(udp[0:2], "big")),
        Endpoint(frame[16:20], int.from_bytes(udp[2:4], "big")),
        udp[8:udp_length],
    )


def _ipv4_udp(linktype: int, frame: bytes) -> tuple[Endpoint, Endpoint, bytes] | None:
    if linktype == LINKTYPE_RAW_IP:
        return _ipv4_udp_from_ip(frame)
    if linktype == LINKTYPE_ETHERNET:
        if len(frame) < 14 or frame[12:14] != b"\x08\x00":
            return None
        return _ipv4_udp_from_ip(frame[14:])
    if linktype == LINKTYPE_LINUX_SLL2:
        if len(frame) < 20:
            return None
        if frame[0:2] == b"\x08\x00":
            return _ipv4_udp_from_ip(frame[20:])
        if frame[14:16] == b"\x08\x00":
            return _ipv4_udp_from_ip(frame[20:])
        return None
    raise ValueError(f"unsupported linktype: {linktype}")


def _pseudotcp_segment(
    packet_number: int,
    timestamp: float,
    source: Endpoint,
    target: Endpoint,
    payload: bytes,
) -> PseudoTcpSegment | None:
    if len(payload) < PSEUDOTCP_HEADER or int.from_bytes(payload[0:4], "big") != 0:
        return None
    return PseudoTcpSegment(
        packet_number=packet_number,
        timestamp=timestamp,
        source=source,
        target=target,
        sequence=int.from_bytes(payload[4:8], "big"),
        flags=payload[13],
        data=payload[PSEUDOTCP_HEADER:],
    )


def load_capture(path: Path) -> CaptureInfo:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise ValueError("PCAP file is shorter than global header")
    endian, timestamp_scale = _pcap_format(blob[:4])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", blob[:24])
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
        parsed = _ipv4_udp(linktype, blob[offset : offset + captured_len])
        offset += captured_len
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
    return CaptureInfo(hashlib.sha256(blob).hexdigest(), linktype, packet_number, tuple(segments))


def _flow_key(segment: PseudoTcpSegment) -> tuple[Endpoint, Endpoint]:
    return tuple(sorted((segment.source, segment.target)))  # type: ignore[return-value]


def _anchor_hits(segments: Iterable[PseudoTcpSegment], sender: Endpoint) -> int:
    return sum(
        sum(anchor in segment.data for anchor in CLIENT_ANCHORS)
        for segment in segments
        if segment.source == sender and segment.data
    )


def select_vip_flow(capture: CaptureInfo) -> FlowAnalysis:
    flows: dict[tuple[Endpoint, Endpoint], list[PseudoTcpSegment]] = defaultdict(list)
    for segment in capture.segments:
        flows[_flow_key(segment)].append(segment)
    ranked: list[tuple[int, int, tuple[Endpoint, Endpoint], list[PseudoTcpSegment]]] = []
    for key, segments in flows.items():
        first, second = key
        ranked.append((
            max(_anchor_hits(segments, first), _anchor_hits(segments, second)),
            len(segments),
            key,
            segments,
        ))
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
    return FlowAnalysis(
        tuple(sorted(segments, key=lambda item: (item.timestamp, item.packet_number))),
        client,
        device,
        max(first_hits, second_hits),
        min(first_hits, second_hits),
    )


def _direction(segment: PseudoTcpSegment, flow: FlowAnalysis) -> str:
    if segment.source == flow.client:
        return "CLIENT_TO_DEVICE"
    if segment.source == flow.device:
        return "DEVICE_TO_CLIENT"
    raise AssertionError("segment outside selected flow")


def _stream_chunks(flow: FlowAnalysis, direction_name: str) -> list[list[StreamByte]]:
    by_sequence: dict[int, StreamByte] = {}
    for segment in flow.segments:
        if not segment.data or _direction(segment, flow) != direction_name:
            continue
        if segment.flags & (PSEUDOTCP_FLAG_CTL | PSEUDOTCP_FLAG_RST):
            continue
        for offset, value in enumerate(segment.data):
            sequence = segment.sequence + offset
            previous = by_sequence.get(sequence)
            cell = StreamByte(value, segment.packet_number, segment.timestamp)
            if previous is None:
                by_sequence[sequence] = cell
            elif previous.value != value:
                raise ValueError("conflicting retransmission bytes in PseudoTCP stream")
    chunks: list[list[StreamByte]] = []
    current: list[StreamByte] = []
    previous_sequence: int | None = None
    for sequence in sorted(by_sequence):
        if previous_sequence is not None and sequence != previous_sequence + 1:
            if current:
                chunks.append(current)
            current = []
        current.append(by_sequence[sequence])
        previous_sequence = sequence
    if current:
        chunks.append(current)
    return chunks


def _parse_chunk(direction_name: str, cells: list[StreamByte]) -> list[VipFrame]:
    blob = bytes(cell.value for cell in cells)
    frames: list[VipFrame] = []
    offset = 0
    while offset + 8 <= len(blob):
        marker = blob.find(b"\x00\x06", offset)
        if marker < 0:
            break
        if marker + 8 > len(blob):
            raise ValueError("truncated ViP frame header")
        body_len = int.from_bytes(blob[marker + 2 : marker + 4], "little")
        frame_len = 8 + body_len
        if body_len == 0 or body_len > MAX_VIP_BODY_LEN:
            offset = marker + 1
            continue
        if marker + frame_len > len(blob):
            raise ValueError("truncated ViP frame body")
        span = cells[marker : marker + frame_len]
        frames.append(
            VipFrame(
                direction=direction_name,
                first_packet=min(cell.packet_number for cell in span),
                last_packet=max(cell.packet_number for cell in span),
                timestamp=min(cell.timestamp for cell in span),
                request_id=int.from_bytes(blob[marker + 4 : marker + 8], "little"),
                body=blob[marker + 8 : marker + frame_len],
            )
        )
        offset = marker + frame_len
    return frames


def collect_vip_frames(flow: FlowAnalysis) -> tuple[VipFrame, ...]:
    frames: list[VipFrame] = []
    for direction_name in ("CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT"):
        for cells in _stream_chunks(flow, direction_name):
            frames.extend(_parse_chunk(direction_name, cells))
    return tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))


def _classify_connection(
    frame_direction: str,
    envelope: CtpEnvelope,
    observed: dict[int, set[str]],
) -> tuple[str, str]:
    connection = envelope.connection_word
    peer = connection ^ 0x8000
    observed.setdefault(connection, set()).add(frame_direction)
    if frame_direction == "CLIENT_TO_DEVICE":
        relation = "CLIENT_LOCAL"
    elif peer in observed and "CLIENT_TO_DEVICE" in observed[peer]:
        relation = "DEVICE_PEER_XOR_CLIENT_LOCAL"
    else:
        relation = "DEVICE_PEER"
    return "SANITIZED", relation


def extract_capabilities_from_vip_frames(
    frames: Iterable[VipFrame],
    *,
    capture_label: str,
) -> tuple[CapabilityFrame, ...]:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    if not ordered:
        return ()
    base_time = ordered[0].timestamp
    observed_connections: dict[int, set[str]] = {}
    output: list[CapabilityFrame] = []
    session_by_connection: dict[int, str] = {}
    next_session = 1
    for frame in ordered:
        try:
            envelope = parse_ctp_envelope(frame.body)
        except ValueError:
            continue
        connection = envelope.connection_word
        if envelope.opcode == 0x0001 and connection not in session_by_connection:
            session_by_connection[connection] = f"session-{next_session}"
            session_by_connection[connection ^ 0x8000] = f"session-{next_session}"
            next_session += 1
        if envelope.opcode != OP_CAPABILITIES:
            continue
        if envelope.flags != FLAG_DATA:
            raise ValueError("CAPABILITIES envelope is not a DATA frame")
        call_type, reserved, word = parse_capabilities_body(envelope.inner_body)
        _outer, relation = _classify_connection(frame.direction, envelope, observed_connections)
        if connection not in session_by_connection:
            session_by_connection[connection] = f"session-{next_session}"
            session_by_connection[connection ^ 0x8000] = f"session-{next_session}"
            next_session += 1
        output.append(
            CapabilityFrame(
                capture_label=capture_label,
                session_label=session_by_connection[connection],
                direction=frame.direction,
                outer_channel="SANITIZED",
                ctp_connection="SANITIZED",
                ctp_sequence=envelope.sequence,
                ctp_ack=envelope.acknowledgement,
                inner_length=len(envelope.inner_body),
                call_type=call_type,
                reserved_byte=reserved,
                capability_word=word,
                relative_time=frame.timestamp - base_time,
                first_packet=frame.first_packet,
                peer_connection_match=relation,
            )
        )
    return tuple(output)


def analyze_capture(path: Path, *, label: str) -> tuple[CaptureInfo, tuple[CapabilityFrame, ...], str]:
    capture = load_capture(path)
    try:
        flow = select_vip_flow(capture)
    except ValueError as exc:
        return capture, (), str(exc)
    frames = collect_vip_frames(flow)
    return capture, extract_capabilities_from_vip_frames(frames, capture_label=label), "OK"


def tsv_lines(rows: Iterable[CapabilityFrame]) -> list[str]:
    lines = [
        "capture_label\tsession_label\tdirection\touter_channel\tctp_connection\t"
        "ctp_sequence\tctp_ack\tinner_length\tcall_type\treserved_byte\t"
        "capability_word\trelative_time_s\tfirst_packet\tpeer_connection_match"
    ]
    for row in rows:
        lines.append(
            "\t".join(
                (
                    row.capture_label,
                    row.session_label,
                    row.direction,
                    row.outer_channel,
                    row.ctp_connection,
                    str(row.ctp_sequence),
                    str(row.ctp_ack),
                    str(row.inner_length),
                    f"0x{row.call_type:02x}",
                    f"0x{row.reserved_byte:02x}",
                    f"0x{row.capability_word:08x}",
                    f"{row.relative_time:.6f}",
                    str(row.first_packet),
                    row.peer_connection_match,
                )
            )
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--label", default="capture")
    args = parser.parse_args(argv)
    try:
        capture, rows, status = analyze_capture(args.pcap, label=args.label)
    except (OSError, ValueError) as exc:
        print("FORENSIC_GATE=FAIL")
        print(f"ERROR={type(exc).__name__}")
        print("NETWORK_IO_PERFORMED=false")
        return 2
    print(f"CAPTURE_LABEL={args.label}")
    print(f"PCAP_SHA256={capture.sha256}")
    print(f"PCAP_LINKTYPE={capture.linktype}")
    print(f"PCAP_PACKET_COUNT={capture.packet_count}")
    print(f"ANALYSIS_STATUS={status}")
    print(f"CAPABILITIES_FRAMES_FOUND={len(rows)}")
    for line in tsv_lines(rows):
        print(line)
    print("ENDPOINTS_EMITTED=false")
    print("RAW_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
