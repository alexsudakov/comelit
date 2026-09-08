#!/usr/bin/env python3
"""P78: bind the P76 RTPC state machine to the reviewed live transport writer.

The transform first composes the same reviewed chain used by P76
(`entrance_device_video_ack_observation_transform` through P76), then applies
one narrow transport-binding stage.  `--report` follows the P76-family quirk:
report mode prints markers and does not write an output C file.

No raw, hex, or base64 payload bytes are printed by the generated stage.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from entrance_rtpc_control_media_runtime_transform import (
    DEFAULT_SOURCE,
    transform as add_p76_runtime,
)


P78_REVIEW_COMMIT_SHA = ""


@dataclass(frozen=True)
class Replacement:
    name: str
    old: str
    new: str


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"anchor count for {old[:80]!r}: {count}")
    return source.replace(old, new, 1)


TX_ENUM_ANCHOR = """    P12_TX_ENTRANCE_SELF_ACTIVATION,
    P12_TX_ENTRANCE_VIDEO_EVENT,
    P12_TX_ENTRANCE_DEVICE_VIDEO_ACK,

    P12_TX_V4_DOOR_WRITE
} P12TxKind;"""

TX_ENUM_REPLACEMENT = """    P12_TX_ENTRANCE_SELF_ACTIVATION,
    P12_TX_ENTRANCE_VIDEO_EVENT,
    P12_TX_ENTRANCE_DEVICE_VIDEO_ACK,

    P78_TX_RTPC_OPEN_1,
    P78_TX_RTPC_OPEN_2,
    P78_TX_RTPC_CLIENT_RESPONSE,
    P78_TX_RTPC_CLIENT_000A,
    P78_TX_RTPC_CLIENT_001A,

    P12_TX_V4_DOOR_WRITE
} P12TxKind;"""


STATE_ANCHOR = """static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static guint32 entrance_video_event_sequence = 0;
static guint32 entrance_device_video_ack_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;"""

STATE_REPLACEMENT = """static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static guint32 entrance_video_event_sequence = 0;
static guint32 entrance_device_video_ack_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;

/* P78 live RTPC binding state. */
typedef enum {
    P78_RTPC_IDLE = 0,
    P78_RTPC_WAIT_DEVICE_OPEN,
    P78_RTPC_WAIT_DEVICE_RESPONSES,
    P78_RTPC_CLIENT_MEDIA_TX,
    P78_RTPC_COMPLETE,
    P78_RTPC_FAILED
} P78RtpcLiveStage;

#define P78_MEDIA_OBSERVE_MS 3000

static P78RtpcLiveStage p78_rtpc_stage = P78_RTPC_IDLE;
static gboolean p78_rtpc_open_1_sent = FALSE;
static gboolean p78_rtpc_open_2_sent = FALSE;
static gboolean p78_rtpc_device_open_observed = FALSE;
static gboolean p78_rtpc_client_response_sent = FALSE;
static guint p78_rtpc_device_response_count = 0;
static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;

