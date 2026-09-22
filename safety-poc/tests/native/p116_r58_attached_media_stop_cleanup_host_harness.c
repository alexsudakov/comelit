/*
 * P116/R58 attached-media STOP cleanup host harness.
 *
 * The Python test inserts the generated R58 declaration/definition regions at
 * the placeholder below. This host harness supplies only fake R35 and P12
 * state: no native helper, network, Door, Gate, ADB, ptrace or PCAP path is
 * present.
 */

#include <stdio.h>
#include <string.h>

typedef int gboolean;
typedef void *gpointer;
#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif
#define G_SOURCE_CONTINUE TRUE

typedef enum {
    R35_FORM_TUNNEL = 0,
    R35_FORM_ADDRESS = 1
} R35Form;

typedef enum {
    R35_STATE_CALL_CAPTURED = 0,
    R35_STATE_CHANNEL_UNALLOCATED,
    R35_STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED,
    R35_STATE_OPEN_SENT,
    R35_STATE_RTP_ELIGIBLE,
    R35_STATE_STOP_SENT,
    R35_STATE_DISPOSED,
    R35_STATE_TERMINAL,
    R35_STATE_ERROR
} R35MediaState;

typedef enum {
    R35_OK = 0,
    R35_ERR_BAD_ARGUMENT,
    R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER,
    R35_ERR_NO_CHANNEL_ALLOCATED,
    R35_ERR_CHANNEL_ALREADY_ALLOCATED,
    R35_ERR_OPEN_ALREADY_PENDING,
    R35_ERR_OPEN_ALREADY_EMITTED,
    R35_ERR_STOP_ALREADY_SENT,
    R35_ERR_CHANNEL_ALREADY_DISPOSED,
    R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL,
    R35_ERR_WRONG_CHANNEL,
    R35_ERR_STALE_CHANNEL,
    R35_ERR_STOP_BEFORE_OPEN,
    R35_ERR_SECOND_STOP,
    R35_ERR_DISPOSE_BEFORE_STOP,
    R35_ERR_RTP_BEFORE_OPEN
} R35Result;

typedef void (*R35RtpArmHook)(void *ctx, int armed);

typedef struct {
    int call_ctp_valid;
    int call_transaction_alive;
    unsigned call_generation;
    unsigned call_ctp_connection;
    unsigned call_sequence;
    unsigned call_ack;
    unsigned outer_ctpp_handle;
    unsigned char source_logical[10];
    unsigned char dest_logical[10];
    int channel_allocated;
    int channel_disposed;
    unsigned channel_generation;
    unsigned channel_id;
    unsigned channel_token;
    int open_pending;
    int open_sent;
    int open_confirmed;
    int stop_sent;
    int rtp_armed;
    unsigned open_count;
    unsigned stop_count;
    int listener_alive;
    int registration_alive;
    int pseudotcp_alive;
    R35MediaState state;
    void *writer;
    void *writer_ctx;
    R35RtpArmHook rtp_arm_hook;
    void *rtp_arm_hook_ctx;
} R35AttachedMediaSession;

typedef enum {
    R54_TX_SUBJECT_NONE = 0,
    R54_TX_SUBJECT_INVITE_ACK,
    R54_TX_SUBJECT_LOCAL_CAPABILITIES,
    R54_TX_SUBJECT_LOCAL_ALERTING,
    R54_TX_SUBJECT_PEER_DATA_ACK,
    R54_TX_SUBJECT_MEDIA_OPEN,
    R54_TX_SUBJECT_MEDIA_STOP,
    R54_TX_SUBJECT_OTHER_EXISTING
} R54TxSubject;

typedef enum {
    R54_TX_QUEUE_REASON_NONE = 0,
    R54_TX_QUEUE_REASON_BUSY,
    R54_TX_QUEUE_REASON_INVALID_LENGTH,
    R54_TX_QUEUE_REASON_TRANSPORT,
    R54_TX_QUEUE_REASON_UNKNOWN
} R54TxQueueReason;

typedef enum {
    P12_TX_NONE = 0,
    P12_TX_R35_MEDIA_STOP,
    P12_TX_OTHER
} P12TxKind;

typedef enum {
    R42_MEDIA_IDLE = 0,
    R42_MEDIA_CHANNEL_OPEN_TX,
    R42_MEDIAREQ_OPEN_TX,
    R42_MEDIA_ACTIVE,
    R42_MEDIAREQ_STOP_TX,
    R42_MEDIA_CHANNEL_CLOSE_TX,
    R42_MEDIA_CHANNEL_CLOSE_WAIT,
    R42_MEDIA_CLOSED,
    R42_MEDIA_FAILED
} R42AttachedMediaStage;

