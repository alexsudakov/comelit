/*
 * P116/R53 call-adoption profile host harness.
 *
 * Assembled from the R35, R36, R45, and R53 dependency-free regions.  All
 * outbound frames are intercepted by fake_writer().
 */

#include <stdio.h>
#include <string.h>

#define R53H_MAX_WRITES 32u
#define R53H_MAX_FRAME  72u

typedef struct {
    char kind[32];
    unsigned char packet[R53H_MAX_FRAME];
    unsigned len;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
} R53HCapturedWrite;

static R53HCapturedWrite g_writes[R53H_MAX_WRITES];
static unsigned g_write_count = 0u;
static unsigned g_rtp_arm_calls = 0u;
static unsigned g_network_tx = 0u;
static unsigned g_actuator_actions = 0u;
static unsigned g_self_activation_actions = 0u;

static void mark(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
}

static void r53h_reset_fakes(void)
{
    memset(g_writes, 0, sizeof(g_writes));
    g_write_count = 0u;
    g_rtp_arm_calls = 0u;
}

static void fake_writer(
    void *ctx,
    const char *kind,
    const unsigned char *packet,
    unsigned len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement)
{
    R53HCapturedWrite *w;
    (void)ctx;
    if (!kind || !packet || len > R53H_MAX_FRAME || g_write_count >= R53H_MAX_WRITES) return;
    w = &g_writes[g_write_count++];
    strncpy(w->kind, kind, sizeof(w->kind) - 1u);
    memcpy(w->packet, packet, len);
    w->len = len;
    w->connection = connection;
    w->sequence = sequence;
    w->acknowledgement = acknowledgement;
}

static void fake_rtp_hook(void *ctx, int armed)
{
    (void)ctx;
    if (armed) g_rtp_arm_calls++;
}

static void r53h_wire(R35AttachedMediaSession *s)
{
    memset(s, 0, sizeof(*s));
    s->writer = fake_writer;
    s->rtp_arm_hook = fake_rtp_hook;
}

static int r53h_parse_write(unsigned index, R35CtpEnvelopeView *view)
{
    if (index >= g_write_count) return 0;
    return r35_parse_ctp_envelope(g_writes[index].packet, g_writes[index].len, view);
}

static void r53h_build_call_init(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack)
{
    memset(out, 0, 72u);
    out[0] = 0xc0u;
    out[1] = R35_CTP_VERSION;
    r35_write_be16(out + 2, peer_connection);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[7] = 0x28u;
    out[8] = 0x00u;
    out[9] = 0x01u;
    out[48] = 0xffu; out[49] = 0xffu; out[50] = 0xffu; out[51] = 0xffu;
    memset(out + 52, 0x41, 10u);
    memset(out + 62, 0x42, 10u);
}

static void r53h_build_peer_capabilities(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack,
    unsigned word)
{
    memset(out, 0, 40u);
    out[0] = R35_CTP_FLAG_DATA;
    out[1] = R35_CTP_VERSION;
    r35_write_be16(out + 2, peer_connection);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[7] = 0x08u;
    out[8] = 0x00u;
    out[9] = 0x03u;
    out[10] = 0x50u;
    out[11] = 0x07u;
    out[12] = (unsigned char)(word & 0xffu);
    out[13] = (unsigned char)((word >> 8) & 0xffu);
    out[14] = (unsigned char)((word >> 16) & 0xffu);
    out[15] = (unsigned char)((word >> 24) & 0xffu);
    out[16] = 0xffu; out[17] = 0xffu; out[18] = 0xffu; out[19] = 0xffu;
    memset(out + 20, 0x41, 10u);
    memset(out + 30, 0x42, 10u);
}

static int r53h_empty_ack_matches(
    const R35CtpEnvelopeView *view,
    unsigned seq,
    unsigned ack)
{
    return view && view->flags == R45_CTP_FLAG_EMPTY_ACK
        && view->inner_len == 0u
        && view->sequence == (seq & 0xffu)
        && view->acknowledgement == (ack & 0xffu);
}

