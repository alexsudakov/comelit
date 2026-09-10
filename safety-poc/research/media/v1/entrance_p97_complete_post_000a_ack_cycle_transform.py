#!/usr/bin/env python3
"""P97: complete the capture-proven ACK cycle after device 0x000A.

The frozen official self-activation timeline proves this order after RTPC OPEN:

    client 0x000A
    -> device 0x000A
    -> client structural ACK for device 0x000A
    -> device structural ACK for client 0x000A
    -> client 0x001A
    -> device structural ACK for client 0x001A
    -> media

P96 live/HA evidence proved the generated exchange through device 0x000A and
client 0x001A, but the runtime skipped the three structural ACK transitions and
marked media active immediately after local 0x001A TX completion.  No offset-8
RTP followed.

This overlay composes P96 and restores only those observed transitions.  The
client ACK body is generated from live device-0x000A address roles and the
capture-proven client sequence delta.  The already-generated 0x001A body keeps
all allocator/geometry/address fields but its sequence is rebound immediately
before transmission to the capture-proven nearest-previous-client rule: client
ACK sequence + 0x00010000.  Media is not declared active until the structural
device ACK for client 0x001A is observed.

No captured sequence value, address, target id, raw payload, second CTPP OPEN,
automatic retry, or Door path is introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p96_device_000a_peer_target_transform import (
    DEFAULT_SOURCE,
    transform as add_p96_runtime,
)


_TX_ENUM_OLD = """    P78_TX_RTPC_CLIENT_000A,
    P78_TX_RTPC_CLIENT_001A,

    P95_TX_DEVICE_0002_ACK,

    P12_TX_V4_DOOR_WRITE
"""

_TX_ENUM_NEW = """    P78_TX_RTPC_CLIENT_000A,
    P78_TX_RTPC_CLIENT_001A,

    P95_TX_DEVICE_0002_ACK,
    P97_TX_DEVICE_000A_ACK,

    P12_TX_V4_DOOR_WRITE
"""

_STATE_OLD = """static guint p95_device_0002_rx_count = 0;
"""

_STATE_NEW = """static guint p95_device_0002_rx_count = 0;

/* P97 post-000A ACK-cycle state. */
static gboolean p97_device_000a_roles_stored = FALSE;
static guint8 p97_device_000a_first_role[9];
static guint8 p97_device_000a_second_role[9];
static gboolean p97_client_ack_000a_queued = FALSE;
static gboolean p97_client_ack_000a_sent = FALSE;
static guint32 p97_client_ack_000a_sequence = 0;
static gboolean p97_wait_device_ack_000a = FALSE;
static gboolean p97_device_ack_000a_observed = FALSE;
static gboolean p97_client_001a_started = FALSE;
static gboolean p97_wait_device_ack_001a = FALSE;
static gboolean p97_device_ack_001a_observed = FALSE;
static gboolean p97_signaling_finished = FALSE;

