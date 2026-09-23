/*
 * P116/R57 native failure-identity observability harness.
 *
 * The Python test extracts the R57_NATIVE_FAILURE_ATTRIBUTION region from
 * the real generated candidate (the same enums, p116_record_failure(),
 * p116_infer_phase() and p116_emit_native_exit_summary() the production
 * source uses) and inserts it below. This harness does not compile the
 * frozen listener's GLib/PseudoTCP/libnice callbacks (the existing R54
 * region harness already documents why that full runtime is out of
 * scope for an offline host harness); instead each scenario calls
 * p116_record_failure() with the exact (id, phase) argument pair that the
 * corresponding real call site in the generated source passes, so the
 * contract itself (first-fail-wins, exit summary, count) is exercised
 * against the real, unmodified region text.
 */

#include <stdio.h>
#include <string.h>

typedef int gboolean;
typedef unsigned int guint;
#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif

static gboolean v4_listener_ready = TRUE;

typedef enum {
    R42_MEDIA_IDLE = 0,
    R42_MEDIA_CHANNEL_OPEN_TX,
    R42_MEDIAREQ_OPEN_TX,
    R42_MEDIA_ACTIVE,
    R42_MEDIA_CHANNEL_CLOSE_TX,
    R42_MEDIA_CHANNEL_CLOSE_WAIT,
    R42_MEDIA_CLOSED,
    R42_MEDIA_FAILED
} R42AttachedMediaStage;
static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;

typedef enum {
    R54_TX_STATE_IDLE = 0,
    R54_TX_STATE_NEED_INVITE_ACK,
    R54_TX_STATE_WAIT_INVITE_ACK_FLUSH,
    R54_TX_STATE_NEED_LOCAL_CAPABILITIES,
    R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH,
    R54_TX_STATE_NEED_LOCAL_ALERTING,
    R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH,
    R54_TX_STATE_WAIT_PEER_CAPABILITIES,
    R54_TX_STATE_NEED_PEER_DATA_ACK,
    R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH,
    R54_TX_STATE_MEDIA_TRIGGER_READY,
    R54_TX_STATE_TERMINAL_FAILURE
} R54TxState;
static R54TxState g_r54_tx_state = R54_TX_STATE_IDLE;

/* R57_GENERATED_REGION_INSERT_HERE */

static void r57h_reset(void)
{
    g_p116_failure_id = P116_FAILURE_NONE;
    g_p116_failure_phase = P116_PHASE_STARTUP;
    g_p116_failure_count = 0u;
    v4_listener_ready = TRUE;
    r42_media_stage = R42_MEDIA_IDLE;
    g_r54_tx_state = R54_TX_STATE_IDLE;
}

static void r57h_mark(const char *scenario, gboolean ok)
{
    printf("R57_SCENARIO_%s=%s\n", scenario, ok ? "PASS" : "FAIL");
}

/* Positive flow: no failure recorded, exit code 0, id stays NONE. */
static void r57h_scenario_positive_no_failure(void)
{
    gboolean ok;
    r57h_reset();
    p116_emit_native_exit_summary(FALSE);
    ok = g_p116_failure_id == P116_FAILURE_NONE &&
        g_p116_failure_count == 0u;
    r57h_mark("POSITIVE_NO_FAILURE_ID_NONE", ok);
}

/* Scenario 1: pseudotcp_writable_cb (real site at "try_send_uaut_open() ||",
 * ID=PSEUDOTCP_WRITABLE_TRANSPORT, dynamic phase -> WAIT_PEER_CAPABILITIES
 * here for a concrete example). */
static void r57h_scenario_pseudotcp_writable_fatal(void)
{
    gboolean ok;
    r57h_reset();
    g_r54_tx_state = R54_TX_STATE_WAIT_PEER_CAPABILITIES;
    p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT &&
        g_p116_failure_phase == P116_PHASE_WAIT_PEER_CAPABILITIES &&
        g_p116_failure_count == 1u;
    r57h_mark("PSEUDOTCP_WRITABLE_FATAL", ok);
}

/* Scenario 2: pseudotcp_closed_cb (real site "PSEUDOTCP_CLOSED_CALLBACK=true ",
 * ID=PSEUDOTCP_CLOSED). */
static void r57h_scenario_pseudotcp_closed(void)
{
    gboolean ok;
    r57h_reset();
    g_r54_tx_state = R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH;
    p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOSED, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_PSEUDOTCP_CLOSED &&
        g_p116_failure_phase == P116_PHASE_PEER_ACK &&
        g_p116_failure_count == 1u;
    r57h_mark("PSEUDOTCP_CLOSED", ok);
}

/* Scenario 3: pseudotcp_write_packet_cb (real site "PSEUDOTCP_WRITE_PACKET=FAIL ",
 * ID=PSEUDOTCP_WRITE_PACKET). */
static void r57h_scenario_write_packet_fatal(void)
{
    gboolean ok;
    r57h_reset();
    r42_media_stage = R42_MEDIA_ACTIVE;
    p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_PSEUDOTCP_WRITE_PACKET &&
        g_p116_failure_phase == P116_PHASE_MEDIA_ACTIVE &&
        g_p116_failure_count == 1u;
    r57h_mark("WRITE_PACKET_FATAL", ok);
}

