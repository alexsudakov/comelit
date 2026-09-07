#!/usr/bin/env python3
"""P68: test typed OPEN/RESPONSE pairing, not P67's rejected echo model.

Offline only. P67's frozen-capture run rejected zero-filled OPEN fields and
byte-for-byte reflection of the nearest device response. The existing v1_5_7
channel builders define ABCD OPEN as opcode=1, data length=7, a four-byte name,
a two-byte target and a zero trailer. Its response parser and OPEN callers
check opcode=2, data length=4, a two-byte target and a zero status word.

Check those schemas against the capture. Bind each response to a unique earlier
OPEN from the opposite sender, including the device OPEN before packet 208.
Never infer causality from adjacency alone or weaken the old P67 gate. Packet
positions and semantic classifications are emitted; identifiers, body values,
addresses and media are not. No live code is generated or executed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    EXPECTED_PCAP_SHA256, VipFrame, load_capture, select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames

KNOWN_CHANNELS = (b"RTPC", b"ECHO", b"CTPP", b"CSPB", b"UAUT", b"UCFG")
WINDOW_START = 205
WINDOW_END = 209


def _word(body: bytes, start: int, size: int) -> int:
    return int.from_bytes(body[start:start + size], "little")


def _channel(body: bytes) -> str:
    name = body[8:12]
    return name.decode("ascii") if name in KNOWN_CHANNELS else "UNKNOWN"


def _open_shape(body: bytes) -> bool:
    return bool(
        len(body) == 15 and _word(body, 0, 2) == 0xABCD
        and _word(body, 2, 2) == 1 and _word(body, 4, 4) == 7
        and _channel(body) != "UNKNOWN" and body[14] == 0
        and _word(body, 12, 2) != 0
    )


def _response_shape(body: bytes) -> bool:
    return bool(
        len(body) == 12 and _word(body, 0, 2) == 0xABCD
        and _word(body, 2, 2) == 2 and _word(body, 4, 4) == 4
        and _word(body, 8, 2) != 0 and body[10:12] == b"\0\0"
    )


def _before(left: VipFrame, right: VipFrame) -> bool:
    # Timestamp/packet cannot order coalesced frames reliably. Fail closed if
    # the OPEN does not complete in a strictly earlier capture packet.
    return left.last_packet < right.first_packet and left.timestamp <= right.timestamp


def _positions(left: bytes, right: bytes, ignore: tuple[int, ...] = ()) -> tuple[int, ...]:
    return tuple(i for i in range(max(len(left), len(right)))
                 if i not in ignore and
                 (i >= len(left) or i >= len(right) or left[i] != right[i]))


@dataclass(frozen=True)
class ControlMeta:
    packet: int
    direction: str
    body_length: int
    kind: str
    channel: str
    declared_length_matches: bool
    schema_ok: bool


@dataclass(frozen=True)
class Pair:
    response_packet: int
    response_direction: str
    response_schema_ok: bool
    matching_open_count: int
    open_packet: int | None
    open_channel: str


@dataclass(frozen=True)
class Result:
    controls: tuple[ControlMeta, ...]
    client_open_count: int
    open_schema_ok: bool
    legacy_open_mismatches: tuple[tuple[int, ...], ...]
    typed_open_mismatches: tuple[tuple[int, ...], ...]
    ids_distinct_nonzero_sequential: bool
    device_pairs: tuple[Pair, ...]
    client_pairs: tuple[Pair, ...]
    client_response_diff_positions: tuple[int, ...]
    client_response_diff_only_target: bool
    pairing_ok: bool


def analyze(frames: Iterable[VipFrame]) -> Result:
    ordered = tuple(sorted(frames, key=lambda f: (f.timestamp, f.first_packet)))
    if any(f.direction not in ("CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT") for f in ordered):
        raise ValueError("invalid direction")
    controls = tuple(f for f in ordered if f.request_id == 0
                     and WINDOW_START <= f.first_packet <= WINDOW_END)
    # Keep shape failures visible instead of filtering invalid candidates out.
    client_opens = tuple(f for f in controls if f.direction == "CLIENT_TO_DEVICE"
                         and f.first_packet == 206 and f.body_length == 15
                         and f.body[8:12] == b"RTPC")
    all_opens = tuple(f for f in ordered if f.request_id == 0 and _open_shape(f.body))
    device_responses = tuple(f for f in controls if f.direction == "DEVICE_TO_CLIENT"
                             and f.first_packet > 206 and f.body_length == 12)
    client_responses = tuple(f for f in controls if f.direction == "CLIENT_TO_DEVICE"
                             and f.first_packet == 208 and f.body_length == 12)

    def pair(response: VipFrame) -> Pair:
        matches = tuple(f for f in all_opens if f.direction != response.direction
                        and _before(f, response)
                        and f.body[12:14] == response.body[8:10])
        match = matches[0] if len(matches) == 1 else None
        return Pair(response.first_packet, response.direction,
                    _response_shape(response.body), len(matches),
                    match.first_packet if match else None,
                    _channel(match.body) if match else "UNRESOLVED")

    device_pairs = tuple(pair(f) for f in device_responses)
    client_pairs = tuple(pair(f) for f in client_responses)
    ids = tuple(_word(f.body, 12, 2) for f in client_opens)
    ids_ok = (len(ids) == 2 and all(ids) and ids[0] != ids[1]
              and ((ids[1] - ids[0]) & 0xFFFF) == 1)
    legacy = bytearray(15)
    legacy[0:2] = (0xABCD).to_bytes(2, "little")
    legacy[8:12] = b"RTPC"
    typed = bytearray(legacy)
    typed[2:4] = (1).to_bytes(2, "little")
    typed[4:8] = (7).to_bytes(4, "little")
    legacy_diffs = tuple(_positions(f.body, legacy, (12, 13)) for f in client_opens)
    typed_diffs = tuple(_positions(f.body, typed, (12, 13)) for f in client_opens)

    diffs: tuple[int, ...] = ()
    comparable = False
    if len(client_responses) == 1:
        prior = tuple(f for f in device_responses if _before(f, client_responses[0]))
        if prior:
            comparable = True
            nearest = max(prior, key=lambda f: (f.timestamp, f.first_packet))
            diffs = _positions(client_responses[0].body, nearest.body)
    diff_only_target = comparable and bool(diffs) and set(diffs) <= {8, 9}

    metadata = []
    for f in controls:
        body = f.body
        family_ok = len(body) >= 8 and _word(body, 0, 2) == 0xABCD
        opcode = _word(body, 2, 2) if family_ok else None
        kind = {1: "OPEN", 2: "OPEN_RESPONSE", 3: "CLOSE", 4: "CLOSE_RESPONSE"}.get(opcode, "UNKNOWN")
        metadata.append(ControlMeta(
            f.first_packet, f.direction, f.body_length, kind,
            _channel(body) if kind == "OPEN" else "NOT_APPLICABLE",
            len(body) >= 8 and _word(body, 4, 4) == len(body) - 8,
            _open_shape(body) if kind == "OPEN" else _response_shape(body)
            if kind == "OPEN_RESPONSE" else False,
        ))

    open_schema_ok = len(client_opens) == 2 and all(_open_shape(f.body) for f in client_opens)
    # Strict, capture-specific bijection: each client OPEN receives exactly one
    # device response; the client response answers a separate earlier device
    # OPEN in this exchange. Unknown/extra CONTROL traffic remains a blocker.
    device_pairing_ok = (
        len(device_pairs) == 2
        and all(p.response_schema_ok and p.matching_open_count == 1
                and p.open_packet == 206 and p.open_channel == "RTPC" for p in device_pairs)
        and len({f.body[8:10] for f in device_responses}) == 2
    )
    client_pairing_ok = (
        len(client_pairs) == 1 and client_pairs[0].response_schema_ok
        and client_pairs[0].matching_open_count == 1 and client_pairs[0].open_packet == 205
        and client_pairs[0].open_channel == "RTPC"
    )
    pairing_ok = bool(
        open_schema_ok and ids_ok and device_pairing_ok and client_pairing_ok
        and len(controls) == 6 and all(m.schema_ok for m in metadata)
    )
    return Result(tuple(metadata), len(client_opens), open_schema_ok, legacy_diffs,
                  typed_diffs, ids_ok, device_pairs, client_pairs, diffs,
                  diff_only_target, pairing_ok)


def _pos(values: tuple[int, ...]) -> str:
    return ",".join(map(str, values)) if values else "NONE"


def report(result: Result) -> str:
    lines = ["=== COMELIT P68 RTPC CONTROL PAIRING ===",
             f"CLIENT_RTPC_OPEN_COUNT={result.client_open_count}",
             f"CLIENT_RTPC_TYPED_OPEN_SCHEMA={'PASS' if result.open_schema_ok else 'FAIL'}",
             f"CLIENT_RTPC_IDS_DISTINCT_NONZERO_SEQUENTIAL={str(result.ids_distinct_nonzero_sequential).lower()}"]
    for i, (legacy, typed) in enumerate(zip(result.legacy_open_mismatches, result.typed_open_mismatches), 1):
        lines.append(f"OPEN_TEMPLATE ordinal={i} legacy_mismatch_positions={_pos(legacy)} typed_mismatch_positions={_pos(typed)}")
    for m in result.controls:
        lines.append(f"CONTROL packet={m.packet} direction={m.direction} body_len={m.body_length} kind={m.kind} channel={m.channel} declared_length_matches={str(m.declared_length_matches).lower()} schema={'PASS' if m.schema_ok else 'FAIL'}")
    for p in result.device_pairs + result.client_pairs:
        packet = p.open_packet if p.open_packet is not None else "NONE"
        lines.append(f"PAIR response_packet={p.response_packet} direction={p.response_direction} response_schema={'PASS' if p.response_schema_ok else 'FAIL'} matching_open_count={p.matching_open_count} open_packet={packet} open_channel={p.open_channel}")
    lines.extend([
        f"CLIENT_RESPONSE_NEAREST_DEVICE_RESPONSE_DIFF_POSITIONS={_pos(result.client_response_diff_positions)}",
        f"CLIENT_RESPONSE_DIFF_ONLY_TARGET_FIELD={str(result.client_response_diff_only_target).lower()}",
        f"RTPC_CONTROL_PAIRING_CONTRACT={'PASS' if result.pairing_ok else 'NOT_PROVEN'}",
        "LIVE_RUN_AUTHORIZED_BY_ANALYZER=false",
        "REQUEST_ID_VALUES_EMITTED=false", "CONTROL_BODY_VALUES_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false", "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false", "DOOR_ACTION_SENT=false",
        "MEDIA_SIGNALING_SENT=false", "=== END COMELIT P68 RTPC CONTROL PAIRING ===",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != EXPECTED_PCAP_SHA256:
            print("PCAP_SHA256_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
            return 2
        print("PCAP_SHA256_GATE=PASS")
        frames = collect_extended_vip_frames(select_vip_flow(load_capture(args.pcap)))
        result = analyze(frames)
    except (OSError, ValueError):
        print("FORENSIC_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
        return 3
    print(report(result))
    return 0 if result.pairing_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
