#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_gate_common import (
    LEGACY_SOURCE,
    load_module_from_path,
    require_canonical_pins,
    require_legacy_pin,
)
import verify_legacy_synthetic_body_oracle as oracle

EXPECTED_UCFG_SHA256 = "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7"
CHANNEL_ID = 7449
OUTPUT_DIR = Path("/root/comelit-p13-actuator-prep")
OUTPUT_JSON = OUTPUT_DIR / "real-door-payloads.json"
MANIFEST = OUTPUT_DIR / "MANIFEST.txt"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _walk_ucfg_candidates(root: Path = Path("/root")):
    prune = {".config", ".ssh", ".cache", ".git", "node_modules", "__pycache__"}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in prune]
        if "p12-ucfg-response.json" in files:
            yield Path(base) / "p12-ucfg-response.json"


def find_exact_ucfg() -> Path:
    matches = []
    for path in _walk_ucfg_candidates():
        try:
            if sha256_file(path) == EXPECTED_UCFG_SHA256:
                matches.append(path)
        except (OSError, PermissionError):
            continue
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one pinned UCFG snapshot, found {len(matches)}")
    return matches[0]


def _dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _dicts(item)


def extract_vip(doc: object) -> dict:
    candidates: list[dict] = []
    seen: set[str] = set()
    for mapping in _dicts(doc):
        options = []
        vip = mapping.get("vip")
        if isinstance(vip, dict):
            options.append(vip)
        if "apt-address" in mapping and isinstance(mapping.get("user-parameters"), dict):
            options.append(mapping)
        for candidate in options:
            key = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one ViP configuration object, found {len(candidates)}")
    return candidates[0]


def extract_doors(vip: dict) -> list[dict]:
    params = vip.get("user-parameters")
    if not isinstance(params, dict):
        raise RuntimeError("ViP user-parameters missing")
    doors = params.get("opendoor-address-book")
    if not isinstance(doors, list) or not doors or not all(isinstance(x, dict) for x in doors):
        raise RuntimeError("opendoor-address-book is missing or empty")
    return list(doors)


