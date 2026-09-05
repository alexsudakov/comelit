import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_NATIVE_SHA = "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86"
EXPECTED_DOOR_SOURCE_SHA = (
    "088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P16HomeAssistantBackgroundTaskContract(unittest.TestCase):
    def test_manifest_is_1_5_4(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["version"], "1.5.4")

    def test_long_lived_tasks_use_config_entry_background_lifecycle(self):
        init = (ROOT / "custom_components/comelit/__init__.py").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "custom_components/comelit/runtime.py").read_text(
            encoding="utf-8"
        )
        supervisor = (
            ROOT / "custom_components/comelit/supervisor.py"
        ).read_text(encoding="utf-8")

        ast.parse(init)
        ast.parse(runtime)
        ast.parse(supervisor)

        self.assertEqual(
            runtime.count("self._entry.async_create_background_task("),
            2,
        )
        self.assertEqual(
            supervisor.count("self._entry.async_create_background_task("),
            1,
        )
        self.assertNotIn("self._hass.async_create_task(", runtime)
        self.assertNotIn("self._hass.async_create_task(", supervisor)
        self.assertGreaterEqual(init.count("entry=entry"), 2)

    def test_native_failure_diagnostics_are_bounded_and_sanitized(self):
        runtime = (ROOT / "custom_components/comelit/runtime.py").read_text(
            encoding="utf-8"
        )
        supervisor = (
            ROOT / "custom_components/comelit/supervisor.py"
        ).read_text(encoding="utf-8")
        sensor = (ROOT / "custom_components/comelit/sensor.py").read_text(
            encoding="utf-8"
        )

        ast.parse(runtime)
        ast.parse(supervisor)
        ast.parse(sensor)

        self.assertIn("_NATIVE_MARKER_TAIL_LIMIT = 20", runtime)
        self.assertIn("_NATIVE_MARKER_SAFE_VALUE_RE", runtime)
        self.assertIn('else "<redacted>"', runtime)
        self.assertIn("_capture_native_failure", runtime)
        self.assertIn("safe_native_markers=%s", runtime)
        self.assertIn('"last_native_exit_code"', runtime)
        self.assertIn('"last_native_failure_markers"', runtime)
        self.assertIn('"last_native_exit_code"', supervisor)
        self.assertIn('"last_native_failure_markers"', supervisor)
        self.assertIn('"last_native_exit_code"', sensor)
        self.assertIn('"last_native_failure_markers"', sensor)

    def test_door_native_artifact_is_unchanged(self):
        binary = ROOT / "custom_components/comelit/native/comelit-v4"
        source = (
            ROOT
            / "safety-poc/research/door/v1_5_3"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        self.assertEqual(sha256(binary), EXPECTED_NATIVE_SHA)
        self.assertEqual(sha256(source), EXPECTED_DOOR_SOURCE_SHA)


if __name__ == "__main__":
    unittest.main()
