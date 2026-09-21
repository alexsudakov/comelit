#!/usr/bin/env python3
"""P116/R53 helper capability-profile call adoption core.

This research-only module adds a production-shaped orchestration wrapper around
the existing R45 call-adoption serializers and the R36 media trigger.  It does
not duplicate those regions: host tests assemble R35 + R36 + R45 + this R53
region, so ACK/CAPABILITIES/ALERTING bytes and media OPEN remain owned by the
earlier dependency-free cores.

No production file is modified by this module.  No network, signal, actuator,
or self-activation primitive appears in the C core.
"""
from __future__ import annotations

import entrance_p116_r45_call_adoption_core as r45

CORE_BEGIN_MARKER = "/* R53_CALL_ADOPTION_PROFILE_BEGIN */"
CORE_END_MARKER = "/* R53_CALL_ADOPTION_PROFILE_END */"

CORE_REGION = r'''/* R53_CALL_ADOPTION_PROFILE_BEGIN */
#define R53_HELPER_CAP_AUDIO_DST  0x01u
#define R53_HELPER_CAP_AUDIO_SRC  0x02u
#define R53_HELPER_CAP_VIDEO_DST  0x04u
#define R53_HELPER_CAP_MSTREAM    0x20u
#define R53_HELPER_INTUNIT_CALL_TYPE 0x49u
#define R53_HELPER_ALERTING_ARGUMENT 0x00u

typedef enum {
    R53_STAGE_NONE = 0,
    R53_STAGE_ACK_BUILD_FAILED,
    R53_STAGE_ACK_WRITE_FAILED,
    R53_STAGE_CAPABILITIES_BUILD_FAILED,
    R53_STAGE_CAPABILITIES_WRITE_FAILED,
    R53_STAGE_ALERTING_BUILD_FAILED,
    R53_STAGE_ALERTING_WRITE_FAILED,
    R53_STAGE_WAITING_PEER_CAPABILITIES,
    R53_STAGE_PEER_CAPABILITIES_REJECTED,
    R53_STAGE_MEDIA_TRIGGER_REJECTED
} R53FailureStage;

typedef struct {
    unsigned generation;
    unsigned connection;
    int adoption_attempted;
    int call_adoption_started;
    int invite_ack_sent;
    int local_capabilities_sent;
    unsigned local_capability_word;
    int local_alerting_sent;
    int waiting_peer_capabilities;
    int peer_capabilities_seen;
    unsigned peer_capability_word;
    int peer_video_requested;
    R53FailureStage call_adoption_failure_stage;
} R53Diagnostics;

typedef struct {
    R45CallAdoptionState r45;
    R53Diagnostics diag;
} R53CallAdoptionProfileState;

static unsigned r53_helper_local_capability_profile(void) {
    return R53_HELPER_CAP_AUDIO_DST
        | R53_HELPER_CAP_AUDIO_SRC
        | R53_HELPER_CAP_VIDEO_DST
        | R53_HELPER_CAP_MSTREAM;
}

static int r53_helper_profile_is_expected(void) {
    return r53_helper_local_capability_profile() == 0x27u ? 1 : 0;
}

static const char *r53_failure_stage_name(R53FailureStage stage) {
    switch (stage) {
    case R53_STAGE_NONE: return "NONE";
    case R53_STAGE_ACK_BUILD_FAILED: return "ACK_BUILD_FAILED";
    case R53_STAGE_ACK_WRITE_FAILED: return "ACK_WRITE_FAILED";
    case R53_STAGE_CAPABILITIES_BUILD_FAILED: return "CAPABILITIES_BUILD_FAILED";
    case R53_STAGE_CAPABILITIES_WRITE_FAILED: return "CAPABILITIES_WRITE_FAILED";
    case R53_STAGE_ALERTING_BUILD_FAILED: return "ALERTING_BUILD_FAILED";
    case R53_STAGE_ALERTING_WRITE_FAILED: return "ALERTING_WRITE_FAILED";
    case R53_STAGE_WAITING_PEER_CAPABILITIES: return "WAITING_PEER_CAPABILITIES";
    case R53_STAGE_PEER_CAPABILITIES_REJECTED: return "PEER_CAPABILITIES_REJECTED";
    case R53_STAGE_MEDIA_TRIGGER_REJECTED: return "MEDIA_TRIGGER_REJECTED";
    }
    return "PEER_CAPABILITIES_REJECTED";
}

static void r53_reset_state(R53CallAdoptionProfileState *state, unsigned generation) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->diag.generation = generation;
    r45_reset_state(&state->r45, generation);
}

static void r53_sync_generation(
    R53CallAdoptionProfileState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return;
    if (state->diag.generation != session->call_generation) {
        r53_reset_state(state, session->call_generation);
    }
}

static R45RuntimeFields r53_runtime_fields(void) {
    R45RuntimeFields runtime;
    runtime.call_type = R53_HELPER_INTUNIT_CALL_TYPE;
    runtime.capability_word = r53_helper_local_capability_profile();
    runtime.alerting_argument = R53_HELPER_ALERTING_ARGUMENT;
    return runtime;
}

static int r53_start_after_call_capture(
    R35AttachedMediaSession *session,
    R53CallAdoptionProfileState *state,
    const R35CtpEnvelopeView *invite_view) {
    R45RuntimeFields runtime;
    unsigned before;
    if (!session || !state || !invite_view) return 0;
    r53_sync_generation(state, session);
    if (!r35_call_ready(session)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_ACK_BUILD_FAILED;
        return 0;
    }
    if (state->diag.adoption_attempted &&
        state->diag.generation == session->call_generation) {
        state->diag.call_adoption_failure_stage = R53_STAGE_WAITING_PEER_CAPABILITIES;
        return 0;
    }
    if (!r53_helper_profile_is_expected()) {
        state->diag.call_adoption_failure_stage = R53_STAGE_CAPABILITIES_BUILD_FAILED;
        return 0;
    }

    state->diag.adoption_attempted = 1;
    state->diag.call_adoption_started = 1;
    state->diag.connection = session->call_ctp_connection;
    state->diag.call_adoption_failure_stage = R53_STAGE_NONE;

    before = state->r45.local_signaling_write_count;
    if (!r45_send_invite_ack(session, &state->r45, invite_view)) {
        state->diag.call_adoption_failure_stage =
            state->r45.local_signaling_write_count == before
                ? R53_STAGE_ACK_WRITE_FAILED
                : R53_STAGE_ACK_BUILD_FAILED;
        return 0;
    }
    state->diag.invite_ack_sent = 1;

    runtime = r53_runtime_fields();
    before = state->r45.local_signaling_write_count;
    if (!r45_send_local_capabilities(session, &state->r45, &runtime)) {
        state->diag.call_adoption_failure_stage =
            state->r45.local_signaling_write_count == before
                ? R53_STAGE_CAPABILITIES_WRITE_FAILED
                : R53_STAGE_CAPABILITIES_BUILD_FAILED;
        return 0;
    }
    state->diag.local_capabilities_sent = 1;
    state->diag.local_capability_word = runtime.capability_word;

    before = state->r45.local_signaling_write_count;
    if (!r45_send_local_alerting(session, &state->r45, &runtime)) {
        state->diag.call_adoption_failure_stage =
            state->r45.local_signaling_write_count == before
                ? R53_STAGE_ALERTING_WRITE_FAILED
                : R53_STAGE_ALERTING_BUILD_FAILED;
        return 0;
    }
    state->diag.local_alerting_sent = 1;
    state->diag.waiting_peer_capabilities = 1;
    return 1;
}

static int r53_peer_capability_word(
    const R35CtpEnvelopeView *view,
    unsigned *word_out) {
    if (!view || !word_out) return 0;
    if (view->inner_len < 8u) return 0;
    if (r35_read_be16(view->inner_body) != R36_OP_CAPABILITIES) return 0;
    *word_out = (unsigned)view->inner_body[4]
        | ((unsigned)view->inner_body[5] << 8)
        | ((unsigned)view->inner_body[6] << 16)
        | ((unsigned)view->inner_body[7] << 24);
    return 1;
}

static int r53_handle_peer_capabilities(
    R35AttachedMediaSession *session,
    R53CallAdoptionProfileState *state,
    const R35CtpEnvelopeView *peer_view) {
    unsigned word = 0u;
    R35Result rc;
    if (!session || !state || !peer_view) return 0;
    r53_sync_generation(state, session);
    if (state->diag.peer_capabilities_seen) {
        state->diag.call_adoption_failure_stage = R53_STAGE_MEDIA_TRIGGER_REJECTED;
        return 0;
    }
    if (!state->diag.waiting_peer_capabilities ||
        !r45_call_adoption_complete(&state->r45, session)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_WAITING_PEER_CAPABILITIES;
        return 0;
    }
    if (!r36_is_capabilities_for_current_call(session, peer_view) ||
        !r53_peer_capability_word(peer_view, &word)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_PEER_CAPABILITIES_REJECTED;
        return 0;
    }

    state->diag.peer_capabilities_seen = 1;
    state->diag.peer_capability_word = word;
    state->diag.peer_video_requested = r36_capabilities_video_requested(peer_view);
    if (!state->diag.peer_video_requested) {
        state->diag.call_adoption_failure_stage = R53_STAGE_PEER_CAPABILITIES_REJECTED;
        return 0;
    }

    if (!r45_accept_peer_data_and_ack(session, &state->r45, peer_view)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_ACK_WRITE_FAILED;
        return 0;
    }
    rc = r36_trigger_open_from_capabilities(session, peer_view);
    if (rc != R35_OK) {
        state->diag.call_adoption_failure_stage = R53_STAGE_MEDIA_TRIGGER_REJECTED;
        return 0;
    }
    state->diag.waiting_peer_capabilities = 0;
    state->diag.call_adoption_failure_stage = R53_STAGE_NONE;
    return 1;
}
/* R53_CALL_ADOPTION_PROFILE_END */'''


