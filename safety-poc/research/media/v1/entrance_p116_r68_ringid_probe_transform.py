#!/usr/bin/env python3
"""P116/R68 listener ring opaque body probe transform.

The CLI accepts the shared --include-p116 contract for builder symmetry.
For this listener chain, include_p116=True is a compatibility flag and does
not alter the R67 transform call; --no-include-p116 is fail-closed because
there is no supported no-P116 listener variant.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r67_attached_media_refresh_transform as r67
import entrance_p116_r68_ringid_probe_core as core

BASE_SOURCE_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
INPUT_SOURCE_SHA256 = "a850b8f96bc529e3c3016195109680b44af336954c6cfa5f8370c43dbaaa684c"

_CTPP_INBOUND_EVENT = '''            printf(
                "V4_CTPP_EVENT "
                "prefix=0x%04x "
                "action=0x%04x\\n",

                (unsigned)prefix,
                (unsigned)action
            );
'''

_CTPP_INBOUND_TRACE = '''            printf(
                "V4_CTPP_EVENT "
                "prefix=0x%04x "
                "action=0x%04x\\n",

                (unsigned)prefix,
                (unsigned)action
            );
            printf("CTPP_TRACE_DIRECTION=IN\\n");
            printf("CTPP_TRACE_OPCODE=%u\\n", (unsigned)prefix);
            printf("CTPP_TRACE_TYPE=%u\\n", (unsigned)action);
            printf("CTPP_TRACE_CHANNEL=%u\\n", (unsigned)v4_ctpp_channel_id);
            printf("CTPP_TRACE_LENGTH=%u\\n", (unsigned)frame_len);
            printf("CTPP_TRACE_MONOTONIC_MS=%llu\\n",
                (unsigned long long)(g_get_monotonic_time() / 1000));
'''

_CTPP_OUTBOUND_ANCHOR = '''    gboolean ok =
        p12_queue_bytes(
            frame,
            body_len + 8u,
            kind
        );

    memset(frame, 0, body_len + 8u);
    return ok;
'''

_CTPP_OUTBOUND_TRACE = '''    gboolean ok =
        p12_queue_bytes(
            frame,
            body_len + 8u,
            kind
        );

    if (ok) {
        printf("CTPP_TRACE_DIRECTION=OUT\\n");
        printf("CTPP_TRACE_OPCODE=%u\\n",
            body_len >= 2u ? (unsigned)(((guint16)body[0] << 8) | body[1]) : 0u);
        printf("CTPP_TRACE_TYPE=%u\\n",
            body_len >= 4u ? (unsigned)(((guint16)body[2] << 8) | body[3]) : 0u);
        printf("CTPP_TRACE_CHANNEL=%u\\n", (unsigned)(request_id & 0xffffu));
        printf("CTPP_TRACE_LENGTH=%u\\n", (unsigned)(body_len + 8u));
        printf("CTPP_TRACE_MONOTONIC_MS=%llu\\n",
            (unsigned long long)(g_get_monotonic_time() / 1000));
    }

    memset(frame, 0, body_len + 8u);
    return ok;
'''

_RTP_STATE_ANCHOR = "static guint64 p80_audio_rtp_packets = 0;\n"
_RTP_STATE_REPLACEMENT = """static guint64 p80_audio_rtp_packets = 0;
static gint64 p80_last_video_rtp_monotonic_ms = 0;
static gint64 p80_last_audio_rtp_monotonic_ms = 0;
static guint64 p80_video_packet_count_at_previous_repeat = 0;
static guint64 p80_audio_packet_count_at_previous_repeat = 0;
static gint64 p80_previous_repeat_monotonic_ms = 0;
"""

_VIDEO_INCREMENT_ANCHOR = "        p80_video_rtp_packets++;\n"
_VIDEO_INCREMENT_REPLACEMENT = """        p80_video_rtp_packets++;
        p80_last_video_rtp_monotonic_ms = g_get_monotonic_time() / 1000;
"""

_AUDIO_INCREMENT_ANCHOR = "        p80_audio_rtp_packets++;\n"
_AUDIO_INCREMENT_REPLACEMENT = """        p80_audio_rtp_packets++;
        p80_last_audio_rtp_monotonic_ms = g_get_monotonic_time() / 1000;
