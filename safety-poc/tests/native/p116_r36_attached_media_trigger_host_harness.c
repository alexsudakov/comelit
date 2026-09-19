/*
 * P116/R36 attached inbound media trigger host harness.
 *
 * This file is NOT part of the packaged helper.  It is a research-only,
 * host-compilable driver for the dependency-free
 * R35_ATTACHED_MEDIA_BEGIN/END core region (unchanged, from R35) plus the
 * new R36_ATTACHED_MEDIA_TRIGGER_BEGIN/END core region (this round),
 * concatenated by the Python test module
 * (test_p116_r36_attached_media_trigger.py) in front of this file's
 * contents.  It proves the OPEN-trigger decision logic actually behaves as
 * specified against synthetic CTP envelopes, not merely that certain
 * strings are present in the generated source.
 *
 * This harness never opens a socket, never forks, never touches the
 * filesystem beyond stdio, and never calls Door/Gate.  All transport and
 * RTP-forwarding side effects are captured by fake, in-memory
 * writer/hook functions so the assertions below are pure counters.
 */

#include <stdio.h>
#include <string.h>

/* ---- fake writer / RTP-arm hook (host-only substitutes, same shape R35's
 * own harness uses) ---- */

static unsigned g_open_writes = 0;
static unsigned g_stop_writes = 0;
static unsigned g_rtp_arm_calls = 0;
static unsigned g_rtp_disarm_calls = 0;
static unsigned g_network_tx = 0;
static unsigned g_door_actions = 0;
static unsigned g_gate_actions = 0;

static void fake_writer(
    void *ctx,
    const char *kind,
    const unsigned char *packet,
    unsigned len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement)
{
    (void)ctx;
    (void)packet;
    (void)len;
    (void)connection;
    (void)sequence;
    (void)acknowledgement;
    if (strcmp(kind, "MEDIA_OPEN") == 0) {
        g_open_writes++;
    } else if (strcmp(kind, "MEDIA_STOP") == 0) {
        g_stop_writes++;
    }
}

static void fake_rtp_hook(void *ctx, int armed)
{
    (void)ctx;
    if (armed) {
        g_rtp_arm_calls++;
    } else {
        g_rtp_disarm_calls++;
    }
}

static void reset_fakes(void)
{
    g_open_writes = 0;
    g_stop_writes = 0;
    g_rtp_arm_calls = 0;
    g_rtp_disarm_calls = 0;
}

static void wire(R35AttachedMediaSession *s)
{
    memset(s, 0, sizeof(*s));
    s->writer = fake_writer;
    s->writer_ctx = NULL;
    s->rtp_arm_hook = fake_rtp_hook;
    s->rtp_arm_hook_ctx = NULL;
}

/* ---- sample CTP envelope builders, mirroring R35's own
 * build_sample_call_init (R30-proven layout: 8 header + inner_len body
 * (padded to 4) + 4 trailer + 10 source + 10 dest). ---- */

static void build_sample_call_init(unsigned char *out, unsigned peer_connection, unsigned seq, unsigned ack)
{
    memset(out, 0, 72);
    out[0] = 0xC0; /* SYN */
    out[1] = 0x18; /* version */
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00;
    out[7] = 0x28; /* inner_len = 40, BE16 */
    out[8] = 0x00;
    out[9] = 0x01; /* OP_INVITE */
    out[48] = 0xff; out[49] = 0xff; out[50] = 0xff; out[51] = 0xff; /* trailer */
    memset(out + 52, 0x41, 10); /* source_raw */
    memset(out + 62, 0x42, 10); /* dest_raw */
}

/* Mirrors the independently-confirmed public CTP capabilities body
 * (.r33-evidence/public-vip/viper/ctp.py:28 OP_CAPABILITIES=0x0003;
 * .r33-evidence/public-vip/viper/call.py:43, 8-byte DATA body opcode(2)
 * type(1) reserved(1) word(4)) wrapped in the same R30-proven outer CTP
 * envelope R35's own builder already uses.  40 bytes total:
 * 8 header + 8 inner body (already 4-aligned) + 4 trailer + 10 + 10. */
