from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_p13_peer_payload.py"
spec = importlib.util.spec_from_file_location("prepare_p13_peer_payload", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class PrepareP13PeerPayloadTests(unittest.TestCase):
    def _vip(self) -> dict:
        return {
            "apt-address": "redacted",
            "user-parameters": {
                "opendoor-address-book": [],
                "opendoor-actions": [{"action": "peer", "output-index": 1}],
            },
        }

    def test_empty_address_book_uses_runtime_pinned_peer_target(self):
        env = {
            "P13_PEER_ENTRANCE": "00000643",
            "P13_PEER_OUTPUT_INDEX": "1",
            "P13_PEER_ENTRANCE_NAME": "fixture",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            doors = module.extract_doors_with_peer_fallback(self._vip())
        self.assertEqual(len(doors), 1)
        self.assertEqual(doors[0]["number"], "00000643")
        self.assertEqual(doors[0]["output-index"], 1)
        self.assertEqual(doors[0]["name"], "fixture")

    def test_wrong_runtime_target_fails_closed(self):
        env = {
            "P13_PEER_ENTRANCE": "00000610",
            "P13_PEER_OUTPUT_INDEX": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                module.extract_doors_with_peer_fallback(self._vip())

    def test_peer_action_is_required(self):
        vip = {
            "user-parameters": {
                "opendoor-address-book": [],
                "opendoor-actions": [{"action": "other"}],
            }
        }
        env = {
            "P13_PEER_ENTRANCE": "00000643",
            "P13_PEER_OUTPUT_INDEX": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                module.extract_doors_with_peer_fallback(vip)

    def test_source_declares_offline_only(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertNotIn("socket.", text)
        self.assertNotIn("asyncio.open_connection", text)


if __name__ == "__main__":
    unittest.main()
