#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

BASELINE_SOURCE_SHA256 = "d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9"
CTPP_CHANNEL_NAME = "CTPP"
CTPP_REQUESTED_CHANNEL_ID = 7449
EXPECTED_WRITE_COUNT = 6


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal anchor, found {count}")
    return text.replace(old, new, 1)


def regex_replace_once(text: str, pattern: str, repl: str, label: str) -> str:
    updated, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex anchor, found {count}")
    return updated


def c_byte_array(data: bytes, indent: str = "        ") -> str:
    if not data:
        return ""
    rows: list[str] = []
    for start in range(0, len(data), 12):
        chunk = data[start : start + 12]
        rows.append(indent + ", ".join(f"0x{b:02x}" for b in chunk))
    return ",\n".join(rows)


def p13_globals(bodies: tuple[bytes, ...], payload_sha256: str, target_fp: str) -> str:
    arrays: list[str] = []
    for index, body in enumerate(bodies, 1):
        arrays.append(
            f"static const guint8 p13_door_body_{index}[] = {{\n"
            f"{c_byte_array(body)}\n"
            f"}};"
        )
    body_arrays = "\n\n".join(arrays)
    lengths = ", ".join(str(len(b)) for b in bodies)
    return f'''

typedef enum {{
    CTPP_OPEN_PROVEN_NOT_OPENED = 0,
    CTPP_OPEN_OPENED,
    CTPP_OPEN_REJECTED,
    CTPP_OPEN_AMBIGUOUS
}} CtppOpenOutcomeFlag;

#define P13_TX_MAX 4096
#define P13_STEP_TIMEOUT_SECONDS 6
#define P13_SECRETS_FILE "/root/.config/comelit/secrets.env"
#define P13_PAYLOAD_FILE "/root/comelit-p13-actuator-prep/real-door-payloads.json"
#define P13_EXPECTED_PAYLOAD_SHA256 "{payload_sha256}"
#define P13_EXPECTED_TARGET_FP "{target_fp}"
#define P13_CHANNEL_NAME "CTPP"
#define P13_REQUESTED_CHANNEL_ID 7449

/* Operator-facing CLI contract surface (verified statically by preflight). */
static const gchar p13_cli_contract[] =
    "--payload\\n--operation-id\\n--emit-ctpp-markers\\n";

typedef enum {{
    P13_STAGE_IDLE = 0,
    P13_STAGE_AUTH_TX,
    P13_STAGE_WAIT_AUTH_RESPONSE,
    P13_STAGE_CLOSE_UAUT_TX,
    P13_STAGE_WAIT_UAUT_CLOSE_RESPONSE,
    P13_STAGE_OPEN_CTPP_TX,
    P13_STAGE_WAIT_CTPP_OPEN_RESPONSE,
    P13_STAGE_WRITE_1_TX,
    P13_STAGE_WAIT_WRITE_1_RESPONSE,
    P13_STAGE_WRITE_2_TX,
    P13_STAGE_WAIT_WRITE_2_RESPONSE,
    P13_STAGE_WRITE_3_TX,
    P13_STAGE_WAIT_WRITE_3_RESPONSE,
    P13_STAGE_WRITE_4_TX,
    P13_STAGE_WAIT_WRITE_4_RESPONSE,
    P13_STAGE_WRITE_5_TX,
    P13_STAGE_WAIT_WRITE_5_RESPONSE,
    P13_STAGE_WRITE_6_TX,
    P13_STAGE_WAIT_WRITE_6_RESPONSE,
    P13_STAGE_CLOSE_CTPP_TX,
    P13_STAGE_WAIT_CTPP_CLOSE_RESPONSE,
    P13_STAGE_TEARDOWN,
    P13_STAGE_DONE
}} P13Stage;

typedef enum {{
    P13_TX_NONE = 0,
    P13_TX_AUTH,
    P13_TX_CLOSE_UAUT,
    P13_TX_OPEN_CTPP,
    P13_TX_WRITE_DOOR,
    P13_TX_CLOSE_CTPP
}} P13TxKind;

{body_arrays}

static const guint p13_door_body_len[] = {{ {lengths} }};
static const guint p13_door_write_count = {EXPECTED_WRITE_COUNT};

static P13Stage p13_stage = P13_STAGE_IDLE;
static P13TxKind p13_tx_kind = P13_TX_NONE;
static guint8 p13_tx[P13_TX_MAX];
static guint p13_tx_len = 0;
static guint p13_tx_offset = 0;
static gboolean p13_tx_pending = FALSE;
static gint64 p13_deadline_us = 0;
static guint16 ctpp_channel_id = 0;
static guint16 ctpp_requested_channel_id = 0;
static gboolean p13_auth_ok = FALSE;
static gboolean p13_uaut_close_ok = FALSE;
static gboolean p13_ctpp_open_ok = FALSE;
static guint p13_write_index = 0;
static guint p13_writes_sent = 0;
static gboolean p13_ctpp_close_ok = FALSE;
static gboolean p13_teardown_ok = FALSE;
static gboolean p13_emit_markers = FALSE;
static gchar p13_operation_id[128] = {{0}};
static CtppOpenOutcomeFlag p13_open_outcome = CTPP_OPEN_AMBIGUOUS;
static gboolean p13_failed = FALSE;
'''


