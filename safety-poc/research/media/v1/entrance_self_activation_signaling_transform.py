#!/usr/bin/env python3
"""Generate a one-shot entrance self-activation signaling research candidate.

This transform starts from the frozen v1.5.7 HAOS source, applies the already
reviewed early-PseudoTCP datagram replay transform, removes the reachable Door
signal/timer surface, and adds one bounded capture-derived entrance signaling
sequence:

    registered CTPP
      -> 0x0028 self-activation
      -> structural ACK
      -> 0x0008 client video event
      -> structural ACK
      -> 0x0008 device video event
      -> PASS + graceful PseudoTCP close

It deliberately stops at the device video event.  It does not acknowledge that
final event, does not inspect/capture RTP or H264 bytes, and does not expose any
Home Assistant camera entity.  The capture-derived sequence/timestamp fields
which are session state are regenerated; protocol structure and address roles
are preserved from the frozen primary capture.

The transform itself performs no network I/O.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pseudotcp_prestart_replay_transform import transform as add_prestart_replay


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    source = add_prestart_replay(source)

    tx_anchor = """    P12_TX_V4_PEER_ECHO_CLOSE_ACK,

    P12_TX_V4_DOOR_WRITE
} P12TxKind;
"""
    tx_replacement = """    P12_TX_V4_PEER_ECHO_CLOSE_ACK,

    P12_TX_ENTRANCE_SELF_ACTIVATION,
    P12_TX_ENTRANCE_VIDEO_EVENT,

    P12_TX_V4_DOOR_WRITE
} P12TxKind;
"""
    source = _replace_once(source, tx_anchor, tx_replacement, "media tx kinds")

    state_anchor = """static gboolean v4_registered = FALSE;
static gboolean v4_listener_ready = FALSE;

static gboolean v4_ring_observed = FALSE;
"""
    state_replacement = """static gboolean v4_registered = FALSE;
static gboolean v4_listener_ready = FALSE;

/* Research-only, one-shot entrance signaling state. */
typedef enum {
    ENTRANCE_SIGNAL_IDLE = 0,
    ENTRANCE_SIGNAL_WAIT_SETTLE,
    ENTRANCE_SIGNAL_SELF_TX,
    ENTRANCE_SIGNAL_WAIT_SELF_ACK,
    ENTRANCE_SIGNAL_VIDEO_TX,
    ENTRANCE_SIGNAL_WAIT_VIDEO_ACK,
    ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO,
    ENTRANCE_SIGNAL_DONE
} EntranceSignalStage;

#define ENTRANCE_SIGNAL_SETTLE_MS 4000
#define ENTRANCE_SIGNAL_TIMEOUT_MS 20000

static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;
static gboolean entrance_video_event_sent = FALSE;
static gboolean entrance_signaling_result = FALSE;

static gboolean v4_ring_observed = FALSE;
"""
    source = _replace_once(source, state_anchor, state_replacement, "media state")

    helper_anchor = """static void