typedef struct {
    unsigned bounded_stop_request_received_count;
    unsigned call_bound_media_stop_sent_count;
    unsigned rtp_disarmed_count;
    unsigned media_rx_channel_disposed_count;
    unsigned duplicate_stop_request_ignored_count;
} R37BoundedStopTelemetry;

static R35AttachedMediaSession g_r35_session;
static R37BoundedStopTelemetry g_r37_telemetry;
static R54TxSubject g_r54_tx_last_subject = R54_TX_SUBJECT_NONE;
static R54TxSubject g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
static R54TxQueueReason g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
static gboolean p12_tx_pending = FALSE;
static P12TxKind p12_tx_kind = P12_TX_NONE;
static R42AttachedMediaStage r42_media_stage = R42_MEDIA_ACTIVE;
static unsigned r42_media_channel_id = 0u;
static int fake_flush_complete = 1;
static int fake_write_fail = 0;
static int fake_rtp_armed = 1;
static unsigned fake_closed_marker_count = 0u;
static unsigned fake_network_tx = 0u;
static unsigned fake_door_actions = 0u;
static unsigned fake_gate_actions = 0u;
static unsigned fake_stop_count_max = 0u;
static int fake_flushed_before_closed = 1;
static int fake_saw_flushed_phase = 0;
static int fake_ha_close_confirmation_reached = 0;
static int fake_ha_close_confirmation_ever = 0;
static int fake_no_false_stop_timeout = 1;

static int r35_call_ready(const R35AttachedMediaSession *s);
static R35Result r35_send_stop(R35AttachedMediaSession *s, int form, unsigned channel_id);
static R35Result r35_dispose_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id);
static void r35_teardown_call(R35AttachedMediaSession *s);
static gboolean p12_flush_tx(void);
static void p12_tx_completed(P12TxKind kind);
static void r42_finish_media_channel_close(void);

/* R58_GENERATED_REGION_INSERT_HERE */

static void fake_rtp_arm_hook(void *ctx, int armed)
{
    (void)ctx;
    fake_rtp_armed = armed;
}

static int r35_call_ready(const R35AttachedMediaSession *s)
{
    return s && s->call_ctp_valid && s->call_transaction_alive;
}

static R35Result r35_send_stop(R35AttachedMediaSession *s, int form, unsigned channel_id)
{
    (void)form;
    if (!s)
        return R35_ERR_BAD_ARGUMENT;
    if (fake_write_fail)
        return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s))
        return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (!s->channel_allocated || s->channel_disposed)
        return R35_ERR_STALE_CHANNEL;
    if (s->channel_id != channel_id)
        return R35_ERR_WRONG_CHANNEL;
    if (!s->open_sent || s->open_count == 0u)
        return R35_ERR_STOP_BEFORE_OPEN;
    if (s->stop_sent || s->stop_count != 0u)
        return R35_ERR_SECOND_STOP;

    g_r54_tx_last_subject = R54_TX_SUBJECT_MEDIA_STOP;
    g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
    if (p12_tx_pending) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_BUSY;
    } else {
        p12_tx_pending = TRUE;
        p12_tx_kind = P12_TX_R35_MEDIA_STOP;
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_MEDIA_STOP;
    }

    s->call_sequence = (s->call_sequence + 1u) & 0xffu;
    s->stop_sent = 1;
    s->stop_count += 1u;
    s->rtp_armed = 0;
    s->state = R35_STATE_STOP_SENT;
    if (s->rtp_arm_hook)
        s->rtp_arm_hook(s->rtp_arm_hook_ctx, 0);
    return R35_OK;
}

static R35Result r35_dispose_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id)
{
    if (!s)
        return R35_ERR_BAD_ARGUMENT;
    if (s->channel_id != channel_id)
        return R35_ERR_WRONG_CHANNEL;
    if (!s->stop_sent || s->stop_count == 0u)
        return R35_ERR_DISPOSE_BEFORE_STOP;
    s->channel_disposed = 1;
    s->channel_allocated = 0;
    s->rtp_armed = 0;
    s->state = R35_STATE_DISPOSED;
    return R35_OK;
}

static void r35_teardown_call(R35AttachedMediaSession *s)
{
    if (!s)
        return;
    s->call_ctp_valid = 0;
    s->call_transaction_alive = 0;
    s->state = R35_STATE_TERMINAL;
}

static gboolean r42_queue_media_channel_close(void)
{
    r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_TX;
    return TRUE;
}

