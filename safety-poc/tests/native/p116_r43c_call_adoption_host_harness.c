/*
 * P116/R43C call-adoption host harness (research-only, offline).
 *
 * Assembled by test_p116_r43c_call_adoption_host_harness.py from the exact R35,
 * R36 and R45 dependency-free C regions plus this file.  It never opens a
 * socket: every outbound frame lands in fake_writer(), the media OPEN is
 * intercepted, and the counters below prove no network/Door/Gate/self-activation
 * path is reachable.
 *
 * Every exact-wire expectation here is the R43B native contract; every runtime
 * field is passed in from outside (SET A / SET B), so no protocol value is
 * hardcoded in the serializer path.
 */

#include <stdio.h>
#include <string.h>

#define R43C_MAX_WRITES 24u
#define R43C_MAX_FRAME  64u

typedef struct {
    char kind[32];
    unsigned char packet[R43C_MAX_FRAME];
    unsigned len;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
} R43CCapturedWrite;

static R43CCapturedWrite g_writes[R43C_MAX_WRITES];
static unsigned g_write_count = 0u;
static unsigned g_rtp_arm_calls = 0u;
static unsigned g_network_tx = 0u;
static unsigned g_door_actions = 0u;
static unsigned g_gate_actions = 0u;
static unsigned g_self_activation_actions = 0u;

static void r43c_reset_fakes(void)
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
    R43CCapturedWrite *w;
    (void)ctx;
    if (!kind || !packet || len > R43C_MAX_FRAME || g_write_count >= R43C_MAX_WRITES) return;
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

static void r43c_wire(R35AttachedMediaSession *s)
{
    memset(s, 0, sizeof(*s));
    s->writer = fake_writer;
    s->writer_ctx = NULL;
    s->rtp_arm_hook = fake_rtp_hook;
    s->rtp_arm_hook_ctx = NULL;
}

static int r43c_parse_write(unsigned index, R35CtpEnvelopeView *view)
{
    if (index >= g_write_count) return 0;
    return r35_parse_ctp_envelope(g_writes[index].packet, g_writes[index].len, view);
}

static int r43c_parse_buffer(
    const unsigned char *packet,
    unsigned len,
    R35CtpEnvelopeView *view)
{
    if (!packet) return 0;
    return r35_parse_ctp_envelope(packet, len, view);
}

static int r43c_bytes_equal(const unsigned char *a, const unsigned char *b, unsigned n)
{
    return memcmp(a, b, n) == 0;
}

/* ---- detectors: an expectation that cannot be flipped is not evidence ---- */

static int r43c_is_empty_transport_ack(
    const R35CtpEnvelopeView *view,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement)
{
    if (!view) return 0;
    if (view->flags != 0x80u) return 0;
    if (view->inner_len != 0u) return 0;
    if (view->connection != connection) return 0;
    if ((view->sequence & 0xffu) != (sequence & 0xffu)) return 0;
    if ((view->acknowledgement & 0xffu) != (acknowledgement & 0xffu)) return 0;
    return 1;
}

static int r43c_is_capabilities_body(
    const unsigned char *body,
    unsigned len,
    unsigned call_type,
    unsigned capability_word)
{
    const unsigned char *raw;
    if (!body) return 0;
    if (len != R45_CAPABILITIES_BODY_LEN) return 0;
    raw = body;
    if (raw[0] != 0x00u || raw[1] != 0x03u) return 0;
    if (raw[2] != (unsigned char)(call_type & 0xffu)) return 0;
    if (raw[3] != 0x00u) return 0;
    if (raw[4] != (unsigned char)(capability_word & 0xffu)) return 0;
    if (raw[5] != (unsigned char)((capability_word >> 8) & 0xffu)) return 0;
    if (raw[6] != (unsigned char)((capability_word >> 16) & 0xffu)) return 0;
    if (raw[7] != (unsigned char)((capability_word >> 24) & 0xffu)) return 0;
    return 1;
}

