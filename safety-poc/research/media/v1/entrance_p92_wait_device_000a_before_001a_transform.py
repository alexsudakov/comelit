#!/usr/bin/env python3
"""P92: restore the observed device-000A gate before client 001A.

Live P91 evidence proved that the generated RTPC exchange reaches
P80_MEDIA_ACTIVE but no non-PseudoTCP offset-8 media UDP starts: only residual
selected-flow datagrams are seen and none matches the proven P77 media wrapper.
The frozen official self-activation capture orders the final CTPP media setup as
client 0x000A -> device 0x000A -> client 0x001A.  P78/P83 currently sends
client 0x001A immediately when client 0x000A TX completes and does not wait for
that device 0x000A.

This overlay composes P91 and makes only that observed ordering a bounded live
gate.  It arms the gate before client 0x000A is queued, recognizes only a
structural device 0x000A on the already-open CTPP request id with the same
RTPC tag/target binding as the generated client 0x000A, and queues client
0x001A only after both the device 0x000A and local client-0x000A TX completion
have occurred.  A three-second missing-device-000A timeout fails closed.

No capture target ids, addresses, payload bytes, credentials, Door action,
second CTPP OPEN, or automatic retry are introduced.  P91 media RX diagnostics
and the HA-owned 180-second lifetime remain intact.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p91_media_rx_stage_diagnostics_transform import (
    DEFAULT_SOURCE,
    transform as add_p91_runtime,
)


_STATE_ANCHOR = """static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;

static void p78_fail_rtpc(const char *marker);"""

_STATE_REPLACEMENT = """static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;

/* P92 observed-order gate: official client waits for device 0x000A before
 * sending client 0x001A. */
static gboolean p92_wait_device_000a = FALSE;
static gboolean p92_device_000a_observed = FALSE;

static void p78_fail_rtpc(const char *marker);
static gboolean p92_handle_device_000a(guint16 request_id, const guint8 *body, guint body_len);"""


_CLIENT_000A_COMPLETION_OLD = """        case P78_TX_RTPC_CLIENT_000A:
            p78_rtpc_client_000a_sent = TRUE;
            printf(\"P78_RTPC_CLIENT_000A_SENT=PASS\\n\");
            fflush(stdout);
            (void)p78_queue_rtpc_client_001a();
            break;"""

_CLIENT_000A_COMPLETION_NEW = """        case P78_TX_RTPC_CLIENT_000A:
            p78_rtpc_client_000a_sent = TRUE;
            printf(\"P78_RTPC_CLIENT_000A_SENT=PASS\\n\");
            fflush(stdout);
            if (p92_device_000a_observed) {
                printf(\"P92_DEVICE_000A_GATE=PASS\\n\");
                fflush(stdout);
                (void)p78_queue_rtpc_client_001a();
            } else {
                printf(\"P92_WAIT_DEVICE_000A=true\\n\");
                fflush(stdout);
            }
            break;"""


_FRAME_HOOK_OLD = """        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
            if (p78_handle_rtpc_control_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""

_FRAME_HOOK_NEW = """        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
            if (p78_handle_rtpc_control_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p92_wait_device_000a) {
            if (p92_handle_device_000a(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""


_QUEUE_CLIENT_000A_OLD = """    p78_rtpc_stage = P78_RTPC_CLIENT_000A_TX;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            p78_rtpc_client_000a,
            p78_rtpc_client_000a_len,
            P78_TX_RTPC_CLIENT_000A)) {"""

_QUEUE_CLIENT_000A_NEW = """    p92_wait_device_000a = TRUE;
    p92_device_000a_observed = FALSE;
    g_timeout_add_seconds(3, p92_device_000a_timeout_cb, NULL);
    printf(\"P92_DEVICE_000A_GATE_ARMED=true\\n\");
    printf(\"P92_DEVICE_000A_TIMEOUT_SECONDS=3\\n\");
    fflush(stdout);

    p78_rtpc_stage = P78_RTPC_CLIENT_000A_TX;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            p78_rtpc_client_000a,
            p78_rtpc_client_000a_len,
            P78_TX_RTPC_CLIENT_000A)) {"""


_HELPER_ANCHOR = "static gboolean\np83_queue_client_media_after_responses(void)\n"

_P92_HELPERS = r'''#define P92_DEVICE_000A_TIMEOUT_SECONDS 3

static gboolean
p92_device_000a_timeout_cb(gpointer data)
{
    (void)data;

    if (!p92_wait_device_000a || p92_device_000a_observed)
        return G_SOURCE_REMOVE;

    p92_wait_device_000a = FALSE;
    p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}

static gboolean
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
}

static gboolean
p92_handle_device_000a(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!p92_wait_device_000a ||
        !p92_device_000a_is_valid(request_id, body, body_len))
        return FALSE;

    p92_device_000a_observed = TRUE;
    p92_wait_device_000a = FALSE;
    printf("P92_DEVICE_000A_OBSERVED=PASS\n");
    fflush(stdout);

    if (!p78_rtpc_client_000a_sent) {
        printf("P92_DEVICE_000A_BEFORE_TX_COMPLETE=true\n");
        fflush(stdout);
        return TRUE;
    }

    printf("P92_DEVICE_000A_GATE=PASS\n");
    fflush(stdout);
    (void)p78_queue_rtpc_client_001a();
    return TRUE;
}

'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p91_runtime(source)
    candidate = _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE_REPLACEMENT,
        "P92 state/prototype",
    )
    candidate = _replace_once(
        candidate,
        _CLIENT_000A_COMPLETION_OLD,
        _CLIENT_000A_COMPLETION_NEW,
        "P92 client 000A completion",
    )
    candidate = _replace_once(
        candidate,
        _FRAME_HOOK_OLD,
        _FRAME_HOOK_NEW,
        "P92 device 000A frame hook",
    )
    candidate = _replace_once(
        candidate,
        _HELPER_ANCHOR,
        _P92_HELPERS + _HELPER_ANCHOR,
        "P92 helpers",
    )
    candidate = _replace_once(
        candidate,
        _QUEUE_CLIENT_000A_OLD,
        _QUEUE_CLIENT_000A_NEW,
        "P92 gate arm before client 000A",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P92 DEVICE 000A ORDER GATE ===",
            "P92_COMPOSES=P91",
            "P92_OFFICIAL_ORDER=CLIENT_000A_DEVICE_000A_CLIENT_001A",
            "P92_DEVICE_000A_GATE_REQUIRED=true",
            "P92_DEVICE_000A_TIMEOUT_SECONDS=3",
            "P92_DEVICE_000A_MATCH=CTPP_REQUEST_PREFIX_ACTION_DYNAMIC_RTPC_BINDING",
            "P92_CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false",
            "P92_RAW_PAYLOAD_EMITTED=false",
            "P92_AUTOMATIC_RETRY=false",
            "P92_SECOND_CTPP_OPEN=false",
            "P92_DOOR_ACTION_SENT=false",
            "P92_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P92_MEDIA_HARD_LIMIT_SECONDS=180",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P92 DEVICE 000A ORDER GATE ===",
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
    print("P92_TRANSFORM=PASS")
    print("P92_DEVICE_000A_GATE_REQUIRED=true")
    print("P92_DEVICE_000A_TIMEOUT_SECONDS=3")
    print("P92_RAW_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
