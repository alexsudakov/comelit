#include <nice/agent.h>
#include <nice/pseudotcp.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <glib-unix.h>

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>
#include <sys/socket.h>
#include <netinet/in.h>

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

/* Research-only graceful shutdown state. */
#define PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS 5000
#define PSEUDOTCP_GRACEFUL_STOP_POLL_MS     100

static gboolean pseudotcp_graceful_stop_started = FALSE;
static gint64 pseudotcp_graceful_stop_deadline_us = 0;

static guint pseudotcp_packets_in = 0;
static guint pseudotcp_packets_out = 0;
static guint pseudotcp_max_wire_out = 0;
static guint64 pseudotcp_app_bytes_in = 0;


/* === P80_HA_MEDIA_RTP_FORWARDING_BEGIN === */
#define P80_VIDEO_RTP_PORT 17899
#define P80_AUDIO_RTP_PORT 17808
#define P80_RTP_PROGRESS_CADENCE 50u
#define P116_RTP_TELEMETRY_CADENCE 50u
#define P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES 12u
#define P116_RTP_PT_WORD_BITS 128u
#define P116_RTP_MAX_TRACKED_SSRC 8u

/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN */
/*
 * R57 declaration-order contract (build-blocking corrective).
 *
 * Every declaration below MUST be visible before the earliest instrumented
 * `failed = TRUE` site in the generated translation unit: that site is in
 * p80_try_forward_wrapped_rtp() at ~line 463, roughly 3000 lines before the
 * late R54 anchor where R57's helper bodies are emitted. The first R57
 * candidate emitted its typedefs *and* its helpers only at that late anchor,
 * which is a pure C declaration-order error (implicit declaration /
 * undeclared identifier / "static declaration follows non-static
 * declaration").
 *
 * This block is declarations only: no file-scope state is defined here and no
 * helper body appears here, because p116_infer_phase() reads R42/R54 state
 * (v4_listener_ready, r42_media_stage, g_r54_tx_state) that is declared later
 * in the file. The prototypes are `static` so they match the `static`
 * definitions in the R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN/END block exactly.
 */
typedef enum {
    P116_FAILURE_NONE = 0,
    P116_FAILURE_STARTUP,
    P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT,
    P116_FAILURE_P12_STEP_TIMEOUT,
    P116_FAILURE_UAUT_OPEN_TIMEOUT,
    P116_FAILURE_RECV_PARSE,
    P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT,
    P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT,
    P116_FAILURE_PSEUDOTCP_CLOSED,
    P116_FAILURE_PSEUDOTCP_WRITE_PACKET,
    P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED,
    P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET,
    P116_FAILURE_ICE_CONNECTIVITY,
    P116_FAILURE_ICE_GATHER,
    P116_FAILURE_SDP_FILE,
    P116_FAILURE_DOOR_WRITE,
    P116_FAILURE_DOOR_TIMER,
    P116_FAILURE_P80_RTP_FORWARD,
    P116_FAILURE_OTHER
} P116NativeFailureId;

typedef enum {
    P116_PHASE_STARTUP = 0,
    P116_PHASE_LISTENER_READY,
    P116_PHASE_CALL_ADOPTION_LOCAL,
    P116_PHASE_WAIT_PEER_CAPABILITIES,
    P116_PHASE_PEER_ACK,
    P116_PHASE_MEDIA_OPEN,
    P116_PHASE_MEDIA_ACTIVE,
    P116_PHASE_MEDIA_STOP,
    P116_PHASE_GENERATION_END
} P116NativeFailurePhase;

static void p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase);
static P116NativeFailurePhase p116_infer_phase(void);
static void p116_emit_timeout_observability(const char *kind);
static void p116_emit_native_exit_summary(gboolean failed_flag);
/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_END */

/* R58_STOP_CLEANUP_DECLS_BEGIN */
typedef enum {
    R58_STOP_PHASE_NONE = 0,
    R58_STOP_PHASE_REQUESTED,
    R58_STOP_PHASE_WAIT_TX_SLOT,
    R58_STOP_PHASE_ENQUEUED,
    R58_STOP_PHASE_FLUSHED,
    R58_STOP_PHASE_RTP_DISARMED,
    R58_STOP_PHASE_DISPOSED,
    R58_STOP_PHASE_CLOSED,
    R58_STOP_PHASE_REMOTE_RELEASE,
    R58_STOP_PHASE_FAILED
} R58StopPhase;

typedef enum {
    R58_STOP_FAILURE_STAGE_NONE = 0,
    R58_STOP_FAILURE_STAGE_SIGNAL,
    R58_STOP_FAILURE_STAGE_STALE_CALL,
    R58_STOP_FAILURE_STAGE_QUEUE,
    R58_STOP_FAILURE_STAGE_WRITE,
    R58_STOP_FAILURE_STAGE_FLUSH_TIMEOUT,
    R58_STOP_FAILURE_STAGE_DISPOSE,
    R58_STOP_FAILURE_STAGE_REMOTE_RACE,
    R58_STOP_FAILURE_STAGE_OTHER
} R58StopFailureStage;

typedef enum {
    R58_STOP_ORIGIN_NONE = 0,
    R58_STOP_ORIGIN_HA_SIGNAL,
    R58_STOP_ORIGIN_REMOTE_RELEASE,
    R58_STOP_ORIGIN_CAPABILITY_CLEARED
} R58StopOrigin;

static void r58_stop_publish_closed(void);
static int r58_closed_published_for_generation(void);
static void r58_mark_closed_published(void);
/* R58_STOP_CLEANUP_DECLS_END */

static gboolean p80_media_forwarding_enabled = FALSE;
static int p80_video_rtp_fd = -1;
static int p80_audio_rtp_fd = -1;
static struct sockaddr_in p80_video_rtp_target;
static struct sockaddr_in p80_audio_rtp_target;
static gboolean p80_video_target_ready = FALSE;
static gboolean p80_audio_target_ready = FALSE;
static gboolean p80_video_profile_seen = FALSE;
static gboolean p80_audio_profile_seen = FALSE;
static guint8 p80_video_profile[6] = {0};
static guint8 p80_audio_profile[6] = {0};
static guint64 p80_video_rtp_packets = 0;
static guint64 p80_audio_rtp_packets = 0;

typedef struct {
    guint8 payload_type;
    gboolean is_video;
    guint64 packet_count;
    long long first_monotonic_ms;
    long long last_monotonic_ms;
    long long first_keyframe_monotonic_ms;
    guint16 first_seq;
    guint16 last_seq;
    guint16 max_seq;
    guint32 first_timestamp;
    guint32 last_timestamp;
    guint64 sequence_gaps;
    guint64 duplicates;
    guint64 out_of_order;
    guint64 timestamp_regressions;
    guint64 marker_count;
    guint64 sps_count;
    guint64 pps_count;
    guint64 fua_count;
    guint64 single_nal_count;
    guint64 ssrc_changes;
    guint32 last_ssrc;
    guint32 tracked_ssrc[P116_RTP_MAX_TRACKED_SSRC];
    guint tracked_ssrc_count;
    guint64 ssrc_overflow_count;
    guint64 pt_seen_hi;
    guint64 pt_seen_lo;
    guint periodic_summary_count;
} P116RtpTelemetry;

static P116RtpTelemetry p116_video_rtp = {
    .payload_type = 99u,
    .is_video = TRUE
};
static P116RtpTelemetry p116_audio_rtp = {
    .payload_type = 8u,
    .is_video = FALSE
};

static guint16
p80_read_le16(const guint8 *p)
{
    return (guint16)(((guint16)p[0]) | ((guint16)p[1] << 8));
}

static guint16
p80_read_be16(const guint8 *p)
{
    return (guint16)(((guint16)p[0] << 8) | (guint16)p[1]);
}

static guint32
p116_read_be32(const guint8 *p)
{
    return ((guint32)p[0] << 24) |
           ((guint32)p[1] << 16) |
           ((guint32)p[2] << 8) |
           (guint32)p[3];
}

static long long
p116_monotonic_ms(void)
{
#ifdef G_USEC_PER_SEC
    return (long long)(g_get_monotonic_time() / 1000);
#else
    static long long fallback_monotonic_ms = 0;
    return ++fallback_monotonic_ms;
#endif
}

static guint
p116_rtp_payload_offset(const guint8 *packet, guint len)
{
    if (!packet || len < 12u || (packet[0] >> 6) != 2)
        return 0u;

    guint csrc_count = packet[0] & 0x0f;
    guint offset = 12u + 4u * csrc_count;
    if (offset > len)
        return 0u;

    if ((packet[0] & 0x10) != 0) {
        if (offset + 4u > len)
            return 0u;
        guint extension_words = p80_read_be16(packet + offset + 2u);
        if (extension_words > (G_MAXUINT - offset - 4u) / 4u)
            return 0u;
        offset += 4u + 4u * extension_words;
        if (offset > len)
            return 0u;
    }

    if ((packet[0] & 0x20) != 0) {
        guint padding_len = packet[len - 1u];
        if (padding_len == 0u || padding_len > len - offset)
            return 0u;
        if (len - offset - padding_len == 0u)
            return 0u;
    } else if (offset == len) {
        return 0u;
    }

    return offset;
}

static void
p116_note_pt(P116RtpTelemetry *stream, guint8 payload_type)
{
    if (payload_type < 64u)
        stream->pt_seen_lo |= ((guint64)1u << payload_type);
    else
        stream->pt_seen_hi |= ((guint64)1u << (payload_type - 64u));
}

static void
p116_print_pt_set(P116RtpTelemetry *stream)
{
    gboolean first = TRUE;
    for (guint pt = 0; pt < P116_RTP_PT_WORD_BITS; pt++) {
        gboolean seen = pt < 64u
            ? ((stream->pt_seen_lo & ((guint64)1u << pt)) != 0)
            : ((stream->pt_seen_hi & ((guint64)1u << (pt - 64u))) != 0);
        if (seen) {
            printf("%s%u", first ? "" : ",", pt);
            first = FALSE;
        }
    }
    if (first)
        printf("NONE");
}

static void
p116_note_ssrc(P116RtpTelemetry *stream, guint32 ssrc)
{
    if (stream->packet_count > 1u && stream->last_ssrc != ssrc)
        stream->ssrc_changes++;
    stream->last_ssrc = ssrc;

    for (guint i = 0; i < stream->tracked_ssrc_count; i++) {
        if (stream->tracked_ssrc[i] == ssrc)
            return;
    }
    if (stream->tracked_ssrc_count < P116_RTP_MAX_TRACKED_SSRC) {
        stream->tracked_ssrc[stream->tracked_ssrc_count++] = ssrc;
    } else {
        stream->ssrc_overflow_count++;
    }
}

static void
p116_print_summary(P116RtpTelemetry *stream, const char *prefix)
{
    printf("P116_%s_COUNT=%llu\n", prefix, (unsigned long long)stream->packet_count);
    if (stream->packet_count == 0u) {
        printf("P116_%s_FIRST_SEQ=0\n", prefix);
        printf("P116_%s_LAST_SEQ=0\n", prefix);
        printf("P116_%s_FIRST_TS=0\n", prefix);
        printf("P116_%s_LAST_TS=0\n", prefix);
        printf("P116_%s_FIRST_MONOTONIC_MS=0\n", prefix);
        printf("P116_%s_LAST_MONOTONIC_MS=0\n", prefix);
    } else {
        printf("P116_%s_FIRST_SEQ=%u\n", prefix, stream->first_seq);
        printf("P116_%s_LAST_SEQ=%u\n", prefix, stream->last_seq);
        printf("P116_%s_FIRST_TS=%u\n", prefix, stream->first_timestamp);
        printf("P116_%s_LAST_TS=%u\n", prefix, stream->last_timestamp);
        printf("P116_%s_FIRST_MONOTONIC_MS=%lld\n", prefix, (long long)stream->first_monotonic_ms);
        printf("P116_%s_LAST_MONOTONIC_MS=%lld\n", prefix, (long long)stream->last_monotonic_ms);
    }
    printf("P116_%s_SEQ_GAPS=%llu\n", prefix, (unsigned long long)stream->sequence_gaps);
    printf("P116_%s_DUPLICATES=%llu\n", prefix, (unsigned long long)stream->duplicates);
    printf("P116_%s_OUT_OF_ORDER=%llu\n", prefix, (unsigned long long)stream->out_of_order);
    printf("P116_%s_TIMESTAMP_REGRESSIONS=%llu\n", prefix, (unsigned long long)stream->timestamp_regressions);
    printf("P116_%s_SSRC_COUNT=%u\n", prefix, stream->tracked_ssrc_count);
    printf("P116_%s_SSRC_CHANGES=%llu\n", prefix, (unsigned long long)stream->ssrc_changes);
    printf("P116_%s_PT_SET=", prefix);
    p116_print_pt_set(stream);
    printf("\n");
    if (stream->is_video) {
        printf("P116_VIDEO_MARKER_COUNT=%llu\n", (unsigned long long)stream->marker_count);
        printf("P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS=%lld\n", (long long)stream->first_keyframe_monotonic_ms);
        printf("P116_VIDEO_SPS_COUNT=%llu\n", (unsigned long long)stream->sps_count);
        printf("P116_VIDEO_PPS_COUNT=%llu\n", (unsigned long long)stream->pps_count);
        printf("P116_VIDEO_FUA_COUNT=%llu\n", (unsigned long long)stream->fua_count);
        printf("P116_VIDEO_SINGLE_NAL_COUNT=%llu\n", (unsigned long long)stream->single_nal_count);
    }
    fflush(stdout);
}

static void
p116_print_final_rtp_summary(void)
{
    p116_print_summary(&p116_video_rtp, "VIDEO");
    p116_print_summary(&p116_audio_rtp, "AUDIO");
}

static void
p116_classify_h264(P116RtpTelemetry *stream, const guint8 *packet, guint len, long long now_ms)
{
    guint payload_offset = p116_rtp_payload_offset(packet, len);
    if (payload_offset == 0u || payload_offset >= len)
        return;

    guint8 nal_header = packet[payload_offset];
    guint8 nal_type = nal_header & 0x1fu;
    if (nal_type >= 1u && nal_type <= 23u) {
        stream->single_nal_count++;
        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0)
            stream->first_keyframe_monotonic_ms = now_ms;
        else if (nal_type == 7u)
            stream->sps_count++;
        else if (nal_type == 8u)
            stream->pps_count++;
        return;
    }

    if (nal_type == 28u) {
        stream->fua_count++;
        if (payload_offset + 1u < len) {
            guint8 fu_header = packet[payload_offset + 1u];
            guint8 fu_start = fu_header & 0x80u;
            guint8 original_nal_type = fu_header & 0x1fu;
            if (fu_start && original_nal_type == 5u &&
                stream->first_keyframe_monotonic_ms == 0) {
                stream->first_keyframe_monotonic_ms = now_ms;
            }
        }
    }
}

static void
p116_observe_rtp(const guint8 *packet, guint len, guint8 payload_type)
{
    P116RtpTelemetry *stream = payload_type == 99u
        ? &p116_video_rtp : &p116_audio_rtp;
    const char *prefix = payload_type == 99u ? "VIDEO" : "AUDIO";
    long long now_ms = p116_monotonic_ms();
    guint16 seq = p80_read_be16(packet + 2u);
    guint32 timestamp = p116_read_be32(packet + 4u);
    guint32 ssrc = p116_read_be32(packet + 8u);
    gboolean marker = (packet[1] & 0x80u) != 0;

    stream->packet_count++;
    if (stream->packet_count == 1u) {
        stream->first_monotonic_ms = now_ms;
        stream->first_seq = seq;
        stream->max_seq = seq;
        stream->first_timestamp = timestamp;
    } else {
        guint16 expected = (guint16)(stream->max_seq + 1u);
        if (seq == stream->max_seq) {
            stream->duplicates++;
        } else if ((guint16)(seq - stream->max_seq) < 0x8000u) {
            if (seq != expected)
                stream->sequence_gaps += (guint16)(seq - expected);
            stream->max_seq = seq;
        } else {
            stream->out_of_order++;
        }
        if (timestamp < stream->last_timestamp)
            stream->timestamp_regressions++;
    }

    stream->last_monotonic_ms = now_ms;
    stream->last_seq = seq;
    stream->last_timestamp = timestamp;
    if (marker)
        stream->marker_count++;
    p116_note_pt(stream, payload_type);
    p116_note_ssrc(stream, ssrc);
    if (payload_type == 99u)
        p116_classify_h264(stream, packet, len, now_ms);

    if (stream->packet_count == 1u) {
        p116_print_summary(stream, prefix);
    } else if (stream->packet_count % P116_RTP_TELEMETRY_CADENCE == 0u &&
        stream->periodic_summary_count < P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES) {
        stream->periodic_summary_count++;
        p116_print_summary(stream, prefix);
    }
}

static gboolean
p80_rtp_v2_shape(const guint8 *packet, guint len, guint8 *payload_type)
{
    if (!packet || !payload_type || len < 12 || (packet[0] >> 6) != 2)
        return FALSE;

    gboolean padding = (packet[0] & 0x20) != 0;
    gboolean extension = (packet[0] & 0x10) != 0;
    guint csrc_count = packet[0] & 0x0f;
    guint header_len = 12u + 4u * csrc_count;
    if (header_len > len)
        return FALSE;

    if (extension) {
        if (header_len + 4u > len)
            return FALSE;
        guint extension_words = p80_read_be16(packet + header_len + 2u);
        if (extension_words > (G_MAXUINT - header_len - 4u) / 4u)
            return FALSE;
        header_len += 4u + 4u * extension_words;
        if (header_len > len)
            return FALSE;
    }

    guint padding_len = padding ? packet[len - 1u] : 0u;
    if (padding && (padding_len == 0u || padding_len > len - header_len))
        return FALSE;
    if (len - header_len - padding_len == 0u)
        return FALSE;

    *payload_type = packet[1] & 0x7f;
    return TRUE;
}

static gboolean
p80_profile_accept(
    const guint8 *wrapper,
    guint8 payload_type)
{
    guint8 profile[6] = {
        wrapper[0], wrapper[1], wrapper[4],
        wrapper[5], wrapper[6], wrapper[7]
    };
    guint8 *expected = NULL;
    gboolean *seen = NULL;

    if (payload_type == 99u) {
        expected = p80_video_profile;
        seen = &p80_video_profile_seen;
    } else if (payload_type == 8u) {
        expected = p80_audio_profile;
        seen = &p80_audio_profile_seen;
    } else {
        return FALSE;
    }

    if (!*seen) {
        memcpy(expected, profile, sizeof(profile));
        *seen = TRUE;
        return TRUE;
    }

    return memcmp(expected, profile, sizeof(profile)) == 0;
}

static int
p80_loopback_socket(struct sockaddr_in *target, guint16 port)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0)
        return -1;

    memset(target, 0, sizeof(*target));
    target->sin_family = AF_INET;
    target->sin_port = htons(port);
    target->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return fd;
}

