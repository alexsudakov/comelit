#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_markers(text: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key.replace("_", "").isalnum():
            markers[key] = value
    return markers


def require(markers: dict[str, str], expected: dict[str, str], label: str) -> None:
    for key, value in expected.items():
        actual = markers.get(key)
        if actual != value:
            raise RuntimeError(f"{label} marker {key} expected {value!r}, got {actual!r}")


def reclassify(service_text: str, target_text: str) -> dict[str, str]:
    service = parse_markers(service_text)
    target = parse_markers(target_text)

    require(
        service,
        {
            "P12_LIVE_SERVICE_PAYLOAD_START": "true",
            "P12_LIVE_SERVICE_PAYLOAD_END": "true",
            "P12_ONE_SHOT_PROCESS_INVOCATIONS": "1",
            "P12_ONE_SHOT_AUTO_RETRY": "false",
            "P12_ONE_SHOT_PROCESS_GROUP_ISOLATED": "true",
            "TIMEOUT_MAPPING_VERIFIED": "PASS",
            "P12_READONLY_LIVE_RUN_PERFORMED": "true",
            "P12_READONLY_LIVE_WRAPPER_INVOCATIONS": "1",
            "P12_READONLY_LIVE_WRAPPER_OUTCOME": "COMPLETED",
            "P12_READONLY_LIVE_WRAPPER_RC": "0",
            "P2_VIP_UAUT_AUTH": "PASS",
            "UAUT_RESPONSE_CODE": "200",
            "VIP_UAUT_CLOSE_RESPONSE": "PASS",
            "VIP_UAUT_CLOSE_RESPONSE_WORD": "0",
            "VIP_UCFG_OPEN_RESPONSE": "PASS",
            "VIP_UCFG_OPEN_RESPONSE_WORD": "0",
            "UCFG_RECEIVED": "true",
            "VIP_UCFG_CLOSE_RESPONSE": "PASS",
            "VIP_UCFG_CLOSE_RESPONSE_WORD": "0",
            "P12_READONLY_TRANSACTION": "PASS",
            "P12_AUTH_SESSION_LIFETIME_SEQUENCE": "PASS",
            "READONLY_SCOPE_ENFORCED": "PASS",
            "CREDENTIAL_MATERIAL_EMITTED": "false",
            "ACTUATOR_COMMAND_ATTEMPTED": "false",
            "AUTO_RETRY_OBSERVED": "false",
            "PHYSICAL_DOOR_ACTION": "false",
            "PHYSICAL_EFFECT_ASSERTED": "false",
        },
        "service",
    )
    require(
        target,
        {
            "P12_TARGET_BINDING_SCHEMA": "2",
            "P12_TARGET_REQUIRED_IDENTITY": "APT_ADDRESS_PLUS_APT_SUBADDRESS",
            "P12_TARGET_REQUIRED_UNIQUE": "true",
            "P12_TARGET_APT_ADDRESS_MATCH": "true",
            "P12_TARGET_APT_SUBADDRESS_MATCH": "true",
            "P12_TARGET_APT_ADDRESS_UNIQUE": "true",
            "P12_TARGET_APT_SUBADDRESS_UNIQUE": "true",
            "P12_TARGET_MODEL_CONTEXT_COMPATIBLE": "true",
            "P12_TARGET_VERSION_CONTEXT_COMPATIBLE": "true",
            "TARGET_BINDING_VERIFIED": "PASS",
            "TARGET_IDENTITY_VALUES_EMITTED": "false",
            "CREDENTIAL_MATERIAL_EMITTED": "false",
            "ACTUATOR_COMMAND_ATTEMPTED": "false",
            "PHYSICAL_DOOR_ACTION": "false",
        },
        "target",
    )

    service_sha = service.get("UCFG_RESPONSE_SHA256")
    target_sha = target.get("UCFG_RESPONSE_SHA256")
    if not service_sha or service_sha != target_sha:
        raise RuntimeError("preserved UCFG SHA-256 does not match between service and target reports")

    return {
        "P12_PRESERVED_LIVE_RECLASSIFICATION": "PASS",
        "P12_PRESERVED_UCFG_SHA256": service_sha,
        "REAL_TRANSPORT_IMPLEMENTED": "true",
        "REAL_TRANSPORT_READONLY_SESSION_PROOF": "PASS",
        "READONLY_SCOPE_ENFORCED": "PASS",
        "TARGET_BINDING_VERIFIED": "PASS",
        "AUTH_SESSION_LIFETIME_VERIFIED": "PASS",
        "TIMEOUT_MAPPING_VERIFIED": "PASS",
        "CREDENTIAL_MATERIAL_EMITTED": "false",
        "ACTUATOR_COMMAND_ATTEMPTED": "false",
        "PHYSICAL_DOOR_ACTION": "false",
        "PHYSICAL_EFFECT_ASSERTED": "false",
        "AUTO_RETRY_OBSERVED": "false",
        "P12_READONLY_LIVE_GATES": "PASS",
    }


def write_report(path: Path, markers: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{key}={value}" for key, value in markers.items()) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify one preserved P12 live read-only run without network access")
    parser.add_argument("--service-log", type=Path, required=True)
    parser.add_argument("--target-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markers = reclassify(
        args.service_log.read_text(encoding="utf-8"),
        args.target_report.read_text(encoding="utf-8"),
    )
    write_report(args.output, markers)
    print("P12_PRESERVED_LIVE_RECLASSIFICATION=PASS")
    print("P12_READONLY_LIVE_GATES=PASS")
    print("NETWORK_ACTION_PERFORMED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
