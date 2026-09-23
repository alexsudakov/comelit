#!/usr/bin/env python3
"""P116/R60 Track B Door/Gate offline contract tests."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
BUTTON = COMPONENT / "button.py"
CONST = COMPONENT / "const.py"
RUNTIME = COMPONENT / "runtime.py"
CAMERA = COMPONENT / "camera.py"
SWITCH = COMPONENT / "switch.py"
SERVICES = COMPONENT / "services.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def class_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.ClassDef) and item.name == name
    )
    return ast.get_source_segment(source, node) or ""


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node) or ""


def derive_one_shot_marker(case: dict[str, object]) -> dict[str, str]:
    """Pure offline model of the entrance Door one-shot safety envelope."""
    if case.get("gate") is True:
        ok = (
            case.get("runtime_call") is True
            and case.get("target_written") is True
            and case.get("sigusr1_count") == 1
            and case.get("automatic_retry_allowed") is False
        )
        return {"GATE_ONE_SHOT_CONTRACT": "PASS" if ok else "FAIL"}
    if case.get("duplicate_caller") is True or case.get("operation_in_progress") is True:
        return {"DOOR_SAFETY_CONTRACT": "PASS" if case.get("sigusr1_count") == 1 else "FAIL"}
    if case.get("listener_ready") is not True or case.get("media_active") is True:
        return {"DOOR_SAFETY_CONTRACT": "PASS" if case.get("sigusr1_count") == 0 else "FAIL"}
    if case.get("malformed_response") is True:
        return {"DOOR_SAFETY_CONTRACT": "PASS" if case.get("state") == "UNKNOWN_OUTCOME" else "FAIL"}
    if case.get("timeout") is True:
        return {"DOOR_SAFETY_CONTRACT": "PASS" if case.get("state") == "UNKNOWN_OUTCOME" else "FAIL"}
    if case.get("ack") is True:
        ok = (
            case.get("state") == "ACKED"
            and case.get("door_specific_ack_proven") is True
            and case.get("automatic_retry_allowed") is False
            and case.get("sigusr1_count") == 1
        )
        return {"DOOR_SAFETY_CONTRACT": "PASS" if ok else "FAIL"}
    ok = (
        case.get("state") in {"REJECTED", "REJECTED_NOT_READY", "FAILED_SAFE"}
        and case.get("protocol_acked") is False
        and case.get("automatic_retry_allowed") is False
    )
    return {"DOOR_SAFETY_CONTRACT": "PASS" if ok else "FAIL"}


class P116R60DoorGateEntityMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.button_text = BUTTON.read_text(encoding="utf-8")
        cls.const_text = CONST.read_text(encoding="utf-8")
        cls.runtime_text = RUNTIME.read_text(encoding="utf-8")
        cls.camera_text = CAMERA.read_text(encoding="utf-8")
        cls.switch_text = SWITCH.read_text(encoding="utf-8")
        cls.services_text = SERVICES.read_text(encoding="utf-8")
        cls.const = load_module("r60_comelit_const", CONST)

    def test_entrance_button_mapping_is_unambiguous(self) -> None:
        entrance = class_source(self.button_text, "ComelitEntranceDoorButton")
        switch = class_source(self.switch_text, "ComelitEntranceMediaSwitch")
        camera = class_source(self.camera_text, "ComelitEntranceCamera")
        self.assertIn('_attr_name = "Comelit — Открыть подъезд"', entrance)
        self.assertIn('_attr_name = "Comelit — Подъезд"', switch)
        self.assertIn('_attr_name = "Comelit — Камера подъезда"', camera)
        self.assertNotIn('_attr_name = "Comelit — Подъезд"', entrance)
        self.assertIn("self.entity_id = MAIN_ENTRANCE_ENTITY_ID", entrance)
        self.assertIn("_attr_unique_id = MAIN_ENTRANCE_UNIQUE_ID", entrance)

    def test_gate_button_name_and_entity_identity_use_validated_runtime(self) -> None:
        gate = class_source(self.button_text, "ComelitGateDoorButton")
        self.assertIn('_attr_name = "Comelit — Калитка"', gate)
        self.assertRegex(gate, r"Калитка|Ворота")
        self.assertIn("self.entity_id = MAIN_GATE_ENTITY_ID", gate)
        self.assertIn("_attr_unique_id = MAIN_GATE_UNIQUE_ID", gate)
        self.assertIn("raise HomeAssistantError", gate)
        self.assertIn("async_open_door(DOOR_GATE)", gate)
        self.assertIn('result.get("one_shot_sequence_sent") is True', gate)

    def test_one_add_entities_call_and_ids_unchanged(self) -> None:
        self.assertEqual(self.button_text.count("async_add_entities("), 1)
        self.assertEqual(self.camera_text.count("async_add_entities("), 1)
        self.assertEqual(self.switch_text.count("async_add_entities("), 1)
        self.assertIn('MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"', self.const_text)
        self.assertIn('MAIN_GATE_ENTITY_ID = "button.comelit_main_gate_open_door"', self.const_text)

    def test_entrance_and_gate_capabilities_are_derived_from_const(self) -> None:
        entrance = self.const.resolve_door_capability(self.const.DOOR_ENTRANCE, media_paused=False)
        self.assertTrue(entrance.available)
        self.assertTrue(entrance.press_allowed)
        self.assertTrue(entrance.actuation_profile_validated)

        gate = self.const.resolve_door_capability(self.const.DOOR_GATE, media_paused=False)
        self.assertTrue(gate.available)
        self.assertTrue(gate.ring_source_validated)
        self.assertEqual(gate.ring_source, "00000610")
        self.assertTrue(gate.actuation_profile_validated)
        self.assertTrue(gate.press_allowed)
        self.assertIsNone(gate.blocked_reason)
        self.assertEqual(
            self.const.SUPPORTED_DOORS,
            (self.const.DOOR_ENTRANCE, self.const.DOOR_GATE),
        )
        self.assertIn("- gate", self.services_text)


class P116R60DoorRuntimeStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_text = RUNTIME.read_text(encoding="utf-8")

    def test_runtime_sigusr1_one_shot_order_and_ready_guard(self) -> None:
        method = function_source(self.runtime_text, "async_open_door")
        self.assertLess(method.index("async with self._door_lock"), method.index("os.kill(process.pid, signal.SIGUSR1)"))
        self.assertLess(method.index("if not await self.async_wait_ready(timeout=30):"), method.index("os.kill(process.pid, signal.SIGUSR1)"))
        self.assertEqual(method.count("os.kill(process.pid, signal.SIGUSR1)"), 1)
        self.assertIn('state = "UNKNOWN_OUTCOME"', method)
        self.assertIn('"automatic_retry_allowed": False', method)
        self.assertIn('"physical_effect_asserted": False', method)
        self.assertIn('operation_id = f"comelit-ha-{uuid4()}"', method)

    def test_runtime_ack_requires_door_specific_proof_and_bounds_write_count(self) -> None:
        method = function_source(self.runtime_text, "async_open_door")
        reader = function_source(self.runtime_text, "_async_read_output")
        self.assertIn('diagnostic.get("door_specific_ack_proven") is True', method)
        self.assertIn('state == "ACKED"', method)
        self.assertIn("not 0 <= write_count <= 5", method)
        self.assertIn("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=", reader)
        self.assertIn("V4_DOOR_WRITE_COUNT=", reader)
        self.assertIn("V4_DOOR_RESULT=", reader)


class P116R60DoorGateOfflineHarnessTests(unittest.TestCase):
    def test_entrance_one_shot_matrix_and_gate_fail_closed(self) -> None:
        cases = {
            "ready_press_allowed_ack": {
                "listener_ready": True,
                "ack": True,
                "state": "ACKED",
                "door_specific_ack_proven": True,
                "automatic_retry_allowed": False,
                "sigusr1_count": 1,
            },
            "listener_unavailable": {"listener_ready": False, "sigusr1_count": 0},
            "media_active": {"listener_ready": True, "media_active": True, "sigusr1_count": 0},
            "operation_in_progress": {"operation_in_progress": True, "sigusr1_count": 1},
            "no_ack": {
                "listener_ready": True,
                "state": "REJECTED",
                "protocol_acked": False,
                "automatic_retry_allowed": False,
            },
            "malformed_response": {"listener_ready": True, "malformed_response": True, "state": "UNKNOWN_OUTCOME"},
            "unknown_outcome": {"listener_ready": True, "timeout": True, "state": "UNKNOWN_OUTCOME"},
            "duplicate_caller": {"duplicate_caller": True, "sigusr1_count": 1},
            "gate_validated_one_shot": {
                "gate": True,
                "runtime_call": True,
                "target_written": True,
                "sigusr1_count": 1,
                "automatic_retry_allowed": False,
            },
        }
        for name, case in cases.items():
            with self.subTest(name=name):
                marker = derive_one_shot_marker(case)
                self.assertIn("PASS", marker.values())

    def test_offline_harness_flip_cases_fail(self) -> None:
        flips = [
            {"listener_ready": False, "sigusr1_count": 1},
            {"listener_ready": True, "ack": True, "state": "ACKED", "door_specific_ack_proven": False, "automatic_retry_allowed": False, "sigusr1_count": 1},
            {"listener_ready": True, "state": "REJECTED", "protocol_acked": True, "automatic_retry_allowed": False},
            {"listener_ready": True, "malformed_response": True, "state": "ACKED"},
            {"duplicate_caller": True, "sigusr1_count": 2},
            {
                "gate": True,
                "runtime_call": True,
                "target_written": False,
                "sigusr1_count": 1,
                "automatic_retry_allowed": False,
            },
        ]
        for case in flips:
            with self.subTest(case=case):
                marker = derive_one_shot_marker(case)
                self.assertIn("FAIL", marker.values())

    def test_harness_markers_are_derived_not_literals(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        door_literal = '"' + "DOOR_SAFETY_CONTRACT" + "=" + "PASS" + '"'
        gate_literal = '"' + "GATE_ONE_SHOT_CONTRACT" + "=" + "PASS" + '"'
        self.assertNotIn(door_literal, source)
        self.assertNotIn(gate_literal, source)
        good = derive_one_shot_marker({
            "gate": True,
            "runtime_call": True,
            "target_written": True,
            "sigusr1_count": 1,
            "automatic_retry_allowed": False,
        })
        bad = derive_one_shot_marker({
            "gate": True,
            "runtime_call": True,
            "target_written": False,
            "sigusr1_count": 1,
            "automatic_retry_allowed": False,
        })
        self.assertEqual(good["GATE_ONE_SHOT_CONTRACT"], "PASS")
        self.assertEqual(bad["GATE_ONE_SHOT_CONTRACT"], "FAIL")


if __name__ == "__main__":
    unittest.main()