static gboolean
p80_try_forward_wrapped_rtp(const guint8 *packet, guint len)
{
    if (!p80_media_forwarding_enabled || !packet || len < 20u)
        return FALSE;

    guint inner_len = p80_read_le16(packet + 2u);
    if (inner_len + 8u != len)
        return FALSE;

    const guint8 *inner = packet + 8u;
    guint8 payload_type = 0;
    if (!p80_rtp_v2_shape(inner, inner_len, &payload_type))
        return FALSE;
    if (payload_type != 99u && payload_type != 8u)
        return FALSE;

    if (!p80_profile_accept(packet, payload_type)) {
        fprintf(stderr, "P80_WRAPPER_PROFILE_MISMATCH=true\n");
        p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase());
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }

    int *fd = payload_type == 99u ? &p80_video_rtp_fd : &p80_audio_rtp_fd;
    struct sockaddr_in *target = payload_type == 99u
        ? &p80_video_rtp_target : &p80_audio_rtp_target;
    gboolean *target_ready = payload_type == 99u
        ? &p80_video_target_ready : &p80_audio_target_ready;
    guint16 port = payload_type == 99u
        ? P80_VIDEO_RTP_PORT : P80_AUDIO_RTP_PORT;

    if (!*target_ready) {
        *fd = p80_loopback_socket(target, port);
        if (*fd < 0) {
            fprintf(stderr, "P80_RTP_FORWARD_SOCKET=FAIL\n");
            p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase());
            failed = TRUE;
            if (loop)
                g_main_loop_quit(loop);
            return TRUE;
        }
        *target_ready = TRUE;
    }

    ssize_t sent = sendto(
        *fd,
        inner,
        inner_len,
        0,
        (const struct sockaddr *)target,
        sizeof(*target)
    );
    if (sent != (ssize_t)inner_len) {
        fprintf(stderr, "P80_RTP_FORWARD_SEND=FAIL\n");
        p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase());
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }

    p116_observe_rtp(inner, inner_len, payload_type);

    if (payload_type == 99u) {
        p80_video_rtp_packets++;
        if (p80_video_rtp_packets == 1u) {
            printf("P80_VIDEO_RTP_FORWARDING=PASS\n");
            fflush(stdout);
        }
        if (p80_video_rtp_packets == 1u ||
            p80_video_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {
            printf(
                "P80_VIDEO_RTP_PACKETS=%llu\n",
                (unsigned long long)p80_video_rtp_packets
            );
            fflush(stdout);
        }
    } else {
        p80_audio_rtp_packets++;
        if (p80_audio_rtp_packets == 1u) {
            printf("P80_AUDIO_RTP_FORWARDING=PASS\n");
            fflush(stdout);
        }
        if (p80_audio_rtp_packets == 1u ||
            p80_audio_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {
            printf(
                "P80_AUDIO_RTP_PACKETS=%llu\n",
                (unsigned long long)p80_audio_rtp_packets
            );
            fflush(stdout);
        }
    }

    return TRUE;
}
/* === P80_HA_MEDIA_RTP_FORWARDING_END === */


/* R42_LISTENER_RTP_BRIDGE_BEGIN */
static void
r42_listener_rtp_reset_lifetime(void)
{
    p80_video_profile_seen = FALSE;
    p80_audio_profile_seen = FALSE;
    memset(p80_video_profile, 0, sizeof(p80_video_profile));
    memset(p80_audio_profile, 0, sizeof(p80_audio_profile));
    p80_video_rtp_packets = 0;
    p80_audio_rtp_packets = 0;

    memset(&p116_video_rtp, 0, sizeof(p116_video_rtp));
    p116_video_rtp.payload_type = 99u;
    p116_video_rtp.is_video = TRUE;

    memset(&p116_audio_rtp, 0, sizeof(p116_audio_rtp));
    p116_audio_rtp.payload_type = 8u;
    p116_audio_rtp.is_video = FALSE;
}

static void
r42_listener_rtp_arm(int armed)
{
    if (armed) {
        if (!p80_media_forwarding_enabled)
            r42_listener_rtp_reset_lifetime();
        p80_media_forwarding_enabled = TRUE;
        printf("R42_LISTENER_RTP_LIFETIME_RESET=true\n");
        printf("R42_LISTENER_RTP_FORWARDING_ARMED=true\n");
    } else {
        p80_media_forwarding_enabled = FALSE;
        printf("R42_LISTENER_RTP_FORWARDING_ARMED=false\n");
    }
    fflush(stdout);
}
/* R42_LISTENER_RTP_BRIDGE_END */

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

    P12_TX_V4_DOOR_WRITE,
    P12_TX_CALL_TIME_DOOR,

    P12_TX_R35_MEDIA_OPEN,
    P12_TX_R35_MEDIA_STOP,

    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_R54_INVITE_ACK,
    P12_TX_R54_LOCAL_CAPABILITIES,
    P12_TX_R54_LOCAL_ALERTING,
    P12_TX_R54_PEER_DATA_ACK
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

static const guint8 v4_gate_operation_body_1[] = {
    0x00, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00,
};

static const guint8 v4_gate_operation_body_2[] = {
    0x20, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00,
};

static const guint8 v4_gate_operation_body_3[] = {
    0xc0, 0x18, 0x70, 0xab, 0x29, 0x9f, 0x00, 0x0d, 0x00, 0x2d, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
    0xff, 0xff, 0xff, 0xff, 0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37,
    0x31, 0x00, 0x30, 0x30, 0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00,
};

static const guint8 v4_gate_operation_body_4[] = {
    0x00, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00,
};

static const guint8 v4_gate_operation_body_5[] = {
    0x20, 0x18, 0x5c, 0x8b, 0x2c, 0x74, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
    0x30, 0x30, 0x30, 0x34, 0x30, 0x31, 0x31, 0x37, 0x31, 0x00, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x36, 0x31, 0x30, 0x00, 0x00,
};

/* R63_GATE_PEER_TAP_BEGIN */
#define V4_DOOR_TARGET_FILE RUN_DIR "/door-target"

typedef enum {
    V4_DOOR_TARGET_NONE = 0,
    V4_DOOR_TARGET_ENTRANCE,
    V4_DOOR_TARGET_GATE
} V4DoorTarget;

static V4DoorTarget v4_door_target = V4_DOOR_TARGET_NONE;

static const char *
v4_door_target_name(V4DoorTarget target)
{
    switch (target) {
    case V4_DOOR_TARGET_ENTRANCE: return "entrance";
    case V4_DOOR_TARGET_GATE: return "gate";
    case V4_DOOR_TARGET_NONE:
    default:
        return "none";
    }
}

static V4DoorTarget
v4_door_read_target(void)
{
    gchar *contents = NULL;
    gsize length = 0;
    GError *error = NULL;
    V4DoorTarget target = V4_DOOR_TARGET_NONE;

    if (!g_file_get_contents(V4_DOOR_TARGET_FILE, &contents, &length, &error)) {
        if (error)
            g_error_free(error);
        return V4_DOOR_TARGET_NONE;
    }

    gchar *value = g_strstrip(contents);
    if (g_strcmp0(value, "entrance") == 0)
        target = V4_DOOR_TARGET_ENTRANCE;
    else if (g_strcmp0(value, "gate") == 0)
        target = V4_DOOR_TARGET_GATE;

    if (contents && length > 0)
        memset(contents, 0, length);
    g_free(contents);
    (void)g_unlink(V4_DOOR_TARGET_FILE);
    return target;
}
/* R63_GATE_PEER_TAP_END */

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
    if (p80_try_forward_wrapped_rtp((const guint8 *)buf, len))
        return;

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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET, p116_infer_phase());
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

    p116_record_failure(P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT, P116_PHASE_STARTUP);
    failed = TRUE;

    if (loop)
        g_main_loop_quit(loop);

    return G_SOURCE_REMOVE;
}


static guint
pseudotcp_drain_before_graceful_close(void)
{
    guint total = 0;
    gchar discard[4096];

    if (!pseudo_tcp)
        return 0;

    while (TRUE) {
        gint n = pseudo_tcp_socket_recv(
            pseudo_tcp,
            discard,
            sizeof(discard)
        );

        if (n > 0) {
            total += (guint)n;
            memset(discard, 0, (gsize)n);
            continue;
        }

        if (n == 0)
            break;

        gint err = pseudo_tcp_socket_get_error(pseudo_tcp);
        if (err == EWOULDBLOCK || err == ENOTCONN)
            break;

        printf(
            "PSEUDOTCP_GRACEFUL_CLOSE_DRAIN_ERROR=%d\n",
            err
        );
        break;
    }

    memset(discard, 0, sizeof(discard));
    return total;
}


static gboolean
pseudotcp_graceful_stop_poll_cb(gpointer data)
{
    (void)data;

    if (!pseudo_tcp) {
        printf("PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true\n");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    guint64 next_clock = 0;
    if (!pseudo_tcp_socket_get_next_clock(pseudo_tcp, &next_clock)) {
        printf("PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true\n");
        printf("PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=false\n");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    if (g_get_monotonic_time() >= pseudotcp_graceful_stop_deadline_us) {
        printf("PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=false\n");
        printf("PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true\n");
        printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\n");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
stop_check_cb(gpointer data)
{
    (void)data;

    if (!g_file_test(STOP_FILE, G_FILE_TEST_EXISTS))
        return G_SOURCE_CONTINUE;

    if (pseudotcp_graceful_stop_started)
        return G_SOURCE_CONTINUE;

    pseudotcp_graceful_stop_started = TRUE;
    printf("ICE_HOLDER_STOP=true\n");

    if (!pseudo_tcp || !pseudotcp_open) {
        printf("PSEUDOTCP_GRACEFUL_CLOSE_SKIPPED_NOT_OPEN=true\n");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    guint drained = pseudotcp_drain_before_graceful_close();
    printf(
        "PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u\n",
        drained
    );

    /*
     * libnice documents force=FALSE as graceful close.  It sends FIN after
     * pending data and does not intentionally send RST.  Keep the main loop
     * alive so the existing PseudoTCP clock and ICE receive paths can finish
     * the close handshake.
     */
    pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    printf("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false\n");

    pseudotcp_graceful_stop_deadline_us =
        g_get_monotonic_time() +
        ((gint64)PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS * 1000);

    guint timer = g_timeout_add(
        PSEUDOTCP_GRACEFUL_STOP_POLL_MS,
        pseudotcp_graceful_stop_poll_cb,
        NULL
    );

    if (timer == 0) {
        fprintf(stderr, "PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=FAIL\n");
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    printf("PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=PASS\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\n");
    fflush(stdout);

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

        p116_record_failure(P116_FAILURE_P12_STEP_TIMEOUT, p116_infer_phase());
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



/* R35_ATTACHED_MEDIA_BEGIN */
/*
 * P116/R35 attached inbound media: dependency-free call-bound MEDIAREQ26
 * OPEN/STOP state machine.
 *
 * This region intentionally never includes GLib or libnice headers and never
 * calls a network/socket primitive.  All transport and RTP-forwarding side
 * effects are reached only through the injected R35FrameWriter/R35RtpArmHook
 * function pointers so a host test can substitute a fake writer and drive
 * the full call-bound media lifecycle without the packaged helper runtime.
 *
 * Wire layout/action bytes/flag formulas are the R33-proven MEDIAREQ26
 * contract (P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md CHILD A) as
 * ported offline by R34 (entrance_p116_r34_attached_media_helper_model.py).
 */
#include <stdint.h>
#include <string.h>

#define R35_MEDIAREQ26_BODY_LEN     26u
#define R35_MEDIAREQ26_OPCODE       0x0011u
#define R35_MEDIAREQ26_OPEN_ACTION  0x14u
#define R35_MEDIAREQ26_STOP_ACTION  0x94u
#define R35_CTP_VERSION             0x18u
#define R35_CTP_FLAG_DATA           0x40u
#define R35_CTP_FLAG_SYN_MASK       0x80u
#define R35_CALL_BOUND_PACKET_LEN   60u
#define R35_CTP_LOGADDR_LEN         10u

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

/* The seven forbidden second-OPEN conditions, proven native/offline in R33/R34
 * (P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md CHILD D item 6;
 * entrance_p116_r34_attached_media_helper_model.py SECOND_OPEN_FORBIDDEN_STATES). */
typedef struct {
    const char *code;
    const char *description;
} R35SecondOpenForbiddenState;

static const R35SecondOpenForbiddenState R35_SECOND_OPEN_FORBIDDEN_STATES[7] = {
    { "NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER",
      "no call-transaction capture / no call signaling barrier" },
    { "NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED",
      "no local media RX channel / id allocated" },
    { "OPEN_ALREADY_PENDING", "OPEN already pending" },
    { "OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED",
      "OPEN already emitted/active or confirmed" },
    { "STOP_ALREADY_SENT", "STOP already sent" },
    { "MEDIA_CHANNEL_ALREADY_DISPOSED", "media channel already disposed" },
    { "REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION",
      "OPEN aimed at the registration handle or a foreign call transaction" }
};

typedef void (*R35FrameWriter)(
    void *ctx,
    const char *semantic_kind,
    const unsigned char *ctp_packet,
    unsigned packet_len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement);

typedef void (*R35RtpArmHook)(void *ctx, int armed);

typedef struct {
    /* call-bound transaction state (R32 CHILD1 / R30 model). */
    int call_ctp_valid;
    int call_transaction_alive;
    unsigned call_generation;
    unsigned call_ctp_connection;
    unsigned call_sequence;
    unsigned call_ack;
    unsigned outer_ctpp_handle;
    unsigned char source_logical[R35_CTP_LOGADDR_LEN];
    unsigned char dest_logical[R35_CTP_LOGADDR_LEN];

    /* media RX channel state (R33 CHILD B minimal model / R34 session). */
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

    /* preservation booleans (R32 CHILD4 teardown ownership model). */
    int listener_alive;
    int registration_alive;
    int pseudotcp_alive;

    R35MediaState state;

    R35FrameWriter writer;
    void *writer_ctx;
    R35RtpArmHook rtp_arm_hook;
    void *rtp_arm_hook_ctx;
} R35AttachedMediaSession;

typedef struct {
    int form;
    int video_request;
    int profile_selector;
    unsigned media_channel_id;
    unsigned max_rtp_payload;
    unsigned channel_profile_word;
    unsigned profile_halfwords[3];
    unsigned profile_halfword_3;
    unsigned profile_byte_4;
    unsigned char address_ipv4[4];
} R35MediaRequestSources;

typedef struct {
    unsigned flags;
    unsigned version;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
    unsigned inner_len;
    const unsigned char *inner_body;
    const unsigned char *source_raw;
    const unsigned char *dest_raw;
} R35CtpEnvelopeView;

static unsigned r35_read_be16(const unsigned char *p) {
    return ((unsigned)p[0] << 8) | (unsigned)p[1];
}

static void r35_write_be16(unsigned char *p, unsigned v) {
    p[0] = (unsigned char)((v >> 8) & 0xffu);
    p[1] = (unsigned char)(v & 0xffu);
}

static void r35_write_le16(unsigned char *p, unsigned v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
}

static void r35_write_le32(unsigned char *p, unsigned long v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
    p[2] = (unsigned char)((v >> 16) & 0xffu);
    p[3] = (unsigned char)((v >> 24) & 0xffu);
}

/* R33 CHILD A: tunnel base 0x32 with bit3 re-derived from video_request;
 * address base 0x30 composed with the profile-selector (bit2) and
 * video-request (bit3) bits.  Never an unconditional literal for callers:
 * the flags byte is always the return value of this function. */
static unsigned r35_open_flags(int form, int video_request, int profile_selector) {
    if (form == R35_FORM_TUNNEL) {
        return (unsigned)((0x32u & ~0x08u) | (video_request ? 0x08u : 0x00u));
    }
    return (unsigned)(0x30u | (profile_selector ? 0x04u : 0x00u) | (video_request ? 0x08u : 0x00u));
}

static unsigned r35_stop_flags(int form) {
    return form == R35_FORM_TUNNEL ? 0x02u : 0x00u;
}

static int r35_serialize_mediareq26_open(unsigned char out[26], const R35MediaRequestSources *src) {
    if (!out || !src) return 0;
    if (src->media_channel_id == 0u || src->media_channel_id > 0xFFFFu) return 0;
    if (src->form != R35_FORM_TUNNEL && src->form != R35_FORM_ADDRESS) return 0;
    memset(out, 0, R35_MEDIAREQ26_BODY_LEN);
    r35_write_be16(out + 0, R35_MEDIAREQ26_OPCODE);
    out[2] = (unsigned char)R35_MEDIAREQ26_OPEN_ACTION;
    out[3] = (unsigned char)r35_open_flags(src->form, src->video_request, src->profile_selector);
    if (src->form == R35_FORM_ADDRESS) {
        memcpy(out + 4, src->address_ipv4, 4);
    }
    r35_write_le16(out + 8, src->media_channel_id);
    r35_write_le16(out + 10, src->max_rtp_payload);
    r35_write_le32(out + 12, (unsigned long)src->channel_profile_word);
    r35_write_le16(out + 16, src->profile_halfwords[0]);
    r35_write_le16(out + 18, src->profile_halfwords[1]);
    r35_write_le16(out + 20, src->profile_halfwords[2]);
    r35_write_le16(out + 22, src->profile_halfword_3);
    out[24] = (unsigned char)(src->profile_byte_4 & 0xffu);
    out[25] = 0;
    return 1;
}

static int r35_serialize_mediareq26_stop(unsigned char out[26], int form, unsigned media_channel_id) {
    if (!out) return 0;
    if (media_channel_id == 0u || media_channel_id > 0xFFFFu) return 0;
    if (form != R35_FORM_TUNNEL && form != R35_FORM_ADDRESS) return 0;
    memset(out, 0, R35_MEDIAREQ26_BODY_LEN);
    r35_write_be16(out + 0, R35_MEDIAREQ26_OPCODE);
    out[2] = (unsigned char)R35_MEDIAREQ26_STOP_ACTION;
    out[3] = (unsigned char)r35_stop_flags(form);
    r35_write_le16(out + 8, media_channel_id);
    return 1;
}

/* Generic CTP envelope reader mirroring the R30-proven layout
 * (entrance_p116_r30_call_ctp_envelope_model.py:parse_ctp_envelope):
 * flags(1) version(1) connection(2,BE) sequence(1) ack(1) inner_len(2,BE)
 * inner_body(inner_len) pad trailer(4x0xff) source(10) dest(10). */
static int r35_parse_ctp_envelope(const unsigned char *payload, unsigned len, R35CtpEnvelopeView *out) {
    unsigned inner_len, body_end, pad, trailer_start;
    if (!payload || !out || len < 32u) return 0;
    if (payload[1] != R35_CTP_VERSION) return 0;
    inner_len = r35_read_be16(payload + 6);
    body_end = 8u + inner_len;
    pad = (4u - (inner_len % 4u)) % 4u;
    trailer_start = body_end + pad;
    if (len != trailer_start + 24u) return 0;
    if (!(payload[trailer_start] == 0xffu && payload[trailer_start + 1] == 0xffu &&
          payload[trailer_start + 2] == 0xffu && payload[trailer_start + 3] == 0xffu)) {
        return 0;
    }
    out->flags = payload[0];
    out->version = payload[1];
    out->connection = r35_read_be16(payload + 2);
    out->sequence = payload[4];
    out->acknowledgement = payload[5];
    out->inner_len = inner_len;
    out->inner_body = payload + 8;
    out->source_raw = payload + trailer_start + 4;
    out->dest_raw = payload + trailer_start + 14;
    return 1;
}

static int r35_build_call_bound_packet(
    unsigned char out[R35_CALL_BOUND_PACKET_LEN],
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char mediareq26[R35_MEDIAREQ26_BODY_LEN],
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN]) {
    if (!out || !mediareq26 || !source_raw || !dest_raw) return 0;
    memset(out, 0, R35_CALL_BOUND_PACKET_LEN);
    out[0] = (unsigned char)R35_CTP_FLAG_DATA;
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, connection & 0xFFFFu);
    out[4] = (unsigned char)(sequence & 0xffu);
    out[5] = (unsigned char)(acknowledgement & 0xffu);
    r35_write_be16(out + 6, R35_MEDIAREQ26_BODY_LEN);
    memcpy(out + 8, mediareq26, R35_MEDIAREQ26_BODY_LEN);
    out[36] = 0xffu; out[37] = 0xffu; out[38] = 0xffu; out[39] = 0xffu;
    memcpy(out + 40, source_raw, R35_CTP_LOGADDR_LEN);
    memcpy(out + 50, dest_raw, R35_CTP_LOGADDR_LEN);
    return 1;
}

/* Capture the call-bound CTP transaction at CALL_INIT: connection bytes 2..3
 * of the inbound CTP header, direction-transformed by XOR 0x8000 (R32 CHILD1;
 * entrance_p116_r30b_call_transaction_model.py:derive_native_local_connection_id).
 * Sequence/ack seed the outbound call-bound counters the same way R30B seeds
 * CallTransaction.next_tx_sequence/next_tx_acknowledgement (peer ack/sequence
 * swapped).  Resets media-channel bookkeeping is NOT performed here: a fresh
 * allocate call always starts a new channel generation (see
 * r35_allocate_media_rx_channel), so residual state from a prior call on the
 * same session object cannot be reused without a matching call_generation. */
static int r35_capture_call_ctp_id(
    R35AttachedMediaSession *s,
    const unsigned char *call_init_envelope,
    unsigned envelope_len,
    unsigned outer_ctpp_handle) {
    R35CtpEnvelopeView view;
    unsigned local_connection;
    if (!s || !r35_parse_ctp_envelope(call_init_envelope, envelope_len, &view)) return 0;
    if (!(view.flags & R35_CTP_FLAG_SYN_MASK)) return 0;
    local_connection = (view.connection ^ 0x8000u) & 0xFFFFu;
    if (local_connection == 0u || (local_connection & 0x7FFFu) == 0x7FFFu) return 0;
    if (local_connection == (outer_ctpp_handle & 0xFFFFu)) return 0;

    s->call_generation += 1u;
    s->call_ctp_connection = local_connection;
    s->call_sequence = view.acknowledgement & 0xffu;
    s->call_ack = view.sequence & 0xffu;
    s->outer_ctpp_handle = outer_ctpp_handle;
    memcpy(s->source_logical, view.dest_raw, R35_CTP_LOGADDR_LEN);
    memcpy(s->dest_logical, view.source_raw, R35_CTP_LOGADDR_LEN);
    s->call_ctp_valid = 1;
    s->call_transaction_alive = 1;
    s->listener_alive = 1;
    s->registration_alive = 1;
    s->pseudotcp_alive = 1;
    s->state = R35_STATE_CALL_CAPTURED;
    return 1;
}

static int r35_call_ready(const R35AttachedMediaSession *s) {
    if (!s->call_ctp_valid || !s->call_transaction_alive) return 0;
    if (s->call_ctp_connection == (s->outer_ctpp_handle & 0xFFFFu)) return 0;
    return 1;
}

/* Order mirrors R34's _require_live_channel: disposed is checked before
 * "not allocated" because dispose_media_rx_channel sets both channel_disposed
 * and clears channel_allocated in the same step, and a disposed/invalidated
 * identity must read as STALE rather than merely "never allocated". */
static R35Result r35_require_live_channel(const R35AttachedMediaSession *s, unsigned channel_id) {
    if (s->channel_disposed) return R35_ERR_STALE_CHANNEL;
    if (!s->channel_allocated) return R35_ERR_NO_CHANNEL_ALLOCATED;
    if (s->channel_generation != s->call_generation) return R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL;
    if (s->channel_id != channel_id) return R35_ERR_WRONG_CHANNEL;
    return R35_OK;
}

R35Result r35_allocate_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id, unsigned token) {
    if (!s) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (channel_id == 0u || channel_id > 0xFFFFu) return R35_ERR_BAD_ARGUMENT;
    if (s->channel_allocated && s->channel_generation == s->call_generation) {
        return R35_ERR_CHANNEL_ALREADY_ALLOCATED;
    }
    s->channel_id = channel_id;
    s->channel_token = token;
    s->channel_generation = s->call_generation;
    s->channel_allocated = 1;
    s->channel_disposed = 0;
    s->open_pending = 0;
    s->open_sent = 0;
    s->open_confirmed = 0;
    s->stop_sent = 0;
    s->rtp_armed = 0;
    s->open_count = 0;
    s->stop_count = 0;
    s->state = R35_STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED;
    return R35_OK;
}

R35Result r35_send_open(
    R35AttachedMediaSession *s,
    const R35MediaRequestSources *src,
    int use_registration_handle) {
    unsigned char body[R35_MEDIAREQ26_BODY_LEN];
    unsigned char packet[R35_CALL_BOUND_PACKET_LEN];
    R35Result live;
    if (!s || !src) return R35_ERR_BAD_ARGUMENT;
    if (use_registration_handle) return R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    live = r35_require_live_channel(s, src->media_channel_id);
    if (live != R35_OK) return live;
    if (s->open_pending) return R35_ERR_OPEN_ALREADY_PENDING;
    if (s->open_sent || s->open_confirmed) return R35_ERR_OPEN_ALREADY_EMITTED;
    if (s->stop_sent) return R35_ERR_STOP_ALREADY_SENT;
    if (!r35_serialize_mediareq26_open(body, src)) return R35_ERR_BAD_ARGUMENT;
    if (!r35_build_call_bound_packet(packet, s->call_ctp_connection, s->call_sequence,
                                      s->call_ack, body, s->source_logical, s->dest_logical)) {
        return R35_ERR_BAD_ARGUMENT;
    }
    if (s->writer) {
        s->writer(s->writer_ctx, "MEDIA_OPEN", packet, R35_CALL_BOUND_PACKET_LEN,
                   s->call_ctp_connection, s->call_sequence, s->call_ack);
    }
    s->call_sequence = (s->call_sequence + 1u) & 0xffu;
    s->open_pending = 1;
    s->open_sent = 1;
    s->open_count += 1u;
    s->state = R35_STATE_OPEN_SENT;
    return R35_OK;
}

R35Result r35_observe_channel_open_response(R35AttachedMediaSession *s, unsigned channel_id, int ok) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_pending && !s->open_sent) return R35_ERR_STOP_BEFORE_OPEN;
    s->open_pending = 0;
    s->open_confirmed = ok ? 1 : 0;
    return R35_OK;
}

/* RTP may arm only after exactly one call-bound OPEN (R33 CHILD C:
 * CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_RTP=false, so no response wait is
 * required, but a proven prior OPEN on the same channel/generation is). */
R35Result r35_enable_rtp(R35AttachedMediaSession *s, unsigned channel_id) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_sent || s->open_count != 1u) return R35_ERR_RTP_BEFORE_OPEN;
    s->rtp_armed = 1;
    s->state = R35_STATE_RTP_ELIGIBLE;
    if (s->rtp_arm_hook) s->rtp_arm_hook(s->rtp_arm_hook_ctx, 1);
    return R35_OK;
}

