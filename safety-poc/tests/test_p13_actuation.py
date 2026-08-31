import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.audit import AuditEntry, AuditSink, AuditedExecutorTransport
from comelit_safety_poc.boundary import (
    BoundaryEvidence,
    BoundaryOutcome,
    BoundaryTransportAdapter,
    TransportRequest,
)
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.p13_actuation_boundary import (
    CtppOpenOutcome,
    FixtureP13DoorSession,
    P13BodyFileLoader,
    P13PayloadBundle,
    RealDoorActuationBoundary,
)
from comelit_safety_poc.p13_transport_model import (
    P13ActuationContract,
    P13ActuationEvidence,
    P13TransportStage,
    default_p13_contract,
    validate_p13_plan,
)
from comelit_safety_poc.store import Journal
from comelit_safety_poc.transport import MockTransport

CLI = SRC.parent / "src" / "comelit_safety_poc" / "cli.py"


def make_bundle() -> P13PayloadBundle:
    bodies = [bytes([i + 1]) * 12 for i in range(6)]
    return P13PayloadBundle(
        schema=1,
        ucfg_sha256="d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
        target_index=0,
        target_fingerprint="f" * 64,
        target_name="FixtureDoor",
        channel_id_fixture=7449,
        write_count=6,
        write_sha256=tuple(__import__("hashlib").sha256(b).hexdigest() for b in bodies),
        write_bytes=tuple(len(b) for b in bodies),
    )


class DictBodyLoader:
    def __init__(self, bodies):
        self.bodies = bodies

    def load(self, index: int) -> str:
        return self.bodies[index].hex()


class P13ContractTests(unittest.TestCase):
    def test_default_contract_is_safe(self):
        contract = default_p13_contract()
        self.assertEqual(contract.attempt_number_fixed, 1)
        self.assertFalse(contract.automatic_retry_allowed)
        self.assertFalse(contract.credential_export_allowed)
        self.assertFalse(contract.physical_effect_assertion_allowed)

    def test_direct_tcp_primary_is_forbidden(self):
        with self.assertRaises(ValueError):
            P13ActuationContract(direct_tcp_primary_path_allowed=True).validate()

    def test_retry_or_physical_assertion_is_forbidden(self):
        for kw in ("automatic_retry_allowed", "credential_export_allowed", "physical_effect_assertion_allowed"):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    P13ActuationContract(**{kw: True}).validate()

    def test_plan_matches_fixed_sequence(self):
        validate_p13_plan(tuple(P13TransportStage))
        with self.assertRaises(ValueError):
            validate_p13_plan((P13TransportStage.CTPP_OPEN,))

    def test_evidence_cannot_assert_physical_effect(self):
        ev = P13ActuationEvidence(
            cloud_signaling=True, ice_connected=True, pseudotcp_open=True, vip_echo_ack=True,
            uaut_open=True, uaut_auth_200=True, ctpp_open=True, door_write_count=6,
            ctpp_close=True, clean_teardown=True, physical_effect_asserted=True,
        )
        self.assertFalse(ev.actuation_transaction_complete)


class AuditSinkTests(unittest.TestCase):
    def test_append_only_durable_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            sink = AuditSink(path)
            sink.record_raw(AuditEntry(ts="t1", operation_id="op-1", event_type="transport_attempt", state="SEND_ARMED"))
            sink.record_raw(AuditEntry(ts="t2", operation_id="op-1", event_type="transport_outcome", state="SENT"))
            self.assertTrue(sink.verify_durable())
            entries = sink.entries()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].operation_id, "op-1")

    def test_unknown_event_type_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = AuditSink(Path(tmp) / "audit.jsonl")
            with self.assertRaises(ValueError):
                sink.record_raw(AuditEntry(ts="t", operation_id="x", event_type="bogus", state="PREPARED"))

    def test_truncated_journal_not_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            path.write_text('{"ts":"t","operation_id":"x","event_type":"preflight","state":"PREPARED"}\n{"partial"', encoding="utf-8")
            sink = AuditSink(path)
            self.assertFalse(sink.verify_durable())

    def test_audited_executor_transport_records_attempt_and_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = AuditSink(Path(tmp) / "audit.jsonl")
            transport = AuditedExecutorTransport(MockTransport("ack"), sink)
            receipt = transport.send_once(operation_id="op-9", target="door")
            self.assertTrue(receipt.accepted)
            types = [e.event_type for e in sink.entries()]
            self.assertIn("transport_attempt", types)
            self.assertIn("transport_outcome", types)


