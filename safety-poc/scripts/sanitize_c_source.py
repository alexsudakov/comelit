#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


SAFE_LITERAL_TAGS = (
    "UAUT",
    "UCFG",
    "ECHO",
    "PSEUDOTCP",
    "ICE",
    "VIP_",
    "message",
    "access",
    "user-token",
    "message-type",
    "request",
    "message-id",
    "response-code",
    "get-configuration",
)


def literal_placeholder(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8", errors="surrogateescape")).hexdigest()[:16]
    return f'"<REDACTED_STRING bytes={len(raw.encode("utf-8", errors="surrogateescape"))} sha256={digest}>"'


def sanitize_c_source(text: str) -> tuple[str, dict[str, int], int]:
    out: list[str] = []
    literal_counts = {tag: 0 for tag in SAFE_LITERAL_TAGS}
    string_count = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if ch == "/" and nxt == "/":
            out.extend("  ")
            i += 2
            while i < n and text[i] != "\n":
                out.append(" " if text[i] != "\t" else "\t")
                i += 1
            continue

        if ch == "/" and nxt == "*":
            out.extend("  ")
            i += 2
            while i < n:
                if i + 1 < n and text[i] == "*" and text[i + 1] == "/":
                    out.extend("  ")
                    i += 2
                    break
                out.append("\n" if text[i] == "\n" else ("\t" if text[i] == "\t" else " "))
                i += 1
            continue

        if ch == '"':
            start = i
            i += 1
            escaped = False
            while i < n:
                c = text[i]
                if escaped:
                    escaped = False
                    i += 1
                    continue
                if c == "\\":
                    escaped = True
                    i += 1
                    continue
                if c == '"':
                    i += 1
                    break
                i += 1
            raw = text[start:i]
            string_count += 1
            for tag in SAFE_LITERAL_TAGS:
                if tag in raw:
                    literal_counts[tag] += 1
            placeholder = literal_placeholder(raw)
            newline_count = raw.count("\n")
            out.append(placeholder)
            if newline_count:
                out.append("\n" * newline_count)
            continue

        if ch == "'":
            start = i
            i += 1
            escaped = False
            while i < n:
                c = text[i]
                if escaped:
                    escaped = False
                    i += 1
                    continue
                if c == "\\":
                    escaped = True
                    i += 1
                    continue
                if c == "'":
                    i += 1
                    break
                i += 1
            raw = text[start:i]
            if raw in ("'\\n'", "'\\r'", "'\\0'", "' '", "':'", "','", "'{'", "'}'"):
                out.append(raw)
            else:
                digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
                out.append(f"'<R:{digest}>'")
            continue

        out.append(ch)
        i += 1

    sanitized = "".join(out)
    # Comment redaction intentionally preserves newlines but can leave spaces on otherwise
    # blank lines. Strip only horizontal whitespace immediately before a newline so the
    # structural line map remains intact while generated evidence passes git diff --check.
    sanitized = re.sub(r"[ \t]+(?=\n)", "", sanitized)
    sanitized = re.sub(r"[ \t]+\Z", "", sanitized)
    return sanitized, literal_counts, string_count


def discover_function_names(sanitized: str) -> list[str]:
    pattern = re.compile(
        r"(?m)^[ \t]*(?:static[ \t]+)?(?:inline[ \t]+)?(?:[A-Za-z_][A-Za-z0-9_]*[ \t\*]+)+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*\([^;{}]*\)[ \t]*\{"
    )
    return sorted({m.group("name") for m in pattern.finditer(sanitized)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit line-preserving C structure with comments and string literals redacted")
    parser.add_argument("source", type=Path)
    parser.add_argument("--structure-out", type=Path, required=True)
    parser.add_argument("--metadata-out", type=Path, required=True)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8", errors="surrogateescape")
    sanitized, literal_counts, string_count = sanitize_c_source(text)
    functions = discover_function_names(sanitized)

    args.structure_out.write_text(sanitized, encoding="utf-8")
    lines = [
        "C_SOURCE_SANITIZER=PASS",
        f"SOURCE_SHA256={hashlib.sha256(args.source.read_bytes()).hexdigest()}",
        f"SOURCE_BYTES={len(args.source.read_bytes())}",
        f"SOURCE_LINE_COUNT={text.count(chr(10)) + 1}",
        f"STRING_LITERAL_COUNT={string_count}",
        f"DISCOVERED_FUNCTION_COUNT={len(functions)}",
    ]
    lines.extend(f"FUNCTION_NAME={name}" for name in functions)
    lines.extend(f"SAFE_LITERAL_TAG_COUNT tag={tag} count={literal_counts[tag]}" for tag in SAFE_LITERAL_TAGS)
    lines.extend(
        [
            "COMMENTS_EMITTED=false",
            "STRING_LITERAL_VALUES_EMITTED=false",
            "TRAILING_WHITESPACE_EMITTED=false",
            "SOURCE_EXECUTED=false",
            "SECRETS_READ=false",
            "NETWORK_ACTION_PERFORMED=false",
            "PHYSICAL_DOOR_ACTION=false",
        ]
    )
    args.metadata_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