p12_tx_completed(P12TxKind kind)
{
"""
    helpers = r'''static gboolean
entrance_signal_body_is_ack(const guint8 *body, guint body_len)
{
    return
        body &&
        body_len == 32 &&
        read_le16(body + 0) == 0x1800 &&
        body[6] == 0x00 && body[7] == 0x00 &&
        body[8] == 0xff && body[9] == 0xff &&
        body[10] == 0xff && body[11] == 0xff &&
        memcmp(body + 12, V4_ENTRANCE, 8) == 0 &&
        body[20] == 0x00 && body[21] == 0x00 &&
        memcmp(body + 22, V4_FULL_ADDRESS, 9) == 0 &&
        body[31] == 0x00;
}


static gboolean
entrance_signal_body_is_device_video(const guint8 *body, guint body_len)
{
    return
        body &&
        body_len == 40 &&
        read_le16(body + 0) == 0x1840 &&
        body[6] == 0x00 && body[7] == 0x08 &&
        body[8] == 0x00 && body[9] == 0x03 &&
        body[16] == 0xff && body[17] == 0xff &&
        body[18] == 0xff && body[19] == 0xff &&
        memcmp(body + 20, V4_ENTRANCE, 8) == 0 &&
        body[28] == 0x00 && body[29] == 0x00 &&
        memcmp(body + 30, V4_FULL_ADDRESS, 9) == 0 &&
        body[39] == 0x00;
}


static gboolean
entrance_signal_queue_self_activation(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_SETTLE ||
        entrance_self_activation_sent ||
        !pseudotcp_open ||
        !v4_registered ||
        v4_ctpp_channel_id == 0 ||
        p12_tx_pending) {

        fprintf(stderr, "ENTRANCE_SELF_ACTIVATION_PRECONDITION=FAIL\n");
        return FALSE;
    }

    guint8 body[72];
    memset(body, 0, sizeof(body));

    entrance_signal_sequence = g_random_int();

    write_le16(body + 0, 0x18C0);
    write_le32(body + 2, entrance_signal_sequence);
    body[6] = 0x00;
    body[7] = 0x28;
    body[8] = 0x00;
    body[9] = 0x01;

    memcpy(body + 10, V4_FULL_ADDRESS, 9);
    body[19] = 0x00;
    memcpy(body + 20, V4_ENTRANCE, 8);
    body[28] = 0x00;
    body[29] = 0x00;

    /* Capture-frozen constant fields between the address groups. */
    body[30] = 0x01;
    body[31] = 0x20;
    body[32] = 0x05;
    body[33] = 0x80;
    body[34] = 0x31;
    body[35] = 0x18;

    memcpy(body + 36, V4_FULL_ADDRESS, 9);
    body[45] = 0x00;
    body[46] = 0x49;
    body[47] = 0x49;
    memset(body + 48, 0xff, 4);
    memcpy(body + 52, V4_FULL_ADDRESS, 9);
    body[61] = 0x00;
    memcpy(body + 62, V4_ENTRANCE, 8);
    body[70] = 0x00;
    body[71] = 0x00;

    entrance_signal_stage = ENTRANCE_SIGNAL_SELF_TX;

    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P12_TX_ENTRANCE_SELF_ACTIVATION
    );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    printf("ENTRANCE_SELF_ACTIVATION_BODY_LEN=72\n");
    printf("ENTRANCE_SELF_ACTIVATION_PREFIX=0x18C0\n");
    printf("ENTRANCE_SELF_ACTIVATION_ACTION=0x0028\n");
    printf("ENTRANCE_SELF_ACTIVATION_FLAGS=0x0001\n");
    printf("ENTRANCE_SELF_ACTIVATION_CTPP_REUSED=true\n");
    printf("ENTRANCE_SELF_ACTIVATION_SEQUENCE_EMITTED=false\n");
    fflush(stdout);

    return p12_flush_tx();
}


static gboolean
entrance_signal_queue_video_event(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_SELF_ACK ||
        !entrance_self_activation_sent ||
        entrance_video_event_sent ||
        !pseudotcp_open ||
        v4_ctpp_channel_id == 0 ||
        p12_tx_pending) {

        fprintf(stderr, "ENTRANCE_VIDEO_EVENT_PRECONDITION=FAIL\n");
        return FALSE;
    }

    guint8 body[40];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0x1840);
    write_le32(body + 2, entrance_signal_sequence + 0x00010000u);
    body[6] = 0x00;
    body[7] = 0x08;
    body[8] = 0x00;
    body[9] = 0x03;

    /* Capture-frozen client video-event constant fields. */
    body[10] = 0x49;
    body[11] = 0x00;
    body[12] = 0x27;
    body[13] = 0x00;
    body[14] = 0x00;
    body[15] = 0x00;
    memset(body + 16, 0xff, 4);
    memcpy(body + 20, V4_FULL_ADDRESS, 9);
    body[29] = 0x00;
    memcpy(body + 30, V4_ENTRANCE, 8);
    body[38] = 0x00;
    body[39] = 0x00;

    entrance_signal_stage = ENTRANCE_SIGNAL_VIDEO_TX;

    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P12_TX_ENTRANCE_VIDEO_EVENT
    );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    printf("ENTRANCE_VIDEO_EVENT_BODY_LEN=40\n");
    printf("ENTRANCE_VIDEO_EVENT_PREFIX=0x1840\n");
    printf("ENTRANCE_VIDEO_EVENT_ACTION=0x0008\n");
    printf("ENTRANCE_VIDEO_EVENT_FLAGS=0x0003\n");
    printf("ENTRANCE_VIDEO_EVENT_SEQUENCE_EMITTED=false\n");
    fflush(stdout);

    return p12_flush_tx();
}


static gboolean
entrance_signal_finish_success(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_SIGNALING_FINISH_PRECONDITION=FAIL\n");
        return FALSE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
    entrance_signaling_result = TRUE;
    failed = FALSE;

    printf("ENTRANCE_DEVICE_VIDEO_EVENT=PASS\n");
    printf("ENTRANCE_SIGNALING_PROBE_RESULT=PASS\n");
    printf("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false\n");
    printf("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false\n");
    printf("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false\n");
    printf("ENTRANCE_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    pseudotcp_graceful_stop_started = TRUE;
    guint drained = pseudotcp_drain_before_graceful_close();
    printf("PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u\n", drained);

    pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    printf("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\n");

    pseudotcp_graceful_stop_deadline_us =
        g_get_monotonic_time() +
        ((gint64)PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS * 1000);

    if (g_timeout_add(
            PSEUDOTCP_GRACEFUL_STOP_POLL_MS,
            pseudotcp_graceful_stop_poll_cb,
            NULL) == 0) {

        fprintf(stderr, "PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=FAIL\n");
        return FALSE;
    }

    printf("PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=PASS\n");
    fflush(stdout);
    return TRUE;
}


static gboolean
entrance_signal_start_cb(gpointer data)
{
    (void)data;

    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_SETTLE) {
        fprintf(stderr, "ENTRANCE_SIGNALING_SETTLE_STATE=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    printf("ENTRANCE_SIGNALING_SETTLE_COMPLETE=true\n");
    fflush(stdout);

    if (!entrance_signal_queue_self_activation()) {
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }

    return G_SOURCE_REMOVE;
}


static gboolean
entrance_signal_timeout_cb(gpointer data)
{
    (void)data;

    if (entrance_signal_stage == ENTRANCE_SIGNAL_DONE)
        return G_SOURCE_REMOVE;

    fprintf(
        stderr,
        "ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u\n",
        (unsigned)entrance_signal_stage
    );
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}


static void
p12_tx_completed(P12TxKind kind)
{
'''
    source = _replace_once(source, helper_anchor, helpers, "media helpers")

    tx_case_anchor = """        case P12_TX_V4_DOOR_WRITE:
"""
    tx_case_replacement = r'''        case P12_TX_ENTRANCE_SELF_ACTIVATION:
            entrance_self_activation_sent = TRUE;
            entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_SELF_ACK;
            printf("ENTRANCE_SELF_ACTIVATION_SENT=PASS\n");
            fflush(stdout);
            break;

        case P12_TX_ENTRANCE_VIDEO_EVENT:
            entrance_video_event_sent = TRUE;
            entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_VIDEO_ACK;
            printf("ENTRANCE_VIDEO_EVENT_SENT=PASS\n");
            fflush(stdout);
            break;

        case P12_TX_V4_DOOR_WRITE:
'''
    source = _replace_once(source, tx_case_anchor, tx_case_replacement, "media tx cases")

    registration_anchor = """            p12_stage =
                P12_STAGE_V4_LISTEN_RING;


            p12_deadline_us =
                0;


            break;
"""
    registration_replacement = r"""            p12_stage =
                P12_STAGE_V4_LISTEN_RING;


            p12_deadline_us =
                0;


            if (entrance_signal_stage == ENTRANCE_SIGNAL_IDLE) {
                entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_SETTLE;
                printf("ENTRANCE_SIGNALING_ARMED=true\n");
                printf("ENTRANCE_SIGNALING_WAIT_FOR_PSEUDOTCP_OPEN=true\n");
                printf("ENTRANCE_SIGNALING_CTPP_REUSE_REQUIRED=true\n");
                printf("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false\n");
                fflush(stdout);

                if (g_timeout_add(
                        ENTRANCE_SIGNAL_SETTLE_MS,
                        entrance_signal_start_cb,
                        NULL) == 0 ||
                    g_timeout_add(
                        ENTRANCE_SIGNAL_TIMEOUT_MS,
                        entrance_signal_timeout_cb,
                        NULL) == 0) {

                    fprintf(stderr, "ENTRANCE_SIGNALING_TIMER_START=FAIL\n");
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            }


            break;
"""
    source = _replace_once(
        source, registration_anchor, registration_replacement, "registration media arm"
    )

    parse_anchor = """        const guint8 *body =
            post_ack_capture + 8;




        /*
         * --------------------------------------------------------
         * V4 post-registration diagnostic
"""
    parse_replacement = r'''        const guint8 *body =
            post_ack_capture + 8;


        /* One-shot entrance self-activation signaling state machine. */
        if (entrance_signal_stage == ENTRANCE_SIGNAL_WAIT_SELF_ACK) {
            if (request_id == v4_ctpp_channel_id &&
                entrance_signal_body_is_ack(body, body_len)) {

                printf("ENTRANCE_SELF_ACTIVATION_ACK=PASS\n");
                fflush(stdout);
                p12_consume_post_ack(frame_len);

                if (!entrance_signal_queue_video_event())
                    return FALSE;

                continue;
            }
        } else if (entrance_signal_stage == ENTRANCE_SIGNAL_WAIT_VIDEO_ACK) {
            if (request_id == v4_ctpp_channel_id &&
                entrance_signal_body_is_ack(body, body_len)) {

                printf("ENTRANCE_VIDEO_EVENT_ACK=PASS\n");
                fflush(stdout);
                entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO;
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (entrance_signal_stage == ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO) {
            if (request_id == v4_ctpp_channel_id &&
                entrance_signal_body_is_device_video(body, body_len)) {

                p12_consume_post_ack(frame_len);
                return entrance_signal_finish_success();
            }
        }




        /*
         * --------------------------------------------------------
         * V4 post-registration diagnostic
'''
    source = _replace_once(source, parse_anchor, parse_replacement, "media rx state machine")

    closed_anchor = """    if (!pseudotcp_open) {
        fprintf(
            stderr,
            \"PSEUDOTCP_CLOSED_BEFORE_OPEN=true\\n\"
        );
    } else {
        fprintf(
            stderr,
            \"PSEUDOTCP_CLOSED_AFTER_OPEN=true\\n\"
        );
    }

    /*
     * A closed PseudoTCP transport cannot carry further
     * CTPP/ECHO traffic.  End this session so the HA
     * supervisor can establish a fresh P2P registration.
     */
    failed = TRUE;

    if (loop)
        g_main_loop_quit(loop);

    fflush(stdout);
"""
    closed_replacement = """    if (pseudotcp_graceful_stop_started &&
        entrance_signaling_result &&
        error == 0) {

        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_CALLBACK=PASS\\n\");
        failed = FALSE;
        if (loop)
            g_main_loop_quit(loop);
        fflush(stdout);
        return;
    }

    if (!pseudotcp_open) {
        fprintf(
            stderr,
            \"PSEUDOTCP_CLOSED_BEFORE_OPEN=true\\n\"
        );
    } else {
        fprintf(
            stderr,
            \"PSEUDOTCP_CLOSED_AFTER_OPEN=true\\n\"
        );
    }

    failed = TRUE;

    if (loop)
        g_main_loop_quit(loop);

    fflush(stdout);
"""
    source = _replace_once(source, closed_anchor, closed_replacement, "graceful media close")

    door_signal_anchor = """    signal(SIGUSR1, v4_door_signal_handler);

    g_timeout_add(
        100,
        stop_check_cb,
        NULL
    );

    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );
"""
    door_signal_replacement = """    printf(\"ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\\n\");
    printf(\"ENTRANCE_SIGNALING_DOOR_TIMER_INSTALLED=false\\n\");
    printf(\"ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false\\n\");
    fflush(stdout);

    g_timeout_add(
        100,
        stop_check_cb,
        NULL
    );
"""
    source = _replace_once(source, door_signal_anchor, door_signal_replacement, "disable Door surface")

    source = _replace_once(
        source,
        """    g_timeout_add_seconds(
        3300,
        absolute_timeout_cb,
        NULL
    );
""",
        """    g_timeout_add_seconds(
        45,
        absolute_timeout_cb,
        NULL
    );
""",
        "bounded absolute timeout",
    )

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("ENTRANCE_SIGNALING_TRANSFORM=PASS")
    print("PSEUDOTCP_EARLY_DATAGRAM_REPLAY=ENABLED")
    print("ENTRANCE_SELF_ACTIVATION_COUNT_MAX=1")
    print("ENTRANCE_CLIENT_VIDEO_EVENT_COUNT_MAX=1")
    print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false")
    print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())