#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "f0f051a54553614f092ac0e51858b5448abe94e72360b25acd7c90fe2c0decfe"
PAYLOAD_SHA256 = "0d0159f9cc562c1c67bc362b192a30d3fabd634b2b92c3a96d8f318ecd842832"
TARGET_FP = "832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce"
UCFG_SHA256 = "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7"
EXPECTED_LENGTHS = (52, 32, 32, 48, 32, 32)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def c_array(name: str, body: bytes) -> str:
    rows: list[str] = []
    for start in range(0, len(body), 12):
        chunk = body[start:start + 12]
        rows.append("    " + ", ".join(f"0x{b:02x}" for b in chunk))
    return f"static const guint8 {name}[] = {{\n" + ",\n".join(rows) + "\n};"


def payload_bodies(path: Path) -> tuple[bytes, ...]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PAYLOAD_SHA256:
        raise RuntimeError("Door payload SHA-256 mismatch")
    data = json.loads(raw)
    if data.get("schema") != 1 or data.get("target_index") != 0:
        raise RuntimeError("Door payload identity mismatch")
    if data.get("target_fingerprint") != TARGET_FP:
        raise RuntimeError("Door target fingerprint mismatch")
    if data.get("ucfg_sha256") != UCFG_SHA256:
        raise RuntimeError("Door UCFG fingerprint mismatch")
    bodies = tuple(bytes.fromhex(item["hex"]) for item in data["bodies"])
    if tuple(len(body) for body in bodies) != EXPECTED_LENGTHS:
        raise RuntimeError("Door body lengths mismatch")
    for item, body in zip(data["bodies"], bodies):
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise RuntimeError("Door body SHA-256 mismatch")
    return bodies


def globals_block(bodies: tuple[bytes, ...]) -> str:
    arrays = "\n\n".join(
        c_array(f"v4_door_body_{index}", body)
        for index, body in enumerate(bodies, 1)
    )
    lengths = ", ".join(str(len(body)) for body in bodies)
    return f'''

typedef enum {{
    V4_DOOR_IDLE = 0,
    V4_DOOR_WAIT_OPEN,
    V4_DOOR_WAIT_WRITE,
    V4_DOOR_WAIT_CLOSE
}} V4DoorStage;

typedef enum {{
    V4_DOOR_FRAME_NOT_CONSUMED = 0,
    V4_DOOR_FRAME_CONSUMED,
    V4_DOOR_FRAME_FAIL
}} V4DoorFrameResult;

#define V4_DOOR_REQUESTED_CHANNEL_ID 7449
#define V4_DOOR_STEP_TIMEOUT_SECONDS 6

static V4DoorStage v4_door_stage = V4_DOOR_IDLE;
static guint16 v4_door_requested_channel_id = 0;
static guint16 v4_door_channel_id = 0;
static guint v4_door_write_index = 0;
static guint v4_door_writes_acked = 0;
static gint64 v4_door_deadline_us = 0;
static gboolean v4_door_send_started = FALSE;
static volatile sig_atomic_t v4_door_signal_pending = 0;

{arrays}

static const guint v4_door_body_len[] = {{ {lengths} }};
static const guint v4_door_write_count = 6;

static void v4_door_set_deadline(void);
'''


