#!/usr/bin/env python3
"""Offline structural timeline for the entrance post-device-video phase.

This analyzer reads only the frozen ``self_activation.pcap``. It reuses the
existing P42/P50 PseudoTCP + ViP reassembly path and reports structural metadata
for every reconstructed ViP frame whose packet span intersects packets 200..240.

The goal is to bind the official-client sequence after the packet-200 device
video event without guessing protocol semantics: device 0x0002, its ACK, client
0x000a, the next device frame / ACK pair, client 0x001a, and any newly observed
request/channel identity.

Output never includes request ids, endpoints, protocol addresses, literal
sequence values, raw payload, encoded payload, or media bytes. Address-role
relations are checked only in memory. No network I/O is performed.
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
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from entrance_ack_sequence_pcap_forensic import _reversed_tail_address_relation


TIMELINE_START_PACKET = 200
TIMELINE_END_PACKET = 240


@dataclass(frozen=True)
class StructuralFrame:
    frame: VipFrame
    channel_class: str
    new_channel_after_anchor: bool
    delta_from_anchor_ms: float
    sequence_delta_previous_same_ctpp_direction: int | None


@dataclass(frozen=True)
class AckBinding:
    ack: VipFrame
    nearest_device: VipFrame
    delta_ms: float
    intervening_same_ctpp_frames: int
    reversed_tail_relation: bool


@dataclass(frozen=True)
class TimelineResult:
    anchor: VipFrame
    frames: tuple[StructuralFrame, ...]
    ack_bindings: tuple[AckBinding, ...]


def _fmt_hex(value: int | None, width: int = 4) -> str:
    if value is None:
        return "NONE"
    return f"0x{value:0{width}x}"


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


def _intersects_timeline(frame: VipFrame) -> bool:
    return not (
        frame.last_packet < TIMELINE_START_PACKET
        or frame.first_packet > TIMELINE_END_PACKET
    )


def _channel_class(
    frame: VipFrame,
    *,
    ctpp_request_id: int,
    known_request_ids_before_anchor: set[int],
) -> tuple[str, bool]:
    if frame.request_id == ctpp_request_id:
        return "CTPP", False
    if frame.request_id == 0:
        return "CONTROL", False
    is_new = frame.request_id not in known_request_ids_before_anchor
    return ("OTHER_NEW" if is_new else "OTHER_EXISTING"), is_new


def _is_structural_ack(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.direction == "CLIENT_TO_DEVICE"
        and len(body) == 32
        and frame.prefix == 0x1800
        and frame.action == 0x0000
        and body[8:12] == b"\xff\xff\xff\xff"
    )


def _sequence_delta(previous: VipFrame | None, current: VipFrame) -> int | None:
    if previous is None or previous.sequence is None or current.sequence is None:
        return None
    return (current.sequence - previous.sequence) & 0xFFFFFFFF


def analyze(
    frames: Iterable[VipFrame],
    *,
    anchor_body_sha256: str = DEVICE_VIDEO_BODY_SHA256,
    anchor_packet: int = DEVICE_VIDEO_PCAP_PACKET,
) -> TimelineResult:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    anchor = _find_anchor(
        ordered,
        body_sha256=anchor_body_sha256,
        packet_number=anchor_packet,
    )

    known_request_ids_before_anchor = {
        frame.request_id for frame in ordered if frame.timestamp <= anchor.timestamp
    }

    selected = tuple(frame for frame in ordered if _intersects_timeline(frame))
    if not selected:
        raise ValueError("no ViP frames in structural timeline window")

    structural: list[StructuralFrame] = []
    previous_ctpp_by_direction: dict[str, VipFrame] = {}
    for frame in selected:
        channel, is_new = _channel_class(
            frame,
            ctpp_request_id=anchor.request_id,
            known_request_ids_before_anchor=known_request_ids_before_anchor,
        )
        previous = previous_ctpp_by_direction.get(frame.direction)
        delta = (
            _sequence_delta(previous, frame)
            if channel == "CTPP"
            else None
        )
        structural.append(
            StructuralFrame(
                frame=frame,
                channel_class=channel,
                new_channel_after_anchor=is_new,
                delta_from_anchor_ms=(frame.timestamp - anchor.timestamp) * 1000.0,
                sequence_delta_previous_same_ctpp_direction=delta,
            )
        )
        if channel == "CTPP":
            previous_ctpp_by_direction[frame.direction] = frame

    same_ctpp = tuple(frame for frame in ordered if frame.request_id == anchor.request_id)
    ack_bindings: list[AckBinding] = []
    for frame in selected:
        if not _is_structural_ack(frame):
            continue
        preceding_devices = [
            item
            for item in same_ctpp
            if item.direction == "DEVICE_TO_CLIENT" and item.timestamp < frame.timestamp
        ]
        if not preceding_devices:
            raise ValueError("structural ACK has no preceding same-CTPP device frame")
        nearest = max(
            preceding_devices,
            key=lambda item: (item.timestamp, item.first_packet),
        )
        intervening = sum(
            1
            for item in same_ctpp
            if nearest.timestamp < item.timestamp < frame.timestamp
        )
        ack_bindings.append(
            AckBinding(
                ack=frame,
                nearest_device=nearest,
                delta_ms=(frame.timestamp - nearest.timestamp) * 1000.0,
                intervening_same_ctpp_frames=intervening,
                reversed_tail_relation=_reversed_tail_address_relation(nearest, frame),
            )
        )

    return TimelineResult(
        anchor=anchor,
        frames=tuple(structural),
        ack_bindings=tuple(ack_bindings),
    )


def _struct_fields(frame: VipFrame) -> str:
    if frame.body_length < 10:
        return "struct_fields=false"
    return (
        f"prefix={_fmt_hex(frame.prefix)} "
        f"action={_fmt_hex(frame.action)} "
        f"flags={_fmt_hex(frame.flags)}"
    )


def report(result: TimelineResult) -> str:
    new_channel_frames = [item for item in result.frames if item.new_channel_after_anchor]
    lines = [
        "=== COMELIT ENTRANCE POST-ACK STRUCTURAL TIMELINE PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        "DEVICE_VIDEO_ANCHOR=PASS",
        f"DEVICE_VIDEO_ANCHOR_PACKET_FIRST={result.anchor.first_packet}",
        f"DEVICE_VIDEO_ANCHOR_PACKET_LAST={result.anchor.last_packet}",
        f"TIMELINE_START_PACKET={TIMELINE_START_PACKET}",
        f"TIMELINE_END_PACKET={TIMELINE_END_PACKET}",
        f"STRUCTURAL_TIMELINE_FRAME_COUNT={len(result.frames)}",
        f"STRUCTURAL_ACK_BINDING_COUNT={len(result.ack_bindings)}",
        f"NEW_CHANNEL_FRAME_COUNT={len(new_channel_frames)}",
    ]

    for ordinal, item in enumerate(result.frames, start=1):
        frame = item.frame
        lines.append(
            "STRUCTURAL_TIMELINE_FRAME "
            f"ordinal={ordinal} "
            f"direction={frame.direction} "
            f"packet_first={frame.first_packet} "
            f"packet_last={frame.last_packet} "
            f"delta_from_anchor_ms={item.delta_from_anchor_ms:.3f} "
            f"channel={item.channel_class} "
            f"new_channel_after_anchor={'true' if item.new_channel_after_anchor else 'false'} "
            f"body_len={frame.body_length} "
            f"{_struct_fields(frame)} "
            f"structural_ack={'true' if _is_structural_ack(frame) else 'false'} "
            f"sequence_delta_prev_same_ctpp_direction={_fmt_hex(item.sequence_delta_previous_same_ctpp_direction, 8)}"
        )

    for ordinal, binding in enumerate(result.ack_bindings, start=1):
        lines.append(
            "STRUCTURAL_ACK_BINDING "
            f"ordinal={ordinal} "
            f"ack_packet_first={binding.ack.first_packet} "
            f"ack_packet_last={binding.ack.last_packet} "
            f"nearest_device_packet_first={binding.nearest_device.first_packet} "
            f"nearest_device_packet_last={binding.nearest_device.last_packet} "
            f"nearest_device_body_len={binding.nearest_device.body_length} "
            f"nearest_device_prefix={_fmt_hex(binding.nearest_device.prefix)} "
            f"nearest_device_action={_fmt_hex(binding.nearest_device.action)} "
            f"nearest_device_flags={_fmt_hex(binding.nearest_device.flags)} "
            f"delta_ms={binding.delta_ms:.3f} "
            f"intervening_same_ctpp_frames={binding.intervening_same_ctpp_frames} "
            f"reversed_tail_relation={'true' if binding.reversed_tail_relation else 'false'}"
        )

    if new_channel_frames:
        first = new_channel_frames[0].frame
        lines.append(
            "FIRST_NEW_CHANNEL_FRAME "
            f"direction={first.direction} "
            f"packet_first={first.first_packet} "
            f"packet_last={first.last_packet} "
            f"body_len={first.body_length} "
            f"{_struct_fields(first)}"
        )
    else:
        lines.append("FIRST_NEW_CHANNEL_FRAME=NONE")

    lines.extend(
        [
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "SEQUENCE_VALUES_EMITTED=false",
            "SEQUENCE_DELTAS_EMITTED=true",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE POST-ACK STRUCTURAL TIMELINE PCAP FORENSIC ===",
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
        result = analyze(collect_extended_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
