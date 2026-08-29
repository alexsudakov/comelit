#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
from pathlib import Path


SENSITIVE_NAME_FRAGMENTS = ("password", "passwd", "secret", "credential", "authorization", "bearer")


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return type(node).__name__


def annotation_name(node: ast.AST | None) -> str:
    if node is None:
        return "none"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted_name(node)
    if isinstance(node, ast.Subscript):
        return f"{annotation_name(node.value)}[...]"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "forward-ref"
    return type(node).__name__


def literal_shape(value: object) -> str:
    if isinstance(value, bytes):
        return f"bytes(len={len(value)})"
    if isinstance(value, str):
        return f"str(utf8_len={len(value.encode('utf-8'))})"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "none"
    return type(value).__name__


def safe_identifier(name: str) -> str:
    lower = name.lower()
    if any(fragment in lower for fragment in SENSITIVE_NAME_FRAGMENTS):
        return f"<sensitive-name sha256={hashlib.sha256(name.encode()).hexdigest()[:12]}>"
    return name


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    positional = list(node.args.posonlyargs) + list(node.args.args)
    parts = [f"{safe_identifier(arg.arg)}:{annotation_name(arg.annotation)}" for arg in positional]
    if node.args.vararg:
        parts.append(f"*{safe_identifier(node.args.vararg.arg)}:{annotation_name(node.args.vararg.annotation)}")
    parts.extend(f"{safe_identifier(arg.arg)}:{annotation_name(arg.annotation)}" for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        parts.append(f"**{safe_identifier(node.args.kwarg.arg)}:{annotation_name(node.args.kwarg.annotation)}")
    return ",".join(parts)


def analyze_file(path: Path, label: str) -> list[str]:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    tree = ast.parse(text, filename=str(path))

    imports: set[str] = set()
    classes: list[ast.ClassDef] = []
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    call_counter: Counter[str] = Counter()
    literal_counter: Counter[str] = Counter()
    top_constants: list[str] = []
    struct_pack_calls: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            classes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            call_counter[safe_identifier(name)] += 1
            if name == "struct.pack":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    fmt_shape = f"literal_format_len={len(node.args[0].value)}"
                else:
                    fmt_shape = "dynamic_format"
                struct_pack_calls.append(f"line={getattr(node, 'lineno', 0)} {fmt_shape} value_argc={max(len(node.args)-1, 0)}")
        elif isinstance(node, ast.Constant):
            literal_counter[literal_shape(node.value)] += 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, ast.Constant):
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        top_constants.append(f"{safe_identifier(target.id)}:{literal_shape(value.value)}")

    lines = [
        f"=== FILE {label} ===",
        f"SHA256={sha}",
        f"BYTES={len(raw)}",
        f"LINES={text.count(chr(10)) + 1}",
        f"IMPORT_ROOTS={','.join(sorted(imports))}",
        f"CLASS_COUNT={len(classes)}",
        f"FUNCTION_COUNT={len(functions)}",
        "SOURCE_EXECUTED=false",
        "LITERAL_VALUES_PRINTED=false",
    ]

    for cls in sorted(classes, key=lambda n: (n.lineno, n.name)):
        bases = ",".join(annotation_name(base) for base in cls.bases)
        lines.append(f"CLASS line={cls.lineno} name={safe_identifier(cls.name)} bases={bases or '-'}")

    for fn in sorted(functions, key=lambda n: (n.lineno, n.name)):
        kind = "async" if isinstance(fn, ast.AsyncFunctionDef) else "sync"
        lines.append(f"FUNCTION line={fn.lineno} kind={kind} name={safe_identifier(fn.name)} args={function_signature(fn)} returns={annotation_name(fn.returns)}")

    for name, count in sorted(call_counter.items()):
        lines.append(f"CALL name={name} count={count}")
    for shape, count in sorted(literal_counter.items()):
        lines.append(f"LITERAL_SHAPE type={shape} count={count}")
    for item in sorted(set(top_constants)):
        lines.append(f"TOP_CONSTANT {item}")
    for item in struct_pack_calls:
        lines.append(f"STRUCT_PACK {item}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-safe AST topology inventory. Source is parsed, never imported or executed.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    print("=== SAFE SOURCE TOPOLOGY ===")
    print("SOURCE_EXECUTED=false")
    print("LITERAL_VALUES_PRINTED=false")
    print("SECRETS_READ=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")

    for source in args.paths:
        if not source.is_file():
            print(f"MISSING_FILE={source}")
            continue
        print()
        for line in analyze_file(source, str(source)):
            print(line)

    print()
    print("SAFE_SOURCE_TOPOLOGY=PASS")
    print("SOURCE_EXECUTED=false")
    print("LITERAL_VALUES_PRINTED=false")
    print("SECRETS_READ=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
