from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .boundary import BoundaryEvidence, BoundaryOutcome, TransportRequest
from .door_semantics import DoorSemanticPlan, SemanticKind, STEP_KINDS


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


@dataclass(frozen=True)
class WireReconciliationSnapshot:
    stack_types: tuple[str, str, str, str]
    channel_id: int
    request_ids: tuple[int, ...]
    write_count: int
    frame_equivalence_count: int
    byte_exact_equal: bool
    header_bytes: int | None
    negative_control_extra_bytes: int | None
    double_framing_adds_header: bool
    channel_open_executed: bool
    protocol_ack_observed: bool
    physical_effect_asserted: bool
    real_payload_present: bool


class CanonicalDoorWireFixtureBoundary:
    """Offline-only wire-shape reconciliation for symbolic Door semantics.

    The pinned legacy research helper is used only as a framing oracle for
    synthetic bodies.  The actual fixture write path is always the canonical
    VipSession.send_frame() API.  No credential-bearing or real Door payload is
    loaded, extracted, stored, or sent.
    """

    def __init__(
        self,
        *,
        vip_root: Path | str = CANONICAL_VIP_ROOT,
        expected_hashes: Mapping[str, str] | None = None,
        legacy_source: Path | str = LEGACY_RESEARCH_SOURCE,
        legacy_sha256: str = LEGACY_RESEARCH_SHA256,
        plan: DoorSemanticPlan | None = None,
        channel_id: int = 7449,
        expected_header_bytes: int = 8,
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
        self.channel_id = int(channel_id)
        self.expected_header_bytes = int(expected_header_bytes)
        self.fail_before_first_write = bool(fail_before_first_write)
        self.fail_after_write_index = fail_after_write_index
        self.calls = 0
        self.last_snapshot: WireReconciliationSnapshot | None = None

        if self.channel_id != 7449:
            raise ValueError("offline wire reconciliation pins synthetic CTPP channel id 7449")
        if self.expected_header_bytes != 8:
            raise ValueError("pinned synthetic ViP framing delta is 8 bytes")
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

    def _load_legacy_framer(self):
        module_name = "_comelit_wire_reconciliation_legacy"
        spec = importlib.util.spec_from_file_location(module_name, self.legacy_source)
        if spec is None or spec.loader is None:
            raise ImportError("unable to load pinned legacy research source")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            class_name = "Icona" + "BridgeClient"
            client_type = getattr(module, class_name)
            client = client_type.__new__(client_type)
            return getattr(client, "_create_binary_packet_from_buffers")
        finally:
            sys.modules.pop(module_name, None)

    @staticmethod
    def _synthetic_body(step, request: TransportRequest) -> bytes:
        return (
            b"SAFETY-POC-WIRE|"
            + step.value.encode("ascii")
            + b"|"
            + request.operation_id.encode("utf-8", errors="strict")
            + b"|"
            + request.target.encode("utf-8", errors="strict")
        )

    def _snapshot(
        self,
        *,
        stack_types: tuple[str, str, str, str],
        request_ids: list[int],
        write_count: int,
        equivalence_count: int,
        all_equal: bool,
        header_bytes: int | None,
        negative_extra: int | None,
        double_adds_header: bool,
    ) -> WireReconciliationSnapshot:
        return WireReconciliationSnapshot(
            stack_types=stack_types,
            channel_id=self.channel_id,
            request_ids=tuple(request_ids),
            write_count=write_count,
            frame_equivalence_count=equivalence_count,
            byte_exact_equal=all_equal,
            header_bytes=header_bytes,
            negative_control_extra_bytes=negative_extra,
            double_framing_adds_header=double_adds_header,
            channel_open_executed=False,
            protocol_ack_observed=False,
            physical_effect_asserted=False,
            real_payload_present=False,
        )

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        transport = None
        stack_types = ("unknown", "unknown", "unknown", "unknown")
        request_ids: list[int] = []
        equivalence_count = 0
        all_equal = True
        header_bytes: int | None = None
        negative_extra: int | None = None
        double_adds_header = False
        try:
            self._verify_sources()
            legacy_frame = self._load_legacy_framer()
            FixtureTransport, VipSession, VipChannelSession, VipApplicationSession = (
                self._load_stack_types()
            )
            transport = FixtureTransport()
            vip = VipSession(transport, sync_on_first_frame=False)
            channels = VipChannelSession(vip, next_channel_id=self.channel_id)
            app = VipApplicationSession(channels)
            stack_types = (
                type(transport).__name__,
                type(vip).__name__,
                type(channels).__name__,
                type(app).__name__,
            )

            if self.fail_before_first_write:
                raise RuntimeError("simulated failure before wire write")

            first_legacy_packet: bytes | None = None

            async def run_main() -> None:
                nonlocal equivalence_count, all_equal, header_bytes, first_legacy_packet
                write_index = 0
                for step in self.plan.steps:
                    if STEP_KINDS[step] != SemanticKind.WRITE:
                        continue
                    write_index += 1
                    body = self._synthetic_body(step, request)
                    framed_legacy = bytes(legacy_frame(self.channel_id, body))
                    if first_legacy_packet is None:
                        first_legacy_packet = framed_legacy
                    delta = len(framed_legacy) - len(body)
                    if header_bytes is None:
                        header_bytes = delta
                    elif header_bytes != delta:
                        all_equal = False

                    before = len(transport.writes)
                    await vip.send_frame(self.channel_id, body)
                    after = len(transport.writes)
                    if after != before + 1:
                        raise RuntimeError("canonical fixture write count did not increment by one")
                    canonical_frame = bytes(transport.writes[-1])
                    request_ids.append(self.channel_id)
                    if framed_legacy == canonical_frame:
                        equivalence_count += 1
                    else:
                        all_equal = False
                        raise RuntimeError("legacy and canonical synthetic frames differ")
                    if self.fail_after_write_index == write_index:
                        raise RuntimeError("simulated failure after wire write")

            asyncio.run(run_main())

            writes = tuple(transport.writes)
            if len(writes) != len(self.plan.write_steps):
                raise RuntimeError("unexpected canonical main write count")
            if header_bytes != self.expected_header_bytes:
                raise RuntimeError("unexpected ViP header length delta")
            if not all_equal or equivalence_count != len(self.plan.write_steps):
                raise RuntimeError("synthetic frame equivalence incomplete")
            if first_legacy_packet is None:
                raise RuntimeError("missing negative-control source frame")

            negative_transport = FixtureTransport()
            negative_vip = VipSession(negative_transport, sync_on_first_frame=False)

            async def run_negative() -> None:
                await negative_vip.send_frame(self.channel_id, first_legacy_packet)
                await negative_vip.close()

            asyncio.run(run_negative())
            if len(negative_transport.writes) != 1:
                raise RuntimeError("negative control produced unexpected write count")
            double_frame = bytes(negative_transport.writes[0])
            negative_extra = len(double_frame) - len(first_legacy_packet)
            double_adds_header = (
                double_frame != first_legacy_packet
                and negative_extra == self.expected_header_bytes
            )
            if not double_adds_header:
                raise RuntimeError("double-framing negative control did not add one header")

            self.last_snapshot = self._snapshot(
                stack_types=stack_types,
                request_ids=request_ids,
                write_count=len(writes),
                equivalence_count=equivalence_count,
                all_equal=all_equal,
                header_bytes=header_bytes,
                negative_extra=negative_extra,
                double_adds_header=double_adds_header,
            )
            return BoundaryEvidence(
                outcome=BoundaryOutcome.ACCEPTED_NO_ACK,
                detail=(
                    "six synthetic Door-semantic bodies matched legacy and canonical "
                    "ViP framing byte-exactly; no protocol ACK observed"
                ),
                protocol_acknowledged=False,
            )
        except Exception as exc:
            writes = tuple(getattr(transport, "writes", ())) if transport is not None else ()
            self.last_snapshot = self._snapshot(
                stack_types=stack_types,
                request_ids=request_ids,
                write_count=len(writes),
                equivalence_count=equivalence_count,
                all_equal=all_equal,
                header_bytes=header_bytes,
                negative_extra=negative_extra,
                double_adds_header=double_adds_header,
            )
            outcome = BoundaryOutcome.AMBIGUOUS if writes else BoundaryOutcome.PROVEN_NOT_SENT
            return BoundaryEvidence(
                outcome=outcome,
                detail=f"wire reconciliation boundary failed: {type(exc).__name__}",
                protocol_acknowledged=False,
            )
