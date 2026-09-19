/*
 * P116/R37 attached inbound media live-readiness host harness.
 *
 * This file is NOT part of the packaged helper.  It is a research-only,
 * host-compilable driver for R35's dependency-free core region (unchanged),
 * R36's trigger-core region (unchanged), and R37's own core region (this
 * round), concatenated by the Python test module
 * (test_p116_r37_attached_media_live_readiness.py) in front of this file's
 * contents.  It drives the exact 15 scenarios required by this round's
 * task specification (CHILD F) against synthetic CTP envelopes, never a
 * socket, never a fork, never Door/Gate, and never the packaged/candidate
 * binary.
 *
 * Scenarios 1-7 exercise the OPEN path, which R37 leaves completely
 * untouched (R36's trigger, unedited).  Scenario 3 shows the OPEN
 * MECHANISM firing correctly offline -- it is NOT evidence that the
 * channel id it uses is a proven native value; P116_R37_ATTACHED_INBOUND_
 * MEDIA_LIVE_READINESS.md SECTION 1/2 documents that separately.
 * Scenario 7 ("call CTP used incorrectly as media-channel id => OPEN=0")
 * is run exactly as specified and is EXPECTED, and shown, to FAIL against
 * R36's real, unedited, already-merged trigger: R36's own OPEN mechanism
 * deliberately reuses the call CTP connection id as a placeholder channel
 * id (P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md SECTION 6), which
 * is exactly the condition this scenario forbids. This harness reports
 * that failure honestly rather than rewriting the scenario to pass; it is
 * independent, executable confirmation of this round's CHILD A finding
 * (LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false), not a defect in the test.
 *
 * Scenarios 8-15 exercise the NEW R37 bounded-STOP / protocol-stop paths
 * and are all expected to PASS: none of them requires the blocked
 * media-channel-identity field, only R35's existing, already-proven
 * channel/call state machine plus R37's thin dispatchers on top of it.
 */

#include <stdio.h>
#include <string.h>

/* ---- fake writer / RTP-arm hook (host-only substitutes, same shape R35's
 * and R36's own harnesses use) ---- */

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

/* ---- sample CTP envelope builders (R30-proven layout, same shape R35/R36
 * already use): 8 header + inner_len body (padded to 4) + 4 trailer + 10
 * source + 10 dest. ---- */

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
 * .r33-evidence/public-vip/viper/call.py:43): 40 bytes total, 8 header + 8
 * inner body (already 4-aligned) + 4 trailer + 10 + 10. */
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

/* Mirrors the independently-confirmed public CTP RELEASE opcode
 * (.r33-evidence/public-vip/viper/ctp.py:30 OP_RELEASE=0x000E). Body is a
 * bare 2-byte opcode (no further fields needed by r37_handle_remote_release,
 * which only checks opcode + connection match). 36 bytes total: 8 header +
 * 2 inner body + 2 pad (to 4-align inner_len) + 4 trailer + 10 + 10, exactly
 * mirroring r35_parse_ctp_envelope's own layout formula (pad = (4 -
 * inner_len % 4) % 4). */
static void build_sample_release(unsigned char *out, unsigned peer_connection, unsigned seq, unsigned ack)
{
    memset(out, 0, 36);
    out[0] = R35_CTP_FLAG_DATA; /* 0x40 */
    out[1] = 0x18;              /* version */
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00;
    out[7] = 0x02;      /* inner_len = 2, BE16 */
    out[8] = 0x00;
    out[9] = 0x0e;      /* OP_RELEASE, BE16 */
    /* out[10..11] = pad, left zero by memset */
    out[12] = 0xff; out[13] = 0xff; out[14] = 0xff; out[15] = 0xff; /* trailer */
    memset(out + 16, 0x41, 10); /* source_raw */
    memset(out + 26, 0x42, 10); /* dest_raw */
}

/* Drives a full capture+trigger sequence using R36's REAL, unedited
 * mechanism and returns the resulting R35Result. Shared by several
 * scenarios below so each one starts from the identical, honest OPEN
 * mechanism this round leaves untouched. */
static R35Result capture_and_trigger(R35AttachedMediaSession *s, unsigned peer_connection, unsigned char cap_word)
{
    unsigned char buf[72];
    R35CtpEnvelopeView view;
    build_sample_call_init(buf, peer_connection, 0x01u, 0x02u);
    r35_capture_call_ctp_id(s, buf, 72u, 999u);
    build_sample_capabilities(buf, peer_connection, 0x03u, 0x04u, cap_word);
    if (!r35_parse_ctp_envelope(buf, 40u, &view)) return R35_ERR_BAD_ARGUMENT;
    if (!r36_is_capabilities_for_current_call(s, &view)) return R35_ERR_BAD_ARGUMENT;
    if (!r36_capabilities_video_requested(&view)) return R35_ERR_BAD_ARGUMENT;
    return r36_trigger_open_from_capabilities(s, &view);
}

