/*
 * P116/R46 post-UAut parser replay harness.
 *
 * This is a host-only finite replay of the bounded VIP frame shape consumed by
 * p12_process_post_uaut(): 00 06 + LE16 body length + LE32 request id + body.
 * It drives the exact extracted R35/R36/R45 cores with synthetic CTP frames and
 * an intercepted writer.  No real transport exists in this executable.
 */

#include <stdio.h>
#include <string.h>

#define REPLAY_CAPTURE_MAX 512u
#define REPLAY_MAX_WRITES  24u
#define REPLAY_MAX_FRAME   64u
#define REPLAY_CTPP_HANDLE 999u

typedef struct {
    char kind[32];
    unsigned char packet[REPLAY_MAX_FRAME];
    unsigned len;
    unsigned sequence;
    unsigned acknowledgement;
} ReplayWrite;

typedef struct {
    R35AttachedMediaSession session;
    R45CallAdoptionState adoption;
    R45RuntimeFields runtime;
    unsigned char capture[REPLAY_CAPTURE_MAX];
    unsigned capture_len;
    unsigned consumed_frames;
    unsigned generic_frames;
    int failed;
} ReplayContext;

static ReplayWrite g_writes[REPLAY_MAX_WRITES];
static unsigned g_write_count = 0u;
static unsigned g_rtp_arm_count = 0u;
static unsigned g_network_tx = 0u;
static unsigned g_door_actions = 0u;
static unsigned g_gate_actions = 0u;

static unsigned read_le16_local(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8);
}

static unsigned read_le32_local(const unsigned char *p)
{
    return (unsigned)p[0]
        | ((unsigned)p[1] << 8)
        | ((unsigned)p[2] << 16)
        | ((unsigned)p[3] << 24);
}

static void write_le16_local(unsigned char *p, unsigned v)
{
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
}

static void write_le32_local(unsigned char *p, unsigned v)
{
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
    p[2] = (unsigned char)((v >> 16) & 0xffu);
    p[3] = (unsigned char)((v >> 24) & 0xffu);
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
    ReplayWrite *w;
    (void)ctx;
    (void)connection;
    if (!kind || !packet || len > REPLAY_MAX_FRAME || g_write_count >= REPLAY_MAX_WRITES) return;
    w = &g_writes[g_write_count++];
    strncpy(w->kind, kind, sizeof(w->kind) - 1u);
    memcpy(w->packet, packet, len);
    w->len = len;
    w->sequence = sequence;
    w->acknowledgement = acknowledgement;
}

static void fake_rtp_hook(void *ctx, int armed)
{
    (void)ctx;
    if (armed) g_rtp_arm_count++;
}

static void replay_init(ReplayContext *ctx)
{
    memset(ctx, 0, sizeof(*ctx));
    ctx->session.writer = fake_writer;
    ctx->session.rtp_arm_hook = fake_rtp_hook;
    ctx->runtime.call_type = 0x49u;
    ctx->runtime.capability_word = 0x12345678u;
    ctx->runtime.alerting_argument = 0u;
}

static void reset_globals(void)
{
    memset(g_writes, 0, sizeof(g_writes));
    g_write_count = 0u;
    g_rtp_arm_count = 0u;
}

static void replay_consume(ReplayContext *ctx, unsigned frame_len)
{
    if (!ctx || frame_len > ctx->capture_len) return;
    if (frame_len < ctx->capture_len) {
        memmove(ctx->capture, ctx->capture + frame_len, ctx->capture_len - frame_len);
    }
    ctx->capture_len -= frame_len;
    ctx->consumed_frames++;
}

static int replay_process(ReplayContext *ctx)
{
    while (1) {
        unsigned body_len;
        unsigned frame_len;
        unsigned request_id;
        const unsigned char *body;
        R35CtpEnvelopeView view;

        if (!ctx || ctx->failed) return 0;
        if (ctx->capture_len < 8u) return 1;
        if (ctx->capture[0] != 0x00u || ctx->capture[1] != 0x06u) {
            ctx->failed = 1;
            return 0;
        }

        body_len = read_le16_local(ctx->capture + 2);
        frame_len = 8u + body_len;
        if (frame_len > REPLAY_CAPTURE_MAX) {
            ctx->failed = 1;
            return 0;
        }
        if (ctx->capture_len < frame_len) return 1;

        request_id = read_le32_local(ctx->capture + 4);
        body = ctx->capture + 8;

        if (request_id == REPLAY_CTPP_HANDLE
            && r35_parse_ctp_envelope(body, body_len, &view)) {
            unsigned opcode = view.inner_len >= 2u
                ? r35_read_be16(view.inner_body)
                : 0xffffu;

            if ((view.flags & R35_CTP_FLAG_SYN_MASK) != 0u
                && opcode == 0x0001u) {
                if (!r35_capture_call_ctp_id(
                        &ctx->session, body, body_len, REPLAY_CTPP_HANDLE)
                    || !r45_send_invite_ack(
                        &ctx->session, &ctx->adoption, &view)
                    || !r45_send_local_capabilities(
                        &ctx->session, &ctx->adoption, &ctx->runtime)
                    || !r45_send_local_alerting(
                        &ctx->session, &ctx->adoption, &ctx->runtime)) {
                    ctx->failed = 1;
                    return 0;
                }
                /* Critical invariant: consume then continue, so an already
                 * buffered follow-up frame is handled in the same invocation. */
                replay_consume(ctx, frame_len);
                continue;
            }

            if (r36_is_capabilities_for_current_call(&ctx->session, &view)) {
                if (!r45_accept_peer_data_and_ack(
                        &ctx->session, &ctx->adoption, &view)) {
                    ctx->failed = 1;
                    return 0;
                }
                if (r36_capabilities_video_requested(&view)) {
                    (void)r36_trigger_open_from_capabilities(&ctx->session, &view);
                }
                replay_consume(ctx, frame_len);
                continue;
            }
        }

        ctx->generic_frames++;
        replay_consume(ctx, frame_len);
    }
}

