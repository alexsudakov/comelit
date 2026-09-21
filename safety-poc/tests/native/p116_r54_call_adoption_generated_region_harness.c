/*
 * P116/R54 generated-region host harness.
 *
 * The Python test assembles this after extracting the R35/R36/R45/R53/R54
 * regions from the generated production-candidate source.  R42's full GLib
 * runtime is intentionally not compiled here; r42_queue_media_channel_open()
 * is represented by a fake interception point so ordering is testable:
 * CALL_INIT -> ACK -> CAP -> ALERTING -> peer CAP -> peer ACK -> MEDIA_OPEN.
 */

#include <stdio.h>
#include <string.h>

typedef unsigned char guint8;
typedef unsigned int guint;
typedef int gboolean;
typedef long long gint64;
typedef void *gpointer;

#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif

#define R54H_MAX_WRITES 32u
#define R54H_MAX_FRAME  72u

typedef struct {
    char kind[32];
    unsigned char packet[R54H_MAX_FRAME];
    unsigned len;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
} R54HCapturedWrite;

static R54HCapturedWrite g_writes[R54H_MAX_WRITES];
static unsigned g_write_count = 0u;
static unsigned g_media_open_intercepts = 0u;
static unsigned g_fake_second_media_open_observed = 0u;
static unsigned g_network_tx = 0u;
static unsigned g_door_actions = 0u;
static unsigned g_gate_actions = 0u;
static int g_media_open_should_fail = 0;
static gint64 g_fake_now_us = 0;

static R35AttachedMediaSession g_r35_session;

#define P12_STEP_TIMEOUT_SECONDS 6
#define G_USEC_PER_SEC 1000000
#define G_SOURCE_REMOVE 0

typedef enum {
    P12_TX_NONE = 0,
    P12_TX_R35_MEDIA_OPEN,
    P12_TX_R35_MEDIA_STOP,
    P12_TX_R54_INVITE_ACK,
    P12_TX_R54_LOCAL_CAPABILITIES,
    P12_TX_R54_LOCAL_ALERTING,
    P12_TX_R54_PEER_DATA_ACK
} P12TxKind;

static gboolean p12_tx_pending = FALSE;
static P12TxKind p12_tx_kind = P12_TX_NONE;
static int g_fake_p12_hold_flush = 0;
static int g_fake_p12_single_step_mode = 0;
static int g_fake_enqueue_while_busy = 0;
static int g_fake_enqueue_while_busy_observed = 0;
static int g_fake_p12_partial_flush = 0;
static int g_fake_p12_partial_progress = 0;

static gint64 g_get_monotonic_time(void)
{
    return g_fake_now_us;
}

static gboolean p12_flush_tx(void);
static guint g_timeout_add_seconds(guint seconds, gboolean (*cb)(gpointer), gpointer data)
{
    (void)seconds;
    (void)cb;
    (void)data;
    return 1u;
}