class P13BoundaryTests(unittest.TestCase):
    def test_successful_fixture_transaction_maps_to_accepted_no_ack(self):
        bodies = [bytes([i + 1]) * 12 for i in range(6)]
        session = FixtureP13DoorSession()
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader(bodies))
        evidence = boundary.attempt_once(TransportRequest(operation_id="op-1", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertFalse(evidence.protocol_acknowledged)
        self.assertFalse(evidence.physical_effect_asserted)
        self.assertEqual(session.write_count, 6)
        self.assertTrue(session.teardown_called)

    def test_fail_before_open_is_proven_not_sent(self):
        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.PROVEN_NOT_OPENED)
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]))
        evidence = boundary.attempt_once(TransportRequest(operation_id="op-2", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(session.write_count, 0)

    def test_ambiguous_open_is_never_downgraded(self):
        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.AMBIGUOUS)
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]))
        evidence = boundary.attempt_once(TransportRequest(operation_id="op-3", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)

    def test_failure_after_door_write_is_ambiguous(self):
        bodies = [bytes([i + 1]) * 12 for i in range(6)]
        session = FixtureP13DoorSession(fail_after_writes=3)
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader(bodies))
        evidence = boundary.attempt_once(TransportRequest(operation_id="op-4", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertGreaterEqual(session.write_count, 1)

    def test_second_invocation_is_forbidden(self):
        session = FixtureP13DoorSession()
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]))
        boundary.attempt_once(TransportRequest(operation_id="op-5", target="f" * 64))
        with self.assertRaises(AssertionError):
            boundary.attempt_once(TransportRequest(operation_id="op-5", target="f" * 64))

    def test_target_binding_mismatch_fails_closed(self):
        session = FixtureP13DoorSession()
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]))
        with self.assertRaises(ValueError):
            boundary.attempt_once(TransportRequest(operation_id="op-6", target="wrong-target"))

    def test_body_sha_mismatch_fails_closed(self):
        bodies = [bytes([i + 1]) * 12 for i in range(6)]
        bad = [b"z" * 12] + bodies[1:]
        session = FixtureP13DoorSession()
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader(bad))
        evidence = boundary.attempt_once(TransportRequest(operation_id="op-7", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(session.write_count, 0)

    def test_adapter_maps_ambiguous_to_raise(self):
        from comelit_safety_poc.errors import AmbiguousSend

        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.AMBIGUOUS)
        boundary = RealDoorActuationBoundary(session, make_bundle(), body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]))
        adapter = BoundaryTransportAdapter(boundary)
        with self.assertRaises(AmbiguousSend):
            adapter.send_once(operation_id="op-8", target="f" * 64)


