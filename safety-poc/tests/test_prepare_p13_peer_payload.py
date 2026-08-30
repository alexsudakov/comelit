from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
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

    def test_exact_p12_runtime_ucfg_path_is_known(self):
        self.assertEqual(
            module.P12_RUNTIME_UCFG,
            Path("/run/comelit-p2p/p12-ucfg-response.json"),
        )

    def test_runtime_ucfg_is_selected_only_when_sha_matches(self):
        with tempfile.TemporaryDirectory() as td:
            capture = Path(td) / "p12-ucfg-response.json"
            raw = b'{"fixture":"ucfg"}'
            capture.write_bytes(raw)
            expected = hashlib.sha256(raw).hexdigest()
            with (
                mock.patch.object(module, "P12_RUNTIME_UCFG", capture),
                mock.patch.object(module.base, "EXPECTED_UCFG_SHA256", expected),
                mock.patch.object(module.base, "_walk_ucfg_candidates", return_value=iter(())),
            ):
                self.assertEqual(module.find_pinned_ucfg(), capture)

            capture.write_bytes(b"different")
            with (
                mock.patch.object(module, "P12_RUNTIME_UCFG", capture),
                mock.patch.object(module.base, "EXPECTED_UCFG_SHA256", expected),
                mock.patch.object(module.base, "_walk_ucfg_candidates", return_value=iter(())),
            ):
                with self.assertRaises(RuntimeError):
                    module.find_pinned_ucfg()

    def test_source_declares_offline_only(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertNotIn("socket.", text)
        self.assertNotIn("asyncio.open_connection", text)


if __name__ == "__main__":
    unittest.main()
