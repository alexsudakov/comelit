from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
P112 = ROOT / "research" / "media" / "v1" / "ct120_run_p112_final_run5_runner.sh"
P111 = ROOT / "research" / "media" / "v1" / "ct120_run_p110_final_run5_runner.sh"
SHIM = ROOT / "research" / "media" / "v1" / "p111_packaged_musl_holder_shim.sh"

EXPECTED_P111_SHA = "0826473fa925dd09429238e6c792831897a9077fb0b6899383d75dddda7c4798"
EXPECTED_SHIM_SHA = "316858e7f8658a644151cd4a1ccfe13f253a279e118d7d54a499eb31c75a2c9a"


class P112FinalRun5TimingProvenanceTests(unittest.TestCase):
    def run_patch(self, output: Path, *, shim: Path = SHIM) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(
            {
                "P112_PATCH_ONLY": "1",
                "P112_SOURCE_ROOT": str(REPO_ROOT),
                "P112_OUTPUT": str(output),
                "P112_HOLDER_SHIM_SOURCE": str(shim),
            }
        )
        return subprocess.run(
            ["bash", str(P112)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_source_artifacts_are_exactly_pinned(self) -> None:
        self.assertEqual(hashlib.sha256(P111.read_bytes()).hexdigest(), EXPECTED_P111_SHA)
        self.assertEqual(hashlib.sha256(SHIM.read_bytes()).hexdigest(), EXPECTED_SHIM_SHA)
        text = P112.read_text(encoding="utf-8")
        self.assertIn(f"EXPECTED_P111_RUNNER_SHA256={EXPECTED_P111_SHA}", text)
        self.assertIn(f"EXPECTED_HOLDER_SHIM_SHA256={EXPECTED_SHIM_SHA}", text)

    def test_derivation_restores_run3_outer_timeout_and_preserves_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp) / "derived.sh"
            result = self.run_patch(derived)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = derived.read_text(encoding="utf-8")
            self.assertIn('OBSERVATION_SECONDS_LIMIT=40', text)
            self.assertIn('OUTER_MAX_SECONDS=75', text)
            self.assertIn('timeout --signal=TERM --kill-after=5s "${OUTER_MAX_SECONDS}s"', text)
            self.assertNotIn(
                'timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s"',
                text,
            )
            self.assertIn("OBSERVATION_BOUND_GATE=PASS", result.stdout)
            self.assertIn("OUTER_TIMEOUT_GATE=PASS", result.stdout)
            self.assertIn("GRACEFUL_TEARDOWN_HEADROOM_GATE=PASS", result.stdout)
            syntax = subprocess.run(["bash", "-n", str(derived)], text=True, capture_output=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_derived_runner_pins_source_and_installed_holder_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp) / "derived.sh"
            result = self.run_patch(derived)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = derived.read_text(encoding="utf-8")
            self.assertIn(f"EXPECTED_HOLDER_SHIM_SHA256={EXPECTED_SHIM_SHA}", text)
            self.assertIn('HOLDER_SHIM_SOURCE_SHA_GATE=PASS', text)
            self.assertIn('HOLDER_SHIM_INSTALLED_SHA_GATE=PASS', text)
            self.assertIn(
                '[ "$HOLDER_SHIM_SOURCE_SHA256" = "$EXPECTED_HOLDER_SHIM_SHA256" ]',
                text,
            )
            self.assertIn(
                '[ "$HOLDER_SHIM_SHA256" = "$EXPECTED_HOLDER_SHIM_SHA256" ]',
                text,
            )

    def test_tampered_holder_shim_fails_before_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_shim = Path(tmp) / "shim.sh"
            bad_shim.write_bytes(SHIM.read_bytes() + b"\n# tampered\n")
            derived = Path(tmp) / "derived.sh"
            result = self.run_patch(derived, shim=bad_shim)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("P112_SOURCE_SHIM_SHA_GATE=FAIL", result.stdout)
            self.assertIn("P112_LIVE_INVOCATIONS_THIS_TASK=0", result.stdout)
            self.assertFalse(derived.exists())

    def test_no_live_without_explicit_p112_authorization(self) -> None:
        text = P112.read_text(encoding="utf-8")
        auth = text.index('P112_RUN5_AUTHORIZED:-false')
        delegate = text.index('P111_RESEARCH_ARTIFACT_ROOT=')
        self.assertLess(auth, delegate)
        self.assertIn('P112_RUN5_AUTHORIZATION_GATE=FAIL', text)
        self.assertIn('RUN6_AUTHORIZED=false', text)


if __name__ == "__main__":
    unittest.main()
