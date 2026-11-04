#!/usr/bin/env python3
"""P126 defer same-channel non-ACK frames to the regular CTPP demux."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p125_ringid_probe_media_transform as p125

BASE_SOURCE_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
P125_TRANSFORM = "entrance_p125_ringid_probe_media_transform.py"
INPUT_SOURCE_SHA256 = "4bfdf264fbd74c5796d2386d835f0beeea15d23f8c3b1ea460323b7930b741a7"

_STATE_ANCHOR = "static guint r27_refresh_last_accepted_index = 0;\n"
_STATE_REPLACEMENT = _STATE_ANCHOR + "static guint r126_refresh_deferred_index = 0;\n"

_HANDLER_OLD = r'''static gboolean
r27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!r27_repeat_outstanding)
        return FALSE;
    if (p99_state_scoped_structural_ack(request_id, body, body_len)) {
        r27_repeat_ack_observed = TRUE;
        r27_repeat_outstanding = FALSE;
        r27_refresh_last_accepted_index = r27_refresh_current_index;
        printf("SECOND_001A_RESPONSE=STRUCTURAL_ACK\n");
        printf("SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL\n");
        printf("R27_REPEAT_ACK_BINDING=STATE_SCOPED_STRUCTURAL\n");
        printf("REFRESH_RESPONSE_%u=STRUCTURAL_ACK\n", r27_refresh_current_index);
        printf("REFRESH_OUTSTANDING=false\n");
        (void)r27_schedule_next_refresh("structural-ack");
        fflush(stdout);
        return TRUE;
    }
    if (request_id == v4_ctpp_channel_id && body && body_len >= 4u) {
        /* A distinguishable reject path is not safe here: a non-structural
         * same-channel body cannot be proven to bind to the repeat rather than
         * an unrelated message, so report the contract-permitted AMBIGUOUS
         * state instead of a dead REJECTED state. */
        r27_repeat_ambiguous = TRUE;
        r27_repeat_outstanding = FALSE;
        r27_refresh_fail_closed = TRUE;
        printf("SECOND_001A_RESPONSE=AMBIGUOUS\n");
        printf("SECOND_001A_ACK_CLASSIFICATION=AMBIGUOUS\n");
        printf("REFRESH_RESPONSE_%u=AMBIGUOUS\n", r27_refresh_current_index);
        printf("REFRESH_OUTSTANDING=false\n");
        printf("REFRESH_FAIL_CLOSED=true\n");
        fflush(stdout);
        (void)pseudotcp_begin_graceful_stop("r27-refresh-ambiguous");
        return TRUE;
    }
    return FALSE;
}
'''

_HANDLER_NEW = r'''static gboolean
r27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!r27_repeat_outstanding)
        return FALSE;
    if (p99_state_scoped_structural_ack(request_id, body, body_len)) {
        r27_repeat_ack_observed = TRUE;
        r27_repeat_outstanding = FALSE;
        r27_refresh_last_accepted_index = r27_refresh_current_index;
        printf("SECOND_001A_RESPONSE=STRUCTURAL_ACK\n");
        printf("SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL\n");
        printf("R27_REPEAT_ACK_BINDING=STATE_SCOPED_STRUCTURAL\n");
        printf("REFRESH_RESPONSE_%u=STRUCTURAL_ACK\n", r27_refresh_current_index);
        printf("REFRESH_OUTSTANDING=false\n");
        (void)r27_schedule_next_refresh("structural-ack");
        fflush(stdout);
        return TRUE;
    }
    if (request_id == v4_ctpp_channel_id && body && body_len > 0u) {
        /* A same-channel non-ACK may be an unrelated control frame (including
         * CALL_INIT).  Leave it in the receive buffer for the regular demux. */
        if (r126_refresh_deferred_index != r27_refresh_current_index) {
            r126_refresh_deferred_index = r27_refresh_current_index;
            printf("SECOND_001A_RESPONSE=DEFERRED\n");
            printf("SECOND_001A_ACK_CLASSIFICATION=DEFERRED\n");
            printf("REFRESH_RESPONSE_%u=DEFERRED\n", r27_refresh_current_index);
            printf("REFRESH_OUTSTANDING=true\n");
            fflush(stdout);
        }
    }
    return FALSE;
}
'''


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"P126_{label}_ANCHOR_COUNT=FAIL actual={count}")
    return source.replace(old, new, 1)


def transform(source: str, *, include_p116: bool = True) -> str:
    base_sha = _sha256_text(source)
    if base_sha != BASE_SOURCE_SHA256:
        raise RuntimeError(f"P126_BASE_SOURCE_SHA_GATE=FAIL actual={base_sha}")
    input_source = p125.transform(source, include_p116=include_p116)
    input_sha = _sha256_text(input_source)
    if input_sha != INPUT_SOURCE_SHA256:
        raise RuntimeError(f"P126_INPUT_SOURCE_SHA_GATE=FAIL actual={input_sha}")
    generated = _replace_once(input_source, _STATE_ANCHOR, _STATE_REPLACEMENT, "STATE")
    return _replace_once(generated, _HANDLER_OLD, _HANDLER_NEW, "HANDLER")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    p116 = parser.add_mutually_exclusive_group()
    p116.add_argument("--include-p116", dest="include_p116", action="store_true")
    p116.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    parser.set_defaults(include_p116=True)
    args = parser.parse_args(argv)
    if not args.include_p116:
        parser.error("P126 requires --include-p116; --no-include-p116 is fail-closed")

    generated = transform(args.source.read_text(encoding="utf-8"), include_p116=True)
    args.output.write_text(generated, encoding="utf-8")
    print("P126_REFRESH_DEFER_TRANSFORM=PASS")
    print("P126_P125_TRANSFORM=" + P125_TRANSFORM)
    print("P126_INPUT_SOURCE_SHA256=" + INPUT_SOURCE_SHA256)
    print("P126_GENERATED_SOURCE_SHA256=" + _sha256_text(generated))
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
