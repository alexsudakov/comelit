#!/usr/bin/env python3
"""Add forensic CTPP RX evidence to the already-safe P13 native transform.

This module deliberately layers on top of ``p13_holder_transform_safe.py``.
It does not change the peer/TAP send cadence, add retries, or introduce a new
actuation surface.  It only records inbound frames that are already known to
belong to the opened CTPP channel.

The generated holder writes these lines to its stdout.  On the real CT120 path
that stdout is redirected by ``Ct120RealP13Session`` to the root-only
``/root/comelit-p13-run/p13-live-run.log`` (mode 0600); the Python session
adapter does not forward unknown holder lines to Hermes/public evidence.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
SAFE = SCRIPT_DIR / "p13_holder_transform_safe.py"

spec = importlib.util.spec_from_file_location("p13_holder_transform_safe_evidence_base", SAFE)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def _rx_helper() -> str:
    return r'''static void
p13_log_ctpp_rx_evidence(
    const guint8 *body,
    guint body_len,
    guint32 request_id)
{
    /* This helper is called only after CTPP OPEN has succeeded and only for
     * request_id == ctpp_channel_id.  Therefore UAUT JSON / credential-bearing
     * frames are outside this evidence surface. */
    gint64 ts_us = g_get_monotonic_time();
    gchar *sha256 =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            (const guchar *)body,
            (gsize)body_len
        );
    GString *hex = g_string_sized_new((gsize)body_len * 2u);

    for (guint i = 0; i < body_len; i++)
        g_string_append_printf(hex, "%02x", body[i]);

    printf(
        "P13_CTPP_RX_EVIDENCE ts_us=%" G_GINT64_FORMAT
        " stage=%u request_id=%u body_len=%u body_sha256=%s body_hex=%s\n",
        ts_us,
        (unsigned)p13_stage,
        (unsigned)request_id,
        (unsigned)body_len,
        sha256 ? sha256 : "UNAVAILABLE",
        hex->str
    );
    fflush(stdout);

    if (sha256)
        g_free(sha256);
    g_string_free(hex, TRUE);
}


'''


def transform(source: str, payload: dict, ctpp_address: str) -> str:
    text = module.transform(source, payload, ctpp_address)

    helper_anchor = "static gboolean\np13_process_post_uaut(void)\n{"
    text = _replace_once(
        text,
        helper_anchor,
        _rx_helper() + helper_anchor,
        "CTPP RX evidence helper",
    )

    body_anchor = '''        const guint8 *body =
            post_ack_capture + 8;
'''
    body_with_log = body_anchor + '''
        if (p13_ctpp_open_ok &&
            request_id == ctpp_channel_id) {
            p13_log_ctpp_rx_evidence(body, body_len, request_id);
        }
'''
    text = _replace_once(
        text,
        body_anchor,
        body_with_log,
        "CTPP RX evidence call",
    )

    old_marker = '''            printf("P13_DOOR_INBOUND_FRAME_OBSERVED=true\\n");
            fflush(stdout);
'''
    new_marker = '''            printf("P13_DOOR_INBOUND_FRAME_OBSERVED=true\\n");
            printf("P13_DOOR_RESPONSE_SEEN=true\\n");
            fflush(stdout);
'''
    text = _replace_once(
        text,
        old_marker,
        new_marker,
        "Door response semantic marker",
    )

    required = (
        "p13_log_ctpp_rx_evidence(body, body_len, request_id);",
        "P13_CTPP_RX_EVIDENCE ts_us=",
        "body_sha256=%s body_hex=%s",
        "P13_DOOR_RESPONSE_SEEN=true",
        "P13_DOOR_INBOUND_FRAME_OBSERVED=true",
        "g_timeout_add(200, p13_register_settle_cb, NULL);",
        "g_timeout_add(1000, p13_post_writes_settle_cb, NULL);",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"P13 evidence transform missing marker: {marker}")

    forbidden = (
        "P13_DOOR_WRITE_%u_ACKED=true",
        "P13_DOOR_WRITE_REQUEST_ID=FAIL",
        "p13_retry(",
        "retry_door",
    )
    for marker in forbidden:
        if marker in text:
            raise RuntimeError(f"P13 evidence transform reintroduced forbidden surface: {marker}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add root-only CTPP RX evidence to the safe P13 holder transform"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ctpp-address", required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    text = transform(source, payload, args.ctpp_address)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")

    print("P13_HOLDER_RX_EVIDENCE_TRANSFORM=PASS")
    print("P13_DOOR_ACK_SEMANTICS=UNPROVEN")
    print("P13_DOOR_RESPONSE_SEMANTICS=RESPONSE_SEEN")
    print("P13_CTPP_RX_RAW_EVIDENCE_SCOPE=ROOT_ONLY_RUNTIME_LOG")
    print("P13_SEND_TIMING_CHANGED=false")
    print("P13_RETRY_SURFACE_PRESENT=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
