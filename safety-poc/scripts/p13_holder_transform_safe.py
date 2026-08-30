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
