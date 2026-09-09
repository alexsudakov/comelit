#!/usr/bin/env python3
"""P95: restore the capture-observed device-0002 ACK gate before RTPC.

Live P94 evidence showed that the P92 device-000A gate is reached too early:
while it is waiting for device 0x000A, the panel first emits a generic 0x1800
ACK and then repeats a 36-byte CTPP 0x1840/action-0x0002 frame.  The frozen
self-activation capture orders that device 0x0002 before the RTPC OPEN phase and
shows an immediate structural client 0x1800 ACK after it.

P78 currently starts RTPC immediately when the client ACK for device 0x0008 has
finished transmitting.  This overlay composes P94 and changes only that missing
boundary:

    device 0x0008 -> client structural ACK TX complete
    -> wait for one structural device 0x0002
    -> send one generated structural 0x1800 ACK on the existing CTPP channel
    -> ACK TX complete
    -> begin the existing P78 RTPC state machine

The device-0002 matcher is structural and session-bound: existing CTPP request
id, 36-byte body, prefix 0x1840, action 0x0002, flags 0x000c, and the current
entrance/full-address roles.  The ACK reverses the two address roles from the
live device frame.  Its sequence is derived from the already-generated previous
client ACK sequence using the capture-validated +0x01000000 progression; no
literal captured sequence value is copied.

A three-second missing-device-0002 timeout fails closed.  Duplicate matching
0x0002 frames while the single ACK is in flight are consumed without generating
a second ACK or a second RTPC start.  P92's later device-000A gate remains
unchanged.  Door, second CTPP OPEN, automatic retry, media lifetime and RTP
forwarding are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p94_device_000a_frame_metadata_transform import (
    DEFAULT_SOURCE,
    transform as add_p94_runtime,
)


_TX_ENUM_ANCHOR = """    P12_TX_ENTRANCE_DEVICE_VIDEO_ACK,

    P78_TX_RTPC_OPEN_1,"""

_TX_ENUM_REPLACEMENT = """    P12_TX_ENTRANCE_DEVICE_VIDEO_ACK,
    P95_TX_DEVICE_0002_ACK,

    P78_TX_RTPC_OPEN_1,"""


_STATE_ANCHOR = """static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;

/* P92 observed-order gate:"""

_STATE_REPLACEMENT = """static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;

/* P95 pre-RTPC device-0002 ACK gate. */
#define P95_DEVICE_0002_TIMEOUT_SECONDS 3
#define P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK 0x01000000u
static gboolean p95_wait_device_0002 = FALSE;
static gboolean p95_device_0002_observed = FALSE;
static gboolean p95_device_0002_ack_inflight = FALSE;
static gboolean p95_device_0002_ack_sent = FALSE;
static guint p95_device_0002_duplicate_count = 0;
static guint32 p95_device_0002_ack_sequence = 0;

static gboolean p95_device_0002_timeout_cb(gpointer data);
static gboolean p95_handle_device_0002(guint16 request_id, const guint8 *body, guint body_len);

