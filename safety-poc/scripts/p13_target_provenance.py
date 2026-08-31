#!/usr/bin/env python3
"""Offline P13 target provenance verification.

The proof keeps the two independent identities separate:
- apartment identity: exact P12 UCFG + pinned apt-address/subaddress hashes;
- actuator identity: capture-pinned entrance/output semantic + prepared payload
  fingerprint.

``opendoor-actions`` is advisory when absent, but contradictory metadata is a
hard failure: ABSENT != MISMATCH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

EXPECTED_UCFG_SHA256 = "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7"
EXPECTED_APT_ADDRESS_SHA256 = "baabc15b4b5496c0918278ab7475e3bfa5c5b257495137632f4a846ae4c040a6"
EXPECTED_APT_SUBADDRESS_SHA256 = "7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451"
EXPECTED_PEER_TARGET_SHA256 = "ec95e794a2a16aa02fb02489d9794419f13744ba66dfcb711f8af9326ee1ff30"
EXPECTED_TARGET_FINGERPRINT = "832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce"
EXPECTED_OUTPUT_INDEX = 1
DEFAULT_UCFG = Path("/run/comelit-p2p/p12-ucfg-response.json")
DEFAULT_PAYLOAD = Path("/root/comelit-p13-actuator-prep/real-door-payloads.json")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _scalar_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    return None


def unique_pinned_scalar(doc: object, key: str, expected_sha256: str) -> str:
    values: list[str] = []
    for mapping in _walk(doc):
        if key in mapping:
            text = _scalar_text(mapping[key])
            if text is not None:
                values.append(text)
    if len(values) != 1:
        raise RuntimeError(f"expected exactly one scalar {key}, found {len(values)}")
    if sha256_bytes(values[0].encode("utf-8")) != expected_sha256:
        raise RuntimeError(f"pinned {key} identity mismatch")
    return values[0]


def opendoor_action_entries(doc: object) -> tuple[bool, list[dict]]:
    present = False
    entries: list[dict] = []
    for mapping in _walk(doc):
        if "opendoor-actions" not in mapping:
            continue
        present = True
        value = mapping["opendoor-actions"]
        if isinstance(value, dict):
            entries.append(value)
        elif isinstance(value, list):
            entries.extend(item for item in value if isinstance(item, dict))
    return present, entries


def classify_ucfg_output(doc: object) -> tuple[bool, str]:
    present, entries = opendoor_action_entries(doc)
    if not present or not entries:
        return present, "ABSENT"

    peer_entries = [entry for entry in entries if str(entry.get("action", "")).lower() == "peer"]
    if not peer_entries:
        return True, "MISMATCH"

    values: set[int] = set()
    incomplete = False
    for entry in peer_entries:
        value = entry.get("output-index")
        if isinstance(value, bool) or value is None:
            incomplete = True
            continue
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str) and value.isdigit():
            parsed = int(value)
        else:
            incomplete = True
            continue
        values.add(parsed)

    if incomplete or not values:
        return True, "MISMATCH"
    if values == {EXPECTED_OUTPUT_INDEX}:
        return True, "MATCH"
    return True, "MISMATCH"


def pair_pins(body: bytes) -> set[str]:
    pins: set[str] = set()
    marker = b"\x00\x2d"
    start = 0
    while True:
        pos = body.find(marker, start)
        if pos < 0:
            break
        field_start = pos + 2
        for width in (10, 9, 8):
            end = field_start + width
            if end >= len(body):
                continue
            raw = body[field_start:end]
            address = raw.rstrip(b"\x00")
            if len(address) != 8 or not all(48 <= value <= 57 for value in address):
                continue
            if raw[len(address) :] not in (b"", b"\x00", b"\x00\x00"):
                continue
            output = body[end]
            pins.add(sha256_bytes(address + b"|" + str(output).encode("ascii")))
        start = pos + 1
    return pins


def prepared_capture_target_match_count(payload: dict) -> int:
    bodies = payload.get("bodies")
    if not isinstance(bodies, list):
        return 0
    count = 0
    for item in bodies:
        if not isinstance(item, dict) or not isinstance(item.get("hex"), str):
            continue
        try:
            body = bytes.fromhex(item["hex"])
        except ValueError:
            continue
        if EXPECTED_PEER_TARGET_SHA256 in pair_pins(body):
            count += 1
    return count


def find_exact_ucfg(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    elif DEFAULT_UCFG.is_file():
        candidates.append(DEFAULT_UCFG)

    if explicit is None:
        prune = {".config", ".ssh", ".cache", ".git", "node_modules", "__pycache__"}
        for base, dirs, files in os.walk("/root"):
            dirs[:] = [name for name in dirs if name not in prune]
            if "p12-ucfg-response.json" in files:
                path = Path(base) / "p12-ucfg-response.json"
                if path not in candidates:
                    candidates.append(path)

    matches = []
    for path in candidates:
        try:
            if path.is_file() and sha256_file(path) == EXPECTED_UCFG_SHA256:
                matches.append(path)
        except (OSError, PermissionError):
            continue
    if not matches:
        raise RuntimeError("exact pinned P12 UCFG snapshot not found")
    return sorted(matches, key=lambda value: str(value))[0]


def verify(ucfg_doc: object, payload: dict) -> dict[str, str]:
    unique_pinned_scalar(ucfg_doc, "apt-address", EXPECTED_APT_ADDRESS_SHA256)
    unique_pinned_scalar(ucfg_doc, "apt-subaddress", EXPECTED_APT_SUBADDRESS_SHA256)

    if payload.get("schema") != 1:
        raise RuntimeError("P13 payload schema mismatch")
    if payload.get("ucfg_sha256") != EXPECTED_UCFG_SHA256:
        raise RuntimeError("P13 payload is not bound to the exact P12 UCFG")
    if payload.get("target_fingerprint") != EXPECTED_TARGET_FINGERPRINT:
        raise RuntimeError("P13 prepared target fingerprint mismatch")
    bodies = payload.get("bodies")
    if not isinstance(bodies, list) or len(bodies) != 6:
        raise RuntimeError("P13 prepared payload must contain exactly six bodies")

    target_matches = prepared_capture_target_match_count(payload)
    if target_matches < 1:
        raise RuntimeError("prepared payload does not contain the capture-pinned entrance/output semantic")

    present, output_status = classify_ucfg_output(ucfg_doc)
    if output_status == "MISMATCH":
        raise RuntimeError("present UCFG opendoor-actions contradicts the capture-pinned output")

    return {
        "P13_APARTMENT_IDENTITY_SOURCE": "P12_UCFG",
        "P13_APARTMENT_IDENTITY_MATCH": "PASS",
        "P13_ENTRANCE_TARGET_SOURCE": "SELF_ACTIVATION_CAPTURE_PIN",
        "P13_ENTRANCE_TARGET_MATCH": "PASS",
        "P13_PREPARED_CAPTURE_TARGET_MATCH_COUNT": str(target_matches),
        "P13_UCFG_OPENDOOR_ACTION_PRESENT": str(present).lower(),
        "P13_UCFG_OUTPUT_INDEX": output_status,
        "P13_PREPARED_TARGET_FINGERPRINT_MATCH": "PASS",
        "P13_TARGET_VALUE_EMITTED": "false",
        "P13_TARGET_PROVENANCE": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline P13 target provenance gate")
    parser.add_argument("--ucfg", type=Path)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    print("P13_TARGET_PROVENANCE_START=true")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")

    ucfg_path = find_exact_ucfg(args.ucfg)
    payload_path = args.payload
    if not payload_path.is_file():
        raise RuntimeError("P13 prepared payload not found")
    info = payload_path.stat()
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != 0:
        raise RuntimeError("P13 prepared payload must be root-owned mode 0600")
    if sha256_file(ucfg_path) != EXPECTED_UCFG_SHA256:
        raise RuntimeError("P12 UCFG identity changed")

    ucfg_doc = json.loads(ucfg_path.read_text(encoding="utf-8"))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    result = verify(ucfg_doc, payload)
    result["P13_PROVENANCE_UCFG_SHA256"] = EXPECTED_UCFG_SHA256
    result["P13_PROVENANCE_PAYLOAD_SHA256"] = sha256_file(payload_path)
    result["NETWORK_ACTION_PERFORMED"] = "false"
    result["PHYSICAL_DOOR_ACTION"] = "false"
    result["SEND_ARMED_REACHED"] = "false"

    lines = [f"{key}={value}" for key, value in result.items()]
    for line in lines:
        print(line)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        args.report.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
