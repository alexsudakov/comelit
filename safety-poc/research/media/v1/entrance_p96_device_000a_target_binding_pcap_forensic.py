#!/usr/bin/env python3
"""P96 offline forensic: bind device 0x000A target to the peer RTPC OPEN.

The P95 live run proved that device 0x000A frames reach the existing P92 gate
with the expected 44-byte shape, 0x1840 prefix, 0x000A action, and six-byte
RTPC link tag, but none echoes the client 0x000A target at bytes 16:18.

This analyzer uses only the frozen self_activation capture and reports boolean
relationships between dynamic target fields.  It never emits target values,
raw payload, addresses, endpoints, credentials, or media.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames


@dataclass(frozen=True)
class Result:
    client_open_count: int
    device_open_count: int
    client_000a_count: int
    device_000a_count: int
    client_000a_target_equals_client_open_1: bool
    device_000a_target_equals_device_open_same_order: bool
    device_000a_target_equals_device_open_reverse_order: bool
    device_000a_target_equals_client_open_1: bool
    device_000a_target_equals_client_open_2: bool
    device_000a_tag_equals_client_000a_tag: bool

    @property
    def peer_target_binding_proven(self) -> bool:
        return bool(
            self.client_open_count == 2
            and self.device_open_count == 1
            and self.client_000a_count == 1
            and self.device_000a_count == 1
            and self.client_000a_target_equals_client_open_1
            and self.device_000a_target_equals_device_open_same_order
            and not self.device_000a_target_equals_client_open_1
            and not self.device_000a_target_equals_client_open_2
            and self.device_000a_tag_equals_client_000a_tag
        )


def _is_rtpc_open(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.request_id == 0
        and frame.body_length == 15
        and len(body) == 15
        and int.from_bytes(body[0:2], "little") == 0xABCD
        and body[8:12] == b"RTPC"
        and body[12:14] != b"\x00\x00"
    )


def _is_000a(frame: VipFrame) -> bool:
    body = frame.body
    return bool(
        frame.request_id != 0
        and frame.body_length == 44
        and len(body) == 44
        and int.from_bytes(body[0:2], "little") == 0x1840
        and body[6:8] == b"\x00\x0a"
    )


def analyze(frames: Iterable[VipFrame]) -> Result:
    ordered = tuple(sorted(frames, key=lambda f: (f.timestamp, f.first_packet)))
    client_opens = tuple(
        f for f in ordered if f.direction == "CLIENT_TO_DEVICE" and _is_rtpc_open(f)
    )
    device_opens = tuple(
        f for f in ordered if f.direction == "DEVICE_TO_CLIENT" and _is_rtpc_open(f)
    )
    client_000a = tuple(
        f for f in ordered if f.direction == "CLIENT_TO_DEVICE" and _is_000a(f)
    )
    device_000a = tuple(
        f for f in ordered if f.direction == "DEVICE_TO_CLIENT" and _is_000a(f)
    )

    if len(client_opens) != 2:
        raise ValueError(f"expected two client RTPC opens, found {len(client_opens)}")
    if len(device_opens) != 1:
        raise ValueError(f"expected one device RTPC open, found {len(device_opens)}")
    if len(client_000a) != 1:
        raise ValueError(f"expected one client 000A, found {len(client_000a)}")
    if len(device_000a) != 1:
        raise ValueError(f"expected one device 000A, found {len(device_000a)}")

    c1, c2 = client_opens
    dopen = device_opens[0]
    c000a = client_000a[0]
    d000a = device_000a[0]

    if c000a.request_id != d000a.request_id:
        raise ValueError("client/device 000A do not share the CTPP request id")

    client_open_1_target = c1.body[12:14]
    client_open_2_target = c2.body[12:14]
    device_open_target = dopen.body[12:14]
    client_000a_target = c000a.body[16:18]
    device_000a_target = d000a.body[16:18]

    return Result(
        client_open_count=len(client_opens),
        device_open_count=len(device_opens),
        client_000a_count=len(client_000a),
        device_000a_count=len(device_000a),
        client_000a_target_equals_client_open_1=(
            client_000a_target == client_open_1_target
        ),
        device_000a_target_equals_device_open_same_order=(
            device_000a_target == device_open_target
        ),
        device_000a_target_equals_device_open_reverse_order=(
            device_000a_target == device_open_target[::-1]
        ),
        device_000a_target_equals_client_open_1=(
            device_000a_target == client_open_1_target
        ),
        device_000a_target_equals_client_open_2=(
            device_000a_target == client_open_2_target
        ),
        device_000a_tag_equals_client_000a_tag=(
            d000a.body[10:16] == c000a.body[10:16]
        ),
    )


def _b(value: bool) -> str:
    return "true" if value else "false"


def report(result: Result) -> str:
    return "\n".join(
        (
            "=== COMELIT P96 DEVICE 000A TARGET BINDING FORENSIC ===",
            "PCAP_SHA256_GATE=PASS",
            f"CLIENT_RTPC_OPEN_COUNT={result.client_open_count}",
            f"DEVICE_RTPC_OPEN_COUNT={result.device_open_count}",
            f"CLIENT_000A_COUNT={result.client_000a_count}",
            f"DEVICE_000A_COUNT={result.device_000a_count}",
            "CLIENT_000A_TARGET_EQUALS_CLIENT_OPEN_1="
            + _b(result.client_000a_target_equals_client_open_1),
            "DEVICE_000A_TARGET_EQUALS_DEVICE_OPEN_SAME_ORDER="
            + _b(result.device_000a_target_equals_device_open_same_order),
            "DEVICE_000A_TARGET_EQUALS_DEVICE_OPEN_REVERSE_ORDER="
            + _b(result.device_000a_target_equals_device_open_reverse_order),
            "DEVICE_000A_TARGET_EQUALS_CLIENT_OPEN_1="
            + _b(result.device_000a_target_equals_client_open_1),
            "DEVICE_000A_TARGET_EQUALS_CLIENT_OPEN_2="
            + _b(result.device_000a_target_equals_client_open_2),
            "DEVICE_000A_TAG_EQUALS_CLIENT_000A_TAG="
            + _b(result.device_000a_tag_equals_client_000a_tag),
            "P96_DEVICE_000A_PEER_TARGET_BINDING="
            + ("PASS" if result.peer_target_binding_proven else "NOT_PROVEN"),
            "TARGET_ID_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "=== END COMELIT P96 DEVICE 000A TARGET BINDING FORENSIC ===",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    actual = hashlib.sha256(args.pcap.read_bytes()).hexdigest()
    if actual != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("TARGET_ID_VALUES_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    flow = select_vip_flow(capture)
    try:
        result = analyze(collect_extended_vip_frames(flow))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("TARGET_ID_VALUES_EMITTED=false")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0 if result.peer_target_binding_proven else 4


if __name__ == "__main__":
    raise SystemExit(main())