static void build_sample_capabilities(
    unsigned char *out, unsigned peer_connection, unsigned seq, unsigned ack, unsigned char cap_word_byte)
{
    memset(out, 0, 40);
    out[0] = R35_CTP_FLAG_DATA; /* 0x40 */
    out[1] = 0x18;              /* version */
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00;
    out[7] = 0x08;      /* inner_len = 8, BE16 */
    out[8] = 0x00;
    out[9] = 0x03;      /* OP_CAPABILITIES, BE16 */
    out[10] = 0x49;     /* call-type byte (matches native 'I'), unused by the trigger */
    out[11] = 0x00;     /* reserved */
    out[12] = cap_word_byte; /* capability word low byte -- bit3 is the trigger */
    out[13] = 0x00; out[14] = 0x00; out[15] = 0x00;
    out[16] = 0xff; out[17] = 0xff; out[18] = 0xff; out[19] = 0xff; /* trailer */
    memset(out + 20, 0x41, 10); /* source_raw */
    memset(out + 30, 0x42, 10); /* dest_raw */
}

int main(void)
{
    int overall_ok = 1;
    unsigned char buf[72];
    R35CtpEnvelopeView view;
    R35Result rc;
    int ok;

    /* R35's forbidden-state table is not exercised by this trigger-focused
     * harness (R35's own harness already proves it); silence the unused-
     * constant warning without touching R35's core region. */
    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;

    /* ---- 1. pre-trigger: a freshly captured call has never opened ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x5001u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        ok = (s.open_count == 0u) && (g_open_writes == 0u);
        printf("R36_SCENARIO_1_PRE_TRIGGER=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 2. exact trigger: matching capabilities with bit3 set -> exactly
     * one OPEN, RTP armed only after it. ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x5002u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);

        build_sample_capabilities(buf, 0x5002u, 0x03u, 0x04u, 0x27u | 0x08u);
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        int requested = matched && r36_capabilities_video_requested(&view);
        rc = requested ? r36_trigger_open_from_capabilities(&s, &view) : R35_ERR_BAD_ARGUMENT;

        ok = parsed && matched && requested && rc == R35_OK
             && s.open_count == 1u && g_open_writes == 1u
             && s.rtp_armed && g_rtp_arm_calls == 1u;
        printf("R36_SCENARIO_2_EXACT_TRIGGER=%s\n", ok ? "PASS" : "FAIL");
        printf("R36_TRIGGER_RESULT=%s\n", rc == R35_OK ? "OPEN_SENT" : "REJECTED");
        printf("CALL_BOUND_MEDIA_OPEN_SENT_COUNT=%u\n", s.open_count);
        if (!ok) overall_ok = 0;

        /* ---- 3. duplicate trigger: a second matching capabilities event
         * must not produce a second OPEN (R35's own open_sent gate). ---- */
        build_sample_capabilities(buf, 0x5002u, 0x05u, 0x06u, 0x27u | 0x08u);
        parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        R35Result rc2 = matched ? r36_trigger_open_from_capabilities(&s, &view) : R35_ERR_BAD_ARGUMENT;
        ok = matched && rc2 != R35_OK && s.open_count == 1u && g_open_writes == 1u;
        printf("R36_SCENARIO_3_DUPLICATE_TRIGGER=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;

        /* ---- 7. one valid STOP after the trigger-produced OPEN. ---- */
        rc = r35_send_stop(&s, R35_FORM_TUNNEL, s.call_ctp_connection);
        ok = rc == R35_OK && s.stop_count == 1u && g_stop_writes == 1u && !s.rtp_armed && g_rtp_disarm_calls == 1u;
        printf("R36_SCENARIO_7_ONE_VALID_STOP=%s\n", ok ? "PASS" : "FAIL");
        printf("CALL_BOUND_MEDIA_STOP_SENT_COUNT=%u\n", s.stop_count);
        if (!ok) overall_ok = 0;

        /* ---- 8. duplicate STOP: no second write. ---- */
        rc = r35_send_stop(&s, R35_FORM_TUNNEL, s.call_ctp_connection);
        ok = rc != R35_OK && s.stop_count == 1u && g_stop_writes == 1u;
        printf("R36_SCENARIO_8_DUPLICATE_STOP=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;

        /* ---- 9. terminal call: teardown, then a would-be-valid trigger is
         * rejected outright (r35_call_ready fails closed). ---- */
        r35_teardown_call(&s);
        build_sample_capabilities(buf, 0x5002u, 0x07u, 0x08u, 0x27u | 0x08u);
        parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        unsigned open_writes_before = g_open_writes;
        ok = parsed && !matched && g_open_writes == open_writes_before;
        printf("R36_SCENARIO_9_TERMINAL_CALL_REJECTED=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 4. stale/prior call: a capabilities frame bound to an OLDER
     * captured call's connection must not trigger OPEN after the session
     * has moved on to a new call transaction. ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x5010u, 0x01u, 0x02u); /* call A */
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        unsigned call_a_connection = s.call_ctp_connection;

        build_sample_call_init(buf, 0x5011u, 0x03u, 0x04u); /* call B, same session */
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);

        /* A capabilities frame still carrying call A's raw peer connection. */
        build_sample_capabilities(buf, 0x5010u, 0x05u, 0x06u, 0x27u | 0x08u);
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        ok = parsed && !matched && s.call_ctp_connection != call_a_connection
             && s.open_count == 0u && g_open_writes == 0u;
        printf("R36_SCENARIO_4_STALE_PRIOR_CALL=%s\n", ok ? "PASS" : "FAIL");
        printf("CALL_BOUND_MEDIA_OPEN_SENT_COUNT=%u\n", s.open_count);
        if (!ok) overall_ok = 0;
    }

    /* ---- 5. registration-handle misuse: capture itself must already fail
     * closed (R35's own rule) when the derived call connection equals the
     * outer registration/CTPP handle, so no capabilities event can ever
     * reach a live call on that session. ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        unsigned peer = 0x5555u;
        unsigned would_be_local = (peer ^ 0x8000u) & 0xFFFFu;
        build_sample_call_init(buf, peer, 0x01u, 0x02u);
        int cap = r35_capture_call_ctp_id(&s, buf, 72u, would_be_local);

        build_sample_capabilities(buf, peer, 0x03u, 0x04u, 0x27u | 0x08u);
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        ok = (cap == 0) && parsed && !matched && s.open_count == 0u && g_open_writes == 0u;
        printf("R36_SCENARIO_5_REGISTRATION_HANDLE_MISUSE=%s\n", ok ? "PASS" : "FAIL");
        printf("CALL_BOUND_MEDIA_OPEN_SENT_COUNT=%u\n", s.open_count);
        if (!ok) overall_ok = 0;
    }

    /* ---- 6. STOP before OPEN: fail closed on R35's own existing gate. ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x5020u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        r35_allocate_media_rx_channel(&s, s.call_ctp_connection, 1u);
        rc = r35_send_stop(&s, R35_FORM_TUNNEL, s.call_ctp_connection);
        ok = rc != R35_OK && g_stop_writes == 0u;
        printf("R36_SCENARIO_6_STOP_BEFORE_OPEN=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- bit3-clear capability word must not trigger (the public sample's
     * own observed value, 0x27, has bit3 clear -- SECTION 4/6 of the R36
     * closure document records this as the one residual LIVE-BEHAVIOUR
     * question, not a wire-contract unknown; the trigger logic itself must
     * still correctly refuse to open when the bit is clear). ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x5030u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        build_sample_capabilities(buf, 0x5030u, 0x03u, 0x04u, 0x27u); /* bit3 clear */
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        int requested = matched && r36_capabilities_video_requested(&view);
        ok = parsed && matched && !requested && s.open_count == 0u && g_open_writes == 0u;
        printf("R36_CHECK_BIT3_CLEAR_DOES_NOT_TRIGGER=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- zero-side-effect gates: this harness never touches network/door/gate ---- */
    printf("R36_NETWORK_TX=%u\n", g_network_tx);
    printf("R36_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R36_GATE_ACTIONS=%u\n", g_gate_actions);

    printf("R36_HARNESS_RESULT=%s\n", overall_ok ? "PASS" : "FAIL");
    return overall_ok ? 0 : 1;
}