static int replay_feed(
    ReplayContext *ctx,
    const unsigned char *data,
    unsigned len)
{
    if (!ctx || (!data && len != 0u)) return 0;
    if (len > REPLAY_CAPTURE_MAX - ctx->capture_len) return 0;
    if (len != 0u) {
        memcpy(ctx->capture + ctx->capture_len, data, len);
        ctx->capture_len += len;
    }
    return replay_process(ctx);
}

static unsigned wrap_vip(
    unsigned char *out,
    unsigned capacity,
    unsigned request_id,
    const unsigned char *body,
    unsigned body_len)
{
    unsigned total = 8u + body_len;
    if (!out || !body || total > capacity || body_len > 0xffffu) return 0u;
    memset(out, 0, total);
    out[0] = 0x00u;
    out[1] = 0x06u;
    write_le16_local(out + 2, body_len);
    write_le32_local(out + 4, request_id);
    memcpy(out + 8, body, body_len);
    return total;
}

static void build_call_init(
    unsigned char *out,
    unsigned peer_connection,
    unsigned seq,
    unsigned ack)
{
    memset(out, 0, 72u);
    out[0] = 0xc0u;
    out[1] = 0x18u;
    out[2] = (unsigned char)((peer_connection >> 8) & 0xffu);
    out[3] = (unsigned char)(peer_connection & 0xffu);
    out[4] = (unsigned char)(seq & 0xffu);
    out[5] = (unsigned char)(ack & 0xffu);
    out[6] = 0x00u;
    out[7] = 0x28u;
    out[8] = 0x00u;
    out[9] = 0x01u;
    out[48] = 0xffu; out[49] = 0xffu; out[50] = 0xffu; out[51] = 0xffu;
    memset(out + 52, 0x41, 10u);
    memset(out + 62, 0x42, 10u);
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

static unsigned count_kind(const char *kind)
{
    unsigned i;
    unsigned count = 0u;
    for (i = 0u; i < g_write_count; i++) {
        if (strcmp(g_writes[i].kind, kind) == 0) count++;
    }
    return count;
}

static int test_coalesced(void)
{
    ReplayContext ctx;
    unsigned char invite[72];
    unsigned char caps[40];
    unsigned char frame1[80];
    unsigned char frame2[48];
    unsigned char both[128];
    unsigned n1;
    unsigned n2;
    int ok;

    reset_globals();
    replay_init(&ctx);
    build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    build_peer_capabilities(caps, 0x5234u, 0x60u, 0x7au, 0x3bu);
    n1 = wrap_vip(frame1, sizeof(frame1), REPLAY_CTPP_HANDLE, invite, sizeof(invite));
    n2 = wrap_vip(frame2, sizeof(frame2), REPLAY_CTPP_HANDLE, caps, sizeof(caps));
    memcpy(both, frame1, n1);
    memcpy(both + n1, frame2, n2);

    ok = replay_feed(&ctx, both, n1 + n2)
        && !ctx.failed
        && ctx.capture_len == 0u
        && ctx.consumed_frames == 2u
        && count_kind("CALL_INVITE_ACK") == 1u
        && count_kind("CALL_CAPABILITIES") == 1u
        && count_kind("CALL_ALERTING") == 1u
        && count_kind("CALL_PEER_DATA_ACK") == 1u
        && count_kind("MEDIA_OPEN") == 1u
        && ctx.session.open_count == 1u
        && ctx.session.call_ack == 0x61u
        && g_rtp_arm_count == 1u;
    printf("R46_COALESCED_CALL_INIT_AND_CAPABILITIES=%s\n", ok ? "PASS" : "FAIL");
    return ok;
}

static int test_fragmented(void)
{
    ReplayContext ctx;
    unsigned char invite[72];
    unsigned char caps[40];
    unsigned char frame1[80];
    unsigned char frame2[48];
    unsigned n1;
    unsigned n2;
    unsigned writes_after_invite;
    int ok;

    reset_globals();
    replay_init(&ctx);
    build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    build_peer_capabilities(caps, 0x5234u, 0x60u, 0x7au, 0x3bu);
    n1 = wrap_vip(frame1, sizeof(frame1), REPLAY_CTPP_HANDLE, invite, sizeof(invite));
    n2 = wrap_vip(frame2, sizeof(frame2), REPLAY_CTPP_HANDLE, caps, sizeof(caps));

    ok = replay_feed(&ctx, frame1, 7u)
        && g_write_count == 0u
        && ctx.capture_len == 7u;
    if (!ok) {
        printf("R46_FRAGMENTED_FRAME_REASSEMBLY=FAIL\n");
        return 0;
    }

    ok = replay_feed(&ctx, frame1 + 7u, n1 - 7u)
        && ctx.consumed_frames == 1u
        && count_kind("CALL_INVITE_ACK") == 1u
        && count_kind("CALL_CAPABILITIES") == 1u
        && count_kind("CALL_ALERTING") == 1u;
    writes_after_invite = g_write_count;

    ok = ok
        && replay_feed(&ctx, frame2, 13u)
        && g_write_count == writes_after_invite
        && ctx.capture_len == 13u
        && replay_feed(&ctx, frame2 + 13u, n2 - 13u)
        && ctx.capture_len == 0u
        && ctx.consumed_frames == 2u
        && count_kind("CALL_PEER_DATA_ACK") == 1u
        && count_kind("MEDIA_OPEN") == 1u;
    printf("R46_FRAGMENTED_FRAME_REASSEMBLY=%s\n", ok ? "PASS" : "FAIL");
    return ok;
}

static int test_unrelated_request_id(void)
{
    ReplayContext ctx;
    unsigned char invite[72];
    unsigned char frame[80];
    unsigned n;
    int ok;

    reset_globals();
    replay_init(&ctx);
    build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    n = wrap_vip(frame, sizeof(frame), 123u, invite, sizeof(invite));
    ok = replay_feed(&ctx, frame, n)
        && ctx.generic_frames == 1u
        && ctx.consumed_frames == 1u
        && g_write_count == 0u
        && ctx.session.call_generation == 0u;
    printf("R46_UNRELATED_REQUEST_ID_NO_SIGNALING=%s\n", ok ? "PASS" : "FAIL");
    return ok;
}

static int test_malformed_outer_header(void)
{
    ReplayContext ctx;
    unsigned char bad[8] = {0x01u, 0x06u, 0, 0, 0, 0, 0, 0};
    int ok;
    reset_globals();
    replay_init(&ctx);
    ok = !replay_feed(&ctx, bad, sizeof(bad))
        && ctx.failed
        && g_write_count == 0u;
    printf("R46_MALFORMED_OUTER_HEADER_FAILS_CLOSED=%s\n", ok ? "PASS" : "FAIL");
    return ok;
}

static int test_duplicate_peer_capabilities(void)
{
    ReplayContext ctx;
    unsigned char invite[72];
    unsigned char caps[40];
    unsigned char frames[176];
    unsigned n = 0u;
    unsigned one;
    int ok;

    reset_globals();
    replay_init(&ctx);
    build_call_init(invite, 0x5234u, 0x56u, 0x78u);
    build_peer_capabilities(caps, 0x5234u, 0x60u, 0x7au, 0x3bu);
    one = wrap_vip(frames + n, sizeof(frames) - n, REPLAY_CTPP_HANDLE, invite, sizeof(invite));
    n += one;
    one = wrap_vip(frames + n, sizeof(frames) - n, REPLAY_CTPP_HANDLE, caps, sizeof(caps));
    n += one;
    one = wrap_vip(frames + n, sizeof(frames) - n, REPLAY_CTPP_HANDLE, caps, sizeof(caps));
    n += one;

    ok = replay_feed(&ctx, frames, n)
        && !ctx.failed
        && ctx.consumed_frames == 3u
        && count_kind("MEDIA_OPEN") == 1u
        && count_kind("CALL_PEER_DATA_ACK") == 2u
        && ctx.session.open_count == 1u;
    printf("R46_DUPLICATE_PEER_CAP_NO_SECOND_OPEN=%s\n", ok ? "PASS" : "FAIL");
    return ok;
}

int main(void)
{
    int overall = 1;
    (void)R35_SECOND_OPEN_FORBIDDEN_STATES;

    if (!test_coalesced()) overall = 0;
    if (!test_fragmented()) overall = 0;
    if (!test_unrelated_request_id()) overall = 0;
    if (!test_malformed_outer_header()) overall = 0;
    if (!test_duplicate_peer_capabilities()) overall = 0;

    printf("R46_NETWORK_TX=%u\n", g_network_tx);
    printf("R46_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R46_GATE_ACTIONS=%u\n", g_gate_actions);
    printf("R46_PARSER_REPLAY_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
