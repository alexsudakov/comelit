import tempfile
import unittest
from pathlib import Path

from comelit_safety_poc.errors import SimulatedProcessCrash
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal
from comelit_safety_poc.transport import MockTransport


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite3"
        self.journal = Journal(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def executor(self, scenario="ack", min_interval=0):
        transport = MockTransport(scenario)
        return OneShotExecutor(self.journal, transport, Policy(min_interval)), transport

    def test_success_exactly_one_send(self):
        ex, tr = self.executor("ack")
        op = ex.execute(operation_id="op-1", target="door-a")
        self.assertEqual(op.state, State.ACKED)
        self.assertEqual(tr.calls, 1)
        events = self.journal.events("op-1")
        self.assertEqual([e["to_state"] for e in events], ["PREPARED", "SEND_ARMED", "SENT", "ACKED"])

    def test_duplicate_operation_id_never_resends(self):
        ex, tr = self.executor("ack")
        first = ex.execute(operation_id="same", target="door-a")
        second = ex.execute(operation_id="same", target="door-a")
        self.assertEqual(first.state, State.ACKED)
        self.assertEqual(second.state, State.ACKED)
        self.assertEqual(tr.calls, 1)

    def test_definitely_not_sent_is_failed_safe(self):
        ex, tr = self.executor("definitely_not_sent")
        op = ex.execute(operation_id="op-safe", target="door-a")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(tr.calls, 1)

    def test_timeout_after_accept_is_unknown(self):
        ex, _ = self.executor("timeout_after_accept")
        op = ex.execute(operation_id="op-amb", target="door-a")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)

    def test_accepted_without_ack_is_unknown(self):
        ex, _ = self.executor("accepted_no_ack")
        op = ex.execute(operation_id="op-noack", target="door-a")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)

    def test_explicit_rejection_is_failed_safe(self):
        ex, tr = self.executor("rejected")
        op = ex.execute(operation_id="op-rejected", target="door-a")
        self.assertEqual(op.state, State.FAILED_SAFE)
        self.assertEqual(tr.calls, 1)

    def test_crash_pre_arm_recovers_failed_safe_without_retry(self):
        ex, tr = self.executor("ack")
        with self.assertRaises(SimulatedProcessCrash):
            ex.execute(operation_id="crash-pre", target="door-a", fault="crash_pre_arm")
        self.assertEqual(tr.calls, 0)
        recovered = ex.recover()
        self.assertEqual(recovered[0].state, State.FAILED_SAFE)
        self.assertEqual(tr.calls, 0)

    def test_crash_after_arm_recovers_unknown_without_retry(self):
        ex, tr = self.executor("ack")
        with self.assertRaises(SimulatedProcessCrash):
            ex.execute(operation_id="crash-arm", target="door-a", fault="crash_after_arm")
        self.assertEqual(tr.calls, 0)
        recovered = ex.recover()
        self.assertEqual(recovered[0].state, State.UNKNOWN_OUTCOME)
        self.assertEqual(tr.calls, 0)

    def test_crash_after_sent_recovers_unknown_without_retry(self):
        ex, tr = self.executor("ack")
        with self.assertRaises(SimulatedProcessCrash):
            ex.execute(operation_id="crash-sent", target="door-a", fault="crash_after_sent")
        self.assertEqual(tr.calls, 1)
        recovered = ex.recover()
        self.assertEqual(recovered[0].state, State.UNKNOWN_OUTCOME)
        self.assertEqual(tr.calls, 1)

    def test_rate_limit_blocks_second_distinct_operation_without_send(self):
        ex1, tr1 = self.executor("ack", min_interval=3600)
        op1 = ex1.execute(operation_id="rl-1", target="door-a")
        self.assertEqual(op1.state, State.ACKED)
        self.assertEqual(tr1.calls, 1)

        ex2, tr2 = self.executor("ack", min_interval=3600)
        op2 = ex2.execute(operation_id="rl-2", target="door-a")
        self.assertEqual(op2.state, State.FAILED_SAFE)
        self.assertEqual(tr2.calls, 0)


if __name__ == "__main__":
    unittest.main()
