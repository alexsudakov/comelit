from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .ha_contract import HaResultState
from .model import State
from .store import Journal


P14_PROTOCOL_VERSION = "1"
P14_OPEN_DOOR_PATH = "/v1/open-door"
P14_SIGNATURE_HEADER = "X-Comelit-Signature"
P14_TIMESTAMP_HEADER = "X-Comelit-Timestamp"
P14_NONCE_HEADER = "X-Comelit-Nonce"
P14_VERSION_HEADER = "X-Comelit-Version"
P14_MAX_BODY_BYTES = 512

_OPERATION_PREFIX = "p13-hermes-"
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class P14RequestError(ValueError):
    pass


class P14AuthenticationError(P14RequestError):
    pass


class P14ReplayError(P14RequestError):
    pass


def validate_operation_id(value: str) -> str:
    value = (value or "").strip()
    if not value.startswith(_OPERATION_PREFIX):
        raise P14RequestError("invalid_operation_id")
    suffix = value[len(_OPERATION_PREFIX) :]
    try:
        parsed = uuid.UUID(suffix)
    except (ValueError, AttributeError) as exc:
        raise P14RequestError("invalid_operation_id") from exc
    if parsed.version != 4 or str(parsed) != suffix.lower():
        raise P14RequestError("invalid_operation_id")
    canonical = f"{_OPERATION_PREFIX}{parsed}"
    if canonical != value.lower():
        raise P14RequestError("invalid_operation_id")
    return canonical


def canonical_signature_payload(
    *, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    body_sha = hashlib.sha256(body).hexdigest()
    return (
        f"v{P14_PROTOCOL_VERSION}\n"
        f"{method.upper()}\n"
        f"{path}\n"
        f"{timestamp}\n"
        f"{nonce}\n"
        f"{body_sha}"
    ).encode("utf-8")


def sign_request(
    secret: bytes,
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    if len(secret) < 32:
        raise ValueError("shared secret must be at least 32 bytes")
    payload = canonical_signature_payload(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


class P14ReplayStore:
    """Durable nonce replay protection for authenticated HA requests."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS accepted_nonces (
                    nonce TEXT PRIMARY KEY,
                    issued_at INTEGER NOT NULL,
                    accepted_at INTEGER NOT NULL
                )
                """
            )

    def claim(self, nonce: str, issued_at: int, *, now: int) -> None:
        con = sqlite3.connect(self.path)
        try:
            con.execute("PRAGMA synchronous=FULL")
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "INSERT INTO accepted_nonces(nonce, issued_at, accepted_at) VALUES(?,?,?)",
                    (nonce, issued_at, now),
                )
            except sqlite3.IntegrityError as exc:
                raise P14ReplayError("replayed_nonce") from exc
            # Never delete an in-window nonce.  The wide cleanup margin makes a
            # replay durable across bridge restarts without unbounded growth.
            con.execute("DELETE FROM accepted_nonces WHERE accepted_at < ?", (now - 86400,))
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


class P14SignedRequestVerifier:
    def __init__(
        self,
        *,
        shared_secret: bytes,
        replay_store: P14ReplayStore,
        max_clock_skew_seconds: int = 30,
    ):
        if len(shared_secret) < 32:
            raise ValueError("shared secret must be at least 32 bytes")
        if max_clock_skew_seconds < 1 or max_clock_skew_seconds > 300:
            raise ValueError("invalid max clock skew")
        self.shared_secret = shared_secret
        self.replay_store = replay_store
        self.max_clock_skew_seconds = max_clock_skew_seconds

    def verify_open_door(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        now: int | None = None,
    ) -> str:
        if len(body) > P14_MAX_BODY_BYTES:
            raise P14RequestError("request_body_too_large")

        version = (headers.get(P14_VERSION_HEADER) or "").strip()
        timestamp = (headers.get(P14_TIMESTAMP_HEADER) or "").strip()
        nonce = (headers.get(P14_NONCE_HEADER) or "").strip()
        signature = (headers.get(P14_SIGNATURE_HEADER) or "").strip().lower()

        if version != P14_PROTOCOL_VERSION:
            raise P14AuthenticationError("unsupported_protocol_version")
        if not timestamp.isdigit():
            raise P14AuthenticationError("invalid_timestamp")
        if not _NONCE_RE.fullmatch(nonce):
            raise P14AuthenticationError("invalid_nonce")
        if not _SHA256_RE.fullmatch(signature):
            raise P14AuthenticationError("invalid_signature")

        now_i = int(time.time()) if now is None else int(now)
        issued_at = int(timestamp)
        if abs(now_i - issued_at) > self.max_clock_skew_seconds:
            raise P14AuthenticationError("timestamp_outside_window")

        expected = sign_request(
            self.shared_secret,
            method="POST",
            path=P14_OPEN_DOOR_PATH,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        )
        if not hmac.compare_digest(signature, expected):
            raise P14AuthenticationError("signature_mismatch")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise P14RequestError("invalid_json") from exc
        if not isinstance(payload, dict) or set(payload) != {"operation_id"}:
            raise P14RequestError("exact_operation_id_body_required")
        operation_id = validate_operation_id(str(payload.get("operation_id") or ""))

        # Claim only after authentication and structural validation, but before
        # any execution.  A repeated signed request can never invoke the runner
        # twice with the same nonce.
        self.replay_store.claim(nonce, issued_at, now=now_i)
        return operation_id


@dataclass(frozen=True)
class P14BridgeResult:
    operation_id: str
    state: HaResultState
    reason: str
    runner_invoked: bool
    retry_allowed: bool = False
    physical_effect_asserted: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation_id": self.operation_id,
            "state": self.state.value,
            "reason": self.reason,
            "runner_invoked": self.runner_invoked,
            "retry_allowed": False,
            "physical_effect_asserted": False,
        }


