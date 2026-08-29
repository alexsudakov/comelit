#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable

LEGACY_SOURCE = Path('/root/comelit-poc/comelit_client.py')
LEGACY_SHA256 = '03ea7d012587d8751eddfd5fa531d244abddc047c3a69d8ce27986c1e2768d42'
CANONICAL_ROOT = Path('/root/comelit-vip-poc')
CANONICAL_PINS = {
    'comelit_vip/__init__.py': '32d10190dbcfceed5bbabcd39a1d7a8da5dbe0fff85f0d7bb636039d06da8194',
    'comelit_vip/application_session.py': '7c30aab9bd03917e0e84fb9b31f924f95eabeb8edd6a1fe74d4e4f012c2145fd',
    'comelit_vip/channel_session.py': 'b34d87c382ea601d96761f59a31e62aa2d1e959ea9c24e99a63964e1c033e1d1',
    'comelit_vip/control_codec.py': 'e89e3fe20b24ef2f22ceaa15b186b4db7f71f5f48c7f5aeaf6a07f38bea854a2',
    'comelit_vip/fixture_transport.py': '5a4ee43dcb934512728c3cae899bceb56e651a5908699338aa8d3de2064a34d2',
    'comelit_vip/transport.py': '21ce339f15d44216baecdeefa19490a5d5632f689155d628b76d4abb7872a0d4',
    'comelit_vip/vip_codec.py': '4ebf41833977e198b1ef94f4aace37f86dad9fbaec08c716242b9ee40437859a',
    'comelit_vip/vip_session.py': '35b604372e9bd42a6631d0c923ac99d49e02e4b7c8892360633eedc23425dc39',
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f'source hash mismatch: path={path} expected={expected} actual={actual}')


def require_legacy_pin(source: Path = LEGACY_SOURCE) -> None:
    require_sha256(source, LEGACY_SHA256)


def require_canonical_pins(root: Path = CANONICAL_ROOT) -> None:
    for relative, expected in CANONICAL_PINS.items():
        require_sha256(root / relative, expected)


def clear_package(prefix: str) -> None:
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + '.'):
            del sys.modules[name]


def load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load module spec: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_sys_path(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def extract_control_request_id(channel_session_source: Path) -> int:
    """Read the integer request-id literal passed by _send_control to send_frame.

    The value is used locally to construct synthetic inbound fixture frames. It is
    intentionally not printed or persisted by the runtime gates.
    """
    tree = ast.parse(channel_session_source.read_text(encoding='utf-8'), filename=str(channel_session_source))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != 'VipChannelSession':
            continue
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) or child.name != '_send_control':
                continue
            for call in ast.walk(child):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                if call.func.attr != 'send_frame' or len(call.args) < 2:
                    continue
                request_id = call.args[0]
                if isinstance(request_id, ast.Constant) and isinstance(request_id.value, int):
                    return request_id.value
    raise RuntimeError('canonical control request id literal not found')


def decode_frames(vip_codec: ModuleType, stream: bytes) -> tuple[object, ...]:
    decoder = vip_codec.VipStreamDecoder()
    frames = list(decoder.feed(stream))
    tail = decoder.finish()
    if tail is not None:
        frames.extend(tail)
    return tuple(frames)


def marker_lines(items: Iterable[tuple[str, str]]) -> str:
    return ''.join(f'{key}={value}\n' for key, value in items)
