#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


# Expected values are capture-confirmed for the owner's intended ExtB target.
# Store only SHA-256 fingerprints in the repository so the public source does
# not disclose apartment/device identity values.
EXPECTED_VALUE_SHA256 = {
    "model": "382cbd67a020ce64cddd8e2930014f78783a3438048b3fb8d5091b28dc731e96",
    "version": "6040ca42ee4cca4715a67d0fad9b4d6f5b2ff157aadbacf7906fff0f2f267d4d",
    "apt-address": "baabc15b4b5496c0918278ab7475e3bfa5c5b257495137632f4a846ae4c040a6",
    "apt-subaddress": "7902699be42c8a8e46fbbb4501726517e86b22c56a189f7625a6da49081b2451",
}

# The UCFG response observed on the live read-only path does not necessarily
# include server-level model/version fields. Apartment address + subaddress are
# the target-specific identity tuple and must each be present exactly once and
# match the pinned fingerprints. model/version are consistency checks only: if
# present, at least one observed scalar must match the pinned value; absence is
# neutral rather than a binding failure.
REQUIRED_UNIQUE_KEYS = ("apt-address", "apt-subaddress")
OPTIONAL_CONTEXT_KEYS = ("model", "version")


@dataclass(frozen=True)
class TargetBindingResult:
    matches: dict[str, bool]
    observed_scalar_counts: dict[str, int]
    required_unique: dict[str, bool]
    optional_compatible: dict[str, bool]
    ucfg_sha256: str

    @property
    def verified(self) -> bool:
        required_ok = all(
            self.matches[key] and self.required_unique[key]
            for key in REQUIRED_UNIQUE_KEYS
        )
        optional_ok = all(self.optional_compatible[key] for key in OPTIONAL_CONTEXT_KEYS)
        return required_ok and optional_ok


def _scalar_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _walk_key_values(node: Any, wanted: set[str]) -> Iterable[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted:
                yield key, value
            yield from _walk_key_values(value, wanted)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_key_values(item, wanted)


def verify_payload(raw: bytes) -> TargetBindingResult:
    payload = json.loads(raw.decode("utf-8"))
    wanted = set(EXPECTED_VALUE_SHA256)
    observed: dict[str, list[str]] = {key: [] for key in wanted}

    for key, value in _walk_key_values(payload, wanted):
        text = _scalar_text(value)
        if text is not None:
            observed[key].append(hashlib.sha256(text.encode("utf-8")).hexdigest())

    matches = {
        key: EXPECTED_VALUE_SHA256[key] in observed[key]
        for key in sorted(wanted)
    }
    counts = {key: len(observed[key]) for key in sorted(wanted)}
    required_unique = {
        key: counts[key] == 1
        for key in REQUIRED_UNIQUE_KEYS
    }
    optional_compatible = {
        key: counts[key] == 0 or matches[key]
        for key in OPTIONAL_CONTEXT_KEYS
    }
    return TargetBindingResult(
        matches=matches,
        observed_scalar_counts=counts,
        required_unique=required_unique,
        optional_compatible=optional_compatible,
        ucfg_sha256=hashlib.sha256(raw).hexdigest(),
    )


def verify_file(path: Path) -> TargetBindingResult:
    st = path.stat()
    if not path.is_file():
        raise RuntimeError("UCFG capture is not a regular file")
    if os.geteuid() == 0:
        if st.st_uid != 0:
            raise RuntimeError("UCFG capture is not root-owned")
        if st.st_mode & 0o077:
            raise RuntimeError("UCFG capture permissions are broader than owner-only")
    return verify_payload(path.read_bytes())


def write_public_safe_report(path: Path, result: TargetBindingResult) -> None:
    lines = [
        "P12_TARGET_BINDING_SCHEMA=2",
        f"UCFG_RESPONSE_SHA256={result.ucfg_sha256}",
        "P12_TARGET_REQUIRED_IDENTITY=APT_ADDRESS_PLUS_APT_SUBADDRESS",
        "P12_TARGET_REQUIRED_UNIQUE=true",
        "P12_TARGET_OPTIONAL_CONTEXT=MODEL_VERSION_IF_PRESENT",
    ]
    marker_names = {
        "model": "P12_TARGET_MODEL_MATCH",
        "version": "P12_TARGET_VERSION_MATCH",
        "apt-address": "P12_TARGET_APT_ADDRESS_MATCH",
        "apt-subaddress": "P12_TARGET_APT_SUBADDRESS_MATCH",
    }
    for key in ("model", "version", "apt-address", "apt-subaddress"):
        lines.append(f"{marker_names[key]}={'true' if result.matches[key] else 'false'}")
        lines.append(f"P12_TARGET_{key.upper().replace('-', '_')}_OBSERVED_SCALARS={result.observed_scalar_counts[key]}")
    for key in REQUIRED_UNIQUE_KEYS:
        name = key.upper().replace("-", "_")
        lines.append(f"P12_TARGET_{name}_UNIQUE={'true' if result.required_unique[key] else 'false'}")
    for key in OPTIONAL_CONTEXT_KEYS:
        name = key.upper().replace("-", "_")
        lines.append(f"P12_TARGET_{name}_CONTEXT_COMPATIBLE={'true' if result.optional_compatible[key] else 'false'}")
    lines.extend(
        (
            "TARGET_IDENTITY_VALUES_EMITTED=false",
            "CREDENTIAL_MATERIAL_EMITTED=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
            f"TARGET_BINDING_VERIFIED={'PASS' if result.verified else 'FAIL'}",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the P12 UCFG response against the pinned target identity without emitting identity values."
    )
    parser.add_argument("--ucfg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = verify_file(args.ucfg)
    write_public_safe_report(args.output, result)
    return 0 if result.verified else 3


if __name__ == "__main__":
    raise SystemExit(main())
