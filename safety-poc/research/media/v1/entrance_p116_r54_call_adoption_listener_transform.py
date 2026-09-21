#!/usr/bin/env python3
"""P116/R54: production-candidate call-adoption listener overlay.

Input lineage:
    frozen v1.5.7 listener/Door
    -> R42-b attached inbound media transform
    -> R54 call-adoption overlay

R54 reuses the R45 serializers and the canonical R53 profile state.  The only
production-specific bridge is the final peer-CAPABILITIES handler: after the
R53/R45 peer DATA ACK is emitted, it calls the existing R42 runtime media
trigger so MEDIAREQ26 OPEN still uses the runtime RTPC media RX channel.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r42b_listener_attached_media_transform as r42b
import entrance_p116_r45_call_adoption_core as r45
import entrance_p116_r53_call_adoption_profile_core as r53

BEGIN = "/* R54_CALL_ADOPTION_LISTENER_BEGIN */"
END = "/* R54_CALL_ADOPTION_LISTENER_END */"

EXPECTED_FROZEN_SHA256 = (
    "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
)

_R36_CORE_END = "/* R36_ATTACHED_MEDIA_TRIGGER_END */"
_R42_RUNTIME_END = "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */"
_R35_WIRING_BEGIN = "/* R35_WIRING_BEGIN */"

_ENUM_ANCHOR = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE
} P12TxKind;"""
_ENUM_REPLACEMENT = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_R54_INVITE_ACK,
    P12_TX_R54_LOCAL_CAPABILITIES,
    P12_TX_R54_LOCAL_ALERTING,
    P12_TX_R54_PEER_DATA_ACK
} P12TxKind;"""

_WRITER_ANCHOR = """    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        strcmp(semantic_kind, "MEDIA_OPEN") == 0
            ? P12_TX_R35_MEDIA_OPEN
            : P12_TX_R35_MEDIA_STOP);
"""
_WRITER_REPLACEMENT = """    P12TxKind r54_kind = P12_TX_R35_MEDIA_STOP;
    R54TxSubject r54_subject = R54_TX_SUBJECT_OTHER_EXISTING;

    if (strcmp(semantic_kind, "MEDIA_OPEN") == 0) {
        r54_kind = P12_TX_R35_MEDIA_OPEN;
        r54_subject = R54_TX_SUBJECT_MEDIA_OPEN;
    } else if (strcmp(semantic_kind, "MEDIA_STOP") == 0) {
        r54_kind = P12_TX_R35_MEDIA_STOP;
        r54_subject = R54_TX_SUBJECT_MEDIA_STOP;
    } else if (strcmp(semantic_kind, "CALL_INVITE_ACK") == 0) {
        r54_kind = P12_TX_R54_INVITE_ACK;
        r54_subject = R54_TX_SUBJECT_INVITE_ACK;
    } else if (strcmp(semantic_kind, "CALL_CAPABILITIES") == 0) {
        r54_kind = P12_TX_R54_LOCAL_CAPABILITIES;
        r54_subject = R54_TX_SUBJECT_LOCAL_CAPABILITIES;
    } else if (strcmp(semantic_kind, "CALL_ALERTING") == 0) {
        r54_kind = P12_TX_R54_LOCAL_ALERTING;
        r54_subject = R54_TX_SUBJECT_LOCAL_ALERTING;
    } else if (strcmp(semantic_kind, "CALL_PEER_DATA_ACK") == 0) {
        r54_kind = P12_TX_R54_PEER_DATA_ACK;
        r54_subject = R54_TX_SUBJECT_PEER_DATA_ACK;
    }

    g_r54_tx_last_subject = r54_subject;
    g_r54_tx_last_reason = R54_TX_QUEUE_REASON_UNKNOWN;
    g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;

    if (p12_tx_pending) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_BUSY;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=BUSY\\n");
        printf("R54_TX_WAITING_FOR_SLOT=true\\n");
        fflush(stdout);
        return;
    }

    if (packet_len == 0u || packet_len > P12_TX_MAX - 8u) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_INVALID_LENGTH;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=INVALID_LENGTH\\n");
        fflush(stdout);
        return;
    }

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        r54_kind);
    if (queued) {
        g_r54_tx_last_enqueued = r54_subject;
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
        printf("R54_TX_ENQUEUED=%s\\n", r54_tx_subject_name(r54_subject));
    } else {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_UNKNOWN;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=UNKNOWN\\n");
    }
