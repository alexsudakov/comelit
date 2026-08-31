#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

BASELINE_SOURCE_SHA256 = "d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9"
BASELINE_BINARY_SHA256 = "628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de"


def c_byte_array(data: bytes, indent: str = "    ") -> str:
    if not data:
        return ""
    rows: list[str] = []
    for start in range(0, len(data), 12):
        chunk = data[start : start + 12]
        rows.append(indent + ", ".join(f"0x{b:02x}" for b in chunk))
    return ",\n".join(rows)


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


def p12_globals(ucfg_body: bytes) -> str:
    return f'''

#define P12_TX_MAX 4096
#define P12_STEP_TIMEOUT_SECONDS 6
#define P12_SECRETS_FILE "/root/.config/comelit/secrets.env"
#define P12_UCFG_FILE RUN_DIR "/p12-ucfg-response.json"

typedef enum {{
    P12_STAGE_IDLE = 0,
    P12_STAGE_AUTH_TX,
    P12_STAGE_WAIT_AUTH_RESPONSE,
    P12_STAGE_CLOSE_UAUT_TX,
    P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE,
    P12_STAGE_OPEN_UCFG_TX,
    P12_STAGE_WAIT_UCFG_OPEN_RESPONSE,
    P12_STAGE_GET_UCFG_TX,
    P12_STAGE_WAIT_UCFG_RESPONSE,
    P12_STAGE_CLOSE_UCFG_TX,
    P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE,
    P12_STAGE_DONE
}} P12ReadonlyStage;

typedef enum {{
    P12_TX_NONE = 0,
    P12_TX_AUTH,
    P12_TX_CLOSE_UAUT,
    P12_TX_OPEN_UCFG,
    P12_TX_GET_UCFG,
    P12_TX_CLOSE_UCFG
}} P12TxKind;

static P12ReadonlyStage p12_stage = P12_STAGE_IDLE;
static P12TxKind p12_tx_kind = P12_TX_NONE;
static guint8 p12_tx[P12_TX_MAX];
static guint p12_tx_len = 0;
static guint p12_tx_offset = 0;
static gboolean p12_tx_pending = FALSE;
static gint64 p12_deadline_us = 0;
static guint16 ucfg_channel_id = 0;
static guint16 ucfg_requested_channel_id = 0;
static gboolean p12_auth_ok = FALSE;
static gboolean p12_uaut_close_ok = FALSE;
static gboolean p12_ucfg_open_ok = FALSE;
static gboolean p12_ucfg_received = FALSE;
static gboolean p12_ucfg_close_ok = FALSE;

static const guint8 p12_ucfg_request_body[] = {{
{c_byte_array(ucfg_body)}
}};
static const guint p12_ucfg_request_body_len = {len(ucfg_body)}u;
'''