static void r42_finish_media_channel_close(void)
{
    if (r58_closed_published_for_generation())
        return;
    r58_mark_closed_published();
    if (!fake_saw_flushed_phase)
        fake_flushed_before_closed = 0;
    r42_media_stage = R42_MEDIA_CLOSED;
    r42_media_channel_id = 0u;
    fake_closed_marker_count += 1u;
    fake_ha_close_confirmation_reached = 1;
    fake_ha_close_confirmation_ever = 1;
    printf("R42_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    printf("R42_MEDIA_CHANNEL_CLOSED=true\n");
    fflush(stdout);
}

static void p12_tx_completed(P12TxKind kind)
{
    if (kind == P12_TX_R35_MEDIA_STOP) {
        if (r42_media_channel_id != 0u) {
            r42_media_stage = R42_MEDIAREQ_STOP_TX;
            printf("R42_ATTACHED_MEDIA_STOP_SENT=true\n");
            printf("R42_CALL_GENERATION=%u\n", g_r35_session.call_generation);
            printf("R42_MEDIA_STOP_CHANNEL=%u\n", r42_media_channel_id);
            fflush(stdout);
            if (!r42_queue_media_channel_close()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIA_CHANNEL_CLOSE_QUEUE=FAIL\n");
                fflush(stdout);
            }
        }
        fake_saw_flushed_phase = 1;
        r58_stop_publish_closed();
    }
    r58_stop_drive(&g_r35_session);
    fflush(stdout);
}

static gboolean p12_flush_tx(void)
{
    P12TxKind completed;
    if (!p12_tx_pending)
        return TRUE;
    if (!fake_flush_complete)
        return TRUE;
    completed = p12_tx_kind;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    p12_tx_completed(completed);
    return TRUE;
}

static void h_reset(unsigned generation)
{
    memset(&g_r35_session, 0, sizeof(g_r35_session));
    memset(&g_r37_telemetry, 0, sizeof(g_r37_telemetry));
    g_r35_session.call_ctp_valid = 1;
    g_r35_session.call_transaction_alive = 1;
    g_r35_session.call_generation = generation;
    g_r35_session.call_ctp_connection = 1u;
    g_r35_session.call_sequence = 10u;
    g_r35_session.call_ack = 9u;
    g_r35_session.channel_allocated = 1;
    g_r35_session.channel_disposed = 0;
    g_r35_session.channel_generation = generation;
    g_r35_session.channel_id = 7400u + generation;
    g_r35_session.open_sent = 1;
    g_r35_session.open_count = 1u;
    g_r35_session.rtp_armed = 1;
    g_r35_session.listener_alive = 1;
    g_r35_session.registration_alive = 1;
    g_r35_session.pseudotcp_alive = 1;
    g_r35_session.state = R35_STATE_RTP_ELIGIBLE;
    g_r35_session.rtp_arm_hook = fake_rtp_arm_hook;
    r42_media_stage = R42_MEDIA_ACTIVE;
    r42_media_channel_id = g_r35_session.channel_id;
    g_r54_tx_last_subject = R54_TX_SUBJECT_NONE;
    g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
    g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    fake_flush_complete = 1;
    fake_write_fail = 0;
    fake_rtp_armed = 1;
    fake_closed_marker_count = 0u;
    fake_flushed_before_closed = 1;
    fake_saw_flushed_phase = 0;
    fake_ha_close_confirmation_reached = 0;
    fake_no_false_stop_timeout = 1;
    r58_stop_reset_for_generation();
}

static void h_update_max(void)
{
    if (g_r58_stop_write_attempt_count > fake_stop_count_max)
        fake_stop_count_max = g_r58_stop_write_attempt_count;
}

static void h_mark(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
}

static void h_normal_path(void)
{
    h_reset(1u);
    fake_flush_complete = 0;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    if (fake_closed_marker_count != 0u)
        fake_no_false_stop_timeout = 0;
    fake_flush_complete = 1;
    (void)p12_flush_tx();
    h_update_max();
    h_mark("R58_STOP_NORMAL_PATH",
        g_r58_stop_closed && fake_closed_marker_count == 1u &&
        g_r58_stop_write_attempt_count == 1u && g_r58_stop_disposed &&
        fake_ha_close_confirmation_reached);
}

static void h_queue_busy(void)
{
    h_reset(2u);
    p12_tx_pending = TRUE;
    p12_tx_kind = P12_TX_OTHER;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    if (g_r58_stop_write_attempt_count != 0u || g_r58_stop_phase != R58_STOP_PHASE_WAIT_TX_SLOT)
        fake_no_false_stop_timeout = 0;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    (void)r58_stop_drive(&g_r35_session);
    h_update_max();
    h_mark("R58_STOP_QUEUE_BUSY",
        g_r58_stop_closed && g_r58_stop_write_attempt_count == 1u &&
        g_r58_stop_wait_slot_count == 1u && fake_closed_marker_count == 1u);
}

static void h_duplicate_ha_stop(void)
{
    h_reset(3u);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    h_update_max();
    h_mark("R58_STOP_DUPLICATE_HA_STOP",
        g_r58_stop_write_attempt_count == 1u &&
        g_r58_stop_duplicate_ignored_count == 1u &&
        fake_closed_marker_count == 1u);
}

static void h_remote_release_before_sigusr2(void)
{
    h_reset(4u);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_REMOTE_RELEASE);
    r35_teardown_call(&g_r35_session);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    h_update_max();
    h_mark("R58_REMOTE_RELEASE_BEFORE_SIGUSR2",
        g_r58_stop_write_attempt_count == 1u &&
        g_r58_stop_duplicate_ignored_count == 1u &&
        g_r58_stop_closed && fake_closed_marker_count == 1u);
}