def helpers_block() -> str:
    return r'''
static void
v4_door_set_deadline(void)
{
    v4_door_deadline_us =
        g_get_monotonic_time() +
        ((gint64)V4_DOOR_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
}


static void
v4_door_reset(void)
{
    v4_door_stage = V4_DOOR_IDLE;
    v4_door_requested_channel_id = 0;
    v4_door_channel_id = 0;
    v4_door_write_index = 0;
    v4_door_writes_acked = 0;
    v4_door_deadline_us = 0;
    v4_door_send_started = FALSE;
}


static void
v4_door_emit_result(const gchar *state)
{
    printf("V4_DOOR_RESULT=%s\n", state);
    printf("V4_DOOR_WRITE_COUNT=%u\n", (unsigned)v4_door_writes_acked);
    printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    fflush(stdout);
}


static void
v4_door_signal_handler(int signum)
{
    if (signum == SIGUSR1)
        v4_door_signal_pending = 1;
}


static gboolean
v4_door_queue_open(void)
{
    guint16 candidate = V4_DOOR_REQUESTED_CHANNEL_ID;
    while (candidate == echo_channel_id ||
           candidate == uaut_channel_id ||
           candidate == ucfg_channel_id ||
           candidate == v4_ctpp_channel_id ||
           candidate == v4_cspb_channel_id) {
        candidate++;
    }
    v4_door_requested_channel_id = candidate;

    guint8 body[15];
    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "CTPP", 4);
    write_le16(body + 12, candidate);

    gboolean queued = p12_queue_vip_frame(
        0, body, sizeof(body), P12_TX_V4_DOOR_OPEN_CTPP
    );
    memset(body, 0, sizeof(body));
    if (!queued)
        return FALSE;
    v4_door_send_started = TRUE;
    return p12_flush_tx();
}


static gboolean
v4_door_queue_write(guint index)
{
    if (index == 0 || index > v4_door_write_count)
        return FALSE;

    const guint8 *body = v4_door_body_1;
    switch (index) {
        case 2: body = v4_door_body_2; break;
        case 3: body = v4_door_body_3; break;
        case 4: body = v4_door_body_4; break;
        case 5: body = v4_door_body_5; break;
        case 6: body = v4_door_body_6; break;
        default: break;
    }

    v4_door_write_index = index;
    gboolean queued = p12_queue_vip_frame(
        v4_door_channel_id,
        body,
        v4_door_body_len[index - 1],
        P12_TX_V4_DOOR_WRITE
    );
    if (!queued)
        return FALSE;
    v4_door_send_started = TRUE;
    return p12_flush_tx();
}


static gboolean
v4_door_queue_close(void)
{
    guint8 body[10];
    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0x01EF);
    write_le16(body + 2, 3);
    write_le32(body + 4, 2);
    write_le16(body + 8, v4_door_channel_id);

    gboolean queued = p12_queue_vip_frame(
        0, body, sizeof(body), P12_TX_V4_DOOR_CLOSE_CTPP
    );
    memset(body, 0, sizeof(body));
    if (!queued)
        return FALSE;
    v4_door_send_started = TRUE;
    return p12_flush_tx();
}


static V4DoorFrameResult
v4_door_process_frame(guint32 request_id, const guint8 *body, guint body_len)
{
    if (v4_door_stage == V4_DOOR_IDLE)
        return V4_DOOR_FRAME_NOT_CONSUMED;

    if (v4_door_stage == V4_DOOR_WAIT_OPEN) {
        if (request_id != 0 || body_len != 12 ||
            read_le16(body + 0) != 0xABCD || read_le16(body + 2) != 2) {
            return V4_DOOR_FRAME_NOT_CONSUMED;
        }

        guint16 response_channel = 0;
        guint16 response_word = 0xffff;
        if (!p12_parse_control_response(
                body, body_len, 2, v4_door_requested_channel_id, TRUE,
                &response_channel, &response_word)) {
            v4_door_emit_result("UNKNOWN_OUTCOME");
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return V4_DOOR_FRAME_FAIL;
        }
        if (response_word != 0) {
            v4_door_emit_result("REJECTED");
            v4_door_reset();
            return V4_DOOR_FRAME_CONSUMED;
        }

        v4_door_channel_id = response_channel;
        printf("V4_DOOR_CTPP_OPEN_RESPONSE=PASS\n");
        fflush(stdout);
        if (!v4_door_queue_write(1)) {
            v4_door_emit_result("UNKNOWN_OUTCOME");
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return V4_DOOR_FRAME_FAIL;
        }
        return V4_DOOR_FRAME_CONSUMED;
    }

    if (v4_door_stage == V4_DOOR_WAIT_WRITE) {
        if (request_id != v4_door_channel_id)
            return V4_DOOR_FRAME_NOT_CONSUMED;

        v4_door_writes_acked = v4_door_write_index;
        printf("V4_DOOR_WRITE_%u_ACKED=true\n", (unsigned)v4_door_write_index);
        fflush(stdout);

        if (v4_door_write_index < v4_door_write_count) {
            if (!v4_door_queue_write(v4_door_write_index + 1)) {
                v4_door_emit_result("UNKNOWN_OUTCOME");
                failed = TRUE;
                if (loop) g_main_loop_quit(loop);
                return V4_DOOR_FRAME_FAIL;
            }
        } else if (!v4_door_queue_close()) {
            v4_door_emit_result("UNKNOWN_OUTCOME");
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return V4_DOOR_FRAME_FAIL;
        }
        return V4_DOOR_FRAME_CONSUMED;
    }

    if (v4_door_stage == V4_DOOR_WAIT_CLOSE) {
        if (request_id != 0 || body_len != 12 ||
            read_le16(body + 0) != 0x01EF || read_le16(body + 2) != 4 ||
            read_le16(body + 8) != v4_door_channel_id) {
            return V4_DOOR_FRAME_NOT_CONSUMED;
        }

        guint16 response_channel = 0;
        guint16 response_word = 0xffff;
        if (!p12_parse_control_response(
                body, body_len, 4, v4_door_channel_id, FALSE,
                &response_channel, &response_word) || response_word != 0) {
            v4_door_emit_result("UNKNOWN_OUTCOME");
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return V4_DOOR_FRAME_FAIL;
        }

        printf("V4_DOOR_CTPP_CLOSE_RESPONSE=PASS\n");
        v4_door_emit_result("ACKED");
        v4_door_reset();
        return V4_DOOR_FRAME_CONSUMED;
    }

    return V4_DOOR_FRAME_NOT_CONSUMED;
}


static gboolean
v4_door_tick_cb(gpointer data)
{
    (void)data;

    if (v4_door_stage != V4_DOOR_IDLE &&
        v4_door_deadline_us > 0 &&
        g_get_monotonic_time() > v4_door_deadline_us) {
        v4_door_emit_result(v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE");
        if (v4_door_send_started) {
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return G_SOURCE_REMOVE;
        }
        v4_door_reset();
    }

    if (!v4_door_signal_pending)
        return G_SOURCE_CONTINUE;

    v4_door_signal_pending = 0;

    if (!v4_listener_ready ||
        p12_stage != P12_STAGE_V4_LISTEN_RING ||
        v4_door_stage != V4_DOOR_IDLE ||
        p12_tx_pending) {
        printf("V4_DOOR_RESULT=REJECTED_NOT_READY\n");
        printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
        printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
        fflush(stdout);
        return G_SOURCE_CONTINUE;
    }

    printf("V4_DOOR_COMMAND_ACCEPTED=true\n");
    printf("V4_DOOR_TARGET=entrance\n");
    printf("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    fflush(stdout);

    if (!v4_door_queue_open()) {
        v4_door_emit_result(v4_door_send_started ? "UNKNOWN_OUTCOME" : "FAILED_SAFE");
        if (v4_door_send_started) {
            failed = TRUE;
            if (loop) g_main_loop_quit(loop);
            return G_SOURCE_REMOVE;
        }
        v4_door_reset();
    }

    return G_SOURCE_CONTINUE;
}
'''


