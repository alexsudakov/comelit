#!/usr/bin/env python3
"""P122: Entrance Door on the active on-demand/self-activation media CTPP.

This overlay composes the currently shipped P121 production media lineage and
adds one Entrance-only one-shot Door surface to the already-running
`comelit-media` helper.  It intentionally does not touch the persistent
listener R66 path.

Wire profile follows the same PCAP-derived Android active-video Door contract
used by R66: one 48-byte 0x1840/0x000D frame on the existing CTPP, relay 1,
with no second P2P/CTPP bootstrap and no automatic retry.

The legacy persistent-listener Door/Gate paths remain outside this media helper.
Gate is not promoted.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p121_gather_initial_timeout_transform as p121
from entrance_p119_remote_sdp_l1_gather_diag_transform import DEFAULT_SOURCE

BEGIN = "/* P122_ONDEMAND_MEDIA_DOOR_BEGIN */"
END = "/* P122_ONDEMAND_MEDIA_DOOR_END */"

_ENUM_OLD = """    P78_TX_RTPC_CLIENT_001A,
    R27_TX_RTPC_CLIENT_001A_REPEAT,

    P95_TX_DEVICE_0002_ACK,
"""
_ENUM_NEW = """    P78_TX_RTPC_CLIENT_001A,
    R27_TX_RTPC_CLIENT_001A_REPEAT,
    P122_TX_ONDEMAND_DOOR,

    P95_TX_DEVICE_0002_ACK,
