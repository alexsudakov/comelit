import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_application_templates.py"
spec = importlib.util.spec_from_file_location("p12_application_templates", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P12ApplicationTemplateTests(unittest.TestCase):
    def test_close_uaut_predicted_shape(self):
        packet = module.predicted_control_packet(opcode=3, channel_id=7449)
        self.assertEqual(
            packet.hex(),
            "00060a0000000000cdab030002000000191d",
        )

    def test_open_ucfg_predicted_shape(self):
        packet = module.predicted_control_packet(
            opcode=1,
            channel_id=7450,
            channel_name=b"UCFG",
        )
        self.assertEqual(
            packet.hex(),
            "00060f0000000000cdab010007000000554346471a1d00",
        )

    def test_close_ucfg_predicted_shape(self):
        packet = module.predicted_control_packet(opcode=3, channel_id=7450)
        self.assertEqual(
            packet.hex(),
            "00060a0000000000cdab0300020000001a1d",
        )

    def test_auth_contract_has_real_lf_and_expected_length(self):
        body = (
            '{"message":"access","user-token":"'
            + module.SYNTHETIC_TOKEN
            + '","message-type":"request","message-id":5}\n'
        ).encode()
        self.assertEqual(len(body), 109)
        self.assertTrue(body.endswith(b"\n"))
        self.assertFalse(body.endswith(b"\\n"))


if __name__ == "__main__":
    unittest.main()
