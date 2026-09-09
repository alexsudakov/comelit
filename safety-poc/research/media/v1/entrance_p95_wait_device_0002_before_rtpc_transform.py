#!/usr/bin/env python3
"""P95: restore the capture-observed device-0002 ACK gate before RTPC.

P94 live metadata identified the three frames seen while P92 was waiting for a
post-RTPC device 0x000A as one generic 0x1800 ACK followed by two structurally
identical device 0x0002 frames (0x1840/0x0002, flags 0x000C, body length 36).
The frozen official self-activation capture places that device 0x0002 before
RTPC OPEN and immediately follows it with one client 0x1800 ACK.

The inherited P78 binding currently starts RTPC immediately when the ACK for the
device 0x0008 finishes.  This overlay composes P94 and changes only that missing
pre-RTPC transition:

    device 0x0008 -> client ACK completion
    -> wait device 0x0002
    -> queue exactly one structural client 0x1800 ACK
    -> ACK TX completion
    -> begin the existing RTPC sequence

Retransmitted device 0x0002 frames are consumed without a second ACK or second
RTPC start.  The ACK sequence is generated from live session state as the next
capture-observed client ACK step after the already generated device-video ACK;
no captured sequence value is replayed.

No Door action, second CTPP OPEN, automatic retry, raw payload output, captured
identifier, or media payload is introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p94_device_000a_frame_metadata_transform import (
    DEFAULT_SOURCE,
    transform as add_p94_runtime,
)


_TX_KIND_ANCHOR = """    P78_TX_RTPC_CLIENT_000A,
    P78_TX_RTPC_CLIENT_001A,

    P12_TX_V4_DOOR_WRITE
"""

_TX_KIND_REPLACEMENT = """    P78_TX_RTPC_CLIENT_000A,
    P78_TX_RTPC_CLIENT_001A,

    P95_TX_DEVICE_0002_ACK,

    P12_TX_V4_DOOR_WRITE
"""


_STATE_ANCHOR = """static gboolean p92_wait_device_000a = FALSE;
static gboolean p92_device_000a_observed = FALSE;
"""

_STATE_REPLACEMENT = """static gboolean p92_wait_device_000a = FALSE;
static gboolean p92_device_000a_observed = FALSE;

