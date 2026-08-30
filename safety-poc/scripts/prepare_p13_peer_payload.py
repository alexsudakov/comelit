#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import prepare_p13_real_payloads as base

# Public-safe pins. Plaintext apartment/entrance identities remain runtime-only.
# The apartment tuple is proven by the P12 UCFG capture. The entrance/output
# pair is independently pinned from the captured self-activation Door target.
EXPECTED_PEER_TARGET_SHA256 = "ec95e794a2a16aa02fb02489d9794419f13744ba66dfcb711f8af9326ee1ff30"
EXPECTED_APT_ADDRESS_SHA256 = "baabc15b4b5496c0918278ab7475e3bfa5c5b257495137632f4a846ae4c040a6"
EXPECTED_APT_SUBADDRESS_SHA256 = "7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451"

# Exact capture location used by the successful P12 one-shot read-only run.
P12_RUNTIME_UCFG = Path("/run/comelit-p2p/p12-ucfg-response.json")


def _scalar_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _key_scalars(node: object, key: str) -> list[str]:
    values: list[str] = []
    if isinstance(node, dict):
        for current_key, value in node.items():
            if current_key == key:
                text = _scalar_text(value)
                if text is not None:
                    values.append(text)
            values.extend(_key_scalars(value, key))
    elif isinstance(node, list):
        for item in node:
            values.extend(_key_scalars(item, key))
    return values


def _unique_pinned_scalar(node: object, key: str, expected_sha256: str) -> str:
    values = _key_scalars(node, key)
    if len(values) != 1:
        raise RuntimeError(f"expected exactly one scalar {key}, found {len(values)}")
    value = values[0]
    actual = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(f"pinned {key} identity mismatch")
    return value


def extract_vip_for_peer(doc: object) -> dict:
    # The successful P12 UCFG snapshot proves the apartment identity but does
    # not carry the action=peer metadata seen in a separate self-activation
    # capture. Packet construction does not require that action metadata: the
    # pinned legacy open_door path uses apartment address/subaddress for CTPP
    # and the selected output index for the six Door writes.
    apt_address = _unique_pinned_scalar(doc, "apt-address", EXPECTED_APT_ADDRESS_SHA256)
    apt_subaddress = _unique_pinned_scalar(doc, "apt-subaddress", EXPECTED_APT_SUBADDRESS_SHA256)
    return {
        "apt-address": apt_address,
        "apt-subaddress": apt_subaddress,
    }


def runtime_peer_door(_vip: dict) -> dict:
    entrance = os.environ.get("P13_PEER_ENTRANCE", "")
    output_raw = os.environ.get("P13_PEER_OUTPUT_INDEX", "")
    name = os.environ.get("P13_PEER_ENTRANCE_NAME", "peer")

    if not re.fullmatch(r"[0-9]{8}", entrance):
        raise RuntimeError("P13_PEER_ENTRANCE must be exactly 8 decimal digits")
    if not re.fullmatch(r"[0-9]+", output_raw):
        raise RuntimeError("P13_PEER_OUTPUT_INDEX must be a decimal integer")
    output_index = int(output_raw)
    if not 0 <= output_index <= 255:
        raise RuntimeError("P13_PEER_OUTPUT_INDEX out of range")

    material = f"{entrance}|{output_index}".encode("ascii")
    actual = hashlib.sha256(material).hexdigest()
    if actual != EXPECTED_PEER_TARGET_SHA256:
        raise RuntimeError("P13 peer runtime target does not match captured self-activation target pin")

    # open_door() consumes output-index for the actuator frames. Preserve both
    # historical address spellings in the runtime-only descriptor; `number` is
    # also part of the public-safe target fingerprint produced by the prep code.
    return {
        "name": name,
        "number": entrance,
        "apt-address": entrance,
        "output-index": output_index,
    }


def extract_doors_for_peer(vip: dict) -> list[dict]:
    return [runtime_peer_door(vip)]


def _matches_pinned_ucfg(path: Path) -> bool:
    try:
        return path.is_file() and base.sha256_file(path) == base.EXPECTED_UCFG_SHA256
    except (OSError, PermissionError):
        return False


def find_pinned_ucfg() -> Path:
    if _matches_pinned_ucfg(P12_RUNTIME_UCFG):
        return P12_RUNTIME_UCFG

    matches: list[Path] = []
    for path in base._walk_ucfg_candidates():
        if _matches_pinned_ucfg(path):
            matches.append(path)
    if not matches:
        raise RuntimeError(
            "pinned P12 UCFG snapshot not found at /run capture or preserved root artifacts"
        )
    return sorted(matches, key=lambda value: str(value))[0]


def main() -> int:
    # Reuse the proven legacy packet-construction oracle with all network methods
    # replaced. Adapt only UCFG layout and the independently pinned peer target.
    base.extract_vip = extract_vip_for_peer
    base.extract_doors = extract_doors_for_peer
    base.find_exact_ucfg = find_pinned_ucfg
    rc = base.main()
    print("P13_PEER_TARGET_SOURCE=RUNTIME_PINNED")
    print("P13_PEER_TARGET_VALUE_EMITTED=false")
    print("P13_PEER_ACTION_METADATA_REQUIRED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
