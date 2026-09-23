from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = (
    ROOT
    / "safety-poc"
    / "research"
    / "door"
    / "v1_5_7"
    / "comelit-v4-persistent-ctpp-door.c"
)
COMPONENT = ROOT / "custom_components" / "comelit"

if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58
import entrance_p116_r63_gate_peer_tap_actuation_transform as r63


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class P116R63GatePeerTapActuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r58 = r58.transform(cls.source)
        cls.generated_a = r63.transform(cls.source)
        cls.generated_b = r63.transform(cls.source)
        cls.const = load_module("r63_const", COMPONENT / "const.py")
        cls.runtime_text = (COMPONENT / "runtime.py").read_text(encoding="utf-8")
        cls.button_text = (COMPONENT / "button.py").read_text(encoding="utf-8")

    def test_transform_is_deterministic_and_preserves_r58_chain(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertIn("/* R58_STOP_CLEANUP_BEGIN */", self.generated_a)
        self.assertIn(r63.BEGIN, self.generated_a)
        self.assertIn(r63.END, self.generated_a)

    def test_entrance_bodies_are_byte_identical(self) -> None:
        for index in range(1, 6):
            with self.subTest(index=index):
                self.assertEqual(
                    r63._parse_array(self.r58, f"v4_door_operation_body_{index}"),
                    r63._parse_array(
                        self.generated_a, f"v4_door_operation_body_{index}"
                    ),
                )

    def test_gate_bodies_are_parameterised_peer_substitution_only(self) -> None:
        expected_counts = (1, 1, 2, 1, 1)
        for index, expected_count in enumerate(expected_counts, 1):
            with self.subTest(index=index):
                entrance = r63._parse_array(
                    self.generated_a, f"v4_door_operation_body_{index}"
                )
                gate = r63._parse_array(
                    self.generated_a, f"v4_gate_operation_body_{index}"
                )
                self.assertEqual(expected_count, entrance.count(b"00000643"))
                self.assertEqual(expected_count, gate.count(b"00000610"))
                self.assertEqual(
                    entrance.replace(b"00000643", b"00000610"),
                    gate,
                )
                self.assertIn(b"000401171", gate)

    def test_gate_profile_is_enabled_but_remains_one_shot_and_no_retry(self) -> None:
        capability = self.const.resolve_door_capability(
            self.const.DOOR_GATE, media_paused=False
        )
        self.assertTrue(capability.configured)
        self.assertTrue(capability.ring_source_validated)
        self.assertTrue(capability.actuation_profile_validated)
        self.assertTrue(capability.press_allowed)
        self.assertIsNone(capability.blocked_reason)
        self.assertEqual("00000610", capability.ring_source)
        self.assertEqual(
            (self.const.DOOR_ENTRANCE, self.const.DOOR_GATE),
            self.const.SUPPORTED_DOORS,
        )

    def test_runtime_binds_exact_target_before_existing_sigusr1(self) -> None:
        method_start = self.runtime_text.index("    async def async_open_door(")
        method_end = self.runtime_text.index(
            "\n    async def _async_run_once", method_start
        )
        method = self.runtime_text[method_start:method_end]
        self.assertIn("_write_door_target, door", method)
        self.assertIn("os.kill(process.pid, signal.SIGUSR1)", method)
        self.assertLess(
            method.index("_write_door_target, door"),
            method.index("os.kill(process.pid, signal.SIGUSR1)"),
        )
        self.assertEqual(method.count("os.kill(process.pid, signal.SIGUSR1)"), 1)
        self.assertIn('"automatic_retry_allowed": False', method)
        self.assertIn('"physical_effect_asserted": False', method)

    def test_native_missing_or_malformed_target_fails_before_write(self) -> None:
        self.assertIn('V4_DOOR_TARGET_FILE RUN_DIR "/door-target"', self.generated_a)
        self.assertIn('printf("V4_DOOR_TARGET_VALID=false\\n");', self.generated_a)
        invalid_at = self.generated_a.index('printf("V4_DOOR_TARGET_VALID=false')
        failed_at = self.generated_a.index(
            'v4_door_emit_result("FAILED_SAFE")', invalid_at
        )
        first_write_at = self.generated_a.index(
            "v4_door_queue_write(1)", failed_at
        )
        self.assertLess(invalid_at, failed_at)
        self.assertLess(failed_at, first_write_at)

    def test_gate_button_uses_runtime_and_keeps_conservative_outcome(self) -> None:
        start = self.button_text.index("class ComelitGateDoorButton")
        gate = self.button_text[start:]
        self.assertIn("await self._runtime.async_open_door(DOOR_GATE)", gate)
        self.assertIn('"automatic_retry_allowed": False', gate)
        self.assertIn('"physical_effect_asserted": False', gate)
        self.assertIn('result.get("one_shot_sequence_sent") is True', gate)
        self.assertNotIn("Deliberately no runtime call", gate)

    def test_gate_action_does_not_add_second_ctpp_open_or_retry(self) -> None:
        # R63 changes target selection only; the established listener-owned
        # CTPP queue remains the sole transmission path.
        self.assertEqual(
            self.generated_a.count("signal(SIGUSR1, v4_door_signal_handler);"),
            1,
        )
        self.assertIn(
            "The listener-owned CTPP channel is deliberately reused here.",
            self.generated_a,
        )
        self.assertNotIn("automatic_retry_allowed = TRUE", self.generated_a)
        self.assertNotIn("PHYSICAL_EFFECT_ASSERTED=true", self.generated_a)


if __name__ == "__main__":
    unittest.main()
