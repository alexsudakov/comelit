#!/usr/bin/env python3
"""MSL-V1 startup latency instrumentation overlay for the R65 media helper."""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r65_production_media_refresh_transform as r65
from entrance_p116_r65_production_media_refresh_transform import DEFAULT_SOURCE


MSL_START_REFERENCE = "T03_NATIVE_MEDIA_HELPER_PROCESS_START"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


MSL_RUNTIME = r'''
/* === MSL_V1_LATENCY_INSTRUMENTATION_BEGIN === */
typedef enum {
    MSL_T03_NATIVE_HELPER_PROCESS_START = 0,
    MSL_T04_LOCAL_SDP_OFFER_READY,
    MSL_T08_ICE_CONNECTED,
    MSL_T09_PSEUDOTCP_OPEN,
    MSL_T10_VIP_UAUT_READY,
    MSL_T11_CTPP_REGISTRATION_READY,
    MSL_T12_RTPC_MEDIA_OPEN_CONTROL_READY,
    MSL_T13_INITIAL_001A_SENT,
    MSL_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE,
    MSL_T15_MEDIA_ACTIVE,
    MSL_T16_FIRST_AUDIO_RTP,
    MSL_T17_FIRST_VIDEO_RTP,
    MSL_T18_FIRST_SPS_PPS_IDR,
    MSL_T_COUNT
} MslMarker;

static const char *msl_marker_names[MSL_T_COUNT] = {
    "MSL_T03_NATIVE_HELPER_PROCESS_START_MONO_MS",
    "MSL_T04_LOCAL_SDP_OFFER_READY_MONO_MS",
    "MSL_T08_ICE_CONNECTED_MONO_MS",
    "MSL_T09_PSEUDOTCP_OPEN_MONO_MS",
    "MSL_T10_VIP_UAUT_READY_MONO_MS",
    "MSL_T11_CTPP_REGISTRATION_READY_MONO_MS",
    "MSL_T12_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS",
    "MSL_T13_INITIAL_001A_SENT_MONO_MS",
    "MSL_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE_MONO_MS",
    "MSL_T15_MEDIA_ACTIVE_MONO_MS",
    "MSL_T16_FIRST_AUDIO_RTP_MONO_MS",
    "MSL_T17_FIRST_VIDEO_RTP_MONO_MS",
    "MSL_T18_FIRST_SPS_PPS_IDR_MONO_MS"
};

static gboolean msl_marker_seen[MSL_T_COUNT];
static long long msl_marker_values[MSL_T_COUNT];
static long long msl_clock_base_ms = 0;
static gboolean msl_clock_base_loaded = FALSE;
static gboolean msl_h264_sps_seen = FALSE;
static gboolean msl_h264_pps_seen = FALSE;
static gboolean msl_h264_idr_seen = FALSE;

static gboolean
msl_load_clock_base(void)
{
    const char *path = getenv("MSL_CLOCK_BASE_FILE");
    FILE *f = NULL;
    char buf[64];
    char extra;

    if (!path || !*path) {
        printf("MSL_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        return FALSE;
    }
    f = fopen(path, "r");
    if (!f) {
        printf("MSL_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (!fgets(buf, sizeof(buf), f)) {
        fclose(f);
        printf("MSL_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        return FALSE;
    }
    fclose(f);
    if (sscanf(buf, "%lld %c", &msl_clock_base_ms, &extra) != 1 ||
        msl_clock_base_ms <= 0) {
        printf("MSL_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        return FALSE;
    }
    msl_clock_base_loaded = TRUE;
    printf("MSL_CLOCK_BASE_LOADED=true\n");
    fflush(stdout);
    return TRUE;
}

static long long
msl_elapsed_ms(void)
{
    return p116_monotonic_ms() - msl_clock_base_ms;
}

static void
msl_mark_once(MslMarker marker)
{
    long long value;
    if (!msl_clock_base_loaded || marker < 0 || marker >= MSL_T_COUNT ||
        msl_marker_seen[marker])
        return;
    value = msl_elapsed_ms();
    if (value < 0)
        value = 0;
    msl_marker_seen[marker] = TRUE;
    msl_marker_values[marker] = value;
    printf("%s=%lld\n", msl_marker_names[marker], value);
    fflush(stdout);
}

static void
msl_print_delta(const char *name, MslMarker start, MslMarker end)
{
    if (msl_marker_seen[start] && msl_marker_seen[end]) {
        printf("%s=%lld\n", name, msl_marker_values[end] - msl_marker_values[start]);
    } else {
        printf("%s=N/A\n", name);
    }
}

static void
msl_print_summary(void)
{
    printf("MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START\n");
    msl_print_delta("MSL_START_TO_FIRST_RTP_MS", MSL_T03_NATIVE_HELPER_PROCESS_START, MSL_T17_FIRST_VIDEO_RTP);
    msl_print_delta("MSL_START_TO_DECODABLE_VIDEO_MS", MSL_T03_NATIVE_HELPER_PROCESS_START, MSL_T18_FIRST_SPS_PPS_IDR);
    msl_print_delta("MSL_DELTA_T04_T07_MS", MSL_T04_LOCAL_SDP_OFFER_READY, MSL_T08_ICE_CONNECTED);
    printf("MSL_DELTA_T04_T07_MS_NOTE=T07_WRAPPER_REMOTE_SDP_WRITTEN_TO_T08_HELPER_ICE_CONNECTED_IS_REPORTED_BY_RUNNER\n");
    msl_print_delta("MSL_DELTA_T07_T08_MS", MSL_T08_ICE_CONNECTED, MSL_T08_ICE_CONNECTED);
    printf("MSL_DELTA_T07_T08_MS_NOTE=RUNNER_RECOMPUTES_FROM_WRAPPER_T07_AND_HELPER_T08\n");
    msl_print_delta("MSL_DELTA_T08_T09_MS", MSL_T08_ICE_CONNECTED, MSL_T09_PSEUDOTCP_OPEN);
    msl_print_delta("MSL_DELTA_T09_T11_MS", MSL_T09_PSEUDOTCP_OPEN, MSL_T11_CTPP_REGISTRATION_READY);
    msl_print_delta("MSL_DELTA_T11_T15_MS", MSL_T11_CTPP_REGISTRATION_READY, MSL_T15_MEDIA_ACTIVE);
    msl_print_delta("MSL_DELTA_T15_T17_MS", MSL_T15_MEDIA_ACTIVE, MSL_T17_FIRST_VIDEO_RTP);
    fflush(stdout);
}

static void
msl_note_h264_recovery_state(void)
{
    if (msl_h264_sps_seen && msl_h264_pps_seen && msl_h264_idr_seen)
        msl_mark_once(MSL_T18_FIRST_SPS_PPS_IDR);
}
/* === MSL_V1_LATENCY_INSTRUMENTATION_END === */
'''


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("MSL-V1 requires --include-p116; --no-include-p116 is fail-closed")
    candidate = r65.transform(source, include_p116=True)
    candidate = _replace_once(
        candidate,
        "static guint\np116_rtp_payload_offset(const guint8 *packet, guint len)",
        MSL_RUNTIME + "\nstatic guint\np116_rtp_payload_offset(const guint8 *packet, guint len)",
        "MSL runtime insertion",
    )
    replacements = (
        ('printf("PSEUDOTCP_OPEN=PASS\\n");', 'msl_mark_once(MSL_T09_PSEUDOTCP_OPEN);\n    printf("PSEUDOTCP_OPEN=PASS\\n");', "T09"),
        ('printf("ICE_CONNECTED=PASS\\n");\n        printf("ICE_READY=PASS\\n");', 'msl_mark_once(MSL_T08_ICE_CONNECTED);\n        printf("ICE_CONNECTED=PASS\\n");\n        printf("ICE_READY=PASS\\n");', "T08"),
        ('printf("ICE_GATHER=PASS\\n");', 'msl_mark_once(MSL_T04_LOCAL_SDP_OFFER_READY);\n    printf("ICE_GATHER=PASS\\n");', "T04"),
        ('    printf(\n        "VIP_UAUT_OPEN_RESPONSE=PASS\\n"\n    );', '    msl_mark_once(MSL_T10_VIP_UAUT_READY);\n    printf(\n        "VIP_UAUT_OPEN_RESPONSE=PASS\\n"\n    );', "T10"),
        ('                printf(\n                    "V4_CTPP_INITIAL_ACK_OBSERVED=true\\n"\n                );', '                printf(\n                    "V4_CTPP_INITIAL_ACK_OBSERVED=true\\n"\n                );\n                msl_mark_once(MSL_T11_CTPP_REGISTRATION_READY);', "T11"),
        ('printf("P78_RTPC_OPEN_2_SENT=PASS\\n");', 'msl_mark_once(MSL_T12_RTPC_MEDIA_OPEN_CONTROL_READY);\n            printf("P78_RTPC_OPEN_2_SENT=PASS\\n");', "T12"),
        ('printf("P78_RTPC_CLIENT_001A_SENT=PASS\\n");', 'msl_mark_once(MSL_T13_INITIAL_001A_SENT);\n            printf("P78_RTPC_CLIENT_001A_SENT=PASS\\n");', "T13"),
        ('printf("P80_DEVICE_ACK_001A_OBSERVED=PASS\\n");', 'msl_mark_once(MSL_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE);\n        printf("P80_DEVICE_ACK_001A_OBSERVED=PASS\\n");', "T14"),
        ('printf("P80_MEDIA_ACTIVE=true\\n");', 'msl_mark_once(MSL_T15_MEDIA_ACTIVE);\n    printf("P80_MEDIA_ACTIVE=true\\n");', "T15"),
        ('printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");', 'msl_mark_once(MSL_T17_FIRST_VIDEO_RTP);\n            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");', "T17"),
        ('printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");', 'msl_mark_once(MSL_T16_FIRST_AUDIO_RTP);\n            printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");', "T16"),
    )
    for old, new, label in replacements:
        candidate = _replace_once(candidate, old, new, f"MSL {label} marker")

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
        "            msl_h264_idr_seen = TRUE;\n"
        "        } else if (nal_type == 7u) {\n"
        "            stream->sps_count++;\n"
        "            msl_h264_sps_seen = TRUE;\n"
        "        } else if (nal_type == 8u) {\n"
        "            stream->pps_count++;\n"
        "            msl_h264_pps_seen = TRUE;\n"
        "        }\n"
        "        msl_note_h264_recovery_state();\n"
        "        return;",
        "MSL T18 single NAL marker",
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
        "                msl_h264_idr_seen = TRUE;\n"
        "                msl_note_h264_recovery_state();\n"
        "            }",
        "MSL T18 FU-A marker",
    )
    candidate = _replace_once(
        candidate,
        'printf("R27_STDOUT_LINE_BUFFERED=true\\n");\n    fflush(stdout);',
        'printf("R27_STDOUT_LINE_BUFFERED=true\\n");\n    fflush(stdout);\n\n'
        '    if (!msl_load_clock_base())\n        return 2;\n'
        '    msl_mark_once(MSL_T03_NATIVE_HELPER_PROCESS_START);',
        "MSL main clock gate",
    )
    candidate = _replace_once(
        candidate,
        "p116_print_final_rtp_summary();",
        "p116_print_final_rtp_summary();\n    msl_print_summary();",
        "MSL final summary",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT MSL V1 LATENCY INSTRUMENTATION TRANSFORM ===",
            "MSL_COMPOSES=R65_PRODUCTION_MEDIA_REFRESH",
            f"MSL_START_REFERENCE={MSL_START_REFERENCE}",
            "MSL_CLOCK_BASE_REQUIRED=true",
            "MSL_T06_CLOUD_P2P_REQUEST_START_EMITTED_BY=RUNNER_WRAPPER",
            "MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_EMITTED_BY=RUNNER_WRAPPER",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "DOOR_ACTION_SENT=false",
            "GATE_ACTION_SENT=false",
            "=== END COMELIT MSL V1 LATENCY INSTRUMENTATION TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
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
        parser.error("MSL-V1 requires --include-p116; --no-include-p116 is fail-closed")
    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    args.output.write_text(transform(source_path.read_text(encoding="utf-8"), include_p116=True), encoding="utf-8")
    print("MSL_V1_LATENCY_INSTRUMENTATION_TRANSFORM=PASS")
    print("MSL_COMPOSES=R65_PRODUCTION_MEDIA_REFRESH")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
