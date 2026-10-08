#!/usr/bin/env python3
"""P116/R67: attached-media same-generation MEDIAREQ26 refresh.

R67 composes the shipped listener lineage through R66 and adds a bounded
periodic refresh for already-active attached Ring media.  The refresh reuses
the existing call-bound CTPP transaction and the R35 MEDIAREQ26 OPEN serializer;
it does not create a second P2P/ICE/pseudoTCP/CTPP/RTPC/media generation.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r66_call_time_door_transform as r66

BEGIN = "/* R67_ATTACHED_MEDIA_REFRESH_BEGIN */"
END = "/* R67_ATTACHED_MEDIA_REFRESH_END */"

_ENUM_ANCHOR = "    P12_TX_CALL_TIME_DOOR,\n"
_ENUM_REPLACEMENT = "    P12_TX_CALL_TIME_DOOR,\n    P12_TX_R67_ATTACHED_REFRESH,\n"

_REGION_ANCHOR = "/* R66_CALL_TIME_DOOR_BEGIN */"
_R42_ACTIVATE_DECL_ANCHOR = """static gboolean
r42_activate_after_mediareq_open(void)"""
_R42_ACTIVATE_DECL_REPLACEMENT = """static gboolean r67_start_attached_refresh_loop(const char *reason);

static gboolean
r42_activate_after_mediareq_open(void)"""

_REGION = r'''/* R67_ATTACHED_MEDIA_REFRESH_BEGIN */
#define R67_ATTACHED_REFRESH_CADENCE_SECONDS 15u

typedef enum {
    R67_REFRESH_RESULT_NONE = 0,
    R67_REFRESH_RESULT_SENT,
    R67_REFRESH_RESULT_BUSY_DEFERRED,
    R67_REFRESH_RESULT_FAIL_CLOSED,
    R67_REFRESH_RESULT_CANCELLED,
    R67_REFRESH_RESULT_STOPPED
} R67AttachedRefreshResult;

static guint g_r67_attached_refresh_timer_armed = 0u;
static guint g_r67_attached_refresh_timer_source_id = 0u;
static guint g_r67_attached_refresh_outstanding = 0u;
static guint g_r67_attached_refresh_fail_closed = 0u;
static guint g_r67_attached_refresh_cancelled = 0u;
static guint g_r67_attached_refresh_queued_count = 0u;
static guint g_r67_attached_refresh_sent_count = 0u;
static guint g_r67_attached_refresh_first_elapsed_seconds = 0u;
static guint g_r67_attached_refresh_last_elapsed_seconds = 0u;
static guint g_r67_attached_refresh_tick_count = 0u;
static guint g_r67_attached_refresh_generation = 0u;
static guint g_r67_attached_refresh_channel_generation = 0u;
static guint g_r67_attached_refresh_sequence_before = 0u;
static guint g_r67_attached_refresh_sequence_after = 0u;
static R67AttachedRefreshResult g_r67_attached_refresh_last_result =
    R67_REFRESH_RESULT_NONE;
static const char *g_r67_attached_refresh_last_error = "NONE";

static gboolean r67_attached_refresh_delay_cb(gpointer data);
static gboolean r67_schedule_next_attached_refresh(const char *reason);

static const char *
r67_attached_refresh_result_name(R67AttachedRefreshResult result)
{
    switch (result) {
    case R67_REFRESH_RESULT_SENT:
        return "SENT";
    case R67_REFRESH_RESULT_BUSY_DEFERRED:
        return "BUSY_DEFERRED";
    case R67_REFRESH_RESULT_FAIL_CLOSED:
        return "FAIL_CLOSED";
    case R67_REFRESH_RESULT_CANCELLED:
        return "CANCELLED";
    case R67_REFRESH_RESULT_STOPPED:
        return "STOPPED";
    default:
        return "NONE";
    }
}

static void
r67_print_attached_refresh_diagnostics(void)
{
    printf("R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u\n",
        R67_ATTACHED_REFRESH_CADENCE_SECONDS);
    printf("R67_ATTACHED_REFRESH_QUEUED_COUNT=%u\n",
        g_r67_attached_refresh_queued_count);
    printf("R67_ATTACHED_REFRESH_SENT_COUNT=%u\n",
        g_r67_attached_refresh_sent_count);
    printf("R67_ATTACHED_REFRESH_FIRST_AGE_SECONDS=%u\n",
        g_r67_attached_refresh_first_elapsed_seconds);
    printf("R67_ATTACHED_REFRESH_LAST_AGE_SECONDS=%u\n",
        g_r67_attached_refresh_last_elapsed_seconds);
    printf("R67_ATTACHED_REFRESH_LAST_RESULT=%s\n",
        r67_attached_refresh_result_name(g_r67_attached_refresh_last_result));
    printf("R67_ATTACHED_REFRESH_LAST_ERROR=%s\n",
        g_r67_attached_refresh_last_error);
    printf("R67_ATTACHED_REFRESH_OUTSTANDING=%s\n",
        g_r67_attached_refresh_outstanding ? "true" : "false");
    printf("R67_ATTACHED_REFRESH_TIMER_SOURCE_ID=%u\n",
        g_r67_attached_refresh_timer_source_id);
    fflush(stdout);
}

static gboolean
r67_attached_refresh_session_preconditions_ok(void)
{
    return !pseudotcp_graceful_stop_started &&
        v4_listener_ready &&
        v4_registered &&
        v4_ctpp_channel_id != 0 &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        r35_call_ready(&g_r35_session) &&
        g_r35_session.call_ctp_valid &&
        g_r35_session.call_transaction_alive &&
        g_r35_session.listener_alive &&
        g_r35_session.registration_alive &&
        g_r35_session.pseudotcp_alive &&
        g_r35_session.channel_allocated &&
        !g_r35_session.channel_disposed &&
        g_r35_session.channel_generation == g_r35_session.call_generation &&
        g_r35_session.open_sent &&
        g_r35_session.open_count == 1u &&
        g_r35_session.rtp_armed &&
        !g_r35_session.stop_sent &&
        r42_media_stage == R42_MEDIA_ACTIVE &&
        r42_media_channel_id != 0u &&
        (unsigned)r42_media_channel_id == g_r35_session.channel_id;
}

static gboolean
r67_attached_refresh_preconditions_ok(void)
{
    return r67_attached_refresh_session_preconditions_ok() &&
        !g_r67_attached_refresh_cancelled &&
        !g_r67_attached_refresh_fail_closed;
}

static gboolean
r67_attached_refresh_current_session_matches(void)
{
    return g_r67_attached_refresh_generation == g_r35_session.call_generation &&
        g_r67_attached_refresh_channel_generation ==
            g_r35_session.channel_generation;
}

static void
r67_remove_attached_refresh_timer(const char *reason)
{
    guint source_id = g_r67_attached_refresh_timer_source_id;

    if (source_id != 0u) {
        g_r67_attached_refresh_timer_source_id = 0u;
        g_r67_attached_refresh_timer_armed = 0u;
        (void)g_source_remove(source_id);
        printf("R67_ATTACHED_REFRESH_TIMER_REMOVED=true\n");
        printf("R67_ATTACHED_REFRESH_TIMER_REMOVE_REASON=%s\n",
            reason ? reason : "unknown");
        printf("R67_ATTACHED_REFRESH_TIMER_SOURCE_ID=%u\n", source_id);
    } else {
        g_r67_attached_refresh_timer_armed = 0u;
    }
}

static void
r67_reset_attached_refresh_session(const char *reason)
{
    r67_remove_attached_refresh_timer(reason);
    g_r67_attached_refresh_outstanding = 0u;
    g_r67_attached_refresh_fail_closed = 0u;
    g_r67_attached_refresh_cancelled = 0u;
    g_r67_attached_refresh_queued_count = 0u;
    g_r67_attached_refresh_sent_count = 0u;
    g_r67_attached_refresh_first_elapsed_seconds = 0u;
    g_r67_attached_refresh_last_elapsed_seconds = 0u;
    g_r67_attached_refresh_tick_count = 0u;
    g_r67_attached_refresh_generation = g_r35_session.call_generation;
    g_r67_attached_refresh_channel_generation =
        g_r35_session.channel_generation;
    g_r67_attached_refresh_sequence_before = 0u;
    g_r67_attached_refresh_sequence_after = 0u;
    g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_NONE;
    g_r67_attached_refresh_last_error = "NONE";
    printf("R67_ATTACHED_REFRESH_SESSION_RESET=true\n");
    printf("R67_ATTACHED_REFRESH_SESSION_RESET_REASON=%s\n",
        reason ? reason : "new-session");
    printf("R67_ATTACHED_REFRESH_CALL_GENERATION=%u\n",
        g_r67_attached_refresh_generation);
    printf("R67_ATTACHED_REFRESH_CHANNEL_GENERATION=%u\n",
        g_r67_attached_refresh_channel_generation);
}

static void
r67_cancel_attached_refresh(const char *reason)
{
    g_r67_attached_refresh_cancelled = 1u;
    r67_remove_attached_refresh_timer(reason);
    g_r67_attached_refresh_outstanding = 0u;
    g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_CANCELLED;
    g_r67_attached_refresh_last_error = reason ? reason : "cancelled";
    printf("R67_ATTACHED_REFRESH_CANCELLED=true\n");
    printf("R67_ATTACHED_REFRESH_CANCEL_REASON=%s\n",
        g_r67_attached_refresh_last_error);
    r67_print_attached_refresh_diagnostics();
}

static gboolean
r67_start_attached_refresh_loop(const char *reason)
{
    if (!r67_attached_refresh_session_preconditions_ok())
        return FALSE;
    if (!r67_attached_refresh_current_session_matches())
        r67_reset_attached_refresh_session(reason);
    if (!r67_attached_refresh_preconditions_ok())
        return FALSE;
    if (g_r67_attached_refresh_timer_armed ||
        g_r67_attached_refresh_outstanding)
        return TRUE;
    g_r67_attached_refresh_last_error = "NONE";
    return r67_schedule_next_attached_refresh(reason);
}

static gboolean
r67_queue_attached_refresh(void)
{
    R35MediaRequestSources src;
    unsigned char body[R35_MEDIAREQ26_BODY_LEN];
    unsigned char packet[R35_CALL_BOUND_PACKET_LEN];
    gboolean queued;

    g_r67_attached_refresh_tick_count += 1u;
    if (!r67_attached_refresh_preconditions_ok()) {
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_STOPPED;
        g_r67_attached_refresh_last_error = "precondition";
        r67_remove_attached_refresh_timer("precondition");
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }
    if (g_r67_attached_refresh_outstanding) {
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "overlap";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }
    if (p12_tx_pending) {
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_BUSY_DEFERRED;
        g_r67_attached_refresh_last_error = "tx-busy";
        r67_print_attached_refresh_diagnostics();
        return r67_schedule_next_attached_refresh("tx-busy");
    }

    memset(&src, 0, sizeof(src));
    src.form = R35_FORM_TUNNEL;
    src.video_request = 1;
    src.profile_selector = 0;
    src.media_channel_id = (unsigned)r42_media_channel_id;
    src.max_rtp_payload = 0xffffu;
    src.channel_profile_word = 0u;
    src.profile_halfwords[0] = 0x0320u;
    src.profile_halfwords[1] = 0x01e0u;
    src.profile_halfwords[2] = 0x0140u;
    src.profile_halfword_3 = 0x00f0u;
    src.profile_byte_4 = 0x10u;

    if (!r35_serialize_mediareq26_open(body, &src) ||
        !r35_build_call_bound_packet(
            packet,
            g_r35_session.call_ctp_connection,
            g_r35_session.call_sequence,
            g_r35_session.call_ack,
            body,
            g_r35_session.source_logical,
            g_r35_session.dest_logical)) {
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "serialize";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }

    g_r67_attached_refresh_generation = g_r35_session.call_generation;
    g_r67_attached_refresh_channel_generation =
        g_r35_session.channel_generation;
    g_r67_attached_refresh_sequence_before = g_r35_session.call_sequence & 0xffu;
    g_r67_attached_refresh_sequence_after =
        (g_r67_attached_refresh_sequence_before + 1u) & 0xffu;
    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        packet,
        R35_CALL_BOUND_PACKET_LEN,
        P12_TX_R67_ATTACHED_REFRESH);
    memset(packet, 0, sizeof(packet));
    memset(body, 0, sizeof(body));
    if (!queued) {
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "queue";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }

    g_r67_attached_refresh_outstanding = 1u;
    g_r67_attached_refresh_queued_count += 1u;
    g_r67_attached_refresh_last_elapsed_seconds =
        g_r67_attached_refresh_tick_count * R67_ATTACHED_REFRESH_CADENCE_SECONDS;
    if (g_r67_attached_refresh_first_elapsed_seconds == 0u)
        g_r67_attached_refresh_first_elapsed_seconds =
            g_r67_attached_refresh_last_elapsed_seconds;
    g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_SENT;
    g_r67_attached_refresh_last_error = "NONE";
    printf("R67_ATTACHED_REFRESH_QUEUED=true\n");
    printf("R67_ATTACHED_REFRESH_OPCODE=0x0011\n");
    printf("R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN\n");
    printf("R67_ATTACHED_REFRESH_CALL_GENERATION=%u\n",
        g_r67_attached_refresh_generation);
    printf("R67_ATTACHED_REFRESH_CHANNEL_GENERATION=%u\n",
        g_r67_attached_refresh_channel_generation);
    printf("R67_ATTACHED_REFRESH_SEQUENCE_BEFORE=%u\n",
        g_r67_attached_refresh_sequence_before);
    r67_print_attached_refresh_diagnostics();
    if (!p12_flush_tx()) {
        g_r67_attached_refresh_outstanding = 0u;
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "transport";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }
    return TRUE;
}

static gboolean
r67_attached_refresh_tx_completed(void)
{
    gboolean sequence_committed = FALSE;

    if (!g_r67_attached_refresh_outstanding) {
        if (g_r67_attached_refresh_cancelled) {
            printf("R67_ATTACHED_REFRESH_CANCELLED_COMPLETION_IGNORED=true\n");
            r67_print_attached_refresh_diagnostics();
            return TRUE;
        }
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "no-outstanding";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }
    if (g_r35_session.call_generation == g_r67_attached_refresh_generation &&
        g_r35_session.channel_generation ==
            g_r67_attached_refresh_channel_generation &&
        r35_call_ready(&g_r35_session) &&
        (g_r35_session.call_sequence & 0xffu) ==
            g_r67_attached_refresh_sequence_before) {
        g_r35_session.call_sequence =
            g_r67_attached_refresh_sequence_after & 0xffu;
        sequence_committed = TRUE;
    } else {
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "stale-generation";
        printf("R67_ATTACHED_REFRESH_STALE_GENERATION=true\n");
    }

    g_r67_attached_refresh_outstanding = 0u;
    if (sequence_committed)
        g_r67_attached_refresh_sent_count += 1u;
    printf("R67_ATTACHED_REFRESH_SENT=true\n");
    printf("R67_ATTACHED_REFRESH_SEQUENCE_COMMITTED=%s\n",
        sequence_committed ? "true" : "false");
    printf("R67_ATTACHED_REFRESH_SEQUENCE_AFTER=%u\n",
        g_r35_session.call_sequence & 0xffu);
    r67_print_attached_refresh_diagnostics();
    if (!sequence_committed)
        return FALSE;
    return r67_schedule_next_attached_refresh("tx-complete");
}

static gboolean
r67_attached_refresh_delay_cb(gpointer data)
{
    guint timer_generation = GPOINTER_TO_UINT(data);

    if (g_r67_attached_refresh_timer_source_id != 0u)
        g_r67_attached_refresh_timer_source_id = 0u;
    g_r67_attached_refresh_timer_armed = 0u;
    if (timer_generation != g_r67_attached_refresh_generation ||
        !r67_attached_refresh_current_session_matches()) {
        printf("R67_ATTACHED_REFRESH_STALE_TIMER_IGNORED=true\n");
        return G_SOURCE_REMOVE;
    }
    if (g_r67_attached_refresh_cancelled ||
        pseudotcp_graceful_stop_started) {
        return G_SOURCE_REMOVE;
    }
    (void)r67_queue_attached_refresh();
    return G_SOURCE_REMOVE;
}

static gboolean
r67_schedule_next_attached_refresh(const char *reason)
{
    guint source_id;

    (void)reason;
    if (!r67_attached_refresh_preconditions_ok())
        return FALSE;
    if (g_r67_attached_refresh_cancelled ||
        g_r67_attached_refresh_fail_closed ||
        g_r67_attached_refresh_outstanding ||
        g_r67_attached_refresh_timer_armed)
        return FALSE;
    source_id = g_timeout_add_seconds(
            R67_ATTACHED_REFRESH_CADENCE_SECONDS,
            r67_attached_refresh_delay_cb,
            GUINT_TO_POINTER(g_r67_attached_refresh_generation));
    if (source_id == 0u) {
        g_r67_attached_refresh_fail_closed = 1u;
        g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_FAIL_CLOSED;
        g_r67_attached_refresh_last_error = "timer";
        r67_print_attached_refresh_diagnostics();
        return FALSE;
    }
    g_r67_attached_refresh_timer_source_id = source_id;
    g_r67_attached_refresh_timer_armed = 1u;
    printf("R67_ATTACHED_REFRESH_TIMER_ARMED=true\n");
    printf("R67_ATTACHED_REFRESH_TIMER_SOURCE_ID=%u\n",
        g_r67_attached_refresh_timer_source_id);
    r67_print_attached_refresh_diagnostics();
    return TRUE;
}
/* R67_ATTACHED_MEDIA_REFRESH_END */'''

_R42_ACTIVATE_ANCHOR = """    printf("R42_ATTACHED_MEDIA_ACTIVE=true\\n");
    printf("R42_LISTENER_PAUSED=false\\n");"""

_R42_ACTIVATE_REPLACEMENT = """    printf("R42_ATTACHED_MEDIA_ACTIVE=true\\n");
    (void)r67_start_attached_refresh_loop("attached-media-active");
    printf("R42_LISTENER_PAUSED=false\\n");"""

_TX_CASE_ANCHOR = """        case P12_TX_CALL_TIME_DOOR:
            if (!r66_call_time_door_tx_completed()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

"""

_TX_CASE_INSERT = r'''        case P12_TX_R67_ATTACHED_REFRESH:
            if (!r67_attached_refresh_tx_completed()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

'''

_R35_TEARDOWN_ANCHOR = """void r35_teardown_call(R35AttachedMediaSession *s) {
    if (!s) return;
    s->call_ctp_valid = 0;"""

_R35_TEARDOWN_REPLACEMENT = """static void r67_cancel_attached_refresh(const char *reason);

void r35_teardown_call(R35AttachedMediaSession *s) {
    r67_cancel_attached_refresh("call-teardown");
    if (!s) return;
    s->call_ctp_valid = 0;"""

_R37_STOP_ANCHOR = """static R35Result r37_stop_and_dispose(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form)"""

_R37_STOP_REPLACEMENT = """static R35Result r37_stop_and_dispose(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form)"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R67_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


def _insert_stop_cancel(candidate: str) -> str:
    signature = _R37_STOP_ANCHOR
    count = candidate.count(signature)
    if count != 1:
        raise RuntimeError(f"R67_STOP_SIGNATURE_GATE=FAIL count={count}")
    index = candidate.index(signature)
    brace = candidate.index("{", index)
    return candidate[: brace + 1] + '\n    r67_cancel_attached_refresh("attached-media-stop");' + candidate[brace + 1 :]


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("R67_REAPPLY_GATE=FAIL")

    candidate = r66.transform(source)
    candidate = _replace_once(candidate, _ENUM_ANCHOR, _ENUM_REPLACEMENT, "ENUM")
    candidate = _replace_once(
        candidate,
        _REGION_ANCHOR,
        _REGION + "\n\n" + _REGION_ANCHOR,
        "REGION",
    )
    candidate = _replace_once(
        candidate,
        _R42_ACTIVATE_DECL_ANCHOR,
        _R42_ACTIVATE_DECL_REPLACEMENT,
        "R42_ACTIVE_DECL",
    )
    candidate = _replace_once(
        candidate,
        _R42_ACTIVATE_ANCHOR,
        _R42_ACTIVATE_REPLACEMENT,
        "R42_ACTIVE",
    )
    candidate = _replace_once(
        candidate,
        _TX_CASE_ANCHOR,
        _TX_CASE_INSERT + _TX_CASE_ANCHOR,
        "TX_CASE",
    )
    candidate = _replace_once(
        candidate,
        _R35_TEARDOWN_ANCHOR,
        _R35_TEARDOWN_REPLACEMENT,
        "TEARDOWN",
    )
    candidate = _insert_stop_cancel(candidate)

    for marker in (
        BEGIN,
        END,
        "R67_ATTACHED_REFRESH_CADENCE_SECONDS 15u",
        "R67_ATTACHED_REFRESH_QUEUED_COUNT=%u",
        "R67_ATTACHED_REFRESH_OPCODE=0x0011",
        "R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN",
        "R67_ATTACHED_REFRESH_SESSION_RESET=true",
        "R67_ATTACHED_REFRESH_SESSION_RESET_REASON=%s",
        "R67_ATTACHED_REFRESH_TIMER_SOURCE_ID=%u",
        "R67_ATTACHED_REFRESH_TIMER_REMOVED=true",
        "R67_ATTACHED_REFRESH_TIMER_REMOVE_REASON=%s",
        "R67_ATTACHED_REFRESH_CANCELLED_COMPLETION_IGNORED=true",
        "R67_ATTACHED_REFRESH_STALE_TIMER_IGNORED=true",
        "R67_ATTACHED_REFRESH_CHANNEL_GENERATION=%u",
        "P12_TX_R67_ATTACHED_REFRESH",
        "r35_serialize_mediareq26_open(body, &src)",
        "r35_build_call_bound_packet(",
        "g_timeout_add_seconds(",
        "g_source_remove(source_id)",
        "r67_cancel_attached_refresh(\"attached-media-stop\")",
        "r67_cancel_attached_refresh(\"call-teardown\")",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R67_FINAL_GATE=FAIL missing={marker}")

    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for forbidden in (
        "/p2p/start",
        "nice_agent_new",
        "pseudo_tcp_socket_new",
        "P12_TX_V4_OPEN_CTPP",
        "P12_TX_V4_OPEN_CSPB",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "0x001Au",
        "0x1au",
        "vip_token",
        "access_token",
    ):
        if forbidden in region:
            raise RuntimeError(f"R67_FORBIDDEN_GATE=FAIL forbidden={forbidden}")
    if region.count("g_timeout_add_seconds(") != 1:
        raise RuntimeError("R67_SINGLE_TIMER_SITE_GATE=FAIL")
    if region.count("g_source_remove(source_id)") != 1:
        raise RuntimeError("R67_SINGLE_TIMER_REMOVE_SITE_GATE=FAIL")
    if region.count("p12_queue_vip_frame(") != 1:
        raise RuntimeError("R67_SINGLE_EXISTING_WRITER_GATE=FAIL")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    safety_poc_root = Path(__file__).resolve().parents[3]
    source_path = args.source or (
        safety_poc_root
        / "research"
        / "door"
        / "v1_5_7"
        / "comelit-v4-persistent-ctpp-door.c"
    )
    output = transform(source_path.read_text(encoding="utf-8"))
    if args.sha256:
        print(hashlib.sha256(output.encode("utf-8")).hexdigest())
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    elif not args.sha256:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
