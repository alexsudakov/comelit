import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MODULE = SRC / "comelit_safety_poc" / "p13_one_shot_physical.py"
RUNNER_SH = Path(__file__).resolve().parents[1] / "scripts" / "p13_one_shot_physical_runner.sh"

APPROVAL = "I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST"


def make_payload(tmp: Path) -> Path:
    bodies = [bytes([i + 1]) * 12 for i in range(6)]
    payload = {
        "schema": 1,
        "ucfg_sha256": "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
        "target_index": 0,
        "target_fingerprint": "f" * 64,
        "target_name": "FixtureDoor",
        "channel_id_fixture": 7449,
        "write_count": 6,
        "bodies": [
            {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for b in bodies
        ],
    }
    path = tmp / "payloads.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def make_wrapper(tmp: Path, counter: Path) -> Path:
    """Fake wrapper: prints typed markers and increments an invocation counter."""
    script = f"""#!/bin/sh
N=$(cat {counter} 2>/dev/null || echo 0)
echo $((N + 1)) > {counter}
printf '%s\\n' 'P13_CTPP_OPEN_OUTCOME=OPENED'
printf '%s\\n' 'P13_DOOR_WRITE_COUNT=6'
printf '%s\\n' 'P13_CTPP_CLOSE=PASS'
printf '%s\\n' 'P13_TEARDOWN=PASS'
"""
    path = tmp / "wrapper"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return path


class P13OneShotPhysicalTests(unittest.TestCase):
    def _run(self, args, cwd, approval=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if approval is not None:
            env["P13_APPROVAL"] = approval
        return subprocess.run(
            [sys.executable, "-m", "comelit_safety_poc.p13_one_shot_physical", *args],
            capture_output=True, text=True, cwd=cwd, env=env, timeout=90,
        )

    def test_approval_required(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = make_payload(tmp)
            counter = tmp / "counter"
            counter.write_text("0", encoding="utf-8")
            wrapper = make_wrapper(tmp, counter)
            proc = self._run(
                [
                    "--db", str(tmp / "poc.sqlite3"),
                    "--operation-id", "op-approval",
                    "--target-fingerprint", "f" * 64,
                    "--min-interval-seconds", "0",
                    "--wrapper", str(wrapper),
                    "--wrapper-sha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    "--payload", str(payload),
                    "--payload-sha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                    "--audit", str(tmp / "audit.jsonl"),
                    "--head", "h" * 40,
                    "--tree", "t" * 40,
                    "--run-dir", str(tmp / "run"),
                ],
                cwd=tmp,
                approval=None,
            )
            self.assertEqual(proc.returncode, 66, proc.stdout)
            self.assertIn("P13_ONE_SHOT_APPROVAL=FAIL", proc.stdout)
            # wrapper must never have been invoked without approval
            self.assertEqual(counter.read_text().strip(), "0")

    def test_one_shot_execution_with_approval(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = make_payload(tmp)
            counter = tmp / "counter"
            counter.write_text("0", encoding="utf-8")
            wrapper = make_wrapper(tmp, counter)
            db = tmp / "poc.sqlite3"
            audit = tmp / "audit.jsonl"
            proc = self._run(
                [
                    "--db", str(db),
                    "--operation-id", "op-live",
                    "--target-fingerprint", "f" * 64,
                    "--min-interval-seconds", "0",
                    "--wrapper", str(wrapper),
                    "--wrapper-sha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    "--payload", str(payload),
                    "--payload-sha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                    "--audit", str(audit),
                    "--head", "h" * 40,
                    "--tree", "t" * 40,
                    "--run-dir", str(tmp / "run"),
                ],
                cwd=tmp,
                approval=APPROVAL,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            out = json.loads(proc.stdout)
            # accepted without Door-specific ACK -> UNKNOWN_OUTCOME
            self.assertEqual(out["state"], "UNKNOWN_OUTCOME")
            self.assertEqual(out["P13_ONE_SHOT_MAX_INVOCATIONS"], 1)
            self.assertFalse(out["P13_AUTO_RETRY_ALLOWED"])
            self.assertFalse(out["P13_PHYSICAL_EFFECT_ASSERTED"])
            # exactly one wrapper invocation
            self.assertEqual(counter.read_text().strip(), "1")

            # audit journal durable and contains transport events
            con = sqlite3.connect(db)
            armed = con.execute(
                "SELECT COUNT(*) FROM events WHERE operation_id='op-live' AND to_state='SEND_ARMED'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(armed, 1)

    def test_duplicate_operation_id_never_invokes_wrapper_again(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = make_payload(tmp)
            counter = tmp / "counter"
            counter.write_text("0", encoding="utf-8")
            wrapper = make_wrapper(tmp, counter)
            db = tmp / "poc.sqlite3"
            audit = tmp / "audit.jsonl"
            args = [
                "--db", str(db),
                "--operation-id", "op-dupe",
                "--target-fingerprint", "f" * 64,
                "--min-interval-seconds", "0",
                "--wrapper", str(wrapper),
                "--wrapper-sha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                "--payload", str(payload),
                "--payload-sha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                "--audit", str(audit),
                "--head", "h" * 40,
                "--tree", "t" * 40,
                "--run-dir", str(tmp / "run"),
            ]
            first = self._run(args, cwd=tmp, approval=APPROVAL)
            self.assertEqual(first.returncode, 0, first.stdout)
            self.assertEqual(counter.read_text().strip(), "1")
            second = self._run(args, cwd=tmp, approval=APPROVAL)
            self.assertEqual(second.returncode, 0, second.stdout)
            out = json.loads(second.stdout)
            self.assertEqual(out["state"], "UNKNOWN_OUTCOME")
            # wrapper still invoked exactly once across both runs
            self.assertEqual(counter.read_text().strip(), "1")

    def test_target_binding_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = make_payload(tmp)
            counter = tmp / "counter"
            counter.write_text("0", encoding="utf-8")
            wrapper = make_wrapper(tmp, counter)
            proc = self._run(
                [
                    "--db", str(tmp / "poc.sqlite3"),
                    "--operation-id", "op-mismatch",
                    "--target-fingerprint", "a" * 64,
                    "--min-interval-seconds", "0",
                    "--wrapper", str(wrapper),
                    "--wrapper-sha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    "--payload", str(payload),
                    "--payload-sha256", hashlib.sha256(payload.read_bytes()).hexdigest(),
                    "--audit", str(tmp / "audit.jsonl"),
                    "--head", "h" * 40,
                    "--tree", "t" * 40,
                    "--run-dir", str(tmp / "run"),
                ],
                cwd=tmp,
                approval=APPROVAL,
            )
            self.assertEqual(proc.returncode, 65, proc.stdout)
            self.assertIn("P13_TARGET_BINDING_MISMATCH=true", proc.stdout)
            self.assertEqual(counter.read_text().strip(), "0")


class P13OneShotRunnerShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNNER_SH.read_text(encoding="utf-8")

    def test_approval_token_required(self):
        self.assertIn("APPROVAL_TOKEN=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST", self.text)
        self.assertIn("P13_ONE_SHOT_APPROVAL=FAIL", self.text)
        self.assertIn('[[ "${P13_APPROVAL:-}" != "$APPROVAL_TOKEN" ]]', self.text)

    def test_preflight_gate_before_execution(self):
        self.assertIn("p13_actuation_preflight.sh", self.text)
        self.assertIn("P13_ONE_SHOT_PREFLIGHT=FAIL", self.text)
        self.assertIn("P13_ONE_SHOT_PREFLIGHT=PASS", self.text)

    def test_one_invocation_and_no_retry(self):
        # One-shot / no-retry markers live in the Python runner module.
        module_text = MODULE.read_text(encoding="utf-8")
        self.assertIn("P13_ONE_SHOT_MAX_INVOCATIONS", module_text)
        self.assertIn("P13_AUTO_RETRY_ALLOWED", module_text)
        self.assertIn("There is no retry anywhere", self.text)
        self.assertNotIn("for attempt in", self.text)

    def test_runner_never_executes_physical_send_by_itself(self):
        self.assertIn("APPROVAL_TOKEN=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST", self.text)
        self.assertIn("P13_ONE_SHOT_APPROVAL=FAIL", self.text)
        self.assertIn("--operation-id", self.text)
        self.assertIn("--target-fingerprint", self.text)
        self.assertIn("p13_actuation_preflight.sh", self.text)


if __name__ == "__main__":
    unittest.main()
