import tempfile
import unittest
from pathlib import Path
import hashlib
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "legacy_body_shape_inventory.py"
spec = importlib.util.spec_from_file_location("legacy_body_shape_inventory", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SYNTHETIC_SOURCE = b'''\
import asyncio
import struct

class IconaBridgeClient:
    def _create_binary_packet_from_buffers(self, request_id, *buffers):
        return b''.join(buffers)

    async def _open_door_init(self, channel):
        buffers = [struct.pack('>HI', 7, 9), b'SECRET-PAYLOAD']
        packet = self._create_binary_packet_from_buffers(channel.id, *buffers)
        await self._write_packet(packet)
        await self._read_response()
        await self._read_response()

    async def open_door(self, channel, item):
        def create_door_message(confirm: bool):
            return struct.pack('>I', 123456)

        await self._open_door_init(item)
        await self._write_packet(create_door_message(False))
        await self._write_packet(create_door_message(True))
        packet = self._create_binary_packet_from_buffers(channel.id, struct.pack('>I', 123456))
        await self._write_packet(packet)
        await asyncio.wait_for(self._read_response(), timeout=1)
        await asyncio.wait_for(self._read_response(), timeout=1)
        await self._write_packet(create_door_message(False))
        await self._write_packet(create_door_message(True))
        await self._close_channel(channel)

async def open_door(host, token, door_name):
    return False
'''


class LegacyBodyShapeInventoryTests(unittest.TestCase):
    def _analyze(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.py"
            path.write_bytes(SYNTHETIC_SOURCE)
            digest = hashlib.sha256(SYNTHETIC_SOURCE).hexdigest()
            return module.analyze_source(path, digest)

    def test_inventory_selects_qualified_methods_and_redacts_literal_values(self):
        text = "\n".join(self._analyze())
        self.assertIn("LEGACY_DOOR_BODY_SHAPE_INVENTORY=PASS", text)
        self.assertIn("METHOD_SELECTION=QUALIFIED_CLASS_METHOD", text)
        self.assertIn("FUNCTION=IconaBridgeClient._open_door_init", text)
        self.assertIn("FUNCTION=IconaBridgeClient.open_door", text)
        self.assertNotIn("FUNCTION=open_door\n", text)
        self.assertIn("BINARY_BODY_BUILDER_CALLS=1", text)
        self.assertIn("BODY_CALL_1_COMPONENTS=2", text)
        self.assertIn("STRUCT_PACK(fmt='>HI',argc=2)", text)
        self.assertIn("BODY_CALL_1_COMPONENT_1_STATIC_BYTES=6", text)
        self.assertIn("DOOR_MESSAGE_BUILDER_CALLS=4", text)
        self.assertIn("WRITE_PACKET_CALLS=5", text)
        self.assertIn("READ_RESPONSE_CALLS=2", text)
        self.assertIn("WAIT_FOR_CALLS=2", text)
        self.assertIn("OPEN_DOOR_INIT_CALLS=1", text)
        self.assertIn("CLOSE_CHANNEL_CALLS=1", text)
        self.assertNotIn("SECRET-PAYLOAD", text)
        self.assertNotIn("123456", text)
        self.assertIn("PAYLOAD_LITERAL_VALUES_EXTRACTED=false", text)
        self.assertIn("SOURCE_EXECUTED=false", text)
        self.assertIn("SECRETS_READ=false", text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)

    def test_nested_helper_body_is_not_counted_as_outer_method_calls(self):
        text = "\n".join(self._analyze())
        block = text.split("FUNCTION=IconaBridgeClient.open_door", 1)[1]
        self.assertIn("DOOR_MESSAGE_BUILDER_CALLS=4", block)
        self.assertIn("WRITE_PACKET_CALLS=5", block)
        self.assertNotIn("STRUCT_PACK(fmt='>I',argc=1)", block.split("DOOR_MESSAGE_CALL_1_LINE", 1)[0])

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.py"
            path.write_bytes(SYNTHETIC_SOURCE)
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                module.analyze_source(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