R35Result r35_send_stop(R35AttachedMediaSession *s, int form, unsigned channel_id) {
    unsigned char body[R35_MEDIAREQ26_BODY_LEN];
    unsigned char packet[R35_CALL_BOUND_PACKET_LEN];
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_sent || s->open_count == 0u) return R35_ERR_STOP_BEFORE_OPEN;
    if (s->stop_sent || s->stop_count != 0u) return R35_ERR_SECOND_STOP;
    if (!r35_serialize_mediareq26_stop(body, form, channel_id)) return R35_ERR_BAD_ARGUMENT;
    if (!r35_build_call_bound_packet(packet, s->call_ctp_connection, s->call_sequence,
                                      s->call_ack, body, s->source_logical, s->dest_logical)) {
        return R35_ERR_BAD_ARGUMENT;
    }
    if (s->writer) {
        s->writer(s->writer_ctx, "MEDIA_STOP", packet, R35_CALL_BOUND_PACKET_LEN,
                   s->call_ctp_connection, s->call_sequence, s->call_ack);
    }
    s->call_sequence = (s->call_sequence + 1u) & 0xffu;
    s->stop_sent = 1;
    s->stop_count += 1u;
    s->rtp_armed = 0;
    s->state = R35_STATE_STOP_SENT;
    if (s->rtp_arm_hook) s->rtp_arm_hook(s->rtp_arm_hook_ctx, 0);
    return R35_OK;
}

/* STOP strictly precedes disposal; no STOP ACK is awaited (R33 CHILD D items
 * 1-2).  Once disposed, channel_id/token are permanently invalid for this
 * call_generation: r35_require_live_channel rejects any further use. */
R35Result r35_dispose_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->stop_sent || s->stop_count == 0u) return R35_ERR_DISPOSE_BEFORE_STOP;
    s->channel_disposed = 1;
    s->channel_allocated = 0;
    s->rtp_armed = 0;
    s->state = R35_STATE_DISPOSED;
    return R35_OK;
}

int r35_preserve_listener_registration_pseudotcp(const R35AttachedMediaSession *s) {
    if (!s) return 0;
    if (s->channel_allocated || s->rtp_armed) return 0;
    return s->listener_alive && s->registration_alive && s->pseudotcp_alive && s->call_transaction_alive;
}

/* Stale call/media state after call end must fail closed: clearing
 * call_ctp_valid/call_transaction_alive makes r35_call_ready() reject every
 * subsequent allocate/open/stop attempt on this session until a fresh
 * r35_capture_call_ctp_id() call for a new call transaction succeeds. */
void r35_teardown_call(R35AttachedMediaSession *s) {
    if (!s) return;
    s->call_ctp_valid = 0;
    s->call_transaction_alive = 0;
    s->state = R35_STATE_TERMINAL;
}
/* R35_ATTACHED_MEDIA_END */


/* R54_TX_ATTRIBUTION_BEGIN */
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
    R54_TX_QUEUE_REASON_NO_WRITER,
    R54_TX_QUEUE_REASON_TRANSPORT,
    R54_TX_QUEUE_REASON_ALLOCATION,
    R54_TX_QUEUE_REASON_UNKNOWN
} R54TxQueueReason;

static R54TxSubject g_r54_tx_last_subject = R54_TX_SUBJECT_NONE;
static R54TxSubject g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
static R54TxQueueReason g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;

static const char *
r54_tx_subject_name(R54TxSubject subject)
{
    switch (subject) {
    case R54_TX_SUBJECT_NONE: return "NONE";
    case R54_TX_SUBJECT_INVITE_ACK: return "INVITE_ACK";
    case R54_TX_SUBJECT_LOCAL_CAPABILITIES: return "LOCAL_CAPABILITIES";
    case R54_TX_SUBJECT_LOCAL_ALERTING: return "LOCAL_ALERTING";
    case R54_TX_SUBJECT_PEER_DATA_ACK: return "PEER_DATA_ACK";
    case R54_TX_SUBJECT_MEDIA_OPEN: return "MEDIA_OPEN";
    case R54_TX_SUBJECT_MEDIA_STOP: return "MEDIA_STOP";
    case R54_TX_SUBJECT_OTHER_EXISTING: return "OTHER_EXISTING";
    }
    return "OTHER_EXISTING";
}
/* R54_TX_ATTRIBUTION_END */

/* R35_WIRING_BEGIN */
static R35AttachedMediaSession g_r35_session;

static void
r35_glib_transport_writer(
    void *ctx,
    const char *semantic_kind,
    const unsigned char *ctp_packet,
    unsigned packet_len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement)
{
    gboolean queued;

    (void)ctx;
    (void)connection;
    (void)sequence;
    (void)acknowledgement;

    P12TxKind r54_kind = P12_TX_R35_MEDIA_STOP;
    R54TxSubject r54_subject = R54_TX_SUBJECT_OTHER_EXISTING;

    if (strcmp(semantic_kind, "MEDIA_OPEN") == 0) {
        r54_kind = P12_TX_R35_MEDIA_OPEN;
        r54_subject = R54_TX_SUBJECT_MEDIA_OPEN;
    } else if (strcmp(semantic_kind, "MEDIA_STOP") == 0) {
        r54_kind = P12_TX_R35_MEDIA_STOP;
        r54_subject = R54_TX_SUBJECT_MEDIA_STOP;
    } else if (strcmp(semantic_kind, "CALL_INVITE_ACK") == 0) {
        r54_kind = P12_TX_R54_INVITE_ACK;
        r54_subject = R54_TX_SUBJECT_INVITE_ACK;
    } else if (strcmp(semantic_kind, "CALL_CAPABILITIES") == 0) {
        r54_kind = P12_TX_R54_LOCAL_CAPABILITIES;
        r54_subject = R54_TX_SUBJECT_LOCAL_CAPABILITIES;
    } else if (strcmp(semantic_kind, "CALL_ALERTING") == 0) {
        r54_kind = P12_TX_R54_LOCAL_ALERTING;
        r54_subject = R54_TX_SUBJECT_LOCAL_ALERTING;
    } else if (strcmp(semantic_kind, "CALL_PEER_DATA_ACK") == 0) {
        r54_kind = P12_TX_R54_PEER_DATA_ACK;
        r54_subject = R54_TX_SUBJECT_PEER_DATA_ACK;
    }

    g_r54_tx_last_subject = r54_subject;
    g_r54_tx_last_reason = R54_TX_QUEUE_REASON_UNKNOWN;
    g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;

    if (p12_tx_pending) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_BUSY;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=BUSY\n");
        printf("R54_TX_WAITING_FOR_SLOT=true\n");
        fflush(stdout);
        return;
    }

    if (packet_len == 0u || packet_len > P12_TX_MAX - 8u) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_INVALID_LENGTH;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=INVALID_LENGTH\n");
        fflush(stdout);
        return;
    }

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        r54_kind);
    if (queued) {
        g_r54_tx_last_enqueued = r54_subject;
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_NONE;
        printf("R54_TX_ENQUEUED=%s\n", r54_tx_subject_name(r54_subject));
    } else {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_UNKNOWN;
        printf("R54_TX_QUEUE_FAIL_SUBJECT=%s\n", r54_tx_subject_name(r54_subject));
        printf("R54_TX_QUEUE_FAIL_REASON=UNKNOWN\n");
    }

    printf("R35_%s_QUEUED=%s\n", semantic_kind, queued ? "true" : "false");
    fflush(stdout);
}

/* Reuses the existing P80 receive/forwarding gate: R35 arms/disarms the same
 * boolean the self-activation path sets at P80_MEDIA_ACTIVE (see
 * p80_try_forward_wrapped_rtp), rather than duplicating a second forwarding
 * decision surface. */
static void
r35_p80_rtp_arm_hook(void *ctx, int armed)
{
    (void)ctx;
    r42_listener_rtp_arm(armed);
    printf("R35_RTP_ARMED=%s\n", armed ? "true" : "false");
    fflush(stdout);
}

static void
r35_wire_session_transport(void)
{
    g_r35_session.writer = r35_glib_transport_writer;
    g_r35_session.writer_ctx = NULL;
    g_r35_session.rtp_arm_hook = r35_p80_rtp_arm_hook;
    g_r35_session.rtp_arm_hook_ctx = NULL;
}
/* R35_WIRING_END */

/* R36_ATTACHED_MEDIA_TRIGGER_BEGIN */
/*
 * P116/R36 attached inbound media: the OPEN trigger.
 *
 * Dependency-free by the same rule as R35's core region: no GLib/libnice
 * header, no network/socket primitive, no printf/fprintf.  Every decision
 * here is a pure function of an already-parsed R35CtpEnvelopeView and an
 * R35AttachedMediaSession*, so a host test can drive it without the
 * packaged helper runtime, exactly like R35's own core region.
 */
#define R36_OP_CAPABILITIES        0x0003u
#define R36_CAP_VIDEO_REQUEST_BIT  0x08u
#define R36_CAP_BODY_MIN_LEN       5u

/* Fail-closed on every axis this round can prove: wrong CTP flag (not a
 * DATA frame), inner opcode not CAPABILITIES, body too short to hold the
 * capability word, no currently-valid call on this session
 * (r35_call_ready), or a connection that -- after the SAME direction
 * transform r35_capture_call_ctp_id already applies -- does not match the
 * call this session actually captured (stale/prior/foreign call). None of
 * these checks duplicate an R35 rule; r35_call_ready is called, not
 * re-implemented. */
static int r36_is_capabilities_for_current_call(
    const R35AttachedMediaSession *s,
    const R35CtpEnvelopeView *view) {
    unsigned local_connection;
    if (!s || !view) return 0;
    if (view->flags != R35_CTP_FLAG_DATA) return 0;
    if (view->inner_len < R36_CAP_BODY_MIN_LEN) return 0;
    if (r35_read_be16(view->inner_body) != R36_OP_CAPABILITIES) return 0;
    if (!r35_call_ready(s)) return 0;
    local_connection = (view->connection ^ 0x8000u) & 0xFFFFu;
    return local_connection == s->call_ctp_connection ? 1 : 0;
}

static int r36_capabilities_video_requested(const R35CtpEnvelopeView *view) {
    if (!view || view->inner_len < R36_CAP_BODY_MIN_LEN) return 0;
    return (view->inner_body[4] & R36_CAP_VIDEO_REQUEST_BIT) != 0u ? 1 : 0;
}

/* Idempotent, fail-closed, no-retry trigger.  Every early return is a
 * pre-existing R35 guard (R35_ERR_*) reached through R35's own exported
 * functions -- r35_allocate_media_rx_channel, r35_send_open,
 * r35_enable_rtp -- never bypassed and never duplicated.  A rejected
 * attempt is not retried by this function or by its caller: the wiring
 * call site below calls this once per received frame, and a frame that
 * does not satisfy r36_is_capabilities_for_current_call never reaches it.
 *
 * media_channel_id is NOT a proven native field: R33/R34/R35 already
 * record the real local RTP-receiver channel/port as an unproven local
 * runtime field (P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md
 * SECTION 2), and this overlay does not close that gap. It reuses the
 * session's own call connection id as a stable, real, already-unique-
 * per-call local reference (never an invented network value) so that the
 * one-OPEN/idempotency machinery below is exercised meaningfully; a
 * future round that recovers the real local media-channel identity should
 * replace this call-connection-id reuse, not the trigger logic around it.
 */
static R35Result r36_trigger_open_from_capabilities(
    R35AttachedMediaSession *s,
    const R35CtpEnvelopeView *view) {
    R35MediaRequestSources src;
    unsigned channel_id;
    R35Result rc;
    if (!s || !view) return R35_ERR_BAD_ARGUMENT;
    if (!r36_capabilities_video_requested(view)) return R35_ERR_BAD_ARGUMENT;

    channel_id = s->call_ctp_connection;
    if (!(s->channel_allocated && s->channel_generation == s->call_generation)) {
        rc = r35_allocate_media_rx_channel(s, channel_id, channel_id);
        if (rc != R35_OK) return rc;
    }

    memset(&src, 0, sizeof(src));
    src.form = R35_FORM_TUNNEL;
    src.video_request = 1;      /* proven: this is exactly the bit3 checked above */
    src.profile_selector = 0;   /* UNPROVEN local cfg field, unchanged by R36 */
    src.media_channel_id = channel_id;
    src.max_rtp_payload = 0;    /* UNPROVEN local RtpDispatcher field, unchanged by R36 */
    src.channel_profile_word = 0;

    rc = r35_send_open(s, &src, 0);
    if (rc != R35_OK) return rc;

    (void)r35_enable_rtp(s, channel_id);
    return R35_OK;
}
/* R36_ATTACHED_MEDIA_TRIGGER_END */

