from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_target_provenance.py"
spec = importlib.util.spec_from_file_location("p13_target_provenance", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


APT = "12345678"
SUB = "9"
ENTRANCE = b"87654321"
OUTPUT = 1
TARGET_FP = "a" * 64


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pair_pin() -> str:
    return hashlib.sha256(ENTRANCE + b"|1").hexdigest()


def target_body() -> bytes:
    return b"\xc0\x18fixture\x00\x2d" + ENTRANCE + b"\x00\x00" + bytes([OUTPUT]) + b"tail"


def payload() -> dict:
    body = target_body()
    bodies = [body] + [bytes([index]) * 12 for index in range(1, 6)]
    return {
        "schema": 1,
        "ucfg_sha256": module.EXPECTED_UCFG_SHA256,
        "target_fingerprint": TARGET_FP,
        "bodies": [
            {
                "hex": value.hex(),
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }
            for value in bodies
        ],
    }


def ucfg(actions_marker=...):
    params = {}
    if actions_marker is not ...:
        params["opendoor-actions"] = actions_marker
    return {
        "payload": {
            "vip": {
                "apt-address": APT,
                "apt-subaddress": SUB,
                "user-parameters": params,
            }
        }
    }


class P13TargetProvenanceTests(unittest.TestCase):
    def patches(self):
        return (
            mock.patch.object(module, "EXPECTED_APT_ADDRESS_SHA256", sha(APT)),
            mock.patch.object(module, "EXPECTED_APT_SUBADDRESS_SHA256", sha(SUB)),
            mock.patch.object(module, "EXPECTED_PEER_TARGET_SHA256", pair_pin()),
            mock.patch.object(module, "EXPECTED_TARGET_FINGERPRINT", TARGET_FP),
        )

    def verify_with_patches(self, doc):
        patches = self.patches()
        for patch in patches:
            patch.start()
        try:
            return module.verify(doc, payload())
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_absent_opendoor_actions_is_explicit_and_non_blocking(self):
        result = self.verify_with_patches(ucfg())
        self.assertEqual(result["P13_UCFG_OPENDOOR_ACTION_PRESENT"], "false")
        self.assertEqual(result["P13_UCFG_OUTPUT_INDEX"], "ABSENT")
        self.assertEqual(result["P13_TARGET_PROVENANCE"], "PASS")

    def test_empty_opendoor_actions_is_explicit_and_non_blocking(self):
        result = self.verify_with_patches(ucfg([]))
        self.assertEqual(result["P13_UCFG_OPENDOOR_ACTION_PRESENT"], "true")
        self.assertEqual(result["P13_UCFG_OUTPUT_INDEX"], "ABSENT")

    def test_matching_peer_output_passes(self):
        result = self.verify_with_patches(
            ucfg([{"action": "peer", "output-index": OUTPUT}])
        )
        self.assertEqual(result["P13_UCFG_OUTPUT_INDEX"], "MATCH")
        self.assertEqual(result["P13_ENTRANCE_TARGET_MATCH"], "PASS")
        self.assertGreaterEqual(int(result["P13_PREPARED_CAPTURE_TARGET_MATCH_COUNT"]), 1)

    def test_present_mismatching_peer_output_fails_closed(self):
        patches = self.patches()
        for patch in patches:
            patch.start()
        try:
            with self.assertRaises(RuntimeError):
                module.verify(ucfg([{"action": "peer", "output-index": 2}]), payload())
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_present_non_peer_metadata_fails_closed(self):
        patches = self.patches()
        for patch in patches:
            patch.start()
        try:
            with self.assertRaises(RuntimeError):
                module.verify(ucfg([{"action": "other", "output-index": OUTPUT}]), payload())
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_payload_without_capture_target_semantic_fails(self):
        patches = self.patches()
        for patch in patches:
            patch.start()
        try:
            bad = payload()
            generic = b"generic-no-target"
            bad["bodies"] = [
                {
                    "hex": generic.hex(),
                    "bytes": len(generic),
                    "sha256": hashlib.sha256(generic).hexdigest(),
                }
                for _ in range(6)
            ]
            with self.assertRaises(RuntimeError):
                module.verify(ucfg(), bad)
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_source_is_offline_only(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertIn("SEND_ARMED_REACHED=false", text)
        self.assertNotIn("socket.socket", text)
        self.assertNotIn("asyncio.open_connection", text)


if __name__ == "__main__":
    unittest.main()
