#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR / "p13_holder_transform.py"

spec = importlib.util.spec_from_file_location("p13_holder_transform_base", BASE)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ucfg_candidates() -> list[Path]:
    candidates: list[Path] = []
    run_capture = Path("/run/comelit-p2p/p12-ucfg-response.json")
    if run_capture.is_file():
        candidates.append(run_capture)

    prune = {".config", ".ssh", ".cache", ".git", "node_modules", "__pycache__"}
    for base, dirs, files in os.walk("/root"):
        dirs[:] = [d for d in dirs if d not in prune]
        if "p12-ucfg-response.json" in files:
            path = Path(base) / "p12-ucfg-response.json"
            if path not in candidates:
                candidates.append(path)
    return candidates


def _dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _dicts(item)


def _extract_vip(doc: object) -> dict:
    candidates: list[dict] = []
    seen: set[str] = set()
    for mapping in _dicts(doc):
        options: list[dict] = []
        vip = mapping.get("vip") if isinstance(mapping, dict) else None
        if isinstance(vip, dict):
            options.append(vip)
        if (
            isinstance(mapping, dict)
            and "apt-address" in mapping
            and isinstance(mapping.get("user-parameters"), dict)
        ):
            options.append(mapping)
        for candidate in options:
            key = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one ViP configuration object, found {len(candidates)}")
    return candidates[0]


def _ctpp_address_from_doc(doc: object) -> str:
    vip = _extract_vip(doc)
    apt_address = vip.get("apt-address")
    apt_subaddress = vip.get("apt-subaddress", "")
    if not isinstance(apt_address, str) or not isinstance(apt_subaddress, (str, int)):
        raise RuntimeError("ViP apartment address fields have unexpected types")
    value = apt_address + str(apt_subaddress)
    if re.fullmatch(r"[0-9]{9}", value) is None:
        raise RuntimeError("CTPP apartment address must be exactly 9 ASCII digits")
    return value


def _load_bound_ctpp_address(payload: dict) -> str:
    expected = str(payload.get("ucfg_sha256", ""))
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise RuntimeError("P13 payload ucfg_sha256 is invalid")

    matches = [path for path in _ucfg_candidates() if _sha256(path) == expected]
    if not matches:
        raise RuntimeError("exact P13-bound UCFG snapshot not found")

    raw = matches[0].read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("UCFG snapshot changed after selection")
    for other in matches[1:]:
        if other.read_bytes() != raw:
            raise RuntimeError("same UCFG hash produced non-identical content")

    return _ctpp_address_from_doc(json.loads(raw.decode("utf-8")))


def _ctpp_open_builder(ctpp_address: str) -> str:
    if re.fullmatch(r"[0-9]{9}", ctpp_address) is None:
        raise RuntimeError("CTPP apartment address must be exactly 9 ASCII digits")
    payload = ctpp_address.encode("ascii") + b"\x00"
    encoded = ", ".join(f"0x{byte:02x}" for byte in payload)

    return f'''static gboolean
p13_queue_open_ctpp(void)
{{
    guint16 candidate = P13_REQUESTED_CHANNEL_ID;

    while (candidate == echo_channel_id ||
           candidate == uaut_channel_id) {{
        candidate++;
    }}

    ctpp_requested_channel_id = candidate;

    /* Canonical OpenChannelRequest with OpenRequestExtension:
     * control header: COMMAND, seq=1, primary_length=7
     * primary: "CTPP" + channel_id(u16 LE) + channel_flag(0)
     * extension: tag(0) + payload_length(u32 LE) + apt_full ASCII + NUL.
     * The apartment value is derived at build time from the exact UCFG
     * snapshot bound by payload.ucfg_sha256 and is never emitted by the
     * installer or committed to Git.
     */
    static const guint8 ctpp_extension_payload[] = {{ {encoded} }};
    guint8 body[30];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, P13_CHANNEL_NAME, 4);
    write_le16(body + 12, ctpp_requested_channel_id);
    body[14] = 0;
    body[15] = 0;
    write_le32(body + 16, (guint32)sizeof(ctpp_extension_payload));
    memcpy(body + 20, ctpp_extension_payload, sizeof(ctpp_extension_payload));

    gboolean ok =
        p13_queue_vip_frame(
            0,
            body,
            sizeof(body),
            P13_TX_OPEN_CTPP
        );

    memset(body, 0, sizeof(body));
    return ok && p13_flush_tx();
}}
'''


