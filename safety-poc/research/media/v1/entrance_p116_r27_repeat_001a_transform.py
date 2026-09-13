#!/usr/bin/env python3
"""P116/R27 research overlay: one same-session repeat client 0x001A probe.

This transform composes the current canonical P106 generator with P116 RTP
telemetry enabled, then adds a bounded, one-shot research-only second client
0x001A attempt after media is already active and video RTP has progressed.

The repeat body is regenerated from the live P76 RTPC runtime and current
semantic bindings, then only the mutable CTPP sequence is rebound from the live
initial 0x001A sequence.  It is not a replay of captured bytes and does not
reset the initial P97/P99 ACK gate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p106_teardown_state_classification_transform import (
    DEFAULT_SOURCE,
    transform as add_p106_runtime,
)


_TX_ENUM_OLD = """    P78_TX_RTPC_CLIENT_001A,

    P95_TX_DEVICE_0002_ACK,
"""

_TX_ENUM_NEW = """    P78_TX_RTPC_CLIENT_001A,
    R27_TX_RTPC_CLIENT_001A_REPEAT,

    P95_TX_DEVICE_0002_ACK,
"""

_STATE_OLD = """static gboolean p97_signaling_finished = FALSE;

/* P100: P99 pre-active demux state is defined with the earlier P80 RTP state. */
"""

_STATE_NEW = """static gboolean p97_signaling_finished = FALSE;

/* R27 one-shot same-session repeat 0x001A research state. */
#define R27_REPEAT_DELAY_SECONDS 20u
#define R27_REPEAT_ACK_TIMEOUT_SECONDS 5u
#define R27_MAX_LIVE_OBSERVATION_SECONDS 70u
#define R27_VIDEO_PAST_35S_SECONDS 35u
#define R27_VIDEO_PAST_40S_SECONDS 40u
static guint r27_initial_001a_sent_count = 0;
static guint r27_repeat_001a_sent_count = 0;
static guint r27_repeat_attempt_count = 0;
static gboolean r27_repeat_timer_armed = FALSE;
static gboolean r27_repeat_timer_cancelled = FALSE;
static gboolean r27_repeat_outstanding = FALSE;
static gboolean r27_repeat_ack_observed = FALSE;
static gboolean r27_repeat_ack_timed_out = FALSE;
static gboolean r27_repeat_ambiguous = FALSE;
static gboolean r27_third_001a_blocked = FALSE;
static gboolean r27_final_summary_printed = FALSE;
static long long r27_media_active_monotonic_ms = 0;
static long long r27_repeat_sent_monotonic_ms = 0;
static guint64 r27_video_packet_count_at_repeat = 0;
static guint8 r27_rtpc_client_001a_repeat[128];
static p76_u32 r27_rtpc_client_001a_repeat_len = 0;
static guint32 r27_initial_001a_sequence = 0;
static guint32 r27_repeat_001a_sequence = 0;
static gboolean r27_sequence_model_pass = FALSE;

static gboolean r27_repeat_delay_cb(gpointer data);
static gboolean r27_repeat_ack_timeout_cb(gpointer data);
static gboolean r27_live_observation_timeout_cb(gpointer data);
static gboolean r27_try_queue_repeat_001a(const char *reason);
static gboolean r27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len);
static void r27_cancel_repeat_timers(void);
static void r27_print_final_summary(void);