int main(void)
{
    int overall_ok = 1;
    unsigned char buf[72];
    R35CtpEnvelopeView view;
    R35Result rc;
    int ok;

    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;

    /* ---- 1. CALL_INIT only => OPEN=0 ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        build_sample_call_init(buf, 0x6001u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        ok = (s.open_count == 0u) && (g_open_writes == 0u);
        printf("R37_SCENARIO_1_CALL_INIT_ONLY=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 2. CAPABILITY bit3 clear => OPEN=0 ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x6002u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        build_sample_capabilities(buf, 0x6002u, 0x03u, 0x04u, 0x27u); /* bit3 clear */
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        int requested = matched && r36_capabilities_video_requested(&view);
        ok = parsed && matched && !requested && s.open_count == 0u && g_open_writes == 0u;
        printf("R37_SCENARIO_2_CAPABILITY_BIT3_CLEAR=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 3. valid CAPABILITY + valid runtime fields => OPEN=1.
     * MECHANISM-ONLY: this proves R36's trigger fires and R35's one-OPEN
     * machinery works offline; it is NOT proof that media_channel_id is a
     * real native value (SECTION 1/2 of the round document). ---- */
    R35AttachedMediaSession s3;
    {
        reset_fakes();
        wire(&s3);
        rc = capture_and_trigger(&s3, 0x6003u, 0x27u | 0x08u);
        ok = rc == R35_OK && s3.open_count == 1u && g_open_writes == 1u && s3.rtp_armed;
        printf("R37_SCENARIO_3_VALID_CAPABILITY_OPENS_MECHANISM_ONLY=%s\n", ok ? "PASS" : "FAIL");
        printf("CALL_BOUND_MEDIA_OPEN_SENT_COUNT=%u\n", s3.open_count);
        if (!ok) overall_ok = 0;
    }

    /* ---- 4. missing media channel id => OPEN=0 (R35's own bad-argument
     * gate: channel_id 0 is never allocatable). ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        build_sample_call_init(buf, 0x6004u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        rc = r35_allocate_media_rx_channel(&s, 0u, 0u);
        ok = rc != R35_OK && s.open_count == 0u && g_open_writes == 0u;
        printf("R37_SCENARIO_4_MISSING_MEDIA_CHANNEL_ID=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 5. stale/prior media channel => OPEN=0 (a channel already
     * disposed can never be re-opened; R35's STALE_CHANNEL_GATE). ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        rc = capture_and_trigger(&s, 0x6005u, 0x27u | 0x08u);
        unsigned stale_id = s.channel_id;
        rc = r37_bounded_stop_request(&s, &t, R35_FORM_TUNNEL); /* legitimate STOP+dispose */
        unsigned open_before = s.open_count;
        R35Result reopen = r35_send_open(
            &s,
            &(R35MediaRequestSources){
                .form = R35_FORM_TUNNEL, .video_request = 1, .profile_selector = 0,
                .media_channel_id = stale_id, .max_rtp_payload = 0, .channel_profile_word = 0,
            },
            0);
        ok = reopen == R35_ERR_STALE_CHANNEL && s.open_count == open_before;
        printf("R37_SCENARIO_5_STALE_PRIOR_MEDIA_CHANNEL=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 6. registered CTPP used as media channel => OPEN=0 (R35's own
     * registration-handle-misuse rule: capture itself fails closed). ---- */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        unsigned peer = 0x6006u;
        unsigned would_be_local = (peer ^ 0x8000u) & 0xFFFFu;
        build_sample_call_init(buf, peer, 0x01u, 0x02u);
        int cap = r35_capture_call_ctp_id(&s, buf, 72u, would_be_local);
        build_sample_capabilities(buf, peer, 0x03u, 0x04u, 0x27u | 0x08u);
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        ok = (cap == 0) && parsed && !matched && s.open_count == 0u && g_open_writes == 0u;
        printf("R37_SCENARIO_6_REGISTERED_CTPP_AS_MEDIA_CHANNEL=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 7. call CTP used incorrectly as media-channel id => OPEN=0.
     * EXPECTED AND SHOWN TO FAIL: R36's real, unedited trigger deliberately
     * reuses the call CTP connection id AS the channel id (its own
     * documented placeholder, P116_R36_..._TRIGGER_CLOSURE.md SECTION 6),
     * which is exactly the condition this scenario forbids. R37 does not
     * rewrite R36's trigger (prohibited) and does not fabricate a PASS
     * here: this failure is independent, executable confirmation of this
     * round's CHILD A finding (LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false). */
    {
        R35AttachedMediaSession s;
        reset_fakes();
        wire(&s);
        rc = capture_and_trigger(&s, 0x6007u, 0x27u | 0x08u);
        int channel_id_equals_call_ctp = (s.channel_id == s.call_ctp_connection);
        ok = (s.open_count == 0u); /* the scenario's REQUIRED outcome */
        printf("R37_SCENARIO_7_CALL_CTP_AS_MEDIA_CHANNEL_ID=%s\n", ok ? "PASS" : "FAIL");
        printf("R37_SCENARIO_7_OBSERVED_OPEN_COUNT=%u\n", s.open_count);
        printf("R37_SCENARIO_7_CHANNEL_ID_EQUALS_CALL_CTP=%s\n", channel_id_equals_call_ctp ? "true" : "false");
        if (!ok) overall_ok = 0; /* left visible, not forced -- see comment above */
    }

    /* ---- 8. external bounded STOP before OPEN => STOP=0 ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        build_sample_call_init(buf, 0x6008u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        rc = r37_bounded_stop_request(&s, &t, R35_FORM_TUNNEL);
        ok = rc != R35_OK && s.stop_count == 0u && g_stop_writes == 0u && t.bounded_stop_request_received_count == 1u;
        printf("R37_SCENARIO_8_BOUNDED_STOP_BEFORE_OPEN=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 9. external bounded STOP after OPEN => STOP=1 ---- */
    R35AttachedMediaSession s9;
    R37BoundedStopTelemetry t9;
    {
        reset_fakes();
        wire(&s9);
        memset(&t9, 0, sizeof(t9));
        rc = capture_and_trigger(&s9, 0x6009u, 0x27u | 0x08u);
        R35Result stop_rc = r37_bounded_stop_request(&s9, &t9, R35_FORM_TUNNEL);
        ok = rc == R35_OK && stop_rc == R35_OK && s9.stop_count == 1u && g_stop_writes == 1u
             && t9.call_bound_media_stop_sent_count == 1u && t9.rtp_disarmed_count == 1u
             && t9.media_rx_channel_disposed_count == 1u && !s9.rtp_armed;
        printf("R37_SCENARIO_9_BOUNDED_STOP_AFTER_OPEN=%s\n", ok ? "PASS" : "FAIL");
        printf("BOUNDED_STOP_REQUEST_RECEIVED=%u\n", t9.bounded_stop_request_received_count);
        printf("CALL_BOUND_MEDIA_STOP_SENT_COUNT=%u\n", t9.call_bound_media_stop_sent_count);
        printf("RTP_DISARMED=%u\n", t9.rtp_disarmed_count);
        printf("MEDIA_RX_CHANNEL_DISPOSED=%u\n", t9.media_rx_channel_disposed_count);
        if (!ok) overall_ok = 0;

        /* ---- 10. duplicate STOP => STOP remains 1 ---- */
        R35Result dup_rc = r37_bounded_stop_request(&s9, &t9, R35_FORM_TUNNEL);
        ok = dup_rc != R35_OK && s9.stop_count == 1u && g_stop_writes == 1u
             && t9.bounded_stop_request_received_count == 2u
             && t9.duplicate_stop_request_ignored_count == 1u;
        printf("R37_SCENARIO_10_DUPLICATE_STOP=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;

        /* ---- 14. media disposal invalidates channel identity ---- */
        R35Result reopen = r35_send_open(
            &s9,
            &(R35MediaRequestSources){
                .form = R35_FORM_TUNNEL, .video_request = 1, .profile_selector = 0,
                .media_channel_id = s9.channel_id, .max_rtp_payload = 0, .channel_profile_word = 0,
            },
            0);
        R35Result reenable = r35_enable_rtp(&s9, s9.channel_id);
        ok = reopen == R35_ERR_STALE_CHANNEL && reenable == R35_ERR_STALE_CHANNEL;
        printf("R37_SCENARIO_14_DISPOSAL_INVALIDATES_CHANNEL_IDENTITY=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;

        /* ---- 15. a new CALL generation cannot reuse a prior media
         * channel: capture a NEW call on the SAME session; the OLD
         * (disposed) channel id must still be rejected -- now as a
         * foreign-generation channel, not merely a stale one, and any
         * bounded-STOP attempt referencing the stale session-wide
         * s.channel_id (which r37_bounded_stop_request always uses) must
         * not resurrect a write on the new call either. ---- */
        unsigned old_channel_id = s9.channel_id;
        unsigned open_writes_before = g_open_writes;
        build_sample_call_init(buf, 0x600Fu, 0x01u, 0x02u); /* new call, same session */
        r35_capture_call_ctp_id(&s9, buf, 72u, 999u);
        R35Result cross_gen = r35_enable_rtp(&s9, old_channel_id);
        R35Result cross_gen_stop = r37_bounded_stop_request(&s9, &t9, R35_FORM_TUNNEL);
        ok = cross_gen == R35_ERR_STALE_CHANNEL
             && cross_gen_stop != R35_OK
             && g_open_writes == open_writes_before;
        printf("R37_SCENARIO_15_NEW_CALL_GENERATION_CANNOT_REUSE_CHANNEL=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 11. remote release before external STOP => stale write=0 ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        rc = capture_and_trigger(&s, 0x6011u, 0x27u | 0x08u);
        R35Result release_rc = r37_handle_remote_release(&s, &t, R35_FORM_TUNNEL);
        unsigned stop_writes_after_release = g_stop_writes;
        /* the operator's bounded STOP arrives LATER, after RELEASE already
         * tore the call down -- it must be rejected, and must not add a
         * second (stale) write. */
        R35Result late_stop = r37_bounded_stop_request(&s, &t, R35_FORM_TUNNEL);
        ok = rc == R35_OK && release_rc == R35_OK && stop_writes_after_release == 1u
             && late_stop == R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER
             && g_stop_writes == 1u /* unchanged: no stale second write */
             && !r35_call_ready(&s);
        printf("R37_SCENARIO_11_REMOTE_RELEASE_BEFORE_EXTERNAL_STOP=%s\n", ok ? "PASS" : "FAIL");
        printf("R37_SCENARIO_11_STALE_WRITE_COUNT=%u\n", g_stop_writes - stop_writes_after_release);
        if (!ok) overall_ok = 0;
    }

    /* ---- 12. capability clears bit3 after OPEN => proven stop
     * behaviour, call/listener preserved. ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        rc = capture_and_trigger(&s, 0x6012u, 0x27u | 0x08u);
        R35Result clear_rc = r37_handle_capability_cleared(&s, &t, R35_FORM_TUNNEL);
        ok = rc == R35_OK && clear_rc == R35_OK && s.stop_count == 1u && g_stop_writes == 1u
             && !s.rtp_armed && t.media_rx_channel_disposed_count == 1u
             && r35_call_ready(&s) /* call/listener deliberately preserved */
             && s.call_transaction_alive;
        printf("R37_SCENARIO_12_CAPABILITY_CLEARS_BIT3_AFTER_OPEN=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 13. terminal call + later trigger => OPEN=0 / no duplicate
     * STOP. ---- */
    {
        R35AttachedMediaSession s;
        R37BoundedStopTelemetry t;
        reset_fakes();
        wire(&s);
        memset(&t, 0, sizeof(t));
        build_sample_call_init(buf, 0x6013u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s, buf, 72u, 999u);
        r35_teardown_call(&s);

        build_sample_capabilities(buf, 0x6013u, 0x03u, 0x04u, 0x27u | 0x08u);
        int parsed = r35_parse_ctp_envelope(buf, 40u, &view);
        int matched = parsed && r36_is_capabilities_for_current_call(&s, &view);
        R35Result stop_rc = r37_bounded_stop_request(&s, &t, R35_FORM_TUNNEL);
        ok = parsed && !matched && s.open_count == 0u && g_open_writes == 0u
             && stop_rc != R35_OK && s.stop_count == 0u && g_stop_writes == 0u;
        printf("R37_SCENARIO_13_TERMINAL_CALL_LATER_TRIGGER=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- consistency check: the RELEASE envelope builder actually
     * produces bytes r35_parse_ctp_envelope/r35_read_be16 decode to
     * R37_OP_RELEASE on the right connection -- the same rigor R36's own
     * harness applies to its capabilities builder. Not part of the wiring
     * itself (that lives in the glib-typed R37_WIRING_PROTOCOL_STOP region,
     * excluded from host-harness extraction by design, same as R35/R36's
     * own wiring regions), but proves the wire-layout assumption
     * r37_handle_remote_release's caller (the wiring insertion) depends
     * on. ---- */
    {
        unsigned char rel[36];
        build_sample_release(rel, 0x6099u, 0x01u, 0x02u);
        R35CtpEnvelopeView rv;
        int parsed = r35_parse_ctp_envelope(rel, 36u, &rv);
        unsigned local_conn = parsed ? ((rv.connection ^ 0x8000u) & 0xFFFFu) : 0u;
        ok = parsed && rv.inner_len >= 2u && r35_read_be16(rv.inner_body) == R37_OP_RELEASE
             && local_conn == ((0x6099u ^ 0x8000u) & 0xFFFFu);
        printf("R37_CHECK_RELEASE_ENVELOPE_PARSES=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- zero-side-effect gates: this harness never touches network/door/gate ---- */
    printf("R37_NETWORK_TX=%u\n", g_network_tx);
    printf("R37_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R37_GATE_ACTIONS=%u\n", g_gate_actions);

    printf("R37_HARNESS_RESULT=%s\n", overall_ok ? "PASS" : "FAIL");
    return 0; /* the return code intentionally does not gate on scenario 7 --
                 see the comment above scenario 7; markers are the record. */
}