def _apply_peer_timing(text: str) -> str:
    """Match the proven peer/TAP write cadence without requiring Door ACKs.

    The recovered peer implementation performs six writes total: register,
    ~200 ms settle, then five operation packets back-to-back, ~1 s settle, and
    channel close. It does not read a response between those writes. Incoming
    CTPP frames are therefore observational only and never advance the write
    sequence.
    """

    tx_completed_anchor = "static void\np13_tx_completed(P13TxKind kind)"
    prototypes = '''static gboolean p13_queue_door_write(guint index);
static gboolean p13_queue_close_ctpp(void);
static gboolean p13_register_settle_cb(gpointer data);
static gboolean p13_post_writes_settle_cb(gpointer data);


static void
p13_tx_completed(P13TxKind kind)'''
    text = _replace_once(
        text,
        tx_completed_anchor,
        prototypes,
        "peer/TAP forward declarations",
    )

    old_write_completed = '''        case P13_TX_WRITE_DOOR:
            printf(
                "P13_DOOR_WRITE_%u_SENT=PASS\\n",
                (unsigned)p13_write_index
            );
            p13_stage = (P13Stage)(
                P13_STAGE_WAIT_WRITE_1_RESPONSE +
                (p13_write_index - 1) * 2
            );
            break;
'''
    new_write_completed = '''        case P13_TX_WRITE_DOOR:
            printf(
                "P13_DOOR_WRITE_%u_SENT=PASS\\n",
                (unsigned)p13_write_index
            );
            p13_writes_sent = p13_write_index;

            if (p13_write_index == 1) {
                /* Peer/TAP register settles for ~200 ms; no ACK is required. */
                p13_stage = P13_STAGE_WAIT_WRITE_1_RESPONSE;
                p13_set_deadline();
                g_timeout_add(200, p13_register_settle_cb, NULL);
            } else if (p13_write_index < p13_door_write_count) {
                /* The five operation packets are emitted back-to-back. */
                p13_stage = (P13Stage)(
                    P13_STAGE_WRITE_1_TX +
                    p13_write_index * 2
                );
                if (!p13_queue_door_write(p13_write_index + 1)) {
                    p13_failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }
            } else {
                /* Give the gateway ~1 s to process the full operation. */
                p13_stage = P13_STAGE_WAIT_WRITE_6_RESPONSE;
                p13_set_deadline();
                g_timeout_add(1000, p13_post_writes_settle_cb, NULL);
            }
            break;
'''
    text = _replace_once(
        text,
        old_write_completed,
        new_write_completed,
        "peer/TAP send-only write progression",
    )

    close_fn = '''static gboolean
p13_queue_close_ctpp(void)
{
    return p13_queue_close_channel(
        ctpp_channel_id,
        P13_TX_CLOSE_CTPP
    );
}
'''
    close_with_callbacks = close_fn + '''

static gboolean
p13_register_settle_cb(gpointer data)
{
    (void)data;

    if (p13_stage != P13_STAGE_WAIT_WRITE_1_RESPONSE ||
        p13_writes_sent != 1) {
        return G_SOURCE_REMOVE;
    }

    p13_deadline_us = 0;
    p13_stage = P13_STAGE_WRITE_2_TX;
    if (!p13_queue_door_write(2)) {
        p13_failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }

    return G_SOURCE_REMOVE;
}


static gboolean
p13_post_writes_settle_cb(gpointer data)
{
    (void)data;

    if (p13_stage != P13_STAGE_WAIT_WRITE_6_RESPONSE ||
        p13_writes_sent != p13_door_write_count) {
        return G_SOURCE_REMOVE;
    }

    p13_deadline_us = 0;
    p13_stage = P13_STAGE_CLOSE_CTPP_TX;
    if (!p13_queue_close_ctpp()) {
        p13_failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }

    return G_SOURCE_REMOVE;
}
'''
    text = _replace_once(
        text,
        close_fn,
        close_with_callbacks,
        "peer/TAP settle callbacks",
    )

    old_ack_block = '''        if (p13_stage >= P13_STAGE_WAIT_WRITE_1_RESPONSE &&
            p13_stage <= P13_STAGE_WAIT_WRITE_6_RESPONSE) {

            guint write_index =
                (p13_stage - P13_STAGE_WAIT_WRITE_1_RESPONSE) / 2 + 1;

            if (request_id != ctpp_channel_id) {
                fprintf(stderr, "P13_DOOR_WRITE_REQUEST_ID=FAIL\\n");
                return FALSE;
            }

            p13_writes_sent = write_index;
            printf(
                "P13_DOOR_WRITE_%u_ACKED=true\\n",
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
'''
    new_inbound_block = '''        if (request_id == ctpp_channel_id &&
            p13_ctpp_open_ok &&
            p13_stage >= P13_STAGE_WRITE_1_TX &&
            p13_stage <= P13_STAGE_WAIT_CTPP_CLOSE_RESPONSE) {

            /* Peer/TAP does not require a response to any Door write. Any
             * CTPP frame observed here is informational and must not advance
             * or retry the actuator sequence. */
            printf("P13_DOOR_INBOUND_FRAME_OBSERVED=true\\n");
            fflush(stdout);
            p13_consume_post_ack(frame_len);
            continue;
        }
'''
    text = _replace_once(
        text,
        old_ack_block,
        new_inbound_block,
        "peer/TAP non-blocking inbound handling",
    )

    required = (
        "g_timeout_add(200, p13_register_settle_cb, NULL);",
        "g_timeout_add(1000, p13_post_writes_settle_cb, NULL);",
        "P13_DOOR_INBOUND_FRAME_OBSERVED=true",
        "p13_writes_sent = p13_write_index;",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"peer/TAP timing patch missing marker: {marker}")
    if "P13_DOOR_WRITE_%u_ACKED=true" in text:
        raise RuntimeError("peer/TAP candidate still requires per-write Door ACKs")

    return text


