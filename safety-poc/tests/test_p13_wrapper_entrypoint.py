from pathlib import Path
import unittest


WRAPPER = Path(__file__).resolve().parents[1] / "deploy" / "p13_wrapper_template.sh"
BASE_SIGNALING_SHA256 = "a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9"


class P13WrapperEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WRAPPER.read_text(encoding="utf-8")

    def test_operation_id_gate_is_required_before_network_handoff(self):
        self.assertIn('OPERATION_ID="${P13_OPERATION_ID:-}"', self.text)
        self.assertIn("P13_WRAPPER_OPERATION_ID_MISSING=true", self.text)
        self.assertLess(
            self.text.index("P13_WRAPPER_OPERATION_ID_MISSING=true"),
            self.text.index('exec "$HOLDER_PATH"'),
        )

    def test_wrapper_restores_pinned_proven_signaling_orchestration(self):
        self.assertIn(
            "BASE_SIGNALING_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe",
            self.text,
        )
        self.assertIn(
            f"EXPECTED_BASE_SIGNALING_SHA256={BASE_SIGNALING_SHA256}",
            self.text,
        )
        self.assertIn('needle = \'"$BASE/bin/comelit_ice_offer_holder"\'', self.text)
        self.assertIn("if count != 1:", self.text)
        self.assertIn("P13_SIGNALING_BASE_HOLDER_INVOCATION_COUNT", self.text)
        self.assertIn("P13_SIGNALING_BASE_PIN=PASS", self.text)
        self.assertIn("P13_SIGNALING_HOLDER_BIND=PASS", self.text)

    def test_outer_wrapper_execs_exactly_one_derived_signaling_process(self):
        self.assertEqual(self.text.count('exec "$HOLDER_PATH"'), 1)
        self.assertIn('HOLDER_PATH="$SIGNALING_WRAPPER"', self.text)
        self.assertLess(
            self.text.index('HOLDER_PATH="$SIGNALING_WRAPPER"'),
            self.text.index('exec "$HOLDER_PATH"'),
        )
        self.assertNotIn('exec "$HOLDER_PATH" --payload', self.text)
        self.assertNotIn('--operation-id "$OPERATION_ID"', self.text)
        self.assertNotIn('--emit-ctpp-markers', self.text.split('exec "$HOLDER_PATH"', 1)[1])


if __name__ == "__main__":
    unittest.main()
