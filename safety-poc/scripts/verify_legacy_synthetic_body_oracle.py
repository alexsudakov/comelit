#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import inspect
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace

from runtime_gate_common import (
    CANONICAL_ROOT,
    LEGACY_SOURCE,
    add_sys_path,
    clear_package,
    load_module_from_path,
    require_canonical_pins,
    require_legacy_pin,
)

CHANNEL_ID = 7449


class SyntheticScalar:
    """Deterministic non-secret value usable as text or an integer field."""

    def __init__(self, label: str) -> None:
        self.label = label
        digest = hashlib.sha256(label.encode('utf-8')).digest()
        self._integer = 1 + int.from_bytes(digest[:2], 'big') % 20000
        self._text = f'SYNTH-{digest[:6].hex()}'

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return '<SyntheticScalar>'

    def __int__(self) -> int:
        return self._integer

    def __index__(self) -> int:
        return self._integer

    def __bytes__(self) -> bytes:
        return self._text.encode('ascii')

    def __len__(self) -> int:
        return len(bytes(self))

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

    def encode(self, encoding: str = 'utf-8', errors: str = 'strict') -> bytes:
        return self._text.encode(encoding, errors)


class SyntheticMapping:
    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    def _value(self, key: object) -> SyntheticScalar:
        return SyntheticScalar(f'{self.namespace}:{type(key).__name__}:{key!s}')

    def get(self, key: object, default: object = None) -> object:
        return self._value(key)

    def __getitem__(self, key: object) -> object:
        return self._value(key)


class SyntheticResponse:
    request_id = CHANNEL_ID
    body = b''

    def __iter__(self):
        yield self.request_id
        yield self.body


def _seed_synthetic_ctpp_binding(client: object, legacy: object, channel: object) -> None:
    """Populate only the in-memory channel lookup required by legacy open_door().

    The production `_open_channel` implementation normally owns this mapping.
    The runtime oracle replaces `_open_channel` to guarantee zero network I/O, so
    the harness must reproduce that one local side effect explicitly.  No
    credentials, endpoints, sockets or real channel state are used.
    """

    open_channels = getattr(client, 'open_channels', None)
    if open_channels is None:
        open_channels = {}
        setattr(client, 'open_channels', open_channels)
    if not hasattr(open_channels, '__setitem__'):
        raise RuntimeError('legacy open_channels is not a mutable mapping')

    keys: list[object] = ['CTPP']
    channel_type = getattr(legacy, 'Channel', None)
    enum_key = getattr(channel_type, 'CTPP', None) if channel_type is not None else None
    if enum_key is not None and enum_key not in keys:
        keys.append(enum_key)

    for key in keys:
        open_channels[key] = channel


async def _capture_legacy_packets(source: Path = LEGACY_SOURCE) -> tuple[bytes, ...]:
    require_legacy_pin(source)
    legacy = load_module_from_path('_comelit_legacy_synthetic_oracle', source)

    client_cls = getattr(legacy, 'IconaBridgeClient')
    signature = inspect.signature(client_cls)
    positional = [p for p in signature.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    args: list[object] = []
    if positional:
        args.append('offline.invalid')
    if len(positional) >= 2:
        args.append(0)
    client = client_cls(*args)

    captured: list[bytes] = []
    synthetic_channel = SimpleNamespace(id=CHANNEL_ID, channel_id=CHANNEL_ID, name='CTPP', channel='CTPP')

    async def fake_open_channel(self, *args, **kwargs):
        return synthetic_channel

    async def fake_write_packet(self, packet):
        captured.append(bytes(packet))

    async def fake_read_response(self, *args, **kwargs):
        return SyntheticResponse()

    async def fake_close_channel(self, *args, **kwargs):
        return True

    client._open_channel = MethodType(fake_open_channel, client)
    client._write_packet = MethodType(fake_write_packet, client)
    client._read_response = MethodType(fake_read_response, client)
    client._close_channel = MethodType(fake_close_channel, client)
    _seed_synthetic_ctpp_binding(client, legacy, synthetic_channel)

    vip = SyntheticMapping('vip')
    door = SyntheticMapping('door')
    await client.open_door(vip, door)

    if len(captured) != 6:
        raise RuntimeError(f'legacy synthetic oracle expected 6 writes, got {len(captured)}')
    if any(len(packet) <= 8 for packet in captured):
        raise RuntimeError('legacy synthetic oracle produced an invalid short frame')
    return tuple(captured)


async def _canonical_reframe(legacy_packets: tuple[bytes, ...]) -> tuple[bytes, ...]:
    require_canonical_pins()
    add_sys_path(CANONICAL_ROOT)
    clear_package('comelit_vip')
    from comelit_vip.fixture_transport import FixtureTransport
    from comelit_vip.vip_session import VipSession

    transport = FixtureTransport()
    session = VipSession(transport, sync_on_first_frame=False)
    for packet in legacy_packets:
        body = packet[8:]
        await session.send_frame(CHANNEL_ID, body)
    writes = tuple(bytes(item) for item in transport.writes)
    await transport.close()
    return writes


async def run() -> tuple[bytes, ...]:
    legacy_packets = await _capture_legacy_packets()
    canonical_packets = await _canonical_reframe(legacy_packets)
    if canonical_packets != legacy_packets:
        raise RuntimeError('canonical reframing differs from the legacy synthetic oracle')
    return legacy_packets


def main() -> int:
    packets = asyncio.run(run())
    print('=== LEGACY SYNTHETIC BODY ORACLE ===')
    print('LEGACY_RESEARCH_SOURCE_HASH=PASS')
    print('CANONICAL_VIP_SOURCE_HASHES=PASS')
    print(f'LEGACY_SYNTHETIC_WRITE_COUNT={len(packets)}')
    print(f'CANONICAL_FRAME_EQUIVALENCE_COUNT={len(packets)}')
    for index, packet in enumerate(packets, 1):
        body = packet[8:]
        print(f'WRITE_{index}_BODY_BYTES={len(body)}')
        print(f'WRITE_{index}_BODY_SHA256={hashlib.sha256(body).hexdigest()}')
    print('CTPP_BODY_LAYOUT_RECONCILIATION=PASS')
    print('SYNTHETIC_INPUTS_ONLY=true')
    print('SYNTHETIC_CTPP_CHANNEL_BINDING=true')
    print('LEGACY_SOURCE_EXECUTED_OFFLINE=true')
    print('SECRETS_READ=false')
    print('REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false')
    print('NETWORK_ACTION_PERFORMED=false')
    print('PHYSICAL_DOOR_ACTION=false')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