"""

_REFRESH_QUEUED_ANCHOR = '    printf("R67_ATTACHED_REFRESH_QUEUED=true\\n");\n'
_REFRESH_QUEUED_REPLACEMENT = '''    printf("R67_ATTACHED_REFRESH_QUEUED=true\\n");
    gint64 p80_repeat_monotonic_ms = g_get_monotonic_time() / 1000;
    gboolean p80_video_stalled =
        p80_video_packet_count_at_previous_repeat == p80_video_rtp_packets;
    gboolean p80_audio_stalled =
        p80_audio_packet_count_at_previous_repeat == p80_audio_rtp_packets;
    printf("VIDEO_PACKET_COUNT_AT_REPEAT=%llu\\n",
        (unsigned long long)p80_video_rtp_packets);
    printf("AUDIO_PACKET_COUNT_AT_REPEAT=%llu\\n",
        (unsigned long long)p80_audio_rtp_packets);
    printf("LAST_VIDEO_RTP_MONOTONIC_MS=%llu\\n",
        (unsigned long long)p80_last_video_rtp_monotonic_ms);
    printf("LAST_AUDIO_RTP_MONOTONIC_MS=%llu\\n",
        (unsigned long long)p80_last_audio_rtp_monotonic_ms);
    if (p80_video_stalled || p80_audio_stalled) {
        gint64 p80_stalled_since_monotonic_ms = p80_repeat_monotonic_ms;
        if (p80_video_stalled && p80_last_video_rtp_monotonic_ms > 0) {
            p80_stalled_since_monotonic_ms = p80_last_video_rtp_monotonic_ms;
        }
        if (p80_audio_stalled && p80_last_audio_rtp_monotonic_ms > 0 &&
            p80_last_audio_rtp_monotonic_ms > p80_stalled_since_monotonic_ms) {
            p80_stalled_since_monotonic_ms = p80_last_audio_rtp_monotonic_ms;
        }
        if (p80_stalled_since_monotonic_ms == p80_repeat_monotonic_ms &&
            p80_previous_repeat_monotonic_ms > 0) {
            p80_stalled_since_monotonic_ms = p80_previous_repeat_monotonic_ms;
        }
        printf("RX_STALLED=true\\n");
        printf("RTP_STALL_SECONDS=%llu\\n",
            (unsigned long long)((p80_repeat_monotonic_ms -
                p80_stalled_since_monotonic_ms) / 1000));
    }
    p80_video_packet_count_at_previous_repeat = p80_video_rtp_packets;
    p80_audio_packet_count_at_previous_repeat = p80_audio_rtp_packets;
    p80_previous_repeat_monotonic_ms = p80_repeat_monotonic_ms;
'''


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise RuntimeError("R68 requires --include-p116; --no-include-p116 is fail-closed")
    base_sha = _sha256_text(source)
    if base_sha != BASE_SOURCE_SHA256:
        raise RuntimeError(f"R68_BASE_SOURCE_SHA_GATE=FAIL actual={base_sha}")
    input_source = r67.transform(source)
    input_sha = _sha256_text(input_source)
    if input_sha != INPUT_SOURCE_SHA256:
        raise RuntimeError(f"R68_INPUT_SOURCE_SHA_GATE=FAIL actual={input_sha}")
    candidate = core.apply_probe(input_source)
    if candidate.count(_RTP_STATE_ANCHOR) != 1:
        raise RuntimeError("R68_RTP_STATE_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(_RTP_STATE_ANCHOR, _RTP_STATE_REPLACEMENT, 1)
    if candidate.count(_VIDEO_INCREMENT_ANCHOR) != 1:
        raise RuntimeError("R68_VIDEO_RTP_INCREMENT_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _VIDEO_INCREMENT_ANCHOR, _VIDEO_INCREMENT_REPLACEMENT, 1
    )
    if candidate.count(_AUDIO_INCREMENT_ANCHOR) != 1:
        raise RuntimeError("R68_AUDIO_RTP_INCREMENT_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _AUDIO_INCREMENT_ANCHOR, _AUDIO_INCREMENT_REPLACEMENT, 1
    )
    if candidate.count(_REFRESH_QUEUED_ANCHOR) != 1:
        raise RuntimeError("R68_REFRESH_RTP_DIAGNOSTIC_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _REFRESH_QUEUED_ANCHOR, _REFRESH_QUEUED_REPLACEMENT, 1
    )
    if candidate.count(_CTPP_INBOUND_EVENT) != 1:
        raise RuntimeError("R68_CTPP_INBOUND_TRACE_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(_CTPP_INBOUND_EVENT, _CTPP_INBOUND_TRACE, 1)
    if candidate.count(_CTPP_OUTBOUND_ANCHOR) != 1:
        raise RuntimeError("R68_CTPP_OUTBOUND_TRACE_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(_CTPP_OUTBOUND_ANCHOR, _CTPP_OUTBOUND_TRACE, 1)
    for marker in (
        "VIDEO_PACKET_COUNT_AT_REPEAT=%llu",
        "AUDIO_PACKET_COUNT_AT_REPEAT=%llu",
        "LAST_VIDEO_RTP_MONOTONIC_MS=%llu",
        "LAST_AUDIO_RTP_MONOTONIC_MS=%llu",
        "RX_STALLED=true",
        "RTP_STALL_SECONDS=%llu",
        "CTPP_TRACE_DIRECTION=IN",
        "CTPP_TRACE_DIRECTION=OUT",
        "CTPP_TRACE_OPCODE=%u",
        "CTPP_TRACE_TYPE=%u",
        "CTPP_TRACE_CHANNEL=%u",
        "CTPP_TRACE_LENGTH=%u",
        "CTPP_TRACE_MONOTONIC_MS=%llu",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R68_CTPP_TRACE_GATE=FAIL missing={marker}")
    for forbidden in ("CTPP_TRACE_PAYLOAD", "CTPP_TRACE_HEX"):
        if forbidden in candidate:
            raise RuntimeError(f"R68_CTPP_TRACE_SANITIZE_GATE=FAIL forbidden={forbidden}")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    p116 = parser.add_mutually_exclusive_group()
    p116.add_argument("--include-p116", dest="include_p116", action="store_true")
    p116.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    parser.set_defaults(include_p116=True)
    args = parser.parse_args(argv)

    if not args.include_p116:
        parser.error("R68 requires --include-p116; --no-include-p116 is fail-closed")

    generated = transform(
        args.source.read_text(encoding="utf-8"),
        include_p116=args.include_p116,
    )
    args.output.write_text(generated, encoding="utf-8")
    print("R68_RINGID_PROBE_TRANSFORM=PASS")
    print("RINGID_PROBE_SOURCE_SHA256=" + _sha256_text(generated))
    print("RAW_RING_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
