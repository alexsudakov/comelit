import importlib.util
from pathlib import Path
import stat
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_one_shot_exec.py"
spec = importlib.util.spec_from_file_location("p12_one_shot_exec", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P12OneShotExecTests(unittest.TestCase):
    def _script(self, directory: Path, body: str) -> Path:
        path = directory / "fixture.sh"
        path.write_text("#!/usr/bin/env bash\nset -Eeuo pipefail\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_success_is_completed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = self._script(root, "echo SAFE_FIXTURE\nexit 0\n")
            raw = root / "raw.log"
            result = module.run_once(wrapper, raw, timeout_seconds=1, term_grace_seconds=1)
            self.assertEqual(result.outcome, module.OneShotOutcome.COMPLETED)
            self.assertEqual(result.process_rc, 0)
            self.assertFalse(result.timeout_observed)
            self.assertEqual(raw.read_text(encoding="utf-8"), "SAFE_FIXTURE\n")

    def test_nonzero_exit_is_process_failure_not_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = self._script(root, "exit 23\n")
            result = module.run_once(wrapper, root / "raw.log", timeout_seconds=1, term_grace_seconds=1)
            self.assertEqual(result.outcome, module.OneShotOutcome.PROCESS_FAILURE)
            self.assertEqual(result.process_rc, 23)
            self.assertFalse(result.timeout_observed)

    def test_timeout_is_observed_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter.txt"
            wrapper = self._script(
                root,
                f"echo x >> {counter!s}\ntrap 'exit 0' TERM\nsleep 2\n",
            )
            result = module.run_once(wrapper, root / "raw.log", timeout_seconds=0.05, term_grace_seconds=0.5)
            self.assertIn(
                result.outcome,
                (module.OneShotOutcome.TIMEOUT_TERM, module.OneShotOutcome.TIMEOUT_KILL),
            )
            self.assertTrue(result.timeout_observed)
            self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["x"])

    def test_status_declares_timeout_mapping_and_one_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.txt"
            module.write_status(
                path,
                module.OneShotResult(module.OneShotOutcome.TIMEOUT_KILL, -9, True),
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("P12_ONE_SHOT_OUTCOME=TIMEOUT_KILL", text)
            self.assertIn("P12_ONE_SHOT_TIMEOUT_OBSERVED=true", text)
            self.assertIn("P12_ONE_SHOT_PROCESS_INVOCATIONS=1", text)
            self.assertIn("P12_ONE_SHOT_AUTO_RETRY=false", text)
            self.assertIn("P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true", text)
            self.assertIn("TIMEOUT_MAPPING_VERIFIED=PASS", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_source_contains_exactly_one_process_spawn_and_group_cleanup(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(text.count("subprocess.Popen("), 1)
        self.assertIn("start_new_session=True", text)
        self.assertIn("os.killpg(proc.pid, sig)", text)
        self.assertIn("signal.SIGTERM", text)
        self.assertIn("signal.SIGKILL", text)
        self.assertNotIn("while True", text)
        self.assertNotIn("for attempt", text)
        self.assertNotIn("shell=True", text)


if __name__ == "__main__":
    unittest.main()
