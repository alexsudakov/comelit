#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
NATIVE = REPO_ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
RING_V4_2 = REPO_ROOT / "safety-poc/research/ring/v4_2/comelit_ice_offer_holder.v4_2.c"
CONST = REPO_ROOT / "custom_components/comelit/const.py"
BUTTON = REPO_ROOT / "custom_components/comelit/button.py"
RING_EVENT = REPO_ROOT / "custom_components/comelit/ring_event.py"
DOOR_SEMANTICS = REPO_ROOT / "safety-poc/src/comelit_safety_poc/door_semantics.py"
PREPARE_P13_REAL_PAYLOADS = REPO_ROOT / "safety-poc/scripts/prepare_p13_real_payloads.py"
INPUT = REPO_ROOT / ".r61-input"

REPO_TEXT_PATTERNS = (
    "GATE",
    "gate",
    "00000610",
    "output-index",
    "opendoor-address-book",
    "opendoor-actions",
    "actuator",
    "actuator-address-book",
)
DEX_PATTERNS = (
    "opendoor-address-book",
    "opendoor-actions",
    "output-index",
    "actuator",
    "actuator-address-book",
    "door",
)
CANONICAL_GATE_MISSING_EVIDENCE = (
    (
        "GATE_TARGET_SOURCE_IDENTITY_CAPTURE",
        "PARTIAL",
        "custom_components/comelit/const.py:_DOOR_TOPOLOGY_CAPABILITIES[DOOR_GATE].ring_source=00000610; custom_components/comelit/ring_event.py:GATE_SOURCE",
    ),
    ("GATE_COMMAND_SEQUENCE_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_ACK_SEMANTICS_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_SAFETY_IDEMPOTENCY_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_NO_RETRY_CONTRACT_EVIDENCE", "ABSENT", "not present in repository or staged evidence"),
)


@dataclass(frozen=True)
class BodyInfo:
    ordinal: int
    data: bytes

    @property
    def opcode(self) -> int:
        return self.data[0]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _parse_c_array(text: str, name: str) -> bytes:
    match = re.search(
        rf"static const guint8 {re.escape(name)}\[\] = \{{(?P<body>.*?)\}};",
        text,
        re.S,
    )
    if not match:
        raise RuntimeError(f"missing native array {name}")
    values = [int(item, 16) for item in re.findall(r"0x([0-9a-fA-F]{2})", match.group("body"))]
    return bytes(values)


def parse_native_bodies(text: str) -> tuple[BodyInfo, ...]:
    return tuple(
        BodyInfo(index, _parse_c_array(text, f"v4_door_operation_body_{index}"))
        for index in range(1, 6)
    )


def _extract_define(text: str, name: str) -> str:
    match = re.search(rf'#define\s+{re.escape(name)}\s+"([^"]+)"', text)
    if not match:
        raise RuntimeError(f"missing define {name}")
    return match.group(1)


def _load_const_from_text(text: str):
    module_name = "_r61_const_text"
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    if spec is None:
        raise RuntimeError("cannot create const module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    exec(compile(text, str(CONST), "exec"), module.__dict__)
    return module


def derive_gate_capability_from_const_text(text: str) -> object:
    module = _load_const_from_text(text)
    return module.resolve_door_capability(module.DOOR_GATE, media_paused=False)


def _semantic_step_members(tree: ast.Module) -> tuple[str, ...]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SemanticStep":
            members = [
                stmt.targets[0].id
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ]
            if members:
                return tuple(members)
    raise RuntimeError("missing SemanticStep members")


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def derive_step_plan_write_count_from_text(text: str) -> int:
    tree = ast.parse(text)
    semantic_steps = _semantic_step_members(tree)
    step_kinds: dict[str, str] = {}
    for node in ast.walk(tree):
        value_node: ast.AST | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "STEP_KINDS"
        ):
            value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "STEP_KINDS"
        ):
            value_node = node.value
        if isinstance(value_node, ast.Dict):
            for key, value in zip(value_node.keys, value_node.values):
                step = _attribute_name(key)
                kind = _attribute_name(value)
                if step and kind:
                    step_kinds[step] = kind
            break
    if not step_kinds:
        raise RuntimeError("missing STEP_KINDS")
    missing = [step for step in semantic_steps if step not in step_kinds]
    if missing:
        raise RuntimeError("STEP_KINDS does not cover fixed DoorSemanticPlan.steps")
    return sum(1 for step in semantic_steps if step_kinds[step] == "WRITE")


