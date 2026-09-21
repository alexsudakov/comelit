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
static unsigned g_network_tx = 0u;
static unsigned g_door_actions = 0u;
static unsigned g_gate_actions = 0u;
static int g_media_open_should_fail = 0;

static R35AttachedMediaSession g_r35_session;

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
    (void)ctx;
    if (!kind || len > R54H_MAX_FRAME || g_write_count >= R54H_MAX_WRITES) return;
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

static void r54h_reset_fakes(void)
{
    memset(g_writes, 0, sizeof(g_writes));
    g_write_count = 0u;
    g_media_open_intercepts = 0u;
    g_media_open_should_fail = 0;
    memset(&g_r35_session, 0, sizeof(g_r35_session));
    memset(&g_r54_call_adoption, 0, sizeof(g_r54_call_adoption));
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
            == R53_STAGE_MEDIA_TRIGGER_REJECTED;
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

    printf("R54_NETWORK_TX=%u\n", g_network_tx);
    printf("R54_DOOR_ACTIONS=%u\n", g_door_actions);
    printf("R54_GATE_ACTIONS=%u\n", g_gate_actions);
    printf("R54_HOST_HARNESS_RESULT=%s\n", overall ? "PASS" : "FAIL");
    return overall ? 0 : 1;
}
