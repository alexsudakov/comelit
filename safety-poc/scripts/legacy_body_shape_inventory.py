#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import struct
from pathlib import Path

DEFAULT_SOURCE = Path('/root/comelit-poc/comelit_client.py')
EXPECTED_SHA256 = '03ea7d012587d8751eddfd5fa531d244abddc047c3a69d8ce27986c1e2768d42'
TARGET_FUNCTIONS = ('_open_door_init', 'open_door')


def callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = callee_name(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return type(node).__name__


def find_function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise ValueError(f'required function missing: {name}')


def calls_named(function: ast.AST, leaf: str) -> list[ast.Call]:
    found = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and callee_name(node.func).split('.')[-1] == leaf:
            found.append(node)
    return sorted(found, key=lambda n: (n.lineno, n.col_offset))


def assignment_index(function: ast.AST) -> dict[str, list[tuple[int, ast.AST]]]:
    result: dict[str, list[tuple[int, ast.AST]]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            value = node.value
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                result.setdefault(target.id, []).append((node.lineno, value))
    for values in result.values():
        values.sort(key=lambda item: item[0])
    return result


def prior_assignment(name: str, line: int, assignments: dict[str, list[tuple[int, ast.AST]]]) -> ast.AST | None:
    result = None
    for assignment_line, value in assignments.get(name, ()):
        if assignment_line >= line:
            break
        result = value
    return result


def shape(node: ast.AST, line: int, assignments: dict[str, list[tuple[int, ast.AST]]], seen: frozenset[str] = frozenset()) -> tuple[str, int | None]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bytes):
            return f'CONST_BYTES(len={len(node.value)})', len(node.value)
        if isinstance(node.value, str):
            return f'CONST_STR(utf8_len={len(node.value.encode("utf-8"))})', None
        if node.value is None:
            return 'CONST_NONE', None
        return f'CONST_{type(node.value).__name__.upper()}', None

    if isinstance(node, ast.Name):
        if node.id in seen:
            return f'NAME({node.id}:cycle)', None
        assigned = prior_assignment(node.id, line, assignments)
        if assigned is None:
            return f'NAME({node.id})', None
        nested, size = shape(assigned, getattr(assigned, 'lineno', line) + 1, assignments, seen | {node.id})
        return f'NAME({node.id})->{nested}', size

    if isinstance(node, ast.Attribute):
        return f'ATTR({callee_name(node)})', None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, left_size = shape(node.left, line, assignments, seen)
        right, right_size = shape(node.right, line, assignments, seen)
        size = left_size + right_size if left_size is not None and right_size is not None else None
        return f'ADD({left},{right})', size

    if isinstance(node, ast.Call):
        callee = callee_name(node.func)
        leaf = callee.split('.')[-1]
        if callee == 'struct.pack' and node.args:
            fmt = node.args[0]
            if isinstance(fmt, ast.Constant) and isinstance(fmt.value, str):
                try:
                    size = struct.calcsize(fmt.value)
                except struct.error:
                    size = None
                return f'STRUCT_PACK(fmt={fmt.value!r},argc={len(node.args)-1})', size
            return f'STRUCT_PACK(fmt=dynamic,argc={len(node.args)-1})', None
        if leaf in {'bytes', 'bytearray'} and len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
            count = len(node.args[0].elts)
            return f'{leaf.upper()}(items={count})', count
        if leaf == 'encode' and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Constant) and isinstance(base.value, str):
                size = len(base.value.encode('utf-8'))
                return f'ENCODE(CONST_STR,len={size})', size
            return f'ENCODE({type(base).__name__})', None
        return f'CALL({callee},argc={len(node.args)},kw={len(node.keywords)})', None

    if isinstance(node, ast.Subscript):
        return f'SUBSCRIPT({callee_name(node.value)})', None

    if isinstance(node, (ast.List, ast.Tuple)):
        return f'{type(node).__name__.upper()}(items={len(node.elts)})', None

    return type(node).__name__.upper(), None


def analyze_source(source: Path, expected_sha256: str) -> list[str]:
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f'legacy research source hash mismatch: expected={expected_sha256} actual={actual}')

    tree = ast.parse(raw.decode('utf-8'), filename=str(source))
    lines = [
        '=== LEGACY DOOR BODY SHAPE INVENTORY ===',
        f'SOURCE_SHA256={actual}',
        'SOURCE_HASH_PIN=PASS',
        'SOURCE_EXECUTED=false',
        'LITERAL_PAYLOAD_VALUES_PRINTED=false',
        'SECRETS_READ=false',
        'NETWORK_ACTION_PERFORMED=false',
        'PHYSICAL_DOOR_ACTION=false',
    ]

    for function_name in TARGET_FUNCTIONS:
        function = find_function(tree, function_name)
        assignments = assignment_index(function)
        binary_calls = calls_named(function, '_create_binary_packet_from_buffers')
        message_calls = calls_named(function, 'create_door_message')
        write_calls = calls_named(function, '_write_packet')
        read_calls = calls_named(function, '_read_response')
        lines += [
            '',
            f'FUNCTION={function_name}',
            f'BINARY_BODY_BUILDER_CALLS={len(binary_calls)}',
            f'DOOR_MESSAGE_BUILDER_CALLS={len(message_calls)}',
            f'WRITE_PACKET_CALLS={len(write_calls)}',
            f'READ_RESPONSE_CALLS={len(read_calls)}',
        ]

        for index, call in enumerate(binary_calls, 1):
            if not call.args:
                raise ValueError(f'{function_name}:{call.lineno} binary builder has no request id')
            body_args = call.args[1:]
            lines += [
                f'BODY_CALL_{index}_LINE={call.lineno}',
                f'BODY_CALL_{index}_COMPONENTS={len(body_args)}',
                f'BODY_CALL_{index}_REQUEST_ID_KIND={type(call.args[0]).__name__}',
            ]
            for component_index, component in enumerate(body_args, 1):
                component_shape, static_bytes = shape(component, call.lineno, assignments)
                static_text = 'unknown' if static_bytes is None else str(static_bytes)
                lines.append(f'BODY_CALL_{index}_COMPONENT_{component_index}_SHAPE={component_shape}')
                lines.append(f'BODY_CALL_{index}_COMPONENT_{component_index}_STATIC_BYTES={static_text}')

        for index, call in enumerate(message_calls, 1):
            arg_shapes = [shape(arg, call.lineno, assignments)[0] for arg in call.args]
            lines += [
                f'DOOR_MESSAGE_CALL_{index}_LINE={call.lineno}',
                f'DOOR_MESSAGE_CALL_{index}_ARGC={len(call.args)}',
                f'DOOR_MESSAGE_CALL_{index}_ARG_SHAPES=' + '|'.join(arg_shapes),
            ]

    lines += [
        '',
        'LEGACY_DOOR_BODY_SHAPE_INVENTORY=PASS',
        'PAYLOAD_LITERAL_VALUES_EXTRACTED=false',
        'SOURCE_EXECUTED=false',
        'SECRETS_READ=false',
        'NETWORK_ACTION_PERFORMED=false',
        'PHYSICAL_DOOR_ACTION=false',
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only AST inventory of pinned legacy Door body construction.')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--expected-sha256', default=EXPECTED_SHA256)
    args = parser.parse_args()
    for line in analyze_source(args.source, args.expected_sha256):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