/* P95 pre-RTPC device-0002 gate. */
static gboolean p95_wait_device_0002 = FALSE;
static gboolean p95_device_0002_observed = FALSE;
static gboolean p95_device_0002_ack_queued = FALSE;
static gboolean p95_device_0002_ack_sent = FALSE;
static gboolean p95_rtpc_started = FALSE;
static guint p95_device_0002_rx_count = 0;
"""


_DEVICE_VIDEO_ACK_COMPLETION_OLD = r'''        case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:
            entrance_device_video_ack_sent = TRUE;
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true\n");
            printf("P78_DEVICE_0008_ACK_SENT=true\n");
            printf("P78_DEVICE_0008_ACK_GATE_PROVEN=false\n");
            fflush(stdout);

            if (!p78_begin_rtpc_control()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;
'''

_DEVICE_VIDEO_ACK_COMPLETION_NEW = r'''        case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:
            entrance_device_video_ack_sent = TRUE;
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true\n");
            printf("P78_DEVICE_0008_ACK_SENT=true\n");
            printf("P78_DEVICE_0008_ACK_GATE_PROVEN=false\n");
            fflush(stdout);

            p95_wait_device_0002 = TRUE;
            p95_device_0002_observed = FALSE;
            p95_device_0002_ack_queued = FALSE;
            p95_device_0002_ack_sent = FALSE;
            p95_rtpc_started = FALSE;
            p95_device_0002_rx_count = 0;
            if (g_timeout_add_seconds(3, p95_device_0002_timeout_cb, NULL) == 0) {
                p78_fail_rtpc("P80_DEVICE_0002_TIMER_START=FAIL");
                break;
            }
            printf("P80_DEVICE_0002_GATE_ARMED=true\n");
            printf("P80_DEVICE_0002_TIMEOUT_SECONDS=3\n");
            fflush(stdout);
            break;

        case P95_TX_DEVICE_0002_ACK:
            p95_device_0002_ack_sent = TRUE;
            p95_wait_device_0002 = FALSE;
            printf("P80_DEVICE_0002_ACK_SENT=PASS\n");
            printf("P80_DEVICE_0002_ACK_SEQUENCE_EMITTED=false\n");
            printf("P80_DEVICE_0002_ACK_CTPP_REUSED=true\n");
            fflush(stdout);

            if (p95_rtpc_started) {
                p78_fail_rtpc("P80_DEVICE_0002_RTPC_DOUBLE_START=FAIL");
                break;
            }
            p95_rtpc_started = TRUE;
            printf("P80_DEVICE_0002_GATE=PASS\n");
            fflush(stdout);
            if (!p78_begin_rtpc_control()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;
'''


_FRAME_HOOK_ANCHOR = """        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
"""

_FRAME_HOOK_REPLACEMENT = """        } else if (p95_wait_device_0002) {
            if (p95_handle_device_0002(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
"""


_HELPER_ANCHOR = "static gboolean\np92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)\n{"

_P95_HELPERS = r'''#define P95_DEVICE_0002_TIMEOUT_SECONDS 3
#define P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK 0x01000000u

static gboolean
p95_device_0002_timeout_cb(gpointer data)
{
    (void)data;

    if (!p95_wait_device_0002 || p95_device_0002_observed)
        return G_SOURCE_REMOVE;

    p95_wait_device_0002 = FALSE;
    printf("P80_DEVICE_0002_RX_COUNT=%u\n", p95_device_0002_rx_count);
    fflush(stdout);
    p78_fail_rtpc("P80_DEVICE_0002_GATE_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}

static gboolean
p95_device_0002_is_valid(guint16 request_id, const guint8 *body, guint body_len)
{
    return
        body &&
        request_id == v4_ctpp_channel_id &&
        body_len == 36u &&
        read_le16(body + 0) == 0x1840u &&
        body[6] == 0x00u && body[7] == 0x02u &&
        body[8] == 0x00u && body[9] == 0x0cu &&
        body[10] == 0x00u && body[11] == 0x00u &&
        body[12] == 0xffu && body[13] == 0xffu &&
        body[14] == 0xffu && body[15] == 0xffu &&
        memcmp(body + 16u, V4_ENTRANCE, 8u) == 0 &&
        body[24] == 0x00u && body[25] == 0x00u &&
        memcmp(body + 26u, V4_FULL_ADDRESS, 9u) == 0 &&
        body[35] == 0x00u;
}

static gboolean
p95_queue_device_0002_ack(void)
{
    if (!p95_wait_device_0002 ||
        !p95_device_0002_observed ||
        p95_device_0002_ack_queued ||
        p95_device_0002_ack_sent ||
        p95_rtpc_started ||
        !entrance_device_video_ack_sent ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        v4_ctpp_channel_id == 0 ||
        p12_tx_pending ||
        pseudotcp_graceful_stop_started) {

        p78_fail_rtpc("P80_DEVICE_0002_ACK_PRECONDITION=FAIL");
        return FALSE;
    }

    guint8 body[32];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0x1800u);
    write_le32(
        body + 2,
        entrance_device_video_ack_sequence +
            P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK
    );
    body[6] = 0x00u;
    body[7] = 0x00u;
    memset(body + 8, 0xff, 4);

    /* Capture-observed response address role reversal. */
    memcpy(body + 12, V4_FULL_ADDRESS, 9);
    body[21] = 0x00u;
    memcpy(body + 22, V4_ENTRANCE, 8);
    body[30] = 0x00u;
    body[31] = 0x00u;

    p95_device_0002_ack_queued = TRUE;
    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P95_TX_DEVICE_0002_ACK
    );
    memset(body, 0, sizeof(body));

    if (!ok) {
        p95_device_0002_ack_queued = FALSE;
        p78_fail_rtpc("P80_DEVICE_0002_ACK_QUEUE=FAIL");
        return FALSE;
    }

    printf("P80_DEVICE_0002_ACK_QUEUED=PASS\n");
    printf("P80_DEVICE_0002_ACK_SEQUENCE_SOURCE=LIVE_SESSION_STATE\n");
    printf("P80_DEVICE_0002_ACK_SEQUENCE_EMITTED=false\n");
    fflush(stdout);

    if (!p12_flush_tx()) {
        p78_fail_rtpc("P80_DEVICE_0002_ACK_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p95_handle_device_0002(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!p95_wait_device_0002)
        return FALSE;

    if (request_id == v4_ctpp_channel_id)
        p95_device_0002_rx_count++;

    if (!p95_device_0002_is_valid(request_id, body, body_len))
        return FALSE;

    if (p95_device_0002_observed) {
        printf("P80_DEVICE_0002_RETRANSMIT_CONSUMED=true\n");
        fflush(stdout);
        return TRUE;
    }

    p95_device_0002_observed = TRUE;
    printf("P80_DEVICE_0002_OBSERVED=PASS\n");
    printf("P80_DEVICE_0002_BODY_LEN=36\n");
    printf("P80_DEVICE_0002_PREFIX=6208\n");
    printf("P80_DEVICE_0002_ACTION=2\n");
    printf("P80_DEVICE_0002_FLAGS=12\n");
    fflush(stdout);

    if (!p95_queue_device_0002_ack())
        return TRUE;

    return TRUE;
}

'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p94_runtime(source)
    candidate = _replace_once(
        candidate, _TX_KIND_ANCHOR, _TX_KIND_REPLACEMENT, "P95 tx kind"
    )
    candidate = _replace_once(
        candidate, _STATE_ANCHOR, _STATE_REPLACEMENT, "P95 state"
    )
    candidate = _replace_once(
        candidate,
        _DEVICE_VIDEO_ACK_COMPLETION_OLD,
        _DEVICE_VIDEO_ACK_COMPLETION_NEW,
        "P95 device-video ACK completion",
    )
    candidate = _replace_once(
        candidate, _FRAME_HOOK_ANCHOR, _FRAME_HOOK_REPLACEMENT, "P95 frame hook"
    )
    candidate = _replace_once(
        candidate, _HELPER_ANCHOR, _P95_HELPERS + _HELPER_ANCHOR, "P95 helpers"
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P95 DEVICE 0002 PRE-RTPC GATE ===",
            "P95_COMPOSES=P94",
            "P95_ORDER=DEVICE_0008_ACK_DEVICE_0002_ACK_RTPC",
            "P95_DEVICE_0002_BODY_LEN=36",
            "P95_DEVICE_0002_PREFIX=0x1840",
            "P95_DEVICE_0002_ACTION=0x0002",
            "P95_DEVICE_0002_FLAGS=0x000C",
            "P95_DEVICE_0002_TIMEOUT_SECONDS=3",
            "P95_DEVICE_0002_ACK_MAX_SENDS=1",
            "P95_RETRANSMIT_SECOND_ACK=false",
            "P95_RTPC_START_AFTER_ACK_TX_COMPLETE=true",
            "P95_ACK_SEQUENCE_SOURCE=LIVE_SESSION_STATE",
            "P95_CAPTURE_SEQUENCE_REPLAY=false",
            "P95_AUTOMATIC_RETRY=false",
            "P95_SECOND_CTPP_OPEN=false",
            "P95_DOOR_ACTION_SENT=false",
            "P95_RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P95 DEVICE 0002 PRE-RTPC GATE ===",
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
    print("P95_TRANSFORM=PASS")
    print("P95_DEVICE_0002_GATE_REQUIRED=true")
    print("P95_RTPC_START_AFTER_ACK_TX_COMPLETE=true")
    print("P95_DEVICE_0002_ACK_MAX_SENDS=1")
    print("P95_CAPTURE_SEQUENCE_REPLAY=false")
    print("P95_AUTOMATIC_RETRY=false")
    print("P95_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
