#!/usr/bin/env python3
"""Research-only pausable P2P bootstrap interlock overlay.

This transform composes the current production media source generator and adds
an opt-in research stop gate controlled only by environment variables:

    RESEARCH_STOP_AFTER_STAGE=6|7|8|9|10|11|12
    RESEARCH_HOLD_MS=3000..5000

Default is disabled.  With the variable unset the generated text is byte-for-
byte identical to the production generator output for the same inputs.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r65_production_media_refresh_transform as production
from entrance_p116_r65_production_media_refresh_transform import DEFAULT_SOURCE


VALID_STAGES = frozenset({6, 7, 8, 9, 10, 11, 12})
DEFAULT_HOLD_MS = 4000
MIN_HOLD_MS = 100
MAX_HOLD_MS = 5000


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


_HELPERS = r'''
/* === RESEARCH_STAGE_INTERLOCK_BEGIN === */
#define RESEARCH_STAGE_INTERLOCK_DEFAULT_HOLD_MS 4000u
#define RESEARCH_STAGE_INTERLOCK_MAX_HOLD_MS 5000u

static int research_stop_after_stage = 0;
static guint research_hold_ms = RESEARCH_STAGE_INTERLOCK_DEFAULT_HOLD_MS;
static gboolean research_hold_active = FALSE;
static gboolean research_teardown_started = FALSE;
static gboolean research_stop_file_seen = FALSE;
static gboolean research_stage_11_not_separable = TRUE;
static gboolean research_self_activation_sent = FALSE;
static gboolean research_rtpc_opened = FALSE;
static gboolean research_rtp_started = FALSE;

static gboolean research_parse_uint_env(const char *name, guint *out)
{
    const char *value = getenv(name);
    char *end = NULL;
    unsigned long parsed;

    if (!value || !*value)
        return FALSE;

    errno = 0;
    parsed = strtoul(value, &end, 10);
    if (errno != 0 || !end || *end != '\0' || parsed > 600000ul)
        return FALSE;

    *out = (guint)parsed;
    return TRUE;
}

static gboolean research_interlock_enabled(void)
{
    return research_stop_after_stage >= 6 && research_stop_after_stage <= 12;
}

static gboolean research_stop_file_present(void)
{
    return g_file_test(STOP_FILE, G_FILE_TEST_EXISTS);
}

static void research_print_negative_markers(void)
{
    printf("SELF_ACTIVATION_SENT=false\n");
    printf("RTPC_OPENED=false\n");
    printf("RTP_STARTED=false\n");
}

static void research_teardown_begin(const char *reason)
{
    if (research_teardown_started)
        return;

    research_teardown_started = TRUE;
    printf("RESEARCH_TEARDOWN_BEGIN=true\n");
    printf("RESEARCH_TEARDOWN_REASON=%s\n", reason);
    research_print_negative_markers();
    fflush(stdout);

    if (pseudo_tcp && pseudotcp_open && !pseudotcp_graceful_stop_started) {
        pseudotcp_graceful_stop_started = TRUE;
        pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    }
}

static gboolean research_hold_timeout_cb(gpointer data)
{
    (void)data;
    if (!research_hold_active)
        return G_SOURCE_REMOVE;

    research_teardown_begin("timeout");
    printf("RESEARCH_TEARDOWN_DONE=true\n");
    fflush(stdout);
    failed = FALSE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}

static gboolean research_hold_stop_check_cb(gpointer data)
{
    (void)data;
    if (!research_hold_active)
        return G_SOURCE_REMOVE;

    if (research_stop_file_present()) {
        research_stop_file_seen = TRUE;
        research_teardown_begin("stop_file");
        printf("RESEARCH_STOP_FILE_OBSERVED=true\n");
        printf("RESEARCH_TEARDOWN_DONE=true\n");
        fflush(stdout);
        failed = FALSE;
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}

static gboolean research_enter_hold(int stage, const char *marker)
{
    if (research_stop_after_stage != stage)
        return FALSE;

    printf("%s\n", marker);
    printf("RESEARCH_HOLD_ENTERED=true\n");
    printf("RESEARCH_STOP_AFTER_STAGE=%d\n", stage);
    printf("RESEARCH_HOLD_MS=%u\n", research_hold_ms);
    printf("STAGE_11_NOT_SEPARABLE=%s\n", research_stage_11_not_separable ? "true" : "false");
    research_print_negative_markers();
    fflush(stdout);

    research_hold_active = TRUE;
    if (g_timeout_add(research_hold_ms, research_hold_timeout_cb, NULL) == 0 ||
        g_timeout_add(50, research_hold_stop_check_cb, NULL) == 0) {
        fprintf(stderr, "RESEARCH_HOLD_TIMER_START=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }
    return TRUE;
}

static gboolean research_forbidden_stage_crossing(const char *label)
{
    if (!research_interlock_enabled())
        return FALSE;

    fprintf(stderr, "FORBIDDEN_STAGE_CROSSING=%s\n", label);
    research_print_negative_markers();
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return TRUE;
}

static gboolean research_init_from_env(void)
{
    guint parsed = 0;
    const char *stop = getenv("RESEARCH_STOP_AFTER_STAGE");

    if (!stop || !*stop) {
        research_stop_after_stage = 0;
        return TRUE;
    }

    if (!research_parse_uint_env("RESEARCH_STOP_AFTER_STAGE", &parsed) ||
        !((parsed >= 6 && parsed <= 10) || parsed == 12)) {
        fprintf(stderr, "RESEARCH_STOP_AFTER_STAGE=INVALID\n");
        return FALSE;
    }

    research_stop_after_stage = (int)parsed;

    if (research_parse_uint_env("RESEARCH_HOLD_MS", &parsed)) {
        if (parsed < 100u || parsed > RESEARCH_STAGE_INTERLOCK_MAX_HOLD_MS) {
            fprintf(stderr, "RESEARCH_HOLD_MS=INVALID\n");
            return FALSE;
        }
        research_hold_ms = parsed;
    }

    printf("RESEARCH_STAGE_INTERLOCK=ENABLED\n");
    printf("RESEARCH_STOP_AFTER_STAGE=%d\n", research_stop_after_stage);
    printf("STAGE_11_NOT_SEPARABLE=true\n");
    fflush(stdout);
    return TRUE;
}
/* === RESEARCH_STAGE_INTERLOCK_END === */
'''


def _inject_interlock(candidate: str) -> str:
    candidate = _replace_once(
        candidate,
        "static goffset remote_last_size = -1;\n",
        _HELPERS + "\nstatic goffset remote_last_size = -1;\n",
        "research helpers",
    )

    candidate = _replace_once(
        candidate,
        "    ready = TRUE;\n\n    g_free(sdp);\n",
        (
            '    if (research_enter_hold(6, "RESEARCH_STAGE_6_LOCAL_OFFER_READY"))\n'
            "        return;\n\n"
            "    ready = TRUE;\n\n    g_free(sdp);\n"
        ),
        "stage 6 hold",
    )

    candidate = _replace_once(
        candidate,
        '    printf(\n        "REMOTE_PRIMITIVES_IMPORT=PASS\\n"\n    );\n\n    fflush(stdout);\n',
        (
            '    if (research_enter_hold(8, "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED"))\n'
            "        return G_SOURCE_REMOVE;\n\n"
            '    printf(\n        "REMOTE_PRIMITIVES_IMPORT=PASS\\n"\n    );\n\n'
            "    fflush(stdout);\n"
        ),
        "stage 8 hold",
    )

    candidate = _replace_once(
        candidate,
        '        if (!report_selected_pair()) {\n',
        (
            '        if (research_enter_hold(9, "RESEARCH_STAGE_9_ICE_CONNECTED"))\n'
            "            return;\n\n"
            "        if (!report_selected_pair()) {\n"
        ),
        "stage 9 hold",
    )

    candidate = _replace_once(
        candidate,
        '    printf("PSEUDOTCP_OPEN=PASS\\n");\n    fflush(stdout);\n',
        (
            '    if (research_enter_hold(10, "RESEARCH_STAGE_10_PSEUDOTCP_OPEN"))\n'
            "        return;\n\n"
            '    printf("PSEUDOTCP_OPEN=PASS\\n");\n    fflush(stdout);\n'
        ),
        "stage 10 hold",
    )

    candidate = _replace_once(
        candidate,
        '                printf(\n                    "V4_CTPP_REGISTRATION=PASS\\n"\n                );\n',
        (
            '                printf("RESEARCH_STAGE_11_CTPP_PRE_REGISTER\\n");\n'
            '                if (research_enter_hold(12, "RESEARCH_STAGE_12_CTPP_REGISTERED"))\n'
            "                    break;\n\n"
            '                printf(\n                    "V4_CTPP_REGISTRATION=PASS\\n"\n                );\n'
        ),
        "stage 12 hold",
    )

    candidate = _replace_once(
        candidate,
        "    if (g_mkdir_with_parents(\n",
        (
            "    if (!research_init_from_env())\n"
            "        return 64;\n\n"
            "    if (g_mkdir_with_parents(\n"
        ),
        "main init",
    )

    candidate = _replace_once(
        candidate,
        '                printf("ENTRANCE_SIGNALING_ARMED=true\\n");\n',
        (
            '                if (research_forbidden_stage_crossing("ENTRANCE_SIGNALING_ARMED"))\n'
            "                    break;\n\n"
            '                printf("ENTRANCE_SIGNALING_ARMED=true\\n");\n'
        ),
        "signaling guard",
    )

    candidate = _replace_once(
        candidate,
        '            printf("ENTRANCE_SELF_ACTIVATION_SENT=PASS\\n");\n',
        (
            '            research_self_activation_sent = TRUE;\n'
            '            if (research_forbidden_stage_crossing("ENTRANCE_SELF_ACTIVATION_SENT"))\n'
            "                break;\n\n"
            '            printf("ENTRANCE_SELF_ACTIVATION_SENT=PASS\\n");\n'
        ),
        "self activation guard",
    )

    for marker, label in (
        ('printf("P78_RTPC_OPEN_REQUESTED=true\\n");', "RTPC_OPENED"),
        ('printf("P80_RTP_FORWARD=PASS\\n");', "RTP_STARTED"),
    ):
        if marker in candidate:
            candidate = candidate.replace(
                marker,
                f'research_{label.lower()} = TRUE;\n'
                f'    if (research_forbidden_stage_crossing("{label}"))\n'
                "        return FALSE;\n\n"
                f"    {marker}",
                1,
            )

    return candidate


def transform(source: str, *, research: bool = False) -> str:
    candidate = production.transform(source, include_p116=True)
    if not research:
        return candidate
    return _inject_interlock(candidate)


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT RESEARCH STAGE INTERLOCK TRANSFORM ===",
            "RESEARCH_ONLY=true",
            "RESEARCH_STOP_AFTER_STAGE_ENV=RESEARCH_STOP_AFTER_STAGE",
            "RESEARCH_HOLD_MS_ENV=RESEARCH_HOLD_MS",
            "DEFAULT_RESEARCH_INTERLOCK=disabled",
            "DEFAULT_RESEARCH_HOLD_MS=4000",
            "STAGE_11_NOT_SEPARABLE=true",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT RESEARCH STAGE INTERLOCK TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    generated = transform(source_path.read_text(encoding="utf-8"), research=args.research)
    if args.sha256:
        print(hashlib.sha256(generated.encode("utf-8")).hexdigest())
    if args.output is not None:
        args.output.write_text(generated, encoding="utf-8")
        print("RESEARCH_STAGE_INTERLOCK_TRANSFORM=PASS")
        print(f"RESEARCH_ENABLED={'true' if args.research else 'false'}")
        print("NETWORK_IO_PERFORMED=false")
        print("CANDIDATE_EXECUTED=false")
    if not args.sha256 and args.output is None:
        parser.error("--output, --sha256, or --report is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
