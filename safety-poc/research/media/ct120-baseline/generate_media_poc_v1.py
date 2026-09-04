#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent / "ring" / "v4_3" / "comelit_ice_offer_holder.v4-persistent.c"
OUT = HERE / "comelit-v4-media-poc.c"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PATCH_{label}=FAIL count={count}")
    return text.replace(old, new, 1)


def main() -> int:
    src = BASE.read_text(encoding="utf-8")

    src = replace_once(
        src,
        '#define RUN_DIR     "/run/comelit-p2p"',
        '#define RUN_DIR     "/run/comelit-media-poc"',
        "RUN_DIR",
    )

    src = replace_once(
        src,
        """    P12_TX_V4_PEER_ECHO_REPLY,\n    P12_TX_V4_PEER_ECHO_CLOSE_ACK\n} P12TxKind;""",
        """    P12_TX_V4_PEER_ECHO_REPLY,\n    P12_TX_V4_PEER_ECHO_CLOSE_ACK,\n\n    P12_TX_V4_MEDIA_CALL_INIT,\n    P12_TX_V4_MEDIA_ACTION_0008,\n    P12_TX_V4_MEDIA_ACTION_000A_START,\n    P12_TX_V4_MEDIA_ACTION_001A_START,\n    P12_TX_V4_MEDIA_PEER_ACK,\n    P12_TX_V4_MEDIA_ACTION_000E_ACTIVE,\n    P12_TX_V4_MEDIA_ACTION_0003_STOP,\n    P12_TX_V4_MEDIA_ACTION_000A_STOP,\n    P12_TX_V4_MEDIA_ACTION_001A_STOP,\n    P12_TX_V4_MEDIA_ACTION_000E_FINAL\n} P12TxKind;""",
        "TX_ENUM",
    )

    globals_anchor = "static gboolean v4_ring_observed = FALSE;\n\n"
    globals_block = r'''static gboolean v4_ring_observed = FALSE;


/*
 * CT120-only media PoC state.
 *
 * Safety boundary: this source is generated from the no-Door v4_3
 * baseline.  It contains no Door command trigger, Door payload array,
 * or automatic Door retry surface.
 */
#define V4_MEDIA_OUTPUT_DIR "/root/comelit-media-poc-output"
#define V4_MEDIA_H264_FILE  V4_MEDIA_OUTPUT_DIR "/live.h264"
#define V4_MEDIA_TARGET     V4_ENTRANCE
#define V4_MEDIA_RTP_PT     99
#define V4_MEDIA_CAPTURE_USEC ((gint64)10 * G_USEC_PER_SEC)
#define V4_MEDIA_KEEPALIVE_USEC ((gint64)7500 * 1000)
#define V4_MEDIA_STAGE_TIMEOUT_USEC ((gint64)6 * G_USEC_PER_SEC)


typedef enum {
    V4_MEDIA_IDLE = 0,
    V4_MEDIA_WAIT_CALL_ACK,
    V4_MEDIA_WAIT_0008_ACK,
    V4_MEDIA_WAIT_PEER_0008,
    V4_MEDIA_WAIT_PEER_0002,
    V4_MEDIA_WAIT_000A_EXCHANGE,
    V4_MEDIA_WAIT_001A_ACK,
    V4_MEDIA_WAIT_FIRST_RTP,
    V4_MEDIA_ACTIVE,
    V4_MEDIA_WAIT_KEEPALIVE_ACK,
    V4_MEDIA_STOP_WAIT_0003_ACK,
    V4_MEDIA_STOP_WAIT_000A_ACK,
    V4_MEDIA_STOP_WAIT_001A_EXCHANGE,
    V4_MEDIA_STOP_WAIT_FINAL_000E_ACK,
    V4_MEDIA_DONE,
    V4_MEDIA_ERROR
} V4MediaStage;


typedef enum {
    V4_MEDIA_FRAME_NOT_CONSUMED = 0,
    V4_MEDIA_FRAME_CONSUMED,
    V4_MEDIA_FRAME_FAIL
} V4MediaFrameResult;


static V4MediaStage v4_media_stage = V4_MEDIA_IDLE;
static gboolean v4_media_start_requested = FALSE;
static gboolean v4_media_setup_started = FALSE;
static gboolean v4_media_active = FALSE;
static gboolean v4_media_keepalive_sent = FALSE;
static gboolean v4_media_teardown_requested = FALSE;
static gboolean v4_media_teardown_started = FALSE;
static gboolean v4_media_teardown_acked = FALSE;
static gboolean v4_media_seen_peer_000a_start = FALSE;
static gboolean v4_media_peer_000a_start_ack_sent = FALSE;
static gboolean v4_media_own_000a_start_acked = FALSE;
static gboolean v4_media_seen_peer_000a_stop = FALSE;
static gboolean v4_media_peer_000a_stop_ack_sent = FALSE;
static gboolean v4_media_own_001a_stop_acked = FALSE;
static gboolean v4_media_send_000a_after_peer_ack = FALSE;

static guint16 v4_media_audio_id = 0;
static guint16 v4_media_video_id = 0;

static guint8 v4_media_seq_base0 = 0;
static guint8 v4_media_seq_base1 = 0;
static guint8 v4_media_seq_local = 0;
static guint8 v4_media_seq_remote = 0;

static gboolean v4_media_waiting_own_ack = FALSE;
static guint8 v4_media_pending_local = 0;
static guint8 v4_media_pending_remote = 0;
static P12TxKind v4_media_pending_kind = P12_TX_NONE;

static gint64 v4_media_stage_deadline_us = 0;
static gint64 v4_media_active_started_us = 0;
static gint64 v4_media_force_exit_us = 0;

static FILE *v4_media_h264 = NULL;
static guint64 v4_media_h264_bytes = 0;
static guint64 v4_media_rtp_packets = 0;
static guint64 v4_media_rtp_sequence_gaps = 0;
static gboolean v4_media_have_last_rtp_seq = FALSE;
static guint16 v4_media_last_rtp_seq = 0;
static gboolean v4_media_fu_open = FALSE;
static gboolean v4_media_cleanup_done = FALSE;


static gboolean v4_media_try_handle_raw(const guint8 *buf, guint len);
static gboolean v4_media_tick_cb(gpointer data);
static gboolean v4_media_watchdog_cb(gpointer data);
static void v4_media_request_stop(const gchar *reason);
static void v4_media_cleanup_transport(void);

'''
    src = replace_once(src, globals_anchor, globals_block, "GLOBALS")

    recv_anchor = """    if (!pseudo_tcp) {\n"""
    recv_insert = """    /* Raw ViP media is multiplexed beside PseudoTCP on the same ICE component. */\n    if (v4_media_try_handle_raw((const guint8 *)buf, len))\n        return;\n\n    if (!pseudo_tcp) {\n"""
    src = replace_once(src, recv_anchor, recv_insert, "RECV_DEMUX")

    stop_old = r'''    if (g_file_test(STOP_FILE, G_FILE_TEST_EXISTS)) {
        printf("ICE_HOLDER_STOP=true\n");

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }
'''
    stop_new = r'''    if (g_file_test(STOP_FILE, G_FILE_TEST_EXISTS)) {
        printf("ICE_HOLDER_STOP=true\n");
        v4_media_request_stop("stop_file");
        return G_SOURCE_REMOVE;
    }
'''
    src = replace_once(src, stop_old, stop_new, "STOP_CB")

    media_impl_anchor = "\n\n\nstatic void\np12_tx_completed(P12TxKind kind)\n"
    media_impl = r'''


/* ------------------------------------------------------------------------- */
/* CT120 media PoC v1                                                       */
/* ------------------------------------------------------------------------- */

static void
v4_media_write_be16(guint8 *p, guint16 value)
{
    p[0] = (guint8)((value >> 8) & 0xff);
    p[1] = (guint8)(value & 0xff);
}


static void
v4_media_write_seq(guint8 *p)
{
    p[0] = v4_media_seq_base0;
    p[1] = v4_media_seq_base1;
    p[2] = v4_media_seq_local;
    p[3] = v4_media_seq_remote;
}


static guint
v4_media_write_address_tail(guint8 *p, guint remaining)
{
    if (remaining < 24)
        return 0;

    memset(p, 0xff, 4);
    memcpy(p + 4, V4_FULL_ADDRESS, 9);
    p[13] = 0;
    memcpy(p + 14, V4_MEDIA_TARGET, 8);
    p[22] = 0;
    p[23] = 0;
    return 24;
}


static gboolean
v4_media_prepare_output(void)
{
    if (v4_media_h264)
        return TRUE;

    if (g_mkdir_with_parents(V4_MEDIA_OUTPUT_DIR, 0700) != 0) {
        perror("media-output-mkdir");
        return FALSE;
    }

    chmod(V4_MEDIA_OUTPUT_DIR, 0700);
    unlink(V4_MEDIA_H264_FILE);

    v4_media_h264 = fopen(V4_MEDIA_H264_FILE, "wb");
    if (!v4_media_h264) {
        perror("media-h264-open");
        return FALSE;
    }

    chmod(V4_MEDIA_H264_FILE, 0600);
    return TRUE;
}


static gboolean
v4_media_write_bytes(const guint8 *data, guint len)
{
    if (!v4_media_h264 || !data || len == 0)
        return FALSE;

    if (fwrite(data, 1, len, v4_media_h264) != len)
        return FALSE;

    v4_media_h264_bytes += len;
    return TRUE;
}


static gboolean
v4_media_write_start_code(void)
{
    static const guint8 start_code[4] = {0, 0, 0, 1};
    return v4_media_write_bytes(start_code, sizeof(start_code));
}


static gboolean
v4_media_depacketize_h264(const guint8 *payload, guint len)
{
    if (!payload || len == 0)
        return TRUE;

    guint nal_type = payload[0] & 0x1f;

    if (nal_type >= 1 && nal_type <= 23) {
        v4_media_fu_open = FALSE;
        return v4_media_write_start_code() &&
               v4_media_write_bytes(payload, len);
    }

    if (nal_type == 24) {
        guint pos = 1;
        v4_media_fu_open = FALSE;

        while (pos + 2 <= len) {
            guint n = ((guint)payload[pos] << 8) | payload[pos + 1];
            pos += 2;

            if (n == 0 || pos + n > len)
                return FALSE;

            if (!v4_media_write_start_code() ||
                !v4_media_write_bytes(payload + pos, n))
                return FALSE;

            pos += n;
        }

        return pos == len;
    }

    if (nal_type == 28 && len >= 2) {
        guint8 fu_indicator = payload[0];
        guint8 fu_header = payload[1];
        gboolean start = (fu_header & 0x80) != 0;
        gboolean end = (fu_header & 0x40) != 0;
        guint8 original_type = fu_header & 0x1f;

        if (start) {
            guint8 reconstructed =
                (guint8)((fu_indicator & 0xe0) | original_type);

            if (!v4_media_write_start_code() ||
                !v4_media_write_bytes(&reconstructed, 1) ||
                !v4_media_write_bytes(payload + 2, len - 2))
                return FALSE;

            v4_media_fu_open = TRUE;
        } else if (v4_media_fu_open) {
            if (!v4_media_write_bytes(payload + 2, len - 2))
                return FALSE;
        }

        if (end)
            v4_media_fu_open = FALSE;

        return TRUE;
    }

    /* Unobserved packetization mode: ignore, do not feed corrupted bytes. */
    return TRUE;
}


static gboolean
v4_media_try_handle_raw(const guint8 *buf, guint len)
{
    if (!buf || len < 8)
        return FALSE;

    if (buf[0] != 0x00 || buf[1] != 0x06)
        return FALSE;

    guint16 body_len = read_le16(buf + 2);
    guint32 request_id = read_le32(buf + 4);

    if (request_id != v4_media_video_id &&
        request_id != v4_media_audio_id)
        return FALSE;

    /* Raw audio belongs to the negotiated media flow but is out of scope. */
    if (request_id == v4_media_audio_id)
        return TRUE;

    if ((guint)body_len > len - 8 || body_len < 12)
        return TRUE;

    const guint8 *rtp = buf + 8;
    guint rtp_len = body_len;

    if ((rtp[0] >> 6) != 2)
        return TRUE;

    if ((rtp[1] & 0x7f) != V4_MEDIA_RTP_PT)
        return TRUE;

    guint cc = rtp[0] & 0x0f;
    gboolean extension = (rtp[0] & 0x10) != 0;
    gboolean padding = (rtp[0] & 0x20) != 0;
    guint pos = 12 + cc * 4;

    if (pos > rtp_len)
        return TRUE;

    if (extension) {
        if (pos + 4 > rtp_len)
            return TRUE;

        guint words = ((guint)rtp[pos + 2] << 8) | rtp[pos + 3];
        pos += 4 + words * 4;
        if (pos > rtp_len)
            return TRUE;
    }

    guint end = rtp_len;
    if (padding) {
        guint pad = rtp[rtp_len - 1];
        if (pad == 0 || pad > end - pos)
            return TRUE;
        end -= pad;
    }

    guint16 seq = ((guint16)rtp[2] << 8) | rtp[3];

    if (v4_media_have_last_rtp_seq) {
        guint16 delta = (guint16)(seq - v4_media_last_rtp_seq);
        if (delta != 1) {
            v4_media_rtp_sequence_gaps++;
            v4_media_fu_open = FALSE;
        }
    }

    v4_media_have_last_rtp_seq = TRUE;
    v4_media_last_rtp_seq = seq;
    v4_media_rtp_packets++;

    if (!v4_media_active) {
        v4_media_active = TRUE;
        v4_media_active_started_us = g_get_monotonic_time();
        v4_media_stage = V4_MEDIA_ACTIVE;
        v4_media_stage_deadline_us = 0;

        printf("V4_MEDIA_ACTIVE=true\n");
        printf("V4_MEDIA_RTP_PT=%u\n", (unsigned)V4_MEDIA_RTP_PT);
        fflush(stdout);
    }

    if (pos < end &&
        !v4_media_depacketize_h264(rtp + pos, end - pos)) {
        fprintf(stderr, "V4_MEDIA_H264_WRITE=FAIL\n");
        failed = TRUE;
        v4_media_request_stop("h264_write_failure");
    }

    return TRUE;
}


static guint
v4_media_build_event(
    guint8 *body,
    guint body_size,
    guint16 prefix,
    guint16 action,
    guint16 flags,
    const guint8 *payload,
    guint payload_len)
{
    guint needed = 10 + payload_len + 24;
    if (!body || body_size < needed)
        return 0;

    memset(body, 0, needed);
    write_le16(body + 0, prefix);
    v4_media_write_seq(body + 2);
    v4_media_write_be16(body + 6, action);
    v4_media_write_be16(body + 8, flags);

    if (payload_len > 0)
        memcpy(body + 10, payload, payload_len);

    if (!v4_media_write_address_tail(
            body + 10 + payload_len,
            body_size - 10 - payload_len))
        return 0;

    return needed;
}


static gboolean
v4_media_queue_body(
    const guint8 *body,
    guint body_len,
    P12TxKind kind)
{
    if (p12_tx_pending || v4_media_waiting_own_ack)
        return FALSE;

    v4_media_pending_local = v4_media_seq_local;
    v4_media_pending_remote = v4_media_seq_remote;
    v4_media_pending_kind = kind;

    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        body_len,
        kind
    );

    return ok && p12_flush_tx();
}


static gboolean
v4_media_queue_event(
    guint16 prefix,
    guint16 action,
    guint16 flags,
    const guint8 *payload,
    guint payload_len,
    P12TxKind kind)
{
    guint8 body[128];
    guint body_len = v4_media_build_event(
        body, sizeof(body), prefix, action, flags, payload, payload_len);

    if (body_len == 0)
        return FALSE;

    gboolean ok = v4_media_queue_body(body, body_len, kind);
    memset(body, 0, sizeof(body));
    return ok;
}


static gboolean
v4_media_queue_call_init(void)
{
    guint8 payload[38];
    guint p = 0;
    memset(payload, 0, sizeof(payload));

    memcpy(payload + p, V4_FULL_ADDRESS, 9); p += 9;
    payload[p++] = 0;
    memcpy(payload + p, V4_MEDIA_TARGET, 8); p += 8;
    payload[p++] = 0;
    payload[p++] = 0;

    const guint8 profile[6] = {0x01, 0x20, 0x05, 0x80, 0x31, 0x18};
    memcpy(payload + p, profile, sizeof(profile)); p += sizeof(profile);

    memcpy(payload + p, V4_FULL_ADDRESS, 9); p += 9;
    payload[p++] = 0;
    payload[p++] = 0x49;
    payload[p++] = 0x49;

    if (p != sizeof(payload))
        return FALSE;

    return v4_media_queue_event(
        0x18C0, 0x0028, 0x0001,
        payload, sizeof(payload),
        P12_TX_V4_MEDIA_CALL_INIT);
}


static gboolean
v4_media_queue_action_0008(void)
{
    static const guint8 payload[6] = {0x49, 0x00, 0x27, 0x00, 0x00, 0x00};
    return v4_media_queue_event(
        0x1840, 0x0008, 0x0003,
        payload, sizeof(payload),
        P12_TX_V4_MEDIA_ACTION_0008);
}


static gboolean
v4_media_queue_action_000a(gboolean stop)
{
    guint8 payload[10] = {0};
    payload[0] = stop ? 0x98 : 0x18;
    payload[1] = 0x02;
    write_le16(payload + 6, v4_media_audio_id);

    return v4_media_queue_event(
        0x1840, 0x000A, 0x0011,
        payload, sizeof(payload),
        stop ? P12_TX_V4_MEDIA_ACTION_000A_STOP
             : P12_TX_V4_MEDIA_ACTION_000A_START);
}


static gboolean
v4_media_queue_action_001a(gboolean stop)
{
    guint8 payload[26] = {0};
    payload[0] = stop ? 0x94 : 0x14;
    payload[1] = stop ? 0x02 : 0x32;
    write_le16(payload + 6, v4_media_video_id);

    if (!stop) {
        payload[8] = 0xff;
        payload[9] = 0xff;
        /* bytes 10..13 remain zero */
        const guint8 profile[12] = {
            0x20, 0x03, 0xe0, 0x01,
            0x40, 0x01, 0xf0, 0x00,
            0x10, 0x00, 0x00, 0x00
        };
        memcpy(payload + 14, profile, sizeof(profile));
    }

    return v4_media_queue_event(
        0x1840, 0x001A, 0x0011,
        payload, sizeof(payload),
        stop ? P12_TX_V4_MEDIA_ACTION_001A_STOP
             : P12_TX_V4_MEDIA_ACTION_001A_START);
}


static gboolean
v4_media_queue_action_000e(gboolean active)
{
    guint8 payload[14] = {0};
    memcpy(payload, V4_FULL_ADDRESS, 9);
    payload[9] = 0;
    payload[10] = active ? 1 : 0;

    return v4_media_queue_event(
        active ? 0x1840 : 0x1860,
        0x000E,
        0x0070,
        payload, sizeof(payload),
        active ? P12_TX_V4_MEDIA_ACTION_000E_ACTIVE
               : P12_TX_V4_MEDIA_ACTION_000E_FINAL);
}


static gboolean
v4_media_queue_action_0003(void)
{
    const guint8 payload[2] = {0, 0};
    return v4_media_queue_event(
        0x1840, 0x0003, 0x000E,
        payload, sizeof(payload),
        P12_TX_V4_MEDIA_ACTION_0003_STOP);
}


static gboolean
v4_media_queue_peer_ack(const guint8 *peer_body, guint body_len)
{
    if (!peer_body || body_len < 8 || p12_tx_pending)
        return FALSE;

    const guint8 *peer_seq = peer_body + 2;

    if ((peer_seq[0] & 0x7f) != v4_media_seq_base0 ||
        peer_seq[1] != v4_media_seq_base1 ||
        peer_seq[3] != v4_media_seq_local) {
        fprintf(stderr, "V4_MEDIA_PEER_SEQUENCE=FAIL\n");
        return FALSE;
    }

    v4_media_seq_local = peer_seq[3];
    v4_media_seq_remote = (guint8)(peer_seq[2] + 1);

    guint8 ack[32];
    memset(ack, 0, sizeof(ack));
    write_le16(ack + 0, 0x1800);
    v4_media_write_seq(ack + 2);
    v4_media_write_be16(ack + 6, 0x0000);
    memset(ack + 8, 0xff, 4);
    memcpy(ack + 12, V4_FULL_ADDRESS, 9);
    ack[21] = 0;
    memcpy(ack + 22, V4_MEDIA_TARGET, 8);
    ack[30] = 0;
    ack[31] = 0;

    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        ack,
        sizeof(ack),
        P12_TX_V4_MEDIA_PEER_ACK);

    memset(ack, 0, sizeof(ack));
    return ok && p12_flush_tx();
}


static void
v4_media_set_stage_deadline(void)
{
    v4_media_stage_deadline_us =
        g_get_monotonic_time() + V4_MEDIA_STAGE_TIMEOUT_USEC;
}


static gboolean
v4_media_allocate_ids(void)
{
    guint16 audio = v4_allocate_channel_id(7459);
    guint16 video = (guint16)(audio + 1);

    while (video == 0 ||
           video == echo_channel_id ||
           video == uaut_channel_id ||
           video == ucfg_channel_id ||
           video == v4_ctpp_channel_id ||
           video == v4_cspb_channel_id ||
           video == audio) {
        video++;
    }

    v4_media_audio_id = audio;
    v4_media_video_id = video;
    return audio != 0 && video != 0;
}


static gboolean
v4_media_start_setup(void)
{
    if (v4_media_setup_started)
        return TRUE;

    if (!v4_registered || !v4_listener_ready ||
        p12_stage != P12_STAGE_V4_LISTEN_RING ||
        p12_tx_pending || v4_media_waiting_own_ack)
        return FALSE;

    if (!v4_media_prepare_output() || !v4_media_allocate_ids())
        return FALSE;

    guint32 seed = g_random_int();
    v4_media_seq_base0 = (guint8)(seed & 0x7f);
    v4_media_seq_base1 = (guint8)((seed >> 8) & 0xff);
    v4_media_seq_local = (guint8)((seed >> 16) & 0xff);
    v4_media_seq_remote = (guint8)((seed >> 24) & 0xff);

    v4_media_setup_started = TRUE;

    printf("V4_DOOR_ACTION_SURFACE_PRESENT=false\n");
    printf("V4_MEDIA_ACTION_SURFACE_PRESENT=true\n");
    printf("V4_MEDIA_TARGET=entrance\n");
    printf("V4_MEDIA_SETUP_STARTED=true\n");
    fflush(stdout);

    if (!v4_media_queue_call_init())
        return FALSE;

    return TRUE;
}


static void
v4_media_begin_teardown(void)
{
    if (v4_media_teardown_started || v4_media_stage == V4_MEDIA_DONE)
        return;

    v4_media_teardown_requested = TRUE;

    if (!v4_media_setup_started ||
        !v4_registered || !pseudotcp_open ||
        p12_tx_pending || v4_media_waiting_own_ack)
        return;

    v4_media_teardown_started = TRUE;
    printf("V4_MEDIA_TEARDOWN_STARTED=true\n");
    fflush(stdout);

    if (!v4_media_queue_action_0003()) {
        v4_media_stage = V4_MEDIA_ERROR;
        failed = TRUE;
        if (loop) g_main_loop_quit(loop);
    }
}


static void
v4_media_request_stop(const gchar *reason)
{
    (void)reason;
    v4_media_teardown_requested = TRUE;

    if (v4_media_force_exit_us == 0)
        v4_media_force_exit_us =
            g_get_monotonic_time() + ((gint64)3 * G_USEC_PER_SEC);

    v4_media_begin_teardown();
}


static void
v4_media_command_sent(P12TxKind kind)
{
    v4_media_waiting_own_ack = TRUE;
    v4_media_pending_kind = kind;
    v4_media_set_stage_deadline();

    switch (kind) {
        case P12_TX_V4_MEDIA_CALL_INIT:
            v4_media_stage = V4_MEDIA_WAIT_CALL_ACK;
            printf("V4_MEDIA_CALL_INIT_SENT=true\n");
            break;
        case P12_TX_V4_MEDIA_ACTION_0008:
            v4_media_stage = V4_MEDIA_WAIT_0008_ACK;
            printf("V4_MEDIA_ACTION_0008_SENT=true\n");
            break;
        case P12_TX_V4_MEDIA_ACTION_000A_START:
            v4_media_stage = V4_MEDIA_WAIT_000A_EXCHANGE;
            printf("V4_MEDIA_ACTION_000A_START_SENT=true\n");
            break;
        case P12_TX_V4_MEDIA_ACTION_001A_START:
            v4_media_stage = V4_MEDIA_WAIT_001A_ACK;
            printf("V4_MEDIA_ACTION_001A_START_SENT=true\n");
            break;
        case P12_TX_V4_MEDIA_ACTION_000E_ACTIVE:
            v4_media_stage = V4_MEDIA_WAIT_KEEPALIVE_ACK;
            printf("V4_MEDIA_ACTION_000E_ACTIVE_SENT=true\n");
            break;
        case P12_TX_V4_MEDIA_ACTION_0003_STOP:
            v4_media_stage = V4_MEDIA_STOP_WAIT_0003_ACK;
            break;
        case P12_TX_V4_MEDIA_ACTION_000A_STOP:
            v4_media_stage = V4_MEDIA_STOP_WAIT_000A_ACK;
            break;
        case P12_TX_V4_MEDIA_ACTION_001A_STOP:
            v4_media_stage = V4_MEDIA_STOP_WAIT_001A_EXCHANGE;
            break;
        case P12_TX_V4_MEDIA_ACTION_000E_FINAL:
            v4_media_stage = V4_MEDIA_STOP_WAIT_FINAL_000E_ACK;
            break;
        default:
            break;
    }

    fflush(stdout);
}


static gboolean
v4_media_queue_000a_start_if_ready(void)
{
    if (!v4_media_send_000a_after_peer_ack ||
        p12_tx_pending || v4_media_waiting_own_ack)
        return TRUE;

    v4_media_send_000a_after_peer_ack = FALSE;
    return v4_media_queue_action_000a(FALSE);
}


static gboolean
v4_media_queue_001a_start_if_ready(void)
{
    if (!v4_media_seen_peer_000a_start ||
        !v4_media_peer_000a_start_ack_sent ||
        !v4_media_own_000a_start_acked ||
        p12_tx_pending || v4_media_waiting_own_ack)
        return TRUE;

    return v4_media_queue_action_001a(FALSE);
}


static gboolean
v4_media_queue_final_000e_if_ready(void)
{
    if (!v4_media_seen_peer_000a_stop ||
        !v4_media_peer_000a_stop_ack_sent ||
        !v4_media_own_001a_stop_acked ||
        p12_tx_pending || v4_media_waiting_own_ack)
        return TRUE;

    return v4_media_queue_action_000e(FALSE);
}


static void
v4_media_peer_ack_sent(void)
{
    if (v4_media_stage == V4_MEDIA_WAIT_PEER_0002 &&
        v4_media_send_000a_after_peer_ack) {
        if (!v4_media_queue_000a_start_if_ready()) {
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
        }
        return;
    }

    if (v4_media_seen_peer_000a_start &&
        !v4_media_peer_000a_start_ack_sent) {
        v4_media_peer_000a_start_ack_sent = TRUE;
        if (!v4_media_queue_001a_start_if_ready()) {
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
        }
        return;
    }

    if (v4_media_seen_peer_000a_stop &&
        !v4_media_peer_000a_stop_ack_sent) {
        v4_media_peer_000a_stop_ack_sent = TRUE;
        if (!v4_media_queue_final_000e_if_ready()) {
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
        }
    }
}


static gboolean
v4_media_handle_own_ack(const guint8 *body, guint body_len)
{
    if (!v4_media_waiting_own_ack || !body || body_len < 8)
        return FALSE;

    const guint8 *seq = body + 2;
    guint8 expected0 = (guint8)(v4_media_seq_base0 | 0x80);
    guint8 expected_local_next = (guint8)(v4_media_pending_local + 1);

    if (seq[0] != expected0 ||
        seq[1] != v4_media_seq_base1 ||
        seq[2] != v4_media_pending_remote ||
        seq[3] != expected_local_next) {
        return FALSE;
    }

    P12TxKind acked = v4_media_pending_kind;
    v4_media_seq_local = expected_local_next;
    v4_media_waiting_own_ack = FALSE;
    v4_media_pending_kind = P12_TX_NONE;
    v4_media_stage_deadline_us = 0;

    switch (acked) {
        case P12_TX_V4_MEDIA_CALL_INIT:
            return v4_media_queue_action_0008();

        case P12_TX_V4_MEDIA_ACTION_0008:
            v4_media_stage = V4_MEDIA_WAIT_PEER_0008;
            v4_media_set_stage_deadline();
            return TRUE;

        case P12_TX_V4_MEDIA_ACTION_000A_START:
            v4_media_own_000a_start_acked = TRUE;
            return v4_media_queue_001a_start_if_ready();

        case P12_TX_V4_MEDIA_ACTION_001A_START:
            v4_media_stage = V4_MEDIA_WAIT_FIRST_RTP;
            v4_media_set_stage_deadline();
            return TRUE;

        case P12_TX_V4_MEDIA_ACTION_000E_ACTIVE:
            v4_media_stage = V4_MEDIA_ACTIVE;
            if (v4_media_teardown_requested)
                v4_media_begin_teardown();
            return TRUE;

        case P12_TX_V4_MEDIA_ACTION_0003_STOP:
            return v4_media_queue_action_000a(TRUE);

        case P12_TX_V4_MEDIA_ACTION_000A_STOP:
            return v4_media_queue_action_001a(TRUE);

        case P12_TX_V4_MEDIA_ACTION_001A_STOP:
            v4_media_own_001a_stop_acked = TRUE;
            return v4_media_queue_final_000e_if_ready();

        case P12_TX_V4_MEDIA_ACTION_000E_FINAL:
            v4_media_teardown_acked = TRUE;
            v4_media_stage = V4_MEDIA_DONE;
            v4_media_active = FALSE;
            printf("V4_MEDIA_TEARDOWN_RESULT=ACKED\n");
            fflush(stdout);
            if (loop) g_main_loop_quit(loop);
            return TRUE;

        default:
            return TRUE;
    }
}


static V4MediaFrameResult
v4_media_process_ctpp(guint32 request_id, const guint8 *body, guint body_len)
{
    if (!v4_media_setup_started ||
        request_id != v4_ctpp_channel_id ||
        !body || body_len < 8)
        return V4_MEDIA_FRAME_NOT_CONSUMED;

    guint16 prefix = read_le16(body + 0);
    guint16 action = ((guint16)body[6] << 8) | body[7];

    if (prefix == 0x1800 && v4_media_waiting_own_ack) {
        if (!v4_media_handle_own_ack(body, body_len)) {
            fprintf(stderr, "V4_MEDIA_OWN_ACK=FAIL\n");
            return V4_MEDIA_FRAME_FAIL;
        }
        return V4_MEDIA_FRAME_CONSUMED;
    }

    if (prefix == 0x1840 && action == 0x0008 &&
        v4_media_stage == V4_MEDIA_WAIT_PEER_0008) {
        if (!v4_media_queue_peer_ack(body, body_len))
            return V4_MEDIA_FRAME_FAIL;
        v4_media_stage = V4_MEDIA_WAIT_PEER_0002;
        v4_media_set_stage_deadline();
        return V4_MEDIA_FRAME_CONSUMED;
    }

    if (prefix == 0x1840 && action == 0x0002 &&
        v4_media_stage == V4_MEDIA_WAIT_PEER_0002) {
        v4_media_send_000a_after_peer_ack = TRUE;
        if (!v4_media_queue_peer_ack(body, body_len))
            return V4_MEDIA_FRAME_FAIL;
        v4_media_set_stage_deadline();
        return V4_MEDIA_FRAME_CONSUMED;
    }

    if (prefix == 0x1840 && action == 0x000A &&
        v4_media_stage == V4_MEDIA_WAIT_000A_EXCHANGE) {
        v4_media_seen_peer_000a_start = TRUE;
        if (!v4_media_queue_peer_ack(body, body_len))
            return V4_MEDIA_FRAME_FAIL;
        return V4_MEDIA_FRAME_CONSUMED;
    }

    if (prefix == 0x1860 && action == 0x000A &&
        v4_media_stage == V4_MEDIA_STOP_WAIT_001A_EXCHANGE) {
        v4_media_seen_peer_000a_stop = TRUE;
        if (!v4_media_queue_peer_ack(body, body_len))
            return V4_MEDIA_FRAME_FAIL;
        return V4_MEDIA_FRAME_CONSUMED;
    }

    return V4_MEDIA_FRAME_NOT_CONSUMED;
}


static gboolean
v4_media_tick_cb(gpointer data)
{
    (void)data;
    gint64 now = g_get_monotonic_time();

    if (v4_media_start_requested && !v4_media_setup_started &&
        v4_registered && v4_listener_ready &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        !p12_tx_pending) {

        if (!v4_media_start_setup()) {
            fprintf(stderr, "V4_MEDIA_SETUP_QUEUE=FAIL\n");
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return G_SOURCE_REMOVE;
        }
    }

    if (v4_media_stage_deadline_us > 0 &&
        now > v4_media_stage_deadline_us) {
        fprintf(stderr, "V4_MEDIA_STAGE_TIMEOUT=%u\n", (unsigned)v4_media_stage);
        v4_media_stage_deadline_us = 0;
        v4_media_request_stop("stage_timeout");
    }

    if (v4_media_active && v4_media_active_started_us > 0) {
        gint64 elapsed = now - v4_media_active_started_us;

        if (!v4_media_keepalive_sent &&
            elapsed >= V4_MEDIA_KEEPALIVE_USEC &&
            !p12_tx_pending && !v4_media_waiting_own_ack &&
            !v4_media_teardown_requested) {

            v4_media_keepalive_sent = TRUE;
            if (!v4_media_queue_action_000e(TRUE)) {
                fprintf(stderr, "V4_MEDIA_ACTIVE_000E_QUEUE=FAIL\n");
                v4_media_request_stop("active_keepalive_failure");
            }
        }

        if (elapsed >= V4_MEDIA_CAPTURE_USEC)
            v4_media_teardown_requested = TRUE;
    }

    if (v4_media_teardown_requested &&
        !v4_media_teardown_started &&
        !p12_tx_pending && !v4_media_waiting_own_ack)
        v4_media_begin_teardown();

    if (v4_media_force_exit_us > 0 && now >= v4_media_force_exit_us &&
        v4_media_stage != V4_MEDIA_DONE) {
        fprintf(stderr, "V4_MEDIA_FORCE_EXIT=true\n");
        if (v4_media_teardown_started)
            printf("V4_MEDIA_TEARDOWN_RESULT=PARTIAL\n");
        else
            printf("V4_MEDIA_TEARDOWN_RESULT=FAILED\n");
        fflush(stdout);
        failed = TRUE;
        if (loop) g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
v4_media_watchdog_cb(gpointer data)
{
    (void)data;

    if (v4_media_stage == V4_MEDIA_DONE)
        return G_SOURCE_REMOVE;

    printf("V4_MEDIA_INTERNAL_WATCHDOG=true\n");
    fflush(stdout);

    v4_media_teardown_requested = TRUE;
    v4_media_force_exit_us =
        g_get_monotonic_time() + ((gint64)1 * G_USEC_PER_SEC);
    v4_media_begin_teardown();
    return G_SOURCE_REMOVE;
}


static void
v4_media_cleanup_transport(void)
{
    if (v4_media_cleanup_done)
        return;

    v4_media_cleanup_done = TRUE;

    if (v4_media_h264) {
        fflush(v4_media_h264);
        fclose(v4_media_h264);
        v4_media_h264 = NULL;
    }

    printf("V4_MEDIA_H264_BYTES=%llu\n",
           (unsigned long long)v4_media_h264_bytes);
    printf("V4_MEDIA_RTP_PACKETS=%llu\n",
           (unsigned long long)v4_media_rtp_packets);
    printf("V4_MEDIA_RTP_SEQUENCE_GAPS=%llu\n",
           (unsigned long long)v4_media_rtp_sequence_gaps);

    if (pseudo_tcp) {
        pseudo_tcp_socket_close(pseudo_tcp, TRUE);
        g_object_unref(pseudo_tcp);
        pseudo_tcp = NULL;
    }

    if (agent && stream_id != 0) {
        nice_agent_remove_stream(agent, stream_id);
        stream_id = 0;
    }

    printf("V4_MEDIA_ICE_CLOSED=true\n");

    gboolean pass =
        !failed &&
        v4_media_teardown_acked &&
        v4_media_rtp_packets > 0 &&
        v4_media_h264_bytes > 0;

    printf("V4_MEDIA_EXIT=%s\n", pass ? "PASS" : "FAIL");
    fflush(stdout);

    if (!pass)
        failed = TRUE;
}


'''
    src = replace_once(
        src,
        media_impl_anchor,
        media_impl + "\n\nstatic void\np12_tx_completed(P12TxKind kind)\n",
        "MEDIA_IMPL",
    )

    tx_default_anchor = r'''        case P12_TX_V4_PEER_ECHO_CLOSE_ACK:

            printf(
                "V4_PEER_ECHO_CLOSE_ACK_SENT=true\n"
            );

            p12_stage =
                P12_STAGE_V4_LISTEN_RING;

            p12_deadline_us =
                0;

            break;


        default:
            break;
'''
    tx_default_new = r'''        case P12_TX_V4_PEER_ECHO_CLOSE_ACK:

            printf(
                "V4_PEER_ECHO_CLOSE_ACK_SENT=true\n"
            );

            p12_stage =
                P12_STAGE_V4_LISTEN_RING;

            p12_deadline_us =
                0;

            break;


        case P12_TX_V4_MEDIA_CALL_INIT:
        case P12_TX_V4_MEDIA_ACTION_0008:
        case P12_TX_V4_MEDIA_ACTION_000A_START:
        case P12_TX_V4_MEDIA_ACTION_001A_START:
        case P12_TX_V4_MEDIA_ACTION_000E_ACTIVE:
        case P12_TX_V4_MEDIA_ACTION_0003_STOP:
        case P12_TX_V4_MEDIA_ACTION_000A_STOP:
        case P12_TX_V4_MEDIA_ACTION_001A_STOP:
        case P12_TX_V4_MEDIA_ACTION_000E_FINAL:
            v4_media_command_sent(kind);
            break;

        case P12_TX_V4_MEDIA_PEER_ACK:
            v4_media_peer_ack_sent();
            break;


        default:
            break;
'''
    src = replace_once(src, tx_default_anchor, tx_default_new, "TX_COMPLETION")

    ready_old = r'''                printf(
                    "V4_RING_LISTENER_READY=true\n"
                );

                printf(
                    "V4_DOOR_ACTION_SURFACE_PRESENT=false\n"
                );

                printf(
                    "V4_MEDIA_ACTION_SURFACE_PRESENT=false\n"
                );
'''
    ready_new = r'''                printf(
                    "V4_MEDIA_TRANSPORT_READY=true\n"
                );

                printf(
                    "V4_DOOR_ACTION_SURFACE_PRESENT=false\n"
                );

                printf(
                    "V4_MEDIA_ACTION_SURFACE_PRESENT=true\n"
                );

                v4_media_start_requested = TRUE;
'''
    src = replace_once(src, ready_old, ready_new, "READY_MARKERS")

    listener_anchor = r'''        if (
            p12_stage ==
            P12_STAGE_V4_LISTEN_RING
        ) {

            /*
             * ----------------------------------------------------
             * Peer-opened ECHO
'''
    listener_new = r'''        if (
            p12_stage ==
            P12_STAGE_V4_LISTEN_RING
        ) {

            V4MediaFrameResult media_frame =
                v4_media_process_ctpp(request_id, body, body_len);

            if (media_frame == V4_MEDIA_FRAME_FAIL)
                return FALSE;

            if (media_frame == V4_MEDIA_FRAME_CONSUMED) {
                p12_consume_post_ack(frame_len);
                continue;
            }

            /*
             * ----------------------------------------------------
             * Peer-opened ECHO
'''
    src = replace_once(src, listener_anchor, listener_new, "CTPP_MEDIA_HOOK")

    timeout_old = r'''    g_timeout_add_seconds(
        3300,
        absolute_timeout_cb,
        NULL
    );
'''
    timeout_new = r'''    g_timeout_add(
        100,
        v4_media_tick_cb,
        NULL
    );

    /* Internal graceful watchdog.  The runner adds an independent
     * process-level 30 second watchdog as the final safety boundary. */
    g_timeout_add_seconds(
        28,
        v4_media_watchdog_cb,
        NULL
    );
'''
    src = replace_once(src, timeout_old, timeout_new, "WATCHDOG")

    cleanup_old = r'''    if (pseudo_tcp)
        g_object_unref(pseudo_tcp);

    g_object_unref(agent);
    g_main_loop_unref(loop);

    return failed ? 6 : 0;
'''
    cleanup_new = r'''    v4_media_cleanup_transport();

    g_object_unref(agent);
    g_main_loop_unref(loop);

    return failed ? 6 : 0;
'''
    src = replace_once(src, cleanup_old, cleanup_new, "CLEANUP")

    # Safety assertions on generated source.
    forbidden = (
        "v4_door_queue_open",
        "v4_door_queue_write",
        "v4_door_signal_handler",
        "V4_DOOR_COMMAND_ACCEPTED",
        "SIGUSR1",
    )
    for token in forbidden:
        if token in src:
            raise SystemExit(f"SAFETY_SOURCE_FORBIDDEN={token}")

    required = (
        "V4_DOOR_ACTION_SURFACE_PRESENT=false",
        "V4_MEDIA_ACTION_SURFACE_PRESENT=true",
        "V4_MEDIA_TARGET=entrance",
        "V4_MEDIA_TEARDOWN_STARTED=true",
        "V4_MEDIA_ICE_CLOSED=true",
        "P12_TX_V4_MEDIA_ACTION_0003_STOP",
    )
    for token in required:
        if token not in src:
            raise SystemExit(f"REQUIRED_TOKEN_MISSING={token}")

    OUT.write_text(src, encoding="utf-8")

    print(f"BASE={BASE}")
    print(f"OUT={OUT}")
    print(f"LINES={src.count(chr(10)) + 1}")
    print("DOOR_ACTION_SOURCE=ABSENT")
    print("MEDIA_POC_GENERATE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