static void h_remote_release_after_sigusr2(void)
{
    h_reset(5u);
    fake_flush_complete = 0;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_REMOTE_RELEASE);
    r35_teardown_call(&g_r35_session);
    fake_flush_complete = 1;
    (void)p12_flush_tx();
    h_update_max();
    h_mark("R58_REMOTE_RELEASE_AFTER_SIGUSR2",
        g_r58_stop_write_attempt_count == 1u &&
        g_r58_stop_duplicate_ignored_count == 1u &&
        fake_closed_marker_count == 1u);
}

static void h_sigusr2_after_closed(void)
{
    h_reset(6u);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    h_update_max();
    h_mark("R58_SIGUSR2_AFTER_CLOSED",
        g_r58_stop_write_attempt_count == 1u &&
        fake_closed_marker_count == 1u &&
        g_r58_stop_duplicate_ignored_count == 1u);
}

static void h_write_failure(void)
{
    h_reset(7u);
    fake_write_fail = 1;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    h_update_max();
    h_mark("R58_STOP_WRITE_FAILURE",
        g_r58_stop_phase == R58_STOP_PHASE_FAILED &&
        g_r58_stop_failure_stage == R58_STOP_FAILURE_STAGE_WRITE &&
        fake_closed_marker_count == 0u);
}

static void h_flush_timeout(void)
{
    h_reset(8u);
    fake_flush_complete = 0;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    h_update_max();
    h_mark("R58_STOP_FLUSH_TIMEOUT",
        g_r58_stop_write_attempt_count == 1u &&
        !g_r58_stop_closed &&
        fake_closed_marker_count == 0u);
}

static void h_generation_replacement(void)
{
    h_reset(9u);
    p12_tx_pending = TRUE;
    p12_tx_kind = P12_TX_OTHER;
    (void)r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    g_r35_session.call_generation = 10u;
    g_r35_session.channel_generation = 10u;
    g_r35_session.channel_id = 7410u;
    r42_media_channel_id = 7410u;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    r58_stop_reset_for_generation();
    h_update_max();
    h_mark("R58_GENERATION_REPLACEMENT",
        g_r58_stop_request_count == 0u &&
        g_r58_stop_write_attempt_count == 0u &&
        !g_r58_stop_requested);
}

static void h_exactly_one_protocol_stop(void)
{
    h_mark("R58_EXACTLY_ONE_PROTOCOL_STOP", fake_stop_count_max == 1u);
}

int main(void)
{
    h_normal_path();
    h_queue_busy();
    h_duplicate_ha_stop();
    h_remote_release_before_sigusr2();
    h_remote_release_after_sigusr2();
    h_sigusr2_after_closed();
    h_write_failure();
    h_flush_timeout();
    h_generation_replacement();
    h_exactly_one_protocol_stop();
    printf("R58_HOST_HARNESS_RESULT=%s\n", fake_stop_count_max == 1u ? "PASS" : "FAIL");
    printf("R58_STOP_COUNT_MAX=%u\n", fake_stop_count_max);
    printf("R58_STOP_FLUSHED_BEFORE_CLOSED=%s\n", fake_flushed_before_closed ? "true" : "false");
    printf("R58_HA_CLOSE_CONFIRMATION_REACHED=%s\n", fake_ha_close_confirmation_ever ? "true" : "false");
    printf("R58_NO_FALSE_STOP_TIMEOUT=%s\n", fake_no_false_stop_timeout ? "true" : "false");
    printf("R58_NETWORK_TX=%u\n", fake_network_tx);
    printf("R58_DOOR_ACTIONS=%u\n", fake_door_actions);
    printf("R58_GATE_ACTIONS=%u\n", fake_gate_actions);
    return fake_stop_count_max == 1u ? 0 : 1;
}
