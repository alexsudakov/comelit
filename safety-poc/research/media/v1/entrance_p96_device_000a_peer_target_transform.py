#!/usr/bin/env python3
"""P96: bind device 0x000A to the dynamic peer/device RTPC OPEN target.

P95 live evidence proved that the real device 0x000A reaches the P92 gate and
matches body length, prefix, action, and the six-byte RTPC-link tag, while the
old assumption that its target bytes echo the client 0x000A allocation target
is false.  The P75/P76 runtime already records the dynamic target from the
peer/device RTPC OPEN.

This overlay changes only the last two-byte target predicate of the device
0x000A gate. Client 0x000A and 0x001A generation remains allocator #1/#2 exactly
as before. No captured target value, second CTPP OPEN, retry, Door path, or raw
payload is introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p95_compile_declarations_transform import (
    DEFAULT_SOURCE,
    transform as add_p95_runtime,
)


_TARGET_PREDICATE_OLD = r'''    if (memcmp(body + 16u, p78_rtpc_client_000a + 16u, 2u) != 0)
        return FALSE;
    p93_device_000a_target_match++;
'''

_TARGET_PREDICATE_NEW = r'''    /* P96: the device-originated 0x000A belongs to the peer/device RTPC
     * channel, so bind it to the dynamic target recorded from the device OPEN.
     * Client 0x000A still binds independently to client allocation/open #1. */
    if (p78_rtpc_runtime.device_open_target == 0u ||
        read_le16(body + 16u) != p78_rtpc_runtime.device_open_target)
        return FALSE;
    p93_device_000a_target_match++;
    printf("P80_DEVICE_000A_PEER_TARGET_MATCH=PASS\n");
    fflush(stdout);
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p95_runtime(source)
    return _replace_once(
        candidate,
        _TARGET_PREDICATE_OLD,
        _TARGET_PREDICATE_NEW,
        "P96 device 000A peer target predicate",
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P96 DEVICE 000A PEER TARGET BINDING ===",
            "P96_COMPOSES=P95",
            "P96_DEVICE_000A_TARGET_SOURCE=DEVICE_RTPC_OPEN_RUNTIME_STATE",
            "P96_CLIENT_000A_BINDING_UNCHANGED=ALLOCATION_1",
            "P96_CLIENT_001A_BINDING_UNCHANGED=ALLOCATION_2",
            "P96_CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false",
            "P96_AUTOMATIC_RETRY=false",
            "P96_SECOND_CTPP_OPEN=false",
            "P96_DOOR_ACTION_SENT=false",
            "P96_RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P96 DEVICE 000A PEER TARGET BINDING ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])

    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print("P96_TRANSFORM=PASS")
    print("P96_DEVICE_000A_TARGET_SOURCE=DEVICE_RTPC_OPEN_RUNTIME_STATE")
    print("P96_CLIENT_BINDINGS_UNCHANGED=true")
    print("P96_CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false")
    print("P96_AUTOMATIC_RETRY=false")
    print("P96_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
