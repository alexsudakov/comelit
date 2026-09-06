#!/usr/bin/env python3
"""Offline forensic for the official-app ACK after the entrance device 0x0008 event.

The analyzer is intentionally capture-only. It reads the frozen
``self_activation.pcap`` through the existing public-safe PseudoTCP parser,
reassembles bounded ViP application frames around the capture boundary, anchors
on the frozen device-video body hash from packet 200, and reports only protocol
metadata needed to determine whether the official client sends a matching CTPP
ACK.

It never emits endpoints, raw payload bytes, protocol addresses, ICE material,
or media contents, and it performs no network I/O.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from pseudotcp_pcap_handshake_forensic import (
    FlowAnalysis,
    PseudoTcpSegment,
    direction,
    load_capture,
    select_vip_flow,
)


EXPECTED_PCAP_SHA256 = (
    "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a"
)
DEVICE_VIDEO_BODY_SHA256 = (
    "fbb8884012c7b6f0202a2a1418ffaf0ac06b5cbfe66a823b4d7780e559c4b02b"
)
DEVICE_VIDEO_PCAP_PACKET = 200
WINDOW_START_PACKET = 160
WINDOW_END_PACKET = 280
MAX_VIP_BODY_LEN = 512


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

    @property
    def body_length(self) -> int:
        return len(self.body)

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def prefix(self) -> int | None:
        return int.from_bytes(self.body[0:2], "little") if len(self.body) >= 2 else None

    @property
    def sequence(self) -> int | None:
        return int.from_bytes(self.body[2:6], "little") if len(self.body) >= 6 else None

    @property
    def action(self) -> int | None:
        return int.from_bytes(self.body[6:8], "big") if len(self.body) >= 8 else None

    @property
    def flags(self) -> int | None:
        return int.from_bytes(self.body[8:10], "big") if len(self.body) >= 10 else None


@dataclass(frozen=True)
class AckEvidence:
    anchor: VipFrame
    candidates: tuple[VipFrame, ...]
    matching_acks: tuple[VipFrame, ...]


def _fmt_hex(value: int | None, width: int = 4) -> str:
    if value is None:
        return "NONE"
    return f"0x{value:0{width}x}"


def _window_segments(analysis: FlowAnalysis, sender_name: str) -> Iterable[PseudoTcpSegment]:
    for segment in analysis.segments:
        if segment.packet_number < WINDOW_START_PACKET:
            continue
        if segment.packet_number > WINDOW_END_PACKET:
            continue
        if not segment.data:
            continue
        if direction(segment, analysis) != sender_name:
            continue
        yield segment


def _stream_chunks(
    analysis: FlowAnalysis,
    sender_name: str,
) -> list[tuple[int, list[StreamByte]]]:
    """Return contiguous PseudoTCP byte ranges, deduplicating retransmissions.

    The selected packet window is deliberately small enough that a 32-bit
    PseudoTCP sequence wrap is not expected. Conflicting bytes at the same
    sequence position fail closed instead of being guessed.
    """

    by_sequence: dict[int, StreamByte] = {}
    for segment in sorted(
        _window_segments(analysis, sender_name),
        key=lambda item: (item.timestamp, item.packet_number),
    ):
        for offset, value in enumerate(segment.data):
            sequence = segment.sequence + offset
            cell = StreamByte(value, segment.packet_number, segment.timestamp)
            previous = by_sequence.get(sequence)
            if previous is None:
                by_sequence[sequence] = cell
            elif previous.value != value:
                raise ValueError(
                    "conflicting retransmission bytes in bounded PseudoTCP window"
                )

    if not by_sequence:
        return []

    chunks: list[tuple[int, list[StreamByte]]] = []
    start: int | None = None
    previous_sequence: int | None = None
    cells: list[StreamByte] = []

    for sequence in sorted(by_sequence):
        if previous_sequence is None or sequence != previous_sequence + 1:
            if cells and start is not None:
                chunks.append((start, cells))
            start = sequence
            cells = []
        cells.append(by_sequence[sequence])
        previous_sequence = sequence

    if cells and start is not None:
        chunks.append((start, cells))

    return chunks


def _parse_chunk(sender_name: str, cells: list[StreamByte]) -> list[VipFrame]:
    blob = bytes(cell.value for cell in cells)
    frames: list[VipFrame] = []
    offset = 0

    while offset + 8 <= len(blob):
        marker = blob.find(b"\x00\x06", offset)
        if marker < 0 or marker + 8 > len(blob):
            break

        body_len = int.from_bytes(blob[marker + 2 : marker + 4], "little")
        frame_len = 8 + body_len
        if body_len == 0 or body_len > MAX_VIP_BODY_LEN:
            offset = marker + 1
            continue
        if marker + frame_len > len(blob):
            break

        span = cells[marker : marker + frame_len]
        body = blob[marker + 8 : marker + frame_len]
        frames.append(
            VipFrame(
                direction=sender_name,
                first_packet=min(cell.packet_number for cell in span),
                last_packet=max(cell.packet_number for cell in span),
                timestamp=min(cell.timestamp for cell in span),
                request_id=int.from_bytes(blob[marker + 4 : marker + 8], "little"),
                body=body,
            )
        )
        offset = marker + frame_len

    return frames


def collect_vip_frames(analysis: FlowAnalysis) -> tuple[VipFrame, ...]:
    frames: list[VipFrame] = []
    for sender_name in ("CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT"):
        for _stream_start, cells in _stream_chunks(analysis, sender_name):
            frames.extend(_parse_chunk(sender_name, cells))
    return tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))


def _is_structural_ack(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.direction == "CLIENT_TO_DEVICE"
        and len(body) == 32
        and frame.prefix == 0x1800
        and frame.action == 0x0000
        and body[8:12] == b"\xff\xff\xff\xff"
    )


def _address_relation_matches(anchor: VipFrame, ack: VipFrame) -> bool:
    """Compare address roles without emitting either address value."""
    device = anchor.body
    body = ack.body
    return bool(
        len(device) == 40
        and len(body) == 32
        and body[12:20] == device[20:28]
        and body[20:22] == b"\x00\x00"
        and body[22:31] == device[30:39]
        and body[31] == 0x00
    )


def derive_ack_evidence(
    frames: Iterable[VipFrame],
    anchor_body_sha256: str = DEVICE_VIDEO_BODY_SHA256,
) -> AckEvidence:
    ordered = tuple(frames)
    anchors = [
        frame
        for frame in ordered
        if frame.direction == "DEVICE_TO_CLIENT"
        and frame.body_sha256 == anchor_body_sha256
        and frame.first_packet <= DEVICE_VIDEO_PCAP_PACKET <= frame.last_packet
    ]
    if len(anchors) != 1:
        raise ValueError(f"expected exactly one frozen device-video anchor, found {len(anchors)}")

    anchor = anchors[0]
    candidates = tuple(
        frame
        for frame in ordered
        if frame.direction == "CLIENT_TO_DEVICE"
        and frame.timestamp > anchor.timestamp
        and frame.request_id == anchor.request_id
    )
    matching = tuple(
        frame
        for frame in candidates
        if _is_structural_ack(frame) and _address_relation_matches(anchor, frame)
    )
    return AckEvidence(anchor=anchor, candidates=candidates, matching_acks=matching)


def _sequence_delta(anchor: VipFrame, ack: VipFrame) -> int | None:
    if anchor.sequence is None or ack.sequence is None:
        return None
    return (ack.sequence - anchor.sequence) & 0xFFFFFFFF


def report(evidence: AckEvidence) -> str:
    anchor = evidence.anchor
    lines = [
        "=== COMELIT ENTRANCE DEVICE VIDEO ACK PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        "DEVICE_VIDEO_ANCHOR=PASS",
        f"DEVICE_VIDEO_ANCHOR_PACKET_FIRST={anchor.first_packet}",
        f"DEVICE_VIDEO_ANCHOR_PACKET_LAST={anchor.last_packet}",
        f"DEVICE_VIDEO_PREFIX={_fmt_hex(anchor.prefix)}",
        f"DEVICE_VIDEO_ACTION={_fmt_hex(anchor.action)}",
        f"DEVICE_VIDEO_FLAGS={_fmt_hex(anchor.flags)}",
        f"DEVICE_VIDEO_BODY_LEN={anchor.body_length}",
        f"CLIENT_SAME_CTPP_FRAMES_AFTER_ANCHOR={len(evidence.candidates)}",
        f"STRUCTURAL_ACK_MATCH_COUNT={len(evidence.matching_acks)}",
    ]

    for ordinal, frame in enumerate(evidence.candidates, start=1):
        delta_ms = max(0.0, (frame.timestamp - anchor.timestamp) * 1000.0)
        lines.append(
            "POST_DEVICE_FRAME "
            f"ordinal={ordinal} "
            f"packet_first={frame.first_packet} "
            f"packet_last={frame.last_packet} "
            f"delta_ms={delta_ms:.3f} "
            f"body_len={frame.body_length} "
            f"prefix={_fmt_hex(frame.prefix)} "
            f"action={_fmt_hex(frame.action)} "
            f"flags={_fmt_hex(frame.flags)} "
            f"structural_ack={'true' if _is_structural_ack(frame) else 'false'} "
            f"address_relation_match={'true' if _address_relation_matches(anchor, frame) else 'false'}"
        )

    if len(evidence.matching_acks) == 1:
        ack = evidence.matching_acks[0]
        sequence_delta = _sequence_delta(anchor, ack)
        lines.extend(
            [
                "OFFICIAL_CLIENT_DEVICE_VIDEO_ACK=PROVEN",
                f"ACK_PACKET_FIRST={ack.first_packet}",
                f"ACK_PACKET_LAST={ack.last_packet}",
                f"ACK_BODY_LEN={ack.body_length}",
                f"ACK_PREFIX={_fmt_hex(ack.prefix)}",
                f"ACK_ACTION={_fmt_hex(ack.action)}",
                f"ACK_FLAGS={_fmt_hex(ack.flags)}",
                "ACK_ADDRESS_RELATION_MATCH=true",
                f"ACK_SEQUENCE_EQUALS_DEVICE={'true' if sequence_delta == 0 else 'false'}",
                f"ACK_SEQUENCE_DELTA={_fmt_hex(sequence_delta, 8)}",
                f"ACK_BODY_SHA256={ack.body_sha256}",
                "CAPTURE_DERIVED_ACK_CONTRACT=PASS",
            ]
        )
    else:
        lines.extend(
            [
                "OFFICIAL_CLIENT_DEVICE_VIDEO_ACK=NOT_PROVEN",
                "CAPTURE_DERIVED_ACK_CONTRACT=FAIL",
            ]
        )

    lines.extend(
        [
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE DEVICE VIDEO ACK PCAP FORENSIC ===",
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
        evidence = derive_ack_evidence(collect_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    output = report(evidence)
    print(output)
    return 0 if len(evidence.matching_acks) == 1 else 4


if __name__ == "__main__":
    raise SystemExit(main())
