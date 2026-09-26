#!/usr/bin/env python3
"""MSL-V1 Variant B: idle entrance media inside the ready listener.

This research transform composes the reviewed R58 listener chain, then adds a
small control-file driven idle-media overlay.  The overlay never opens cloud,
ICE, PseudoTCP, UAUT, or CTPP state.  It accepts a start request only after the
listener is already READY and reuses the listener's existing CTPP channel,
single pending TX slot, RTPC channel allocator, and P80 RTP forwarding path.

The generated candidate performs no network I/O at transform time.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)

BEGIN = "/* MSL_V1_IDLE_LISTENER_MEDIA_BEGIN */"
END = "/* MSL_V1_IDLE_LISTENER_MEDIA_END */"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"MSL_B_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


CONTROL_DEFS_ANCHOR = '#define STOP_FILE   RUN_DIR "/stop"\n'
CONTROL_DEFS_REPLACEMENT = (
    CONTROL_DEFS_ANCHOR
    + '#define MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"\n'
    + '#define MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"\n'
    + "\n"
    # The B05/B06/B07 markers are read from the RTP/H.264 receive path, which is
    # anchored earlier in this file than the overlay block (near the R42 media
    # state) that owns their storage and printer; forward-declare them here so
    # the earlier anchors compile against a declaration instead of an implicit one.
    + "static gboolean msl_b_b05_audio_marked;\n"
    + "static gboolean msl_b_b06_video_marked;\n"
    + "static gboolean msl_b_b07_decodable_marked;\n"
    + "static void msl_b_print_clock_marker(const char *name);\n"
)

ENUM_ANCHOR = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_R54_INVITE_ACK,"""
ENUM_REPLACEMENT = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_MSL_B_PREAMBLE_0028,
    P12_TX_MSL_B_PREAMBLE_CLIENT_0008,
    P12_TX_MSL_B_ACK_DEVICE_0008,
    P12_TX_MSL_B_ACK_DEVICE_0002,
    P12_TX_MSL_B_RTPC_OPEN_2,
    P12_TX_MSL_B_RTPC_CLIENT_RESPONSE,
    P12_TX_MSL_B_RTPC_CLIENT_000A,
    P12_TX_MSL_B_DEVICE_000A_ACK,
    P12_TX_MSL_B_IDLE_SELF_ACTIVATION,

    P12_TX_R54_INVITE_ACK,"""

STATE_ANCHOR = """static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;
static guint16 r42_media_channel_id = 0;
static unsigned r42_attempted_call_generation = 0;
"""

OVERLAY = r'''
/* MSL_V1_IDLE_LISTENER_MEDIA_BEGIN */
typedef enum {
    MSL_B_IDLE_STATE_IDLE = 0,
    /* MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_BEGIN: reuses
     * entrance_self_activation_signaling_transform.py (0x0028 self-activation
     * and client 0x0008 video event),
     * entrance_device_video_ack_observation_transform.py (device 0x0008 and
     * its client ACK), and entrance_p95_wait_device_0002_before_rtpc_transform.py
     * (device 0x0002 and its client ACK) -- rebound to this overlay's own
     * already-READY listener session instead of those transforms' own
     * one-shot signaling probe.  RTPC (below) may only begin after this
     * sequence's last stage transmits successfully. */
    MSL_B_IDLE_STATE_PREAMBLE_0028_TX,
    MSL_B_IDLE_STATE_WAIT_0028_ACK,
    MSL_B_IDLE_STATE_PREAMBLE_CLIENT_0008_TX,
    MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK,
    MSL_B_IDLE_STATE_WAIT_DEVICE_0008,
    MSL_B_IDLE_STATE_ACK_DEVICE_0008_TX,
    MSL_B_IDLE_STATE_WAIT_DEVICE_0002,
    MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX,
    /* MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_END */
    MSL_B_IDLE_STATE_CHANNEL_OPEN_TX,
    /* MSL_B_PRE_001A_SEQUENCE_BEGIN: reuses entrance_rtpc_control_media_runtime_transform.py
     * (P76) open/response/000a wire builders and
     * entrance_p97_complete_post_000a_ack_cycle_transform.py (P97) post-000A
     * ACK-cycle logic.  Each stage below is the msl_b-local reuse of exactly
     * one proven primitive; see the functions that set/consume each state. */
    MSL_B_IDLE_STATE_OPEN2_TX,
    MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN,
    MSL_B_IDLE_STATE_CLIENT_RESPONSE_TX,
    MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES,
    MSL_B_IDLE_STATE_CLIENT_000A_TX,
    MSL_B_IDLE_STATE_WAIT_DEVICE_000A,
    MSL_B_IDLE_STATE_DEVICE_000A_ACK_TX,
    MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A,
    /* MSL_B_PRE_001A_SEQUENCE_END */
    MSL_B_IDLE_STATE_SELF_ACTIVATION_TX,
    MSL_B_IDLE_STATE_ACTIVE,
    MSL_B_IDLE_STATE_CLOSE_TX,
    MSL_B_IDLE_STATE_CLOSED,
    MSL_B_IDLE_STATE_FAILED
} MslBIdleMediaState;

static MslBIdleMediaState msl_b_idle_state = MSL_B_IDLE_STATE_IDLE;
static guint msl_b_media_session_count = 0;
static guint msl_b_duplicate_start_rejected_count = 0;
static guint msl_b_ring_collision_rejected_count = 0;
static guint msl_b_cloud_negotiation_count_after_ready = 0;
static guint msl_b_ice_bootstrap_count_after_ready = 0;
static guint msl_b_pseudotcp_open_count_after_ready = 0;
static guint msl_b_ctpp_registration_count_after_ready = 0;
static guint msl_b_reconnect_count_before = 0;
static guint msl_b_reconnect_count_after = 0;
static guint msl_b_listener_pid_before = 0;
static guint msl_b_listener_pid_after = 0;
static gboolean msl_b_ready_snapshot_taken = FALSE;
static gboolean msl_b_media_rx_active = FALSE;
static gboolean msl_b_media_rx_inactive_after_close = FALSE;
static gboolean msl_b_start_control_consumed = FALSE;
static gboolean msl_b_stop_control_consumed = FALSE;
static gboolean msl_b_b05_audio_marked = FALSE;
static gboolean msl_b_b06_video_marked = FALSE;
static gboolean msl_b_b07_decodable_marked = FALSE;
static gboolean msl_b_wait_device_ack_001a = FALSE;
static gboolean msl_b_device_ack_001a_observed = FALSE;
static gboolean msl_b_receive_path_registered = FALSE;
static guint8 msl_b_idle_001a_body[60];
static guint msl_b_idle_001a_body_len = 0;

/* MSL_B_PRE_001A_SEQUENCE_STATE_BEGIN: local session state for the reused
 * P76/P97 RTPC control primitives.  The first target id below is an alias
 * for the channel id already allocated when the R42 media channel open is
 * queued (P76's "allocation_1"); the second is the additional id P76's
 * p76_generate_client_exchange also allocates before it will build client
 * 0x000A/0x001A bodies
 * (entrance_rtpc_control_media_runtime_transform.py:326-363). */
static guint16 msl_b_rtpc_target_1 = 0;
static guint16 msl_b_rtpc_target_2 = 0;
static guint16 msl_b_device_open_target = 0;
static gboolean msl_b_device_response_1_seen = FALSE;
static gboolean msl_b_device_response_2_seen = FALSE;
static guint32 msl_b_seq_000a = 0;
static guint32 msl_b_seq_001a = 0;
static guint8 msl_b_client_000a_body[44];
static guint msl_b_client_000a_body_len = 0;
static gboolean msl_b_device_000a_roles_stored = FALSE;
static guint8 msl_b_device_000a_first_role[9];
static guint8 msl_b_device_000a_second_role[9];
static guint32 msl_b_device_000a_ack_sequence = 0;
static gboolean msl_b_wait_device_ack_000a = FALSE;
static gboolean msl_b_device_ack_000a_observed = FALSE;
/* MSL_B_PRE_001A_SEQUENCE_STATE_END */
static guint msl_b_post_001a_frame_count = 0;
static guint msl_b_post_001a_same_request_id_count = 0;
static guint msl_b_post_001a_body32_count = 0;
static guint msl_b_post_001a_1800_count = 0;
static guint msl_b_ack_request_id_match_count = 0;
static guint msl_b_ack_header_match_count = 0;
static guint msl_b_ack_address_role_match_count = 0;
static guint msl_b_ack_exact_match_count = 0;
static guint msl_b_device_0008_count = 0;
static guint msl_b_device_000a_count = 0;
static guint msl_b_device_response_count = 0;
static guint msl_b_rtpc_open_response_count = 0;
static guint msl_b_ack_reject_wrong_request_id = 0;
static guint msl_b_ack_reject_wrong_length = 0;
static guint msl_b_ack_reject_wrong_prefix = 0;
static guint msl_b_ack_reject_wrong_flags = 0;
static guint msl_b_ack_reject_address_role = 0;
static guint msl_b_ack_reject_other = 0;

/* MSL_B_RTPC_WINDOW_DIAGNOSTICS_BEGIN: bounded, no-payload counters covering
 * only the RTPC-open window (WAIT_DEVICE_OPEN / WAIT_DEVICE_RESPONSES), so a
 * single live attempt shows whether the panel answered at all even if the
 * sequence never reaches 0x000A. Reused from P82's own no-target-id,
 * no-raw-payload diagnostic posture
 * (entrance_p82_rtpc_device_open_shape_transform.py:1-9,84-91). */
static guint msl_b_rtpc_window_inbound_count = 0;
static guint msl_b_rtpc_window_open_schema_count = 0;
static guint msl_b_rtpc_window_response_schema_count = 0;
static guint msl_b_rtpc_window_paired_response_count = 0;
static guint msl_b_rtpc_window_rejected_count = 0;

static void
msl_b_print_rtpc_window_diagnostics(void)
{
    printf("MSL_B_RTPC_WINDOW_INBOUND_COUNT=%u\n", msl_b_rtpc_window_inbound_count);
    printf("MSL_B_RTPC_WINDOW_OPEN_SCHEMA_COUNT=%u\n", msl_b_rtpc_window_open_schema_count);
    printf("MSL_B_RTPC_WINDOW_RESPONSE_SCHEMA_COUNT=%u\n", msl_b_rtpc_window_response_schema_count);
    printf("MSL_B_RTPC_WINDOW_PAIRED_RESPONSE_COUNT=%u\n", msl_b_rtpc_window_paired_response_count);
    printf("MSL_B_RTPC_WINDOW_REJECTED_COUNT=%u\n", msl_b_rtpc_window_rejected_count);
    fflush(stdout);
}
/* MSL_B_RTPC_WINDOW_DIAGNOSTICS_END */

/* MSL_B_PRE_RTPC_ACTIVATION_STATE_BEGIN: local session state for the reused
 * entrance 0x0028/0x0008/0x0002 preamble primitives, generated the same way
 * the pre-001A block above generates its own sequence/role state -- each
 * value is derived from the previous one at runtime, never a literal
 * capture value. */
static guint32 msl_b_seq_0028 = 0;
static guint32 msl_b_seq_client_0008 = 0;
static guint32 msl_b_seq_device_0008_ack = 0;
static guint32 msl_b_seq_device_0002_ack = 0;
static gboolean msl_b_device_0002_observed = FALSE;
static gboolean msl_b_rtpc_begin_started = FALSE;
/* MSL_B_PRE_RTPC_ACTIVATION_STATE_END */

static gboolean r42_queue_media_channel_close(void);

static gboolean msl_b_clock_base_loaded = FALSE;
static gboolean msl_b_clock_base_valid = FALSE;
static gint64 msl_b_clock_base_value = 0;

/* Shared contract with ct120_run_msl_v1_baseline_live.sh's write_clock_base:
 * the runner writes one decimal millisecond value followed by a trailing
 * newline ("<n>\n", via python print()/printf '%s\n').  Accept exactly that
 * -- trailing ASCII whitespace after the digits is well-formed, not corrupt
 * -- so a genuinely missing/malformed file is the only thing that reports
 * invalid. */
static void
msl_b_load_clock_base(void)
{
    const char *base_path;
    gchar *text = NULL;
    gchar *end = NULL;
    gint64 value;

    if (msl_b_clock_base_loaded)
        return;
    msl_b_clock_base_loaded = TRUE;

    base_path = getenv("MSL_B_CLOCK_BASE_FILE");
    if (!base_path || !g_file_get_contents(base_path, &text, NULL, NULL)) {
        printf("MSL_B_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        g_free(text);
        return;
    }

    value = g_ascii_strtoll(text, &end, 10);
    while (end && *end != '\0' && g_ascii_isspace(*end))
        end++;
    if (!end || end == text || *end != '\0' || value <= 0) {
        printf("MSL_B_CLOCK_BASE_INVALID=true\n");
        fflush(stdout);
        g_free(text);
        return;
    }

    msl_b_clock_base_valid = TRUE;
    msl_b_clock_base_value = value;
    printf("MSL_B_CLOCK_BASE_PATH=%s\n", base_path);
    printf("MSL_B_CLOCK_BASE_VALUE=%lld\n", (long long)value);
    fflush(stdout);
    g_free(text);
}

static void
msl_b_print_clock_marker(const char *name)
{
    gint64 now_us = g_get_monotonic_time();
    gint64 base_us;
    gint64 delta_us;

    msl_b_load_clock_base();
    if (!msl_b_clock_base_valid)
        return;
    base_us = msl_b_clock_base_value * 1000;
    delta_us = MAX((gint64)0, now_us - base_us);
    printf("MSL_B_%s_MONO_US=%lld\n", name, (long long)delta_us);
    printf("MSL_B_%s_MONO_MS=%lld\n", name, (long long)(delta_us / 1000));
    fflush(stdout);
}

static gboolean
msl_b_ready_now(void)
{
    return v4_listener_ready && pseudotcp_open && v4_registered && v4_ctpp_channel_id != 0;
}

static void
msl_b_take_ready_snapshot(void)
{
    if (msl_b_ready_snapshot_taken || !msl_b_ready_now())
        return;
    msl_b_ready_snapshot_taken = TRUE;
    msl_b_listener_pid_before = (guint)getpid();
    msl_b_reconnect_count_before = 0;
    printf("MSL_B_LISTENER_READY_BEFORE=true\n");
    printf("MSL_B_LISTENER_PROCESS_PID=%u\n", msl_b_listener_pid_before);
    fflush(stdout);
}

static void
msl_b_print_reuse_counters(void)
{
    msl_b_listener_pid_after = (guint)getpid();
    msl_b_reconnect_count_after = msl_b_reconnect_count_before;
    printf("MSL_B_CLOUD_NEGOTIATION_COUNT=%u\n", msl_b_cloud_negotiation_count_after_ready);
    printf("MSL_B_ICE_BOOTSTRAP_COUNT=%u\n", msl_b_ice_bootstrap_count_after_ready);
    printf("MSL_B_PSEUDOTCP_OPEN_COUNT=%u\n", msl_b_pseudotcp_open_count_after_ready);
    printf("MSL_B_CTPP_REGISTRATION_COUNT=%u\n", msl_b_ctpp_registration_count_after_ready);
    printf("MSL_B_MEDIA_SESSION_COUNT=%u\n", msl_b_media_session_count);
    printf("MSL_B_SECOND_MEDIA_SESSION=%s\n", msl_b_media_session_count > 1 ? "true" : "false");
    printf("MSL_B_LISTENER_PROCESS_PID=%u\n", msl_b_listener_pid_after);
    printf("MSL_B_LISTENER_READY_AFTER=%s\n", msl_b_ready_now() ? "true" : "false");
    printf("MSL_B_RECONNECT_COUNT_BEFORE=%u\n", msl_b_reconnect_count_before);
    printf("MSL_B_RECONNECT_COUNT_AFTER=%u\n", msl_b_reconnect_count_after);
    printf("MSL_B_RECONNECT_COUNT_DELTA=%u\n", msl_b_reconnect_count_after - msl_b_reconnect_count_before);
    printf("MSL_B_MEDIA_RX_ACTIVE=%s\n", msl_b_media_rx_active ? "true" : "false");
    printf("MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE=%s\n", msl_b_media_rx_inactive_after_close ? "true" : "false");
    printf("MSL_B_MEDIA_FORWARDING_INACTIVE=%s\n", p80_media_forwarding_enabled ? "false" : "true");
    printf("MSL_B_VIDEO_RTP_PACKETS=%llu\n", (unsigned long long)p80_video_rtp_packets);
    printf("MSL_B_AUDIO_RTP_PACKETS=%llu\n", (unsigned long long)p80_audio_rtp_packets);
    printf("MSL_B_SPS_COUNT=%llu\n", (unsigned long long)p116_video_rtp.sps_count);
    printf("RESIDUAL_MEDIA_CHANNELS=%u\n", r42_media_channel_id == 0u ? 0u : 1u);
    printf("MSL_B_TUNNEL_PRESERVED=%s\n", pseudotcp_open ? "true" : "false");
    printf("MSL_B_POST_001A_FRAME_COUNT=%u\n", msl_b_post_001a_frame_count);
    printf("MSL_B_POST_001A_SAME_REQUEST_ID_COUNT=%u\n", msl_b_post_001a_same_request_id_count);
    printf("MSL_B_POST_001A_BODY32_COUNT=%u\n", msl_b_post_001a_body32_count);
    printf("MSL_B_POST_001A_1800_COUNT=%u\n", msl_b_post_001a_1800_count);
    printf("MSL_B_ACK_REQUEST_ID_MATCH_COUNT=%u\n", msl_b_ack_request_id_match_count);
    printf("MSL_B_ACK_HEADER_MATCH_COUNT=%u\n", msl_b_ack_header_match_count);
    printf("MSL_B_ACK_ADDRESS_ROLE_MATCH_COUNT=%u\n", msl_b_ack_address_role_match_count);
    printf("MSL_B_ACK_EXACT_MATCH_COUNT=%u\n", msl_b_ack_exact_match_count);
    printf("MSL_B_DEVICE_0008_COUNT=%u\n", msl_b_device_0008_count);
    printf("MSL_B_DEVICE_000A_COUNT=%u\n", msl_b_device_000a_count);
    printf("MSL_B_DEVICE_RESPONSE_COUNT=%u\n", msl_b_device_response_count);
    printf("MSL_B_RTPC_OPEN_RESPONSE_COUNT=%u\n", msl_b_rtpc_open_response_count);
    printf("ACK_REJECT_WRONG_REQUEST_ID=%u\n", msl_b_ack_reject_wrong_request_id);
    printf("ACK_REJECT_WRONG_LENGTH=%u\n", msl_b_ack_reject_wrong_length);
    printf("ACK_REJECT_WRONG_PREFIX=%u\n", msl_b_ack_reject_wrong_prefix);
    printf("ACK_REJECT_WRONG_FLAGS=%u\n", msl_b_ack_reject_wrong_flags);
    printf("ACK_REJECT_ADDRESS_ROLE=%u\n", msl_b_ack_reject_address_role);
    printf("ACK_REJECT_OTHER=%u\n", msl_b_ack_reject_other);
    msl_b_print_rtpc_window_diagnostics();
    fflush(stdout);
}

static gboolean
msl_b_ack_matches_source(const guint8 *body, guint body_len,
                         const guint8 *source, guint source_len,
                         gboolean count_reject)
{
    guint first;
    guint second;

    if (!body || !source || source_len < 20u) {
        if (count_reject)
            msl_b_ack_reject_other++;
        return FALSE;
    }
    if (body_len != 32u) {
        if (count_reject)
            msl_b_ack_reject_wrong_length++;
        return FALSE;
    }
    if (read_le16(body + 0u) != 0x1800u ||
        body[6] != 0x00u || body[7] != 0x00u) {
        if (count_reject)
            msl_b_ack_reject_wrong_prefix++;
        return FALSE;
    }
    msl_b_ack_header_match_count++;
    if (
        body[6] != 0x00u || body[7] != 0x00u ||
        body[8] != 0xffu || body[9] != 0xffu ||
        body[10] != 0xffu || body[11] != 0xffu) {
        if (count_reject)
            msl_b_ack_reject_wrong_flags++;
        return FALSE;
    }

    first = source_len - 20u;
    second = source_len - 10u;
    if (source[first + 9u] != 0x00u || source[second + 9u] != 0x00u) {
        if (count_reject)
            msl_b_ack_reject_other++;
        return FALSE;
    }

    if (memcmp(body + 12u, source + second, 9u) == 0 &&
        body[21] == 0x00u &&
        memcmp(body + 22u, source + first, 9u) == 0 &&
        body[31] == 0x00u) {
        msl_b_ack_address_role_match_count++;
        msl_b_ack_exact_match_count++;
        return TRUE;
    }

    if (count_reject)
        msl_b_ack_reject_address_role++;
    return FALSE;
}

static void
msl_b_note_post_001a_frame(guint32 request_id, const guint8 *body, guint body_len)
{
    guint16 prefix = 0u;
    guint16 action = 0u;

    if (!msl_b_wait_device_ack_001a)
        return;

    msl_b_post_001a_frame_count++;
    if (request_id == v4_ctpp_channel_id) {
        msl_b_post_001a_same_request_id_count++;
        msl_b_ack_request_id_match_count++;
    }
    if (body_len == 32u)
        msl_b_post_001a_body32_count++;
    if (body && body_len >= 2u) {
        prefix = read_le16(body + 0u);
        if (prefix == 0x1800u)
            msl_b_post_001a_1800_count++;
    }
    if (body && body_len >= 8u) {
        action = read_le16(body + 6u);
        if (prefix == 0x1840u && action == 0x0008u)
            msl_b_device_0008_count++;
        if (prefix == 0x1840u && action == 0x000au)
            msl_b_device_000a_count++;
        if (prefix == 0x1800u && action == 0x0000u)
            msl_b_device_response_count++;
    }
    if (request_id == 0u && body && body_len >= 12u &&
        read_le16(body + 0u) == 0xabcdu && read_le16(body + 2u) == 2u)
        msl_b_rtpc_open_response_count++;
}

static gboolean
msl_b_register_receive_path(void)
{
    if (!p80_video_target_ready) {
        p80_video_rtp_fd = p80_loopback_socket(&p80_video_rtp_target, P80_VIDEO_RTP_PORT);
        if (p80_video_rtp_fd < 0) {
            fprintf(stderr, "MSL_B_RTP_FORWARD_SOCKET=FAIL media=video\n");
            return FALSE;
        }
        p80_video_target_ready = TRUE;
    }
    if (!p80_audio_target_ready) {
        p80_audio_rtp_fd = p80_loopback_socket(&p80_audio_rtp_target, P80_AUDIO_RTP_PORT);
        if (p80_audio_rtp_fd < 0) {
            fprintf(stderr, "MSL_B_RTP_FORWARD_SOCKET=FAIL media=audio\n");
            return FALSE;
        }
        p80_audio_target_ready = TRUE;
    }

    msl_b_receive_path_registered = TRUE;
    printf("MSL_B_RECEIVE_PATH_REGISTERED_BEFORE_MEDIA_ACTIVE=true\n");
    fflush(stdout);
    return TRUE;
}

static void
msl_b_dispose_receive_path(void)
{
    if (p80_video_rtp_fd >= 0) {
        close(p80_video_rtp_fd);
        p80_video_rtp_fd = -1;
    }
    if (p80_audio_rtp_fd >= 0) {
        close(p80_audio_rtp_fd);
        p80_audio_rtp_fd = -1;
    }
    p80_video_target_ready = FALSE;
    p80_audio_target_ready = FALSE;
    msl_b_receive_path_registered = FALSE;
}

/* MSL_B_PRE_001A_PRIMITIVES_BEGIN: byte-for-byte reuse of the proven P76/P97
 * wire-format primitives below, rebound to this overlay's own
 * channel/session state instead of the unrelated entrance_signal_stage
 * state machine those transforms were originally written against.  Each
 * function below corresponds 1:1 to one upstream primitive:
 *
 * copy_role       == p78_copy_role
 *     (entrance_p78_rtpc_media_live_stage_transform.py:253-259)
 * build_rtpc_open / rtpc_open_is_valid
 *     == p76_build_rtpc_open / p76_rtpc_open_is_valid
 *     (entrance_rtpc_control_media_runtime_transform.py:217-257)
 * build_rtpc_response / rtpc_response_is_valid
 *     == p76_build_rtpc_response / p76_rtpc_response_is_valid
 *     (entrance_rtpc_control_media_runtime_transform.py:229-266)
 * build_client_000a == p76_build_client_000a
 *     (entrance_rtpc_control_media_runtime_transform.py:268-292)
 * build_client_001a == p76_build_client_001a
 *     (entrance_rtpc_control_media_runtime_transform.py:294-324; the
 *     sequence field is written plain, per P97's own post-ack rebind at
 *     entrance_p97_complete_post_000a_ack_cycle_transform.py:351-355,
 *     instead of P76's pre-rebind advance-sequence helper, since that value
 *     is unconditionally overwritten before transmission either way)
 * store_device_000a_roles == p97_store_device_000a_roles
 *     (entrance_p97_complete_post_000a_ack_cycle_transform.py:230-240)
 *
 * The structural-ACK matcher declared earlier in this overlay is already
 * the same match as p97_ack_matches_source
 * (entrance_p97_complete_post_000a_ack_cycle_transform.py:242-267); it is
 * reused unmodified below against both the 44-byte client 0x000A body and
 * the 60-byte client 0x001A body.
 */
static void
msl_b_copy_role(guint8 out[9], const char *value)
{
    guint i;
    for (i = 0; i < 9; i++)
        out[i] = value[i] ? (guint8)value[i] : 0;
}

static guint
msl_b_build_rtpc_open(guint16 target_id, guint8 out[15])
{
    write_le16(out + 0, 0xABCD);
    write_le16(out + 2, 1);
    write_le32(out + 4, 7);
    memcpy(out + 8, "RTPC", 4);
    write_le16(out + 12, target_id);
    out[14] = 0x01;
    return 15u;
}

static gboolean
msl_b_rtpc_open_is_valid(const guint8 *body, guint len)
{
    return body != NULL && len == 15u &&
        read_le16(body + 0) == 0xABCDu &&
        read_le16(body + 2) == 1u &&
        read_le32(body + 4) == 7u &&
        memcmp(body + 8, "RTPC", 4) == 0 &&
        read_le16(body + 12) != 0u &&
        body[14] == 0x01u;
}

static guint
msl_b_build_rtpc_response(guint16 target_id, guint8 out[12])
{
    write_le16(out + 0, 0xABCD);
    write_le16(out + 2, 2);
    write_le32(out + 4, 4);
    write_le16(out + 8, target_id);
    out[10] = 0x00;
    out[11] = 0x00;
    return 12u;
}

static gboolean
msl_b_rtpc_response_is_valid(const guint8 *body, guint len)
{
    return body != NULL && len == 12u &&
        read_le16(body + 0) == 0xABCDu &&
        read_le16(body + 2) == 2u &&
        read_le32(body + 4) == 4u &&
        read_le16(body + 8) != 0u &&
        body[10] == 0x00u && body[11] == 0x00u;
}

static guint
msl_b_build_client_000a(guint32 sequence, guint16 target_id,
                        const guint8 role_a[9], const guint8 role_b[9],
                        guint8 out[44])
{
    memset(out, 0, 44);
    write_le16(out + 0, 0x1840);
    write_le32(out + 2, sequence);
    out[6] = 0x00; out[7] = 0x0a;
    out[8] = 0x00; out[9] = 0x11;
    out[10] = 0x18; out[11] = 0x02;
    write_le16(out + 16, target_id);
    out[20] = 0xff; out[21] = 0xff; out[22] = 0xff; out[23] = 0xff;
    memcpy(out + 24, role_b, 9);
    out[33] = 0x00;
    memcpy(out + 34, role_a, 9);
    out[43] = 0x00;
    return 44u;
}

static guint
msl_b_build_client_001a(guint32 sequence, guint16 target_id,
                        const guint8 role_a[9], const guint8 role_b[9],
                        guint8 out[60])
{
    memset(out, 0, 60);
    write_le16(out + 0, 0x1840);
    write_le32(out + 2, sequence);
    out[6] = 0x00; out[7] = 0x1a;
    out[8] = 0x00; out[9] = 0x11;
    out[10] = 0x14; out[11] = 0x32;
    write_le16(out + 16, target_id);
    out[18] = 0xff; out[19] = 0xff;
    write_le16(out + 24, 800u);
    write_le16(out + 26, 480u);
    write_le16(out + 28, 320u);
    write_le16(out + 30, 240u);
    write_le16(out + 32, 16u);
    out[36] = 0xff; out[37] = 0xff; out[38] = 0xff; out[39] = 0xff;
    memcpy(out + 40, role_b, 9);
    out[49] = 0x00;
    memcpy(out + 50, role_a, 9);
    out[59] = 0x00;
    return 60u;
}

static gboolean
msl_b_store_device_000a_roles(const guint8 *body, guint body_len)
{
    if (!body || body_len != 44u || body[33] != 0x00u || body[43] != 0x00u)
        return FALSE;
    memcpy(msl_b_device_000a_first_role, body + 24u, 9u);
    memcpy(msl_b_device_000a_second_role, body + 34u, 9u);
    msl_b_device_000a_roles_stored = TRUE;
    return TRUE;
}
/* MSL_B_PRE_001A_PRIMITIVES_END */

/* MSL_B_PRE_RTPC_ACTIVATION_PRIMITIVES_BEGIN: byte-for-byte reuse of the
 * proven entrance self-activation/video-event/device-video-ack/device-0002
 * wire-format primitives below, rebound to this overlay's own
 * already-registered v4_ctpp_channel_id instead of the unrelated
 * entrance_signal_stage state machine those transforms were originally
 * written against.  Each function below corresponds 1:1 to one upstream
 * primitive:
 *
 * build_preamble_0028 == entrance_signal_queue_self_activation's body build
 *     (entrance_self_activation_signaling_transform.py:149-185)
 * preamble_ack_is_valid == entrance_signal_body_is_ack
 *     (entrance_self_activation_signaling_transform.py:100-114; this same
 *     generic device-ACK shape acks both the 0x0028 self-activation and the
 *     client 0x0008 video event, per that transform's own two WAIT_*_ACK
 *     stages sharing one predicate)
 * build_preamble_client_0008 == entrance_signal_queue_video_event's body
 *     build (entrance_self_activation_signaling_transform.py:226-248)
 * device_0008_is_valid == entrance_signal_body_is_device_video
 *     (entrance_self_activation_signaling_transform.py:117-132)
 * build_structural_ack == entrance_signal_queue_device_video_ack's body
 *     build (entrance_device_video_ack_observation_transform.py:222-243),
 *     reused unmodified for the device-0002 ACK too since
 *     p95_queue_device_0002_ack's body
 *     (entrance_p95_wait_device_0002_before_rtpc_transform.py:208-226) is the
 *     identical shape with only the sequence value differing
 * device_0002_is_valid == p95_device_0002_is_valid, minus its own
 *     request_id check (already filtered by the caller below)
 *     (entrance_p95_wait_device_0002_before_rtpc_transform.py:170-187)
 */
static guint
msl_b_build_preamble_0028(guint32 sequence, guint8 out[72])
{
    memset(out, 0, 72);
    write_le16(out + 0, 0x18C0);
    write_le32(out + 2, sequence);
    out[6] = 0x00;
    out[7] = 0x28;
    out[8] = 0x00;
    out[9] = 0x01;

    memcpy(out + 10, V4_FULL_ADDRESS, 9);
    out[19] = 0x00;
    memcpy(out + 20, V4_ENTRANCE, 8);
    out[28] = 0x00;
    out[29] = 0x00;

    out[30] = 0x01;
    out[31] = 0x20;
    out[32] = 0x05;
    out[33] = 0x80;
    out[34] = 0x31;
    out[35] = 0x18;

    memcpy(out + 36, V4_FULL_ADDRESS, 9);
    out[45] = 0x00;
    out[46] = 0x49;
    out[47] = 0x49;
    memset(out + 48, 0xff, 4);
    memcpy(out + 52, V4_FULL_ADDRESS, 9);
    out[61] = 0x00;
    memcpy(out + 62, V4_ENTRANCE, 8);
    out[70] = 0x00;
    out[71] = 0x00;
    return 72u;
}

static gboolean
msl_b_preamble_ack_is_valid(const guint8 *body, guint body_len)
{
    return
        body != NULL &&
        body_len == 32u &&
        read_le16(body + 0) == 0x1800u &&
        body[6] == 0x00u && body[7] == 0x00u &&
        body[8] == 0xffu && body[9] == 0xffu &&
        body[10] == 0xffu && body[11] == 0xffu &&
        memcmp(body + 12, V4_ENTRANCE, 8) == 0 &&
        body[20] == 0x00u && body[21] == 0x00u &&
        memcmp(body + 22, V4_FULL_ADDRESS, 9) == 0 &&
        body[31] == 0x00u;
}

static guint
msl_b_build_preamble_client_0008(guint32 sequence, guint8 out[40])
{
    memset(out, 0, 40);
    write_le16(out + 0, 0x1840);
    write_le32(out + 2, sequence);
    out[6] = 0x00;
    out[7] = 0x08;
    out[8] = 0x00;
    out[9] = 0x03;

    out[10] = 0x49;
    out[11] = 0x00;
    out[12] = 0x27;
    out[13] = 0x00;
    out[14] = 0x00;
    out[15] = 0x00;
    memset(out + 16, 0xff, 4);
    memcpy(out + 20, V4_FULL_ADDRESS, 9);
    out[29] = 0x00;
    memcpy(out + 30, V4_ENTRANCE, 8);
    out[38] = 0x00;
    out[39] = 0x00;
    return 40u;
}

static gboolean
msl_b_device_0008_is_valid(const guint8 *body, guint body_len)
{
    return
        body != NULL &&
        body_len == 40u &&
        read_le16(body + 0) == 0x1840u &&
        body[6] == 0x00u && body[7] == 0x08u &&
        body[8] == 0x00u && body[9] == 0x03u &&
        body[16] == 0xffu && body[17] == 0xffu &&
        body[18] == 0xffu && body[19] == 0xffu &&
        memcmp(body + 20, V4_ENTRANCE, 8) == 0 &&
        body[28] == 0x00u && body[29] == 0x00u &&
        memcmp(body + 30, V4_FULL_ADDRESS, 9) == 0 &&
        body[39] == 0x00u;
}

static guint
msl_b_build_structural_ack(guint32 sequence, guint8 out[32])
{
    memset(out, 0, 32);
    write_le16(out + 0, 0x1800u);
    write_le32(out + 2, sequence);
    out[6] = 0x00u;
    out[7] = 0x00u;
    memset(out + 8, 0xff, 4);
    memcpy(out + 12, V4_FULL_ADDRESS, 9);
    out[21] = 0x00u;
    memcpy(out + 22, V4_ENTRANCE, 8);
    out[30] = 0x00u;
    out[31] = 0x00u;
    return 32u;
}

static gboolean
msl_b_device_0002_is_valid(const guint8 *body, guint body_len)
{
    return
        body != NULL &&
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
/* MSL_B_PRE_RTPC_ACTIVATION_PRIMITIVES_END */

static gboolean msl_b_queue_rtpc_open_1(void);

static gboolean
msl_b_queue_idle_channel_open(void)
{
    guint8 body[72];

    if (r42_media_channel_id != 0u ||
        (r42_media_stage != R42_MEDIA_IDLE && r42_media_stage != R42_MEDIA_CLOSED) ||
        msl_b_idle_state != MSL_B_IDLE_STATE_IDLE) {
        printf("MSL_B_DUPLICATE_START_REJECTED=true\n");
        msl_b_duplicate_start_rejected_count++;
        fflush(stdout);
        return FALSE;
    }
    if (!msl_b_ready_now() || p12_tx_pending) {
        printf("MSL_B_IDLE_START_PRECONDITION=FAIL\n");
        fflush(stdout);
        return FALSE;
    }
    if (g_r35_session.call_transaction_alive || r42_media_stage == R42_MEDIA_ACTIVE) {
        printf("MSL_B_RING_COLLISION_FAIL_CLOSED=true\n");
        msl_b_ring_collision_rejected_count++;
        fflush(stdout);
        return FALSE;
    }

    msl_b_seq_0028 = g_random_int();
    msl_b_build_preamble_0028(msl_b_seq_0028, body);

    msl_b_idle_state = MSL_B_IDLE_STATE_PREAMBLE_0028_TX;
    msl_b_media_session_count++;
    printf("MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true\n");
    printf("MSL_B_SECOND_UPSTREAM_SESSION=false\n");
    msl_b_print_clock_marker("B00_IDLE_MEDIA_REQUEST_RECEIVED");
    msl_b_print_clock_marker("T00_IDLE_MEDIA_REQUEST_ACCEPTED");
    msl_b_print_clock_marker("V3_0028_QUEUED");
    fflush(stdout);
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_PREAMBLE_0028)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

/* MSL_B_PRE_RTPC_ACTIVATION_ORCHESTRATION_BEGIN
 *
 * Proven order reused from entrance_self_activation_signaling_transform.py,
 * entrance_device_video_ack_observation_transform.py, and
 * entrance_p95_wait_device_0002_before_rtpc_transform.py's own composed
 * docstring ("device 0x0008 ACK completion -> wait device 0x0002 -> queue
 * exactly one structural client 0x1800 ACK -> ACK TX completion -> begin the
 * existing RTPC sequence"), preceded by the 0x0028/client-0x0008 exchange
 * from entrance_self_activation_signaling_transform.py's own registration-
 * armed one-shot state machine.  Every step here fires strictly after the
 * previous one's TX completion or matching inbound frame; RTPC OPEN #1
 * (msl_b_queue_rtpc_open_1, declared above and defined below) is reachable
 * only from the last stage, MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX.
 */
static gboolean
msl_b_queue_preamble_client_0008(void)
{
    guint8 body[40];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_0028_ACK || p12_tx_pending)
        return FALSE;

    msl_b_seq_client_0008 = msl_b_seq_0028 + 0x00010000u;
    msl_b_build_preamble_client_0008(msl_b_seq_client_0008, body);

    msl_b_idle_state = MSL_B_IDLE_STATE_PREAMBLE_CLIENT_0008_TX;
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_PREAMBLE_CLIENT_0008)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    msl_b_print_clock_marker("V3_CLIENT_0008_QUEUED");
    return p12_flush_tx();
}

static gboolean
msl_b_queue_ack_device_0008(void)
{
    guint8 body[32];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_0008 || p12_tx_pending)
        return FALSE;

    msl_b_seq_device_0008_ack = msl_b_seq_client_0008 + 0x01010000u;
    msl_b_build_structural_ack(msl_b_seq_device_0008_ack, body);

    msl_b_idle_state = MSL_B_IDLE_STATE_ACK_DEVICE_0008_TX;
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_ACK_DEVICE_0008)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

static gboolean
msl_b_queue_ack_device_0002(void)
{
    guint8 body[32];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_0002 || p12_tx_pending)
        return FALSE;

    msl_b_seq_device_0002_ack = msl_b_seq_device_0008_ack + 0x01000000u;
    msl_b_build_structural_ack(msl_b_seq_device_0002_ack, body);

    msl_b_idle_state = MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX;
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_ACK_DEVICE_0002)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

/* Reuse of entrance_signal_stage's own WAIT_SELF_ACK/WAIT_VIDEO_ACK/
 * WAIT_DEVICE_VIDEO dispatch (entrance_self_activation_signaling_transform.py:
 * 463-493) plus P95's device-0002 retransmit dedup
 * (entrance_p95_wait_device_0002_before_rtpc_transform.py:255-285), rebound
 * to this overlay's msl_b_idle_state instead of entrance_signal_stage. */
static gboolean
msl_b_handle_preamble_frame(guint32 request_id, const guint8 *body, guint body_len)
{
    if (request_id != v4_ctpp_channel_id)
        return FALSE;

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_0028_ACK) {
        if (!msl_b_preamble_ack_is_valid(body, body_len))
            return FALSE;
        msl_b_print_clock_marker("V3_0028_ACK_OBSERVED");
        (void)msl_b_queue_preamble_client_0008();
        return TRUE;
    }

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK) {
        if (!msl_b_preamble_ack_is_valid(body, body_len))
            return FALSE;
        msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_0008;
        msl_b_print_clock_marker("V3_CLIENT_0008_ACK_OBSERVED");
        return TRUE;
    }

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_DEVICE_0008) {
        if (!msl_b_device_0008_is_valid(body, body_len))
            return FALSE;
        msl_b_print_clock_marker("V3_DEVICE_0008_OBSERVED");
        (void)msl_b_queue_ack_device_0008();
        return TRUE;
    }

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_DEVICE_0002) {
        if (!msl_b_device_0002_is_valid(body, body_len))
            return FALSE;
        if (msl_b_device_0002_observed) {
            printf("MSL_B_DEVICE_0002_RETRANSMIT_CONSUMED=true\n");
            fflush(stdout);
            return TRUE;
        }
        msl_b_device_0002_observed = TRUE;
        msl_b_print_clock_marker("V3_DEVICE_0002_OBSERVED");
        (void)msl_b_queue_ack_device_0002();
        return TRUE;
    }

    return FALSE;
}

static gboolean
msl_b_queue_rtpc_open_1(void)
{
    guint8 body[15];
    guint16 seed;
    guint16 channel_id;

    if (msl_b_idle_state != MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX ||
        r42_media_channel_id != 0u ||
        !msl_b_ready_now() || p12_tx_pending)
        return FALSE;
    if (msl_b_rtpc_begin_started) {
        printf("MSL_B_RTPC_BEGIN_DOUBLE_START=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (g_r35_session.call_transaction_alive || r42_media_stage == R42_MEDIA_ACTIVE) {
        printf("MSL_B_RING_COLLISION_FAIL_CLOSED=true\n");
        msl_b_ring_collision_rejected_count++;
        fflush(stdout);
        return FALSE;
    }

    seed = (guint16)(g_random_int() & 0x7fffu);
    channel_id = v4_allocate_channel_id(seed);
    if (channel_id == 0u)
        return FALSE;

    r42_media_channel_id = channel_id;
    msl_b_rtpc_target_1 = channel_id;
    msl_b_build_rtpc_open(channel_id, body);

    msl_b_rtpc_begin_started = TRUE;
    r42_media_stage = R42_MEDIA_CHANNEL_OPEN_TX;
    msl_b_idle_state = MSL_B_IDLE_STATE_CHANNEL_OPEN_TX;
    printf("MSL_B_MEDIA_CHANNEL_ALLOCATED=true\n");
    msl_b_print_clock_marker("B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED");
    msl_b_print_clock_marker("V3_RTPC_BEGIN");
    fflush(stdout);
    if (!p12_queue_vip_frame(0, body, sizeof(body), P12_TX_R42_MEDIA_CHANNEL_OPEN)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}
/* MSL_B_PRE_RTPC_ACTIVATION_ORCHESTRATION_END */

/* MSL_B_PRE_001A_SEQUENCE_ORCHESTRATION_BEGIN
 *
 * Proven order reused from entrance_p78_rtpc_media_live_stage_transform.py
 * and entrance_p97_complete_post_000a_ack_cycle_transform.py's own docstring
 * ("client 0x000A -> device 0x000A -> client structural ACK for device
 * 0x000A -> device structural ACK for client 0x000A -> client 0x001A ->
 * device structural ACK for client 0x001A -> media"), preceded by the
 * RTPC OPEN/RESPONSE exchange from entrance_p78:299-450
 * (p78_begin_rtpc_control / p78_handle_rtpc_control_frame).  Every step here
 * fires strictly after the previous one's TX completion or matching inbound
 * frame; the final 0x001A step (declared further below) is reachable only
 * from the last stage, MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A.
 */
static gboolean msl_b_queue_idle_self_activation(void);

static gboolean
msl_b_queue_rtpc_open_2(void)
{
    guint8 body[15];
    guint16 seed;

    if (msl_b_idle_state != MSL_B_IDLE_STATE_CHANNEL_OPEN_TX ||
        msl_b_rtpc_target_1 == 0u ||
        !msl_b_ready_now() ||
        p12_tx_pending)
        return FALSE;

    seed = (guint16)(g_random_int() & 0x7fffu);
    msl_b_rtpc_target_2 = v4_allocate_channel_id(seed);
    if (msl_b_rtpc_target_2 == 0u || msl_b_rtpc_target_2 == msl_b_rtpc_target_1)
        return FALSE;

    msl_b_build_rtpc_open(msl_b_rtpc_target_2, body);
    msl_b_idle_state = MSL_B_IDLE_STATE_OPEN2_TX;
    if (!p12_queue_vip_frame(0, body, 15u, P12_TX_MSL_B_RTPC_OPEN_2)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

static gboolean
msl_b_queue_rtpc_client_response(guint16 device_target)
{
    guint8 body[12];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN || p12_tx_pending)
        return FALSE;

    msl_b_build_rtpc_response(device_target, body);
    msl_b_idle_state = MSL_B_IDLE_STATE_CLIENT_RESPONSE_TX;
    if (!p12_queue_vip_frame(0, body, 12u, P12_TX_MSL_B_RTPC_CLIENT_RESPONSE)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

static gboolean
msl_b_queue_client_000a(void)
{
    guint8 role_a[9];
    guint8 role_b[9];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES ||
        !msl_b_device_response_1_seen || !msl_b_device_response_2_seen ||
        p12_tx_pending)
        return FALSE;

    msl_b_copy_role(role_a, V4_FULL_ADDRESS);
    msl_b_copy_role(role_b, V4_ENTRANCE);
    msl_b_seq_000a = g_random_int();
    msl_b_client_000a_body_len = msl_b_build_client_000a(
        msl_b_seq_000a, msl_b_rtpc_target_1, role_a, role_b, msl_b_client_000a_body);

    msl_b_idle_state = MSL_B_IDLE_STATE_CLIENT_000A_TX;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            msl_b_client_000a_body,
            msl_b_client_000a_body_len,
            P12_TX_MSL_B_RTPC_CLIENT_000A)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

/* Reuse of P83's request-id-0 classification fix
 * (entrance_p83_rtpc_response_before_open_transform.py:104-186): live
 * evidence showed the device may answer one of the two client RTPC OPENs
 * with a valid RESPONSE before sending its own RTPC OPEN. The prior version
 * of this handler assumed every request-id-0 frame seen in WAIT_DEVICE_OPEN
 * was the device OPEN, so an early RESPONSE failed msl_b_rtpc_open_is_valid
 * and was silently dropped -- losing one of the two pairings the post-000A
 * cycle later requires. This records a target-id match against either the
 * OPEN or the RESPONSE schema before deciding what the frame is. */
static gboolean
msl_b_record_device_response(const guint8 *body)
{
    guint16 target = read_le16(body + 8);

    if (target == msl_b_rtpc_target_1) {
        if (msl_b_device_response_1_seen)
            return FALSE;
        msl_b_device_response_1_seen = TRUE;
    } else if (target == msl_b_rtpc_target_2) {
        if (msl_b_device_response_2_seen)
            return FALSE;
        msl_b_device_response_2_seen = TRUE;
    } else {
        return FALSE;
    }
    msl_b_rtpc_window_paired_response_count++;
    return TRUE;
}

static gboolean
msl_b_handle_rtpc_control_frame(guint32 request_id, const guint8 *body, guint body_len)
{
    if (request_id != 0u)
        return FALSE;
    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN &&
        msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES)
        return FALSE;

    msl_b_rtpc_window_inbound_count++;

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN) {
        if (msl_b_rtpc_response_is_valid(body, body_len)) {
            msl_b_rtpc_window_response_schema_count++;
            if (!msl_b_record_device_response(body)) {
                msl_b_rtpc_window_rejected_count++;
                return TRUE;
            }
            msl_b_print_clock_marker("V3_RTPC_EARLY_DEVICE_RESPONSE_OBSERVED");
            return TRUE;
        }

        if (!msl_b_rtpc_open_is_valid(body, body_len)) {
            msl_b_rtpc_window_rejected_count++;
            return TRUE;
        }
        msl_b_rtpc_window_open_schema_count++;
        msl_b_device_open_target = read_le16(body + 12);
        msl_b_print_clock_marker("B02A_DEVICE_RTPC_OPEN_OBSERVED");
        (void)msl_b_queue_rtpc_client_response(msl_b_device_open_target);
        return TRUE;
    }

    /* MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES */
    if (!msl_b_rtpc_response_is_valid(body, body_len)) {
        msl_b_rtpc_window_rejected_count++;
        return TRUE;
    }
    msl_b_rtpc_window_response_schema_count++;
    if (!msl_b_record_device_response(body)) {
        msl_b_rtpc_window_rejected_count++;
        return TRUE;
    }
    if (!msl_b_device_response_1_seen || !msl_b_device_response_2_seen)
        return TRUE;
    msl_b_print_clock_marker("B02B_DEVICE_RESPONSES_OBSERVED");
    (void)msl_b_queue_client_000a();
    return TRUE;
}

/* Reuse of p97_queue_device_000a_ack's sequence/role derivation
 * (entrance_p97_complete_post_000a_ack_cycle_transform.py:269-337), stripped
 * of the entrance_signal_stage-specific preconditions and timer, bound to
 * msl_b_client_000a_body instead of p78_rtpc_client_000a. */
static gboolean
msl_b_queue_device_000a_ack(void)
{
    guint8 body[32];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_000A ||
        !msl_b_device_000a_roles_stored || p12_tx_pending)
        return FALSE;

    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0x1800);
    msl_b_device_000a_ack_sequence = read_le32(msl_b_client_000a_body + 2u) + 0x01000000u;
    write_le32(body + 2, msl_b_device_000a_ack_sequence);
    body[6] = 0x00;
    body[7] = 0x00;
    memset(body + 8, 0xff, 4u);
    memcpy(body + 12, msl_b_device_000a_second_role, 9u);
    body[21] = 0x00;
    memcpy(body + 22, msl_b_device_000a_first_role, 9u);
    body[31] = 0x00;

    msl_b_idle_state = MSL_B_IDLE_STATE_DEVICE_000A_ACK_TX;
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_DEVICE_000A_ACK)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

/* Reuse of p97_store_device_000a_roles + p97_handle_device_ack's first branch
 * (entrance_p97_complete_post_000a_ack_cycle_transform.py:230-240,397-414):
 * observe the device's own 0x1840/0x000A frame, ack it, then observe the
 * device's structural ACK of our client 0x000A via the existing
 * msl_b_ack_matches_source primitive. */
static gboolean
msl_b_handle_device_000a_cycle(guint32 request_id, const guint8 *body, guint body_len)
{
    if (request_id != v4_ctpp_channel_id)
        return FALSE;

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_DEVICE_000A) {
        if (!msl_b_store_device_000a_roles(body, body_len))
            return FALSE;
        msl_b_print_clock_marker("B02D_DEVICE_000A_OBSERVED");
        (void)msl_b_queue_device_000a_ack();
        return TRUE;
    }

    if (msl_b_idle_state == MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A) {
        if (!msl_b_ack_matches_source(body, body_len,
                                      msl_b_client_000a_body,
                                      msl_b_client_000a_body_len,
                                      FALSE))
            return FALSE;
        msl_b_device_ack_000a_observed = TRUE;
        msl_b_wait_device_ack_000a = FALSE;
        msl_b_print_clock_marker("B02E_DEVICE_ACK_000A_OBSERVED");
        (void)msl_b_queue_idle_self_activation();
        return TRUE;
    }

    return FALSE;
}
/* MSL_B_PRE_001A_SEQUENCE_ORCHESTRATION_END */

static gboolean
msl_b_queue_idle_self_activation(void)
{
    guint8 body[60];
    guint8 role_a[9];
    guint8 role_b[9];

    if (msl_b_idle_state != MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A ||
        !msl_b_device_ack_000a_observed ||
        r42_media_channel_id == 0u ||
        !msl_b_ready_now() ||
        p12_tx_pending)
        return FALSE;

    msl_b_copy_role(role_a, V4_FULL_ADDRESS);
    msl_b_copy_role(role_b, V4_ENTRANCE);
    msl_b_seq_001a = msl_b_device_000a_ack_sequence + 0x00010000u;
    msl_b_idle_001a_body_len = msl_b_build_client_001a(
        msl_b_seq_001a, msl_b_rtpc_target_2, role_a, role_b, body);

    msl_b_idle_state = MSL_B_IDLE_STATE_SELF_ACTIVATION_TX;
    printf("MSL_B_INITIAL_001A_STRUCTURED_FROM_SESSION_STATE=true\n");
    fflush(stdout);
    memcpy(msl_b_idle_001a_body, body, msl_b_idle_001a_body_len);
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            body,
            msl_b_idle_001a_body_len,
            P12_TX_MSL_B_IDLE_SELF_ACTIVATION)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    msl_b_print_clock_marker("B03A_001A_QUEUED");
    memset(body, 0, sizeof(body));
    return p12_flush_tx();
}

static gboolean
msl_b_arm_device_ack_wait(void)
{
    if (msl_b_idle_state != MSL_B_IDLE_STATE_SELF_ACTIVATION_TX)
        return FALSE;
    msl_b_wait_device_ack_001a = TRUE;
    msl_b_device_ack_001a_observed = FALSE;
    printf("MSL_B_DEVICE_ACK_001A_GATE_ARMED=true\n");
    fflush(stdout);
    return TRUE;
}

static gboolean
msl_b_activate_idle_media_after_ack(void)
{
    if (msl_b_idle_state != MSL_B_IDLE_STATE_SELF_ACTIVATION_TX ||
        !msl_b_device_ack_001a_observed)
        return FALSE;
    if (!msl_b_register_receive_path()) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    r42_listener_rtp_arm(1);
    msl_b_media_rx_active = TRUE;
    msl_b_idle_state = MSL_B_IDLE_STATE_ACTIVE;
    r42_media_stage = R42_MEDIA_ACTIVE;
    printf("MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=false\n");
    printf("MSL_B_MEDIA_ACTIVE=true\n");
    msl_b_print_clock_marker("B04_STRUCTURAL_ACK_MEDIA_ACCEPTED");
    msl_b_print_clock_marker("T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE");
    msl_b_print_clock_marker("T15_MEDIA_ACTIVE");
    fflush(stdout);
    return TRUE;
}

static gboolean
msl_b_handle_device_ack_001a(guint32 request_id, const guint8 *body, guint body_len)
{
    if (!msl_b_wait_device_ack_001a)
        return FALSE;

    msl_b_note_post_001a_frame(request_id, body, body_len);
    if (request_id != v4_ctpp_channel_id) {
        msl_b_ack_reject_wrong_request_id++;
        return FALSE;
    }
    if (!msl_b_ack_matches_source(body, body_len,
                                  msl_b_idle_001a_body,
                                  msl_b_idle_001a_body_len,
                                  TRUE))
        return FALSE;

    msl_b_wait_device_ack_001a = FALSE;
    msl_b_device_ack_001a_observed = TRUE;
    msl_b_print_clock_marker("B04_DEVICE_ACK_OBSERVED");
    printf("MSL_B_DEVICE_ACK_001A_OBSERVED=PASS\n");
    fflush(stdout);
    (void)msl_b_activate_idle_media_after_ack();
    return TRUE;
}

static gboolean
msl_b_queue_idle_close(void)
{
    if (msl_b_idle_state != MSL_B_IDLE_STATE_ACTIVE || r42_media_channel_id == 0u) {
        printf("MSL_B_IDLE_STOP_PRECONDITION=FAIL\n");
        msl_b_print_rtpc_window_diagnostics();
        fflush(stdout);
        return FALSE;
    }
    if (p12_tx_pending) {
        printf("MSL_B_IDLE_STOP_WAITING_FOR_TX_SLOT=true\n");
        fflush(stdout);
        return TRUE;
    }
    r42_listener_rtp_arm(0);
    msl_b_dispose_receive_path();
    msl_b_media_rx_active = FALSE;
    msl_b_media_rx_inactive_after_close = TRUE;
    msl_b_rtpc_target_2 = 0;
    msl_b_device_open_target = 0;
    msl_b_device_response_1_seen = FALSE;
    msl_b_device_response_2_seen = FALSE;
    msl_b_device_000a_roles_stored = FALSE;
    msl_b_wait_device_ack_000a = FALSE;
    msl_b_device_ack_000a_observed = FALSE;
    msl_b_idle_state = MSL_B_IDLE_STATE_CLOSE_TX;
    r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_TX;
    printf("MSL_B_MEDIA_CLOSE_REQUESTED=true\n");
    fflush(stdout);
    return r42_queue_media_channel_close() && p12_flush_tx();
}

static gboolean
msl_b_control_poll_cb(gpointer data)
{
    (void)data;
    msl_b_take_ready_snapshot();
    if (!msl_b_start_control_consumed &&
        g_file_test(MSL_B_START_FILE, G_FILE_TEST_EXISTS)) {
        msl_b_start_control_consumed = TRUE;
        unlink(MSL_B_START_FILE);
        (void)msl_b_queue_idle_channel_open();
    }
    if (!msl_b_stop_control_consumed &&
        g_file_test(MSL_B_STOP_FILE, G_FILE_TEST_EXISTS)) {
        msl_b_stop_control_consumed = TRUE;
        unlink(MSL_B_STOP_FILE);
        (void)msl_b_queue_idle_close();
    }
    return G_SOURCE_CONTINUE;
}
/* MSL_V1_IDLE_LISTENER_MEDIA_END */
'''

STATE_REPLACEMENT = STATE_ANCHOR + "\n" + OVERLAY

TX_COMPLETION_OPEN_ANCHOR = """        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\\n");
            fflush(stdout);
            if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\\n");
                fflush(stdout);
            }
            break;"""
TX_COMPLETION_OPEN_REPLACEMENT = """        case P12_TX_MSL_B_PREAMBLE_0028:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_0028_ACK;
            msl_b_print_clock_marker("V3_0028_TX_COMPLETED");
            printf("MSL_B_PREAMBLE_0028_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_PREAMBLE_CLIENT_0008:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK;
            msl_b_print_clock_marker("V3_CLIENT_0008_TX_COMPLETED");
            printf("MSL_B_PREAMBLE_CLIENT_0008_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_ACK_DEVICE_0008:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_0002;
            msl_b_print_clock_marker("V3_DEVICE_0008_ACK_TX_COMPLETED");
            printf("MSL_B_ACK_DEVICE_0008_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_ACK_DEVICE_0002:
            msl_b_print_clock_marker("V3_DEVICE_0002_ACK_TX_COMPLETED");
            printf("MSL_B_ACK_DEVICE_0002_SENT=true\\n");
            fflush(stdout);
            if (!msl_b_queue_rtpc_open_1()) {
                msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
                printf("MSL_B_RTPC_OPEN_1_QUEUE=FAIL\\n");
                fflush(stdout);
            }
            break;

        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\\n");
            fflush(stdout);
            if (msl_b_idle_state == MSL_B_IDLE_STATE_CHANNEL_OPEN_TX) {
                msl_b_print_clock_marker("B01A_RTPC_OPEN_1_SENT");
                if (!msl_b_queue_rtpc_open_2()) {
                    msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
                    printf("MSL_B_RTPC_OPEN_2_QUEUE=FAIL\\n");
                    fflush(stdout);
                }
            } else if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\\n");
                fflush(stdout);
            }
            break;

        case P12_TX_MSL_B_RTPC_OPEN_2:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN;
            msl_b_print_clock_marker("B02_RTPC_MEDIA_OPEN_CONTROL_READY");
            msl_b_print_clock_marker("T12_RTPC_MEDIA_OPEN_CONTROL_READY");
            printf("MSL_B_RTPC_OPEN_2_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_RTPC_CLIENT_RESPONSE:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES;
            printf("MSL_B_RTPC_CLIENT_RESPONSE_SENT=true\\n");
            fflush(stdout);
            if (msl_b_device_response_1_seen && msl_b_device_response_2_seen) {
                msl_b_print_clock_marker("B02B_DEVICE_RESPONSES_OBSERVED");
                if (!msl_b_queue_client_000a()) {
                    msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
                    printf("MSL_B_RTPC_CLIENT_000A_QUEUE=FAIL\\n");
                    fflush(stdout);
                }
            }
            break;

        case P12_TX_MSL_B_RTPC_CLIENT_000A:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_000A;
            msl_b_print_clock_marker("B02C_CLIENT_000A_SENT");
            printf("MSL_B_RTPC_CLIENT_000A_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_DEVICE_000A_ACK:
            msl_b_idle_state = MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A;
            msl_b_wait_device_ack_000a = TRUE;
            msl_b_device_ack_000a_observed = FALSE;
            printf("MSL_B_DEVICE_000A_ACK_SENT=true\\n");
            fflush(stdout);
            break;

        case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:
            msl_b_print_clock_marker("B03B_001A_TX_COMPLETED");
            msl_b_print_clock_marker("T13_INITIAL_001A_SENT");
            (void)msl_b_arm_device_ack_wait();
            break;"""

TX_COMPLETION_CLOSE_ANCHOR = """        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\\n");
            fflush(stdout);
            break;"""
TX_COMPLETION_CLOSE_REPLACEMENT = """        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\\n");
            if (msl_b_idle_state == MSL_B_IDLE_STATE_CLOSE_TX) {
                r42_finish_media_channel_close();
                msl_b_idle_state = MSL_B_IDLE_STATE_CLOSED;
                printf("MSL_B_MEDIA_CHANNEL_CLOSED=true\\n");
                msl_b_print_reuse_counters();
            }
            fflush(stdout);
            break;"""

RTP_VIDEO_ANCHOR = """        if (p80_video_rtp_packets == 1u) {
            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }"""
RTP_VIDEO_REPLACEMENT = """        if (p80_video_rtp_packets == 1u) {
            if (!msl_b_b06_video_marked) {
                msl_b_b06_video_marked = TRUE;
                msl_b_print_clock_marker("B06_FIRST_VIDEO_RTP");
            }
            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }"""

RTP_AUDIO_ANCHOR = """        if (p80_audio_rtp_packets == 1u) {
            printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }"""
RTP_AUDIO_REPLACEMENT = """        if (p80_audio_rtp_packets == 1u) {
            if (!msl_b_b05_audio_marked) {
                msl_b_b05_audio_marked = TRUE;
                msl_b_print_clock_marker("B05_FIRST_AUDIO_RTP");
            }
            printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }"""

H264_RECOVERY_ANCHOR = """        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0)
            stream->first_keyframe_monotonic_ms = now_ms;
        else if (nal_type == 7u)
            stream->sps_count++;
        else if (nal_type == 8u)
            stream->pps_count++;"""
H264_RECOVERY_REPLACEMENT = """        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0)
            stream->first_keyframe_monotonic_ms = now_ms;
        else if (nal_type == 7u)
            stream->sps_count++;
        else if (nal_type == 8u)
            stream->pps_count++;
        if (!msl_b_b07_decodable_marked &&
            stream->sps_count > 0u &&
            stream->first_keyframe_monotonic_ms != 0) {
            msl_b_b07_decodable_marked = TRUE;
            msl_b_print_clock_marker("B07_FIRST_USABLE_SPS_PPS_IDR_RECOVERY_POINT");
        }"""

DEVICE_ACK_HOOK_ANCHOR = """            if (r42_media_stage == R42_MEDIA_CHANNEL_CLOSE_WAIT) {
"""
DEVICE_ACK_HOOK_REPLACEMENT = """            if (msl_b_handle_preamble_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }

            if (msl_b_handle_rtpc_control_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }

            if (msl_b_handle_device_000a_cycle(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }

            if (msl_b_handle_device_ack_001a(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }

            if (r42_media_stage == R42_MEDIA_CHANNEL_CLOSE_WAIT) {
"""

READY_ANCHOR = """                printf(
                    "V4_RING_LISTENER_READY=true\\n"
                );
"""
READY_REPLACEMENT = READY_ANCHOR + """
                msl_b_take_ready_snapshot();
"""

TIMER_ANCHOR = """    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );
"""
TIMER_REPLACEMENT = TIMER_ANCHOR + """
    g_timeout_add(
        100,
        msl_b_control_poll_cb,
        NULL
    );
"""

EXIT_ANCHOR = """    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    fflush(stdout);
"""
EXIT_REPLACEMENT = """    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    msl_b_print_reuse_counters();

    fflush(stdout);
"""


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("MSL_B_REAPPLY_GATE=FAIL")
    candidate = r58.transform(source)
    candidate = _replace_once(candidate, CONTROL_DEFS_ANCHOR, CONTROL_DEFS_REPLACEMENT, "CONTROL")
    candidate = _replace_once(candidate, ENUM_ANCHOR, ENUM_REPLACEMENT, "ENUM")
    candidate = _replace_once(candidate, STATE_ANCHOR, STATE_REPLACEMENT, "STATE")
    candidate = _replace_once(candidate, TX_COMPLETION_OPEN_ANCHOR, TX_COMPLETION_OPEN_REPLACEMENT, "OPEN_COMPLETION")
    candidate = _replace_once(candidate, TX_COMPLETION_CLOSE_ANCHOR, TX_COMPLETION_CLOSE_REPLACEMENT, "CLOSE_COMPLETION")
    candidate = _replace_once(candidate, RTP_VIDEO_ANCHOR, RTP_VIDEO_REPLACEMENT, "B06_VIDEO_RTP")
    candidate = _replace_once(candidate, RTP_AUDIO_ANCHOR, RTP_AUDIO_REPLACEMENT, "B05_AUDIO_RTP")
    candidate = _replace_once(candidate, H264_RECOVERY_ANCHOR, H264_RECOVERY_REPLACEMENT, "B07_H264_RECOVERY")
    candidate = _replace_once(candidate, DEVICE_ACK_HOOK_ANCHOR, DEVICE_ACK_HOOK_REPLACEMENT, "DEVICE_ACK_HOOK")
    candidate = _replace_once(candidate, READY_ANCHOR, READY_REPLACEMENT, "READY")
    candidate = _replace_once(candidate, TIMER_ANCHOR, TIMER_REPLACEMENT, "TIMER")
    candidate = _replace_once(candidate, EXIT_ANCHOR, EXIT_REPLACEMENT, "EXIT")
    _assert_gates(candidate)
    return candidate


def _assert_gates(candidate: str) -> None:
    for marker in (BEGIN, END, "R58_STOP_CLEANUP_BEGIN", "R54_CALL_ADOPTION_LISTENER_BEGIN"):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"MSL_B_MARKER_GATE=FAIL marker={marker}")
    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    forbidden = (
        "nice_agent_new",
        "pseudo_tcp_socket_new",
        "oauth",
        "curl",
        "P12_TX_V4_OPEN_CTPP",
        "P12_TX_AUTH",
        "P12_TX_V4_DOOR_WRITE",
        "p80_media_forwarding_enabled = TRUE",
        "p80_media_forwarding_enabled = FALSE",
    )
    for needle in forbidden:
        if needle in region:
            raise RuntimeError(f"MSL_B_NO_NEW_SESSION_PATH_GATE=FAIL needle={needle}")
    for required in (
        'MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"',
        'MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"',
        "static gboolean r42_queue_media_channel_close(void);",
        "static gboolean msl_b_b05_audio_marked;",
        "static gboolean msl_b_b06_video_marked;",
        "static gboolean msl_b_b07_decodable_marked;",
        "static void msl_b_print_clock_marker(const char *name);",
        "msl_b_ready_now",
        "msl_b_queue_idle_channel_open",
        "msl_b_queue_idle_self_activation",
        "msl_b_arm_device_ack_wait",
        "msl_b_handle_device_ack_001a",
        "msl_b_ack_matches_source",
        "msl_b_register_receive_path",
        "MSL_B_DEVICE_ACK_001A_GATE_ARMED=true",
        "MSL_B_DEVICE_ACK_001A_OBSERVED=PASS",
        "MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=false",
        "MSL_B_RECEIVE_PATH_REGISTERED_BEFORE_MEDIA_ACTIVE=true",
        "r42_listener_rtp_arm(1);",
        "r42_listener_rtp_arm(0);",
        "B00_IDLE_MEDIA_REQUEST_RECEIVED",
        "B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED",
        "B01A_RTPC_OPEN_1_SENT",
        "B02_RTPC_MEDIA_OPEN_CONTROL_READY",
        "B02A_DEVICE_RTPC_OPEN_OBSERVED",
        "B02B_DEVICE_RESPONSES_OBSERVED",
        "B02C_CLIENT_000A_SENT",
        "B02D_DEVICE_000A_OBSERVED",
        "B02E_DEVICE_ACK_000A_OBSERVED",
        "B03A_001A_QUEUED",
        "B03B_001A_TX_COMPLETED",
        "B04_DEVICE_ACK_OBSERVED",
        "B05_FIRST_AUDIO_RTP",
        "B06_FIRST_VIDEO_RTP",
        "B07_FIRST_USABLE_SPS_PPS_IDR_RECOVERY_POINT",
        "MSL_B_POST_001A_FRAME_COUNT",
        "MSL_B_ACK_EXACT_MATCH_COUNT",
        "ACK_REJECT_ADDRESS_ROLE",
        "MSL_B_RING_COLLISION_FAIL_CLOSED=true",
        "MSL_B_DUPLICATE_START_REJECTED=true",
        "MSL_B_SECOND_UPSTREAM_SESSION=false",
        "MSL_B_AUDIO_RTP_PACKETS",
        "MSL_B_MEDIA_FORWARDING_INACTIVE",
        "RESIDUAL_MEDIA_CHANNELS",
        "DOOR",
        "msl_b_queue_rtpc_open_2",
        "msl_b_queue_rtpc_client_response",
        "msl_b_queue_client_000a",
        "msl_b_handle_rtpc_control_frame",
        "msl_b_queue_device_000a_ack",
        "msl_b_handle_device_000a_cycle",
        "msl_b_store_device_000a_roles",
        "msl_b_build_rtpc_open",
        "msl_b_rtpc_open_is_valid",
        "msl_b_build_rtpc_response",
        "msl_b_rtpc_response_is_valid",
        "msl_b_build_client_000a",
        "msl_b_build_client_001a",
        "P12_TX_MSL_B_RTPC_OPEN_2",
        "P12_TX_MSL_B_RTPC_CLIENT_RESPONSE",
        "P12_TX_MSL_B_RTPC_CLIENT_000A",
        "P12_TX_MSL_B_DEVICE_000A_ACK",
        "msl_b_build_preamble_0028",
        "msl_b_preamble_ack_is_valid",
        "msl_b_build_preamble_client_0008",
        "msl_b_device_0008_is_valid",
        "msl_b_build_structural_ack",
        "msl_b_device_0002_is_valid",
        "msl_b_queue_preamble_client_0008",
        "msl_b_queue_ack_device_0008",
        "msl_b_queue_ack_device_0002",
        "msl_b_handle_preamble_frame",
        "msl_b_queue_rtpc_open_1",
        "P12_TX_MSL_B_PREAMBLE_0028",
        "P12_TX_MSL_B_PREAMBLE_CLIENT_0008",
        "P12_TX_MSL_B_ACK_DEVICE_0008",
        "P12_TX_MSL_B_ACK_DEVICE_0002",
        "V3_0028_QUEUED",
        "V3_0028_TX_COMPLETED",
        "V3_0028_ACK_OBSERVED",
        "V3_CLIENT_0008_QUEUED",
        "V3_CLIENT_0008_TX_COMPLETED",
        "V3_CLIENT_0008_ACK_OBSERVED",
        "V3_DEVICE_0008_OBSERVED",
        "V3_DEVICE_0008_ACK_TX_COMPLETED",
        "V3_DEVICE_0002_OBSERVED",
        "V3_DEVICE_0002_ACK_TX_COMPLETED",
        "V3_RTPC_BEGIN",
        "MSL_B_DEVICE_0002_RETRANSMIT_CONSUMED=true",
        "MSL_B_RTPC_BEGIN_DOUBLE_START=true",
    ):
        if required not in candidate:
            raise RuntimeError(f"MSL_B_REQUIRED_GATE=FAIL needle={required}")
    if candidate.count("P12_TX_MSL_B_IDLE_SELF_ACTIVATION") != 3:
        raise RuntimeError("MSL_B_SELF_ACTIVATION_TX_KIND_GATE=FAIL")
    tx_case = candidate.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
    if "msl_b_arm_device_ack_wait()" not in tx_case or "msl_b_activate_idle_media" in tx_case:
        raise RuntimeError("MSL_B_SELF_ACTIVATION_ACK_WAIT_GATE=FAIL")
    ack_handler = candidate.split("msl_b_handle_device_ack_001a(guint32 request_id", 1)[1].split("\n}\n", 1)[0]
    if "msl_b_activate_idle_media_after_ack()" not in ack_handler:
        raise RuntimeError("MSL_B_ACK_ACTIVATION_GATE=FAIL")
    activation = candidate.split("msl_b_activate_idle_media_after_ack(void)\n{", 1)[1].split("\n}\n", 1)[0]
    if not (
        activation.index("msl_b_register_receive_path()") <
        activation.index("r42_listener_rtp_arm(1);") <
        activation.index('printf("MSL_B_MEDIA_ACTIVE=true\\n");')
    ):
        raise RuntimeError("MSL_B_RECEIVE_REGISTER_BEFORE_ACTIVE_GATE=FAIL")
    receive_hook = candidate.split("msl_b_handle_device_ack_001a(request_id, body, body_len)", 1)[1].split(
        "R42_CAPABILITIES_DIAGNOSTICS_BEGIN", 1
    )[0]
    if "p12_consume_post_ack(frame_len);" not in receive_hook:
        raise RuntimeError("MSL_B_DEVICE_ACK_CONSUME_GATE=FAIL")
    close_proto = candidate.index("static gboolean r42_queue_media_channel_close(void);")
    close_call = candidate.index("return r42_queue_media_channel_close() && p12_flush_tx();")
    close_definition = candidate.index("r42_queue_media_channel_close(void)\n{")
    if not (close_proto < close_call < close_definition):
        raise RuntimeError("MSL_B_R42_CLOSE_DECLARATION_ORDER_GATE=FAIL")
    for symbol, use_marker in (
        ("msl_b_b05_audio_marked", "msl_b_b05_audio_marked = TRUE;"),
        ("msl_b_b06_video_marked", "msl_b_b06_video_marked = TRUE;"),
        ("msl_b_b07_decodable_marked", "msl_b_b07_decodable_marked = TRUE;"),
    ):
        decl = candidate.index(f"static gboolean {symbol};")
        use = candidate.index(use_marker)
        if not decl < use:
            raise RuntimeError(f"MSL_B_{symbol.upper()}_DECLARATION_ORDER_GATE=FAIL")
    marker_proto = candidate.index("static void msl_b_print_clock_marker(const char *name);")
    marker_first_use = candidate.index('msl_b_print_clock_marker("B07_FIRST_USABLE_SPS_PPS_IDR_RECOVERY_POINT")')
    marker_definition = candidate.index("msl_b_print_clock_marker(const char *name)\n{")
    if not (marker_proto < marker_first_use < marker_definition):
        raise RuntimeError("MSL_B_CLOCK_MARKER_DECLARATION_ORDER_GATE=FAIL")

    # MSL_B_PRE_001A_SEQUENCE_ORDER_GATE: prove the runtime order of the
    # reused P76/P97 primitives -- device RTPC OPEN -> client RESPONSE ->
    # device RESPONSE(s) -> client 0x000A -> device 0x000A -> client ACK of
    # device 0x000A -> device ACK of client 0x000A -> only then client
    # 0x001A -- via the state-machine dependency chain rather than raw
    # source-text position (function *definitions* and their *call sites*
    # are legitimately interleaved in the file; only each function's own
    # precondition-state/successor-state pair is a runtime-order claim).
    state_enum_region = candidate.split(
        "typedef enum {\n    MSL_B_IDLE_STATE_IDLE = 0,", 1
    )[1].split("} MslBIdleMediaState;", 1)[0]
    ordered_states = (
        "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX",
        "MSL_B_IDLE_STATE_OPEN2_TX",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN",
        "MSL_B_IDLE_STATE_CLIENT_RESPONSE_TX",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES",
        "MSL_B_IDLE_STATE_CLIENT_000A_TX",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_000A",
        "MSL_B_IDLE_STATE_DEVICE_000A_ACK_TX",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A",
        "MSL_B_IDLE_STATE_SELF_ACTIVATION_TX",
    )
    state_positions = [state_enum_region.index(state) for state in ordered_states]
    if state_positions != sorted(state_positions):
        raise RuntimeError("MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL reason=state_enum_out_of_order")

    def _fn_body(name: str) -> str:
        # Match the *definition* ("name(args)\n{"), never a forward
        # prototype ("name(args);") that may textually precede it.
        match = re.search(rf"\b{re.escape(name)}\([^;{{}}]*\)\n\{{", candidate)
        if not match:
            raise RuntimeError(f"MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn={name} reason=definition_not_found")
        return candidate[match.end():].split("\n}\n", 1)[0]

    # Each transition function's precondition names the exact predecessor
    # state, and its own state-write names the exact successor state -- a
    # broken/reordered/removed link here is a runtime-order regression even
    # though every function still individually compiles.
    step_chain = (
        ("msl_b_queue_rtpc_open_2", "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX", "MSL_B_IDLE_STATE_OPEN2_TX"),
        ("msl_b_queue_rtpc_client_response", "MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN", "MSL_B_IDLE_STATE_CLIENT_RESPONSE_TX"),
        ("msl_b_queue_client_000a", "MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES", "MSL_B_IDLE_STATE_CLIENT_000A_TX"),
        ("msl_b_queue_device_000a_ack", "MSL_B_IDLE_STATE_WAIT_DEVICE_000A", "MSL_B_IDLE_STATE_DEVICE_000A_ACK_TX"),
        ("msl_b_queue_idle_self_activation", "MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A", "MSL_B_IDLE_STATE_SELF_ACTIVATION_TX"),
    )
    for fn_name, predecessor, successor in step_chain:
        body = _fn_body(fn_name)
        if predecessor not in body:
            raise RuntimeError(f"MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=missing_precondition:{predecessor}")
        if f"msl_b_idle_state = {successor};" not in body:
            raise RuntimeError(f"MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=missing_successor:{successor}")
        if body.index(predecessor) > body.index(f"msl_b_idle_state = {successor};"):
            raise RuntimeError(f"MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=precondition_after_transition")

    # The two frame-hook dispatchers must also only advance from the correct
    # predecessor wait-state to the correct successor call.
    control_frame_fn = _fn_body("msl_b_handle_rtpc_control_frame")
    if control_frame_fn.index("MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN") > control_frame_fn.index("MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES"):
        raise RuntimeError("MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_rtpc_control_frame reason=wait_states_out_of_order")
    if "msl_b_queue_rtpc_client_response" not in control_frame_fn or "msl_b_queue_client_000a" not in control_frame_fn:
        raise RuntimeError("MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_rtpc_control_frame reason=missing_forward_call")
    device_000a_cycle_body = _fn_body("msl_b_handle_device_000a_cycle")
    if device_000a_cycle_body.index("MSL_B_IDLE_STATE_WAIT_DEVICE_000A") > device_000a_cycle_body.index("MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A"):
        raise RuntimeError("MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_device_000a_cycle reason=wait_states_out_of_order")
    if "msl_b_queue_device_000a_ack" not in device_000a_cycle_body:
        raise RuntimeError("MSL_B_PRE_001A_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_device_000a_cycle reason=missing_forward_call")

    # MSL_B_NO_001A_BEFORE_SEQUENCE_GATE: msl_b_queue_idle_self_activation
    # (which queues P12_TX_MSL_B_IDLE_SELF_ACTIVATION, i.e. 0x001A) must only
    # be callable once the post-000A device ACK has been observed, and its
    # only caller must be the post-000A ACK-cycle handler -- not the R42
    # channel-open completion that used to call it directly.
    self_activation_fn = candidate.split(
        "msl_b_queue_idle_self_activation(void)\n{", 1
    )[1].split("\n}\n", 1)[0]
    if "MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A" not in self_activation_fn:
        raise RuntimeError("MSL_B_NO_001A_BEFORE_SEQUENCE_GATE=FAIL reason=missing_precondition")
    if "msl_b_device_ack_000a_observed" not in self_activation_fn:
        raise RuntimeError("MSL_B_NO_001A_BEFORE_SEQUENCE_GATE=FAIL reason=missing_ack_flag_check")
    open_completion_case = candidate.split("case P12_TX_R42_MEDIA_CHANNEL_OPEN:", 1)[1].split(
        "case P12_TX_MSL_B_RTPC_OPEN_2:", 1
    )[0]
    if "msl_b_queue_idle_self_activation" in open_completion_case:
        raise RuntimeError("MSL_B_NO_001A_BEFORE_SEQUENCE_GATE=FAIL reason=open_completion_still_calls_activation")
    if candidate.count("msl_b_queue_idle_self_activation()") != 1:
        raise RuntimeError("MSL_B_NO_001A_BEFORE_SEQUENCE_GATE=FAIL reason=unexpected_call_count")
    device_000a_cycle_fn = candidate.split(
        "msl_b_handle_device_000a_cycle(guint32 request_id", 1
    )[1].split("\n}\n", 1)[0]
    if "msl_b_queue_idle_self_activation()" not in device_000a_cycle_fn:
        raise RuntimeError("MSL_B_NO_001A_BEFORE_SEQUENCE_GATE=FAIL reason=not_called_from_ack_cycle")

    # MSL_B_RX_AFTER_ACK_GATE: the receive path must still be registered only
    # from msl_b_activate_idle_media_after_ack, which fires only after the
    # (unchanged) 0x001A device-ACK gate -- unaffected by the new pre-001A
    # sequence, re-asserted here for the ordering proof.
    if "msl_b_register_receive_path()" in device_000a_cycle_fn:
        raise RuntimeError("MSL_B_RX_AFTER_ACK_GATE=FAIL reason=receive_path_registered_too_early")

    # MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE: prove the runtime order
    # of the reused entrance 0x0028/0x0008/0x0002 preamble -- 0x0028 ->
    # structural ACK -> client 0x0008 -> structural ACK -> device 0x0008 ->
    # client ACK -> device 0x0002 -> client ACK -- via the same
    # predecessor-state/successor-state dependency-chain technique used for
    # the pre-001A gate above, and that RTPC OPEN #1 is reachable only from
    # the last stage.
    activation_state_enum_region = candidate.split(
        "typedef enum {\n    MSL_B_IDLE_STATE_IDLE = 0,", 1
    )[1].split("} MslBIdleMediaState;", 1)[0]
    ordered_activation_states = (
        "MSL_B_IDLE_STATE_PREAMBLE_0028_TX",
        "MSL_B_IDLE_STATE_WAIT_0028_ACK",
        "MSL_B_IDLE_STATE_PREAMBLE_CLIENT_0008_TX",
        "MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_0008",
        "MSL_B_IDLE_STATE_ACK_DEVICE_0008_TX",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_0002",
        "MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX",
        "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX",
    )
    activation_state_positions = [
        activation_state_enum_region.index(state) for state in ordered_activation_states
    ]
    if activation_state_positions != sorted(activation_state_positions):
        raise RuntimeError(
            "MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL reason=state_enum_out_of_order"
        )

    activation_step_chain = (
        ("msl_b_queue_preamble_client_0008", "MSL_B_IDLE_STATE_WAIT_0028_ACK", "MSL_B_IDLE_STATE_PREAMBLE_CLIENT_0008_TX"),
        ("msl_b_queue_ack_device_0008", "MSL_B_IDLE_STATE_WAIT_DEVICE_0008", "MSL_B_IDLE_STATE_ACK_DEVICE_0008_TX"),
        ("msl_b_queue_ack_device_0002", "MSL_B_IDLE_STATE_WAIT_DEVICE_0002", "MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX"),
        ("msl_b_queue_rtpc_open_1", "MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX", "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX"),
    )
    for fn_name, predecessor, successor in activation_step_chain:
        body = _fn_body(fn_name)
        if predecessor not in body:
            raise RuntimeError(
                f"MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=missing_precondition:{predecessor}"
            )
        if f"msl_b_idle_state = {successor};" not in body:
            raise RuntimeError(
                f"MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=missing_successor:{successor}"
            )
        if body.index(predecessor) > body.index(f"msl_b_idle_state = {successor};"):
            raise RuntimeError(
                f"MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL fn={fn_name} reason=precondition_after_transition"
            )

    preamble_frame_fn = _fn_body("msl_b_handle_preamble_frame")
    preamble_wait_order = (
        "MSL_B_IDLE_STATE_WAIT_0028_ACK",
        "MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_0008",
        "MSL_B_IDLE_STATE_WAIT_DEVICE_0002",
    )
    preamble_wait_positions = [preamble_frame_fn.index(state) for state in preamble_wait_order]
    if preamble_wait_positions != sorted(preamble_wait_positions):
        raise RuntimeError(
            "MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_preamble_frame reason=wait_states_out_of_order"
        )
    for forward_call in (
        "msl_b_queue_preamble_client_0008",
        "msl_b_queue_ack_device_0008",
        "msl_b_queue_ack_device_0002",
    ):
        if forward_call not in preamble_frame_fn:
            raise RuntimeError(
                f"MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER_GATE=FAIL fn=msl_b_handle_preamble_frame reason=missing_forward_call:{forward_call}"
            )

    # MSL_B_DEVICE_0002_RETRANSMIT_NO_DOUBLE_RTPC_GATE: a retransmitted
    # device 0x0002 must be consumed without a second ACK or a second RTPC
    # begin -- the dedup check must precede the ACK-queue call, exactly like
    # P95's own retransmit branch.
    device_0002_branch = preamble_frame_fn.split(
        "MSL_B_IDLE_STATE_WAIT_DEVICE_0002) {", 1
    )[1]
    if device_0002_branch.index("msl_b_device_0002_observed") > device_0002_branch.index(
        "msl_b_queue_ack_device_0002()"
    ):
        raise RuntimeError(
            "MSL_B_DEVICE_0002_RETRANSMIT_NO_DOUBLE_RTPC_GATE=FAIL reason=dedup_check_after_ack_queue"
        )

    # MSL_B_RTPC_BEGIN_ONCE_GATE: msl_b_queue_rtpc_open_1 -- which queues
    # P12_TX_R42_MEDIA_CHANNEL_OPEN, the actual RTPC-begin transition -- must
    # only be callable once (msl_b_rtpc_begin_started dedup) and its only
    # caller must be the post-preamble ACK_DEVICE_0002 TX completion, not the
    # preamble entry point itself.
    rtpc_open_1_fn = _fn_body("msl_b_queue_rtpc_open_1")
    if "msl_b_rtpc_begin_started" not in rtpc_open_1_fn:
        raise RuntimeError("MSL_B_RTPC_BEGIN_ONCE_GATE=FAIL reason=missing_dedup_flag")
    if candidate.count("msl_b_queue_rtpc_open_1()") != 1:
        raise RuntimeError("MSL_B_RTPC_BEGIN_ONCE_GATE=FAIL reason=unexpected_call_count")
    channel_open_entry_fn = candidate.split(
        "msl_b_queue_idle_channel_open(void)\n{", 1
    )[1].split("\n}\n", 1)[0]
    if "msl_b_queue_rtpc_open_1" in channel_open_entry_fn:
        raise RuntimeError(
            "MSL_B_RTPC_BEGIN_ONCE_GATE=FAIL reason=entry_point_still_calls_rtpc_open_1_directly"
        )
    ack_device_0002_tx_case = candidate.split(
        "case P12_TX_MSL_B_ACK_DEVICE_0002:", 1
    )[1].split("break;", 1)[0]
    if "msl_b_queue_rtpc_open_1()" not in ack_device_0002_tx_case:
        raise RuntimeError(
            "MSL_B_RTPC_BEGIN_ONCE_GATE=FAIL reason=not_called_from_ack_device_0002_tx_completion"
        )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT MSL V1 VARIANT B IDLE LISTENER MEDIA TRANSFORM ===",
            "CHAIN=R58_R54_R42B_R42_R37",
            "MEDIA_OPEN_EXECUTION_SITE=listener_process",
            "CONTROL_SURFACE=/run/comelit-p2p/msl-b-start-idle-media,/run/comelit-p2p/msl-b-stop-idle-media",
            "NO_NEW_UPSTREAM_SESSION=true",
            "RING_COLLISION_POLICY=reject_busy_fail_closed",
            "DOOR_ACTION_SENT=false",
            "GATE_ACTION_SENT=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "LIVE_INVOCATIONS=0",
            "=== END COMELIT MSL V1 VARIANT B IDLE LISTENER MEDIA TRANSFORM ===",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        print(report())
        return

    generated = transform(args.source.read_text(encoding="utf-8"))
    if args.output:
        args.output.write_text(generated, encoding="utf-8")
    else:
        print(generated, end="")


if __name__ == "__main__":
    main()
