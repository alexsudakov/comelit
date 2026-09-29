#!/usr/bin/env python3
"""P116/R66: call-time Entrance Door single-message path.

R66 composes the shipped listener lineage through R64 and adds one narrowly
selected Entrance-only Door path for an already attached, active physical call.
The legacy standalone persistent-CTPP Door/Gate path is left byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r64_postcall_observability_transform as r64

BEGIN = "/* R66_CALL_TIME_DOOR_BEGIN */"
END = "/* R66_CALL_TIME_DOOR_END */"

_ENUM_ANCHOR = "    P12_TX_V4_DOOR_WRITE,\n"
_ENUM_REPLACEMENT = "    P12_TX_V4_DOOR_WRITE,\n    P12_TX_CALL_TIME_DOOR,\n"

_REGION_ANCHOR = "/* R54_CALL_ADOPTION_LISTENER_BEGIN */"

_REGION = r'''/* R66_CALL_TIME_DOOR_BEGIN */
#define R66_CALL_TIME_DOOR_PACKET_LEN 48u
#define R66_CALL_TIME_DOOR_INNER_LEN 13u
#define R66_CALL_TIME_DOOR_OPCODE 0x002Du
#define R66_CALL_TIME_DOOR_RELAY_ENTRANCE 1u

static unsigned g_r66_call_time_door_sequence_before = 0u;
static unsigned g_r66_call_time_door_sequence_after = 0u;
static unsigned g_r66_call_time_door_generation = 0u;
static gboolean g_r66_call_time_door_ack_observed = FALSE;
static gboolean g_r66_call_time_door_waiting_ack = FALSE;
static gboolean g_r66_call_time_door_selected = FALSE;

static void v4_door_set_deadline(void);
static gboolean v4_door_settle_cb(gpointer data);
static void v4_door_emit_result(const char *result);
static void v4_door_reset(void);

static void
r66_write_padded_ascii(unsigned char *out, const char *value, unsigned max_len)
{
    unsigned i;
    memset(out, 0, max_len);
    if (!value)
        return;
    for (i = 0; i < max_len && value[i] != '\0'; i++)
        out[i] = (unsigned char)value[i];
}

static int
r66_serialize_call_time_door_packet(
    unsigned char out[R66_CALL_TIME_DOOR_PACKET_LEN],
    const R35AttachedMediaSession *s)
{
    if (!out || !s || !r35_call_ready(s))
        return 0;

    memset(out, 0, R66_CALL_TIME_DOOR_PACKET_LEN);
    out[0] = (unsigned char)R35_CTP_FLAG_DATA;
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, s->call_ctp_connection & 0xffffu);
    out[4] = (unsigned char)(s->call_sequence & 0xffu);
    out[5] = (unsigned char)(s->call_ack & 0xffu);
    r35_write_be16(out + 6, R66_CALL_TIME_DOOR_INNER_LEN);
    r35_write_be16(out + 8, R66_CALL_TIME_DOOR_OPCODE);
    memcpy(out + 10, s->dest_logical, R35_CTP_LOGADDR_LEN);
    out[20] = (unsigned char)R66_CALL_TIME_DOOR_RELAY_ENTRANCE;
    out[21] = 0u;
    out[22] = 0u;
    out[23] = 0u;
    out[24] = 0xffu;
    out[25] = 0xffu;
    out[26] = 0xffu;
    out[27] = 0xffu;
    memcpy(out + 28, s->source_logical, R35_CTP_LOGADDR_LEN);
    r66_write_padded_ascii(out + 38, V4_APT_ADDRESS, R35_CTP_LOGADDR_LEN);

    if (R66_CALL_TIME_DOOR_PACKET_LEN != 48u ||
        r35_read_be16(out + 6) != R66_CALL_TIME_DOOR_INNER_LEN ||
        r35_read_be16(out + 8) != R66_CALL_TIME_DOOR_OPCODE ||
        out[20] != R66_CALL_TIME_DOOR_RELAY_ENTRANCE ||
        out[24] != 0xffu || out[25] != 0xffu ||
        out[26] != 0xffu || out[27] != 0xffu) {
        memset(out, 0, R66_CALL_TIME_DOOR_PACKET_LEN);
        return 0;
    }

    return 1;
}

static gboolean
r66_call_time_door_eligible(void)
{
    return v4_door_target == V4_DOOR_TARGET_ENTRANCE &&
        v4_listener_ready &&
        v4_registered &&
        v4_ctpp_channel_id != 0 &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        v4_door_stage == V4_DOOR_IDLE &&
        !p12_tx_pending &&
        r35_call_ready(&g_r35_session) &&
        r42_media_stage == R42_MEDIA_ACTIVE;
}

static gboolean
r66_call_time_door_queue_ready(void)
{
    return g_r66_call_time_door_selected &&
        v4_door_target == V4_DOOR_TARGET_ENTRANCE &&
        v4_listener_ready &&
        v4_registered &&
        v4_ctpp_channel_id != 0 &&
        p12_stage == P12_STAGE_V4_LISTEN_RING &&
        v4_door_stage == V4_DOOR_SENDING &&
        !p12_tx_pending &&
        r35_call_ready(&g_r35_session) &&
        r42_media_stage == R42_MEDIA_ACTIVE;
}

static gboolean
r66_queue_call_time_door(void)
{
    unsigned char packet[R66_CALL_TIME_DOOR_PACKET_LEN];
    gboolean queued;

    if (!r66_call_time_door_queue_ready())
        return FALSE;
    if (!r66_serialize_call_time_door_packet(packet, &g_r35_session))
        return FALSE;

    g_r66_call_time_door_generation = g_r35_session.call_generation;
    g_r66_call_time_door_sequence_before = g_r35_session.call_sequence & 0xffu;
    g_r66_call_time_door_sequence_after =
        (g_r66_call_time_door_sequence_before + 1u) & 0xffu;
    g_r66_call_time_door_ack_observed = FALSE;
    g_r66_call_time_door_waiting_ack = FALSE;

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        packet,
        R66_CALL_TIME_DOOR_PACKET_LEN,
        P12_TX_CALL_TIME_DOOR);
    memset(packet, 0, sizeof(packet));
    if (!queued) {
        g_r66_call_time_door_selected = FALSE;
        return FALSE;
    }

    g_r66_call_time_door_selected = FALSE;
    v4_door_send_started = TRUE;
    printf("V4_DOOR_PATH=CALL_TIME_SINGLE\n");
    printf("V4_CALL_TIME_DOOR_QUEUED=true\n");
    printf("CALL_GENERATION=%u\n", g_r66_call_time_door_generation);
    printf("CALL_SEQUENCE_BEFORE=%u\n", g_r66_call_time_door_sequence_before);
    fflush(stdout);
    return p12_flush_tx();
}

static gboolean
r66_call_time_door_note_control_response(
    guint32 request_id,
    const guint8 *body,
    guint body_len)
{
    guint16 prefix;
    guint16 action;

    if (!g_r66_call_time_door_waiting_ack ||
        v4_door_stage != V4_DOOR_WAIT_SETTLE ||
        request_id != (guint32)v4_ctpp_channel_id ||
        !body ||
        body_len < 8)
        return FALSE;

    prefix = read_le16(body + 0);
    action = (((guint16)body[6]) << 8) | ((guint16)body[7]);
    if (prefix == 0x1800u && action == 0x0000u) {
        g_r66_call_time_door_ack_observed = TRUE;
        return TRUE;
    }

    return FALSE;
}

static void
r66_call_time_door_emit_settle_result(void)
{
    printf("CALL_TIME_DOOR_ACK_OBSERVED=%s\n",
        g_r66_call_time_door_ack_observed ? "true" : "false");
    printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\n");
    g_r66_call_time_door_waiting_ack = FALSE;
    v4_door_emit_result("UNKNOWN_OUTCOME");
    v4_door_reset();
    fflush(stdout);
}

static gboolean
r66_call_time_door_tx_completed(void)
{
    gboolean sequence_committed = FALSE;

    if (g_r35_session.call_generation == g_r66_call_time_door_generation &&
        r35_call_ready(&g_r35_session) &&
        (g_r35_session.call_sequence & 0xffu) ==
            g_r66_call_time_door_sequence_before) {
        g_r35_session.call_sequence =
            g_r66_call_time_door_sequence_after & 0xffu;
        sequence_committed = TRUE;
    } else {
        printf("CALL_TIME_DOOR_STALE_GENERATION=true\n");
    }

    v4_door_writes_sent = 1;
    v4_door_stage = V4_DOOR_WAIT_SETTLE;
    g_r66_call_time_door_waiting_ack = TRUE;
    v4_door_set_deadline();
    printf("V4_CALL_TIME_DOOR_SENT=true\n");
    printf("V4_CALL_TIME_DOOR_WRITE_COUNT=1\n");
    printf("CALL_TIME_DOOR_SEQUENCE_COMMITTED=%s\n",
        sequence_committed ? "true" : "false");
    printf("CALL_SEQUENCE_AFTER=%u\n", g_r35_session.call_sequence & 0xffu);
    fflush(stdout);
    if (g_timeout_add(V4_DOOR_SETTLE_MS, v4_door_settle_cb, NULL) == 0) {
        r66_call_time_door_emit_settle_result();
        return FALSE;
    }
    return TRUE;
}
/* R66_CALL_TIME_DOOR_END */'''

_TX_CASE_ANCHOR = """        case P12_TX_V4_DOOR_WRITE:
            printf(
                "V4_DOOR_OPERATION_WRITE_%u_SENT=true\\n","""

_TX_CASE_INSERT = r'''        case P12_TX_CALL_TIME_DOOR:
            if (!r66_call_time_door_tx_completed()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

'''

_SETTLE_ANCHOR = """    printf("V4_DOOR_SETTLE_COMPLETE=true\\n");
    printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\\n");"""

_SETTLE_REPLACEMENT = """    printf("V4_DOOR_SETTLE_COMPLETE=true\\n");
    if (g_r66_call_time_door_waiting_ack) {
        r66_call_time_door_emit_settle_result();
        return G_SOURCE_REMOVE;
    }
    printf("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\\n");"""

_POST_UAUT_BODY_ANCHOR = """        const guint8 *body =
            post_ack_capture + 8;



"""

_POST_UAUT_ACK_REPLACEMENT = """        const guint8 *body =
            post_ack_capture + 8;

        if (r66_call_time_door_note_control_response(request_id, body, body_len)) {
            p12_consume_post_ack(frame_len);
            continue;
        }


"""

_DOOR_TIMEOUT_ANCHOR = """    if (v4_door_stage != V4_DOOR_IDLE &&
        v4_door_deadline_us > 0 &&
        g_get_monotonic_time() > v4_door_deadline_us) {

        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {"""

_DOOR_TIMEOUT_REPLACEMENT = """    if (v4_door_stage != V4_DOOR_IDLE &&
        v4_door_deadline_us > 0 &&
        g_get_monotonic_time() > v4_door_deadline_us) {

        if (g_r66_call_time_door_waiting_ack) {
            r66_call_time_door_emit_settle_result();
            return G_SOURCE_REMOVE;
        }

        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );

        if (v4_door_send_started) {"""

_TICK_ANCHOR = """    printf("V4_DOOR_COMMAND_ACCEPTED=true\\n");
    printf("V4_DOOR_TARGET=%s\\n", v4_door_target_name(v4_door_target));
    printf("V4_DOOR_EXISTING_CTPP_REUSED=true\\n");"""

_TICK_REPLACEMENT = """    g_r66_call_time_door_selected = r66_call_time_door_eligible();
    printf("V4_DOOR_COMMAND_ACCEPTED=true\\n");
    printf("V4_DOOR_TARGET=%s\\n", v4_door_target_name(v4_door_target));
    if (g_r66_call_time_door_selected)
        printf("V4_CALL_TIME_DOOR_COMMAND_ACCEPTED=true\\n");
    printf("V4_DOOR_EXISTING_CTPP_REUSED=true\\n");"""

_QUEUE_ANCHOR = """    if (!v4_door_queue_write(1)) {
        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );"""

_QUEUE_REPLACEMENT = """    if (g_r66_call_time_door_selected) {
        if (!r66_queue_call_time_door()) {
            v4_door_emit_result(
                v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
            );

            if (v4_door_send_started) {
                p116_record_failure(P116_FAILURE_DOOR_WRITE, P116_PHASE_LISTENER_READY);
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
                return G_SOURCE_REMOVE;
            }

            v4_door_reset();
        }

        return G_SOURCE_CONTINUE;
    }

    if (!v4_door_queue_write(1)) {
        v4_door_emit_result(
            v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE"
        );"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R66_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("R66_REAPPLY_GATE=FAIL")

    candidate = r64.transform(source)
    candidate = _replace_once(candidate, _ENUM_ANCHOR, _ENUM_REPLACEMENT, "ENUM")
    candidate = _replace_once(
        candidate,
        _REGION_ANCHOR,
        _REGION + "\n\n" + _REGION_ANCHOR,
        "REGION",
    )
    candidate = _replace_once(
        candidate,
        _TX_CASE_ANCHOR,
        _TX_CASE_INSERT + _TX_CASE_ANCHOR,
        "TX_CASE",
    )
    candidate = _replace_once(candidate, _SETTLE_ANCHOR, _SETTLE_REPLACEMENT, "SETTLE")
    candidate = _replace_once(
        candidate,
        _POST_UAUT_BODY_ANCHOR,
        _POST_UAUT_ACK_REPLACEMENT,
        "POST_UAUT_ACK",
    )
    candidate = _replace_once(
        candidate,
        _DOOR_TIMEOUT_ANCHOR,
        _DOOR_TIMEOUT_REPLACEMENT,
        "DOOR_TIMEOUT",
    )
    candidate = _replace_once(candidate, _TICK_ANCHOR, _TICK_REPLACEMENT, "TICK")
    candidate = _replace_once(candidate, _QUEUE_ANCHOR, _QUEUE_REPLACEMENT, "QUEUE")

    for marker in (
        BEGIN,
        END,
        "P12_TX_CALL_TIME_DOOR",
        "r66_serialize_call_time_door_packet",
        "R66_CALL_TIME_DOOR_PACKET_LEN 48u",
        "V4_DOOR_PATH=CALL_TIME_SINGLE",
        "V4_CALL_TIME_DOOR_WRITE_COUNT=1",
        "CALL_TIME_DOOR_ACK_OBSERVED=%s",
        "r66_call_time_door_note_control_response",
        "r66_call_time_door_queue_ready",
        "g_r66_call_time_door_selected",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R66_FINAL_GATE=FAIL missing={marker}")

    if candidate.count("P12_TX_CALL_TIME_DOOR") != 3:
        raise RuntimeError("R66_TX_KIND_COUNT_GATE=FAIL")
    if candidate.count("P12_TX_V4_DOOR_WRITE") < 2:
        raise RuntimeError("R66_STANDALONE_TX_KIND_GATE=FAIL")
    if "V4_DOOR_TARGET_GATE" not in candidate or "V4_DOOR_TARGET_ENTRANCE" not in candidate:
        raise RuntimeError("R66_TARGET_ENUM_GATE=FAIL")
    if "v4_sequence_seed" not in candidate:
        raise RuntimeError("R66_BASE_SEQUENCE_SEED_VISIBILITY_GATE=FAIL")
    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    if "v4_sequence_seed" in region:
        raise RuntimeError("R66_NO_LEGACY_SEQUENCE_SEED_GATE=FAIL")
    for forbidden in (
        "P12_TX_V4_OPEN_CTPP",
        "P12_TX_V4_OPEN_CSPB",
        "entrance_self_activation",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
    ):
        if forbidden in region:
            raise RuntimeError(f"R66_NO_SECOND_SESSION_GATE=FAIL forbidden={forbidden}")
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
    candidate = transform(source_path.read_text(encoding="utf-8"))

    if args.sha256:
        print(hashlib.sha256(candidate.encode("utf-8")).hexdigest())
        return 0
    if args.output is None:
        parser.error("--output is required unless --sha256 is used")

    args.output.write_text(candidate, encoding="utf-8")
    print("R66_CALL_TIME_DOOR_TRANSFORM=PASS")
    print(
        "R66_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    )
    print("R66_CALL_TIME_DOOR_PACKET_LEN=48")
    print("R66_STANDALONE_DOOR_UNCHANGED=true")
    print("R66_GATE_CALL_TIME_PROMOTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