"""

_R54_TX_PRELUDE = r'''/* R54_TX_ATTRIBUTION_BEGIN */
typedef enum {
    R54_TX_SUBJECT_NONE = 0,
    R54_TX_SUBJECT_INVITE_ACK,
    R54_TX_SUBJECT_LOCAL_CAPABILITIES,
    R54_TX_SUBJECT_LOCAL_ALERTING,
    R54_TX_SUBJECT_PEER_DATA_ACK,
    R54_TX_SUBJECT_MEDIA_OPEN,
    R54_TX_SUBJECT_MEDIA_STOP,
    R54_TX_SUBJECT_OTHER_EXISTING
} R54TxSubject;

typedef enum {
    R54_TX_QUEUE_REASON_NONE = 0,
    R54_TX_QUEUE_REASON_BUSY,
    R54_TX_QUEUE_REASON_INVALID_LENGTH,
    R54_TX_QUEUE_REASON_NO_WRITER,
    R54_TX_QUEUE_REASON_TRANSPORT,
    R54_TX_QUEUE_REASON_ALLOCATION,
    R54_TX_QUEUE_REASON_UNKNOWN
} R54TxQueueReason;

static R54TxSubject g_r54_tx_last_subject = R54_TX_SUBJECT_NONE;
static R54TxSubject g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
static R54TxQueueReason g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;

static const char *
r54_tx_subject_name(R54TxSubject subject)
{
    switch (subject) {
    case R54_TX_SUBJECT_NONE: return "NONE";
    case R54_TX_SUBJECT_INVITE_ACK: return "INVITE_ACK";
    case R54_TX_SUBJECT_LOCAL_CAPABILITIES: return "LOCAL_CAPABILITIES";
    case R54_TX_SUBJECT_LOCAL_ALERTING: return "LOCAL_ALERTING";
    case R54_TX_SUBJECT_PEER_DATA_ACK: return "PEER_DATA_ACK";
    case R54_TX_SUBJECT_MEDIA_OPEN: return "MEDIA_OPEN";
    case R54_TX_SUBJECT_MEDIA_STOP: return "MEDIA_STOP";
    case R54_TX_SUBJECT_OTHER_EXISTING: return "OTHER_EXISTING";
    }
    return "OTHER_EXISTING";
}
/* R54_TX_ATTRIBUTION_END */
'''

_CALL_INIT_CAPTURE_ANCHOR = """                    printf("R35_CALL_CTP_CAPTURED=true\\n");
                    printf(
                        "R42_CALL_GENERATION=%u\\n",
                        g_r35_session.call_generation
                    );
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\\n");
                }
                fflush(stdout);
"""
_CALL_INIT_CAPTURE_REPLACEMENT = """                    printf("R35_CALL_CTP_CAPTURED=true\\n");
                    printf(
                        "R42_CALL_GENERATION=%u\\n",
                        g_r35_session.call_generation
                    );
                    r54_handle_call_init(body, body_len);
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\\n");
                    r54_publish_diagnostics(
                        &g_r54_call_adoption,
                        R54_DIAGNOSTICS_GENERATION_END);
                }
                fflush(stdout);
"""

_R42_TRIGGER_ANCHOR = """                    gboolean r42_ok = r42_queue_media_channel_open();
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");
"""
_R42_TRIGGER_REPLACEMENT = """                    gboolean r42_ok = r54_handle_peer_capabilities_for_r42(&r42_view);
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");
"""

_FINAL_STATUS_ANCHOR = """    printf(
        "PSEUDOTCP_OPEN_FINAL=%s\\n",
        pseudotcp_open ? "true" : "false"
    );

    fflush(stdout);
"""
_FINAL_STATUS_REPLACEMENT = """    printf(
        "PSEUDOTCP_OPEN_FINAL=%s\\n",
        pseudotcp_open ? "true" : "false"
    );

    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    fflush(stdout);
"""

_P12_COMPLETED_DEFAULT_ANCHOR = """        default:
            break;
    }
"""

_P12_COMPLETED_R54_REPLACEMENT = """        case P12_TX_R54_INVITE_ACK:
        case P12_TX_R54_LOCAL_CAPABILITIES:
        case P12_TX_R54_LOCAL_ALERTING:
        case P12_TX_R54_PEER_DATA_ACK:
            r54_p12_tx_completed(kind);
            break;

        default:
            break;
    }
