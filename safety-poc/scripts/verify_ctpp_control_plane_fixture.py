#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from runtime_gate_common import (
    CANONICAL_ROOT,
    add_sys_path,
    clear_package,
    decode_frames,
    extract_control_request_id,
    require_canonical_pins,
)

CHANNEL_ID = 7449


async def run() -> tuple[int, int, int]:
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

    request_id = extract_control_request_id(CANONICAL_ROOT / 'comelit_vip/channel_session.py')
    inbound = b''.join((
        encode_frame(request_id, encode_control_message(OpenChannelResponse(
            channel_id=CHANNEL_ID,
            response_word=0,
            extension=None,
        ))),
        encode_frame(request_id, encode_control_message(CloseChannelResponse(
            channel_id=CHANNEL_ID,
            response_word=0,
        ))),
    ))

    transport = FixtureTransport(inbound)
    vip = VipSession(transport, sync_on_first_frame=False)
    channels = VipChannelSession(vip, next_channel_id=CHANNEL_ID)

    opened = await channels.open_channel('CTPP')
    if opened.channel_name != 'CTPP' or opened.channel_id != CHANNEL_ID:
        raise RuntimeError('canonical CTPP open returned an unexpected binding')
    closed = await channels.close_channel(opened.channel_id)
    if closed.channel_id != CHANNEL_ID or closed.response_word != 0:
        raise RuntimeError('canonical CTPP close returned an unexpected response')

    frames = decode_frames(vip_codec, transport.written_bytes)
    if len(frames) != 2:
        raise RuntimeError(f'expected exactly two canonical control writes, got {len(frames)}')
    open_request = decode_control_body(frames[0].body)
    close_request = decode_control_body(frames[1].body)
    if not isinstance(open_request, OpenChannelRequest):
        raise RuntimeError('first canonical control write is not OpenChannelRequest')
    if open_request.channel_name != 'CTPP' or open_request.channel_id != CHANNEL_ID:
        raise RuntimeError('canonical open request CTPP binding mismatch')
    if not isinstance(close_request, CloseChannelRequest):
        raise RuntimeError('second canonical control write is not CloseChannelRequest')
    if close_request.channel_id != CHANNEL_ID:
        raise RuntimeError('canonical close request channel id mismatch')

    await transport.close()
    return len(frames), opened.channel_id, closed.response_word


def main() -> int:
    writes, channel_id, close_word = asyncio.run(run())
    print('=== CANONICAL CTPP CONTROL FIXTURE ===')
    print('CANONICAL_VIP_SOURCE_HASHES=PASS')
    print(f'CTPP_CONTROL_WRITE_COUNT={writes}')
    print(f'CTPP_BOUND_CHANNEL_ID={channel_id}')
    print(f'CTPP_CLOSE_RESPONSE_WORD={close_word}')
    print('CTPP_OPEN_REQUEST_TYPE=PASS')
    print('CTPP_CLOSE_REQUEST_TYPE=PASS')
    print('CTPP_CHANNEL_BINDING=PASS')
    print('CTPP_CONTROL_PLANE_RECONCILIATION=PASS')
    print('FIXTURE_ONLY=true')
    print('SECRETS_READ=false')
    print('NETWORK_ACTION_PERFORMED=false')
    print('PHYSICAL_DOOR_ACTION=false')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
