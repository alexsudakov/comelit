import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_p13_real_payloads.py"
spec = importlib.util.spec_from_file_location("prepare_p13_real_payloads", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class PrepareP13RealPayloadTests(unittest.TestCase):
    def test_exact_ucfg_identity_is_pinned(self):
        self.assertEqual(
            module.EXPECTED_UCFG_SHA256,
            "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
        )
        self.assertEqual(module.CHANNEL_ID, 7449)

    def test_extract_vip_and_doors_from_nested_response(self):
        vip = {
            "apt-address": "100",
            "user-parameters": {
                "opendoor-address-book": [
                    {"name": "Main", "number": 1, "output-index": 2}
                ]
            },
        }
        doc = {"message": "configuration", "payload": {"vip": vip}}
        self.assertEqual(module.extract_vip(doc), vip)
        self.assertEqual(module.extract_doors(vip)[0]["name"], "Main")

    def test_single_target_auto_selects(self):
        doors = [{"name": "Main", "number": 1, "output-index": 2}]
        index, door = module.select_door(doors, None)
        self.assertEqual(index, 0)
        self.assertIs(door, doors[0])

    def test_multiple_targets_require_explicit_fingerprint(self):
        doors = [
            {"name": "Main", "number": 1, "output-index": 2},
            {"name": "Gate", "number": 2, "output-index": 3},
        ]
        with self.assertRaises(SystemExit) as ctx:
            module.select_door(doors, None)
        self.assertEqual(ctx.exception.code, 2)
        fp = module.door_fingerprint(doors[1])
        index, door = module.select_door(doors, fp)
        self.assertEqual(index, 1)
        self.assertIs(door, doors[1])

    def test_script_declares_no_live_action(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("LEGACY_NETWORK_METHODS_REPLACED=true", text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertIn("REAL_DOOR_PAYLOAD_VALUES_EMITTED=false", text)
        self.assertNotIn("asyncio.open_connection", text)
        self.assertNotIn("socket.", text)


if __name__ == "__main__":
    unittest.main()