static void mark(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
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
    R54HCapturedWrite *w;
    P12TxKind kind_id = P12_TX_R35_MEDIA_STOP;
    R54TxSubject subject = R54_TX_SUBJECT_OTHER_EXISTING;
    (void)ctx;
    if (!kind || len > R54H_MAX_FRAME || g_write_count >= R54H_MAX_WRITES) return;
    if (strcmp(kind, "MEDIA_OPEN") == 0) {
        kind_id = P12_TX_R35_MEDIA_OPEN;
        subject = R54_TX_SUBJECT_MEDIA_OPEN;
    } else if (strcmp(kind, "MEDIA_STOP") == 0) {
        kind_id = P12_TX_R35_MEDIA_STOP;
        subject = R54_TX_SUBJECT_MEDIA_STOP;
    } else if (strcmp(kind, "CALL_INVITE_ACK") == 0) {
        kind_id = P12_TX_R54_INVITE_ACK;
        subject = R54_TX_SUBJECT_INVITE_ACK;
    } else if (strcmp(kind, "CALL_CAPABILITIES") == 0) {
        kind_id = P12_TX_R54_LOCAL_CAPABILITIES;
        subject = R54_TX_SUBJECT_LOCAL_CAPABILITIES;
    } else if (strcmp(kind, "CALL_ALERTING") == 0) {
        kind_id = P12_TX_R54_LOCAL_ALERTING;
        subject = R54_TX_SUBJECT_LOCAL_ALERTING;
    } else if (strcmp(kind, "CALL_PEER_DATA_ACK") == 0) {
        kind_id = P12_TX_R54_PEER_DATA_ACK;
        subject = R54_TX_SUBJECT_PEER_DATA_ACK;
    }
    g_r54_tx_last_subject = subject;
    g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
    g_r54_tx_last_reason = R54_TX_QUEUE_REASON_UNKNOWN;
    if (p12_tx_pending) {
        g_fake_enqueue_while_busy = 1;
        g_fake_enqueue_while_busy_observed++;
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_BUSY;
        return;
    }
    p12_tx_pending = TRUE;
    p12_tx_kind = kind_id;
    g_r54_tx_last_enqueued = subject;
    g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
    w = &g_writes[g_write_count++];
    strncpy(w->kind, kind, sizeof(w->kind) - 1u);
    if (packet && len > 0u) memcpy(w->packet, packet, len);
    w->len = len;
    w->connection = connection;
    w->sequence = sequence;
    w->acknowledgement = acknowledgement;
}

static void r54h_wire(void)
{
    g_r35_session.writer = fake_writer;
}

static gboolean r42_queue_media_channel_open(void)
{
    unsigned char marker = 0x42u;
    if (g_media_open_should_fail) return FALSE;
    g_media_open_intercepts++;
    if (g_media_open_intercepts > 1u)
        g_fake_second_media_open_observed++;
    fake_writer(
        NULL,
        "MEDIA_OPEN",
        &marker,
        1u,
        g_r35_session.call_ctp_connection,
        g_r35_session.call_sequence,
        g_r35_session.call_ack);
    return TRUE;
}

/* R54_GENERATED_REGION_INSERT_HERE */

static gboolean p12_flush_tx(void)
{
    P12TxKind completed;
    if (!p12_tx_pending)
        return TRUE;
    if (g_fake_p12_partial_flush) {
        g_fake_p12_partial_flush = 0;
        g_fake_p12_partial_progress = 1;
        return TRUE;
    }
    if (g_fake_p12_hold_flush)
        return TRUE;
    completed = p12_tx_kind;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    /* In single-step mode, re-arm the hold before driving the completion
     * callback so a same-call re-drive (e.g. WAIT_INVITE_ACK_FLUSH ->
     * NEED_LOCAL_CAPABILITIES -> enqueue -> WAIT_LOCAL_CAPABILITIES_FLUSH)
     * cannot also complete inline; each p12_flush_tx() call then advances
     * exactly one P12 TX slot instead of cascading the whole local chain. */
    if (g_fake_p12_single_step_mode)
        g_fake_p12_hold_flush = 1;
    r54_p12_tx_completed(completed);
    return TRUE;
}

static void r54h_reset_fakes(void)
{
    memset(g_writes, 0, sizeof(g_writes));
    g_write_count = 0u;
    g_media_open_intercepts = 0u;
    g_media_open_should_fail = 0;
    g_fake_p12_hold_flush = 0;
    g_fake_p12_single_step_mode = 0;
    g_fake_enqueue_while_busy = 0;
    g_fake_p12_partial_flush = 0;
    g_fake_p12_partial_progress = 0;
    p12_tx_pending = FALSE;
    p12_tx_kind = P12_TX_NONE;
    g_fake_now_us = 0;
    memset(&g_r35_session, 0, sizeof(g_r35_session));
    memset(&g_r54_call_adoption, 0, sizeof(g_r54_call_adoption));
    g_r54_tx_state = R54_TX_STATE_IDLE;
    g_r54_tx_generation = 0u;
    memset(&g_r54_invite_view, 0, sizeof(g_r54_invite_view));
    memset(&g_r54_pending_peer_view, 0, sizeof(g_r54_pending_peer_view));
    g_r54_pending_peer_capabilities = 0;
    g_r54_pending_peer_capability_word = 0u;
    g_r54_pending_peer_video_requested = 0;
    g_r54_peer_data_ack_enqueued = 0;
    g_r54_peer_data_ack_flushed = 0;
    g_r54_tx_wait_deadline_us = 0;
}