class ThrowingOpenSession:
    """Simulates a real adapter whose CTPP open raises (timeout/disconnect/parse)."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.write_count = 0

    def open_ctpp(self):
        raise self.exc

    def write_door_body(self, body_hex: str) -> None:
        self.write_count += 1

    def close_ctpp(self) -> bool:
        return True

    def teardown(self) -> None:
        return None


class P13CtppOpenConservativeTests(unittest.TestCase):
    """Blocker 2: exceptions from the real open operation default to AMBIGUOUS."""

    def _boundary(self, session):
        return RealDoorActuationBoundary(
            session,
            make_bundle(),
            body_loader=DictBodyLoader([bytes([i + 1]) * 12 for i in range(6)]),
        )

    def test_timeout_during_open_is_ambiguous(self):
        session = ThrowingOpenSession(TimeoutError("open timed out"))
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t1", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(session.write_count, 0)

    def test_disconnect_during_open_is_ambiguous(self):
        session = ThrowingOpenSession(ConnectionError("peer disconnected"))
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t2", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)

    def test_parse_failure_during_open_is_ambiguous(self):
        session = ThrowingOpenSession(ValueError("malformed open response"))
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t3", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)

    def test_proven_not_opened_is_proven_not_sent(self):
        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.PROVEN_NOT_OPENED)
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t4", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(session.write_count, 0)

    def test_explicit_rejection_is_rejected(self):
        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.REJECTED)
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t5", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.REJECTED)
        self.assertEqual(session.write_count, 0)

    def test_ambiguous_outcome_never_downgraded(self):
        session = FixtureP13DoorSession(open_outcome=CtppOpenOutcome.AMBIGUOUS)
        evidence = self._boundary(session).attempt_once(TransportRequest(operation_id="op-t6", target="f" * 64))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)


class P13ExactSixWritesTests(unittest.TestCase):
    """Blocker 3: actuation_transaction_complete requires exactly six writes."""

    def _evidence(self, count: int) -> P13ActuationEvidence:
        return P13ActuationEvidence(
            cloud_signaling=True, ice_connected=True, pseudotcp_open=True, vip_echo_ack=True,
            uaut_open=True, uaut_auth_200=True, ctpp_open=True, door_write_count=count,
            ctpp_close=True, clean_teardown=True,
        )

    def test_exactly_six_writes_complete(self):
        self.assertTrue(self._evidence(6).actuation_transaction_complete)

    def test_zero_writes_incomplete(self):
        self.assertFalse(self._evidence(0).actuation_transaction_complete)

    def test_one_write_incomplete(self):
        self.assertFalse(self._evidence(1).actuation_transaction_complete)

    def test_five_writes_incomplete(self):
        self.assertFalse(self._evidence(5).actuation_transaction_complete)

    def test_seven_writes_incomplete(self):
        self.assertFalse(self._evidence(7).actuation_transaction_complete)


class P13PayloadFileTests(unittest.TestCase):
    def test_loader_requires_mode_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payloads.json"
            path.write_text(json.dumps({"bodies": [{"hex": "aa", "bytes": 1, "sha256": "x"}]}), encoding="utf-8")
            os.chmod(path, 0o644)
            loader = P13BodyFileLoader(path)
            with self.assertRaises(ValueError):
                loader.load(0)

    def test_loader_reads_body_hex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payloads.json"
            path.write_text(json.dumps({"bodies": [{"hex": "aabb", "bytes": 2, "sha256": "y"}]}), encoding="utf-8")
            os.chmod(path, 0o600)
            loader = P13BodyFileLoader(path)
            self.assertEqual(loader.load(0), "aabb")


class P13ExecutorIntegrationTests(unittest.TestCase):
    def _run_cli(self, args, cwd):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "comelit_safety_poc.cli", *args],
            capture_output=True, text=True, cwd=cwd, env=env, timeout=60,
        )

    def _payload_file(self, tmp: Path) -> Path:
        bodies = [bytes([i + 1]) * 12 for i in range(6)]
        payload = {
            "schema": 1,
            "ucfg_sha256": "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
            "target_index": 0,
            "target_fingerprint": "f" * 64,
            "target_name": "FixtureDoor",
            "channel_id_fixture": 7449,
            "write_count": 6,
            "bodies": [
                {"hex": b.hex(), "bytes": len(b), "sha256": __import__("hashlib").sha256(b).hexdigest()}
                for b in bodies
            ],
        }
        path = tmp / "payloads.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def test_duplicate_operation_id_never_sends_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "poc.sqlite3"
            payload = self._payload_file(tmp)
            first = self._run_cli(
                ["--db", str(db), "run", "--operation-id", "p13-dupe", "--target", "f" * 64,
                 "--backend", "p13-fixture", "--p13-payload", str(payload), "--min-interval-seconds", "0"],
                cwd=tmp,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self._run_cli(
                ["--db", str(db), "run", "--operation-id", "p13-dupe", "--target", "f" * 64,
                 "--backend", "p13-fixture", "--p13-payload", str(payload), "--min-interval-seconds", "0"],
                cwd=tmp,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            out = json.loads(second.stdout)
            self.assertEqual(out["state"], "UNKNOWN_OUTCOME")
            # Exactly one operation row, one SEND_ARMED event.
            con = sqlite3.connect(db)
            count = con.execute("SELECT COUNT(*) FROM operations WHERE operation_id='p13-dupe'").fetchone()[0]
            armed = con.execute(
                "SELECT COUNT(*) FROM events WHERE operation_id='p13-dupe' AND to_state='SEND_ARMED'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(count, 1)
            self.assertEqual(armed, 1)

    def test_crash_before_arm_is_failed_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "poc.sqlite3"
            payload = self._payload_file(tmp)
            proc = self._run_cli(
                ["--db", str(db), "run", "--operation-id", "p13-crash-pre", "--target", "f" * 64,
                 "--backend", "p13-fixture", "--p13-payload", str(payload),
                 "--fault", "crash_pre_arm", "--min-interval-seconds", "0"],
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 75, proc.stdout)
            recover = self._run_cli(["--db", str(db), "recover"], cwd=tmp)
            self.assertEqual(recover.returncode, 0)
            con = sqlite3.connect(db)
            state = con.execute("SELECT state FROM operations WHERE operation_id='p13-crash-pre'").fetchone()[0]
            con.close()
            self.assertEqual(state, "FAILED_SAFE")

    def test_crash_after_arm_is_unknown_outcome_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "poc.sqlite3"
            payload = self._payload_file(tmp)
            proc = self._run_cli(
                ["--db", str(db), "run", "--operation-id", "p13-crash-post", "--target", "f" * 64,
                 "--backend", "p13-fixture", "--p13-payload", str(payload),
                 "--fault", "crash_after_arm", "--min-interval-seconds", "0"],
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 75, proc.stdout)
            recover = self._run_cli(["--db", str(db), "recover"], cwd=tmp)
            self.assertEqual(recover.returncode, 0)
            con = sqlite3.connect(db)
            state = con.execute("SELECT state FROM operations WHERE operation_id='p13-crash-post'").fetchone()[0]
            events = con.execute(
                "SELECT to_state FROM events WHERE operation_id='p13-crash-post' ORDER BY id"
            ).fetchall()
            con.close()
            self.assertEqual(state, "UNKNOWN_OUTCOME")
            self.assertEqual([r[0] for r in events].count("SEND_ARMED"), 1)

    def test_audit_durable_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "poc.sqlite3"
            audit = tmp / "audit.jsonl"
            payload = self._payload_file(tmp)
            proc = self._run_cli(
                ["--db", str(db), "run", "--operation-id", "p13-audit", "--target", "f" * 64,
                 "--backend", "p13-fixture", "--p13-payload", str(payload),
                 "--min-interval-seconds", "0", "--audit", str(audit)],
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(AuditSink(audit).verify_durable())
            types = [e.event_type for e in AuditSink(audit).entries()]
            self.assertIn("transport_attempt", types)
            self.assertIn("transport_outcome", types)


class P13SafetySourceTests(unittest.TestCase):
    def test_boundary_source_has_no_network_or_credentials(self):
        text = Path(__file__).resolve().parents[1] / "src" / "comelit_safety_poc" / "p13_actuation_boundary.py"
        body = text.read_text(encoding="utf-8")
        for forbidden in ("socket.", "requests", "urllib", "asyncio.open_connection", "os.system", "Popen("):
            self.assertNotIn(forbidden, body)
        self.assertNotIn("physical_effect_asserted=True", body.replace("physical_effect_asserted: bool = False", ""))

    def test_audit_source_never_prints_credentials(self):
        text = Path(__file__).resolve().parents[1] / "src" / "comelit_safety_poc" / "audit.py"
        body = text.read_text(encoding="utf-8")
        self.assertNotIn("print(", body)
        self.assertNotIn("token", body.lower().replace("operation_id", ""))


if __name__ == "__main__":
    unittest.main()
