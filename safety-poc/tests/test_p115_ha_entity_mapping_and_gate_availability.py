#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def class_node(source: str, name: str) -> ast.ClassDef:
    tree = ast.parse(source)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def class_source(source: str, name: str) -> str:
    node = class_node(source, name)
    return ast.get_source_segment(source, node) or ""


class P115HaEntityMappingAndGateAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.const_text = (COMPONENT / "const.py").read_text(encoding="utf-8")
        cls.button_text = (COMPONENT / "button.py").read_text(encoding="utf-8")
        cls.camera_text = (COMPONENT / "camera.py").read_text(encoding="utf-8")
        cls.switch_text = (COMPONENT / "switch.py").read_text(encoding="utf-8")
        cls.session_text = (COMPONENT / "media_session.py").read_text(
            encoding="utf-8"
        )
        cls.services_text = (COMPONENT / "services.yaml").read_text(
            encoding="utf-8"
        )
        cls.const = load_module("comelit_const", COMPONENT / "const.py")
        cls.media = load_module(
            "comelit_media_session",
            COMPONENT / "media_session.py",
        )

    def test_camera_entity_carries_camera_identity(self) -> None:
        camera = class_source(self.camera_text, "ComelitEntranceCamera")
        self.assertIn("ENTRANCE_CAMERA_ENTITY_ID", camera)
        self.assertIn('_attr_name = "Comelit — Камера подъезда"', camera)
        self.assertIn('_attr_icon = "mdi:video"', camera)
        self.assertNotIn("mdi:doorbell-video", camera)

    def test_switch_entity_carries_panel_session_identity(self) -> None:
        switch = class_source(self.switch_text, "ComelitEntranceMediaSwitch")
        self.assertIn("ENTRANCE_MEDIA_SWITCH_ENTITY_ID", switch)
        self.assertIn('_attr_name = "Comelit — Подъезд"', switch)
        self.assertIn('_attr_icon = "mdi:doorbell-video"', switch)
        self.assertNotIn('_attr_icon = "mdi:video"', switch)

    def test_entity_ids_and_unique_ids_are_unchanged(self) -> None:
        self.assertIn(
            'ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"',
            self.const_text,
        )
        self.assertIn(
            'ENTRANCE_MEDIA_SWITCH_ENTITY_ID = "switch.comelit_entrance_camera"',
            self.const_text,
        )
        self.assertIn(
            'ENTRANCE_CAMERA_UNIQUE_ID = "comelit_entrance_camera"',
            self.const_text,
        )
        self.assertIn(
            'ENTRANCE_MEDIA_SWITCH_UNIQUE_ID = "comelit_entrance_media_session"',
            self.const_text,
        )
        self.assertIn("self.entity_id = ENTRANCE_CAMERA_ENTITY_ID", self.camera_text)
        self.assertIn(
            "self.entity_id = ENTRANCE_MEDIA_SWITCH_ENTITY_ID",
            self.switch_text,
        )

    def test_no_duplicate_entities_are_added(self) -> None:
        self.assertEqual(self.camera_text.count("async_add_entities(["), 1)
        self.assertEqual(self.switch_text.count("async_add_entities(["), 1)
        self.assertIn("ComelitEntranceCamera(manager, transport)", self.camera_text)
        self.assertIn(
            "ComelitEntranceMediaSwitch(manager, transport)",
            self.switch_text,
        )

    def test_gate_availability_is_capability_derived_not_literal(self) -> None:
        gate = class_source(self.button_text, "ComelitGateDoorButton")
        self.assertNotIn("_attr_available =", gate)
        self.assertIn("resolve_door_capability(", gate)
        self.assertIn("def available(self) -> bool:", gate)
        self.assertIn(".available", gate)

    def test_resolver_positive_case_gate_configured_and_idle(self) -> None:
        capability = self.const.resolve_door_capability(
            self.const.DOOR_GATE,
            media_paused=False,
        )
        self.assertTrue(capability.available)
        self.assertTrue(capability.configured)
        self.assertTrue(capability.ring_source_validated)
        self.assertFalse(capability.actuation_profile_validated)
        self.assertFalse(capability.press_allowed)
        self.assertEqual(capability.ring_source, "00000610")

    def test_resolver_negative_case_media_exclusivity(self) -> None:
        gate = self.const.resolve_door_capability(
            self.const.DOOR_GATE,
            media_paused=True,
        )
        entrance = self.const.resolve_door_capability(
            self.const.DOOR_ENTRANCE,
            media_paused=True,
        )
        self.assertFalse(gate.available)
        self.assertIsNotNone(gate.blocked_reason)
        self.assertFalse(entrance.available)
        self.assertEqual(
            gate.blocked_reason,
            "media_session_exclusive_connection",
        )
        self.assertEqual(entrance.blocked_reason, gate.blocked_reason)

    def test_resolver_negative_case_unvalidated_target(self) -> None:
        capability = self.const.resolve_door_capability(
            "unknown",
            media_paused=False,
        )
        self.assertFalse(capability.available)
        self.assertFalse(capability.configured)
        self.assertFalse(capability.press_allowed)
        self.assertEqual(capability.blocked_reason, "door_target_not_configured")
        self.assertIsNone(capability.ring_source)

    def test_gate_press_path_remains_fail_closed(self) -> None:
        gate = class_source(self.button_text, "ComelitGateDoorButton")
        tree = ast.parse(gate)
        press = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_press"
        )
        self.assertTrue(any(isinstance(node, ast.Raise) for node in ast.walk(press)))
        self.assertNotIn("async_open_door(DOOR_GATE)", self.button_text)
        self.assertEqual(self.const.SUPPORTED_DOORS, (self.const.DOOR_ENTRANCE,))
        self.assertNotIn("- gate", self.services_text)

    def test_media_hard_limit_is_centralised(self) -> None:
        self.assertIn("def hard_limit_seconds(self) -> float:", self.session_text)
        self.assertIn("return self._hard_limit_seconds", self.session_text)
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", self.session_text)
        self.assertNotIn('"hard_limit_seconds": 600', self.camera_text)
        self.assertNotIn('"hard_limit_seconds": 600', self.switch_text)

        class Listener:
            @property
            def media_paused(self) -> bool:
                return False

            async def async_pause_for_media(self) -> None:
                raise AssertionError("not used")

            async def async_resume_after_media(self) -> None:
                raise AssertionError("not used")

        class Transport:
            @property
            def active(self) -> bool:
                return False

            async def async_start(self, panel: str) -> None:
                raise AssertionError("not used")

            async def async_stop(self) -> None:
                raise AssertionError("not used")

        default_manager = self.media.ComelitMediaSessionManager(
            Listener(),
            Transport(),
        )
        explicit_manager = self.media.ComelitMediaSessionManager(
            Listener(),
            Transport(),
            hard_limit_seconds=42,
        )
        self.assertEqual(
            default_manager.hard_limit_seconds,
            self.media.MEDIA_SESSION_HARD_LIMIT_SECONDS,
        )
        self.assertEqual(default_manager.hard_limit_seconds, 600)
        self.assertEqual(explicit_manager.hard_limit_seconds, 42)


if __name__ == "__main__":
    unittest.main()
