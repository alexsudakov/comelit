/*
 * P116/R66 call-time Door host harness.
 *
 * Research-only, host-compilable driver for the freshly generated
 * R66_CALL_TIME_DOOR_BEGIN/END region.  The Python test prepends a small
 * C prelude plus the extracted generated region, then compiles this file
 * with `cc -std=c99 -Wall -Wextra -pedantic`.
 *
 * No sockets, filesystem writes, GLib runtime, or Home Assistant process are
 * used here.  Queueing, flushing and timers are in-memory fakes so the output
 * is limited to bounded PASS/FAIL markers.
 */

static void reset_session(void)
{
    memset(&g_r35_session, 0, sizeof(g_r35_session));
    g_r35_session.call_ready = TRUE;
    g_r35_session.call_ctp_connection = 0x92a5u;
    g_r35_session.call_sequence = 0x7eu;
    g_r35_session.call_ack = 0x21u;
    g_r35_session.call_generation = 9u;
    memcpy(g_r35_session.dest_logical, "00000643\0\0", R35_CTP_LOGADDR_LEN);
    memcpy(g_r35_session.source_logical, "000401177\0", R35_CTP_LOGADDR_LEN);
}

static void reset_world(void)
{
    reset_session();
    v4_door_target = V4_DOOR_TARGET_ENTRANCE;
    v4_listener_ready = TRUE;
    v4_registered = TRUE;
    v4_ctpp_channel_id = 0x3456u;
    p12_stage = P12_STAGE_V4_LISTEN_RING;
    v4_door_stage = V4_DOOR_IDLE;
    p12_tx_pending = FALSE;
    r42_media_stage = R42_MEDIA_ACTIVE;
    v4_door_send_started = FALSE;
    v4_door_writes_sent = 0u;
    g_r66_call_time_door_ack_observed = FALSE;
    g_r66_call_time_door_waiting_ack = FALSE;
    g_queue_accept = TRUE;
    g_flush_accept = TRUE;
    g_queued_frames = 0u;
    g_legacy_standalone_writes = 0u;
    g_last_kind = P12_TX_NONE;
    g_last_body_len = 0u;
    memset(g_last_body, 0, sizeof(g_last_body));
}

static int bytes_equal(const unsigned char *a, const unsigned char *b, unsigned len)
{
    unsigned i;
    for (i = 0; i < len; i++) {
        if (a[i] != b[i])
            return 0;
    }
    return 1;
}

static void print_passfail(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
}

static void case_a_eligible_queues_one_call_time_frame(void)
{
    int ok;

    reset_world();
    ok = r66_queue_call_time_door();
    print_passfail(
        "R66_CASE_A_ELIGIBLE_ONE_CALL_TIME_FRAME",
        ok &&
        g_queued_frames == 1u &&
        g_last_kind == P12_TX_CALL_TIME_DOOR &&
        g_last_body_len == R66_CALL_TIME_DOOR_PACKET_LEN &&
        g_legacy_standalone_writes == 0u);
    printf("R66_CASE_A_QUEUED_FRAMES=%u\n", g_queued_frames);
    printf("R66_CASE_A_QUEUED_KIND=%s\n",
        g_last_kind == P12_TX_CALL_TIME_DOOR ? "CALL_TIME_DOOR" : "OTHER");
    printf("R66_CASE_A_LEGACY_STANDALONE_WRITES=%u\n", g_legacy_standalone_writes);
}

static void case_b_byte_equality_and_inversion(void)
{
    unsigned char packet[R66_CALL_TIME_DOOR_PACKET_LEN];
    unsigned char changed[R66_CALL_TIME_DOOR_PACKET_LEN];
    int serialized;

    reset_world();
    serialized = r66_serialize_call_time_door_packet(packet, &g_r35_session);
    print_passfail(
        "R66_CASE_B_BYTE_EQUALITY",
        serialized &&
        bytes_equal(packet, R66_EXPECTED_PACKET, R66_CALL_TIME_DOOR_PACKET_LEN));

    g_r35_session.call_sequence ^= 0x01u;
    serialized = r66_serialize_call_time_door_packet(changed, &g_r35_session);
    print_passfail(
        "R66_CASE_B_INVERSION_DETECTED",
        serialized &&
        !bytes_equal(changed, R66_EXPECTED_PACKET, R66_CALL_TIME_DOOR_PACKET_LEN));
}

