import tempfile
import unittest
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryTransportAdapter
from comelit_safety_poc.control_plane_model import ControlOutcome
from comelit_safety_poc.door_transaction import SyntheticDoorTransactionBoundary
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal


class DoorTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, boundary, operation_id):
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        return executor.execute(operation_id=operation_id, target="synthetic-door")

    def test_full_transaction_is_unknown_without_door_ack(self):
        boundary = SyntheticDoorTransactionBoundary()
        op = self.execute(boundary, "tx-full")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(boundary.last_snapshot.door_write_count, 6)
        self.assertEqual(boundary.last_snapshot.channel_open_calls, 1)
        self.assertEqual(boundary.last_snapshot.channel_close_calls, 1)
        self.assertFalse(boundary.last_snapshot.physical_effect_asserted)

    def test_failure_before_any_control_attempt_is_failed_safe(self):
        boundary = SyntheticDoorTransactionBoundary(fail_before_open=True)
        op = self.execute(boundary, "tx-before")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(boundary.last_snapshot.channel_open_calls, 0)
        self.assertEqual(boundary.last_snapshot.door_write_count, 0)

    def test_explicit_open_rejection_is_failed_safe_without_door_payload(self):
        boundary = SyntheticDoorTransactionBoundary(control_open_outcome=ControlOutcome.REJECTED)
        op = self.execute(boundary, "tx-open-reject")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(boundary.last_snapshot.channel_open_calls, 1)
        self.assertEqual(boundary.last_snapshot.door_write_count, 0)

    def test_ambiguous_channel_open_is_unknown_and_not_retryable(self):
        boundary = SyntheticDoorTransactionBoundary(control_open_outcome=ControlOutcome.AMBIGUOUS)
        op = self.execute(boundary, "tx-open-amb")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.last_snapshot.channel_open_calls, 1)
        self.assertEqual(boundary.last_snapshot.door_write_count, 0)

    def test_failure_after_partial_door_write_is_unknown(self):
        boundary = SyntheticDoorTransactionBoundary(fail_after_door_write=3)
        op = self.execute(boundary, "tx-partial")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.last_snapshot.door_write_count, 3)

    def test_duplicate_operation_id_does_not_repeat_transaction(self):
        boundary = SyntheticDoorTransactionBoundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        first = executor.execute(operation_id="tx-dup", target="synthetic-door")
        second = executor.execute(operation_id="tx-dup", target="synthetic-door")
        self.assertEqual(first.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(second.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)


if __name__ == "__main__":
    unittest.main()
