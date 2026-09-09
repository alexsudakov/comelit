#!/usr/bin/env python3
"""P94: expose structural metadata for the first P93 same-CTPP frames.

The P93 live run proved that, after client 0x000A is sent, three inbound frames
arrive on the same persistent CTPP channel but none has the capture-observed
44-byte device-0x000A shape. P93 therefore stops before prefix/action/tag/target
validation can begin.

This overlay composes P93 and does not change protocol behavior. It records only
bounded structural metadata for the first three same-CTPP frames observed while
the existing P92 device-0x000A gate is active:

* body length;
* prefix scalar (little-endian bytes 0..1), when present;
* action scalar (big-endian bytes 6..7), when present;
* flags scalar (big-endian bytes 8..9), when present.

The values are emitted under the already-allowlisted P80_ prefix immediately
before the unchanged P92 timeout fails closed. No payload bytes, sequence
numbers, target/channel identifiers, protocol addresses, endpoints, credentials,
or media are emitted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p93_device_000a_gate_diagnostics_transform import (
    DEFAULT_SOURCE,
    transform as add_p93_runtime,
)


_META_MAX = 3

_STATE_ANCHOR = """static guint64 p93_device_000a_target_match = 0;

static void p78_fail_rtpc(const char *marker);"""

_STATE_REPLACEMENT = f"""static guint64 p93_device_000a_target_match = 0;

/* P94 bounded structural metadata for same-CTPP frames seen by the P92 gate. */
#define P94_DEVICE_000A_FRAME_META_MAX {_META_MAX}u
static guint p94_device_000a_frame_meta_count = 0;
static guint p94_device_000a_frame_body_len[P94_DEVICE_000A_FRAME_META_MAX] = {{0}};
static guint p94_device_000a_frame_prefix[P94_DEVICE_000A_FRAME_META_MAX] = {{0}};
static guint p94_device_000a_frame_action[P94_DEVICE_000A_FRAME_META_MAX] = {{0}};
static guint p94_device_000a_frame_flags[P94_DEVICE_000A_FRAME_META_MAX] = {{0}};
static gboolean p94_device_000a_frame_prefix_present[P94_DEVICE_000A_FRAME_META_MAX] = {{FALSE}};
static gboolean p94_device_000a_frame_action_present[P94_DEVICE_000A_FRAME_META_MAX] = {{FALSE}};
static gboolean p94_device_000a_frame_flags_present[P94_DEVICE_000A_FRAME_META_MAX] = {{FALSE}};

