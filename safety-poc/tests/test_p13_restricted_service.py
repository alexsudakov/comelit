import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.audit import AuditSink
from comelit_safety_poc.ha_contract import HaDoorRequest, HaResultState
from comelit_safety_poc.model import State
from comelit_safety_poc.p13_restricted_service import (
    P13RestrictedDoorService,
    P13ServiceConfig,
    P13ServiceState,
)
from comelit_safety_poc.store import Journal
from comelit_safety_poc.transport import MockTransport


class P13RestrictedServiceTests(unittest.TestCase):
    def _make(self, tmp: Path, *, approved: bool = False, scenario: str = "ack"):
        db = tmp / "poc.sqlite3"
        audit = tmp / "audit.jsonl"
        config = P13ServiceConfig(
            journal_path=str(db),
            audit_path=str(audit),
            min_interval_seconds=0,
            explicit_live_approval=approved,
        )
        journal = Journal(db)
        sink = AuditSink(audit)
        transport = MockTransport(scenario)
        service = P13RestrictedDoorService(transport, config, journal=journal, sink=sink)
        return service, journal, audit

    def test_disabled_service_is_fail_closed_without_transport_call(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service, journal, audit = self._make(tmp, approved=False)
            self.assertEqual(service.service_state, P13ServiceState.DISABLED)
            result = service.open_door(HaDoorRequest("op-1", "door"))
            self.assertEqual(result.state, HaResultState.FAILED_SAFE)
            self.assertFalse(result.retry_allowed)
            self.assertFalse(result.physical_effect_asserted)
            # No operation was persisted and no transport call occurred.
            self.assertIsNone(journal.maybe_get("op-1"))

    def test_disabled_service_never_reaches_executor(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service, journal, _ = self._make(tmp, approved=False)
            self.assertEqual(service.service_state, P13ServiceState.DISABLED)
            # Even a duplicate call is rejected without persistence.
            service.open_door(HaDoorRequest("op-1", "door"))
            service.open_door(HaDoorRequest("op-1", "door"))
            self.assertIsNone(journal.maybe_get("op-1"))

    def test_armed_service_uses_one_shot_executor_and_audit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service, journal, audit = self._make(tmp, approved=True, scenario="ack")
            self.assertEqual(service.service_state, P13ServiceState.ARMED)
            result = service.open_door(HaDoorRequest("op-2", "door"))
            self.assertEqual(result.state, HaResultState.ACKED)
            self.assertFalse(result.retry_allowed)
            self.assertFalse(result.physical_effect_asserted)
            op = journal.get("op-2")
            self.assertEqual(op.state, State.ACKED)
            self.assertTrue(AuditSink(audit).verify_durable())

    def test_duplicate_operation_returns_persisted_without_resend(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service, journal, _ = self._make(tmp, approved=True, scenario="ack")
            service.open_door(HaDoorRequest("op-3", "door"))
            # second call returns persisted state, no new transport invocation
            second = service.open_door(HaDoorRequest("op-3", "door"))
            self.assertEqual(second.state, HaResultState.ACKED)
            armed_events = [
                e for e in journal.events("op-3") if e["to_state"] == State.SEND_ARMED.value
            ]
            self.assertEqual(len(armed_events), 1)

    def test_unknown_outcome_maps_conservatively(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service, _, _ = self._make(tmp, approved=True, scenario="timeout_after_accept")
            result = service.open_door(HaDoorRequest("op-4", "door"))
            self.assertEqual(result.state, HaResultState.UNKNOWN_OUTCOME)
            self.assertFalse(result.retry_allowed)

    def test_approval_never_implies_physical_effect(self):
        with self.assertRaises(ValueError):
            P13ServiceConfig(
                journal_path="/tmp/x.sqlite3",
                audit_path="/tmp/x.jsonl",
                explicit_live_approval=True,
                physical_effect_asserted=True,
            )

    def test_service_exposes_no_shell_or_credential_surface(self):
        from comelit_safety_poc import p13_restricted_service as mod

        text = Path(mod.__file__).read_text(encoding="utf-8")
        for forbidden in ("subprocess", "os.system", "Popen(", "read_bytes", "secrets", "token"):
            self.assertNotIn(forbidden, text.replace("operation_id", "").replace("retry_allowed", ""))


if __name__ == "__main__":
    unittest.main()