def door_fingerprint(door: dict) -> str:
    material = json.dumps(
        {
            "name": door.get("name"),
            "number": door.get("number"),
            "output-index": door.get("output-index"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256_bytes(material)


def select_door(doors: list[dict], requested: str | None) -> tuple[int, dict]:
    fingerprints = [door_fingerprint(item) for item in doors]
    if requested:
        matches = [i for i, fp in enumerate(fingerprints) if fp == requested]
        if len(matches) != 1:
            raise RuntimeError("requested P13 target fingerprint is not unique")
        index = matches[0]
        return index, doors[index]
    if len(doors) == 1:
        return 0, doors[0]
    print("P13_TARGET_SELECTION_REQUIRED=true")
    print(f"P13_TARGET_COUNT={len(doors)}")
    for i, (door, fp) in enumerate(zip(doors, fingerprints), 1):
        name = str(door.get("name", ""))
        print(f"P13_TARGET_{i}_NAME={name}")
        print(f"P13_TARGET_{i}_FINGERPRINT={fp}")
    raise SystemExit(2)


async def capture_real_packets(vip: dict, door: dict) -> tuple[bytes, ...]:
    require_legacy_pin(LEGACY_SOURCE)
    legacy = load_module_from_path("_comelit_p13_real_oracle", LEGACY_SOURCE)
    client_cls = getattr(legacy, "IconaBridgeClient")
    signature = inspect.signature(client_cls)
    positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    args: list[object] = []
    if positional:
        args.append("offline.invalid")
    if len(positional) >= 2:
        args.append(0)
    client = client_cls(*args)

    captured: list[bytes] = []
    channel = SimpleNamespace(id=CHANNEL_ID, channel_id=CHANNEL_ID, name="CTPP", channel="CTPP")
    client.open_channels = oracle.SyntheticOpenChannels(channel, oracle._ctpp_keys(legacy))

    async def fake_open_channel(self, *args, **kwargs):
        oracle._bind_synthetic_ctpp_channel(self, legacy, channel)
        return channel

    async def fake_write_packet(self, packet):
        captured.append(bytes(packet))

    async def fake_read_response(self, *args, **kwargs):
        return oracle.SyntheticResponse()

    async def fake_close_channel(self, *args, **kwargs):
        return True

    client._open_channel = MethodType(fake_open_channel, client)
    client._write_packet = MethodType(fake_write_packet, client)
    client._read_response = MethodType(fake_read_response, client)
    client._close_channel = MethodType(fake_close_channel, client)

    await client.open_door(vip, door)
    packets = tuple(captured)
    if len(packets) != 6:
        raise RuntimeError(f"real offline oracle expected 6 writes, got {len(packets)}")
    if any(len(packet) <= 8 for packet in packets):
        raise RuntimeError("real offline oracle produced an invalid short frame")
    canonical = await oracle._canonical_reframe(packets)
    if canonical != packets:
        raise RuntimeError("canonical reframing differs from real legacy payload frames")
    return packets


def main() -> int:
    require_canonical_pins()
    require_legacy_pin(LEGACY_SOURCE)
    ucfg_path = find_exact_ucfg()
    raw = ucfg_path.read_bytes()
    if sha256_bytes(raw) != EXPECTED_UCFG_SHA256:
        raise RuntimeError("UCFG snapshot changed after selection")
    doc = json.loads(raw.decode("utf-8"))
    vip = extract_vip(doc)
    doors = extract_doors(vip)
    requested = os.environ.get("P13_TARGET_FINGERPRINT") or None
    index, door = select_door(doors, requested)
    target_fp = door_fingerprint(door)

    packets = asyncio.run(capture_real_packets(vip, door))
    bodies = tuple(packet[8:] for packet in packets)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.chmod(0o700)
    payload = {
        "schema": 1,
        "ucfg_sha256": EXPECTED_UCFG_SHA256,
        "target_index": index,
        "target_fingerprint": target_fp,
        "target_name": door.get("name"),
        "channel_id_fixture": CHANNEL_ID,
        "write_count": len(bodies),
        "bodies": [
            {"hex": body.hex(), "bytes": len(body), "sha256": sha256_bytes(body)}
            for body in bodies
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    OUTPUT_JSON.chmod(0o600)

    lines = [
        "P13_REAL_PAYLOAD_SCHEMA=1",
        f"UCFG_SHA256={EXPECTED_UCFG_SHA256}",
        f"TARGET_COUNT={len(doors)}",
        f"TARGET_INDEX={index}",
        f"TARGET_FINGERPRINT={target_fp}",
        "LEGACY_RESEARCH_SOURCE_HASH=PASS",
        "CANONICAL_VIP_SOURCE_HASHES=PASS",
        "LEGACY_SOURCE_EXECUTED_OFFLINE=true",
        "LEGACY_NETWORK_METHODS_REPLACED=true",
        "CTPP_CHANNEL_OPEN_EXECUTED=false",
        f"REAL_DOOR_WRITE_COUNT={len(bodies)}",
        "CANONICAL_FRAME_EQUIVALENCE=PASS",
    ]
    for i, body in enumerate(bodies, 1):
        lines.append(f"WRITE_{i}_BODY_BYTES={len(body)}")
        lines.append(f"WRITE_{i}_BODY_SHA256={sha256_bytes(body)}")
    lines += [
        "REAL_DOOR_PAYLOAD_VALUES_STORED_ROOT_ONLY=true",
        "REAL_DOOR_PAYLOAD_VALUES_EMITTED=false",
        "SECRETS_READ=false",
        "NETWORK_ACTION_PERFORMED=false",
        "ACTUATOR_COMMAND_ATTEMPTED=false",
        "PHYSICAL_DOOR_ACTION=false",
        "PHYSICAL_EFFECT_ASSERTED=false",
        "P13_REAL_PAYLOAD_PREP=PASS",
    ]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    MANIFEST.chmod(0o600)
    for line in lines:
        print(line)
    print(f"P13_REAL_PAYLOAD_LOCAL_FILE={OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
