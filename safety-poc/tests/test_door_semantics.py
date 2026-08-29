import hashlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryOutcome, BoundaryTransportAdapter, TransportRequest
from comelit_safety_poc.door_semantics import (
    CanonicalDoorSemanticFixtureBoundary,
    DoorSemanticPlan,
    SemanticKind,
    SemanticStep,
    STEP_KINDS,
)
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal


class DoorSemanticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vip_root = base / "vip"
        pkg = self.vip_root / "comelit_vip"
        pkg.mkdir(parents=True)
        self._write_fake_package(pkg, mode="ok")
        self.legacy = base / "legacy.py"
        self.legacy.write_text("# pinned research source\n", encoding="utf-8")
        self.legacy_hash = hashlib.sha256(self.legacy.read_bytes()).hexdigest()
        self.hashes = self._hashes()
        self.journal = Journal(base / "state.sqlite3")

    def tearDown(self):
        for name in list(sys.modules):
            if name == "comelit_vip" or name.startswith("comelit_vip."):
                del sys.modules[name]
        self.tmp.cleanup()

    def _write_fake_package(self, pkg: Path, *, mode: str):
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "transport.py").write_text("class VipTransport: pass\n", encoding="utf-8")
        (pkg / "control_codec.py").write_text("class Placeholder: pass\n", encoding="utf-8")
        (pkg / "vip_codec.py").write_text("class Placeholder: pass\n", encoding="utf-8")
        (pkg / "fixture_transport.py").write_text(
            textwrap.dedent(
                """
                class FixtureTransport:
                    def __init__(self):
                        self._writes = []
                    @property
                    def writes(self):
                        return tuple(self._writes)
                    async def write(self, data):
                        self._writes.append(bytes(data))
                    async def read(self, max_bytes=4096):
                        return b""
                    async def close(self):
                        pass
                """
            ),
            encoding="utf-8",
        )
        if mode == "ok":
            send_body = "await self.transport.write(b'FRAME:' + body)"
        elif mode == "after_write":
            send_body = "await self.transport.write(b'FRAME:' + body); raise RuntimeError('after write')"
        else:
            send_body = "raise RuntimeError('before write')"
        (pkg / "vip_session.py").write_text(
            textwrap.dedent(
                f"""
                class VipSession:
                    def __init__(self, transport, *, sync_on_first_frame=True):
                        self.transport = transport
                        self.sync_on_first_frame = sync_on_first_frame
                    async def send_frame(self, request_id, body):
                        {send_body}
                """
            ),
            encoding="utf-8",
        )
        (pkg / "channel_session.py").write_text(
            "class VipChannelSession:\n    def __init__(self, session, *, next_channel_id, ack_response_word=0):\n        self.session = session\n        self.next_channel_id = next_channel_id\n",
            encoding="utf-8",
        )
        (pkg / "application_session.py").write_text(
            "class VipApplicationSession:\n    def __init__(self, channels): self.channels = channels\n",
            encoding="utf-8",
        )

    def _hashes(self):
        return {
            str(path.relative_to(self.vip_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.vip_root / "comelit_vip").glob("*.py"))
        }

    def _boundary(self, **kwargs):
        return CanonicalDoorSemanticFixtureBoundary(
            vip_root=self.vip_root,
            expected_hashes=self.hashes,
            legacy_source=self.legacy,
            legacy_sha256=self.legacy_hash,
            **kwargs,
        )

    def test_plan_is_fixed_and_contains_six_writes(self):
        plan = DoorSemanticPlan()
        self.assertEqual(plan.steps, tuple(SemanticStep))
        self.assertEqual(len(plan.steps), 9)
        self.assertEqual(len(plan.write_steps), 6)
        self.assertEqual(len(plan.optional_wait_steps), 2)
        self.assertEqual(STEP_KINDS[plan.steps[0]], SemanticKind.CHANNEL_PRECONDITION)

    def test_channel_precondition_is_symbolic_not_executed(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("v4-channel", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertFalse(boundary.last_snapshot.channel_open_executed)
        self.assertEqual(boundary.last_snapshot.stack_types, (
            "FixtureTransport", "VipSession", "VipChannelSession", "VipApplicationSession"
        ))

    def test_complete_semantic_plan_maps_accepted_without_ack(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("v4-one", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertFalse(evidence.protocol_acknowledged)
        self.assertFalse(evidence.physical_effect_asserted)
        self.assertEqual(boundary.last_snapshot.write_count, 6)
        self.assertEqual(boundary.last_snapshot.write_steps, boundary.plan.write_steps)

    def test_executor_maps_complete_plan_to_unknown_outcome(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        op = executor.execute(operation_id="v4-exec", target="semantic-target")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(boundary.last_snapshot.write_count, 6)

    def test_duplicate_operation_id_does_not_execute_second_plan(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        first = executor.execute(operation_id="v4-dup", target="semantic-target")
        second = executor.execute(operation_id="v4-dup", target="semantic-target")
        self.assertEqual(first.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(second.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(boundary.last_snapshot.write_count, 6)

    def test_failure_before_first_write_is_proven_not_sent(self):
        boundary = self._boundary(fail_before_first_write=True)
        evidence = boundary.attempt_once(TransportRequest("v4-pre", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_failure_after_partial_plan_is_ambiguous(self):
        boundary = self._boundary(fail_after_write_index=3)
        evidence = boundary.attempt_once(TransportRequest("v4-mid", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(boundary.last_snapshot.write_count, 3)

    def test_legacy_source_hash_mismatch_is_proven_not_sent(self):
        boundary = CanonicalDoorSemanticFixtureBoundary(
            vip_root=self.vip_root,
            expected_hashes=self.hashes,
            legacy_source=self.legacy,
            legacy_sha256="0" * 64,
        )
        evidence = boundary.attempt_once(TransportRequest("v4-legacy", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_canonical_source_hash_mismatch_is_proven_not_sent(self):
        hashes = dict(self.hashes)
        key = sorted(hashes)[0]
        hashes[key] = "0" * 64
        boundary = CanonicalDoorSemanticFixtureBoundary(
            vip_root=self.vip_root,
            expected_hashes=hashes,
            legacy_source=self.legacy,
            legacy_sha256=self.legacy_hash,
        )
        evidence = boundary.attempt_once(TransportRequest("v4-canonical", "semantic-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_payload_is_synthetic_semantic_marker_only(self):
        boundary = self._boundary()
        boundary.attempt_once(TransportRequest("v4-synth", "semantic-target"))
        data = boundary.last_snapshot.written_bytes
        self.assertIn(b"SAFETY-POC-SEMANTIC|", data)
        self.assertNotIn(b"credential", data.lower())
        self.assertFalse(boundary.last_snapshot.protocol_ack_observed)
        self.assertFalse(boundary.last_snapshot.physical_effect_asserted)


if __name__ == "__main__":
    unittest.main()
