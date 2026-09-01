import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
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
RUNNER_SHA = "b" * 64
NOW = 1_800_000_000


def operation_id() -> str:
    return f"p13-hermes-{uuid.uuid4()}"


def signed_request(
    op_id: str, *, nonce: str = "abcdefghijklmnopqrstuvwx", now: int = NOW
):
    body = json.dumps(
        {"operation_id": op_id}, sort_keys=True, separators=(",", ":")
    ).encode()
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
            self.assertEqual(
                self._verifier(Path(td)).verify_open_door(
                    headers=headers, body=body, now=NOW
                ),
                op_id,
            )

    def test_replayed_nonce_is_durably_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            op_id = operation_id()
            body, headers = signed_request(op_id)
            self._verifier(tmp).verify_open_door(headers=headers, body=body, now=NOW)
            with self.assertRaises(P14ReplayError):
                self._verifier(tmp).verify_open_door(
                    headers=headers, body=body, now=NOW
                )

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
                runner_path="/usr/local/sbin/comelit-p14-production-runner",
                runner_sha256=RUNNER_SHA,
                journal_path=str(tmp / "poc.sqlite3"),
                target_fingerprint=TARGET,
                lock_path=str(tmp / "runner.lock"),
                live_enabled=live,
                timeout_seconds=120,
                term_grace_seconds=2,
            )
        )

    def test_live_disabled_persists_failed_safe_and_never_spawns(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp, live=False)
            op_id = operation_id()
            with mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(op_id)
            popen.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(
                Journal(tmp / "poc.sqlite3").get(op_id).state, State.FAILED_SAFE
            )
            self.assertFalse(result.retry_allowed)

    def test_disabled_operation_cannot_later_send_after_live_enable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            op_id = operation_id()
            self._runner(tmp, live=False).invoke(op_id)
            runner = self._runner(tmp, live=True)
            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(op_id)
            popen.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")

    def test_exact_contained_command_and_minimal_environment(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()

            class FakeProcess:
                pid = 999999
                returncode = 0

                def communicate(self, timeout=None):
                    return (b"", None)

            def fake_popen(command, **kwargs):
                journal = Journal(tmp / "poc.sqlite3")
                journal.create(op_id, TARGET)
                journal.arm_if_allowed(op_id, 10)
                journal.transition(op_id, State.SENT, "accepted")
                journal.transition(op_id, State.ACKED, "protocol ack")
                return FakeProcess()

            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen",
                side_effect=fake_popen,
            ) as popen:
                result = runner.invoke(op_id)

            self.assertEqual(popen.call_count, 1)
            command = popen.call_args.args[0]
            self.assertEqual(command[0], "/usr/bin/systemd-run")
            self.assertIn("--wait", command)
            self.assertIn("--collect", command)
            self.assertIn("--service-type=exec", command)
            self.assertIn("--property=KillMode=control-group", command)
            self.assertIn("--property=TimeoutStopSec=5s", command)
            self.assertEqual(command[-3:], [runner.config.runner_path, "--operation-id", op_id])
            self.assertEqual(command.count(runner.config.runner_path), 1)
            env = popen.call_args.kwargs["env"]
            self.assertNotIn("COMELIT_P14_SHARED_SECRET", env)
            self.assertNotIn("P13_APPROVAL", env)
            self.assertEqual(
                set(env), {"PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"}
            )
            self.assertEqual(result.state.value, "ACKED")
            self.assertFalse(runner._inflight_path().exists())

    def test_process_lock_busy_is_persisted_failed_safe(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()
            with mock.patch.object(
                runner, "_acquire_process_lock", return_value=None
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(op_id)
            popen.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(
                Journal(tmp / "poc.sqlite3").get(op_id).state, State.FAILED_SAFE
            )

    def test_runner_identity_failure_is_persisted_failed_safe(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()
            with mock.patch.object(
                runner, "verify_runner_identity", side_effect=RuntimeError("bad")
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(op_id)
            popen.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(
                Journal(tmp / "poc.sqlite3").get(op_id).state, State.FAILED_SAFE
            )
            self.assertIn("runner_identity_or_containment_invalid_no_send", result.reason)

    def test_runner_spawn_failure_is_persisted_failed_safe_and_clears_marker(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()
            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen",
                side_effect=OSError("exec"),
            ):
                result = runner.invoke(op_id)
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(
                Journal(tmp / "poc.sqlite3").get(op_id).state, State.FAILED_SAFE
            )
            self.assertIn("runner_spawn_failed_no_send", result.reason)
            self.assertFalse(runner._inflight_path().exists())

    def test_timeout_after_send_armed_stops_cgroup_before_terminal_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            op_id = operation_id()

            class TimeoutProcess:
                pid = 999999
                returncode = -9
                calls = 0

                def communicate(self, timeout=None):
                    self.calls += 1
                    if self.calls == 1:
                        raise subprocess.TimeoutExpired(["systemd-run"], timeout)
                    return (b"", None)

            def fake_popen(command, **kwargs):
                journal = Journal(tmp / "poc.sqlite3")
                journal.create(op_id, TARGET)
                journal.arm_if_allowed(op_id, 10)
                return TimeoutProcess()

            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch.object(
                runner, "_stop_contained_unit_until_inactive"
            ) as stop_unit, mock.patch.object(
                runner, "_terminate_group"
            ) as terminate_group, mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen",
                side_effect=fake_popen,
            ):
                result = runner.invoke(op_id)

            unit_name = runner._unit_name(op_id)
            self.assertGreaterEqual(stop_unit.call_count, 1)
            self.assertEqual(stop_unit.call_args_list[0].args, (unit_name,))
            terminate_group.assert_called_with(mock.ANY, __import__("signal").SIGKILL)
            self.assertEqual(result.state.value, "UNKNOWN_OUTCOME")
            self.assertEqual(
                Journal(tmp / "poc.sqlite3").get(op_id).state,
                State.UNKNOWN_OUTCOME,
            )
            self.assertFalse(result.retry_allowed)
            self.assertFalse(runner._inflight_path().exists())

    def test_active_prior_containment_marker_blocks_new_spawn(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            prior = operation_id()
            current = operation_id()
            journal = Journal(tmp / "poc.sqlite3")
            journal.create(prior, TARGET)
            journal.arm_if_allowed(prior, 10)
            runner._persist_inflight(prior, runner._unit_name(prior))

            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch.object(
                runner, "_unit_has_live_processes", return_value=True
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(current)

            popen.assert_not_called()
            self.assertEqual(result.state.value, "FAILED_SAFE")
            self.assertEqual(journal.get(prior).state, State.SEND_ARMED)
            self.assertTrue(runner._inflight_path().exists())

    def test_inactive_prior_containment_terminalizes_send_armed_before_reply(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            runner = self._runner(tmp)
            prior = operation_id()
            journal = Journal(tmp / "poc.sqlite3")
            journal.create(prior, TARGET)
            journal.arm_if_allowed(prior, 10)
            runner._persist_inflight(prior, runner._unit_name(prior))

            with mock.patch.object(
                runner, "verify_runner_identity"
            ), mock.patch.object(
                runner, "_unit_has_live_processes", return_value=False
            ), mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.Popen"
            ) as popen:
                result = runner.invoke(prior)

            popen.assert_not_called()
            self.assertEqual(result.state.value, "UNKNOWN_OUTCOME")
            self.assertEqual(journal.get(prior).state, State.UNKNOWN_OUTCOME)
            self.assertFalse(runner._inflight_path().exists())

    def test_collected_not_found_unit_is_proven_inactive(self):
        with tempfile.TemporaryDirectory() as td:
            runner = self._runner(Path(td))
            completed = subprocess.CompletedProcess(
                args=["systemctl"],
                returncode=1,
                stdout="LoadState=not-found\nActiveState=inactive\n",
                stderr="",
            )
            with mock.patch(
                "comelit_safety_poc.p14_ha_bridge.subprocess.run",
                return_value=completed,
            ):
                self.assertFalse(
                    runner._unit_has_live_processes("comelit-p14-op-dead.service")
                )


if __name__ == "__main__":
    unittest.main()
