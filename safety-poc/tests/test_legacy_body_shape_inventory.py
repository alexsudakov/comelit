from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "legacy_body_shape_inventory.py"
spec = importlib.util.spec_from_file_location("legacy_body_shape_inventory", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SYNTHETIC_SOURCE = b'''\
import struct

class Demo:
    def _create_binary_packet_from_buffers(self, request_id, *buffers):
        return b''.join(buffers)

    async def _open_door_init(self, channel):
        alpha = struct.pack('>HI', 7, 9)
        beta = b'SECRET-PAYLOAD'
        packet = self._create_binary_packet_from_buffers(channel.id, alpha, beta)
        await self._write_packet(packet)
        await self._read_response()
        await self._read_response()

    async def open_door(self, channel, item):
        packet = self._create_binary_packet_from_buffers(channel.id, struct.pack('>I', 123456))
        await self._write_packet(create_door_message(channel.id, item, 'TOP-SECRET-A'))
        await self._write_packet(create_door_message(channel.id, item, 'TOP-SECRET-B'))
        await self._write_packet(packet)
        await self._read_response()
        await self._read_response()
        await self._write_packet(create_door_message(channel.id, item, 'TOP-SECRET-C'))
        await self._write_packet(create_door_message(channel.id, item, 'TOP-SECRET-D'))
'''


class LegacyBodyShapeInventoryTests(unittest.TestCase):
    def _analyze(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.py"
            path.write_bytes(SYNTHETIC_SOURCE)
            digest = hashlib.sha256(SYNTHETIC_SOURCE).hexdigest()
            return module.analyze_source(path, digest)

    def test_inventory_is_structural_and_redacts_literal_values(self):
        text = "\n".join(self._analyze())
        self.assertIn("LEGACY_DOOR_BODY_SHAPE_INVENTORY=PASS", text)
        self.assertIn("FUNCTION=_open_door_init", text)
        self.assertIn("FUNCTION=open_door", text)
        self.assertIn("BINARY_BODY_BUILDER_CALLS=1", text)
        self.assertIn("STRUCT_PACK(fmt='>HI',argc=2)", text)
        self.assertIn("BODY_CALL_1_COMPONENT_1_STATIC_BYTES=6", text)
        self.assertIn("DOOR_MESSAGE_BUILDER_CALLS=4", text)
        self.assertNotIn("SECRET-PAYLOAD", text)
        self.assertNotIn("TOP-SECRET", text)
        self.assertNotIn("123456", text)
        self.assertIn("PAYLOAD_LITERAL_VALUES_EXTRACTED=false", text)
        self.assertIn("SOURCE_EXECUTED=false", text)
        self.assertIn("SECRETS_READ=false", text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.py"
            path.write_bytes(SYNTHETIC_SOURCE)
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                module.analyze_source(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
