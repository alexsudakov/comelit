#!/usr/bin/env python3
"""Offline forensic for the RTPC CONTROL exchange around packets 206-209.

P66 proved that the two packet-206 client RTPC opens carry fresh sequential
runtime ids.  This analyzer closes the remaining outbound CONTROL gap before a
live media-signaling candidate:

* validates the complete fixed 15-byte client-open template while masking only
  the two runtime request-id bytes;
* binds the two device 12-byte echoes to the two generated request ids;
* characterizes the single packet-208 client 12-byte CONTROL response relative
  to the immediately preceding device echo and both runtime ids.

Only structural relations and byte positions are emitted. Request-id values,
CONTROL bytes, addresses/endpoints, raw/hex/base64 payload and media are never
emitted. No network I/O or signaling is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from entrance_rtpc_control_open_contract_pcap_forensic import _client_rtpc_opens

OPEN_PACKET = 206
CLIENT_RESPONSE_PACKET = 208
CONTROL_WINDOW_START_PACKET = 205
CONTROL_WINDOW_END_PACKET = 209


@dataclass(frozen=True)
class EchoRelation:
    ordinal: int
    packet_first: int
    request_id_positions: tuple[int, ...]


@dataclass(frozen=True)
class Result:
    open_count: int
    open_full_template_ok: bool
    device_echo_count: int
    device_echo_relations: tuple[EchoRelation, ...]
    device_echo_common_request_position: int | None
    client_response_count: int
    client_response_exact_preceding_echo: bool
    client_response_diff_positions: tuple[int, ...]
    client_response_request_id_ordinals: tuple[int, ...]
    client_response_request_id_positions: tuple[int, ...]

    @property
    def live_control_generation_contract_ok(self) -> bool:
        return bool(
            self.open_count == 2
            and self.open_full_template_ok
            and self.device_echo_count == 2
            and len(self.device_echo_relations) == 2
            and all(item.request_id_positions for item in self.device_echo_relations)
            and self.device_echo_common_request_position is not None
            and self.client_response_count == 1
            and self.client_response_exact_preceding_echo
        )


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


def _controls(frames: Iterable[VipFrame]) -> tuple[VipFrame, ...]:
    return tuple(
        sorted(
            (
                frame
                for frame in frames
                if frame.request_id == 0
                and CONTROL_WINDOW_START_PACKET <= frame.first_packet <= CONTROL_WINDOW_END_PACKET
                and frame.body_length in (12, 15)
            ),
            key=lambda item: (item.timestamp, item.first_packet),
        )
    )


def _diff_positions(left: bytes, right: bytes) -> tuple[int, ...]:
    if len(left) != len(right):
        return tuple(range(max(len(left), len(right))))
    return tuple(index for index, (a, b) in enumerate(zip(left, right)) if a != b)


def analyze(frames: Iterable[VipFrame]) -> Result:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    opens = _client_rtpc_opens(ordered)
    if len(opens) != 2:
        raise ValueError(f"expected exactly two client RTPC opens, found {len(opens)}")

    request_ids = tuple(frame.body[12:14] for frame in opens)
    open_full_template_ok = all(
        len(frame.body) == 15
        and int.from_bytes(frame.body[0:2], "little") == 0xABCD
        and frame.body[2:8] == b"\x00" * 6
        and frame.body[8:12] == b"RTPC"
        and frame.body[14] == 0x00
        for frame in opens
    )

    controls = _controls(ordered)
    device_12 = tuple(
        frame
        for frame in controls
        if frame.direction == "DEVICE_TO_CLIENT"
        and frame.body_length == 12
        and frame.first_packet > OPEN_PACKET
    )

    echo_relations: list[EchoRelation] = []
    used_packets: set[int] = set()
    for ordinal, request_id in enumerate(request_ids, start=1):
        matches = []
        for frame in device_12:
            positions = _find_all(frame.body, request_id)
            if positions:
                matches.append((frame, positions))
        if len(matches) != 1:
            echo_relations.append(EchoRelation(ordinal, 0, ()))
            continue
        frame, positions = matches[0]
        used_packets.add(frame.first_packet)
        echo_relations.append(EchoRelation(ordinal, frame.first_packet, positions))

    common_position: int | None = None
    if len(echo_relations) == 2 and all(len(item.request_id_positions) == 1 for item in echo_relations):
        positions = {item.request_id_positions[0] for item in echo_relations}
        if len(positions) == 1:
            common_position = next(iter(positions))

    client_responses = tuple(
        frame
        for frame in controls
        if frame.direction == "CLIENT_TO_DEVICE"
        and frame.body_length == 12
        and frame.first_packet == CLIENT_RESPONSE_PACKET
    )

    exact_echo = False
    response_diffs: tuple[int, ...] = ()
    response_ordinals: tuple[int, ...] = ()
    response_positions: tuple[int, ...] = ()
    if len(client_responses) == 1:
        response = client_responses[0]
        preceding_device = [
            frame
            for frame in device_12
            if (frame.timestamp, frame.first_packet) < (response.timestamp, response.first_packet)
        ]
        if preceding_device:
            nearest = max(preceding_device, key=lambda item: (item.timestamp, item.first_packet))
            response_diffs = _diff_positions(nearest.body, response.body)
            exact_echo = not response_diffs

        ordinal_hits: list[int] = []
        position_hits: set[int] = set()
        for ordinal, request_id in enumerate(request_ids, start=1):
            positions = _find_all(response.body, request_id)
            if positions:
                ordinal_hits.append(ordinal)
                position_hits.update(positions)
        response_ordinals = tuple(ordinal_hits)
        response_positions = tuple(sorted(position_hits))

    return Result(
        open_count=len(opens),
        open_full_template_ok=open_full_template_ok,
        device_echo_count=len(device_12),
        device_echo_relations=tuple(echo_relations),
        device_echo_common_request_position=common_position,
        client_response_count=len(client_responses),
        client_response_exact_preceding_echo=exact_echo,
        client_response_diff_positions=response_diffs,
        client_response_request_id_ordinals=response_ordinals,
        client_response_request_id_positions=response_positions,
    )


def _positions(values: tuple[int, ...]) -> str:
    return "NONE" if not values else ",".join(str(value) for value in values)


def _ordinals(values: tuple[int, ...]) -> str:
    return "NONE" if not values else ",".join(str(value) for value in values)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE RTPC CONTROL RESPONSE CONTRACT PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"CLIENT_RTPC_OPEN_COUNT={result.open_count}",
        f"CLIENT_RTPC_OPEN_FULL_TEMPLATE_CONTRACT={'PASS' if result.open_full_template_ok else 'FAIL'}",
        f"DEVICE_RTPC_ECHO_COUNT={result.device_echo_count}",
    ]
    for item in result.device_echo_relations:
        lines.append(
            "DEVICE_RTPC_ECHO_RELATION "
            f"ordinal={item.ordinal} "
            f"packet_first={item.packet_first if item.packet_first else 'NONE'} "
            f"request_id_positions={_positions(item.request_id_positions)}"
        )
    lines.extend(
        [
            "DEVICE_RTPC_ECHO_COMMON_REQUEST_ID_POSITION="
            + (str(result.device_echo_common_request_position) if result.device_echo_common_request_position is not None else "NONE"),
            f"CLIENT_RTPC_RESPONSE_COUNT={result.client_response_count}",
            f"CLIENT_RTPC_RESPONSE_EXACT_PRECEDING_DEVICE_ECHO={'true' if result.client_response_exact_preceding_echo else 'false'}",
            f"CLIENT_RTPC_RESPONSE_DIFF_POSITION_COUNT={len(result.client_response_diff_positions)}",
            f"CLIENT_RTPC_RESPONSE_DIFF_POSITIONS={_positions(result.client_response_diff_positions)}",
            f"CLIENT_RTPC_RESPONSE_REQUEST_ID_ORDINALS={_ordinals(result.client_response_request_id_ordinals)}",
            f"CLIENT_RTPC_RESPONSE_REQUEST_ID_POSITIONS={_positions(result.client_response_request_id_positions)}",
            f"RTPC_LIVE_CONTROL_GENERATION_CONTRACT={'PASS' if result.live_control_generation_contract_ok else 'NOT_PROVEN'}",
            "REQUEST_ID_VALUES_EMITTED=false",
            "CONTROL_BODY_VALUES_EMITTED=false",
            "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
            "ENDPOINT_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE RTPC CONTROL RESPONSE CONTRACT PCAP FORENSIC ===",
        ]
    )
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
        result = analyze(collect_extended_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("CONTROL_BODY_VALUES_EMITTED=false")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
