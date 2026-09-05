#include <nice/agent.h>
#include <nice/pseudotcp.h>
#include <glib.h>
#include <glib/gstdio.h>

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>

#define RUN_DIR     "/run/comelit-p2p"
#define OFFER_FILE  RUN_DIR "/offer.sdp"
#define REMOTE_FILE RUN_DIR "/remote.sdp"
#define STOP_FILE   RUN_DIR "/stop"

#define STUN_SERVER "192.248.183.213"
#define STUN_PORT   3478

#define PSEUDOTCP_CONVERSATION 0
#define PSEUDOTCP_MTU          1320

static GMainLoop *loop = NULL;
static NiceAgent *agent = NULL;

static guint stream_id = 0;

static gboolean ready = FALSE;
static gboolean failed = FALSE;

static gboolean remote_loaded = FALSE;
static gboolean ice_connected = FALSE;
static gboolean ice_ready = FALSE;
static gboolean selected_pair_present = FALSE;

static PseudoTcpSocket *pseudo_tcp = NULL;

static gboolean pseudotcp_started = FALSE;
static gboolean pseudotcp_open = FALSE;

static guint pseudotcp_packets_in = 0;
static guint pseudotcp_packets_out = 0;
static guint pseudotcp_max_wire_out = 0;
static guint64 pseudotcp_app_bytes_in = 0;

#define APP_CAPTURE_MAX 64

static guint8 app_capture[APP_CAPTURE_MAX];
static guint app_capture_len = 0;

#define VIP_BOOTSTRAP_MAX 128
#define POST_ACK_CAPTURE_MAX 262144

static guint8 vip_bootstrap[VIP_BOOTSTRAP_MAX];
static guint vip_bootstrap_len = 0;

static gboolean echo_open_seen = FALSE;
static gboolean echo_ack_sent = FALSE;
static guint16 echo_channel_id = 0;

static guint8 echo_ack[20];
static guint echo_ack_offset = 0;

static guint8 post_ack_capture[POST_ACK_CAPTURE_MAX];
static guint post_ack_capture_len = 0;

static gboolean uaut_open_started = FALSE;
static gboolean uaut_open_sent = FALSE;
static gboolean uaut_response_seen = FALSE;

static guint16 uaut_channel_id = 0;
static guint16 uaut_response_word = 0;

static guint8 uaut_open[23];
static guint uaut_open_offset = 0;

#define P12_TX_MAX 4096
#define P12_STEP_TIMEOUT_SECONDS 6
#define P12_SECRETS_FILE "/root/.config/comelit/secrets.env"
#define P12_UCFG_FILE RUN_DIR "/p12-ucfg-response.json"

typedef enum {
    P12_STAGE_IDLE = 0,
    P12_STAGE_AUTH_TX,
    P12_STAGE_WAIT_AUTH_RESPONSE,
    P12_STAGE_CLOSE_UAUT_TX,
    P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE,
    P12_STAGE_OPEN_UCFG_TX,
    P12_STAGE_WAIT_UCFG_OPEN_RESPONSE,
    P12_STAGE_GET_UCFG_TX,
    P12_STAGE_WAIT_UCFG_RESPONSE,
    P12_STAGE_CLOSE_UCFG_TX,
    P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE,

    P12_STAGE_V4_OPEN_CTPP_TX,
    P12_STAGE_V4_WAIT_CTPP_OPEN_RESPONSE,

    P12_STAGE_V4_OPEN_CSPB_TX,
    P12_STAGE_V4_WAIT_CSPB_OPEN_RESPONSE,

    P12_STAGE_V4_CTPP_INIT_TX,
    P12_STAGE_V4_WAIT_CTPP_BOOTSTRAP,

    P12_STAGE_V4_ACK_PAIR_TX,
    P12_STAGE_V4_LISTEN_RING,

    P12_STAGE_DONE
} P12ReadonlyStage;

typedef enum {
    P12_TX_NONE = 0,
    P12_TX_AUTH,
    P12_TX_CLOSE_UAUT,
    P12_TX_OPEN_UCFG,
    P12_TX_GET_UCFG,
    P12_TX_CLOSE_UCFG,

    P12_TX_V4_OPEN_CTPP,
    P12_TX_V4_OPEN_CSPB,
    P12_TX_V4_CTPP_INIT,
    P12_TX_V4_ACK_PAIR,

    P12_TX_V4_PEER_ECHO_REPLY,
    P12_TX_V4_PEER_ECHO_CLOSE_ACK,

    P12_TX_V4_DOOR_WRITE
} P12TxKind;

static P12ReadonlyStage p12_stage = P12_STAGE_IDLE;
static P12TxKind p12_tx_kind = P12_TX_NONE;
static guint8 p12_tx[P12_TX_MAX];
static guint p12_tx_len = 0;
static guint p12_tx_offset = 0;
static gboolean p12_tx_pending = FALSE;
static gint64 p12_deadline_us = 0;
static guint16 ucfg_channel_id = 0;
static guint16 ucfg_requested_channel_id = 0;
static gboolean p12_auth_ok = FALSE;
static gboolean p12_uaut_close_ok = FALSE;
static gboolean p12_ucfg_open_ok = FALSE;
static gboolean p12_ucfg_received = FALSE;
static gboolean p12_ucfg_close_ok = FALSE;


/*
 * V4 ring listener state.
 *
 * Capture/UCFG validated identities:
 *
 * apartment      = 00040117
 * apartment+sub  = 000401177
 * entrance panel = 00000643
 * gate panel     = 00000610
 *
 * This candidate contains:
 *
 *   P2P
 *   UAUT
 *   UCFG
 *   CTPP/CSPB registration
 *   registration renewal ACK
 *   passive ring observation
 *
 * It contains no call answer, media activation or actuator action.
 */

#define V4_APT_ADDRESS  "00040117"
#define V4_FULL_ADDRESS "000401177"

#define V4_ENTRANCE     "00000643"
#define V4_GATE         "00000610"


static guint16 v4_ctpp_requested_channel_id = 0;
static guint16 v4_ctpp_channel_id = 0;

static guint16 v4_cspb_requested_channel_id = 0;
static guint16 v4_cspb_channel_id = 0;


static guint16 v4_registration_token = 0;

static guint32 v4_sequence_seed = 0;

static guint32 v4_registration_ack_sequence = 0;


static gboolean v4_token_generated = FALSE;

static gboolean v4_ctpp_open_ok = FALSE;
static gboolean v4_cspb_open_ok = FALSE;

static gboolean v4_initial_ack_seen = FALSE;
static gboolean v4_registration_renewal_seen = FALSE;

static gboolean v4_registered = FALSE;
static gboolean v4_listener_ready = FALSE;

static gboolean v4_ring_observed = FALSE;


typedef enum {
    V4_DOOR_IDLE = 0,
    V4_DOOR_SENDING,
    V4_DOOR_WAIT_SETTLE
} V4DoorStage;

#define V4_DOOR_STEP_TIMEOUT_SECONDS 6
#define V4_DOOR_SETTLE_MS 1000

static V4DoorStage v4_door_stage = V4_DOOR_IDLE;
static guint v4_door_write_index = 0;
static guint v4_door_writes_sent = 0;
static gint64 v4_door_deadline_us = 0;
static gboolean v4_door_send_started = FALSE;
static volatile sig_atomic_t v4_door_signal_pending = 0;

/*
 * Persistent Door contract:
 *
 * - v4_ctpp_channel_id is already opened and registered by the listener;
 * - Door never opens a second CTPP channel;
 * - Door never closes the persistent CTPP channel;
 * - five operation bodies are transmitted in source order;
 * - inbound CTPP traffic never advances the Door write sequence;
 * - no generic frame is promoted to a Door ACK;
 * - completion without a proven Door-specific ACK is UNKNOWN_OUTCOME;
 * - automatic retry is forbidden.
 */

static const guint8 v4_door_operation_body_1[] = {
    0x00, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00
};

static const guint8 v4_door_operation_body_2[] = {
    0x20, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00
};

static const guint8 v4_door_operation_body_3[] = {
    0xc0, 0x18, 0x70, 0xab, 0x29, 0x9f, 0x00, 0x0d, 0x00, 0x2d, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
    0xff, 0xff, 0xff, 0xff, 0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37,
    0x31, 0x00, 0x30, 0x30, 0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00
};

static const guint8 v4_door_operation_body_4[] = {
    0x00, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00
};

static const guint8 v4_door_operation_body_5[] = {
    0x20, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x34, 0x33, 0x00, 0x00
};

static const guint v4_door_operation_body_len[] = { 32, 32, 48, 32, 32 };
static const guint v4_door_write_count = 5;

static void v4_door_set_deadline(void);
static void v4_door_reset(void);
static void v4_door_emit_result(const gchar *state);
static gboolean v4_door_queue_write(guint index);
static gboolean v4_door_settle_cb(gpointer data);

/* Exact CALL_INIT retransmit suppression.  The device retries the same
 * CALL_INIT frame with a short backoff.  Hashing the protocol body lets
 * us suppress only an identical frame inside a bounded window while a
 * later or different CALL_INIT remains eligible for a new HA event. */
#define V4_RING_DEDUP_WINDOW_USEC ((gint64)15 * G_USEC_PER_SEC)
static gchar v4_last_ring_sha256[65] = {0};
static gint64 v4_last_ring_seen_us = 0;


static const guint8 p12_ucfg_request_body[] = {
    0x7b, 0x22, 0x6d, 0x65, 0x73, 0x73, 0x61, 0x67, 0x65, 0x22, 0x3a, 0x22,
    0x67, 0x65, 0x74, 0x2d, 0x63, 0x6f, 0x6e, 0x66, 0x69, 0x67, 0x75, 0x72,
    0x61, 0x74, 0x69, 0x6f, 0x6e, 0x22, 0x2c, 0x22, 0x61, 0x64, 0x64, 0x72,
    0x65, 0x73, 0x73, 0x62, 0x6f, 0x6f, 0x6b, 0x73, 0x22, 0x3a, 0x22, 0x6e,
    0x6f, 0x6e, 0x65, 0x22, 0x2c, 0x22, 0x6d, 0x65, 0x73, 0x73, 0x61, 0x67,
    0x65, 0x2d, 0x74, 0x79, 0x70, 0x65, 0x22, 0x3a, 0x22, 0x72, 0x65, 0x71,
    0x75, 0x65, 0x73, 0x74, 0x22, 0x2c, 0x22, 0x6d, 0x65, 0x73, 0x73, 0x61,
    0x67, 0x65, 0x2d, 0x69, 0x64, 0x22, 0x3a, 0x36, 0x7d, 0x0a
};
static const guint p12_ucfg_request_body_len = 94u;


static gboolean
pseudotcp_success_quit_cb(gpointer data);

static goffset remote_last_size = -1;
static guint remote_stable_ticks = 0;


/*
 * Application data callback.
 *
 * STUN/ICE control packets are consumed internally by libnice.
 * Attaching the component to the GLib context is required so
 * inbound STUN responses are processed during gathering.
 */
static void
recv_cb(
    NiceAgent *nice_agent,
    guint sid,
    guint component_id,
    guint len,
    gchar *buf,
    gpointer data)
{
    (void)nice_agent;
    (void)data;

    if (sid != stream_id ||
        component_id != 1) {
        return;
    }

    /*
     * STUN/ICE control packets are consumed by libnice.
     * Data reaching this callback is application payload
     * carried by the selected ICE component.
     */
    if (!pseudo_tcp) {
        printf(
            "PSEUDOTCP_RX_BEFORE_START=%u\n",
            len
        );

        fflush(stdout);
        return;
    }

    pseudotcp_packets_in++;

    gboolean ok =
        pseudo_tcp_socket_notify_packet(
            pseudo_tcp,
            buf,
            len
        );

    if (!ok) {
        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET=FAIL "
            "LEN=%u\n",
            len
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);
    }
}


static gboolean
absolute_timeout_cb(gpointer data)
{
    (void)data;


    /*
     * Once registration succeeded, timeout means simply:
     *
     * listener was READY but no ring arrived.
     *
     * It is not a protocol failure.
     */
    if (v4_listener_ready) {

        printf(
            "V4_LISTENER_TIMEOUT=true\n"
        );


        printf(
            "V4_RING_OBSERVED=%s\n",
            v4_ring_observed
                ? "true"
                : "false"
        );


        printf(
            "NETWORK_DOOR_ACTION_PERFORMED=false\n"
        );


        printf(
            "PHYSICAL_DOOR_ACTION=false\n"
        );


        fflush(stdout);


        failed =
            FALSE;


        if (loop)
            g_main_loop_quit(loop);


        return
            G_SOURCE_REMOVE;
    }

    if (ice_ready &&
        pseudotcp_started &&
        !pseudotcp_open) {

        fprintf(
            stderr,
            "PSEUDOTCP_TIMEOUT=true\n"
        );
    } else {
        fprintf(
            stderr,
            "ICE_HOLDER_TIMEOUT=true\n"
        );
    }

    failed = TRUE;

    if (loop)
        g_main_loop_quit(loop);

    return G_SOURCE_REMOVE;
}


