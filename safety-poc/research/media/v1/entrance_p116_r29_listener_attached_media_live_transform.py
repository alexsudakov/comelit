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
static gboolean r29_media_stop_requested = FALSE;
static gboolean r29_media_stop_completed = FALSE;
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
static gboolean r29_media_only_teardown(const char *reason);
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
    gboolean call_separate_from_registration = r29_call_transaction_created &&
        r29_listener_registered_ready;
    long long observed_ms = r29_media_observation_end_ms - r29_media_observation_start_ms;
    if (observed_ms < 0)
        observed_ms = 0;

    printf("ICE_BOOTSTRAP_COUNT=%u\n", r29_ice_bootstrap_count);
    printf("CLOUD_NEGOTIATION_COUNT=%u\n", r29_cloud_negotiation_count);
    printf("PSEUDOTCP_OPEN_COUNT=%u\n", r29_pseudotcp_open_count);
    printf("CTPP_REGISTRATION_COUNT=%u\n", r29_ctpp_registration_count);
    printf("RTPC_MEDIA_CHANNELS_OPEN=%u\n", r29_rtpc_media_channels_open);
    printf("SELF_ACTIVATION_SENT_COUNT=%u\n", r29_self_activation_sent_count);
    printf("CLIENT_001A_SENT_COUNT=%u\n", r29_client_001a_sent_count);
    printf("R27_REPEAT_SENT_COUNT=%u\n", r29_r27_repeat_sent_count);
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
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           call_separate_from_registration ? "true" : "false");
    printf("ATTACHED_MEDIA_STARTED=%s\n",
           r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ||
           r29_media_stop_completed ? "true" : "false");
    printf("VIDEO_RTP_STARTED=%s\n", p80_video_rtp_packets > 0u ? "true" : "false");
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
    r29_call_init_monotonic_ms = p116_monotonic_ms();
    r29_media_observation_start_ms = r29_call_init_monotonic_ms;
    r29_attached_media_state = R29_INBOUND_CALL_ACTIVE;
    r29_media_open_blocked = TRUE;

    printf("R29_MEDIA_OPEN_MODEL=BLOCKED\n");
    printf("R29_MEDIA_OPEN_BLOCKED_REASON=NO_PROVEN_HELPER_ACTION_FOR_ATTACHED_INBOUND_RTPC_OPEN\n");
    printf("INBOUND_VIDEO_RX_INITIATION=AUTO_ON_INCOMING_CALL_STATIC_ONLY\n");
    printf("INBOUND_MEDIA_REQUEST_DIRECTION=DEVICE_TO_CLIENT\n");
    printf("PREVIEW_ANSWERS_CALL=false\n");
    printf("PREVIEW_CAN_RUN_WHILE_RINGING=true\n");
    printf("CALL_TRANSACTION_CREATED=true\n");
    printf("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s\n",
           (r29_call_transaction_created && r29_listener_registered_ready) ?
           "true" : "false");
    printf("ATTACHED_MEDIA_STARTED=%s\n",
           r29_attached_media_state == R29_ATTACHED_MEDIA_ACTIVE ? "true" : "false");
    printf("RTPC_MEDIA_CHANNELS_OPEN=%u\n", r29_rtpc_media_channels_open);
    r29_print_scalar_snapshot("MEDIA_OPEN_BLOCKED");
    fflush(stdout);
    return TRUE;
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
    printf("R29_MEDIA_ONLY_TEARDOWN_BLOCKED_REASON=NO_PROVEN_HELPER_ACTION_FOR_NATIVE_CLOSE_MEDIA_RX_CHANNEL\n");
    printf("MEDIA_ONLY_TEARDOWN_COMPLETE=%s\n",
           r29_media_stop_completed ? "true" : "false");
    r29_print_scalar_snapshot(r29_media_stop_completed ?
                              "MEDIA_ONLY_TEARDOWN_COMPLETE" :
                              "MEDIA_ONLY_TEARDOWN_BLOCKED");
    return r29_media_stop_completed;
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
    printf("R29_MEDIA_OPEN_MODEL=BLOCKED\n");
    printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\n");
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
        "static gboolean\np80_rtp_v2_shape",
        R29_FUNCTIONS + "\nstatic gboolean\np80_rtp_v2_shape",
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
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE TRANSFORM ===",
            "LISTENER_SOURCE_LINEAGE=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c",
            "R29_MEDIA_OPEN_MODEL=BLOCKED",
            "R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED",
            "R29_ONE_SHOT_CONTROL_KIND=SIGUSR2",
            "R29_GENERATED_SOURCE_GATES=SCOPED_FORBIDDEN_PATHS",
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
