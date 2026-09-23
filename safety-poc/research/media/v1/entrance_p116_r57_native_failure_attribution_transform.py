#!/usr/bin/env python3
"""P116/R57: native failure-identity and exit-summary observability overlay.

R57 does not change any protocol, scheduling, timeout, or Door semantics. It
adds a bounded `P116NativeFailureId` / `P116NativeFailurePhase` pair in front
of every one of the 26 real `failed = TRUE;` sites inherited from the frozen
v1.5.7 listener (through R54's `transform()`), plus a first-fail-wins counter
and a terminal exit summary printed immediately before `return failed ? 6 :
0;`. It is generator-integrated: this module patches the text produced by
`entrance_p116_r54_call_adoption_listener_transform.transform()` at unique
anchors, the same technique R54 itself already uses against the frozen base.
It never edits the generated `.c` file or the frozen listener directly.

Corrective (build-blocking declaration order): the first R57 candidate emitted
its typedefs/enums/helpers at the late R54 anchor only, while the earliest
instrumented call site (p80_try_forward_wrapped_rtp) sits ~3000 lines earlier
in the generated translation unit. That does not compile (implicit
declaration / undeclared identifier / "static declaration follows non-static
declaration"). R57 is therefore emitted in two pieces: declarations
(`_R57_DECLS`) early, next to the pre-existing P80 media-forwarding state, and
definitions (`_R57_DEFS`) at the late R54 anchor. The whole-translation-unit
compile gate that catches this defect class lives in
`safety-poc/tests/test_p116_r57_whole_tu_compile_gate.py`.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r54_call_adoption_listener_transform as r54

BEGIN = "/* R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN */"
END = "/* R57_NATIVE_FAILURE_ATTRIBUTION_END */"
DECLS_BEGIN = "/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN */"
DECLS_END = "/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_END */"

_ANCHOR_AFTER = "/* R54_CALL_ADOPTION_LISTENER_END */"

# Declaration-order contract (build-blocking corrective).
#
# The first R57 candidate emitted everything -- typedefs, enum constants,
# file-scope state and helper definitions -- at _ANCHOR_AFTER, which lands
# around line 3550 of the generated translation unit, while the earliest
# instrumented site (p80_try_forward_wrapped_rtp -> P80_RTP_FORWARD) is at
# line ~463. Everything must be declared before its first use, so the
# overlay is emitted in two pieces:
#   * _R57_DECLS -- typedefs, enum constants and `static` prototypes, emitted
#     immediately before the pre-existing P80 media-forwarding state (the
#     same early anchor the P100 compile-order corrective uses), so every
#     declaration precedes its first use;
#   * _R57_DEFS -- file-scope state and helper bodies, kept at the late R54
#     anchor because p116_infer_phase() reads R42/R54 state
#     (v4_listener_ready, r42_media_stage, g_r54_tx_state) that is only
#     declared later in the file.
_EARLY_ANCHOR_BEFORE = "static gboolean p80_media_forwarding_enabled = FALSE;"

_R57_DECLS = r'''/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN */
/*
 * R57 declaration-order contract (build-blocking corrective).
 *
 * Every declaration below MUST be visible before the earliest instrumented
 * `failed = TRUE` site in the generated translation unit: that site is in
 * p80_try_forward_wrapped_rtp() at ~line 463, roughly 3000 lines before the
 * late R54 anchor where R57's helper bodies are emitted. The first R57
 * candidate emitted its typedefs *and* its helpers only at that late anchor,
 * which is a pure C declaration-order error (implicit declaration /
 * undeclared identifier / "static declaration follows non-static
 * declaration").
 *
 * This block is declarations only: no file-scope state is defined here and no
 * helper body appears here, because p116_infer_phase() reads R42/R54 state
 * (v4_listener_ready, r42_media_stage, g_r54_tx_state) that is declared later
 * in the file. The prototypes are `static` so they match the `static`
 * definitions in the R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN/END block exactly.
 */
typedef enum {
    P116_FAILURE_NONE = 0,
    P116_FAILURE_STARTUP,
    P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT,
    P116_FAILURE_P12_STEP_TIMEOUT,
    P116_FAILURE_UAUT_OPEN_TIMEOUT,
    P116_FAILURE_RECV_PARSE,
    P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT,
    P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT,
    P116_FAILURE_PSEUDOTCP_CLOSED,
    P116_FAILURE_PSEUDOTCP_WRITE_PACKET,
    P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED,
    P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET,
    P116_FAILURE_ICE_CONNECTIVITY,
    P116_FAILURE_ICE_GATHER,
    P116_FAILURE_SDP_FILE,
    P116_FAILURE_DOOR_WRITE,
    P116_FAILURE_DOOR_TIMER,
    P116_FAILURE_P80_RTP_FORWARD,
    P116_FAILURE_OTHER
} P116NativeFailureId;

typedef enum {
    P116_PHASE_STARTUP = 0,
    P116_PHASE_LISTENER_READY,
    P116_PHASE_CALL_ADOPTION_LOCAL,
    P116_PHASE_WAIT_PEER_CAPABILITIES,
    P116_PHASE_PEER_ACK,
    P116_PHASE_MEDIA_OPEN,
    P116_PHASE_MEDIA_ACTIVE,
    P116_PHASE_MEDIA_STOP,
    P116_PHASE_GENERATION_END
} P116NativeFailurePhase;

static void p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase);
static P116NativeFailurePhase p116_infer_phase(void);
static void p116_emit_timeout_observability(const char *kind);
static void p116_emit_native_exit_summary(gboolean failed_flag);
/* R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_END */'''

_R57_DEFS = r'''/* R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN */
/*
 * R57 file-scope state and helper definitions, emitted at the late R54 anchor
 * on purpose: p116_infer_phase() reads R42/R54 state (v4_listener_ready,
 * r42_media_stage, g_r54_tx_state) that is only declared later in this
 * translation unit. The matching declarations -- typedefs, enum constants and
 * static prototypes -- are emitted early, in the
 * R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN/END block, so that every
 * instrumented call site compiles wherever it sits in the file.
 */
static P116NativeFailureId g_p116_failure_id = P116_FAILURE_NONE;
static P116NativeFailurePhase g_p116_failure_phase = P116_PHASE_STARTUP;
static unsigned g_p116_failure_count = 0u;

static const char *
p116_failure_id_name(P116NativeFailureId id)
{
    switch (id) {
    case P116_FAILURE_NONE: return "NONE";
    case P116_FAILURE_STARTUP: return "STARTUP";
    case P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT: return "ABSOLUTE_SESSION_TIMEOUT";
    case P116_FAILURE_P12_STEP_TIMEOUT: return "P12_STEP_TIMEOUT";
    case P116_FAILURE_UAUT_OPEN_TIMEOUT: return "UAUT_OPEN_TIMEOUT";
    case P116_FAILURE_RECV_PARSE: return "RECV_PARSE";
    case P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT: return "PSEUDOTCP_RECV_TRANSPORT";
    case P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT: return "PSEUDOTCP_WRITABLE_TRANSPORT";
    case P116_FAILURE_PSEUDOTCP_CLOSED: return "PSEUDOTCP_CLOSED";
    case P116_FAILURE_PSEUDOTCP_WRITE_PACKET: return "PSEUDOTCP_WRITE_PACKET";
    case P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED: return "PSEUDOTCP_CLOCK_CLOSED";
    case P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET: return "PSEUDOTCP_NOTIFY_PACKET";
    case P116_FAILURE_ICE_CONNECTIVITY: return "ICE_CONNECTIVITY";
    case P116_FAILURE_ICE_GATHER: return "ICE_GATHER";
    case P116_FAILURE_SDP_FILE: return "SDP_FILE";
    case P116_FAILURE_DOOR_WRITE: return "DOOR_WRITE";
    case P116_FAILURE_DOOR_TIMER: return "DOOR_TIMER";
    case P116_FAILURE_P80_RTP_FORWARD: return "P80_RTP_FORWARD";
    case P116_FAILURE_OTHER: return "OTHER";
    }
    return "OTHER";
}

static const char *
p116_failure_phase_name(P116NativeFailurePhase phase)
{
    switch (phase) {
    case P116_PHASE_STARTUP: return "STARTUP";
    case P116_PHASE_LISTENER_READY: return "LISTENER_READY";
    case P116_PHASE_CALL_ADOPTION_LOCAL: return "CALL_ADOPTION_LOCAL";
    case P116_PHASE_WAIT_PEER_CAPABILITIES: return "WAIT_PEER_CAPABILITIES";
    case P116_PHASE_PEER_ACK: return "PEER_ACK";
    case P116_PHASE_MEDIA_OPEN: return "MEDIA_OPEN";
    case P116_PHASE_MEDIA_ACTIVE: return "MEDIA_ACTIVE";
    case P116_PHASE_MEDIA_STOP: return "MEDIA_STOP";
    case P116_PHASE_GENERATION_END: return "GENERATION_END";
    }
    return "GENERATION_END";
}

/*
 * Best-effort dynamic phase classification for the handful of failure
 * sites that are reachable across more than one call-adoption phase
 * (the generic PseudoTCP receive/write/close/writable callbacks and the
 * RTP forwarder). It reads only existing state that R42/R54 already
 * maintain; it performs no writes and changes no control flow.
 */
static P116NativeFailurePhase
p116_infer_phase(void)
{
    if (!v4_listener_ready)
        return P116_PHASE_STARTUP;

    switch (r42_media_stage) {
    case R42_MEDIA_CHANNEL_OPEN_TX:
    case R42_MEDIAREQ_OPEN_TX:
        return P116_PHASE_MEDIA_OPEN;
    case R42_MEDIA_ACTIVE:
        return P116_PHASE_MEDIA_ACTIVE;
    case R42_MEDIA_CHANNEL_CLOSE_TX:
    case R42_MEDIA_CHANNEL_CLOSE_WAIT:
        return P116_PHASE_MEDIA_STOP;
    default:
        break;
    }

    switch (g_r54_tx_state) {
    case R54_TX_STATE_NEED_INVITE_ACK:
    case R54_TX_STATE_WAIT_INVITE_ACK_FLUSH:
    case R54_TX_STATE_NEED_LOCAL_CAPABILITIES:
    case R54_TX_STATE_WAIT_LOCAL_CAPABILITIES_FLUSH:
    case R54_TX_STATE_NEED_LOCAL_ALERTING:
    case R54_TX_STATE_WAIT_LOCAL_ALERTING_FLUSH:
        return P116_PHASE_CALL_ADOPTION_LOCAL;
    case R54_TX_STATE_WAIT_PEER_CAPABILITIES:
        return P116_PHASE_WAIT_PEER_CAPABILITIES;
    case R54_TX_STATE_NEED_PEER_DATA_ACK:
    case R54_TX_STATE_WAIT_PEER_DATA_ACK_FLUSH:
        return P116_PHASE_PEER_ACK;
    case R54_TX_STATE_MEDIA_TRIGGER_READY:
        return P116_PHASE_MEDIA_OPEN;
    case R54_TX_STATE_TERMINAL_FAILURE:
        return P116_PHASE_GENERATION_END;
    case R54_TX_STATE_IDLE:
    default:
        break;
    }

    return P116_PHASE_LISTENER_READY;
}

/*
 * First-fail-wins: only the first call records the primary id/phase, so a
 * cascade of later failed=TRUE sites (e.g. a write failure that then
 * trips a teardown callback on the way out) can never overwrite the root
 * cause. g_p116_failure_count is bounded cascade diagnostics only.
 */
static void
p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase)
{
    g_p116_failure_count++;
    if (g_p116_failure_id == P116_FAILURE_NONE) {
        g_p116_failure_id = id;
        g_p116_failure_phase = phase;
    }
}

static void
p116_emit_timeout_observability(const char *kind)
{
    printf("P116_TIMEOUT_KIND=%s\n", kind);
    printf("P116_TIMEOUT_PHASE=%s\n", p116_failure_phase_name(p116_infer_phase()));
    fflush(stdout);
}

static void
p116_emit_native_exit_summary(gboolean failed_flag)
{
    printf("P116_NATIVE_EXIT_CODE=%d\n", failed_flag ? 6 : 0);
    printf("P116_NATIVE_FAILURE_ID=%s\n", p116_failure_id_name(g_p116_failure_id));
    printf("P116_NATIVE_FAILURE_PHASE=%s\n", p116_failure_phase_name(g_p116_failure_phase));
    printf("P116_NATIVE_FAILURE_COUNT=%u\n", g_p116_failure_count);
    fflush(stdout);
}
/* R57_NATIVE_FAILURE_ATTRIBUTION_END */'''


# (needle, call_expr, label). `needle` must occur exactly once in the R54
# candidate and must precede its site's own `failed = TRUE;` with no other
# site's `failed = TRUE;` in between.
_FAILURE_SITES: tuple[tuple[str, str, str], ...] = (
    ("P80_WRAPPER_PROFILE_MISMATCH=true",
     "p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase())",
     "R57 site p80_try_forward_wrapped_rtp/profile_mismatch"),
    ("P80_RTP_FORWARD_SOCKET=FAIL",
     "p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase())",
     "R57 site p80_try_forward_wrapped_rtp/socket"),
    ("P80_RTP_FORWARD_SEND=FAIL",
     "p116_record_failure(P116_FAILURE_P80_RTP_FORWARD, p116_infer_phase())",
     "R57 site p80_try_forward_wrapped_rtp/send"),
    ("PSEUDOTCP_NOTIFY_PACKET=FAIL ",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET, p116_infer_phase())",
     "R57 site recv_cb/notify_packet"),
    ("ICE_HOLDER_TIMEOUT=true",
     "p116_record_failure(P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT, P116_PHASE_STARTUP)",
     "R57 site absolute_timeout_cb"),
    ("P12_READONLY_STAGE_TIMEOUT stage=%u",
     "p116_record_failure(P116_FAILURE_P12_STEP_TIMEOUT, p116_infer_phase())",
     "R57 site p12_stage_timeout_cb"),
    ("v4_door_queue_write(v4_door_write_index + 1)",
     "p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY)",
     "R57 site p12_tx_completed/door_chained_write"),
    ("V4_DOOR_SETTLE_MS,",
     "p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY)",
     "R57 site p12_tx_completed/door_settle_timer_install"),
    ("g_get_monotonic_time() > v4_door_deadline_us) {",
     "p116_record_failure(P116_FAILURE_DOOR_TIMER, P116_PHASE_LISTENER_READY)",
     "R57 site v4_door_tick_cb/deadline"),
    ("v4_door_queue_write(1)",
     "p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY)",
     "R57 site v4_door_tick_cb/initial_write"),
    ("VIP_UAUT_OPEN_RESPONSE_TIMEOUT=true",
     "p116_record_failure(P116_FAILURE_UAUT_OPEN_TIMEOUT, P116_PHASE_STARTUP)",
     "R57 site uaut_response_timeout_cb"),
    ("if (!try_parse_initial_echo())",
     "p116_record_failure(P116_FAILURE_RECV_PARSE, P116_PHASE_STARTUP)",
     "R57 site pseudotcp_readable_cb/initial_echo"),
    ("if (!try_parse_uaut_response())",
     "p116_record_failure(P116_FAILURE_RECV_PARSE, p116_infer_phase())",
     "R57 site pseudotcp_readable_cb/post_handshake_recv"),
    ("PSEUDOTCP_RECV=FAIL",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_RECV_TRANSPORT, p116_infer_phase())",
     "R57 site pseudotcp_readable_cb/recv_error"),
    ("try_send_uaut_open() ||",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITABLE_TRANSPORT, p116_infer_phase())",
     "R57 site pseudotcp_writable_cb"),
    ("PSEUDOTCP_CLOSED_CALLBACK=true ",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOSED, p116_infer_phase())",
     "R57 site pseudotcp_closed_cb"),
    ("PSEUDOTCP_CONVERSATION_WIRE=FAIL",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase())",
     "R57 site pseudotcp_write_packet_cb/wire"),
    ("PSEUDOTCP_WRITE_PACKET=FAIL ",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_WRITE_PACKET, p116_infer_phase())",
     "R57 site pseudotcp_write_packet_cb/send"),
    ("pseudo_tcp_socket_is_closed(",
     "p116_record_failure(P116_FAILURE_PSEUDOTCP_CLOCK_CLOSED, P116_PHASE_STARTUP)",
     "R57 site pseudotcp_clock_cb"),
    ("SELECTED_PAIR=FAIL",
     "p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, P116_PHASE_STARTUP)",
     "R57 site component_state_changed_cb/selected_pair"),
    ("PSEUDOTCP_START=FAIL",
     "p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, P116_PHASE_STARTUP)",
     "R57 site component_state_changed_cb/start_pseudotcp"),
    ("ICE_CONNECTIVITY=FAIL",
     "p116_record_failure(P116_FAILURE_ICE_CONNECTIVITY, p116_infer_phase())",
     "R57 site component_state_changed_cb/failed_state"),
    ("REMOTE_SDP_READ=FAIL",
     "p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP)",
     "R57 site remote_sdp_check_cb/read"),
    ("REMOTE_PRIMITIVES_IMPORT=FAIL",
     "p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP)",
     "R57 site remote_sdp_check_cb/import"),
    ("ICE_GATHER=FAIL",
     "p116_record_failure(P116_FAILURE_ICE_GATHER, P116_PHASE_STARTUP)",
     "R57 site candidate_gathering_done_cb/gather"),
    ("OFFER_WRITE=FAIL",
     "p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP)",
     "R57 site candidate_gathering_done_cb/offer_write"),
)

_MAX_GAP = 700

# First use of each R57 identifier in the generated translation unit. The
# declaration-order gate asserts all three land after *_DECLS_END.
_FIRST_USE_NEEDLES = (
    "p116_record_failure(P116_FAILURE_",
    'p116_emit_timeout_observability("',
    "p116_emit_native_exit_summary(failed)",
)

# Everything the early declaration block must carry -- exactly once, and
# only there (a duplicated enum would be a C redeclaration error).
_EARLY_DECLARATION_NEEDLES = (
    "typedef enum {\n    P116_FAILURE_NONE = 0,",
    "typedef enum {\n    P116_PHASE_STARTUP = 0,",
    "static void p116_record_failure(P116NativeFailureId id, "
    "P116NativeFailurePhase phase);",
    "static P116NativeFailurePhase p116_infer_phase(void);",
    "static void p116_emit_timeout_observability(const char *kind);",
    "static void p116_emit_native_exit_summary(gboolean failed_flag);",
)

_TX_WAIT_TIMEOUT_NEEDLE = 'printf("TX_WAIT_TIMEOUT_MS=%u\\n", P12_STEP_TIMEOUT_SECONDS * 1000u);\n        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);\n        r54_publish_diagnostics('
_TX_WAIT_TIMEOUT_CALL = '        p116_emit_timeout_observability("R54_TX_WAIT_TIMEOUT");\n'

_FINAL_RETURN_NEEDLE = "    return failed ? 6 : 0;"
_FINAL_RETURN_CALL = "    p116_emit_native_exit_summary(failed);\n\n"


def _inject_before_failed(text: str, needle: str, call_expr: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one needle, found {count}")
    idx = text.index(needle)
    pos = text.index("failed = TRUE;", idx)
    if pos - idx > _MAX_GAP:
        raise RuntimeError(f"{label}: failed=TRUE too far from needle ({pos - idx} chars)")
    line_start = text.rfind("\n", 0, pos) + 1
    indent = text[line_start:pos]
    if indent.strip(" \t") != "":
        raise RuntimeError(f"{label}: unexpected non-whitespace before failed=TRUE")
    # `text[:pos]` already ends with `indent` (it precedes "failed" on the
    # same line), so the insertion must not repeat it before the call —
    # only re-emit it after the call to re-indent the "failed = TRUE;" line.
    insertion = f"{call_expr};\n{indent}"
    return text[:pos] + insertion + text[pos:]


def _assert_gates(candidate: str) -> None:
    for marker in (BEGIN, END, DECLS_BEGIN, DECLS_END):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R57_MARKER_GATE=FAIL marker={marker}")

    # Declaration-order gate: this is exactly the defect class that failed
    # the orchestrator's musl build (BUILD_RC=1, 11 errors: implicit
    # declaration, undeclared identifier, static-declaration-follows-
    # non-static). Every first use of an R57 identifier must come after the
    # early declaration block.
    decls_end = candidate.index(DECLS_END)
    for first_use in _FIRST_USE_NEEDLES:
        pos = candidate.find(first_use)
        if pos < 0:
            raise RuntimeError(f"R57_DECLARATION_ORDER_GATE=FAIL missing={first_use}")
        if pos < decls_end:
            raise RuntimeError(
                f"R57_DECLARATION_ORDER_GATE=FAIL use_before_declaration={first_use}"
            )
    decls = candidate.split(DECLS_BEGIN, 1)[1].split(DECLS_END, 1)[0]
    defs = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for needle in _EARLY_DECLARATION_NEEDLES:
        if needle not in decls:
            raise RuntimeError(f"R57_EARLY_DECLARATION_GATE=FAIL missing={needle!r}")
        if needle in defs:
            raise RuntimeError(f"R57_LATE_DUPLICATE_DECLARATION_GATE=FAIL duplicate={needle!r}")
    if "typedef enum {" in defs:
        raise RuntimeError("R57_LATE_TYPEDEF_GATE=FAIL")
    for needle in ("} P116NativeFailureId;", "} P116NativeFailurePhase;"):
        if candidate.count(needle) != 1:
            raise RuntimeError(f"R57_DECLARATION_DUPLICATION_GATE=FAIL marker={needle}")

    # +1 for the early `static` prototype and +1 for the definition itself
    # (`static void\np116_record_failure(...`).
    expected_occurrences = len(_FAILURE_SITES) + 2
    if candidate.count("p116_record_failure(") != expected_occurrences:
        raise RuntimeError(
            "R57_SITE_COUNT_GATE=FAIL "
            f"expected={expected_occurrences} "
            f"actual={candidate.count('p116_record_failure(')}"
        )
    if candidate.count("p116_record_failure(P116_FAILURE_") != len(_FAILURE_SITES):
        raise RuntimeError("R57_SITE_CALL_COUNT_GATE=FAIL")
    if candidate.count("failed = TRUE;") != len(_FAILURE_SITES):
        raise RuntimeError("R57_FAILED_TRUE_COUNT_CHANGED=FAIL")
    if candidate.count("p116_emit_native_exit_summary(failed);") != 1:
        raise RuntimeError("R57_EXIT_SUMMARY_GATE=FAIL")
    if candidate.count("p116_emit_timeout_observability(") < 1:
        raise RuntimeError("R57_TIMEOUT_OBSERVABILITY_GATE=FAIL")

    required = (
        "typedef enum {\n    P116_FAILURE_NONE = 0,",
        "typedef enum {\n    P116_PHASE_STARTUP = 0,",
        "static void\np116_record_failure(",
        "static P116NativeFailurePhase\np116_infer_phase(void)",
        "static void\np116_emit_native_exit_summary(gboolean failed_flag)",
    )
    for needle in required:
        if needle not in candidate:
            raise RuntimeError(f"R57_STRUCTURE_GATE=FAIL missing={needle!r}")

    # The exit summary must run before the return, and it must be the
    # last thing to run before it (no logic between summary and return).
    exit_idx = candidate.index("p116_emit_native_exit_summary(failed);")
    return_idx = candidate.index("return failed ? 6 : 0;")
    if not exit_idx < return_idx:
        raise RuntimeError("R57_EXIT_SUMMARY_ORDER_GATE=FAIL")

    # No protocol writes: R57 must not add any p12_queue_*/p12_flush_tx/
    # nice_agent_send/pseudo_tcp_socket_send call sites.
    r57_region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for forbidden in (
        "p12_queue_bytes(",
        "p12_queue_vip_frame(",
        "p12_flush_tx(",
        "nice_agent_send(",
        "pseudo_tcp_socket_send(",
    ):
        if forbidden in r57_region:
            raise RuntimeError(f"R57_NO_PROTOCOL_WRITES_GATE=FAIL needle={forbidden}")


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("R57_REAPPLY_GATE=FAIL")

    candidate = r54.transform(source)

    # (1) Declarations first: the overlay's typedefs, enum constants and
    # static prototypes are emitted immediately before the pre-existing P80
    # media-forwarding state, i.e. before the earliest instrumented function
    # (p80_try_forward_wrapped_rtp). Emitting them only at the late R54
    # anchor is what failed the orchestrator's musl build on declaration
    # order.
    if candidate.count(_EARLY_ANCHOR_BEFORE) != 1:
        raise RuntimeError("R57_EARLY_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _EARLY_ANCHOR_BEFORE,
        _R57_DECLS + "\n\n" + _EARLY_ANCHOR_BEFORE,
        1,
    )
    if DECLS_BEGIN not in candidate or DECLS_END not in candidate:
        raise RuntimeError("R57_EARLY_DECLARATION_INSERTION_GATE=FAIL")

    # (2) Definitions at the existing late R54 anchor: their bodies read
    # R42/R54 state that is only declared later in the translation unit.
    if candidate.count(_ANCHOR_AFTER) != 1:
        raise RuntimeError("R57_REGION_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _ANCHOR_AFTER,
        _ANCHOR_AFTER + "\n\n" + _R57_DEFS,
        1,
    )
    if BEGIN not in candidate or END not in candidate:
        raise RuntimeError("R57_REGION_INSERTION_GATE=FAIL")

    for needle, call_expr, label in _FAILURE_SITES:
        candidate = _inject_before_failed(candidate, needle, call_expr, label)

    if _TX_WAIT_TIMEOUT_NEEDLE not in candidate:
        raise RuntimeError("R57_TX_WAIT_TIMEOUT_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _TX_WAIT_TIMEOUT_NEEDLE,
        _TX_WAIT_TIMEOUT_CALL + '        printf("TX_WAIT_TIMEOUT_MS=%u\\n", P12_STEP_TIMEOUT_SECONDS * 1000u);\n        r54_tx_terminal_failure(R53_STAGE_TX_WAIT_TIMEOUT);\n        r54_publish_diagnostics(',
        1,
    )

    if candidate.count(_FINAL_RETURN_NEEDLE) != 1:
        raise RuntimeError("R57_FINAL_RETURN_ANCHOR_GATE=FAIL")
    candidate = candidate.replace(
        _FINAL_RETURN_NEEDLE,
        _FINAL_RETURN_CALL + _FINAL_RETURN_NEEDLE,
        1,
    )

    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R57 NATIVE FAILURE ATTRIBUTION TRANSFORM ===",
            "CORRECTIVE_TARGET=GENERATOR_OVERLAY_ON_R54_CANDIDATE",
            "GENERATED_TEXT_PATCH=false",
            "FROZEN_SOURCE_UNCHANGED=true",
            "OVERLAY_ANCHOR_STRATEGY=SPLIT_EARLY_DECLARATIONS_LATE_DEFINITIONS",
            f"EARLY_DECLARATION_ANCHOR={_EARLY_ANCHOR_BEFORE}",
            "DECLARATIONS_PRECEDE_FIRST_INSTRUMENTED_SITE=true",
            f"FAILED_SETTERS_TOTAL={len(_FAILURE_SITES)}",
            "FAILURE_ID_CONTRACT_IMPLEMENTED=true",
            "FAILURE_PHASE_CONTRACT_IMPLEMENTED=true",
            "FIRST_FAILURE_WINS=true",
            "OBSERVABILITY_PROTOCOL_WRITES_ADDED=0",
            "DOOR_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "WHOLE_TU_COMPILE_GATE=tests/test_p116_r57_whole_tu_compile_gate.py",
            "WHOLE_TU_COMPILE_GATE_MODE=cc -fsyntax-only",
            "=== END COMELIT P116 R57 NATIVE FAILURE ATTRIBUTION TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    safety_poc_root = Path(__file__).resolve().parents[3]
    source_path = args.source or (
        safety_poc_root / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
    )

    if args.sha256:
        candidate = transform(source_path.read_text(encoding="utf-8"))
        print(hashlib.sha256(candidate.encode("utf-8")).hexdigest())
        return 0

    if args.output is None:
        # Backwards compatible: a bare invocation still prints the report.
        print(report())
        return 0

    candidate = transform(source_path.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")
    print("R57_TRANSFORM=PASS")
    print(
        "R57_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    )
    print("R57_DECLARATIONS_PRECEDE_FIRST_INSTRUMENTED_SITE=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
