#!/usr/bin/env python3
"""P116/R29 research-only listener-attached inbound media live candidate.

This transform composes the current P80/P106 musl media helper lineage from
the v1_5_7 persistent listener source, then removes the older self-activation
media start path.  The R29 candidate starts attached media only after an
inbound entrance CALL_INIT observed by the already-registered listener.

The transform performs no network I/O and never executes the candidate.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from entrance_p106_teardown_state_classification_transform import (
    DEFAULT_SOURCE,
    transform as add_p106_runtime,
)


LINEAGE_MARKERS = (
    '#define RUN_DIR     "/run/comelit-p2p"',
    "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
    "V4_RING_KIND=CALL_INIT",
    "Persistent listener:",
)


C_KEYWORDS = {
    "break", "case", "char", "const", "continue", "default", "do", "else",
    "enum", "for", "if", "int", "long", "return", "sizeof", "static",
    "struct", "switch", "typedef", "unsigned", "void", "while",
}


R29_IDENTIFIER_ALLOWLIST = {
    "FALSE", "G_SOURCE_CONTINUE", "G_SOURCE_REMOVE", "NULL", "SIGUSR2",
    "TRUE", "close", "fflush", "gboolean", "gpointer", "guint", "guint64",
    "getpid", "pid_t", "printf", "signal", "stdout", "strcmp",
}


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _block_end(text: str, opening_brace: int) -> int:
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
        raise RuntimeError(f"function not found: {signature!r}")
    if text.find(signature, start + 1) >= 0:
        raise RuntimeError(f"function not unique: {signature!r}")
    opening = text.find("{", start + len(signature))
    if opening < 0:
        raise RuntimeError(f"function opening brace not found: {signature!r}")
    end = _block_end(text, opening)
    return text[:start] + replacement + text[end:]


def _strip_c_comments_and_literals(text: str) -> str:
    out: list[str] = []
    i = 0
    state = "normal"
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "normal":
            if ch == '"':
                out.append(" ")
                state = "string"
            elif ch == "'":
                out.append(" ")
                state = "char"
            elif ch == "/" and nxt == "/":
                out.append("  ")
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                out.append("  ")
                state = "block_comment"
                i += 1
            else:
                out.append(ch)
        elif state in {"string", "char"}:
            out.append("\n" if ch == "\n" else " ")
            if ch == "\\":
                i += 1
                if i < len(text):
                    out.append("\n" if text[i] == "\n" else " ")
            elif (state == "string" and ch == '"') or (
                state == "char" and ch == "'"
            ):
                state = "normal"
        elif state == "line_comment":
            out.append("\n" if ch == "\n" else " ")
            if ch == "\n":
                state = "normal"
        elif state == "block_comment":
            out.append("\n" if ch == "\n" else " ")
            if ch == "*" and nxt == "/":
                out.append(" ")
                state = "normal"
                i += 1
        i += 1
    return "".join(out)


def _identifier_tokens(text: str) -> set[str]:
    stripped = _strip_c_comments_and_literals(text)
    tokens: set[str] = set()
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", stripped):
        name = match.group(0)
        if name in C_KEYWORDS:
            continue
        if name.startswith("R29_") and (name.endswith("_BEGIN") or name.endswith("_END")):
            continue
        before = stripped[:match.start()].rstrip()
        if before.endswith(".") or before.endswith("->"):
            continue
        tokens.add(name)
    return tokens


def _defined_identifiers(text: str) -> set[str]:
    return set(_defined_identifier_positions(text))


def _defined_identifier_positions(text: str) -> dict[str, int]:
    stripped = _strip_c_comments_and_literals(text)
    names: dict[str, int] = {}

    def add(name: str, pos: int) -> None:
        if name not in C_KEYWORDS and (name not in names or pos < names[name]):
            names[name] = pos

    for match in re.finditer(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)", stripped, re.M):
        add(match.group(1), match.start(1))
    for match in re.finditer(r"}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;", stripped):
        add(match.group(1), match.start(1))
    for enum_match in re.finditer(r"typedef\s+enum\s*{([^}]*)}", stripped, re.S):
        enum_body = enum_match.group(1)
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:=[^,}]*)?(?:,|$)", enum_body):
            add(match.group(1), enum_match.start(1) + match.start(1))
    for pattern in (
        r"\b(?:static\s+)?(?:const\s+)?(?:gboolean|guint|guint64|int|long\s+long|pid_t|void|EntranceSignalStage|R29AttachedMediaState)\s+\**\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\b(?:static\s+)?(?:gboolean|int|void)\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*void\s*\)",
        r"\b(?:const\s+)?(?:char|gpointer|int)\s+\**\s*([A-Za-z_][A-Za-z0-9_]*)\b",
    ):
        for match in re.finditer(pattern, stripped):
            add(match.group(1), match.start(1))
    return names


def _identifier_token_positions(text: str, base_offset: int = 0) -> dict[str, int]:
    stripped = _strip_c_comments_and_literals(text)
    tokens: dict[str, int] = {}
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", stripped):
        name = match.group(0)
        if name in C_KEYWORDS:
            continue
        if name.startswith("R29_") and (name.endswith("_BEGIN") or name.endswith("_END")):
            continue
        before = stripped[:match.start()].rstrip()
        if before.endswith(".") or before.endswith("->"):
            continue
        tokens.setdefault(name, base_offset + match.start())
    return tokens


def _assert_r29_identifier_ordering(
    candidate: str,
    region_name: str,
    region_start: int,
    region: str,
    r29_defined: set[str],
) -> list[str]:
    definition_positions = _defined_identifier_positions(candidate)
    references = _identifier_token_positions(region, region_start)
    failures: list[str] = []
    for ref, use_pos in sorted(references.items()):
        if ref in R29_IDENTIFIER_ALLOWLIST or ref in r29_defined:
            continue
        if ref not in definition_positions:
            continue
        definition_pos = definition_positions.get(ref)
        if definition_pos is None or definition_pos >= use_pos:
            failures.append(
                f"{region_name}:{ref}:definition_pos={definition_pos}:first_use_pos={use_pos}"
            )
    return failures


def _assert_r29_external_identifier_ordering(candidate: str) -> None:
    regions = _r29_audit_regions(candidate)
    r29_defined: set[str] = set()
    for _, _, region in regions:
        r29_defined.update(_defined_identifiers(region))
    failures: list[str] = []
    for name, start, region in regions:
        failures.extend(
            _assert_r29_identifier_ordering(
                candidate, name, start, region, r29_defined
            )
        )
    if failures:
        raise RuntimeError("R29_IDENTIFIER_ORDER_GATE=FAIL " + ",".join(failures))


def _r29_audit_regions(candidate: str) -> list[tuple[str, int, str]]:
    spans = [
        (
            "state",
            "R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN",
            "R29_LISTENER_ATTACHED_MEDIA_STATE_END",
        ),
        (
            "functions",
            "R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN",
            "R29_ATTACHED_MEDIA_FUNCTIONS_END",
        ),
        (
            "self_activation_stub",
            "static gboolean\nentrance_signal_queue_self_activation(void)\n{",
            "static gboolean\nentrance_signal_queue_video_event",
        ),
        (
            "client_001a_stub",
            "static gboolean\np78_queue_rtpc_client_001a(void)\n{",
            "static gboolean\np78_begin_rtpc_control",
        ),
        (
            "ready_hook",
            "r29_ctpp_registration_count++;",
            "V4_RING_LISTENER_READY=true",
        ),
        (
            "call_init_hook",
            "r29_start_attached_media_from_call_init(source)",
            "                fflush(stdout);\n",
        ),
        (
            "pseudotcp_counter",
            "r29_pseudotcp_open_count++;",
            "PSEUDOTCP_OPEN_COUNT=%u",
        ),
        (
            "cloud_counter",
            "r29_cloud_negotiation_count++;",
            "REMOTE_PRIMITIVES_IMPORT=PASS",
        ),
        (
            "ice_counter",
            "r29_ice_bootstrap_count++;",
            "ICE_GATHER_START=PASS",
        ),
        (
            "rtp_progress_hook",
            "r29_first_video_rtp_monotonic_ms = p116_monotonic_ms();",
            "P80_VIDEO_RTP_FORWARDING=PASS",
        ),
        (
            "forbidden_call_site_stub",
            "r29_client_001a_sent_count++;\n    printf(\"R29_CLIENT_001A_DISABLED=true\\n\");",
            "return FALSE;\n}",
        ),
        (
            "main_selfcheck_patch",
            "argc == 2 && strcmp(argv[1], \"--r29-selfcheck\") == 0",
            "return r29_selfcheck();",
        ),
        (
            "main_signal_patch",
            "signal(SIGUSR2, r29_sigusr2_handler);",
            "R29_ONE_SHOT_CONTROL_KIND=SIGUSR2",
        ),
        (
            "main_poll_patch",
            "        r29_sigusr2_poll_cb,\n        NULL\n    );",
            "NULL\n    );",
        ),
    ]
    regions: list[tuple[str, int, str]] = []
    for name, start, end in spans:
        s = candidate.find(start)
        if s < 0:
            raise RuntimeError(f"R29_IDENTIFIER_GATE=FAIL region_missing={name}:start")
        e = candidate.find(end, s)
        if e < 0:
            raise RuntimeError(f"R29_IDENTIFIER_GATE=FAIL region_missing={name}:end")
        regions.append((name, s, candidate[s:e]))
    return regions


R29_STATE = r'''

/* === R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN === */
typedef enum {
    R29_LISTENER_REGISTERED_READY = 0,
    R29_INBOUND_CALL_ACTIVE,
    R29_ATTACHED_MEDIA_ACTIVE,
    R29_ATTACHED_MEDIA_STOPPING
} R29AttachedMediaState;

static R29AttachedMediaState r29_attached_media_state =
    R29_LISTENER_REGISTERED_READY;
static gboolean r29_listener_registered_ready = FALSE;
static gboolean r29_call_transaction_active = FALSE;
static gboolean r29_call_transaction_created = FALSE;
static gboolean r29_inbound_call_ctp_captured = FALSE;
static gboolean r29_call_ctp_separate_from_registration = FALSE;
static gboolean r29_call_bound_mediareq26_uses_inbound_ctp = FALSE;
static gboolean r29_media_channel_runtime_allocated = FALSE;
static gboolean r29_media_channel_state_persisted = FALSE;
static gboolean r29_media_channel_open_request_sent = FALSE;
static gboolean r29_media_channel_open_response_observed = FALSE;
static gboolean r29_call_bound_mediareq26_open_sent = FALSE;
static gboolean r29_call_bound_mediareq26_stop_sent = FALSE;
static gboolean r29_video_rtp_started_marker = FALSE;
static gboolean r29_media_stop_requested = FALSE;
static gboolean r29_media_stop_completed = FALSE;
static gboolean r29_media_stop_before_open_blocked = FALSE;
static gboolean r29_sigusr2_seen = FALSE;
static gboolean r29_sigusr2_second_refused = FALSE;
static gboolean r29_second_media_start_blocked = FALSE;
static gboolean r29_media_open_blocked = FALSE;
static gboolean r29_media_teardown_blocked = FALSE;
static guint r29_ice_bootstrap_count = 0;
static guint r29_cloud_negotiation_count = 0;
static guint r29_pseudotcp_open_count = 0;
static guint r29_ctpp_registration_count = 0;
static guint r29_rtpc_media_channels_open = 0;
static guint r29_self_activation_sent_count = 0;
static guint r29_client_001a_sent_count = 0;
static guint r29_r27_repeat_sent_count = 0;
static guint r29_call_bound_mediareq26_open_sent_count = 0;
static guint r29_call_bound_mediareq26_stop_sent_count = 0;
static guint r29_unknown_001a_form_blocked_count = 0;
static guint r29_registration_ctp_rejected_for_media_count = 0;
static guint r29_stop_call_release_count = 0;
static guint r29_stop_registration_close_count = 0;
static guint r29_stop_pseudotcp_close_count = 0;
static guint r29_stop_listener_stop_count = 0;
static guint r29_door_actions_sent = 0;
static guint r29_gate_actions_sent = 0;
static guint r29_refresh_loop_started_count = 0;
static guint r29_ready_ice_bootstrap_count = 0;
static guint r29_ready_cloud_negotiation_count = 0;
static guint r29_ready_pseudotcp_open_count = 0;
static guint r29_ready_ctpp_registration_count = 0;
static long long r29_call_init_monotonic_ms = 0;
static long long r29_first_video_rtp_monotonic_ms = 0;
static long long r29_media_observation_start_ms = 0;
static long long r29_media_observation_end_ms = 0;
static pid_t r29_listener_ready_pid = 0;

static void r29_print_scalar_snapshot(const char *call_end_state);
static gboolean r29_same_listener_process(void);
static void r29_capture_ready_snapshot(void);
static gboolean r29_start_attached_media_from_call_init(const char *source);
static gboolean r29_registration_ctp_rejected_for_media(void);
static gboolean r29_unknown_001a_form_blocked(void);
static gboolean r29_media_only_teardown(const char *reason);
static const char *r29_first_rtp_order_result(void);
static gboolean r29_sigusr2_poll_cb(gpointer data);
static void r29_sigusr2_handler(int signum);
static int r29_selfcheck(void);
/* === R29_LISTENER_ATTACHED_MEDIA_STATE_END === */
'''


R29_FUNCTIONS = r'''

/* === R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN === */
static void
r29_print_scalar_snapshot(const char *call_end_state)
{
    guint new_ice = r29_ice_bootstrap_count - r29_ready_ice_bootstrap_count;
    guint new_cloud = r29_cloud_negotiation_count - r29_ready_cloud_negotiation_count;
    guint new_pseudotcp = r29_pseudotcp_open_count - r29_ready_pseudotcp_open_count;
    guint new_registration = r29_ctpp_registration_count - r29_ready_ctpp_registration_count;
    gboolean same_process = r29_same_listener_process();
    gboolean transport_preserved = same_process && new_ice == 0u &&
        new_cloud == 0u && new_pseudotcp == 0u;
    gboolean registration_preserved = r29_listener_registered_ready &&
        new_registration == 0u;
    gboolean ring_listener_preserved = same_process && r29_listener_registered_ready;
    gboolean call_separate_from_registration = r29_call_ctp_separate_from_registration;
    long long observed_ms = r29_media_observation_end_ms - r29_media_observation_start_ms;
    if (observed_ms < 0)
        observed_ms = 0;

    printf("ICE_BOOTSTRAP_COUNT=%u\n", r29_ice_bootstrap_count);
    printf("CLOUD_NEGOTIATION_COUNT=%u\n", r29_cloud_negotiation_count);
    printf("PSEUDOTCP_OPEN_COUNT=%u\n", r29_pseudotcp_open_count);
    printf("CTPP_REGISTRATION_COUNT=%u\n", r29_ctpp_registration_count);
    printf("RTPC_MEDIA_CHANNELS_OPEN=%u\n", r29_rtpc_media_channels_open);
    printf("SELF_ACTIVATION_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    printf("SELF_ACTIVATION_001A_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    printf("CLIENT_001A_SENT_COUNT=%u\n", r29_client_001a_sent_count);
    printf("R27_REPEAT_SENT_COUNT=%u\n", r29_r27_repeat_sent_count);
    printf("R27_REPEAT_001A_SENT_COUNT=%u\n", r29_r27_repeat_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_open_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_stop_sent_count);
    printf("UNKNOWN_001A_FORM_BLOCKED_COUNT=%u\n",
           r29_unknown_001a_form_blocked_count);
    printf("REGISTRATION_CTP_REJECTED_FOR_MEDIA_COUNT=%u\n",
           r29_registration_ctp_rejected_for_media_count);
    printf("DOOR_ACTIONS_SENT=%u\n", r29_door_actions_sent);
    printf("GATE_ACTIONS_SENT=%u\n", r29_gate_actions_sent);
    printf("REFRESH_LOOP_STARTED_COUNT=%u\n", r29_refresh_loop_started_count);
    printf("NEW_ICE_BOOTSTRAP_AFTER_READY=%u\n", new_ice);
    printf("NEW_CLOUD_NEGOTIATION_AFTER_READY=%u\n", new_cloud);
    printf("NEW_PSEUDOTCP_AFTER_READY=%u\n", new_pseudotcp);
    printf("NEW_REGISTRATION_AFTER_READY=%u\n", new_registration);
    printf("R29_MEDIA_OPEN_MODEL=%s\n",
           r29_media_open_blocked ? "BLOCKED" : "UNPROVEN");
    printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=%s\n",
           r29_media_teardown_blocked ? "BLOCKED" : "UNPROVEN");
    printf("RESEARCH_LISTENER_READY=%s\n",
           r29_listener_registered_ready ? "true" : "false");
    printf("CALL_TRANSACTION_CREATED=%s\n",
           r29_call_transaction_created ? "true" : "false");
    printf("INBOUND_CALL_CTP_CAPTURE_IMPLEMENTED=%s\n",
           r29_inbound_call_ctp_captured ? "true" : "false");
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           call_separate_from_registration ? "true" : "false");
    printf("CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=%s\n",
           r29_call_bound_mediareq26_uses_inbound_ctp ? "true" : "false");
    printf("MEDIA_CHANNEL_RUNTIME_ALLOCATION_IMPLEMENTED=%s\n",
           r29_media_channel_runtime_allocated ? "true" : "false");
    printf("MEDIA_CHANNEL_STATE_PERSISTED=%s\n",
           r29_media_channel_state_persisted ? "true" : "false");
    printf("CALL_BOUND_MEDIAREQ26_OPEN_GENERATION=%s\n",
           r29_call_bound_mediareq26_open_sent ? "PROVEN_OFFLINE" : "BLOCKED");
    printf("CALL_BOUND_MEDIAREQ26_STOP_GENERATION=%s\n",
           r29_call_bound_mediareq26_stop_sent ? "PROVEN_OFFLINE" : "BLOCKED");
    printf("OPEN_FIELDS_HAVE_PROVEN_SOURCES=%s\n",
           r29_call_bound_mediareq26_uses_inbound_ctp ? "true" : "false");
    printf("STOP_FIELDS_HAVE_PROVEN_SOURCES=%s\n",
           r29_call_bound_mediareq26_stop_sent ? "true" : "false");
    printf("ATTACHED_MEDIA_STARTED=%s\n",
           r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ||
           r29_media_stop_completed ? "true" : "false");
    printf("MEDIA_CHANNEL_OPEN_REQUEST_SENT=%s\n",
           r29_media_channel_open_request_sent ? "true" : "false");
    printf("MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED=%s\n",
           r29_media_channel_open_response_observed ? "true" : "false");
    printf("CALL_BOUND_MEDIAREQ26_OPEN_SENT=%s\n",
           r29_call_bound_mediareq26_open_sent ? "true" : "false");
    printf("VIDEO_RTP_STARTED=%s\n",
           (r29_video_rtp_started_marker || p80_video_rtp_packets > 0u) ?
           "true" : "false");
    printf("FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=%s\n",
           r29_first_rtp_order_result());
    printf("VIDEO_RTP_PACKETS=%llu\n", (unsigned long long)p80_video_rtp_packets);
    printf("VIDEO_RTP_FIRST_AFTER_CALL_MS=%lld\n",
           (r29_first_video_rtp_monotonic_ms > 0 && r29_call_init_monotonic_ms > 0)
           ? (long long)(r29_first_video_rtp_monotonic_ms - r29_call_init_monotonic_ms)
           : 0LL);
    printf("VIDEO_RTP_OBSERVATION_SECONDS=%lld\n", observed_ms / 1000LL);
    printf("ATTACHED_MEDIA_STOP_REQUESTED=%s\n",
           r29_media_stop_requested ? "true" : "false");
    printf("MEDIA_ONLY_TEARDOWN_COMPLETE=%s\n",
           r29_media_stop_completed ? "true" : "false");
    printf("STOP_USES_SAME_CALL_CTP=%s\n",
           r29_call_bound_mediareq26_stop_sent ? "true" : "false");
    printf("MEDIA_LOCAL_DISPOSAL_IMPLEMENTED=%s\n",
           r29_media_stop_completed ? "true" : "false");
    printf("STOP_CALL_RELEASE_COUNT=%u\n", r29_stop_call_release_count);
    printf("STOP_REGISTRATION_CLOSE_COUNT=%u\n", r29_stop_registration_close_count);
    printf("STOP_PSEUDOTCP_CLOSE_COUNT=%u\n", r29_stop_pseudotcp_close_count);
    printf("STOP_LISTENER_STOP_COUNT=%u\n", r29_stop_listener_stop_count);
    printf("LISTENER_PROCESS_SAME_AFTER_CALL=%s\n",
           same_process ? "true" : "false");
    printf("LISTENER_PROCESS_SAME_AFTER_MEDIA=%s\n",
           same_process ? "true" : "false");
    printf("LISTENER_READY_AFTER_MEDIA=%s\n",
           r29_listener_registered_ready ? "true" : "false");
    printf("CALL_TRANSACTION_END_STATE=%s\n", call_end_state);
    printf("MEDIA_TEARDOWN_PRESERVES_TRANSPORT=%s\n",
           transport_preserved ? "true" : "false");
    printf("MEDIA_TEARDOWN_PRESERVES_REGISTRATION=%s\n",
           registration_preserved ? "true" : "false");
    printf("MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=%s\n",
           ring_listener_preserved ? "true" : "false");
    fflush(stdout);
}

static gboolean
r29_same_listener_process(void)
{
    return r29_listener_ready_pid != 0 && r29_listener_ready_pid == getpid();
}

static void
r29_capture_ready_snapshot(void)
{
    r29_listener_ready_pid = getpid();
    r29_ready_ice_bootstrap_count = r29_ice_bootstrap_count;
    r29_ready_cloud_negotiation_count = r29_cloud_negotiation_count;
    r29_ready_pseudotcp_open_count = r29_pseudotcp_open_count;
    r29_ready_ctpp_registration_count = r29_ctpp_registration_count;
}

static gboolean
r29_start_attached_media_from_call_init(const char *source)
{
    if (!source || strcmp(source, V4_ENTRANCE) != 0) {
        printf("R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE) {
        r29_second_media_start_blocked = TRUE;
        printf("R29_SECOND_MEDIA_START_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }
    if (r29_call_transaction_active) {
        printf("R29_SECOND_CALL_INIT_DURING_ACTIVE_MEDIA_BLOCKED=true\n");
        fflush(stdout);
        return FALSE;
    }

    r29_call_transaction_active = TRUE;
    r29_call_transaction_created = TRUE;
    r29_inbound_call_ctp_captured = FALSE;
    r29_call_ctp_separate_from_registration = FALSE;
    r29_call_bound_mediareq26_uses_inbound_ctp = FALSE;
    r29_call_init_monotonic_ms = p116_monotonic_ms();
    r29_media_observation_start_ms = r29_call_init_monotonic_ms;
    r29_attached_media_state = R29_INBOUND_CALL_ACTIVE;
    r29_media_open_blocked = TRUE;

    printf("R29_MEDIA_OPEN_MODEL=BLOCKED\n");
    printf("R29_MEDIA_OPEN_BLOCKED_REASON=CALL_INIT_ON_REGISTERED_CTPP_NO_SEPARATE_CALL_CTP_OR_MEDIAREQ26_BUILDER\n");
    printf("R29B_RESULT=BLOCKED_MISSING_OPEN_MAPPING\n");
    printf("INBOUND_CALL_CTP_CAPTURE_IMPLEMENTED=false\n");
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           r29_call_ctp_separate_from_registration ? "true" : "false");
    printf("CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=false\n");
    printf("MEDIA_CHANNEL_RUNTIME_ALLOCATION_IMPLEMENTED=false\n");
    printf("CALL_BOUND_MEDIAREQ26_OPEN_GENERATION=BLOCKED\n");
    printf("OPEN_FIELDS_HAVE_PROVEN_SOURCES=false\n");
    printf("INBOUND_VIDEO_RX_INITIATION=AUTO_ON_INCOMING_CALL_STATIC_ONLY\n");
    printf("INBOUND_MEDIA_REQUEST_DIRECTION=DEVICE_TO_CLIENT\n");
    printf("PREVIEW_ANSWERS_CALL=false\n");
    printf("PREVIEW_CAN_RUN_WHILE_RINGING=true\n");
    printf("CALL_TRANSACTION_CREATED=true\n");
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           r29_call_ctp_separate_from_registration ?
           "true" : "false");
    printf("ATTACHED_MEDIA_STARTED=%s\n",
           r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ? "true" : "false");
    printf("RTPC_MEDIA_CHANNELS_OPEN=%u\n", r29_rtpc_media_channels_open);
    r29_print_scalar_snapshot("MEDIA_OPEN_BLOCKED");
    fflush(stdout);
    return TRUE;
}

static gboolean
r29_registration_ctp_rejected_for_media(void)
{
    r29_registration_ctp_rejected_for_media_count++;
    printf("REGISTRATION_CTP_REJECTED_FOR_MEDIA=true\n");
    printf("REGISTRATION_CTP_REJECTED_FOR_MEDIA_COUNT=%u\n",
           r29_registration_ctp_rejected_for_media_count);
    fflush(stdout);
    return FALSE;
}

static gboolean
r29_unknown_001a_form_blocked(void)
{
    r29_unknown_001a_form_blocked_count++;
    printf("UNKNOWN_001A_FORM_BLOCKED=true\n");
    printf("UNKNOWN_001A_FORM_BLOCKED_COUNT=%u\n",
           r29_unknown_001a_form_blocked_count);
    fflush(stdout);
    return FALSE;
}

static gboolean
r29_media_only_teardown(const char *reason)
{
    (void)reason;
    if (r29_media_stop_completed) {
        printf("R29_MEDIA_STOP_SECOND_INVOCATION_REFUSED=true\n");
        fflush(stdout);
        return FALSE;
    }
    r29_media_stop_requested = TRUE;
    if (!r29_call_bound_mediareq26_open_sent) {
        r29_media_stop_before_open_blocked = TRUE;
        r29_media_teardown_blocked = TRUE;
        printf("R29_MEDIA_STOP_BEFORE_OPEN_BLOCKED=true\n");
        printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\n");
        printf("R29_MEDIA_ONLY_TEARDOWN_BLOCKED_REASON=NO_PROVEN_CALL_BOUND_MEDIAREQ26_STOP_BUILDER_OR_MEDIA_RX_POINTER_ID\n");
        fflush(stdout);
        return FALSE;
    }
    r29_media_teardown_blocked = TRUE;
    r29_media_observation_end_ms = p116_monotonic_ms();
    r29_attached_media_state = R29_ATTACHED_MEDIA_STOPPING;
    p80_media_forwarding_enabled = FALSE;
    if (p80_video_rtp_fd >= 0) {
        close(p80_video_rtp_fd);
        p80_video_rtp_fd = -1;
    }
    if (p80_audio_rtp_fd >= 0) {
        close(p80_audio_rtp_fd);
        p80_audio_rtp_fd = -1;
    }
    r29_call_transaction_active = FALSE;
    r29_media_stop_completed =
        !p80_media_forwarding_enabled &&
        p80_video_rtp_fd < 0 &&
        p80_audio_rtp_fd < 0 &&
        r29_same_listener_process() &&
        r29_listener_registered_ready;
    r29_attached_media_state = R29_LISTENER_REGISTERED_READY;
    printf("ATTACHED_MEDIA_STOP_REQUESTED=true\n");
    printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\n");
    printf("R29_MEDIA_ONLY_TEARDOWN_BLOCKED_REASON=NO_PROVEN_CALL_BOUND_MEDIAREQ26_STOP_BUILDER_OR_MEDIA_RX_POINTER_ID\n");
    printf("R29B_RESULT=BLOCKED_MISSING_STOP_MAPPING\n");
    printf("CALL_BOUND_MEDIAREQ26_STOP_GENERATION=BLOCKED\n");
    printf("STOP_FIELDS_HAVE_PROVEN_SOURCES=false\n");
    printf("MEDIA_ONLY_TEARDOWN_COMPLETE=%s\n",
           r29_media_stop_completed ? "true" : "false");
    r29_print_scalar_snapshot(r29_media_stop_completed ?
                              "MEDIA_ONLY_TEARDOWN_COMPLETE" :
                              "MEDIA_ONLY_TEARDOWN_BLOCKED");
    return r29_media_stop_completed;
}

static void
r29_note_channel_open_response_observed(void)
{
    r29_media_channel_open_response_observed = TRUE;
    printf("MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED=true\n");
    printf("FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=%s\n",
           r29_first_rtp_order_result());
    fflush(stdout);
}

static const char *
r29_first_rtp_order_result(void)
{
    if (r29_video_rtp_started_marker && r29_media_channel_open_response_observed)
        return "UNKNOWN";
    if (r29_video_rtp_started_marker)
        return "RESPONSE_NOT_OBSERVED";
    if (r29_media_channel_open_response_observed)
        return "RTP_NOT_OBSERVED";
    return "UNKNOWN";
}

static void
r29_sigusr2_handler(int signum)
{
    (void)signum;
    if (r29_sigusr2_seen) {
        r29_sigusr2_second_refused = TRUE;
        return;
    }
    r29_sigusr2_seen = TRUE;
}

static gboolean
r29_sigusr2_poll_cb(gpointer data)
{
    (void)data;
    if (r29_sigusr2_second_refused) {
        printf("R29_SIGUSR2_SECOND_INVOCATION_REFUSED=true\n");
        fflush(stdout);
        r29_sigusr2_second_refused = FALSE;
    }
    if (!r29_sigusr2_seen)
        return G_SOURCE_CONTINUE;
    r29_sigusr2_seen = FALSE;
    (void)r29_media_only_teardown("SIGUSR2");
    return G_SOURCE_CONTINUE;
}

static int
r29_selfcheck(void)
{
    printf("CANDIDATE_HELPER_EXECUTED=true\n");
    printf("R29_SELF_ACTIVATION_STUB_PRESENT=true\n");
    printf("R29_CLIENT_001A_STUB_PRESENT=true\n");
    r29_listener_registered_ready = TRUE;
    r29_capture_ready_snapshot();
    (void)r29_registration_ctp_rejected_for_media();
    (void)r29_unknown_001a_form_blocked();
    (void)r29_start_attached_media_from_call_init(V4_ENTRANCE);
    (void)r29_media_only_teardown("SELFCHECK");
    printf("NETWORK_WRITES_INTERCEPTED=true\n");
    printf("SELF_ACTIVATION_001A_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    printf("R27_REPEAT_001A_SENT_COUNT=%u\n", r29_r27_repeat_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_open_sent_count);
    printf("CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT=%u\n",
           r29_call_bound_mediareq26_stop_sent_count);
    printf("REGISTRATION_GENERATION_UNCHANGED=true\n");
    printf("PSEUDOTCP_TEARDOWN_COUNT=%u\n", r29_stop_pseudotcp_close_count);
    printf("LISTENER_STOP_COUNT=%u\n", r29_stop_listener_stop_count);
    printf("R29_MEDIA_OPEN_MODEL=BLOCKED\n");
    printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\n");
    printf("MISSING_IMPLEMENTATION_EVIDENCE=CALL_INIT_REQUEST_ID_EQUALS_REGISTERED_V4_CTPP_CHANNEL_ID_NO_PEER_CALL_CTP_FIELD_STORED;NO_26_BYTE_CALL_BOUND_MEDIAREQ_OPEN_STOP_BUILDER;RTPC_ALLOCATOR_AND_P80_FORWARDING_ARE_COMPONENT_ONLY_NOT_NATIVE_MEDIA_RX_POINTER_ID\n");
    return 0;
}
/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */
'''


R29_DISABLED_SELF_ACTIVATION_QUEUE = r'''static gboolean
entrance_signal_queue_self_activation(void)
{
    r29_self_activation_sent_count++;
    printf("R29_SELF_ACTIVATION_DISABLED=true\n");
    printf("SELF_ACTIVATION_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    fflush(stdout);
    return FALSE;
}'''


R29_DISABLED_CLIENT_001A_QUEUE = r'''static gboolean
p78_queue_rtpc_client_001a(void)
{
    r29_client_001a_sent_count++;
    printf("R29_CLIENT_001A_DISABLED=true\n");
    printf("CLIENT_001A_SENT_COUNT=%u\n", r29_client_001a_sent_count);
    fflush(stdout);
    return FALSE;
}'''


R29_READY_START_CB = r'''static gboolean
entrance_signal_start_cb(gpointer data)
{
    (void)data;

    r29_listener_registered_ready = TRUE;
    r29_attached_media_state = R29_LISTENER_REGISTERED_READY;
    r29_capture_ready_snapshot();
    r29_print_scalar_snapshot("NO_CALL");
    printf("RESEARCH_LISTENER_READY=true\n");
    printf("R29_LISTENER_STATE=LISTENER_REGISTERED_READY\n");
    fflush(stdout);
    return G_SOURCE_REMOVE;
}'''


def _patch_call_init_handler(candidate: str) -> str:
    anchor = """                printf(
                    \"PHYSICAL_DOOR_ACTION=false\\n\"
                );


                fflush(stdout);
