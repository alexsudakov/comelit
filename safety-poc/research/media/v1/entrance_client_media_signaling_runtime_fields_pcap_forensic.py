#!/usr/bin/env python3
"""Offline targeted forensic for the last unresolved client media-signaling fields.

P61 reduced the unknown body positions to:

* CLIENT_000A[10:12]
* CLIENT_001A[10:12]
* CLIENT_001A[24:33]

This analyzer tests only runtime-derivable hypotheses for those fields.  It
compares the two-byte fields with already-established ViP request/channel ids
(CTPP and any earlier named CSPB channel) in both byte orders, and compares the
nine-byte field with identities derivable from the packet-200 address roles.
No request-id values, body values, protocol addresses, endpoint values, raw
payload, hex/base64 payload, or media bytes are emitted.

The analyzer is capture-only and performs no network I/O or signaling.
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
from entrance_client_media_signaling_body_contract_pcap_forensic import (
    _find_anchor,
    _find_exact,
    CLIENT_000A_PACKET,
    DEVICE_000A_PACKET,
    CLIENT_001A_PACKET,
)


@dataclass(frozen=True)
class FieldRelation:
    label: str
    relation: str


@dataclass(frozen=True)
class Result:
    relations: tuple[FieldRelation, ...]
    c000a_mirrors_device_000a: bool
    c000a_equals_c001a: bool
    cspb_request_id_count: int
    unresolved_labels: tuple[str, ...]


def _low16_patterns(value: int) -> tuple[tuple[str, bytes], ...]:
    low = value & 0xFFFF
    return (
        ("LE", low.to_bytes(2, "little")),
        ("BE", low.to_bytes(2, "big")),
    )


def _named_request_ids(frames: Iterable[VipFrame], name: bytes) -> tuple[int, ...]:
    values = {
        frame.request_id
        for frame in frames
        if name in frame.body
    }
    return tuple(sorted(values))


def _match_two_byte_runtime_field(
    value: bytes,
    *,
    ctpp_request_id: int,
    cspb_request_ids: tuple[int, ...],
) -> str:
    for endian, pattern in _low16_patterns(ctpp_request_id):
        if value == pattern:
            return f"CTPP_REQUEST_ID_LOW16_{endian}"

    for request_id in cspb_request_ids:
        for endian, pattern in _low16_patterns(request_id):
            if value == pattern:
                return f"CSPB_REQUEST_ID_LOW16_{endian}"

    return "NONE"


def analyze(frames: Iterable[VipFrame]) -> Result:
    ordered = tuple(sorted(frames, key=lambda frame: (frame.timestamp, frame.first_packet)))
    anchor = _find_anchor(ordered)
    c000a = _find_exact(
        ordered,
        direction="CLIENT_TO_DEVICE",
        packet=CLIENT_000A_PACKET,
        action=0x000A,
        body_len=44,
    )
    d000a = _find_exact(
        ordered,
        direction="DEVICE_TO_CLIENT",
        packet=DEVICE_000A_PACKET,
        action=0x000A,
        body_len=44,
    )
    c001a = _find_exact(
        ordered,
        direction="CLIENT_TO_DEVICE",
        packet=CLIENT_001A_PACKET,
        action=0x001A,
        body_len=60,
    )

    if not (
        anchor.request_id == c000a.request_id == d000a.request_id == c001a.request_id
    ):
        raise ValueError("target signaling frames do not share CTPP request id")
    if anchor.body_length != 40:
        raise ValueError("unexpected anchor body length")

    cspb_request_ids = _named_request_ids(ordered, b"CSPB")

    c000a_10 = c000a.body[10:12]
    c001a_10 = c001a.body[10:12]
    c001a_identity = c001a.body[24:33]

    relation_c000a_10 = _match_two_byte_runtime_field(
        c000a_10,
        ctpp_request_id=anchor.request_id,
        cspb_request_ids=cspb_request_ids,
    )
    relation_c001a_10 = _match_two_byte_runtime_field(
        c001a_10,
        ctpp_request_id=anchor.request_id,
        cspb_request_ids=cspb_request_ids,
    )

    address_role_a = anchor.body[20:29]
    address_role_b = anchor.body[30:39]
    if len(address_role_a) != 9 or len(address_role_b) != 9:
        raise ValueError("anchor address-role extraction failed")

    apartment_from_full = address_role_b[:8] + b"\x00"
    if c001a_identity == apartment_from_full:
        identity_relation = "APARTMENT_ADDRESS_FROM_FULL_ROLE_B"
    elif c001a_identity == address_role_a:
        identity_relation = "ANCHOR_ADDRESS_ROLE_A"
    elif c001a_identity == address_role_b:
        identity_relation = "ANCHOR_ADDRESS_ROLE_B"
    else:
        identity_relation = "NONE"

    relations = (
        FieldRelation("CLIENT_000A_10_11", relation_c000a_10),
        FieldRelation("CLIENT_001A_10_11", relation_c001a_10),
        FieldRelation("CLIENT_001A_24_32", identity_relation),
    )
    unresolved = tuple(item.label for item in relations if item.relation == "NONE")

    return Result(
        relations=relations,
        c000a_mirrors_device_000a=c000a_10 == d000a.body[10:12],
        c000a_equals_c001a=c000a_10 == c001a_10,
        cspb_request_id_count=len(cspb_request_ids),
        unresolved_labels=unresolved,
    )


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE CLIENT MEDIA SIGNALING RUNTIME FIELDS PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"CSPB_REQUEST_ID_DISCOVERY_COUNT={result.cspb_request_id_count}",
        f"CLIENT_000A_10_11_MIRRORS_DEVICE_000A={'true' if result.c000a_mirrors_device_000a else 'false'}",
        f"CLIENT_000A_10_11_EQUALS_CLIENT_001A_10_11={'true' if result.c000a_equals_c001a else 'false'}",
    ]
    for item in result.relations:
        lines.append(f"TARGET_FIELD_RELATION label={item.label} relation={item.relation}")

    lines.extend(
        [
            f"TARGETED_UNRESOLVED_FIELD_COUNT={len(result.unresolved_labels)}",
            "TARGETED_UNRESOLVED_FIELDS="
            + ("NONE" if not result.unresolved_labels else ",".join(result.unresolved_labels)),
            f"LIVE_BODY_GENERATION_CONTRACT={'PASS' if not result.unresolved_labels else 'NOT_PROVEN'}",
            "BODY_VALUES_EMITTED=false",
            "REQUEST_ID_VALUES_EMITTED=false",
            "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
            "ENDPOINT_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "=== END COMELIT ENTRANCE CLIENT MEDIA SIGNALING RUNTIME FIELDS PCAP FORENSIC ===",
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
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
