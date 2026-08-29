import tempfile
import unittest
from pathlib import Path

from comelit_safety_poc.boundary import (
    BoundaryEvidence,
    BoundaryOutcome,
    BoundaryTransportAdapter,
    DisabledBoundary,
    MockBoundary,
    TransportRequest,
)
from comelit_safety_poc.errors import RealTransportDisabled
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal


class BoundaryContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def run_outcome(self, outcome: BoundaryOutcome, op_id: str):
        boundary = MockBoundary(outcome)
        adapter = BoundaryTransportAdapter(boundary)
        executor = OneShotExecutor(self.journal, adapter, Policy(0))
        op = executor.execute(operation_id=op_id, target="door-contract")
        return op, boundary, adapter, executor

    def test_typed_request_fixes_attempt_number_to_one(self):
        request = TransportRequest(operation_id="op", target="door")
        self.assertEqual(request.attempt_number, 1)
        with self.assertRaises(ValueError):
            TransportRequest(operation_id="op", target="door", attempt_number=2)

    def test_evidence_cannot_assert_physical_effect(self):
        with self.assertRaises(ValueError):
            BoundaryEvidence(
                outcome=BoundaryOutcome.ACKED,
                detail="invalid",
                protocol_acknowledged=True,
                physical_effect_asserted=True,
            )

    def test_ack_maps_to_protocol_acked_only(self):
        op, boundary, adapter, _ = self.run_outcome(BoundaryOutcome.ACKED, "b-ack")
        self.assertEqual(op.state, State.ACKED)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(adapter.last_request.attempt_number, 1)
        self.assertTrue(adapter.last_evidence.protocol_acknowledged)
        self.assertFalse(adapter.last_evidence.physical_effect_asserted)

    def test_accepted_without_ack_maps_unknown(self):
        op, boundary, _, _ = self.run_outcome(BoundaryOutcome.ACCEPTED_NO_ACK, "b-noack")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)

    def test_ambiguous_maps_unknown(self):
        op, boundary, _, _ = self.run_outcome(BoundaryOutcome.AMBIGUOUS, "b-amb")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)

    def test_proven_not_sent_maps_failed_safe(self):
        op, boundary, _, _ = self.run_outcome(BoundaryOutcome.PROVEN_NOT_SENT, "b-safe")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(boundary.calls, 1)

    def test_rejected_maps_failed_safe(self):
        op, boundary, _, _ = self.run_outcome(BoundaryOutcome.REJECTED, "b-reject")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(boundary.calls, 1)

    def test_duplicate_operation_id_never_calls_boundary_twice(self):
        boundary = MockBoundary(BoundaryOutcome.ACKED)
        adapter = BoundaryTransportAdapter(boundary)
        executor = OneShotExecutor(self.journal, adapter, Policy(0))
        first = executor.execute(operation_id="b-dup", target="door-contract")
        second = executor.execute(operation_id="b-dup", target="door-contract")
        self.assertEqual(first.state, State.ACKED)
        self.assertEqual(second.state, State.ACKED)
        self.assertEqual(boundary.calls, 1)

    def test_disabled_boundary_fails_closed(self):
        adapter = BoundaryTransportAdapter(DisabledBoundary())
        request = TransportRequest(operation_id="disabled", target="door")
        with self.assertRaises(RealTransportDisabled):
            DisabledBoundary().attempt_once(request)
        receipt_executor = OneShotExecutor(self.journal, adapter, Policy(0))
        op = receipt_executor.execute(operation_id="disabled-exec", target="door-disabled")
        self.assertEqual(op.state, State.FAILED_SAFE)


if __name__ == "__main__":
    unittest.main()