def transform(source: str, payload: dict, ctpp_address: str) -> str:
    original_helpers = module.p13_helpers

    def helpers_with_distinct_final_timer() -> str:
        text = original_helpers()
        old = """            g_timeout_add(\n                250,\n                pseudotcp_success_quit_cb,\n                NULL\n            );"""
        new = """            g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb,\n                NULL\n            );"""
        if text.count(old) != 1:
            raise RuntimeError("expected one final P13 success timer in helper block")
        return text.replace(old, new, 1)

    module.p13_helpers = helpers_with_distinct_final_timer
    try:
        transformed = module.transform(source, payload)
    finally:
        module.p13_helpers = original_helpers

    old_open = '''static gboolean
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
'''
    transformed = _replace_once(
        transformed,
        old_open,
        _ctpp_open_builder(ctpp_address),
        "CTPP OpenRequestExtension builder",
    )

    # OPEN responses may legally carry an extension. CLOSE responses remain
    # exact 12-byte control bodies. Accept an OPEN extension only when its
    # declared length matches the remaining body exactly; its value is not
    # needed for the one-shot Door transaction and is never printed.
    old_parser = '''    if (body_len != 12 ||
        read_le16(body + 0) != expected_magic ||
        read_le16(body + 2) != expected_opcode ||
        read_le32(body + 4) != 4) {

        return FALSE;
    }
'''
    new_parser = '''    if (body_len < 12 ||
        read_le16(body + 0) != expected_magic ||
        read_le16(body + 2) != expected_opcode ||
        read_le32(body + 4) != 4) {

        return FALSE;
    }

    if (expected_opcode == 4 && body_len != 12)
        return FALSE;

    if (expected_opcode == 2 && body_len > 12) {
        if (body_len < 16)
            return FALSE;
        guint32 extension_len = read_le32(body + 12);
        if (extension_len != body_len - 16u)
            return FALSE;
    }
'''
    transformed = _replace_once(
        transformed,
        old_parser,
        new_parser,
        "optional OPEN response extension parser",
    )

    transformed = _apply_peer_timing(transformed)

    final_timer = "g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb"
    premature_timer = "g_timeout_add(\n        250,\n        pseudotcp_success_quit_cb"
    if transformed.count(final_timer) != 1:
        raise RuntimeError("final P13 success timer is not preserved exactly once")
    if premature_timer in transformed:
        raise RuntimeError("premature baseline UAUT success timer remains")
    if transformed.count("if (!p13_begin_auth())") != 1:
        raise RuntimeError("UAUT-open handoff to P13 auth is not unique")

    if transformed.count("guint8 body[30];") != 1:
        raise RuntimeError("P13 candidate must contain exactly one extended CTPP OPEN builder")
    if "write_le32(body + 16, (guint32)sizeof(ctpp_extension_payload));" not in transformed:
        raise RuntimeError("P13 CTPP OPEN extension length is missing")
    if "extension_len != body_len - 16u" not in transformed:
        raise RuntimeError("P13 OPEN response extension validation is missing")
    if "P13_DOOR_WRITE_%u_ACKED=true" in transformed:
        raise RuntimeError("P13 peer/TAP candidate must not require Door write ACKs")

    return transformed


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe entry point for P13 holder transformation")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    ctpp_address = _load_bound_ctpp_address(payload)
    transformed = transform(source, payload, ctpp_address)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(transformed, encoding="utf-8")

    print("P13_HOLDER_TRANSFORM_SAFE=PASS")
    print("P13_PREMATURE_UAUT_SUCCESS_TIMER=false")
    print("P13_FINAL_SUCCESS_TIMER_COUNT=1")
    print("P13_UAUT_AUTH_HANDOFF=PASS")
    print("P13_CTPP_OPEN_EXTENSION=PASS")
    print("P13_PEER_TAP_WRITE_TIMING=PASS")
    print("P13_DOOR_WRITE_ACK_REQUIRED=false")
    print("P13_CTPP_ADDRESS_UCFG_BINDING=PASS")
    print("P13_CTPP_ADDRESS_VALUE_EMITTED=false")
    print(f"P13_PAYLOAD_WRITE_COUNT={len(payload['bodies'])}")
    print("P13_RETRY_SURFACE_PRESENT=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
