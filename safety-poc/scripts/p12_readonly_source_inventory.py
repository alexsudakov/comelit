#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


LEGACY_DEFAULT = Path("/root/comelit-poc/comelit_client.py")
CANONICAL_ROOT_DEFAULT = Path("/root/comelit-vip-poc/comelit_vip")

EXPECTED_HASHES = {
    "legacy": "03ea7d012587d8751eddfd5fa531d244abddc047c3a69d8ce27986c1e2768d42",
    "transport.py": "21ce339f15d44216baecdeefa19490a5d5632f689155d628b76d4abb7872a0d4",
    "vip_session.py": "35b604372e9bd42a6631d0c923ac99d49e02e4b7c8892360633eedc23425dc39",
    "channel_session.py": "b34d87c382ea601d96761f59a31e62aa2d1e959ea9c24e99a63964e1c033e1d1",
    "application_session.py": "7c30aab9bd03917e0e84fb9b31f924f95eabeb8edd6a1fe74d4e4f012c2145fd",
}

LEGACY_TARGETS = (
    "connect",
    "_test_nc_connection",
    "shutdown",
    "authenticate",
    "get_config",
    "list_doors",
)

CANONICAL_TARGETS = {
    "transport.py": ("VipTransport", ("read", "write", "close")),
    "vip_session.py": ("VipSession", ("send_frame", "recv_frame", "close")),
    "channel_session.py": ("VipChannelSession", ("open_channel", "close_channel", "close")),
    "application_session.py": (
        "VipApplicationSession",
        ("authenticate", "open_ucfg", "get_configuration", "close_channel"),
    ),
}


@dataclass(frozen=True)
class MethodShape:
    qualified_name: str
    line: int
    async_method: bool
    positional_args: tuple[str, ...]
    call_counts: tuple[tuple[str, int], ...]
    await_count: int
    try_count: int
    except_count: int
    return_count: int


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    if not parts:
        return type(node.func).__name__
    return ".".join(reversed(parts))


def method_shape(source: str, class_name: str, method_name: str) -> MethodShape:
    tree = ast.parse(source)
    selected: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                selected = child
                break
    if selected is None:
        raise ValueError(f"qualified method not found: {class_name}.{method_name}")

    calls = Counter(_call_name(node) for node in ast.walk(selected) if isinstance(node, ast.Call))
    args = tuple(arg.arg for arg in selected.args.args)
    return MethodShape(
        qualified_name=f"{class_name}.{method_name}",
        line=selected.lineno,
        async_method=isinstance(selected, ast.AsyncFunctionDef),
        positional_args=args,
        call_counts=tuple(sorted(calls.items())),
        await_count=sum(isinstance(node, ast.Await) for node in ast.walk(selected)),
        try_count=sum(isinstance(node, ast.Try) for node in ast.walk(selected)),
        except_count=sum(isinstance(node, ast.ExceptHandler) for node in ast.walk(selected)),
        return_count=sum(isinstance(node, ast.Return) for node in ast.walk(selected)),
    )


def render_shape(shape: MethodShape) -> list[str]:
    lines = [
        f"METHOD={shape.qualified_name}",
        f"LINE={shape.line}",
        f"ASYNC={'true' if shape.async_method else 'false'}",
        f"POSITIONAL_ARG_NAMES={','.join(shape.positional_args)}",
        f"AWAIT_COUNT={shape.await_count}",
        f"TRY_COUNT={shape.try_count}",
        f"EXCEPT_COUNT={shape.except_count}",
        f"RETURN_COUNT={shape.return_count}",
    ]
    for name, count in shape.call_counts:
        lines.append(f"CALL name={name} count={count}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-safe AST inventory for P12 read-only session planning")
    parser.add_argument("--legacy-source", type=Path, default=LEGACY_DEFAULT)
    parser.add_argument("--canonical-root", type=Path, default=CANONICAL_ROOT_DEFAULT)
    args = parser.parse_args()

    legacy_hash = sha256(args.legacy_source)
    if legacy_hash != EXPECTED_HASHES["legacy"]:
        print("LEGACY_SOURCE_HASH=FAIL")
        return 2

    canonical_paths = {name: args.canonical_root / name for name in CANONICAL_TARGETS}
    for name, path in canonical_paths.items():
        if sha256(path) != EXPECTED_HASHES[name]:
            print(f"CANONICAL_SOURCE_HASH_{name.replace('.', '_').upper()}=FAIL")
            return 2

    print("=== P12 READ-ONLY SOURCE INVENTORY ===")
    print("LEGACY_SOURCE_HASH=PASS")
    print("CANONICAL_SOURCE_HASHES=PASS")

    legacy_source = args.legacy_source.read_text(encoding="utf-8")
    for method_name in LEGACY_TARGETS:
        print()
        for line in render_shape(method_shape(legacy_source, "IconaBridgeClient", method_name)):
            print(line)

    for filename, (class_name, methods) in CANONICAL_TARGETS.items():
        source = canonical_paths[filename].read_text(encoding="utf-8")
        for method_name in methods:
            print()
            for line in render_shape(method_shape(source, class_name, method_name)):
                print(line)

    print()
    print("P12_READONLY_SOURCE_INVENTORY=PASS")
    print("SELECTED_METHODS_ONLY=true")
    print("LITERAL_VALUES_EMITTED=false")
    print("SOURCE_EXECUTED=false")
    print("SECRETS_READ=false")
    print("CREDENTIAL_MATERIAL_EMITTED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
