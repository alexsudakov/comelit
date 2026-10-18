"""Require offline-safety parity and strict DEV v2 manifest-v1 syntax."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DevV2VerifyParity(unittest.TestCase):
    def test_manifest_is_strict_subset_and_seven_checks(self):
        text = (ROOT / ".dev/hermes-dev.yaml").read_text(encoding="utf-8")
        lines = [s for s in text.splitlines() if s.strip() and not s.strip().startswith("#")]
        self.assertEqual(lines[:3], ["version: 1", "checks:", "  required:"])
        self.assertEqual(len(lines), 10)  # header 3 + 7 single-line checks
        for line in lines[3:]:
            self.assertTrue(line.startswith("    - '") and line.endswith("'"), line)
            self.assertNotIn("\t", line)
            self.assertNotIn("|", line)
        self.assertIn("    - 'sh safety-poc/scripts/dev_v2_offline_safety.sh'", text)

    def test_offline_safety_steps_are_base_owned(self):
        manifest = (ROOT / ".dev/hermes-dev.yaml").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/offline-safety.yml").read_text(encoding="utf-8")
        script = (ROOT / "safety-poc/scripts/dev_v2_offline_safety.sh").read_text(encoding="utf-8")
        self.assertIn("name: offline-safety", workflow)
        self.assertIn("sh safety-poc/scripts/dev_v2_offline_safety.sh", manifest)
        self.assertTrue(script.startswith("#!/bin/sh\nset -eu\n") or script.startswith("#!/bin/sh\n#"))
        for marker in (
            "scripts/static_safety_check.py",
            "-m py_compile scripts/*.py",
            "-m compileall -q ../custom_components/comelit",
            "node --check ../custom_components/comelit/frontend/comelit-card.js",
            "bash -n",
            "-m unittest discover -s tests -v",
            "ci-ack", "ci-amb", "ci-crash", "crash_after_arm", "UNKNOWN_OUTCOME",
            "PYTHONPATH=", "PYTHONDONTWRITEBYTECODE=1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        for marker in ("Static safety scan", "Repository-only unit tests", "Repository-only CLI safety scenarios"):
            self.assertIn(marker, workflow)


if __name__ == "__main__":
    unittest.main()