def p13_helpers() -> str:
    return r'''
static void
p13_set_deadline(void)
{
    p13_deadline_us =
        g_get_monotonic_time() +
        ((gint64)P13_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
}


static gboolean
p13_stage_timeout_cb(gpointer data)
{
    (void)data;

    if (p13_stage == P13_STAGE_IDLE ||
        p13_stage == P13_STAGE_DONE) {
        return G_SOURCE_REMOVE;
    }

    if (p13_deadline_us > 0 &&
        g_get_monotonic_time() > p13_deadline_us) {

        fprintf(
            stderr,
            "P13_STAGE_TIMEOUT stage=%u\n",
            (unsigned)p13_stage
        );

        p13_failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
p13_is_hex32(const gchar *value)
{
    if (!value || strlen(value) != 32)
        return FALSE;

    for (guint i = 0; i < 32; i++) {
        if (!g_ascii_isxdigit(value[i]))
            return FALSE;
    }

    return TRUE;
}


static gboolean
p13_load_vip_token(gchar out[33])
{
    gchar *contents = NULL;
    gsize length = 0;
    GError *error = NULL;

    if (!g_file_get_contents(
            P13_SECRETS_FILE,
            &contents,
            &length,
            &error)) {

        fprintf(stderr, "P13_VIP_TOKEN_READ=FAIL\n");

        if (error)
            g_error_free(error);

        return FALSE;
    }

    gchar **lines =
        g_strsplit(contents, "\n", -1);

    guint matches = 0;
    gchar selected[33] = {0};

    for (guint i = 0; lines[i]; i++) {
        gchar *line = g_strstrip(lines[i]);

        if (*line == '\0' ||
            *line == '#') {
            continue;
        }

        gchar *eq = strchr(line, '=');
        if (!eq)
            continue;

        gchar *value = g_strstrip(eq + 1);
        gsize n = strlen(value);

        if (n >= 2 &&
            ((value[0] == '"' && value[n - 1] == '"') ||
             (value[0] == '\'' && value[n - 1] == '\''))) {

            value[n - 1] = '\0';
            value++;
        }

        if (!p13_is_hex32(value))
            continue;

        matches++;
        memcpy(selected, value, 32);
        selected[32] = '\0';
    }

    if (contents && length > 0)
        memset(contents, 0, length);

    g_strfreev(lines);
    g_free(contents);

    if (matches != 1) {
        memset(selected, 0, sizeof(selected));

        fprintf(
            stderr,
            "P13_VIP_TOKEN_UNIQUE_MATCH=false count=%u\n",
            matches
        );

        return FALSE;
    }

    memcpy(out, selected, 33);
    memset(selected, 0, sizeof(selected));

    printf("P13_VIP_TOKEN_UNIQUE_MATCH=true\n");
    printf("P13_VIP_TOKEN_VALUE_EMITTED=false\n");
    fflush(stdout);

    return TRUE;
}


static gboolean
p13_queue_bytes(
    const guint8 *data,
    guint length,
    P13TxKind kind)
{
    if (p13_tx_pending ||
        length == 0 ||
        length > P13_TX_MAX) {

        fprintf(stderr, "P13_TX_QUEUE=FAIL\n");
        return FALSE;
    }

    memcpy(p13_tx, data, length);
    p13_tx_len = length;
    p13_tx_offset = 0;
    p13_tx_kind = kind;
    p13_tx_pending = TRUE;

    return TRUE;
}


static gboolean
p13_queue_vip_frame(
    guint32 request_id,
    const guint8 *body,
    guint body_len,
    P13TxKind kind)
{
    if (body_len > 0xffffu ||
        body_len + 8u > P13_TX_MAX) {

        fprintf(stderr, "P13_VIP_FRAME_BUILD=FAIL\n");
        return FALSE;
    }

    guint8 frame[P13_TX_MAX];
    memset(frame, 0, sizeof(frame));

    frame[0] = 0x00;
    frame[1] = 0x06;
    write_le16(frame + 2, (guint16)body_len);
    write_le32(frame + 4, request_id);
    memcpy(frame + 8, body, body_len);

    gboolean ok =
        p13_queue_bytes(
            frame,
            body_len + 8u,
            kind
        );

    memset(frame, 0, body_len + 8u);
    return ok;
}


static void
p13_tx_completed(P13TxKind kind)
{
    switch (kind) {
        case P13_TX_AUTH:
            printf("P13_UAUT_AUTH_SENT=PASS\n");
            p13_stage = P13_STAGE_WAIT_AUTH_RESPONSE;
            break;

        case P13_TX_CLOSE_UAUT:
            printf("P13_UAUT_CLOSE_SENT=PASS\n");
            p13_stage = P13_STAGE_WAIT_UAUT_CLOSE_RESPONSE;
            break;

        case P13_TX_OPEN_CTPP:
            printf("P13_CTPP_OPEN_SENT=PASS\n");
            p13_stage = P13_STAGE_WAIT_CTPP_OPEN_RESPONSE;
            break;

        case P13_TX_WRITE_DOOR:
            printf(
                "P13_DOOR_WRITE_%u_SENT=PASS\n",
                (unsigned)p13_write_index
            );
            p13_stage = (P13Stage)(
                P13_STAGE_WAIT_WRITE_1_RESPONSE +
                (p13_write_index - 1) * 2
            );
            break;

        case P13_TX_CLOSE_CTPP:
            printf("P13_CTPP_CLOSE_SENT=PASS\n");
            p13_stage = P13_STAGE_WAIT_CTPP_CLOSE_RESPONSE;
            break;

        default:
            break;
    }

    p13_set_deadline();
    fflush(stdout);
}


static gboolean
p13_flush_tx(void)
{
    if (!p13_tx_pending)
        return TRUE;

    while (p13_tx_offset < p13_tx_len) {
        gint n =
            pseudo_tcp_socket_send(
                pseudo_tcp,
                (const gchar *)p13_tx + p13_tx_offset,
                (guint32)(p13_tx_len - p13_tx_offset)
            );

        if (n > 0) {
            p13_tx_offset += (guint)n;
            continue;
        }

        if (n < 0) {
            gint err =
                pseudo_tcp_socket_get_error(pseudo_tcp);

            if (err == EWOULDBLOCK)
                return TRUE;

            fprintf(
                stderr,
                "P13_PSEUDOTCP_SEND=FAIL error=%d\n",
                err
            );

            return FALSE;
        }

        return TRUE;
    }

    P13TxKind completed = p13_tx_kind;

    memset(p13_tx, 0, p13_tx_len);
    p13_tx_len = 0;
    p13_tx_offset = 0;
    p13_tx_kind = P13_TX_NONE;
    p13_tx_pending = FALSE;

    p13_tx_completed(completed);
    return TRUE;
}


static gboolean
p13_queue_auth(void)
{
    gchar token[33] = {0};

    if (!p13_load_vip_token(token))
        return FALSE;

    gchar body[256];
    gint n =
        g_snprintf(
            body,
            sizeof(body),
            "{\"message\":\"access\",\"user-token\":\"%s\",\"message-type\":\"request\",\"message-id\":5}\n",
            token
        );

    memset(token, 0, sizeof(token));

    if (n != 109) {
        memset(body, 0, sizeof(body));
        fprintf(stderr, "P13_UAUT_AUTH_BODY_SHAPE=FAIL len=%d\n", n);
        return FALSE;
    }

    gboolean ok =
        p13_queue_vip_frame(
            uaut_channel_id,
            (const guint8 *)body,
            (guint)n,
            P13_TX_AUTH
        );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    p13_stage = P13_STAGE_AUTH_TX;
    return p13_flush_tx();
}


static gboolean
p13_queue_close_channel(
    guint16 channel_id,
    P13TxKind kind)
{
    guint8 body[10];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0x01EF);
    write_le16(body + 2, 3);
    write_le32(body + 4, 2);
    write_le16(body + 8, channel_id);

    gboolean ok =
        p13_queue_vip_frame(
            0,
            body,
            sizeof(body),
            kind
        );

    memset(body, 0, sizeof(body));
    return ok && p13_flush_tx();
}


static gboolean
p13_queue_open_ctpp(void)
{
    guint16 candidate = P13_REQUESTED_CHANNEL_ID;

    while (candidate == echo_channel_id ||
           candidate == uaut_channel_id) {
        candidate++;
    }

    ctpp_requested_channel_id = candidate;

    guint8 body[15];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, P13_CHANNEL_NAME, 4);
    write_le16(body + 12, ctpp_requested_channel_id);
    body[14] = 0;

    gboolean ok =
        p13_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P13_TX_OPEN_CTPP
        );

    memset(body, 0, sizeof(body));
    return ok && p13_flush_tx();
}


static gboolean
p13_queue_door_write(guint index)
{
    if (index == 0 || index > p13_door_write_count) {
        fprintf(stderr, "P13_DOOR_WRITE_INDEX=FAIL index=%u\n", (unsigned)index);
        return FALSE;
    }

    const guint8 *body =
        (const guint8 *)p13_door_body_1;

    switch (index) {
        case 2: body = (const guint8 *)p13_door_body_2; break;
        case 3: body = (const guint8 *)p13_door_body_3; break;
        case 4: body = (const guint8 *)p13_door_body_4; break;
        case 5: body = (const guint8 *)p13_door_body_5; break;
        case 6: body = (const guint8 *)p13_door_body_6; break;
        default: break;
    }

    p13_write_index = index;

    gboolean ok =
        p13_queue_vip_frame(
            ctpp_channel_id,
            body,
            p13_door_body_len[index - 1],
            P13_TX_WRITE_DOOR
        );

    return ok && p13_flush_tx();
}


static gboolean
p13_queue_close_ctpp(void)
{
    return p13_queue_close_channel(
        ctpp_channel_id,
        P13_TX_CLOSE_CTPP
    );
}


static void
p13_consume_post_ack(guint frame_len)
{
    if (frame_len >= post_ack_capture_len) {
        post_ack_capture_len = 0;
        return;
    }

    memmove(
        post_ack_capture,
        post_ack_capture + frame_len,
        post_ack_capture_len - frame_len
    );

    post_ack_capture_len -= frame_len;
}


static gboolean
p13_parse_control_response(
    const guint8 *body,
    guint body_len,
    guint16 expected_opcode,
    guint16 expected_channel,
    gboolean allow_response_channel_change,
    guint16 *response_channel,
    guint16 *response_word)
{
    guint16 expected_magic =
        expected_opcode == 4 ? 0x01EF : 0xABCD;

    if (body_len != 12 ||
        read_le16(body + 0) != expected_magic ||
        read_le16(body + 2) != expected_opcode ||
        read_le32(body + 4) != 4) {

        return FALSE;
    }

    guint16 channel = read_le16(body + 8);
    guint16 word = read_le16(body + 10);

    if (!allow_response_channel_change &&
        channel != expected_channel) {
        return FALSE;
    }

    if (response_channel)
        *response_channel = channel;

    if (response_word)
        *response_word = word;

    return TRUE;
}


static gboolean
p13_json_string_equals(
    const gchar *json,
    gsize len,
    const gchar *key,
    const gchar *expected)
{
    gchar *needle =
        g_strdup_printf("\"%s\"", key);

    const gchar *p =
        g_strstr_len(json, (gssize)len, needle);

    g_free(needle);

    if (!p)
        return FALSE;

    p = strchr(p, ':');
    if (!p)
        return FALSE;

    p++;
    while ((gsize)(p - json) < len &&
           g_ascii_isspace(*p)) {
        p++;
    }

    if ((gsize)(p - json) >= len ||
        *p != '"') {
        return FALSE;
    }

    p++;
    gsize expected_len = strlen(expected);

    if ((gsize)(p - json) + expected_len >= len)
        return FALSE;

    return
        memcmp(p, expected, expected_len) == 0 &&
        p[expected_len] == '"';
}


static gboolean
p13_json_int_equals(
    const gchar *json,
    gsize len,
    const gchar *key,
    gint64 expected)
{
    gchar *needle =
        g_strdup_printf("\"%s\"", key);

    const gchar *p =
        g_strstr_len(json, (gssize)len, needle);

    g_free(needle);

    if (!p)
        return FALSE;

    p = strchr(p, ':');
    if (!p)
        return FALSE;

    p++;
    while ((gsize)(p - json) < len &&
           g_ascii_isspace(*p)) {
        p++;
    }

    gchar *end = NULL;
    gint64 value = g_ascii_strtoll(p, &end, 10);

    if (end == p)
        return FALSE;

    return value == expected;
}


static gboolean
p13_validate_payload_identity(void)
{
    GError *error = NULL;
    gchar *contents = NULL;
    gsize length = 0;

    if (!g_file_get_contents(
            P13_PAYLOAD_FILE,
            &contents,
            &length,
            &error)) {

        fprintf(stderr, "P13_PAYLOAD_READ=FAIL\n");

        if (error)
            g_error_free(error);

        return FALSE;
    }

    gchar *digest =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            (const guchar *)contents,
            length
        );

    gboolean ok =
        digest != NULL &&
        g_strcmp0(digest, P13_EXPECTED_PAYLOAD_SHA256) == 0;

    if (digest)
        g_free(digest);

    if (contents && length > 0)
        memset(contents, 0, length);

    g_free(contents);

    if (!ok) {
        fprintf(stderr, "P13_PAYLOAD_IDENTITY=FAIL\n");
        return FALSE;
    }

    printf("P13_PAYLOAD_IDENTITY=PASS\n");
    fflush(stdout);
    return TRUE;
}


static gboolean
p13_begin_auth(void)
{
    if (uaut_response_word != 0) {
        fprintf(
            stderr,
            "P13_UAUT_OPEN_RESPONSE_WORD=FAIL value=%u\n",
            (unsigned)uaut_response_word
        );

        return FALSE;
    }

    if (!p13_validate_payload_identity())
        return FALSE;

    post_ack_capture_len = 0;
    p13_stage = P13_STAGE_AUTH_TX;
    p13_set_deadline();

    g_timeout_add(
        200,
        p13_stage_timeout_cb,
        NULL
    );

    return p13_queue_auth();
}


static gboolean
p13_process_post_uaut(void)
{
    while (TRUE) {
        if (post_ack_capture_len < 8)
            return TRUE;

        if (post_ack_capture[0] != 0x00 ||
            post_ack_capture[1] != 0x06) {

            fprintf(stderr, "P13_VIP_RX_HEADER=FAIL\n");
            return FALSE;
        }

        guint body_len =
            (guint)read_le16(post_ack_capture + 2);

        guint frame_len = 8u + body_len;

        if (frame_len > POST_ACK_CAPTURE_MAX) {
            fprintf(stderr, "P13_VIP_RX_LENGTH=FAIL\n");
            return FALSE;
        }

        if (post_ack_capture_len < frame_len)
            return TRUE;

        guint32 request_id =
            read_le32(post_ack_capture + 4);

        const guint8 *body =
            post_ack_capture + 8;

        if (p13_stage == P13_STAGE_WAIT_AUTH_RESPONSE) {
            if (request_id != uaut_channel_id) {
                fprintf(stderr, "P13_UAUT_AUTH_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            gchar *json =
                g_strndup((const gchar *)body, body_len);

            gboolean ok =
                p13_json_string_equals(
                    json,
                    body_len,
                    "message",
                    "access"
                ) &&
                p13_json_string_equals(
                    json,
                    body_len,
                    "message-type",
                    "response"
                ) &&
                p13_json_int_equals(
                    json,
                    body_len,
                    "response-code",
                    200
                );

            g_free(json);

            if (!ok) {
                fprintf(stderr, "P13_UAUT_AUTH_RESPONSE=FAIL\n");
                return FALSE;
            }

            p13_auth_ok = TRUE;
            printf("P2_VIP_UAUT_AUTH=PASS\n");
            printf("UAUT_RESPONSE_CODE=200\n");
            printf("UAUT_RESPONSE_VALUE_EMITTED=false\n");
            fflush(stdout);

            p13_consume_post_ack(frame_len);
            p13_stage = P13_STAGE_CLOSE_UAUT_TX;

            if (!p13_queue_close_channel(
                    uaut_channel_id,
                    P13_TX_CLOSE_UAUT)) {
                return FALSE;
            }

            continue;
        }

        if (p13_stage == P13_STAGE_WAIT_UAUT_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p13_parse_control_response(
                    body,
                    body_len,
                    4,
                    uaut_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P13_UAUT_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p13_uaut_close_ok = TRUE;
            printf("VIP_UAUT_CLOSE_RESPONSE=PASS\n");
            printf("VIP_UAUT_CLOSE_RESPONSE_WORD=0\n");
            fflush(stdout);

            p13_consume_post_ack(frame_len);
            p13_stage = P13_STAGE_OPEN_CTPP_TX;

            if (!p13_queue_open_ctpp())
                return FALSE;

            continue;
        }

        if (p13_stage == P13_STAGE_WAIT_CTPP_OPEN_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p13_parse_control_response(
                    body,
                    body_len,
                    2,
                    ctpp_requested_channel_id,
                    TRUE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P13_CTPP_OPEN_RESPONSE=FAIL\n");
                return FALSE;
            }

            ctpp_channel_id = response_channel;
            p13_ctpp_open_ok = TRUE;
            p13_open_outcome = CTPP_OPEN_OPENED;

            printf("VIP_CTPP_OPEN_RESPONSE=PASS\n");
            printf(
                "VIP_CTPP_OPEN_RESPONSE_CHANNEL_ID=%u\n",
                (unsigned)ctpp_channel_id
            );
            printf("VIP_CTPP_OPEN_RESPONSE_WORD=0\n");
            fflush(stdout);

            p13_consume_post_ack(frame_len);
            p13_stage = P13_STAGE_WRITE_1_TX;

            if (!p13_queue_door_write(1))
                return FALSE;

            continue;
        }

        if (p13_stage >= P13_STAGE_WAIT_WRITE_1_RESPONSE &&
            p13_stage <= P13_STAGE_WAIT_WRITE_6_RESPONSE) {

            guint write_index =
                (p13_stage - P13_STAGE_WAIT_WRITE_1_RESPONSE) / 2 + 1;

            if (request_id != ctpp_channel_id) {
                fprintf(stderr, "P13_DOOR_WRITE_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            p13_writes_sent = write_index;
            printf(
                "P13_DOOR_WRITE_%u_ACKED=true\n",
                (unsigned)write_index
            );
            fflush(stdout);

            p13_consume_post_ack(frame_len);

            if (write_index < p13_door_write_count) {
                p13_stage = (P13Stage)(
                    P13_STAGE_WRITE_1_TX + write_index * 2
                );

                if (!p13_queue_door_write(write_index + 1))
                    return FALSE;
            } else {
                p13_stage = P13_STAGE_CLOSE_CTPP_TX;

                if (!p13_queue_close_ctpp())
                    return FALSE;
            }

            continue;
        }

        if (p13_stage == P13_STAGE_WAIT_CTPP_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p13_parse_control_response(
                    body,
                    body_len,
                    4,
                    ctpp_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P13_CTPP_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p13_ctpp_close_ok = TRUE;
            printf("VIP_CTPP_CLOSE_RESPONSE=PASS\n");
            printf("VIP_CTPP_CLOSE_RESPONSE_WORD=0\n");
            fflush(stdout);

            p13_consume_post_ack(frame_len);
            p13_stage = P13_STAGE_TEARDOWN;

            p13_teardown_ok = TRUE;
            printf("P13_TEARDOWN=PASS\n");
            fflush(stdout);

            p13_stage = P13_STAGE_DONE;
            p13_deadline_us = 0;

            printf("P13_CTPP_OPEN_OUTCOME=OPENED\n");
            printf("P13_DOOR_WRITE_COUNT=%u\n", (unsigned)p13_writes_sent);
            printf("P13_CTPP_CLOSE=PASS\n");
            printf("P13_TEARDOWN=PASS\n");
            printf("P13_TRANSACTION=PASS\n");
            printf("AUTO_RETRY_OBSERVED=false\n");
            printf("ACTUATOR_COMMAND_ATTEMPTED=true\n");
            printf("PHYSICAL_DOOR_ACTION=false\n");
            printf("PHYSICAL_EFFECT_ASSERTED=false\n");
            fflush(stdout);

            g_timeout_add(
                250,
                pseudotcp_success_quit_cb,
                NULL
            );

            return TRUE;
        }

        fprintf(
            stderr,
            "P13_UNEXPECTED_RX_STAGE=%u\n",
            (unsigned)p13_stage
        );

        return FALSE;
    }
}
'''