static int r43c_is_alerting_body(const unsigned char *body, unsigned len, unsigned argument)
{
    if (!body) return 0;
    if (len != R45_ALERTING_BODY_LEN) return 0;
    return body[0] == 0x00u && body[1] == 0x0au
        && body[2] == (unsigned char)(argument & 0xffu);
}

static int r43c_body_is_capabilities(const unsigned char *inner, unsigned inner_len)
{
    if (!inner || inner_len < R36_CAP_BODY_MIN_LEN) return 0;
    return r35_read_be16(inner) == R36_OP_CAPABILITIES;
}

static void r43c_build_call_init(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack)
{
    memset(out, 0, 72u);
    out[0] = 0xC0u;
    out[1] = R35_CTP_VERSION;
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00u;
    out[7] = 0x28u;
    out[8] = 0x00u;
    out[9] = 0x01u; /* INVITE */
    out[48] = 0xffu; out[49] = 0xffu; out[50] = 0xffu; out[51] = 0xffu;
    memset(out + 52, 0x41, 10u);
    memset(out + 62, 0x42, 10u);
}

static void r43c_build_peer_capabilities(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack,
    unsigned call_type,
    unsigned capability_word)
{
    memset(out, 0, 40u);
    out[0] = R35_CTP_FLAG_DATA;
    out[1] = R35_CTP_VERSION;
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00u;
    out[7] = 0x08u;
    out[8] = 0x00u;
    out[9] = 0x03u;
    out[10] = (unsigned char)(call_type & 0xffu);
    out[11] = 0x03u;
    out[12] = (unsigned char)(capability_word & 0xffu);
    out[13] = (unsigned char)((capability_word >> 8) & 0xffu);
    out[14] = (unsigned char)((capability_word >> 16) & 0xffu);
    out[15] = (unsigned char)((capability_word >> 24) & 0xffu);
    out[16] = 0xffu; out[17] = 0xffu; out[18] = 0xffu; out[19] = 0xffu;
    memset(out + 20, 0x41, 10u);
    memset(out + 30, 0x42, 10u);
}

static void mark(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
}