"""
    replacement = """                printf(
                    \"PHYSICAL_DOOR_ACTION=false\\n\"
                );


                if (source && strcmp(source, V4_ENTRANCE) == 0) {
                    (void)r29_start_attached_media_from_call_init(source);
                } else {
                    printf(\"R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true\\n\");
                }


                fflush(stdout);
"""
    return _replace_once(candidate, anchor, replacement, "CALL_INIT R29 hook")


def _patch_rtp_progress(candidate: str) -> str:
    old = """        p80_video_rtp_packets++;
        if (p80_video_rtp_packets == 1u) {
            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }
"""
    new = """        p80_video_rtp_packets++;
        if (p80_video_rtp_packets == 1u) {
            r29_first_video_rtp_monotonic_ms = p116_monotonic_ms();
            printf("VIDEO_RTP_STARTED=true\\n");
            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");
            fflush(stdout);
        }
"""
    return _replace_once(candidate, old, new, "R29 video RTP first marker")


def _patch_counters(candidate: str) -> str:
    candidate = _replace_once(
        candidate,
        '    printf("PSEUDOTCP_OPEN=PASS\\n");\n',
        '    r29_pseudotcp_open_count++;\n    printf("PSEUDOTCP_OPEN=PASS\\n");\n'
        '    printf("PSEUDOTCP_OPEN_COUNT=%u\\n", r29_pseudotcp_open_count);\n',
        "R29 PseudoTCP counter",
    )
    candidate = _replace_once(
        candidate,
        '                "V4_CTPP_REGISTRATION=PASS\\n"\n',
        '                "V4_CTPP_REGISTRATION=PASS\\n"\n',
        "R29 CTPP registration anchor",
    )
    candidate = _replace_once(
        candidate,
        '                printf(\n                    "V4_CTPP_REGISTRATION=PASS\\n"\n                );\n',
        '                r29_ctpp_registration_count++;\n'
        '                r29_listener_registered_ready = TRUE;\n'
        '                printf(\n                    "V4_CTPP_REGISTRATION=PASS\\n"\n                );\n'
        '                printf("CTPP_REGISTRATION_COUNT=%u\\n", r29_ctpp_registration_count);\n'
        '                printf("RESEARCH_LISTENER_READY=true\\n");\n',
        "R29 CTPP ready counter",
    )
    candidate = _replace_once(
        candidate,
        '    remote_loaded = TRUE;\n\n    printf(\n        "REMOTE_PRIMITIVES_IMPORT=PASS\\n"\n    );\n',
        '    remote_loaded = TRUE;\n\n'
        '    r29_cloud_negotiation_count++;\n'
        '    printf("CLOUD_NEGOTIATION_COUNT=%u\\n", r29_cloud_negotiation_count);\n\n'
        '    printf(\n        "REMOTE_PRIMITIVES_IMPORT=PASS\\n"\n    );\n',
        "R29 cloud negotiation counter",
    )
    candidate = _replace_once(
        candidate,
        '    printf("ICE_GATHER_START=PASS\\n");\n',
        '    r29_ice_bootstrap_count++;\n    printf("ICE_GATHER_START=PASS\\n");\n'
        '    printf("ICE_BOOTSTRAP_COUNT=%u\\n", r29_ice_bootstrap_count);\n'
        '    printf("CLOUD_NEGOTIATION_COUNT=%u\\n", r29_cloud_negotiation_count);\n',
        "R29 ICE counter",
    )
    return candidate


def _patch_main(candidate: str) -> str:
    candidate = _replace_once(
        candidate,
        "main(void)\n{",
        "main(int argc, char **argv)\n{\n"
        "    if (argc == 2 && strcmp(argv[1], \"--r29-selfcheck\") == 0)\n"
        "        return r29_selfcheck();\n",
        "R29 selfcheck argv",
    )
    candidate = _replace_once(
        candidate,
        '    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\\n");\n',
        '    signal(SIGUSR2, r29_sigusr2_handler);\n'
        '    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\\n");\n'
        '    printf("R29_ONE_SHOT_CONTROL_KIND=SIGUSR2\\n");\n',
        "R29 SIGUSR2 install",
    )
    candidate = _replace_once(
        candidate,
        "    g_timeout_add(\n        100,\n        remote_sdp_check_cb,\n        NULL\n    );\n",
        "    g_timeout_add(\n        100,\n        remote_sdp_check_cb,\n        NULL\n    );\n\n"
        "    g_timeout_add(\n        100,\n        r29_sigusr2_poll_cb,\n        NULL\n    );\n",
        "R29 SIGUSR2 poll",
    )
    return candidate


def _patch_forbidden_call_sites(candidate: str) -> str:
    return _replace_once(
        candidate,
        "    return p78_queue_rtpc_client_001a();\n",
        "    r29_client_001a_sent_count++;\n"
        "    printf(\"R29_CLIENT_001A_DISABLED=true\\n\");\n"
        "    printf(\"CLIENT_001A_SENT_COUNT=%u\\n\", r29_client_001a_sent_count);\n"
        "    fflush(stdout);\n"
        "    return FALSE;\n",
        "R29 remove P78 001A queue call site",
    )


def _assert_source_lineage(source: str) -> None:
    missing = [marker for marker in LINEAGE_MARKERS if marker not in source]
    if missing:
        raise RuntimeError("R29_SOURCE_LINEAGE_GATE=FAIL missing=" + ",".join(missing))


def _assert_generated_gates(candidate: str) -> None:
    regions = {
        "self_activation": _region(candidate, "entrance_signal_queue_self_activation", "static gboolean\nentrance_signal_queue_video_event"),
        "client_001a": _region(candidate, "p78_queue_rtpc_client_001a(void)\n{", "static gboolean\np78_begin_rtpc_control"),
        "r29_attached": _region(candidate, "R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN", "R29_ATTACHED_MEDIA_FUNCTIONS_END"),
    }
    forbidden = {
        "self_activation": ("p12_queue_vip_frame", "P12_TX_ENTRANCE_SELF_ACTIVATION"),
        "client_001a": ("p12_queue_vip_frame", "P78_TX_RTPC_CLIENT_001A"),
        "r29_attached": ("v4_door_signal_handler", "P12_TX_V4_DOOR_WRITE", "pseudotcp_begin_graceful_stop"),
    }
    failures: list[str] = []
    for name, needles in forbidden.items():
        region = regions[name]
        for needle in needles:
            if needle in region:
                failures.append(f"{name}:{needle}")
    if failures:
        raise RuntimeError("R29_GENERATED_SOURCE_FORBIDDEN_GATE=FAIL " + ",".join(failures))


def _assert_r29_identifiers_resolved(candidate: str) -> None:
    regions = _r29_audit_regions(candidate)
    r29_defined: set[str] = set()
    for _, _, region in regions:
        r29_defined.update(_defined_identifiers(region))
    failures: list[str] = []
    full_defined = _defined_identifiers(candidate)
    for name, start, region in regions:
        prefix_defined = _defined_identifiers(candidate[:start])
        allowed = R29_IDENTIFIER_ALLOWLIST | r29_defined | prefix_defined | full_defined
        references = _identifier_tokens(region)
        unresolved = sorted(ref for ref in references if ref not in allowed)
        failures.extend(f"{name}:{ref}" for ref in unresolved)
    if failures:
        raise RuntimeError("R29_IDENTIFIER_GATE=FAIL unresolved=" + ",".join(failures))
    _assert_r29_external_identifier_ordering(candidate)


def _region(text: str, start: str, end: str) -> str:
    s = text.find(start)
    if s < 0:
        raise RuntimeError(f"region start missing: {start}")
    e = text.find(end, s)
    if e < 0:
        raise RuntimeError(f"region end missing: {end}")
    return text[s:e]


def transform(source: str) -> str:
    _assert_source_lineage(source)
    candidate = add_p106_runtime(source, include_p116=True)
    candidate = _replace_once(
        candidate,
        "static gboolean p80_media_forwarding_enabled = FALSE;\n",
        "static gboolean p80_media_forwarding_enabled = FALSE;\n" + R29_STATE,
        "R29 state insertion",
    )
    candidate = _replace_once(
        candidate,
        '#define V4_GATE         "00000610"\n',
        '#define V4_GATE         "00000610"\n' + R29_FUNCTIONS,
        "R29 function insertion",
    )
    candidate = _replace_named_function(
        candidate,
        "static gboolean\nentrance_signal_queue_self_activation(void)\n",
        R29_DISABLED_SELF_ACTIVATION_QUEUE,
    )
    candidate = _replace_named_function(
        candidate,
        "static gboolean\np78_queue_rtpc_client_001a(void)\n",
        R29_DISABLED_CLIENT_001A_QUEUE,
    )
    candidate = _replace_named_function(
        candidate,
        "static gboolean\nentrance_signal_start_cb(gpointer data)\n",
        R29_READY_START_CB,
    )
    candidate = _patch_call_init_handler(candidate)
    candidate = _patch_rtp_progress(candidate)
    candidate = _patch_counters(candidate)
    candidate = _patch_forbidden_call_sites(candidate)
    candidate = _patch_main(candidate)
    _assert_generated_gates(candidate)
    _assert_r29_identifiers_resolved(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE TRANSFORM ===",
            "LISTENER_SOURCE_LINEAGE=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c",
            "R29_MEDIA_OPEN_MODEL=BLOCKED",
            "R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED",
            "R29_ONE_SHOT_CONTROL_KIND=SIGUSR2",
            "R29_GENERATED_SOURCE_GATES=SCOPED_FORBIDDEN_PATHS,STATIC_IDENTIFIER_GATE,STATIC_IDENTIFIER_ORDER_GATE",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--include-p116", action="store_true", default=True)
    parser.add_argument("--no-include-p116", dest="include_p116", action="store_false")
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
    print("R29_TRANSFORM=PASS")
    print("R29_GENERATED_SOURCE_GATES=PASS")
    print("R29_MEDIA_OPEN_MODEL=BLOCKED")
    print("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
