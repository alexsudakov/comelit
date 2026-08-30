import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.boundary import (
    BoundaryOutcome,
    BoundaryTransportAdapter,
    TransportRequest,
)
from comelit_safety_poc.ct120_real_session import Ct120ArtifactSpec, Ct120RealP13Session
from comelit_safety_poc.p13_actuation_boundary import (
    CtppOpenOutcome,
    P13PayloadBundle,
    RealDoorActuationBoundary,
)


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
        write_sha256=tuple(hashlib.sha256(b).hexdigest() for b in bodies),
        write_bytes=tuple(len(b) for b in bodies),
    )


class DictBodyLoader:
    def __init__(self, bodies):
        self.bodies = bodies

    def load(self, index: int) -> str:
        return self.bodies[index].hex()


def write_wrapper(path: Path, marker_body: str) -> None:
    """A fake native wrapper that prints a fixed typed marker payload."""
    script = f"""#!/bin/sh
printf '%s\\n' 'P13_CTPP_OPEN_OUTCOME={marker_body}'
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)


def write_wrapper_count(path: Path, open_outcome: str, count: int, close: str = "PASS", teardown: str | None = "PASS", exit_code: int = 0) -> None:
    lines = [f"#!/bin/sh\nprintf '%s\\n' 'P13_CTPP_OPEN_OUTCOME={open_outcome}'"]
    lines.append(f"printf '%s\\n' 'P13_DOOR_WRITE_COUNT={count}'")
    lines.append(f"printf '%s\\n' 'P13_CTPP_CLOSE={close}'")
    if teardown is not None:
        lines.append(f"printf '%s\\n' 'P13_TEARDOWN={teardown}'")
    lines.append(f"exit {exit_code}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o700)


class Ct120RealSessionTests(unittest.TestCase):
    def _spec(self, tmp: Path, wrapper: Path, payload: Path) -> Ct120ArtifactSpec:
        return Ct120ArtifactSpec(
            wrapper=wrapper,
            wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            payload_file=payload,
            require_root_owner=False,
        )

    def _payload(self, tmp: Path) -> Path:
        import json

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
                {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                for b in bodies
            ],
        }
        path = tmp / "payloads.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def _bodies(self):
        return [bytes([i + 1]) * 12 for i in range(6)]

    def test_dry_initialize_requires_exact_wrapper_hash(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper(wrapper, "OPENED")
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            markers = session.dry_initialize()
            self.assertEqual(markers["P13_REAL_ADAPTER_CONSTRUCTED"], "true")

            bad_spec = Ct120ArtifactSpec(
                wrapper=wrapper,
                wrapper_sha256="0" * 64,
                payload_file=payload,
                require_root_owner=False,
            )
            with self.assertRaises(ValueError):
                Ct120RealP13Session(bad_spec, make_bundle(), dry_init=True)

    def test_wrapper_absent_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = self._payload(tmp)
            spec = Ct120ArtifactSpec(
                wrapper=tmp / "missing-wrapper",
                wrapper_sha256="0" * 64,
                payload_file=payload,
                require_root_owner=False,
            )
            with self.assertRaises(FileNotFoundError):
                Ct120RealP13Session(spec, make_bundle(), dry_init=True)

    def test_successful_open_maps_to_opened_and_six_writes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "OPENED", 6)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            boundary = RealDoorActuationBoundary(
                session, make_bundle(), body_loader=DictBodyLoader(self._bodies())
            )
            evidence = boundary.attempt_once(TransportRequest(operation_id="op-r1", target="f" * 64))
            self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
            self.assertEqual(session._open_outcome, CtppOpenOutcome.OPENED)
            self.assertTrue(session._teardown_ok)

    def test_ambiguous_open_marker_is_never_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "AMBIGUOUS", 0)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            outcome = session.open_ctpp()
            self.assertEqual(outcome, CtppOpenOutcome.AMBIGUOUS)

    def test_proven_not_opened_marker_is_proven_not_sent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "PROVEN_NOT_OPENED", 0)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            outcome = session.open_ctpp()
            self.assertEqual(outcome, CtppOpenOutcome.PROVEN_NOT_OPENED)

    def test_missing_open_marker_is_conservative_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "", 0)
            wrapper.write_text("#!/bin/sh\nprintf '%s\\n' 'P13_DOOR_WRITE_COUNT=0'\n", encoding="utf-8")
            wrapper.chmod(0o700)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            outcome = session.open_ctpp()
            self.assertEqual(outcome, CtppOpenOutcome.AMBIGUOUS)

    def test_second_open_invocation_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "OPENED", 6)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            session.open_ctpp()
            with self.assertRaises(AssertionError):
                session.open_ctpp()

    def test_partial_write_count_via_boundary_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            write_wrapper_count(wrapper, "OPENED", 3)
            payload = self._payload(tmp)
            spec = self._spec(tmp, wrapper, payload)
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            boundary = RealDoorActuationBoundary(
                session, make_bundle(), body_loader=DictBodyLoader(self._bodies())
            )
            evidence = boundary.attempt_once(TransportRequest(operation_id="op-r2", target="f" * 64))
            self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)


class Ct120ReportConsistencyTests(unittest.TestCase):
    """Blocker 3/4/5: wrapper result must be one consistent transaction report."""

    def _make(self, tmp: Path, open_outcome: str, count: int, close: str = "PASS",
              teardown: str | None = "PASS", exit_code: int = 0, run_dir: Path | None = None):
        wrapper = tmp / "wrapper"
        write_wrapper_count(wrapper, open_outcome, count, close, teardown, exit_code)
        payload = tmp / "payloads.json"
        import json
        bodies = [bytes([i + 1]) * 12 for i in range(6)]
        payload.write_text(json.dumps({
            "schema": 1,
            "ucfg_sha256": "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
            "target_index": 0,
            "target_fingerprint": "f" * 64,
            "target_name": "FixtureDoor",
            "channel_id_fixture": 7449,
            "write_count": 6,
            "bodies": [
                {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                for b in bodies
            ],
        }), encoding="utf-8")
        os.chmod(payload, 0o600)
        spec = Ct120ArtifactSpec(
            wrapper=wrapper,
            wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            payload_file=payload,
            require_root_owner=False,
        )
        run_dir = run_dir or (tmp / "run")
        session = Ct120RealP13Session(spec, make_bundle(), run_dir=run_dir)
        return session

    def _bodies(self):
        return [bytes([i + 1]) * 12 for i in range(6)]

    def test_missing_teardown_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 6, close="PASS", teardown=None)
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_failed_teardown_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 6, close="PASS", teardown="FAIL")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_six_writes_missing_close_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 6, close="FAIL", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_six_writes_no_close_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            wrapper.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'P13_CTPP_OPEN_OUTCOME=OPENED'\n"
                "printf '%s\\n' 'P13_DOOR_WRITE_COUNT=6'\n"
                "printf '%s\\n' 'P13_TEARDOWN=PASS'\n"
                "exit 0\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o700)
            payload = tmp / "payloads.json"
            import json
            bodies = [bytes([i + 1]) * 12 for i in range(6)]
            payload.write_text(json.dumps({
                "schema": 1,
                "ucfg_sha256": "d31dca0f" + "0" * 56,
                "target_index": 0,
                "target_fingerprint": "f" * 64,
                "target_name": "FixtureDoor",
                "channel_id_fixture": 7449,
                "write_count": 6,
                "bodies": [
                    {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                    for b in bodies
                ],
            }), encoding="utf-8")
            os.chmod(payload, 0o600)
            spec = Ct120ArtifactSpec(
                wrapper=wrapper,
                wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                payload_file=payload,
                require_root_owner=False,
            )
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_proven_not_opened_with_writes_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "PROVEN_NOT_OPENED", 3, close="PASS", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_rejected_with_writes_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "REJECTED", 1, close="PASS", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_opened_partial_writes_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 3, close="PASS", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_invalid_open_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "BOGUS", 6, close="PASS", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_missing_open_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            wrapper.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'P13_DOOR_WRITE_COUNT=6'\n"
                "exit 0\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o700)
            payload = tmp / "payloads.json"
            import json
            bodies = [bytes([i + 1]) * 12 for i in range(6)]
            payload.write_text(json.dumps({
                "schema": 1,
                "ucfg_sha256": "d31dca0f" + "0" * 56,
                "target_index": 0,
                "target_fingerprint": "f" * 64,
                "target_name": "FixtureDoor",
                "channel_id_fixture": 7449,
                "write_count": 6,
                "bodies": [
                    {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                    for b in bodies
                ],
            }), encoding="utf-8")
            os.chmod(payload, 0o600)
            spec = Ct120ArtifactSpec(
                wrapper=wrapper,
                wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                payload_file=payload,
                require_root_owner=False,
            )
            session = Ct120RealP13Session(spec, make_bundle(), run_dir=tmp / "run")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_nonzero_exit_is_ambiguous_even_with_complete_markers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 6, close="PASS", teardown="PASS", exit_code=3)
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)

    def test_proven_not_opened_with_zero_writes_and_clean_exit_is_proven_not_sent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "PROVEN_NOT_OPENED", 0, close="PASS", teardown="PASS")
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.PROVEN_NOT_OPENED)
            self.assertTrue(session._report_valid)

    def test_timeout_wrapper_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrapper = tmp / "wrapper"
            wrapper.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
            wrapper.chmod(0o700)
            payload = tmp / "payloads.json"
            import json
            bodies = [bytes([i + 1]) * 12 for i in range(6)]
            payload.write_text(json.dumps({
                "schema": 1,
                "ucfg_sha256": "d31dca0f" + "0" * 56,
                "target_index": 0,
                "target_fingerprint": "f" * 64,
                "target_name": "FixtureDoor",
                "channel_id_fixture": 7449,
                "write_count": 6,
                "bodies": [
                    {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                    for b in bodies
                ],
            }), encoding="utf-8")
            os.chmod(payload, 0o600)
            spec = Ct120ArtifactSpec(
                wrapper=wrapper,
                wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                payload_file=payload,
                require_root_owner=False,
            )
            session = Ct120RealP13Session(
                spec, make_bundle(), run_dir=tmp / "run",
                timeout_seconds=0.2, term_grace_seconds=0.2,
            )
            self.assertEqual(session.open_ctpp(), CtppOpenOutcome.AMBIGUOUS)
            self.assertTrue(session._timeout_observed)

    def test_teardown_never_synthesized_by_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            session = self._make(tmp, "OPENED", 6, close="PASS", teardown=None)
            session.open_ctpp()
            self.assertFalse(session.teardown())

    def test_ownership_checks_fail_closed(self):
        class SyntheticNonRootArtifact:
            def __init__(self, content: bytes):
                self._content = content

            def is_file(self):
                return True

            def read_bytes(self):
                return self._content

            def stat(self):
                class S:
                    st_mode = stat.S_IFREG | 0o700
                    st_uid = 12345
                return S()

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = tmp / "payloads.json"
            payload.write_text('{"bodies": []}', encoding="utf-8")
            os.chmod(payload, 0o600)
            wrapper = SyntheticNonRootArtifact(b"synthetic-wrapper")
            spec = Ct120ArtifactSpec(
                wrapper=wrapper,
                wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                payload_file=payload,
                require_root_owner=True,
            )
            with self.assertRaises(ValueError):
                Ct120RealP13Session(spec, make_bundle(), dry_init=True)


if __name__ == "__main__":
    unittest.main()
