/*
 * P116/R35 attached inbound media host harness.
 *
 * This file is NOT part of the packaged helper.  It is a research-only,
 * host-compilable driver for the dependency-free R35_ATTACHED_MEDIA_BEGIN/END
 * core region extracted from the R35 native transform's candidate output.
 * The Python test module (test_p116_r35_attached_media_native_helper.py)
 * extracts that core region from a freshly generated candidate, concatenates
 * it in front of this file's contents, compiles the result with the host
 * `cc`, runs the resulting binary, and asserts on the bounded `R35_...=`
 * markers printed below.  This proves the actual injected C behaves as
 * specified, not merely that certain strings are present in the source.
 *
 * This harness never opens a socket, never forks, never touches the
 * filesystem beyond stdio, and never calls Door/Gate.  All transport and
 * RTP-forwarding side effects are captured by fake, in-memory
 * writer/hook functions so the assertions below are pure counters.
 */

#include <stdio.h>
#include <string.h>

/* ---- fake writer / RTP-arm hook (host-only substitutes) ---- */

static unsigned g_open_writes = 0;
static unsigned g_stop_writes = 0;
static unsigned char g_last_open_packet[R35_CALL_BOUND_PACKET_LEN];
static unsigned char g_last_stop_packet[R35_CALL_BOUND_PACKET_LEN];
static unsigned g_last_open_len = 0;
static unsigned g_last_stop_len = 0;
static unsigned g_rtp_arm_calls = 0;
static unsigned g_rtp_disarm_calls = 0;
static int g_last_rtp_armed = -1;
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
    (void)connection;
    (void)sequence;
    (void)acknowledgement;
    if (strcmp(kind, "MEDIA_OPEN") == 0) {
        g_open_writes++;
        if (len == R35_CALL_BOUND_PACKET_LEN) {
            memcpy(g_last_open_packet, packet, len);
            g_last_open_len = len;
        }
    } else if (strcmp(kind, "MEDIA_STOP") == 0) {
        g_stop_writes++;
        if (len == R35_CALL_BOUND_PACKET_LEN) {
            memcpy(g_last_stop_packet, packet, len);
            g_last_stop_len = len;
        }
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
    g_last_rtp_armed = armed;
}

/* ---- sample CALL_INIT envelope builder (72 bytes: 8 header + 40 INVITE body
 * + 4 trailer + 10 source + 10 dest), mirroring the R30-proven layout. ---- */

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

static void default_sources(R35MediaRequestSources *src, int form, int video_request, int profile_selector, unsigned channel_id)
{
    memset(src, 0, sizeof(*src));
    src->form = form;
    src->video_request = video_request;
    src->profile_selector = profile_selector;
    src->media_channel_id = channel_id;
    src->max_rtp_payload = 0x04D2u;
    src->channel_profile_word = 0x00001234u;
    src->profile_halfwords[0] = 0x0320u;
    src->profile_halfwords[1] = 0x01E0u;
    src->profile_halfwords[2] = 0x0140u;
    src->profile_halfword_3 = 0x00F0u;
    src->profile_byte_4 = 0x10u;
    if (form == R35_FORM_ADDRESS) {
        src->address_ipv4[0] = 0x01; src->address_ipv4[1] = 0x02;
        src->address_ipv4[2] = 0x03; src->address_ipv4[3] = 0x04;
    }
}

static void print_hex(const char *label, const unsigned char *data, unsigned len)
{
    unsigned i;
    printf("%s=", label);
    for (i = 0; i < len; i++) {
        printf("%02x", data[i]);
    }
    printf("\n");
}

static void reset_fakes(void)
{
    g_open_writes = 0;
    g_stop_writes = 0;
    g_last_open_len = 0;
    g_last_stop_len = 0;
    g_rtp_arm_calls = 0;
    g_rtp_disarm_calls = 0;
    g_last_rtp_armed = -1;
}

static void wire(R35AttachedMediaSession *s)
{
    memset(s, 0, sizeof(*s));
    s->writer = fake_writer;
    s->writer_ctx = NULL;
    s->rtp_arm_hook = fake_rtp_hook;
    s->rtp_arm_hook_ctx = NULL;
}

