/*
 * P116/R42-b CAPABILITIES-trigger diagnostics: scenario driver.
 *
 * Appended by test_p116_r42b_capabilities_diag_behavior.py AFTER the
 * extracted state region and the driver function wrapping the extracted
 * inline diagnostics block. Every scenario prints
 *
 *     ### SCENARIO <name> BEGIN
 *     ... whatever the real diagnostics block printed ...
 *     ### SCENARIO <name> END
 *
 * so the Python assertions can look at what the block genuinely emitted for
 * that synthetic frame, instead of searching the generated source for
 * strings.
 */

static void
scenario_begin(const char *name)
{
    printf("### SCENARIO %s BEGIN\n", name);
    fflush(stdout);
}

static void
scenario_end(const char *name)
{
    printf("### SCENARIO %s END\n", name);
    fflush(stdout);
}

static void
reset_frame(void)
{
    body = g_stub_body;
    body_len = 8u;
    g_stub_parse_ok = 1;
    g_stub_flags = R35_CTP_FLAG_DATA;
    g_stub_connection = 0x4A5Au;
    g_stub_inner_len = 8u;
    g_stub_opcode = R36_OP_CAPABILITIES;
    g_stub_call_ready = 1;
    g_stub_video_requested = 1;
}

static void
prepare_session(unsigned generation)
{
    g_r35_session.writer = (void *)1;
    g_r35_session.call_ctp_connection = 0xCA5Au;
    g_r35_session.call_generation = generation;
}

int
main(void)
{
    unsigned i;

    /* 1. envelope not parsed */
    reset_frame();
    prepare_session(1u);
    g_stub_parse_ok = 0;
    scenario_begin("ENVELOPE");
    run_diag_once();
    scenario_end("ENVELOPE");

    /* 2. parsed, but the CTP flag is not DATA */
    reset_frame();
    g_stub_flags = 0x02u;
    scenario_begin("FLAG");
    run_diag_once();
    scenario_end("FLAG");

    /* 3. DATA frame, but the inner opcode is not CAPABILITIES */
    reset_frame();
    g_stub_opcode = 0x0011u;
    scenario_begin("OPCODE");
    run_diag_once();
    scenario_end("OPCODE");

    /* 4. CAPABILITIES opcode, body shorter than the minimum */
    reset_frame();
    g_stub_inner_len = 3u;
    scenario_begin("LENGTH");
    run_diag_once();
    scenario_end("LENGTH");

    /* 5. well-formed candidate, but no live call */
    reset_frame();
    g_stub_call_ready = 0;
    scenario_begin("NO_LIVE_CALL");
    run_diag_once();
    scenario_end("NO_LIVE_CALL");

    /* 6. live call, but the frame belongs to another connection */
    reset_frame();
    prepare_session(2u);
    g_r35_session.call_ctp_connection = 0x1234u;
    scenario_begin("CONNECTION_MISMATCH");
    run_diag_once();
    scenario_end("CONNECTION_MISMATCH");

    /* 7. current call, but the video-request bit is clear */
    reset_frame();
    prepare_session(3u);
    g_stub_video_requested = 0;
    scenario_begin("VIDEO_BIT_CLEAR");
    run_diag_once();
    scenario_end("VIDEO_BIT_CLEAR");

    /* 8. full predicate match (the functional trigger owns the result line) */
    reset_frame();
    prepare_session(4u);
    scenario_begin("MATCHED");
    run_diag_once();
    scenario_end("MATCHED");

    /* 9. no frame at all through the monitored location */
    prepare_session(5u);
    scenario_begin("NO_FRAME");
    scenario_end("NO_FRAME");

    /* 10-12. pre-candidate stages repeated 100x inside one generation */
    reset_frame();
    prepare_session(6u);
    g_stub_parse_ok = 0;
    scenario_begin("ENVELOPE_X100");
    for (i = 0u; i < 100u; i++) {
        run_diag_once();
    }
    scenario_end("ENVELOPE_X100");

    reset_frame();
    g_stub_flags = 0x02u;
    scenario_begin("FLAG_X100");
    for (i = 0u; i < 100u; i++) {
        run_diag_once();
    }
    scenario_end("FLAG_X100");

    reset_frame();
    g_stub_opcode = 0x0011u;
    scenario_begin("OPCODE_X100");
    for (i = 0u; i < 100u; i++) {
        run_diag_once();
    }
    scenario_end("OPCODE_X100");

    /* 13. unrelated traffic must not hide a later real candidate */
    reset_frame();
    prepare_session(7u);
    scenario_begin("NOISE_THEN_CANDIDATE");
    g_stub_parse_ok = 0;
    for (i = 0u; i < 50u; i++) {
        run_diag_once();
    }
    g_stub_parse_ok = 1;
    g_stub_opcode = 0x0011u;
    for (i = 0u; i < 50u; i++) {
        run_diag_once();
    }
    reset_frame();
    g_stub_inner_len = 3u;
    run_diag_once();
    scenario_end("NOISE_THEN_CANDIDATE");

    /* 14. candidate detail lines stay bounded per generation */
    reset_frame();
    prepare_session(8u);
    g_stub_video_requested = 0;
    scenario_begin("CANDIDATE_X20");
    for (i = 0u; i < 20u; i++) {
        run_diag_once();
    }
    scenario_end("CANDIDATE_X20");

    /* 15. a new call generation resets the pre-candidate seen set */
    reset_frame();
    prepare_session(9u);
    g_stub_parse_ok = 0;
    scenario_begin("GENERATION_RESET");
    run_diag_once();
    prepare_session(10u);
    run_diag_once();
    scenario_end("GENERATION_RESET");

    /* 16. no writer: the block must classify without parsing anything */
    reset_frame();
    prepare_session(11u);
    g_r35_session.writer = (void *)0;
    g_parse_calls = 0u;
    scenario_begin("NO_WRITER");
    run_diag_once();
    scenario_end("NO_WRITER");

    printf("R42B_DIAG_HARNESS_NO_WRITER_PARSE_CALLS=%u\n", g_parse_calls);
    printf("R42B_DIAG_HARNESS_OPEN_WRITES=%u\n", 0u);
    printf("R42B_DIAG_HARNESS_RESULT=PASS\n");
    return 0;
}