static void r54h_build_call_init(
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

static void r54h_build_peer_capabilities(
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

static int r54h_parse_write(unsigned index, R35CtpEnvelopeView *view)
{
    if (index >= g_write_count) return 0;
    return r35_parse_ctp_envelope(g_writes[index].packet, g_writes[index].len, view);
}

static int r54h_positive(unsigned peer_word)
{
    unsigned char invite[72];
    unsigned char peer_caps[40];
    R35CtpEnvelopeView view;
    int ok;

    r54h_reset_fakes();
    r54h_wire();
    r54h_build_call_init(invite, 0x5234u, 0xfeu, 0xffu);
    ok = r35_capture_call_ctp_id(&g_r35_session, invite, sizeof(invite), 999u)
        && r54_handle_call_init(invite, sizeof(invite));
    if (!ok) return 0;

    r54h_build_peer_capabilities(peer_caps, 0x5234u, 0x60u, 0x22u, peer_word);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &view)
        && r54_handle_peer_capabilities_for_r42(&view);
    if (!ok) return 0;

    return g_write_count == 5u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
        && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0
        && g_media_open_intercepts == 1u
        && g_r54_call_adoption.diag.peer_capability_word == peer_word
        && g_r54_call_adoption.diag.peer_video_requested
        && g_r54_call_adoption.r45.inbound_ack_count == 2u;
}

static int r56h_aggregate_invariants(void)
{
    return g_media_open_intercepts <= 1u && g_fake_enqueue_while_busy == 0;
}

static int r56h_start_invite(unsigned seq, int hold_flush)
{
    unsigned char invite[72];
    r54h_build_call_init(invite, 0x5234u, seq, (seq + 1u) & 0xffu);
    g_fake_p12_hold_flush = hold_flush;
    return r35_capture_call_ctp_id(&g_r35_session, invite, sizeof(invite), 999u)
        && r54_handle_call_init(invite, sizeof(invite));
}

static int r56h_make_peer_caps(R35CtpEnvelopeView *view, unsigned seq)
{
    static unsigned char peer_caps[40];
    r54h_build_peer_capabilities(peer_caps, 0x5234u, seq, 0x22u, 0x0000002fu);
    return r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), view);
}

static int r56h_hold_at_wait_state(R54TxState target)
{
    unsigned guard = 0u;
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    g_fake_p12_single_step_mode = 1;
    if (!r56h_start_invite(0x10u, 1)) {
        g_fake_p12_single_step_mode = 0;
        return 0;
    }
    while (g_r54_tx_state != target && guard++ < 8u) {
        g_fake_p12_hold_flush = 0;
        if (!p12_flush_tx()) {
            g_fake_p12_single_step_mode = 0;
            return 0;
        }
    }
    ok = g_r54_tx_state == target && p12_tx_pending;
    g_fake_p12_single_step_mode = 0;
    return ok;
}

static int r56_busy_wait_serialized(void)
{
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    ok = r56h_start_invite(0x20u, 1)
        && g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH
        && g_r54_call_adoption.diag.call_adoption_failure_stage == R53_STAGE_NONE
        && g_write_count == 1u
        && p12_tx_pending
        && p12_tx_kind == P12_TX_R54_INVITE_ACK
        && g_fake_enqueue_while_busy == 0;
    ok = ok && r54_tx_drive()
        && g_write_count == 1u
        && g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH
        && g_fake_enqueue_while_busy == 0;
    g_fake_p12_hold_flush = 0;
    ok = ok && p12_flush_tx()
        && g_write_count == 3u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
        && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
        && g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES
        && g_media_open_intercepts == 0u
        && r56h_aggregate_invariants();
    return ok;
}

