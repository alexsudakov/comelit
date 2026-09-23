/*
 * P116/R45 call-adoption host harness.
 *
 * Research-only executable assembled by the Python test from the exact R35,
 * R36 and R45 dependency-free C regions.  It never opens a socket and every
 * outbound frame is intercepted by fake_writer().
 */

#include <stdio.h>
#include <string.h>

#define MAX_WRITES 16u
#define MAX_FRAME  64u

typedef struct {
    char kind[32];
    unsigned char packet[MAX_FRAME];
    unsigned len;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
} CapturedWrite;

static CapturedWrite g_writes[MAX_WRITES];
static unsigned g_write_count = 0u;
static unsigned g_rtp_arm_calls = 0u;
static unsigned g_network_tx = 0u;
static unsigned g_door_actions = 0u;
static unsigned g_gate_actions = 0u;

static void reset_fakes(void)
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
    CapturedWrite *w;
    (void)ctx;
    if (!kind || !packet || len > MAX_FRAME || g_write_count >= MAX_WRITES) return;
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

static void wire(R35AttachedMediaSession *s)
{
    memset(s, 0, sizeof(*s));
    s->writer = fake_writer;
    s->writer_ctx = NULL;
    s->rtp_arm_hook = fake_rtp_hook;
    s->rtp_arm_hook_ctx = NULL;
}

static void build_sample_call_init(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack)
{
    memset(out, 0, 72u);
    out[0] = 0xC0u; /* SYN + DATA bit, matching captured CALL_INIT shape */
    out[1] = 0x18u;
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00u;
    out[7] = 0x28u;
    out[8] = 0x00u;
    out[9] = 0x01u; /* INVITE */
    out[48] = 0xffu; out[49] = 0xffu; out[50] = 0xffu; out[51] = 0xffu;
    memset(out + 52, 0x41, 10u); /* peer source */
    memset(out + 62, 0x42, 10u); /* local destination */
}

static void build_peer_capabilities(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack,
    unsigned capability_word)
{
    memset(out, 0, 40u);
    out[0] = R35_CTP_FLAG_DATA;
    out[1] = 0x18u;
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00u;
    out[7] = 0x08u;
    out[8] = 0x00u;
    out[9] = 0x03u;
    out[10] = 0x50u;
    out[11] = 0x03u;
    out[12] = (unsigned char)(capability_word & 0xffu);
    out[13] = (unsigned char)((capability_word >> 8) & 0xffu);
    out[14] = (unsigned char)((capability_word >> 16) & 0xffu);
    out[15] = (unsigned char)((capability_word >> 24) & 0xffu);
    out[16] = 0xffu; out[17] = 0xffu; out[18] = 0xffu; out[19] = 0xffu;
    memset(out + 20, 0x41, 10u);
    memset(out + 30, 0x42, 10u);
}

static int write_parses(unsigned index, R35CtpEnvelopeView *view)
{
    if (index >= g_write_count) return 0;
    return r35_parse_ctp_envelope(
        g_writes[index].packet,
        g_writes[index].len,
        view);
}

static int bytes_equal(const unsigned char *a, const unsigned char *b, unsigned n)
{
    return memcmp(a, b, n) == 0;
}