/* P92 observed-order gate:"""


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

        case P78_TX_RTPC_OPEN_1:'''

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
            p95_device_0002_ack_inflight = FALSE;
            p95_device_0002_ack_sent = FALSE;
            p95_device_0002_duplicate_count = 0;
            if (g_timeout_add_seconds(
                    P95_DEVICE_0002_TIMEOUT_SECONDS,
                    p95_device_0002_timeout_cb,
                    NULL) == 0) {
                p78_fail_rtpc("P95_DEVICE_0002_TIMER_START=FAIL");
                break;
            }
            printf("P95_WAIT_DEVICE_0002=true\n");
            printf("P95_DEVICE_0002_TIMEOUT_SECONDS=%u\n",
                   P95_DEVICE_0002_TIMEOUT_SECONDS);
            fflush(stdout);
            break;

        case P95_TX_DEVICE_0002_ACK:
            p95_device_0002_ack_inflight = FALSE;
            p95_device_0002_ack_sent = TRUE;
            printf("P95_DEVICE_0002_ACK_SENT=PASS\n");
            printf("P95_DEVICE_0002_ACK_SEQUENCE_EMITTED=false\n");
            printf("P95_DEVICE_0002_ACK_ADDRESS_ROLE_REVERSAL=true\n");
            printf("P95_DEVICE_0002_ACK_CTPP_REUSED=true\n");
            printf("P95_DEVICE_0002_GATE=PASS\n");
            fflush(stdout);

            if (!p78_begin_rtpc_control()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

        case P78_TX_RTPC_OPEN_1:'''


_FRAME_HOOK_ANCHOR = """        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {"""

_FRAME_HOOK_REPLACEMENT = """        } else if (p95_wait_device_0002 ||
                   p95_device_0002_ack_inflight) {
            if (p95_handle_device_0002(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {"""


_HELPER_ANCHOR = "static gboolean\np83_queue_client_media_after_responses(void)\n"

_P95_HELPERS = r'''static gboolean
p95_device_0002_timeout_cb(gpointer data)
{
    (void)data;

    if (!p95_wait_device_0002 || p95_device_0002_observed)
        return G_SOURCE_REMOVE;

    p95_wait_device_0002 = FALSE;
    p78_fail_rtpc("P95_DEVICE_0002_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}

static gboolean
p95_device_0002_is_valid(
    guint16 request_id,
    const guint8 *body,
    guint body_len)
{
    if (!body || request_id != v4_ctpp_channel_id || body_len != 36u)
        return FALSE;

    /* CTPP prefix 0x1840 LE, action 0x0002 BE, flags 0x000c BE. */
    if (body[0] != 0x40u || body[1] != 0x18u ||
        body[6] != 0x00u || body[7] != 0x02u ||
        body[8] != 0x00u || body[9] != 0x0cu)
        return FALSE;

    /* Capture-observed address roles, validated against current session state.
     * Device frame tail: entrance addr10, then full-address addr10. */
    if (memcmp(body + 16u, V4_ENTRANCE, 8u) != 0 ||
        body[24] != 0x00u || body[25] != 0x00u ||
        memcmp(body + 26u, V4_FULL_ADDRESS, 9u) != 0 ||
        body[35] != 0x00u)
        return FALSE;

    return TRUE;
}