static int r56_partial_write_blocks_next_frame(void)
{
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    g_fake_p12_partial_flush = 1;
    ok = r56h_start_invite(0x30u, 0)
        && g_fake_p12_partial_progress
        && p12_tx_pending
        && p12_tx_kind == P12_TX_R54_INVITE_ACK
        && g_write_count == 1u
        && g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH
        && g_media_open_intercepts == 0u
        && g_fake_enqueue_while_busy == 0;
    ok = ok && p12_flush_tx()
        && g_write_count == 3u
        && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
        && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
        && g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES
        && r56h_aggregate_invariants();
    return ok;
}

static int r56_peer_cap_during_local_tx_stored(void)
{
    R35CtpEnvelopeView view;
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    ok = r56h_start_invite(0x40u, 1)
        && r56h_make_peer_caps(&view, 0x60u)
        && r54_handle_peer_capabilities_for_r42(&view)
        && g_r54_pending_peer_capabilities
        && g_r54_call_adoption.diag.peer_capabilities_seen
        && g_r54_peer_data_ack_enqueued == 0
        && g_media_open_intercepts == 0u
        && g_write_count == 1u;
    g_fake_p12_hold_flush = 0;
    ok = ok && p12_flush_tx()
        && g_write_count == 5u
        && strcmp(g_writes[0].kind, "CALL_INVITE_ACK") == 0
        && strcmp(g_writes[1].kind, "CALL_CAPABILITIES") == 0
        && strcmp(g_writes[2].kind, "CALL_ALERTING") == 0
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0
        && g_r54_peer_data_ack_enqueued
        && g_r54_peer_data_ack_flushed
        && g_media_open_intercepts == 1u
        && r56h_aggregate_invariants();
    return ok;
}

static int r56_duplicate_call_init_no_replay(void)
{
    static const R54TxState waits[] = {
        R54_TX_STATE_WAIT_INVITE_ACK_FLUSH,
        R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH,
        R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH
    };
    unsigned i;
    for (i = 0u; i < sizeof(waits) / sizeof(waits[0]); i++) {
        unsigned before_writes;
        unsigned before_generation;
        R54TxState before_state;
        unsigned char invite[72];
        if (!r56h_hold_at_wait_state(waits[i])) return 0;
        before_writes = g_write_count;
        before_generation = g_r54_tx_generation;
        before_state = g_r54_tx_state;
        r54h_build_call_init(invite, 0x5234u, 0x70u + i, 0x80u + i);
        if (!r54_handle_call_init(invite, sizeof(invite))) return 0;
        if (g_write_count != before_writes ||
            g_r54_tx_generation != before_generation ||
            g_r54_tx_state != before_state ||
            g_fake_enqueue_while_busy != 0 ||
            !r56h_aggregate_invariants()) {
            return 0;
        }
    }
    return 1;
}

static int r56_generation_replaced_no_cross_write(void)
{
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    ok = r56h_start_invite(0x50u, 1)
        && g_write_count == 1u
        && p12_tx_kind == P12_TX_R54_INVITE_ACK;
    g_r35_session.call_generation++;
    g_fake_p12_hold_flush = 0;
    ok = ok && p12_flush_tx()
        && g_write_count == 1u
        && g_media_open_intercepts == 0u
        && g_fake_enqueue_while_busy == 0;
    return ok;
}

static int r56_release_twice_no_double_enqueue(void)
{
    unsigned after_release;
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    ok = r56h_start_invite(0x60u, 1) && g_write_count == 1u;
    g_fake_p12_hold_flush = 0;
    ok = ok && p12_flush_tx();
    after_release = g_write_count;
    r54_p12_tx_completed(P12_TX_R54_INVITE_ACK);
    r54_p12_tx_completed(P12_TX_R54_LOCAL_CAPABILITIES);
    r54_p12_tx_completed(P12_TX_R54_LOCAL_ALERTING);
    ok = ok
        && after_release == 3u
        && g_write_count == after_release
        && g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES
        && r56h_aggregate_invariants();
    return ok;
}

