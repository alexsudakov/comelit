#!/usr/bin/env python3
"""Correlate post-device-video structural ACKs with preceding ViP frames offline.

This analyzer is a follow-up to ``entrance_device_video_ack_pcap_forensic.py``.
The first forensic proved that the frozen capture contains several client-to-device
32-byte ``0x1800`` structural ACK-shaped frames after the entrance device ``0x0008``
event, but the initially assumed address-role mapping did not match.

This tool does not relax that contract or send an ACK.  Instead it reads only the
same frozen PCAP and reports correlation metadata for each structural ACK:

* sequence equality/delta relative to the device-video anchor;
* equal 8-byte and 9-byte slice *offset pairs* between the ACK and anchor;
* the same metadata against recent preceding device-to-client frames on the same
  CTPP request id.

Raw bytes, protocol address values, request ids, endpoints and media payload are
never emitted.  No network I/O is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    DEVICE_VIDEO_BODY_SHA256,
    DEVICE_VIDEO_PCAP_PACKET,
    EXPECTED_PCAP_SHA256,
    VipFrame,
    collect_vip_frames,
    load_capture,
    select_vip_flow,
)


MAX_PRECEDING_MS = 1000.0
MATCH_LENGTHS = (8, 9)


@dataclass(frozen=True)
class FrameRelation:
    frame: VipFrame
    delta_ms: float
    sequence_equal: bool
    sequence_delta: int | None
    matches8: tuple[tuple[int, int], ...]
    matches9: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class AckCorrelation:
    ack: VipFrame
    anchor_relation: FrameRelation
    preceding_relations: tuple[FrameRelation, ...]


def _fmt_hex(value: int | None, width: int = 4) -> str:
    if value is None:
        return "NONE"
    return f"0x{value:0{width}x}"


def _is_structural_ack(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.direction == "CLIENT_TO_DEVICE"
        and len(body) == 32
        and frame.prefix == 0x1800
        and frame.action == 0x0000
        and body[8:12] == b"\xff\xff\xff\xff"
    )


def _sequence_delta(source: VipFrame, ack: VipFrame) -> int | None:
    if source.sequence is None or ack.sequence is None:
        return None
    return (ack.sequence - source.sequence) & 0xFFFFFFFF


def _nontrivial_slice(value: bytes) -> bool:
    """Reject only constant padding-like slices; do not inspect/emit contents."""
    return bool(value) and any(byte != value[0] for byte in value[1:])


def equal_slice_offsets(
    source: bytes,
    ack: bytes,
    length: int,
    *,
    source_start: int = 10,
    ack_start: int = 12,
) -> tuple[tuple[int, int], ...]:
    """Return offset pairs whose equal slices may represent address relations.

    Only offsets are returned.  Constant all-zero/all-FF-style runs are ignored
    so padding cannot create a misleading correlation.
    """
    if length <= 0:
        raise ValueError("length must be positive")

    result: list[tuple[int, int]] = []
    for source_offset in range(source_start, len(source) - length + 1):
        candidate = source[source_offset : source_offset + length]
        if not _nontrivial_slice(candidate):
            continue
        for ack_offset in range(ack_start, len(ack) - length + 1):
            if candidate == ack[ack_offset : ack_offset + length]:
                result.append((source_offset, ack_offset))
    return tuple(result)


def relation(source: VipFrame, ack: VipFrame) -> FrameRelation:
    delta_ms = max(0.0, (ack.timestamp - source.timestamp) * 1000.0)
    seq_delta = _sequence_delta(source, ack)
    return FrameRelation(
        frame=source,
        delta_ms=delta_ms,
        sequence_equal=seq_delta == 0 if seq_delta is not None else False,
        sequence_delta=seq_delta,
        matches8=equal_slice_offsets(source.body, ack.body, 8),
        matches9=equal_slice_offsets(source.body, ack.body, 9),
    )


def _find_anchor(frames: Iterable[VipFrame]) -> VipFrame:
    anchors = [
        frame
        for frame in frames
        if frame.direction == "DEVICE_TO_CLIENT"
        and frame.body_sha256 == DEVICE_VIDEO_BODY_SHA256
        and frame.first_packet <= DEVICE_VIDEO_PCAP_PACKET <= frame.last_packet
    ]
    if len(anchors) != 1:
        raise ValueError(f"expected exactly one frozen device-video anchor, found {len(anchors)}")
    return anchors[0]


def correlate(frames: Iterable[VipFrame]) -> tuple[VipFrame, tuple[AckCorrelation, ...]]:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    anchor = _find_anchor(ordered)

    acks = tuple(
        frame
        for frame in ordered
        if frame.timestamp > anchor.timestamp
        and frame.request_id == anchor.request_id
        and _is_structural_ack(frame)
    )

    correlations: list[AckCorrelation] = []
    for ack in acks:
        preceding = [
            frame
            for frame in ordered
            if frame.direction == "DEVICE_TO_CLIENT"
            and frame.request_id == ack.request_id
            and frame.timestamp <= ack.timestamp
            and 0.0 <= (ack.timestamp - frame.timestamp) * 1000.0 <= MAX_PRECEDING_MS
        ]
        preceding_relations = tuple(
            relation(frame, ack)
            for frame in sorted(preceding, key=lambda item: item.timestamp, reverse=True)
        )
        correlations.append(
            AckCorrelation(
                ack=ack,
                anchor_relation=relation(anchor, ack),
                preceding_relations=preceding_relations,
            )
        )

    return anchor, tuple(correlations)


def _format_pairs(pairs: tuple[tuple[int, int], ...]) -> str:
    if not pairs:
        return "NONE"
    return ",".join(f"src{source}:ack{ack}" for source, ack in pairs)


def report(anchor: VipFrame, correlations: tuple[AckCorrelation, ...]) -> str:
    lines = [
        "=== COMELIT ENTRANCE ACK CORRELATION PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        "DEVICE_VIDEO_ANCHOR=PASS",
        f"DEVICE_VIDEO_ANCHOR_PACKET_FIRST={anchor.first_packet}",
        f"DEVICE_VIDEO_ANCHOR_PACKET_LAST={anchor.last_packet}",
        f"DEVICE_VIDEO_ACTION={_fmt_hex(anchor.action)}",
        f"DEVICE_VIDEO_BODY_LEN={anchor.body_length}",
        f"STRUCTURAL_ACK_COUNT={len(correlations)}",
    ]

    for ack_ordinal, item in enumerate(correlations, start=1):
        anchor_relation = item.anchor_relation
        lines.append(
            "ACK_ANCHOR_RELATION "
            f"ack_ordinal={ack_ordinal} "
            f"ack_packet_first={item.ack.first_packet} "
            f"ack_packet_last={item.ack.last_packet} "
            f"delta_ms={anchor_relation.delta_ms:.3f} "
            f"sequence_equal={'true' if anchor_relation.sequence_equal else 'false'} "
            f"sequence_delta={_fmt_hex(anchor_relation.sequence_delta, 8)} "
            f"match8_count={len(anchor_relation.matches8)} "
            f"match8_offsets={_format_pairs(anchor_relation.matches8)} "
            f"match9_count={len(anchor_relation.matches9)} "
            f"match9_offsets={_format_pairs(anchor_relation.matches9)}"
        )

        relevant = [
            candidate
            for candidate in item.preceding_relations
            if candidate.sequence_equal or candidate.matches8 or candidate.matches9
        ]
        if not relevant and item.preceding_relations:
            # Preserve one nearest-frame diagnostic even if no relation matched.
            relevant = [item.preceding_relations[0]]

        lines.append(
            f"ACK_PRECEDING_RELEVANT_COUNT ack_ordinal={ack_ordinal} count={len(relevant)}"
        )
        for candidate_ordinal, candidate in enumerate(relevant, start=1):
            lines.append(
                "ACK_PRECEDING_RELATION "
                f"ack_ordinal={ack_ordinal} "
                f"candidate_ordinal={candidate_ordinal} "
                f"device_packet_first={candidate.frame.first_packet} "
                f"device_packet_last={candidate.frame.last_packet} "
                f"device_action={_fmt_hex(candidate.frame.action)} "
                f"device_body_len={candidate.frame.body_length} "
                f"delta_ms={candidate.delta_ms:.3f} "
                f"sequence_equal={'true' if candidate.sequence_equal else 'false'} "
                f"sequence_delta={_fmt_hex(candidate.sequence_delta, 8)} "
                f"match8_count={len(candidate.matches8)} "
                f"match8_offsets={_format_pairs(candidate.matches8)} "
                f"match9_count={len(candidate.matches9)} "
                f"match9_offsets={_format_pairs(candidate.matches9)}"
            )

    lines.extend(
        [
            "ACK_BYTES_EMITTED=false",
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE ACK CORRELATION PCAP FORENSIC ===",
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
        anchor, correlations = correlate(collect_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(anchor, correlations))
    return 0 if correlations else 4


if __name__ == "__main__":
    raise SystemExit(main())