def extract_core_region(text: str) -> str:
    if CORE_BEGIN_MARKER not in text or CORE_END_MARKER not in text:
        raise ValueError("R53 core markers missing")
    return text.split(CORE_BEGIN_MARKER, 1)[1].split(CORE_END_MARKER, 1)[0]


def report() -> str:
    return "\n".join(
        (
            "=== P116 R53 CALL ADOPTION PROFILE CORE ===",
            "REUSES_R45_CORE=true",
            f"R45_CORE_MARKER={r45.CORE_BEGIN_MARKER}",
            "HELPER_CAPABILITY_PROFILE_SOURCE=OFFICIAL_APP_DECLARED_INTUNIT_MSTREAM_PROFILE",
            "HELPER_CAPABILITY_PROFILE_FORMULA=AUDIO_DST|AUDIO_SRC|VIDEO_DST|MSTREAM",
            "HELPER_CAPABILITY_PROFILE_VALUE=0x00000027",
            "CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false",
            "CAPTURE_LITERAL_REPLAY_USED=false",
            "TRANSPORT_IO=false",
            "PHYSICAL_CALLS=0",
            "PRODUCTION_PATCH_ALLOWED=false",
            "=== END P116 R53 CALL ADOPTION PROFILE CORE ===",
        )
    )


if __name__ == "__main__":
    print(report())