int main(void)
{
    int overall_ok = 1;
    unsigned char init[72];
    R35AttachedMediaSession s;
    R35Result rc;
    unsigned i;

    for (i = 0; i < 7; i++) {
        printf("R35_SECOND_OPEN_FORBIDDEN_CODE_%u=%s\n", i + 1u, R35_SECOND_OPEN_FORBIDDEN_STATES[i].code);
    }

    /* ---- 1. CALL_INIT capture: connection bytes 2..3 direction-transformed ---- */
    reset_fakes();
    wire(&s);
    build_sample_call_init(init, 0x1234u, 0x56u, 0x78u);
    {
        int cap = r35_capture_call_ctp_id(&s, init, 72u, 999u);
        unsigned expected_connection = (0x1234u ^ 0x8000u) & 0xFFFFu;
        int ok = cap && s.call_ctp_connection == expected_connection
                  && s.call_sequence == 0x78u && s.call_ack == 0x56u;
        printf("R35_CHECK_CALL_CTP_CAPTURE=%s\n", ok ? "PASS" : "FAIL");
        printf("R35_CALL_CTP_CONNECTION=%u\n", s.call_ctp_connection);
        printf("R35_CALL_SEQUENCE=%u\n", s.call_sequence);
        printf("R35_CALL_ACK=%u\n", s.call_ack);
        if (!ok) overall_ok = 0;
    }

    /* ---- 2. registration handle distinct from call CTP id ---- */
    {
        R35AttachedMediaSession s2;
        wire(&s2);
        /* choose outer handle equal to the connection that WOULD be derived */
        unsigned peer = 0x5555u;
        unsigned would_be_local = (peer ^ 0x8000u) & 0xFFFFu;
        build_sample_call_init(init, peer, 0x01u, 0x02u);
        int cap = r35_capture_call_ctp_id(&s2, init, 72u, would_be_local);
        int ok = (cap == 0); /* must fail closed: call id must not equal registration handle */
        printf("R35_CHECK_REGISTRATION_DISTINCT=%s\n", ok ? "PASS" : "FAIL");
        if (!ok) overall_ok = 0;
    }

    /* ---- 3/5/8. byte-exact OPEN/STOP serialization + flags-as-expressions ---- */
    {
        unsigned char body[26];
        R35MediaRequestSources src;

        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x3456u);
        r35_serialize_mediareq26_open(body, &src);
        print_hex("R35_OPEN_BODY_TUNNEL_NOVIDEO_HEX", body, 26u);
        unsigned char flags_tunnel_novideo = body[3];

        default_sources(&src, R35_FORM_TUNNEL, 1, 0, 0x3456u);
        r35_serialize_mediareq26_open(body, &src);
        unsigned char flags_tunnel_video = body[3];

        default_sources(&src, R35_FORM_ADDRESS, 0, 0, 0x3456u);
        r35_serialize_mediareq26_open(body, &src);
        unsigned char flags_addr_novideo_noprof = body[3];

        default_sources(&src, R35_FORM_ADDRESS, 1, 1, 0x3456u);
        r35_serialize_mediareq26_open(body, &src);
        print_hex("R35_OPEN_BODY_ADDRESS_VIDEO_PROFILE_HEX", body, 26u);
        unsigned char flags_addr_video_prof = body[3];

        printf("R35_OPEN_FLAGS_TUNNEL_NOVIDEO=0x%02x\n", flags_tunnel_novideo);
        printf("R35_OPEN_FLAGS_TUNNEL_VIDEO=0x%02x\n", flags_tunnel_video);
        printf("R35_OPEN_FLAGS_ADDRESS_NOVIDEO_NOPROFILE=0x%02x\n", flags_addr_novideo_noprof);
        printf("R35_OPEN_FLAGS_ADDRESS_VIDEO_PROFILE=0x%02x\n", flags_addr_video_prof);

        int flip_ok = flags_tunnel_novideo != flags_tunnel_video
                       && flags_addr_novideo_noprof != flags_addr_video_prof
                       && flags_tunnel_novideo != 0x32u /* not an unconditional constant read path */
                       ? 1 : (flags_tunnel_novideo == 0x32u ? 1 : 0);
        /* flags_tunnel_novideo IS expected to equal 0x32 (that is the proven
         * TUNNEL/no-video value), but it must be produced by the computed
         * expression, not by an unconditional literal write; the flip checks
         * below are the actual proof. */
        flip_ok = (flags_tunnel_novideo != flags_tunnel_video)
                  && (flags_addr_novideo_noprof != flags_addr_video_prof)
                  && (flags_tunnel_novideo == 0x32u)
                  && (flags_tunnel_video == 0x3Au)
                  && (flags_addr_novideo_noprof == 0x30u)
                  && (flags_addr_video_prof == 0x3Cu);
        printf("R35_CHECK_OPEN_FLAGS_ARE_EXPRESSIONS=%s\n", flip_ok ? "PASS" : "FAIL");
        if (!flip_ok) overall_ok = 0;

        r35_serialize_mediareq26_stop(body, R35_FORM_TUNNEL, 0x3456u);
        print_hex("R35_STOP_BODY_TUNNEL_HEX", body, 26u);
        {
            int stop_ok = body[2] == 0x94u && body[3] == 0x02u;
            unsigned k;
            for (k = 10; k < 26; k++) {
                if (body[k] != 0) stop_ok = 0;
            }
            printf("R35_CHECK_STOP_BYTE_EXACT_TUNNEL=%s\n", stop_ok ? "PASS" : "FAIL");
            if (!stop_ok) overall_ok = 0;
        }

        r35_serialize_mediareq26_stop(body, R35_FORM_ADDRESS, 0x3456u);
        print_hex("R35_STOP_BODY_ADDRESS_HEX", body, 26u);
        {
            int stop_ok = body[2] == 0x94u && body[3] == 0x00u;
            printf("R35_CHECK_STOP_BYTE_EXACT_ADDRESS=%s\n", stop_ok ? "PASS" : "FAIL");
            if (!stop_ok) overall_ok = 0;
        }
    }

    /* ---- 4/9/16. full lifecycle: envelope call-binding, order, preservation ---- */
    reset_fakes();
    wire(&s);
    build_sample_call_init(init, 0x1234u, 0x56u, 0x78u);
    r35_capture_call_ctp_id(&s, init, 72u, 999u);
    {
        unsigned expected_connection = s.call_ctp_connection;
        R35MediaRequestSources src;

        rc = r35_allocate_media_rx_channel(&s, 0x3456u, 0xAAu);
        printf("R35_CHECK_ALLOCATE=%s\n", rc == R35_OK ? "PASS" : "FAIL");
        if (rc != R35_OK) overall_ok = 0;

        /* RTP must never arm before OPEN. */
        rc = r35_enable_rtp(&s, 0x3456u);
        printf("R35_CHECK_RTP_NEVER_BEFORE_OPEN=%s\n", rc != R35_OK ? "PASS" : "FAIL");
        if (rc == R35_OK) overall_ok = 0;

        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x3456u);
        rc = r35_send_open(&s, &src, 0);
        printf("R35_CHECK_OPEN_SENT=%s\n", rc == R35_OK ? "PASS" : "FAIL");
        if (rc != R35_OK) overall_ok = 0;

        {
            int envelope_ok = g_open_writes == 1u && g_last_open_len == R35_CALL_BOUND_PACKET_LEN
                && g_last_open_packet[0] == R35_CTP_FLAG_DATA
                && g_last_open_packet[1] == R35_CTP_VERSION
                && ((unsigned)((g_last_open_packet[2] << 8) | g_last_open_packet[3])) == expected_connection
                && ((unsigned)((g_last_open_packet[2] << 8) | g_last_open_packet[3])) != 999u
                && memcmp(g_last_open_packet + 40, s.source_logical, 10) == 0
                && memcmp(g_last_open_packet + 50, s.dest_logical, 10) == 0;
            print_hex("R35_ENVELOPE_OPEN_HEX", g_last_open_packet, g_last_open_len);
            printf("R35_CHECK_ENVELOPE_CALL_BOUND=%s\n", envelope_ok ? "PASS" : "FAIL");
            if (!envelope_ok) overall_ok = 0;
        }

        /* Exactly one OPEN: a second attempt must be rejected without a write. */
        rc = r35_send_open(&s, &src, 0);
        printf("R35_CHECK_AT_MOST_ONE_OPEN=%s\n", (rc != R35_OK && g_open_writes == 1u) ? "PASS" : "FAIL");
        if (rc == R35_OK || g_open_writes != 1u) overall_ok = 0;

        rc = r35_enable_rtp(&s, 0x3456u);
        printf("R35_CHECK_RTP_ARM_AFTER_OPEN=%s\n",
               (rc == R35_OK && s.rtp_armed && g_rtp_arm_calls == 1u && g_last_rtp_armed == 1) ? "PASS" : "FAIL");
        if (!(rc == R35_OK && s.rtp_armed)) overall_ok = 0;

        rc = r35_send_stop(&s, R35_FORM_TUNNEL, 0x3456u);
        printf("R35_CHECK_STOP_SENT=%s\n",
               (rc == R35_OK && g_stop_writes == 1u && !s.rtp_armed && g_rtp_disarm_calls == 1u) ? "PASS" : "FAIL");
        if (rc != R35_OK) overall_ok = 0;

        rc = r35_send_stop(&s, R35_FORM_TUNNEL, 0x3456u);
        printf("R35_CHECK_AT_MOST_ONE_STOP=%s\n", (rc != R35_OK && g_stop_writes == 1u) ? "PASS" : "FAIL");
        if (rc == R35_OK || g_stop_writes != 1u) overall_ok = 0;

        /* STOP must strictly precede local disposal: channel is still live now. */
        printf("R35_CHECK_STOP_PRECEDES_DISPOSAL=%s\n", (!s.channel_disposed && s.stop_sent) ? "PASS" : "FAIL");
        if (s.channel_disposed || !s.stop_sent) overall_ok = 0;

        rc = r35_dispose_media_rx_channel(&s, 0x3456u);
        printf("R35_CHECK_DISPOSE_AFTER_STOP=%s\n", rc == R35_OK ? "PASS" : "FAIL");
        if (rc != R35_OK) overall_ok = 0;

        {
            int preserved = r35_preserve_listener_registration_pseudotcp(&s);
            printf("R35_CHECK_LISTENER_REGISTRATION_PSEUDOTCP_PRESERVED=%s\n", preserved ? "PASS" : "FAIL");
            if (!preserved) overall_ok = 0;
        }
    }

    /* ---- 10. STOP before OPEN rejected ---- */
    {
        R35AttachedMediaSession s3;
        wire(&s3);
        build_sample_call_init(init, 0x2001u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&s3, init, 72u, 999u);
        r35_allocate_media_rx_channel(&s3, 0x1000u, 1u);
        rc = r35_send_stop(&s3, R35_FORM_TUNNEL, 0x1000u);
        printf("R35_CHECK_STOP_BEFORE_OPEN_REJECTED=%s\n", rc != R35_OK ? "PASS" : "FAIL");
        if (rc == R35_OK) overall_ok = 0;
    }

    /* ---- 11/12. wrong / stale channel id rejected ---- */
    {
        R35AttachedMediaSession s4;
        R35MediaRequestSources src;
        wire(&s4);
        build_sample_call_init(init, 0x2002u, 0x03u, 0x04u);
        r35_capture_call_ctp_id(&s4, init, 72u, 999u);
        r35_allocate_media_rx_channel(&s4, 0x1001u, 1u);
        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x9999u); /* wrong channel */
        rc = r35_send_open(&s4, &src, 0);
        printf("R35_CHECK_WRONG_CHANNEL_REJECTED=%s\n", rc == R35_ERR_WRONG_CHANNEL ? "PASS" : "FAIL");
        if (rc != R35_ERR_WRONG_CHANNEL) overall_ok = 0;

        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x1001u);
        r35_send_open(&s4, &src, 0);
        r35_send_stop(&s4, R35_FORM_TUNNEL, 0x1001u);
        r35_dispose_media_rx_channel(&s4, 0x1001u);
        rc = r35_enable_rtp(&s4, 0x1001u);
        printf("R35_CHECK_STALE_CHANNEL_REJECTED=%s\n", rc == R35_ERR_STALE_CHANNEL ? "PASS" : "FAIL");
        if (rc != R35_ERR_STALE_CHANNEL) overall_ok = 0;
    }

    /* ---- 13. dispose before stop rejected ---- */
    {
        R35AttachedMediaSession s5;
        R35MediaRequestSources src;
        wire(&s5);
        build_sample_call_init(init, 0x2003u, 0x05u, 0x06u);
        r35_capture_call_ctp_id(&s5, init, 72u, 999u);
        r35_allocate_media_rx_channel(&s5, 0x1002u, 1u);
        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x1002u);
        r35_send_open(&s5, &src, 0);
        rc = r35_dispose_media_rx_channel(&s5, 0x1002u);
        printf("R35_CHECK_DISPOSE_BEFORE_STOP_REJECTED=%s\n", rc == R35_ERR_DISPOSE_BEFORE_STOP ? "PASS" : "FAIL");
        if (rc != R35_ERR_DISPOSE_BEFORE_STOP) overall_ok = 0;
    }

    /* ---- 14. prior-call state reuse rejected ---- */
    {
        R35AttachedMediaSession s6;
        R35MediaRequestSources src;
        wire(&s6);
        build_sample_call_init(init, 0x2004u, 0x07u, 0x08u);
        r35_capture_call_ctp_id(&s6, init, 72u, 999u);
        r35_allocate_media_rx_channel(&s6, 0x1003u, 1u); /* call A channel, generation 1 */
        unsigned stale_channel_id = s6.channel_id;

        build_sample_call_init(init, 0x2005u, 0x09u, 0x0Au); /* call B, same session */
        r35_capture_call_ctp_id(&s6, init, 72u, 999u); /* generation bumps to 2 */

        default_sources(&src, R35_FORM_TUNNEL, 0, 0, stale_channel_id);
        rc = r35_send_open(&s6, &src, 0);
        printf("R35_CHECK_PRIOR_CALL_STATE_REUSE_REJECTED=%s\n",
               rc == R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL ? "PASS" : "FAIL");
        if (rc != R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL) overall_ok = 0;
    }

    /* ---- registration-handle-targeted OPEN rejected without a write ---- */
    {
        R35AttachedMediaSession s7;
        R35MediaRequestSources src;
        wire(&s7);
        build_sample_call_init(init, 0x2006u, 0x0Bu, 0x0Cu);
        r35_capture_call_ctp_id(&s7, init, 72u, 999u);
        r35_allocate_media_rx_channel(&s7, 0x1004u, 1u);
        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x1004u);
        unsigned writes_before = g_open_writes;
        rc = r35_send_open(&s7, &src, 1 /* use_registration_handle */);
        printf("R35_CHECK_REGISTRATION_HANDLE_OPEN_REJECTED=%s\n",
               (rc == R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL && g_open_writes == writes_before) ? "PASS" : "FAIL");
        if (rc == R35_OK || g_open_writes != writes_before) overall_ok = 0;
    }

    /* ---- 22. state cleanup on terminal call teardown; fail closed on reuse ---- */
    {
        R35AttachedMediaSession s8;
        wire(&s8);
        build_sample_call_init(init, 0x2007u, 0x0Du, 0x0Eu);
        r35_capture_call_ctp_id(&s8, init, 72u, 999u);
        r35_teardown_call(&s8);
        rc = r35_allocate_media_rx_channel(&s8, 0x2000u, 1u);
        printf("R35_CHECK_STATE_CLEANUP_ON_TEARDOWN=%s\n",
               rc == R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER ? "PASS" : "FAIL");
        if (rc != R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER) overall_ok = 0;
    }

    /* ---- 24 (behavioural half): all seven second-OPEN forbidden setups,
     * mirroring entrance_p116_r34_attached_media_helper_model.py's
     * _session_for_second_open_state / test_07 exactly. ---- */
    for (i = 0; i < 7; i++) {
        R35AttachedMediaSession fs;
        R35MediaRequestSources src;
        unsigned before;
        int use_reg = 0;

        wire(&fs);
        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x3456u);

        switch (i) {
            case 0: /* NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER: never captured */
                break;
            case 1: /* NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED: captured, not allocated */
                build_sample_call_init(init, 0x3001u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                break;
            case 2: /* OPEN_ALREADY_PENDING */
                build_sample_call_init(init, 0x3002u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                r35_allocate_media_rx_channel(&fs, 0x3456u, 1u);
                r35_send_open(&fs, &src, 0);
                break;
            case 3: /* OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED */
                build_sample_call_init(init, 0x3003u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                r35_allocate_media_rx_channel(&fs, 0x3456u, 1u);
                r35_send_open(&fs, &src, 0);
                r35_observe_channel_open_response(&fs, 0x3456u, 1);
                break;
            case 4: /* STOP_ALREADY_SENT */
                build_sample_call_init(init, 0x3004u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                r35_allocate_media_rx_channel(&fs, 0x3456u, 1u);
                r35_send_open(&fs, &src, 0);
                r35_send_stop(&fs, R35_FORM_TUNNEL, 0x3456u);
                break;
            case 5: /* MEDIA_CHANNEL_ALREADY_DISPOSED */
                build_sample_call_init(init, 0x3005u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                r35_allocate_media_rx_channel(&fs, 0x3456u, 1u);
                r35_send_open(&fs, &src, 0);
                r35_send_stop(&fs, R35_FORM_TUNNEL, 0x3456u);
                r35_dispose_media_rx_channel(&fs, 0x3456u);
                break;
            case 6: /* REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION */
                build_sample_call_init(init, 0x3006u, 0x01u, 0x02u);
                r35_capture_call_ctp_id(&fs, init, 72u, 999u);
                r35_allocate_media_rx_channel(&fs, 0x3456u, 1u);
                use_reg = 1;
                break;
            default:
                break;
        }

        before = fs.open_count;
        rc = r35_send_open(&fs, &src, use_reg);
        {
            int ok = rc != R35_OK && fs.open_count == before;
            printf("R35_FORBIDDEN_STATE_%u=%s\n", i + 1u, ok ? "PASS" : "FAIL");
            if (!ok) overall_ok = 0;
        }
    }

    /* ---- STALE_CHANNEL_GATE: normal PASS, then a corrupted-state FAIL
     * (the R34 gap: R34 defined this gate but never proved it can fail). ---- */
    {
        R35AttachedMediaSession sg;
        R35MediaRequestSources src;
        wire(&sg);
        build_sample_call_init(init, 0x4001u, 0x01u, 0x02u);
        r35_capture_call_ctp_id(&sg, init, 72u, 999u);
        r35_allocate_media_rx_channel(&sg, 0x3456u, 1u);
        default_sources(&src, R35_FORM_TUNNEL, 0, 0, 0x3456u);
        r35_send_open(&sg, &src, 0);
        r35_send_stop(&sg, R35_FORM_TUNNEL, 0x3456u);
        r35_dispose_media_rx_channel(&sg, 0x3456u);
        {
            int gate = (!sg.channel_allocated) && sg.channel_disposed
                       && sg.open_count == 1u && sg.stop_count == 1u;
            printf("STALE_CHANNEL_GATE=%s\n", gate ? "PASS" : "FAIL");
            if (!gate) overall_ok = 0;
        }

        /* Corrupt: simulate the R34-class bug where disposal state is not
         * actually retained (channel_disposed incorrectly cleared). */
        sg.channel_disposed = 0;
        {
            int gate = (!sg.channel_allocated) && sg.channel_disposed
                       && sg.open_count == 1u && sg.stop_count == 1u;
            printf("STALE_CHANNEL_GATE=%s\n", gate ? "PASS" : "FAIL");
            if (gate) overall_ok = 0; /* the corrupted run MUST compute FAIL */
        }
    }

    /* ---- zero-side-effect gates: this harness never touches network/door/gate ---- */
    printf("R35_NETWORK_TX=%u\n", g_network_tx);
    printf("R35_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R35_GATE_ACTIONS=%u\n", g_gate_actions);

    printf("R35_HARNESS_RESULT=%s\n", overall_ok ? "PASS" : "FAIL");
    return overall_ok ? 0 : 1;
}