@dataclass(frozen=True)
class P14RunnerConfig:
    runner_path: str
    runner_sha256: str
    journal_path: str
    target_fingerprint: str
    lock_path: str
    live_enabled: bool = False
    timeout_seconds: int = 150
    term_grace_seconds: int = 5

    def __post_init__(self) -> None:
        for value, name in (
            (self.runner_path, "runner_path"),
            (self.journal_path, "journal_path"),
            (self.lock_path, "lock_path"),
        ):
            if not Path(value).is_absolute():
                raise ValueError(f"{name} must be absolute")
        if not _SHA256_RE.fullmatch(self.runner_sha256):
            raise ValueError("runner_sha256 must be a lowercase sha256")
        if not _SHA256_RE.fullmatch(self.target_fingerprint):
            raise ValueError("target_fingerprint must be a lowercase sha256")
        if self.timeout_seconds < 10 or self.timeout_seconds > 300:
            raise ValueError("invalid timeout_seconds")
        if self.term_grace_seconds < 1 or self.term_grace_seconds > 30:
            raise ValueError("invalid term_grace_seconds")


class P14CanonicalRunner:
    """Narrow bridge to a locally pinned P14 production runner.

    Network input controls only ``operation_id``.  The executable identity,
    P13 target/journal/artifacts, approval mapping and rate limit remain local
    root-owned configuration.  No P14 secret is inherited by the child.  A
    process-wide flock complements the in-process lock so two bridge processes
    cannot launch actuation children concurrently during restarts/upgrades.
    """

    def __init__(self, config: P14RunnerConfig):
        self.config = config
        self._thread_lock = threading.Lock()

    def _journal(self) -> Journal:
        return Journal(self.config.journal_path)

    def verify_runner_identity(self) -> None:
        path = Path(self.config.runner_path)
        if not path.is_file():
            raise RuntimeError("p14_production_runner_absent")
        if path.stat().st_uid != 0:
            raise RuntimeError("p14_production_runner_owner_not_root")
        if (path.stat().st_mode & 0o777) != 0o700:
            raise RuntimeError("p14_production_runner_mode_invalid")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual, self.config.runner_sha256):
            raise RuntimeError("p14_production_runner_sha256_mismatch")

    @staticmethod
    def _map_existing(operation_id: str, state: State, detail: str | None) -> P14BridgeResult:
        if state == State.ACKED:
            mapped = HaResultState.ACKED
        elif state == State.FAILED_SAFE:
            mapped = HaResultState.FAILED_SAFE
        else:
            # PREPARED/SEND_ARMED/SENT are deliberately not re-executed.  A
            # nonterminal record may belong to a still-running or crashed
            # operation, so the only safe network-facing state is UNKNOWN.
            mapped = HaResultState.UNKNOWN_OUTCOME
        return P14BridgeResult(
            operation_id=operation_id,
            state=mapped,
            reason=detail or f"persisted_{state.value.lower()}",
            runner_invoked=False,
        )

    def _existing_without_resend(self, operation_id: str) -> P14BridgeResult | None:
        op = self._journal().maybe_get(operation_id)
        if op is None:
            return None
        return self._map_existing(operation_id, op.state, op.detail)

    def _record_failed_safe(self, operation_id: str, reason: str) -> P14BridgeResult:
        journal = self._journal()
        existing = journal.maybe_get(operation_id)
        if existing is not None:
            return self._map_existing(operation_id, existing.state, existing.detail)
        try:
            journal.create(operation_id, self.config.target_fingerprint, reason)
            op = journal.transition(operation_id, State.FAILED_SAFE, reason)
        except sqlite3.IntegrityError:
            op = journal.get(operation_id)
        mapped = self._map_existing(operation_id, op.state, op.detail)
        return P14BridgeResult(
            operation_id=mapped.operation_id,
            state=mapped.state,
            reason=mapped.reason,
            runner_invoked=False,
        )

    def _acquire_process_lock(self):
        lock_path = Path(self.config.lock_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(lock_path.parent, 0o700)
        handle = lock_path.open("a+", encoding="utf-8")
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        return handle

    @staticmethod
    def _minimal_child_env() -> dict[str, str]:
        # In particular, COMELIT_P14_SHARED_SECRET and every request HMAC value
        # are absent.  The root-only P14 production runner maps the P13 approval
        # token locally after its own immutable-runtime checks.
        return {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    @staticmethod
    def _terminate_group(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    def invoke(self, operation_id: str) -> P14BridgeResult:
        operation_id = validate_operation_id(operation_id)

        existing = self._existing_without_resend(operation_id)
        if existing is not None:
            return existing

        if not self.config.live_enabled:
            # Persist the no-send result so this operation identity can never be
            # reused later after live mode is enabled.
            return self._record_failed_safe(operation_id, "p14_live_execution_disabled_no_send")

        if not self._thread_lock.acquire(blocking=False):
            return self._record_failed_safe(operation_id, "bridge_busy_no_send_attempted")

        process_lock = None
        runner_invoked = False
        timed_out = False
        return_code: int | None = None
        try:
            try:
                process_lock = self._acquire_process_lock()
            except OSError:
                return self._record_failed_safe(
                    operation_id, "bridge_process_lock_error_no_send_attempted"
                )
            if process_lock is None:
                return self._record_failed_safe(operation_id, "bridge_process_busy_no_send_attempted")

            # Another request/process may have completed this operation while
            # this request was waiting on local scheduling.
            existing = self._existing_without_resend(operation_id)
            if existing is not None:
                return existing

            try:
                self.verify_runner_identity()
            except RuntimeError as exc:
                return self._record_failed_safe(
                    operation_id, f"runner_identity_invalid_no_send:{exc}"
                )

            command = [self.config.runner_path, "--operation-id", operation_id]
            try:
                proc = subprocess.Popen(
                    command,
                    env=self._minimal_child_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError as exc:
                return self._record_failed_safe(
                    operation_id, f"runner_spawn_failed_no_send:{type(exc).__name__}"
                )
            runner_invoked = True
            try:
                proc.communicate(timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_group(proc, signal.SIGTERM)
                try:
                    proc.communicate(timeout=self.config.term_grace_seconds)
                except subprocess.TimeoutExpired:
                    self._terminate_group(proc, signal.SIGKILL)
                    proc.communicate(timeout=5)
            return_code = proc.returncode
        finally:
            if process_lock is not None:
                try:
                    fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
                finally:
                    process_lock.close()
            self._thread_lock.release()

        journal = self._journal()
        op = journal.maybe_get(operation_id)
        if op is None:
            # The production runner validates all identities before it creates
            # PREPARED.  No durable operation means SEND_ARMED was not reached.
            reason = (
                "runner_timeout_before_operation_persisted_no_send"
                if timed_out
                else f"runner_exit_{return_code}_before_operation_persisted_no_send"
            )
            persisted = self._record_failed_safe(operation_id, reason)
            return P14BridgeResult(
                operation_id=persisted.operation_id,
                state=persisted.state,
                reason=persisted.reason,
                runner_invoked=runner_invoked,
            )

        # The child process group has ended.  Normalize crash residue without
        # ever launching another process/send.
        if op.state == State.PREPARED:
            op = journal.transition(
                operation_id,
                State.FAILED_SAFE,
                "P14 bridge recovery: runner ended before SEND_ARMED; retry forbidden",
            )
        elif op.state in {State.SEND_ARMED, State.SENT}:
            op = journal.transition(
                operation_id,
                State.UNKNOWN_OUTCOME,
                "P14 bridge recovery after uncertainty boundary; retry forbidden",
            )

        result = self._map_existing(operation_id, op.state, op.detail)
        return P14BridgeResult(
            operation_id=result.operation_id,
            state=result.state,
            reason=result.reason,
            runner_invoked=runner_invoked,
        )


class P14BridgeApplication:
    def __init__(self, verifier: P14SignedRequestVerifier, runner: P14CanonicalRunner):
        self.verifier = verifier
        self.runner = runner

    def open_door(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        now: int | None = None,
    ) -> P14BridgeResult:
        operation_id = self.verifier.verify_open_door(headers=headers, body=body, now=now)
        return self.runner.invoke(operation_id)
