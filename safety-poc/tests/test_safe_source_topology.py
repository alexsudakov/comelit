import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "safe_source_topology.py"
spec = importlib.util.spec_from_file_location("safe_source_topology", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class SafeSourceTopologyTests(unittest.TestCase):
    def test_literal_values_are_not_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                'PASSWORD = "do-not-print-this"\n'
                'PAYLOAD = b"\\x01\\x02\\x03"\n'
                'def demo(token: str):\n'
                '    return struct.pack(">H", 7) + PAYLOAD\n',
                encoding="utf-8",
            )
            output = "\n".join(module.analyze_file(source, "sample.py"))
            self.assertNotIn("do-not-print-this", output)
            self.assertNotIn("\\x01", output)
            self.assertIn("str(utf8_len=17)", output)
            self.assertIn("bytes(len=3)", output)
            self.assertIn("literal_format_len=2", output)

    def test_sensitive_identifier_is_hashed(self):
        value = module.safe_identifier("client_password")
        self.assertTrue(value.startswith("<sensitive-name sha256="))
        self.assertNotIn("client_password", value)


if __name__ == "__main__":
    unittest.main()
