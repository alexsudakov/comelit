from __future__ import annotations

import asyncio
import hashlib
import importlib
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from .boundary import BoundaryEvidence, BoundaryOutcome, TransportRequest


CANONICAL_VIP_ROOT = Path("/root/comelit-vip-poc")
LEGACY_RESEARCH_SOURCE = Path("/root/comelit-poc/comelit_client.py")
LEGACY_RESEARCH_SHA256 = "03ea7d012587d8751eddfd5fa531d244abddc047c3a69d8ce27986c1e2768d42"
CANONICAL_VIP_SOURCE_HASHES: dict[str, str] = {
    "comelit_vip/__init__.py": "32d10190dbcfceed5bbabcd39a1d7a8da5dbe0fff85f0d7bb636039d06da8194",
    "comelit_vip/application_session.py": "7c30aab9bd03917e0e84fb9b31f924f95eabeb8edd6a1fe74d4e4f012c2145fd",
    "comelit_vip/channel_session.py": "b34d87c382ea601d96761f59a31e62aa2d1e959ea9c24e99a63964e1c033e1d1",
    "comelit_vip/control_codec.py": "e89e3fe20b24ef2f22ceaa15b186b4db7f71f5f48c7f5aeaf6a07f38bea854a2",
    "comelit_vip/fixture_transport.py": "5a4ee43dcb934512728c3cae899bceb56e651a5908699338aa8d3de2064a34d2",
    "comelit_vip/transport.py": "21ce339f15d44216baecdeefa19490a5d5632f689155d628b76d4abb7872a0d4",
    "comelit_vip/vip_codec.py": "4ebf41833977e198b1ef94f4aace37f86dad9fbaec08c716242b9ee40437859a",
    "comelit_vip/vip_session.py": "35b604372e9bd42a6631d0c923ac99d49e02e4b7c8892360633eedc23425dc39",
}


class SemanticKind(str, Enum):
    CHANNEL_PRECONDITION = "CHANNEL_PRECONDITION"
    WRITE = "WRITE"
    OPTIONAL_WAIT = "OPTIONAL_WAIT"


class SemanticStep(str, Enum):
    CTPP_CHANNEL_REQUIRED = "CTPP_CHANNEL_REQUIRED"
    INIT_A = "INIT_A"
    OPTIONAL_WAIT_A = "OPTIONAL_WAIT_A"
    COMMAND_PRIMARY = "COMMAND_PRIMARY"
    CONFIRM_PRIMARY = "CONFIRM_PRIMARY"
    INIT_B = "INIT_B"
    OPTIONAL_WAIT_B = "OPTIONAL_WAIT_B"
    COMMAND_FINAL = "COMMAND_FINAL"
    CONFIRM_FINAL = "CONFIRM_FINAL"


STEP_KINDS: dict[SemanticStep, SemanticKind] = {
    SemanticStep.CTPP_CHANNEL_REQUIRED: SemanticKind.CHANNEL_PRECONDITION,
    SemanticStep.INIT_A: SemanticKind.WRITE,
    SemanticStep.OPTIONAL_WAIT_A: SemanticKind.OPTIONAL_WAIT,
    SemanticStep.COMMAND_PRIMARY: SemanticKind.WRITE,
    SemanticStep.CONFIRM_PRIMARY: SemanticKind.WRITE,
    SemanticStep.INIT_B: SemanticKind.WRITE,
    SemanticStep.OPTIONAL_WAIT_B: SemanticKind.OPTIONAL_WAIT,
    SemanticStep.COMMAND_FINAL: SemanticKind.WRITE,
    SemanticStep.CONFIRM_FINAL: SemanticKind.WRITE,
}


@dataclass(frozen=True)
class DoorSemanticPlan:
    channel_name: str = "CTPP"
    steps: tuple[SemanticStep, ...] = tuple(SemanticStep)

    def __post_init__(self) -> None:
        expected = tuple(SemanticStep)
        if self.steps != expected:
            raise ValueError("door semantic plan order is fixed")
        if self.channel_name != "CTPP":
            raise ValueError("door semantic plan requires CTPP channel semantics")

    @property
    def write_steps(self) -> tuple[SemanticStep, ...]:
        return tuple(step for step in self.steps if STEP_KINDS[step] == SemanticKind.WRITE)

    @property
    def optional_wait_steps(self) -> tuple[SemanticStep, ...]:
        return tuple(
            step for step in self.steps if STEP_KINDS[step] == SemanticKind.OPTIONAL_WAIT
        )