"""


R54_REGION = r'''/* R54_CALL_ADOPTION_LISTENER_BEGIN */
static R53CallAdoptionProfileState g_r54_call_adoption;

typedef enum {
    R54_TX_STATE_IDLE = 0,
    R54_TX_STATE_NEED_INVITE_ACK,
    R54_TX_STATE_WAIT_INVITE_ACK_FLUSH,
    R54_TX_STATE_NEED_LOCAL_CAPABILITIES,
    R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH,
    R54_TX_STATE_NEED_LOCAL_ALERTING,
    R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH,
    R54_TX_STATE_WAIT_PEER_CAPABILITIES,
    R54_TX_STATE_NEED_PEER_DATA_ACK,
    R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH,
    R54_TX_STATE_MEDIA_TRIGGER_READY,
    R54_TX_STATE_TERMINAL_FAILURE
} R54TxState;

static R54TxState g_r54_tx_state = R54_TX_STATE_IDLE;
static unsigned g_r54_tx_generation = 0u;
static R35CtpEnvelopeView g_r54_invite_view;
static R35CtpEnvelopeView g_r54_pending_peer_view;
static int g_r54_pending_peer_capabilities = 0;
static unsigned g_r54_pending_peer_capability_word = 0u;
static int g_r54_pending_peer_video_requested = 0;
static int g_r54_peer_data_ack_enqueued = 0;
static int g_r54_peer_data_ack_flushed = 0;
static gint64 g_r54_tx_wait_deadline_us = 0;

typedef enum {
    R54_DIAGNOSTICS_LOCAL_AFTER_TRIO = 0,
    R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES,
    R54_DIAGNOSTICS_GENERATION_END
} R54DiagnosticsPhase;

static const char *
r54_diagnostics_phase_name(R54DiagnosticsPhase phase)
{
    switch (phase) {
    case R54_DIAGNOSTICS_LOCAL_AFTER_TRIO: return "LOCAL_AFTER_TRIO";
    case R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES: return "AFTER_PEER_CAPABILITIES";
    case R54_DIAGNOSTICS_GENERATION_END: return "GENERATION_END";
    }
    return "GENERATION_END";
}

static const char *
r54_tx_state_name(R54TxState state)
{
    switch (state) {
    case R54_TX_STATE_IDLE: return "IDLE";
    case R54_TX_STATE_NEED_INVITE_ACK: return "NEED_INVITE_ACK";
    case R54_TX_STATE_WAIT_INVITE_ACK_FLUSH: return "WAIT_INVITE_ACK_FLUSH";
    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES: return "NEED_LOCAL_CAPABILITIES";
    case R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH: return "WAIT_LOCAL_CAPABILITIES_FLUSH";
    case R54_TX_STATE_NEED_LOCAL_ALERTING: return "NEED_LOCAL_ALERTING";
    case R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH: return "WAIT_LOCAL_ALERTING_FLUSH";
    case R54_TX_STATE_WAIT_PEER_CAPABILITIES: return "WAIT_PEER_CAPABILITIES";
    case R54_TX_STATE_NEED_PEER_DATA_ACK: return "NEED_PEER_DATA_ACK";
    case R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH: return "WAIT_PEER_DATA_ACK_FLUSH";
    case R54_TX_STATE_MEDIA_TRIGGER_READY: return "MEDIA_TRIGGER_READY";
    case R54_TX_STATE_TERMINAL_FAILURE: return "TERMINAL_FAILURE";
    }
    return "TERMINAL_FAILURE";
}

static gboolean r54_tx_wait_timeout_cb(gpointer data);

static void
r54_tx_set_wait_deadline(void)
{
    g_r54_tx_wait_deadline_us =
        g_get_monotonic_time() +
        ((gint64)P12_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
    (void)g_timeout_add_seconds(
        P12_STEP_TIMEOUT_SECONDS,
        r54_tx_wait_timeout_cb,
        NULL);
}

static void
r54_tx_clear_wait_deadline(void)
{
    g_r54_tx_wait_deadline_us = 0;
}

static void
r54_tx_terminal_failure(R53FailureStage stage)
{
    g_r54_tx_state = R54_TX_STATE_TERMINAL_FAILURE;
    g_r54_call_adoption.diag.call_adoption_failure_stage = stage;
    r54_tx_clear_wait_deadline();
}

static void
r54_publish_diagnostics(
    const R53CallAdoptionProfileState *state,
    R54DiagnosticsPhase phase)
{
    const R53Diagnostics *diag;
    gboolean peer_phase_reached;
    if (!state) return;
    diag = &state->diag;
    peer_phase_reached = phase != R54_DIAGNOSTICS_LOCAL_AFTER_TRIO;
    printf("R54_DIAGNOSTICS_PHASE=%s\n", r54_diagnostics_phase_name(phase));
    printf("R54_CALL_ADOPTION_STARTED=%s\n", diag->call_adoption_started ? "true" : "false");
    printf("R54_INVITE_ACK_SENT=%s\n", diag->invite_ack_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITIES_SENT=%s\n", diag->local_capabilities_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITY_WORD=%u\n", diag->local_capability_word);
    printf("R54_LOCAL_ALERTING_SENT=%s\n", diag->local_alerting_sent ? "true" : "false");
    printf("R54_WAITING_PEER_CAPABILITIES=%s\n", diag->waiting_peer_capabilities ? "true" : "false");
    if (peer_phase_reached) {
        printf("R54_PEER_CAPABILITIES_SEEN=%s\n", diag->peer_capabilities_seen ? "true" : "false");
        printf("R54_PEER_CAPABILITY_WORD=%u\n", diag->peer_capability_word);
        printf("R54_PEER_VIDEO_REQUESTED=%s\n", diag->peer_video_requested ? "true" : "false");
    } else {
        printf("R54_PEER_CAPABILITIES_SEEN=NOT_REACHED\n");
        printf("R54_PEER_CAPABILITY_WORD=NOT_REACHED\n");
        printf("R54_PEER_VIDEO_REQUESTED=NOT_REACHED\n");
    }
    printf("R54_PEER_DATA_ACK_ENQUEUED=%s\n", g_r54_peer_data_ack_enqueued ? "true" : "false");
    printf("R54_PEER_DATA_ACK_FLUSHED=%s\n", g_r54_peer_data_ack_flushed ? "true" : "false");
    printf("R54_PEER_DATA_ACK_SENT=%s\n", g_r54_peer_data_ack_flushed ? "true" : "false");
    printf("R54_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R54_TX_WAITING_FOR_SLOT=%s\n", p12_tx_pending ? "true" : "false");
    printf("R54_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    if (phase == R54_DIAGNOSTICS_GENERATION_END) {
        printf("R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s\n",
            diag->waiting_peer_capabilities && !diag->peer_capabilities_seen ? "true" : "false");
    }
    printf("R54_CALL_ADOPTION_FAILURE_STAGE=%s\n", r53_failure_stage_name(diag->call_adoption_failure_stage));
    fflush(stdout);
}

static gboolean
r54_tx_wait_timeout_cb(gpointer data)
{
    (void)data;
    if (g_r54_tx_wait_deadline_us > 0 &&
        g_get_monotonic_time() >= g_r54_tx_wait_deadline_us) {
        printf("TX_WAIT_TIMEOUT_SOURCE=P12_STEP_TIMEOUT_SECONDS\n");
        printf("TX_WAIT_TIMEOUT_MS=%u\n", P12_STEP_TIMEOUT_SECONDS * 1000u);
        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);
        r54_publish_diagnostics(
            &g_r54_call_adoption,
            R54_DIAGNOSTICS_GENERATION_END);
    }
    return G_SOURCE_REMOVE;
}

static int
r54_tx_last_enqueue_matches(R54TxSubject subject)
{
    return g_r54_tx_last_enqueued == subject &&
        g_r54_tx_last_reason == R54_TX_QUEUE_REASON_NONE;
}

static gboolean r54_tx_drive(void);

static gboolean
r54_flush_current_tx(void)
{
    gboolean ok = p12_flush_tx();
    if (!ok) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_TRANSPORT;
        printf("R54_TX_QUEUE_FAIL_REASON=TRANSPORT\n");
        fflush(stdout);
    }
    return ok && g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
}

static gboolean
r54_handle_call_init(const guint8 *body, guint body_len)
{
    R35CtpEnvelopeView invite_view;
    if (!r35_parse_ctp_envelope(body, body_len, &invite_view)) {
        g_r54_call_adoption.diag.call_adoption_failure_stage =
            R53_STAGE_ACK_BUILD_FAILED;
        r54_publish_diagnostics(
            &g_r54_call_adoption,
            R54_DIAGNOSTICS_LOCAL_AFTER_TRIO);
        return FALSE;
    }

    /* A repeated CALL_INIT for the generation the scheduler already owns
     * (g_r54_tx_generation is set once per r53_reset_state below and only
     * changes here) must not reset progress: the scheduler may be sitting
     * in any WAIT_*_FLUSH state with a P12 frame already enqueued, or may
     * already have reached MEDIA_TRIGGER_READY/IDLE after completing.
     * Resetting here would re-drive the chain and enqueue a duplicate
     * frame on top of one already owned by the single P12 TX slot. Only a
     * genuinely new generation (the pre-existing R35 capture authority:
     * call_generation / call_ctp_connection) may replace state, and that
     * replacement path (r53_reset_state below, and the cross-generation
     * drop in r54_p12_tx_completed/r54_tx_drive) is unchanged. */
    if (g_r54_tx_generation != 0u &&
        g_r54_tx_generation == g_r35_session.call_generation) {
        printf("R54_TX_DUPLICATE_CALL_INIT_IGNORED=true\n");
        printf("R54_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
        fflush(stdout);
        return g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
    }

    r53_reset_state(&g_r54_call_adoption, g_r35_session.call_generation);
    g_r54_call_adoption.diag.adoption_attempted = 1;
    g_r54_call_adoption.diag.call_adoption_started = 1;
    g_r54_call_adoption.diag.connection = g_r35_session.call_ctp_connection;
    g_r54_call_adoption.diag.call_adoption_failure_stage = R53_STAGE_NONE;
    g_r54_invite_view = invite_view;
    g_r54_tx_generation = g_r35_session.call_generation;
    g_r54_pending_peer_capabilities = 0;
    g_r54_peer_data_ack_enqueued = 0;
    g_r54_peer_data_ack_flushed = 0;
    g_r54_tx_state = R54_TX_STATE_NEED_INVITE_ACK;
    r54_tx_drive();
    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_LOCAL_AFTER_TRIO);
    return g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
}

static gboolean
r54_trigger_r42_media_open(
    R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *peer_view)
{
    (void)session;
    (void)peer_view;
    return r42_queue_media_channel_open();
}

static gboolean
r54_store_pending_peer_capabilities(const R35CtpEnvelopeView *peer_view)
{
    unsigned word = 0u;
    if (!peer_view) return FALSE;
    if (!r36_is_capabilities_for_current_call(&g_r35_session, peer_view) ||
        !r53_peer_capability_word(peer_view, &word)) {
        r54_tx_terminal_failure(R53_STAGE_PEER_CAPABILITIES_REJECTED);
        return FALSE;
    }
    g_r54_call_adoption.diag.peer_capabilities_seen = 1;
    g_r54_call_adoption.diag.peer_capability_word = word;
    g_r54_call_adoption.diag.peer_video_requested =
        r36_capabilities_video_requested(peer_view);
    if (!g_r54_call_adoption.diag.peer_video_requested) {
        r54_tx_terminal_failure(R53_STAGE_PEER_CAPABILITIES_REJECTED);
        return FALSE;
    }

    memset(&g_r54_pending_peer_view, 0, sizeof(g_r54_pending_peer_view));
    g_r54_pending_peer_view.flags = R35_CTP_FLAG_DATA;
    g_r54_pending_peer_view.connection = peer_view->connection;
    g_r54_pending_peer_view.sequence = peer_view->sequence;
    g_r54_pending_peer_view.acknowledgement = peer_view->acknowledgement;
    g_r54_pending_peer_view.inner_len = 8u;
    g_r54_pending_peer_capability_word = word;
    g_r54_pending_peer_video_requested = 1;
    g_r54_pending_peer_capabilities = 1;
    return TRUE;
}

static gboolean
r54_tx_drive(void)
{
    R45RuntimeFields runtime;
    if (g_r54_tx_state == R54_TX_STATE_TERMINAL_FAILURE)
        return FALSE;
    if (g_r54_tx_generation != 0u &&
        g_r54_tx_generation != g_r35_session.call_generation) {
        r54_tx_terminal_failure(R53_STAGE_TX_GENERATION_REPLACED);
        return FALSE;
    }
    if (g_r54_tx_wait_deadline_us > 0 &&
        g_get_monotonic_time() > g_r54_tx_wait_deadline_us) {
        printf("TX_WAIT_TIMEOUT_SOURCE=P12_STEP_TIMEOUT_SECONDS\n");
        printf("TX_WAIT_TIMEOUT_MS=%u\n", P12_STEP_TIMEOUT_SECONDS * 1000u);
        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);
        return FALSE;
    }
    if (p12_tx_pending) {
        printf("R54_TX_WAITING_FOR_SLOT=true\n");
        fflush(stdout);
        return TRUE;
    }

    runtime = r53_runtime_fields();
    switch (g_r54_tx_state) {
    case R54_TX_STATE_NEED_INVITE_ACK:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_invite_ack(&g_r35_session, &g_r54_call_adoption.r45,
                &g_r54_invite_view) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_INVITE_ACK)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_INVITE_ACK_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.invite_ack_sent = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_INVITE_ACK_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_local_capabilities(&g_r35_session, &g_r54_call_adoption.r45,
                &runtime) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_LOCAL_CAPABILITIES)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_LOCAL_CAPABILITIES_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.local_capabilities_sent = 1;
        g_r54_call_adoption.diag.local_capability_word = runtime.capability_word;
        g_r54_tx_state = R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_LOCAL_ALERTING:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_local_alerting(&g_r35_session, &g_r54_call_adoption.r45,
                &runtime) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_LOCAL_ALERTING)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_LOCAL_ALERTING_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.local_alerting_sent = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_PEER_DATA_ACK:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_accept_peer_data_and_ack(&g_r35_session,
                &g_r54_call_adoption.r45, &g_r54_pending_peer_view) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_PEER_DATA_ACK)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_PEER_ACK_FAILED);
            return FALSE;
        }
        g_r54_peer_data_ack_enqueued = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_MEDIA_TRIGGER_READY:
        if (!r54_trigger_r42_media_open(&g_r35_session, &g_r54_pending_peer_view)) {
            r54_tx_terminal_failure(R53_STAGE_TX_MEDIA_TRIGGER_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.waiting_peer_capabilities = 0;
        g_r54_call_adoption.diag.call_adoption_failure_stage = R53_STAGE_NONE;
        g_r54_tx_state = R54_TX_STATE_IDLE;
        return TRUE;

    default:
        return TRUE;
    }
}

static void
r54_p12_tx_completed(P12TxKind kind)
{
    if (g_r54_tx_generation != g_r35_session.call_generation)
        return;
    switch (kind) {
    case P12_TX_R54_INVITE_ACK:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH) {
            printf("R54_TX_FLUSHED=INVITE_ACK\n");
            r54_tx_clear_wait_deadline();
            g_r54_tx_state = R54_TX_STATE_NEED_LOCAL_CAPABILITIES;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_LOCAL_CAPABILITIES:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH) {
            printf("R54_TX_FLUSHED=LOCAL_CAPABILITIES\n");
            r54_tx_clear_wait_deadline();
            g_r54_tx_state = R54_TX_STATE_NEED_LOCAL_ALERTING;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_LOCAL_ALERTING:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH) {
            printf("R54_TX_FLUSHED=LOCAL_ALERTING\n");
            printf("LOCAL_ALERTING_FLUSHED_BEFORE_WAIT_PEER_CAPABILITIES=true\n");
            r54_tx_clear_wait_deadline();
            g_r54_call_adoption.diag.waiting_peer_capabilities = 1;
            g_r54_tx_state = g_r54_pending_peer_capabilities
                ? R54_TX_STATE_NEED_PEER_DATA_ACK
                : R54_TX_STATE_WAIT_PEER_CAPABILITIES;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_PEER_DATA_ACK:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH) {
            printf("R54_TX_FLUSHED=PEER_DATA_ACK\n");
            printf("PEER_DATA_ACK_FLUSHED_BEFORE_MEDIA_TRIGGER=true\n");
            r54_tx_clear_wait_deadline();
            g_r54_peer_data_ack_flushed = 1;
            g_r54_tx_state = R54_TX_STATE_MEDIA_TRIGGER_READY;
            r54_tx_drive();
        }
        break;
    default:
        break;
    }
}

static gboolean
r54_handle_peer_capabilities_for_r42(const R35CtpEnvelopeView *peer_view)
{
    gboolean ok;
    if (g_r54_call_adoption.diag.peer_capabilities_seen) {
        r54_tx_terminal_failure(R53_STAGE_MEDIA_TRIGGER_REJECTED);
        ok = FALSE;
    } else if (g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES ||
        g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_NEED_LOCAL_ALERTING ||
        g_r54_tx_state == R54_TX_STATE_NEED_LOCAL_CAPABILITIES) {
        ok = r54_store_pending_peer_capabilities(peer_view);
        if (ok && g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES)
            g_r54_tx_state = R54_TX_STATE_NEED_PEER_DATA_ACK;
        if (ok)
            ok = r54_tx_drive();
    } else {
        g_r54_call_adoption.diag.call_adoption_failure_stage =
            R53_STAGE_WAITING_PEER_CAPABILITIES;
        ok = FALSE;
    }
    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES);
    return ok;
}
/* R54_CALL_ADOPTION_LISTENER_END */
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (
        r45.CORE_BEGIN_MARKER,
        r45.CORE_END_MARKER,
        r53.CORE_BEGIN_MARKER,
        r53.CORE_END_MARKER,
        BEGIN,
        END,
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R54_MARKER_GATE=FAIL marker={marker}")

    required = (
        "r45_accept_peer_data_and_ack(",
        "r53_handle_peer_capabilities_with_trigger(",
        "r42_queue_media_channel_open()",
        "R54_DIAGNOSTICS_PHASE=%s",
        "R54_CALL_ADOPTION_STARTED=%s",
        "R54_INVITE_ACK_SENT=%s",
        "R54_LOCAL_CAPABILITIES_SENT=%s",
        "R54_LOCAL_CAPABILITY_WORD=%u",
        "R54_LOCAL_ALERTING_SENT=%s",
        "R54_WAITING_PEER_CAPABILITIES=%s",
        "R54_PEER_CAPABILITIES_SEEN=%s",
        "R54_PEER_CAPABILITY_WORD=%u",
        "R54_PEER_VIDEO_REQUESTED=%s",
        "R54_PEER_CAPABILITIES_SEEN=NOT_REACHED",
        "R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s",
        "R54_PEER_DATA_ACK_SENT=%s",
        "R54_CALL_ADOPTION_FAILURE_STAGE=%s",
        "P12_TX_R54_INVITE_ACK",
        "P12_TX_R54_PEER_DATA_ACK",
    )
    for needle in required:
        if needle not in candidate:
            raise RuntimeError(f"R54_FINAL_GATE=FAIL missing={needle}")

    if "r53_start_after_call_capture" in candidate:
        raise RuntimeError("R54_OBSOLETE_IMMEDIATE_TRIO_GATE=FAIL")
    if candidate.count("gboolean r42_ok = r54_handle_peer_capabilities_for_r42(&r42_view);") != 1:
        raise RuntimeError("R54_R42_TRIGGER_REPLACEMENT_GATE=FAIL")
    if "gboolean r42_ok = r42_queue_media_channel_open();" in candidate:
        raise RuntimeError("R54_DIRECT_R42_TRIGGER_GATE=FAIL")
    if candidate.count("static int r53_handle_peer_capabilities_with_trigger(") != 1:
        raise RuntimeError("R54_SINGLE_PEER_CHAIN_OWNER_GATE=FAIL")
    if candidate.count("r42_queue_media_channel_open()") != 1:
        raise RuntimeError("R54_QUEUE_MEDIA_OPEN_CALL_SITE_GATE=FAIL")
    if candidate.count("r54_publish_diagnostics(") < 5:
        raise RuntimeError("R54_DIAGNOSTIC_PUBLICATION_SITE_GATE=FAIL")
    if candidate.count("R54_DIAGNOSTICS_LOCAL_AFTER_TRIO") < 2:
        raise RuntimeError("R54_LOCAL_PHASE_GATE=FAIL")
    if candidate.count("R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES") < 2:
        raise RuntimeError("R54_PEER_PHASE_GATE=FAIL")
    if candidate.count("R54_DIAGNOSTICS_GENERATION_END") < 4:
        raise RuntimeError("R54_GENERATION_END_PHASE_GATE=FAIL")
    listener_region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    if listener_region.count("r45_accept_peer_data_and_ack(") != 1:
        raise RuntimeError("R54_PEER_ACK_SCHEDULER_OWNER_GATE=FAIL")
    if "r53_handle_peer_capabilities_with_trigger(" in listener_region:
        raise RuntimeError("R54_IMMEDIATE_PEER_CHAIN_GATE=FAIL")
    if candidate.count("signal(SIGUSR1, v4_door_signal_handler);") != 1:
        raise RuntimeError("R54_DOOR_SIGUSR1_PRESERVATION_GATE=FAIL")
    if "v4_door_tick_cb" not in candidate:
        raise RuntimeError("R54_DOOR_TICK_PRESERVATION_GATE=FAIL")
    for forbidden in (
        "startAudioTX",
        "PT8_GENERATOR",
        "microphone",
        "entrance_self_activation",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "signal(SIGUSR1, SIG_IGN);",
    ):
        if forbidden in candidate:
            raise RuntimeError(f"R54_FORBIDDEN_GATE=FAIL needle={forbidden}")


def transform(source: str) -> str:
    if BEGIN in source or r53.CORE_BEGIN_MARKER in source:
        raise RuntimeError("R54_REAPPLY_GATE=FAIL")

    candidate = r42b.transform(source)
    candidate = _replace_once(
        candidate,
        _R36_CORE_END,
        _R36_CORE_END + "\n\n" + r45.CORE_REGION + "\n\n" + r53.CORE_REGION,
        "R54 R45/R53 dependency insertion",
    )
    candidate = _replace_once(
        candidate,
        _R35_WIRING_BEGIN,
        _R54_TX_PRELUDE + "\n" + _R35_WIRING_BEGIN,
        "R54 tx attribution prelude insertion",
    )
    candidate = _replace_once(
        candidate,
        _R42_RUNTIME_END,
        _R42_RUNTIME_END + "\n\n" + R54_REGION,
        "R54 listener bridge insertion",
    )
    candidate = _replace_once(
        candidate,
        _ENUM_ANCHOR,
        _ENUM_REPLACEMENT,
        "R54 P12 tx kind extension",
    )
    candidate = _replace_once(
        candidate,
        _WRITER_ANCHOR,
        _WRITER_REPLACEMENT,
        "R54 call signaling writer mapping",
    )
    candidate = _replace_once(
        candidate,
        _CALL_INIT_CAPTURE_ANCHOR,
        _CALL_INIT_CAPTURE_REPLACEMENT,
        "R54 CALL_INIT adoption start",
    )
    candidate = _replace_once(
        candidate,
        _R42_TRIGGER_ANCHOR,
        _R42_TRIGGER_REPLACEMENT,
        "R54 peer ACK before R42 media trigger",
    )
    candidate = _replace_once(
        candidate,
        _FINAL_STATUS_ANCHOR,
        _FINAL_STATUS_REPLACEMENT,
        "R54 final diagnostic publication",
    )
    candidate = _replace_once(
        candidate,
        _P12_COMPLETED_DEFAULT_ANCHOR,
        _P12_COMPLETED_R54_REPLACEMENT,
        "R54 P12 completion hook",
    )
    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R54 CALL ADOPTION LISTENER TRANSFORM ===",
            "BASE_LINEAGE=FROZEN_V1_5_7_PERSISTENT_LISTENER_DOOR",
            "R42B_TRANSFORM_REUSED=true",
            "R45_SERIALIZERS_REUSED=true",
            "R53_PROFILE_CORE_REUSED=true",
            "HELPER_CAPABILITY_PROFILE_VALUE=0x00000027",
            "CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false",
            "CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN",
            "CALLFSM_840_POSSIBLY_UNINITIALIZED=true",
            "CAPTURE_LITERAL_REPLAY_USED=false",
            "AUDIO_TX_ADDED=false",
            "AUTOMATIC_RETRY=false",
            "ONE_MEDIA_OPEN_PER_GENERATION=true",
            "DOOR_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R54 CALL ADOPTION LISTENER TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    source = args.source.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if source_sha != EXPECTED_FROZEN_SHA256:
        raise SystemExit(f"FROZEN_BASE_SHA256_GATE=FAIL actual={source_sha}")

    if args.report:
        print(report())
        if args.output is None:
            return 0

    if args.output is None:
        parser.error("--output is required")

    args.output.write_text(transform(source), encoding="utf-8")
    print("R54_CALL_ADOPTION_LISTENER_TRANSFORM=PASS")
    print("FROZEN_BASE_SHA256_GATE=PASS")
    print("R42B_TRANSFORM_GATE=PASS")
    print("R54_TRANSFORM_GATE=PASS")
    print("DOOR_SEMANTICS_CHANGED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