static int r56_early_release_safe(void)
{
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    r54_p12_tx_completed(P12_TX_R54_INVITE_ACK);
    ok = g_write_count == 0u
        && g_r54_tx_state == R54_TX_STATE_IDLE
        && r56h_start_invite(0x68u, 1)
        && g_write_count == 1u;
    r54_p12_tx_completed(P12_TX_R54_INVITE_ACK);
    ok = ok
        && g_write_count == 1u
        && g_fake_enqueue_while_busy == 0
        && g_media_open_intercepts == 0u
        && r56h_aggregate_invariants();
    return ok;
}

static int r56_queue_busy_timeout_fail_closed(void)
{
    int ok;
    r54h_reset_fakes();
    r54h_wire();
    ok = r56h_start_invite(0x80u, 1)
        && g_write_count == 1u
        && g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH;
    g_fake_now_us = ((gint64)P12_STEP_TIMEOUT_SECONDS + 1) * G_USEC_PER_SEC;
    ok = ok
        && !r54_tx_drive()
        && g_r54_tx_state == R54_TX_STATE_TERMINAL_FAILURE
        && g_r54_call_adoption.diag.call_adoption_failure_stage
            == R53_STAGE_TX_WAIT_TIMEOUT
        && g_write_count == 1u
        && g_media_open_intercepts == 0u
        && g_fake_enqueue_while_busy == 0;
    return ok;
}

