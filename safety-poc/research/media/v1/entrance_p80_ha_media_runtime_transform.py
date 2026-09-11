#!/usr/bin/env python3
"""Generate the HA-oriented entrance media helper from the reviewed P78 chain.

The transform keeps the P46-P78 signaling/RTPC sequence but changes the runtime
ownership boundary for production Home Assistant use:

* media uses /run/comelit-media, never the persistent listener run directory;
* SIGUSR1 Door actuation is disabled in this helper;
* the P78 three-second observation timer is replaced by manager-owned lifetime;
* structurally valid offset-8 RTP PT99/PT8 datagrams are unwrapped and forwarded
  as inner RTP to loopback UDP ports for a local HA media consumer;
* all non-media datagrams continue through the existing libnice/PseudoTCP path;
* wrapper profile is frozen independently for video and audio after first packet;
* raw media bytes are never printed.

The transform itself performs no network I/O and never executes the candidate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p78_rtpc_media_live_stage_transform import (
    DEFAULT_SOURCE,
    transform as add_p78_runtime,
)


VIDEO_RTP_PORT = 17899
AUDIO_RTP_PORT = 17808


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _block_end(text: str, opening_brace: int) -> int:
    """Return index immediately after a balanced C block, ignoring literals/comments."""
    depth = 0
    i = opening_brace
    state = "normal"
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "normal":
            if ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "/" and nxt == "/":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        elif state in {"string", "char"}:
            if ch == "\\":
                i += 1
            elif (state == "string" and ch == '"') or (
                state == "char" and ch == "'"
            ):
                state = "normal"
        elif state == "line_comment":
            if ch == "\n":
                state = "normal"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 1
        i += 1
    raise RuntimeError("unterminated C block")


def _replace_named_function(text: str, signature: str, replacement: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"function signature not found: {signature!r}")
    if text.find(signature, start + 1) >= 0:
        raise RuntimeError(f"function signature is not unique: {signature!r}")
    opening = text.find("{", start + len(signature))
    if opening < 0:
        raise RuntimeError(f"function opening brace not found: {signature!r}")
    end = _block_end(text, opening)
    return text[:start] + replacement + text[end:]


P80_RTP_RUNTIME = rf'''

/* === P80_HA_MEDIA_RTP_FORWARDING_BEGIN === */
#define P80_VIDEO_RTP_PORT {VIDEO_RTP_PORT}
#define P80_AUDIO_RTP_PORT {AUDIO_RTP_PORT}
#define P80_RTP_PROGRESS_CADENCE 50u
#define P116_RTP_TELEMETRY_CADENCE 50u
#define P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES 12u
#define P116_RTP_PT_WORD_BITS 128u
#define P116_RTP_MAX_TRACKED_SSRC 8u

static gboolean p80_media_forwarding_enabled = FALSE;
static int p80_video_rtp_fd = -1;
static int p80_audio_rtp_fd = -1;
static struct sockaddr_in p80_video_rtp_target;
static struct sockaddr_in p80_audio_rtp_target;
static gboolean p80_video_target_ready = FALSE;
static gboolean p80_audio_target_ready = FALSE;
static gboolean p80_video_profile_seen = FALSE;
static gboolean p80_audio_profile_seen = FALSE;
static guint8 p80_video_profile[6] = {{0}};
static guint8 p80_audio_profile[6] = {{0}};
static guint64 p80_video_rtp_packets = 0;
static guint64 p80_audio_rtp_packets = 0;

typedef struct {{
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
}} P116RtpTelemetry;

static P116RtpTelemetry p116_video_rtp = {{
    .payload_type = 99u,
    .is_video = TRUE
}};
static P116RtpTelemetry p116_audio_rtp = {{
    .payload_type = 8u,
    .is_video = FALSE
}};

static guint16
p80_read_le16(const guint8 *p)
{{
    return (guint16)(((guint16)p[0]) | ((guint16)p[1] << 8));
}}

static guint16
p80_read_be16(const guint8 *p)
{{
    return (guint16)(((guint16)p[0] << 8) | (guint16)p[1]);
}}

static guint32
p116_read_be32(const guint8 *p)
{{
    return ((guint32)p[0] << 24) |
           ((guint32)p[1] << 16) |
           ((guint32)p[2] << 8) |
           (guint32)p[3];
}}

static long long
p116_monotonic_ms(void)
{{
#ifdef G_USEC_PER_SEC
    return (long long)(g_get_monotonic_time() / 1000);
#else
    static long long fallback_monotonic_ms = 0;
    return ++fallback_monotonic_ms;
#endif
}}

static guint
p116_rtp_payload_offset(const guint8 *packet, guint len)
{{
    if (!packet || len < 12u || (packet[0] >> 6) != 2)
        return 0u;

    guint csrc_count = packet[0] & 0x0f;
    guint offset = 12u + 4u * csrc_count;
    if (offset > len)
        return 0u;

    if ((packet[0] & 0x10) != 0) {{
        if (offset + 4u > len)
            return 0u;
        guint extension_words = p80_read_be16(packet + offset + 2u);
        if (extension_words > (G_MAXUINT - offset - 4u) / 4u)
            return 0u;
        offset += 4u + 4u * extension_words;
        if (offset > len)
            return 0u;
    }}

    if ((packet[0] & 0x20) != 0) {{
        guint padding_len = packet[len - 1u];
        if (padding_len == 0u || padding_len > len - offset)
            return 0u;
        if (len - offset - padding_len == 0u)
            return 0u;
    }} else if (offset == len) {{
        return 0u;
    }}

    return offset;
}}

static void
p116_note_pt(P116RtpTelemetry *stream, guint8 payload_type)
{{
    if (payload_type < 64u)
        stream->pt_seen_lo |= ((guint64)1u << payload_type);
    else
        stream->pt_seen_hi |= ((guint64)1u << (payload_type - 64u));
}}

static void
p116_print_pt_set(P116RtpTelemetry *stream)
{{
    gboolean first = TRUE;
    for (guint pt = 0; pt < P116_RTP_PT_WORD_BITS; pt++) {{
        gboolean seen = pt < 64u
            ? ((stream->pt_seen_lo & ((guint64)1u << pt)) != 0)
            : ((stream->pt_seen_hi & ((guint64)1u << (pt - 64u))) != 0);
        if (seen) {{
            printf("%s%u", first ? "" : ",", pt);
            first = FALSE;
        }}
    }}
    if (first)
        printf("NONE");
}}

static void
p116_note_ssrc(P116RtpTelemetry *stream, guint32 ssrc)
{{
    if (stream->packet_count > 1u && stream->last_ssrc != ssrc)
        stream->ssrc_changes++;
    stream->last_ssrc = ssrc;

    for (guint i = 0; i < stream->tracked_ssrc_count; i++) {{
        if (stream->tracked_ssrc[i] == ssrc)
            return;
    }}
    if (stream->tracked_ssrc_count < P116_RTP_MAX_TRACKED_SSRC) {{
        stream->tracked_ssrc[stream->tracked_ssrc_count++] = ssrc;
    }} else {{
        stream->ssrc_overflow_count++;
    }}
}}

static void
p116_print_summary(P116RtpTelemetry *stream, const char *prefix)
{{
    printf("P116_%s_COUNT=%llu\n", prefix, (unsigned long long)stream->packet_count);
    if (stream->packet_count == 0u) {{
        printf("P116_%s_FIRST_SEQ=0\n", prefix);
        printf("P116_%s_LAST_SEQ=0\n", prefix);
        printf("P116_%s_FIRST_TS=0\n", prefix);
        printf("P116_%s_LAST_TS=0\n", prefix);
        printf("P116_%s_FIRST_MONOTONIC_MS=0\n", prefix);
        printf("P116_%s_LAST_MONOTONIC_MS=0\n", prefix);
    }} else {{
        printf("P116_%s_FIRST_SEQ=%u\n", prefix, stream->first_seq);
        printf("P116_%s_LAST_SEQ=%u\n", prefix, stream->last_seq);
        printf("P116_%s_FIRST_TS=%u\n", prefix, stream->first_timestamp);
        printf("P116_%s_LAST_TS=%u\n", prefix, stream->last_timestamp);
        printf("P116_%s_FIRST_MONOTONIC_MS=%lld\n", prefix, (long long)stream->first_monotonic_ms);
        printf("P116_%s_LAST_MONOTONIC_MS=%lld\n", prefix, (long long)stream->last_monotonic_ms);
    }}
    printf("P116_%s_SEQ_GAPS=%llu\n", prefix, (unsigned long long)stream->sequence_gaps);
    printf("P116_%s_DUPLICATES=%llu\n", prefix, (unsigned long long)stream->duplicates);
    printf("P116_%s_OUT_OF_ORDER=%llu\n", prefix, (unsigned long long)stream->out_of_order);
    printf("P116_%s_TIMESTAMP_REGRESSIONS=%llu\n", prefix, (unsigned long long)stream->timestamp_regressions);
    printf("P116_%s_SSRC_COUNT=%u\n", prefix, stream->tracked_ssrc_count);
    printf("P116_%s_SSRC_CHANGES=%llu\n", prefix, (unsigned long long)stream->ssrc_changes);
    printf("P116_%s_PT_SET=", prefix);
    p116_print_pt_set(stream);
    printf("\n");
    if (stream->is_video) {{
        printf("P116_VIDEO_MARKER_COUNT=%llu\n", (unsigned long long)stream->marker_count);
        printf("P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS=%lld\n", (long long)stream->first_keyframe_monotonic_ms);
        printf("P116_VIDEO_SPS_COUNT=%llu\n", (unsigned long long)stream->sps_count);
        printf("P116_VIDEO_PPS_COUNT=%llu\n", (unsigned long long)stream->pps_count);
        printf("P116_VIDEO_FUA_COUNT=%llu\n", (unsigned long long)stream->fua_count);
        printf("P116_VIDEO_SINGLE_NAL_COUNT=%llu\n", (unsigned long long)stream->single_nal_count);
    }}
    fflush(stdout);
}}

static void
p116_print_final_rtp_summary(void)
{{
    p116_print_summary(&p116_video_rtp, "VIDEO");
    p116_print_summary(&p116_audio_rtp, "AUDIO");
}}

static void
p116_classify_h264(P116RtpTelemetry *stream, const guint8 *packet, guint len, long long now_ms)
{{
    guint payload_offset = p116_rtp_payload_offset(packet, len);
    if (payload_offset == 0u || payload_offset >= len)
        return;

    guint8 nal_header = packet[payload_offset];
    guint8 nal_type = nal_header & 0x1fu;
    if (nal_type >= 1u && nal_type <= 23u) {{
        stream->single_nal_count++;
        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0)
            stream->first_keyframe_monotonic_ms = now_ms;
        else if (nal_type == 7u)
            stream->sps_count++;
        else if (nal_type == 8u)
            stream->pps_count++;
        return;
    }}

    if (nal_type == 28u) {{
        stream->fua_count++;
        if (payload_offset + 1u < len) {{
            guint8 fu_header = packet[payload_offset + 1u];
            guint8 fu_start = fu_header & 0x80u;
            guint8 original_nal_type = fu_header & 0x1fu;
            if (fu_start && original_nal_type == 5u &&
                stream->first_keyframe_monotonic_ms == 0) {{
                stream->first_keyframe_monotonic_ms = now_ms;
            }}
        }}
    }}
}}

static void
p116_observe_rtp(const guint8 *packet, guint len, guint8 payload_type)
{{
    P116RtpTelemetry *stream = payload_type == 99u
        ? &p116_video_rtp : &p116_audio_rtp;
    const char *prefix = payload_type == 99u ? "VIDEO" : "AUDIO";
    long long now_ms = p116_monotonic_ms();
    guint16 seq = p80_read_be16(packet + 2u);
    guint32 timestamp = p116_read_be32(packet + 4u);
    guint32 ssrc = p116_read_be32(packet + 8u);
    gboolean marker = (packet[1] & 0x80u) != 0;

    stream->packet_count++;
    if (stream->packet_count == 1u) {{
        stream->first_monotonic_ms = now_ms;
        stream->first_seq = seq;
        stream->max_seq = seq;
        stream->first_timestamp = timestamp;
    }} else {{
        guint16 expected = (guint16)(stream->max_seq + 1u);
        if (seq == stream->max_seq) {{
            stream->duplicates++;
        }} else if ((guint16)(seq - stream->max_seq) < 0x8000u) {{
            if (seq != expected)
                stream->sequence_gaps += (guint16)(seq - expected);
            stream->max_seq = seq;
        }} else {{
            stream->out_of_order++;
        }}
        if (timestamp < stream->last_timestamp)
            stream->timestamp_regressions++;
    }}

    stream->last_monotonic_ms = now_ms;
    stream->last_seq = seq;
    stream->last_timestamp = timestamp;
    if (marker)
        stream->marker_count++;
    p116_note_pt(stream, payload_type);
    p116_note_ssrc(stream, ssrc);
    if (payload_type == 99u)
        p116_classify_h264(stream, packet, len, now_ms);

    if (stream->packet_count == 1u) {{
        p116_print_summary(stream, prefix);
    }} else if (stream->packet_count % P116_RTP_TELEMETRY_CADENCE == 0u &&
        stream->periodic_summary_count < P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES) {{
        stream->periodic_summary_count++;
        p116_print_summary(stream, prefix);
    }}
}}

static gboolean
p80_rtp_v2_shape(const guint8 *packet, guint len, guint8 *payload_type)
{{
    if (!packet || !payload_type || len < 12 || (packet[0] >> 6) != 2)
        return FALSE;

    gboolean padding = (packet[0] & 0x20) != 0;
    gboolean extension = (packet[0] & 0x10) != 0;
    guint csrc_count = packet[0] & 0x0f;
    guint header_len = 12u + 4u * csrc_count;
    if (header_len > len)
        return FALSE;

    if (extension) {{
        if (header_len + 4u > len)
            return FALSE;
        guint extension_words = p80_read_be16(packet + header_len + 2u);
        if (extension_words > (G_MAXUINT - header_len - 4u) / 4u)
            return FALSE;
        header_len += 4u + 4u * extension_words;
        if (header_len > len)
            return FALSE;
    }}

    guint padding_len = padding ? packet[len - 1u] : 0u;
    if (padding && (padding_len == 0u || padding_len > len - header_len))
        return FALSE;
    if (len - header_len - padding_len == 0u)
        return FALSE;

    *payload_type = packet[1] & 0x7f;
    return TRUE;
}}

static gboolean
p80_profile_accept(
    const guint8 *wrapper,
    guint8 payload_type)
{{
    guint8 profile[6] = {{
        wrapper[0], wrapper[1], wrapper[4],
        wrapper[5], wrapper[6], wrapper[7]
    }};
    guint8 *expected = NULL;
    gboolean *seen = NULL;

    if (payload_type == 99u) {{
        expected = p80_video_profile;
        seen = &p80_video_profile_seen;
    }} else if (payload_type == 8u) {{
        expected = p80_audio_profile;
        seen = &p80_audio_profile_seen;
    }} else {{
        return FALSE;
    }}

    if (!*seen) {{
        memcpy(expected, profile, sizeof(profile));
        *seen = TRUE;
        return TRUE;
    }}

    return memcmp(expected, profile, sizeof(profile)) == 0;
}}

static int
p80_loopback_socket(struct sockaddr_in *target, guint16 port)
{{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0)
        return -1;

    memset(target, 0, sizeof(*target));
    target->sin_family = AF_INET;
    target->sin_port = htons(port);
    target->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return fd;
}}

static gboolean
p80_try_forward_wrapped_rtp(const guint8 *packet, guint len)
{{
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

    if (!p80_profile_accept(packet, payload_type)) {{
        fprintf(stderr, "P80_WRAPPER_PROFILE_MISMATCH=true\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }}

    int *fd = payload_type == 99u ? &p80_video_rtp_fd : &p80_audio_rtp_fd;
    struct sockaddr_in *target = payload_type == 99u
        ? &p80_video_rtp_target : &p80_audio_rtp_target;
    gboolean *target_ready = payload_type == 99u
        ? &p80_video_target_ready : &p80_audio_target_ready;
    guint16 port = payload_type == 99u
        ? P80_VIDEO_RTP_PORT : P80_AUDIO_RTP_PORT;

    if (!*target_ready) {{
        *fd = p80_loopback_socket(target, port);
        if (*fd < 0) {{
            fprintf(stderr, "P80_RTP_FORWARD_SOCKET=FAIL\n");
            failed = TRUE;
            if (loop)
                g_main_loop_quit(loop);
            return TRUE;
        }}
        *target_ready = TRUE;
    }}

    ssize_t sent = sendto(
        *fd,
        inner,
        inner_len,
        0,
        (const struct sockaddr *)target,
        sizeof(*target)
    );
    if (sent != (ssize_t)inner_len) {{
        fprintf(stderr, "P80_RTP_FORWARD_SEND=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }}

    p116_observe_rtp(inner, inner_len, payload_type);

    if (payload_type == 99u) {{
        p80_video_rtp_packets++;
        if (p80_video_rtp_packets == 1u) {{
            printf("P80_VIDEO_RTP_FORWARDING=PASS\n");
            fflush(stdout);
        }}
        if (p80_video_rtp_packets == 1u ||
            p80_video_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {{
            printf(
                "P80_VIDEO_RTP_PACKETS=%llu\n",
                (unsigned long long)p80_video_rtp_packets
            );
            fflush(stdout);
        }}
    }} else {{
        p80_audio_rtp_packets++;
        if (p80_audio_rtp_packets == 1u) {{
            printf("P80_AUDIO_RTP_FORWARDING=PASS\n");
            fflush(stdout);
        }}
        if (p80_audio_rtp_packets == 1u ||
            p80_audio_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {{
            printf(
                "P80_AUDIO_RTP_PACKETS=%llu\n",
                (unsigned long long)p80_audio_rtp_packets
            );
            fflush(stdout);
        }}
    }}

    return TRUE;
}}
/* === P80_HA_MEDIA_RTP_FORWARDING_END === */
'''


P80_MEDIA_ACTIVE_FUNCTION = r'''static gboolean
entrance_signal_begin_media_observation(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX ||
        !entrance_device_video_ack_sent ||
        p78_rtpc_stage != P78_RTPC_COMPLETE ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "P80_MEDIA_START_PRECONDITION=FAIL\n");
        return FALSE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
    p80_media_forwarding_enabled = TRUE;

    printf("P80_MEDIA_ACTIVE=true\n");
    printf("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT\n");
    printf("P80_MEDIA_AUTO_CLOSE_3000MS=false\n");
    printf("P80_VIDEO_RTP_PORT=%u\n", P80_VIDEO_RTP_PORT);
    printf("P80_AUDIO_RTP_PORT=%u\n", P80_AUDIO_RTP_PORT);
    printf("P80_DOOR_SIGNAL_ENTRYPOINT=false\n");
    printf("P80_RUN_DIR=/run/comelit-media\n");
    fflush(stdout);
    return TRUE;
}'''


OBSERVATION_READABLE_BRANCH = r'''            if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {
                entrance_media_observation_events++;
                entrance_media_observation_bytes += (guint64)n;
                if ((guint)n > entrance_media_observation_max_chunk)
                    entrance_media_observation_max_chunk = (guint)n;

                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
            }

'''


def transform(source: str) -> str:
    out = add_p78_runtime(source)

    out = _replace_once(
        out,
        '#include <signal.h>\n',
        '#include <signal.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\n',
        "socket includes",
    )
    out = _replace_once(
        out,
        '#define RUN_DIR     "/run/comelit-p2p"',
        '#define RUN_DIR     "/run/comelit-media"',
        "media run directory",
    )

    # The P30 signaling transform, which is already part of the P78 chain,
    # removes the reachable SIGUSR1 Door handler and its timer. Older sources
    # may still expose the legacy install line, so accept either proven state:
    # remove it here if present, otherwise require the inherited false marker.
    legacy_door_signal = 'signal(SIGUSR1, v4_door_signal_handler);'
    if legacy_door_signal in out:
        out = _replace_once(
            out,
            legacy_door_signal,
            'signal(SIGUSR1, SIG_IGN);',
            "disable Door signal entrypoint",
        )
    elif "ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false" not in out:
        raise RuntimeError("Door signal disable provenance missing")

    if legacy_door_signal in out:
        raise RuntimeError("Door signal entrypoint remains reachable")

    out = _replace_once(
        out,
        'static guint64 pseudotcp_app_bytes_in = 0;\n',
        'static guint64 pseudotcp_app_bytes_in = 0;\n' + P80_RTP_RUNTIME,
        "RTP forwarding runtime",
    )

    recv_signature = "static void\nrecv_cb("
    recv_start = out.find(recv_signature)
    if recv_start < 0:
        raise RuntimeError("recv_cb not found")
    recv_open = out.find("{", recv_start)
    recv_end = _block_end(out, recv_open)
    recv = out[recv_start:recv_end]
    recv = _replace_once(
        recv,
        "    if (!pseudo_tcp) {\n",
        "    if (p80_try_forward_wrapped_rtp((const guint8 *)buf, len))\n"
        "        return;\n\n"
        "    if (!pseudo_tcp) {\n",
        "recv media intercept",
    )
    out = out[:recv_start] + recv + out[recv_end:]

    out = _replace_named_function(
        out,
        "static gboolean\nentrance_signal_begin_media_observation(void)\n",
        P80_MEDIA_ACTIVE_FUNCTION,
    )
    out = _replace_once(
        out,
        "    return failed ? 6 : 0;\n}",
        "    p116_print_final_rtp_summary();\n\n    return failed ? 6 : 0;\n}",
        "P116 final RTP summary",
    )

    count = out.count(OBSERVATION_READABLE_BRANCH)
    if count != 1:
        raise RuntimeError(
            f"observation readable branch: expected one anchor, found {count}"
        )
    out = out.replace(OBSERVATION_READABLE_BRANCH, "", 1)

    return out


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P80 HA MEDIA RUNTIME TRANSFORM ===",
            "P80_COMPOSES=P46_THROUGH_P78",
            "P80_RUN_DIR=/run/comelit-media",
            "P80_DOOR_SIGNAL_ENTRYPOINT=false",
            "P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P80_MEDIA_AUTO_CLOSE_3000MS=false",
            f"P80_VIDEO_RTP_PORT={VIDEO_RTP_PORT}",
            f"P80_AUDIO_RTP_PORT={AUDIO_RTP_PORT}",
            "P80_RTP_OUTPUT_SCOPE=LOOPBACK_ONLY",
            "P80_VIDEO_PAYLOAD_TYPE=99",
            "P80_AUDIO_PAYLOAD_TYPE=8",
            "P80_RTP_PROGRESS_CADENCE=50",
            "SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P80 HA MEDIA RUNTIME TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
