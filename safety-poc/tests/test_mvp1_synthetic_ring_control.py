from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "custom_components" / "comelit" / "runtime.py"
RING_MEDIA = ROOT / "custom_components" / "comelit" / "ring_media.py"
TEST_CONTROL = ROOT / "custom_components" / "comelit" / "test_control.py"
CONST = ROOT / "custom_components" / "comelit" / "const.py"
SERVICES = ROOT / "custom_components" / "comelit" / "services.yaml"


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                return ast.unparse(child)
    raise AssertionError(f"{class_name}.{method_name} not found")


class MVP1SyntheticRingControlTests(unittest.TestCase):
    def test_runtime_synthetic_ring_uses_normal_media_coordinator_without_door(self) -> None:
        source = _method_source(
            RUNTIME,
            "ComelitRingRuntime",
            "async_simulate_entrance_ring",
        )
        self.assertIn("'synthetic': True", source)
        self.assertIn("'door': 'entrance'", source)
        self.assertIn("'kind': 'CALL_INIT'", source)
        self.assertIn("'direction': 'DEVICE_TO_CLIENT'", source)
        self.assertIn("EVENT_RING", source)
        self.assertIn("async_start_for_ring", source)
        self.assertIn("listener_not_ready", source)
        self.assertIn("ring_media_busy", source)
        self.assertNotIn("async_open_door", source)
        self.assertNotIn("SIGUSR1", source)

    def test_synthetic_trigger_stays_on_local_restricted_test_control(self) -> None:
        source = TEST_CONTROL.read_text(encoding="utf-8")
        self.assertIn('_ALLOWED_REMOTE = "192.168.1.85"', source)
        self.assertIn('if action == "simulate_entrance_ring":', source)
        self.assertIn("await runtime.async_simulate_entrance_ring()", source)
        self.assertIn("local_only=True", source)
        self.assertIn('result["synthetic"] = True', source)

    def test_synthetic_trigger_is_not_public_ha_service(self) -> None:
        const_source = CONST.read_text(encoding="utf-8")
        services_source = SERVICES.read_text(encoding="utf-8")
        self.assertNotIn("SERVICE_SIMULATE", const_source)
        self.assertNotIn("simulate_entrance_ring:", services_source)

    def test_ring_media_status_exposes_safe_canary_scalars(self) -> None:
        source = _method_source(RING_MEDIA, "RingMediaCoordinator", "status")
        for key in (
            "running",
            "active_event_id",
            "snapshot_event_count",
            "snapshot_sequence_last",
            "snapshot_average_interval_seconds",
            "snapshot_path",
            "recording_event_count",
            "recording_result",
        ):
            self.assertIn(key, source)

    def test_runtime_status_includes_ring_media_diagnostics(self) -> None:
        source = _method_source(RUNTIME, "ComelitRingRuntime", "status")
        self.assertIn('"ring_media"', source)
        self.assertIn("self._ring_media.status()", source)


if __name__ == "__main__":
    unittest.main()