int main(void)
{
    int overall = 1;
    int ok;
    unsigned char invite[72];
    unsigned char peer_caps[40];
    R35AttachedMediaSession session;
    R45CallAdoptionState adoption;
    R45RuntimeFields runtime;
    R35CtpEnvelopeView invite_view;
    R35CtpEnvelopeView peer_view;
    R35CtpEnvelopeView view;
    R35Result open_rc;

    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;
    reset_fakes();
    wire(&session);
    memset(&adoption, 0, sizeof(adoption));

    build_sample_call_init(invite, 0x5234u, 0x56u, 0x78u);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u);
    printf("R45_SCENARIO_1_CALL_CAPTURE=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = session.call_ctp_connection == 0xD234u
        && session.call_sequence == 0x78u
        && session.call_ack == 0x56u
        && session.call_generation == 1u;
    printf("R45_SCENARIO_2_CAPTURE_STATE=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* Initial empty ACK: ack becomes accepted INVITE sequence+1, TX sequence
     * remains the peer acknowledgement seed. */
    ok = r45_send_invite_ack(&session, &adoption, &invite_view);
    printf("R45_SCENARIO_3_INVITE_ACK_EMITTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = g_write_count == 1u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && g_writes[0].len == 32u
        && write_parses(0u, &view)
        && view.flags == 0x80u
        && view.connection == 0xD234u
        && view.sequence == 0x78u
        && view.acknowledgement == 0x57u
        && view.inner_len == 0u
        && session.call_sequence == 0x78u
        && session.call_ack == 0x57u;
    printf("R45_SCENARIO_4_INVITE_ACK_NATIVE_BYTES=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* Duplicate initial ACK must not create a second local adoption write. */
    ok = !r45_send_invite_ack(&session, &adoption, &invite_view)
        && g_write_count == 1u;
    printf("R45_SCENARIO_5_DUPLICATE_INVITE_ACK_REJECTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    runtime.call_type = 0x49u;
    runtime.capability_word = 0x12345678u;
    runtime.alerting_argument = 0u;

    ok = r45_send_local_capabilities(&session, &adoption, &runtime);
    printf("R45_SCENARIO_6_LOCAL_CAPABILITIES_EMITTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    {
        const unsigned char expected_body[8] =
            {0x00u, 0x03u, 0x49u, 0x00u, 0x78u, 0x56u, 0x34u, 0x12u};
        ok = g_write_count == 2u
            && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
            && g_writes[1].len == 40u
            && write_parses(1u, &view)
            && view.flags == R35_CTP_FLAG_DATA
            && view.sequence == 0x78u
            && view.acknowledgement == 0x57u
            && view.inner_len == 8u
            && bytes_equal(view.inner_body, expected_body, 8u)
            && session.call_sequence == 0x79u;
    }
    printf("R45_SCENARIO_7_LOCAL_CAPABILITIES_NATIVE_BYTES=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = !r45_send_local_capabilities(&session, &adoption, &runtime)
        && g_write_count == 2u;
    printf("R45_SCENARIO_8_DUPLICATE_CAPABILITIES_REJECTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = r45_send_local_alerting(&session, &adoption, &runtime);
    printf("R45_SCENARIO_9_LOCAL_ALERTING_EMITTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    {
        const unsigned char expected_body[3] = {0x00u, 0x0au, 0x00u};
        ok = g_write_count == 3u
            && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
            && g_writes[2].len == 36u
            && write_parses(2u, &view)
            && view.flags == R35_CTP_FLAG_DATA
            && view.sequence == 0x79u
            && view.acknowledgement == 0x57u
            && view.inner_len == 3u
            && bytes_equal(view.inner_body, expected_body, 3u)
            && session.call_sequence == 0x7au
            && r45_call_adoption_complete(&adoption, &session);
    }
    printf("R45_SCENARIO_10_LOCAL_ALERTING_NATIVE_BYTES=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = !r45_send_local_alerting(&session, &adoption, &runtime)
        && g_write_count == 3u;
    printf("R45_SCENARIO_11_DUPLICATE_ALERTING_REJECTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* A real peer body-bearing CAPABILITIES frame advances our acknowledgement
     * and gets an empty transport ACK before the higher-level R36 trigger. */
    build_peer_capabilities(peer_caps, 0x5234u, 0x60u, 0x7au, 0x0000003bu);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
        && r36_is_capabilities_for_current_call(&session, &peer_view)
        && r36_capabilities_video_requested(&peer_view);
    printf("R45_SCENARIO_12_PEER_CAPABILITIES_MATCH=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = r45_accept_peer_data_and_ack(&session, &adoption, &peer_view);
    printf("R45_SCENARIO_13_PEER_CAPABILITIES_ACK_EMITTED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    ok = g_write_count == 4u
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && write_parses(3u, &view)
        && view.flags == 0x80u
        && view.sequence == 0x7au
        && view.acknowledgement == 0x61u
        && view.inner_len == 0u
        && session.call_sequence == 0x7au
        && session.call_ack == 0x61u;
    printf("R45_SCENARIO_14_PEER_ACK_UPDATES_STATE_NO_TX_ADVANCE=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* Existing R36 trigger now sees the same peer CAPABILITIES and sends the
     * media OPEN on the updated CTP transaction. */
    open_rc = r36_trigger_open_from_capabilities(&session, &peer_view);
    ok = open_rc == R35_OK
        && session.open_count == 1u
        && g_write_count == 5u
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0
        && write_parses(4u, &view)
        && view.sequence == 0x7au
        && view.acknowledgement == 0x61u
        && g_rtp_arm_calls == 1u;
    printf("R45_SCENARIO_15_MEDIA_OPEN_USES_UPDATED_CTP_STATE=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    open_rc = r36_trigger_open_from_capabilities(&session, &peer_view);
    ok = open_rc != R35_OK && session.open_count == 1u && g_write_count == 5u;
    printf("R45_SCENARIO_16_DUPLICATE_PEER_CAP_NO_SECOND_OPEN=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* New call generation resets adoption state and cannot reuse prior
     * signaling completion. */
    build_sample_call_init(invite, 0x5235u, 0x10u, 0x20u);
    ok = r35_parse_ctp_envelope(invite, sizeof(invite), &invite_view)
        && r35_capture_call_ctp_id(&session, invite, sizeof(invite), 999u);
    r45_sync_generation(&adoption, &session);
    ok = ok
        && session.call_generation == 2u
        && adoption.generation == 2u
        && !adoption.invite_ack_sent
        && !adoption.local_capabilities_sent
        && !adoption.local_alerting_sent
        && !r45_call_adoption_complete(&adoption, &session);
    printf("R45_SCENARIO_17_GENERATION_RESET=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    /* Wrong peer connection is rejected without adding a write. */
    {
        unsigned before = g_write_count;
        build_peer_capabilities(peer_caps, 0x7777u, 0x30u, 0x20u, 0x3bu);
        ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &peer_view)
            && !r45_accept_peer_data_and_ack(&session, &adoption, &peer_view)
            && g_write_count == before;
    }
    printf("R45_SCENARIO_18_FOREIGN_CONNECTION_FAILS_CLOSED=%s\n", ok ? "PASS" : "FAIL");
    if (!ok) overall = 0;

    printf("R45_NETWORK_TX=%u\n", g_network_tx);
    printf("R45_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R45_GATE_ACTIONS=%u\n", g_gate_actions);
    printf("R45_HOST_HARNESS_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
