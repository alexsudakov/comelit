#!/usr/bin/env python3
"""P95 compile corrective: declare new helpers before their first generated use.

The P95 protocol transform is intentionally unchanged.  The first CT120 HAOS
compile exposed a C declaration-order defect: p12_tx_completed() references the
P95 timeout callback before its later definition, and p12_process_post_uaut()
references the P95 device-0002 handler before its later definition.

This overlay composes P95 and adds only forward declarations near the P95 state.
It changes no packet shape, state transition, timeout, retry, Door behavior, or
network behavior.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p95_wait_device_0002_before_rtpc_transform import (
    DEFAULT_SOURCE,
    transform as add_p95_runtime,
)


_STATE_ANCHOR = """static gboolean p95_rtpc_started = FALSE;
static guint p95_device_0002_rx_count = 0;
"""

_STATE_REPLACEMENT = """static gboolean p95_rtpc_started = FALSE;
static guint p95_device_0002_rx_count = 0;

/* P95 forward declarations required by earlier generated call sites. */
static gboolean p95_device_0002_timeout_cb(gpointer data);
static gboolean p95_handle_device_0002(
    guint16 request_id,
    const guint8 *body,
    guint body_len
);
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p95_runtime(source)
    return _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE_REPLACEMENT,
        "P95 compile forward declarations",
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P95 COMPILE DECLARATIONS CORRECTIVE ===",
            "P95_COMPOSES=WAIT_DEVICE_0002_BEFORE_RTPC",
            "P95_PROTOCOL_BEHAVIOR_CHANGED=false",
            "P95_FORWARD_DECLARATIONS_ADDED=true",
            "P95_AUTOMATIC_RETRY=false",
            "P95_SECOND_CTPP_OPEN=false",
            "P95_DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P95 COMPILE DECLARATIONS CORRECTIVE ===",
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
        transform(source_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    print("P95_COMPILE_DECLARATIONS_TRANSFORM=PASS")
    print("P95_PROTOCOL_BEHAVIOR_CHANGED=false")
    print("P95_FORWARD_DECLARATIONS_ADDED=true")
    print("P95_AUTOMATIC_RETRY=false")
    print("P95_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
