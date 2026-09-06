#!/usr/bin/env python3
"""Offline field-relation forensic for client 0x000a / 0x001a signaling bodies.

P51/P52 proved the post-device-video signaling order, but order alone is not
sufficient to construct a safe live client.  This analyzer derives only
relationships from the frozen self_activation capture:

* exact target-frame identity and sequence deltas;
* occurrence positions of the two already-known ViP address roles;
* whether selected-flow endpoint address/port bytes occur inside the bodies;
* copy/equality spans between the mirrored 0x000a frames and client 0x001a;
* whether first wrapped-RTP stream identifiers occur inside client 0x001a.

No body bytes, protocol addresses, endpoint values, request ids, RTP sequence /
timestamp / SSRC values, raw payload, hex payload, or media are emitted.  The
analyzer performs no network I/O and sends no signaling.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    DEVICE_VIDEO_BODY_SHA256,
    DEVICE_VIDEO_PCAP_PACKET,
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import _read_selected_datagrams
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _opaque
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape

ANCHOR_PACKET = 200
CLIENT_000A_PACKET = 206
DEVICE_000A_PACKET = 209
CLIENT_001A_PACKET = 212
RTP_OFFSET = 8
MIN_COPY_SPAN = 4


@dataclass(frozen=True)
class MatchSpan:
    label: str
    start: int
    length: int


@dataclass(frozen=True)
class CopySpan:
    source_label: str
    source_start: int
    target_start: int
    length: int


@dataclass(frozen=True)
class FrameEvidence:
    label: str
    frame: VipFrame
    sequence_delta_previous_same_direction: int | None
    address_matches: tuple[MatchSpan, ...]
    endpoint_matches: tuple[MatchSpan, ...]


@dataclass(frozen=True)
class RtpRelation:
    stream_ordinal: int
    direction: str
    payload_type: int
    ssrc_matches: tuple[int, ...]
    sequence_matches: tuple[int, ...]
    timestamp_matches: tuple[int, ...]


@dataclass(frozen=True)
class Result:
    anchor: VipFrame
    client_000a: FrameEvidence
    device_000a: FrameEvidence
    client_001a: FrameEvidence
    mirror_compared_positions: int
    mirror_equal_positions: int
    mirror_diff_positions: tuple[int, ...]
    client_001a_copy_spans: tuple[CopySpan, ...]
    client_001a_copy_coverage_bytes: int
    client_001a_rtp_relations: tuple[RtpRelation, ...]


def _fmt_hex(value: int | None, width: int = 8) -> str:
    return "NONE" if value is None else f"0x{value:0{width}x}"


def _find_exact(
    frames: Iterable[VipFrame],
    *,
    direction: str,
    packet: int,
    action: int,
    body_len: int,
) -> VipFrame:
    matches = [
        frame
        for frame in frames
        if frame.direction == direction
        and frame.first_packet <= packet <= frame.last_packet
        and frame.action == action
        and frame.body_length == body_len
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {direction} action=0x{action:04x} frame at packet {packet}, found {len(matches)}"
        )
    return matches[0]


def _find_anchor(frames: Iterable[VipFrame]) -> VipFrame:
    matches = [
        frame
        for frame in frames
        if frame.direction == "DEVICE_TO_CLIENT"
        and frame.first_packet <= DEVICE_VIDEO_PCAP_PACKET <= frame.last_packet
        and frame.body_sha256 == DEVICE_VIDEO_BODY_SHA256
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frozen device-video anchor, found {len(matches)}")
    return matches[0]


def _sequence_delta_previous_same_direction(
    ordered: tuple[VipFrame, ...], target: VipFrame, *, request_id: int
) -> int | None:
    previous = [
        frame
        for frame in ordered
        if frame.request_id == request_id
        and frame.direction == target.direction
        and frame.timestamp < target.timestamp
        and frame.sequence is not None
    ]
    if not previous or target.sequence is None:
        return None
    nearest = max(previous, key=lambda frame: (frame.timestamp, frame.first_packet))
    assert nearest.sequence is not None
    return (target.sequence - nearest.sequence) & 0xFFFFFFFF


def _find_all(blob: bytes, needle: bytes) -> tuple[int, ...]:
    if not needle:
        return ()
    positions: list[int] = []
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            return tuple(positions)
        positions.append(pos)
        start = pos + 1


def _address_matches(frame: VipFrame, address_a: bytes, address_b: bytes) -> tuple[MatchSpan, ...]:
    spans: list[MatchSpan] = []
    for label, needle in (("ANCHOR_ADDRESS_ROLE_A", address_a), ("ANCHOR_ADDRESS_ROLE_B", address_b)):
        spans.extend(MatchSpan(label, pos, len(needle)) for pos in _find_all(frame.body, needle))
    return tuple(sorted(spans, key=lambda span: (span.start, span.label)))


def _endpoint_matches(frame: VipFrame, client, device) -> tuple[MatchSpan, ...]:
    patterns = (
        ("CLIENT_IPV4", client.address),
        ("DEVICE_IPV4", device.address),
        ("CLIENT_PORT_BE", client.port.to_bytes(2, "big")),
        ("CLIENT_PORT_LE", client.port.to_bytes(2, "little")),
        ("DEVICE_PORT_BE", device.port.to_bytes(2, "big")),
        ("DEVICE_PORT_LE", device.port.to_bytes(2, "little")),
    )
    spans: list[MatchSpan] = []
    for label, needle in patterns:
        spans.extend(MatchSpan(label, pos, len(needle)) for pos in _find_all(frame.body, needle))
    return tuple(sorted(spans, key=lambda span: (span.start, span.label)))


def _covered_positions(spans: Iterable[MatchSpan], length: int) -> set[int]:
    covered: set[int] = set(range(2, min(6, length)))  # sequence is always session-derived
    for span in spans:
        covered.update(range(span.start, min(length, span.start + span.length)))
    return covered


def _mirror_equality(
    left: FrameEvidence, right: FrameEvidence
) -> tuple[int, int, tuple[int, ...]]:
    if left.frame.body_length != right.frame.body_length:
        raise ValueError("mirrored 0x000a bodies have different lengths")
    length = left.frame.body_length
    masked = _covered_positions(
        left.address_matches + left.endpoint_matches + right.address_matches + right.endpoint_matches,
        length,
    )
    # Prefix/action/flags are structural fields already reported separately; compare them too.
    compared = [index for index in range(length) if index not in masked]
    diffs = tuple(index for index in compared if left.frame.body[index] != right.frame.body[index])
    return len(compared), len(compared) - len(diffs), diffs


def _best_copy_spans(target: bytes, sources: tuple[tuple[str, bytes], ...]) -> tuple[CopySpan, ...]:
    candidates: list[CopySpan] = []
    for source_label, source in sources:
        for src in range(len(source)):
            for dst in range(len(target)):
                size = 0
                while src + size < len(source) and dst + size < len(target) and source[src + size] == target[dst + size]:
                    size += 1
                if size >= MIN_COPY_SPAN:
                    candidates.append(CopySpan(source_label, src, dst, size))
    candidates.sort(key=lambda span: (-span.length, span.target_start, span.source_label, span.source_start))
    used: set[int] = set()
    selected: list[CopySpan] = []
    for span in candidates:
        positions = set(range(span.target_start, span.target_start + span.length))
        if positions & used:
            continue
        selected.append(span)
        used |= positions
    return tuple(sorted(selected, key=lambda span: span.target_start))


def _first_rtp_stream_relations(datagrams, target_body: bytes, client, device) -> tuple[RtpRelation, ...]:
    opaque = _opaque(datagrams, ANCHOR_PACKET + 18)  # packet 218 boundary
    groups: dict[tuple[str, int, int], list[tuple[bytes, object]]] = {}
    for item in opaque:
        if len(item.payload) <= RTP_OFFSET:
            continue
        inner = item.payload[RTP_OFFSET:]
        meta = _parse_rtp_v2_shape(inner)
        if meta is None:
            continue
        if item.source == client and item.target == device:
            direction = "CLIENT_TO_DEVICE"
        elif item.source == device and item.target == client:
            direction = "DEVICE_TO_CLIENT"
        else:
            continue
        groups.setdefault((direction, meta.ssrc, meta.payload_type), []).append((inner, meta))

    ordered = sorted(groups.items(), key=lambda pair: min(len(item[0]) for item in pair[1]))
    relations: list[RtpRelation] = []
    for ordinal, ((direction, _ssrc_key, payload_type), items) in enumerate(ordered, start=1):
        inner, meta = items[0]
        timestamp = int.from_bytes(inner[4:8], "big")
        patterns = {
            "ssrc": (meta.ssrc.to_bytes(4, "big"), meta.ssrc.to_bytes(4, "little")),
            "sequence": (meta.sequence.to_bytes(2, "big"), meta.sequence.to_bytes(2, "little")),
            "timestamp": (timestamp.to_bytes(4, "big"), timestamp.to_bytes(4, "little")),
        }
        relations.append(
            RtpRelation(
                stream_ordinal=ordinal,
                direction=direction,
                payload_type=payload_type,
                ssrc_matches=tuple(sorted(set(pos for needle in patterns["ssrc"] for pos in _find_all(target_body, needle)))),
                sequence_matches=tuple(sorted(set(pos for needle in patterns["sequence"] for pos in _find_all(target_body, needle)))),
                timestamp_matches=tuple(sorted(set(pos for needle in patterns["timestamp"] for pos in _find_all(target_body, needle)))),
            )
        )
    return tuple(relations)


def analyze(frames: Iterable[VipFrame], *, client, device, datagrams=()) -> Result:
    ordered = tuple(sorted(frames, key=lambda frame: (frame.timestamp, frame.first_packet)))
    anchor = _find_anchor(ordered)
    client_000a_frame = _find_exact(
        ordered, direction="CLIENT_TO_DEVICE", packet=CLIENT_000A_PACKET, action=0x000A, body_len=44
    )
    device_000a_frame = _find_exact(
        ordered, direction="DEVICE_TO_CLIENT", packet=DEVICE_000A_PACKET, action=0x000A, body_len=44
    )
    client_001a_frame = _find_exact(
        ordered, direction="CLIENT_TO_DEVICE", packet=CLIENT_001A_PACKET, action=0x001A, body_len=60
    )
    if not (anchor.request_id == client_000a_frame.request_id == device_000a_frame.request_id == client_001a_frame.request_id):
        raise ValueError("target signaling frames do not share the anchor CTPP request id")

    if anchor.body_length != 40:
        raise ValueError("unexpected device-video anchor body length")
    address_a = anchor.body[20:29]
    address_b = anchor.body[30:39]
    if len(address_a) != 9 or len(address_b) != 9 or address_a == address_b:
        raise ValueError("anchor address-role extraction failed")

    def evidence(label: str, frame: VipFrame) -> FrameEvidence:
        return FrameEvidence(
            label=label,
            frame=frame,
            sequence_delta_previous_same_direction=_sequence_delta_previous_same_direction(
                ordered, frame, request_id=anchor.request_id
            ),
            address_matches=_address_matches(frame, address_a, address_b),
            endpoint_matches=_endpoint_matches(frame, client, device),
        )

    client_000a = evidence("CLIENT_000A", client_000a_frame)
    device_000a = evidence("DEVICE_000A", device_000a_frame)
    client_001a = evidence("CLIENT_001A", client_001a_frame)

    compared, equal, diffs = _mirror_equality(client_000a, device_000a)
    copy_spans = _best_copy_spans(
        client_001a.frame.body,
        (("CLIENT_000A", client_000a.frame.body), ("DEVICE_000A", device_000a.frame.body)),
    )
    coverage = len({pos for span in copy_spans for pos in range(span.target_start, span.target_start + span.length)})
    rtp_relations = _first_rtp_stream_relations(datagrams, client_001a.frame.body, client, device) if datagrams else ()

    return Result(
        anchor=anchor,
        client_000a=client_000a,
        device_000a=device_000a,
        client_001a=client_001a,
        mirror_compared_positions=compared,
        mirror_equal_positions=equal,
        mirror_diff_positions=diffs,
        client_001a_copy_spans=copy_spans,
        client_001a_copy_coverage_bytes=coverage,
        client_001a_rtp_relations=rtp_relations,
    )


def _positions(values: Iterable[int]) -> str:
    data = tuple(values)
    return "NONE" if not data else ",".join(str(value) for value in data)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE CLIENT MEDIA SIGNALING BODY CONTRACT PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"ANCHOR_PACKET={ANCHOR_PACKET}",
    ]
    for evidence in (result.client_000a, result.device_000a, result.client_001a):
        frame = evidence.frame
        lines.append(
            "SIGNAL_FRAME "
            f"label={evidence.label} direction={frame.direction} packet_first={frame.first_packet} "
            f"packet_last={frame.last_packet} body_len={frame.body_length} "
            f"prefix=0x{frame.prefix:04x} action=0x{frame.action:04x} flags=0x{frame.flags:04x} "
            f"sequence_delta_prev_same_direction={_fmt_hex(evidence.sequence_delta_previous_same_direction)} "
            f"address_match_count={len(evidence.address_matches)} endpoint_match_count={len(evidence.endpoint_matches)}"
        )
        for span in evidence.address_matches:
            lines.append(
                f"SIGNAL_ADDRESS_RELATION label={evidence.label} role={span.label} start={span.start} length={span.length}"
            )
        for span in evidence.endpoint_matches:
            lines.append(
                f"SIGNAL_ENDPOINT_RELATION label={evidence.label} kind={span.label} start={span.start} length={span.length}"
            )

    lines.extend(
        [
            f"MIRROR_000A_COMPARED_POSITIONS={result.mirror_compared_positions}",
            f"MIRROR_000A_EQUAL_POSITIONS={result.mirror_equal_positions}",
            f"MIRROR_000A_DIFF_POSITION_COUNT={len(result.mirror_diff_positions)}",
            f"MIRROR_000A_DIFF_POSITIONS={_positions(result.mirror_diff_positions)}",
            f"CLIENT_001A_COPY_SPAN_COUNT={len(result.client_001a_copy_spans)}",
            f"CLIENT_001A_COPY_COVERAGE_BYTES={result.client_001a_copy_coverage_bytes}",
        ]
    )
    for ordinal, span in enumerate(result.client_001a_copy_spans, start=1):
        lines.append(
            "CLIENT_001A_COPY_SPAN "
            f"ordinal={ordinal} source={span.source_label} source_start={span.source_start} "
            f"target_start={span.target_start} length={span.length}"
        )
    for relation in result.client_001a_rtp_relations:
        lines.append(
            "CLIENT_001A_RTP_RELATION "
            f"stream_ordinal={relation.stream_ordinal} direction={relation.direction} payload_type={relation.payload_type} "
            f"ssrc_match_positions={_positions(relation.ssrc_matches)} "
            f"sequence_match_positions={_positions(relation.sequence_matches)} "
            f"timestamp_match_positions={_positions(relation.timestamp_matches)}"
        )

    lines.extend(
        [
            "REQUEST_ID_EMITTED=false",
            "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
            "ENDPOINT_VALUES_EMITTED=false",
            "RTP_IDENTIFIER_VALUES_EMITTED=false",
            "SEQUENCE_VALUES_EMITTED=false",
            "TIMESTAMP_VALUES_EMITTED=false",
            "SSRC_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE CLIENT MEDIA SIGNALING BODY CONTRACT PCAP FORENSIC ===",
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
        datagrams = _read_selected_datagrams(args.pcap, client=analysis.client, device=analysis.device)
        result = analyze(frames, client=analysis.client, device=analysis.device, datagrams=datagrams)
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
