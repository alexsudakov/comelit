#!/usr/bin/env python3
"""P122 Home Assistant routing contract for on-demand media-owned Door."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
MEDIA_TRANSPORT = COMPONENT / "media_transport.py"
BUTTON = COMPONENT / "button.py"
INIT = COMPONENT / "__init__.py"


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    return ast.get_source_segment(source, node) or ""


def class_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.ClassDef) and item.name == name
    )
    return ast.get_source_segment(source, node) or ""


class P122OnDemandDoorPythonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.media = MEDIA_TRANSPORT.read_text(encoding="utf-8")
        cls.button = BUTTON.read_text(encoding="utf-8")
        cls.init = INIT.read_text(encoding="utf-8")

    def test_media_transport_has_exactly_one_sigusr1_door_boundary(self) -> None:
        method = function_source(self.media, "async_open_door")
        self.assertEqual(method.count("os.kill(process.pid, signal.SIGUSR1)"), 1)
        self.assertIn("async with self._door_lock", method)
        self.assertIn("if (\n                not self.active", method)
        self.assertIn("timeout=5", method)
        self.assertIn('"automatic_retry_allowed"] = False', self.media)
        self.assertIn('"physical_effect_asserted"] = False', self.media)
        self.assertIn('door=entrance media_active=%s', method)
        self.assertNotIn("async_start(", method)
        self.assertNotIn("async_negotiate_p2p", method)

    def test_media_transport_consumes_bounded_p122_result(self) -> None:
        observer = function_source(self.media, "_observe_on_demand_door_marker")
        reader = function_source(self.media, "_async_read_output")
        for marker in (
            "P122_ON_DEMAND_DOOR_COMMAND_ACCEPTED",
            "P122_ON_DEMAND_DOOR_PATH=MEDIA_SESSION_SINGLE",
            "P122_ON_DEMAND_DOOR_EXISTING_CTPP_REUSED",
            "P122_ON_DEMAND_DOOR_SENT",
            "P122_ON_DEMAND_DOOR_WRITE_COUNT=1",
            "P122_ON_DEMAND_DOOR_ACK_OBSERVED",
            "P122_ON_DEMAND_DOOR_RESULT=",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, observer)
        self.assertIn("self._observe_on_demand_door_marker(line)", reader)
        self.assertIn('"P122_"', self.media)
        self.assertNotIn("_LOGGER.warning(line", observer)
        self.assertNotIn("payload", observer.lower())
        self.assertNotIn("channel_id", observer.lower())

    def test_service_routes_active_media_entrance_without_resuming_listener(self) -> None:
        setup = function_source(self.init, "async_setup")
        self.assertIn("if supervisor.media_paused:", setup)
        self.assertIn("door == DOOR_ENTRANCE", setup)
        self.assertIn("media_transport.active", setup)
        self.assertIn("await media_transport.async_open_door(", setup)
        self.assertNotIn("async_resume_after_media", setup)
        self.assertNotIn("async_start()", setup)

    def test_button_exposes_active_media_entrance_and_gate_stays_fail_closed(self) -> None:
        entrance = class_source(self.button, "ComelitEntranceDoorButton")
        gate = class_source(self.button, "ComelitGateDoorButton")
        self.assertIn("_on_demand_media_door_ready", entrance)
        self.assertIn("self._media_transport.active", entrance)
        self.assertIn("await self._media_transport.async_open_door()", entrance)
        self.assertIn("if self._supervisor.media_paused:", gate)
        self.assertNotIn("_media_transport", gate)
        self.assertNotIn("MEDIA_SESSION_SINGLE", gate)

    def test_on_demand_result_is_conservative(self) -> None:
        method = function_source(self.media, "async_open_door")
        self.assertIn('"protocol_acked": False', method)
        self.assertIn('"door_specific_ack_proven": False', method)
        self.assertIn('"physical_effect_asserted"] = False', self.media)
        self.assertIn('"one_shot_sequence_sent": one_shot_sequence_sent', method)
        self.assertIn('diagnostic.get("door_path") == "MEDIA_SESSION_SINGLE"', method)
        self.assertNotIn('"physical_effect_asserted": True', self.media)


if __name__ == "__main__":
    unittest.main()
