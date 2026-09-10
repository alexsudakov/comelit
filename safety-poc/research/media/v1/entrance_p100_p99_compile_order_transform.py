#!/usr/bin/env python3
"""P100 compile-order corrective for the P99 early-media demux state.

P99 intentionally extends p80_try_forward_wrapped_rtp() so it can classify
capture-proven offset-8 RTP before MEDIA_ACTIVE.  The first P99 transform placed
its two file-scope state definitions near the later P97 signaling state, while
the P80 RTP classifier appears much earlier in the generated translation unit.
That is a pure C declaration-order error: the generated source references the
state before its declaration.

This overlay composes P99, moves those two definitions next to the existing P80
media-forwarding state (before p80_try_forward_wrapped_rtp), and removes the
later duplicate definitions.  Runtime/protocol behavior is unchanged.

No network I/O, captured values, identifiers, retry, second CTPP OPEN, raw media,
or Door path are introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p99_state_scoped_ack_and_early_media_demux_transform import (
    DEFAULT_SOURCE,
    transform as add_p99_runtime,
)


_EARLY_ANCHOR = """static gboolean p80_media_forwarding_enabled = FALSE;
static int p80_video_rtp_fd = -1;
"""

_EARLY_REPLACEMENT = """static gboolean p80_media_forwarding_enabled = FALSE;

/* P100: P99 classifier state must be declared before the P80 RTP classifier. */
static gboolean p99_preactive_media_demux_armed = FALSE;
static guint64 p99_preactive_media_packets = 0;

static int p80_video_rtp_fd = -1;
"""

_LATE_ANCHOR = """/* P99 narrow pre-active raw-media demux. */
static gboolean p99_preactive_media_demux_armed = FALSE;
static guint64 p99_preactive_media_packets = 0;

static gboolean p97_store_device_000a_roles"""

_LATE_REPLACEMENT = """/* P100: P99 pre-active demux state is defined with the earlier P80 RTP state. */
static gboolean p97_store_device_000a_roles"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p99_runtime(source)
    candidate = _replace_once(
        candidate,
        _EARLY_ANCHOR,
        _EARLY_REPLACEMENT,
        "P100 early P99 state insertion",
    )
    candidate = _replace_once(
        candidate,
        _LATE_ANCHOR,
        _LATE_REPLACEMENT,
        "P100 remove late P99 state definitions",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P100 P99 COMPILE ORDER CORRECTIVE ===",
            "P100_COMPOSES=P99",
            "P100_P99_STATE_DECLARED_BEFORE_CLASSIFIER=true",
            "P100_PROTOCOL_BEHAVIOR_CHANGED=false",
            "P100_AUTOMATIC_RETRY=false",
            "P100_SECOND_CTPP_OPEN=false",
            "P100_DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P100 P99 COMPILE ORDER CORRECTIVE ===",
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
    print("P100_TRANSFORM=PASS")
    print("P100_P99_STATE_DECLARED_BEFORE_CLASSIFIER=true")
    print("P100_PROTOCOL_BEHAVIOR_CHANGED=false")
    print("P100_AUTOMATIC_RETRY=false")
    print("P100_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
