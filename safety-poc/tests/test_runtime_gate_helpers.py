import asyncio
import struct
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import runtime_gate_common as common
import verify_legacy_synthetic_body_oracle as oracle


class RuntimeGateHelperTests(unittest.TestCase):
    def test_extract_control_request_id_from_send_control(self):
        source = textwrap.dedent('''
            class VipChannelSession:
                async def _send_control(self, message):
                    body = encode_control_message(message)
                    await self.session.send_frame(17, body)
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'channel_session.py'
            path.write_text(source, encoding='utf-8')
            self.assertEqual(common.extract_control_request_id(path), 17)

    def test_synthetic_scalar_is_text_and_integer_compatible(self):
        value = oracle.SyntheticScalar('unit-test')
        self.assertTrue(value.encode().startswith(b'SYNTH-'))
        packed = struct.pack('>I', value)
        self.assertEqual(len(packed), 4)
        self.assertEqual(bytes(value), value.encode('ascii'))

    def test_sandboxed_legacy_capture_produces_exactly_six_frames(self):
        source = textwrap.dedent('''
            import struct

            class IconaBridgeClient:
                def __init__(self, host, port):
                    self.host = host
                    self.port = port

                def _string_to_buffer(self, value, null_terminated=True):
                    data = value.encode('utf-8')
                    return data + (b'\\x00' if null_terminated else b'')

                def _create_binary_packet_from_buffers(self, request_id, *buffers):
                    return b'HEADER00' + b''.join(buffers)

                async def _open_door_init(self, vip):
                    channel = await self._open_channel('CTPP')
                    packet = self._create_binary_packet_from_buffers(
                        channel.id,
                        bytes([1, 2, 3, 4]),
                        self._string_to_buffer(vip.get('alpha'), True),
                    )
                    await self._write_packet(packet)
                    await self._read_response()
                    await self._read_response()
                    return channel

                async def open_door(self, vip, door_item):
                    channel = await self._open_door_init(vip)

                    def create_door_message(confirm):
                        body = struct.pack('>I', int(door_item.get('number')))
                        body += bytes([1 if confirm else 0])
                        return self._create_binary_packet_from_buffers(channel.id, body)

                    await self._write_packet(create_door_message(False))
                    await self._write_packet(create_door_message(True))
                    packet = self._create_binary_packet_from_buffers(
                        channel.id,
                        bytes([9, 8]),
                        self._string_to_buffer(vip.get('beta'), True),
                    )
                    await self._write_packet(packet)
                    await self._read_response()
                    await self._read_response()
                    await self._write_packet(create_door_message(False))
                    await self._write_packet(create_door_message(True))
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'legacy.py'
            path.write_text(source, encoding='utf-8')
            original = oracle.require_legacy_pin
            oracle.require_legacy_pin = lambda source: None
            try:
                packets = asyncio.run(oracle._capture_legacy_packets(path))
            finally:
                oracle.require_legacy_pin = original

        self.assertEqual(len(packets), 6)
        self.assertTrue(all(packet.startswith(b'HEADER00') for packet in packets))
        self.assertTrue(all(len(packet) > 8 for packet in packets))


if __name__ == '__main__':
    unittest.main()