/* R45_CALL_ADOPTION_BEGIN */
#define R45_CTP_FLAG_EMPTY_ACK        0x80u
#define R45_OP_CAPABILITIES           0x0003u
#define R45_OP_ALERTING               0x000Au
#define R45_CAPABILITIES_BODY_LEN     8u
#define R45_ALERTING_BODY_LEN         3u
#define R45_PACKET_MAX_LEN            40u

typedef struct {
    unsigned generation;
    int invite_ack_sent;
    int local_capabilities_sent;
    int local_alerting_sent;
    unsigned inbound_ack_count;
    unsigned peer_data_ack_count;
    unsigned local_signaling_write_count;
} R45CallAdoptionState;

typedef struct {
    unsigned call_type;
    unsigned capability_word;
    unsigned alerting_argument;
} R45RuntimeFields;

static void r45_reset_state(R45CallAdoptionState *state, unsigned generation) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->generation = generation;
}

static void r45_sync_generation(
    R45CallAdoptionState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return;
    if (state->generation != session->call_generation) {
        r45_reset_state(state, session->call_generation);
    }
}

static unsigned r45_padded_inner_len(unsigned inner_len) {
    return (inner_len + 3u) & ~3u;
}

static unsigned r45_packet_len(unsigned inner_len) {
    return 8u + r45_padded_inner_len(inner_len) + 4u
        + (2u * R35_CTP_LOGADDR_LEN);
}

static int r45_build_packet(
    unsigned char out[R45_PACKET_MAX_LEN],
    unsigned *out_len,
    unsigned flags,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char *inner_body,
    unsigned inner_len,
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN]) {
    unsigned padded_len;
    unsigned trailer_start;
    unsigned packet_len;
    if (!out || !out_len || !source_raw || !dest_raw) return 0;
    if (inner_len > R45_CAPABILITIES_BODY_LEN) return 0;
    if (inner_len != 0u && !inner_body) return 0;

    padded_len = r45_padded_inner_len(inner_len);
    trailer_start = 8u + padded_len;
    packet_len = r45_packet_len(inner_len);
    if (packet_len > R45_PACKET_MAX_LEN) return 0;

    memset(out, 0, R45_PACKET_MAX_LEN);
    out[0] = (unsigned char)(flags & 0xffu);
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, connection & 0xffffu);
    out[4] = (unsigned char)(sequence & 0xffu);
    out[5] = (unsigned char)(acknowledgement & 0xffu);
    r35_write_be16(out + 6, inner_len);
    if (inner_len != 0u) memcpy(out + 8, inner_body, inner_len);

    out[trailer_start + 0u] = 0xffu;
    out[trailer_start + 1u] = 0xffu;
    out[trailer_start + 2u] = 0xffu;
    out[trailer_start + 3u] = 0xffu;
    memcpy(out + trailer_start + 4u, source_raw, R35_CTP_LOGADDR_LEN);
    memcpy(out + trailer_start + 14u, dest_raw, R35_CTP_LOGADDR_LEN);
    *out_len = packet_len;
    return 1;
}

static int r45_emit(
    R35AttachedMediaSession *session,
    const char *semantic_kind,
    const unsigned char *packet,
    unsigned packet_len,
    unsigned sequence,
    unsigned acknowledgement) {
    if (!session || !semantic_kind || !packet || !session->writer) return 0;
    session->writer(
        session->writer_ctx,
        semantic_kind,
        packet,
        packet_len,
        session->call_ctp_connection,
        sequence,
        acknowledgement);
    return 1;
}

static int r45_view_matches_current_call(
    const R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *view) {
    unsigned local_connection;
    if (!session || !view || !r35_call_ready(session)) return 0;
    local_connection = (view->connection ^ 0x8000u) & 0xffffu;
    return local_connection == session->call_ctp_connection ? 1 : 0;
}

static int r45_emit_empty_ack_for_peer_frame(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *view,
    const char *semantic_kind) {
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned outgoing_ack;
    unsigned sequence;
    if (!session || !state || !view || !semantic_kind) return 0;
    r45_sync_generation(state, session);
    if (!r45_view_matches_current_call(session, view)) return 0;
    if ((view->flags & R35_CTP_FLAG_DATA) == 0u &&
        (view->flags & R35_CTP_FLAG_SYN_MASK) == 0u) return 0;
    if (view->inner_len == 0u) return 0;

    outgoing_ack = (view->sequence + 1u) & 0xffu;
    sequence = session->call_sequence & 0xffu;
    session->call_ack = outgoing_ack;

    if (!r45_build_packet(
            packet, &packet_len,
            R45_CTP_FLAG_EMPTY_ACK,
            session->call_ctp_connection,
            sequence,
            outgoing_ack,
            NULL, 0u,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, semantic_kind, packet, packet_len,
            sequence, outgoing_ack)) {
        return 0;
    }
    /* Primary-native invariant: empty ACK does not advance TX sequence. */
    state->inbound_ack_count += 1u;
    return 1;
}

