#!/usr/bin/env python3
"""P105 LEN=24 fallback diagnostic overlay.

The live diagnostic is bounded to LEN24_FALLBACK_MAX_SIGNATURES distinct
(length, PseudoTCP flags byte, PseudoTCP header-shape) signatures.  It emits
only derived structural scalars and composes P101.  It is behavior-neutral:
the media classifier, PseudoTCP notify call, notify-failure fatal path,
signaling sequence, sockets, timers, retry policy, and Door path are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p101_preactive_profile_gate_transform import (
    DEFAULT_SOURCE,
    transform as add_p101_runtime,
)


LEN24_FALLBACK_MAX_SIGNATURES = 8


_STATE_ANCHOR = """static guint64 p99_preactive_media_packets = 0;

static int p80_video_rtp_fd = -1;
"""

_STATE_INSERT = f"""static guint64 p99_preactive_media_packets = 0;

/* P105 bounded scalar-only fallback diagnostics. */
#define LEN24_FALLBACK_MAX_SIGNATURES {LEN24_FALLBACK_MAX_SIGNATURES}u

typedef struct {{
    guint len;
    guint flags;
    gboolean shape;
}} Len24FallbackSignature;

static Len24FallbackSignature len24_fallback_seen[LEN24_FALLBACK_MAX_SIGNATURES];
static guint len24_fallback_seen_count = 0;

static guint
len24_fallback_le16(const guint8 *packet, guint len, guint offset)
{{
    if (!packet || len < offset + 2u)
        return 0u;
    return ((guint)packet[offset]) | (((guint)packet[offset + 1u]) << 8);
}}

static guint
len24_fallback_version_bits(const guint8 *packet, guint len, guint offset)
{{
    if (!packet || len <= offset)
        return 0u;
    return ((guint)packet[offset] >> 6) & 3u;
}}

static gboolean
len24_fallback_stun_magic_present(const guint8 *packet, guint len)
{{
    return packet && len >= 8u &&
        packet[4] == 0x21u && packet[5] == 0x12u &&
        packet[6] == 0xa4u && packet[7] == 0x42u;
}}

static gboolean
len24_fallback_pseudotcp_header_shape(const guint8 *packet, guint len)
{{
    if (!packet || len != 24u)
        return FALSE;
    if (packet[0] != 0u || packet[1] != 0u || packet[2] != 0u || packet[3] != 0u)
        return FALSE;
    if ((packet[13] & (guint8)~0x07u) != 0u)
        return FALSE;
    for (guint i = 16u; i < 24u; i++) {{
        if (packet[i] != 0u)
            return FALSE;
    }}
    return TRUE;
}}

static guint
len24_fallback_flags_byte(const guint8 *packet, guint len)
{{
    if (!packet || len <= 13u)
        return 0u;
    return packet[13];
}}