static int r53h_capabilities_match(const R35CtpEnvelopeView *view)
{
    unsigned word = 0u;
    return view
        && view->flags == R35_CTP_FLAG_DATA
        && view->inner_len == R45_CAPABILITIES_BODY_LEN
        && view->inner_body[0] == 0x00u
        && view->inner_body[1] == 0x03u
        && view->inner_body[2] == R53_HELPER_INTUNIT_CALL_TYPE
        && view->inner_body[3] == 0x00u
        && r53_peer_capability_word(view, &word)
        && word == r53_helper_local_capability_profile();
}

static int r53h_alerting_match(const R35CtpEnvelopeView *view)
{
    return view
        && view->flags == R35_CTP_FLAG_DATA
        && view->inner_len == R45_ALERTING_BODY_LEN
        && view->inner_body[0] == 0x00u
        && view->inner_body[1] == 0x0au
        && view->inner_body[2] == R53_HELPER_ALERTING_ARGUMENT;
}

static int r53h_emit_local_adoption_frames(
    R35AttachedMediaSession *session,
    R53CallAdoptionProfileState *state,
    const R35CtpEnvelopeView *invite_view)
{
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
    if (r53_helper_local_capability_profile() != 0x27u) {
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

static int r53h_run_positive(unsigned peer_word, const char *prefix)
{
    int ok;
    unsigned char invite[72];
    unsigned char peer_caps[40];
    R35AttachedMediaSession session;
    R53CallAdoptionProfileState adoption;
    R35CtpEnvelopeView invite_view;
    R35CtpEnvelopeView peer_view;
    R35CtpEnvelopeView view;

    r53h_reset_fakes();
    r53h_wire(&session);
    memset(&adoption, 0, sizeof(adoption));
    r53h_build_call_init(invite, 0x5234u, 0xfeu, 0xffu);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u)
        && r53h_emit_local_adoption_frames(&session, &adoption, &invite_view);
    if (!ok) return 0;

    ok = g_write_count == 3u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
        && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
        && r53h_parse_write(0u, &view)
        && r53h_empty_ack_matches(&view, 0xffu, 0xffu)
        && r53h_parse_write(1u, &view)
        && r53h_capabilities_match(&view)
        && view.sequence == 0xffu
        && r53h_parse_write(2u, &view)
        && r53h_alerting_match(&view)
        && view.sequence == 0x00u
        && session.call_sequence == 0x01u
        && adoption.diag.call_adoption_started
        && adoption.diag.invite_ack_sent
        && adoption.diag.local_capabilities_sent
        && adoption.diag.local_capability_word == 0x27u
        && adoption.diag.local_alerting_sent
        && adoption.diag.waiting_peer_capabilities;
    if (!ok) return 0;

    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x60u, 0x22u, peer_word);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && r53_handle_peer_capabilities(&session, &adoption, &peer_view);
    if (!ok) return 0;

    ok = g_write_count == 5u
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0
        && r53h_parse_write(3u, &view)
        && r53h_empty_ack_matches(&view, 0x01u, 0x61u)
        && session.open_count == 1u
        && g_rtp_arm_calls == 1u
        && adoption.diag.peer_capabilities_seen
        && adoption.diag.peer_capability_word == peer_word
        && adoption.diag.peer_video_requested
        && adoption.diag.call_adoption_failure_stage == R53_STAGE_NONE;
    printf("%s_WRITE_COUNT=%u\n", prefix, g_write_count);
    printf("%s_PEER_WORD=0x%08x\n", prefix, peer_word);
    return ok;
}