@dataclass(frozen=True)
class DoorSemanticSnapshot:
    stack_types: tuple[str, str, str, str]
    planned_steps: tuple[SemanticStep, ...]
    completed_steps: tuple[SemanticStep, ...]
    write_steps: tuple[SemanticStep, ...]
    write_count: int
    written_bytes: bytes
    channel_open_executed: bool
    protocol_ack_observed: bool
    physical_effect_asserted: bool


class CanonicalDoorSemanticFixtureBoundary:
    """Offline-only semantic adapter over the pinned canonical ViP fixture stack.

    The adapter deliberately does not contain credential-bearing payload bytes and
    does not call the canonical channel open primitive.  It models the observed
    research sequence as symbolic steps and emits synthetic semantic markers into
    FixtureTransport through VipSession.send_frame().  This proves ordering,
    one-attempt ambiguity semantics, and compatibility with the canonical session
    stack without providing a real access-control transport.
    """

    def __init__(
        self,
        *,
        vip_root: Path | str = CANONICAL_VIP_ROOT,
        expected_hashes: Mapping[str, str] | None = None,
        legacy_source: Path | str = LEGACY_RESEARCH_SOURCE,
        legacy_sha256: str = LEGACY_RESEARCH_SHA256,
        plan: DoorSemanticPlan | None = None,
        next_channel_id: int = 7449,
        request_id_base: int = 0x7E00,
        fail_before_first_write: bool = False,
        fail_after_write_index: int | None = None,
    ) -> None:
        self.vip_root = Path(vip_root).resolve()
        self.expected_hashes = dict(
            CANONICAL_VIP_SOURCE_HASHES if expected_hashes is None else expected_hashes
        )
        self.legacy_source = Path(legacy_source).resolve()
        self.legacy_sha256 = str(legacy_sha256)
        self.plan = plan or DoorSemanticPlan()
        self.next_channel_id = int(next_channel_id)
        self.request_id_base = int(request_id_base)
        self.fail_before_first_write = bool(fail_before_first_write)
        self.fail_after_write_index = fail_after_write_index
        self.calls = 0
        self.last_snapshot: DoorSemanticSnapshot | None = None

        if self.next_channel_id != 7449:
            raise ValueError("offline semantic adapter pins canonical fixture channel id 7449")
        if self.fail_after_write_index is not None:
            if self.fail_after_write_index < 1:
                raise ValueError("fail_after_write_index must be >= 1")
            if self.fail_after_write_index > len(self.plan.write_steps):
                raise ValueError("fail_after_write_index exceeds semantic write count")

    def _verify_sources(self) -> None:
        if not self.expected_hashes:
            raise ValueError("expected_hashes must not be empty")

        for relative, expected in sorted(self.expected_hashes.items()):
            path = (self.vip_root / relative).resolve()
            try:
                path.relative_to(self.vip_root)
            except ValueError as exc:
                raise ValueError("canonical source path escaped vip_root") from exc
            if not path.is_file():
                raise FileNotFoundError(relative)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"canonical source hash mismatch: {relative}")

        if not self.legacy_source.is_file():
            raise FileNotFoundError(str(self.legacy_source))
        actual_legacy = hashlib.sha256(self.legacy_source.read_bytes()).hexdigest()
        if actual_legacy != self.legacy_sha256:
            raise ValueError("legacy research source hash mismatch")

    def _load_stack_types(self):
        root_str = str(self.vip_root)
        loaded = {
            name: module
            for name, module in sys.modules.items()
            if name == "comelit_vip" or name.startswith("comelit_vip.")
        }
        for name, module in loaded.items():
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                continue
            try:
                Path(module_file).resolve().relative_to(self.vip_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"canonical module already loaded from another root: {name}"
                ) from exc

        inserted = False
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            inserted = True
        try:
            fixture_module = importlib.import_module("comelit_vip.fixture_transport")
            vip_module = importlib.import_module("comelit_vip.vip_session")
            channel_module = importlib.import_module("comelit_vip.channel_session")
            app_module = importlib.import_module("comelit_vip.application_session")
            return (
                fixture_module.FixtureTransport,
                vip_module.VipSession,
                channel_module.VipChannelSession,
                app_module.VipApplicationSession,
            )
        finally:
            if inserted and sys.path and sys.path[0] == root_str:
                sys.path.pop(0)

    @staticmethod
    def _synthetic_body(step: SemanticStep, request: TransportRequest) -> bytes:
        return (
            b"SAFETY-POC-SEMANTIC|"
            + step.value.encode("ascii")
            + b"|"
            + request.operation_id.encode("utf-8", errors="strict")
            + b"|"
            + request.target.encode("utf-8", errors="strict")
        )

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        transport = None
        stack_types = ("unknown", "unknown", "unknown", "unknown")
        completed: list[SemanticStep] = []
        writes_done: list[SemanticStep] = []
        try:
            self._verify_sources()
            FixtureTransport, VipSession, VipChannelSession, VipApplicationSession = (
                self._load_stack_types()
            )
            transport = FixtureTransport()
            vip = VipSession(transport, sync_on_first_frame=False)
            channels = VipChannelSession(vip, next_channel_id=self.next_channel_id)
            app = VipApplicationSession(channels)
            stack_types = (
                type(transport).__name__,
                type(vip).__name__,
                type(channels).__name__,
                type(app).__name__,
            )

            if self.fail_before_first_write:
                raise RuntimeError("simulated failure before semantic write")

            async def run_plan() -> None:
                write_index = 0
                for step in self.plan.steps:
                    kind = STEP_KINDS[step]
                    completed.append(step)
                    if kind != SemanticKind.WRITE:
                        continue
                    write_index += 1
                    await vip.send_frame(
                        self.request_id_base + write_index,
                        self._synthetic_body(step, request),
                    )
                    writes_done.append(step)
                    if self.fail_after_write_index == write_index:
                        raise RuntimeError("simulated failure after semantic write")

            asyncio.run(run_plan())
            writes = tuple(transport.writes)
            self.last_snapshot = DoorSemanticSnapshot(
                stack_types=stack_types,
                planned_steps=self.plan.steps,
                completed_steps=tuple(completed),
                write_steps=tuple(writes_done),
                write_count=len(writes),
                written_bytes=b"".join(writes),
                channel_open_executed=False,
                protocol_ack_observed=False,
                physical_effect_asserted=False,
            )

            if len(writes) != len(self.plan.write_steps):
                return BoundaryEvidence(
                    outcome=BoundaryOutcome.AMBIGUOUS if writes else BoundaryOutcome.PROVEN_NOT_SENT,
                    detail="semantic fixture plan produced unexpected write count",
                    protocol_acknowledged=False,
                )
            return BoundaryEvidence(
                outcome=BoundaryOutcome.ACCEPTED_NO_ACK,
                detail="semantic fixture plan emitted all synthetic writes; protocol ACK not observed",
                protocol_acknowledged=False,
            )
        except Exception as exc:
            writes = tuple(getattr(transport, "writes", ())) if transport is not None else ()
            self.last_snapshot = DoorSemanticSnapshot(
                stack_types=stack_types,
                planned_steps=self.plan.steps,
                completed_steps=tuple(completed),
                write_steps=tuple(writes_done),
                write_count=len(writes),
                written_bytes=b"".join(writes),
                channel_open_executed=False,
                protocol_ack_observed=False,
                physical_effect_asserted=False,
            )
            outcome = BoundaryOutcome.AMBIGUOUS if writes else BoundaryOutcome.PROVEN_NOT_SENT
            return BoundaryEvidence(
                outcome=outcome,
                detail=f"semantic fixture boundary failed: {type(exc).__name__}",
                protocol_acknowledged=False,
            )
