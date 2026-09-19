#!/usr/bin/env python3
"""P116/R42: production-candidate attached inbound media runtime overlay.

Input is the already-R37-augmented persistent listener source. R42 closes the
R37 media-channel placeholder using the physical official-app call evidence:

* the call CTP direction transform is peer_connection XOR 0x8000;
* the media id in MEDIAREQ26 is the id of the Viper RTPC RX channel opened
  immediately before the request;
* the observed TUNNEL OPEN body uses flags 0x3a, max RTP 0xffff, profile
  800/480/320/240 and profile byte 0x10;
* STOP uses action 0x94, flags 0x02, the same media channel id and zero profile.

The helper owns its own Viper tunnel, so it uses the already-proven generic
Viper allocator/open contract (P73/P74): runtime low15 allocation, tag RTPC,
transport 1. No capture channel id is reused as a constant.

R42 intercepts a video CAPABILITIES trigger before R36. The old R36 placeholder
therefore cannot transmit for a call handled by R42. There is one attempt per
call generation and no retry. Door/Gate/self-activation are untouched.
"""
from __future__ import annotations

import argparse
from pathlib import Path

BEGIN = "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */"
END = "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */"
TRIGGER_BEGIN = "/* R42_ATTACHED_TRIGGER_BEGIN */"
TRIGGER_END = "/* R42_ATTACHED_TRIGGER_END */"

_ENUM_ANCHOR = """    P12_TX_R35_MEDIA_OPEN,
    P12_TX_R35_MEDIA_STOP
} P12TxKind;"""
_ENUM_REPLACEMENT = """    P12_TX_R35_MEDIA_OPEN,
    P12_TX_R35_MEDIA_STOP,

    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE
} P12TxKind;"""

_FORWARD_ANCHOR = """static gboolean
p12_flush_tx(void);"""

RUNTIME = r'''
/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */
typedef enum {
    R42_MEDIA_IDLE = 0,
    R42_MEDIA_CHANNEL_OPEN_TX,
    R42_MEDIAREQ_OPEN_TX,
    R42_MEDIA_ACTIVE,
    R42_MEDIAREQ_STOP_TX,
    R42_MEDIA_CHANNEL_CLOSE_TX,
    R42_MEDIA_CHANNEL_CLOSE_WAIT,
    R42_MEDIA_CLOSED,
    R42_MEDIA_FAILED
} R42AttachedMediaStage;

static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;
static guint16 r42_media_channel_id = 0;
static unsigned r42_attempted_call_generation = 0;

static gboolean
r42_queue_media_channel_open(void)
{
    guint8 body[15];
    guint16 seed;
    guint16 channel_id;

    if (!r35_call_ready(&g_r35_session) ||
        r42_attempted_call_generation == g_r35_session.call_generation)
        return FALSE;

    r42_attempted_call_generation = g_r35_session.call_generation;
    seed = (guint16)(g_random_int() & 0x7fffu);
    channel_id = v4_allocate_channel_id(seed);
    if (channel_id == 0u)
        return FALSE;

    if (r35_allocate_media_rx_channel(
            &g_r35_session,
            (unsigned)channel_id,
            (unsigned)channel_id) != R35_OK)
        return FALSE;

    r42_media_channel_id = channel_id;
    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "RTPC", 4);
    write_le16(body + 12, channel_id);
    body[14] = 1;

    r42_media_stage = R42_MEDIA_CHANNEL_OPEN_TX;
    if (!p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_R42_MEDIA_CHANNEL_OPEN)) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    printf("R42_MEDIA_CHANNEL_ALLOCATED=true\n");
    printf("R42_CAPTURE_CHANNEL_LITERAL_USED=false\n");
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r42_queue_mediareq_open(void)
{
    R35MediaRequestSources src;
    R35Result rc;

    if (r42_media_stage != R42_MEDIA_CHANNEL_OPEN_TX ||
        r42_media_channel_id == 0u)
        return FALSE;

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

    r42_media_stage = R42_MEDIAREQ_OPEN_TX;
    rc = r35_send_open(&g_r35_session, &src, 0);
    if (rc != R35_OK ||
        !p12_tx_pending ||
        p12_tx_kind != P12_TX_R35_MEDIA_OPEN) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }

    printf("R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED\n");
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r42_activate_after_mediareq_open(void)
{
    R35Result rc;
    if (r42_media_stage != R42_MEDIAREQ_OPEN_TX ||
        r42_media_channel_id == 0u)
        return FALSE;
    rc = r35_enable_rtp(&g_r35_session, (unsigned)r42_media_channel_id);
    if (rc != R35_OK) {
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    r42_media_stage = R42_MEDIA_ACTIVE;
    printf("R42_ATTACHED_MEDIA_ACTIVE=true\n");
    printf("R42_LISTENER_PAUSED=false\n");
    printf("R42_SECOND_P2P_SESSION=false\n");
    fflush(stdout);
    return TRUE;
}

static gboolean
r42_queue_media_channel_close(void)
{
    if (r42_media_channel_id == 0u)
        return FALSE;
    r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_TX;
    return p12_queue_close_channel(
        r42_media_channel_id,
        P12_TX_R42_MEDIA_CHANNEL_CLOSE
    );
}

static void
r42_finish_media_channel_close(void)
{
    r42_media_stage = R42_MEDIA_CLOSED;
    r42_media_channel_id = 0u;
    printf("R42_MEDIA_CHANNEL_CLOSED=true\n");
    fflush(stdout);
}
/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */
'''