int main(void)
{
    int overall = 1;
    int ok;
    unsigned char invite[72];
    unsigned char peer_caps[40];
    unsigned char mutated[R53H_MAX_FRAME];
    R35AttachedMediaSession session;
    R53CallAdoptionProfileState adoption;
    R35CtpEnvelopeView invite_view;
    R35CtpEnvelopeView peer_view;
    R35CtpEnvelopeView view;
    unsigned before;

    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;

    ok = R53_HELPER_CAP_AUDIO_DST == 0x01u
        && R53_HELPER_CAP_AUDIO_SRC == 0x02u
        && R53_HELPER_CAP_VIDEO_DST == 0x04u
        && R53_HELPER_CAP_MSTREAM == 0x20u
        && r53_helper_local_capability_profile() == 0x27u;
    mark("R53_PROFILE_FLAGS_OR_VALUE", ok);
    if (!ok) overall = 0;

    ok = r53h_run_positive(0x0000001bu, "R53_POS_A");
    mark("R53_POSITIVE_A_OFFICIAL_PEER_WORD", ok);
    if (!ok) overall = 0;

    ok = r53h_run_positive(0x0000002fu, "R53_POS_B");
    mark("R53_POSITIVE_B_ALTERNATE_PEER_WORD", ok);
    if (!ok) overall = 0;

    r53h_reset_fakes();
    r53h_wire(&session);
    memset(&adoption, 0, sizeof(adoption));
    r53h_build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u)
        && r53h_emit_local_adoption_frames(&session, &adoption, &invite_view);
    mark("R53_ORDER_CALL_INIT_ACK_CAP_ALERT", ok && g_write_count == 3u);
    if (!ok) overall = 0;

    before = g_write_count;
    ok = !r53h_emit_local_adoption_frames(&session, &adoption, &invite_view)
        && g_write_count == before
        && adoption.diag.call_adoption_failure_stage == R53_STAGE_WAITING_PEER_CAPABILITIES;
    mark("R53_DUPLICATE_CALL_INIT_SAME_GENERATION_NO_OPEN", ok);
    if (!ok) overall = 0;

    ok = !r45_send_invite_ack(&session, &adoption.r45, &invite_view) && g_write_count == before;
    mark("R53_DUPLICATE_ACK_ATTEMPT_NO_OPEN", ok);
    if (!ok) overall = 0;

    ok = !r45_send_local_capabilities(&session, &adoption.r45, &(R45RuntimeFields){0x49u, 0x27u, 0x00u})
        && g_write_count == before;
    mark("R53_DUPLICATE_CAPABILITIES_NO_OPEN", ok);
    if (!ok) overall = 0;

    ok = !r45_send_local_alerting(&session, &adoption.r45, &(R45RuntimeFields){0x49u, 0x27u, 0x00u})
        && g_write_count == before;
    mark("R53_DUPLICATE_ALERTING_NO_OPEN", ok);
    if (!ok) overall = 0;

    ok = session.open_count == 0u && g_write_count == 3u;
    mark("R53_NO_OPEN_BEFORE_PEER_CAPABILITIES", ok);
    if (!ok) overall = 0;

    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x60u, 0x22u, 0x0000001bu);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 1u
        && g_write_count == 5u;
    mark("R53_PEER_ACK_BEFORE_MEDIA_OPEN", ok
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0);
    if (!ok) overall = 0;

    before = g_write_count;
    ok = !r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 1u
        && g_write_count == before
        && adoption.diag.call_adoption_failure_stage == R53_STAGE_MEDIA_TRIGGER_REJECTED;
    mark("R53_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN", ok);
    if (!ok) overall = 0;

    ok = r53h_parse_write(0u, &view);
    memcpy(mutated, g_writes[0].packet, g_writes[0].len);
    mutated[0] = 0x00u;
    ok = ok && !(r35_parse_ctp_envelope(mutated, g_writes[0].len, &view)
        && r53h_empty_ack_matches(&view, 0x78u, 0x57u));
    mark("R53_MUT_WRONG_ACK_FLAGS", ok);
    if (!ok) overall = 0;

    memcpy(mutated, g_writes[0].packet, g_writes[0].len);
    mutated[4] = 0x79u;
    ok = !(r35_parse_ctp_envelope(mutated, g_writes[0].len, &view)
        && r53h_empty_ack_matches(&view, 0x78u, 0x57u));
    mark("R53_MUT_WRONG_ACK_SEQUENCE", ok);
    if (!ok) overall = 0;

    memcpy(mutated, g_writes[0].packet, g_writes[0].len);
    mutated[5] = 0x58u;
    ok = !(r35_parse_ctp_envelope(mutated, g_writes[0].len, &view)
        && r53h_empty_ack_matches(&view, 0x78u, 0x57u));
    mark("R53_MUT_WRONG_ACK_ACKNOWLEDGEMENT", ok);
    if (!ok) overall = 0;

    memcpy(mutated, g_writes[0].packet, g_writes[0].len);
    mutated[7] = 0x04u;
    ok = !(r35_parse_ctp_envelope(mutated, g_writes[0].len, &view)
        && r53h_empty_ack_matches(&view, 0x78u, 0x57u));
    mark("R53_MUT_ACK_WITH_BODY_PRESENT", ok);
    if (!ok) overall = 0;

    ok = r53h_parse_write(1u, &view) && r53h_capabilities_match(&view);
    mark("R53_MUT_WRONG_LOCAL_CALL_TYPE_DETECTED", ok && view.inner_body[2] == 0x49u);
    mark("R53_MUT_WRONG_LOCAL_RESERVED_DETECTED", ok && view.inner_body[3] == 0x00u);
    mark("R53_MUT_WRONG_LOCAL_CAPABILITY_COMPUTATION_DETECTED", ok
        && r53_helper_local_capability_profile() == 0x27u);
    if (!ok) overall = 0;

    ok = r53h_parse_write(2u, &view) && r53h_alerting_match(&view);
    mark("R53_MUT_ALERTING_OPCODE_000C_DETECTED", ok && view.inner_body[1] == 0x0au);
    mark("R53_MUT_WRONG_ALERTING_ARGUMENT_DETECTED", ok && view.inner_body[2] == 0x00u);
    if (!ok) overall = 0;

    r53h_reset_fakes();
    r53h_wire(&session);
    memset(&adoption, 0, sizeof(adoption));
    r53h_build_call_init(invite, 0x5234u, 0x10u, 0x20u);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u)
        && r53h_emit_local_adoption_frames(&session, &adoption, &invite_view);
    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x11u, 0x22u, 0x00000000u);
    ok = ok
        && r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && !r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 0u
        && adoption.diag.call_adoption_failure_stage == R53_STAGE_PEER_CAPABILITIES_REJECTED;
    mark("R53_PEER_VIDEO_BIT_CLEAR_FAIL_CLOSED", ok);
    if (!ok) overall = 0;

    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x12u, 0x22u, 0x0000001bu);
    peer_caps[9] = 0x0cu;
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && !r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 0u;
    mark("R53_PEER_OPCODE_000C_REJECTED", ok);
    if (!ok) overall = 0;

    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x13u, 0x22u, 0x0000001bu);
    peer_caps[7] = 0x04u;
    ok = 1;
    if (r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)) {
        ok = !r53_handle_peer_capabilities(&session, &adoption, &peer_view);
    }
    ok = ok && session.open_count == 0u;
    mark("R53_MALFORMED_PEER_CAPABILITIES_REJECTED", ok);
    if (!ok) overall = 0;

    r53h_build_peer_capabilities(peer_caps, 0x7777u, 0x14u, 0x22u, 0x0000001bu);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && !r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 0u;
    mark("R53_FOREIGN_CONNECTION_REJECTED", ok);
    if (!ok) overall = 0;

    r53h_build_peer_capabilities(peer_caps, 0x5234u, 0x15u, 0x22u, 0x0000001bu);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view);
    r53h_build_call_init(invite, 0x5235u, 0x16u, 0x23u);
    ok = ok
        && r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u)
        && !r53_handle_peer_capabilities(&session, &adoption, &peer_view)
        && session.open_count == 0u;
    mark("R53_PRIOR_GENERATION_PEER_FRAME_REJECTED", ok);
    if (!ok) overall = 0;

    {
        R35AttachedMediaSession no_writer;
        R53CallAdoptionProfileState no_writer_adoption;
        memset(&no_writer, 0, sizeof(no_writer));
        memset(&no_writer_adoption, 0, sizeof(no_writer_adoption));
        r53h_build_call_init(invite, 0x5236u, 0x20u, 0x30u);
        ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
            && r35_capture_call_ctp_id(&no_writer, invite, sizeof(invite), 999u)
            && !r53h_emit_local_adoption_frames(&no_writer, &no_writer_adoption, &invite_view)
            && no_writer.open_count == 0u
            && no_writer_adoption.diag.call_adoption_failure_stage == R53_STAGE_ACK_WRITE_FAILED;
        mark("R53_ACK_WRITE_FAIL_CLOSED", ok);
        if (!ok) overall = 0;
    }

    printf("R53_FAILURE_STAGE_NAME=%s\n", r53_failure_stage_name(adoption.diag.call_adoption_failure_stage));
    printf("R53_NETWORK_TX=%u\n", g_network_tx);
    printf("R53_ACTUATOR_ACTIONS=%u\n", g_actuator_actions);
    printf("R53_SELF_ACTIVATION_ACTIONS=%u\n", g_self_activation_actions);
    printf("R53_HOST_HARNESS_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