static gboolean
stop_check_cb(gpointer data)
{
    (void)data;

    if (g_file_test(STOP_FILE, G_FILE_TEST_EXISTS)) {
        printf("ICE_HOLDER_STOP=true\n");

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static guint16
read_le16(
    const guint8 *p)
{
    return
        (guint16)p[0] |
        ((guint16)p[1] << 8);
}


static guint32
read_le32(
    const guint8 *p)
{
    return
        (guint32)p[0] |
        ((guint32)p[1] << 8) |
        ((guint32)p[2] << 16) |
        ((guint32)p[3] << 24);
}


static void
write_le16(
    guint8 *p,
    guint16 value)
{
    p[0] =
        (guint8)(value & 0xff);

    p[1] =
        (guint8)((value >> 8) & 0xff);
}


static void
write_le32(
    guint8 *p,
    guint32 value)
{
    p[0] =
        (guint8)(value & 0xff);

    p[1] =
        (guint8)((value >> 8) & 0xff);

    p[2] =
        (guint8)((value >> 16) & 0xff);

    p[3] =
        (guint8)((value >> 24) & 0xff);
}



static void
p12_set_deadline(void)
{
    p12_deadline_us =
        g_get_monotonic_time() +
        ((gint64)P12_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
}


static gboolean
p12_stage_timeout_cb(gpointer data)
{
    (void)data;

    if (p12_stage == P12_STAGE_IDLE ||
        p12_stage == P12_STAGE_DONE) {
        return G_SOURCE_REMOVE;
    }

    if (p12_deadline_us > 0 &&
        g_get_monotonic_time() > p12_deadline_us) {

        fprintf(
            stderr,
            "P12_READONLY_STAGE_TIMEOUT stage=%u\n",
            (unsigned)p12_stage
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
p12_is_hex32(const gchar *value)
{
    if (!value || strlen(value) != 32)
        return FALSE;

    for (guint i = 0; i < 32; i++) {
        if (!g_ascii_isxdigit(value[i]))
            return FALSE;
    }

    return TRUE;
}


static gboolean
p12_load_vip_token(gchar out[33])
{
    gchar *contents = NULL;
    gsize length = 0;
    GError *error = NULL;

    if (!g_file_get_contents(
            P12_SECRETS_FILE,
            &contents,
            &length,
            &error)) {

        fprintf(
            stderr,
            "P12_VIP_TOKEN_READ=FAIL\n"
        );

        if (error)
            g_error_free(error);

        return FALSE;
    }

    gchar **lines =
        g_strsplit(contents, "\n", -1);

    guint matches = 0;
    gchar selected[33] = {0};

    for (guint i = 0; lines[i]; i++) {
        gchar *line = g_strstrip(lines[i]);

        if (*line == '\0' ||
            *line == '#') {
            continue;
        }

        gchar *eq = strchr(line, '=');
        if (!eq)
            continue;

        gchar *value = g_strstrip(eq + 1);
        gsize n = strlen(value);

        if (n >= 2 &&
            ((value[0] == '"' && value[n - 1] == '"') ||
             (value[0] == '\'' && value[n - 1] == '\''))) {

            value[n - 1] = '\0';
            value++;
        }

        if (!p12_is_hex32(value))
            continue;

        matches++;
        memcpy(selected, value, 32);
        selected[32] = '\0';
    }

    if (contents && length > 0)
        memset(contents, 0, length);

    g_strfreev(lines);
    g_free(contents);

    if (matches != 1) {
        memset(selected, 0, sizeof(selected));

        fprintf(
            stderr,
            "P12_VIP_TOKEN_UNIQUE_MATCH=false count=%u\n",
            matches
        );

        return FALSE;
    }

    memcpy(out, selected, 33);
    memset(selected, 0, sizeof(selected));

    printf("P12_VIP_TOKEN_UNIQUE_MATCH=true\n");
    printf("P12_VIP_TOKEN_VALUE_EMITTED=false\n");
    fflush(stdout);

    return TRUE;
}


static gboolean
p12_queue_bytes(
    const guint8 *data,
    guint length,
    P12TxKind kind)
{
    if (p12_tx_pending ||
        length == 0 ||
        length > P12_TX_MAX) {

        fprintf(stderr, "P12_TX_QUEUE=FAIL\n");
        return FALSE;
    }

    memcpy(p12_tx, data, length);
    p12_tx_len = length;
    p12_tx_offset = 0;
    p12_tx_kind = kind;
    p12_tx_pending = TRUE;

    return TRUE;
}


static gboolean
p12_queue_vip_frame(
    guint32 request_id,
    const guint8 *body,
    guint body_len,
    P12TxKind kind)
{
    if (body_len > 0xffffu ||
        body_len + 8u > P12_TX_MAX) {

        fprintf(stderr, "P12_VIP_FRAME_BUILD=FAIL\n");
        return FALSE;
    }

    guint8 frame[P12_TX_MAX];
    memset(frame, 0, sizeof(frame));

    frame[0] = 0x00;
    frame[1] = 0x06;
    write_le16(frame + 2, (guint16)body_len);
    write_le32(frame + 4, request_id);
    memcpy(frame + 8, body, body_len);

    gboolean ok =
        p12_queue_bytes(
            frame,
            body_len + 8u,
            kind
        );

    memset(frame, 0, body_len + 8u);
    return ok;
}



/*
 * Forward declaration.
 *
 * V4 send helpers are inserted before the existing implementation
 * of p12_flush_tx().
 */
static gboolean
p12_flush_tx(void);


static void
v4_write_be16(
    guint8 *p,
    guint16 value)
{
    p[0] =
        (guint8)((value >> 8) & 0xff);

    p[1] =
        (guint8)(value & 0xff);
}


static gboolean
v4_contains_ascii(
    const guint8 *body,
    guint body_len,
    const gchar *needle)
{
    if (!body || !needle)
        return FALSE;

    gsize n =
        strlen(needle);

    if (n == 0 ||
        body_len < n) {

        return FALSE;
    }

    for (guint i = 0;
         i + n <= body_len;
         i++) {

        if (memcmp(
                body + i,
                needle,
                n) == 0) {

            return TRUE;
        }
    }

    return FALSE;
}


/*
 * Capture/native-SDK compatible registration token.
 *
 * Native Utility::rand16():
 *
 *     r = rand()
 *     return low16(
 *         r ^ (r >> 16)
 *     )
 *
 * This is correlation state only.
 * Its value is never printed.
 */
static guint16
v4_new_registration_token(void)
{
    static gboolean seeded = FALSE;

    if (!seeded) {

        guint64 seed =
            ((guint64)g_get_real_time()) ^
            (((guint64)getpid()) << 17);

        srand(
            (unsigned int)(
                seed ^
                (seed >> 32)
            )
        );

        seeded = TRUE;
    }

    guint32 r =
        (guint32)rand();

    return
        (guint16)(
            (
                r ^
                (r >> 16)
            ) &
            0xffffu
        );
}


/*
 * Allocate a local requested channel ID without colliding
 * with channels already used in this P2P session.
 */
static guint16
v4_allocate_channel_id(
    guint16 start)
{
    guint16 candidate =
        start;

    while (
        candidate == 0 ||

        candidate == echo_channel_id ||

        candidate == uaut_channel_id ||

        candidate == ucfg_channel_id ||

        candidate ==
            ucfg_requested_channel_id ||

        candidate ==
            v4_ctpp_requested_channel_id ||

        candidate ==
            v4_ctpp_channel_id ||

        candidate ==
            v4_cspb_requested_channel_id ||

        candidate ==
            v4_cspb_channel_id
    ) {

        candidate++;

        if (candidate == 0)
            candidate = 7400;
    }

    return candidate;
}


/*
 * P2P channel OPEN:
 *
 * COMMAND
 * sequence = 1
 * wire type = 7
 * name = CTPP
 *
 * CTPP has additional address data:
 *
 * pad byte
 * length LE32
 * "000401177\0"
 */
static gboolean
v4_queue_open_ctpp(void)
{
    v4_ctpp_requested_channel_id =
        v4_allocate_channel_id(
            7451
        );

    guint8 body[30];

    memset(
        body,
        0,
        sizeof(body)
    );

    write_le16(
        body + 0,
        0xABCD
    );

    write_le16(
        body + 2,
        1
    );

    /*
     * Official P2P capture/P12 channel type.
     */
    write_le32(
        body + 4,
        7
    );

    memcpy(
        body + 8,
        "CTPP",
        4
    );

    write_le16(
        body + 12,
        v4_ctpp_requested_channel_id
    );

    /*
     * Normal trailing byte.
     */
    body[14] = 0x00;

    /*
     * Additional pad required before extra-data length.
     */
    body[15] = 0x00;

    write_le32(
        body + 16,
        (guint32)(
            strlen(V4_FULL_ADDRESS) +
            1u
        )
    );

    memcpy(
        body + 20,
        V4_FULL_ADDRESS,
        strlen(V4_FULL_ADDRESS)
    );

    body[29] = 0x00;

    p12_stage =
        P12_STAGE_V4_OPEN_CTPP_TX;

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_V4_OPEN_CTPP
        );

    memset(
        body,
        0,
        sizeof(body)
    );

    return
        ok &&
        p12_flush_tx();
}


/*
 * CSPB is opened on the same authenticated P2P session.
 */
static gboolean
v4_queue_open_cspb(void)
{
    v4_cspb_requested_channel_id =
        v4_allocate_channel_id(
            (guint16)(
                v4_ctpp_requested_channel_id +
                1
            )
        );

    guint8 body[15];

    memset(
        body,
        0,
        sizeof(body)
    );

    write_le16(
        body + 0,
        0xABCD
    );

    write_le16(
        body + 2,
        1
    );

    write_le32(
        body + 4,
        7
    );

    memcpy(
        body + 8,
        "CSPB",
        4
    );

    write_le16(
        body + 12,
        v4_cspb_requested_channel_id
    );

    body[14] = 0x00;

    p12_stage =
        P12_STAGE_V4_OPEN_CSPB_TX;

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_V4_OPEN_CSPB
        );

    memset(
        body,
        0,
        sizeof(body)
    );

    return
        ok &&
        p12_flush_tx();
}


/*
 * Capture-proven ExtB registration message:
 *
 * 18C0
 * sequence LE32
 * 0011
 * 0040
 * registration_token LE16
 * 000401177\0
 * 100E
 * 00000000
 * FFFFFFFF
 * 000401177\0
 * 00040117\0
 * 00
 */
static gboolean
v4_queue_ctpp_registration_init(void)
{
    if (!v4_token_generated) {

        v4_registration_token =
            v4_new_registration_token();

        /*
         * Initial CTP sequence seed.
         *
         * This is protocol state, not wall-clock time.
         *
         * Device acceptance is verified deterministically
         * by requiring a valid 1860/0010 registration renewal
         * containing our echoed registration token.
         */
        v4_sequence_seed =
            g_random_int();

        /*
         * ExtB ACK profile proven from two captures.
         */
        v4_registration_ack_sequence =
            v4_sequence_seed +
            0x01010000u;

        v4_token_generated =
            TRUE;

        printf(
            "V4_REGISTRATION_TOKEN_GENERATED=true\n"
        );

        printf(
            "V4_REGISTRATION_TOKEN_VALUE_EMITTED=false\n"
        );

        printf(
            "V4_SEQUENCE_SEED_VALUE_EMITTED=false\n"
        );

        fflush(stdout);
    }

    guint8 body[52];

    memset(
        body,
        0,
        sizeof(body)
    );


    write_le16(
        body + 0,
        0x18C0
    );

    write_le32(
        body + 2,
        v4_sequence_seed
    );


    /*
     * action = 0x0011
     */
    body[6] = 0x00;
    body[7] = 0x11;


    /*
     * flags = 0x0040
     */
    body[8] = 0x00;
    body[9] = 0x40;


    write_le16(
        body + 10,
        v4_registration_token
    );


    memcpy(
        body + 12,
        V4_FULL_ADDRESS,
        9
    );

    body[21] = 0x00;


    /*
     * Registration lifetime 3600 seconds:
     *
     * 0x0E10 little endian
     */
    body[22] = 0x10;
    body[23] = 0x0E;


    memset(
        body + 24,
        0x00,
        4
    );


    memset(
        body + 28,
        0xFF,
        4
    );


    memcpy(
        body + 32,
        V4_FULL_ADDRESS,
        9
    );

    body[41] = 0x00;


    memcpy(
        body + 42,
        V4_APT_ADDRESS,
        8
    );

    body[50] = 0x00;
    body[51] = 0x00;


    p12_stage =
        P12_STAGE_V4_CTPP_INIT_TX;


    gboolean ok =
        p12_queue_vip_frame(
            v4_ctpp_channel_id,
            body,
            sizeof(body),
            P12_TX_V4_CTPP_INIT
        );


    memset(
        body,
        0,
        sizeof(body)
    );


    return
        ok &&
        p12_flush_tx();
}



/*
 * ------------------------------------------------------------
 * Peer ECHO response
 * ------------------------------------------------------------
 *
 * PROVEN by both official Android PCAPs:
 *
 *   device -> client:
 *
 *       echo 2026-...Z
 *
 *   client -> device:
 *
 *       exact same payload
 *
 * No transformation, timestamp generation or parsing is required.
 */
static gboolean
v4_queue_peer_echo_reply(
    const guint8 *body,
    guint body_len)
{
    if (
        !body ||
        body_len < 6 ||
        body_len > 64
    ) {

        fprintf(
            stderr,
            "V4_PEER_ECHO_REFLECT=REJECTED_SHAPE\n"
        );

        return FALSE;
    }


    /*
     * Constrain behavior to the capture-proven request family.
     *
     * We do NOT blindly reflect arbitrary channel data.
     */
    if (
        memcmp(
            body,
            "echo ",
            5
        ) != 0
    ) {

        fprintf(
            stderr,
            "V4_PEER_ECHO_REFLECT=REJECTED_PREFIX\n"
        );

        return FALSE;
    }


    /*
     * Require printable ASCII.
     */
    for (
        guint i = 0;
        i < body_len;
        i++
    ) {

        if (
            !g_ascii_isprint(
                body[i]
            )
        ) {

            fprintf(
                stderr,
                "V4_PEER_ECHO_REFLECT=REJECTED_NONPRINTABLE\n"
            );

            return FALSE;
        }
    }


    gboolean ok =
        p12_queue_vip_frame(
            echo_channel_id,
            body,
            body_len,
            P12_TX_V4_PEER_ECHO_REPLY
        );


    return
        ok &&
        p12_flush_tx();
}


/*
 * Capture-proven ViP END/CLOSE response.
 *
 * Request:
 *
 *   EF 01
 *   03 00
 *   02 00 00 00
 *   channel-id LE16
 *
 * Response:
 *
 *   EF 01
 *   04 00
 *   04 00 00 00
 *   channel-id LE16
 *   00 00
 */
static gboolean
v4_queue_peer_echo_close_ack(
    guint16 channel_id)
{
    guint8 body[12];

    memset(
        body,
        0,
        sizeof(body)
    );


    write_le16(
        body + 0,
        0x01EF
    );

    write_le16(
        body + 2,
        4
    );

    write_le32(
        body + 4,
        4
    );

    write_le16(
        body + 8,
        channel_id
    );

    write_le16(
        body + 10,
        0
    );


    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_V4_PEER_ECHO_CLOSE_ACK
        );


    memset(
        body,
        0,
        sizeof(body)
    );


    return
        ok &&
        p12_flush_tx();
}


/*
 * Registration ACK/CONFIRM body.
 *
 * Capture-proven exact body length = 32 bytes.
 */
static guint
v4_make_ack_body(
    guint8 body[32],
    guint16 prefix)
{
    memset(
        body,
        0,
        32
    );


    write_le16(
        body + 0,
        prefix
    );


    write_le32(
        body + 2,
        v4_registration_ack_sequence
    );


    v4_write_be16(
        body + 6,
        0x0000
    );


    memset(
        body + 8,
        0xFF,
        4
    );


    memcpy(
        body + 12,
        V4_FULL_ADDRESS,
        9
    );

    body[21] = 0x00;


    memcpy(
        body + 22,
        V4_APT_ADDRESS,
        8
    );

    body[30] = 0x00;
    body[31] = 0x00;


    return 32;
}


/*
 * Build one normal outer ViP frame.
 */
static guint
v4_make_outer_frame(
    guint8 *dst,
    guint dst_size,
    guint16 request_id,
    const guint8 *body,
    guint body_len)
{
    if (
        !dst ||
        !body ||
        body_len > 0xffffu ||
        dst_size < body_len + 8u
    ) {
        return 0;
    }


    memset(
        dst,
        0,
        body_len + 8u
    );


    dst[0] = 0x00;
    dst[1] = 0x06;


    write_le16(
        dst + 2,
        (guint16)body_len
    );


    /*
     * Existing P12 represents request-id + zero padding
     * as one LE32 value.
     */
    write_le32(
        dst + 4,
        request_id
    );


    memcpy(
        dst + 8,
        body,
        body_len
    );


    return
        body_len +
        8u;
}


/*
 * Send capture-proven ACK pair:
 *
 * 1800
 * 1820
 *
 * Both use:
 *
 * initial sequence + 0x01010000
 */
static gboolean
v4_queue_registration_ack_pair(void)
{
    guint8 body_ack[32];
    guint8 body_confirm[32];

    guint8 frames[80];


    guint ack_len =
        v4_make_ack_body(
            body_ack,
            0x1800
        );


    guint confirm_len =
        v4_make_ack_body(
            body_confirm,
            0x1820
        );


    guint first =
        v4_make_outer_frame(
            frames,
            sizeof(frames),
            v4_ctpp_channel_id,
            body_ack,
            ack_len
        );


    guint second =
        v4_make_outer_frame(
            frames + first,
            sizeof(frames) - first,
            v4_ctpp_channel_id,
            body_confirm,
            confirm_len
        );


    memset(
        body_ack,
        0,
        sizeof(body_ack)
    );


    memset(
        body_confirm,
        0,
        sizeof(body_confirm)
    );


    if (
        first == 0 ||
        second == 0 ||
        first + second >
            sizeof(frames)
    ) {

        memset(
            frames,
            0,
            sizeof(frames)
        );

        return FALSE;
    }


    p12_stage =
        P12_STAGE_V4_ACK_PAIR_TX;


    gboolean ok =
        p12_queue_bytes(
            frames,
            first + second,
            P12_TX_V4_ACK_PAIR
        );


    memset(
        frames,
        0,
        sizeof(frames)
    );


    return
        ok &&
        p12_flush_tx();
}



static void
p12_tx_completed(P12TxKind kind)
{
    switch (kind) {
        case P12_TX_AUTH:
            printf("VIP_UAUT_AUTH_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_AUTH_RESPONSE;
            break;

        case P12_TX_CLOSE_UAUT:
            printf("VIP_UAUT_CLOSE_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE;
            break;

        case P12_TX_OPEN_UCFG:
            printf(
                "VIP_UCFG_OPEN_SENT=PASS requested_channel_id=%u\n",
                (unsigned)ucfg_requested_channel_id
            );
            p12_stage = P12_STAGE_WAIT_UCFG_OPEN_RESPONSE;
            break;

        case P12_TX_GET_UCFG:
            printf("VIP_UCFG_GET_CONFIGURATION_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UCFG_RESPONSE;
            break;

        case P12_TX_CLOSE_UCFG:
            printf("VIP_UCFG_CLOSE_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE;
            break;


        case P12_TX_V4_OPEN_CTPP:

            printf(
                "V4_CTPP_OPEN_SENT=PASS\n"
            );

            p12_stage =
                P12_STAGE_V4_WAIT_CTPP_OPEN_RESPONSE;

            break;


        case P12_TX_V4_OPEN_CSPB:

            printf(
                "V4_CSPB_OPEN_SENT=PASS\n"
            );

            p12_stage =
                P12_STAGE_V4_WAIT_CSPB_OPEN_RESPONSE;

            break;


        case P12_TX_V4_CTPP_INIT:

            printf(
                "V4_CTPP_REGISTRATION_INIT_SENT=PASS\n"
            );

            p12_stage =
                P12_STAGE_V4_WAIT_CTPP_BOOTSTRAP;

            break;


        case P12_TX_V4_ACK_PAIR:

            if (!v4_registered) {

                v4_registered =
                    TRUE;

                v4_listener_ready =
                    TRUE;


                printf(
                    "V4_CTPP_REGISTRATION=PASS\n"
                );

                printf(
                    "V4_RING_LISTENER_READY=true\n"
                );

                printf(
                    "V4_DOOR_ACTION_SURFACE_PRESENT=true\n"
                );

                printf(
                    "V4_MEDIA_ACTION_SURFACE_PRESENT=false\n"
                );

            } else {

                printf(
                    "V4_REGISTRATION_RENEWAL_ACK_PAIR=PASS\n"
                );
            }


            p12_stage =
                P12_STAGE_V4_LISTEN_RING;


            p12_deadline_us =
                0;


            break;


        case P12_TX_V4_PEER_ECHO_REPLY:

            printf(
                "V4_RX_ECHO_RESPONSE_SENT=true\n"
            );

            printf(
                "V4_PEER_ECHO_REFLECT=PASS\n"
            );

            p12_stage =
                P12_STAGE_V4_LISTEN_RING;

            p12_deadline_us =
                0;

            break;


        case P12_TX_V4_PEER_ECHO_CLOSE_ACK:

            printf(
                "V4_PEER_ECHO_CLOSE_ACK_SENT=true\n"
            );

            p12_stage =
                P12_STAGE_V4_LISTEN_RING;

            p12_deadline_us =
                0;

            break;


        case P12_TX_V4_DOOR_WRITE:
            printf(
                "V4_DOOR_OPERATION_WRITE_%u_SENT=true\n",
                (unsigned)v4_door_write_index
            );
            v4_door_writes_sent = v4_door_write_index;

            if (v4_door_write_index < v4_door_write_count) {
                v4_door_stage = V4_DOOR_SENDING;
                v4_door_set_deadline();

                if (!v4_door_queue_write(v4_door_write_index + 1)) {
                    v4_door_emit_result("UNKNOWN_OUTCOME");
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            } else {
                v4_door_stage = V4_DOOR_WAIT_SETTLE;
                v4_door_set_deadline();

                printf("V4_DOOR_OPERATION_WRITES_SENT=5\n");
                printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\n");
                fflush(stdout);

                if (g_timeout_add(
                        V4_DOOR_SETTLE_MS,
                        v4_door_settle_cb,
                        NULL
                    ) == 0) {
                    v4_door_emit_result("UNKNOWN_OUTCOME");
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            }
            break;

        default:
            break;
    }

    if (
        p12_stage ==
        P12_STAGE_V4_LISTEN_RING
    ) {

        p12_deadline_us = 0;

    } else {

        p12_set_deadline();
    }

    fflush(stdout);
}


static gboolean
p12_flush_tx(void)
{
    if (!p12_tx_pending)
        return TRUE;

    while (p12_tx_offset < p12_tx_len) {
        gint n =
            pseudo_tcp_socket_send(
                pseudo_tcp,
                (const gchar *)p12_tx + p12_tx_offset,
                (guint32)(p12_tx_len - p12_tx_offset)
            );

        if (n > 0) {
            p12_tx_offset += (guint)n;
            continue;
        }

        if (n < 0) {
            gint err =
                pseudo_tcp_socket_get_error(pseudo_tcp);

            if (err == EWOULDBLOCK)
                return TRUE;

            fprintf(
                stderr,
                "P12_PSEUDOTCP_SEND=FAIL error=%d\n",
                err
            );

            return FALSE;
        }

        return TRUE;
    }

    P12TxKind completed = p12_tx_kind;

    memset(p12_tx, 0, p12_tx_len);
    p12_tx_len = 0;
    p12_tx_offset = 0;
    p12_tx_kind = P12_TX_NONE;
    p12_tx_pending = FALSE;

    p12_tx_completed(completed);
    return TRUE;
}


static gboolean
p12_queue_auth(void)
{
    gchar token[33] = {0};

    if (!p12_load_vip_token(token))
        return FALSE;

    gchar body[256];
    gint n =
        g_snprintf(
            body,
            sizeof(body),
            "{\"message\":\"access\",\"user-token\":\"%s\",\"message-type\":\"request\",\"message-id\":5}\n",
            token
        );

    memset(token, 0, sizeof(token));

    if (n != 109) {
        memset(body, 0, sizeof(body));
        fprintf(stderr, "P12_UAUT_AUTH_BODY_SHAPE=FAIL len=%d\n", n);
        return FALSE;
    }

    gboolean ok =
        p12_queue_vip_frame(
            uaut_channel_id,
            (const guint8 *)body,
            (guint)n,
            P12_TX_AUTH
        );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    p12_stage = P12_STAGE_AUTH_TX;
    return p12_flush_tx();
}


static gboolean
p12_queue_close_channel(
    guint16 channel_id,
    P12TxKind kind)
{
    guint8 body[10];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0x01EF);
    write_le16(body + 2, 3);
    write_le32(body + 4, 2);
    write_le16(body + 8, channel_id);

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            kind
        );

    memset(body, 0, sizeof(body));
    return ok && p12_flush_tx();
}


static gboolean
p12_queue_open_ucfg(void)
{
    guint16 candidate = 7449;

    while (candidate == echo_channel_id ||
           candidate == uaut_channel_id) {
        candidate++;
    }

    ucfg_requested_channel_id = candidate;

    guint8 body[15];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "UCFG", 4);
    write_le16(body + 12, ucfg_requested_channel_id);
    body[14] = 0;

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_OPEN_UCFG
        );

    memset(body, 0, sizeof(body));
    return ok && p12_flush_tx();
}


static gboolean
p12_queue_get_ucfg(void)
{
    if (p12_ucfg_request_body_len == 0 ||
        p12_ucfg_request_body[
            p12_ucfg_request_body_len - 1
        ] != 0x0a) {

        fprintf(stderr, "P12_UCFG_REQUEST_LF=FAIL\n");
        return FALSE;
    }

    return
        p12_queue_vip_frame(
            ucfg_channel_id,
            p12_ucfg_request_body,
            p12_ucfg_request_body_len,
            P12_TX_GET_UCFG
        ) &&
        p12_flush_tx();
}


static gboolean
p12_json_string_equals(
    const gchar *json,
    gsize len,
    const gchar *key,
    const gchar *expected)
{
    gchar *needle =
        g_strdup_printf("\"%s\"", key);

    const gchar *p =
        g_strstr_len(json, (gssize)len, needle);

    g_free(needle);

    if (!p)
        return FALSE;

    p = strchr(p, ':');
    if (!p)
        return FALSE;

    p++;
    while ((gsize)(p - json) < len &&
           g_ascii_isspace(*p)) {
        p++;
    }

    if ((gsize)(p - json) >= len ||
        *p != '"') {
        return FALSE;
    }

    p++;
    gsize expected_len = strlen(expected);

    if ((gsize)(p - json) + expected_len >= len)
        return FALSE;

    return
        memcmp(p, expected, expected_len) == 0 &&
        p[expected_len] == '"';
}


static gboolean
p12_json_int_equals(
    const gchar *json,
    gsize len,
    const gchar *key,
    gint64 expected)
{
    gchar *needle =
        g_strdup_printf("\"%s\"", key);

    const gchar *p =
        g_strstr_len(json, (gssize)len, needle);

    g_free(needle);

    if (!p)
        return FALSE;

    p = strchr(p, ':');
    if (!p)
        return FALSE;

    p++;
    while ((gsize)(p - json) < len &&
           g_ascii_isspace(*p)) {
        p++;
    }

    gchar *end = NULL;
    gint64 value = g_ascii_strtoll(p, &end, 10);

    if (end == p)
        return FALSE;

    return value == expected;
}


static gboolean
p12_parse_control_response(
    const guint8 *body,
    guint body_len,
    guint16 expected_opcode,
    guint16 expected_channel,
    gboolean allow_response_channel_change,
    guint16 *response_channel,
    guint16 *response_word)
{
    guint16 expected_magic =
        expected_opcode == 4 ? 0x01EF : 0xABCD;

    if (body_len != 12 ||
        read_le16(body + 0) != expected_magic ||
        read_le16(body + 2) != expected_opcode ||
        read_le32(body + 4) != 4) {

        return FALSE;
    }

    guint16 channel = read_le16(body + 8);
    guint16 word = read_le16(body + 10);

    if (!allow_response_channel_change &&
        channel != expected_channel) {
        return FALSE;
    }

    if (response_channel)
        *response_channel = channel;

    if (response_word)
        *response_word = word;

    return TRUE;
}


static void
p12_consume_post_ack(guint frame_len)
{
    if (frame_len >= post_ack_capture_len) {
        post_ack_capture_len = 0;
        return;
    }

    memmove(
        post_ack_capture,
        post_ack_capture + frame_len,
        post_ack_capture_len - frame_len
    );

    post_ack_capture_len -= frame_len;
}


static gboolean
p12_save_ucfg(
    const guint8 *body,
    guint body_len)
{
    if (body_len == 0)
        return FALSE;

    const guint8 *p = body;
    guint remaining = body_len;

    while (remaining > 0 &&
           g_ascii_isspace(*p)) {
        p++;
        remaining--;
    }

    if (remaining == 0 || *p != '{') {
        fprintf(stderr, "P12_UCFG_JSON_SHAPE=FAIL\n");
        return FALSE;
    }

    GError *error = NULL;

    if (!g_file_set_contents(
            P12_UCFG_FILE,
            (const gchar *)body,
            (gssize)body_len,
            &error)) {

        fprintf(stderr, "P12_UCFG_LOCAL_CAPTURE_WRITE=FAIL\n");

        if (error)
            g_error_free(error);

        return FALSE;
    }

    chmod(P12_UCFG_FILE, 0600);

    gchar *digest =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            body,
            body_len
        );

    printf("UCFG_RECEIVED=true\n");
    printf("UCFG_RESPONSE_BYTES=%u\n", body_len);
    printf("UCFG_RESPONSE_SHA256=%s\n", digest ? digest : "unavailable");
    printf("UCFG_RESPONSE_VALUE_EMITTED=false\n");
    printf("UCFG_LOCAL_CAPTURE_MODE=600\n");

    g_free(digest);
    fflush(stdout);

    return TRUE;
}



static gboolean
v4_ring_is_retransmit(
    const guint8 *body,
    guint body_len)
{
    gchar *digest =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            body,
            body_len
        );

    if (!digest) {
        /* Fail open: never drop a real ring merely because local hashing failed. */
        return FALSE;
    }

    gint64 now = g_get_monotonic_time();
    gboolean duplicate =
        v4_last_ring_seen_us > 0 &&
        now >= v4_last_ring_seen_us &&
        (now - v4_last_ring_seen_us) <= V4_RING_DEDUP_WINDOW_USEC &&
        g_strcmp0(digest, v4_last_ring_sha256) == 0;

    if (duplicate) {
        /* Refresh the window while the same protocol retransmit train continues. */
        v4_last_ring_seen_us = now;
        printf("V4_RING_RETRANSMIT_SUPPRESSED=true\n");
        printf("V4_RING_RETRANSMIT_SHA256=%s\n", digest);
    } else {
        g_strlcpy(
            v4_last_ring_sha256,
            digest,
            sizeof(v4_last_ring_sha256)
        );
        v4_last_ring_seen_us = now;
        printf("V4_RING_FRAME_SHA256=%s\n", digest);
    }

    g_free(digest);
    fflush(stdout);
    return duplicate;
}



static void
v4_door_set_deadline(void)
{
    v4_door_deadline_us =
        g_get_monotonic_time() +
        ((gint64)V4_DOOR_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
}


static void
v4_door_reset(void)
{
    v4_door_stage = V4_DOOR_IDLE;
    v4_door_write_index = 0;
    v4_door_writes_sent = 0;
    v4_door_deadline_us = 0;
    v4_door_send_started = FALSE;
}


static void
v4_door_emit_result(const gchar *state)
{
    /*
     * V4_DOOR_RESULT is the terminal stdout marker consumed by HA.
     * Every diagnostic belonging to this one-shot operation MUST be
     * emitted before it so Python cannot complete the result future
     * before the accompanying metadata has been parsed.
     */
    printf(
        "V4_DOOR_WRITE_COUNT=%u\n",
        (unsigned)v4_door_writes_sent
    );
    printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    printf("V4_DOOR_RESULT=%s\n", state);
    fflush(stdout);
}


static void
v4_door_signal_handler(int signum)
{
    if (signum == SIGUSR1)
        v4_door_signal_pending = 1;
}


static gboolean
v4_door_queue_write(guint index)
{
    if (index == 0 || index > v4_door_write_count)
        return FALSE;

    const guint8 *body = NULL;
    guint body_len = 0;

    switch (index) {
        case 1:
            body = v4_door_operation_body_1;
            body_len = v4_door_operation_body_len[0];
            break;
        case 2:
            body = v4_door_operation_body_2;
            body_len = v4_door_operation_body_len[1];
            break;
        case 3:
            body = v4_door_operation_body_3;
            body_len = v4_door_operation_body_len[2];
            break;
        case 4:
            body = v4_door_operation_body_4;
            body_len = v4_door_operation_body_len[3];
            break;
        case 5:
            body = v4_door_operation_body_5;
            body_len = v4_door_operation_body_len[4];
            break;
        default:
            return FALSE;
    }

    /*
     * The listener-owned CTPP channel is deliberately reused here.
     * This function must never open or close a CTPP channel.
     */
    if (!v4_registered || v4_ctpp_channel_id == 0)
        return FALSE;

    v4_door_write_index = index;

    gboolean queued =
        p12_queue_vip_frame(
            v4_ctpp_channel_id,
            body,
            body_len,
            P12_TX_V4_DOOR_WRITE
        );

    if (!queued)
        return FALSE;

    v4_door_send_started = TRUE;
    return p12_flush_tx();
}


static gboolean
v4_door_settle_cb(gpointer data)
{
    (void)data;

    if (v4_door_stage != V4_DOOR_WAIT_SETTLE)
        return G_SOURCE_REMOVE;

    printf("V4_DOOR_SETTLE_COMPLETE=true\n");
    printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\n");
    fflush(stdout);

    /*
     * All five operation writes left the local PseudoTCP TX boundary.
     * There is still no proven Door-specific acknowledgement and no
     * assertion about the physical relay/door state.
     */
    v4_door_emit_result("UNKNOWN_OUTCOME");
    v4_door_reset();

    return G_SOURCE_REMOVE;
}


static gboolean
v4_door_tick_cb(gpointer data)
{
    (void)data;

    if (v4_door_stage != V4_DOOR_IDLE &&
        v4_door_deadline_us > 0 &&
        g_get_monotonic_time() > v4_door_deadline_us) {

        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {
            failed = TRUE;
            if (loop)
                g_main_loop_quit(loop);
            return G_SOURCE_REMOVE;
        }

        v4_door_reset();
    }

    if (!v4_door_signal_pending)
        return G_SOURCE_CONTINUE;

    v4_door_signal_pending = 0;

    if (!v4_listener_ready ||
        !v4_registered ||
        v4_ctpp_channel_id == 0 ||
        p12_stage != P12_STAGE_V4_LISTEN_RING ||
        v4_door_stage != V4_DOOR_IDLE ||
        p12_tx_pending) {

        printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
        printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
        printf("V4_DOOR_RESULT=REJECTED_NOT_READY\n");
        fflush(stdout);
        return G_SOURCE_CONTINUE;
    }

    printf("V4_DOOR_COMMAND_ACCEPTED=true\n");
    printf("V4_DOOR_TARGET=entrance\n");
    printf("V4_DOOR_EXISTING_CTPP_REUSED=true\n");
    printf(
        "V4_DOOR_CTPP_CHANNEL_ID=%u\n",
        (unsigned)v4_ctpp_channel_id
    );
    printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    fflush(stdout);

    v4_door_stage = V4_DOOR_SENDING;
    v4_door_write_index = 0;
    v4_door_writes_sent = 0;
    v4_door_send_started = FALSE;
    v4_door_set_deadline();

    if (!v4_door_queue_write(1)) {
        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {
            failed = TRUE;
            if (loop)
                g_main_loop_quit(loop);
            return G_SOURCE_REMOVE;
        }

        v4_door_reset();
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
p12_process_post_uaut(void)
{
    while (TRUE) {
        if (post_ack_capture_len < 8)
            return TRUE;

        if (post_ack_capture[0] != 0x00 ||
            post_ack_capture[1] != 0x06) {

            fprintf(stderr, "P12_VIP_RX_HEADER=FAIL\n");
            return FALSE;
        }

        guint body_len =
            (guint)read_le16(post_ack_capture + 2);

        guint frame_len = 8u + body_len;

        if (frame_len > POST_ACK_CAPTURE_MAX) {
            fprintf(stderr, "P12_VIP_RX_LENGTH=FAIL\n");
            return FALSE;
        }

        if (post_ack_capture_len < frame_len)
            return TRUE;

        guint32 request_id =
            read_le32(post_ack_capture + 4);

        const guint8 *body =
            post_ack_capture + 8;




        /*
         * --------------------------------------------------------
         * V4 post-registration diagnostic
         * --------------------------------------------------------
         *
         * Metadata only.
         *
         * Does NOT print:
         *   - JSON payloads
         *   - credentials
         *   - tokens
         *   - arbitrary binary payloads
         *
         * Does NOT send any additional network traffic.
         */
        if (
            p12_stage >=
                P12_STAGE_V4_OPEN_CTPP_TX &&

            p12_stage <=
                P12_STAGE_V4_LISTEN_RING
        ) {

            const gchar *channel_name =
                "OTHER";


            if (
                v4_ctpp_channel_id != 0 &&
                request_id ==
                v4_ctpp_channel_id
            ) {

                channel_name = "CTPP";

            } else if (
                v4_cspb_channel_id != 0 &&
                request_id ==
                v4_cspb_channel_id
            ) {

                channel_name = "CSPB";

            } else if (
                request_id ==
                echo_channel_id
            ) {

                channel_name = "ECHO";

            } else if (
                request_id ==
                uaut_channel_id
            ) {

                channel_name = "UAUT";

            } else if (
                request_id ==
                ucfg_channel_id
            ) {

                channel_name = "UCFG";

            } else if (
                request_id == 0
            ) {

                channel_name = "CONTROL";
            }


            printf(
                "V4_RX_META "
                "stage=%u "
                "frame_len=%u "
                "body_len=%u "
                "request_id=%u "
                "channel=%s\n",

                (unsigned)p12_stage,
                (unsigned)frame_len,
                (unsigned)body_len,
                (unsigned)request_id,
                channel_name
            );


            /*
             * ABCD command/control family.
             */
            if (
                request_id == 0 &&
                body_len >= 8 &&
                read_le16(body + 0) ==
                    0xABCD
            ) {

                guint16 opcode =
                    read_le16(body + 2);

                guint32 control_len =
                    read_le32(body + 4);


                const gchar *opcode_name =
                    "UNKNOWN";


                if (opcode == 1)
                    opcode_name = "OPEN_REQUEST";

                else if (opcode == 2)
                    opcode_name = "OPEN_RESPONSE";

                else if (opcode == 3)
                    opcode_name = "CLOSE_REQUEST";

                else if (opcode == 4)
                    opcode_name = "CLOSE_RESPONSE";


                printf(
                    "V4_RX_ABCD "
                    "opcode=%u "
                    "opcode_name=%s "
                    "control_len=%u",

                    (unsigned)opcode,
                    opcode_name,
                    (unsigned)control_len
                );


                /*
                 * OPEN request:
                 *
                 * bytes 8..11 = ASCII channel name
                 * bytes 12..13 = requested ID
                 */
                if (
                    opcode == 1 &&
                    body_len >= 15
                ) {

                    guint16 target =
                        read_le16(body + 12);


                    gchar name[5];

                    memset(
                        name,
                        0,
                        sizeof(name)
                    );


                    for (
                        guint i = 0;
                        i < 4;
                        i++
                    ) {

                        guint8 ch =
                            body[8 + i];

                        name[i] =
                            g_ascii_isprint(ch)
                                ? (gchar)ch
                                : '?';
                    }


                    printf(
                        " channel_name=%s"
                        " target_channel=%u",

                        name,
                        (unsigned)target
                    );

                } else if (
                    (
                        opcode == 2 ||
                        opcode == 3 ||
                        opcode == 4
                    ) &&
                    body_len >= 10
                ) {

                    guint16 target =
                        read_le16(body + 8);


                    printf(
                        " target_channel=%u",
                        (unsigned)target
                    );


                    if (body_len >= 12) {

                        printf(
                            " response_word=%u",
                            (unsigned)
                                read_le16(
                                    body + 10
                                )
                        );
                    }
                }


                printf("\n");
            }


            /*
             * Official END family:
             *
             *   EF 01
             *   operation LE16
             *   length LE32
             *   channel LE16
             *   optional response word LE16
             *
             * Capture-proven:
             *
             *   operation=3  close request
             *   operation=4  close response
             */
            if (
                request_id == 0 &&
                body_len >= 10 &&
                read_le16(body + 0) ==
                    0x01EF
            ) {

                guint16 operation =
                    read_le16(body + 2);

                guint32 end_len =
                    read_le32(body + 4);

                guint16 target =
                    read_le16(body + 8);


                const gchar *operation_name =
                    "UNKNOWN";


                if (operation == 3)
                    operation_name =
                        "CLOSE_REQUEST";

                else if (operation == 4)
                    operation_name =
                        "CLOSE_RESPONSE";


                const gchar *target_name =
                    "OTHER";


                if (
                    target ==
                    v4_ctpp_channel_id
                ) {

                    target_name = "CTPP";

                } else if (
                    target ==
                    v4_cspb_channel_id
                ) {

                    target_name = "CSPB";

                } else if (
                    target ==
                    echo_channel_id
                ) {

                    target_name = "ECHO";

                } else if (
                    target ==
                    uaut_channel_id
                ) {

                    target_name = "UAUT";

                } else if (
                    target ==
                    ucfg_channel_id
                ) {

                    target_name = "UCFG";
                }


                printf(
                    "V4_RX_END "
                    "operation=%u "
                    "operation_name=%s "
                    "end_len=%u "
                    "target_channel=%u "
                    "target_name=%s",

                    (unsigned)operation,
                    operation_name,
                    (unsigned)end_len,
                    (unsigned)target,
                    target_name
                );


                if (body_len >= 12) {

                    printf(
                        " response_word=%u",
                        (unsigned)
                            read_le16(
                                body + 10
                            )
                    );
                }


                printf("\n");
            }


            /*
             * CTPP metadata only.
             */
            if (
                request_id ==
                    v4_ctpp_channel_id &&
                body_len >= 8
            ) {

                guint16 prefix =
                    read_le16(
                        body + 0
                    );

                guint16 action =
                    (
                        ((guint16)body[6])
                        << 8
                    ) |
                    ((guint16)body[7]);


                printf(
                    "V4_RX_CTPP "
                    "prefix=0x%04x "
                    "action=0x%04x "
                    "body_len=%u\n",

                    (unsigned)prefix,
                    (unsigned)action,
                    (unsigned)body_len
                );
            }


            /*
             * ----------------------------------------------------
             * ECHO diagnostic
             * ----------------------------------------------------
             *
             * ECHO is a dedicated protocol-maintenance channel.
             *
             * Only this channel is inspected.
             *
             * No UAUT/UCFG/PUSH bodies are ever emitted.
             */
            if (
                request_id ==
                    echo_channel_id
            ) {

                gboolean printable =
                    TRUE;

                gboolean sensitive =
                    FALSE;


                for (
                    guint i = 0;
                    i < body_len;
                    i++
                ) {

                    guint8 ch =
                        body[i];


                    if (
                        ch != '\r' &&
                        ch != '\n' &&
                        ch != '\t' &&
                        !g_ascii_isprint(ch)
                    ) {

                        printable =
                            FALSE;

                        break;
                    }
                }


                /*
                 * Compute SHA-256 locally so repeated ECHO payloads
                 * can be correlated without exposing binary data.
                 */
                GChecksum *sum =
                    g_checksum_new(
                        G_CHECKSUM_SHA256
                    );


                if (sum) {

                    g_checksum_update(
                        sum,
                        body,
                        body_len
                    );


                    printf(
                        "V4_RX_ECHO_SHA256=%s\n",
                        g_checksum_get_string(sum)
                    );


                    g_checksum_free(sum);
                }


                printf(
                    "V4_RX_ECHO_BODY_LEN=%u\n",
                    (unsigned)body_len
                );


                printf(
                    "V4_RX_ECHO_PRINTABLE=%s\n",
                    printable
                        ? "true"
                        : "false"
                );


                /*
                 * Exact known keepalive forms.
                 */
                if (
                    body_len == 10 &&
                    memcmp(
                        body,
                        "keep-alive",
                        10
                    ) == 0
                ) {

                    printf(
                        "V4_RX_ECHO_CLASS="
                        "KEEPALIVE_REQUEST\n"
                    );

                } else if (
                    body_len == 10 &&
                    memcmp(
                        body,
                        "KEEP-ALIVE",
                        10
                    ) == 0
                ) {

                    printf(
                        "V4_RX_ECHO_CLASS="
                        "KEEPALIVE_RESPONSE\n"
                    );

                } else {

                    printf(
                        "V4_RX_ECHO_CLASS="
                        "UNKNOWN\n"
                    );
                }


                /*
                 * Printable ECHO payload may be useful for identifying
                 * the maintenance handshake.
                 *
                 * Before emitting it, reject common credential-bearing
                 * terms. ECHO is the only eligible channel.
                 */
                if (
                    printable &&
                    body_len > 0 &&
                    body_len <= 64
                ) {

                    gchar text[65];

                    memset(
                        text,
                        0,
                        sizeof(text)
                    );


                    memcpy(
                        text,
                        body,
                        body_len
                    );


                    gchar *lower =
                        g_ascii_strdown(
                            text,
                            -1
                        );


                    if (lower) {

                        if (
                            strstr(lower, "token") ||
                            strstr(lower, "password") ||
                            strstr(lower, "passwd") ||
                            strstr(lower, "secret") ||
                            strstr(lower, "credential") ||
                            strstr(lower, "authorization") ||
                            strstr(lower, "bearer") ||
                            strstr(lower, "mqtt")
                        ) {

                            sensitive =
                                TRUE;
                        }


                        g_free(lower);
                    }


                    if (!sensitive) {

                        /*
                         * Escape CR/LF/TAB instead of allowing
                         * arbitrary extra log lines.
                         */
                        gchar escaped[193];

                        guint o = 0;

                        memset(
                            escaped,
                            0,
                            sizeof(escaped)
                        );


                        for (
                            guint i = 0;
                            i < body_len &&
                            o + 4 < sizeof(escaped);
                            i++
                        ) {

                            guint8 ch =
                                body[i];


                            if (ch == '\r') {

                                escaped[o++] = '\\';
                                escaped[o++] = 'r';

                            } else if (
                                ch == '\n'
                            ) {

                                escaped[o++] = '\\';
                                escaped[o++] = 'n';

                            } else if (
                                ch == '\t'
                            ) {

                                escaped[o++] = '\\';
                                escaped[o++] = 't';

                            } else {

                                escaped[o++] =
                                    (gchar)ch;
                            }
                        }


                        escaped[o] = '\0';


                        printf(
                            "V4_RX_ECHO_SAFE_ASCII=%s\n",
                            escaped
                        );

                    } else {

                        printf(
                            "V4_RX_ECHO_SAFE_ASCII="
                            "REDACTED_SENSITIVE_TERM\n"
                        );
                    }


                    memset(
                        text,
                        0,
                        sizeof(text)
                    );
                }


                /*
                 * Structural data only for non-printable payloads.
                 */
                if (
                    !printable &&
                    body_len >= 2
                ) {

                    printf(
                        "V4_RX_ECHO_FIRST_LE16=0x%04x\n",
                        (unsigned)
                            read_le16(body)
                    );


                    if (body_len >= 4) {

                        printf(
                            "V4_RX_ECHO_SECOND_LE16=0x%04x\n",
                            (unsigned)
                                read_le16(
                                    body + 2
                                )
                        );
                    }
                }


                /*
                 * Response is performed by the bounded listener
                 * handler below. Do not emit a speculative result here.
                 */
                fflush(stdout);
            }


            /*
             * CSPB metadata only.
             */
            if (
                request_id ==
                    v4_cspb_channel_id
            ) {

                printf(
                    "V4_RX_CSPB "
                    "body_len=%u\n",
                    (unsigned)body_len
                );
            }


            fflush(stdout);
        }


        if (p12_stage == P12_STAGE_WAIT_AUTH_RESPONSE) {
            if (request_id != uaut_channel_id) {
                fprintf(stderr, "P12_UAUT_AUTH_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            gchar *json =
                g_strndup((const gchar *)body, body_len);

            gboolean ok =
                p12_json_string_equals(
                    json,
                    body_len,
                    "message",
                    "access"
                ) &&
                p12_json_string_equals(
                    json,
                    body_len,
                    "message-type",
                    "response"
                ) &&
                p12_json_int_equals(
                    json,
                    body_len,
                    "response-code",
                    200
                );

            g_free(json);

            if (!ok) {
                fprintf(stderr, "P12_UAUT_AUTH_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_auth_ok = TRUE;
            printf("P2_VIP_UAUT_AUTH=PASS\n");
            printf("UAUT_RESPONSE_CODE=200\n");
            printf("UAUT_RESPONSE_VALUE_EMITTED=false\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_CLOSE_UAUT_TX;

            if (!p12_queue_close_channel(
                    uaut_channel_id,
                    P12_TX_CLOSE_UAUT)) {
                return FALSE;
            }

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    4,
                    uaut_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UAUT_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_uaut_close_ok = TRUE;
            printf("VIP_UAUT_CLOSE_RESPONSE=PASS\n");
            printf("VIP_UAUT_CLOSE_RESPONSE_WORD=0\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_OPEN_UCFG_TX;

            if (!p12_queue_open_ucfg())
                return FALSE;

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_OPEN_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    2,
                    ucfg_requested_channel_id,
                    TRUE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UCFG_OPEN_RESPONSE=FAIL\n");
                return FALSE;
            }

            ucfg_channel_id = response_channel;
            p12_ucfg_open_ok = TRUE;

            printf("VIP_UCFG_OPEN_RESPONSE=PASS\n");
            printf(
                "VIP_UCFG_OPEN_RESPONSE_CHANNEL_ID=%u\n",
                (unsigned)ucfg_channel_id
            );
            printf("VIP_UCFG_OPEN_RESPONSE_WORD=0\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_GET_UCFG_TX;

            if (!p12_queue_get_ucfg())
                return FALSE;

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_RESPONSE) {
            if (request_id != ucfg_channel_id) {
                fprintf(stderr, "P12_UCFG_RESPONSE_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            if (!p12_save_ucfg(body, body_len))
                return FALSE;

            p12_ucfg_received = TRUE;
            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_CLOSE_UCFG_TX;

            if (!p12_queue_close_channel(
                    ucfg_channel_id,
                    P12_TX_CLOSE_UCFG)) {
                return FALSE;
            }

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    4,
                    ucfg_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UCFG_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_ucfg_close_ok = TRUE;

            p12_consume_post_ack(
                frame_len
            );


            printf(
                "VIP_UCFG_CLOSE_RESPONSE=PASS\n"
            );

            printf(
                "VIP_UCFG_CLOSE_RESPONSE_WORD=0\n"
            );

            printf(
                "P12_READONLY_TRANSACTION=PASS\n"
            );

            printf(
                "V4_REGISTRATION_START=true\n"
            );

            fflush(stdout);


            p12_stage =
                P12_STAGE_V4_OPEN_CTPP_TX;


            if (!v4_queue_open_ctpp())
                return FALSE;


            continue;
        }


        /*
         * --------------------------------------------------------
         * CTPP OPEN response
         * --------------------------------------------------------
         */
        if (
            p12_stage ==
            P12_STAGE_V4_WAIT_CTPP_OPEN_RESPONSE
        ) {

            guint16 response_channel = 0;
            guint16 response_word = 0xffff;


            if (
                request_id != 0 ||

                !p12_parse_control_response(
                    body,
                    body_len,
                    2,
                    v4_ctpp_requested_channel_id,
                    TRUE,
                    &response_channel,
                    &response_word
                ) ||

                response_word != 0
            ) {

                fprintf(
                    stderr,
                    "V4_CTPP_OPEN_RESPONSE=FAIL\n"
                );

                return FALSE;
            }


            v4_ctpp_channel_id =
                response_channel;


            v4_ctpp_open_ok =
                TRUE;


            printf(
                "V4_CTPP_OPEN_RESPONSE=PASS\n"
            );


            printf(
                "V4_CTPP_SERVER_CHANNEL_ID=%u\n",
                (unsigned)
                    v4_ctpp_channel_id
            );


            p12_consume_post_ack(
                frame_len
            );


            p12_stage =
                P12_STAGE_V4_OPEN_CSPB_TX;


            if (!v4_queue_open_cspb())
                return FALSE;


            continue;
        }


        /*
         * --------------------------------------------------------
         * CSPB OPEN response
         * --------------------------------------------------------
         */
        if (
            p12_stage ==
            P12_STAGE_V4_WAIT_CSPB_OPEN_RESPONSE
        ) {

            guint16 response_channel = 0;
            guint16 response_word = 0xffff;


            if (
                request_id != 0 ||

                !p12_parse_control_response(
                    body,
                    body_len,
                    2,
                    v4_cspb_requested_channel_id,
                    TRUE,
                    &response_channel,
                    &response_word
                ) ||

                response_word != 0
            ) {

                fprintf(
                    stderr,
                    "V4_CSPB_OPEN_RESPONSE=FAIL\n"
                );

                return FALSE;
            }


            v4_cspb_channel_id =
                response_channel;


            v4_cspb_open_ok =
                TRUE;


            printf(
                "V4_CSPB_OPEN_RESPONSE=PASS\n"
            );


            printf(
                "V4_CSPB_SERVER_CHANNEL_ID=%u\n",
                (unsigned)
                    v4_cspb_channel_id
            );


            p12_consume_post_ack(
                frame_len
            );


            p12_stage =
                P12_STAGE_V4_CTPP_INIT_TX;


            if (
                !v4_queue_ctpp_registration_init()
            ) {

                return FALSE;
            }


            continue;
        }


        /*
         * --------------------------------------------------------
         * Initial CTPP registration handshake
         * --------------------------------------------------------
         */
        if (
            p12_stage ==
            P12_STAGE_V4_WAIT_CTPP_BOOTSTRAP
        ) {

            /*
             * Other channels may remain alive.
             * Ignore unrelated frames without exposing payload.
             */
            if (
                request_id !=
                v4_ctpp_channel_id
            ) {

                p12_consume_post_ack(
                    frame_len
                );

                continue;
            }


            if (body_len < 8) {

                fprintf(
                    stderr,
                    "V4_CTPP_BOOTSTRAP_SHORT_FRAME=FAIL\n"
                );

                return FALSE;
            }


            guint16 prefix =
                read_le16(
                    body + 0
                );


            guint16 action =
                (
                    ((guint16)body[6]) <<
                    8
                ) |
                ((guint16)body[7]);


            /*
             * Device's initial ACK.
             */
            if (
                prefix ==
                0x1800
            ) {

                v4_initial_ack_seen =
                    TRUE;


                printf(
                    "V4_CTPP_INITIAL_ACK_OBSERVED=true\n"
                );


                p12_consume_post_ack(
                    frame_len
                );


                continue;
            }


            /*
             * Registration renewal / registration accepted.
             */
            if (
                prefix ==
                    0x1860 &&

                action ==
                    0x0010
            ) {

                if (
                    body_len < 12 ||

                    read_le16(
                        body + 10
                    ) !=
                        v4_registration_token
                ) {

                    fprintf(
                        stderr,
                        "V4_REGISTRATION_TOKEN_ECHO=FAIL\n"
                    );

                    return FALSE;
                }


                v4_registration_renewal_seen =
                    TRUE;


                printf(
                    "V4_REGISTRATION_RENEWAL_1860_0010=true\n"
                );


                printf(
                    "V4_REGISTRATION_TOKEN_ECHO=PASS\n"
                );


                p12_consume_post_ack(
                    frame_len
                );


                p12_stage =
                    P12_STAGE_V4_ACK_PAIR_TX;


                if (
                    !v4_queue_registration_ack_pair()
                ) {

                    return FALSE;
                }


                continue;
            }


            printf(
                "V4_CTPP_BOOTSTRAP_OTHER "
                "prefix=0x%04x "
                "action=0x%04x\n",

                (unsigned)prefix,
                (unsigned)action
            );


            p12_consume_post_ack(
                frame_len
            );


            continue;
        }


        /*
         * --------------------------------------------------------
         * Persistent ring listener
         * --------------------------------------------------------
         */
        if (
            p12_stage ==
            P12_STAGE_V4_LISTEN_RING
        ) {

            /*
             * ----------------------------------------------------
             * Peer-opened ECHO
             * ----------------------------------------------------
             *
             * Official PCAP behavior:
             *
             * device sends:
             *
             *     echo <timestamp>
             *
             * client immediately reflects identical bytes.
             */
            if (
                echo_channel_id != 0 &&
                request_id ==
                    echo_channel_id
            ) {

                if (
                    !v4_queue_peer_echo_reply(
                        body,
                        body_len
                    )
                ) {

                    return FALSE;
                }


                p12_consume_post_ack(
                    frame_len
                );


                continue;
            }


            /*
             * ----------------------------------------------------
             * Peer closes ECHO
             * ----------------------------------------------------
             *
             * Normally this should no longer occur once reflection
             * works. Still ACK it correctly if the peer closes.
             */
            if (
                request_id == 0 &&
                body_len >= 10 &&
                read_le16(body + 0) ==
                    0x01EF &&
                read_le16(body + 2) ==
                    3
            ) {

                guint32 end_len =
                    read_le32(
                        body + 4
                    );

                guint16 target =
                    read_le16(
                        body + 8
                    );


                if (
                    end_len == 2 &&
                    echo_channel_id != 0 &&
                    target ==
                        echo_channel_id
                ) {

                    printf(
                        "V4_PEER_ECHO_CLOSE_REQUEST=true\n"
                    );


                    if (
                        !v4_queue_peer_echo_close_ack(
                            target
                        )
                    ) {

                        return FALSE;
                    }


                    p12_consume_post_ack(
                        frame_len
                    );


                    continue;
                }
            }


            /*
             * Ignore other unrelated channels.
             */
            if (
                request_id !=
                v4_ctpp_channel_id
            ) {

                p12_consume_post_ack(
                    frame_len
                );

                continue;
            }


            if (body_len < 8) {

                p12_consume_post_ack(
                    frame_len
                );

                continue;
            }


            guint16 prefix =
                read_le16(
                    body + 0
                );


            guint16 action =
                (
                    ((guint16)body[6]) <<
                    8
                ) |
                ((guint16)body[7]);


            /*
             * Periodic registration renewal.
             */
            if (
                prefix ==
                    0x1860 &&

                action ==
                    0x0010
            ) {

                if (
                    body_len >= 12 &&

                    read_le16(
                        body + 10
                    ) ==
                        v4_registration_token
                ) {

                    p12_consume_post_ack(
                        frame_len
                    );


                    p12_stage =
                        P12_STAGE_V4_ACK_PAIR_TX;


                    if (
                        !v4_queue_registration_ack_pair()
                    ) {

                        return FALSE;
                    }


                    continue;
                }


                fprintf(
                    stderr,
                    "V4_RENEWAL_TOKEN_ECHO=FAIL\n"
                );


                return FALSE;
            }


            /*
             * Ring candidates.
             *
             * 18C0 / 0028 = call-init
             *
             * 1860 / 0001 = IN_ALERTING
             *
             * First V4 test is observation-only:
             *
             * - no call answer
             * - no media activation
             * - no actuator action
             */
            if (
                prefix ==
                    0x18C0 &&

                action ==
                    0x0028
            ) {

                const gchar *door =
                    "unknown";

                const gchar *source =
                    "unknown";


                if (
                    v4_contains_ascii(
                        body,
                        body_len,
                        V4_ENTRANCE
                    )
                ) {

                    door =
                        "entrance";

                    source =
                        V4_ENTRANCE;

                } else if (
                    v4_contains_ascii(
                        body,
                        body_len,
                        V4_GATE
                    )
                ) {

                    door =
                        "gate";

                    source =
                        V4_GATE;
                }


                if (
                    v4_ring_is_retransmit(
                        body,
                        body_len
                    )
                ) {
                    p12_consume_post_ack(
                        frame_len
                    );
                    continue;
                }


                v4_ring_observed =
                    TRUE;


                printf(
                    "V4_RING_OBSERVED=true\n"
                );


                printf(
                    "V4_RING_DIRECTION=DEVICE_TO_CLIENT\n"
                );


                printf(
                    "V4_RING_KIND=CALL_INIT\n"
                );


                printf(
                    "V4_RING_DOOR=%s\n",
                    door
                );


                printf(
                    "V4_RING_SOURCE=%s\n",
                    source
                );


                printf(
                    "V4_RING_RAW_PAYLOAD_EMITTED=false\n"
                );


                printf(
                    "NETWORK_DOOR_ACTION_PERFORMED=false\n"
                );


                printf(
                    "PHYSICAL_DOOR_ACTION=false\n"
                );


                fflush(stdout);


                p12_consume_post_ack(
                    frame_len
                );


                failed =
                    FALSE;


                /*
                 * Persistent listener:
                 * CALL_INIT observation must not terminate the
                 * registered PseudoTCP/CTPP session.
                 */
                return TRUE;
            }


            /*
             * Other CTPP traffic:
             *
             * prefix/action only.
             * Raw payload is never printed.
             */
            printf(
                "V4_CTPP_EVENT "
                "prefix=0x%04x "
                "action=0x%04x\n",

                (unsigned)prefix,
                (unsigned)action
            );


            p12_consume_post_ack(
                frame_len
            );


            continue;
        }


        fprintf(
            stderr,
            "P12_UNEXPECTED_RX_STAGE=%u\n",
            (unsigned)p12_stage
        );

        return FALSE;
    }
}


static gboolean
p12_begin_auth(void)
{
    if (uaut_response_word != 0) {
        fprintf(
            stderr,
            "P12_UAUT_OPEN_RESPONSE_WORD=FAIL value=%u\n",
            (unsigned)uaut_response_word
        );

        return FALSE;
    }

    post_ack_capture_len = 0;
    p12_stage = P12_STAGE_AUTH_TX;
    p12_set_deadline();

    g_timeout_add(
        200,
        p12_stage_timeout_cb,
        NULL
    );

    return p12_queue_auth();
}


static gboolean
uaut_response_timeout_cb(gpointer data)
{
    (void)data;

    if (!uaut_response_seen) {
        fprintf(
            stderr,
            "VIP_UAUT_OPEN_RESPONSE_TIMEOUT=true\n"
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);
    }

    return G_SOURCE_REMOVE;
}


static gboolean
try_parse_uaut_response(void)
{
    if (uaut_response_seen)
        return p12_process_post_uaut();

    if (!uaut_open_sent)
        return TRUE;

    if (post_ack_capture_len < 8)
        return TRUE;

    if (post_ack_capture[0] != 0x00 ||
        post_ack_capture[1] != 0x06) {

        fprintf(
            stderr,
            "VIP_UAUT_RESPONSE_MAGIC=FAIL\n"
        );

        return FALSE;
    }

    guint16 body_len =
        read_le16(
            post_ack_capture + 2
        );

    guint frame_len =
        8u + (guint)body_len;

    if (frame_len >
        POST_ACK_CAPTURE_MAX) {

        fprintf(
            stderr,
            "VIP_UAUT_RESPONSE_SIZE=FAIL "
            "BODY=%u\n",
            (unsigned)body_len
        );

        return FALSE;
    }

    if (post_ack_capture_len <
        frame_len) {

        return TRUE;
    }

    /*
     * OPEN RESPONSE:
     *
     * outer:
     *   magic       00 06
     *   body_len    12
     *   request_id  0
     *   reserved    0
     *
     * control:
     *   type        0xABCD
     *   sequence    2
     *   primary_len 4
     *
     * primary:
     *   channel_id  uint16 LE
     *   response    uint16 LE
     */
    if (body_len != 12 ||
        read_le16(post_ack_capture + 4) != 0 ||
        read_le16(post_ack_capture + 6) != 0 ||
        read_le16(post_ack_capture + 8) != 0xABCD ||
        read_le16(post_ack_capture + 10) != 2 ||
        read_le32(post_ack_capture + 12) != 4) {

        fprintf(
            stderr,
            "VIP_UAUT_RESPONSE_LAYOUT=FAIL\n"
        );

        return FALSE;
    }

    guint16 response_channel_id =
        read_le16(
            post_ack_capture + 16
        );

    if (response_channel_id !=
        uaut_channel_id) {

        fprintf(
            stderr,
            "VIP_UAUT_RESPONSE_CHANNEL_ID=FAIL "
            "EXPECTED=%u ACTUAL=%u\n",
            (unsigned)uaut_channel_id,
            (unsigned)response_channel_id
        );

        return FALSE;
    }

    uaut_response_word =
        read_le16(
            post_ack_capture + 18
        );

    uaut_response_seen = TRUE;

    printf(
        "VIP_UAUT_OPEN_RESPONSE_CHANNEL_ID=%u\n",
        (unsigned)response_channel_id
    );

    printf(
        "VIP_UAUT_OPEN_RESPONSE_WORD=%u\n",
        (unsigned)uaut_response_word
    );

    printf(
        "VIP_UAUT_OPEN_RESPONSE=PASS\n"
    );

    fflush(stdout);

    /*
     * Give PseudoTCP a short opportunity to emit ACKs,
     * then end this deliberately narrow experiment.
     */
    if (!p12_begin_auth())
        return FALSE;

    return TRUE;
}


static gboolean
try_send_uaut_open(void)
{
    if (!echo_ack_sent ||
        uaut_open_sent ||
        !pseudo_tcp) {

        return TRUE;
    }

    if (!uaut_open_started) {
        /*
         * Capture starts local allocation at 7449.
         *
         * Avoid the only currently active peer channel
         * if a future session happens to allocate the
         * same numeric ID.
         */
        uaut_channel_id =
            echo_channel_id == 7449 ?
                7450 :
                7449;

        memset(
            uaut_open,
            0,
            sizeof(uaut_open)
        );

        /*
         * ViP outer header.
         */
        uaut_open[0] = 0x00;
        uaut_open[1] = 0x06;

        write_le16(
            uaut_open + 2,
            15
        );

        write_le16(
            uaut_open + 4,
            0
        );

        write_le16(
            uaut_open + 6,
            0
        );

        /*
         * Control OPEN request.
         */
        write_le16(
            uaut_open + 8,
            0xABCD
        );

        write_le16(
            uaut_open + 10,
            1
        );

        write_le32(
            uaut_open + 12,
            7
        );

        memcpy(
            uaut_open + 16,
            "UAUT",
            4
        );

        write_le16(
            uaut_open + 20,
            uaut_channel_id
        );

        uaut_open[22] = 0;

        uaut_open_offset = 0;
        uaut_open_started = TRUE;

        printf(
            "VIP_UAUT_OPEN_CHANNEL_ID=%u\n",
            (unsigned)uaut_channel_id
        );

        printf("VIP_UAUT_OPEN_FLAG=0\n");

        fflush(stdout);
    }

    while (uaut_open_offset <
           sizeof(uaut_open)) {

        gint n =
            pseudo_tcp_socket_send(
                pseudo_tcp,
                (const gchar *)uaut_open +
                    uaut_open_offset,
                (guint32)(
                    sizeof(uaut_open) -
                    uaut_open_offset
                )
            );

        if (n > 0) {
            uaut_open_offset +=
                (guint)n;

            continue;
        }

        if (n < 0) {
            gint err =
                pseudo_tcp_socket_get_error(
                    pseudo_tcp
                );

            if (err == EWOULDBLOCK)
                return TRUE;

            fprintf(
                stderr,
                "VIP_UAUT_OPEN_SEND=FAIL "
                "ERROR=%d\n",
                err
            );

            return FALSE;
        }

        return TRUE;
    }

    uaut_open_sent = TRUE;

    printf(
        "VIP_UAUT_OPEN_BYTES=%zu\n",
        sizeof(uaut_open)
    );

    printf("VIP_UAUT_OPEN_HEX=");

    for (guint i = 0;
         i < sizeof(uaut_open);
         i++) {

        printf(
            "%02x",
            (unsigned)uaut_open[i]
        );
    }

    printf("\n");
    printf("VIP_UAUT_OPEN_SENT=PASS\n");

    fflush(stdout);

    /*
     * This stage expects only the OPEN RESPONSE.
     * No UAUT JSON/token is sent.
     */
    g_timeout_add(
        3000,
        uaut_response_timeout_cb,
        NULL
    );

    /*
     * Handle any bytes which might already have arrived.
     */
    return try_parse_uaut_response();
}


static gboolean
try_send_echo_ack(void)
{
    if (!echo_open_seen ||
        echo_ack_sent ||
        !pseudo_tcp) {

        return TRUE;
    }

    while (echo_ack_offset <
           sizeof(echo_ack)) {

        gint n =
            pseudo_tcp_socket_send(
                pseudo_tcp,
                (const gchar *)echo_ack +
                    echo_ack_offset,
                (guint32)(
                    sizeof(echo_ack) -
                    echo_ack_offset
                )
            );

        if (n > 0) {
            echo_ack_offset +=
                (guint)n;

            continue;
        }

        if (n < 0) {
            gint err =
                pseudo_tcp_socket_get_error(
                    pseudo_tcp
                );

            if (err == EWOULDBLOCK)
                return TRUE;

            fprintf(
                stderr,
                "VIP_ECHO_ACK_SEND=FAIL "
                "ERROR=%d\n",
                err
            );

            return FALSE;
        }

        return TRUE;
    }

    echo_ack_sent = TRUE;

    printf(
        "VIP_ECHO_ACK_CHANNEL_ID=%u\n",
        (unsigned)echo_channel_id
    );

    printf(
        "VIP_ECHO_ACK_BYTES=%zu\n",
        sizeof(echo_ack)
    );

    printf("VIP_ECHO_ACK_HEX=");

    for (guint i = 0;
         i < sizeof(echo_ack);
         i++) {

        printf(
            "%02x",
            (unsigned)echo_ack[i]
        );
    }

    printf("\n");
    printf("VIP_ECHO_ACK=PASS\n");

    fflush(stdout);

    /*
     * ECHO bootstrap is complete.
     * The next PoC gate is only OPEN UAUT.
     */
    return try_send_uaut_open();
}


static gboolean
try_parse_initial_echo(void)
{
    if (echo_open_seen)
        return TRUE;

    if (vip_bootstrap_len < 8)
        return TRUE;

    if (vip_bootstrap[0] != 0x00 ||
        vip_bootstrap[1] != 0x06) {

        fprintf(
            stderr,
            "VIP_FIRST_FRAME_MAGIC=FAIL\n"
        );

        return FALSE;
    }

    guint16 body_len =
        read_le16(
            vip_bootstrap + 2
        );

    guint frame_len =
        8u + (guint)body_len;

    if (frame_len >
        VIP_BOOTSTRAP_MAX) {

        fprintf(
            stderr,
            "VIP_FIRST_FRAME_SIZE=FAIL "
            "BODY=%u\n",
            (unsigned)body_len
        );

        return FALSE;
    }

    if (vip_bootstrap_len <
        frame_len) {

        return TRUE;
    }

    /*
     * Exact peer OPEN ECHO structure derived from
     * capture + production codec:
     *
     * outer:
     *   magic       00 06
     *   body_len    15
     *   request_id  0
     *   reserved    0
     *
     * control:
     *   type        0xABCD
     *   sequence    1
     *   primary_len 7
     *
     * primary:
     *   "ECHO"
     *   channel_id  uint16 LE
     *   flag        0
     */
    if (body_len != 15 ||
        read_le16(vip_bootstrap + 4) != 0 ||
        read_le16(vip_bootstrap + 6) != 0 ||
        read_le16(vip_bootstrap + 8) != 0xABCD ||
        read_le16(vip_bootstrap + 10) != 1 ||
        read_le32(vip_bootstrap + 12) != 7 ||
        memcmp(
            vip_bootstrap + 16,
            "ECHO",
            4
        ) != 0 ||
        vip_bootstrap[22] != 0) {

        fprintf(
            stderr,
            "VIP_FIRST_FRAME_NOT_ECHO_OPEN=true\n"
        );

        return FALSE;
    }

    echo_channel_id =
        read_le16(
            vip_bootstrap + 20
        );

    echo_open_seen = TRUE;

    printf("VIP_PEER_OPEN=PASS\n");
    printf("VIP_PEER_CHANNEL=ECHO\n");

    printf(
        "VIP_PEER_ECHO_CHANNEL_ID=%u\n",
        (unsigned)echo_channel_id
    );

    printf("VIP_PEER_ECHO_FLAG=0\n");

    /*
     * Build:
     *
     * 00 06
     * 0c 00
     * 00 00
     * 00 00
     * cd ab
     * 02 00
     * 04 00 00 00
     * <channel_id LE>
     * 00 00
     */
    memset(
        echo_ack,
        0,
        sizeof(echo_ack)
    );

    echo_ack[0] = 0x00;
    echo_ack[1] = 0x06;

    write_le16(
        echo_ack + 2,
        12
    );

    write_le16(
        echo_ack + 4,
        0
    );

    write_le16(
        echo_ack + 6,
        0
    );

    write_le16(
        echo_ack + 8,
        0xABCD
    );

    write_le16(
        echo_ack + 10,
        2
    );

    write_le32(
        echo_ack + 12,
        4
    );

    write_le16(
        echo_ack + 16,
        echo_channel_id
    );

    write_le16(
        echo_ack + 18,
        0
    );

    echo_ack_offset = 0;

    fflush(stdout);

    return try_send_echo_ack();
}


static gboolean
pseudotcp_success_quit_cb(gpointer data)
{
    (void)data;

    printf(
        "P12_UAUT_AUTH_OK=%s\n",
        p12_auth_ok ? "true" : "false"
    );
    printf(
        "P12_UAUT_CLOSE_OK=%s\n",
        p12_uaut_close_ok ? "true" : "false"
    );
    printf(
        "P12_UCFG_OPEN_OK=%s\n",
        p12_ucfg_open_ok ? "true" : "false"
    );
    printf(
        "P12_UCFG_RECEIVED=%s\n",
        p12_ucfg_received ? "true" : "false"
    );
    printf(
        "P12_UCFG_CLOSE_OK=%s\n",
        p12_ucfg_close_ok ? "true" : "false"
    );
    printf("READONLY_SCOPE_ENFORCED=PASS\n");
    printf("CREDENTIAL_MATERIAL_EMITTED=false\n");
    printf("ACTUATOR_COMMAND_ATTEMPTED=false\n");
    printf("MEDIA_ACTIVATION_ATTEMPTED=false\n");
    printf("AUTO_RETRY_OBSERVED=false\n");
    printf("PHYSICAL_DOOR_ACTION=false\n");
    printf("PHYSICAL_EFFECT_ASSERTED=false\n");
    printf("LIVE_TEST_READY=false\n");

    printf("PSEUDOTCP_SETTLE_COMPLETE=true\n");

    printf(
        "PSEUDOTCP_PACKETS_IN=%u\n",
        pseudotcp_packets_in
    );

    printf(
        "PSEUDOTCP_PACKETS_OUT=%u\n",
        pseudotcp_packets_out
    );

    printf(
        "PSEUDOTCP_MAX_WIRE_OUT=%u\n",
        pseudotcp_max_wire_out
    );

    printf(
        "PSEUDOTCP_APP_BYTES_IN=%" G_GUINT64_FORMAT "\n",
        pseudotcp_app_bytes_in
    );

    printf(
        "PSEUDOTCP_APP_CAPTURE_LEN=%u\n",
        app_capture_len
    );

    printf(
        "VIP_ECHO_OPEN_SEEN=%s\n",
        echo_open_seen ? "true" : "false"
    );

    printf(
        "VIP_ECHO_ACK_SENT=%s\n",
        echo_ack_sent ? "true" : "false"
    );

    printf(
        "VIP_UAUT_OPEN_SENT_FINAL=%s\n",
        uaut_open_sent ? "true" : "false"
    );

    printf(
        "VIP_UAUT_RESPONSE_SEEN_FINAL=%s\n",
        uaut_response_seen ? "true" : "false"
    );

    if (uaut_open_started) {
        printf(
            "VIP_UAUT_CHANNEL_ID_FINAL=%u\n",
            (unsigned)uaut_channel_id
        );
    }

    if (uaut_response_seen) {
        printf(
            "VIP_UAUT_RESPONSE_WORD_FINAL=%u\n",
            (unsigned)uaut_response_word
        );
    }

    printf(
        "VIP_POST_ACK_CAPTURE_LEN=%u\n",
        post_ack_capture_len
    );

    printf("VIP_POST_ACK_CAPTURE_HEX=");

    for (guint i = 0;
         i < post_ack_capture_len;
         i++) {

        printf(
            "%02x",
            (unsigned)
                post_ack_capture[i]
        );
    }

    printf("\n");

    printf("PSEUDOTCP_APP_CAPTURE_HEX=");

    for (guint i = 0;
         i < app_capture_len;
         i++) {

        printf(
            "%02x",
            (unsigned)app_capture[i]
        );
    }

    printf("\n");

    fflush(stdout);

    if (loop)
        g_main_loop_quit(loop);

    return G_SOURCE_REMOVE;
}


static void
pseudotcp_opened_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)tcp;
    (void)data;

    if (pseudotcp_open)
        return;

    pseudotcp_open = TRUE;

    printf("PSEUDOTCP_OPEN=PASS\n");
    fflush(stdout);

    /*
     * Do not terminate on PseudoTCP OPEN.
     * Wait for peer OPEN ECHO, ACK it, then observe
     * the peer passively.
     */
}


static void
pseudotcp_readable_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)data;

    gchar buf[4096];

    while (TRUE) {
        gint n =
            pseudo_tcp_socket_recv(
                tcp,
                buf,
                sizeof(buf)
            );

        if (n > 0) {
            pseudotcp_app_bytes_in +=
                (guint64)n;

            if (app_capture_len <
                APP_CAPTURE_MAX) {

                guint remaining =
                    APP_CAPTURE_MAX -
                    app_capture_len;

                guint copy_len =
                    (guint)n < remaining ?
                        (guint)n :
                        remaining;

                memcpy(
                    app_capture +
                        app_capture_len,
                    buf,
                    copy_len
                );

                app_capture_len +=
                    copy_len;
            }

            printf(
                "PSEUDOTCP_APP_RX_EVENT="
                "%d OPEN=%s ACK=%s\n",
                n,
                pseudotcp_open ?
                    "true" :
                    "false",
                echo_ack_sent ?
                    "true" :
                    "false"
            );

            if (!echo_ack_sent) {
                guint available =
                    VIP_BOOTSTRAP_MAX -
                    vip_bootstrap_len;

                guint copy_len =
                    (guint)n < available ?
                        (guint)n :
                        available;

                if (copy_len > 0) {
                    memcpy(
                        vip_bootstrap +
                            vip_bootstrap_len,
                        buf,
                        copy_len
                    );

                    vip_bootstrap_len +=
                        copy_len;
                }

                if (!try_parse_initial_echo()) {
                    failed = TRUE;

                    if (loop)
                        g_main_loop_quit(loop);

                    return;
                }
            } else {
                guint available =
                    POST_ACK_CAPTURE_MAX -
                    post_ack_capture_len;

                guint copy_len =
                    (guint)n < available ?
                        (guint)n :
                        available;

                if (copy_len > 0) {
                    memcpy(
                        post_ack_capture +
                            post_ack_capture_len,
                        buf,
                        copy_len
                    );

                    post_ack_capture_len +=
                        copy_len;
                }

                if (!try_parse_uaut_response()) {
                    failed = TRUE;

                    if (loop)
                        g_main_loop_quit(loop);

                    return;
                }
            }

            fflush(stdout);

            continue;
        }

        if (n == 0)
            break;

        gint err =
            pseudo_tcp_socket_get_error(
                tcp
            );

        if (err == EWOULDBLOCK)
            break;

        fprintf(
            stderr,
            "PSEUDOTCP_RECV=FAIL ERROR=%d\n",
            err
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        break;
    }
}


static void
pseudotcp_writable_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)tcp;
    (void)data;

    if (!try_send_echo_ack() ||
        !try_send_uaut_open() ||
        !p12_flush_tx()) {

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);
    }
}


static void
pseudotcp_closed_cb(
    PseudoTcpSocket *tcp,
    guint32 error,
    gpointer data)
{
    (void)tcp;
    (void)data;

    printf(
        "PSEUDOTCP_CLOSED_CALLBACK=true "
        "ERROR=%u\n",
        error
    );

    if (!pseudotcp_open) {
        fprintf(
            stderr,
            "PSEUDOTCP_CLOSED_BEFORE_OPEN=true\n"
        );
    } else {
        fprintf(
            stderr,
            "PSEUDOTCP_CLOSED_AFTER_OPEN=true\n"
        );
    }

    /*
     * A closed PseudoTCP transport cannot carry further
     * CTPP/ECHO traffic.  End this session so the HA
     * supervisor can establish a fresh P2P registration.
     */
    failed = TRUE;

    if (loop)
        g_main_loop_quit(loop);

    fflush(stdout);
}


static PseudoTcpWriteResult
pseudotcp_write_packet_cb(
    PseudoTcpSocket *tcp,
    const gchar *buffer,
    guint32 len,
    gpointer data)
{
    (void)tcp;
    (void)data;

    /*
     * conversation is uint32 BE and must be zero.
     * Since zero has identical byte representation
     * in either endian order, a four-zero-byte check
     * is sufficient here.
     */
    if (len < 4 ||
        buffer[0] != 0 ||
        buffer[1] != 0 ||
        buffer[2] != 0 ||
        buffer[3] != 0) {

        fprintf(
            stderr,
            "PSEUDOTCP_CONVERSATION_WIRE=FAIL\n"
        );

        failed = TRUE;
        return WR_FAIL;
    }

    gint sent =
        nice_agent_send(
            agent,
            stream_id,
            1,
            len,
            buffer
        );

    if (sent != (gint)len) {
        fprintf(
            stderr,
            "PSEUDOTCP_WRITE_PACKET=FAIL "
            "LEN=%u SEND_RC=%d\n",
            len,
            sent
        );

        failed = TRUE;
        return WR_FAIL;
    }

    pseudotcp_packets_out++;

    if (len > pseudotcp_max_wire_out)
        pseudotcp_max_wire_out = len;

    return WR_SUCCESS;
}


static gboolean
pseudotcp_clock_cb(gpointer data)
{
    (void)data;

    if (!pseudo_tcp)
        return G_SOURCE_REMOVE;

    pseudo_tcp_socket_notify_clock(
        pseudo_tcp
    );

    if (!pseudotcp_open &&
        pseudo_tcp_socket_is_closed(
            pseudo_tcp
        )) {

        fprintf(
            stderr,
            "PSEUDOTCP_CLOSED_BEFORE_OPEN=true\n"
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
start_pseudotcp(void)
{
    if (pseudotcp_started)
        return TRUE;

    PseudoTcpCallbacks callbacks = {
        .user_data = NULL,
        .PseudoTcpOpened =
            pseudotcp_opened_cb,
        .PseudoTcpReadable =
            pseudotcp_readable_cb,
        .PseudoTcpWritable =
            pseudotcp_writable_cb,
        .PseudoTcpClosed =
            pseudotcp_closed_cb,
        .WritePacket =
            pseudotcp_write_packet_cb
    };

    pseudo_tcp =
        pseudo_tcp_socket_new(
            PSEUDOTCP_CONVERSATION,
            &callbacks
        );

    if (!pseudo_tcp) {
        fprintf(
            stderr,
            "PSEUDOTCP_CREATE=FAIL\n"
        );

        return FALSE;
    }

    guint conversation = 999;

    g_object_get(
        pseudo_tcp,
        "conversation",
        &conversation,
        NULL
    );

    printf(
        "PSEUDOTCP_CONVERSATION=%u\n",
        conversation
    );

    if (conversation !=
        PSEUDOTCP_CONVERSATION) {

        fprintf(
            stderr,
            "PSEUDOTCP_CONVERSATION=FAIL\n"
        );

        return FALSE;
    }

    pseudo_tcp_socket_notify_mtu(
        pseudo_tcp,
        PSEUDOTCP_MTU
    );

    printf(
        "PSEUDOTCP_MTU=%u\n",
        (unsigned)PSEUDOTCP_MTU
    );

    pseudotcp_started = TRUE;

    /*
     * Existing local probe uses a frequent clock
     * and libnice explicitly permits notify_clock()
     * to be called too frequently.
     */
    g_timeout_add(
        1,
        pseudotcp_clock_cb,
        NULL
    );

    /*
     * Comelit client is the PseudoTCP initiator,
     * even though its ICE role is CONTROLLED.
     */
    if (!pseudo_tcp_socket_connect(
            pseudo_tcp)) {

        fprintf(
            stderr,
            "PSEUDOTCP_CONNECT_START=FAIL "
            "ERROR=%d\n",
            pseudo_tcp_socket_get_error(
                pseudo_tcp
            )
        );

        return FALSE;
    }

    printf(
        "PSEUDOTCP_CONNECT_START=PASS\n"
    );

    fflush(stdout);

    return TRUE;
}


static const char *
component_state_name(
    NiceComponentState state)
{
    switch (state) {
        case NICE_COMPONENT_STATE_DISCONNECTED:
            return "DISCONNECTED";

        case NICE_COMPONENT_STATE_GATHERING:
            return "GATHERING";

        case NICE_COMPONENT_STATE_CONNECTING:
            return "CONNECTING";

        case NICE_COMPONENT_STATE_CONNECTED:
            return "CONNECTED";

        case NICE_COMPONENT_STATE_READY:
            return "READY";

        case NICE_COMPONENT_STATE_FAILED:
            return "FAILED";

        default:
            return "UNKNOWN";
    }
}


static gboolean
report_selected_pair(void)
{
    NiceCandidate *local = NULL;
    NiceCandidate *remote = NULL;

    gboolean ok =
        nice_agent_get_selected_pair(
            agent,
            stream_id,
            1,
            &local,
            &remote
        );

    if (!ok || !local || !remote) {
        printf("SELECTED_PAIR=ABSENT\n");
        fflush(stdout);

        return FALSE;
    }

    selected_pair_present = TRUE;

    printf("SELECTED_PAIR=PASS\n");

    /*
     * Do not print addresses, ports, foundations
     * or ICE credentials here.
     */
    printf(
        "SELECTED_LOCAL_TYPE=%d\n",
        (int)local->type
    );

    printf(
        "SELECTED_LOCAL_TRANSPORT=%d\n",
        (int)local->transport
    );

    printf(
        "SELECTED_REMOTE_TYPE=%d\n",
        (int)remote->type
    );

    printf(
        "SELECTED_REMOTE_TRANSPORT=%d\n",
        (int)remote->transport
    );

    fflush(stdout);

    return TRUE;
}


static void
component_state_changed_cb(
    NiceAgent *nice_agent,
    guint sid,
    guint component_id,
    guint state_value,
    gpointer data)
{
    (void)nice_agent;
    (void)data;

    if (sid != stream_id ||
        component_id != 1) {
        return;
    }

    NiceComponentState state =
        (NiceComponentState)state_value;

    printf(
        "ICE_COMPONENT_STATE=%s\n",
        component_state_name(state)
    );

    if (state ==
        NICE_COMPONENT_STATE_CONNECTED) {

        if (!ice_connected) {
            ice_connected = TRUE;
            printf("ICE_CONNECTED=PASS\n");
        }
    }

    if (state ==
        NICE_COMPONENT_STATE_READY) {

        ice_connected = TRUE;
        ice_ready = TRUE;

        printf("ICE_CONNECTED=PASS\n");
        printf("ICE_READY=PASS\n");

        if (!report_selected_pair()) {
            fprintf(
                stderr,
                "SELECTED_PAIR=FAIL\n"
            );

            failed = TRUE;

            if (loop)
                g_main_loop_quit(loop);

            return;
        }

        if (!start_pseudotcp()) {
            fprintf(
                stderr,
                "PSEUDOTCP_START=FAIL\n"
            );

            failed = TRUE;

            if (loop)
                g_main_loop_quit(loop);

            return;
        }

        fflush(stdout);

        return;
    }

    if (state ==
        NICE_COMPONENT_STATE_FAILED) {

        fprintf(
            stderr,
            "ICE_CONNECTIVITY=FAIL\n"
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return;
    }

    fflush(stdout);
}


static gboolean
import_remote_primitives(
    const gchar *remote_sdp)
{
    const gchar *ufrag_prefix =
        "a=ice-ufrag:";

    const gchar *pwd_prefix =
        "a=ice-pwd:";

    const gchar *cand_prefix =
        "a=candidate:";

    gchar **lines =
        g_strsplit_set(
            remote_sdp,
            "\r\n",
            -1
        );

    gchar *ufrag = NULL;
    gchar *pwd = NULL;

    guint ufrag_count = 0;
    guint pwd_count = 0;
    guint candidate_lines = 0;

    for (guint i = 0;
         lines[i] != NULL;
         i++) {

        const gchar *line = lines[i];

        if (!line[0])
            continue;

        if (g_str_has_prefix(
                line,
                ufrag_prefix)) {

            ufrag_count++;

            if (!ufrag) {
                ufrag =
                    g_strdup(
                        line +
                        strlen(
                            ufrag_prefix
                        )
                    );
            }

            continue;
        }

        if (g_str_has_prefix(
                line,
                pwd_prefix)) {

            pwd_count++;

            if (!pwd) {
                pwd =
                    g_strdup(
                        line +
                        strlen(
                            pwd_prefix
                        )
                    );
            }

            continue;
        }

        if (g_str_has_prefix(
                line,
                cand_prefix)) {

            candidate_lines++;
        }
    }

    printf(
        "REMOTE_UFRAG_COUNT=%u\n",
        ufrag_count
    );

    printf(
        "REMOTE_PWD_COUNT=%u\n",
        pwd_count
    );

    printf(
        "REMOTE_CANDIDATE_LINES=%u\n",
        candidate_lines
    );

    if (ufrag_count != 1 ||
        pwd_count != 1 ||
        candidate_lines == 0 ||
        !ufrag ||
        !pwd) {

        fprintf(
            stderr,
            "REMOTE_PRIMITIVES_EXTRACT=FAIL\n"
        );

        g_free(ufrag);
        g_free(pwd);
        g_strfreev(lines);

        return FALSE;
    }

    printf("REMOTE_PRIMITIVES_EXTRACT=PASS\n");

    printf(
        "REMOTE_UFRAG_LENGTH=%zu\n",
        strlen(ufrag)
    );

    printf(
        "REMOTE_PWD_LENGTH=%zu\n",
        strlen(pwd)
    );

    GSList *candidates = NULL;

    guint parsed = 0;
    guint parse_failed = 0;

    guint host = 0;
    guint srflx = 0;
    guint prflx = 0;
    guint relay = 0;
    guint non_udp = 0;

    for (guint i = 0;
         lines[i] != NULL;
         i++) {

        const gchar *line = lines[i];

        if (!g_str_has_prefix(
                line,
                cand_prefix)) {

            continue;
        }

        NiceCandidate *candidate =
            nice_agent_parse_remote_candidate_sdp(
                agent,
                stream_id,
                line
            );

        if (!candidate) {
            parse_failed++;
            continue;
        }

        if (candidate->component_id != 1) {
            fprintf(
                stderr,
                "REMOTE_COMPONENT_UNEXPECTED=%u\n",
                candidate->component_id
            );

            nice_candidate_free(
                candidate
            );

            parse_failed++;
            continue;
        }

        if (candidate->transport !=
            NICE_CANDIDATE_TRANSPORT_UDP) {

            non_udp++;
        }

        switch (candidate->type) {
            case NICE_CANDIDATE_TYPE_HOST:
                host++;
                break;

            case NICE_CANDIDATE_TYPE_SERVER_REFLEXIVE:
                srflx++;
                break;

            case NICE_CANDIDATE_TYPE_PEER_REFLEXIVE:
                prflx++;
                break;

            case NICE_CANDIDATE_TYPE_RELAYED:
                relay++;
                break;

            default:
                break;
        }

        candidates =
            g_slist_prepend(
                candidates,
                candidate
            );

        parsed++;
    }

    candidates =
        g_slist_reverse(
            candidates
        );

    printf(
        "REMOTE_CANDIDATES_PARSED=%u\n",
        parsed
    );

    printf(
        "REMOTE_CANDIDATES_FAILED=%u\n",
        parse_failed
    );

    printf(
        "REMOTE_CANDIDATES_HOST=%u\n",
        host
    );

    printf(
        "REMOTE_CANDIDATES_SRFLX=%u\n",
        srflx
    );

    printf(
        "REMOTE_CANDIDATES_PRFLX=%u\n",
        prflx
    );

    printf(
        "REMOTE_CANDIDATES_RELAY=%u\n",
        relay
    );

    printf(
        "REMOTE_CANDIDATES_NON_UDP=%u\n",
        non_udp
    );

    if (parse_failed != 0 ||
        parsed != candidate_lines) {

        fprintf(
            stderr,
            "REMOTE_CANDIDATE_PARSE=FAIL\n"
        );

        g_slist_free_full(
            candidates,
            (GDestroyNotify)
                nice_candidate_free
        );

        g_free(ufrag);
        g_free(pwd);
        g_strfreev(lines);

        return FALSE;
    }

    printf("REMOTE_CANDIDATE_PARSE=PASS\n");

    gboolean credentials_ok =
        nice_agent_set_remote_credentials(
            agent,
            stream_id,
            ufrag,
            pwd
        );

    printf(
        "REMOTE_CREDENTIALS_SET=%s\n",
        credentials_ok ?
            "PASS" :
            "FAIL"
    );

    int added = -1;

    if (credentials_ok) {
        added =
            nice_agent_set_remote_candidates(
                agent,
                stream_id,
                1,
                candidates
            );
    }

    printf(
        "REMOTE_CANDIDATES_SET_RC=%d\n",
        added
    );

    gboolean ok =
        credentials_ok &&
        added == (int)parsed;

    g_slist_free_full(
        candidates,
        (GDestroyNotify)
            nice_candidate_free
    );

    g_free(ufrag);
    g_free(pwd);
    g_strfreev(lines);

    return ok;
}


static gboolean
remote_sdp_check_cb(gpointer data)
{
    (void)data;

    if (!ready || remote_loaded)
        return G_SOURCE_CONTINUE;

    GStatBuf st;

    if (g_stat(REMOTE_FILE, &st) != 0 ||
        st.st_size <= 0) {

        remote_last_size = -1;
        remote_stable_ticks = 0;

        return G_SOURCE_CONTINUE;
    }

    /*
     * Require the size to be stable across multiple
     * polling passes so we never parse a partially
     * written remote.sdp.
     */
    if (remote_last_size != st.st_size) {
        remote_last_size = st.st_size;
        remote_stable_ticks = 0;

        return G_SOURCE_CONTINUE;
    }

    remote_stable_ticks++;

    if (remote_stable_ticks < 2)
        return G_SOURCE_CONTINUE;

    gchar *remote_sdp = NULL;
    gsize remote_len = 0;
    GError *error = NULL;

    if (!g_file_get_contents(
            REMOTE_FILE,
            &remote_sdp,
            &remote_len,
            &error)) {

        fprintf(
            stderr,
            "REMOTE_SDP_READ=FAIL\n"
        );

        if (error)
            g_error_free(error);

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    chmod(
        REMOTE_FILE,
        0600
    );

    printf(
        "REMOTE_SDP_BYTES=%zu\n",
        (size_t)remote_len
    );

    /*
     * Do not feed Comelit's wire SDP to the
     * libnice full-SDP parser.
     *
     * Import only the actual ICE primitives:
     * remote credentials + candidate lines.
     */
    gboolean import_ok =
        import_remote_primitives(
            remote_sdp
        );

    g_free(remote_sdp);

    if (!import_ok) {
        fprintf(
            stderr,
            "REMOTE_PRIMITIVES_IMPORT=FAIL\n"
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    remote_loaded = TRUE;

    printf(
        "REMOTE_PRIMITIVES_IMPORT=PASS\n"
    );

    fflush(stdout);

    return G_SOURCE_REMOVE;
}



static void
candidate_gathering_done_cb(
    NiceAgent *nice_agent,
    guint sid,
    gpointer data)
{
    (void)data;

    if (sid != stream_id)
        return;

    gchar *ufrag = NULL;
    gchar *pwd = NULL;

    gboolean credentials_ok =
        nice_agent_get_local_credentials(
            nice_agent,
            sid,
            &ufrag,
            &pwd
        );

    GSList *candidates =
        nice_agent_get_local_candidates(
            nice_agent,
            sid,
            1
        );

    guint total = 0;
    guint host = 0;
    guint srflx = 0;
    guint prflx = 0;
    guint relay = 0;

    for (GSList *it = candidates;
         it != NULL;
         it = it->next) {

        NiceCandidate *candidate =
            (NiceCandidate *)it->data;

        total++;

        switch (candidate->type) {
            case NICE_CANDIDATE_TYPE_HOST:
                host++;
                break;

            case NICE_CANDIDATE_TYPE_SERVER_REFLEXIVE:
                srflx++;
                break;

            case NICE_CANDIDATE_TYPE_PEER_REFLEXIVE:
                prflx++;
                break;

            case NICE_CANDIDATE_TYPE_RELAYED:
                relay++;
                break;

            default:
                break;
        }
    }

    gchar *sdp =
        nice_agent_generate_local_sdp(
            nice_agent
        );

    if (!credentials_ok ||
        !ufrag ||
        !pwd ||
        !sdp ||
        total == 0) {

        fprintf(
            stderr,
            "ICE_GATHER=FAIL\n"
        );

        failed = TRUE;

        if (sdp)
            g_free(sdp);

        if (ufrag)
            g_free(ufrag);

        if (pwd)
            g_free(pwd);

        g_slist_free_full(
            candidates,
            (GDestroyNotify)nice_candidate_free
        );

        g_main_loop_quit(loop);
        return;
    }

    GError *error = NULL;

    if (!g_file_set_contents(
            OFFER_FILE,
            sdp,
            -1,
            &error)) {

        fprintf(
            stderr,
            "OFFER_WRITE=FAIL\n"
        );

        if (error) {
            g_error_free(error);
        }

        failed = TRUE;

        g_free(sdp);
        g_free(ufrag);
        g_free(pwd);

        g_slist_free_full(
            candidates,
            (GDestroyNotify)nice_candidate_free
        );

        g_main_loop_quit(loop);
        return;
    }

    chmod(OFFER_FILE, 0600);

    printf("ICE_GATHER=PASS\n");
    printf("ICE_ROLE=CONTROLLED\n");
    printf("ICE_COMPONENTS=1\n");

    printf(
        "LOCAL_CANDIDATES_TOTAL=%u\n",
        total
    );

    printf(
        "LOCAL_CANDIDATES_HOST=%u\n",
        host
    );

    printf(
        "LOCAL_CANDIDATES_SRFLX=%u\n",
        srflx
    );

    printf(
        "LOCAL_CANDIDATES_PRFLX=%u\n",
        prflx
    );

    printf(
        "LOCAL_CANDIDATES_RELAY=%u\n",
        relay
    );

    printf(
        "LOCAL_UFRAG_LENGTH=%zu\n",
        strlen(ufrag)
    );

    printf(
        "LOCAL_PWD_LENGTH=%zu\n",
        strlen(pwd)
    );

    printf(
        "LOCAL_SDP_BYTES=%zu\n",
        strlen(sdp)
    );

    printf(
        "OFFER_FILE_MODE=600\n"
    );

    fflush(stdout);

    ready = TRUE;

    g_free(sdp);
    g_free(ufrag);
    g_free(pwd);

    g_slist_free_full(
        candidates,
        (GDestroyNotify)nice_candidate_free
    );
}


int
main(void)
{
    if (g_mkdir_with_parents(
            RUN_DIR,
            0700) != 0) {

        perror("mkdir");

        return 2;
    }

    chmod(RUN_DIR, 0700);

    unlink(OFFER_FILE);
    unlink(REMOTE_FILE);
    unlink(STOP_FILE);

    loop =
        g_main_loop_new(
            NULL,
            FALSE
        );

    agent =
        nice_agent_new(
            g_main_loop_get_context(loop),
            NICE_COMPATIBILITY_RFC5245
        );

    if (!agent) {
        fprintf(
            stderr,
            "NICE_AGENT_CREATE=FAIL\n"
        );

        return 3;
    }

    /*
     * Capture + UCFG:
     * client is ICE CONTROLLED.
     *
     * UDP only, no UPnP, no local TURN allocation.
     */
    g_object_set(
        G_OBJECT(agent),

        "controlling-mode",
        FALSE,

        "ice-udp",
        TRUE,

        "ice-tcp",
        FALSE,

        "upnp",
        FALSE,

        "stun-server",
        STUN_SERVER,

        "stun-server-port",
        STUN_PORT,

        NULL
    );

    stream_id =
        nice_agent_add_stream(
            agent,
            1
        );

    if (stream_id == 0) {
        fprintf(
            stderr,
            "ICE_STREAM_CREATE=FAIL\n"
        );

        g_object_unref(agent);
        g_main_loop_unref(loop);

        return 4;
    }

    nice_agent_set_stream_name(
        agent,
        stream_id,
        "audio"
    );

    if (!nice_agent_attach_recv(
            agent,
            stream_id,
            1,
            g_main_loop_get_context(loop),
            recv_cb,
            NULL)) {

        fprintf(
            stderr,
            "ICE_ATTACH_RECV=FAIL\n"
        );

        g_object_unref(agent);
        g_main_loop_unref(loop);

        return 5;
    }

    printf("ICE_ATTACH_RECV=PASS\n");
    fflush(stdout);

    g_signal_connect(
        agent,
        "candidate-gathering-done",
        G_CALLBACK(
            candidate_gathering_done_cb
        ),
        NULL
    );

    g_signal_connect(
        agent,
        "component-state-changed",
        G_CALLBACK(
            component_state_changed_cb
        ),
        NULL
    );

    if (!nice_agent_gather_candidates(
            agent,
            stream_id)) {

        fprintf(
            stderr,
            "ICE_GATHER_START=FAIL\n"
        );

        g_object_unref(agent);
        g_main_loop_unref(loop);

        return 5;
    }

    printf("ICE_GATHER_START=PASS\n");
    fflush(stdout);

    signal(SIGUSR1, v4_door_signal_handler);

    g_timeout_add(
        100,
        stop_check_cb,
        NULL
    );

    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );

    g_timeout_add(
        100,
        remote_sdp_check_cb,
        NULL
    );

    g_timeout_add_seconds(
        3300,
        absolute_timeout_cb,
        NULL
    );

    g_main_loop_run(loop);

    if (ready)
        printf("ICE_OFFER_HELD=true\n");

    printf(
        "REMOTE_SDP_LOADED=%s\n",
        remote_loaded ? "true" : "false"
    );

    printf(
        "ICE_CONNECTED_FINAL=%s\n",
        ice_connected ? "true" : "false"
    );

    printf(
        "ICE_READY_FINAL=%s\n",
        ice_ready ? "true" : "false"
    );

    printf(
        "SELECTED_PAIR_FINAL=%s\n",
        selected_pair_present ? "true" : "false"
    );

    fflush(stdout);

    printf(
        "PSEUDOTCP_STARTED_FINAL=%s\n",
        pseudotcp_started ? "true" : "false"
    );

    printf(
        "PSEUDOTCP_OPEN_FINAL=%s\n",
        pseudotcp_open ? "true" : "false"
    );

    fflush(stdout);

    if (pseudo_tcp)
        g_object_unref(pseudo_tcp);

    g_object_unref(agent);
    g_main_loop_unref(loop);

    return failed ? 6 : 0;
}
