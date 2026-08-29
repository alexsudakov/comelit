#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib

from runtime_gate_common import (
    CANONICAL_ROOT,
    add_sys_path,
    clear_package,
    decode_frames,
    extract_control_request_id,
    require_canonical_pins,
)

CHANNEL_ID = 7449
SEMANTIC_WRITES = (
    'INIT_A',
    'COMMAND_PRIMARY',
    'CONFIRM_PRIMARY',
    'INIT_B',
    'COMMAND_FINAL',
    'CONFIRM_FINAL',
)


def synthetic_body(label: str) -> bytes:
    digest = hashlib.sha256(('v0.6:' + label).encode('ascii')).digest()
    return b'V06S' + digest[:20]


async def run() -> tuple[int, tuple[int, ...], tuple[str, ...]]:
    require_canonical_pins()
    add_sys_path(CANONICAL_ROOT)
    clear_package('comelit_vip')

    from comelit_vip.channel_session import VipChannelSession
    from comelit_vip.control_codec import (
        CloseChannelRequest,
        CloseChannelResponse,
        OpenChannelRequest,
        OpenChannelResponse,
        decode_control_body,
        encode_control_message,
    )
    from comelit_vip.fixture_transport import FixtureTransport
    from comelit_vip.vip_codec import encode_frame
    import comelit_vip.vip_codec as vip_codec
    from comelit_vip.vip_session import VipSession

    control_request_id = extract_control_request_id(CANONICAL_ROOT / 'comelit_vip/channel_session.py')
    inbound = b''.join((
        encode_frame(control_request_id, encode_control_message(OpenChannelResponse(
            channel_id=CHANNEL_ID,
            response_word=0,
            extension=None,
        ))),
        encode_frame(control_request_id, encode_control_message(CloseChannelResponse(
            channel_id=CHANNEL_ID,
            response_word=0,
        ))),
    ))

    transport = FixtureTransport(inbound)
    vip = VipSession(transport, sync_on_first_frame=False)
    channels = VipChannelSession(vip, next_channel_id=CHANNEL_ID)

    opened = await channels.open_channel('CTPP')
    if opened.channel_id != CHANNEL_ID or opened.channel_name != 'CTPP':
        raise RuntimeError('unexpected CTPP channel binding')

    bodies = tuple(synthetic_body(label) for label in SEMANTIC_WRITES)
    for body in bodies:
        await vip.send_frame(opened.channel_id, body)

    closed = await channels.close_channel(opened.channel_id)
    if closed.channel_id != CHANNEL_ID:
        raise RuntimeError('close response channel id mismatch')

    frames = decode_frames(vip_codec, transport.written_bytes)
    if len(frames) != 8:
        raise RuntimeError(f'expected 8 total fixture writes (2 control + 6 Door), got {len(frames)}')

    first_control = decode_control_body(frames[0].body)
    last_control = decode_control_body(frames[-1].body)
    if not isinstance(first_control, OpenChannelRequest) or first_control.channel_name != 'CTPP':
        raise RuntimeError('transaction does not begin with CTPP open')
    if not isinstance(last_control, CloseChannelRequest) or last_control.channel_id != CHANNEL_ID:
        raise RuntimeError('transaction does not end with matching CTPP close')

    data_frames = frames[1:7]
    if tuple(frame.request_id for frame in data_frames) != (CHANNEL_ID,) * 6:
        raise RuntimeError('Door fixture writes are not bound to one CTPP channel id')
    if tuple(bytes(frame.body) for frame in data_frames) != bodies:
        raise RuntimeError('Door fixture body order changed')

    await transport.close()
    hashes = tuple(hashlib.sha256(body).hexdigest() for body in bodies)
    return len(frames), tuple(frame.request_id for frame in data_frames), hashes


def main() -> int:
    total_writes, request_ids, hashes = asyncio.run(run())
    print('=== FULL OFFLINE DOOR TRANSACTION FIXTURE ===')
    print('CANONICAL_VIP_SOURCE_HASHES=PASS')
    print(f'TOTAL_FIXTURE_WRITE_COUNT={total_writes}')
    print('CONTROL_WRITE_COUNT=2')
    print('DOOR_FIXTURE_WRITE_COUNT=6')
    print(f'DOOR_REQUEST_IDS_SINGLE_CHANNEL={str(len(set(request_ids)) == 1).lower()}')
    print(f'DOOR_CHANNEL_ID={request_ids[0]}')
    print(f'DOOR_SYNTHETIC_BODY_UNIQUE_COUNT={len(set(hashes))}')
    print('TRANSACTION_BEGINS_OPEN_CTPP=PASS')
    print('TRANSACTION_ENDS_CLOSE_CTPP=PASS')
    print('DOOR_PROTOCOL_ACK_PROVEN=false')
    print('FULL_OFFLINE_DOOR_TRANSACTION=PASS')
    print('FIXTURE_ONLY=true')
    print('AUTO_RETRY_IMPLEMENTED=false')
    print('PHYSICAL_EFFECT_ASSERTED=false')
    print('SECRETS_READ=false')
    print('NETWORK_ACTION_PERFORMED=false')
    print('PHYSICAL_DOOR_ACTION=false')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