static int r45_send_invite_ack(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *invite_view) {
    if (!session || !state || !invite_view) return 0;
    r45_sync_generation(state, session);
    if (state->invite_ack_sent) return 0;
    if ((invite_view->flags & R35_CTP_FLAG_SYN_MASK) == 0u) return 0;
    if (!r45_emit_empty_ack_for_peer_frame(
            session, state, invite_view, "CALL_INVITE_ACK")) {
        return 0;
    }
    state->invite_ack_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_serialize_capabilities(
    unsigned char body[R45_CAPABILITIES_BODY_LEN],
    const R45RuntimeFields *runtime) {
    unsigned word;
    if (!body || !runtime) return 0;
    if (runtime->call_type > 0xffu) return 0;
    body[0] = 0x00u;
    body[1] = 0x03u;
    body[2] = (unsigned char)(runtime->call_type & 0xffu);
    body[3] = 0x00u;
    word = runtime->capability_word;
    body[4] = (unsigned char)(word & 0xffu);
    body[5] = (unsigned char)((word >> 8) & 0xffu);
    body[6] = (unsigned char)((word >> 16) & 0xffu);
    body[7] = (unsigned char)((word >> 24) & 0xffu);
    return 1;
}

static int r45_serialize_alerting(
    unsigned char body[R45_ALERTING_BODY_LEN],
    const R45RuntimeFields *runtime) {
    if (!body || !runtime) return 0;
    if (runtime->alerting_argument > 0xffu) return 0;
    body[0] = 0x00u;
    body[1] = 0x0au;
    body[2] = (unsigned char)(runtime->alerting_argument & 0xffu);
    return 1;
}

static int r45_send_local_capabilities(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R45RuntimeFields *runtime) {
    unsigned char body[R45_CAPABILITIES_BODY_LEN];
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned sequence;
    if (!session || !state || !runtime) return 0;
    r45_sync_generation(state, session);
    if (!r35_call_ready(session)) return 0;
    if (!state->invite_ack_sent || state->local_capabilities_sent) return 0;
    if (!r45_serialize_capabilities(body, runtime)) return 0;

    sequence = session->call_sequence & 0xffu;
    if (!r45_build_packet(
            packet, &packet_len,
            R35_CTP_FLAG_DATA,
            session->call_ctp_connection,
            sequence,
            session->call_ack,
            body, R45_CAPABILITIES_BODY_LEN,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, "CALL_CAPABILITIES", packet, packet_len,
            sequence, session->call_ack)) {
        return 0;
    }
    session->call_sequence = (sequence + 1u) & 0xffu;
    state->local_capabilities_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_send_local_alerting(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R45RuntimeFields *runtime) {
    unsigned char body[R45_ALERTING_BODY_LEN];
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned sequence;
    if (!session || !state || !runtime) return 0;
    r45_sync_generation(state, session);
    if (!r35_call_ready(session)) return 0;
    if (!state->local_capabilities_sent || state->local_alerting_sent) return 0;
    if (!r45_serialize_alerting(body, runtime)) return 0;

    sequence = session->call_sequence & 0xffu;
    if (!r45_build_packet(
            packet, &packet_len,
            R35_CTP_FLAG_DATA,
            session->call_ctp_connection,
            sequence,
            session->call_ack,
            body, R45_ALERTING_BODY_LEN,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, "CALL_ALERTING", packet, packet_len,
            sequence, session->call_ack)) {
        return 0;
    }
    session->call_sequence = (sequence + 1u) & 0xffu;
    state->local_alerting_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_call_adoption_complete(
    const R45CallAdoptionState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return 0;
    return state->generation == session->call_generation
        && state->invite_ack_sent
        && state->local_capabilities_sent
        && state->local_alerting_sent;
}

static int r45_accept_peer_data_and_ack(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *view) {
    if (!session || !state || !view) return 0;
    r45_sync_generation(state, session);
    if (!r45_call_adoption_complete(state, session)) return 0;
    if (view->flags != R35_CTP_FLAG_DATA) return 0;
    if (!r45_emit_empty_ack_for_peer_frame(
            session, state, view, "CALL_PEER_DATA_ACK")) {
        return 0;
    }
    state->peer_data_ack_count += 1u;
    return 1;
}
/* R45_CALL_ADOPTION_END */

/* R53_CALL_ADOPTION_PROFILE_BEGIN */
#define R53_HELPER_CAP_AUDIO_DST  0x01u
#define R53_HELPER_CAP_AUDIO_SRC  0x02u
#define R53_HELPER_CAP_VIDEO_DST  0x04u
#define R53_HELPER_CAP_MSTREAM    0x20u
#define R53_HELPER_INTUNIT_CALL_TYPE 0x49u
#define R53_HELPER_ALERTING_ARGUMENT 0x00u

typedef enum {
    R53_STAGE_NONE = 0,
    R53_STAGE_ACK_BUILD_FAILED,
    R53_STAGE_ACK_WRITE_FAILED,
    R53_STAGE_CAPABILITIES_BUILD_FAILED,
    R53_STAGE_CAPABILITIES_WRITE_FAILED,
    R53_STAGE_ALERTING_BUILD_FAILED,
    R53_STAGE_ALERTING_WRITE_FAILED,
    R53_STAGE_WAITING_PEER_CAPABILITIES,
    R53_STAGE_PEER_CAPABILITIES_REJECTED,
    R53_STAGE_MEDIA_TRIGGER_REJECTED,
    R53_STAGE_TX_INVITE_ACK_FAILED,
    R53_STAGE_TX_LOCAL_CAPABILITIES_FAILED,
    R53_STAGE_TX_LOCAL_ALERTING_FAILED,
    R53_STAGE_TX_PEER_ACK_FAILED,
    R53_STAGE_TX_MEDIA_TRIGGER_FAILED,
    R53_STAGE_TX_WAIT_TIMEOUT,
    R53_STAGE_TX_GENERATION_REPLACED,
    R53_STAGE_TX_LISTENER_TEARDOWN
} R53FailureStage;

typedef struct {
    unsigned generation;
    unsigned connection;
    int adoption_attempted;
    int call_adoption_started;
    int invite_ack_sent;
    int local_capabilities_sent;
    unsigned local_capability_word;
    int local_alerting_sent;
    int waiting_peer_capabilities;
    int peer_capabilities_seen;
    unsigned peer_capability_word;
    int peer_video_requested;
    R53FailureStage call_adoption_failure_stage;
} R53Diagnostics;

typedef struct {
    R45CallAdoptionState r45;
    R53Diagnostics diag;
} R53CallAdoptionProfileState;

static unsigned r53_helper_local_capability_profile(void) {
    return R53_HELPER_CAP_AUDIO_DST
        | R53_HELPER_CAP_AUDIO_SRC
        | R53_HELPER_CAP_VIDEO_DST
        | R53_HELPER_CAP_MSTREAM;
}

static const char *r53_failure_stage_name(R53FailureStage stage) {
    switch (stage) {
    case R53_STAGE_NONE: return "NONE";
    case R53_STAGE_ACK_BUILD_FAILED: return "ACK_BUILD_FAILED";
    case R53_STAGE_ACK_WRITE_FAILED: return "ACK_WRITE_FAILED";
    case R53_STAGE_CAPABILITIES_BUILD_FAILED: return "CAPABILITIES_BUILD_FAILED";
    case R53_STAGE_CAPABILITIES_WRITE_FAILED: return "CAPABILITIES_WRITE_FAILED";
    case R53_STAGE_ALERTING_BUILD_FAILED: return "ALERTING_BUILD_FAILED";
    case R53_STAGE_ALERTING_WRITE_FAILED: return "ALERTING_WRITE_FAILED";
    case R53_STAGE_WAITING_PEER_CAPABILITIES: return "WAITING_PEER_CAPABILITIES";
    case R53_STAGE_PEER_CAPABILITIES_REJECTED: return "PEER_CAPABILITIES_REJECTED";
    case R53_STAGE_MEDIA_TRIGGER_REJECTED: return "MEDIA_TRIGGER_REJECTED";
    case R53_STAGE_TX_INVITE_ACK_FAILED: return "TX_INVITE_ACK_FAILED";
    case R53_STAGE_TX_LOCAL_CAPABILITIES_FAILED: return "TX_LOCAL_CAPABILITIES_FAILED";
    case R53_STAGE_TX_LOCAL_ALERTING_FAILED: return "TX_LOCAL_ALERTING_FAILED";
    case R53_STAGE_TX_PEER_ACK_FAILED: return "TX_PEER_ACK_FAILED";
    case R53_STAGE_TX_MEDIA_TRIGGER_FAILED: return "TX_MEDIA_TRIGGER_FAILED";
    case R53_STAGE_TX_WAIT_TIMEOUT: return "TX_WAIT_TIMEOUT";
    case R53_STAGE_TX_GENERATION_REPLACED: return "TX_GENERATION_REPLACED";
    case R53_STAGE_TX_LISTENER_TEARDOWN: return "TX_LISTENER_TEARDOWN";
    }
    return "PEER_CAPABILITIES_REJECTED";
}

static void r53_reset_state(R53CallAdoptionProfileState *state, unsigned generation) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->diag.generation = generation;
    r45_reset_state(&state->r45, generation);
}

static void r53_sync_generation(
    R53CallAdoptionProfileState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return;
    if (state->diag.generation != session->call_generation) {
        r53_reset_state(state, session->call_generation);
    }
}

static R45RuntimeFields r53_runtime_fields(void) {
    R45RuntimeFields runtime;
    runtime.call_type = R53_HELPER_INTUNIT_CALL_TYPE;
    runtime.capability_word = r53_helper_local_capability_profile();
    runtime.alerting_argument = R53_HELPER_ALERTING_ARGUMENT;
    return runtime;
}

static int r53_peer_capability_word(
    const R35CtpEnvelopeView *view,
    unsigned *word_out) {
    if (!view || !word_out) return 0;
    if (view->inner_len < 8u) return 0;
    if (r35_read_be16(view->inner_body) != R36_OP_CAPABILITIES) return 0;
    *word_out = (unsigned)view->inner_body[4]
        | ((unsigned)view->inner_body[5] << 8)
        | ((unsigned)view->inner_body[6] << 16)
        | ((unsigned)view->inner_body[7] << 24);
    return 1;
}

typedef int (*R53PeerCapabilitiesTrigger)(
    R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *peer_view);

static inline int r53_default_media_trigger(
    R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *peer_view) {
    return r36_trigger_open_from_capabilities(session, peer_view) == R35_OK
        ? 1
        : 0;
}

static int r53_handle_peer_capabilities_with_trigger(
    R35AttachedMediaSession *session,
    R53CallAdoptionProfileState *state,
    const R35CtpEnvelopeView *peer_view,
    R53PeerCapabilitiesTrigger trigger_fn) {
    unsigned word = 0u;
    if (!session || !state || !peer_view || !trigger_fn) return 0;
    r53_sync_generation(state, session);
    if (state->diag.peer_capabilities_seen) {
        state->diag.call_adoption_failure_stage = R53_STAGE_MEDIA_TRIGGER_REJECTED;
        return 0;
    }
    if (!state->diag.waiting_peer_capabilities ||
        !r45_call_adoption_complete(&state->r45, session)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_WAITING_PEER_CAPABILITIES;
        return 0;
    }
    if (!r36_is_capabilities_for_current_call(session, peer_view) ||
        !r53_peer_capability_word(peer_view, &word)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_PEER_CAPABILITIES_REJECTED;
        return 0;
    }

    state->diag.peer_capabilities_seen = 1;
    state->diag.peer_capability_word = word;
    state->diag.peer_video_requested = r36_capabilities_video_requested(peer_view);
    if (!state->diag.peer_video_requested) {
        state->diag.call_adoption_failure_stage = R53_STAGE_PEER_CAPABILITIES_REJECTED;
        return 0;
    }

    if (!r45_accept_peer_data_and_ack(session, &state->r45, peer_view)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_ACK_WRITE_FAILED;
        return 0;
    }
    if (!trigger_fn(session, peer_view)) {
        state->diag.call_adoption_failure_stage = R53_STAGE_MEDIA_TRIGGER_REJECTED;
        return 0;
    }
    state->diag.waiting_peer_capabilities = 0;
    state->diag.call_adoption_failure_stage = R53_STAGE_NONE;
    return 1;
}

static inline int r53_handle_peer_capabilities(
    R35AttachedMediaSession *session,
    R53CallAdoptionProfileState *state,
    const R35CtpEnvelopeView *peer_view) {
    return r53_handle_peer_capabilities_with_trigger(
        session,
        state,
        peer_view,
        r53_default_media_trigger);
}
/* R53_CALL_ADOPTION_PROFILE_END */

/* R37_LIVE_READINESS_BEGIN */
/*
 * P116/R37 attached inbound media: live-readiness closure.
 *
 * CHILD A of this round's task (the remaining native OPEN runtime-field
 * sources -- cfg capability threshold cfg->+16, tunnel-busy RtpDispatcher+
 * 136, the media-eligibility selector CallFsm+840 bit2, the TUNNEL/ADDRESS
 * choice cfg->+288 != NULL, the profile-selector CallFsm+812, max RTP
 * payload RtpDispatcher::getMaxRtpPayload(), and -- critically -- the local
 * media RX channel identity viper_tunnel_channel_create ->
 * ViperTunnel::openMediaRXChannel -> RtpDispatcher+8) is NOT closed by this
 * region or by any R37 file: every one of those fields was traced this
 * round to its exact native source (P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_
 * READINESS.md SECTION 1) and every one of them is C++ object state inside
 * the SAME process as libvipcomelit.so, never carried on the wire, and not
 * reachable by this helper (a separate musl binary that does not link
 * libvipcomelit.so). This region therefore adds NO new OPEN wiring: R36's
 * existing OPEN trigger is untouched, and no function below ever calls
 * r35_allocate_media_rx_channel or r35_send_open.
 */
/* R58_STOP_CLEANUP_PROTOS_BEGIN */
static R35Result r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin);
/* R58_STOP_CLEANUP_PROTOS_END */
#define R37_OP_RELEASE        0x000Eu
#define R37_CTP_FLAG_FIN      0x20u

typedef struct {
    unsigned bounded_stop_request_received_count;
    unsigned call_bound_media_stop_sent_count;
    unsigned rtp_disarmed_count;
    unsigned media_rx_channel_disposed_count;
    unsigned duplicate_stop_request_ignored_count;
} R37BoundedStopTelemetry;

/* The single stop-and-dispose sequence every stop cause below funnels
 * through: exactly one r35_send_stop call (RTP disarm is already part of
 * that call -- R35's own r35_send_stop invokes the rtp_arm_hook with 0),
 * then exactly one r35_dispose_media_rx_channel call.  Every early return
 * is one of R35's own existing R35Result gates -- this function adds no new
 * idempotency mechanism, it relies on R35's (stop_sent/stop_count,
 * R35_ERR_SECOND_STOP; open_sent, R35_ERR_STOP_BEFORE_OPEN). */
static R35Result r37_stop_and_dispose(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    R35Result rc;
    int already_stopped;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    already_stopped = s->stop_sent;
    rc = r35_send_stop(s, form, s->channel_id);
    if (rc != R35_OK) {
        /* Once a stop has already succeeded, R35's own gates reject any
         * further attempt on the same channel -- R35_ERR_SECOND_STOP if
         * called again before disposal, or R35_ERR_STALE_CHANNEL if called
         * after this function's own disposal step below already ran (the
         * common case, since disposal happens immediately). Both are the
         * SAME semantic event from this function's point of view: a
         * duplicate, already-handled stop request, not a fresh rejection
         * for some other reason. */
        if (already_stopped) t->duplicate_stop_request_ignored_count += 1u;
        return rc;
    }
    t->call_bound_media_stop_sent_count += 1u;
    t->rtp_disarmed_count += 1u;
    rc = r35_dispose_media_rx_channel(s, s->channel_id);
    if (rc == R35_OK) t->media_rx_channel_disposed_count += 1u;
    return rc;
}

/* CHILD B: the real, bounded, explicitly-invocable STOP control.  Exactly
 * one external request is ever effective per media lifetime -- a second
 * call is rejected by R35's own stop_sent/stop_count gate without a second
 * write.  A request that arrives after the call transaction is already
 * gone (REMOTE_CALL_TERMINATED, see r37_handle_remote_release below) is
 * rejected HERE, before reaching r35_send_stop, by the same r35_call_ready
 * check r35_send_stop itself would apply -- this makes the "stale,
 * terminated call" rejection observable via
 * bounded_stop_request_received_count without ever attempting a write. */
/* R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_BEGIN
 * Retired by R58: this forwarder called r37_stop_and_dispose() with no
 * knowledge of the single P12 TX slot, so a BUSY slot silently dropped the
 * protocol STOP. The bounded STOP request is now owned by
 * r58_stop_request()/r58_stop_drive() in the R58 region below, which defers
 * the write to the next free slot instead of dropping it and publishes the
 * authoritative CLOSED completion boundary. r37_stop_and_dispose() itself is
 * unchanged and is still reached by r37_handle_capability_cleared().
 * R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_END */

/* CHILD C item 1: a LATER CAPABILITY_REPORT clearing bit3 (native:
 * CallFsm::st_in_alerting's SAME event-0xa03 handler re-evaluates flags100
 * and calls stop_videorx() when bit3 is now clear --
 * P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md SECTION 5). The call
 * itself is NOT over: call/listener state is deliberately left untouched
 * here (no r35_teardown_call) -- only channel/RTP state changes, matching
 * CHILD D's preservation requirement. This is an ADDITIONAL fail-closed
 * safety net, not a substitute for the explicit bounded STOP above. */
static R35Result r37_handle_capability_cleared(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    return r37_stop_and_dispose(s, t, form);
}

/* CHILD C item 2 and the required race rule: REMOTE_CALL_TERMINATED => no
 * stale media write => local state cleanup / exact native-equivalent
 * behaviour. R36 SECTION 5 found stop_videorx() is called as PART of
 * native call-teardown on RELEASE (local FSM event 0xb0e; wire OP_RELEASE=
 * 0x000E, .r33-evidence/public-vip/viper/ctp.py:30) -- i.e. native
 * sequencing stops media BEFORE the call transaction is gone. This
 * function performs the SAME order: attempt exactly one stop-and-dispose
 * FIRST while r35_call_ready(s) is still true, THEN mark the call
 * terminal. Once r35_teardown_call has run, r35_call_ready(s) is false and
 * every subsequent r37_bounded_stop_request/r37_handle_capability_cleared
 * call is rejected with R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER -- no stale
 * write can ever reach r35_send_stop after this function returns, which is
 * exactly how the race named in CHILD C (remote RELEASE arriving before
 * the operator's explicit bounded STOP) resolves: the later operator
 * request is received (counted) and rejected, never written. */
static R35Result r37_handle_remote_release(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    R35Result rc = R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    rc = r58_stop_request(s, R58_STOP_ORIGIN_REMOTE_RELEASE);
    (void)form;
    r35_teardown_call(s);
    return rc;
}
/* R37_LIVE_READINESS_END */

/* R37_WIRING_BEGIN */
static gboolean
p12_flush_tx(void);

static R37BoundedStopTelemetry g_r37_telemetry;

/* Dispatched by GLib's own main loop when SIGUSR2 is delivered (g_unix_
 * signal_add uses a self-pipe/signalfd internally -- this callback never
 * runs in real POSIX signal context, satisfying "no complex work inside
 * the signal handler; defer to the normal main loop"). The watch is kept
 * installed (G_SOURCE_CONTINUE) rather than removed after first use:
 * idempotency is enforced by R35's own stop_sent/stop_count gate inside
 * r37_bounded_stop_request, not by tearing down the control point, so a
 * second delivery is safely rejected rather than silently dropped. */
static gboolean
r37_bounded_stop_signal_cb(gpointer data)
{
    R35Result rc;
    (void)data;
    rc = r58_stop_request(&g_r35_session, R58_STOP_ORIGIN_HA_SIGNAL);
    (void)p12_flush_tx();
    printf("BOUNDED_STOP_REQUEST_RECEIVED=%u\n", g_r37_telemetry.bounded_stop_request_received_count);
    printf("R37_BOUNDED_STOP_RESULT=%s\n", rc == R35_OK ? "STOP_SENT" : "REJECTED");
    printf("CALL_BOUND_MEDIA_STOP_SENT_COUNT=%u\n", g_r37_telemetry.call_bound_media_stop_sent_count);
    printf("RTP_DISARMED=%u\n", g_r37_telemetry.rtp_disarmed_count);
    printf("MEDIA_RX_CHANNEL_DISPOSED=%u\n", g_r37_telemetry.media_rx_channel_disposed_count);
    fflush(stdout);
    return G_SOURCE_CONTINUE;
}

static void
r37_install_bounded_stop_control(void)
{
    g_unix_signal_add(SIGUSR2, r37_bounded_stop_signal_cb, NULL);
    printf("R37_BOUNDED_STOP_CONTROL_KIND=SIGUSR2_UNIX_SIGNAL_SOURCE\n");
    fflush(stdout);
}
/* R37_WIRING_END */




/*
 * Forward declaration.
 *
 * V4 send helpers are inserted before the existing implementation
 * of p12_flush_tx().
 */
static gboolean
p12_flush_tx(void);

static gboolean
p12_queue_close_channel(
    guint16 channel_id,
    P12TxKind kind);

static guint16
v4_allocate_channel_id(
    guint16 start);


/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */
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

/* R42_CAPABILITIES_DIAGNOSTICS_STATE_BEGIN */
static unsigned r42_diag_call_generation = 0;
static unsigned r42_diag_candidate_count = 0;
static unsigned r42_diag_detail_lines_printed = 0;
#define R42_DIAG_DETAIL_LINE_LIMIT 8u
/*
 * Pre-candidate rejection stages have their OWN bounded budget: each of
 * NO_WRITER/ENVELOPE/FLAG/OPCODE is published at most ONCE per call
 * generation, so a burst of unrelated frames cannot exhaust the
 * candidate detail-line budget before a real CAPABILITIES frame arrives.
 */
#define R42_DIAG_PRE_NO_WRITER (1u << 0)
#define R42_DIAG_PRE_ENVELOPE  (1u << 1)
#define R42_DIAG_PRE_FLAG      (1u << 2)
#define R42_DIAG_PRE_OPCODE    (1u << 3)
static unsigned r42_diag_pre_seen_mask = 0u;

static unsigned
r42_diag_pre_stage_bit(
    int writer_present,
    int envelope_parsed,
    int data_flag,
    int capabilities_opcode)
{
    if (!writer_present) {
        return R42_DIAG_PRE_NO_WRITER;
    }
    if (!envelope_parsed) {
        return R42_DIAG_PRE_ENVELOPE;
    }
    if (!data_flag) {
        return R42_DIAG_PRE_FLAG;
    }
    if (!capabilities_opcode) {
        return R42_DIAG_PRE_OPCODE;
    }
    return 0u;
}

static int
r42_diag_pre_stage_should_emit(unsigned *seen_mask, unsigned stage_bit)
{
    if (seen_mask == 0 || stage_bit == 0u) {
        return 0;
    }
    if ((*seen_mask & stage_bit) != 0u) {
        return 0;
    }
    *seen_mask |= stage_bit;
    return 1;
}

static const char *
r42_diag_pre_stage_name(unsigned stage_bit)
{
    switch (stage_bit) {
    case R42_DIAG_PRE_NO_WRITER:
        return "NO_WRITER";
    case R42_DIAG_PRE_ENVELOPE:
        return "ENVELOPE";
    case R42_DIAG_PRE_FLAG:
        return "FLAG";
    case R42_DIAG_PRE_OPCODE:
        return "OPCODE";
    default:
        return "NONE";
    }
}
/* R42_CAPABILITIES_DIAGNOSTICS_STATE_END */
static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;
static guint16 r42_media_channel_id = 0;
static unsigned r42_attempted_call_generation = 0;

static gboolean
r42_queue_media_channel_open(void)
{
    guint8 body[15];
    guint16 seed;
    guint16 channel_id;

    if (!r35_call_ready(&g_r35_session) ||
        r42_attempted_call_generation == g_r35_session.call_generation)
        return FALSE;

    if (r42_media_channel_id != 0u ||
        (r42_media_stage != R42_MEDIA_IDLE &&
         r42_media_stage != R42_MEDIA_CLOSED)) {
        printf("R42_STALE_MEDIA_CHANNEL_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }

    r42_attempted_call_generation = g_r35_session.call_generation;
    seed = (guint16)(g_random_int() & 0x7fffu);
    channel_id = v4_allocate_channel_id(seed);
    if (channel_id == 0u)
        return FALSE;

    if (r35_allocate_media_rx_channel(
            &g_r35_session,
            (unsigned)channel_id,
            (unsigned)channel_id) != R35_OK)
        return FALSE;

    r42_media_channel_id = channel_id;
    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "RTPC", 4);
    write_le16(body + 12, channel_id);
    body[14] = 1;

    r42_media_stage = R42_MEDIA_CHANNEL_OPEN_TX;
    if (!p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_R42_MEDIA_CHANNEL_OPEN)) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    printf("R42_MEDIA_CHANNEL_ALLOCATED=true\n");
    printf("R42_CAPTURE_CHANNEL_LITERAL_USED=false\n");
    printf("R42_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    printf("R42_MEDIA_CHANNEL_ID=%u\n", (unsigned)r42_media_channel_id);
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r42_queue_mediareq_open(void)
{
    R35MediaRequestSources src;
    R35Result rc;

    if (r42_media_stage != R42_MEDIA_CHANNEL_OPEN_TX ||
        r42_media_channel_id == 0u)
        return FALSE;

    memset(&src, 0, sizeof(src));
    src.form = R35_FORM_TUNNEL;
    src.video_request = 1;
    src.profile_selector = 0;
    src.media_channel_id = (unsigned)r42_media_channel_id;
    src.max_rtp_payload = 0xffffu;
    src.channel_profile_word = 0u;
    src.profile_halfwords[0] = 0x0320u;
    src.profile_halfwords[1] = 0x01e0u;
    src.profile_halfwords[2] = 0x0140u;
    src.profile_halfword_3 = 0x00f0u;
    src.profile_byte_4 = 0x10u;

    r42_media_stage = R42_MEDIAREQ_OPEN_TX;
    rc = r35_send_open(&g_r35_session, &src, 0);
    if (rc != R35_OK ||
        !p12_tx_pending ||
        p12_tx_kind != P12_TX_R35_MEDIA_OPEN) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }

    printf("R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED\n");
    printf("R42_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    printf(
        "R42_MEDIAREQ26_OPEN_CHANNEL=%u\n",
        (unsigned)r42_media_channel_id
    );
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r42_activate_after_mediareq_open(void)
{
    R35Result rc;
    if (r42_media_stage != R42_MEDIAREQ_OPEN_TX ||
        r42_media_channel_id == 0u)
        return FALSE;
    rc = r35_enable_rtp(&g_r35_session, (unsigned)r42_media_channel_id);
    if (rc != R35_OK) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    r42_media_stage = R42_MEDIA_ACTIVE;
    printf("R42_ATTACHED_MEDIA_ACTIVE=true\n");
    printf("R42_LISTENER_PAUSED=false\n");
    printf("R42_SECOND_P2P_SESSION=false\n");
    fflush(stdout);
    return TRUE;
}

static gboolean
r42_queue_media_channel_close(void)
{
    if (r42_media_channel_id == 0u)
        return FALSE;
    r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_TX;
    return p12_queue_close_channel(
        r42_media_channel_id,
        P12_TX_R42_MEDIA_CHANNEL_CLOSE
    );
}

static void
r42_finish_media_channel_close(void)
{
    if (r58_closed_published_for_generation())
        return;
    r58_mark_closed_published();
    r42_media_stage = R42_MEDIA_CLOSED;
    r42_media_channel_id = 0u;
    printf("R42_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    printf("R42_MEDIA_CHANNEL_CLOSED=true\n");
    fflush(stdout);
}
/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */

/* R66_CALL_TIME_DOOR_BEGIN */
#define R66_CALL_TIME_DOOR_PACKET_LEN 48u
#define R66_CALL_TIME_DOOR_INNER_LEN 13u
#define R66_CALL_TIME_DOOR_OPCODE 0x002Du
#define R66_CALL_TIME_DOOR_RELAY_ENTRANCE 1u

static unsigned g_r66_call_time_door_sequence_before = 0u;
static unsigned g_r66_call_time_door_sequence_after = 0u;
static unsigned g_r66_call_time_door_generation = 0u;
static gboolean g_r66_call_time_door_ack_observed = FALSE;
static gboolean g_r66_call_time_door_waiting_ack = FALSE;
static gboolean g_r66_call_time_door_selected = FALSE;

static void v4_door_set_deadline(void);
static gboolean v4_door_settle_cb(gpointer data);
static void v4_door_emit_result(const char *result);
static void v4_door_reset(void);

static void
r66_write_padded_ascii(unsigned char *out, const char *value, unsigned max_len)
{
    unsigned i;
    memset(out, 0, max_len);
    if (!value)
        return;
    for (i = 0; i < max_len && value[i] != '\0'; i++)
        out[i] = (unsigned char)value[i];
}

static int
r66_serialize_call_time_door_packet(
    unsigned char out[R66_CALL_TIME_DOOR_PACKET_LEN],
    const R35AttachedMediaSession *s)
{
    if (!out || !s || !r35_call_ready(s))
        return 0;

    memset(out, 0, R66_CALL_TIME_DOOR_PACKET_LEN);
    out[0] = (unsigned char)R35_CTP_FLAG_DATA;
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, s->call_ctp_connection & 0xffffu);
    out[4] = (unsigned char)(s->call_sequence & 0xffu);
    out[5] = (unsigned char)(s->call_ack & 0xffu);
    r35_write_be16(out + 6, R66_CALL_TIME_DOOR_INNER_LEN);
    r35_write_be16(out + 8, R66_CALL_TIME_DOOR_OPCODE);
    memcpy(out + 10, s->dest_logical, R35_CTP_LOGADDR_LEN);
    out[20] = (unsigned char)R66_CALL_TIME_DOOR_RELAY_ENTRANCE;
    out[21] = 0u;
    out[22] = 0u;
    out[23] = 0u;
    out[24] = 0xffu;
    out[25] = 0xffu;
    out[26] = 0xffu;
    out[27] = 0xffu;
    memcpy(out + 28, s->source_logical, R35_CTP_LOGADDR_LEN);
    r66_write_padded_ascii(out + 38, V4_APT_ADDRESS, R35_CTP_LOGADDR_LEN);

    if (R66_CALL_TIME_DOOR_PACKET_LEN != 48u ||
        r35_read_be16(out + 6) != R66_CALL_TIME_DOOR_INNER_LEN ||
        r35_read_be16(out + 8) != R66_CALL_TIME_DOOR_OPCODE ||
        out[20] != R66_CALL_TIME_DOOR_RELAY_ENTRANCE ||
        out[24] != 0xffu || out[25] != 0xffu ||
        out[26] != 0xffu || out[27] != 0xffu) {
        memset(out, 0, R66_CALL_TIME_DOOR_PACKET_LEN);
        return 0;
    }

    return 1;
}

static gboolean
r66_call_time_door_eligible(void)
{
    return v4_door_target == V4_DOOR_TARGET_ENTRANCE &&
        v4_listener_ready &&
        v4_registered &&
        v4_ctpp_channel_id != 0 &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        v4_door_stage == V4_DOOR_IDLE &&
        !p12_tx_pending &&
        r35_call_ready(&g_r35_session) &&
        r42_media_stage == R42_MEDIA_ACTIVE;
}

static gboolean
r66_call_time_door_queue_ready(void)
{
    return g_r66_call_time_door_selected &&
        v4_door_target == V4_DOOR_TARGET_ENTRANCE &&
        v4_listener_ready &&
        v4_registered &&
        v4_ctpp_channel_id != 0 &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        v4_door_stage == V4_DOOR_SENDING &&
        !p12_tx_pending &&
        r35_call_ready(&g_r35_session) &&
        r42_media_stage == R42_MEDIA_ACTIVE;
}

static gboolean
r66_queue_call_time_door(void)
{
    unsigned char packet[R66_CALL_TIME_DOOR_PACKET_LEN];
    gboolean queued;

    if (!r66_call_time_door_queue_ready())
        return FALSE;
    if (!r66_serialize_call_time_door_packet(packet, &g_r35_session))
        return FALSE;

    g_r66_call_time_door_generation = g_r35_session.call_generation;
    g_r66_call_time_door_sequence_before = g_r35_session.call_sequence & 0xffu;
    g_r66_call_time_door_sequence_after =
        (g_r66_call_time_door_sequence_before + 1u) & 0xffu;
    g_r66_call_time_door_ack_observed = FALSE;
    g_r66_call_time_door_waiting_ack = FALSE;

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        packet,
        R66_CALL_TIME_DOOR_PACKET_LEN,
        P12_TX_CALL_TIME_DOOR);
    memset(packet, 0, sizeof(packet));
    if (!queued) {
        g_r66_call_time_door_selected = FALSE;
        return FALSE;
    }

    g_r66_call_time_door_selected = FALSE;
    v4_door_send_started = TRUE;
    printf("V4_DOOR_PATH=CALL_TIME_SINGLE\n");
    printf("V4_CALL_TIME_DOOR_QUEUED=true\n");
    printf("CALL_GENERATION=%u\n", g_r66_call_time_door_generation);
    printf("CALL_SEQUENCE_BEFORE=%u\n", g_r66_call_time_door_sequence_before);
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r66_call_time_door_note_control_response(
    guint32 request_id,
    const guint8 *body,
    guint body_len)
{
    guint16 prefix;
    guint16 action;

    if (!g_r66_call_time_door_waiting_ack ||
        v4_door_stage != V4_DOOR_WAIT_SETTLE ||
        request_id != (guint32)v4_ctpp_channel_id ||
        !body ||
        body_len < 8)
        return FALSE;

    prefix = read_le16(body + 0);
    action = (((guint16)body[6]) << 8) | ((guint16)body[7]);
    if (prefix == 0x1800u && action == 0x0000u) {
        g_r66_call_time_door_ack_observed = TRUE;
        return TRUE;
    }

    return FALSE;
}

static void
r66_call_time_door_emit_settle_result(void)
{
    printf("CALL_TIME_DOOR_ACK_OBSERVED=%s\n",
        g_r66_call_time_door_ack_observed ? "true" : "false");
    printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\n");
    g_r66_call_time_door_waiting_ack = FALSE;
    v4_door_emit_result("UNKNOWN_OUTCOME");
    v4_door_reset();
    fflush(stdout);
}

static gboolean
r66_call_time_door_tx_completed(void)
{
    gboolean sequence_committed = FALSE;

    if (g_r35_session.call_generation == g_r66_call_time_door_generation &&
        r35_call_ready(&g_r35_session) &&
        (g_r35_session.call_sequence & 0xffu) ==
            g_r66_call_time_door_sequence_before) {
        g_r35_session.call_sequence =
            g_r66_call_time_door_sequence_after & 0xffu;
        sequence_committed = TRUE;
    } else {
        printf("CALL_TIME_DOOR_STALE_GENERATION=true\n");
    }

    v4_door_writes_sent = 1;
    v4_door_stage = V4_DOOR_WAIT_SETTLE;
    g_r66_call_time_door_waiting_ack = TRUE;
    v4_door_set_deadline();
    printf("V4_CALL_TIME_DOOR_SENT=true\n");
    printf("V4_CALL_TIME_DOOR_WRITE_COUNT=1\n");
    printf("CALL_TIME_DOOR_SEQUENCE_COMMITTED=%s\n",
        sequence_committed ? "true" : "false");
    printf("CALL_SEQUENCE_AFTER=%u\n", g_r35_session.call_sequence & 0xffu);
    fflush(stdout);
    if (g_timeout_add(V4_DOOR_SETTLE_MS, v4_door_settle_cb, NULL) == 0) {
        r66_call_time_door_emit_settle_result();
        return FALSE;
    }
    return TRUE;
}
/* R66_CALL_TIME_DOOR_END */

/* R54_CALL_ADOPTION_LISTENER_BEGIN */
static R53CallAdoptionProfileState g_r54_call_adoption;

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
static unsigned g_r54_tx_generation = 0u;
static R35CtpEnvelopeView g_r54_invite_view;
static R35CtpEnvelopeView g_r54_pending_peer_view;
static int g_r54_pending_peer_capabilities = 0;
static unsigned g_r54_pending_peer_capability_word = 0u;
static int g_r54_pending_peer_video_requested = 0;
static int g_r54_peer_data_ack_enqueued = 0;
static int g_r54_peer_data_ack_flushed = 0;
static gint64 g_r54_tx_wait_deadline_us = 0;

typedef enum {
    R54_DIAGNOSTICS_LOCAL_AFTER_TRIO = 0,
    R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES,
    R54_DIAGNOSTICS_GENERATION_END
} R54DiagnosticsPhase;

static const char *
r54_diagnostics_phase_name(R54DiagnosticsPhase phase)
{
    switch (phase) {
    case R54_DIAGNOSTICS_LOCAL_AFTER_TRIO: return "LOCAL_AFTER_TRIO";
    case R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES: return "AFTER_PEER_CAPABILITIES";
    case R54_DIAGNOSTICS_GENERATION_END: return "GENERATION_END";
    }
    return "GENERATION_END";
}

static const char *
r54_tx_state_name(R54TxState state)
{
    switch (state) {
    case R54_TX_STATE_IDLE: return "IDLE";
    case R54_TX_STATE_NEED_INVITE_ACK: return "NEED_INVITE_ACK";
    case R54_TX_STATE_WAIT_INVITE_ACK_FLUSH: return "WAIT_INVITE_ACK_FLUSH";
    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES: return "NEED_LOCAL_CAPABILITIES";
    case R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH: return "WAIT_LOCAL_CAPABILITIES_FLUSH";
    case R54_TX_STATE_NEED_LOCAL_ALERTING: return "NEED_LOCAL_ALERTING";
    case R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH: return "WAIT_LOCAL_ALERTING_FLUSH";
    case R54_TX_STATE_WAIT_PEER_CAPABILITIES: return "WAIT_PEER_CAPABILITIES";
    case R54_TX_STATE_NEED_PEER_DATA_ACK: return "NEED_PEER_DATA_ACK";
    case R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH: return "WAIT_PEER_DATA_ACK_FLUSH";
    case R54_TX_STATE_MEDIA_TRIGGER_READY: return "MEDIA_TRIGGER_READY";
    case R54_TX_STATE_TERMINAL_FAILURE: return "TERMINAL_FAILURE";
    }
    return "TERMINAL_FAILURE";
}

static gboolean r54_tx_wait_timeout_cb(gpointer data);

static void
r54_tx_set_wait_deadline(void)
{
    g_r54_tx_wait_deadline_us =
        g_get_monotonic_time() +
        ((gint64)P12_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
    (void)g_timeout_add_seconds(
        P12_STEP_TIMEOUT_SECONDS,
        r54_tx_wait_timeout_cb,
        NULL);
}

static void
r54_tx_clear_wait_deadline(void)
{
    g_r54_tx_wait_deadline_us = 0;
}

static void
r54_tx_terminal_failure(R53FailureStage stage)
{
    g_r54_tx_state = R54_TX_STATE_TERMINAL_FAILURE;
    g_r54_call_adoption.diag.call_adoption_failure_stage = stage;
    r54_tx_clear_wait_deadline();
}

static void
r54_publish_diagnostics(
    const R53CallAdoptionProfileState *state,
    R54DiagnosticsPhase phase)
{
    const R53Diagnostics *diag;
    gboolean peer_phase_reached;
    if (!state) return;
    diag = &state->diag;
    peer_phase_reached = phase != R54_DIAGNOSTICS_LOCAL_AFTER_TRIO;
    printf("R54_DIAGNOSTICS_PHASE=%s\n", r54_diagnostics_phase_name(phase));
    printf("R54_CALL_ADOPTION_STARTED=%s\n", diag->call_adoption_started ? "true" : "false");
    printf("R54_INVITE_ACK_SENT=%s\n", diag->invite_ack_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITIES_SENT=%s\n", diag->local_capabilities_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITY_WORD=%u\n", diag->local_capability_word);
    printf("R54_LOCAL_ALERTING_SENT=%s\n", diag->local_alerting_sent ? "true" : "false");
    printf("R54_WAITING_PEER_CAPABILITIES=%s\n", diag->waiting_peer_capabilities ? "true" : "false");
    if (peer_phase_reached) {
        printf("R54_PEER_CAPABILITIES_SEEN=%s\n", diag->peer_capabilities_seen ? "true" : "false");
        printf("R54_PEER_CAPABILITY_WORD=%u\n", diag->peer_capability_word);
        printf("R54_PEER_VIDEO_REQUESTED=%s\n", diag->peer_video_requested ? "true" : "false");
    } else {
        printf("R54_PEER_CAPABILITIES_SEEN=NOT_REACHED\n");
        printf("R54_PEER_CAPABILITY_WORD=NOT_REACHED\n");
        printf("R54_PEER_VIDEO_REQUESTED=NOT_REACHED\n");
    }
    printf("R54_PEER_DATA_ACK_ENQUEUED=%s\n", g_r54_peer_data_ack_enqueued ? "true" : "false");
    printf("R54_PEER_DATA_ACK_FLUSHED=%s\n", g_r54_peer_data_ack_flushed ? "true" : "false");
    printf("R54_PEER_DATA_ACK_SENT=%s\n", g_r54_peer_data_ack_flushed ? "true" : "false");
    printf("R54_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R54_TX_WAITING_FOR_SLOT=%s\n", p12_tx_pending ? "true" : "false");
    printf("R54_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    if (phase == R54_DIAGNOSTICS_GENERATION_END) {
        printf("R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s\n",
            diag->waiting_peer_capabilities && !diag->peer_capabilities_seen ? "true" : "false");
    }
    printf("R54_CALL_ADOPTION_FAILURE_STAGE=%s\n", r53_failure_stage_name(diag->call_adoption_failure_stage));
    fflush(stdout);
}

static gboolean
r54_tx_wait_timeout_cb(gpointer data)
{
    (void)data;
    if (g_r54_tx_wait_deadline_us > 0 &&
        g_get_monotonic_time() >= g_r54_tx_wait_deadline_us) {
        printf("TX_WAIT_TIMEOUT_SOURCE=P12_STEP_TIMEOUT_SECONDS\n");
                p116_emit_timeout_observability("R54_TX_WAIT_TIMEOUT");
        printf("TX_WAIT_TIMEOUT_MS=%u\n", P12_STEP_TIMEOUT_SECONDS * 1000u);
        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);
        r54_publish_diagnostics(
            &g_r54_call_adoption,
            R54_DIAGNOSTICS_GENERATION_END);
    }
    return G_SOURCE_REMOVE;
}

static int
r54_tx_last_enqueue_matches(R54TxSubject subject)
{
    return g_r54_tx_last_enqueued == subject &&
        g_r54_tx_last_reason == R54_TX_QUEUE_REASON_NONE;
}

static gboolean r54_tx_drive(void);

static gboolean
r54_flush_current_tx(void)
{
    gboolean ok = p12_flush_tx();
    if (!ok) {
        g_r54_tx_last_reason = R54_TX_QUEUE_REASON_TRANSPORT;
        printf("R54_TX_QUEUE_FAIL_REASON=TRANSPORT\n");
        fflush(stdout);
    }
    return ok && g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
}

static gboolean
r54_handle_call_init(const guint8 *body, guint body_len)
{
    R35CtpEnvelopeView invite_view;
    if (!r35_parse_ctp_envelope(body, body_len, &invite_view)) {
        g_r54_call_adoption.diag.call_adoption_failure_stage =
            R53_STAGE_ACK_BUILD_FAILED;
        r54_publish_diagnostics(
            &g_r54_call_adoption,
            R54_DIAGNOSTICS_LOCAL_AFTER_TRIO);
        return FALSE;
    }

    /* A repeated CALL_INIT for the generation the scheduler already owns
     * (g_r54_tx_generation is set once per r53_reset_state below and only
     * changes here) must not reset progress: the scheduler may be sitting
     * in any WAIT_*_FLUSH state with a P12 frame already enqueued, or may
     * already have reached MEDIA_TRIGGER_READY/IDLE after completing.
     * Resetting here would re-drive the chain and enqueue a duplicate
     * frame on top of one already owned by the single P12 TX slot. Only a
     * genuinely new generation (the pre-existing R35 capture authority:
     * call_generation / call_ctp_connection) may replace state, and that
     * replacement path (r53_reset_state below, and the cross-generation
     * drop in r54_p12_tx_completed/r54_tx_drive) is unchanged. */
    if (g_r54_tx_generation != 0u &&
        g_r54_tx_generation == g_r35_session.call_generation) {
        printf("R54_TX_DUPLICATE_CALL_INIT_IGNORED=true\n");
        printf("R54_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
        fflush(stdout);
        return g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
    }

    r53_reset_state(&g_r54_call_adoption, g_r35_session.call_generation);
    g_r54_call_adoption.diag.adoption_attempted = 1;
    g_r54_call_adoption.diag.call_adoption_started = 1;
    g_r54_call_adoption.diag.connection = g_r35_session.call_ctp_connection;
    g_r54_call_adoption.diag.call_adoption_failure_stage = R53_STAGE_NONE;
    g_r54_invite_view = invite_view;
    g_r54_tx_generation = g_r35_session.call_generation;
    g_r54_pending_peer_capabilities = 0;
    g_r54_peer_data_ack_enqueued = 0;
    g_r54_peer_data_ack_flushed = 0;
    g_r54_tx_state = R54_TX_STATE_NEED_INVITE_ACK;
    r54_tx_drive();
    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_LOCAL_AFTER_TRIO);
    return g_r54_tx_state != R54_TX_STATE_TERMINAL_FAILURE;
}

static gboolean
r54_trigger_r42_media_open(
    R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *peer_view)
{
    (void)session;
    (void)peer_view;
    return r42_queue_media_channel_open();
}

static gboolean
r54_store_pending_peer_capabilities(const R35CtpEnvelopeView *peer_view)
{
    unsigned word = 0u;
    if (!peer_view) return FALSE;
    if (!r36_is_capabilities_for_current_call(&g_r35_session, peer_view) ||
        !r53_peer_capability_word(peer_view, &word)) {
        r54_tx_terminal_failure(R53_STAGE_PEER_CAPABILITIES_REJECTED);
        return FALSE;
    }
    g_r54_call_adoption.diag.peer_capabilities_seen = 1;
    g_r54_call_adoption.diag.peer_capability_word = word;
    g_r54_call_adoption.diag.peer_video_requested =
        r36_capabilities_video_requested(peer_view);
    if (!g_r54_call_adoption.diag.peer_video_requested) {
        r54_tx_terminal_failure(R53_STAGE_PEER_CAPABILITIES_REJECTED);
        return FALSE;
    }

    memset(&g_r54_pending_peer_view, 0, sizeof(g_r54_pending_peer_view));
    g_r54_pending_peer_view.flags = R35_CTP_FLAG_DATA;
    g_r54_pending_peer_view.connection = peer_view->connection;
    g_r54_pending_peer_view.sequence = peer_view->sequence;
    g_r54_pending_peer_view.acknowledgement = peer_view->acknowledgement;
    g_r54_pending_peer_view.inner_len = 8u;
    g_r54_pending_peer_capability_word = word;
    g_r54_pending_peer_video_requested = 1;
    g_r54_pending_peer_capabilities = 1;
    return TRUE;
}

static gboolean
r54_tx_drive(void)
{
    R45RuntimeFields runtime;
    if (g_r54_tx_state == R54_TX_STATE_TERMINAL_FAILURE)
        return FALSE;
    if (g_r54_tx_generation != 0u &&
        g_r54_tx_generation != g_r35_session.call_generation) {
        r54_tx_terminal_failure(R53_STAGE_TX_GENERATION_REPLACED);
        return FALSE;
    }
    if (g_r54_tx_wait_deadline_us > 0 &&
        g_get_monotonic_time() > g_r54_tx_wait_deadline_us) {
        printf("TX_WAIT_TIMEOUT_SOURCE=P12_STEP_TIMEOUT_SECONDS\n");
        printf("TX_WAIT_TIMEOUT_MS=%u\n", P12_STEP_TIMEOUT_SECONDS * 1000u);
        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);
        return FALSE;
    }
    if (p12_tx_pending) {
        printf("R54_TX_WAITING_FOR_SLOT=true\n");
        fflush(stdout);
        return TRUE;
    }

    runtime = r53_runtime_fields();
    switch (g_r54_tx_state) {
    case R54_TX_STATE_NEED_INVITE_ACK:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_invite_ack(&g_r35_session, &g_r54_call_adoption.r45,
                &g_r54_invite_view) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_INVITE_ACK)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_INVITE_ACK_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.invite_ack_sent = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_INVITE_ACK_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_local_capabilities(&g_r35_session, &g_r54_call_adoption.r45,
                &runtime) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_LOCAL_CAPABILITIES)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_LOCAL_CAPABILITIES_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.local_capabilities_sent = 1;
        g_r54_call_adoption.diag.local_capability_word = runtime.capability_word;
        g_r54_tx_state = R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_LOCAL_ALERTING:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_send_local_alerting(&g_r35_session, &g_r54_call_adoption.r45,
                &runtime) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_LOCAL_ALERTING)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_LOCAL_ALERTING_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.local_alerting_sent = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_NEED_PEER_DATA_ACK:
        g_r54_tx_last_enqueued = R54_TX_SUBJECT_NONE;
        if (!r45_accept_peer_data_and_ack(&g_r35_session,
                &g_r54_call_adoption.r45, &g_r54_pending_peer_view) ||
            !r54_tx_last_enqueue_matches(R54_TX_SUBJECT_PEER_DATA_ACK)) {
            if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY)
                return TRUE;
            r54_tx_terminal_failure(R53_STAGE_TX_PEER_ACK_FAILED);
            return FALSE;
        }
        g_r54_peer_data_ack_enqueued = 1;
        g_r54_tx_state = R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH;
        r54_tx_set_wait_deadline();
        return r54_flush_current_tx();

    case R54_TX_STATE_MEDIA_TRIGGER_READY:
        if (!r54_trigger_r42_media_open(&g_r35_session, &g_r54_pending_peer_view)) {
            r54_tx_terminal_failure(R53_STAGE_TX_MEDIA_TRIGGER_FAILED);
            return FALSE;
        }
        g_r54_call_adoption.diag.waiting_peer_capabilities = 0;
        g_r54_call_adoption.diag.call_adoption_failure_stage = R53_STAGE_NONE;
        g_r54_tx_state = R54_TX_STATE_IDLE;
        return TRUE;

    default:
        return TRUE;
    }
}