static void p78_fail_rtpc(const char *marker);"""


_HELPER_ANCHOR = """static gboolean
p92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)
{"""

_HELPER_REPLACEMENT = r'''static void
p94_observe_device_000a_frame_metadata(const guint8 *body, guint body_len)
{
    if (!body || p94_device_000a_frame_meta_count >= P94_DEVICE_000A_FRAME_META_MAX)
        return;

    guint index = p94_device_000a_frame_meta_count++;
    p94_device_000a_frame_body_len[index] = body_len;

    if (body_len >= 2u) {
        p94_device_000a_frame_prefix[index] =
            (guint)body[0] | ((guint)body[1] << 8);
        p94_device_000a_frame_prefix_present[index] = TRUE;
    }

    if (body_len >= 8u) {
        p94_device_000a_frame_action[index] =
            ((guint)body[6] << 8) | (guint)body[7];
        p94_device_000a_frame_action_present[index] = TRUE;
    }

    if (body_len >= 10u) {
        p94_device_000a_frame_flags[index] =
            ((guint)body[8] << 8) | (guint)body[9];
        p94_device_000a_frame_flags_present[index] = TRUE;
    }
}


static gboolean
p92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)
{'''


_VALIDATOR_ANCHOR = """    p93_device_000a_ctpp_frames++;

    if (body_len != 44u || p78_rtpc_client_000a_len != 44u)"""

_VALIDATOR_REPLACEMENT = """    p93_device_000a_ctpp_frames++;
    p94_observe_device_000a_frame_metadata(body, body_len);

    if (body_len != 44u || p78_rtpc_client_000a_len != 44u)"""


_TIMEOUT_MARKER_ANCHOR = '    printf("P80_DEVICE_000A_GATE_TIMEOUT=true\\n");\n'

_TIMEOUT_MARKER_REPLACEMENT = r'''    printf(
        "P80_DEVICE_000A_FRAME_META_COUNT=%u\n",
        p94_device_000a_frame_meta_count
    );
    for (guint i = 0; i < p94_device_000a_frame_meta_count; i++) {
        guint ordinal = i + 1u;
        printf(
            "P80_DEVICE_000A_FRAME_%u_BODY_LEN=%u\n",
            ordinal,
            p94_device_000a_frame_body_len[i]
        );
        printf(
            "P80_DEVICE_000A_FRAME_%u_PREFIX_PRESENT=%s\n",
            ordinal,
            p94_device_000a_frame_prefix_present[i] ? "true" : "false"
        );
        if (p94_device_000a_frame_prefix_present[i]) {
            printf(
                "P80_DEVICE_000A_FRAME_%u_PREFIX=%u\n",
                ordinal,
                p94_device_000a_frame_prefix[i]
            );
        }
        printf(
            "P80_DEVICE_000A_FRAME_%u_ACTION_PRESENT=%s\n",
            ordinal,
            p94_device_000a_frame_action_present[i] ? "true" : "false"
        );
        if (p94_device_000a_frame_action_present[i]) {
            printf(
                "P80_DEVICE_000A_FRAME_%u_ACTION=%u\n",
                ordinal,
                p94_device_000a_frame_action[i]
            );
        }
        printf(
            "P80_DEVICE_000A_FRAME_%u_FLAGS_PRESENT=%s\n",
            ordinal,
            p94_device_000a_frame_flags_present[i] ? "true" : "false"
        );
        if (p94_device_000a_frame_flags_present[i]) {
            printf(
                "P80_DEVICE_000A_FRAME_%u_FLAGS=%u\n",
                ordinal,
                p94_device_000a_frame_flags[i]
            );
        }
    }
    printf("P80_DEVICE_000A_GATE_TIMEOUT=true\n");
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p93_runtime(source)
    candidate = _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE_REPLACEMENT,
        "P94 metadata state",
    )
    candidate = _replace_once(
        candidate,
        _HELPER_ANCHOR,
        _HELPER_REPLACEMENT,
        "P94 metadata helper",
    )
    candidate = _replace_once(
        candidate,
        _VALIDATOR_ANCHOR,
        _VALIDATOR_REPLACEMENT,
        "P94 validator observation",
    )
    candidate = _replace_once(
        candidate,
        _TIMEOUT_MARKER_ANCHOR,
        _TIMEOUT_MARKER_REPLACEMENT,
        "P94 timeout metadata report",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P94 DEVICE 000A FRAME METADATA ===",
            "P94_COMPOSES=P93",
            "P94_PROTOCOL_BEHAVIOR_CHANGED=false",
            "P94_FRAME_METADATA_LIMIT=3",
            "P94_FIELDS=BODY_LEN_PREFIX_ACTION_FLAGS",
            "P94_RAW_PAYLOAD_EMITTED=false",
            "P94_SEQUENCE_VALUE_EMITTED=false",
            "P94_TARGET_ID_VALUE_EMITTED=false",
            "P94_CHANNEL_ID_VALUE_EMITTED=false",
            "P94_ADDRESS_VALUE_EMITTED=false",
            "P94_AUTOMATIC_RETRY=false",
            "P94_SECOND_CTPP_OPEN=false",
            "P94_DOOR_ACTION_SENT=false",
            "P94_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P94_MEDIA_HARD_LIMIT_SECONDS=180",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P94 DEVICE 000A FRAME METADATA ===",
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
    print("P94_TRANSFORM=PASS")
    print("P94_PROTOCOL_BEHAVIOR_CHANGED=false")
    print("P94_FRAME_METADATA_LIMIT=3")
    print("P94_RAW_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
