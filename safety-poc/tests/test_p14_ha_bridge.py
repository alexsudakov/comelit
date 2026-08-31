import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.model import State
from comelit_safety_poc.p14_ha_bridge import (
    P14AuthenticationError,
    P14CanonicalRunner,
    P14ReplayError,
    P14ReplayStore,
    P14RequestError,
    P14RunnerConfig,
    P14SignedRequestVerifier,
    P14_NONCE_HEADER,
    P14_SIGNATURE_HEADER,
    P14_TIMESTAMP_HEADER,
    P14_VERSION_HEADER,
    sign_request,
    validate_operation_id,
)
from comelit_safety_poc.store import Journal


SECRET = b"0123456789abcdef0123456789abcdef"
TARGET = "a" * 64
NOW = 1_800_000_000


def operation_id() -> str:
    return f"p13-hermes-{uuid.uuid4()}"


def signed_request(op_id: str, *, nonce: str = "abcdefghijklmnopqrstuvwx", now: int = NOW):
    body = json.dumps({"operation_id": op_id}, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(now)
    signature = sign_request(
        SECRET,
        method="POST",
        path="/v1/open-door",
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    headers = {
        P14_VERSION_HEADER: "1",
        P14_TIMESTAMP_HEADER: timestamp,
        P14_NONCE_HEADER: nonce,
        P14_SIGNATURE_HEADER: signature,
    }
    return body, headers


class P14SignedRequestTests(unittest.TestCase):
    def _verifier(self, tmp: Path):
        return P14SignedRequestVerifier(
            shared_secret=SECRET,
            replay_store=P14ReplayStore(tmp / "replay.sqlite3"),
            max_clock_skew_seconds=30,
        )

    def test_valid_signed_request_returns_only_operation_id(self):
        with tempfile.TemporaryDirectory() as td:
            op_id = operation_id()
            body, headers = signed_request(op_id)
            verified = self._verifier(Path(td)).verify_open_door(
                headers=headers, body=body, now=NOW
            )
            self.assertEqual(verified, op_id)

    def test_replayed_nonce_is_durably_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            op_id = operation_id()
            body, headers = signed_request(op_id)
            self._verifier(tmp).verify_open_door(headers=headers, body=body, now=NOW)
            # New verifier instance proves replay state survives process recreation.
            with self.assertRaises(P14ReplayError):
                self._verifier(tmp).verify_open_door(headers=headers, body=body, now=NOW)

    def test_bad_signature_does_not_consume_nonce(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = self._verifier(Path(td))
            op_id = operation_id()
            body, headers = signed_request(op_id)
            bad = dict(headers)
            bad[P14_SIGNATURE_HEADER] = "0" * 64
            with self.assertRaises(P14AuthenticationError):
                verifier.verify_open_door(headers=bad, body=body, now=NOW)
            self.assertEqual(
                verifier.verify_open_door(headers=headers, body=body, now=NOW), op_id
            )

    def test_stale_request_is_rejected_before_replay_claim(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = self._verifier(Path(td))
            op_id = operation_id()
            body, headers = signed_request(op_id, now=NOW - 31)
            with self.assertRaises(P14AuthenticationError):
                verifier.verify_open_door(headers=headers, body=body, now=NOW)

    def test_request_body_may_contain_only_operation_id(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = self._verifier(Path(td))
            op_id = operation_id()
            body = json.dumps(
                {"operation_id": op_id, "target": TARGET},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            nonce = "abcdefghijklmnopqrstuvw1"
            timestamp = str(NOW)
            headers = {
                P14_VERSION_HEADER: "1",
                P14_TIMESTAMP_HEADER: timestamp,
                P14_NONCE_HEADER: nonce,
                P14_SIGNATURE_HEADER: sign_request(
                    SECRET,
                    method="POST",
                    path="/v1/open-door",
                    timestamp=timestamp,
                    nonce=nonce,
                    body=body,
                ),
            }
            with self.assertRaises(P14RequestError):
                verifier.verify_open_door(headers=headers, body=body, now=NOW)

    def test_operation_id_requires_uuid4_p13_hermes_identity(self):
        with self.assertRaises(P14RequestError):
            validate_operation_id("p13-hermes-not-a-uuid")
        with self.assertRaises(P14RequestError):
            validate_operation_id(f"p13-hermes-{uuid.uuid1()}")


class P14CanonicalRunnerTests(unittest.TestCase):
    def _runner(self, tmp: Path, *, live: bool = True):
        return P14CanonicalRunner(
            P14RunnerConfig(
                runner_path="/opt/comelit/p13_one_shot_physical_runner.sh",
                journal_path=str(tmp / "poc.sqlite3"),
                target_fingerprint=TARGET,
                min_interval_seconds=10,
                live_enabled=live,
                timeout_seconds=120,
            )
        )

    def test_live_disabled_never_spawns_runner(self):
        with tempfile.TemporaryDirectory() as td:
            runner = self._runner(Path(td), live=False)
            with mock.patch("comelit_safety_poc.p14_ha_bridge.subprocess.run") as run:
                result = runner.invoke(operation_id())
            run.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertFalse(result.runner_invoked)
            self.assertFalse(result.retry_allowed)
            self.assertFalse(result.physical_effect_asserted)

    def test_exact_fixed_command_invoked_once_and_network_cannot_choose_target(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()

            def fake_run(command, **kwargs):
                journal = Journal(tmp / "poc.sqlite3")
                journal.create(op_id, TARGET)
                journal.arm_if_allowed(op_id, 10)
                journal.transition(op_id, State.SENT, "accepted")
                journal.transition(op_id, State.ACKED, "protocol ack only")
                return SimpleNamespace(returncode=0, stdout="redacted")

            with mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.run", side_effect=fake_run
            ) as run:
                result = runner.invoke(op_id)

            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(
                command,
                [
                    "/usr/bin/bash",
                    "/opt/comelit/p13_one_shot_physical_runner.sh",
                    "--db",
                    str(tmp / "poc.sqlite3"),
                    "--operation-id",
                    op_id,
                    "--target-fingerprint",
                    TARGET,
                    "--min-interval-seconds",
                    "10",
                ],
            )
            self.assertEqual(result.state.value, "ACKED")
            self.assertTrue(result.runner_invoked)
            self.assertFalse(result.physical_effect_asserted)
            self.assertFalse(result.retry_allowed)

    def test_duplicate_operation_returns_persisted_without_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()
            journal = Journal(tmp / "poc.sqlite3")
            journal.create(op_id, TARGET)
            journal.arm_if_allowed(op_id, 10)
            journal.transition(op_id, State.SENT, "accepted")
            journal.transition(op_id, State.UNKNOWN_OUTCOME, "ack absent")

            with mock.patch("comelit_safety_poc.p14_ha_bridge.subprocess.run") as run:
                result = runner.invoke(op_id)
            run.assert_not_called()
            self.assertEqual(result.state.value, "UNKNOWN_OUTCOME")
            self.assertFalse(result.runner_invoked)

    def test_timeout_after_send_armed_becomes_terminal_unknown_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()

            def timeout_after_arm(command, **kwargs):
                journal = Journal(tmp / "poc.sqlite3")
                journal.create(op_id, TARGET)
                journal.arm_if_allowed(op_id, 10)
                raise subprocess.TimeoutExpired(command, 120)

            with mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.run",
                side_effect=timeout_after_arm,
            ) as run:
                result = runner.invoke(op_id)

            self.assertEqual(run.call_count, 1)
            self.assertEqual(result.state.value, "UNKNOWN_OUTCOME")
            self.assertEqual(Journal(tmp / "poc.sqlite3").get(op_id).state, State.UNKNOWN_OUTCOME)
            self.assertFalse(result.retry_allowed)

    def test_busy_bridge_rejects_new_operation_before_runner(self):
        with tempfile.TemporaryDirectory() as td:
            runner = self._runner(Path(td))
            op_id = operation_id()
            runner._lock.acquire()
            try:
                with mock.patch("comelit_safety_poc.p14_ha_bridge.subprocess.run") as run:
                    result = runner.invoke(op_id)
            finally:
                runner._lock.release()
            run.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(result.reason, "bridge_busy_no_send_attempted")


if __name__ == "__main__":
    unittest.main()
