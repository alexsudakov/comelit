from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from .boundary import BoundaryEvidence, BoundaryOutcome, TransportRequest
from .p13_transport_model import P13ActuationEvidence


class CtppOpenOutcome(str, Enum):
    """Typed result of one CTPP channel-open attempt.

    The boundary maps these conservatively:

    - ``PROVEN_NOT_OPENED`` — the adapter can prove the open request was never
      emitted (local failure before any transmission).  Maps to
      ``PROVEN_NOT_SENT``.
    - ``REJECTED`` — an explicit protocol rejection was received before any
      side-effect-capable acceptance.  Maps to ``REJECTED``.
    - ``OPENED`` — the channel opened; the transaction may continue.
    - ``AMBIGUOUS`` — timeout/disconnect/parse failure after the open request
      may have been transmitted.  Maps to ``AMBIGUOUS`` and is never
      downgraded.
    """

    PROVEN_NOT_OPENED = "PROVEN_NOT_OPENED"
    REJECTED = "REJECTED"
    OPENED = "OPENED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class P13PayloadBundle:
    """Prepared real Door payload metadata loaded from the root-only prep file.

    Only the metadata (write count, per-write SHA256, target fingerprint and
    UCFG binding) is kept in memory; raw payload hex is loaded on demand by the
    session adapter and is never written to Git, stdout, or Codex context.
    """

    schema: int
    ucfg_sha256: str
    target_index: int
    target_fingerprint: str
    target_name: str
    channel_id_fixture: int
    write_count: int
    write_sha256: tuple[str, ...]
    write_bytes: tuple[int, ...]

    def verify(self) -> None:
        if self.schema != 1:
            raise ValueError("P13 payload bundle schema must be 1")
        if not self.ucfg_sha256 or len(self.ucfg_sha256) != 64:
            raise ValueError("P13 payload bundle requires a pinned UCFG SHA-256")
        if not self.target_fingerprint or len(self.target_fingerprint) != 64:
            raise ValueError("P13 payload bundle requires a target fingerprint")
        if self.write_count != len(self.write_sha256) or self.write_count != len(self.write_bytes):
            raise ValueError("P13 payload bundle write metadata is inconsistent")
        if self.write_count != 6:
            raise ValueError("P13 real Door transaction requires exactly six writes")


class P13DoorSession(Protocol):
    """Typed real actuation session.

    A real implementation on CT120 wraps the proven P2P path
    (cloud signaling -> ICE -> PseudoTCP -> ViP) and the reconciled CTPP Door
    transaction.  The repository ships a fixture implementation and a concrete
    CT120 adapter (root-only); neither receives credential material through
    the boundary.
    """

    def open_ctpp(self) -> CtppOpenOutcome:
        """Open the CTPP channel exactly once with a typed outcome."""
        ...

    def write_door_body(self, body_hex: str) -> None:
        """Send exactly one prepared Door body over the open CTPP channel."""
        ...

    def close_ctpp(self) -> bool:
        """Close the CTPP channel. Returns True on clean close."""
        ...

    def teardown(self) -> None:
        """Clean ViP session teardown."""
        ...


class P13BodyLoader(Protocol):
    def load(self, index: int) -> str: ...


@dataclass
class FixtureP13DoorSession:
    """Deterministic in-memory session used by tests and offline preflight."""

    opened: bool = False
    open_outcome: CtppOpenOutcome = CtppOpenOutcome.OPENED
    write_count: int = 0
    close_ok: bool = True
    teardown_called: bool = False
    fail_after_writes: int | None = None
    ambiguous_close: bool = False

    def open_ctpp(self) -> CtppOpenOutcome:
        if self.open_outcome == CtppOpenOutcome.OPENED:
            self.opened = True
        return self.open_outcome

    def write_door_body(self, body_hex: str) -> None:
        if not self.opened:
            raise RuntimeError("fixture session write before CTPP open")
        self.write_count += 1
        if self.fail_after_writes is not None and self.write_count >= self.fail_after_writes:
            raise RuntimeError("fixture session write failure after partial emission")

    def close_ctpp(self) -> bool:
        if not self.opened:
            raise RuntimeError("fixture session close before CTPP open")
        self.opened = False
        if self.ambiguous_close:
            raise RuntimeError("fixture session close outcome ambiguous")
        return self.close_ok

    def teardown(self) -> None:
        self.teardown_called = True


