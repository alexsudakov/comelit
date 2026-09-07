#!/usr/bin/env python3
"""Offline DEX forensic for literal RTPC string references.

The analyzer accepts preserved official Android DEX files, verifies their
expected SHA-256 digests, parses enough of the DEX format to locate methods that
load the exact string literal ``RTPC`` via const-string/const-string-jumbo, and
emits only file names, hashes, counts, class descriptors and method names.

No network I/O is performed. Raw DEX bytes and unrelated string values are not
emitted.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import struct

TARGET = b"RTPC"


def u16(blob: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(blob):
        raise ValueError("u16 out of bounds")
    return struct.unpack_from("<H", blob, off)[0]


def u32(blob: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(blob):
        raise ValueError("u32 out of bounds")
    return struct.unpack_from("<I", blob, off)[0]


def uleb(blob: bytes, off: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if off >= len(blob):
            raise ValueError("truncated uleb128")
        byte = blob[off]
        off += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, off
        shift += 7
    raise ValueError("invalid uleb128")


def read_string_bytes(blob: bytes, off: int) -> bytes:
    _, pos = uleb(blob, off)
    end = blob.find(b"\x00", pos)
    if end < 0:
        raise ValueError("unterminated dex string")
    return blob[pos:end]


def safe_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def payload_width(units: list[int], index: int) -> int:
    ident = units[index] >> 8
    if ident == 0x01:
        size = units[index + 1]
        return 4 + 2 * size
    if ident == 0x02:
        size = units[index + 1]
        return 2 + 4 * size
    if ident == 0x03:
        element_width = units[index + 1]
        size = units[index + 2] | (units[index + 3] << 16)
        return 4 + ((element_width * size + 1) // 2)
    return 1


WIDTH_2 = {
    0x02, 0x05, 0x08, 0x13, 0x15, 0x16, 0x19, 0x1A, 0x1C, 0x1F, 0x20,
    0x22, 0x23, 0x29, 0xFE, 0xFF,
}
WIDTH_3 = {
    0x03, 0x06, 0x09, 0x14, 0x17, 0x1B, 0x24, 0x25, 0x26, 0x2A, 0x2B,
    0x2C, 0xFC, 0xFD,
}


def instruction_width(units: list[int], index: int) -> int:
    op = units[index] & 0xFF
    if op == 0x00:
        return payload_width(units, index)
    if op == 0x18:
        return 5
    if op in (0xFA, 0xFB):
        return 4
    if op in WIDTH_3 or 0x6E <= op <= 0x72 or 0x74 <= op <= 0x78:
        return 3
    if op in WIDTH_2 or 0x2D <= op <= 0x3D or 0x44 <= op <= 0x6D or 0x90 <= op <= 0xAF or 0xD0 <= op <= 0xE2:
        return 2
    return 1


def const_string_indices(units: list[int]) -> tuple[int, ...]:
    result: list[int] = []
    index = 0
    while index < len(units):
        op = units[index] & 0xFF
        if op == 0x1A:
            if index + 1 >= len(units):
                raise ValueError("truncated const-string")
            result.append(units[index + 1])
        elif op == 0x1B:
            if index + 2 >= len(units):
                raise ValueError("truncated const-string/jumbo")
            result.append(units[index + 1] | (units[index + 2] << 16))
        width = instruction_width(units, index)
        if width <= 0 or index + width > len(units):
            raise ValueError("invalid instruction width")
        index += width
    return tuple(result)


def code_references_string(blob: bytes, code_off: int, targets: set[int]) -> bool:
    if code_off == 0:
        return False
    if code_off + 16 > len(blob):
        raise ValueError("code item outside dex")
    insns_size = u32(blob, code_off + 12)
    start = code_off + 16
    end = start + insns_size * 2
    if end > len(blob):
        raise ValueError("instruction array outside dex")
    units = list(struct.unpack_from("<" + "H" * insns_size, blob, start))
    return any(value in targets for value in const_string_indices(units))


def parse_method_list(blob, pos, count, method_ids, type_desc, strings, targets):
    method_idx = 0
    matches: list[tuple[str, str]] = []
    for _ in range(count):
        diff, pos = uleb(blob, pos)
        _, pos = uleb(blob, pos)
        code_off, pos = uleb(blob, pos)
        method_idx += diff
        if method_idx >= len(method_ids):
            raise ValueError("method index outside method_ids")
        if not code_off or not code_references_string(blob, code_off, targets):
            continue
        class_idx, name_idx = method_ids[method_idx]
        class_name = type_desc[class_idx] if class_idx < len(type_desc) else "UNKNOWN_CLASS"
        method_name = safe_text(strings[name_idx]) if name_idx < len(strings) else "UNKNOWN_METHOD"
        matches.append((class_name, method_name))
    return pos, matches


def analyze_dex(path: Path) -> tuple[tuple[tuple[str, str], ...], int]:
    blob = path.read_bytes()
    if len(blob) < 112 or not blob.startswith(b"dex\n"):
        raise ValueError("not a supported dex file")

    string_ids_size, string_ids_off = u32(blob, 56), u32(blob, 60)
    type_ids_size, type_ids_off = u32(blob, 64), u32(blob, 68)
    method_ids_size, method_ids_off = u32(blob, 88), u32(blob, 92)
    class_defs_size, class_defs_off = u32(blob, 96), u32(blob, 100)

    strings = [read_string_bytes(blob, u32(blob, string_ids_off + i * 4)) for i in range(string_ids_size)]
    targets = {i for i, value in enumerate(strings) if value == TARGET}
    if len(targets) != 1:
        raise ValueError(f"expected one RTPC string-id, found {len(targets)}")

    type_desc = []
    for i in range(type_ids_size):
        string_idx = u32(blob, type_ids_off + i * 4)
        if string_idx >= len(strings):
            raise ValueError("type descriptor outside string table")
        type_desc.append(safe_text(strings[string_idx]))

    method_ids = []
    for i in range(method_ids_size):
        off = method_ids_off + i * 8
        method_ids.append((u16(blob, off), u32(blob, off + 4)))

    found: list[tuple[str, str]] = []
    for i in range(class_defs_size):
        class_data_off = u32(blob, class_defs_off + i * 32 + 24)
        if not class_data_off:
            continue
        pos = class_data_off
        static_fields, pos = uleb(blob, pos)
        instance_fields, pos = uleb(blob, pos)
        direct_methods, pos = uleb(blob, pos)
        virtual_methods, pos = uleb(blob, pos)
        for count in (static_fields, instance_fields):
            for _ in range(count):
                _, pos = uleb(blob, pos)
                _, pos = uleb(blob, pos)
        pos, direct = parse_method_list(blob, pos, direct_methods, method_ids, type_desc, strings, targets)
        pos, virtual = parse_method_list(blob, pos, virtual_methods, method_ids, type_desc, strings, targets)
        found.extend(direct)
        found.extend(virtual)

    return tuple(sorted(set(found))), len(targets)


def parse_input(value: str) -> tuple[Path, str]:
    try:
        path_text, digest = value.rsplit("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected PATH=SHA256") from exc
    if len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise argparse.ArgumentTypeError("invalid SHA256")
    return Path(path_text), digest.lower()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=parse_input)
    args = parser.parse_args(argv)

    total = 0
    ok = True
    print("=== COMELIT P70 RTPC STRING-REFERENCE FORENSIC ===")
    for path, expected in args.input:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"DEX_FILE={path.name}")
        print(f"SHA256_GATE={'PASS' if actual == expected else 'FAIL'}")
        if actual != expected:
            ok = False
            print("RTPC_METHOD_REFERENCE_COUNT=0")
            continue
        try:
            refs, target_count = analyze_dex(path)
        except (OSError, ValueError):
            ok = False
            print("DEX_PARSE=FAIL")
            print("RTPC_METHOD_REFERENCE_COUNT=0")
            continue
        print("DEX_PARSE=PASS")
        print(f"RTPC_STRING_ID_COUNT={target_count}")
        print(f"RTPC_METHOD_REFERENCE_COUNT={len(refs)}")
        for class_name, method_name in refs:
            print(f"RTPC_METHOD_REFERENCE class={class_name} method={method_name}")
        total += len(refs)
        if not refs:
            ok = False

    print(f"TOTAL_RTPC_METHOD_REFERENCE_COUNT={total}")
    print(f"RTPC_CONST_STRING_REFERENCE_CONTRACT={'PASS' if ok and total else 'NOT_PROVEN'}")
    print("RAW_DEX_BYTES_EMITTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_SIGNALING_SENT=false")
    print("=== END COMELIT P70 RTPC STRING-REFERENCE FORENSIC ===")
    return 0 if ok and total else 4


if __name__ == "__main__":
    raise SystemExit(main())