_TX_TAIL_ANCHOR = """        default:
            break;
    }

    if (
        p12_stage =="""
_TX_TAIL_REPLACEMENT = r'''        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\n");
            fflush(stdout);
            if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\n");
                fflush(stdout);
            }
            break;

        case P12_TX_R35_MEDIA_OPEN:
            if (r42_media_stage == R42_MEDIAREQ_OPEN_TX) {
                if (!r42_activate_after_mediareq_open()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_ATTACHED_MEDIA_ACTIVATE=FAIL\n");
                    fflush(stdout);
                }
            }
            break;

        case P12_TX_R35_MEDIA_STOP:
            if (r42_media_channel_id != 0u) {
                r42_media_stage = R42_MEDIAREQ_STOP_TX;
                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\n");
                fflush(stdout);
                if (!r42_queue_media_channel_close()) {
                    r42_media_stage = R42_MEDIA_FAILED;
                    printf("R42_MEDIA_CHANNEL_CLOSE_QUEUE=FAIL\n");
                    fflush(stdout);
                }
            }
            break;

        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\n");
            fflush(stdout);
            break;

        default:
            break;
    }

    if (
        p12_stage =='''

_TRIGGER_ANCHOR = """            /* R36_WIRING_TRIGGER_BEGIN */"""
_TRIGGER_REPLACEMENT = r'''            /* R42_ATTACHED_TRIGGER_BEGIN */
            if (r42_media_stage == R42_MEDIA_CHANNEL_CLOSE_WAIT) {
                guint16 r42_response_channel = 0;
                guint16 r42_response_word = 0xffff;
                if (request_id == 0 &&
                    p12_parse_control_response(
                        body,
                        body_len,
                        4,
                        r42_media_channel_id,
                        FALSE,
                        &r42_response_channel,
                        &r42_response_word) &&
                    r42_response_word == 0) {
                    r42_finish_media_channel_close();
                    p12_consume_post_ack(frame_len);
                    continue;
                }
            }

            {
                R35CtpEnvelopeView r42_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r42_view) &&
                    r36_is_capabilities_for_current_call(
                        &g_r35_session, &r42_view) &&
                    r36_capabilities_video_requested(&r42_view)) {

                    gboolean r42_ok = r42_queue_media_channel_open();
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\n");
                    printf(
                        "R42_ATTACHED_TRIGGER_RESULT=%s\n",
                        r42_ok ? "CHANNEL_OPEN_SENT" : "REJECTED"
                    );
                    printf("R42_AUTOMATIC_RETRY=false\n");
                    fflush(stdout);

                    p12_consume_post_ack(frame_len);
                    continue;
                }
            }
            /* R42_ATTACHED_TRIGGER_END */

            /* R36_WIRING_TRIGGER_BEGIN */'''

_R37_WIRING_BEGIN = """/* R37_WIRING_BEGIN */"""
_R37_WIRING_BEGIN_REPLACEMENT = """/* R37_WIRING_BEGIN */
static gboolean
p12_flush_tx(void);
"""

