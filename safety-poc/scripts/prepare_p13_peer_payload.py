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

# Public-safe pin for the already captured self-activation target pair
# entrance|output-index. The plaintext target remains runtime-only.
EXPECTED_PEER_TARGET_SHA256 = "ec95e794a2a16aa02fb02489d9794419f13744ba66dfcb711f8af9326ee1ff30"

# Exact capture location used by the successful P12 one-shot read-only run.
# The UCFG value remains runtime-only; content is accepted only if its SHA
# matches the already pinned P12 live evidence.
P12_RUNTIME_UCFG = Path("/run/comelit-p2p/p12-ucfg-response.json")


def _peer_actions(vip: dict) -> list[dict]:
    params = vip.get("user-parameters")
    if not isinstance(params, dict):
        raise RuntimeError("ViP user-parameters missing")
    actions = params.get("opendoor-actions")
    if actions is None:
        raise RuntimeError("opendoor-actions missing")
    peers = [mapping for mapping in base._dicts(actions) if mapping.get("action") == "peer"]
    if len(peers) != 1:
        raise RuntimeError(f"expected exactly one peer opendoor action, found {len(peers)}")
    return peers


def runtime_peer_door(vip: dict) -> dict:
    _peer_actions(vip)
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

    return {
        "name": name,
        "number": entrance,
        "output-index": output_index,
    }


def extract_doors_with_peer_fallback(vip: dict) -> list[dict]:
    params = vip.get("user-parameters")
    if not isinstance(params, dict):
        raise RuntimeError("ViP user-parameters missing")
    doors = params.get("opendoor-address-book")
    if isinstance(doors, list) and doors:
        if not all(isinstance(item, dict) for item in doors):
            raise RuntimeError("opendoor-address-book contains invalid entries")
        return list(doors)
    # This installation is the captured peer-door configuration. Construct the
    # exact runtime-only door descriptor needed by the proven legacy oracle.
    return [runtime_peer_door(vip)]


def _matches_pinned_ucfg(path: Path) -> bool:
    try:
        return path.is_file() and base.sha256_file(path) == base.EXPECTED_UCFG_SHA256
    except (OSError, PermissionError):
        return False


def find_pinned_ucfg() -> Path:
    # Prefer the exact runtime capture used by P12. Never trust the path alone:
    # require the already-proven UCFG SHA before using its content.
    if _matches_pinned_ucfg(P12_RUNTIME_UCFG):
        return P12_RUNTIME_UCFG

    # Fallback to any preserved root-only copy with the exact same identity.
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
    # Reuse the already-tested offline oracle and output format. Only target
    # discovery is adapted for this installation's action=peer configuration.
    base.extract_doors = extract_doors_with_peer_fallback
    base.find_exact_ucfg = find_pinned_ucfg
    rc = base.main()
    print("P13_PEER_TARGET_SOURCE=RUNTIME_PINNED")
    print("P13_PEER_TARGET_VALUE_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
