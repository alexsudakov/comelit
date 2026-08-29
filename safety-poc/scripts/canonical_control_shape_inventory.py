#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path

DEFAULT_ROOT = Path('/root/comelit-vip-poc')
PINNED = {
    'comelit_vip/application_session.py': '7c30aab9bd03917e0e84fb9b31f924f95eabeb8edd6a1fe74d4e4f012c2145fd',
    'comelit_vip/channel_session.py': 'b34d87c382ea601d96761f59a31e62aa2d1e959ea9c24e99a63964e1c033e1d1',
    'comelit_vip/control_codec.py': 'e89e3fe20b24ef2f22ceaa15b186b4db7f71f5f48c7f5aeaf6a07f38bea854a2',
    'comelit_vip/vip_session.py': '35b604372e9bd42a6631d0c923ac99d49e02e4b7c8892360633eedc23425dc39',
}
TARGET_METHODS = (
    ('comelit_vip/channel_session.py', 'VipChannelSession', 'open_channel'),
    ('comelit_vip/channel_session.py', 'VipChannelSession', 'close_channel'),
    ('comelit_vip/channel_session.py', 'VipChannelSession', '_send_control'),
    ('comelit_vip/channel_session.py', 'VipChannelSession', 'recv_event'),
    ('comelit_vip/vip_session.py', 'VipSession', 'send_frame'),
)
TEST_FILES = (
    'tests/test_channel_session.py',
    'tests/test_vip_session.py',
    'tests/test_application_session.py',
)
TEST_CALLS = {
    'FixtureTransport', 'VipSession', 'VipChannelSession', 'VipApplicationSession',
    'open_channel', 'close_channel', 'recv_event', 'send_frame',
    'OpenChannelRequest', 'OpenChannelResponse', 'CloseChannelRequest', 'CloseChannelResponse',
    'encode_control_message', 'encode_vip_frame',
}


def callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = callee_name(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return type(node).__name__


def annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return 'none'
    try:
        return ast.unparse(node).replace(' ', '')
    except Exception:
        return type(node).__name__


def shape(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bytes):
            return f'CONST_BYTES(len={len(value)})'
        if isinstance(value, str):
            return f'CONST_STR(utf8_len={len(value.encode("utf-8"))})'
        if value is None:
            return 'CONST_NONE'
        return f'CONST_{type(value).__name__.upper()}'
    if isinstance(node, ast.Name):
        return f'NAME({node.id})'
    if isinstance(node, ast.Attribute):
        return f'ATTR({callee_name(node)})'
    if isinstance(node, ast.Call):
        return f'CALL({callee_name(node.func)},argc={len(node.args)},kw={len(node.keywords)})'
    if isinstance(node, ast.List):
        return f'LIST(items={len(node.elts)})'
    if isinstance(node, ast.Tuple):
        return f'TUPLE(items={len(node.elts)})'
    if isinstance(node, ast.Dict):
        return f'DICT(items={len(node.keys)})'
    if isinstance(node, ast.BinOp):
        return f'BINOP({type(node.op).__name__})'
    if isinstance(node, ast.UnaryOp):
        return f'UNARY({type(node.op).__name__})'
    if isinstance(node, ast.Subscript):
        return f'SUBSCRIPT({callee_name(node.value)})'
    return type(node).__name__.upper()


class OuterVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return None


def outer_nodes(function: ast.AST) -> list[ast.AST]:
    visitor = OuterVisitor()
    for statement in getattr(function, 'body', ()):
        visitor.nodes.append(statement)
        visitor.visit(statement)
    return visitor.nodes


def find_method(tree: ast.Module, class_name: str, method_name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return child
    raise ValueError(f'missing canonical method: {class_name}.{method_name}')


def method_args(function: ast.AST) -> str:
    args = getattr(function, 'args')
    rendered = []
    for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        rendered.append(f'{arg.arg}:{annotation_text(arg.annotation)}')
    if args.vararg:
        rendered.append(f'*{args.vararg.arg}:{annotation_text(args.vararg.annotation)}')
    if args.kwarg:
        rendered.append(f'**{args.kwarg.arg}:{annotation_text(args.kwarg.annotation)}')
    return ','.join(rendered)


def class_fields(tree: ast.Module, path: str) -> list[str]:
    rows: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                default_kind = 'none' if child.value is None else shape(child.value)
                rows.append(
                    f'FIELD path={path} class={node.name} name={child.target.id} '
                    f'annotation={annotation_text(child.annotation)} default_shape={default_kind}'
                )
    return rows


def analyze(root: Path) -> list[str]:
    lines = [
        '=== CANONICAL CONTROL SHAPE INVENTORY ===',
        'SOURCE_EXECUTED=false',
        'LITERAL_VALUES_PRINTED=false',
        'SECRETS_READ=false',
        'NETWORK_ACTION_PERFORMED=false',
        'PHYSICAL_DOOR_ACTION=false',
    ]
    trees: dict[str, ast.Module] = {}
    for relative, expected in PINNED.items():
        path = root / relative
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError(f'canonical source hash mismatch: {relative}')
        lines.append(f'SOURCE path={relative} sha256={actual} hash_pin=PASS')
        tree = ast.parse(raw.decode('utf-8'), filename=str(path))
        trees[relative] = tree
        lines.extend(class_fields(tree, relative))

    for relative, class_name, method_name in TARGET_METHODS:
        function = find_method(trees[relative], class_name, method_name)
        calls = sorted(
            (node for node in outer_nodes(function) if isinstance(node, ast.Call)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        lines += [
            '',
            f'METHOD={class_name}.{method_name}',
            f'METHOD_PATH={relative}',
            f'METHOD_LINE={function.lineno}',
            f'METHOD_ARGS={method_args(function)}',
            f'METHOD_CALL_COUNT={len(calls)}',
        ]
        for index, call in enumerate(calls, 1):
            arg_shapes = '|'.join(shape(arg) for arg in call.args)
            lines.append(f'METHOD_CALL_{index}_LINE={call.lineno}')
            lines.append(f'METHOD_CALL_{index}_NAME={callee_name(call.func)}')
            lines.append(f'METHOD_CALL_{index}_ARGC={len(call.args)}')
            lines.append(f'METHOD_CALL_{index}_ARG_SHAPES={arg_shapes}')

    for relative in TEST_FILES:
        path = root / relative
        if not path.is_file():
            lines.append(f'TEST_FILE_MISSING={relative}')
            continue
        raw = path.read_bytes()
        lines += ['', f'TEST_FILE={relative}', f'TEST_SHA256={hashlib.sha256(raw).hexdigest()}']
        tree = ast.parse(raw.decode('utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith('test_'):
                continue
            selected = []
            for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
                leaf = callee_name(call.func).split('.')[-1]
                if leaf in TEST_CALLS:
                    selected.append(call)
            selected.sort(key=lambda call: (call.lineno, call.col_offset))
            if not selected:
                continue
            lines.append(f'TEST={node.name} line={node.lineno} selected_calls={len(selected)}')
            for index, call in enumerate(selected, 1):
                arg_shapes = '|'.join(shape(arg) for arg in call.args)
                lines.append(
                    f'TEST_CALL index={index} line={call.lineno} name={callee_name(call.func)} '
                    f'argc={len(call.args)} arg_shapes={arg_shapes}'
                )

    lines += [
        '',
        'CANONICAL_CONTROL_SHAPE_INVENTORY=PASS',
        'SOURCE_EXECUTED=false',
        'LITERAL_VALUES_PRINTED=false',
        'SECRETS_READ=false',
        'NETWORK_ACTION_PERFORMED=false',
        'PHYSICAL_DOOR_ACTION=false',
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    for line in analyze(args.root):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
