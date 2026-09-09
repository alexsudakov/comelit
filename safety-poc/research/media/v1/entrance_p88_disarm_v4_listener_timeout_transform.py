#!/usr/bin/env python3
"""P88: remove the legacy bounded V4 listener timeout from HA-owned media.

The entrance self-activation research transform intentionally shortens the
persistent listener's 3300-second absolute timeout to 45 seconds.  That was
correct for the old bounded one-shot probe, but P80 later transferred media
lifetime ownership to Home Assistant and removed the 3-second media auto-close.
P85 separately completes the inherited entrance signaling state.

A successful HA media session therefore must not still be terminated by the
old 45-second V4 listener probe timer.  This overlay composes P85, removes only
that generated 45-second absolute-timeout scheduling block, and emits a safe
marker when the already-gated P80 media transition becomes active.

Home Assistant remains the media lifetime owner and enforces the existing
180-second absolute session limit.  Stop-file teardown, protocol signaling,
PseudoTCP maintenance, the listener implementation, and Door behavior are not
changed here.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p85_complete_signaling_on_media_active_transform import (
    DEFAULT_SOURCE,
    transform as add_p85_runtime,
)


_LEGACY_V4_TIMEOUT = """    g_timeout_add_seconds(
        45,
        absolute_timeout_cb,
        NULL
    );
"""

_ACTIVE_MARKER = '    printf("P80_SIGNALING_WATCHDOG_DISARMED=true\\n");\n'
_ACTIVE_MARKER_REPLACEMENT = (
    _ACTIVE_MARKER
    + '    printf("P80_V4_LISTENER_TIMEOUT_DISARMED=true\\n");\n'
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label} anchor count: {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p85_runtime(source)
    candidate = _replace_once(
        candidate,
        _LEGACY_V4_TIMEOUT,
        "",
        "legacy V4 listener timeout",
    )
    candidate = _replace_once(
        candidate,
        _ACTIVE_MARKER,
        _ACTIVE_MARKER_REPLACEMENT,
        "P80 active diagnostic marker",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P88 HA MEDIA LIFETIME CORRECTIVE ===",
            "P88_COMPOSES=P85",
            "P88_LEGACY_V4_LISTENER_TIMEOUT_45S=DISARMED",
            "P88_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P88_MEDIA_HARD_LIMIT_SECONDS=180",
            "P88_SIGNALING_WATCHDOG=P85_DISARMED",
            "P88_AUTOMATIC_RETRY=false",
            "P88_SECOND_CTPP_OPEN=false",
            "P88_DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P88 HA MEDIA LIFETIME CORRECTIVE ===",
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

    args.output.write_text(
        transform(args.source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    print("P88_TRANSFORM=PASS")
    print("P88_LEGACY_V4_LISTENER_TIMEOUT_45S=DISARMED")
    print("P88_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
