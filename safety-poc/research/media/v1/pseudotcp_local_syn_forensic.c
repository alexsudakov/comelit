#include <glib.h>
#include <nice/pseudotcp.h>
#include <stdint.h>
#include <stdio.h>

#define EXPECTED_CONVERSATION 0u
#define EXPECTED_MTU 1320u
#define PSEUDOTCP_HEADER_LEN 24u
#define PSEUDOTCP_FLAG_CTL 0x02u

static guint write_count = 0;
static gboolean first_packet_seen = FALSE;
static gboolean first_packet_matches_official = FALSE;

static guint32 read_be32(const guint8 *p)
{
    return ((guint32)p[0] << 24) |
           ((guint32)p[1] << 16) |
           ((guint32)p[2] << 8) |
           (guint32)p[3];
}

static guint16 read_be16(const guint8 *p)
{
    return (guint16)(((guint16)p[0] << 8) | (guint16)p[1]);
}

static void opened_cb(PseudoTcpSocket *tcp, gpointer data)
{
    (void)tcp;
    (void)data;
    printf("LOCAL_SYN_UNEXPECTED_OPEN=true\n");
}

static void readable_cb(PseudoTcpSocket *tcp, gpointer data)
{
    (void)tcp;
    (void)data;
    printf("LOCAL_SYN_UNEXPECTED_READABLE=true\n");
}

static void writable_cb(PseudoTcpSocket *tcp, gpointer data)
{
    (void)tcp;
    (void)data;
    printf("LOCAL_SYN_WRITABLE_CALLBACK=true\n");
}

static void closed_cb(PseudoTcpSocket *tcp, guint32 error, gpointer data)
{
    (void)tcp;
    (void)data;
    printf("LOCAL_SYN_UNEXPECTED_CLOSED=true ERROR=%u\n", error);
}

static PseudoTcpWriteResult write_packet_cb(
    PseudoTcpSocket *tcp,
    const gchar *buffer,
    guint32 len,
    gpointer data)
{
    (void)tcp;
    (void)data;

    write_count++;

    if (write_count != 1)
        return WR_SUCCESS;

    first_packet_seen = TRUE;

    if (len < PSEUDOTCP_HEADER_LEN) {
        printf("LOCAL_SYN_FIRST_WIRE_LEN=%u\n", len);
        printf("LOCAL_SYN_FIRST_PARSE=FAIL_SHORT\n");
        return WR_SUCCESS;
    }

    const guint8 *p = (const guint8 *)buffer;
    guint32 conversation = read_be32(p + 0);
    guint32 sequence = read_be32(p + 4);
    guint32 acknowledgment = read_be32(p + 8);
    guint8 control = p[12];
    guint8 flags = p[13];
    guint16 window = read_be16(p + 14);
    guint32 data_len = len - PSEUDOTCP_HEADER_LEN;

    printf("LOCAL_SYN_FIRST_WIRE_LEN=%u\n", len);
    printf("LOCAL_SYN_FIRST_CONVERSATION=%u\n", conversation);
    printf("LOCAL_SYN_FIRST_SEQUENCE=%u\n", sequence);
    printf("LOCAL_SYN_FIRST_ACKNOWLEDGMENT=%u\n", acknowledgment);
    printf("LOCAL_SYN_FIRST_CONTROL=0x%02x\n", control);
    printf("LOCAL_SYN_FIRST_FLAGS=0x%02x\n", flags);
    printf("LOCAL_SYN_FIRST_WINDOW=%u\n", window);
    printf("LOCAL_SYN_FIRST_DATA_LEN=%u\n", data_len);
    printf("LOCAL_SYN_RAW_PAYLOAD_EMITTED=false\n");

    /*
     * Both official Android captures have the same first client PseudoTCP
     * structural signature:
     *   wire_len=31, seq=0, ack=0, control=0x00, flags=CTL, data_len=7.
     * No endpoint, credential or raw-payload comparison is required here.
     */
    first_packet_matches_official =
        len == 31u &&
        conversation == EXPECTED_CONVERSATION &&
        sequence == 0u &&
        acknowledgment == 0u &&
        control == 0u &&
        flags == PSEUDOTCP_FLAG_CTL &&
        data_len == 7u;

    printf(
        "LOCAL_SYN_OFFICIAL_STRUCTURAL_MATCH=%s\n",
        first_packet_matches_official ? "PASS" : "FAIL"
    );
    fflush(stdout);

    return WR_SUCCESS;
}

int main(void)
{
    PseudoTcpCallbacks callbacks = {
        .user_data = NULL,
        .PseudoTcpOpened = opened_cb,
        .PseudoTcpReadable = readable_cb,
        .PseudoTcpWritable = writable_cb,
        .PseudoTcpClosed = closed_cb,
        .WritePacket = write_packet_cb,
    };

    PseudoTcpSocket *tcp = pseudo_tcp_socket_new(
        EXPECTED_CONVERSATION,
        &callbacks
    );

    if (!tcp) {
        fprintf(stderr, "LOCAL_SYN_SOCKET_CREATE=FAIL\n");
        return 2;
    }

    pseudo_tcp_socket_notify_mtu(tcp, EXPECTED_MTU);

    guint state_before = 999u;
    g_object_get(tcp, "state", &state_before, NULL);
    printf("LOCAL_SYN_STATE_BEFORE_CONNECT=%u\n", state_before);
    printf("LOCAL_SYN_MTU=%u\n", EXPECTED_MTU);

    gboolean connect_ok = pseudo_tcp_socket_connect(tcp);
    printf("LOCAL_SYN_CONNECT_CALL=%s\n", connect_ok ? "PASS" : "FAIL");

    if (!first_packet_seen)
        pseudo_tcp_socket_notify_clock(tcp);

    guint state_after = 999u;
    g_object_get(tcp, "state", &state_after, NULL);
    printf("LOCAL_SYN_STATE_AFTER_CONNECT=%u\n", state_after);
    printf("LOCAL_SYN_WRITE_COUNT=%u\n", write_count);
    printf("NETWORK_IO_PERFORMED=false\n");
    printf("HOME_ASSISTANT_TOUCHED=false\n");
    printf("DOOR_ACTION_SENT=false\n");
    printf("SELF_ACTIVATION_SENT=false\n");
    printf("MEDIA_SIGNALING_SENT=false\n");

    gboolean pass =
        connect_ok &&
        first_packet_seen &&
        first_packet_matches_official &&
        state_before == PSEUDO_TCP_LISTEN &&
        state_after == PSEUDO_TCP_SYN_SENT;

    printf("LOCAL_PSEUDOTCP_SYN_FORENSIC=%s\n", pass ? "PASS" : "FAIL");
    fflush(stdout);

    g_object_unref(tcp);
    return pass ? 0 : 1;
}
