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

    if (payload_type == 99u) {{
        p80_video_rtp_packets++;
        if (p80_video_rtp_packets == 1u) {{
            printf("P80_VIDEO_RTP_FORWARDING=PASS\n");
            fflush(stdout);
        }}
    }} else {{
        p80_audio_rtp_packets++;
        if (p80_audio_rtp_packets == 1u) {{
            printf("P80_AUDIO_RTP_FORWARDING=PASS\n");
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