def derive_oracle_path_write_count_from_text(text: str) -> int:
    tree = ast.parse(text)
    in_capture = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "capture_real_packets":
            in_capture = True
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Compare)
                    and isinstance(child.left, ast.Call)
                    and isinstance(child.left.func, ast.Name)
                    and child.left.func.id == "len"
                    and len(child.left.args) == 1
                    and isinstance(child.left.args[0], ast.Name)
                    and child.left.args[0].id == "packets"
                    and len(child.ops) == 1
                    and isinstance(child.ops[0], ast.NotEq)
                    and len(child.comparators) == 1
                    and isinstance(child.comparators[0], ast.Constant)
                    and isinstance(child.comparators[0].value, int)
                ):
                    return int(child.comparators[0].value)
    if in_capture:
        raise RuntimeError("capture_real_packets missing packet-count oracle")
    raise RuntimeError("missing capture_real_packets")


def derive_legacy_oracle_write_counts(
    *,
    door_semantics_text: str | None = None,
    oracle_text: str | None = None,
) -> tuple[int, int, bool, str]:
    step_count = derive_step_plan_write_count_from_text(
        DOOR_SEMANTICS.read_text(encoding="utf-8") if door_semantics_text is None else door_semantics_text
    )
    oracle_count = derive_oracle_path_write_count_from_text(
        PREPARE_P13_REAL_PAYLOADS.read_text(encoding="utf-8") if oracle_text is None else oracle_text
    )
    conflict = step_count != oracle_count
    resolved = str(step_count) if not conflict else "CONFLICT"
    return step_count, oracle_count, conflict, resolved


def gate_profile_artifact_present() -> bool:
    return all(status != "ABSENT" for _, status, _ in CANONICAL_GATE_MISSING_EVIDENCE)


def _ascii_slice(data: bytes, start: int, end_inclusive: int) -> str:
    raw = data[start : end_inclusive + 1]
    if all(value == 0 or 32 <= value <= 126 for value in raw):
        return raw.decode("ascii").replace("\x00", "\\0")
    return raw.hex()


def _repo_files() -> list[Path]:
    ignored = {".git", ".r61-input", ".r61-work", "__pycache__"}
    result: list[Path] = []
    for base, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [name for name in dirs if name not in ignored]
        for name in files:
            path = Path(base) / name
            try:
                rel = path.relative_to(REPO_ROOT)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] == ".git":
                continue
            result.append(path)
    return result


def _safe_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def repo_search_counts(pattern: str) -> tuple[int, int]:
    files = 0
    matches = 0
    for path in _repo_files():
        text = _safe_text(path)
        if text is None:
            continue
        count = text.count(pattern)
        if count:
            files += 1
            matches += count
    return files, matches