def p12_helpers() -> str:
    return r'''
static void
p12_set_deadline(void)
{
    p12_deadline_us =
        g_get_monotonic_time() +
        ((gint64)P12_STEP_TIMEOUT_SECONDS * G_USEC_PER_SEC);
}


static gboolean
p12_stage_timeout_cb(gpointer data)
{
    (void)data;

    if (p12_stage == P12_STAGE_IDLE ||
        p12_stage == P12_STAGE_DONE) {
        return G_SOURCE_REMOVE;
    }

    if (p12_deadline_us > 0 &&
        g_get_monotonic_time() > p12_deadline_us) {

        fprintf(
            stderr,
            "P12_READONLY_STAGE_TIMEOUT stage=%u\n",
            (unsigned)p12_stage
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
p12_is_hex32(const gchar *value)
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
p12_load_vip_token(gchar out[33])
{
    gchar *contents = NULL;
    gsize length = 0;
    GError *error = NULL;

    if (!g_file_get_contents(
            P12_SECRETS_FILE,
            &contents,
            &length,
            &error)) {

        fprintf(
            stderr,
            "P12_VIP_TOKEN_READ=FAIL\n"
        );

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

        if (!p12_is_hex32(value))
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
            "P12_VIP_TOKEN_UNIQUE_MATCH=false count=%u\n",
            matches
        );

        return FALSE;
    }

    memcpy(out, selected, 33);
    memset(selected, 0, sizeof(selected));

    printf("P12_VIP_TOKEN_UNIQUE_MATCH=true\n");
    printf("P12_VIP_TOKEN_VALUE_EMITTED=false\n");
    fflush(stdout);

    return TRUE;
}


static gboolean
p12_queue_bytes(
    const guint8 *data,
    guint length,
    P12TxKind kind)
{
    if (p12_tx_pending ||
        length == 0 ||
        length > P12_TX_MAX) {

        fprintf(stderr, "P12_TX_QUEUE=FAIL\n");
        return FALSE;
    }

    memcpy(p12_tx, data, length);
    p12_tx_len = length;
    p12_tx_offset = 0;
    p12_tx_kind = kind;
    p12_tx_pending = TRUE;

    return TRUE;
}


static gboolean
p12_queue_vip_frame(
    guint32 request_id,
    const guint8 *body,
    guint body_len,
    P12TxKind kind)
{
    if (body_len > 0xffffu ||
        body_len + 8u > P12_TX_MAX) {

        fprintf(stderr, "P12_VIP_FRAME_BUILD=FAIL\n");
        return FALSE;
    }

    guint8 frame[P12_TX_MAX];
    memset(frame, 0, sizeof(frame));

    frame[0] = 0x00;
    frame[1] = 0x06;
    write_le16(frame + 2, (guint16)body_len);
    write_le32(frame + 4, request_id);
    memcpy(frame + 8, body, body_len);

    gboolean ok =
        p12_queue_bytes(
            frame,
            body_len + 8u,
            kind
        );

    memset(frame, 0, body_len + 8u);
    return ok;
}


static void
p12_tx_completed(P12TxKind kind)
{
    switch (kind) {
        case P12_TX_AUTH:
            printf("VIP_UAUT_AUTH_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_AUTH_RESPONSE;
            break;

        case P12_TX_CLOSE_UAUT:
            printf("VIP_UAUT_CLOSE_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE;
            break;

        case P12_TX_OPEN_UCFG:
            printf(
                "VIP_UCFG_OPEN_SENT=PASS requested_channel_id=%u\n",
                (unsigned)ucfg_requested_channel_id
            );
            p12_stage = P12_STAGE_WAIT_UCFG_OPEN_RESPONSE;
            break;

        case P12_TX_GET_UCFG:
            printf("VIP_UCFG_GET_CONFIGURATION_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UCFG_RESPONSE;
            break;

        case P12_TX_CLOSE_UCFG:
            printf("VIP_UCFG_CLOSE_SENT=PASS\n");
            p12_stage = P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE;
            break;

        default:
            break;
    }

    p12_set_deadline();
    fflush(stdout);
}


static gboolean
p12_flush_tx(void)
{
    if (!p12_tx_pending)
        return TRUE;

    while (p12_tx_offset < p12_tx_len) {
        gint n =
            pseudo_tcp_socket_send(
                pseudo_tcp,
                (const gchar *)p12_tx + p12_tx_offset,
                (guint32)(p12_tx_len - p12_tx_offset)
            );

        if (n > 0) {
            p12_tx_offset += (guint)n;
            continue;
        }

        if (n < 0) {
            gint err =
                pseudo_tcp_socket_get_error(pseudo_tcp);

            if (err == EWOULDBLOCK)
                return TRUE;

            fprintf(
                stderr,
                "P12_PSEUDOTCP_SEND=FAIL error=%d\n",
                err
            );

            return FALSE;
        }

        return TRUE;
    }

    P12TxKind completed = p12_tx_kind;

    memset(p12_tx, 0, p12_tx_len);
    p12_tx_len = 0;
    p12_tx_offset = 0;
    p12_tx_kind = P12_TX_NONE;
    p12_tx_pending = FALSE;

    p12_tx_completed(completed);
    return TRUE;
}


static gboolean
p12_queue_auth(void)
{
    gchar token[33] = {0};

    if (!p12_load_vip_token(token))
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
        fprintf(stderr, "P12_UAUT_AUTH_BODY_SHAPE=FAIL len=%d\n", n);
        return FALSE;
    }

    gboolean ok =
        p12_queue_vip_frame(
            uaut_channel_id,
            (const guint8 *)body,
            (guint)n,
            P12_TX_AUTH
        );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    p12_stage = P12_STAGE_AUTH_TX;
    return p12_flush_tx();
}


static gboolean
p12_queue_close_channel(
    guint16 channel_id,
    P12TxKind kind)
{
    guint8 body[10];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 3);
    write_le32(body + 4, 2);
    write_le16(body + 8, channel_id);

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            kind
        );

    memset(body, 0, sizeof(body));
    return ok && p12_flush_tx();
}


static gboolean
p12_queue_open_ucfg(void)
{
    guint16 candidate = 7449;

    while (candidate == echo_channel_id ||
           candidate == uaut_channel_id) {
        candidate++;
    }

    ucfg_requested_channel_id = candidate;

    guint8 body[15];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "UCFG", 4);
    write_le16(body + 12, ucfg_requested_channel_id);
    body[14] = 0;

    gboolean ok =
        p12_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P12_TX_OPEN_UCFG
        );

    memset(body, 0, sizeof(body));
    return ok && p12_flush_tx();
}


static gboolean
p12_queue_get_ucfg(void)
{
    if (p12_ucfg_request_body_len == 0 ||
        p12_ucfg_request_body[
            p12_ucfg_request_body_len - 1
        ] != 0x0a) {

        fprintf(stderr, "P12_UCFG_REQUEST_LF=FAIL\n");
        return FALSE;
    }

    return
        p12_queue_vip_frame(
            ucfg_channel_id,
            p12_ucfg_request_body,
            p12_ucfg_request_body_len,
            P12_TX_GET_UCFG
        ) &&
        p12_flush_tx();
}


static gboolean
p12_json_string_equals(
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
p12_json_int_equals(
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
p12_parse_control_response(
    const guint8 *body,
    guint body_len,
    guint16 expected_opcode,
    guint16 expected_channel,
    gboolean allow_response_channel_change,
    guint16 *response_channel,
    guint16 *response_word)
{
    if (body_len != 12 ||
        read_le16(body + 0) != 0xABCD ||
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


static void
p12_consume_post_ack(guint frame_len)
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
p12_save_ucfg(
    const guint8 *body,
    guint body_len)
{
    if (body_len == 0)
        return FALSE;

    const guint8 *p = body;
    guint remaining = body_len;

    while (remaining > 0 &&
           g_ascii_isspace(*p)) {
        p++;
        remaining--;
    }

    if (remaining == 0 || *p != '{') {
        fprintf(stderr, "P12_UCFG_JSON_SHAPE=FAIL\n");
        return FALSE;
    }

    GError *error = NULL;

    if (!g_file_set_contents(
            P12_UCFG_FILE,
            (const gchar *)body,
            (gssize)body_len,
            &error)) {

        fprintf(stderr, "P12_UCFG_LOCAL_CAPTURE_WRITE=FAIL\n");

        if (error)
            g_error_free(error);

        return FALSE;
    }

    chmod(P12_UCFG_FILE, 0600);

    gchar *digest =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            body,
            body_len
        );

    printf("UCFG_RECEIVED=true\n");
    printf("UCFG_RESPONSE_BYTES=%u\n", body_len);
    printf("UCFG_RESPONSE_SHA256=%s\n", digest ? digest : "unavailable");
    printf("UCFG_RESPONSE_VALUE_EMITTED=false\n");
    printf("UCFG_LOCAL_CAPTURE_MODE=600\n");

    g_free(digest);
    fflush(stdout);

    return TRUE;
}


static gboolean
p12_process_post_uaut(void)
{
    while (TRUE) {
        if (post_ack_capture_len < 8)
            return TRUE;

        if (post_ack_capture[0] != 0x00 ||
            post_ack_capture[1] != 0x06) {

            fprintf(stderr, "P12_VIP_RX_HEADER=FAIL\n");
            return FALSE;
        }

        guint body_len =
            (guint)read_le16(post_ack_capture + 2);

        guint frame_len = 8u + body_len;

        if (frame_len > POST_ACK_CAPTURE_MAX) {
            fprintf(stderr, "P12_VIP_RX_LENGTH=FAIL\n");
            return FALSE;
        }

        if (post_ack_capture_len < frame_len)
            return TRUE;

        guint32 request_id =
            read_le32(post_ack_capture + 4);

        const guint8 *body =
            post_ack_capture + 8;

        if (p12_stage == P12_STAGE_WAIT_AUTH_RESPONSE) {
            if (request_id != uaut_channel_id) {
                fprintf(stderr, "P12_UAUT_AUTH_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            gchar *json =
                g_strndup((const gchar *)body, body_len);

            gboolean ok =
                p12_json_string_equals(
                    json,
                    body_len,
                    "message",
                    "access"
                ) &&
                p12_json_string_equals(
                    json,
                    body_len,
                    "message-type",
                    "response"
                ) &&
                p12_json_int_equals(
                    json,
                    body_len,
                    "response-code",
                    200
                );

            g_free(json);

            if (!ok) {
                fprintf(stderr, "P12_UAUT_AUTH_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_auth_ok = TRUE;
            printf("P2_VIP_UAUT_AUTH=PASS\n");
            printf("UAUT_RESPONSE_CODE=200\n");
            printf("UAUT_RESPONSE_VALUE_EMITTED=false\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_CLOSE_UAUT_TX;

            if (!p12_queue_close_channel(
                    uaut_channel_id,
                    P12_TX_CLOSE_UAUT)) {
                return FALSE;
            }

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UAUT_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    4,
                    uaut_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UAUT_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_uaut_close_ok = TRUE;
            printf("VIP_UAUT_CLOSE_RESPONSE=PASS\n");
            printf("VIP_UAUT_CLOSE_RESPONSE_WORD=0\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_OPEN_UCFG_TX;

            if (!p12_queue_open_ucfg())
                return FALSE;

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_OPEN_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    2,
                    ucfg_requested_channel_id,
                    TRUE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UCFG_OPEN_RESPONSE=FAIL\n");
                return FALSE;
            }

            ucfg_channel_id = response_channel;
            p12_ucfg_open_ok = TRUE;

            printf("VIP_UCFG_OPEN_RESPONSE=PASS\n");
            printf(
                "VIP_UCFG_OPEN_RESPONSE_CHANNEL_ID=%u\n",
                (unsigned)ucfg_channel_id
            );
            printf("VIP_UCFG_OPEN_RESPONSE_WORD=0\n");
            fflush(stdout);

            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_GET_UCFG_TX;

            if (!p12_queue_get_ucfg())
                return FALSE;

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_RESPONSE) {
            if (request_id != ucfg_channel_id) {
                fprintf(stderr, "P12_UCFG_RESPONSE_REQUEST_ID=FAIL\n");
                return FALSE;
            }

            if (!p12_save_ucfg(body, body_len))
                return FALSE;

            p12_ucfg_received = TRUE;
            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_CLOSE_UCFG_TX;

            if (!p12_queue_close_channel(
                    ucfg_channel_id,
                    P12_TX_CLOSE_UCFG)) {
                return FALSE;
            }

            continue;
        }

        if (p12_stage == P12_STAGE_WAIT_UCFG_CLOSE_RESPONSE) {
            guint16 response_channel = 0;
            guint16 response_word = 0xffff;

            if (request_id != 0 ||
                !p12_parse_control_response(
                    body,
                    body_len,
                    4,
                    ucfg_channel_id,
                    FALSE,
                    &response_channel,
                    &response_word) ||
                response_word != 0) {

                fprintf(stderr, "P12_UCFG_CLOSE_RESPONSE=FAIL\n");
                return FALSE;
            }

            p12_ucfg_close_ok = TRUE;
            p12_consume_post_ack(frame_len);
            p12_stage = P12_STAGE_DONE;
            p12_deadline_us = 0;

            printf("VIP_UCFG_CLOSE_RESPONSE=PASS\n");
            printf("VIP_UCFG_CLOSE_RESPONSE_WORD=0\n");
            printf("P12_READONLY_TRANSACTION=PASS\n");
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
            "P12_UNEXPECTED_RX_STAGE=%u\n",
            (unsigned)p12_stage
        );

        return FALSE;
    }
}


static gboolean
p12_begin_auth(void)
{
    if (uaut_response_word != 0) {
        fprintf(
            stderr,
            "P12_UAUT_OPEN_RESPONSE_WORD=FAIL value=%u\n",
            (unsigned)uaut_response_word
        );

        return FALSE;
    }

    post_ack_capture_len = 0;
    p12_stage = P12_STAGE_AUTH_TX;
    p12_set_deadline();

    g_timeout_add(
        200,
        p12_stage_timeout_cb,
        NULL
    );

    return p12_queue_auth();
}


'''