static void
len24_fallback_diagnostic(const guint8 *packet, guint len)
{{
    guint flags = len24_fallback_flags_byte(packet, len);
    gboolean pseudo_shape = len24_fallback_pseudotcp_header_shape(packet, len);

    for (guint i = 0u; i < len24_fallback_seen_count; i++) {{
        if (len24_fallback_seen[i].len == len &&
            len24_fallback_seen[i].flags == flags &&
            len24_fallback_seen[i].shape == pseudo_shape)
            return;
    }}
    if (len24_fallback_seen_count >= LEN24_FALLBACK_MAX_SIGNATURES)
        return;

    len24_fallback_seen[len24_fallback_seen_count].len = len;
    len24_fallback_seen[len24_fallback_seen_count].flags = flags;
    len24_fallback_seen[len24_fallback_seen_count].shape = pseudo_shape;
    len24_fallback_seen_count++;

    guint inner_len = len24_fallback_le16(packet, len, 2u);
    guint version0 = len24_fallback_version_bits(packet, len, 0u);
    guint version8 = len24_fallback_version_bits(packet, len, 8u);
    guint pt8 = (packet && len > 9u) ? (((guint)packet[9]) & 0x7fu) : 0u;
    guint rtcp_pt8 = (packet && len > 9u) ? ((guint)packet[9]) : 0u;
    gboolean wrapper_ok = inner_len + 8u == len;
    gboolean rtcp_range = version8 == 2u && rtcp_pt8 >= 200u && rtcp_pt8 <= 211u;

    printf("LEN24_FALLBACK_LEN=%u\\n", len);
    printf("LEN24_FALLBACK_MEDIA_ACTIVE=%s\\n", p80_media_forwarding_enabled ? "true" : "false");
    printf("LEN24_FALLBACK_PREACTIVE_ARMED=%s\\n", p99_preactive_media_demux_armed ? "true" : "false");
    printf("LEN24_FALLBACK_WRAPPER_INNER_LEN_LE16=%u\\n", inner_len);
    printf("LEN24_FALLBACK_WRAPPER_LEN_CONSISTENT=%s\\n", wrapper_ok ? "true" : "false");
    printf("LEN24_FALLBACK_VERSION_BITS_0=%u\\n", version0);
    printf("LEN24_FALLBACK_VERSION_BITS_8=%u\\n", version8);
    printf("LEN24_FALLBACK_PT_AT_8=%u\\n", pt8);
    printf("LEN24_FALLBACK_RTCP_PT_RANGE=%s\\n", rtcp_range ? "true" : "false");
    printf("LEN24_FALLBACK_STUN_MAGIC_PRESENT=%s\\n", len24_fallback_stun_magic_present(packet, len) ? "true" : "false");
    printf("LEN24_FALLBACK_PSEUDOTCP_HEADER_SHAPE=%s\\n", pseudo_shape ? "true" : "false");
    printf("LEN24_FALLBACK_PSEUDOTCP_FLAGS_BYTE=%u\\n", flags);
    printf("LEN24_FALLBACK_DIAGNOSTIC_ONLY=true\\n");
    fflush(stdout);
}}

static int p80_video_rtp_fd = -1;
"""

_RECV_ANCHOR = """    pseudotcp_packets_in++;

    gboolean ok =
        pseudo_tcp_socket_notify_packet(
"""

_RECV_INSERT = """    len24_fallback_diagnostic((const guint8 *)buf, len);

    pseudotcp_packets_in++;

    gboolean ok =
        pseudo_tcp_socket_notify_packet(
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p101_runtime(source)
    candidate = _replace_once(candidate, _STATE_ANCHOR, _STATE_INSERT, "P105 diagnostic state")
    candidate = _replace_once(candidate, _RECV_ANCHOR, _RECV_INSERT, "P105 recv fallback diagnostic")
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P105 LEN24 FALLBACK DIAGNOSTIC TRANSFORM ===",
            "LEN24_FALLBACK_DIAGNOSTIC_TRANSFORM=PASS",
            f"LEN24_FALLBACK_MAX_SIGNATURES={LEN24_FALLBACK_MAX_SIGNATURES}",
            "LEN24_FALLBACK_BEHAVIOUR_CHANGED=false",
            "LEN24_FALLBACK_RAW_BYTES_EMITTED=false",
            "LEN24_FALLBACK_AUTOMATIC_RETRY=false",
            "LEN24_FALLBACK_SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P105 LEN24 FALLBACK DIAGNOSTIC TRANSFORM ===",
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

    args.output.write_text(transform(source_path.read_text(encoding="utf-8")), encoding="utf-8")
    print("LEN24_FALLBACK_DIAGNOSTIC_TRANSFORM=PASS")
    print("LEN24_FALLBACK_BEHAVIOUR_CHANGED=false")
    print("LEN24_FALLBACK_RAW_BYTES_EMITTED=false")
    print("LEN24_FALLBACK_AUTOMATIC_RETRY=false")
    print("LEN24_FALLBACK_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