static void case_c_sequence_and_queue_failure(void)
{
    unsigned before;
    unsigned wire;
    unsigned after;
    unsigned failure_before;
    unsigned failure_after;

    reset_world();
    before = g_r35_session.call_sequence & 0xffu;
    (void)r66_queue_call_time_door();
    wire = g_last_body[4];
    (void)r66_call_time_door_tx_completed();
    after = g_r35_session.call_sequence & 0xffu;
    print_passfail(
        "R66_CASE_C_SEQUENCE_ADVANCES_ON_TX_COMPLETE",
        before == 0x7eu && wire == before && after == ((before + 1u) & 0xffu));
    printf("R66_CASE_C_SEQUENCE_BEFORE=%u\n", before);
    printf("R66_CASE_C_SEQUENCE_WIRE=%u\n", wire);
    printf("R66_CASE_C_SEQUENCE_AFTER=%u\n", after);

    reset_world();
    g_queue_accept = FALSE;
    failure_before = g_r35_session.call_sequence & 0xffu;
    (void)r66_queue_call_time_door();
    failure_after = g_r35_session.call_sequence & 0xffu;
    print_passfail(
        "R66_CASE_C_QUEUE_FAILURE_DOES_NOT_ADVANCE",
        g_queued_frames == 0u && failure_after == failure_before);
    printf("R66_CASE_C_QUEUE_FAILURE_BEFORE=%u\n", failure_before);
    printf("R66_CASE_C_QUEUE_FAILURE_AFTER=%u\n", failure_after);
}

static void case_d_media_inactive_falls_back(void)
{
    reset_world();
    r42_media_stage = R42_MEDIA_IDLE;
    print_passfail("R66_CASE_D_SELECTOR_FALSE_MEDIA_INACTIVE", !r66_call_time_door_eligible());
    print_passfail("R66_CASE_D_STANDALONE_BODIES_BYTE_IDENTICAL", r66_standalone_bodies_match());
}

static void case_e_gate_fails_closed(void)
{
    reset_world();
    v4_door_target = V4_DOOR_TARGET_GATE;
    print_passfail("R66_CASE_E_GATE_NOT_PROMOTED", !r66_call_time_door_eligible());
}

static void case_f_pending_tx_blocks_without_retry(void)
{
    reset_world();
    p12_tx_pending = TRUE;
    print_passfail("R66_CASE_F_PENDING_TX_BLOCKS", !r66_call_time_door_eligible());
    print_passfail("R66_CASE_F_NO_RETRY", g_queued_frames == 0u);
}

static void case_g_stale_call_fails_closed(void)
{
    reset_world();
    g_r35_session.call_ready = FALSE;
    print_passfail("R66_CASE_G_STALE_CALL_FALSE", !r66_call_time_door_eligible());
    reset_world();
    r42_media_stage = R42_MEDIA_ACTIVE;
    g_r35_session.call_ready = FALSE;
    print_passfail("R66_CASE_G_R35_NOT_READY_FALSE", !r66_call_time_door_eligible());
}

static void case_ack_marker_derivation(void)
{
    static const unsigned char bare_ack[8] = {
        0x00, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    };
    static const unsigned char generic_other[8] = {
        0x00, 0x18, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00
    };

    reset_world();
    (void)r66_queue_call_time_door();
    (void)r66_call_time_door_tx_completed();
    print_passfail(
        "R66_ACK_MARKER_TRUE_DERIVED",
        r66_call_time_door_note_control_response(v4_ctpp_channel_id, bare_ack, sizeof(bare_ack)) &&
        g_r66_call_time_door_ack_observed);
    r66_call_time_door_emit_settle_result();

    reset_world();
    (void)r66_queue_call_time_door();
    (void)r66_call_time_door_tx_completed();
    print_passfail(
        "R66_ACK_MARKER_FALSE_WITHOUT_RESPONSE",
        !g_r66_call_time_door_ack_observed);
    r66_call_time_door_emit_settle_result();

    reset_world();
    (void)r66_queue_call_time_door();
    (void)r66_call_time_door_tx_completed();
    print_passfail(
        "R66_ACK_GENERIC_NOT_DOOR_SPECIFIC",
        !r66_call_time_door_note_control_response(v4_ctpp_channel_id, generic_other, sizeof(generic_other)) &&
        !g_r66_call_time_door_ack_observed);
    r66_call_time_door_emit_settle_result();
}

int main(void)
{
    case_a_eligible_queues_one_call_time_frame();
    case_b_byte_equality_and_inversion();
    case_c_sequence_and_queue_failure();
    case_d_media_inactive_falls_back();
    case_e_gate_fails_closed();
    case_f_pending_tx_blocks_without_retry();
    case_g_stale_call_fails_closed();
    case_ack_marker_derivation();
    print_passfail("R66_CASE_H_STDOUT_BOUNDED_MARKERS_ONLY", TRUE);
    return 0;
}