"""

_STATE_ANCHOR = """/* P100: P99 pre-active demux state is defined with the earlier P80 RTP state. */
"""

_STATE = r'''/* P122_ONDEMAND_MEDIA_DOOR_BEGIN */
#define P122_DOOR_PACKET_LEN 48u
#define P122_DOOR_RELAY_ENTRANCE 1u
#define P122_DOOR_SETTLE_MS 1000u

static volatile sig_atomic_t p122_door_signal_pending = 0;
static gboolean p122_door_inflight = FALSE;
static gboolean p122_door_sent = FALSE;
static gboolean p122_door_waiting_ack = FALSE;
static gboolean p122_door_ack_observed = FALSE;
static gboolean p122_door_relay_event_observed = FALSE;
static guint32 p122_door_sequence = 0u;
static guint32 p122_door_pending_sequence = 0u;

static gboolean p122_door_tick_cb(gpointer data);
static gboolean p122_door_settle_cb(gpointer data);

/* P122 is inserted before the legacy P12 helper definitions. */
static gboolean p12_queue_vip_frame(
    guint32 request_id,
    const guint8 *body,
    guint body_len,
    P12TxKind kind);
static gboolean p12_flush_tx(void);

static guint16
p122_read_le16(const guint8 *p)
{
    return (guint16)p[0] | ((guint16)p[1] << 8);
}

static void
p122_write_le16(guint8 *p, guint16 value)
{
    p[0] = (guint8)(value & 0xffu);
    p[1] = (guint8)((value >> 8) & 0xffu);
}

static void
p122_write_le32(guint8 *p, guint32 value)
{
    p[0] = (guint8)(value & 0xffu);
    p[1] = (guint8)((value >> 8) & 0xffu);
    p[2] = (guint8)((value >> 16) & 0xffu);
    p[3] = (guint8)((value >> 24) & 0xffu);
}

static void
p122_write_be16(guint8 *p, guint16 value)
{
    p[0] = (guint8)((value >> 8) & 0xffu);
    p[1] = (guint8)(value & 0xffu);
}

static void
p122_door_signal_handler(int signum)
{
    if (signum == SIGUSR1)
        p122_door_signal_pending = 1;
}

static guint32
p122_latest_client_sequence(void)
{
    if (p122_door_sent)
        return p122_door_sequence;
    if (r27_repeat_001a_sent_count > 0u)
        return r27_repeat_001a_sequence;
    return r27_initial_001a_sequence;
}

static gboolean
p122_door_eligible(void)
{
    return entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA &&
        p80_media_forwarding_enabled &&
        p78_rtpc_stage == P78_RTPC_COMPLETE &&
        pseudo_tcp &&
        pseudotcp_open &&
        !pseudotcp_graceful_stop_started &&
        v4_ctpp_channel_id != 0u &&
        !p12_tx_pending &&
        !r27_repeat_outstanding &&
        !r27_refresh_fail_closed &&
        r27_initial_001a_sent_count == 1u &&
        !p122_door_inflight;
}

static gboolean
p122_serialize_door(guint8 out[P122_DOOR_PACKET_LEN])
{
    guint32 previous_sequence;

    if (!out || !p122_door_eligible())
        return FALSE;

    previous_sequence = p122_latest_client_sequence();
    if (previous_sequence == 0u)
        return FALSE;

    p122_door_pending_sequence = previous_sequence + 0x00010000u;

    memset(out, 0, P122_DOOR_PACKET_LEN);
    p122_write_le16(out + 0, 0x1840u);
    p122_write_le32(out + 2, p122_door_pending_sequence);
    p122_write_be16(out + 6, 0x000du);
    p122_write_be16(out + 8, 0x002du);
    memcpy(out + 10, V4_ENTRANCE, 8u);
    p122_write_le32(out + 20, P122_DOOR_RELAY_ENTRANCE);
    memset(out + 24, 0xff, 4u);
    memcpy(out + 28, V4_FULL_ADDRESS, 9u);
    memcpy(out + 38, V4_APT_ADDRESS, 8u);

    return out[0] == 0x40u &&
        out[1] == 0x18u &&
        out[6] == 0x00u &&
        out[7] == 0x0du &&
        out[8] == 0x00u &&
        out[9] == 0x2du &&
        out[20] == 0x01u &&
        out[21] == 0x00u &&
        out[22] == 0x00u &&
        out[23] == 0x00u &&
        out[24] == 0xffu &&
        out[25] == 0xffu &&
        out[26] == 0xffu &&
        out[27] == 0xffu;
}

static void
p122_emit_result(const char *result)
{
    printf("P122_ONDEMAND_DOOR_ACK_OBSERVED=%s\n",
        p122_door_ack_observed ? "true" : "false");
    printf("P122_ONDEMAND_DOOR_RELAY_EVENT_OBSERVED=%s\n",
        p122_door_relay_event_observed ? "true" : "false");
    printf("P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    printf("P122_ONDEMAND_DOOR_RESULT=%s\n", result);
    fflush(stdout);
}

static gboolean
p122_queue_door(void)
{
    guint8 body[P122_DOOR_PACKET_LEN];
    gboolean queued;

    if (!p122_serialize_door(body))
        return FALSE;

    /*
     * Prevent the periodic 0x001A refresh timer from racing this one-shot.
     * Door is a terminal user action for this media transaction; after it,
     * device-side CALL_END/relay behavior owns what happens next.
     */
    r27_repeat_timer_cancelled = TRUE;

    queued = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P122_TX_ONDEMAND_DOOR);
    memset(body, 0, sizeof(body));
    if (!queued)
        return FALSE;

    p122_door_inflight = TRUE;
    printf("P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE\n");
    printf("P122_ONDEMAND_DOOR_COMMAND_ACCEPTED=true\n");
    printf("P122_ONDEMAND_DOOR_QUEUED=true\n");
    printf("P122_ONDEMAND_DOOR_EXISTING_CTPP_REUSED=true\n");
    printf("P122_ONDEMAND_DOOR_REFRESH_CANCELLED=true\n");
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
p122_door_settle_cb(gpointer data)
{
    (void)data;
    if (!p122_door_waiting_ack)
        return G_SOURCE_REMOVE;

    p122_door_waiting_ack = FALSE;
    p122_door_inflight = FALSE;
    p122_emit_result("UNKNOWN_OUTCOME");
    return G_SOURCE_REMOVE;
}

static gboolean
p122_note_control_frame(guint16 request_id, const guint8 *body, guint body_len)
{
    guint16 prefix;
    guint16 action;
    guint16 sub = 0u;

    if (!p122_door_waiting_ack ||
        request_id != v4_ctpp_channel_id ||
        !body ||
        body_len < 8u)
        return FALSE;

    prefix = p122_read_le16(body + 0);
    action = (guint16)((((guint16)body[6]) << 8) | (guint16)body[7]);

    if (prefix == 0x1800u && action == 0x0000u) {
        p122_door_ack_observed = TRUE;
        return TRUE;
    }

    if (body_len >= 10u &&
        prefix == 0x1840u &&
        action == 0x0003u) {
        sub = (guint16)((((guint16)body[8]) << 8) | (guint16)body[9]);
        if (sub == 0x000eu) {
            p122_door_relay_event_observed = TRUE;
            return TRUE;
        }
    }

    return FALSE;
}

static gboolean
p122_door_tick_cb(gpointer data)
{
    (void)data;

    if (!p122_door_signal_pending)
        return G_SOURCE_CONTINUE;

    p122_door_signal_pending = 0;

    if (!p122_door_eligible()) {
        printf("P122_ONDEMAND_DOOR_COMMAND_ACCEPTED=false\n");
        p122_emit_result("REJECTED_NOT_READY");
        return G_SOURCE_CONTINUE;
    }

    p122_door_ack_observed = FALSE;
    p122_door_relay_event_observed = FALSE;
    printf("P122_ONDEMAND_DOOR_SEQUENCE_BEFORE=%u\n",
        (unsigned)p122_latest_client_sequence());

    if (!p122_queue_door()) {
        p122_door_inflight = FALSE;
        p122_emit_result("FAILED_SAFE");
    }

    return G_SOURCE_CONTINUE;
}
/* P122_ONDEMAND_MEDIA_DOOR_END */
'''

_TX_CASE_ANCHOR = """        case P12_TX_V4_DOOR_WRITE:
"""
_TX_CASE = r'''        case P122_TX_ONDEMAND_DOOR:
            p122_door_sequence = p122_door_pending_sequence;
            p122_door_sent = TRUE;
            p122_door_waiting_ack = TRUE;
            printf("P122_ONDEMAND_DOOR_SENT=true\n");
            printf("P122_ONDEMAND_DOOR_WRITE_COUNT=1\n");
            printf("P122_ONDEMAND_DOOR_COUNTER_COMMITTED=true\n");
            printf("P122_ONDEMAND_DOOR_SEQUENCE_AFTER=%u\n",
                (unsigned)p122_door_sequence);
            fflush(stdout);
            if (g_timeout_add(P122_DOOR_SETTLE_MS, p122_door_settle_cb, NULL) == 0u) {
                p122_door_waiting_ack = FALSE;
                p122_door_inflight = FALSE;
                p122_emit_result("UNKNOWN_OUTCOME");
            }
            break;

'''

_ACK_OLD = """        } else if (r27_repeat_outstanding) {
            if (r27_handle_repeat_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
"""
_ACK_NEW = """        } else if (p122_door_waiting_ack) {
            if (p122_note_control_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (r27_repeat_outstanding) {
            if (r27_handle_repeat_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
"""

_SIGNAL_OLD = """    printf("R27_STDOUT_LINE_BUFFERED=true\\n");
    fflush(stdout);
"""
_SIGNAL_NEW = """    printf("R27_STDOUT_LINE_BUFFERED=true\\n");
    fflush(stdout);
    signal(SIGUSR1, p122_door_signal_handler);
    printf("P122_ONDEMAND_DOOR_SIGNAL_INSTALLED=true\\n");
    fflush(stdout);
    if (g_timeout_add(100u, p122_door_tick_cb, NULL) == 0u) {
        fprintf(stderr, "P122_ONDEMAND_DOOR_TIMER_START=FAIL\\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }
"""

_MEDIA_MARKER_OLD = '    printf("P80_DOOR_SIGNAL_ENTRYPOINT=false\\n");\n'
_MEDIA_MARKER_NEW = (
    '    printf("P80_DOOR_SIGNAL_ENTRYPOINT=true\\n");\n'
    '    printf("P122_ONDEMAND_DOOR_PROFILE=ACTIVE_MEDIA_SINGLE\\n");\n'
)

def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"P122_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = p121.transform(source)
    if BEGIN in candidate:
        raise RuntimeError("P122_REAPPLY_GATE=FAIL")

    candidate = _replace_once(candidate, _ENUM_OLD, _ENUM_NEW, "ENUM")
    candidate = _replace_once(
        candidate,
        _STATE_ANCHOR,
        _STATE + "\n" + _STATE_ANCHOR,
        "STATE",
    )
    candidate = _replace_once(
        candidate,
        _TX_CASE_ANCHOR,
        _TX_CASE + _TX_CASE_ANCHOR,
        "TX_CASE",
    )
    candidate = _replace_once(candidate, _ACK_OLD, _ACK_NEW, "ACK")
    candidate = _replace_once(candidate, _SIGNAL_OLD, _SIGNAL_NEW, "SIGNAL")
    candidate = _replace_once(
        candidate,
        _MEDIA_MARKER_OLD,
        _MEDIA_MARKER_NEW,
        "MEDIA_MARKER",
    )

    required = (
        BEGIN,
        END,
        "P122_TX_ONDEMAND_DOOR",
        "P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE",
        "P122_ONDEMAND_DOOR_WRITE_COUNT=1",
        "P122_ONDEMAND_DOOR_RESULT=%s",
        "signal(SIGUSR1, p122_door_signal_handler);",
        "P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
        "P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
    )
    for marker in required:
        if marker not in candidate:
            raise RuntimeError(f"P122_FINAL_GATE=FAIL missing={marker}")

    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for forbidden in (
        "P12_TX_V4_OPEN_CTPP",
        "P12_TX_V4_OPEN_CSPB",
        "V4_DOOR_TARGET_GATE",
        "v4_door_queue_write",
    ):
        if forbidden in region:
            raise RuntimeError(f"P122_ISOLATION_GATE=FAIL forbidden={forbidden}")

    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P122 ON-DEMAND MEDIA DOOR ===",
            "P122_COMPOSES=P121_PRODUCTION_MEDIA",
            "P122_PROFILE=ACTIVE_MEDIA_SINGLE_0x1840_0x000D",
            "P122_TARGET=ENTRANCE_ONLY",
            "P122_RELAY_INDEX=1",
            "P122_PACKET_LEN=48",
            "P122_EXISTING_CTPP_REUSED=true",
            "P122_SECOND_CTPP_OPEN=false",
            "P122_SECOND_P2P_SESSION=false",
            "P122_AUTOMATIC_RETRY=false",
            "P122_GATE_PROFILE_PROMOTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "=== END COMELIT P122 ON-DEMAND MEDIA DOOR ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    generated = transform(source_path.read_text(encoding="utf-8"))

    if args.sha256:
        print(hashlib.sha256(generated.encode("utf-8")).hexdigest())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report or --sha256 is used")

    args.output.write_text(generated, encoding="utf-8")
    print("P122_ONDEMAND_MEDIA_DOOR_TRANSFORM=PASS")
    print(
        "P122_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(generated.encode("utf-8")).hexdigest()
    )
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
