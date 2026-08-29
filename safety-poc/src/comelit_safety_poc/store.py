from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .model import Operation, State


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_ALLOWED = {
    State.PREPARED: {State.SEND_ARMED, State.FAILED_SAFE},
    State.SEND_ARMED: {State.SENT, State.FAILED_SAFE, State.UNKNOWN_OUTCOME},
    State.SENT: {State.ACKED, State.UNKNOWN_OUTCOME},
    State.ACKED: set(),
    State.FAILED_SAFE: set(),
    State.UNKNOWN_OUTCOME: set(),
}


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init(self) -> None:
        with closing(self._connect()) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    detail TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    detail TEXT,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ops_target_updated
                    ON operations(target, updated_at);
                """
            )

    @contextmanager
    def tx(self):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def create(self, operation_id: str, target: str, detail: str = "created") -> Operation:
        now = utc_now()
        with self.tx() as con:
            con.execute(
                "INSERT INTO operations(operation_id,target,state,created_at,updated_at,detail) VALUES(?,?,?,?,?,?)",
                (operation_id, target, State.PREPARED.value, now, now, detail),
            )
            con.execute(
                "INSERT INTO events(operation_id,ts,from_state,to_state,detail) VALUES(?,?,?,?,?)",
                (operation_id, now, None, State.PREPARED.value, detail),
            )
        return self.get(operation_id)

    def get(self, operation_id: str) -> Operation:
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return Operation(
            operation_id=row["operation_id"],
            target=row["target"],
            state=State(row["state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            detail=row["detail"],
        )

    def maybe_get(self, operation_id: str) -> Operation | None:
        try:
            return self.get(operation_id)
        except KeyError:
            return None

    def transition(self, operation_id: str, to_state: State, detail: str) -> Operation:
        now = utc_now()
        with self.tx() as con:
            row = con.execute(
                "SELECT state FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            from_state = State(row["state"])
            if to_state not in _ALLOWED[from_state]:
                raise ValueError(f"illegal transition {from_state.value}->{to_state.value}")
            con.execute(
                "UPDATE operations SET state=?,updated_at=?,detail=? WHERE operation_id=?",
                (to_state.value, now, detail, operation_id),
            )
            con.execute(
                "INSERT INTO events(operation_id,ts,from_state,to_state,detail) VALUES(?,?,?,?,?)",
                (operation_id, now, from_state.value, to_state.value, detail),
            )
        return self.get(operation_id)


    def arm_if_allowed(self, operation_id: str, min_interval_seconds: int) -> Operation:
        """Atomically enforce per-target exclusion/rate-limit and commit SEND_ARMED."""
        now = utc_now()
        now_dt = datetime.fromisoformat(now)
        with self.tx() as con:
            row = con.execute(
                "SELECT target,state FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            target = row["target"]
            from_state = State(row["state"])
            if from_state != State.PREPARED:
                raise ValueError(f"cannot arm from {from_state.value}")

            active = con.execute(
                """SELECT operation_id FROM operations
                   WHERE target=? AND operation_id<>? AND state IN (?,?)
                   LIMIT 1""",
                (target, operation_id, State.SEND_ARMED.value, State.SENT.value),
            ).fetchone()

            blocked_detail = None
            if active is not None:
                blocked_detail = "another operation for target is active: no send attempted"
            else:
                latest = con.execute(
                    """SELECT updated_at FROM operations
                       WHERE target=? AND operation_id<>? AND state IN (?,?,?)
                       ORDER BY updated_at DESC LIMIT 1""",
                    (
                        target,
                        operation_id,
                        State.ACKED.value,
                        State.FAILED_SAFE.value,
                        State.UNKNOWN_OUTCOME.value,
                    ),
                ).fetchone()
                if latest is not None:
                    age = (now_dt - datetime.fromisoformat(latest["updated_at"])).total_seconds()
                    if age < min_interval_seconds:
                        blocked_detail = "rate limit: no send attempted"

            to_state = State.FAILED_SAFE if blocked_detail else State.SEND_ARMED
            detail = blocked_detail or "uncertainty boundary committed before send"
            con.execute(
                "UPDATE operations SET state=?,updated_at=?,detail=? WHERE operation_id=?",
                (to_state.value, now, detail, operation_id),
            )
            con.execute(
                "INSERT INTO events(operation_id,ts,from_state,to_state,detail) VALUES(?,?,?,?,?)",
                (operation_id, now, from_state.value, to_state.value, detail),
            )
        return self.get(operation_id)

    def events(self, operation_id: str) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT ts,from_state,to_state,detail FROM events WHERE operation_id=? ORDER BY id",
                (operation_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def nonterminal(self) -> list[Operation]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT * FROM operations WHERE state IN (?,?,?) ORDER BY created_at",
                (State.PREPARED.value, State.SEND_ARMED.value, State.SENT.value),
            ).fetchall()
        return [
            Operation(
                operation_id=r["operation_id"], target=r["target"], state=State(r["state"]),
                created_at=r["created_at"], updated_at=r["updated_at"], detail=r["detail"]
            ) for r in rows
        ]

    def latest_terminal_for_target(self, target: str) -> Operation | None:
        with closing(self._connect()) as con:
            row = con.execute(
                """SELECT * FROM operations
                   WHERE target=? AND state IN (?,?,?)
                   ORDER BY updated_at DESC LIMIT 1""",
                (target, State.ACKED.value, State.FAILED_SAFE.value, State.UNKNOWN_OUTCOME.value),
            ).fetchone()
        if row is None:
            return None
        return Operation(
            operation_id=row["operation_id"], target=row["target"], state=State(row["state"]),
            created_at=row["created_at"], updated_at=row["updated_at"], detail=row["detail"]
        )