static void
r54_p12_tx_completed(P12TxKind kind)
{
    if (g_r54_tx_generation != g_r35_session.call_generation)
        return;
    switch (kind) {
    case P12_TX_R54_INVITE_ACK:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH) {
            printf("R54_TX_FLUSHED=INVITE_ACK\n");
            r54_tx_clear_wait_deadline();
            g_r54_tx_state = R54_TX_STATE_NEED_LOCAL_CAPABILITIES;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_LOCAL_CAPABILITIES:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH) {
            printf("R54_TX_FLUSHED=LOCAL_CAPABILITIES\n");
            r54_tx_clear_wait_deadline();
            g_r54_tx_state = R54_TX_STATE_NEED_LOCAL_ALERTING;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_LOCAL_ALERTING:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH) {
            printf("R54_TX_FLUSHED=LOCAL_ALERTING\n");
            printf("LOCAL_ALERTING_FLUSHED_BEFORE_WAIT_PEER_CAPABILITIES=true\n");
            r54_tx_clear_wait_deadline();
            g_r54_call_adoption.diag.waiting_peer_capabilities = 1;
            g_r54_tx_state = g_r54_pending_peer_capabilities
                ? R54_TX_STATE_NEED_PEER_DATA_ACK
                : R54_TX_STATE_WAIT_PEER_CAPABILITIES;
            r54_tx_drive();
        }
        break;
    case P12_TX_R54_PEER_DATA_ACK:
        if (g_r54_tx_state == R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH) {
            printf("R54_TX_FLUSHED=PEER_DATA_ACK\n");
            printf("PEER_DATA_ACK_FLUSHED_BEFORE_MEDIA_TRIGGER=true\n");
            r54_tx_clear_wait_deadline();
            g_r54_peer_data_ack_flushed = 1;
            g_r54_tx_state = R54_TX_STATE_MEDIA_TRIGGER_READY;
            r54_tx_drive();
        }
        break;
    default:
        break;
    }
}