def transform(source: str, bodies: tuple[bytes, ...]) -> str:
    text = source
    text = replace_once(
        text,
        "#include <unistd.h>\n",
        "#include <unistd.h>\n#include <signal.h>\n",
        "signal include",
    )
    text = replace_once(
        text,
        "    P12_TX_V4_PEER_ECHO_REPLY,\n    P12_TX_V4_PEER_ECHO_CLOSE_ACK\n} P12TxKind;",
        "    P12_TX_V4_PEER_ECHO_REPLY,\n    P12_TX_V4_PEER_ECHO_CLOSE_ACK,\n\n"
        "    P12_TX_V4_DOOR_OPEN_CTPP,\n    P12_TX_V4_DOOR_WRITE,\n"
        "    P12_TX_V4_DOOR_CLOSE_CTPP\n} P12TxKind;",
        "Door tx enum",
    )
    text = replace_once(
        text,
        "static gboolean v4_ring_observed = FALSE;\n",
        "static gboolean v4_ring_observed = FALSE;\n" + globals_block(bodies),
        "Door globals",
    )
    text = replace_once(
        text,
        "\n\n        default:\n            break;\n    }\n\n    if (\n        p12_stage ==\n        P12_STAGE_V4_LISTEN_RING\n    ) {",
        "\n\n        case P12_TX_V4_DOOR_OPEN_CTPP:\n"
        "            printf(\"V4_DOOR_CTPP_OPEN_SENT=true\\n\");\n"
        "            v4_door_stage = V4_DOOR_WAIT_OPEN;\n"
        "            v4_door_set_deadline();\n            break;\n\n"
        "        case P12_TX_V4_DOOR_WRITE:\n"
        "            printf(\"V4_DOOR_WRITE_%u_SENT=true\\n\", (unsigned)v4_door_write_index);\n"
        "            v4_door_stage = V4_DOOR_WAIT_WRITE;\n"
        "            v4_door_set_deadline();\n            break;\n\n"
        "        case P12_TX_V4_DOOR_CLOSE_CTPP:\n"
        "            printf(\"V4_DOOR_CTPP_CLOSE_SENT=true\\n\");\n"
        "            v4_door_stage = V4_DOOR_WAIT_CLOSE;\n"
        "            v4_door_set_deadline();\n            break;\n\n"
        "        default:\n            break;\n    }\n\n    if (\n"
        "        p12_stage ==\n        P12_STAGE_V4_LISTEN_RING\n    ) {",
        "Door tx completion",
    )
    text = replace_once(
        text,
        "static gboolean\np12_process_post_uaut(void)\n{",
        helpers_block() + "\n\nstatic gboolean\np12_process_post_uaut(void)\n{",
        "Door helper insertion",
    )
    text = replace_once(
        text,
        "        const guint8 *body =\n            post_ack_capture + 8;\n\n\n        /*",
        "        const guint8 *body =\n            post_ack_capture + 8;\n\n\n"
        "        V4DoorFrameResult door_frame =\n"
        "            v4_door_process_frame(request_id, body, body_len);\n\n"
        "        if (door_frame == V4_DOOR_FRAME_FAIL)\n            return FALSE;\n\n"
        "        if (door_frame == V4_DOOR_FRAME_CONSUMED) {\n"
        "            p12_consume_post_ack(frame_len);\n            continue;\n        }\n\n\n        /*",
        "Door frame dispatch",
    )
    text = replace_once(
        text,
        "                    \"V4_DOOR_ACTION_SURFACE_PRESENT=false\\n\"",
        "                    \"V4_DOOR_ACTION_SURFACE_PRESENT=true\\n\"",
        "Door capability marker",
    )
    text = replace_once(
        text,
        "    g_timeout_add(\n        100,\n        stop_check_cb,\n        NULL\n    );\n\n"
        "    g_timeout_add(\n        100,\n        remote_sdp_check_cb,\n        NULL\n    );",
        "    signal(SIGUSR1, v4_door_signal_handler);\n\n"
        "    g_timeout_add(\n        100,\n        stop_check_cb,\n        NULL\n    );\n\n"
        "    g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );\n\n"
        "    g_timeout_add(\n        100,\n        remote_sdp_check_cb,\n        NULL\n    );",
        "Door signal/timer",
    )
    for marker in (
        "P12_TX_V4_DOOR_OPEN_CTPP",
        "V4_DOOR_COMMAND_ACCEPTED=true",
        "V4_DOOR_RESULT=%s",
        "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
        "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
    ):
        if marker not in text:
            raise RuntimeError(f"generated source missing {marker}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate persistent Ring+Door helper source")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("persistent source SHA-256 mismatch")
    bodies = payload_bodies(args.payload)
    generated = transform(source_bytes.decode("utf-8"), bodies)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")

    print("V14_PERSISTENT_DOOR_TRANSFORM=PASS")
    print(f"V14_GENERATED_SOURCE_SHA256={hashlib.sha256(generated.encode()).hexdigest()}")
    print("V14_TARGET=entrance")
    print("V14_WRITE_COUNT=6")
    print("V14_AUTO_RETRY_ALLOWED=false")
    print("RAW_DOOR_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
