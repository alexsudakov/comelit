from __future__ import annotations

import asyncio
import hashlib
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .boundary import BoundaryEvidence, BoundaryOutcome, TransportRequest


CANONICAL_VIP_ROOT = Path("/root/comelit-vip-poc")
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
class FixtureProbeSnapshot:
    stack_types: tuple[str, str, str, str]
    write_count: int
    written_bytes: bytes


class CanonicalVipFixtureBoundary:
    """Offline-only adapter to the canonical ViP session stack.

    The boundary verifies pinned source hashes before importing the canonical
    package, injects FixtureTransport, constructs the full session stack, and
    sends one synthetic ViP frame.  No socket/network transport is created.

    A successful fixture write is deliberately *not* an ACK: it maps to
    ACCEPTED_NO_ACK so the OneShotExecutor persists UNKNOWN_OUTCOME.  This
    class does not contain Door payloads or physical-action semantics.
    """

    def __init__(
        self,
        *,
        vip_root: Path | str = CANONICAL_VIP_ROOT,
        expected_hashes: Mapping[str, str] | None = None,
        request_id: int = 0x7F01,
    ) -> None:
        self.vip_root = Path(vip_root).resolve()
        self.expected_hashes = dict(
            CANONICAL_VIP_SOURCE_HASHES if expected_hashes is None else expected_hashes
        )
        self.request_id = int(request_id)
        self.calls = 0
        self.last_snapshot: FixtureProbeSnapshot | None = None

    def _verify_source_hashes(self) -> None:
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
    def _probe_body(request: TransportRequest) -> bytes:
        # Synthetic fixture-only payload. It is intentionally not a Door command.
        return (
            b"SAFETY-POC-VIP-FIXTURE|"
            + request.operation_id.encode("utf-8", errors="strict")
            + b"|"
            + request.target.encode("utf-8", errors="strict")
        )

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        transport = None
        try:
            self._verify_source_hashes()
            FixtureTransport, VipSession, VipChannelSession, VipApplicationSession = (
                self._load_stack_types()
            )
            transport = FixtureTransport()
            vip = VipSession(transport, sync_on_first_frame=False)
            channels = VipChannelSession(vip, next_channel_id=7449)
            app = VipApplicationSession(channels)
            payload = self._probe_body(request)

            async def write_once() -> None:
                await vip.send_frame(self.request_id, payload)

            asyncio.run(write_once())
            writes = tuple(transport.writes)
            self.last_snapshot = FixtureProbeSnapshot(
                stack_types=(
                    type(transport).__name__,
                    type(vip).__name__,
                    type(channels).__name__,
                    type(app).__name__,
                ),
                write_count=len(writes),
                written_bytes=b"".join(writes),
            )

            if len(writes) == 0:
                return BoundaryEvidence(
                    outcome=BoundaryOutcome.PROVEN_NOT_SENT,
                    detail="canonical fixture stack produced no transport write",
                    protocol_acknowledged=False,
                )
            if len(writes) != 1:
                return BoundaryEvidence(
                    outcome=BoundaryOutcome.AMBIGUOUS,
                    detail="canonical fixture stack produced unexpected write count",
                    protocol_acknowledged=False,
                )
            return BoundaryEvidence(
                outcome=BoundaryOutcome.ACCEPTED_NO_ACK,
                detail="canonical VipSession emitted one fixture write; protocol ACK not observed",
                protocol_acknowledged=False,
            )
        except Exception as exc:
            writes = tuple(getattr(transport, "writes", ())) if transport is not None else ()
            self.last_snapshot = FixtureProbeSnapshot(
                stack_types=("unknown", "unknown", "unknown", "unknown"),
                write_count=len(writes),
                written_bytes=b"".join(writes),
            )
            outcome = BoundaryOutcome.AMBIGUOUS if writes else BoundaryOutcome.PROVEN_NOT_SENT
            return BoundaryEvidence(
                outcome=outcome,
                detail=f"canonical fixture boundary failed: {type(exc).__name__}",
                protocol_acknowledged=False,
            )
