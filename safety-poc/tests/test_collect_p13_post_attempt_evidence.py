import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect_p13_post_attempt_evidence.py"


class P13PostAttemptCollectorTests(unittest.TestCase):
    def _load(self):
        spec = importlib.util.spec_from_file_location("collect_p13_post_attempt_evidence", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_public_safe_read_only_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "p13.sqlite3"
            audit = root / "audit.jsonl"
            live = root / "p13-live-run.log"
            op_id = "p13-hermes-test-op"

            con = sqlite3.connect(db)
            con.executescript(
                """
                CREATE TABLE operations (
                    operation_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    detail TEXT
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    detail TEXT
                );
                """
            )
            con.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?)",
                (op_id, "secret-target", "UNKNOWN_OUTCOME", "t0", "t1", "secret-detail"),
            )
            events = [
                (None, "PREPARED"),
                ("PREPARED", "SEND_ARMED"),
                ("SEND_ARMED", "SENT"),
                ("SENT", "UNKNOWN_OUTCOME"),
            ]
            for index, (src, dst) in enumerate(events):
                con.execute(
                    "INSERT INTO events(operation_id,ts,from_state,to_state,detail) VALUES(?,?,?,?,?)",
                    (op_id, f"t{index}", src, dst, "private-detail"),
                )
            con.commit()
            con.close()

            audit.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in (
                        {
                            "operation_id": op_id,
                            "event_type": "transport_attempt",
                            "attempt_number": 1,
                        },
                        {
                            "operation_id": op_id,
                            "event_type": "transport_outcome",
                            "attempt_number": 1,
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            live.write_text(
                "\n".join(
                    [
                        "P13_SIGNALING_HOLDER_BIND=PASS",
                        "P13_SIGNALING_WRAPPER_READY=true",
                        "P13_CTPP_OPEN_OUTCOME=OPENED",
                        "P13_DOOR_WRITE_COUNT=6",
                        "P13_CTPP_CLOSE=PASS",
                        "P13_TEARDOWN=PASS",
                        "P13_CTPP_OPEN_OUTCOME=OPENED",
                        "P13_DOOR_WRITE_COUNT=6",
                        "P13_CTPP_CLOSE=PASS",
                        "P13_TEARDOWN=PASS",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            physical = root / "p13-physical-test.log"
            physical.write_text(
                "\n".join(
                    [
                        "P13_HERMES_TRIGGER=ACCEPTED",
                        f"P13_HERMES_OPERATION_ID={op_id}",
                        "P13_ONE_SHOT_APPROVAL=GRANTED",
                        "P13_ONE_SHOT_PREFLIGHT=PASS",
                        "P13_ONE_SHOT_LAST_STEP=COMPLETE",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            module = self._load()
            argv = [
                str(SCRIPT),
                "--operation-id",
                op_id,
                "--db",
                str(db),
                "--audit",
                str(audit),
                "--live-log",
                str(live),
                "--physical-log-dir",
                str(root),
            ]
            out = io.StringIO()
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
                rc = module.main()

            text = out.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("P13_STATE=UNKNOWN_OUTCOME", text)
            self.assertIn("P13_AUDIT_TRANSPORT_ATTEMPT_COUNT=1", text)
            self.assertIn("P13_AUDIT_TRANSPORT_OUTCOME_COUNT=1", text)
            self.assertIn("P13_ONE_AUDITED_TRANSPORT_ATTEMPT=true", text)
            self.assertIn("P13_CTPP_OPENED_MARKER_COUNT=2", text)
            self.assertIn("P13_DOOR_WRITE_COUNT_6_MARKER_COUNT=2", text)
            self.assertIn("P13_PHYSICAL_OBSERVATION=UNAVAILABLE", text)
            self.assertIn("P13_DUPLICATE_TRANSMISSION_EVIDENCE=NOT_OBSERVED", text)
            self.assertNotIn("secret-target", text)
            self.assertNotIn("secret-detail", text)
            self.assertNotIn("private-detail", text)


if __name__ == "__main__":
    unittest.main()