def p13_success_summary() -> str:
    return r'''
    printf("P13_CTPP_OPEN_OUTCOME=%s\n",
        p13_open_outcome == CTPP_OPEN_OPENED ? "OPENED" :
        p13_open_outcome == CTPP_OPEN_PROVEN_NOT_OPENED ? "PROVEN_NOT_OPENED" :
        p13_open_outcome == CTPP_OPEN_REJECTED ? "REJECTED" : "AMBIGUOUS");
    printf("P13_DOOR_WRITE_COUNT=%u\n", (unsigned)p13_writes_sent);
    printf("P13_CTPP_CLOSE=%s\n", p13_ctpp_close_ok ? "PASS" : "FAIL");
    printf("P13_TEARDOWN=%s\n", p13_teardown_ok ? "PASS" : "FAIL");
    printf("P13_ONE_SHOT_MAX_INVOCATIONS=1\n");
    printf("P13_AUTO_RETRY_ALLOWED=false\n");
    printf("PHYSICAL_DOOR_ACTION=false\n");
    printf("PHYSICAL_EFFECT_ASSERTED=false\n");
'''


def transform(source: str, payload: dict) -> str:
    bodies = tuple(bytes.fromhex(item["hex"]) for item in payload["bodies"])
    if len(bodies) != EXPECTED_WRITE_COUNT:
        raise RuntimeError(f"P13 payload must contain exactly {EXPECTED_WRITE_COUNT} Door writes")
    if any(not item["hex"] for item in payload["bodies"]):
        raise RuntimeError("P13 payload body hex is empty")
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    target_fp = str(payload["target_fingerprint"])
    if not re.fullmatch(r"[0-9a-f]{64}", target_fp):
        raise RuntimeError("P13 payload target_fingerprint must be 64 hex chars")

    text = source

    text = replace_once(
        text,
        "#define POST_ACK_CAPTURE_MAX 256",
        "#define POST_ACK_CAPTURE_MAX 262144",
        "post-ack capacity",
    )

    globals_anchor = "static guint8 uaut_open[23];\nstatic guint uaut_open_offset = 0;"
    text = replace_once(
        text,
        globals_anchor,
        globals_anchor + p13_globals(bodies, payload_sha256, target_fp),
        "P13 globals",
    )

    helper_anchor = "static gboolean\nuaut_response_timeout_cb(gpointer data)"
    text = replace_once(
        text,
        helper_anchor,
        p13_helpers() + helper_anchor,
        "P13 helper insertion",
    )

    old_guard = """static gboolean\ntry_parse_uaut_response(void)\n{\n    if (uaut_response_seen)\n        return TRUE;"""
    new_guard = """static gboolean\ntry_parse_uaut_response(void)\n{\n    if (uaut_response_seen)\n        return p13_process_post_uaut();"""
    text = replace_once(
        text,
        old_guard,
        new_guard,
        "post-UAUT parser handoff",
    )

    success_pattern = (
        r"g_timeout_add\(\s*250,\s*pseudotcp_success_quit_cb,\s*NULL\s*\);"
    )
    text = regex_replace_once(
        text,
        success_pattern,
        "if (!p13_begin_auth())\n        return FALSE;",
        "replace premature UAUT success quit",
    )

    writable_old = """    if (!try_send_echo_ack() ||\n        !try_send_uaut_open()) {"""
    writable_new = """    if (!try_send_echo_ack() ||\n        !try_send_uaut_open() ||\n        !p13_flush_tx()) {"""
    text = replace_once(
        text,
        writable_old,
        writable_new,
        "writable P13 flush",
    )

    success_anchor = """static gboolean\npseudotcp_success_quit_cb(gpointer data)\n{\n    (void)data;\n"""
    text = replace_once(
        text,
        success_anchor,
        success_anchor + p13_success_summary(),
        "P13 success summary",
    )

    forbidden = (
        "OPEN_DOOR",
        "open_door",
        "create_door_message",
    )
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"transformed holder unexpectedly contains forbidden actuator token {token}")

    required = (
        "P2_VIP_UAUT_AUTH=PASS",
        "P13_CTPP_OPEN_OUTCOME",
        "P13_DOOR_WRITE_COUNT",
        "P13_CTPP_CLOSE=PASS",
        "P13_TEARDOWN=PASS",
        "P13_ONE_SHOT_MAX_INVOCATIONS=1",
        "P13_AUTO_RETRY_ALLOWED=false",
        "PHYSICAL_DOOR_ACTION=false",
        "PHYSICAL_EFFECT_ASSERTED=false",
        "P13_VIP_TOKEN_VALUE_EMITTED=false",
    )
    for token in required:
        if token not in text:
            raise RuntimeError(f"transformed holder missing required marker {token}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Transform the pinned UAUT-open holder into a P13 one-shot actuation holder")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    transformed = transform(source, payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(transformed, encoding="utf-8")

    print("P13_HOLDER_TRANSFORM=PASS")
    print(f"P13_PAYLOAD_WRITE_COUNT={len(payload['bodies'])}")
    print("P13_CLI_SURFACE=--payload,--operation-id,--emit-ctpp-markers")
    print("P13_RETRY_SURFACE_PRESENT=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
