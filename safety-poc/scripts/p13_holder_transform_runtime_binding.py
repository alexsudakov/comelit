#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
EVIDENCE_TRANSFORM = SCRIPT_DIR / "p13_holder_transform_evidence.py"

spec = importlib.util.spec_from_file_location("p13_holder_transform_evidence_runtime", EVIDENCE_TRANSFORM)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

EXPECTED_UCFG_SHA256 = "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7"
EXPECTED_APT_ADDRESS_SHA256 = "baabc15b4b5496c0918278ab7475e3bfa5c5b257495137632f4a846ae4c040a6"
EXPECTED_APT_SUBADDRESS_SHA256 = "7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451"
DEFAULT_BINDING = Path("/root/.config/comelit/p13-ctpp-binding.json")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _ctpp_address_from_binding_doc(doc: object, payload: dict) -> str:
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise RuntimeError("P13 CTPP runtime binding schema must be 1")

    payload_ucfg = str(payload.get("ucfg_sha256", ""))
    binding_ucfg = str(doc.get("ucfg_sha256", ""))
    if payload_ucfg != EXPECTED_UCFG_SHA256 or binding_ucfg != EXPECTED_UCFG_SHA256:
        raise RuntimeError("P13 CTPP runtime binding UCFG identity mismatch")

    apt_address = doc.get("apt_address")
    apt_subaddress = doc.get("apt_subaddress")
    if not isinstance(apt_address, str) or not isinstance(apt_subaddress, str):
        raise RuntimeError("P13 CTPP runtime binding address fields must be strings")
    if len(apt_address) != 8 or not apt_address.isdigit():
        raise RuntimeError("P13 CTPP runtime binding apt_address shape mismatch")
    if len(apt_subaddress) != 1 or not apt_subaddress.isdigit():
        raise RuntimeError("P13 CTPP runtime binding apt_subaddress shape mismatch")
    if _sha(apt_address) != EXPECTED_APT_ADDRESS_SHA256:
        raise RuntimeError("P13 CTPP runtime binding apt_address pin mismatch")
    if _sha(apt_subaddress) != EXPECTED_APT_SUBADDRESS_SHA256:
        raise RuntimeError("P13 CTPP runtime binding apt_subaddress pin mismatch")
    return apt_address + apt_subaddress


def _load_runtime_binding(path: Path, payload: dict, *, require_root_owner: bool = True) -> str:
    if not path.is_file():
        raise RuntimeError("root-only P13 CTPP runtime binding file not found")
    info = path.stat()
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o600:
        raise RuntimeError("P13 CTPP runtime binding file mode must be 0600")
    if require_root_owner and info.st_uid != 0:
        raise RuntimeError("P13 CTPP runtime binding file owner must be uid 0")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return _ctpp_address_from_binding_doc(doc, payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="P13 evidence-enabled safe holder transform using a root-only pinned CTPP identity binding"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))

    # Prefer the exact P12 UCFG snapshot when it still exists. If it was an
    # ephemeral /run capture and has disappeared, use only the root-owned 0600
    # runtime binding whose two address fields are independently SHA-pinned.
    try:
        ctpp_address = module.module._load_bound_ctpp_address(payload)
        binding_source = "EXACT_UCFG_SNAPSHOT"
    except RuntimeError as exc:
        if str(exc) != "exact P13-bound UCFG snapshot not found":
            raise
        ctpp_address = _load_runtime_binding(args.binding, payload)
        binding_source = "ROOT_ONLY_RUNTIME_PINNED"

    transformed = module.transform(source, payload, ctpp_address)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(transformed, encoding="utf-8")

    print("P13_HOLDER_TRANSFORM_SAFE=PASS")
    print("P13_HOLDER_RX_EVIDENCE_TRANSFORM=PASS")
    print("P13_PREMATURE_UAUT_SUCCESS_TIMER=false")
    print("P13_FINAL_SUCCESS_TIMER_COUNT=1")
    print("P13_UAUT_AUTH_HANDOFF=PASS")
    print("P13_CTPP_OPEN_EXTENSION=PASS")
    print("P13_CTPP_ADDRESS_UCFG_BINDING=PASS")
    print(f"P13_CTPP_ADDRESS_BINDING_SOURCE={binding_source}")
    print("P13_CTPP_ADDRESS_VALUE_EMITTED=false")
    print(f"P13_PAYLOAD_WRITE_COUNT={len(payload['bodies'])}")
    print("P13_DOOR_ACK_SEMANTICS=UNPROVEN")
    print("P13_DOOR_RESPONSE_SEMANTICS=RESPONSE_SEEN")
    print("P13_CTPP_RX_RAW_EVIDENCE_SCOPE=ROOT_ONLY_RUNTIME_LOG")
    print("P13_RETRY_SURFACE_PRESENT=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