static gboolean p97_store_device_000a_roles(const guint8 *body, guint body_len);
static gboolean p97_queue_device_000a_ack(void);
static gboolean p97_queue_client_001a_after_ack(void);
static gboolean p97_handle_device_ack(guint16 request_id, const guint8 *body, guint body_len);
static gboolean p97_finish_after_device_ack_001a(void);
"""

_CLIENT_000A_COMPLETION_OLD = r'''        case P78_TX_RTPC_CLIENT_000A:
            p78_rtpc_client_000a_sent = TRUE;
            printf("P78_RTPC_CLIENT_000A_SENT=PASS\n");
            fflush(stdout);
            if (p92_device_000a_observed) {
                printf("P92_DEVICE_000A_GATE=PASS\n");
                fflush(stdout);
                (void)p78_queue_rtpc_client_001a();
            } else {
                printf("P92_WAIT_DEVICE_000A=true\n");
                fflush(stdout);
            }
            break;'''

_CLIENT_000A_COMPLETION_NEW = r'''        case P78_TX_RTPC_CLIENT_000A:
            p78_rtpc_client_000a_sent = TRUE;
            printf("P78_RTPC_CLIENT_000A_SENT=PASS\n");
            fflush(stdout);
            if (p92_device_000a_observed) {
                printf("P92_DEVICE_000A_GATE=PASS\n");
                fflush(stdout);
                (void)p97_queue_device_000a_ack();
            } else {
                printf("P92_WAIT_DEVICE_000A=true\n");
                fflush(stdout);
            }
            break;'''

_TX_COMPLETION_INSERT_ANCHOR = """        case P78_TX_RTPC_OPEN_1:
"""

_TX_COMPLETION_INSERT = r'''        case P97_TX_DEVICE_000A_ACK:
            p97_client_ack_000a_sent = TRUE;
            printf("P80_DEVICE_000A_ACK_SENT=PASS\n");
            printf("P80_DEVICE_000A_ACK_SEQUENCE_EMITTED=false\n");
            fflush(stdout);

            if (p97_device_ack_000a_observed) {
                (void)p97_queue_client_001a_after_ack();
            } else {
                printf("P80_WAIT_DEVICE_ACK_000A=true\n");
                fflush(stdout);
            }
            break;

'''

_CLIENT_001A_COMPLETION_OLD = r'''        case P78_TX_RTPC_CLIENT_001A:
            p78_rtpc_client_001a_sent = TRUE;
            p78_rtpc_stage = P78_RTPC_COMPLETE;
            printf("P78_RTPC_CLIENT_001A_SENT=PASS\n");
            printf("P78_RTPC_SIGNALING_RESULT=PASS\n");
            fflush(stdout);

            if (!entrance_signal_begin_media_observation()) {
                p78_fail_rtpc("P78_MEDIA_OBSERVATION_START=FAIL");
            }
            break;'''

_CLIENT_001A_COMPLETION_NEW = r'''        case P78_TX_RTPC_CLIENT_001A:
            p78_rtpc_client_001a_sent = TRUE;
            printf("P78_RTPC_CLIENT_001A_SENT=PASS\n");
            fflush(stdout);

            if (p97_device_ack_001a_observed) {
                (void)p97_finish_after_device_ack_001a();
            } else {
                printf("P80_WAIT_DEVICE_ACK_001A=true\n");
                fflush(stdout);
            }
            break;'''

_FRAME_HOOK_OLD = """        } else if (p92_wait_device_000a) {
            if (p92_handle_device_000a(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""

_FRAME_HOOK_NEW = """        } else if (p92_wait_device_000a) {
            if (p92_handle_device_000a(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
            if (p97_handle_device_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""

_DEVICE_000A_STORE_OLD = """    p92_device_000a_observed = TRUE;
    p92_wait_device_000a = FALSE;
"""

_DEVICE_000A_STORE_NEW = """    if (!p97_store_device_000a_roles(body, body_len)) {
        p78_fail_rtpc("P80_DEVICE_000A_ROLE_CAPTURE=FAIL");
        return TRUE;
    }

    p92_device_000a_observed = TRUE;
    p92_wait_device_000a = FALSE;
"""

_DEVICE_000A_HANDLE_TAIL_OLD = r'''    printf("P92_DEVICE_000A_GATE=PASS\n");
    fflush(stdout);
    (void)p78_queue_rtpc_client_001a();
    return TRUE;
}'''

_DEVICE_000A_HANDLE_TAIL_NEW = r'''    printf("P92_DEVICE_000A_GATE=PASS\n");
    fflush(stdout);
    (void)p97_queue_device_000a_ack();
    return TRUE;
}'''

_HELPER_ANCHOR = "static gboolean\np92_device_000a_is_valid(guint16 request_id, const guint8 *body, guint body_len)\n{"

_P97_HELPERS = r'''#define P97_ACK_TIMEOUT_SECONDS 3
#define P97_CLIENT_ACK_000A_SEQUENCE_DELTA 0x01000000u
#define P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u

static gboolean
p97_ack_000a_timeout_cb(gpointer data)
{
    (void)data;
    if (!p97_wait_device_ack_000a || p97_device_ack_000a_observed)
        return G_SOURCE_REMOVE;
    p97_wait_device_ack_000a = FALSE;
    p78_fail_rtpc("P80_DEVICE_ACK_000A_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}

static gboolean
p97_ack_001a_timeout_cb(gpointer data)
{
    (void)data;
    if (!p97_wait_device_ack_001a || p97_device_ack_001a_observed)
        return G_SOURCE_REMOVE;
    p97_wait_device_ack_001a = FALSE;
    p78_fail_rtpc("P80_DEVICE_ACK_001A_TIMEOUT=true");
    return G_SOURCE_REMOVE;
}

static gboolean
p97_store_device_000a_roles(const guint8 *body, guint body_len)
{
    if (!body || body_len != 44u || body[33] != 0x00u || body[43] != 0x00u)
        return FALSE;

    memcpy(p97_device_000a_first_role, body + 24u, 9u);
    memcpy(p97_device_000a_second_role, body + 34u, 9u);
    p97_device_000a_roles_stored = TRUE;
    return TRUE;
}

static gboolean
p97_ack_matches_source(const guint8 *body, guint body_len,
                       const guint8 *source, guint source_len)
{
    guint first;
    guint second;

    if (!body || !source || body_len != 32u || source_len < 20u)
        return FALSE;
    if (read_le16(body + 0u) != 0x1800u ||
        body[6] != 0x00u || body[7] != 0x00u ||
        body[8] != 0xffu || body[9] != 0xffu ||
        body[10] != 0xffu || body[11] != 0xffu)
        return FALSE;

    first = source_len - 20u;
    second = source_len - 10u;
    if (source[first + 9u] != 0x00u || source[second + 9u] != 0x00u)
        return FALSE;

    return
        memcmp(body + 12u, source + second, 9u) == 0 &&
        body[21] == 0x00u &&
        memcmp(body + 22u, source + first, 9u) == 0 &&
        body[31] == 0x00u;
}

static gboolean
p97_queue_device_000a_ack(void)
{
    guint8 body[32];
    gboolean ok;

    if (p97_client_ack_000a_queued || p97_client_ack_000a_sent)
        return TRUE;

    if (!p92_device_000a_observed || !p78_rtpc_client_000a_sent ||
        !p97_device_000a_roles_stored || !pseudo_tcp || !pseudotcp_open ||
        v4_ctpp_channel_id == 0 || p12_tx_pending ||
        pseudotcp_graceful_stop_started) {
        p78_fail_rtpc("P80_DEVICE_000A_ACK_PRECONDITION=FAIL");
        return FALSE;
    }

    memset(body, 0, sizeof(body));
    write_le16(body + 0u, 0x1800u);
    p97_client_ack_000a_sequence =
        read_le32(p78_rtpc_client_000a + 2u) +
        P97_CLIENT_ACK_000A_SEQUENCE_DELTA;
    write_le32(body + 2u, p97_client_ack_000a_sequence);
    body[6] = 0x00u;
    body[7] = 0x00u;
    memset(body + 8u, 0xff, 4u);

    /* Generic structural ACK reverses the two address roles from the
     * device-originated frame. Values remain live-session-only. */
    memcpy(body + 12u, p97_device_000a_second_role, 9u);
    body[21] = 0x00u;
    memcpy(body + 22u, p97_device_000a_first_role, 9u);
    body[31] = 0x00u;

    p97_client_ack_000a_queued = TRUE;
    p97_wait_device_ack_000a = TRUE;
    p97_device_ack_000a_observed = FALSE;

    if (g_timeout_add_seconds(P97_ACK_TIMEOUT_SECONDS,
                              p97_ack_000a_timeout_cb, NULL) == 0) {
        p78_fail_rtpc("P80_DEVICE_ACK_000A_TIMER_START=FAIL");
        memset(body, 0, sizeof(body));
        return FALSE;
    }

    ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P97_TX_DEVICE_000A_ACK
    );
    memset(body, 0, sizeof(body));

    if (!ok) {
        p78_fail_rtpc("P80_DEVICE_000A_ACK_QUEUE=FAIL");
        return FALSE;
    }

    printf("P80_DEVICE_000A_ACK_QUEUED=PASS\n");
    printf("P80_DEVICE_000A_ACK_SEQUENCE_RULE=PASS\n");
    printf("P80_DEVICE_ACK_000A_GATE_ARMED=true\n");
    fflush(stdout);

    if (!p12_flush_tx()) {
        p78_fail_rtpc("P80_DEVICE_000A_ACK_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p97_queue_client_001a_after_ack(void)
{
    if (p97_client_001a_started)
        return TRUE;

    if (!p97_client_ack_000a_sent || !p97_device_ack_000a_observed ||
        p78_rtpc_client_001a_len != 60u) {
        p78_fail_rtpc("P80_CLIENT_001A_POST_ACK_PRECONDITION=FAIL");
        return FALSE;
    }

    write_le32(
        p78_rtpc_client_001a + 2u,
        p97_client_ack_000a_sequence +
            P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK
    );

    p97_client_001a_started = TRUE;
    p97_wait_device_ack_001a = TRUE;
    p97_device_ack_001a_observed = FALSE;

    if (g_timeout_add_seconds(P97_ACK_TIMEOUT_SECONDS,
                              p97_ack_001a_timeout_cb, NULL) == 0) {
        p78_fail_rtpc("P80_DEVICE_ACK_001A_TIMER_START=FAIL");
        return FALSE;
    }

    printf("P80_CLIENT_001A_SEQUENCE_REBOUND=PASS\n");
    printf("P80_DEVICE_ACK_001A_GATE_ARMED=true\n");
    fflush(stdout);
    return p78_queue_rtpc_client_001a();
}

static gboolean
p97_finish_after_device_ack_001a(void)
{
    if (p97_signaling_finished)
        return TRUE;
    if (!p78_rtpc_client_001a_sent || !p97_device_ack_001a_observed) {
        p78_fail_rtpc("P80_POST_001A_ACK_PRECONDITION=FAIL");
        return FALSE;
    }

    p97_signaling_finished = TRUE;
    p78_rtpc_stage = P78_RTPC_COMPLETE;
    printf("P80_POST_001A_ACK_GATE=PASS\n");
    printf("P78_RTPC_SIGNALING_RESULT=PASS\n");
    fflush(stdout);

    if (!entrance_signal_begin_media_observation()) {
        p78_fail_rtpc("P78_MEDIA_OBSERVATION_START=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p97_handle_device_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (request_id != v4_ctpp_channel_id)
        return FALSE;

    if (p97_wait_device_ack_000a &&
        p97_ack_matches_source(body, body_len,
                               p78_rtpc_client_000a,
                               p78_rtpc_client_000a_len)) {
        p97_device_ack_000a_observed = TRUE;
        p97_wait_device_ack_000a = FALSE;
        printf("P80_DEVICE_ACK_000A_OBSERVED=PASS\n");
        fflush(stdout);

        if (p97_client_ack_000a_sent)
            (void)p97_queue_client_001a_after_ack();
        return TRUE;
    }

    if (p97_wait_device_ack_001a &&
        p97_ack_matches_source(body, body_len,
                               p78_rtpc_client_001a,
                               p78_rtpc_client_001a_len)) {
        p97_device_ack_001a_observed = TRUE;
        p97_wait_device_ack_001a = FALSE;
        printf("P80_DEVICE_ACK_001A_OBSERVED=PASS\n");
        fflush(stdout);

        if (p78_rtpc_client_001a_sent)
            (void)p97_finish_after_device_ack_001a();
        return TRUE;
    }

    return FALSE;
}

'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p96_runtime(source)
    candidate = _replace_once(candidate, _TX_ENUM_OLD, _TX_ENUM_NEW, "P97 tx enum")
    candidate = _replace_once(candidate, _STATE_OLD, _STATE_NEW, "P97 state")
    candidate = _replace_once(
        candidate,
        _CLIENT_000A_COMPLETION_OLD,
        _CLIENT_000A_COMPLETION_NEW,
        "P97 client 000A completion",
    )
    candidate = _replace_once(
        candidate,
        _TX_COMPLETION_INSERT_ANCHOR,
        _TX_COMPLETION_INSERT + _TX_COMPLETION_INSERT_ANCHOR,
        "P97 device 000A ACK completion",
    )
    candidate = _replace_once(
        candidate,
        _CLIENT_001A_COMPLETION_OLD,
        _CLIENT_001A_COMPLETION_NEW,
        "P97 client 001A completion",
    )
    candidate = _replace_once(candidate, _FRAME_HOOK_OLD, _FRAME_HOOK_NEW, "P97 ACK frame hook")
    candidate = _replace_once(
        candidate,
        _DEVICE_000A_STORE_OLD,
        _DEVICE_000A_STORE_NEW,
        "P97 device 000A live roles",
    )
    candidate = _replace_once(
        candidate,
        _DEVICE_000A_HANDLE_TAIL_OLD,
        _DEVICE_000A_HANDLE_TAIL_NEW,
        "P97 device 000A gate transition",
    )
    candidate = _replace_once(
        candidate,
        _HELPER_ANCHOR,
        _P97_HELPERS + _HELPER_ANCHOR,
        "P97 helpers",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P97 POST-000A ACK CYCLE ===",
            "P97_COMPOSES=P96",
            "P97_OFFICIAL_ORDER=000A_DEVICE_ACK_CLIENT_ACK_000A_001A_DEVICE_ACK",
            "P97_CLIENT_ACK_000A_REQUIRED=true",
            "P97_DEVICE_ACK_000A_REQUIRED=true",
            "P97_DEVICE_ACK_001A_REQUIRED=true",
            "P97_MEDIA_ACTIVE_AFTER_DEVICE_ACK_001A=true",
            "P97_CLIENT_ACK_000A_SEQUENCE_DELTA=0x01000000",
            "P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK=0x00010000",
            "P97_ACK_ADDRESS_SOURCE=LIVE_DEVICE_FRAME",
            "P97_CAPTURE_SEQUENCE_VALUES_REPLAYED=false",
            "P97_CAPTURE_ADDRESS_VALUES_REPLAYED=false",
            "P97_AUTOMATIC_RETRY=false",
            "P97_SECOND_CTPP_OPEN=false",
            "P97_DOOR_ACTION_SENT=false",
            "P97_RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P97 POST-000A ACK CYCLE ===",
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
    print("P97_TRANSFORM=PASS")
    print("P97_POST_000A_ACK_CYCLE_REQUIRED=true")
    print("P97_MEDIA_ACTIVE_AFTER_DEVICE_ACK_001A=true")
    print("P97_CAPTURE_SEQUENCE_VALUES_REPLAYED=false")
    print("P97_AUTOMATIC_RETRY=false")
    print("P97_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