static gboolean p78_begin_rtpc_control(void);
static gboolean p78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len);"""


ACK_COMPLETION_ANCHOR = """        case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:
            entrance_device_video_ack_sent = TRUE;
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS\\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true\\n");
            fflush(stdout);

            if (!entrance_signal_begin_media_observation()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;"""

ACK_COMPLETION_REPLACEMENT = """        case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:
            entrance_device_video_ack_sent = TRUE;
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS\\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true\\n");
            printf("P78_DEVICE_0008_ACK_SENT=true\\n");
            printf("P78_DEVICE_0008_ACK_GATE_PROVEN=false\\n");
            fflush(stdout);

            if (!p78_begin_rtpc_control()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

        case P78_TX_RTPC_OPEN_1:
            p78_rtpc_open_1_sent = TRUE;
            printf("P78_RTPC_OPEN_1_SENT=PASS\\n");
            fflush(stdout);
            break;

        case P78_TX_RTPC_OPEN_2:
            p78_rtpc_open_2_sent = TRUE;
            p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_OPEN;
            printf("P78_RTPC_OPEN_2_SENT=PASS\\n");
            fflush(stdout);
            break;

        case P78_TX_RTPC_CLIENT_RESPONSE:
            p78_rtpc_client_response_sent = TRUE;
            printf("P78_RTPC_CLIENT_RESPONSE_SENT=PASS\\n");
            fflush(stdout);
            break;

        case P78_TX_RTPC_CLIENT_000A:
            p78_rtpc_client_000a_sent = TRUE;
            printf("P78_RTPC_CLIENT_000A_SENT=PASS\\n");
            fflush(stdout);
            break;

        case P78_TX_RTPC_CLIENT_001A:
            p78_rtpc_client_001a_sent = TRUE;
            p78_rtpc_stage = P78_RTPC_COMPLETE;
            printf("P78_RTPC_CLIENT_001A_SENT=PASS\\n");
            printf("P78_RTPC_SIGNALING_RESULT=PASS\\n");
            fflush(stdout);

            if (!entrance_signal_begin_media_observation()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;"""


FRAME_HOOK_ANCHOR = """        } else if (entrance_signal_stage == ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO) {
            if (request_id == v4_ctpp_channel_id &&
                entrance_signal_body_is_device_video(body, body_len)) {

                p12_consume_post_ack(frame_len);
                return entrance_signal_queue_device_video_ack();
            }
        }




        /*
         * --------------------------------------------------------
         * V4 post-registration diagnostic"""

FRAME_HOOK_REPLACEMENT = """        } else if (entrance_signal_stage == ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO) {
            if (request_id == v4_ctpp_channel_id &&
                entrance_signal_body_is_device_video(body, body_len)) {

                p12_consume_post_ack(frame_len);
                return entrance_signal_queue_device_video_ack();
            }
        } else if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN ||
                   p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
            if (p78_handle_rtpc_control_frame(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        }




        /*
         * --------------------------------------------------------
         * V4 post-registration diagnostic"""


P78_HELPER_ANCHOR = "\n/* === P76_RTPC_CONTROL_MEDIA_RUNTIME_END === */\n"

P78_HELPER_REPLACEMENT = r'''
/* === P76_RTPC_CONTROL_MEDIA_RUNTIME_END === */

/* === P78_RTPC_MEDIA_LIVE_STAGE_BEGIN ===
 * P78_TRANSPORT_BINDING=REVIEW_REQUIRED
 * P78_REVIEW_COMMIT_SHA_REQUIRED=true
 * REGISTERED_CTPP_REUSED=true
 * SECOND_CTPP_OPEN=false
 * DOOR_ACTION_SENT=false
 * RAW_PAYLOAD_EMITTED=false
 * HEX_PAYLOAD_EMITTED=false
 * BASE64_PAYLOAD_EMITTED=false
 * DEVICE_0008_ACK_GATE_PROVEN=false
 * P78_MEDIA_OBSERVE_MS=3000
 */
static P76Runtime p78_rtpc_runtime;
static guint8 p78_rtpc_open_1[P76_MAX_BODY];
static guint8 p78_rtpc_open_2[P76_MAX_BODY];
static guint8 p78_rtpc_client_response[P76_MAX_BODY];
static guint8 p78_rtpc_client_000a[P76_MAX_BODY];
static guint8 p78_rtpc_client_001a[P76_MAX_BODY];
static p76_u32 p78_rtpc_open_1_len = 0;
static p76_u32 p78_rtpc_open_2_len = 0;
static p76_u32 p78_rtpc_client_response_len = 0;
static p76_u32 p78_rtpc_client_000a_len = 0;
static p76_u32 p78_rtpc_client_001a_len = 0;

static void
p78_fail_rtpc(const char *marker)
{
    p78_rtpc_stage = P78_RTPC_FAILED;
    failed = TRUE;
    fprintf(stderr, "%s\n", marker);
    fprintf(stderr, "P78_RTPC_SIGNALING_RESULT=FAIL\n");
    if (loop)
        g_main_loop_quit(loop);
}

static void
p78_copy_role(guint8 out[9], const char *value)
{
    guint i;
    for (i = 0; i < 9; i++)
        out[i] = value[i] ? (guint8)value[i] : 0;
}

static gboolean
p78_begin_rtpc_control(void)
{
    guint8 role_a[9];
    guint8 role_b[9];
    P76Status status;

    if (p78_rtpc_stage != P78_RTPC_IDLE ||
        entrance_signal_stage != ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX ||
        !entrance_device_video_ack_sent ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        p78_fail_rtpc("P78_RTPC_START_PRECONDITION=FAIL");
        return FALSE;
    }

    p76_runtime_init(&p78_rtpc_runtime, g_random_int());
    p78_copy_role(role_a, V4_FULL_ADDRESS);
    p78_copy_role(role_b, V4_ENTRANCE);

    status = p76_generate_client_exchange(
        &p78_rtpc_runtime,
        entrance_video_event_sequence,
        entrance_video_event_sequence + 0x00010000u,
        role_a,
        role_b,
        p78_rtpc_open_1,
        &p78_rtpc_open_1_len,
        p78_rtpc_open_2,
        &p78_rtpc_open_2_len,
        p78_rtpc_client_000a,
        &p78_rtpc_client_000a_len,
        p78_rtpc_client_001a,
        &p78_rtpc_client_001a_len);
    if (status != P76_OK) {
        p78_fail_rtpc("P78_RTPC_GENERATE_CLIENT_EXCHANGE=FAIL");
        return FALSE;
    }

    printf("P78_CTPP_REGISTERED_REUSED=true\n");
    printf("P78_SECOND_CTPP_OPEN=false\n");
    printf("P78_MEDIA_OBSERVATION_WINDOW_MS=%u\n", P78_MEDIA_OBSERVE_MS);
    printf("P78_RAW_PAYLOAD_EMITTED=false\n");
    fflush(stdout);

    p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_OPEN;
    if (!p12_queue_vip_frame(0, p78_rtpc_open_1, p78_rtpc_open_1_len, P78_TX_RTPC_OPEN_1)) {
        p78_fail_rtpc("P78_RTPC_OPEN_1_QUEUE=FAIL");
        return FALSE;
    }
    if (!p12_queue_vip_frame(0, p78_rtpc_open_2, p78_rtpc_open_2_len, P78_TX_RTPC_OPEN_2)) {
        p78_fail_rtpc("P78_RTPC_OPEN_2_QUEUE=FAIL");
        return FALSE;
    }
    return TRUE;
}

static gboolean
p78_handle_rtpc_control_frame(guint16 request_id, const guint8 *body, guint body_len)
{
    P76Status status;

    if (request_id != 0)
        return FALSE;

    if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN) {
        status = p76_observe_device_open(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL");
            return TRUE;
        }
        p78_rtpc_device_open_observed = TRUE;
        printf("P78_RTPC_DEVICE_OPEN_OBSERVED=PASS\n");
        status = p76_generate_client_response_to_device_open(
            &p78_rtpc_runtime,
            p78_rtpc_client_response,
            &p78_rtpc_client_response_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_CLIENT_RESPONSE_GENERATION=FAIL");
            return TRUE;
        }
        p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_RESPONSES;
        if (!p12_queue_vip_frame(0, p78_rtpc_client_response, p78_rtpc_client_response_len, P78_TX_RTPC_CLIENT_RESPONSE))
            p78_fail_rtpc("P78_RTPC_CLIENT_RESPONSE_QUEUE=FAIL");
        return TRUE;
    }

    if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES) {
        status = p76_observe_device_response(&p78_rtpc_runtime, body, body_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_DEVICE_RESPONSE=FAIL");
            return TRUE;
        }
        p78_rtpc_device_response_count++;
        printf("P78_RTPC_DEVICE_RESPONSE_%u=PASS\n", (unsigned)p78_rtpc_device_response_count);
        fflush(stdout);
        if (p78_rtpc_device_response_count < 2)
            return TRUE;

        status = p76_generate_client_000a(&p78_rtpc_runtime, p78_rtpc_client_000a, p78_rtpc_client_000a_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_CLIENT_000A_GENERATION=FAIL");
            return TRUE;
        }
        status = p76_generate_client_001a(&p78_rtpc_runtime, p78_rtpc_client_001a, p78_rtpc_client_001a_len);
        if (status != P76_OK) {
            p78_fail_rtpc("P78_RTPC_CLIENT_001A_GENERATION=FAIL");
            return TRUE;
        }
        p78_rtpc_stage = P78_RTPC_CLIENT_MEDIA_TX;
        if (!p12_queue_vip_frame(v4_ctpp_channel_id, p78_rtpc_client_000a, p78_rtpc_client_000a_len, P78_TX_RTPC_CLIENT_000A)) {
            p78_fail_rtpc("P78_RTPC_CLIENT_000A_QUEUE=FAIL");
            return TRUE;
        }
        if (!p12_queue_vip_frame(v4_ctpp_channel_id, p78_rtpc_client_001a, p78_rtpc_client_001a_len, P78_TX_RTPC_CLIENT_001A))
            p78_fail_rtpc("P78_RTPC_CLIENT_001A_QUEUE=FAIL");
        return TRUE;
    }

    return FALSE;
}
/* === P78_RTPC_MEDIA_LIVE_STAGE_END === */
'''


REPLACEMENTS = (
    Replacement("tx_enum", TX_ENUM_ANCHOR, TX_ENUM_REPLACEMENT),
    Replacement("state", STATE_ANCHOR, STATE_REPLACEMENT),
    Replacement("ack_completion", ACK_COMPLETION_ANCHOR, ACK_COMPLETION_REPLACEMENT),
    Replacement("frame_hook", FRAME_HOOK_ANCHOR, FRAME_HOOK_REPLACEMENT),
    Replacement("p76_helper_tail", P78_HELPER_ANCHOR, P78_HELPER_REPLACEMENT),
)


def composed_p76(source: str) -> str:
    return add_p76_runtime(source)


def anchor_counts(source: str) -> dict[str, int]:
    candidate = composed_p76(source)
    return {replacement.name: candidate.count(replacement.old) for replacement in REPLACEMENTS}


def transform(source: str) -> str:
    out = composed_p76(source)
    for replacement in REPLACEMENTS:
        out = _replace_once(out, replacement.old, replacement.new)
    return out


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P78 RTPC MEDIA LIVE STAGE TRANSFORM ===",
            "P78_TRANSPORT_BINDING=REVIEW_REQUIRED",
            "P78_REVIEW_COMMIT_SHA_REQUIRED=true",
            f"P78_REVIEW_COMMIT_SHA_SET={'true' if P78_REVIEW_COMMIT_SHA else 'false'}",
            "P78_COMPOSES=P46_THROUGH_P76",
            "REGISTERED_CTPP_REUSED=true",
            "SECOND_CTPP_OPEN=false",
            "DEVICE_0008_ACK_GATE_PROVEN=false",
            "RTPC_CONTROL_REQUEST_ID=0",
            "RTPC_CTPP_MEDIA_REQUEST_ID=v4_ctpp_channel_id",
            "P78_MEDIA_OBSERVATION_WINDOW_MS=3000",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "LIVE_INVOCATIONS=0",
            "DOOR_ACTION_SENT=false",
            "=== END COMELIT P78 RTPC MEDIA LIVE STAGE TRANSFORM ===",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
