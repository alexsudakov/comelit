from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
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
from .p13_one_shot_physical import APPROVAL_TOKEN
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
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
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
            # Old nonces are irrelevant after the timestamp window. Keep a wide
            # cleanup margin so cleanup can never make an in-window replay valid.
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
        # any possible execution. A repeated signed request can never invoke the
        # runner twice with the same nonce.
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
    journal_path: str
    target_fingerprint: str
    min_interval_seconds: int = 10
    live_enabled: bool = False
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if not Path(self.runner_path).is_absolute():
            raise ValueError("runner_path must be absolute")
        if not _SHA256_RE.fullmatch(self.target_fingerprint):
            raise ValueError("target_fingerprint must be a lowercase sha256")
        if self.min_interval_seconds < 1:
            raise ValueError("min_interval_seconds must be positive")
        if self.timeout_seconds < 10:
            raise ValueError("timeout_seconds too small")


class P14CanonicalRunner:
    """Narrow CT120 adapter to the already-proven P13 physical runner.

    Network input controls only ``operation_id``. Runner path, journal, target,
    approval mapping, rate limit and timeout are local trusted configuration.
    There is no retry loop. The process lock prevents two native runner
    processes from being launched concurrently by this bridge.
    """

    def __init__(self, config: P14RunnerConfig):
        self.config = config
        self._lock = threading.Lock()

    def _journal(self) -> Journal:
        return Journal(self.config.journal_path)

    @staticmethod
    def _map_existing(operation_id: str, state: State, detail: str | None) -> P14BridgeResult:
        if state == State.ACKED:
            mapped = HaResultState.ACKED
        elif state == State.FAILED_SAFE:
            mapped = HaResultState.FAILED_SAFE
        else:
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

    def invoke(self, operation_id: str) -> P14BridgeResult:
        operation_id = validate_operation_id(operation_id)

        existing = self._existing_without_resend(operation_id)
        if existing is not None:
            return existing

        if not self.config.live_enabled:
            return P14BridgeResult(
                operation_id=operation_id,
                state=HaResultState.FAILED_SAFE,
                reason="p14_live_execution_disabled",
                runner_invoked=False,
            )

        if not self._lock.acquire(blocking=False):
            return P14BridgeResult(
                operation_id=operation_id,
                state=HaResultState.FAILED_SAFE,
                reason="bridge_busy_no_send_attempted",
                runner_invoked=False,
            )

        timed_out = False
        return_code: int | None = None
        try:
            # Re-check after acquiring the lock: another request may have
            # completed this operation between the first lookup and the lock.
            existing = self._existing_without_resend(operation_id)
            if existing is not None:
                return existing

            command = [
                "/usr/bin/bash",
                self.config.runner_path,
                "--db",
                self.config.journal_path,
                "--operation-id",
                operation_id,
                "--target-fingerprint",
                self.config.target_fingerprint,
                "--min-interval-seconds",
                str(self.config.min_interval_seconds),
            ]
            env = os.environ.copy()
            # The static P13 approval token is never accepted from the network.
            # It is mapped locally only after the HMAC-authenticated HA request
            # passed the P14 verifier and live execution is explicitly enabled.
            env["P13_APPROVAL"] = APPROVAL_TOKEN
            try:
                completed = subprocess.run(
                    command,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                )
                return_code = completed.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            self._lock.release()

        journal = self._journal()
        op = journal.maybe_get(operation_id)
        if op is None:
            return P14BridgeResult(
                operation_id=operation_id,
                state=HaResultState.FAILED_SAFE,
                reason=(
                    "runner_timeout_before_operation_persisted"
                    if timed_out
                    else f"runner_exit_{return_code}_before_operation_persisted"
                ),
                runner_invoked=True,
            )

        # The child is no longer running. Normalize any crash residue without
        # ever attempting another send.
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
            runner_invoked=True,
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


def new_nonce() -> str:
    """Helper used by compatibility tests; HA has its own equivalent signer."""
    return secrets.token_urlsafe(24)