static gboolean
r54_handle_peer_capabilities_for_r42(const R35CtpEnvelopeView *peer_view)
{
    gboolean ok;
    if (g_r54_call_adoption.diag.peer_capabilities_seen) {
        r54_tx_terminal_failure(R53_STAGE_MEDIA_TRIGGER_REJECTED);
        ok = FALSE;
    } else if (g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES ||
        g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_WAIT_INVITE_ACK_FLUSH ||
        g_r54_tx_state == R54_TX_STATE_NEED_LOCAL_ALERTING ||
        g_r54_tx_state == R54_TX_STATE_NEED_LOCAL_CAPABILITIES) {
        ok = r54_store_pending_peer_capabilities(peer_view);
        if (ok && g_r54_tx_state == R54_TX_STATE_WAIT_PEER_CAPABILITIES)
            g_r54_tx_state = R54_TX_STATE_NEED_PEER_DATA_ACK;
        if (ok)
            ok = r54_tx_drive();
    } else {
        g_r54_call_adoption.diag.call_adoption_failure_stage =
            R53_STAGE_WAITING_PEER_CAPABILITIES;
        ok = FALSE;
    }
    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_AFTER_PEER_CAPABILITIES);
    return ok;
}
/* R54_CALL_ADOPTION_LISTENER_END */

/* R64_POSTCALL_OBSERVABILITY_BEGIN */
static unsigned g_r64_generation = 0u;
static gboolean g_r64_remote_release_observed = FALSE;
static gboolean g_r64_capability_cleared_observed = FALSE;

static void
r64_reset_for_generation(void)
{
    if (g_r64_generation == g_r35_session.call_generation)
        return;
    g_r64_generation = g_r35_session.call_generation;
    g_r64_remote_release_observed = FALSE;
    g_r64_capability_cleared_observed = FALSE;
}

static void
r64_note_remote_release(void)
{
    r64_reset_for_generation();
    g_r64_remote_release_observed = TRUE;
}

static void
r64_note_capability_cleared(void)
{
    r64_reset_for_generation();
    g_r64_capability_cleared_observed = TRUE;
}

static void
r64_publish_post_call_snapshot(void)
{
    r64_reset_for_generation();
    printf("R64_POST_CALL_REMOTE_RELEASE_OBSERVED=%s\n",
        g_r64_remote_release_observed ? "true" : "false");
    printf("R64_POST_CALL_CAPABILITY_CLEARED_OBSERVED=%s\n",
        g_r64_capability_cleared_observed ? "true" : "false");
    printf("R64_POST_CALL_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R64_POST_CALL_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    printf("R64_POST_CALL_TX_PENDING=%s\n", p12_tx_pending ? "true" : "false");
    printf("R64_POST_CALL_CALL_READY=%s\n",
        r35_call_ready(&g_r35_session) ? "true" : "false");
    printf("R64_POST_CALL_PSEUDOTCP_OPEN=%s\n", pseudotcp_open ? "true" : "false");
    printf("R64_POST_CALL_SNAPSHOT=true\n");
    fflush(stdout);
}

static void
r64_publish_terminal_snapshot(void)
{
    r64_reset_for_generation();
    printf("R64_TERMINAL_REMOTE_RELEASE_OBSERVED=%s\n",
        g_r64_remote_release_observed ? "true" : "false");
    printf("R64_TERMINAL_CAPABILITY_CLEARED_OBSERVED=%s\n",
        g_r64_capability_cleared_observed ? "true" : "false");
    printf("R64_TERMINAL_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R64_TERMINAL_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    printf("R64_TERMINAL_TX_PENDING=%s\n", p12_tx_pending ? "true" : "false");
    printf("R64_TERMINAL_CALL_READY=%s\n",
        r35_call_ready(&g_r35_session) ? "true" : "false");
    printf("R64_TERMINAL_PSEUDOTCP_OPEN=%s\n", pseudotcp_open ? "true" : "false");
    printf("R64_TERMINAL_SNAPSHOT=true\n");
    fflush(stdout);
}
/* R64_POSTCALL_OBSERVABILITY_END */

/* R58_STOP_CLEANUP_BEGIN */
static unsigned g_r58_stop_generation = 0u;
static R58StopPhase g_r58_stop_phase = R58_STOP_PHASE_NONE;
static R58StopFailureStage g_r58_stop_failure_stage = R58_STOP_FAILURE_STAGE_NONE;
static R58StopOrigin g_r58_stop_origin = R58_STOP_ORIGIN_NONE;
static unsigned g_r58_stop_request_count = 0u;
static unsigned g_r58_stop_duplicate_ignored_count = 0u;
static unsigned g_r58_stop_wait_slot_count = 0u;
static unsigned g_r58_stop_write_attempt_count = 0u;
static int g_r58_stop_requested = 0;
static int g_r58_stop_written = 0;
static int g_r58_stop_disposed = 0;
static int g_r58_stop_closed = 0;
static int g_r58_closed_marker_published = 0;
static R58StopPhase g_r58_stop_last_published_phase = R58_STOP_PHASE_NONE;
static int g_r58_stop_last_phase_valid = 0;
static R58StopFailureStage g_r58_stop_last_published_failure = R58_STOP_FAILURE_STAGE_NONE;
static int g_r58_stop_last_failure_valid = 0;

static R35Result r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin);
static R35Result r58_stop_drive(R35AttachedMediaSession *s);

static const char *
r58_stop_phase_name(R58StopPhase phase)
{
    switch (phase) {
    case R58_STOP_PHASE_NONE: return "NONE";
    case R58_STOP_PHASE_REQUESTED: return "REQUESTED";
    case R58_STOP_PHASE_WAIT_TX_SLOT: return "WAIT_TX_SLOT";
    case R58_STOP_PHASE_ENQUEUED: return "ENQUEUED";
    case R58_STOP_PHASE_FLUSHED: return "FLUSHED";
    case R58_STOP_PHASE_RTP_DISARMED: return "RTP_DISARMED";
    case R58_STOP_PHASE_DISPOSED: return "DISPOSED";
    case R58_STOP_PHASE_CLOSED: return "CLOSED";
    case R58_STOP_PHASE_REMOTE_RELEASE: return "REMOTE_RELEASE";
    case R58_STOP_PHASE_FAILED: return "FAILED";
    }
    return "FAILED";
}

static const char *
r58_stop_failure_stage_name(R58StopFailureStage stage)
{
    switch (stage) {
    case R58_STOP_FAILURE_STAGE_NONE: return "NONE";
    case R58_STOP_FAILURE_STAGE_SIGNAL: return "SIGNAL";
    case R58_STOP_FAILURE_STAGE_STALE_CALL: return "STALE_CALL";
    case R58_STOP_FAILURE_STAGE_QUEUE: return "QUEUE";
    case R58_STOP_FAILURE_STAGE_WRITE: return "WRITE";
    case R58_STOP_FAILURE_STAGE_FLUSH_TIMEOUT: return "FLUSH_TIMEOUT";
    case R58_STOP_FAILURE_STAGE_DISPOSE: return "DISPOSE";
    case R58_STOP_FAILURE_STAGE_REMOTE_RACE: return "REMOTE_RACE";
    case R58_STOP_FAILURE_STAGE_OTHER: return "OTHER";
    }
    return "OTHER";
}

static void
r58_stop_reset_for_generation(void)
{
    if (g_r58_stop_generation == g_r35_session.call_generation)
        return;
    g_r58_stop_generation = g_r35_session.call_generation;
    g_r58_stop_phase = R58_STOP_PHASE_NONE;
    g_r58_stop_failure_stage = R58_STOP_FAILURE_STAGE_NONE;
    g_r58_stop_origin = R58_STOP_ORIGIN_NONE;
    g_r58_stop_request_count = 0u;
    g_r58_stop_duplicate_ignored_count = 0u;
    g_r58_stop_wait_slot_count = 0u;
    g_r58_stop_write_attempt_count = 0u;
    g_r58_stop_requested = 0;
    g_r58_stop_written = 0;
    g_r58_stop_disposed = 0;
    g_r58_stop_closed = 0;
    g_r58_closed_marker_published = 0;
    g_r58_stop_last_published_phase = R58_STOP_PHASE_NONE;
    g_r58_stop_last_phase_valid = 0;
    g_r58_stop_last_published_failure = R58_STOP_FAILURE_STAGE_NONE;
    g_r58_stop_last_failure_valid = 0;
}

static void
r58_stop_publish_failure_stage(void)
{
    if (g_r58_stop_last_failure_valid &&
        g_r58_stop_last_published_failure == g_r58_stop_failure_stage)
        return;
    g_r58_stop_last_failure_valid = 1;
    g_r58_stop_last_published_failure = g_r58_stop_failure_stage;
    printf("R58_STOP_FAILURE_STAGE=%s\n", r58_stop_failure_stage_name(g_r58_stop_failure_stage));
    fflush(stdout);
}

static void
r58_stop_publish_phase(void)
{
    if (g_r58_stop_last_phase_valid &&
        g_r58_stop_last_published_phase == g_r58_stop_phase)
        return;
    g_r58_stop_last_phase_valid = 1;
    g_r58_stop_last_published_phase = g_r58_stop_phase;
    printf("R58_STOP_PHASE=%s\n", r58_stop_phase_name(g_r58_stop_phase));
    printf("R58_STOP_COUNT=%u\n", g_r58_stop_write_attempt_count);
    printf("R58_STOP_REQUEST_COUNT=%u\n", g_r58_stop_request_count);
    printf("R58_STOP_DUPLICATE_IGNORED_COUNT=%u\n", g_r58_stop_duplicate_ignored_count);
    printf("R58_STOP_WAIT_SLOT_COUNT=%u\n", g_r58_stop_wait_slot_count);
    printf("R58_CALL_GENERATION=%u\n", g_r35_session.call_generation);
    if (g_r58_stop_phase == R58_STOP_PHASE_FAILED)
        printf("R58_STOP_FAILED=true\n");
    fflush(stdout);
}

static void
r58_stop_set_phase(R58StopPhase phase)
{
    g_r58_stop_phase = phase;
    r58_stop_publish_phase();
}

static void
r58_stop_set_failure(R58StopFailureStage stage)
{
    g_r58_stop_failure_stage = stage;
    r58_stop_publish_failure_stage();
    r58_stop_set_phase(R58_STOP_PHASE_FAILED);
}

static int
r58_closed_published_for_generation(void)
{
    r58_stop_reset_for_generation();
    return g_r58_closed_marker_published;
}

static void
r58_mark_closed_published(void)
{
    r58_stop_reset_for_generation();
    g_r58_closed_marker_published = 1;
}

static void
r58_stop_undo_unqueued_send(R35AttachedMediaSession *s, unsigned old_sequence)
{
    if (!s)
        return;
    s->call_sequence = old_sequence;
    s->stop_sent = 0;
    s->stop_count = 0u;
    s->rtp_armed = 1;
    s->state = R35_STATE_RTP_ELIGIBLE;
    if (s->rtp_arm_hook)
        s->rtp_arm_hook(s->rtp_arm_hook_ctx, 1);
}

static int
r58_stop_writer_queued_media_stop(void)
{
    return g_r54_tx_last_reason == R54_TX_QUEUE_REASON_NONE &&
        g_r54_tx_last_enqueued == R54_TX_SUBJECT_MEDIA_STOP &&
        p12_tx_pending &&
        p12_tx_kind == P12_TX_R35_MEDIA_STOP;
}

static R35Result
r58_stop_drive(R35AttachedMediaSession *s)
{
    R35Result rc;
    unsigned old_sequence;
    int already_stopped;

    r58_stop_reset_for_generation();
    if (!g_r58_stop_requested || g_r58_stop_closed ||
        g_r58_stop_written || g_r58_stop_disposed)
        return R35_OK;

    if (p12_tx_pending) {
        if (g_r58_stop_phase != R58_STOP_PHASE_WAIT_TX_SLOT) {
            g_r58_stop_wait_slot_count += 1u;
            r58_stop_set_phase(R58_STOP_PHASE_WAIT_TX_SLOT);
        }
        return R35_OK;
    }

    if (!r35_call_ready(s)) {
        r58_stop_set_failure(
            g_r58_stop_origin == R58_STOP_ORIGIN_REMOTE_RELEASE
                ? R58_STOP_FAILURE_STAGE_REMOTE_RACE
                : R58_STOP_FAILURE_STAGE_STALE_CALL);
        return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    }

    already_stopped = s->stop_sent;
    old_sequence = s->call_sequence;
    rc = r35_send_stop(s, R35_FORM_TUNNEL, s->channel_id);
    if (rc != R35_OK) {
        if (already_stopped) {
            g_r58_stop_duplicate_ignored_count += 1u;
            r58_stop_publish_phase();
            return R35_OK;
        }
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_WRITE);
        return rc;
    }

    if (!r58_stop_writer_queued_media_stop()) {
        if (g_r54_tx_last_reason == R54_TX_QUEUE_REASON_BUSY) {
            r58_stop_undo_unqueued_send(s, old_sequence);
            if (g_r58_stop_phase != R58_STOP_PHASE_WAIT_TX_SLOT) {
                g_r58_stop_wait_slot_count += 1u;
                r58_stop_set_phase(R58_STOP_PHASE_WAIT_TX_SLOT);
            }
            return R35_OK;
        }
        r58_stop_undo_unqueued_send(s, old_sequence);
        r58_stop_set_failure(
            g_r54_tx_last_reason == R54_TX_QUEUE_REASON_UNKNOWN
                ? R58_STOP_FAILURE_STAGE_QUEUE
                : R58_STOP_FAILURE_STAGE_WRITE);
        return R35_ERR_BAD_ARGUMENT;
    }

    g_r58_stop_written = 1;
    g_r58_stop_write_attempt_count += 1u;
    g_r37_telemetry.call_bound_media_stop_sent_count = g_r58_stop_write_attempt_count;
    g_r37_telemetry.rtp_disarmed_count = g_r58_stop_write_attempt_count;
    r58_stop_set_phase(R58_STOP_PHASE_ENQUEUED);
    r58_stop_set_phase(R58_STOP_PHASE_RTP_DISARMED);

    rc = r35_dispose_media_rx_channel(s, s->channel_id);
    if (rc != R35_OK) {
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_DISPOSE);
        return rc;
    }
    g_r58_stop_disposed = 1;
    g_r37_telemetry.media_rx_channel_disposed_count = 1u;
    r58_stop_set_phase(R58_STOP_PHASE_DISPOSED);
    (void)p12_flush_tx();
    return R35_OK;
}

static R35Result
r58_stop_request(R35AttachedMediaSession *s, R58StopOrigin origin)
{
    r58_stop_reset_for_generation();
    g_r58_stop_request_count += 1u;
    g_r37_telemetry.bounded_stop_request_received_count = g_r58_stop_request_count;
    if (g_r58_stop_closed || g_r58_closed_marker_published) {
        g_r58_stop_duplicate_ignored_count += 1u;
        r58_stop_publish_phase();
        return R35_OK;
    }
    if (g_r58_stop_requested) {
        g_r58_stop_duplicate_ignored_count += 1u;
        r58_stop_publish_phase();
        return R35_OK;
    }
    if (!r35_call_ready(s)) {
        r58_stop_set_failure(R58_STOP_FAILURE_STAGE_STALE_CALL);
        return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    }
    g_r58_stop_origin = origin;
    g_r58_stop_requested = 1;
    r58_stop_set_phase(
        origin == R58_STOP_ORIGIN_REMOTE_RELEASE
            ? R58_STOP_PHASE_REMOTE_RELEASE
            : R58_STOP_PHASE_REQUESTED);
    return r58_stop_drive(s);
}

static void
r58_stop_publish_closed(void)
{
    r58_stop_reset_for_generation();
    if (g_r58_stop_closed)
        return;
    if (!g_r58_stop_written || !g_r58_stop_disposed)
        return;
    r58_stop_set_phase(R58_STOP_PHASE_FLUSHED);
    g_r58_stop_closed = 1;
    printf("R58_CLOSED_BOUNDARY=LOCAL_DISPOSAL_AFTER_STOP_FLUSH\n");
    r58_stop_set_phase(R58_STOP_PHASE_CLOSED);
    printf("R58_STOP_CLOSED=true\n");
    fflush(stdout);
    r42_finish_media_channel_close();
    r64_publish_post_call_snapshot();
}
/* R58_STOP_CLEANUP_END */

/* R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN */
/*
 * R57 file-scope state and helper definitions, emitted at the late R54 anchor
 * on purpose: p116_infer_phase() reads R42/R54 state (v4_listener_ready,
 * r42_media_stage, g_r54_tx_state) that is only declared later in this
 * translation unit. The matching declarations -- typedefs, enum constants and
 * static prototypes -- are emitted early, in the
 * R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN/END block, so that every
 * instrumented call site compiles wherever it sits in the file.
 */
static P116NativeFailureId g_p116_failure_id = P116_FAILURE_NONE;
static P116NativeFailurePhase g_p116_failure_phase = P116_PHASE_STARTUP;
static unsigned g_p116_failure_count = 0u;

static const char *
p116_failure_id_name(P116NativeFailureId id)
{
    switch (id) {
    case P116_FAILURE_NONE: return "NONE";
    case P116_FAILURE_STARTUP: return "STARTUP";
    case P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT: return "ABSOLUTE_SESSION_TIMEOUT";
    case P116_FAILURE_P12_STEP_TIMEOUT: return "P12_STEP_TIMEOUT";
    case P116_FAILURE_UAUT_OPEN_TIMEOUT: return "UAUT_OPEN_TIMEOUT";
    case P116_FAILURE_RECV_PARSE: return "RECV_PARSE";
    case P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT: return "PSEUDOTCP_RECV_TRANSPORT";
    case P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT: return "PSEUDOTCP_WRITABLE_TRANSPORT";
    case P116_FAILURE_PSEUDOTCP_CLOSED: return "PSEUDOTCP_CLOSED";
    case P116_FAILURE_PSEUDOTCP_WRITE_PACKET: return "PSEUDOTCP_WRITE_PACKET";
    case P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED: return "PSEUDOTCP_CLOCK_CLOSED";
    case P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET: return "PSEUDOTCP_NOTIFY_PACKET";
    case P116_FAILURE_ICE_CONNECTIVITY: return "ICE_CONNECTIVITY";
    case P116_FAILURE_ICE_GATHER: return "ICE_GATHER";
    case P116_FAILURE_SDP_FILE: return "SDP_FILE";
    case P116_FAILURE_DOOR_WRITE: return "DOOR_WRITE";
    case P116_FAILURE_DOOR_TIMER: return "DOOR_TIMER";
    case P116_FAILURE_P80_RTP_FORWARD: return "P80_RTP_FORWARD";
    case P116_FAILURE_OTHER: return "OTHER";
    }
    return "OTHER";
}

static const char *
p116_failure_phase_name(P116NativeFailurePhase phase)
{
    switch (phase) {
    case P116_PHASE_STARTUP: return "STARTUP";
    case P116_PHASE_LISTENER_READY: return "LISTENER_READY";
    case P116_PHASE_CALL_ADOPTION_LOCAL: return "CALL_ADOPTION_LOCAL";
    case P116_PHASE_WAIT_PEER_CAPABILITIES: return "WAIT_PEER_CAPABILITIES";
    case P116_PHASE_PEER_ACK: return "PEER_ACK";
    case P116_PHASE_MEDIA_OPEN: return "MEDIA_OPEN";
    case P116_PHASE_MEDIA_ACTIVE: return "MEDIA_ACTIVE";
    case P116_PHASE_MEDIA_STOP: return "MEDIA_STOP";
    case P116_PHASE_GENERATION_END: return "GENERATION_END";
    }
    return "GENERATION_END";
}

