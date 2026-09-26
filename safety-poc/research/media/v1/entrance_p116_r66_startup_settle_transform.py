#!/usr/bin/env python3
"""P116/R66 research overlay: startup settle duration candidates.

R66 composes the R65 production media-refresh candidate and exposes the
single cold-start settle constant as a research parameter.  The R65-equivalent
value (4000 ms, including ``None``) intentionally returns byte-identical R65
output so the live campaign has an unchanged control candidate.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r65_production_media_refresh_transform as r65
from entrance_p116_r65_production_media_refresh_transform import DEFAULT_SOURCE


ALLOWED_SETTLE_MS = (0, 500, 1000, 2000, 4000)
SETTLE_DEFINE = "#define ENTRANCE_SIGNAL_SETTLE_MS 4000"
SETTLE_CALL = "g_timeout_add(\n                        ENTRANCE_SIGNAL_SETTLE_MS,\n                        entrance_signal_start_cb,\n                        NULL)"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def _validate_settle_ms(settle_ms: int | None) -> int:
    value = 4000 if settle_ms is None else settle_ms
    if value not in ALLOWED_SETTLE_MS:
        allowed = ", ".join(str(v) for v in ALLOWED_SETTLE_MS)
        raise ValueError(f"settle_ms must be one of {allowed}; got {settle_ms!r}")
    return value


def _validate_r65_anchors(candidate: str) -> None:
    define_count = candidate.count(SETTLE_DEFINE)
    if define_count != 1:
        raise RuntimeError(f"R66 settle define anchor: expected one anchor, found {define_count}")
    call_count = candidate.count(SETTLE_CALL)
    if call_count != 1:
        raise RuntimeError(f"R66 settle schedule call anchor: expected one anchor, found {call_count}")


V5_RUNTIME = r'''
/* === V5_STARTUP_SETTLE_MARKERS_BEGIN === */
static gboolean v5_marker_ctpp_ready_seen = FALSE;
static gboolean v5_marker_settle_start_seen = FALSE;
static gboolean v5_marker_signaling_start_seen = FALSE;
static gboolean v5_marker_0028_ack_seen = FALSE;
static gboolean v5_marker_device_0008_seen = FALSE;
static gboolean v5_marker_device_0002_seen = FALSE;
static gboolean v5_marker_rtpc_begin_seen = FALSE;
static gboolean v5_marker_rtpc_control_ready_seen = FALSE;
static gboolean v5_marker_first_video_rtp_seen = FALSE;
static gboolean v5_marker_first_decodable_video_seen = FALSE;
static gboolean v5_h264_sps_seen = FALSE;
static gboolean v5_h264_pps_seen = FALSE;
static gboolean v5_h264_idr_seen = FALSE;

static void
v5_mark_us(const char *name, gboolean *seen)
{
    long long value_us;
    if (*seen)
        return;
    *seen = TRUE;
    value_us = p116_monotonic_ms() * 1000LL;
    printf("%s=%lld\n", name, value_us);
    fflush(stdout);
}

static void
v5_note_h264_recovery_state(void)
{
    if (v5_h264_sps_seen && v5_h264_pps_seen && v5_h264_idr_seen)
        v5_mark_us("V5_FIRST_DECODABLE_VIDEO_US", &v5_marker_first_decodable_video_seen);
}
/* === V5_STARTUP_SETTLE_MARKERS_END === */
'''


def _add_v5_markers(candidate: str, settle_ms: int) -> str:
    candidate = _replace_once(
        candidate,
        "static guint\np116_rtp_payload_offset(const guint8 *packet, guint len)",
        V5_RUNTIME + "\nstatic guint\np116_rtp_payload_offset(const guint8 *packet, guint len)",
        "R66 V5 runtime insertion",
    )
    candidate = _replace_once(
        candidate,
        'printf("R27_STDOUT_LINE_BUFFERED=true\\n");\n    fflush(stdout);',
        'printf("R27_STDOUT_LINE_BUFFERED=true\\n");\n'
        f'    printf("V5_SETTLE_CONFIGURED_MS={settle_ms}\\n");\n'
        '    fflush(stdout);',
        "R66 startup contract print",
    )
    candidate = _replace_once(
        candidate,
        '                printf(\n                    "V4_CTPP_INITIAL_ACK_OBSERVED=true\\n"\n                );',
        '                printf(\n                    "V4_CTPP_INITIAL_ACK_OBSERVED=true\\n"\n                );\n'
        '                v5_mark_us("V5_CTPP_READY_US", &v5_marker_ctpp_ready_seen);',
        "R66 V5 CTPP ready marker",
    )
    candidate = _replace_once(
        candidate,
        '                printf("ENTRANCE_SIGNALING_ARMED=true\\n");',
        '                printf("ENTRANCE_SIGNALING_ARMED=true\\n");\n'
        '                v5_mark_us("V5_SETTLE_START_US", &v5_marker_settle_start_seen);',
        "R66 V5 settle start marker",
    )
    candidate = _replace_once(
        candidate,
        '    printf("ENTRANCE_SIGNALING_SETTLE_COMPLETE=true\\n");',
        '    v5_mark_us("V5_SIGNALING_START_US", &v5_marker_signaling_start_seen);\n'
        '    printf("ENTRANCE_SIGNALING_SETTLE_COMPLETE=true\\n");',
        "R66 V5 signaling start marker",
    )
    candidate = _replace_once(
        candidate,
        '                printf("ENTRANCE_SELF_ACTIVATION_ACK=PASS\\n");',
        '                v5_mark_us("V5_0028_ACK_US", &v5_marker_0028_ack_seen);\n'
        '                printf("ENTRANCE_SELF_ACTIVATION_ACK=PASS\\n");',
        "R66 V5 0028 ack marker",
    )
    candidate = _replace_once(
        candidate,
        '            printf("P78_DEVICE_0008_ACK_SENT=true\\n");',
        '            v5_mark_us("V5_DEVICE_0008_US", &v5_marker_device_0008_seen);\n'
        '            printf("P78_DEVICE_0008_ACK_SENT=true\\n");',
        "R66 V5 device 0008 marker",
    )
    candidate = _replace_once(
        candidate,
        '    printf("P80_DEVICE_0002_OBSERVED=PASS\\n");',
        '    v5_mark_us("V5_DEVICE_0002_US", &v5_marker_device_0002_seen);\n'
        '    printf("P80_DEVICE_0002_OBSERVED=PASS\\n");',
        "R66 V5 device 0002 marker",
    )
    candidate = _replace_once(
        candidate,
        '            printf("P80_DEVICE_0002_GATE=PASS\\n");\n            fflush(stdout);\n            if (!p78_begin_rtpc_control()) {',
        '            printf("P80_DEVICE_0002_GATE=PASS\\n");\n'
        '            v5_mark_us("V5_RTPC_BEGIN_US", &v5_marker_rtpc_begin_seen);\n'
        '            fflush(stdout);\n'
        '            if (!p78_begin_rtpc_control()) {',
        "R66 V5 RTPC begin marker",
    )
    candidate = _replace_once(
        candidate,
        'printf("P78_RTPC_OPEN_2_SENT=PASS\\n");',
        'v5_mark_us("V5_RTPC_CONTROL_READY_US", &v5_marker_rtpc_control_ready_seen);\n'
        '            printf("P78_RTPC_OPEN_2_SENT=PASS\\n");',
        "R66 V5 RTPC control ready marker",
    )
    candidate = _replace_once(
        candidate,
        'printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");',
        'v5_mark_us("V5_FIRST_VIDEO_RTP_US", &v5_marker_first_video_rtp_seen);\n'
        '            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");',
        "R66 V5 first video RTP marker",
    )
    candidate = _replace_once(
        candidate,
        "        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0)\n"
        "            stream->first_keyframe_monotonic_ms = now_ms;\n"
        "        else if (nal_type == 7u)\n"
        "            stream->sps_count++;\n"
        "        else if (nal_type == 8u)\n"
        "            stream->pps_count++;\n"
        "        return;",
        "        if (nal_type == 5u && stream->first_keyframe_monotonic_ms == 0) {\n"
        "            stream->first_keyframe_monotonic_ms = now_ms;\n"
        "            v5_h264_idr_seen = TRUE;\n"
        "        } else if (nal_type == 7u) {\n"
        "            stream->sps_count++;\n"
        "            v5_h264_sps_seen = TRUE;\n"
        "        } else if (nal_type == 8u) {\n"
        "            stream->pps_count++;\n"
        "            v5_h264_pps_seen = TRUE;\n"
        "        }\n"
        "        v5_note_h264_recovery_state();\n"
        "        return;",
        "R66 V5 decodable single-NAL marker",
    )
    candidate = _replace_once(
        candidate,
        "            if (fu_start && original_nal_type == 5u &&\n"
        "                stream->first_keyframe_monotonic_ms == 0) {\n"
        "                stream->first_keyframe_monotonic_ms = now_ms;\n"
        "            }",
        "            if (fu_start && original_nal_type == 5u &&\n"
        "                stream->first_keyframe_monotonic_ms == 0) {\n"
        "                stream->first_keyframe_monotonic_ms = now_ms;\n"
        "                v5_h264_idr_seen = TRUE;\n"
        "                v5_note_h264_recovery_state();\n"
        "            }",
        "R66 V5 decodable FU-A marker",
    )
    return candidate


def transform(source: str, *, include_p116: bool = True, settle_ms: int | None = None) -> str:
    if not include_p116:
        raise ValueError("R66 requires --include-p116; --no-include-p116 is fail-closed")
    value = _validate_settle_ms(settle_ms)
    candidate = r65.transform(source, include_p116=True)
    _validate_r65_anchors(candidate)
    if value == 4000:
        return candidate
    candidate = _replace_once(
        candidate,
        SETTLE_DEFINE,
        f"#define ENTRANCE_SIGNAL_SETTLE_MS {value}",
        "R66 settle define replacement",
    )
    if candidate.count(SETTLE_CALL) != 1:
        raise RuntimeError("R66 settle schedule call was not preserved uniquely")
    return _add_v5_markers(candidate, value)


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R66 STARTUP SETTLE TRANSFORM ===",
            "R66_COMPOSES=R65_PRODUCTION_MEDIA_REFRESH",
            "R66_SETTLE_VALUES_MS=0,500,1000,2000,4000",
            "R66_4000_EQUALS_R65=true",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R66 STARTUP SETTLE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--settle-ms", type=int, default=None)
    parser.add_argument("--report", action="store_true")
    p116 = parser.add_mutually_exclusive_group()
    p116.add_argument("--include-p116", dest="include_p116", action="store_true")
    p116.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    parser.set_defaults(include_p116=True)
    args = parser.parse_args(argv)
    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")
    if not args.include_p116:
        parser.error("R66 requires --include-p116; --no-include-p116 is fail-closed")
    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    candidate = transform(source_path.read_text(encoding="utf-8"), include_p116=True, settle_ms=args.settle_ms)
    args.output.write_text(candidate, encoding="utf-8")
    value = _validate_settle_ms(args.settle_ms)
    print("P116_R66_STARTUP_SETTLE_TRANSFORM=PASS")
    print(f"V5_SETTLE_CONFIGURED_MS={value}")
    print(f"GENERATED_SOURCE_SHA256={hashlib.sha256(candidate.encode('utf-8')).hexdigest()}")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