class RealDoorActuationBoundary:
    """One-shot real Door actuation behind the typed transport boundary.

    Invariant mapping (identical to the offline transaction model):

    - ``CtppOpenOutcome.PROVEN_NOT_OPENED`` -> ``PROVEN_NOT_SENT`` (adapter
      proves the open request was never emitted);
    - ``CtppOpenOutcome.REJECTED`` -> ``REJECTED``;
    - ``CtppOpenOutcome.AMBIGUOUS`` -> ``AMBIGUOUS`` (never downgraded);
    - a generic exception from ``open_ctpp()`` defaults to ``AMBIGUOUS``
      because a timeout/disconnect/parse failure after the open request may
      mean it was transmitted;
    - failure after any Door write -> ``AMBIGUOUS``;
    - complete six-write transaction without a Door-specific ACK ->
      ``ACCEPTED_NO_ACK`` (executor persists ``UNKNOWN_OUTCOME``);
    - protocol ACK never becomes physical-effect proof.
    """

    def __init__(
        self,
        session: P13DoorSession,
        bundle: P13PayloadBundle,
        *,
        body_loader: P13BodyLoader | None = None,
    ):
        self.session = session
        self.bundle = bundle
        self.body_loader = body_loader
        self.calls = 0
        self.last_evidence: P13ActuationEvidence | None = None

    def _verify_target_binding(self, request: TransportRequest) -> None:
        # The target string is the public-safe fingerprint; the prepared bundle
        # is bound to the exact UCFG snapshot and apartment identity.
        if request.target != self.bundle.target_fingerprint:
            raise ValueError("P13 target binding mismatch: request target != prepared bundle fingerprint")

    def _load_body(self, index: int) -> str:
        if self.body_loader is None:
            raise RuntimeError("P13 real body loader is required on the live path")
        body_hex = self.body_loader.load(index)
        digest = hashlib.sha256(bytes.fromhex(body_hex)).hexdigest()
        if digest != self.bundle.write_sha256[index]:
            raise RuntimeError("P13 prepared body SHA-256 mismatch")
        return body_hex

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("P13 actuation boundary invoked more than once")
        self._verify_target_binding(request)
        self.bundle.verify()

        writes = 0
        opened = False
        protocol_ack = False
        try:
            open_outcome = self.session.open_ctpp()
        except Exception as exc:
            # A generic exception from the real open operation must default to
            # AMBIGUOUS: the open request may already have been transmitted.
            return BoundaryEvidence(
                outcome=BoundaryOutcome.AMBIGUOUS,
                detail=f"P13 CTPP open raised {type(exc).__name__}; may have been transmitted",
                protocol_acknowledged=False,
            )

        if open_outcome == CtppOpenOutcome.AMBIGUOUS:
            return BoundaryEvidence(
                outcome=BoundaryOutcome.AMBIGUOUS,
                detail="P13 CTPP open is ambiguous; retry is unsafe",
                protocol_acknowledged=False,
            )
        if open_outcome == CtppOpenOutcome.PROVEN_NOT_OPENED:
            return BoundaryEvidence(
                outcome=BoundaryOutcome.PROVEN_NOT_SENT,
                detail="P13 CTPP open provably never emitted; zero Door writes",
                protocol_acknowledged=False,
            )
        if open_outcome == CtppOpenOutcome.REJECTED:
            return BoundaryEvidence(
                outcome=BoundaryOutcome.REJECTED,
                detail="P13 CTPP open explicitly rejected before any Door write",
                protocol_acknowledged=False,
            )
        if open_outcome != CtppOpenOutcome.OPENED:
            raise AssertionError(f"unhandled CTPP open outcome: {open_outcome}")
        opened = True

        try:
            for index in range(self.bundle.write_count):
                body_hex = self._load_body(index)
                self.session.write_door_body(body_hex)
                writes += 1

            close_ok = self.session.close_ctpp()
            self.session.teardown()
            protocol_ack = close_ok

            evidence = P13ActuationEvidence(
                cloud_signaling=True,
                ice_connected=True,
                pseudotcp_open=True,
                vip_echo_ack=True,
                uaut_open=True,
                uaut_auth_200=True,
                ctpp_open=True,
                door_write_count=writes,
                ctpp_close=close_ok,
                clean_teardown=True,
                protocol_acknowledged=protocol_ack,
                actuator_command_attempted=True,
            )
            self.last_evidence = evidence
            return BoundaryEvidence(
                outcome=BoundaryOutcome.ACCEPTED_NO_ACK,
                detail="P13 six-write Door transaction emitted; Door-specific ACK unproven",
                protocol_acknowledged=False,
            )
        except Exception as exc:
            # Once the channel is open, any failure after a Door write (or an
            # ambiguous close) is conservative.
            return BoundaryEvidence(
                outcome=BoundaryOutcome.AMBIGUOUS,
                detail=f"P13 failed after CTPP open: {type(exc).__name__}",
                protocol_acknowledged=False,
            )


class P13BodyFileLoader:
    """Loads prepared Door bodies from the root-only payload file on CT120.

    The file is owned by root with mode 0600; this loader never prints body
    values and only hands one body at a time to the session adapter.
    """

    def __init__(self, path: str | Path = "/root/comelit-p13-actuator-prep/real-door-payloads.json"):
        self.path = Path(path)

    def load(self, index: int) -> str:
        if not self.path.is_file():
            raise FileNotFoundError(f"P13 payload file absent: {self.path}")
        mode = self.path.stat().st_mode & 0o777
        if mode != 0o600:
            raise ValueError("P13 payload file must be mode 0600")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        bodies = data.get("bodies")
        if not isinstance(bodies, list) or index >= len(bodies):
            raise ValueError("P13 payload file body index out of range")
        return str(bodies[index]["hex"])
