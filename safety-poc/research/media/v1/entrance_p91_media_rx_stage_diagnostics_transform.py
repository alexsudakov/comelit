#!/usr/bin/env python3
"""P91: bounded live-safe diagnostics for the post-active media RX boundary.

The current HA media path can reach P80_MEDIA_ACTIVE while neither PT99 video
nor PT8 audio is forwarded to the loopback RTP sockets.  P77 proved that the
official self-activation capture contains offset-8 wrapped RTP, but did not
prove that our generated RTPC CONTROL starts that media on a real panel.

This overlay composes P88 and adds metadata-only counters inside the existing
P80 receive classifier.  If no RTP was forwarded within ten seconds after the
already-gated media-active transition, the helper emits only bounded numeric
stage counters and exits fail-closed so Home Assistant preserves them in the
existing safe native failure diagnostics.  If either video or audio forwarding
has started, the diagnostic timer removes itself without changing session
lifetime.

No packet bytes, addresses, identifiers, credentials, or media content are
printed.  Protocol signaling, listener ownership, Door behavior, one-session
ownership, and the 180-second HA hard limit are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p88_disarm_v4_listener_timeout_transform import (
    DEFAULT_SOURCE,
    transform as add_p88_runtime,
)


_DIAG_VARS_ANCHOR = "static guint64 p80_audio_rtp_packets = 0;\n"
_DIAG_VARS = r'''static guint64 p80_audio_rtp_packets = 0;
static guint64 p91_media_rx_total = 0;
static guint64 p91_media_wrapper_len_match = 0;
static guint64 p91_media_inner_rtp_v2 = 0;
static guint64 p91_media_pt99 = 0;
static guint64 p91_media_pt8 = 0;
'''

_CLASSIFIER_OLD = r'''    if (!p80_media_forwarding_enabled || !packet || len < 20u)
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
'''

_CLASSIFIER_NEW = r'''    if (!p80_media_forwarding_enabled || !packet)
        return FALSE;

    p91_media_rx_total++;
    if (len < 20u)
        return FALSE;

    guint inner_len = p80_read_le16(packet + 2u);
    if (inner_len + 8u != len)
        return FALSE;
    p91_media_wrapper_len_match++;

    const guint8 *inner = packet + 8u;
    guint8 payload_type = 0;
    if (!p80_rtp_v2_shape(inner, inner_len, &payload_type))
        return FALSE;
    p91_media_inner_rtp_v2++;

    if (payload_type == 99u)
        p91_media_pt99++;
    else if (payload_type == 8u)
        p91_media_pt8++;
    else
        return FALSE;
'''

_DIAG_CALLBACK = r'''
static gboolean
p91_media_rx_diagnostic_timeout_cb(gpointer data)
{
    (void)data;

    if (p80_video_rtp_packets > 0 || p80_audio_rtp_packets > 0) {
        printf("P80_MEDIA_DIAGNOSTIC_FORWARDING_ALREADY=true\n");
        fflush(stdout);
        return G_SOURCE_REMOVE;
    }

    printf("P80_MEDIA_RX_TOTAL=%llu\n",
           (unsigned long long)p91_media_rx_total);
    printf("P80_MEDIA_WRAPPER_LEN_MATCH=%llu\n",
           (unsigned long long)p91_media_wrapper_len_match);
    printf("P80_MEDIA_INNER_RTP_V2=%llu\n",
           (unsigned long long)p91_media_inner_rtp_v2);
    printf("P80_MEDIA_PT99=%llu\n",
           (unsigned long long)p91_media_pt99);
    printf("P80_MEDIA_PT8=%llu\n",
           (unsigned long long)p91_media_pt8);
    printf("P80_MEDIA_DIAGNOSTIC_TIMEOUT=true\n");
    fflush(stdout);

    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}

'''

_ACTIVE_ARM_OLD = "    p80_media_forwarding_enabled = TRUE;\n\n    printf(\"P80_MEDIA_ACTIVE=true\\n\");\n"
_ACTIVE_ARM_NEW = "    p80_media_forwarding_enabled = TRUE;\n    g_timeout_add_seconds(10, p91_media_rx_diagnostic_timeout_cb, NULL);\n\n    printf(\"P80_MEDIA_ACTIVE=true\\n\");\n"

_CALLBACK_ANCHOR = "static gboolean\nentrance_signal_begin_media_observation(void)\n"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label} anchor count: {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p88_runtime(source)
    candidate = _replace_once(
        candidate,
        _DIAG_VARS_ANCHOR,
        _DIAG_VARS,
        "P91 diagnostic counters",
    )
    candidate = _replace_once(
        candidate,
        _CLASSIFIER_OLD,
        _CLASSIFIER_NEW,
        "P91 classifier counters",
    )
    candidate = _replace_once(
        candidate,
        _CALLBACK_ANCHOR,
        _DIAG_CALLBACK + _CALLBACK_ANCHOR,
        "P91 timeout callback",
    )
    candidate = _replace_once(
        candidate,
        _ACTIVE_ARM_OLD,
        _ACTIVE_ARM_NEW,
        "P91 timeout arm",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P91 MEDIA RX STAGE DIAGNOSTICS ===",
            "P91_COMPOSES=P88",
            "P91_DIAGNOSTIC_TIMEOUT_SECONDS=10",
            "P91_TIMEOUT_ONLY_IF_NO_FORWARDING=true",
            "P91_RX_TOTAL_COUNTER=true",
            "P91_WRAPPER_LEN_MATCH_COUNTER=true",
            "P91_INNER_RTP_V2_COUNTER=true",
            "P91_PT99_COUNTER=true",
            "P91_PT8_COUNTER=true",
            "P91_RAW_PAYLOAD_EMITTED=false",
            "P91_MEDIA_PAYLOAD_EMITTED=false",
            "P91_AUTOMATIC_RETRY=false",
            "P91_SECOND_CTPP_OPEN=false",
            "P91_DOOR_ACTION_SENT=false",
            "P91_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P91_MEDIA_HARD_LIMIT_SECONDS=180",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P91 MEDIA RX STAGE DIAGNOSTICS ===",
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

    args.output.write_text(
        transform(args.source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    print("P91_TRANSFORM=PASS")
    print("P91_DIAGNOSTIC_TIMEOUT_SECONDS=10")
    print("P91_RAW_PAYLOAD_EMITTED=false")
    print("P91_MEDIA_PAYLOAD_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