/* Scenario 4: pseudotcp_readable_cb post-handshake recv (real site
 * "if (!try_parse_uaut_response())", ID=RECV_PARSE, dynamic phase). This is
 * the first-canary top candidate identified by the R57 forensic analysis. */
static void r57h_scenario_recv_parse_failure(void)
{
    gboolean ok;
    r57h_reset();
    g_r54_tx_state = R54_TX_STATE_WAIT_PEER_CAPABILITIES;
    p116_record_failure(P116_FAILURE_RECV_PARSE, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_RECV_PARSE &&
        g_p116_failure_phase == P116_PHASE_WAIT_PEER_CAPABILITIES &&
        g_p116_failure_count == 1u;
    r57h_mark("RECV_PARSE_FAILURE", ok);
}

/* Scenario 5: p12_stage_timeout_cb (real site "P12_READONLY_STAGE_TIMEOUT
 * stage=%u", ID=P12_STEP_TIMEOUT). Also proves the R56 TX-wait timeout
 * (same P12_STEP_TIMEOUT_SECONDS constant, different mechanism) stays
 * non-fatal: this scenario only exercises the fatal legacy path. */
static void r57h_scenario_p12_step_timeout(void)
{
    gboolean ok;
    r57h_reset();
    v4_listener_ready = FALSE;
    p116_record_failure(P116_FAILURE_P12_STEP_TIMEOUT, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_P12_STEP_TIMEOUT &&
        g_p116_failure_phase == P116_PHASE_STARTUP &&
        g_p116_failure_count == 1u;
    r57h_mark("P12_STEP_TIMEOUT", ok);
}

/* Scenario 6: startup failure (real site "VIP_UAUT_OPEN_RESPONSE_TIMEOUT=true"
 * in uaut_response_timeout_cb, ID=UAUT_OPEN_TIMEOUT, fixed PHASE=STARTUP). */
static void r57h_scenario_startup_failure(void)
{
    gboolean ok;
    r57h_reset();
    p116_record_failure(P116_FAILURE_UAUT_OPEN_TIMEOUT, P116_PHASE_STARTUP);
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_UAUT_OPEN_TIMEOUT &&
        g_p116_failure_phase == P116_PHASE_STARTUP &&
        g_p116_failure_count == 1u;
    r57h_mark("STARTUP_FAILURE", ok);
}

/* Scenario 7: SDP failure (real site "REMOTE_SDP_READ=FAIL" in
 * remote_sdp_check_cb, ID=SDP_FILE). */
static void r57h_scenario_sdp_failure(void)
{
    gboolean ok;
    r57h_reset();
    p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP);
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_SDP_FILE &&
        g_p116_failure_count == 1u;
    r57h_mark("SDP_FAILURE", ok);
}

/* Scenario 8: a Door setter, offline fake only -- this harness never
 * performs a Door action; it only proves the observability contract for
 * the existing (pre-R57) Door failed=TRUE site at v4_door_tick_cb's
 * deadline check ("g_get_monotonic_time() > v4_door_deadline_us) {",
 * ID=DOOR_TIMER, fixed PHASE=LISTENER_READY). */
static void r57h_scenario_door_setter(void)
{
    gboolean ok;
    r57h_reset();
    p116_record_failure(P116_FAILURE_DOOR_TIMER, P116_PHASE_LISTENER_READY);
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_DOOR_TIMER &&
        g_p116_failure_phase == P116_PHASE_LISTENER_READY &&
        g_p116_failure_count == 1u;
    r57h_mark("DOOR_SETTER_OFFLINE_FAKE", ok);
}

/* Scenario 9: multiple cascading failures -- first-fail-wins. A closed
 * transport (root cause) is followed by a recv-parse failure triggered by
 * the same teardown (cascade); the primary id/phase must stay the first
 * one and the count must reflect both. */
static void r57h_scenario_cascade_first_fail_wins(void)
{
    gboolean ok;
    r57h_reset();
    g_r54_tx_state = R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH;
    p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOSED, p116_infer_phase());
    p116_record_failure(P116_FAILURE_RECV_PARSE, p116_infer_phase());
    p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase());
    p116_emit_native_exit_summary(TRUE);
    ok = g_p116_failure_id == P116_FAILURE_PSEUDOTCP_CLOSED &&
        g_p116_failure_count == 3u;
    r57h_mark("CASCADE_FIRST_FAIL_WINS", ok);
}

int main(void)
{
    r57h_scenario_positive_no_failure();
    r57h_scenario_pseudotcp_writable_fatal();
    r57h_scenario_pseudotcp_closed();
    r57h_scenario_write_packet_fatal();
    r57h_scenario_recv_parse_failure();
    r57h_scenario_p12_step_timeout();
    r57h_scenario_startup_failure();
    r57h_scenario_sdp_failure();
    r57h_scenario_door_setter();
    r57h_scenario_cascade_first_fail_wins();
    return 0;
}
