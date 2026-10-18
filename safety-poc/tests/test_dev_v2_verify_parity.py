"""Guard the base-owned DEV v2 safety suite against drift from Actions."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DevV2VerifyParity(unittest.TestCase):
    def test_offline_safety_critical_steps_are_base_owned(self):
        manifest = (ROOT / ".dev/hermes-dev.yaml").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/offline-safety.yml").read_text(encoding="utf-8")
        self.assertIn("name: offline-safety", workflow)
        self.assertIn("cd safety-poc", manifest)
        for command in (
            "scripts/static_safety_check.py",
            "-m py_compile scripts/*.py",
            "-m compileall -q ../custom_components/comelit",
            "node --check ../custom_components/comelit/frontend/comelit-card.js",
            "bash -n",
            "-m unittest discover -s tests -v",
            "ci-ack",
            "ci-amb",
            "ci-crash",
            "crash_after_arm",
            "UNKNOWN_OUTCOME",
        ):
            with self.subTest(command=command):
                self.assertIn(command, workflow)
                self.assertIn(command, manifest)

    def test_schema_pin_suite_is_never_excluded(self):
        manifest = (ROOT / ".dev/hermes-dev.yaml").read_text(encoding="utf-8")
        for marker in ("-m unittest discover -s tests -v", "PYTHONPATH=", "PYTHONDONTWRITEBYTECODE=1"):
            self.assertIn(marker, manifest)


if __name__ == "__main__":
    unittest.main()
