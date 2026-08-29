import hashlib
import importlib.util
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "canonical_control_shape_inventory.py"
spec = importlib.util.spec_from_file_location("canonical_control_shape_inventory", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CanonicalControlShapeInventoryTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, text: str) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_inventory_is_structural_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "comelit_vip/application_session.py": "class VipApplicationSession:\n    pass\n",
                "comelit_vip/control_codec.py": textwrap.dedent("""
                    from dataclasses import dataclass
                    @dataclass
                    class OpenChannelRequest:
                        channel_name: str
                        channel_id: int
                    @dataclass
                    class OpenChannelResponse:
                        channel_id: int
                """),
                "comelit_vip/channel_session.py": textwrap.dedent("""
                    class VipChannelSession:
                        async def _send_control(self, message):
                            await self.session.send_frame(1, b'SENSITIVE-PAYLOAD')
                        async def recv_event(self):
                            return await self._recv_event_raw()
                        async def open_channel(self, channel_name: str, channel_flag: int, extension=None, channel_id=None):
                            cid = self.allocate_channel_id()
                            await self._send_control(channel_name)
                            event = await self.recv_event()
                            return event
                        async def close_channel(self, channel_id: int):
                            await self._send_control(channel_id)
                            return await self.recv_event()
                """),
                "comelit_vip/vip_session.py": textwrap.dedent("""
                    class VipSession:
                        async def send_frame(self, request_id: int, body: bytes):
                            await self.transport.write(body)
                """),
            }
            old_pinned = dict(module.PINNED)
            try:
                module.PINNED = {relative: self._write(root, relative, text) for relative, text in files.items()}
                for relative in module.TEST_FILES:
                    self._write(root, relative, "def test_open():\n    x = FixtureTransport(b'SENSITIVE-PAYLOAD')\n    return x\n")
                text = "\n".join(module.analyze(root))
            finally:
                module.PINNED = old_pinned

        self.assertIn("CANONICAL_CONTROL_SHAPE_INVENTORY=PASS", text)
        self.assertIn("METHOD=VipChannelSession.open_channel", text)
        self.assertIn("METHOD=VipChannelSession.close_channel", text)
        self.assertIn("FIELD path=comelit_vip/control_codec.py class=OpenChannelRequest name=channel_name", text)
        self.assertIn("CONST_BYTES(len=17)", text)
        self.assertNotIn("SENSITIVE-PAYLOAD", text)
        self.assertIn("SOURCE_EXECUTED=false", text)
        self.assertIn("SECRETS_READ=false", text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)


if __name__ == "__main__":
    unittest.main()
