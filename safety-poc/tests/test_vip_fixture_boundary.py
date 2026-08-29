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
from comelit_safety_poc.vip_fixture_boundary import CanonicalVipFixtureBoundary


class VipFixtureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vip"
        pkg = self.root / "comelit_vip"
        pkg.mkdir(parents=True)
        self._write_fake_package(pkg, mode="ok")
        self.hashes = self._hashes()
        self.journal = Journal(Path(self.tmp.name) / "state.sqlite3")

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
        result = {}
        for path in sorted((self.root / "comelit_vip").glob("*.py")):
            result[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def _boundary(self):
        return CanonicalVipFixtureBoundary(vip_root=self.root, expected_hashes=self.hashes)

    def test_full_stack_fixture_write_maps_accepted_without_ack(self):
        boundary = self._boundary()
        evidence = boundary.attempt_once(TransportRequest("v3-one", "fixture-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.ACCEPTED_NO_ACK)
        self.assertFalse(evidence.protocol_acknowledged)
        self.assertFalse(evidence.physical_effect_asserted)
        self.assertEqual(boundary.last_snapshot.write_count, 1)
        self.assertEqual(
            boundary.last_snapshot.stack_types,
            ("FixtureTransport", "VipSession", "VipChannelSession", "VipApplicationSession"),
        )

    def test_executor_maps_fixture_write_to_unknown_outcome(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        op = executor.execute(operation_id="v3-exec", target="fixture-target")
        self.assertEqual(op.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(boundary.last_snapshot.write_count, 1)

    def test_duplicate_operation_id_does_not_write_twice(self):
        boundary = self._boundary()
        executor = OneShotExecutor(self.journal, BoundaryTransportAdapter(boundary), Policy(0))
        first = executor.execute(operation_id="v3-dup", target="fixture-target")
        second = executor.execute(operation_id="v3-dup", target="fixture-target")
        self.assertEqual(first.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(second.state, State.UNKNOWN_OUTCOME)
        self.assertEqual(boundary.calls, 1)
        self.assertEqual(boundary.last_snapshot.write_count, 1)

    def test_source_hash_mismatch_is_proven_not_sent(self):
        hashes = dict(self.hashes)
        key = sorted(hashes)[0]
        hashes[key] = "0" * 64
        boundary = CanonicalVipFixtureBoundary(vip_root=self.root, expected_hashes=hashes)
        evidence = boundary.attempt_once(TransportRequest("v3-hash", "fixture-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_failure_before_fixture_write_is_proven_not_sent(self):
        pkg = self.root / "comelit_vip"
        for name in list(sys.modules):
            if name == "comelit_vip" or name.startswith("comelit_vip."):
                del sys.modules[name]
        self._write_fake_package(pkg, mode="before_write")
        boundary = CanonicalVipFixtureBoundary(vip_root=self.root, expected_hashes=self._hashes())
        evidence = boundary.attempt_once(TransportRequest("v3-pre", "fixture-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.PROVEN_NOT_SENT)
        self.assertEqual(boundary.last_snapshot.write_count, 0)

    def test_failure_after_fixture_write_is_ambiguous(self):
        pkg = self.root / "comelit_vip"
        for name in list(sys.modules):
            if name == "comelit_vip" or name.startswith("comelit_vip."):
                del sys.modules[name]
        self._write_fake_package(pkg, mode="after_write")
        boundary = CanonicalVipFixtureBoundary(vip_root=self.root, expected_hashes=self._hashes())
        evidence = boundary.attempt_once(TransportRequest("v3-post", "fixture-target"))
        self.assertEqual(evidence.outcome, BoundaryOutcome.AMBIGUOUS)
        self.assertEqual(boundary.last_snapshot.write_count, 1)


if __name__ == "__main__":
    unittest.main()