def p12_success_summary() -> str:
    return r'''
    printf(
        "P12_UAUT_AUTH_OK=%s\n",
        p12_auth_ok ? "true" : "false"
    );
    printf(
        "P12_UAUT_CLOSE_OK=%s\n",
        p12_uaut_close_ok ? "true" : "false"
    );
    printf(
        "P12_UCFG_OPEN_OK=%s\n",
        p12_ucfg_open_ok ? "true" : "false"
    );
    printf(
        "P12_UCFG_RECEIVED=%s\n",
        p12_ucfg_received ? "true" : "false"
    );
    printf(
        "P12_UCFG_CLOSE_OK=%s\n",
        p12_ucfg_close_ok ? "true" : "false"
    );
    printf("READONLY_SCOPE_ENFORCED=PASS\n");
    printf("CREDENTIAL_MATERIAL_EMITTED=false\n");
    printf("ACTUATOR_COMMAND_ATTEMPTED=false\n");
    printf("MEDIA_ACTIVATION_ATTEMPTED=false\n");
    printf("AUTO_RETRY_OBSERVED=false\n");
    printf("PHYSICAL_DOOR_ACTION=false\n");
    printf("PHYSICAL_EFFECT_ASSERTED=false\n");
    printf("LIVE_TEST_READY=false\n");
'''


