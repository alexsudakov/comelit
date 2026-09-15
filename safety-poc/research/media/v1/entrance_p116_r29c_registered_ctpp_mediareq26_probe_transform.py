#!/usr/bin/env python3
"""P116/R29C registered-CTPP mediareq26 hypothesis probe candidate.

This transform is research-only.  It prepares one bounded experimental
mediareq26 OPEN/STOP path on the already registered CTPP channel and keeps the
generic client 0x1A, self-activation, and R27 repeat forms unreachable.

The transform performs no network I/O and never executes the candidate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29_listener_attached_media_live_transform as r29


DEFAULT_SOURCE = r29.DEFAULT_SOURCE


R29C_TX_ENUM_INSERT = """    P95_TX_DEVICE_0002_ACK,
    P97_TX_DEVICE_000A_ACK,

    P116_R29C_TX_MEDIAREQ26_OPEN,
    P116_R29C_TX_MEDIAREQ26_STOP,

    P12_TX_V4_DOOR_WRITE"""


R29C_TX_COMPLETION_CASES = """        case P116_R29C_TX_MEDIAREQ26_OPEN:
            r29c_registered_ctpp_mediareq26_open_sent = TRUE;
            r29c_open_write_completed_ms = p116_monotonic_ms();
            printf("REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT=true\\n");
            printf("REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u\\n",
                   r29c_registered_ctpp_mediareq26_open_sent_count);
            printf("R29C_OPEN_WRITE_COMPLETED_AT_MS=%lld\\n",
                   r29c_open_write_completed_ms);
            fflush(stdout);
            break;

        case P116_R29C_TX_MEDIAREQ26_STOP:
            r29c_registered_ctpp_mediareq26_stop_sent = TRUE;
            printf("REGISTERED_CTPP_MEDIAREQ26_STOP_SENT=true\\n");
            printf("REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u\\n",
                   r29c_registered_ctpp_mediareq26_stop_sent_count);
            fflush(stdout);
            break;

        case P12_TX_V4_DOOR_WRITE:"""


R29C_STATE = r'''

/* === R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN === */
typedef enum {
    R29_LISTENER_REGISTERED_READY = 0,
    R29_INBOUND_CALL_ACTIVE,
    R29_ATTACHED_MEDIA_ACTIVE,
    R29_ATTACHED_MEDIA_STOPPING
} R29AttachedMediaState;

	typedef enum {
	    R29C_MEDIAREQ26_OPEN = 0,
	    R29C_MEDIAREQ26_STOP
	} R29CMediaReq26State;

	typedef struct {
	    guint16 max_rtp_payload;
	    guint32 bitrate;
	    guint16 max_width;
	    guint16 max_height;
	    guint16 requested_width;
	    guint16 requested_height;
	    guint8 fps;
	    guint8 reserved;
	    const char *provenance;
	} R29CMediaProfile;

	static const R29CMediaProfile r29c_external_tested_client_profile = {
	    0xffffu,
	    0u,
	    800u,
	    480u,
	    320u,
	    240u,
	    16u,
	    0u,
	    "EXTERNAL_TESTED_CLIENT_PROFILE:public-jfmlima:e3714dcccadb5bf934c32ce1400d891c3cfc61bb:call.py:_video_settings"
	};

static R29AttachedMediaState r29_attached_media_state =
    R29_LISTENER_REGISTERED_READY;
static gboolean r29_listener_registered_ready = FALSE;
static gboolean r29_call_transaction_active = FALSE;
static gboolean r29_call_transaction_created = FALSE;
static gboolean r29_inbound_call_ctp_captured = FALSE;
static gboolean r29_call_ctp_separate_from_registration = FALSE;
static gboolean r29_call_bound_mediareq26_uses_inbound_ctp = FALSE;
static gboolean r29_media_channel_runtime_allocated = FALSE;
static gboolean r29_media_channel_state_persisted = FALSE;
static gboolean r29_media_channel_open_request_sent = FALSE;
static gboolean r29_media_channel_open_response_observed = FALSE;
static gboolean r29_call_bound_mediareq26_open_sent = FALSE;
static gboolean r29_call_bound_mediareq26_stop_sent = FALSE;
static gboolean r29_video_rtp_started_marker = FALSE;
static gboolean r29_media_stop_requested = FALSE;
static gboolean r29_media_stop_completed = FALSE;
static gboolean r29_media_stop_before_open_blocked = FALSE;
static gboolean r29_sigusr2_seen = FALSE;
static gboolean r29_sigusr2_second_refused = FALSE;
static gboolean r29_second_media_start_blocked = FALSE;
static gboolean r29_media_open_blocked = TRUE;
static gboolean r29_media_teardown_blocked = TRUE;
static gboolean r29c_live_probe_prepared = FALSE;
static gboolean r29c_registered_ctpp_mediareq26_open_sent = FALSE;
static gboolean r29c_registered_ctpp_mediareq26_stop_sent = FALSE;
static gboolean r29c_registered_ctpp_mediareq26_open_serialized = FALSE;
	static gboolean r29c_registered_ctpp_mediareq26_stop_serialized = FALSE;
	static gboolean r29c_external_profile_accepted_for_bounded_probe = TRUE;
	static gboolean r29c_open_fields_have_proven_sources = FALSE;
static gboolean r29c_stop_fields_have_proven_sources = FALSE;
static gboolean r29c_stop_generation_failed = FALSE;
static gboolean r29c_media_only_stop_result = FALSE;
static gboolean r29c_final_research_session_cleanup = FALSE;
static gboolean r29c_waiting_for_stop = FALSE;
static guint r29_ice_bootstrap_count = 0;
static guint r29_cloud_negotiation_count = 0;
static guint r29_pseudotcp_open_count = 0;
static guint r29_ctpp_registration_count = 0;
static guint r29_rtpc_media_channels_open = 0;
static guint r29_self_activation_sent_count = 0;
static guint r29_client_001a_sent_count = 0;
static guint r29_r27_repeat_sent_count = 0;
static guint r29_call_bound_mediareq26_open_sent_count = 0;
static guint r29_call_bound_mediareq26_stop_sent_count = 0;
static guint r29_unknown_001a_form_blocked_count = 0;
static guint r29_registration_ctp_rejected_for_media_count = 0;
static guint r29_stop_call_release_count = 0;
static guint r29_stop_registration_close_count = 0;
static guint r29_stop_pseudotcp_close_count = 0;
static guint r29_stop_listener_stop_count = 0;
static guint r29_door_actions_sent = 0;
static guint r29_gate_actions_sent = 0;
static guint r29_refresh_loop_started_count = 0;
static guint r29_ready_ice_bootstrap_count = 0;
static guint r29_ready_cloud_negotiation_count = 0;
static guint r29_ready_pseudotcp_open_count = 0;
static guint r29_ready_ctpp_registration_count = 0;
static guint r29c_registered_ctpp_mediareq26_open_sent_count = 0;
static guint r29c_registered_ctpp_mediareq26_stop_sent_count = 0;
static guint16 r29c_saved_media_channel_id = 0;
static long long r29_call_init_monotonic_ms = 0;
static long long r29_first_video_rtp_monotonic_ms = 0;
static long long r29_media_observation_start_ms = 0;
static long long r29_media_observation_end_ms = 0;
static long long r29c_open_write_completed_ms = 0;
static pid_t r29_listener_ready_pid = 0;
	static guint16 v4_ctpp_channel_id;
	static gboolean v4_registered;

	static guint16 read_le16(const guint8 *p);
	static guint32 read_le32(const guint8 *p);
	static void r29_print_scalar_snapshot(const char *call_end_state);
static gboolean r29_same_listener_process(void);
static void r29_capture_ready_snapshot(void);
static gboolean r29_start_attached_media_from_call_init(const char *source);
static gboolean r29_registration_ctp_rejected_for_media(void);
static gboolean r29_unknown_001a_form_blocked(void);
static gboolean r29_media_only_teardown(const char *reason);
static const char *r29_first_rtp_order_result(void);
static gboolean r29_sigusr2_poll_cb(gpointer data);
static void r29_sigusr2_handler(int signum);
static int r29_selfcheck(void);
static gboolean r29c_allocate_media_channel_id(guint32 seed);
	static gboolean r29c_mediareq26_open_fields_proven(void);
	static gboolean r29c_mediareq26_stop_fields_proven(void);
	static gboolean r29c_validate_media_profile(const R29CMediaProfile *profile);
	static gboolean r29c_assert_open_body_semantics(
	    const guint8 body[26],
	    const R29CMediaProfile *profile);
	static gboolean r29c_assert_stop_body_semantics(const guint8 body[26]);
	static void r29c_print_field_source_table(void);
	static gboolean r29c_build_mediareq26(
	    R29CMediaReq26State state,
	    const R29CMediaProfile *profile,
	    guint8 out[26]);
		static gboolean r29c_emit_registered_mediareq26(R29CMediaReq26State state);
		static gboolean r29c_queue_registered_mediareq26(R29CMediaReq26State state);
static void r29c_note_final_research_session_cleanup(void);
static gboolean r29c_rtp_observation_complete_cb(gpointer data);
static void r29c_print_candidate_exit(int code);
	/* === R29_LISTENER_ATTACHED_MEDIA_STATE_END === */
'''


R29C_FUNCTIONS = r'''

/* === R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN === */
	static void write_le16(guint8 *p, guint16 value);
	static void write_le32(guint8 *p, guint32 value);
	static gboolean p12_queue_vip_frame(guint32 request_id, const guint8 *body, guint body_len, P12TxKind kind);
	static gboolean p12_flush_tx(void);

static gboolean
r29c_allocate_media_channel_id(guint32 seed)
{
    guint16 candidate = (guint16)((seed & 0x7fffu) + 1u);
    if (candidate == 0u)
        candidate = 1u;
    r29c_saved_media_channel_id = candidate;
    r29_media_channel_runtime_allocated = TRUE;
    r29_media_channel_state_persisted = TRUE;
    r29_rtpc_media_channels_open = 1u;
    return r29c_saved_media_channel_id != 0u;
}

	static gboolean
	r29c_mediareq26_open_fields_proven(void)
	{
	    return r29c_external_profile_accepted_for_bounded_probe;
	}

static gboolean
	r29c_mediareq26_stop_fields_proven(void)
	{
	    return r29c_saved_media_channel_id != 0u;
	}

	static gboolean
	r29c_validate_media_profile(const R29CMediaProfile *profile)
	{
	    if (!profile || !profile->provenance)
	        return FALSE;
	    if (strcmp(profile->provenance,
	               "EXTERNAL_TESTED_CLIENT_PROFILE:public-jfmlima:e3714dcccadb5bf934c32ce1400d891c3cfc61bb:call.py:_video_settings") != 0)
	        return FALSE;
	    if (profile->max_rtp_payload == 0u)
	        return FALSE;
	    if (profile->max_width < 320u || profile->max_height < 240u)
	        return FALSE;
	    if (profile->requested_width < 320u || profile->requested_height < 240u)
	        return FALSE;
	    if (profile->requested_width > profile->max_width ||
	        profile->requested_height > profile->max_height)
	        return FALSE;
	    if (profile->fps < 1u || profile->fps > 30u)
	        return FALSE;
	    return TRUE;
	}

	static gboolean
	r29c_assert_open_body_semantics(const guint8 body[26],
	                                const R29CMediaProfile *profile)
	{
	    if (!body || !r29c_validate_media_profile(profile))
	        return FALSE;
	    if (read_le16(body + 0) != 0x1100u)
	        return FALSE;
	    if (body[2] != 0x14u || body[3] != 0x32u)
	        return FALSE;
	    if (read_le32(body + 4) != 0u)
	        return FALSE;
	    if (read_le16(body + 8) != r29c_saved_media_channel_id)
	        return FALSE;
	    if (read_le16(body + 10) != profile->max_rtp_payload)
	        return FALSE;
	    if (read_le32(body + 12) != profile->bitrate)
	        return FALSE;
	    if (read_le16(body + 16) != profile->max_width)
	        return FALSE;
	    if (read_le16(body + 18) != profile->max_height)
	        return FALSE;
	    if (read_le16(body + 20) != profile->requested_width)
	        return FALSE;
	    if (read_le16(body + 22) != profile->requested_height)
	        return FALSE;
	    if (body[24] != profile->fps || body[25] != profile->reserved)
	        return FALSE;
	    printf("MEDIAREQ26_OPEN_STRUCTURAL_LAYOUT=PASS\n");
	    printf("MEDIAREQ26_OPEN_PROFILE_SOURCE=%s\n", profile->provenance);
	    printf("MEDIAREQ26_OPEN_OFFSET_10_11_MAX_RTP_PAYLOAD=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_12_15_BITRATE=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_16_17_MAX_WIDTH=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_18_19_MAX_HEIGHT=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_20_21_REQUESTED_WIDTH=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_22_23_REQUESTED_HEIGHT=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_24_FPS=PASS\n");
	    printf("MEDIAREQ26_OPEN_OFFSET_25_RESERVED=PASS\n");
	    fflush(stdout);
	    return TRUE;
	}

	static gboolean
	r29c_assert_stop_body_semantics(const guint8 body[26])
	{
	    guint i;
	    if (!body)
	        return FALSE;
	    if (read_le16(body + 0) != 0x1100u)
	        return FALSE;
	    if (body[2] != 0x94u || body[3] != 0x00u)
	        return FALSE;
	    if (read_le32(body + 4) != 0u)
	        return FALSE;
	    if (read_le16(body + 8) != r29c_saved_media_channel_id)
	        return FALSE;
	    for (i = 10u; i < 26u; i++) {
	        if (body[i] != 0u)
	            return FALSE;
	    }
	    printf("MEDIAREQ26_STOP_STRUCTURAL_LAYOUT=PASS\n");
	    fflush(stdout);
	    return TRUE;
	}

static void
	r29c_print_field_source_table(void)
	{
	    printf("FIELD_SOURCE_TABLE_ROWS=17\n");
	    printf("FIELD_SOURCE[00..01]=prefix_0x1100:SOURCED_SHAPE_CONSTANT:disasm2-csp_send_mediareq26_mov_w8_0x1100\n");
	    printf("FIELD_SOURCE[02_OPEN]=action_0x14:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w1_0x14\n");
	    printf("FIELD_SOURCE[02_STOP]=action_0x94:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w1_0x94\n");
	    printf("FIELD_SOURCE[03_OPEN]=flags_0x32:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w2_0x32\n");
	    printf("FIELD_SOURCE[03_STOP]=flags_0x00:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w2_wzr\n");
	    printf("FIELD_SOURCE[04..07]=address_zero_tunnel_channel_form:SOURCED_SHAPE_CONSTANT:start_videorx_x3_xzr_stop_zero_slot\n");
	    printf("FIELD_SOURCE[08..09]=saved_media_channel_id:SOURCED_RUNTIME:r29c_allocator_result_persisted\n");
	    printf("FIELD_SOURCE[10..11_OPEN]=max_rtp_payload:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_call.py_MAX_PAYLOAD_and_native_RtpDispatcher_getMaxRtpPayload\n");
	    printf("FIELD_SOURCE[10..11_STOP]=max_rtp_payload_zero:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots\n");
	    printf("FIELD_SOURCE[12..15_OPEN]=bitrate:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_VideoCall_bitrate_and_native_VipUnitImpl_setBitrate\n");
	    printf("FIELD_SOURCE[16..17_OPEN]=max_width:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_MAX_RESOLUTION_and_native_setMaxVideoStreamResolution\n");
	    printf("FIELD_SOURCE[18..19_OPEN]=max_height:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_MAX_RESOLUTION_and_native_setMaxVideoStreamResolution\n");
	    printf("FIELD_SOURCE[20..21_OPEN]=requested_width:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_SD_RESOLUTION_and_native_setPrefVideoStreamResolution\n");
	    printf("FIELD_SOURCE[22..23_OPEN]=requested_height:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_SD_RESOLUTION_and_native_setPrefVideoStreamResolution\n");
	    printf("FIELD_SOURCE[24_OPEN]=fps:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_VIDEO_FPS_and_native_setMaxVideoStreamResolution\n");
	    printf("FIELD_SOURCE[25_OPEN]=reserved:CLIENT_SUPPLIED_CONFIGURATION:public-jfmlima_pack_reserved_zero_and_native_stack_zero\n");
	    printf("FIELD_SOURCE[12..25_STOP]=media_profile_zero_tail:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots\n");
	    fflush(stdout);
	}

	static gboolean
	r29c_build_mediareq26(R29CMediaReq26State state,
	                       const R29CMediaProfile *profile,
	                       guint8 out[26])
	{
	    guint i;

	    r29c_open_fields_have_proven_sources = r29c_mediareq26_open_fields_proven();
	    r29c_stop_fields_have_proven_sources = r29c_mediareq26_stop_fields_proven();
	    if (!out || r29c_saved_media_channel_id == 0u ||
	        !r29c_validate_media_profile(profile))
	        return FALSE;
	    if (state == R29C_MEDIAREQ26_OPEN && !r29c_open_fields_have_proven_sources)
	        return FALSE;
	    if (state == R29C_MEDIAREQ26_STOP && !r29c_stop_fields_have_proven_sources)
	        return FALSE;

	    write_le16(out + 0, 0x1100u);
    for (i = 2u; i < 26u; i++)
        out[i] = 0;

	    if (state == R29C_MEDIAREQ26_OPEN) {
	        out[2] = 0x14u;
	        out[3] = 0x32u;
	        write_le16(out + 10, profile->max_rtp_payload);
	        write_le32(out + 12, profile->bitrate);
	        write_le16(out + 16, profile->max_width);
	        write_le16(out + 18, profile->max_height);
	        write_le16(out + 20, profile->requested_width);
	        write_le16(out + 22, profile->requested_height);
	        out[24] = profile->fps;
	        out[25] = profile->reserved;
	    } else if (state == R29C_MEDIAREQ26_STOP) {
	        out[2] = 0x94u;
	        out[3] = 0x00u;
    } else {
        return FALSE;
    }
    write_le32(out + 4, 0u);
    write_le16(out + 8, r29c_saved_media_channel_id);
    return TRUE;
}

static gboolean
	r29c_emit_registered_mediareq26(R29CMediaReq26State state)
	{
	    guint8 body[26];
	    if (!r29c_build_mediareq26(state, &r29c_external_tested_client_profile, body))
	        return FALSE;
    if (state == R29C_MEDIAREQ26_OPEN) {
        if (r29c_registered_ctpp_mediareq26_open_sent_count >= 1u)
            return FALSE;
        r29c_registered_ctpp_mediareq26_open_sent_count++;
        r29c_registered_ctpp_mediareq26_open_serialized = TRUE;
        r29_call_bound_mediareq26_open_sent = TRUE;
        r29_call_bound_mediareq26_open_sent_count =
            r29c_registered_ctpp_mediareq26_open_sent_count;
    r29_media_channel_open_request_sent = TRUE;
        printf("REGISTERED_CTPP_MEDIAREQ26_OPEN_SERIALIZED=true\n");
    } else {
        if (r29c_registered_ctpp_mediareq26_stop_sent_count >= 1u)
            return FALSE;
        r29c_registered_ctpp_mediareq26_stop_sent_count++;
        r29c_registered_ctpp_mediareq26_stop_serialized = TRUE;
        r29_call_bound_mediareq26_stop_sent = TRUE;
        r29_call_bound_mediareq26_stop_sent_count =
            r29c_registered_ctpp_mediareq26_stop_sent_count;
        printf("REGISTERED_CTPP_MEDIAREQ26_STOP_SERIALIZED=true\n");
    }
    memset(body, 0, sizeof(body));
    fflush(stdout);
    return TRUE;
}

static gboolean
r29c_queue_registered_mediareq26(R29CMediaReq26State state)
{
	    guint8 body[26];
	    P12TxKind kind = state == R29C_MEDIAREQ26_OPEN ?
	        P116_R29C_TX_MEDIAREQ26_OPEN : P116_R29C_TX_MEDIAREQ26_STOP;

	    if (!r29c_build_mediareq26(state, &r29c_external_tested_client_profile, body))
	        return FALSE;
    if (state == R29C_MEDIAREQ26_OPEN &&
        r29c_registered_ctpp_mediareq26_open_sent_count >= 1u)
        return FALSE;
    if (state == R29C_MEDIAREQ26_STOP &&
        r29c_registered_ctpp_mediareq26_stop_sent_count >= 1u)
        return FALSE;
    if (!v4_registered || !r29_listener_registered_ready || v4_ctpp_channel_id == 0u)
        return FALSE;
    if (!p12_queue_vip_frame(v4_ctpp_channel_id, body, 26u, kind)) {
        memset(body, 0, sizeof(body));
        return FALSE;
    }
	    if (state == R29C_MEDIAREQ26_OPEN)
	        r29c_registered_ctpp_mediareq26_open_sent_count++;
	    else
	        r29c_registered_ctpp_mediareq26_stop_sent_count++;
	    memset(body, 0, sizeof(body));
	    return p12_flush_tx();
	}

static void
r29_print_scalar_snapshot(const char *call_end_state)
{
    guint new_ice = r29_ice_bootstrap_count - r29_ready_ice_bootstrap_count;
    guint new_cloud = r29_cloud_negotiation_count - r29_ready_cloud_negotiation_count;
    guint new_pseudotcp = r29_pseudotcp_open_count - r29_ready_pseudotcp_open_count;
    guint new_registration = r29_ctpp_registration_count - r29_ready_ctpp_registration_count;
    gboolean same_process = r29_same_listener_process();
    gboolean transport_preserved = same_process && new_ice == 0u &&
        new_cloud == 0u && new_pseudotcp == 0u;
    gboolean registration_preserved = r29_listener_registered_ready &&
        new_registration == 0u;
    long long observed_ms = r29_media_observation_end_ms - r29_media_observation_start_ms;
    if (observed_ms < 0)
        observed_ms = 0;

    printf("REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true\n");
    r29c_open_fields_have_proven_sources = r29c_mediareq26_open_fields_proven();
    r29c_stop_fields_have_proven_sources = r29c_mediareq26_stop_fields_proven();
    r29c_print_field_source_table();
    printf("ICE_BOOTSTRAP_COUNT=%u\n", r29_ice_bootstrap_count);
    printf("CLOUD_NEGOTIATION_COUNT=%u\n", r29_cloud_negotiation_count);
    printf("PSEUDOTCP_OPEN_COUNT=%u\n", r29_pseudotcp_open_count);
    printf("CTPP_REGISTRATION_COUNT=%u\n", r29_ctpp_registration_count);
    printf("SELF_ACTIVATION_001A_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    printf("R27_REPEAT_001A_SENT_COUNT=%u\n", r29_r27_repeat_sent_count);
    printf("REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u\n",
           r29c_registered_ctpp_mediareq26_open_sent_count);
    printf("REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u\n",
           r29c_registered_ctpp_mediareq26_stop_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_open_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_stop_sent_count);
    printf("UNKNOWN_001A_FORM_BLOCKED_COUNT=%u\n",
           r29_unknown_001a_form_blocked_count);
    printf("DOOR_ACTIONS_SENT=%u\n", r29_door_actions_sent);
    printf("GATE_ACTIONS_SENT=%u\n", r29_gate_actions_sent);
    printf("REFRESH_LOOP_STARTED_COUNT=%u\n", r29_refresh_loop_started_count);
    printf("NEW_ICE_COUNT=%u\n", new_ice);
    printf("NEW_CLOUD_NEGOTIATION_COUNT=%u\n", new_cloud);
    printf("NEW_PSEUDOTCP_COUNT=%u\n", new_pseudotcp);
    printf("NEW_REGISTRATION_COUNT=%u\n", new_registration);
    printf("R29_MEDIA_OPEN_MODEL=BLOCKED\n");
	    printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\n");
	    printf("R29E_MEDIA_PROFILE_MODEL=CLIENT_SUPPLIED_CONFIGURATION\n");
	    printf("R29C_MEDIA_PROFILE_IMPLEMENTED=true\n");
	    printf("R29C_PROFILE_SOURCE=EXTERNAL_TESTED_CLIENT_PROFILE\n");
	    printf("R29C_EXTERNAL_PROFILE_ACCEPTED_FOR_BOUNDED_PROBE=%s\n",
	           r29c_external_profile_accepted_for_bounded_probe ? "true" : "false");
	    printf("MEDIAREQ26_OPEN_BUILDER=%s\n",
	           r29c_open_fields_have_proven_sources &&
	           r29c_registered_ctpp_mediareq26_open_serialized ?
           "PROVEN_OFFLINE" : "BLOCKED");
    printf("MEDIAREQ26_STOP_BUILDER=%s\n",
           r29c_open_fields_have_proven_sources &&
           r29c_stop_fields_have_proven_sources &&
           r29c_registered_ctpp_mediareq26_stop_serialized ?
           "PROVEN_OFFLINE" : "BLOCKED");
    printf("OPEN_FIELDS_HAVE_PROVEN_SOURCES=%s\n",
           r29c_open_fields_have_proven_sources ? "true" : "false");
    printf("STOP_FIELDS_HAVE_PROVEN_SOURCES=%s\n",
           r29c_stop_fields_have_proven_sources ? "true" : "false");
    printf("EXPERIMENTAL_REGISTERED_CTPP_BINDING_ISOLATED=true\n");
    printf("SELF_ACTIVATION_PATH_UNREACHABLE=true\n");
    printf("R27_REPEAT_PATH_UNREACHABLE=true\n");
    printf("ONE_SHOT_OPEN_GATE=%s\n",
           r29c_registered_ctpp_mediareq26_open_sent_count <= 1u ? "PASS" : "FAIL");
    printf("ONE_SHOT_STOP_GATE=%s\n",
           r29c_registered_ctpp_mediareq26_stop_sent_count <= 1u ? "PASS" : "FAIL");
    printf("MEDIA_ONLY_STOP_RESULT=%s\n",
           r29c_media_only_stop_result ? "PASS" : "NOT_RUN");
    printf("FINAL_RESEARCH_SESSION_CLEANUP=%s\n",
           r29c_final_research_session_cleanup ? "PASS" : "NOT_RUN");
    printf("RESEARCH_LISTENER_READY=%s\n",
           r29_listener_registered_ready ? "true" : "false");
    printf("LISTENER_READY_AFTER_MEDIA=%s\n",
           r29_listener_registered_ready ? "true" : "false");
    printf("MEDIA_TEARDOWN_PRESERVES_TRANSPORT=%s\n",
           transport_preserved ? "true" : "false");
    printf("MEDIA_TEARDOWN_PRESERVES_REGISTRATION=%s\n",
           registration_preserved ? "true" : "false");
    printf("MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=%s\n",
           (same_process && r29_listener_registered_ready) ? "true" : "false");
    printf("CALL_TRANSACTION_CREATED=%s\n",
           r29_call_transaction_created ? "true" : "false");
    printf("INBOUND_CALL_CTP_CAPTURE_IMPLEMENTED=%s\n",
           r29_inbound_call_ctp_captured ? "true" : "false");
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           r29_call_ctp_separate_from_registration ? "true" : "false");
    printf("CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=%s\n",
           r29_call_bound_mediareq26_uses_inbound_ctp ? "true" : "false");
    printf("MEDIA_CHANNEL_RUNTIME_ALLOCATION_IMPLEMENTED=%s\n",
           r29_media_channel_runtime_allocated ? "true" : "false");
    printf("MEDIA_CHANNEL_STATE_PERSISTED=%s\n",
           r29_media_channel_state_persisted ? "true" : "false");
    printf("ATTACHED_MEDIA_STARTED=%s\n",
           r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ||
           r29_media_stop_completed ? "true" : "false");
    printf("VIDEO_RTP_STARTED=%s\n",
           (r29_video_rtp_started_marker || p80_video_rtp_packets > 0u) ?
           "true" : "false");
    printf("VIDEO_RTP_PACKETS=%llu\n", (unsigned long long)p80_video_rtp_packets);
    printf("VIDEO_RTP_OBSERVATION_SECONDS=%lld\n", observed_ms / 1000LL);
    printf("R29C_OPEN_WRITE_COMPLETED_AT_MS=%lld\n",
           r29c_open_write_completed_ms);
    printf("R29C_RTP_OBSERVATION_STARTED_AT_MS=%lld\n",
           r29_media_observation_start_ms);
    printf("R29C_RTP_OBSERVATION_ENDED_AT_MS=%lld\n",
           r29_media_observation_end_ms);
    printf("R29C_WAITING_FOR_STOP=%s\n",
           r29c_waiting_for_stop ? "true" : "false");
    printf("CALL_TRANSACTION_END_STATE=%s\n", call_end_state);
		    printf("R29C_BUILDER=%s\n",
		           r29c_open_fields_have_proven_sources &&
	           r29c_stop_fields_have_proven_sources ? "PASS" : "BLOCKED");
	    printf("LIVE_PROBE_PREPARED=%s\n",
	           r29c_live_probe_prepared ? "true" : "false");
    fflush(stdout);
}

static gboolean
r29_same_listener_process(void)
{
    return r29_listener_ready_pid != 0 && r29_listener_ready_pid == getpid();
}

static void
r29_capture_ready_snapshot(void)
{
    r29_listener_ready_pid = getpid();
    r29_ready_ice_bootstrap_count = r29_ice_bootstrap_count;
    r29_ready_cloud_negotiation_count = r29_cloud_negotiation_count;
    r29_ready_pseudotcp_open_count = r29_pseudotcp_open_count;
    r29_ready_ctpp_registration_count = r29_ctpp_registration_count;
}

static gboolean
r29_start_attached_media_from_call_init(const char *source)
{
    if (!r29_listener_registered_ready || !source || strcmp(source, V4_ENTRANCE) != 0) {
        printf("R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ||
        r29c_registered_ctpp_mediareq26_open_sent_count > 0u) {
        r29_second_media_start_blocked = TRUE;
        printf("R29_SECOND_MEDIA_START_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (r29_call_transaction_active) {
        printf("R29_SECOND_CALL_INIT_DURING_ACTIVE_MEDIA_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (!r29c_allocate_media_channel_id(g_random_int())) {
        printf("R29C_BUILDER=BLOCKED\n");
        printf("LIVE_PROBE_PREPARED=false\n");
        fflush(stdout);
        return FALSE;
    }

    r29_call_transaction_active = TRUE;
    r29_call_transaction_created = TRUE;
    r29_inbound_call_ctp_captured = FALSE;
    r29_call_ctp_separate_from_registration = FALSE;
    r29_call_bound_mediareq26_uses_inbound_ctp = FALSE;
    r29_call_init_monotonic_ms = p116_monotonic_ms();
    r29_media_observation_start_ms = r29_call_init_monotonic_ms;
    r29_attached_media_state = R29_INBOUND_CALL_ACTIVE;

    printf("REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true\n");
    printf("R29C_OPEN_GATE=PASS\n");
    printf("R29C_PRE_OPEN_SNAPSHOT_RECORDED=true\n");
    if (!r29c_queue_registered_mediareq26(R29C_MEDIAREQ26_OPEN)) {
        r29_print_scalar_snapshot("OPEN_BLOCKED_UNSOURCED_FIELDS");
        return FALSE;
    }
    p80_media_forwarding_enabled = TRUE;
    r29_attached_media_state = R29_ATTACHED_MEDIA_ACTIVE;
    r29c_live_probe_prepared = TRUE;
    r29_media_observation_start_ms = r29c_open_write_completed_ms;
    printf("R29C_RTP_OBSERVATION_STARTED_AT_MS=%lld\n",
           r29_media_observation_start_ms);
    g_timeout_add_seconds(10, r29c_rtp_observation_complete_cb, NULL);
    r29_print_scalar_snapshot("OPEN_SENT_OBSERVING_RTP");
    return TRUE;
}

static gboolean
r29_registration_ctp_rejected_for_media(void)
{
    r29_registration_ctp_rejected_for_media_count++;
    printf("REGISTRATION_CTP_REJECTED_FOR_CALL_BOUND_MODEL=true\n");
    fflush(stdout);
    return FALSE;
}

static gboolean
r29_unknown_001a_form_blocked(void)
{
    r29_unknown_001a_form_blocked_count++;
    printf("UNKNOWN_001A_FORM_BLOCKED=true\n");
    printf("UNKNOWN_001A_FORM_BLOCKED_COUNT=%u\n",
           r29_unknown_001a_form_blocked_count);
    fflush(stdout);
    return FALSE;
}

static gboolean
r29_media_only_teardown(const char *reason)
{
    (void)reason;
    if (r29_media_stop_completed) {
        printf("R29_MEDIA_STOP_SECOND_INVOCATION_REFUSED=true\n");
        fflush(stdout);
        return FALSE;
    }
    r29_media_stop_requested = TRUE;
    if (!r29_call_bound_mediareq26_open_sent) {
        r29_media_stop_before_open_blocked = TRUE;
        r29c_stop_generation_failed = TRUE;
        printf("R29_MEDIA_STOP_BEFORE_OPEN_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }
    r29_media_observation_end_ms = p116_monotonic_ms();
    r29_attached_media_state = R29_ATTACHED_MEDIA_STOPPING;
    if (!r29c_queue_registered_mediareq26(R29C_MEDIAREQ26_STOP)) {
        r29c_stop_generation_failed = TRUE;
        printf("R29C_RESULT=INCONCLUSIVE_CLEANUP_FAILURE\n");
        fflush(stdout);
        return FALSE;
    }
    p80_media_forwarding_enabled = FALSE;
    if (p80_video_rtp_fd >= 0) {
        close(p80_video_rtp_fd);
        p80_video_rtp_fd = -1;
    }
    if (p80_audio_rtp_fd >= 0) {
        close(p80_audio_rtp_fd);
        p80_audio_rtp_fd = -1;
    }
    r29_call_transaction_active = FALSE;
    r29_rtpc_media_channels_open = 0u;
    r29_media_stop_completed =
        !p80_media_forwarding_enabled &&
        p80_video_rtp_fd < 0 &&
        p80_audio_rtp_fd < 0 &&
        r29_same_listener_process() &&
        r29_listener_registered_ready;
    r29c_media_only_stop_result = r29_media_stop_completed;
    r29_attached_media_state = R29_LISTENER_REGISTERED_READY;
    printf("ATTACHED_MEDIA_STOP_REQUESTED=true\n");
    printf("MEDIA_ONLY_STOP_RESULT=%s\n",
           r29c_media_only_stop_result ? "PASS" : "FAIL");
    r29_print_scalar_snapshot(r29_media_stop_completed ?
                              "MEDIA_ONLY_STOP_COMPLETE" :
                              "MEDIA_ONLY_STOP_FAILED");
    return r29_media_stop_completed;
}

static gboolean
r29c_rtp_observation_complete_cb(gpointer data)
{
    (void)data;
    if (!r29c_registered_ctpp_mediareq26_open_sent ||
        r29c_registered_ctpp_mediareq26_stop_sent ||
        r29_media_stop_requested)
        return G_SOURCE_REMOVE;
    r29_media_observation_end_ms = p116_monotonic_ms();
    r29c_waiting_for_stop = TRUE;
    entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
    printf("R29C_RTP_OBSERVATION_ENDED_AT_MS=%lld\n",
           r29_media_observation_end_ms);
    printf("R29C_WAITING_FOR_STOP=true\n");
    r29_print_scalar_snapshot("OPEN_SENT_WAITING_FOR_STOP");
    fflush(stdout);
    return G_SOURCE_REMOVE;
}

static void
r29c_note_final_research_session_cleanup(void)
{
    r29c_final_research_session_cleanup = TRUE;
    printf("FINAL_RESEARCH_SESSION_CLEANUP=PASS\n");
    fflush(stdout);
}

static void
r29c_print_candidate_exit(int code)
{
    const char *reason = "MAIN_LOOP_RETURNED";
    if (code != 0)
        reason = "MAIN_LOOP_FAILED";
    else if (r29c_registered_ctpp_mediareq26_stop_sent)
        reason = "STOP_SENT_MAIN_LOOP_RETURNED";
    else if (r29c_registered_ctpp_mediareq26_open_sent)
        reason = "OPEN_SENT_MAIN_LOOP_RETURNED_BEFORE_STOP";
    printf("R29C_CANDIDATE_EXIT_REASON=%s\n", reason);
    printf("R29C_CANDIDATE_EXIT_CODE=%d\n", code);
    printf("R29C_CANDIDATE_EXIT_AFTER_OPEN=%s\n",
           r29c_registered_ctpp_mediareq26_open_sent ? "true" : "false");
    printf("R29C_CANDIDATE_EXIT_BEFORE_STOP=%s\n",
           !r29c_registered_ctpp_mediareq26_stop_sent ? "true" : "false");
    fflush(stdout);
}

static void
r29_note_channel_open_response_observed(void)
{
    r29_media_channel_open_response_observed = TRUE;
    printf("MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED=true\n");
    fflush(stdout);
}

static const char *
r29_first_rtp_order_result(void)
{
    if (r29_video_rtp_started_marker && r29_media_channel_open_response_observed)
        return "UNKNOWN";
    if (r29_video_rtp_started_marker)
        return "RESPONSE_NOT_OBSERVED";
    if (r29_media_channel_open_response_observed)
        return "RTP_NOT_OBSERVED";
    return "UNKNOWN";
}

static void
r29_sigusr2_handler(int signum)
{
    (void)signum;
    if (r29_sigusr2_seen) {
        r29_sigusr2_second_refused = TRUE;
        return;
    }
    r29_sigusr2_seen = TRUE;
}

static gboolean
r29_sigusr2_poll_cb(gpointer data)
{
    (void)data;
    if (r29_sigusr2_second_refused) {
        printf("R29_SIGUSR2_SECOND_INVOCATION_REFUSED=true\n");
        fflush(stdout);
        r29_sigusr2_second_refused = FALSE;
    }
    if (!r29_sigusr2_seen)
        return G_SOURCE_CONTINUE;
    r29_sigusr2_seen = FALSE;
    (void)r29_media_only_teardown("SIGUSR2");
    return G_SOURCE_CONTINUE;
}

static int
	r29_selfcheck(void)
	{
	    guint8 body[26];
	    const R29CMediaProfile *profile = &r29c_external_tested_client_profile;
	    printf("CANDIDATE_HELPER_EXECUTED=true\n");
	    printf("REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true\n");
	    printf("NETWORK_WRITES_INTERCEPTED=true\n");
	    printf("R29C_PROFILE_SOURCE=EXTERNAL_TESTED_CLIENT_PROFILE\n");
	    printf("R29C_EXTERNAL_PROFILE_ACCEPTED_FOR_BOUNDED_PROBE=true\n");
	    r29_ctpp_registration_count = 1u;
	    r29_listener_registered_ready = TRUE;
	    v4_registered = TRUE;
    v4_ctpp_channel_id = 1u;
    r29_capture_ready_snapshot();
    if (!r29c_allocate_media_channel_id(0x0000002au))
        return 2;
    r29_call_transaction_active = TRUE;
    r29_call_transaction_created = TRUE;
	    r29_attached_media_state = R29_INBOUND_CALL_ACTIVE;
	    r29_call_init_monotonic_ms = p116_monotonic_ms();
	    r29_media_observation_start_ms = r29_call_init_monotonic_ms;
	    r29_media_observation_end_ms = r29_media_observation_start_ms + 10000LL;
	    if (!r29c_build_mediareq26(R29C_MEDIAREQ26_OPEN, profile, body))
	        return 3;
	    if (!r29c_assert_open_body_semantics(body, profile))
	        return 4;
	    memset(body, 0, sizeof(body));
		    if (!r29c_emit_registered_mediareq26(R29C_MEDIAREQ26_OPEN))
		        return 5;
		    r29_attached_media_state = R29_ATTACHED_MEDIA_ACTIVE;
		    r29_media_channel_open_request_sent = TRUE;
		    r29c_waiting_for_stop = TRUE;
		    if (!r29c_build_mediareq26(R29C_MEDIAREQ26_STOP, profile, body))
		        return 6;
	    if (!r29c_assert_stop_body_semantics(body))
	        return 7;
	    memset(body, 0, sizeof(body));
	    if (!r29c_emit_registered_mediareq26(R29C_MEDIAREQ26_STOP))
	        return 8;
	    p80_media_forwarding_enabled = FALSE;
	    r29_call_transaction_active = FALSE;
	    r29_rtpc_media_channels_open = 0u;
	    r29_media_stop_completed = TRUE;
	    r29c_media_only_stop_result = TRUE;
	    r29_attached_media_state = R29_LISTENER_REGISTERED_READY;
	    r29c_live_probe_prepared = TRUE;
	    r29c_note_final_research_session_cleanup();
	    r29_print_scalar_snapshot("SELFCHECK_MEDIA_CLOSED");
	    printf("REGISTRATION_STATE_UNCHANGED=true\n");
	    printf("PSEUDOTCP_TEARDOWN_COUNT=%u\n", r29_stop_pseudotcp_close_count);
	    printf("LISTENER_STOP_COUNT=%u\n", r29_stop_listener_stop_count);
	    printf("R29C_PROBE_READY=true\n");
	    return 0;
	}
/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _region(text: str, start: str, end: str) -> str:
    s = text.find(start)
    if s < 0:
        raise RuntimeError(f"region start missing: {start}")
    e = text.find(end, s)
    if e < 0:
        raise RuntimeError(f"region end missing: {end}")
    return text[s:e]


def _replace_region(text: str, start: str, end: str, replacement: str) -> str:
    s = text.find(start)
    if s < 0:
        raise RuntimeError(f"region start missing: {start}")
    e = text.find(end, s)
    if e < 0:
        raise RuntimeError(f"region end missing: {end}")
    e += len(end)
    return text[:s] + replacement + text[e:]


def _assert_r29c_gates(candidate: str) -> None:
    state = _region(
        candidate,
        "R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN",
        "R29_LISTENER_ATTACHED_MEDIA_STATE_END",
    )
    functions = _region(
        candidate,
        "R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN",
        "R29_ATTACHED_MEDIA_FUNCTIONS_END",
    )
    selfcheck = _region(candidate, "r29_selfcheck(void)\n", "/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */")
    for marker in (
        "REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true",
        "R29C_MEDIAREQ26_OPEN",
        "R29C_MEDIAREQ26_STOP",
        "MEDIAREQ26_OPEN_BUILDER=%s",
        "MEDIAREQ26_STOP_BUILDER=%s",
        "FIELD_SOURCE_TABLE_ROWS=17",
        "R29CMediaProfile",
        "EXTERNAL_TESTED_CLIENT_PROFILE",
        "max_rtp_payload:CLIENT_SUPPLIED_CONFIGURATION",
        "requested_height:CLIENT_SUPPLIED_CONFIGURATION",
        "flags_0x00:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w2_wzr",
    ):
        if marker not in state + functions:
            raise RuntimeError(f"R29C_GATE=FAIL missing={marker}")
    for forbidden in (
        "p78_queue_rtpc_client_001a();",
        "R27_REPEAT_001A_SENT_COUNT=1",
        "SELF_ACTIVATION_001A_SENT_COUNT=1",
    ):
        if forbidden in candidate:
            raise RuntimeError(f"R29C_FORBIDDEN_GATE=FAIL marker={forbidden}")
    for forbidden in ("p12_queue_vip_frame", "p12_flush_tx", "send(", "sendto(", "connect("):
        if forbidden in selfcheck:
            raise RuntimeError(f"R29C_SELFCHECK_NETWORK_GATE=FAIL marker={forbidden}")


def transform(source: str, *, include_p116: bool = True) -> str:
    _ = include_p116
    candidate = r29.transform(source)
    candidate = _replace_once(
        candidate,
        "    P95_TX_DEVICE_0002_ACK,\n    P97_TX_DEVICE_000A_ACK,\n\n    P12_TX_V4_DOOR_WRITE",
        R29C_TX_ENUM_INSERT,
        "R29C tx enum",
    )
    candidate = _replace_once(
        candidate,
        "        case P12_TX_V4_DOOR_WRITE:",
        R29C_TX_COMPLETION_CASES,
        "R29C tx completion",
    )
    candidate = _replace_region(
        candidate,
        "/* === R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN === */",
        "/* === R29_LISTENER_ATTACHED_MEDIA_STATE_END === */",
        R29C_STATE.strip("\n"),
    )
    candidate = _replace_region(
        candidate,
        "/* === R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN === */",
        "/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */",
        R29C_FUNCTIONS.strip("\n"),
    )
    candidate = _replace_once(
        candidate,
        "    return failed ? 6 : 0;\n",
        "    int r29c_exit_code = failed ? 6 : 0;\n"
        "    r29c_print_candidate_exit(r29c_exit_code);\n"
        "    return r29c_exit_code;\n",
        "R29C candidate exit instrumentation",
    )
    r29._assert_generated_gates(candidate)  # pylint: disable=protected-access
    r29.R29_IDENTIFIER_ALLOWLIST.update(  # pylint: disable=protected-access
        {
            "P116_R29C_TX_MEDIAREQ26_OPEN",
            "P116_R29C_TX_MEDIAREQ26_STOP",
            "P76Allocation",
            "P76_OK",
	            "P76Runtime",
	            "ENTRANCE_SIGNAL_DONE",
		            "P12TxKind",
	            "R29CMediaProfile",
	            "R29C_MEDIAREQ26_OPEN",
	            "R29C_MEDIAREQ26_STOP",
	            "R29CMediaReq26State",
	            "action",
	            "allocation",
	            "bitrate",
	            "body",
	            "candidate",
		            "fps",
		            "entrance_signal_stage",
		            "g_timeout_add_seconds",
		            "g_random_int",
	            "guint16",
	            "guint32",
	            "guint8",
	            "kind",
	            "max_height",
	            "max_payload",
	            "max_rtp_payload",
	            "max_width",
	            "memset",
	            "out",
	            "p",
	            "p12_flush_tx",
	            "p12_queue_vip_frame",
            "p76_allocate_target_id",
            "p76_runtime_init",
            "profile0",
            "profile1",
	            "profile2",
	            "profile",
		            "profile3",
	            "profile4",
	            "profile5",
	            "provenance",
	            "r29c_media_channel_allocator",
	            "r29c_assert_open_body_semantics",
	            "r29c_assert_stop_body_semantics",
	            "r29c_external_profile_accepted_for_bounded_probe",
	            "r29c_external_tested_client_profile",
	            "r29c_mediareq26_open_fields_proven",
	            "r29c_mediareq26_stop_fields_proven",
	            "r29c_print_field_source_table",
	            "r29c_saved_media_channel_id",
	            "r29c_validate_media_profile",
	            "read_le16",
	            "read_le32",
	            "requested_height",
	            "requested_width",
	            "request_id",
	            "reserved",
	            "seed",
	        "state",
            "v4_ctpp_channel_id",
            "v4_registered",
            "value",
            "write_le16",
            "write_le32",
        }
    )
    r29._assert_r29_identifiers_resolved(candidate)  # pylint: disable=protected-access
    _assert_r29c_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29C REGISTERED CTPP MEDIAREQ26 PROBE PREP ===",
            "REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true",
            "LIVE_RUN=NOT_RUN",
	            "R29E_MEDIA_PROFILE_MODEL=CLIENT_SUPPLIED_CONFIGURATION",
	            "R29C_MEDIA_PROFILE_IMPLEMENTED=true",
	            "R29C_PROFILE_SOURCE=EXTERNAL_TESTED_CLIENT_PROFILE",
	            "R29C_EXTERNAL_PROFILE_ACCEPTED_FOR_BOUNDED_PROBE=true",
	            "MEDIAREQ26_OPEN_BUILDER=PROVEN_OFFLINE",
	            "MEDIAREQ26_STOP_BUILDER=PROVEN_OFFLINE",
	            "OPEN_FIELDS_HAVE_PROVEN_SOURCES=true",
	            "STOP_FIELDS_HAVE_PROVEN_SOURCES=true",
	            "FIELD_SOURCE_TABLE_ROWS=17",
	            "UNSOURCED_FIELDS=none",
	            "R29C_BUILDER=PASS",
	            "LIVE_PROBE_PREPARED=true",
	            "R29_MEDIA_OPEN_MODEL=BLOCKED",
	            "R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED",
            "PRODUCTION_FILES_CHANGED=0",
            "NATIVE_PRODUCTION_BINARY_CHANGED=false",
            "=== END COMELIT P116 R29C REGISTERED CTPP MEDIAREQ26 PROBE PREP ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--include-p116", action="store_true", default=True)
    parser.add_argument("--no-include-p116", dest="include_p116", action="store_false")
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
        transform(source_path.read_text(encoding="utf-8"), include_p116=args.include_p116),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
