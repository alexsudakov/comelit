from pathlib import Path
import unittest


WRAPPER = Path(__file__).resolve().parents[1] / "deploy" / "p13_wrapper_template.sh"


class P13WrapperEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WRAPPER.read_text(encoding="utf-8")

    def test_operation_id_gate_is_required_before_holder_exec(self):
        self.assertIn('OPERATION_ID="${P13_OPERATION_ID:-}"', self.text)
        self.assertIn("P13_WRAPPER_OPERATION_ID_MISSING=true", self.text)
        self.assertLess(
            self.text.index("P13_WRAPPER_OPERATION_ID_MISSING=true"),
            self.text.index('exec "$HOLDER_PATH"'),
        )

    def test_holder_uses_single_proven_no_argument_entrypoint(self):
        self.assertIn('exec "$HOLDER_PATH"', self.text)
        self.assertNotIn('exec "$HOLDER_PATH" --payload', self.text)
        self.assertNotIn('--operation-id "$OPERATION_ID"', self.text)
        self.assertNotIn('--emit-ctpp-markers', self.text.split('exec "$HOLDER_PATH"', 1)[1])


if __name__ == "__main__":
    unittest.main()