def transform(source: str, ucfg_body: bytes) -> str:
    if not ucfg_body.endswith(b"\n"):
        raise RuntimeError("UCFG request body must end with LF")
    if b"get-configuration" not in ucfg_body:
        raise RuntimeError("UCFG request body must contain get-configuration")
    if any(x in ucfg_body for x in (b"CTPP", b"OPEN_DOOR", b"open_door", b"create_door_message")):
        raise RuntimeError("forbidden actuator surface in UCFG request body")

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
        globals_anchor + p12_globals(ucfg_body),
        "P12 globals",
    )

    helper_anchor = "static gboolean\nuaut_response_timeout_cb(gpointer data)"
    text = replace_once(
        text,
        helper_anchor,
        p12_helpers() + helper_anchor,
        "P12 helper insertion",
    )

    old_guard = """static gboolean\ntry_parse_uaut_response(void)\n{\n    if (uaut_response_seen)\n        return TRUE;"""
    new_guard = """static gboolean\ntry_parse_uaut_response(void)\n{\n    if (uaut_response_seen)\n        return p12_process_post_uaut();"""
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
        "if (!p12_begin_auth())\n        return FALSE;",
        "replace premature UAUT success quit",
    )

    writable_old = """    if (!try_send_echo_ack() ||\n        !try_send_uaut_open()) {"""
    writable_new = """    if (!try_send_echo_ack() ||\n        !try_send_uaut_open() ||\n        !p12_flush_tx()) {"""
    text = replace_once(
        text,
        writable_old,
        writable_new,
        "writable P12 flush",
    )

    success_anchor = """static gboolean\npseudotcp_success_quit_cb(gpointer data)\n{\n    (void)data;\n"""
    text = replace_once(
        text,
        success_anchor,
        success_anchor + p12_success_summary(),
        "P12 success summary",
    )

    forbidden = (
        "OPEN_DOOR",
        "open_door",
        "create_door_message",
        "CTPP",
    )
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"transformed holder unexpectedly contains forbidden actuator token {token}")

    required = (
        "P2_VIP_UAUT_AUTH=PASS",
        "UCFG_RECEIVED=true",
        "P12_READONLY_TRANSACTION=PASS",
        "ACTUATOR_COMMAND_ATTEMPTED=false",
        "LIVE_TEST_READY=false",
        "P12_VIP_TOKEN_VALUE_EMITTED=false",
    )
    for token in required:
        if token not in text:
            raise RuntimeError(f"transformed holder missing required marker {token}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Transform the pinned UAUT-open holder into a P12 read-only candidate")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    templates = json.loads(args.templates.read_text(encoding="utf-8"))
    ucfg_body = bytes.fromhex(templates["ucfg_body_hex"])

    source = args.source.read_text(encoding="utf-8")
    transformed = transform(source, ucfg_body)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(transformed, encoding="utf-8")

    print("P12_HOLDER_TRANSFORM=PASS")
    print(f"P12_UCFG_TEMPLATE_BYTES={len(ucfg_body)}")
    print("P12_CTPP_SURFACE_PRESENT=false")
    print("P12_DOOR_ACTUATOR_SURFACE_PRESENT=false")
    print("P12_MEDIA_ACTIVATION_SURFACE_PRESENT=false")
    print("AUTO_RETRY_IMPLEMENTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