int main(void)
{
    int overall = 1;
    int ok;
    unsigned before;
    unsigned char invite[72];
    unsigned char peer_caps[40];
    R35CtpEnvelopeView view;

    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;
    (void)r54h_parse_write;

    ok = r54h_positive(0x0000002fu);
    mark("R54_GENERATED_ORDERING", ok);
    mark("R54_PEER_ACK_BEFORE_MEDIA_TRIGGER", ok
        && strcmp(g_writes[3].kind, "CALL_PEER_DATA_ACK") == 0
        && strcmp(g_writes[4].kind, "MEDIA_OPEN") == 0);
    mark("R54_RUNTIME_PEER_WORD", ok
        && g_r54_call_adoption.diag.peer_capability_word == 0x0000002fu);
    if (!ok) overall = 0;

    before = g_write_count;
    ok = !r54_handle_peer_capabilities_for_r42(&view)
        && g_write_count == before
        && g_media_open_intercepts == 1u;
    mark("R54_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN", ok);
    if (!ok) overall = 0;

    r54h_reset_fakes();
    r54h_wire();
    r54h_build_call_init(invite, 0x5234u, 0x10u, 0x20u);
    ok = r35_capture_call_ctp_id(&g_r35_session, invite, sizeof(invite), 999u)
        && r54_handle_call_init(invite, sizeof(invite));
    before = g_write_count;
    r54h_build_peer_capabilities(peer_caps, 0x5234u, 0x21u, 0x22u, 0x00000000u);
    ok = ok
        && r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &view)
        && !r54_handle_peer_capabilities_for_r42(&view)
        && g_write_count == before
        && g_media_open_intercepts == 0u;
    mark("R54_VIDEO_BIT_CLEAR_FAIL_CLOSED", ok);
    if (!ok) overall = 0;

    r54h_build_peer_capabilities(peer_caps, 0x7777u, 0x22u, 0x22u, 0x0000002fu);
    ok = r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &view)
        && !r54_handle_peer_capabilities_for_r42(&view)
        && g_media_open_intercepts == 0u;
    mark("R54_FOREIGN_CONNECTION_REJECTED", ok);
    if (!ok) overall = 0;

    r54h_build_peer_capabilities(peer_caps, 0x5234u, 0x23u, 0x22u, 0x0000002fu);
    peer_caps[7] = 0x04u;
    ok = 1;
    if (r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &view)) {
        ok = !r54_handle_peer_capabilities_for_r42(&view);
    }
    ok = ok && g_media_open_intercepts == 0u;
    mark("R54_MALFORMED_PEER_CAPABILITIES_REJECTED", ok);
    if (!ok) overall = 0;

    r54h_reset_fakes();
    r54h_wire();
    r54h_build_call_init(invite, 0x5234u, 0x30u, 0x40u);
    ok = r35_capture_call_ctp_id(&g_r35_session, invite, sizeof(invite), 999u)
        && r54_handle_call_init(invite, sizeof(invite));
    r54h_build_peer_capabilities(peer_caps, 0x5234u, 0x31u, 0x22u, 0x0000002fu);
    ok = ok && r35_parse_ctp_envelope(peer_caps, sizeof(peer_caps), &view);
    g_media_open_should_fail = 1;
    before = g_write_count;
    ok = ok
        && !r54_handle_peer_capabilities_for_r42(&view)
        && g_write_count == before + 1u
        && strcmp(g_writes[before].kind, "CALL_PEER_DATA_ACK") == 0
        && g_media_open_intercepts == 0u
        && g_r54_call_adoption.diag.call_adoption_failure_stage
            == R53_STAGE_TX_MEDIA_TRIGGER_FAILED;
    mark("R54_WRITE_FAILURE_FAIL_CLOSED", ok);
    if (!ok) overall = 0;

    r54h_reset_fakes();
    r54h_build_call_init(invite, 0x5234u, 0x50u, 0x60u);
    ok = r35_capture_call_ctp_id(&g_r35_session, invite, sizeof(invite), 999u)
        && !r54_handle_call_init(invite, sizeof(invite))
        && g_write_count == 0u
        && g_media_open_intercepts == 0u;
    mark("R54_MISSING_WRITER_FAIL_CLOSED", ok);
    if (!ok) overall = 0;

    ok = r56_busy_wait_serialized();
    mark("R56_BUSY_WAIT_SERIALIZED", ok);
    if (!ok) overall = 0;

    ok = r56_partial_write_blocks_next_frame();
    mark("R56_PARTIAL_WRITE_BLOCKS_NEXT_FRAME", ok);
    if (!ok) overall = 0;

    ok = r56_peer_cap_during_local_tx_stored();
    mark("R56_PEER_CAP_DURING_LOCAL_TX_STORED", ok);
    if (!ok) overall = 0;

    ok = r56_duplicate_call_init_no_replay();
    mark("R56_DUPLICATE_CALL_INIT_NO_REPLAY", ok);
    if (!ok) overall = 0;

    ok = r56_generation_replaced_no_cross_write();
    mark("R56_GENERATION_REPLACED_NO_CROSS_WRITE", ok);
    if (!ok) overall = 0;

    ok = r56_release_twice_no_double_enqueue();
    mark("R56_RELEASE_TWICE_NO_DOUBLE_ENQUEUE", ok);
    if (!ok) overall = 0;

    ok = r56_early_release_safe();
    mark("R56_EARLY_RELEASE_SAFE", ok);
    if (!ok) overall = 0;

    ok = r56_queue_busy_timeout_fail_closed();
    mark("R56_QUEUE_BUSY_TIMEOUT_FAIL_CLOSED", ok);
    if (!ok) overall = 0;

    printf("R56_ENQUEUE_WHILE_BUSY_OBSERVED=%d\n",
        g_fake_enqueue_while_busy_observed);
    printf("R56_SECOND_MEDIA_OPEN_OBSERVED=%u\n",
        g_fake_second_media_open_observed);
    printf("R54_NETWORK_TX=%u\n", g_network_tx);
    printf("R54_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R54_GATE_ACTIONS=%u\n", g_gate_actions);
    printf("R54_HOST_HARNESS_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
