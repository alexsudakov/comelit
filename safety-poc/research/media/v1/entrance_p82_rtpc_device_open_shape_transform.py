#!/usr/bin/env python3
"""P82: add safe structural diagnostics for a rejected live RTPC device OPEN.

This is a diagnostic overlay on the reviewed P80 HA media runtime. It does not
change OPEN validation, RTPC signaling, session lifecycle, Door reachability or
media forwarding. On the existing P78 device-OPEN validation failure path it
emits only structural scalars/booleans needed to distinguish an envelope-shape
mismatch. Target/channel IDs and raw payload bytes are never emitted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p80_ha_media_runtime_transform import (
    DEFAULT_SOURCE,
    transform as add_p80_runtime,
)


DEVICE_OPEN_FAILURE_ANCHOR = r'''        status = p76_observe_device_open(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL");
            return TRUE;
        }
'''

DEVICE_OPEN_FAILURE_REPLACEMENT = r'''        status = p76_observe_device_open(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            gboolean p82_magic_match = FALSE;
            gboolean p82_tag_match = FALSE;

            if (body && body_len >= 2u)
                p82_magic_match = body[0] == 0xcdu && body[1] == 0xabu;
            if (body && body_len >= 12u)
                p82_tag_match = body[8] == 'R' && body[9] == 'T' &&
                    body[10] == 'P' && body[11] == 'C';

            printf("P80_RTPC_DEVICE_OPEN_BODY_LEN=%u\n", (unsigned)body_len);
            printf("P80_RTPC_DEVICE_OPEN_MAGIC_MATCH=%s\n",
                p82_magic_match ? "true" : "false");
            if (body && body_len >= 4u)
                printf("P80_RTPC_DEVICE_OPEN_OPCODE=%u\n",
                    (unsigned)p76_read_le16(body + 2u));
            if (body && body_len >= 6u)
                printf("P80_RTPC_DEVICE_OPEN_DECLARED_LEN=%u\n",
                    (unsigned)p76_read_le16(body + 4u));
            printf("P80_RTPC_DEVICE_OPEN_TAG_MATCH=%s\n",
                p82_tag_match ? "true" : "false");
            printf("P80_RTPC_DEVICE_OPEN_TRAILER_PRESENT=%s\n",
                body && body_len >= 15u ? "true" : "false");
            if (body && body_len >= 15u)
                printf("P80_RTPC_DEVICE_OPEN_TRAILER=%u\n",
                    (unsigned)body[14]);
            printf("P80_RTPC_DEVICE_OPEN_VALIDATION_STATUS=%u\n",
                (unsigned)status);
            fflush(stdout);

            p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL");
            return TRUE;
        }
'''


def transform(source: str) -> str:
    out = add_p80_runtime(source)
    count = out.count(DEVICE_OPEN_FAILURE_ANCHOR)
    if count != 1:
        raise RuntimeError(
            f"device OPEN failure anchor: expected one anchor, found {count}"
        )
    return out.replace(
        DEVICE_OPEN_FAILURE_ANCHOR,
        DEVICE_OPEN_FAILURE_REPLACEMENT,
        1,
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P82 RTPC DEVICE OPEN SHAPE DIAGNOSTICS ===",
            "P82_BASE=P80_HA_MEDIA_RUNTIME",
            "P82_VALIDATION_CHANGED=false",
            "P82_SIGNALING_CHANGED=false",
            "P82_TARGET_ID_EMITTED=false",
            "P82_RAW_PAYLOAD_EMITTED=false",
            "P82_NETWORK_IO_PERFORMED=false",
            "P82_CANDIDATE_EXECUTED=false",
            "DOOR_ACTION_SENT=false",
            "=== END COMELIT P82 RTPC DEVICE OPEN SHAPE DIAGNOSTICS ===",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
