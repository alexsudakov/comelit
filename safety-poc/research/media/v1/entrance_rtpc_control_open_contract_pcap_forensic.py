#!/usr/bin/env python3
"""Offline forensic for the two client RTPC CONTROL-open requests.

P63 proves that client 0x000a and 0x001a bind to two distinct RTPC request-id
values carried by the packet-206 CONTROL exchange.  Before any live candidate
may generate those signaling bodies, this analyzer checks whether the RTPC
request ids themselves behave as client-originated runtime correlation ids.

The frozen capture is used only to report structural relationships:

* exactly two client packet-206 RTPC open frames;
* whether the two 15-byte open bodies differ only at request-id bytes 12:14;
* whether the request ids are distinct/non-zero and sequential as a relation;
* whether either id occurs in earlier bounded CONTROL traffic;
* whether each id is echoed later by device CONTROL traffic, in either byte
  order;
* whether either id occurs in the fixed 8-byte wrapper of valid post-218 RTP.

Request-id values, CONTROL body bytes, wrapper values, protocol addresses,
endpoints, RTP identifiers, raw/hex/base64 payload, and media are never emitted.
No network I/O or signaling is performed.
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
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    BOUNDARY_PACKET,
    _read_selected_datagrams,
)
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _opaque

OPEN_PACKET = 206
CONTROL_WINDOW_START_PACKET = 200
CONTROL_WINDOW_END_PACKET = 218
RTP_OFFSET = 8
REQUEST_START = 12
REQUEST_END = 14


@dataclass(frozen=True)
class IdRelation:
    ordinal: int
    prior_control_match_count: int
    device_same_order_match_count: int
    device_reverse_order_match_count: int
    device_same_order_positions: tuple[int, ...]
    device_reverse_order_positions: tuple[int, ...]
    wrapper_same_order_match_count: int
    wrapper_reverse_order_match_count: int
    wrapper_same_order_positions: tuple[int, ...]
    wrapper_reverse_order_positions: tuple[int, ...]

    @property
    def device_echo_supported(self) -> bool:
        return bool(
            self.device_same_order_match_count
            or self.device_reverse_order_match_count
        )


@dataclass(frozen=True)
class Result:
    open_count: int
    fixed_field_contract: bool
    open_body_diff_positions: tuple[int, ...]
    template_static_except_request_id: bool
    request_ids_distinct: bool
    request_ids_nonzero: bool
    request_ids_sequential: bool
    relations: tuple[IdRelation, ...]

    @property
    def runtime_generation_contract_ok(self) -> bool:
        return bool(
            self.open_count == 2
            and self.fixed_field_contract
            and self.template_static_except_request_id
            and self.request_ids_distinct
            and self.request_ids_nonzero
            and len(self.relations) == 2
            and all(item.prior_control_match_count == 0 for item in self.relations)
            and all(item.device_echo_supported for item in self.relations)
        )


def _find_all(blob: bytes, needle: bytes) -> tuple[int, ...]:
    if not needle:
        return ()
    result: list[int] = []
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            return tuple(result)
        result.append(pos)
        start = pos + 1


def _client_rtpc_opens(frames: Iterable[VipFrame]) -> tuple[VipFrame, ...]:
    result = []
    for frame in frames:
        body = frame.body
        if (
            frame.direction == "CLIENT_TO_DEVICE"
            and frame.first_packet == OPEN_PACKET
            and frame.request_id == 0
            and frame.body_length == 15
            and len(body) == 15
            and int.from_bytes(body[0:2], "little") == 0xABCD
            and body[8:12] == b"RTPC"
        ):
            result.append(frame)
    return tuple(sorted(result, key=lambda item: (item.timestamp, item.first_packet)))


def _control_frames(frames: Iterable[VipFrame]) -> tuple[VipFrame, ...]:
    return tuple(
        frame
        for frame in frames
        if CONTROL_WINDOW_START_PACKET <= frame.first_packet <= CONTROL_WINDOW_END_PACKET
        and frame.request_id == 0
        and frame.body_length in (12, 15)
    )


def _rtp_wrappers(datagrams) -> tuple[bytes, ...]:
    wrappers: list[bytes] = []
    for item in _opaque(datagrams, BOUNDARY_PACKET):
        if len(item.payload) <= RTP_OFFSET:
            continue
        if _parse_rtp_v2_shape(item.payload[RTP_OFFSET:]) is None:
            continue
        wrappers.append(item.payload[:RTP_OFFSET])
    return tuple(wrappers)


def _positions_across(blobs: Iterable[bytes], needle: bytes) -> tuple[int, tuple[int, ...]]:
    count = 0
    positions: set[int] = set()
    for blob in blobs:
        matches = _find_all(blob, needle)
        count += len(matches)
        positions.update(matches)
    return count, tuple(sorted(positions))


def analyze(frames: Iterable[VipFrame], wrappers: Iterable[bytes]) -> Result:
    ordered = tuple(sorted(frames, key=lambda item: (item.timestamp, item.first_packet)))
    opens = _client_rtpc_opens(ordered)
    if len(opens) != 2:
        raise ValueError(f"expected exactly two client RTPC opens, found {len(opens)}")

    if any(len(frame.body) != 15 for frame in opens):
        raise ValueError("RTPC open body length changed")

    fixed_field_contract = all(
        int.from_bytes(frame.body[0:2], "little") == 0xABCD
        and frame.body[8:12] == b"RTPC"
        for frame in opens
    )

    diff_positions = tuple(
        index
        for index, (left, right) in enumerate(zip(opens[0].body, opens[1].body))
        if left != right
    )
    template_static_except_request_id = all(
        REQUEST_START <= index < REQUEST_END for index in diff_positions
    )

    request_ids = tuple(frame.body[REQUEST_START:REQUEST_END] for frame in opens)
    request_ids_distinct = request_ids[0] != request_ids[1]
    request_ids_nonzero = all(value != b"\x00\x00" for value in request_ids)
    first_id = int.from_bytes(request_ids[0], "little")
    second_id = int.from_bytes(request_ids[1], "little")
    request_ids_sequential = ((second_id - first_id) & 0xFFFF) == 1

    controls = _control_frames(ordered)
    wrappers_tuple = tuple(wrappers)
    relations: list[IdRelation] = []
    for ordinal, (open_frame, request_id) in enumerate(zip(opens, request_ids), start=1):
        reverse_id = request_id[::-1]

        prior_control_blobs = [
            frame.body
            for frame in controls
            if (frame.timestamp, frame.first_packet) < (open_frame.timestamp, open_frame.first_packet)
        ]
        prior_same, _ = _positions_across(prior_control_blobs, request_id)
        prior_reverse = 0
        if reverse_id != request_id:
            prior_reverse, _ = _positions_across(prior_control_blobs, reverse_id)
        prior_count = prior_same + prior_reverse

        later_device_blobs = [
            frame.body
            for frame in controls
            if frame.direction == "DEVICE_TO_CLIENT"
            and (frame.timestamp, frame.first_packet) > (open_frame.timestamp, open_frame.first_packet)
        ]
        dev_same_count, dev_same_positions = _positions_across(later_device_blobs, request_id)
        if reverse_id == request_id:
            dev_reverse_count, dev_reverse_positions = 0, ()
        else:
            dev_reverse_count, dev_reverse_positions = _positions_across(later_device_blobs, reverse_id)

        wrapper_same_count, wrapper_same_positions = _positions_across(wrappers_tuple, request_id)
        if reverse_id == request_id:
            wrapper_reverse_count, wrapper_reverse_positions = 0, ()
        else:
            wrapper_reverse_count, wrapper_reverse_positions = _positions_across(wrappers_tuple, reverse_id)

        relations.append(
            IdRelation(
                ordinal=ordinal,
                prior_control_match_count=prior_count,
                device_same_order_match_count=dev_same_count,
                device_reverse_order_match_count=dev_reverse_count,
                device_same_order_positions=dev_same_positions,
                device_reverse_order_positions=dev_reverse_positions,
                wrapper_same_order_match_count=wrapper_same_count,
                wrapper_reverse_order_match_count=wrapper_reverse_count,
                wrapper_same_order_positions=wrapper_same_positions,
                wrapper_reverse_order_positions=wrapper_reverse_positions,
            )
        )

    return Result(
        open_count=len(opens),
        fixed_field_contract=fixed_field_contract,
        open_body_diff_positions=diff_positions,
        template_static_except_request_id=template_static_except_request_id,
        request_ids_distinct=request_ids_distinct,
        request_ids_nonzero=request_ids_nonzero,
        request_ids_sequential=request_ids_sequential,
        relations=tuple(relations),
    )


def _fmt_positions(values: tuple[int, ...]) -> str:
    return "NONE" if not values else ",".join(str(value) for value in values)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE RTPC CONTROL-OPEN CONTRACT PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"CLIENT_RTPC_OPEN_COUNT={result.open_count}",
        f"CLIENT_RTPC_OPEN_FIXED_FIELD_CONTRACT={'PASS' if result.fixed_field_contract else 'FAIL'}",
        f"CLIENT_RTPC_OPEN_DIFF_POSITION_COUNT={len(result.open_body_diff_positions)}",
        f"CLIENT_RTPC_OPEN_DIFF_POSITIONS={_fmt_positions(result.open_body_diff_positions)}",
        f"CLIENT_RTPC_OPEN_TEMPLATE_STATIC_EXCEPT_REQUEST_ID={'true' if result.template_static_except_request_id else 'false'}",
        f"CLIENT_RTPC_REQUEST_IDS_DISTINCT={'true' if result.request_ids_distinct else 'false'}",
        f"CLIENT_RTPC_REQUEST_IDS_NONZERO={'true' if result.request_ids_nonzero else 'false'}",
        f"CLIENT_RTPC_REQUEST_IDS_SEQUENTIAL={'true' if result.request_ids_sequential else 'false'}",
    ]
    for item in result.relations:
        lines.append(
            "RTPC_ID_RELATION "
            f"ordinal={item.ordinal} "
            f"prior_control_match_count={item.prior_control_match_count} "
            f"device_same_order_match_count={item.device_same_order_match_count} "
            f"device_reverse_order_match_count={item.device_reverse_order_match_count} "
            f"device_same_order_positions={_fmt_positions(item.device_same_order_positions)} "
            f"device_reverse_order_positions={_fmt_positions(item.device_reverse_order_positions)} "
            f"wrapper_same_order_match_count={item.wrapper_same_order_match_count} "
            f"wrapper_reverse_order_match_count={item.wrapper_reverse_order_match_count} "
            f"wrapper_same_order_positions={_fmt_positions(item.wrapper_same_order_positions)} "
            f"wrapper_reverse_order_positions={_fmt_positions(item.wrapper_reverse_order_positions)} "
            f"device_echo_supported={'true' if item.device_echo_supported else 'false'}"
        )
    lines.extend(
        [
            f"RTPC_RUNTIME_ID_GENERATION_CONTRACT={'PASS' if result.runtime_generation_contract_ok else 'NOT_PROVEN'}",
            "REQUEST_ID_VALUES_EMITTED=false",
            "CONTROL_BODY_VALUES_EMITTED=false",
            "WRAPPER_BYTE_VALUES_EMITTED=false",
            "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
            "ENDPOINT_VALUES_EMITTED=false",
            "RTP_IDENTIFIER_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE RTPC CONTROL-OPEN CONTRACT PCAP FORENSIC ===",
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
        frames = collect_extended_vip_frames(analysis)
        datagrams = _read_selected_datagrams(
            args.pcap,
            client=analysis.client,
            device=analysis.device,
        )
        result = analyze(frames, _rtp_wrappers(datagrams))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("REQUEST_ID_VALUES_EMITTED=false")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
