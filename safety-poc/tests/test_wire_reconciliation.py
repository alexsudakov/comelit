import hashlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryOutcome, BoundaryTransportAdapter, TransportRequest
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal
from comelit_safety_poc.wire_reconciliation import CanonicalDoorWireFixtureBoundary


class WireReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vip_root = base / "vip"
        pkg = self.vip_root / "comelit_vip"
        pkg.mkdir(parents=True)
        self._write_fake_package(pkg, mode="ok")
        self.legacy = base / "legacy.py"
        self._write_legacy(mode="ok")
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
                        self.closed = False
                    @property
                    def writes(self):
                        return tuple(self._writes)
                    async def write(self, data):
                        if self.closed:
                            raise RuntimeError('closed')
                        self._writes.append(bytes(data))
                    async def read(self, max_bytes=4096):
                        return b''
                    async def close(self):
                        self.closed = True
                """
            ),
            encoding="utf-8",
        )
        if mode == "ok":
            send_body = "packet = request_id.to_bytes(4, 'little') + len(body).to_bytes(4, 'little') + body; await self.transport.write(packet)"
        elif mode == "before_write":
            send_body = "raise RuntimeError('before write')"
        else:
            send_body = "packet = b'BADFRAME' + body; await self.transport.write(packet)"
        (pkg / "vip_session.py").write_text(
            textwrap.dedent(
                f"""
                class VipSession:
                    def __init__(self, transport, *, sync_on_first_frame=True):
                        self.transport = transport
                    async def send_frame(self, request_id, body):
                        {send_body}
                    async def close(self):
                        await self.transport.close()
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

    def _write_legacy(self, *, mode: str):
        if mode == "ok":
            packet_expr = "request_id.to_bytes(4, 'little') + len(body).to_bytes(4, 'little') + body"
        else:
            packet_expr = "b'LEGACYBAD' + body"
        self.legacy.write_text(
            textwrap.dedent(
                f"""
                class IconaBridgeClient:
                    def _create_binary_packet_from_buffers(self, request_id, *buffers):
                        body = b''.join(buffers)
                        return {packet_expr}
                """
            ),
            encoding="utf-8",
        )

    def _hashes(self):
        return {
            str(path.relative_to(self.vip_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.vip_root / "comelit_vip").glob("*.py"))
        }

    def _boundary(self, **kwargs):
        return CanonicalDoorWireFixtureBoundary(
            vip_root=self.vip_root,
            expected_hashes=self.hashes,
            legacy_source=self.legacy,
            legacy_sha256=self.legacy_hash,
            **kwargs,
        )

    def test_six_wire_writes_use_same_ctpp_channel_id(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("wire-ids", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertEqual(boundary.last_snapshot.request_ids, (7449,) * 6)
        self.assertEqual(boundary.last_snapshot.channel_id, 7449)

    def test_all_six_frames_are_byte_exact_equal(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("wire-equal", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertTrue(boundary.last_snapshot.byte_exact_equal)
        self.assertEqual(boundary.last_snapshot.frame_equivalence_count, 6)
        self.assertEqual(boundary.last_snapshot.write_count, 6)

    def test_header_delta_is_eight_bytes(self):
        boundary = self._boundary()
        boundary.attempt_once(TransportRequest("wire-header", "synthetic"))
        self.assertEqual(boundary.last_snapshot.header_bytes, 8)

    def test_double_framing_negative_control_adds_header(self):
        boundary = self._boundary()
        boundary.attempt_once(TransportRequest("wire-double", "synthetic"))
        self.assertTrue(boundary.last_snapshot.double_framing_adds_header)
        self.assertEqual(boundary.last_snapshot.negative_control_extra_bytes, 8)

    def test_complete_reconciliation_maps_accepted_without_ack(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("wire-one", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertFalse(evidence.protocol_acknowledged)
        self.assertFalse(evidence.physical_effect_asserted)
        self.assertFalse(boundary.last_snapshot.real_payload_present)
        self.assertFalse(boundary.last_snapshot.channel_open_executed)

    def test_executor_maps_reconciliation_to_unknown_outcome(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        op = executor.execute(operation_id="wire-exec", target="synthetic")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)

    def test_duplicate_operation_id_does_not_repeat_reconciliation(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        first = executor.execute(operation_id="wire-dup", target="synthetic")
        second = executor.execute(operation_id="wire-dup", target="synthetic")
        self.assertEqual(first.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(second.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)

    def test_failure_after_third_write_is_ambiguous(self):
        boundary = self._boundary(fail_after_write_index=3)
        evidence = boundary.attempt_once(TransportRequest("wire-partial", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(boundary.last_snapshot.write_count, 3)
        self.assertEqual(boundary.last_snapshot.request_ids, (7449,) * 3)

    def test_failure_before_first_write_is_proven_not_sent(self):
        boundary = self._boundary(fail_before_first_write=True)
        evidence = boundary.attempt_once(TransportRequest("wire-pre", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_byte_mismatch_after_canonical_write_is_ambiguous(self):
        self._write_legacy(mode="mismatch")
        self.legacy_hash = hashlib.sha256(self.legacy.read_bytes()).hexdigest()
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("wire-mismatch", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(boundary.last_snapshot.write_count, 1)
        self.assertFalse(boundary.last_snapshot.byte_exact_equal)

    def test_source_hash_mismatch_is_proven_not_sent(self):
        bad_hashes = dict(self.hashes)
        first = next(iter(bad_hashes))
        bad_hashes[first] = "0" * 64
        boundary = CanonicalDoorWireFixtureBoundary(
            vip_root=self.vip_root,
            expected_hashes=bad_hashes,
            legacy_source=self.legacy,
            legacy_sha256=self.legacy_hash,
        )
        evidence = boundary.attempt_once(TransportRequest("wire-hash", "synthetic"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)
