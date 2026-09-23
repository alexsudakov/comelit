#!/usr/bin/env python3
"""P116/R58: attached-media STOP cleanup corrective overlay.

R58 chains the R57 generator output and corrects the attached inbound media
STOP lifecycle without editing the generated C candidate directly.  The
authoritative close boundary is local disposal after the MEDIA_STOP frame has
actually completed the existing P12 single-slot TX path.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r57_native_failure_attribution_transform as r57

BEGIN = "/* R58_STOP_CLEANUP_BEGIN */"
END = "/* R58_STOP_CLEANUP_END */"
DECLS_BEGIN = "/* R58_STOP_CLEANUP_DECLS_BEGIN */"
DECLS_END = "/* R58_STOP_CLEANUP_DECLS_END */"

_EARLY_ANCHOR_BEFORE = "static gboolean p80_media_forwarding_enabled = FALSE;"
_ANCHOR_AFTER = "/* R54_CALL_ADOPTION_LISTENER_END */"

# Declaration-order contract (build-blocking corrective, orchestrator-applied
# after the DEV round).  r58_stop_request() is called from
# r37_handle_remote_release() and r37_bounded_stop_signal_cb(), both of which
# sit EARLIER in the translation unit than the late R54/R57 anchor
# (_ANCHOR_AFTER), and its first parameter is the R35AttachedMediaSession type
# declared inside the R35 region.  The early _R58_DECLS anchor therefore
# cannot carry it -- that anchor precedes the R35 region, where the type does
# not exist yet.  The prototype is emitted inside the R37 region, immediately
# before its own OP_RELEASE constant: after the R35 region (type visible) and
# before the first call site.  Without it the unit fails with
# "implicit declaration of function 'r58_stop_request'" followed by
# "conflicting types for 'r58_stop_request'" -- the same defect class R57 hit.
_PROTO_ANCHOR_BEFORE = "#define R37_OP_RELEASE        0x000Eu"
_R58_PROTOS = r'''/* R58_STOP_CLEANUP_PROTOS_BEGIN */
static R35Result r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin);
/* R58_STOP_CLEANUP_PROTOS_END */'''

_R58_DECLS = r'''/* R58_STOP_CLEANUP_DECLS_BEGIN */
typedef enum {
    R58_STOP_PHASE_NONE = 0,
    R58_STOP_PHASE_REQUESTED,
    R58_STOP_PHASE_WAIT_TX_SLOT,
    R58_STOP_PHASE_ENQUEUED,
    R58_STOP_PHASE_FLUSHED,
    R58_STOP_PHASE_RTP_DISARMED,
    R58_STOP_PHASE_DISPOSED,
    R58_STOP_PHASE_CLOSED,
    R58_STOP_PHASE_REMOTE_RELEASE,
    R58_STOP_PHASE_FAILED
} R58StopPhase;

typedef enum {
    R58_STOP_FAILURE_STAGE_NONE = 0,
    R58_STOP_FAILURE_STAGE_SIGNAL,
    R58_STOP_FAILURE_STAGE_STALE_CALL,
    R58_STOP_FAILURE_STAGE_QUEUE,
    R58_STOP_FAILURE_STAGE_WRITE,
    R58_STOP_FAILURE_STAGE_FLUSH_TIMEOUT,
    R58_STOP_FAILURE_STAGE_DISPOSE,
    R58_STOP_FAILURE_STAGE_REMOTE_RACE,
    R58_STOP_FAILURE_STAGE_OTHER
} R58StopFailureStage;

typedef enum {
    R58_STOP_ORIGIN_NONE = 0,
    R58_STOP_ORIGIN_HA_SIGNAL,
    R58_STOP_ORIGIN_REMOTE_RELEASE,
    R58_STOP_ORIGIN_CAPABILITY_CLEARED
} R58StopOrigin;

static void r58_stop_publish_closed(void);
static int r58_closed_published_for_generation(void);
static void r58_mark_closed_published(void);
/* R58_STOP_CLEANUP_DECLS_END */'''

_R58_DEFS = r'''/* R58_STOP_CLEANUP_BEGIN */
static unsigned g_r58_stop_generation = 0u;
static R58StopPhase g_r58_stop_phase = R58_STOP_PHASE_NONE;
static R58StopFailureStage g_r58_stop_failure_stage = R58_STOP_FAILURE_STAGE_NONE;
static R58StopOrigin g_r58_stop_origin = R58_STOP_ORIGIN_NONE;
static unsigned g_r58_stop_request_count = 0u;
static unsigned g_r58_stop_duplicate_ignored_count = 0u;
static unsigned g_r58_stop_wait_slot_count = 0u;
static unsigned g_r58_stop_write_attempt_count = 0u;
static int g_r58_stop_requested = 0;
static int g_r58_stop_written = 0;
static int g_r58_stop_disposed = 0;
static int g_r58_stop_closed = 0;
static int g_r58_closed_marker_published = 0;
static R58StopPhase g_r58_stop_last_published_phase = R58_STOP_PHASE_NONE;
static int g_r58_stop_last_phase_valid = 0;
static R58StopFailureStage g_r58_stop_last_published_failure = R58_STOP_FAILURE_STAGE_NONE;
static int g_r58_stop_last_failure_valid = 0;

static R35Result r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin);
static R35Result r58_stop_drive(R35AttachedMediaSession *s);

static const char *
r58_stop_phase_name(R58StopPhase phase)
{
    switch (phase) {
    case R58_STOP_PHASE_NONE: return "NONE";
    case R58_STOP_PHASE_REQUESTED: return "REQUESTED";
    case R58_STOP_PHASE_WAIT_TX_SLOT: return "WAIT_TX_SLOT";
    case R58_STOP_PHASE_ENQUEUED: return "ENQUEUED";
    case R58_STOP_PHASE_FLUSHED: return "FLUSHED";
    case R58_STOP_PHASE_RTP_DISARMED: return "RTP_DISARMED";
    case R58_STOP_PHASE_DISPOSED: return "DISPOSED";
    case R58_STOP_PHASE_CLOSED: return "CLOSED";
    case R58_STOP_PHASE_REMOTE_RELEASE: return "REMOTE_RELEASE";
    case R58_STOP_PHASE_FAILED: return "FAILED";
    }
    return "FAILED";
}

static const char *
r58_stop_failure_stage_name(R58StopFailureStage stage)
{
    switch (stage) {
    case R58_STOP_FAILURE_STAGE_NONE: return "NONE";
    case R58_STOP_FAILURE_STAGE_SIGNAL: return "SIGNAL";
    case R58_STOP_FAILURE_STAGE_STALE_CALL: return "STALE_CALL";
    case R58_STOP_FAILURE_STAGE_QUEUE: return "QUEUE";
    case R58_STOP_FAILURE_STAGE_WRITE: return "WRITE";
    case R58_STOP_FAILURE_STAGE_FLUSH_TIMEOUT: return "FLUSH_TIMEOUT";
    case R58_STOP_FAILURE_STAGE_DISPOSE: return "DISPOSE";
    case R58_STOP_FAILURE_STAGE_REMOTE_RACE: return "REMOTE_RACE";
    case R58_STOP_FAILURE_STAGE_OTHER: return "OTHER";
    }
    return "OTHER";
}

static void
r58_stop_reset_for_generation(void)
{
    if (g_r58_stop_generation == g_r35_session.call_generation)
        return;
    g_r58_stop_generation = g_r35_session.call_generation;
    g_r58_stop_phase = R58_STOP_PHASE_NONE;
    g_r58_stop_failure_stage = R58_STOP_FAILURE_STAGE_NONE;
    g_r58_stop_origin = R58_STOP_ORIGIN_NONE;
    g_r58_stop_request_count = 0u;
    g_r58_stop_duplicate_ignored_count = 0u;
    g_r58_stop_wait_slot_count = 0u;
    g_r58_stop_write_attempt_count = 0u;
    g_r58_stop_requested = 0;
    g_r58_stop_written = 0;
    g_r58_stop_disposed = 0;
    g_r58_stop_closed = 0;
    g_r58_closed_marker_published = 0;
    g_r58_stop_last_published_phase = R58_STOP_PHASE_NONE;
    g_r58_stop_last_phase_valid = 0;
    g_r58_stop_last_published_failure = R58_STOP_FAILURE_STAGE_NONE;
    g_r58_stop_last_failure_valid = 0;
}

static void
r58_stop_publish_failure_stage(void)
{
    if (g_r58_stop_last_failure_valid &&
        g_r58_stop_last_published_failure == g_r58_stop_failure_stage)
        return;
    g_r58_stop_last_failure_valid = 1;
    g_r58_stop_last_published_failure = g_r58_stop_failure_stage;
    printf("R58_STOP_FAILURE_STAGE=%s\n", r58_stop_failure_stage_name(g_r58_stop_failure_stage));
    fflush(stdout);
}

static void
r58_stop_publish_phase(void)
{
    if (g_r58_stop_last_phase_valid &&
        g_r58_stop_last_published_phase == g_r58_stop_phase)
        return;
    g_r58_stop_last_phase_valid = 1;
    g_r58_stop_last_published_phase = g_r58_stop_phase;
    printf("R58_STOP_PHASE=%s\n", r58_stop_phase_name(g_r58_stop_phase));
    printf("R58_STOP_COUNT=%u\n", g_r58_stop_write_attempt_count);
    printf("R58_STOP_REQUEST_COUNT=%u\n", g_r58_stop_request_count);
    printf("R58_STOP_DUPLICATE_IGNORED_COUNT=%u\n", g_r58_stop_duplicate_ignored_count);
    printf("R58_STOP_WAIT_SLOT_COUNT=%u\n", g_r58_stop_wait_slot_count);
    printf("R58_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    if (g_r58_stop_phase == R58_STOP_PHASE_FAILED)
        printf("R58_STOP_FAILED=true\n");
    fflush(stdout);
}

static void
r58_stop_set_phase(R58StopPhase phase)
{
    g_r58_stop_phase = phase;
    r58_stop_publish_phase();
}

static void
r58_stop_set_failure(R58StopFailureStage stage)
{
    g_r58_stop_failure_stage = stage;
    r58_stop_publish_failure_stage();
    r58_stop_set_phase(R58_STOP_PHASE_FAILED);
}

static int
r58_closed_published_for_generation(void)
{
    r58_stop_reset_for_generation();
    return g_r58_closed_marker_published;
}

static void
r58_mark_closed_published(void)
{
    r58_stop_reset_for_generation();
    g_r58_closed_marker_published = 1;
}

static void
r58_stop_undo_unqueued_send(R35AttachedMediaSession *s, unsigned old_sequence)
{
    if (!s)
        return;
    s->call_sequence = old_sequence;
    s->stop_sent = 0;
    s->stop_count = 0u;
    s->rtp_armed = 1;
    s->state = R35_STATE_RTP_ELIGIBLE;
    if (s->rtp_arm_hook)
        s->rtp_arm_hook(s->rtp_arm_hook_ctx, 1);
}

static int
r58_stop_writer_queued_media_stop(void)
{
    return g_r54_tx_last_reason == R54_TX_QUEUE_REASON_NONE &&
        g_r54_tx_last_enqueued == R54_TX_SUBJECT_MEDIA_STOP &&
        p12_tx_pending &&
        p12_tx_kind == P12_TX_R35_MEDIA_STOP;
}

static R35Result
r58_stop_drive(R35AttachedMediaSession *s)
{
    R35Result rc;
    unsigned old_sequence;
    int already_stopped;

    r58_stop_reset_for_generation();
    if (!g_r58_stop_requested || g_r58_stop_closed ||
        g_r58_stop_written || g_r58_stop_disposed)
        return R35_OK;

    if (p12_tx_pending) {
        if (g_r58_stop_phase != R58_STOP_PHASE_WAIT_TX_SLOT) {
            g_r58_stop_wait_slot_count += 1u;
            r58_stop_set_phase(R58_STOP_PHASE_WAIT_TX_SLOT);
        }
        return R35_OK;
    }

    if (!r35_call_ready(s)) {
        r58_stop_set_failure(
            g_r58_stop_origin == R58_STOP_ORIGIN_REMOTE_RELEASE
                ? R58_STOP_FAILURE_STAGE_REMOTE_RACE
                : R58_STOP_FAILURE_STAGE_STALE_CALL);
        return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    }

    already_stopped = s->stop_sent;
    old_sequence = s->call_sequence;
    rc = r35_send_stop(s, R35_FORM_TUNNEL, s->channel_id);
    if (rc != R35_OK) {
        if (already_stopped) {
            g_r58_stop_duplicate_ignored_count += 1u;
            r58_stop_publish_phase();
            return R35_OK;
        }
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_WRITE);
        return rc;
    }

    if (!r58_stop_writer_queued_media_stop()) {
        if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY) {
            r58_stop_undo_unqueued_send(s, old_sequence);
            if (g_r58_stop_phase != R58_STOP_PHASE_WAIT_TX_SLOT) {
                g_r58_stop_wait_slot_count += 1u;
                r58_stop_set_phase(R58_STOP_PHASE_WAIT_TX_SLOT);
            }
            return R35_OK;
        }
        r58_stop_undo_unqueued_send(s, old_sequence);
        r58_stop_set_failure(
            g_r54_tx_last_reason == R54_TX_QUEUE_REASON_UNKNOWN
                ? R58_STOP_FAILURE_STAGE_QUEUE
                : R58_STOP_FAILURE_STAGE_WRITE);
        return R35_ERR_BAD_ARGUMENT;
    }

    g_r58_stop_written = 1;
    g_r58_stop_write_attempt_count += 1u;
    g_r37_telemetry.call_bound_media_stop_sent_count = g_r58_stop_write_attempt_count;
    g_r37_telemetry.rtp_disarmed_count = g_r58_stop_write_attempt_count;
    r58_stop_set_phase(R58_STOP_PHASE_ENQUEUED);
    r58_stop_set_phase(R58_STOP_PHASE_RTP_DISARMED);

    rc = r35_dispose_media_rx_channel(s, s->channel_id);
    if (rc != R35_OK) {
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_DISPOSE);
        return rc;
    }
    g_r58_stop_disposed = 1;
    g_r37_telemetry.media_rx_channel_disposed_count = 1u;
    r58_stop_set_phase(R58_STOP_PHASE_DISPOSED);
    (void)p12_flush_tx();
    return R35_OK;
}

static R35Result
r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin)
{
    r58_stop_reset_for_generation();
    g_r58_stop_request_count += 1u;
    g_r37_telemetry.bounded_stop_request_received_count = g_r58_stop_request_count;
    if (g_r58_stop_closed || g_r58_closed_marker_published) {
        g_r58_stop_duplicate_ignored_count += 1u;
        r58_stop_publish_phase();
        return R35_OK;
    }
    if (g_r58_stop_requested) {
        g_r58_stop_duplicate_ignored_count += 1u;
        r58_stop_publish_phase();
        return R35_OK;
    }
    if (!r35_call_ready(s)) {
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_STALE_CALL);
        return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    }
    g_r58_stop_origin = origin;
    g_r58_stop_requested = 1;
    r58_stop_set_phase(
        origin == R58_STOP_ORIGIN_REMOTE_RELEASE
            ? R58_STOP_PHASE_REMOTE_RELEASE
            : R58_STOP_PHASE_REQUESTED);
    return r58_stop_drive(s);
}

static void
r58_stop_publish_closed(void)
{
    r58_stop_reset_for_generation();
    if (g_r58_stop_closed)
        return;
    if (!g_r58_stop_written || !g_r58_stop_disposed)
        return;
    r58_stop_set_phase(R58_STOP_PHASE_FLUSHED);
    g_r58_stop_closed = 1;
    printf("R58_CLOSED_BOUNDARY=LOCAL_DISPOSAL_AFTER_STOP_FLUSH\n");
    r58_stop_set_phase(R58_STOP_PHASE_CLOSED);
    printf("R58_STOP_CLOSED=true\n");
    fflush(stdout);
    r42_finish_media_channel_close();
}
/* R58_STOP_CLEANUP_END */'''

_SIGUSR2_ANCHOR = """    rc = r37_bounded_stop_request(&g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
    (void)p12_flush_tx();"""
_SIGUSR2_REPLACEMENT = """    rc = r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    (void)p12_flush_tx();"""

_REMOTE_RELEASE_ANCHOR = """    R35Result rc = R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    if (r35_call_ready(s)) {
        rc = r37_stop_and_dispose(s, t, form);
    }
    r35_teardown_call(s);
    return rc;"""
_REMOTE_RELEASE_REPLACEMENT = """    R35Result rc = R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    rc = r58_stop_request(s, R58_STOP_ORIGIN_REMOTE_RELEASE);
    (void)form;
    r35_teardown_call(s);
    return rc;"""

# R58 retires the R37 synchronous stop-request entry point. Its body called
# r37_stop_and_dispose() directly, i.e. r35_send_stop() wrote through
# r35_glib_transport_writer() -> p12_queue_vip_frame() -> p12_queue_bytes()
# with no knowledge of the single P12 TX slot: on BUSY the writer printed
# R54_TX_QUEUE_FAIL_SUBJECT=MEDIA_STOP/REASON=BUSY and returned without
# queueing, while r35_send_stop() still recorded stop_sent=1/stop_count=1 and
# disarmed RTP -- a silently dropped protocol STOP with no completion boundary.
# The stop request is now owned by the R58 scheduler-aware layer
# (r58_stop_request/r58_stop_drive, see the R58 region), which defers the write
# to the next free slot and never drops it. Deleting the dead forwarder is what
# keeps "one owner" true; the alternative (-Wno-unused-function) would leave the
# duplicate write path compiled into the candidate. r37_stop_and_dispose() stays
# in use, unchanged, by r37_handle_capability_cleared().
_R37_RETIRED_ANCHOR = """static R35Result r37_bounded_stop_request(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    t->bounded_stop_request_received_count += 1u;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    return r37_stop_and_dispose(s, t, form);
}"""
_R37_RETIRED_REPLACEMENT = """/* R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_BEGIN
 * Retired by R58: this forwarder called r37_stop_and_dispose() with no
 * knowledge of the single P12 TX slot, so a BUSY slot silently dropped the
 * protocol STOP. The bounded STOP request is now owned by
 * r58_stop_request()/r58_stop_drive() in the R58 region below, which defers
 * the write to the next free slot instead of dropping it and publishes the
 * authoritative CLOSED completion boundary. r37_stop_and_dispose() itself is
 * unchanged and is still reached by r37_handle_capability_cleared().
 * R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_END */"""

_MEDIA_STOP_ANCHOR = """        case P12_TX_R35_MEDIA_STOP:
            if (r42_media_channel_id != 0u) {
                r42_media_stage = R42_MEDIAREQ_STOP_TX;
                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\\n");
                printf(
                    "R42_CALL_GENERATION=%u\\n",
                    g_r35_session.call_generation
                );
                printf(
                    "R42_MEDIA_STOP_CHANNEL=%u\\n",
                    (unsigned)r42_media_channel_id
                );
                fflush(stdout);
                if (!r42_queue_media_channel_close()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_MEDIA_CHANNEL_CLOSE_QUEUE=FAIL\\n");
                    fflush(stdout);
                }
            }
            break;"""
_MEDIA_STOP_REPLACEMENT = """        case P12_TX_R35_MEDIA_STOP:
            if (r42_media_channel_id != 0u) {
                r42_media_stage = R42_MEDIAREQ_STOP_TX;
                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\\n");
                printf(
                    "R42_CALL_GENERATION=%u\\n",
                    g_r35_session.call_generation
                );
                printf(
                    "R42_MEDIA_STOP_CHANNEL=%u\\n",
                    (unsigned)r42_media_channel_id
                );
                fflush(stdout);
                if (!r42_queue_media_channel_close()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_MEDIA_CHANNEL_CLOSE_QUEUE=FAIL\\n");
                    fflush(stdout);
                }
            }
            r58_stop_publish_closed();
            break;"""

_P12_TAIL_ANCHOR = """    if (
        p12_stage ==
        P12_STAGE_V4_LISTEN_RING
    ) {

        p12_deadline_us = 0;

    } else {

        p12_set_deadline();
    }

    fflush(stdout);
}"""
_P12_TAIL_REPLACEMENT = """    if (
        p12_stage ==
        P12_STAGE_V4_LISTEN_RING
    ) {

        p12_deadline_us = 0;

    } else {

        p12_set_deadline();
    }

    r58_stop_drive(&g_r35_session);
    fflush(stdout);
}"""

_R42_FINISH_ANCHOR = """static void
r42_finish_media_channel_close(void)
{
    r42_media_stage = R42_MEDIA_CLOSED;
    r42_media_channel_id = 0u;
    printf("R42_CALL_GENERATION=%u\\n", g_r35_session.call_generation);
    printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");
    fflush(stdout);
}"""
_R42_FINISH_REPLACEMENT = """static void
r42_finish_media_channel_close(void)
{
    if (r58_closed_published_for_generation())
        return;
    r58_mark_closed_published();
    r42_media_stage = R42_MEDIA_CLOSED;
    r42_media_channel_id = 0u;
    printf("R42_CALL_GENERATION=%u\\n", g_r35_session.call_generation);
    printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");
    fflush(stdout);
}"""

_ANCHORS = (
    ("EARLY", _EARLY_ANCHOR_BEFORE),
    ("LATE", _ANCHOR_AFTER),
    ("SIGUSR2", _SIGUSR2_ANCHOR),
    ("REMOTE_RELEASE", _REMOTE_RELEASE_ANCHOR),
    ("MEDIA_STOP_COMPLETION", _MEDIA_STOP_ANCHOR),
    ("P12_COMPLETION_TAIL", _P12_TAIL_ANCHOR),
    ("R42_FINISH_CLOSE", _R42_FINISH_ANCHOR),
)


def _replace_once(text: str, name: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R58_{name}_ANCHOR_GATE=FAIL")
    return text.replace(old, new, 1)


def _assert_anchor_gates(candidate: str) -> None:
    for name, anchor in _ANCHORS:
        if candidate.count(anchor) != 1:
            raise RuntimeError(f"R58_{name}_ANCHOR_GATE=FAIL")


def _assert_gates(candidate: str) -> None:
    for marker in (BEGIN, END, DECLS_BEGIN, DECLS_END):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R58_MARKER_GATE=FAIL marker={marker}")

    r58_region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for forbidden in (
        "sleep" + "(",
        "nano" + "sleep",
        "g_u" + "sleep",
        "alarm" + "(",
        "socket" + "(",
        "send" + "to",
        "start" + "AudioTX",
        "entrance_" + "self_activation",
        "P12_TX_ENTRANCE_" + "SELF_ACTIVATION",
        "signal(SIGUSR1, " + "SIG_IGN);",
    ):
        if forbidden in r58_region:
            raise RuntimeError(f"R58_FORBIDDEN_PRIMITIVE_GATE=FAIL needle={forbidden}")

    if r58_region.count("r35_send_stop(") != 1:
        raise RuntimeError("R58_SINGLE_WRITE_PATH_GATE=FAIL")
    if candidate.count('printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");') != 1:
        raise RuntimeError("R58_HISTORICAL_CLOSED_MARKER_GATE=FAIL")
    if candidate.count("signal(SIGUSR1, v4_door_signal_handler);") != 1:
        raise RuntimeError("R58_SIGUSR1_PRESERVATION_GATE=FAIL")
    if "R42_LISTENER_DOOR_SIGNAL_PRESERVED=true" not in candidate:
        raise RuntimeError("R58_DOOR_PRESERVATION_MARKER_GATE=FAIL")
    if "/* R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN */" not in candidate:
        raise RuntimeError("R58_R57_CHAIN_GATE=FAIL")
    if "/* R54_CALL_ADOPTION_LISTENER_BEGIN */" not in candidate:
        raise RuntimeError("R58_R54_CHAIN_GATE=FAIL")
    if "r58_stop_drive(&g_r35_session);\n    fflush(stdout);" not in candidate:
        raise RuntimeError("R58_COMPLETION_TAIL_GATE=FAIL")
    if "r58_stop_publish_closed();\n            break;" not in candidate:
        raise RuntimeError("R58_STOP_COMPLETION_GATE=FAIL")
    if candidate.count(_R58_PROTOS) != 1:
        raise RuntimeError("R58_PROTOTYPE_GATE=FAIL")
    proto_at = candidate.find(_R58_PROTOS)
    first_call = candidate.find("rc = r58_stop_request(")
    if proto_at < 0 or first_call < 0 or proto_at > first_call:
        raise RuntimeError("R58_PROTOTYPE_ORDER_GATE=FAIL")
    if candidate.count("rc = r58_stop_request(") != 2:
        raise RuntimeError("R58_PROTOTYPE_CALLSITE_GATE=FAIL")
    if "R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_BEGIN" not in candidate:
        raise RuntimeError("R58_R37_RETIREMENT_GATE=FAIL")
    if candidate.count("return r37_stop_and_dispose(s, t, form);") != 1:
        raise RuntimeError("R58_R37_CAPABILITY_CLEARED_PATH_GATE=FAIL")


def transform(source: str) -> str:
    if BEGIN in source or DECLS_BEGIN in source:
        raise RuntimeError("R58_REAPPLY_GATE=FAIL")

    candidate = r57.transform(source)
    _assert_anchor_gates(candidate)

    candidate = _replace_once(
        candidate,
        "EARLY",
        _EARLY_ANCHOR_BEFORE,
        _R58_DECLS + "\n\n" + _EARLY_ANCHOR_BEFORE,
    )
    candidate = _replace_once(
        candidate,
        "LATE",
        _ANCHOR_AFTER,
        _ANCHOR_AFTER + "\n\n" + _R58_DEFS,
    )
    candidate = _replace_once(
        candidate,
        "PROTOS",
        _PROTO_ANCHOR_BEFORE,
        _R58_PROTOS + "\n" + _PROTO_ANCHOR_BEFORE,
    )
    candidate = _replace_once(candidate, "SIGUSR2", _SIGUSR2_ANCHOR, _SIGUSR2_REPLACEMENT)
    candidate = _replace_once(
        candidate,
        "REMOTE_RELEASE",
        _REMOTE_RELEASE_ANCHOR,
        _REMOTE_RELEASE_REPLACEMENT,
    )
    candidate = _replace_once(
        candidate,
        "R37_RETIRED",
        _R37_RETIRED_ANCHOR,
        _R37_RETIRED_REPLACEMENT,
    )
    candidate = _replace_once(
        candidate,
        "MEDIA_STOP_COMPLETION",
        _MEDIA_STOP_ANCHOR,
        _MEDIA_STOP_REPLACEMENT,
    )
    candidate = _replace_once(
        candidate,
        "P12_COMPLETION_TAIL",
        _P12_TAIL_ANCHOR,
        _P12_TAIL_REPLACEMENT,
    )
    candidate = _replace_once(
        candidate,
        "R42_FINISH_CLOSE",
        _R42_FINISH_ANCHOR,
        _R42_FINISH_REPLACEMENT,
    )

    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R58 ATTACHED MEDIA STOP CLEANUP TRANSFORM ===",
            "CORRECTIVE_TARGET=GENERATOR_OVERLAY_ON_R57_CANDIDATE",
            "GENERATED_TEXT_PATCH=false",
            "FROZEN_SOURCE_UNCHANGED=true",
            "STOP_COMPLETION_BOUNDARY=LOCAL_DISPOSAL_AFTER_STOP_FLUSH",
            "MEDIA_STOP_SINGLE_SLOT_DISCIPLINE=EXISTING_P12_TX_SLOT",
            "REMOTE_RELEASE_CLOSED_MARKER=true",
            "DOOR_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R58 ATTACHED MEDIA STOP CLEANUP TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    safety_poc_root = Path(__file__).resolve().parents[3]
    source_path = args.source or (
        safety_poc_root / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
    )

    if args.sha256:
        candidate = transform(source_path.read_text(encoding="utf-8"))
        print(hashlib.sha256(candidate.encode("utf-8")).hexdigest())
        return 0

    if args.output is None:
        print(report())
        return 0

    candidate = transform(source_path.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")
    print("R58_TRANSFORM=PASS")
    print(
        "R58_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    )
    print("R58_STOP_COMPLETION_BOUNDARY=LOCAL_DISPOSAL_AFTER_STOP_FLUSH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
