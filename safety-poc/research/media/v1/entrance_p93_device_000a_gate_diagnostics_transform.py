#!/usr/bin/env python3
"""P93: add bounded structural diagnostics to the P92 device-000A gate.

P92 restores the capture-observed ordering client 0x000A -> device 0x000A ->
client 0x001A. A live P92 run failed after client 0x000A, before media active.
The HA marker allowlist currently does not include the P92_ prefix, so the
terminal P92 timeout marker is not retained in entity diagnostics.

This overlay does not change P92 protocol behavior. It only counts how far
inbound frames progress through the existing device-000A predicate while the
three-second gate is active, and emits those counts under the already-safe P80_
marker prefix immediately before the existing P92 timeout fails closed.

Counters distinguish:
- no same-CTPP frame at all;
- a 44-byte frame;
- the 0x1840 prefix;
- the 0x000A action;
- the existing six-byte RTPC tag match;
- the existing two-byte dynamic target-id match.

No payload bytes, target IDs, addresses, credentials, or endpoint data are
emitted. No Door path, retry behavior, CTPP lifecycle, media lifetime, or
signaling sequence is changed.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p92_wait_device_000a_before_001a_transform import (
    DEFAULT_SOURCE,
    transform as add_p92_runtime,
)


_STATE_ANCHOR = """static gboolean p92_wait_device_000a = FALSE;
static gboolean p92_device_000a_observed = FALSE;

static void p78_fail_rtpc(const char *marker);"""

_STATE_REPLACEMENT = """static gboolean p92_wait_device_000a = FALSE;
static gboolean p92_device_000a_observed = FALSE;

/* P93 metadata-only diagnostics for the bounded P92 device-000A gate. */
static guint64 p93_device_000a_ctpp_frames = 0;
static guint64 p93_device_000a_len44 = 0;
static guint64 p93_device_000a_prefix_1840 = 0;
static guint64 p93_device_000a_action_000a = 0;
static guint64 p93_device_000a_tag_match = 0;
static guint64 p93_device_000a_target_match = 0;

static void p78_fail_rtpc(const char *marker);"""


_TIMEOUT_OLD = r'''static gboolean
p92_device_000a_timeout_cb(gpointer data)
{
    (void)data;

    if (!p92_wait_device_000a || p92_device_000a_observed)
        return G_SOURCE_REMOVE;

    p92_wait_device_000a = FALSE;
    p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}'''

_TIMEOUT_NEW = r'''static gboolean
p92_device_000a_timeout_cb(gpointer data)
{
    (void)data;

    if (!p92_wait_device_000a || p92_device_000a_observed)
        return G_SOURCE_REMOVE;

    printf(
        "P80_DEVICE_000A_CTPP_FRAME_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_ctpp_frames
    );
    printf(
        "P80_DEVICE_000A_LEN44_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_len44
    );
    printf(
        "P80_DEVICE_000A_PREFIX_1840_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_prefix_1840
    );
    printf(
        "P80_DEVICE_000A_ACTION_000A_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_action_000a
    );
    printf(
        "P80_DEVICE_000A_TAG_MATCH_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_tag_match
    );
    printf(
        "P80_DEVICE_000A_TARGET_MATCH_COUNT=%" G_GUINT64_FORMAT "\n",
        p93_device_000a_target_match
    );
    printf("P80_DEVICE_000A_GATE_TIMEOUT=true\n");
    fflush(stdout);

    p92_wait_device_000a = FALSE;
    p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}'''


_VALIDATOR_OLD = r'''static gboolean
p92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!body || request_id != v4_ctpp_channel_id ||
        body_len != 44u || p78_rtpc_client_000a_len != 44u)
        return FALSE;

    /* prefix 0x1840 little-endian, action 0x000A big-endian */
    if (body[0] != 0x40u || body[1] != 0x18u ||
        body[6] != 0x00u || body[7] != 0x0au)
        return FALSE;

    /* P72/P75: bytes 10:16 are the RTPC-link tag and 16:18 bind to
     * allocator/open #1.  Require the live device frame to echo that dynamic
     * tag+target relation without promoting any captured target id. */
    if (memcmp(body + 10u, p78_rtpc_client_000a + 10u, 8u) != 0)
        return FALSE;

    return TRUE;
}'''

_VALIDATOR_NEW = r'''static gboolean
p92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!body || request_id != v4_ctpp_channel_id)
        return FALSE;

    p93_device_000a_ctpp_frames++;

    if (body_len != 44u || p78_rtpc_client_000a_len != 44u)
        return FALSE;
    p93_device_000a_len44++;

    /* prefix 0x1840 little-endian */
    if (body[0] != 0x40u || body[1] != 0x18u)
        return FALSE;
    p93_device_000a_prefix_1840++;

    /* action 0x000A big-endian */
    if (body[6] != 0x00u || body[7] != 0x0au)
        return FALSE;
    p93_device_000a_action_000a++;

    /* Preserve the exact P92 predicate, but split its eight-byte comparison
     * into metadata-only stages so live failure is diagnosable. */
    if (memcmp(body + 10u, p78_rtpc_client_000a + 10u, 6u) != 0)
        return FALSE;
    p93_device_000a_tag_match++;

    if (memcmp(body + 16u, p78_rtpc_client_000a + 16u, 2u) != 0)
        return FALSE;
    p93_device_000a_target_match++;

    return TRUE;
}'''


_OBSERVED_OLD = r'''    p92_device_000a_observed = TRUE;
    p92_wait_device_000a = FALSE;
    printf("P92_DEVICE_000A_OBSERVED=PASS\n");
    fflush(stdout);'''

_OBSERVED_NEW = r'''    p92_device_000a_observed = TRUE;
    p92_wait_device_000a = FALSE;
    printf("P92_DEVICE_000A_OBSERVED=PASS\n");
    printf("P80_DEVICE_000A_VALIDATION=PASS\n");
    fflush(stdout);'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p92_runtime(source)
    candidate = _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE_REPLACEMENT,
        "P93 diagnostic counters",
    )
    candidate = _replace_once(
        candidate,
        _TIMEOUT_OLD,
        _TIMEOUT_NEW,
        "P93 timeout report",
    )
    candidate = _replace_once(
        candidate,
        _VALIDATOR_OLD,
        _VALIDATOR_NEW,
        "P93 staged validator",
    )
    candidate = _replace_once(
        candidate,
        _OBSERVED_OLD,
        _OBSERVED_NEW,
        "P93 validation pass marker",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P93 DEVICE 000A GATE DIAGNOSTICS ===",
            "P93_COMPOSES=P92",
            "P93_PROTOCOL_BEHAVIOR_CHANGED=false",
            "P93_DIAGNOSTIC_SCOPE=DEVICE_000A_GATE_METADATA_ONLY",
            "P93_RAW_PAYLOAD_EMITTED=false",
            "P93_TARGET_ID_VALUE_EMITTED=false",
            "P93_ADDRESS_VALUE_EMITTED=false",
            "P93_AUTOMATIC_RETRY=false",
            "P93_SECOND_CTPP_OPEN=false",
            "P93_DOOR_ACTION_SENT=false",
            "P93_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P93_MEDIA_HARD_LIMIT_SECONDS=180",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P93 DEVICE 000A GATE DIAGNOSTICS ===",
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
    print("P93_TRANSFORM=PASS")
    print("P93_PROTOCOL_BEHAVIOR_CHANGED=false")
    print("P93_RAW_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