static gboolean
p95_queue_device_0002_ack(const guint8 *device_body, guint device_body_len)
{
    guint8 ack[32];

    if (!device_body || device_body_len != 36u ||
        !p95_device_0002_observed || p95_device_0002_ack_inflight ||
        p95_device_0002_ack_sent || p12_tx_pending ||
        !pseudo_tcp || !pseudotcp_open ||
        pseudotcp_graceful_stop_started || v4_ctpp_channel_id == 0) {

        p78_fail_rtpc("P95_DEVICE_0002_ACK_PRECONDITION=FAIL");
        return FALSE;
    }

    memset(ack, 0, sizeof(ack));
    write_le16(ack + 0, 0x1800);

    p95_device_0002_ack_sequence =
        entrance_device_video_ack_sequence +
        P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK;
    write_le32(ack + 2, p95_device_0002_ack_sequence);

    ack[6] = 0x00;
    ack[7] = 0x00;
    memset(ack + 8, 0xff, 4);

    /* Reverse the two address roles from this live device frame. */
    memcpy(ack + 12, device_body + 26u, 9u);
    ack[21] = 0x00;
    memcpy(ack + 22, device_body + 16u, 9u);
    ack[31] = 0x00;

    p95_device_0002_ack_inflight = TRUE;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            ack,
            sizeof(ack),
            P95_TX_DEVICE_0002_ACK)) {
        p95_device_0002_ack_inflight = FALSE;
        memset(ack, 0, sizeof(ack));
        p78_fail_rtpc("P95_DEVICE_0002_ACK_QUEUE=FAIL");
        return FALSE;
    }
    memset(ack, 0, sizeof(ack));

    printf("P95_DEVICE_0002_ACK_BODY_LEN=32\n");
    printf("P95_DEVICE_0002_ACK_PREFIX=6144\n");
    printf("P95_DEVICE_0002_ACK_ACTION=0\n");
    printf("P95_DEVICE_0002_ACK_FLAGS=65535\n");
    printf("P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK=16777216\n");
    printf("P95_DEVICE_0002_ACK_SEQUENCE_EMITTED=false\n");
    printf("P95_DEVICE_0002_ACK_ADDRESS_ROLE_REVERSAL=true\n");
    printf("P95_DEVICE_0002_ACK_CTPP_REUSED=true\n");
    fflush(stdout);

    if (!p12_flush_tx()) {
        p95_device_0002_ack_inflight = FALSE;
        p78_fail_rtpc("P95_DEVICE_0002_ACK_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p95_handle_device_0002(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!p95_device_0002_is_valid(request_id, body, body_len))
        return FALSE;

    if (p95_device_0002_observed) {
        p95_device_0002_duplicate_count++;
        printf("P95_DEVICE_0002_DUPLICATE_COUNT=%u\n",
               p95_device_0002_duplicate_count);
        fflush(stdout);
        return TRUE;
    }

    p95_device_0002_observed = TRUE;
    p95_wait_device_0002 = FALSE;
    printf("P95_DEVICE_0002_OBSERVED=PASS\n");
    printf("P95_DEVICE_0002_BODY_LEN=36\n");
    printf("P95_DEVICE_0002_PREFIX=6208\n");
    printf("P95_DEVICE_0002_ACTION=2\n");
    printf("P95_DEVICE_0002_FLAGS=12\n");
    fflush(stdout);

    (void)p95_queue_device_0002_ack(body, body_len);
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
        candidate,
        _TX_ENUM_ANCHOR,
        _TX_ENUM_REPLACEMENT,
        "P95 tx kind",
    )
    candidate = _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE_REPLACEMENT,
        "P95 state",
    )
    candidate = _replace_once(
        candidate,
        _DEVICE_VIDEO_ACK_COMPLETION_OLD,
        _DEVICE_VIDEO_ACK_COMPLETION_NEW,
        "P95 device-video ACK completion",
    )
    candidate = _replace_once(
        candidate,
        _FRAME_HOOK_ANCHOR,
        _FRAME_HOOK_REPLACEMENT,
        "P95 pre-RTPC frame hook",
    )
    candidate = _replace_once(
        candidate,
        _HELPER_ANCHOR,
        _P95_HELPERS + _HELPER_ANCHOR,
        "P95 helpers",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P95 DEVICE 0002 ACK BEFORE RTPC ===",
            "P95_COMPOSES=P94",
            "P95_OFFICIAL_ORDER=DEVICE_0008_ACK_DEVICE_0002_ACK_RTPC",
            "P95_DEVICE_0002_GATE_REQUIRED=true",
            "P95_DEVICE_0002_TIMEOUT_SECONDS=3",
            "P95_DEVICE_0002_MATCH=CTPP_REQUEST_PREFIX_ACTION_FLAGS_CURRENT_ADDRESS_ROLES",
            "P95_DEVICE_0002_ACK_MAX_SENDS=1",
            "P95_DEVICE_0002_DUPLICATES_REACKED=false",
            "P95_DEVICE_0002_ACK_SEQUENCE_SOURCE=RUNTIME_PREVIOUS_ACK_PLUS_CAPTURE_VALIDATED_DELTA",
            "P95_CAPTURE_SEQUENCE_VALUES_USED_AS_CONSTANTS=false",
            "P95_CAPTURE_ADDRESSES_USED_AS_CONSTANTS=false",
            "P95_RAW_PAYLOAD_EMITTED=false",
            "P95_AUTOMATIC_RETRY=false",
            "P95_SECOND_CTPP_OPEN=false",
            "P95_DOOR_ACTION_SENT=false",
            "P95_P92_DEVICE_000A_GATE_PRESERVED=true",
            "P95_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P95_MEDIA_HARD_LIMIT_SECONDS=180",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P95 DEVICE 0002 ACK BEFORE RTPC ===",
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
    print("P95_TRANSFORM=PASS")
    print("P95_DEVICE_0002_GATE_REQUIRED=true")
    print("P95_DEVICE_0002_TIMEOUT_SECONDS=3")
    print("P95_DEVICE_0002_ACK_MAX_SENDS=1")
    print("P95_P92_DEVICE_000A_GATE_PRESERVED=true")
    print("P95_RAW_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
