#!/usr/bin/env python3
"""P83: accept valid RTPC RESPONSE frames before the device RTPC OPEN.

Live evidence showed that after both client RTPC OPENs are transmitted the device
may answer one of those OPENs before sending its own RTPC OPEN. P76/P75 already
model response pairing independently of total order, but the P78 live binding
incorrectly treated every request-id 0 frame in WAIT_DEVICE_OPEN as an OPEN.

This overlay keeps the P76 validators and pairing state unchanged. It classifies
request-id 0 RTPC control frames by the already-proven OPEN/RESPONSE schemas,
records valid early RESPONSEs, continues waiting for the device OPEN, and starts
client 000A/001A only after the client response to the device OPEN has completed
and both device RESPONSEs have been paired.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p82_rtpc_device_open_shape_transform import (
    DEFAULT_SOURCE,
    transform as add_p82_runtime,
)


PROTOTYPE_ANCHOR = """static gboolean p78_queue_rtpc_client_001a(void);
static gboolean p78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len);"""

PROTOTYPE_REPLACEMENT = """static gboolean p78_queue_rtpc_client_001a(void);
static gboolean p83_queue_client_media_after_responses(void);
static gboolean p78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len);"""

CLIENT_RESPONSE_COMPLETION_ANCHOR = """        case P78_TX_RTPC_CLIENT_RESPONSE:
            p78_rtpc_client_response_sent = TRUE;
            p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_RESPONSES;
            printf(\"P78_RTPC_CLIENT_RESPONSE_SENT=PASS\\n\");
            fflush(stdout);
            break;"""

CLIENT_RESPONSE_COMPLETION_REPLACEMENT = """        case P78_TX_RTPC_CLIENT_RESPONSE:
            p78_rtpc_client_response_sent = TRUE;
            printf(\"P78_RTPC_CLIENT_RESPONSE_SENT=PASS\\n\");
            fflush(stdout);
            if (p78_rtpc_device_response_count >= 2u) {
                if (!p83_queue_client_media_after_responses()) {
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            } else {
                p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_RESPONSES;
            }
            break;"""

HANDLER_START = "static gboolean\np78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len)\n{"
HANDLER_END = "\n/* === P78_RTPC_MEDIA_LIVE_STAGE_END === */"

P83_HANDLER = r'''static gboolean
p83_queue_client_media_after_responses(void)
{
    P76Status status;

    if (!p78_rtpc_client_response_sent ||
        p78_rtpc_device_response_count < 2u ||
        p78_rtpc_runtime.facts.device_response_1_seen != P76_FACT_PAIRED ||
        p78_rtpc_runtime.facts.device_response_2_seen != P76_FACT_PAIRED) {
        p78_fail_rtpc("P83_RTPC_MEDIA_START_PRECONDITION=FAIL");
        return FALSE;
    }

    status = p76_generate_client_000a(
        &p78_rtpc_runtime,
        p78_rtpc_client_000a,
        p78_rtpc_client_000a_len);
    if (status != P76_OK) {
        p78_fail_rtpc("P78_RTPC_CLIENT_000A_GENERATION=FAIL");
        return FALSE;
    }
    status = p76_generate_client_001a(
        &p78_rtpc_runtime,
        p78_rtpc_client_001a,
        p78_rtpc_client_001a_len);
    if (status != P76_OK) {
        p78_fail_rtpc("P78_RTPC_CLIENT_001A_GENERATION=FAIL");
        return FALSE;
    }

    p78_rtpc_stage = P78_RTPC_CLIENT_000A_TX;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            p78_rtpc_client_000a,
            p78_rtpc_client_000a_len,
            P78_TX_RTPC_CLIENT_000A)) {
        p78_fail_rtpc("P78_RTPC_CLIENT_000A_QUEUE=FAIL");
        return FALSE;
    }
    if (!p12_flush_tx()) {
        p78_fail_rtpc("P78_RTPC_CLIENT_000A_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len)
{
    P76Status status;

    if (request_id != 0)
        return FALSE;

    if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN) {
        if (p76_rtpc_response_is_valid(body, body_len)) {
            status = p76_observe_device_response(&p78_rtpc_runtime, body, body_len);
            if (status != P76_OK) {
                p78_fail_rtpc("P83_RTPC_EARLY_DEVICE_RESPONSE=FAIL");
                return TRUE;
            }
            p78_rtpc_device_response_count++;
            printf("P83_RTPC_EARLY_DEVICE_RESPONSE_%u=PASS\n",
                (unsigned)p78_rtpc_device_response_count);
            fflush(stdout);
            return TRUE;
        }

        if (!p76_rtpc_open_is_valid(body, body_len)) {
            p78_fail_rtpc("P83_RTPC_WAIT_DEVICE_OPEN_UNRECOGNIZED_CONTROL=FAIL");
            return TRUE;
        }

        status = p76_observe_device_open(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL");
            return TRUE;
        }
        p78_rtpc_device_open_observed = TRUE;
        printf("P78_RTPC_DEVICE_OPEN_OBSERVED=PASS\n");
        fflush(stdout);

        status = p76_generate_client_response_to_device_open(
            &p78_rtpc_runtime,
            p78_rtpc_client_response,
            &p78_rtpc_client_response_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_CLIENT_RESPONSE_GENERATION=FAIL");
            return TRUE;
        }

        p78_rtpc_stage = P78_RTPC_CLIENT_RESPONSE_TX;
        if (!p12_queue_vip_frame(
                0,
                p78_rtpc_client_response,
                p78_rtpc_client_response_len,
                P78_TX_RTPC_CLIENT_RESPONSE)) {
            p78_fail_rtpc("P78_RTPC_CLIENT_RESPONSE_QUEUE=FAIL");
            return TRUE;
        }
        if (!p12_flush_tx()) {
            p78_fail_rtpc("P78_RTPC_CLIENT_RESPONSE_FLUSH=FAIL");
        }
        return TRUE;
    }

    if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
        if (!p76_rtpc_response_is_valid(body, body_len)) {
            p78_fail_rtpc("P78_RTPC_DEVICE_RESPONSE=FAIL");
            return TRUE;
        }
        status = p76_observe_device_response(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_DEVICE_RESPONSE=FAIL");
            return TRUE;
        }
        p78_rtpc_device_response_count++;
        printf("P78_RTPC_DEVICE_RESPONSE_%u=PASS\n",
            (unsigned)p78_rtpc_device_response_count);
        fflush(stdout);
        if (p78_rtpc_device_response_count < 2u)
            return TRUE;

        (void)p83_queue_client_media_after_responses();
        return TRUE;
    }

    return FALSE;
}
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    out = add_p82_runtime(source)
    out = _replace_once(out, PROTOTYPE_ANCHOR, PROTOTYPE_REPLACEMENT, "prototype")
    out = _replace_once(
        out,
        CLIENT_RESPONSE_COMPLETION_ANCHOR,
        CLIENT_RESPONSE_COMPLETION_REPLACEMENT,
        "client response completion",
    )

    start = out.find(HANDLER_START)
    if start < 0:
        raise RuntimeError("P78 handler start not found")
    end = out.find(HANDLER_END, start)
    if end < 0:
        raise RuntimeError("P78 handler end not found")
    if out.find(HANDLER_START, start + 1) >= 0:
        raise RuntimeError("P78 handler start is not unique")
    out = out[:start] + P83_HANDLER + out[end:]
    return out


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P83 RTPC RESPONSE-BEFORE-OPEN FIX ===",
            "P83_BASE=P82_DIAGNOSTIC_RUNTIME",
            "P83_RESPONSE_BEFORE_DEVICE_OPEN=SUPPORTED",
            "P83_PAIRING_SOURCE=P76_TARGET_ID_STATE",
            "P83_MEDIA_START_REQUIRES_TWO_PAIRED_RESPONSES=true",
            "P83_SECOND_CTPP_OPEN=false",
            "P83_AUTOMATIC_RETRY=false",
            "P83_DOOR_ACTION_SENT=false",
            "P83_NETWORK_IO_PERFORMED=false",
            "P83_CANDIDATE_EXECUTED=false",
            "=== END COMELIT P83 RTPC RESPONSE-BEFORE-OPEN FIX ===",
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