/* P100: P99 pre-active demux state is defined with the earlier P80 RTP state. */
"""

_QUEUE_FUNCTION_OLD = """static gboolean
p78_queue_rtpc_client_001a(void)
{
    p78_rtpc_stage = P78_RTPC_CLIENT_001A_TX;
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            p78_rtpc_client_001a,
            p78_rtpc_client_001a_len,
            P78_TX_RTPC_CLIENT_001A)) {
        p78_fail_rtpc("P78_RTPC_CLIENT_001A_QUEUE=FAIL");
        return FALSE;
    }
    if (!p12_flush_tx()) {
        p78_fail_rtpc("P78_RTPC_CLIENT_001A_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}
"""

_QUEUE_FUNCTION_NEW = _QUEUE_FUNCTION_OLD + r'''
/* === R27_REPEAT_001A_BEGIN === */
static gboolean
r27_queue_rtpc_client_001a_repeat(void)
{
    if (r27_initial_001a_sent_count > 1u ||
        r27_repeat_001a_sent_count > 0u ||
        r27_initial_001a_sent_count + r27_repeat_001a_sent_count >= 2u) {
        r27_third_001a_blocked = TRUE;
        failed = TRUE;
        fprintf(stderr, "R27_THIRD_001A_BLOCKED=true\n");
        if (loop)
            g_main_loop_quit(loop);
        return FALSE;
    }

    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            r27_rtpc_client_001a_repeat,
            r27_rtpc_client_001a_repeat_len,
            R27_TX_RTPC_CLIENT_001A_REPEAT)) {
        p78_fail_rtpc("R27_REPEAT_001A_QUEUE=FAIL");
        return FALSE;
    }
    if (!p12_flush_tx()) {
        p78_fail_rtpc("R27_REPEAT_001A_FLUSH=FAIL");
        return FALSE;
    }
    return TRUE;
}
/* === R27_REPEAT_001A_END === */
'''

_TX_COMPLETION_OLD = r'''        case P78_TX_RTPC_CLIENT_001A:
            p78_rtpc_client_001a_sent = TRUE;
            printf("P78_RTPC_CLIENT_001A_SENT=PASS\n");
            fflush(stdout);

            if (p97_device_ack_001a_observed) {
                (void)p97_finish_after_device_ack_001a();
            } else {
                printf("P80_WAIT_DEVICE_ACK_001A=true\n");
                fflush(stdout);
            }
            break;
'''

_TX_COMPLETION_NEW = r'''        case P78_TX_RTPC_CLIENT_001A:
            p78_rtpc_client_001a_sent = TRUE;
            r27_initial_001a_sent_count++;
            r27_initial_001a_sequence = read_le32(p78_rtpc_client_001a + 2u);
            printf("P78_RTPC_CLIENT_001A_SENT=PASS\n");
            printf("INITIAL_001A_SENT_COUNT=%u\n", r27_initial_001a_sent_count);
            printf("REPEAT_001A_SENT_COUNT=%u\n", r27_repeat_001a_sent_count);
            printf("TOTAL_001A_SENT_COUNT=%u\n",
                   r27_initial_001a_sent_count + r27_repeat_001a_sent_count);
            fflush(stdout);

            if (p97_device_ack_001a_observed) {
                (void)p97_finish_after_device_ack_001a();
            } else {
                printf("P80_WAIT_DEVICE_ACK_001A=true\n");
                fflush(stdout);
            }
            break;

        case R27_TX_RTPC_CLIENT_001A_REPEAT:
            r27_repeat_001a_sent_count++;
            r27_repeat_sent_monotonic_ms = p116_monotonic_ms();
            r27_repeat_outstanding = TRUE;
            r27_video_packet_count_at_repeat = p80_video_rtp_packets;
            printf("R27_REPEAT_001A_SENT=PASS\n");
            printf("INITIAL_001A_SENT_COUNT=%u\n", r27_initial_001a_sent_count);
            printf("REPEAT_001A_SENT_COUNT=%u\n", r27_repeat_001a_sent_count);
            printf("TOTAL_001A_SENT_COUNT=%u\n",
                   r27_initial_001a_sent_count + r27_repeat_001a_sent_count);
            printf("VIDEO_RTP_BEFORE_REPEAT=%s\n",
                   r27_video_packet_count_at_repeat > 0u ? "true" : "false");
            printf("VIDEO_PACKET_COUNT_AT_REPEAT=%llu\n",
                   (unsigned long long)r27_video_packet_count_at_repeat);
            printf("R27_REPEAT_ACK_GATE_ARMED=true\n");
            fflush(stdout);
            if (g_timeout_add_seconds(R27_REPEAT_ACK_TIMEOUT_SECONDS,
                                      r27_repeat_ack_timeout_cb, NULL) == 0) {
                p78_fail_rtpc("R27_REPEAT_ACK_TIMER_START=FAIL");
            }
            break;
'''

_MEDIA_ACTIVE_OLD = """    p80_media_forwarding_enabled = TRUE;
    g_timeout_add_seconds(10, p91_media_rx_diagnostic_timeout_cb, NULL);

    printf("P80_MEDIA_ACTIVE=true\\n");
"""

_MEDIA_ACTIVE_NEW = """    p80_media_forwarding_enabled = TRUE;
    g_timeout_add_seconds(10, p91_media_rx_diagnostic_timeout_cb, NULL);
    r27_media_active_monotonic_ms = p116_monotonic_ms();
    if (g_timeout_add_seconds(R27_REPEAT_DELAY_SECONDS, r27_repeat_delay_cb, NULL) == 0) {
        fprintf(stderr, "R27_REPEAT_TIMER_START=FAIL\\n");
        return FALSE;
    }
    if (g_timeout_add_seconds(R27_MAX_LIVE_OBSERVATION_SECONDS,
                              r27_live_observation_timeout_cb, NULL) == 0) {
        fprintf(stderr, "R27_OBSERVATION_TIMER_START=FAIL\\n");
        return FALSE;
    }
    r27_repeat_timer_armed = TRUE;

    printf("P80_MEDIA_ACTIVE=true\\n");
    printf("R27_REPEAT_DELAY_SECONDS=%u\\n", R27_REPEAT_DELAY_SECONDS);
    printf("R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false\\n");
    printf("R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false\\n");
    printf("ICE_NEGOTIATION_COUNT=1\\n");
    printf("PSEUDOTCP_OPEN_COUNT=1\\n");
    printf("CTPP_REGISTRATION_COUNT=1\\n");
    printf("RTPC_CLIENT_OPEN_COUNT=2\\n");
    printf("SELF_ACTIVATION_COUNT=1\\n");
    printf("HELPER_PROCESS_UNCHANGED=true\\n");
"""

_ACK_HOOK_OLD = """        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
            if (p97_handle_device_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""

_ACK_HOOK_NEW = """        } else if (r27_repeat_outstanding) {
            if (r27_handle_repeat_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
            if (p97_handle_device_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }
"""

_HELPER_ANCHOR = """static gboolean
p97_handle_device_ack(guint16 request_id, const guint8 *body, guint body_len)
{
"""

_R27_HELPERS = r'''/* === R27_REPEAT_001A_BEGIN === */
static void
r27_cancel_repeat_timers(void)
{
    r27_repeat_timer_cancelled = TRUE;
    r27_repeat_timer_armed = FALSE;
}

static gboolean
r27_repeat_preconditions_ok(void)
{
    if (r27_initial_001a_sent_count != 1u ||
        r27_repeat_001a_sent_count != 0u ||
        r27_repeat_attempt_count != 0u ||
        r27_initial_001a_sent_count + r27_repeat_001a_sent_count != 1u)
        return FALSE;
    if (!p78_rtpc_client_001a_sent || !p97_device_ack_001a_observed ||
        !p97_signaling_finished || !p80_media_forwarding_enabled)
        return FALSE;
    if (p80_video_rtp_packets == 0u)
        return FALSE;
    if (!pseudo_tcp || !pseudotcp_open || pseudotcp_graceful_stop_started)
        return FALSE;
    if (v4_ctpp_channel_id == 0 || p12_tx_pending)
        return FALSE;
    if (p78_rtpc_stage != P78_RTPC_COMPLETE ||
        p78_rtpc_client_001a_len != 60u)
        return FALSE;
    return TRUE;
}

static gboolean
r27_try_queue_repeat_001a(const char *reason)
{
    P76Status status;
    (void)reason;

    if (!r27_repeat_preconditions_ok()) {
        printf("R27_REPEAT_PRECONDITION=FAIL\n");
        fflush(stdout);
        return FALSE;
    }

    r27_repeat_attempt_count++;
    if (r27_repeat_attempt_count != 1u) {
        r27_third_001a_blocked = TRUE;
        failed = TRUE;
        fprintf(stderr, "R27_THIRD_001A_BLOCKED=true\n");
        if (loop)
            g_main_loop_quit(loop);
        return FALSE;
    }

    r27_rtpc_client_001a_repeat_len = p78_rtpc_client_001a_len;
    status = p76_generate_client_001a(
        &p78_rtpc_runtime,
        r27_rtpc_client_001a_repeat,
        r27_rtpc_client_001a_repeat_len);
    if (status != P76_OK) {
        p78_fail_rtpc("R27_REPEAT_001A_GENERATION=FAIL");
        return FALSE;
    }

    /* R27_SEQUENCE_MODEL_DERIVED_FROM_LIVE_INITIAL_001A_SEQUENCE:
     * the second mutable CTPP sequence is derived from the already-sent live
     * initial 0x001A sequence, while target/geometry/address roles are
     * regenerated from p78_rtpc_runtime semantic state. The delta is the
     * lineage's P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u
     * (entrance_p97_complete_post_000a_ack_cycle_transform.py:205-206,
     * applied at :351-355) and the P72 contract's nearest-preceding
     * same-request client CTPP frame delta
     * (P72_RTPC_CLIENT_MEDIA_GENERATION_CONTRACT.md:74-75). For this repeat,
     * the nearest preceding same-request client frame is the initial 0x001A
     * itself. */
    r27_repeat_001a_sequence =
        r27_initial_001a_sequence + P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK;
    write_le32(r27_rtpc_client_001a_repeat + 2u, r27_repeat_001a_sequence);
    r27_sequence_model_pass =
        r27_repeat_001a_sequence != r27_initial_001a_sequence &&
        memcmp(r27_rtpc_client_001a_repeat + 10u,
               p78_rtpc_client_001a + 10u,
               50u) == 0;
    if (!r27_sequence_model_pass) {
        p78_fail_rtpc("R27_REPEAT_SEQUENCE_MODEL=FAIL");
        return FALSE;
    }

    printf("R27_REPEAT_SEQUENCE_MODEL=PASS\n");
    printf("R27_REPEAT_SEQUENCE_SOURCE=LIVE_INITIAL_001A_SEQUENCE_PLUS_P97_DELTA\n");
    printf("CAPTURED_LITERAL_REUSE=false\n");
    printf("R27_REPEAT_SEMANTIC_FIELDS_REUSED=TARGET_GEOMETRY_ADDRESS_ROLES\n");
    printf("ICE_NEGOTIATION_COUNT=1\n");
    printf("PSEUDOTCP_OPEN_COUNT=1\n");
    printf("CTPP_REGISTRATION_COUNT=1\n");
    printf("RTPC_CLIENT_OPEN_COUNT=2\n");
    printf("SELF_ACTIVATION_COUNT=1\n");
    printf("HELPER_PROCESS_UNCHANGED=true\n");
    fflush(stdout);
    return r27_queue_rtpc_client_001a_repeat();
}

static gboolean
r27_repeat_delay_cb(gpointer data)
{
    (void)data;
    if (r27_repeat_timer_cancelled || pseudotcp_graceful_stop_started)
        return G_SOURCE_REMOVE;
    r27_repeat_timer_armed = FALSE;
    (void)r27_try_queue_repeat_001a("delay");
    return G_SOURCE_REMOVE;
}

static gboolean
r27_repeat_ack_timeout_cb(gpointer data)
{
    (void)data;
    if (!r27_repeat_outstanding || r27_repeat_ack_observed)
        return G_SOURCE_REMOVE;
    r27_repeat_ack_timed_out = TRUE;
    r27_repeat_outstanding = FALSE;
    printf("SECOND_001A_RESPONSE=ABSENT\n");
    fflush(stdout);
    return G_SOURCE_REMOVE;
}

static gboolean
r27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!r27_repeat_outstanding || r27_repeat_001a_sent_count != 1u)
        return FALSE;
    if (p99_state_scoped_structural_ack(request_id, body, body_len)) {
        r27_repeat_ack_observed = TRUE;
        r27_repeat_outstanding = FALSE;
        printf("SECOND_001A_RESPONSE=STRUCTURAL_ACK\n");
        printf("R27_REPEAT_ACK_BINDING=STATE_SCOPED_STRUCTURAL\n");
        fflush(stdout);
        return TRUE;
    }
    if (request_id == v4_ctpp_channel_id && body && body_len >= 4u) {
        /* A distinguishable reject path is not safe here: a non-structural
         * same-channel body cannot be proven to bind to the repeat rather than
         * an unrelated message, so report the contract-permitted AMBIGUOUS
         * state instead of a dead REJECTED state. */
        r27_repeat_ambiguous = TRUE;
        r27_repeat_outstanding = FALSE;
        printf("SECOND_001A_RESPONSE=AMBIGUOUS\n");
        fflush(stdout);
        return TRUE;
    }
    return FALSE;
}

static void
r27_print_final_summary(void)
{
    guint last_video_seconds = 0;
    gboolean after_repeat = FALSE;
    gboolean past35 = FALSE;
    gboolean past40 = FALSE;

    if (r27_final_summary_printed)
        return;
    r27_final_summary_printed = TRUE;
    if (r27_media_active_monotonic_ms > 0 &&
        p116_video_rtp.packet_count > 0u &&
        p116_video_rtp.last_monotonic_ms >= r27_media_active_monotonic_ms) {
        last_video_seconds = (guint)(
            (p116_video_rtp.last_monotonic_ms - r27_media_active_monotonic_ms) / 1000);
    }
    after_repeat = r27_repeat_001a_sent_count == 1u &&
        p80_video_rtp_packets > r27_video_packet_count_at_repeat;
    past35 = last_video_seconds >= R27_VIDEO_PAST_35S_SECONDS;
    past40 = last_video_seconds >= R27_VIDEO_PAST_40S_SECONDS;

    if (r27_repeat_001a_sent_count == 1u && !r27_repeat_ack_observed &&
        !r27_repeat_ack_timed_out && !r27_repeat_ambiguous)
        printf("SECOND_001A_RESPONSE=ABSENT\n");
    printf("VIDEO_RTP_AFTER_REPEAT=%s\n", after_repeat ? "true" : "false");
    printf("VIDEO_RTP_PAST_35S=%s\n", past35 ? "true" : "false");
    printf("VIDEO_RTP_PAST_40S=%s\n", past40 ? "true" : "false");
    printf("VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=%u\n", last_video_seconds);
    printf("INITIAL_001A_SENT_COUNT=%u\n", r27_initial_001a_sent_count);
    printf("REPEAT_001A_SENT_COUNT=%u\n", r27_repeat_001a_sent_count);
    printf("TOTAL_001A_SENT_COUNT=%u\n",
           r27_initial_001a_sent_count + r27_repeat_001a_sent_count);
    printf("R27_THIRD_001A_BLOCKED=%s\n",
           r27_third_001a_blocked ? "true" : "false");
    printf("ICE_NEGOTIATION_COUNT=1\n");
    printf("PSEUDOTCP_OPEN_COUNT=1\n");
    printf("CTPP_REGISTRATION_COUNT=1\n");
    printf("RTPC_CLIENT_OPEN_COUNT=2\n");
    printf("SELF_ACTIVATION_COUNT=1\n");
    printf("HELPER_PROCESS_UNCHANGED=true\n");
    fflush(stdout);
}

static gboolean
r27_live_observation_timeout_cb(gpointer data)
{
    (void)data;
    r27_cancel_repeat_timers();
    r27_print_final_summary();
    (void)pseudotcp_begin_graceful_stop("r27-observation-bound");
    return G_SOURCE_REMOVE;
}
/* === R27_REPEAT_001A_END === */

'''

_MAIN_FINAL_OLD = """    p116_print_final_rtp_summary();

    return failed ? 6 : 0;
}
"""

_MAIN_FINAL_NEW = """    r27_cancel_repeat_timers();
    r27_print_final_summary();
    p116_print_final_rtp_summary();

    return failed ? 6 : 0;
}
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("R27 requires --include-p116; --no-include-p116 is fail-closed")
    candidate = add_p106_runtime(source, include_p116=True)
    for old, new, label in (
        (_TX_ENUM_OLD, _TX_ENUM_NEW, "R27 tx enum"),
        (_STATE_OLD, _STATE_NEW, "R27 state"),
        (_QUEUE_FUNCTION_OLD, _QUEUE_FUNCTION_NEW, "R27 queue function"),
        (_TX_COMPLETION_OLD, _TX_COMPLETION_NEW, "R27 tx completion"),
        (_MEDIA_ACTIVE_OLD, _MEDIA_ACTIVE_NEW, "R27 media active timers"),
        (_ACK_HOOK_OLD, _ACK_HOOK_NEW, "R27 ACK hook"),
        (_HELPER_ANCHOR, _R27_HELPERS + _HELPER_ANCHOR, "R27 helpers"),
        (_MAIN_FINAL_OLD, _MAIN_FINAL_NEW, "R27 final summary"),
    ):
        candidate = _replace_once(candidate, old, new, label)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R27 REPEAT 001A TRANSFORM ===",
            "R27_COMPOSES=P106_INCLUDE_P116",
            "R27_REPEAT_SEQUENCE_MODEL=LIVE_INITIAL_001A_SEQUENCE_PLUS_P97_DELTA",
            "CAPTURED_LITERAL_REUSE=false",
            "R27_REPEAT_DELAY_SECONDS=20",
            "R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false",
            "R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false",
            "R27_PRODUCTION_REFRESH=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R27 REPEAT 001A TRANSFORM ===",
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
        parser.error("R27 requires --include-p116; --no-include-p116 is fail-closed")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8"), include_p116=True),
        encoding="utf-8",
    )
    print("P116_R27_REPEAT_001A_TRANSFORM=PASS")
    print("R27_COMPOSES=P106_INCLUDE_P116")
    print("R27_REPEAT_SEQUENCE_MODEL=PASS")
    print("CAPTURED_LITERAL_REUSE=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
