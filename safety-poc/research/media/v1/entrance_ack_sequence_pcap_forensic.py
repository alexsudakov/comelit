#!/usr/bin/env python3
"""Correlate entrance ACKs by temporal adjacency and client sequence deltas.

This analyzer is capture-only. It consumes the same frozen self_activation PCAP
used by the P42/P43 forensics and emits only structural metadata needed to bind
post-device structural ACKs without relying on reusable address values alone.

For the CTPP request containing the frozen entrance device-video anchor it
reports:

* every client frame in the bounded capture window with sequence delta from the
  previous client frame (never the sequence value itself);
* for every structural 0x1800 ACK after the anchor, the nearest preceding
  device frame, temporal gap, number of intervening same-CTPP application
  frames, generic reversed tail-address relation, and sequence deltas relative
  to the previous client frame / previous structural ACK;
* how many ACKs are uniquely immediate candidates for the frozen device-video
  anchor.

No request ids, endpoints, protocol address values, raw payload, media bytes, or
literal sequence values are emitted. No network I/O is performed.
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


@dataclass(frozen=True)
class ClientSequenceRelation:
    frame: VipFrame
    delta_from_anchor_ms: float
    sequence_delta_from_previous_client: int | None


@dataclass(frozen=True)
class AckBinding:
    ack: VipFrame
    nearest_device: VipFrame
    delta_ms: float
    intervening_same_ctpp_frames: int
    reversed_tail_relation: bool
    sequence_delta_from_previous_client: int | None
    sequence_delta_from_previous_ack: int | None
    nearest_device_is_anchor: bool


def _fmt_hex(value: int | None, width: int = 8) -> str:
    if value is None:
        return "NONE"
    return f"0x{value:0{width}x}"


def _sequence_delta(previous: VipFrame | None, current: VipFrame) -> int | None:
    if previous is None or previous.sequence is None or current.sequence is None:
        return None
    return (current.sequence - previous.sequence) & 0xFFFFFFFF


def _is_structural_ack(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.direction == "CLIENT_TO_DEVICE"
        and len(body) == 32
        and frame.prefix == 0x1800
        and frame.action == 0x0000
        and body[8:12] == b"\xff\xff\xff\xff"
    )


def _reversed_tail_address_relation(device: VipFrame, ack: VipFrame) -> bool:
    """Check the capture-derived reversed address roles generically.

    The relevant device frames in the frozen session have variable body lengths
    (32/36/40/44...). Their two NUL-terminated 9-byte address fields occupy the
    final 20 bytes: first at ``len-20``, second at ``len-10``. Structural ACKs
    carry the second device field first and the first device field second.
    Values are compared only in memory and never emitted.
    """
    source = device.body
    body = ack.body
    if len(source) < 20 or len(body) != 32:
        return False

    first = len(source) - 20
    second = len(source) - 10
    return bool(
        source[first + 9] == 0x00
        and source[second + 9] == 0x00
        and body[12:21] == source[second : second + 9]
        and body[21] == 0x00
        and body[22:31] == source[first : first + 9]
        and body[31] == 0x00
    )


def _find_anchor(
    frames: Iterable[VipFrame],
    *,
    body_sha256: str = DEVICE_VIDEO_BODY_SHA256,
    packet_number: int = DEVICE_VIDEO_PCAP_PACKET,
) -> VipFrame:
    anchors = [
        frame
        for frame in frames
        if frame.direction == "DEVICE_TO_CLIENT"
        and frame.body_sha256 == body_sha256
        and frame.first_packet <= packet_number <= frame.last_packet
    ]
    if len(anchors) != 1:
        raise ValueError(f"expected exactly one device-video anchor, found {len(anchors)}")
    return anchors[0]


def analyze(
    frames: Iterable[VipFrame],
    *,
    anchor_body_sha256: str = DEVICE_VIDEO_BODY_SHA256,
    anchor_packet: int = DEVICE_VIDEO_PCAP_PACKET,
) -> tuple[VipFrame, tuple[ClientSequenceRelation, ...], tuple[AckBinding, ...]]:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    anchor = _find_anchor(
        ordered,
        body_sha256=anchor_body_sha256,
        packet_number=anchor_packet,
    )

    same_ctpp = tuple(frame for frame in ordered if frame.request_id == anchor.request_id)
    client_frames = tuple(frame for frame in same_ctpp if frame.direction == "CLIENT_TO_DEVICE")

    client_relations: list[ClientSequenceRelation] = []
    previous_client: VipFrame | None = None
    for frame in client_frames:
        client_relations.append(
            ClientSequenceRelation(
                frame=frame,
                delta_from_anchor_ms=(frame.timestamp - anchor.timestamp) * 1000.0,
                sequence_delta_from_previous_client=_sequence_delta(previous_client, frame),
            )
        )
        previous_client = frame

    ack_frames = tuple(
        frame
        for frame in client_frames
        if frame.timestamp > anchor.timestamp and _is_structural_ack(frame)
    )

    bindings: list[AckBinding] = []
    previous_ack: VipFrame | None = None
    for ack in ack_frames:
        preceding_devices = [
            frame
            for frame in same_ctpp
            if frame.direction == "DEVICE_TO_CLIENT" and frame.timestamp < ack.timestamp
        ]
        if not preceding_devices:
            raise ValueError("structural ACK has no preceding device frame")
        nearest = max(preceding_devices, key=lambda item: (item.timestamp, item.first_packet))

        previous_clients = [
            frame
            for frame in client_frames
            if frame.timestamp < ack.timestamp
        ]
        previous_client = (
            max(previous_clients, key=lambda item: (item.timestamp, item.first_packet))
            if previous_clients
            else None
        )

        intervening = sum(
            1
            for frame in same_ctpp
            if nearest.timestamp < frame.timestamp < ack.timestamp
        )

        bindings.append(
            AckBinding(
                ack=ack,
                nearest_device=nearest,
                delta_ms=(ack.timestamp - nearest.timestamp) * 1000.0,
                intervening_same_ctpp_frames=intervening,
                reversed_tail_relation=_reversed_tail_address_relation(nearest, ack),
                sequence_delta_from_previous_client=_sequence_delta(previous_client, ack),
                sequence_delta_from_previous_ack=_sequence_delta(previous_ack, ack),
                nearest_device_is_anchor=(nearest is anchor),
            )
        )
        previous_ack = ack

    return anchor, tuple(client_relations), tuple(bindings)


def report(
    anchor: VipFrame,
    client_relations: tuple[ClientSequenceRelation, ...],
    bindings: tuple[AckBinding, ...],
) -> str:
    immediate_anchor_candidates = [
        item
        for item in bindings
        if item.nearest_device_is_anchor
        and item.intervening_same_ctpp_frames == 0
        and item.reversed_tail_relation
    ]

    lines = [
        "=== COMELIT ENTRANCE ACK SEQUENCE PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        "DEVICE_VIDEO_ANCHOR=PASS",
        f"DEVICE_VIDEO_ANCHOR_PACKET_FIRST={anchor.first_packet}",
        f"DEVICE_VIDEO_ANCHOR_PACKET_LAST={anchor.last_packet}",
        f"DEVICE_VIDEO_ACTION=0x{anchor.action:04x}" if anchor.action is not None else "DEVICE_VIDEO_ACTION=NONE",
        f"CLIENT_SEQUENCE_FRAME_COUNT={len(client_relations)}",
        f"STRUCTURAL_ACK_BINDING_COUNT={len(bindings)}",
    ]

    for ordinal, item in enumerate(client_relations, start=1):
        position = "AFTER_ANCHOR" if item.delta_from_anchor_ms > 0 else "BEFORE_ANCHOR"
        lines.append(
            "CLIENT_SEQUENCE_FRAME "
            f"ordinal={ordinal} "
            f"packet_first={item.frame.first_packet} "
            f"packet_last={item.frame.last_packet} "
            f"position={position} "
            f"delta_from_anchor_ms={item.delta_from_anchor_ms:.3f} "
            f"body_len={item.frame.body_length} "
            f"prefix=0x{item.frame.prefix:04x} " if item.frame.prefix is not None else "prefix=NONE "
        )
        lines[-1] += (
            f"action=0x{item.frame.action:04x} " if item.frame.action is not None else "action=NONE "
        )
        lines[-1] += (
            f"structural_ack={'true' if _is_structural_ack(item.frame) else 'false'} "
            f"sequence_delta_prev_client={_fmt_hex(item.sequence_delta_from_previous_client)}"
        )

    for ordinal, item in enumerate(bindings, start=1):
        lines.append(
            "ACK_BINDING "
            f"ack_ordinal={ordinal} "
            f"ack_packet_first={item.ack.first_packet} "
            f"ack_packet_last={item.ack.last_packet} "
            f"nearest_device_packet_first={item.nearest_device.first_packet} "
            f"nearest_device_packet_last={item.nearest_device.last_packet} "
            f"nearest_device_action=0x{item.nearest_device.action:04x} "
            f"nearest_device_body_len={item.nearest_device.body_length} "
            f"delta_ms={item.delta_ms:.3f} "
            f"intervening_same_ctpp_frames={item.intervening_same_ctpp_frames} "
            f"reversed_tail_relation={'true' if item.reversed_tail_relation else 'false'} "
            f"nearest_device_is_anchor={'true' if item.nearest_device_is_anchor else 'false'} "
            f"sequence_delta_prev_client={_fmt_hex(item.sequence_delta_from_previous_client)} "
            f"sequence_delta_prev_ack={_fmt_hex(item.sequence_delta_from_previous_ack)}"
        )

    lines.extend(
        [
            f"ANCHOR_IMMEDIATE_ACK_CANDIDATE_COUNT={len(immediate_anchor_candidates)}",
            "ACK_SEQUENCE_VALUES_EMITTED=false",
            "ACK_SEQUENCE_DELTAS_EMITTED=true",
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
            "=== END COMELIT ENTRANCE ACK SEQUENCE PCAP FORENSIC ===",
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
        anchor, client_relations, bindings = analyze(collect_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(anchor, client_relations, bindings))
    return 0 if bindings else 4


if __name__ == "__main__":
    raise SystemExit(main())