_STOP_CALLS = (
    (
        r"""    rc = r37_bounded_stop_request(&g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
    printf("BOUNDED_STOP_REQUEST_RECEIVED=%u\n", g_r37_telemetry.bounded_stop_request_received_count);""",
        r"""    rc = r37_bounded_stop_request(&g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
    (void)p12_flush_tx();
    printf("BOUNDED_STOP_REQUEST_RECEIVED=%u\n", g_r37_telemetry.bounded_stop_request_received_count);""",
    ),
    (
        r"""                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);

                        printf("R37_CAPABILITY_CLEARED_OBSERVED=true\n");""",
        r"""                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
                        (void)p12_flush_tx();

                        printf("R37_CAPABILITY_CLEARED_OBSERVED=true\n");""",
    ),
    (
        r"""                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);

                        printf("R37_REMOTE_RELEASE_OBSERVED=true\n");""",
        r"""                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
                        (void)p12_flush_tx();

                        printf("R37_REMOTE_RELEASE_OBSERVED=true\n");""",
    ),
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(r37_source: str) -> str:
    if BEGIN in r37_source:
        raise RuntimeError("R42_REAPPLY_GATE=FAIL")
    if "R37_LIVE_READINESS_BEGIN" not in r37_source:
        raise RuntimeError("R42_REQUIRES_R37=FAIL")

    out = _replace_once(
        r37_source, _ENUM_ANCHOR, _ENUM_REPLACEMENT, "R42_TX_ENUM"
    )
    # Insert the R42 runtime before adding the extra early flush declaration:
    # the R37 source contains one canonical p12_flush_tx declaration here.
    out = _replace_once(
        out,
        _FORWARD_ANCHOR,
        _FORWARD_ANCHOR
        + "\n\nstatic gboolean\np12_queue_close_channel(\n"
        + "    guint16 channel_id,\n    P12TxKind kind);\n\n"
        + RUNTIME,
        "R42_RUNTIME",
    )
    out = _replace_once(
        out,
        _R37_WIRING_BEGIN,
        _R37_WIRING_BEGIN_REPLACEMENT,
        "R42_EARLY_FLUSH_DECL",
    )
    out = _replace_once(
        out, _TX_TAIL_ANCHOR, _TX_TAIL_REPLACEMENT, "R42_TX_COMPLETION"
    )
    out = _replace_once(
        out, _TRIGGER_ANCHOR, _TRIGGER_REPLACEMENT, "R42_TRIGGER"
    )
    for idx, (old, new) in enumerate(_STOP_CALLS, start=1):
        out = _replace_once(out, old, new, f"R42_STOP_FLUSH_{idx}")

    for marker in (BEGIN, END, TRIGGER_BEGIN, TRIGGER_END):
        if out.count(marker) != 1:
            raise RuntimeError(f"R42_MARKER_GATE=FAIL marker={marker}")

    # Safety/evidence gates.
    r42 = out.split(BEGIN, 1)[1].split(END, 1)[0]
    required = (
        '"RTPC"',
        "P12_TX_R42_MEDIA_CHANNEL_OPEN",
        "v4_allocate_channel_id",
        "0xffffu",
        "0x0320u",
        "0x01e0u",
        "0x0140u",
        "0x00f0u",
        "0x10u",
        "r35_send_open",
        "r35_enable_rtp",
        "p12_queue_close_channel",
        "p12_parse_control_response",
        "R42_MEDIA_CHANNEL_CLOSE_WAIT",
    )
    for needle in required:
        if needle not in r42:
            raise RuntimeError(f"R42_REQUIRED_GATE=FAIL needle={needle}")

    trigger = out.split(TRIGGER_BEGIN, 1)[1].split(TRIGGER_END, 1)[0]
    if "continue;" not in trigger:
        raise RuntimeError("R42_R36_PLACEHOLDER_BYPASS_GATE=FAIL")
    if "r42_queue_media_channel_open" not in trigger:
        raise RuntimeError("R42_TRIGGER_CALL_GATE=FAIL")

    forbidden = (
        "SIGUSR1",
        "P12_TX_V4_DOOR_WRITE",
        "entrance_self_activation",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "0x0C4A",
        "0x4A5A",
        "0xCA5A",
        "g_timeout_add",
        "retry",
    )
    for needle in forbidden:
        if needle.lower() in r42.lower():
            raise RuntimeError(f"R42_FORBIDDEN_GATE=FAIL needle={needle}")

    return out


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R42 ATTACHED INBOUND MEDIA RUNTIME TRANSFORM ===",
            "MEDIA_CHANNEL_SOURCE=RUNTIME_VIPER_ALLOCATOR",
            "MEDIA_CHANNEL_CAPTURE_LITERAL_USED=false",
            "MEDIA_CHANNEL_TAG=RTPC",
            "MEDIA_CHANNEL_TRANSPORT=1",
            "MEDIAREQ26_PROFILE=CAPTURE_VALIDATED_800_480_320_240_16",
            "CALL_CTP_DIRECTION=XOR_0x8000_INHERITED_R35",
            "ONE_ATTEMPT_PER_CALL_GENERATION=true",
            "AUTOMATIC_RETRY=false",
            "R36_PLACEHOLDER_BYPASSED=true",
            "SELF_ACTIVATION_USED=false",
            "LISTENER_PAUSE_REQUIRED=false",
            "DOOR_ACTION_SENT=false",
            "GATE_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R42 ATTACHED INBOUND MEDIA RUNTIME TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required")
    args.output.write_text(
        transform(args.source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    print("R42_ATTACHED_MEDIA_TRANSFORM=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("GATE_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