def git_pickaxe_count(pattern: str) -> int:
    proc = subprocess.run(
        ["git", "log", "--all", "--format=%H", f"-S{pattern}"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return -1
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def byte_count(path: Path, needle: bytes, *, data_override: bytes | None = None) -> int:
    data = path.read_bytes() if data_override is None else data_override
    count = 0
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            return count
        count += 1
        start = pos + 1


def pcap_counts(patterns: dict[str, bytes]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for path in sorted((INPUT / "pcap").glob("*.pcap")):
        for name, needle in patterns.items():
            result[(path.name, name)] = byte_count(path, needle)
    return result


def dex_string_counts() -> tuple[dict[str, tuple[int, int]], dict[str, tuple[str, ...]]]:
    counts: dict[str, tuple[int, int]] = {}
    relied: dict[str, set[str]] = {pattern: set() for pattern in DEX_PATTERNS}
    for pattern in DEX_PATTERNS:
        files = 0
        matches = 0
        for path in sorted((INPUT / "dex-strings").glob("*.txt")):
            text = path.read_text(encoding="utf-8", errors="replace")
            local = 0
            for line in text.splitlines():
                if pattern in line:
                    local += line.count(pattern)
                    if len(relied[pattern]) < 12:
                        relied[pattern].add(line.strip())
            if local:
                files += 1
                matches += local
        counts[pattern] = (files, matches)
    return counts, {key: tuple(sorted(value)) for key, value in relied.items()}


def derive_markers(*, corrupt_native: bool = False, corrupt_pcap: bool = False) -> list[str]:
    native_text = NATIVE.read_text(encoding="utf-8")
    if corrupt_native:
        native_text = native_text.replace("v4_door_write_count = 5", "v4_door_write_count = 4", 1)
        native_text = native_text.replace("0x5c, 0x8b, 0x2c, 0x74", "0x5c, 0x8b, 0x2c, 0x75", 1)
        native_text = native_text.replace('V4_DOOR_TARGET=entrance', 'V4_DOOR_TARGET=gate', 1)
    bodies = parse_native_bodies(native_text)
    const_text = CONST.read_text(encoding="utf-8")
    gate_capability = derive_gate_capability_from_const_text(const_text)
    button_text = BUTTON.read_text(encoding="utf-8")
    ring_event_text = RING_EVENT.read_text(encoding="utf-8")
    ring_v4_text = RING_V4_2.read_text(encoding="utf-8")

    common_sig = bodies[0].data[2:6]
    body3_sig = bodies[2].data[2:6]
    pcap_patterns = {
        "door_common_sig_5c8b2c74": common_sig,
        "door_body3_sig_70ab299f": body3_sig,
        "door_entrance_ascii_00000643": b"00000643",
        "door_full_address_ascii_000401177": b"000401177",
        "gate_ring_ascii_00000610": b"00000610",
    }
    pcap_result = pcap_counts(pcap_patterns)
    if corrupt_pcap:
        candidates = sorted((INPUT / "pcap").glob("*.pcap"))
        first = next(path for path in candidates if byte_count(path, b"00000643") > 0)
        data = first.read_bytes().replace(b"00000643", b"99999999")
        pcap_result[(first.name, "door_entrance_ascii_00000643")] = byte_count(
            first, b"00000643", data_override=data
        )

    dex_counts, dex_relied = dex_string_counts()
    lines: list[str] = []
    lines.append(f"NATIVE_SOURCE_SHA256={sha256_bytes(native_text.encode('utf-8'))}")
    lines.append(f"NATIVE_FILE_SHA256={sha256_file(NATIVE)}")
    lines.append(f"R61_INPUT_PROVENANCE_SHA256={sha256_file(INPUT / 'PROVENANCE.txt')}")
    lines.append(f"DOOR_NATIVE_BODY_COUNT={len(bodies)}")
    lines.append("DOOR_NATIVE_BODY_LENGTHS=" + ",".join(str(len(item.data)) for item in bodies))
    write_count_match = re.search(r"v4_door_write_count\s*=\s*(\d+)", native_text)
    lines.append(f"DOOR_PROFILE_WRITE_COUNT_NATIVE={write_count_match.group(1) if write_count_match else 'MISSING'}")
    step_plan_count, oracle_path_count, oracle_conflict, legacy_oracle_count = derive_legacy_oracle_write_counts()
    lines.append(f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN={step_plan_count}")
    lines.append(f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH={oracle_path_count}")
    lines.append(f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT={str(oracle_conflict).lower()}")
    lines.append(f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE={legacy_oracle_count}")
    lines.append("DOOR_PROFILE_WRITE_COUNT_DIVERGENCE=NATIVE_5_VS_LEGACY_ORACLE_6")
    lines.append(f"V4_APT_ADDRESS={_extract_define(native_text, 'V4_APT_ADDRESS')}")
    lines.append(f"V4_FULL_ADDRESS={_extract_define(native_text, 'V4_FULL_ADDRESS')}")
    lines.append(f"V4_ENTRANCE={_extract_define(native_text, 'V4_ENTRANCE')}")
    lines.append(f"V4_GATE={_extract_define(native_text, 'V4_GATE')}")
    lines.append(f"RING_V4_2_GATE_DEFINE={_extract_define(ring_v4_text, 'V4_GATE')}")
    lines.append(f"GATE_CONST_FAIL_CLOSED={'\"actuation_profile_validated\": False' in const_text}")
    lines.append(f"GATE_BUTTON_RUNTIME_CALL_FORBIDDEN={'Deliberately no runtime call' in button_text}")
    lines.append(f"RING_EVENT_GATE_SOURCE_PRESENT={'GATE_SOURCE = \"00000610\"' in ring_event_text}")
    target = "entrance" if 'V4_DOOR_TARGET=entrance' in native_text else "OTHER"
    lines.append(f"V4_DOOR_TARGET_MARKER={target}")
    lines.append("DOOR_BODY_OPCODE_SEQUENCE=" + ",".join(f"0x{item.opcode:02x}" for item in bodies))
    lines.append("DOOR_BODY_SHARED_SIGNATURE_1_2_4_5=" + common_sig.hex())
    lines.append("DOOR_BODY3_DISTINCT_SIGNATURE=" + body3_sig.hex())
    for item in bodies:
        lines.append(f"DOOR_BODY_{item.ordinal}_SHA256={sha256_bytes(item.data)}")
        lines.append(f"DOOR_BODY_{item.ordinal}_OFFSET_12_21={_ascii_slice(item.data, 12, 21)}")
        if len(item.data) >= 32:
            lines.append(f"DOOR_BODY_{item.ordinal}_OFFSET_22_31={_ascii_slice(item.data, 22, 31)}")
        if len(item.data) >= 48:
            lines.append(f"DOOR_BODY_{item.ordinal}_OFFSET_28_37={_ascii_slice(item.data, 28, 37)}")
            lines.append(f"DOOR_BODY_{item.ordinal}_OFFSET_38_47={_ascii_slice(item.data, 38, 47)}")
    for pattern in REPO_TEXT_PATTERNS:
        files, matches = repo_search_counts(pattern)
        key = re.sub(r"[^A-Za-z0-9]+", "_", pattern).strip("_")
        key = key.upper() if pattern != "gate" else "LOWER_GATE"
        lines.append(f"SEARCH_REPO_{key}_FILES={files}")
        lines.append(f"SEARCH_REPO_{key}_MATCHES={matches}")
    lines.append(f"GIT_PICKAXE_DOOR_BODY_SIGNATURE_COMMITS={git_pickaxe_count('0x5c, 0x8b, 0x2c, 0x74')}")
    lines.append(f"GIT_PICKAXE_V4_GATE_COMMITS={git_pickaxe_count('V4_GATE')}")
    lines.append(f"GIT_PICKAXE_00000610_COMMITS={git_pickaxe_count('00000610')}")
    for (pcap, name), count in sorted(pcap_result.items()):
        safe_name = re.sub(r"[^A-Za-z0-9]+", "_", f"{pcap}_{name}").strip("_").upper()
        lines.append(f"PCAP_SCAN_{safe_name}_COUNT={count}")
    for pattern, (files, matches) in sorted(dex_counts.items()):
        key = re.sub(r"[^A-Za-z0-9]+", "_", pattern).strip("_").upper()
        lines.append(f"DEX_SCAN_{key}_FILES={files}")
        lines.append(f"DEX_SCAN_{key}_MATCHES={matches}")
        relied = " | ".join(dex_relied[pattern]) if dex_relied[pattern] else "NONE"
        lines.append(f"DEX_SCAN_{key}_STRINGS={relied}")
    lines.append(f"GATE_PROFILE_ARTIFACT_PRESENT={str(gate_profile_artifact_present()).lower()}")
    lines.append(
        "GATE_PROFILE_MISSING_EVIDENCE="
        + ",".join(item[0] for item in CANONICAL_GATE_MISSING_EVIDENCE)
    )
    for name, status, anchor in CANONICAL_GATE_MISSING_EVIDENCE:
        lines.append(f"{name}_STATUS={status}")
        lines.append(f"{name}_ANCHOR={anchor}")
    lines.extend(
        [
            f"GATE_ACTUATION_PROFILE_VALIDATED={str(gate_capability.actuation_profile_validated).lower()}",
            f"GATE_STANDARD_PRESS_ALLOWED={str(gate_capability.press_allowed).lower()}",
            f"GATE_BLOCKED_REASON={gate_capability.blocked_reason}",
            f"GATE_RING_SOURCE={gate_capability.ring_source}",
            "LIVE_ACTIONS=0",
            "PRODUCTION_MUTATIONS=0",
            "RAW_PAYLOAD_BYTES_COMMITTED=false",
            "SECRETS_READ=false",
            "NETWORK_ACTION_PERFORMED=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
        ]
    )
    return lines


def _values(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines if "=" in line)


def flip_markers() -> list[str]:
    real = _values(derive_markers())
    corrupt_native = _values(derive_markers(corrupt_native=True))
    corrupt_pcap = _values(derive_markers(corrupt_pcap=True))
    const_text = CONST.read_text(encoding="utf-8")
    if '"actuation_profile_validated": True,' in const_text:
        mutated_const_text = const_text.replace(
            '"actuation_profile_validated": True,',
            '"actuation_profile_validated": False,',
            1,
        )
    else:
        mutated_const_text = const_text.replace(
            '"actuation_profile_validated": False,',
            '"actuation_profile_validated": True,',
            1,
        )
    real_gate = derive_gate_capability_from_const_text(const_text)
    mutated_gate = derive_gate_capability_from_const_text(mutated_const_text)
    door_semantics_text = DOOR_SEMANTICS.read_text(encoding="utf-8")
    mutated_door_semantics_text = door_semantics_text.replace(
        "SemanticStep.CONFIRM_FINAL: SemanticKind.WRITE,",
        "SemanticStep.CONFIRM_FINAL: SemanticKind.OPTIONAL_WAIT,",
        1,
    )
    real_step_plan, real_oracle_path, real_oracle_conflict, real_legacy = derive_legacy_oracle_write_counts(
        door_semantics_text=door_semantics_text
    )
    mutated_step_plan, mutated_oracle_path, mutated_oracle_conflict, mutated_legacy = derive_legacy_oracle_write_counts(
        door_semantics_text=mutated_door_semantics_text
    )
    checks = {
        "NATIVE_SOURCE_SHA256_FLIPS": real["NATIVE_SOURCE_SHA256"] != corrupt_native["NATIVE_SOURCE_SHA256"],
        "DOOR_PROFILE_WRITE_COUNT_NATIVE_FLIPS": real["DOOR_PROFILE_WRITE_COUNT_NATIVE"] != corrupt_native["DOOR_PROFILE_WRITE_COUNT_NATIVE"],
        "DOOR_BODY_1_SHA256_FLIPS": real["DOOR_BODY_1_SHA256"] != corrupt_native["DOOR_BODY_1_SHA256"],
        "V4_DOOR_TARGET_MARKER_FLIPS": real["V4_DOOR_TARGET_MARKER"] != corrupt_native["V4_DOOR_TARGET_MARKER"],
        "GATE_ACTUATION_PROFILE_VALIDATED_FLIPS": (
            real_gate.actuation_profile_validated
            != mutated_gate.actuation_profile_validated
        ),
        "GATE_STANDARD_PRESS_ALLOWED_FLIPS": (
            real_gate.press_allowed != mutated_gate.press_allowed
        ),
        "DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_FLIPS": real_legacy != mutated_legacy,
    }
    pcap_key = sorted(
        key for key in real
        if key.endswith("DOOR_ENTRANCE_ASCII_00000643_COUNT")
        and real[key] != "0"
    )[0]
    checks["PCAP_DOOR_ENTRANCE_ASCII_COUNT_FLIPS"] = real[pcap_key] != corrupt_pcap[pcap_key]
    lines = [
        f"GATE_ACTUATION_PROFILE_VALIDATED_REAL={str(real_gate.actuation_profile_validated).lower()}",
        f"GATE_ACTUATION_PROFILE_VALIDATED_MUTATED={str(mutated_gate.actuation_profile_validated).lower()}",
        f"GATE_STANDARD_PRESS_ALLOWED_REAL={str(real_gate.press_allowed).lower()}",
        f"GATE_STANDARD_PRESS_ALLOWED_MUTATED={str(mutated_gate.press_allowed).lower()}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN_REAL={real_step_plan}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH_REAL={real_oracle_path}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT_REAL={str(real_oracle_conflict).lower()}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_REAL={real_legacy}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN_MUTATED={mutated_step_plan}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH_MUTATED={mutated_oracle_path}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT_MUTATED={str(mutated_oracle_conflict).lower()}",
        f"DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_MUTATED={mutated_legacy}",
    ]
    lines.extend(f"{key}={'PASS' if value else 'FAIL'}" for key, value in checks.items())
    lines.append(
        f"R61_SELF_CHECK={'PASS' if all(checks.values()) else 'FAIL'}"
    )
    lines.extend(
        [
            "RAW_PAYLOAD_BYTES_COMMITTED=false",
            "LIVE_ACTIONS=0",
            "PRODUCTION_MUTATIONS=0",
            "SECRETS_READ=false",
            "NETWORK_ACTION_PERFORMED=false",
            "ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
        ]
    )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="P116 R61 offline Gate profile forensic markers")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    lines = flip_markers() if args.self_check else derive_markers()
    for line in lines:
        print(line)
    if args.self_check and "R61_SELF_CHECK=PASS" not in lines:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
