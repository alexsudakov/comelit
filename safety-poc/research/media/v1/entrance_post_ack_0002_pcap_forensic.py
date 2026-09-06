#!/usr/bin/env python3
"""Offline forensic for the post-device-video 0x0002 signaling phase.

This analyzer reads only the frozen ``self_activation.pcap`` and reuses the
P42 ViP/PseudoTCP reassembly code. It extends only the bounded packet window so
analysis can follow the official client beyond the packet-200 device-video
anchor.

It identifies device-to-client CTPP frames with the exact structural shape
observed by the P49 controlled run:

    body_len=36, prefix=0x1840, action=0x0002, flags=0x000c

For each such frame it reports subsequent official-client frames before the
next matching device event, plus the first frame after the final event.
Output is structural metadata only: packet ranges, timing deltas, channel
class, body length, prefix/action/flags and same-CTPP client sequence deltas.

No request ids, endpoints, protocol addresses, literal sequence values, raw
payload, hex/base64 payload or media bytes are emitted. No network I/O is
performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import entrance_device_video_ack_pcap_forensic as p42
from entrance_device_video_ack_pcap_forensic import (
    DEVICE_VIDEO_BODY_SHA256,
    DEVICE_VIDEO_PCAP_PACKET,
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)


WINDOW_START_PACKET = 160
WINDOW_END_PACKET = 360


@dataclass(frozen=True)
class ClientResponse:
    frame: VipFrame
    channel_class: str
    delta_ms: float
    sequence_delta_from_previous_ctpp_client: int | None
    structural_ack: bool
    new_channel_after_anchor: bool


@dataclass(frozen=True)
class EventExchange:
    event: VipFrame
    responses: tuple[ClientResponse, ...]


@dataclass(frozen=True)
class ForensicResult:
    anchor: VipFrame
    events: tuple[EventExchange, ...]
    first_post_sequence_frame: VipFrame | None
    first_post_sequence_channel_class: str | None
    first_post_sequence_new_channel: bool


def _fmt_hex(value: int | None, width: int = 4) -> str:
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


def _is_post_ack_0002(frame: VipFrame, ctpp_request_id: int) -> bool:
    return bool(
        frame.direction == "DEVICE_TO_CLIENT"
        and frame.request_id == ctpp_request_id
        and frame.body_length == 36
        and frame.prefix == 0x1840
        and frame.action == 0x0002
        and frame.flags == 0x000c
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


def _channel_class(frame: VipFrame, anchor_request_id: int) -> str:
    if frame.request_id == anchor_request_id:
        return "CTPP"
    if frame.request_id == 0:
        return "CONTROL"
    return "OTHER"


def collect_extended_vip_frames(analysis) -> tuple[VipFrame, ...]:
    """Reuse P42 reassembly with a wider but still fixed capture window."""
    old_start = p42.WINDOW_START_PACKET
    old_end = p42.WINDOW_END_PACKET
    try:
        p42.WINDOW_START_PACKET = WINDOW_START_PACKET
        p42.WINDOW_END_PACKET = WINDOW_END_PACKET
        return p42.collect_vip_frames(analysis)
    finally:
        p42.WINDOW_START_PACKET = old_start
        p42.WINDOW_END_PACKET = old_end


def analyze(
    frames: Iterable[VipFrame],
    *,
    anchor_body_sha256: str = DEVICE_VIDEO_BODY_SHA256,
    anchor_packet: int = DEVICE_VIDEO_PCAP_PACKET,
) -> ForensicResult:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    anchor = _find_anchor(
        ordered,
        body_sha256=anchor_body_sha256,
        packet_number=anchor_packet,
    )

    known_request_ids_before_anchor = {
        frame.request_id for frame in ordered if frame.timestamp <= anchor.timestamp
    }

    events = tuple(
        frame
        for frame in ordered
        if frame.timestamp > anchor.timestamp
        and _is_post_ack_0002(frame, anchor.request_id)
    )
    if not events:
        raise ValueError("no post-anchor 0x0002/0x000c CTPP events found")

    ctpp_clients = tuple(
        frame
        for frame in ordered
        if frame.direction == "CLIENT_TO_DEVICE"
        and frame.request_id == anchor.request_id
    )

    exchanges: list[EventExchange] = []
    for index, event in enumerate(events):
        next_event = events[index + 1] if index + 1 < len(events) else None
        candidate_frames = [
            frame
            for frame in ordered
            if frame.direction == "CLIENT_TO_DEVICE"
            and frame.timestamp > event.timestamp
            and (next_event is None or frame.timestamp < next_event.timestamp)
        ]

        responses: list[ClientResponse] = []
        for frame in candidate_frames:
            previous_ctpp_candidates = [
                item
                for item in ctpp_clients
                if item.timestamp < frame.timestamp
            ]
            previous_ctpp = (
                max(
                    previous_ctpp_candidates,
                    key=lambda item: (item.timestamp, item.first_packet),
                )
                if previous_ctpp_candidates
                else None
            )
            responses.append(
                ClientResponse(
                    frame=frame,
                    channel_class=_channel_class(frame, anchor.request_id),
                    delta_ms=max(0.0, (frame.timestamp - event.timestamp) * 1000.0),
                    sequence_delta_from_previous_ctpp_client=(
                        _sequence_delta(previous_ctpp, frame)
                        if frame.request_id == anchor.request_id
                        else None
                    ),
                    structural_ack=_is_structural_ack(frame),
                    new_channel_after_anchor=(
                        frame.request_id not in known_request_ids_before_anchor
                    ),
                )
            )
        exchanges.append(EventExchange(event=event, responses=tuple(responses)))

    final_event = events[-1]
    later_frames = [frame for frame in ordered if frame.timestamp > final_event.timestamp]
    first_post = (
        min(later_frames, key=lambda item: (item.timestamp, item.first_packet))
        if later_frames
        else None
    )

    return ForensicResult(
        anchor=anchor,
        events=tuple(exchanges),
        first_post_sequence_frame=first_post,
        first_post_sequence_channel_class=(
            _channel_class(first_post, anchor.request_id) if first_post else None
        ),
        first_post_sequence_new_channel=bool(
            first_post and first_post.request_id not in known_request_ids_before_anchor
        ),
    )


def _frame_struct_fields(frame: VipFrame) -> str:
    if frame.body_length < 10:
        return "struct_fields=false"
    return (
        f"prefix={_fmt_hex(frame.prefix)} "
        f"action={_fmt_hex(frame.action)} "
        f"flags={_fmt_hex(frame.flags)}"
    )


def report(result: ForensicResult) -> str:
    lines = [
        "=== COMELIT ENTRANCE POST-ACK 0x0002 PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        "DEVICE_VIDEO_ANCHOR=PASS",
        f"DEVICE_VIDEO_ANCHOR_PACKET_FIRST={result.anchor.first_packet}",
        f"DEVICE_VIDEO_ANCHOR_PACKET_LAST={result.anchor.last_packet}",
        f"WINDOW_START_PACKET={WINDOW_START_PACKET}",
        f"WINDOW_END_PACKET={WINDOW_END_PACKET}",
        f"POST_ACK_0002_EVENT_COUNT={len(result.events)}",
    ]

    for event_ordinal, exchange in enumerate(result.events, start=1):
        event = exchange.event
        lines.append(
            "POST_ACK_0002_EVENT "
            f"ordinal={event_ordinal} "
            f"packet_first={event.first_packet} "
            f"packet_last={event.last_packet} "
            f"delta_from_anchor_ms={max(0.0, (event.timestamp - result.anchor.timestamp) * 1000.0):.3f} "
            f"body_len={event.body_length} "
            f"prefix={_fmt_hex(event.prefix)} "
            f"action={_fmt_hex(event.action)} "
            f"flags={_fmt_hex(event.flags)} "
            f"client_response_count={len(exchange.responses)}"
        )

        for response_ordinal, response in enumerate(exchange.responses, start=1):
            frame = response.frame
            lines.append(
                "POST_ACK_0002_CLIENT_RESPONSE "
                f"event_ordinal={event_ordinal} "
                f"response_ordinal={response_ordinal} "
                f"packet_first={frame.first_packet} "
                f"packet_last={frame.last_packet} "
                f"delta_ms={response.delta_ms:.3f} "
                f"channel={response.channel_class} "
                f"body_len={frame.body_length} "
                f"{_frame_struct_fields(frame)} "
                f"structural_ack={'true' if response.structural_ack else 'false'} "
                f"new_channel_after_anchor={'true' if response.new_channel_after_anchor else 'false'} "
                f"sequence_delta_prev_ctpp_client={_fmt_hex(response.sequence_delta_from_previous_ctpp_client, 8)}"
            )

    if result.first_post_sequence_frame is None:
        lines.append("FIRST_FRAME_AFTER_FINAL_0002=NONE")
    else:
        frame = result.first_post_sequence_frame
        lines.append(
            "FIRST_FRAME_AFTER_FINAL_0002 "
            f"direction={frame.direction} "
            f"packet_first={frame.first_packet} "
            f"packet_last={frame.last_packet} "
            f"channel={result.first_post_sequence_channel_class} "
            f"body_len={frame.body_length} "
            f"{_frame_struct_fields(frame)} "
            f"new_channel_after_anchor={'true' if result.first_post_sequence_new_channel else 'false'}"
        )

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
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE POST-ACK 0x0002 PCAP FORENSIC ===",
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