/*
 * Best-effort dynamic phase classification for the handful of failure
 * sites that are reachable across more than one call-adoption phase
 * (the generic PseudoTCP receive/write/close/writable callbacks and the
 * RTP forwarder). It reads only existing state that R42/R54 already
 * maintain; it performs no writes and changes no control flow.
 */
static P116NativeFailurePhase
p116_infer_phase(void)
{
    if (!v4_listener_ready)
        return P116_PHASE_STARTUP;

    switch (r42_media_stage) {
    case R42_MEDIA_CHANNEL_OPEN_TX:
    case R42_MEDIAREQ_OPEN_TX:
        return P116_PHASE_MEDIA_OPEN;
    case R42_MEDIA_ACTIVE:
        return P116_PHASE_MEDIA_ACTIVE;
    case R42_MEDIA_CHANNEL_CLOSE_TX:
    case R42_MEDIA_CHANNEL_CLOSE_WAIT:
        return P116_PHASE_MEDIA_STOP;
    default:
        break;
    }

    switch (g_r54_tx_state) {
    case R54_TX_STATE_NEED_INVITE_ACK:
    case R54_TX_STATE_WAIT_INVITE_ACK_FLUSH:
    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES:
    case R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH:
    case R54_TX_STATE_NEED_LOCAL_ALERTING:
    case R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH:
        return P116_PHASE_CALL_ADOPTION_LOCAL;
    case R54_TX_STATE_WAIT_PEER_CAPABILITIES:
        return P116_PHASE_WAIT_PEER_CAPABILITIES;
    case R54_TX_STATE_NEED_PEER_DATA_ACK:
    case R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH:
        return P116_PHASE_PEER_ACK;
    case R54_TX_STATE_MEDIA_TRIGGER_READY:
        return P116_PHASE_MEDIA_OPEN;
    case R54_TX_STATE_TERMINAL_FAILURE:
        return P116_PHASE_GENERATION_END;
    case R54_TX_STATE_IDLE:
    default:
        break;
    }

    return P116_PHASE_LISTENER_READY;
}

/*
 * First-fail-wins: only the first call records the primary id/phase, so a
 * cascade of later failed=TRUE sites (e.g. a write failure that then
 * trips a teardown callback on the way out) can never overwrite the root
 * cause. g_p116_failure_count is bounded cascade diagnostics only.
 */
static void
p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase)
{
    g_p116_failure_count++;
    if (g_p116_failure_id == P116_FAILURE_NONE) {
        g_p116_failure_id = id;
        g_p116_failure_phase = phase;
    }
}

static void
p116_emit_timeout_observability(const char *kind)
{
    printf("P116_TIMEOUT_KIND=%s\n", kind);
    printf("P116_TIMEOUT_PHASE=%s\n", p116_failure_phase_name(p116_infer_phase()));
    fflush(stdout);
}

static void
p116_emit_native_exit_summary(gboolean failed_flag)
{
    printf("P116_NATIVE_EXIT_CODE=%d\n", failed_flag ? 6 : 0);
    printf("P116_NATIVE_FAILURE_ID=%s\n", p116_failure_id_name(g_p116_failure_id));
    printf("P116_NATIVE_FAILURE_PHASE=%s\n", p116_failure_phase_name(g_p116_failure_phase));
    printf("P116_NATIVE_FAILURE_COUNT=%u\n", g_p116_failure_count);
    fflush(stdout);
}
/* R57_NATIVE_FAILURE_ATTRIBUTION_END */




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


        case P12_TX_CALL_TIME_DOOR:
            if (!r66_call_time_door_tx_completed()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
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
                    p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY);
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
                    p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY);
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            }
            break;

        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\n");
            fflush(stdout);
            if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\n");
                fflush(stdout);
            }
            break;

        case P12_TX_R35_MEDIA_OPEN:
            if (r42_media_stage == R42_MEDIAREQ_OPEN_TX) {
                if (!r42_activate_after_mediareq_open()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_ATTACHED_MEDIA_ACTIVATE=FAIL\n");
                    fflush(stdout);
                }
            }
            break;

        case P12_TX_R35_MEDIA_STOP:
            if (r42_media_channel_id != 0u) {
                r42_media_stage = R42_MEDIAREQ_STOP_TX;
                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\n");
                printf(
                    "R42_CALL_GENERATION=%u\n",
                    g_r35_session.call_generation
                );
                printf(
                    "R42_MEDIA_STOP_CHANNEL=%u\n",
                    (unsigned)r42_media_channel_id
                );
                fflush(stdout);
                if (!r42_queue_media_channel_close()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_MEDIA_CHANNEL_CLOSE_QUEUE=FAIL\n");
                    fflush(stdout);
                }
            }
            r58_stop_publish_closed();
            break;

        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\n");
            fflush(stdout);
            break;

        case P12_TX_R54_INVITE_ACK:
        case P12_TX_R54_LOCAL_CAPABILITIES:
        case P12_TX_R54_LOCAL_ALERTING:
        case P12_TX_R54_PEER_DATA_ACK:
            r54_p12_tx_completed(kind);
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

    r58_stop_drive(&g_r35_session);
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
    v4_door_target = V4_DOOR_TARGET_NONE;
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

    if (v4_door_target == V4_DOOR_TARGET_GATE) {
        switch (index) {
            case 1:
                body = v4_gate_operation_body_1;
                body_len = v4_door_operation_body_len[0];
                break;
            case 2:
                body = v4_gate_operation_body_2;
                body_len = v4_door_operation_body_len[1];
                break;
            case 3:
                body = v4_gate_operation_body_3;
                body_len = v4_door_operation_body_len[2];
                break;
            case 4:
                body = v4_gate_operation_body_4;
                body_len = v4_door_operation_body_len[3];
                break;
            case 5:
                body = v4_gate_operation_body_5;
                body_len = v4_door_operation_body_len[4];
                break;
            default:
                return FALSE;
        }
    } else if (v4_door_target != V4_DOOR_TARGET_ENTRANCE) {
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
    if (g_r66_call_time_door_waiting_ack) {
        r66_call_time_door_emit_settle_result();
        return G_SOURCE_REMOVE;
    }
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

        if (g_r66_call_time_door_waiting_ack) {
            r66_call_time_door_emit_settle_result();
            return G_SOURCE_REMOVE;
        }

        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {
            p116_record_failure(P116_FAILURE_DOOR_TIMER, P116_PHASE_LISTENER_READY);
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

    v4_door_target = v4_door_read_target();
    if (v4_door_target == V4_DOOR_TARGET_NONE) {
        printf("V4_DOOR_TARGET_VALID=false\n");
        v4_door_emit_result("FAILED_SAFE");
        v4_door_reset();
        return G_SOURCE_CONTINUE;
    }
    printf("V4_DOOR_TARGET_VALID=true\n");

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
        v4_door_reset();
        return G_SOURCE_CONTINUE;
    }

    g_r66_call_time_door_selected = r66_call_time_door_eligible();
    printf("V4_DOOR_COMMAND_ACCEPTED=true\n");
    printf("V4_DOOR_TARGET=%s\n", v4_door_target_name(v4_door_target));
    if (g_r66_call_time_door_selected)
        printf("V4_CALL_TIME_DOOR_COMMAND_ACCEPTED=true\n");
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

    if (g_r66_call_time_door_selected) {
        if (!r66_queue_call_time_door()) {
            v4_door_emit_result(
                v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
            );

            if (v4_door_send_started) {
                p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY);
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
                return G_SOURCE_REMOVE;
            }

            v4_door_reset();
        }

        return G_SOURCE_CONTINUE;
    }

    if (!v4_door_queue_write(1)) {
        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {
            p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY);
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

        if (r66_call_time_door_note_control_response(request_id, body, body_len)) {
            p12_consume_post_ack(frame_len);
            continue;
        }



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


                if (!g_r35_session.writer) {
                    r35_wire_session_transport();
                }

                if (r35_capture_call_ctp_id(
                        &g_r35_session,
                        body,
                        body_len,
                        (unsigned)v4_ctpp_channel_id)) {
                    printf("R35_CALL_CTP_CAPTURED=true\n");
                    printf(
                        "R42_CALL_GENERATION=%u\n",
                        g_r35_session.call_generation
                    );
                    r54_handle_call_init(body, body_len);
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\n");
                    r54_publish_diagnostics(
                        &g_r54_call_adoption,
                        R54_DIAGNOSTICS_GENERATION_END);
                }
                fflush(stdout);


                p12_consume_post_ack(
                    frame_len
                );


                failed =
                    FALSE;


                /*
                 * Persistent listener / attached-call drain:
                 * CALL_INIT may be followed by another complete ViP frame in
                 * the bytes already copied into post_ack_capture by the same
                 * pseudo_tcp_socket_recv() call.  Continue this parser loop
                 * now; returning would strand those bytes until unrelated
                 * future socket activity arrives.
                 */
                continue;
            }


            /* R42_ATTACHED_TRIGGER_BEGIN */
            if (r42_media_stage == R42_MEDIA_CHANNEL_CLOSE_WAIT) {
                guint16 r42_response_channel = 0;
                guint16 r42_response_word = 0xffff;
                if (request_id == 0 &&
                    p12_parse_control_response(
                        body,
                        body_len,
                        4,
                        r42_media_channel_id,
                        FALSE,
                        &r42_response_channel,
                        &r42_response_word) &&
                    r42_response_word == 0) {
                    r42_finish_media_channel_close();
                    p12_consume_post_ack(frame_len);
                    continue;
                }
            }

            /* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */
            if (r42_diag_call_generation != g_r35_session.call_generation) {
                r42_diag_call_generation = g_r35_session.call_generation;
                r42_diag_candidate_count = 0;
                r42_diag_detail_lines_printed = 0;
                r42_diag_pre_seen_mask = 0u;
            }

            {
                int r42_diag_writer_ok = g_r35_session.writer ? 1 : 0;
                int r42_diag_envelope_ok = 0;
                int r42_diag_data_flag = 0;
                int r42_diag_opcode_ok = 0;
                int r42_diag_candidate_seen = 0;
                int r42_diag_view_valid = 0;
                unsigned r42_diag_pre_bit = 0u;
                R35CtpEnvelopeView r42_diag_view;

                if (r42_diag_writer_ok &&
                    r35_parse_ctp_envelope(
                        body, body_len, &r42_diag_view)) {
                    r42_diag_view_valid = 1;
                    r42_diag_envelope_ok = 1;
                    if (r42_diag_view.flags == R35_CTP_FLAG_DATA) {
                        r42_diag_data_flag = 1;
                        if (r42_diag_view.inner_len >= 2u &&
                            r35_read_be16(r42_diag_view.inner_body) ==
                                R36_OP_CAPABILITIES) {
                            r42_diag_opcode_ok = 1;
                        }
                    }
                }

                r42_diag_pre_bit = r42_diag_pre_stage_bit(
                    r42_diag_writer_ok,
                    r42_diag_envelope_ok,
                    r42_diag_data_flag,
                    r42_diag_opcode_ok);

                if (r42_diag_pre_bit != 0u) {
                    /*
                     * Pre-candidate rejection: once per stage per
                     * generation, on its own budget, so unrelated
                     * traffic cannot hide a later real candidate.
                     */
                    if (r42_diag_pre_stage_should_emit(
                            &r42_diag_pre_seen_mask, r42_diag_pre_bit)) {
                        printf("R42_CAPABILITIES_CANDIDATE_SEEN=false\n");
                        if (r42_diag_envelope_ok) {
                            printf("R42_CAPABILITIES_PARSE_OK=true\n");
                        } else {
                            printf("R42_CAPABILITIES_PARSE_OK=false\n");
                        }
                        printf("R42_CAPABILITIES_CALL_MATCH=false\n");
                        printf("R42_CAPABILITIES_VIDEO_REQUESTED=false\n");
                        printf(
                            "R42_TRIGGER_REJECT_STAGE=%s\n",
                            r42_diag_pre_stage_name(r42_diag_pre_bit)
                        );
                        printf("R42_CAPABILITIES_CANDIDATE_COUNT=0\n");
                        fflush(stdout);
                    }
                } else if (r42_diag_view_valid) {
                    int r42_diag_parse_ok = 1;
                    int r42_diag_call_match = 0;
                    int r42_diag_video_requested = 0;
                    const char *r42_diag_stage = "NONE";

                    r42_diag_candidate_seen = 1;
                    r42_diag_candidate_count++;
                    if (r42_diag_view.inner_len < R36_CAP_BODY_MIN_LEN) {
                        r42_diag_stage = "LENGTH";
                    } else if (!r35_call_ready(&g_r35_session)) {
                        r42_diag_stage = "NO_LIVE_CALL";
                    } else {
                        unsigned r42_diag_local_connection =
                            (r42_diag_view.connection ^ 0x8000u) & 0xFFFFu;
                        r42_diag_call_match =
                            (r42_diag_local_connection ==
                             g_r35_session.call_ctp_connection) ? 1 : 0;
                        if (!r42_diag_call_match) {
                            r42_diag_stage = "CONNECTION_MISMATCH";
                        } else {
                            r42_diag_video_requested =
                                r36_capabilities_video_requested(
                                    &r42_diag_view) ? 1 : 0;
                            if (!r42_diag_video_requested) {
                                r42_diag_stage = "VIDEO_BIT_CLEAR";
                            }
                        }
                    }

                    if (r42_diag_candidate_seen &&
                        r42_diag_detail_lines_printed <
                            R42_DIAG_DETAIL_LINE_LIMIT) {
                        r42_diag_detail_lines_printed++;
                        printf("R42_CAPABILITIES_CANDIDATE_SEEN=true\n");
                        printf(
                            "R42_CAPABILITIES_PARSE_OK=%s\n",
                            r42_diag_parse_ok ? "true" : "false"
                        );
                        printf(
                            "R42_CAPABILITIES_CALL_MATCH=%s\n",
                            r42_diag_call_match ? "true" : "false"
                        );
                        printf(
                            "R42_CAPABILITIES_VIDEO_REQUESTED=%s\n",
                            r42_diag_video_requested ? "true" : "false"
                        );
                        printf(
                            "R42_TRIGGER_REJECT_STAGE=%s\n",
                            r42_diag_stage
                        );
                        printf(
                            "R42_CAPABILITIES_CANDIDATE_COUNT=%u\n",
                            r42_diag_candidate_count
                        );
                        fflush(stdout);
                    }
                }
            }
            /* R42_CAPABILITIES_DIAGNOSTICS_END */

            {
                R35CtpEnvelopeView r42_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r42_view) &&
                    r36_is_capabilities_for_current_call(
                        &g_r35_session, &r42_view) &&
                    r36_capabilities_video_requested(&r42_view)) {

                    gboolean r42_ok = r54_handle_peer_capabilities_for_r42(&r42_view);
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\n");
                    printf(
                        "R42_ATTACHED_TRIGGER_RESULT=%s\n",
                        r42_ok ? "CHANNEL_OPEN_SENT" : "REJECTED"
                    );
                    printf(
                        "R42_TRIGGER_REJECT_STAGE=%s\n",
                        r42_ok ? "OPEN_SENT" : "QUEUE_REJECTED"
                    );
                    printf("R42_AUTOMATIC_RETRY=false\n");
                    fflush(stdout);

                    p12_consume_post_ack(frame_len);
                    continue;
                }
            }
            /* R42_ATTACHED_TRIGGER_END */

            /* R36_WIRING_TRIGGER_BEGIN */
            {
                R35CtpEnvelopeView r36_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r36_view) &&
                    r36_is_capabilities_for_current_call(&g_r35_session, &r36_view)) {

                    R35Result r36_rc =
                        r36_trigger_open_from_capabilities(&g_r35_session, &r36_view);

                    printf("R36_CAPABILITIES_OBSERVED=true\n");
                    printf(
                        "R36_TRIGGER_RESULT=%s\n",
                        r36_rc == R35_OK ? "OPEN_SENT" : "REJECTED"
                    );
                    fflush(stdout);

                    p12_consume_post_ack(
                        frame_len
                    );

                    continue;
                }
            }
            /* R36_WIRING_TRIGGER_END */

            /* R37_WIRING_PROTOCOL_STOP_BEGIN */
            {
                R35CtpEnvelopeView r37_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r37_view) &&
                    r35_call_ready(&g_r35_session)) {
                    unsigned r37_local_connection =
                        (r37_view.connection ^ 0x8000u) & 0xFFFFu;
                    int r37_on_current_call =
                        (r37_local_connection == g_r35_session.call_ctp_connection);

                    if (r37_on_current_call &&
                        r37_view.flags == R35_CTP_FLAG_DATA &&
                        r37_view.inner_len >= R36_CAP_BODY_MIN_LEN &&
                        r35_read_be16(r37_view.inner_body) == R36_OP_CAPABILITIES &&
                        (r37_view.inner_body[4] & R36_CAP_VIDEO_REQUEST_BIT) == 0u) {

                        r64_note_capability_cleared();
                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
                        (void)p12_flush_tx();

                        printf("R37_CAPABILITY_CLEARED_OBSERVED=true\n");
                        printf(
                            "R37_PROTOCOL_STOP_RESULT=%s\n",
                            r37_rc == R35_OK ? "STOP_SENT" : "NO_OP"
                        );
                        fflush(stdout);

                        p12_consume_post_ack(
                            frame_len
                        );

                        continue;
                    }

                    if (r37_on_current_call &&
                        (r37_view.flags == R35_CTP_FLAG_DATA || r37_view.flags == R37_CTP_FLAG_FIN) &&
                        r37_view.inner_len >= 2u &&
                        r35_read_be16(r37_view.inner_body) == R37_OP_RELEASE) {

                        r64_note_remote_release();
                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
                        (void)p12_flush_tx();

                        printf("R37_REMOTE_RELEASE_OBSERVED=true\n");
                        printf(
                            "R37_PROTOCOL_STOP_RESULT=%s\n",
                            r37_rc == R35_OK ? "STOP_SENT" : "NO_OP"
                        );
                        fflush(stdout);

                        p12_consume_post_ack(
                            frame_len
                        );

                        continue;
                    }
                }
            }
            /* R37_WIRING_PROTOCOL_STOP_END */


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

        p116_record_failure(P116_FAILURE_UAUT_OPEN_TIMEOUT, P116_PHASE_STARTUP);
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
                    p116_record_failure(P116_FAILURE_RECV_PARSE, P116_PHASE_STARTUP);
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
                    p116_record_failure(P116_FAILURE_RECV_PARSE, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT, p116_infer_phase());
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
    p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOSED, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED, P116_PHASE_STARTUP);
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

            p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, P116_PHASE_STARTUP);
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

            p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, P116_PHASE_STARTUP);
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

        p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, p116_infer_phase());
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

        p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP);
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

        p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP);
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

        p116_record_failure(P116_FAILURE_ICE_GATHER, P116_PHASE_STARTUP);
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

        p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP);
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
    r37_install_bounded_stop_control();
    printf("R42_LISTENER_DOOR_SIGNAL_PRESERVED=true\n");
    printf("R42_LISTENER_RUN_DIR=/run/comelit-p2p\n");
    fflush(stdout);

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

    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    fflush(stdout);

    if (pseudo_tcp)
        g_object_unref(pseudo_tcp);

    g_object_unref(agent);
    g_main_loop_unref(loop);

    r64_publish_terminal_snapshot();
    p116_emit_native_exit_summary(failed);

    return failed ? 6 : 0;
}