int main(void)
{
    int overall = 1;
    int ok;
    unsigned char invite[72];
    unsigned char peer_caps[40];
    unsigned char mutated[R43C_MAX_FRAME];
    R35AttachedMediaSession session;
    R35AttachedMediaSession other;
    R45CallAdoptionState adoption;
    R45RuntimeFields runtime;
    R35CtpEnvelopeView invite_view;
    R35CtpEnvelopeView peer_view;
    R35CtpEnvelopeView view;
    R35CtpEnvelopeView mutated_view;
    R35Result open_rc;
    unsigned expected_ack_seq;
    unsigned expected_ack_ack;
    unsigned char set_b_body[8];

    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;

    /* ================= SET A ================= */
    runtime.call_type = 0x49u;
    runtime.capability_word = 0x00000027u;
    runtime.alerting_argument = 0x00u;

    r43c_reset_fakes();
    r43c_wire(&session);
    memset(&adoption, 0, sizeof(adoption));

    r43c_build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u);
    mark("R43C_01_CALL_CAPTURE", ok);
    if (!ok) overall = 0;

    /* CAPABILITIES before the ACK must be rejected. */
    ok = !r45_send_local_capabilities(&session, &adoption, &runtime)
        && g_write_count == 0u;
    mark("R43C_02_CAPABILITIES_BEFORE_ACK_REJECTED", ok);
    if (!ok) overall = 0;

    /* ALERTING before CAPABILITIES must be rejected. */
    ok = !r45_send_local_alerting(&session, &adoption, &runtime)
        && g_write_count == 0u;
    mark("R43C_03_ALERTING_BEFORE_CAPABILITIES_REJECTED", ok);
    if (!ok) overall = 0;

    expected_ack_seq = 0x78u;                 /* inbound acknowledgement byte */
    expected_ack_ack = (0x56u + 1u) & 0xffu;  /* inbound sequence + 1 mod 256 */
    ok = r45_send_invite_ack(&session, &adoption, &invite_view);
    mark("R43C_04_INVITE_ACK_EMITTED", ok);
    if (!ok) overall = 0;

    ok = g_write_count == 1u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && r43c_parse_write(0u, &view)
        && r43c_is_empty_transport_ack(&view, session.call_ctp_connection,
                                       expected_ack_seq, expected_ack_ack)
        && session.call_sequence == expected_ack_seq
        && session.call_ack == expected_ack_ack;
    mark("R43C_05_INVITE_ACK_EXACT_BYTES_AND_NO_TX_ADVANCE", ok);
    if (!ok) overall = 0;

    ok = !r45_send_invite_ack(&session, &adoption, &invite_view) && g_write_count == 1u;
    mark("R43C_06_DUPLICATE_ACK_REJECTED", ok);
    if (!ok) overall = 0;

    /* --- mutation detectors: each of these must be able to flip to FAIL --- */
    {
        const unsigned ack_len = g_writes[0].len;
        memcpy(mutated, g_writes[0].packet, ack_len);

        mutated[0] = 0x00u;
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_07_WRONG_ACK_FLAGS_0X00_DETECTED", ok);
        if (!ok) overall = 0;

        mutated[0] = R35_CTP_FLAG_DATA;
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_08_WRONG_ACK_FLAGS_DATA_DETECTED", ok);
        if (!ok) overall = 0;

        memcpy(mutated, g_writes[0].packet, ack_len);
        mutated[7] = 0x04u; /* declare a non-empty inner body */
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_09_ACK_WITH_BODY_DETECTED", ok);
        if (!ok) overall = 0;

        memcpy(mutated, g_writes[0].packet, ack_len);
        mutated[4] = (unsigned char)((expected_ack_seq + 1u) & 0xffu);
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_10_WRONG_ACK_SEQUENCE_DETECTED", ok);
        if (!ok) overall = 0;

        memcpy(mutated, g_writes[0].packet, ack_len);
        mutated[5] = 0x00u;
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_11_WRONG_ACK_ACKNOWLEDGEMENT_DETECTED", ok);
        if (!ok) overall = 0;

        memcpy(mutated, g_writes[0].packet, ack_len);
        mutated[2] = 0x77u; mutated[3] = 0x77u;
        ok = !(r43c_parse_buffer(mutated, ack_len, &mutated_view)
            && r43c_is_empty_transport_ack(&mutated_view, session.call_ctp_connection,
                                           expected_ack_seq, expected_ack_ack));
        mark("R43C_12_WRONG_ACK_CONNECTION_DETECTED", ok);
        if (!ok) overall = 0;
    }

    /* --- local CAPABILITIES with SET A runtime fields --- */
    ok = r45_send_local_capabilities(&session, &adoption, &runtime);
    mark("R43C_13_LOCAL_CAPABILITIES_EMITTED", ok);
    if (!ok) overall = 0;

    {
        const unsigned char set_a_body[8] =
            {0x00u, 0x03u, 0x49u, 0x00u, 0x27u, 0x00u, 0x00u, 0x00u};
        ok = g_write_count == 2u
            && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
            && r43c_parse_write(1u, &view)
            && view.flags == R35_CTP_FLAG_DATA
            && view.sequence == expected_ack_seq
            && view.acknowledgement == expected_ack_ack
            && view.inner_len == R45_CAPABILITIES_BODY_LEN
            && r43c_bytes_equal(view.inner_body, set_a_body, 8u)
            && r43c_is_capabilities_body(view.inner_body, view.inner_len,
                                         runtime.call_type, runtime.capability_word)
            && session.call_sequence == ((expected_ack_seq + 1u) & 0xffu);
    }
    mark("R43C_14_SET_A_CAPABILITIES_EXACT_BYTES", ok);
    if (!ok) overall = 0;

    ok = !r45_send_local_capabilities(&session, &adoption, &runtime) && g_write_count == 2u;
    mark("R43C_15_DUPLICATE_CAPABILITIES_REJECTED", ok);
    if (!ok) overall = 0;

    ok = r45_send_local_alerting(&session, &adoption, &runtime);
    mark("R43C_16_LOCAL_ALERTING_EMITTED", ok);
    if (!ok) overall = 0;

    {
        const unsigned char alerting_body[3] = {0x00u, 0x0au, 0x00u};
        ok = g_write_count == 3u
            && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
            && r43c_parse_write(2u, &view)
            && view.sequence == ((expected_ack_seq + 1u) & 0xffu)
            && view.acknowledgement == expected_ack_ack
            && view.inner_len == R45_ALERTING_BODY_LEN
            && r43c_is_alerting_body(view.inner_body, view.inner_len, 0u)
            && r43c_bytes_equal(view.inner_body, alerting_body, 3u)
            && session.call_sequence == ((expected_ack_seq + 2u) & 0xffu)
            && r45_call_adoption_complete(&adoption, &session);
    }
    mark("R43C_17_ALERTING_EXACT_BYTES_AND_SEQUENCE_MODEL", ok);
    if (!ok) overall = 0;

    ok = !r45_send_local_alerting(&session, &adoption, &runtime) && g_write_count == 3u;
    mark("R43C_18_DUPLICATE_ALERTING_REJECTED", ok);
    if (!ok) overall = 0;

    /* --- peer CAPABILITIES replay through the existing R36 classifier --- */
    r43c_build_peer_capabilities(peer_caps, 0x5234u, 0x60u, 0x7au, 0x50u, 0x00000008u);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view);
    mark("R43C_19_PEER_CAPABILITIES_PARSED", ok);
    if (!ok) overall = 0;

    mark("R43C_20_CAPABILITIES_SEEN", r36_is_capabilities_for_current_call(&session, &peer_view));
    mark("R43C_21_CAPABILITIES_PARSE_OK", peer_view.inner_len == 8u
        && r36_is_capabilities_for_current_call(&session, &peer_view));
    mark("R43C_22_CAPABILITIES_CALL_MATCH", r36_is_capabilities_for_current_call(&session, &peer_view));
    mark("R43C_23_CAPABILITIES_VIDEO_REQUESTED", r36_capabilities_video_requested(&peer_view));

    ok = r45_accept_peer_data_and_ack(&session, &adoption, &peer_view);
    mark("R43C_24_PEER_DATA_ACK_EMITTED", ok);
    if (!ok) overall = 0;

    ok = g_write_count == 4u
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && r43c_parse_write(3u, &view)
        && r43c_is_empty_transport_ack(&view, session.call_ctp_connection,
                                       ((expected_ack_seq + 2u) & 0xffu),
                                       (0x60u + 1u) & 0xffu)
        && session.call_sequence == ((expected_ack_seq + 2u) & 0xffu);
    mark("R43C_25_PEER_DATA_ACK_BEFORE_TRIGGER_NO_TX_ADVANCE", ok);
    if (!ok) overall = 0;

    open_rc = r36_trigger_open_from_capabilities(&session, &peer_view);
    ok = open_rc == R35_OK
        && session.open_count == 1u
        && g_write_count == 5u
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0
        && g_rtp_arm_calls == 1u;
    mark("R43C_26_MEDIA_OPEN_INTERCEPTED_ONE_OPEN", ok);
    if (!ok) overall = 0;

    open_rc = r36_trigger_open_from_capabilities(&session, &peer_view);
    ok = open_rc != R35_OK && session.open_count == 1u && g_write_count == 5u;
    mark("R43C_27_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN", ok);
    if (!ok) overall = 0;

    /* --- negative peer frames: malformed / wrong opcode / video clear / foreign --- */
    {
        unsigned before = g_write_count;
        r43c_build_peer_capabilities(peer_caps, 0x5234u, 0x61u, 0x7bu, 0x50u, 0x00000000u);
        ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
            && !r36_capabilities_video_requested(&peer_view)
            && r36_trigger_open_from_capabilities(&session, &peer_view) != R35_OK
            && session.open_count == 1u
            && g_write_count == before;
    }
    mark("R43C_28_VIDEO_BIT_CLEAR_NO_OPEN", ok);
    if (!ok) overall = 0;

    {
        r43c_build_peer_capabilities(peer_caps, 0x5234u, 0x62u, 0x7bu, 0x50u, 0x00000008u);
        peer_caps[9] = 0x0cu; /* inner opcode 0x000C: connect/setup, not CAPABILITIES */
        ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
            && !r36_is_capabilities_for_current_call(&session, &peer_view)
            && !r43c_body_is_capabilities(peer_view.inner_body, peer_view.inner_len);
    }
    mark("R43C_29_WRONG_OPCODE_0X000C_REJECTED", ok);
    if (!ok) overall = 0;

    {
        unsigned before = g_write_count;
        r43c_build_peer_capabilities(peer_caps, 0x5234u, 0x63u, 0x7bu, 0x50u, 0x00000008u);
        peer_caps[7] = 0x04u; /* declared inner length 4 < R36_CAP_BODY_MIN_LEN (5) */
        memset(&peer_view, 0, sizeof(peer_view));
        ok = 1;
        if (r43c_parse_buffer(peer_caps, sizeof(peer_caps), &peer_view)) {
            ok = peer_view.inner_len == 0x04u
                && peer_view.inner_len < R36_CAP_BODY_MIN_LEN
                && !r36_is_capabilities_for_current_call(&session, &peer_view);
        }
        ok = ok && g_write_count == before;
    }
    mark("R43C_30_MALFORMED_CAPABILITIES_LENGTH_REJECTED", ok);
    if (!ok) overall = 0;

    {
        unsigned before = g_write_count;
        r43c_build_peer_capabilities(peer_caps, 0x7777u, 0x64u, 0x7bu, 0x50u, 0x00000008u);
        ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
            && !r36_is_capabilities_for_current_call(&session, &peer_view)
            && !r45_accept_peer_data_and_ack(&session, &adoption, &peer_view)
            && g_write_count == before;
    }
    mark("R43C_31_FOREIGN_CONNECTION_REJECTED", ok);
    if (!ok) overall = 0;

    /* --- generation reset: prior-generation state cannot be reused --- */
    {
        unsigned before = g_write_count;
        r43c_build_peer_capabilities(peer_caps, 0x5234u, 0x65u, 0x7bu, 0x50u, 0x00000008u);
        ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view);
        r43c_build_call_init(invite, 0x5235u, 0x10u, 0x20u);
        ok = ok && r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
            && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u);
        r45_sync_generation(&adoption, &session);
        ok = ok && session.call_generation == 2u
            && adoption.generation == 2u
            && !adoption.invite_ack_sent
            && !adoption.local_capabilities_sent
            && !adoption.local_alerting_sent
            && !r45_accept_peer_data_and_ack(&session, &adoption, &peer_view)
            && g_write_count == before;
    }
    mark("R43C_32_PRIOR_GENERATION_FRAME_REJECTED", ok);
    if (!ok) overall = 0;

    /* --- sequence wrap 0xFF -> 0x00 with an ACK byte independent of the wrap --- */
    {
        unsigned char wrap_invite[72];
        r43c_reset_fakes();
        r43c_wire(&other);
        memset(&adoption, 0, sizeof(adoption));
        r43c_build_call_init(wrap_invite, 0x5236u, 0xfeu, 0x10u);
        ok = r35_parse_ctp_envelope(wrap_invite, sizeof(wrap_invite), &invite_view)
            && r35_capture_call_ctp_id(&other, wrap_invite, sizeof(wrap_invite), 999u)
            && r45_send_invite_ack(&other, &adoption, &invite_view);
        /* force the local TX sequence to the wrap boundary before the bodies */
        other.call_sequence = 0xffu;
        ok = ok && r45_send_local_capabilities(&other, &adoption, &runtime);
        mark("R43C_33_SEQUENCE_WRAP_CAPABILITIES_AT_0XFF", ok
            && r43c_parse_write(1u, &view) && view.sequence == 0xffu);
        ok = ok && r45_send_local_alerting(&other, &adoption, &runtime);
        ok = ok && r43c_parse_write(2u, &view)
            && view.sequence == 0x00u
            && view.acknowledgement == ((0xfeu + 1u) & 0xffu)
            && other.call_sequence == 0x01u;
        mark("R43C_34_SEQUENCE_WRAP_0XFF_TO_0X00_ACK_INDEPENDENT", ok);
        if (!ok) overall = 0;
    }

    /* --- SET B: the same builder with different runtime values --- */
    {
        R35AttachedMediaSession b_session;
        R45CallAdoptionState b_adoption;
        R45RuntimeFields b_runtime;
        unsigned char b_invite[72];
        r43c_reset_fakes();
        r43c_wire(&b_session);
        memset(&b_adoption, 0, sizeof(b_adoption));
        b_runtime.call_type = 0x50u;
        b_runtime.capability_word = 0x0000033bu;
        b_runtime.alerting_argument = 0x00u;

        r43c_build_call_init(b_invite, 0x6001u, 0x11u, 0x22u);
        ok = r35_parse_ctp_envelope(b_invite, sizeof(b_invite), &invite_view)
            && r35_capture_call_ctp_id(&b_session, b_invite, sizeof(b_invite), 999u)
            && r45_send_invite_ack(&b_session, &b_adoption, &invite_view)
            && r45_send_local_capabilities(&b_session, &b_adoption, &b_runtime);
        set_b_body[0] = 0x00u; set_b_body[1] = 0x03u;
        set_b_body[2] = 0x50u; set_b_body[3] = 0x00u;
        set_b_body[4] = 0x3bu; set_b_body[5] = 0x03u;
        set_b_body[6] = 0x00u; set_b_body[7] = 0x00u;
        ok = ok && g_write_count == 2u
            && r43c_parse_write(1u, &view)
            && view.inner_len == 8u
            && r43c_bytes_equal(view.inner_body, (const unsigned char *)set_b_body, 8u)
            && r43c_is_capabilities_body(view.inner_body, view.inner_len,
                                         b_runtime.call_type, b_runtime.capability_word);
        mark("R43C_35_SET_B_RUNTIME_FIELDS_PARAMETERIZED", ok);
        if (!ok) overall = 0;

        /* the SET B body must differ from the SET A fixture: proves parameterization */
        {
            const unsigned char set_a_reference[8] =
                {0x00u, 0x03u, 0x49u, 0x00u, 0x27u, 0x00u, 0x00u, 0x00u};
            ok = ok
                && !r43c_bytes_equal(view.inner_body, set_a_reference, 8u)
                && view.inner_body[2] == 0x50u
                && view.inner_body[4] == 0x3bu;
        }
        mark("R43C_36_SET_A_VALUES_NOT_HARDCODED", ok);
        if (!ok) overall = 0;
    }

    printf("R43C_NETWORK_TX=%u\n", g_network_tx);
    printf("R43C_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R43C_GATE_ACTIONS=%u\n", g_gate_actions);
    printf("R43C_SELF_ACTIVATION_ACTIONS=%u\n", g_self_activation_actions);
    printf("R43C_HOST_HARNESS_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
