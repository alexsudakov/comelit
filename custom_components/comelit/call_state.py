from __future__ import annotations

from dataclasses import dataclass

CALL_STATE_IDLE = "idle"
CALL_STATE_RINGING = "ringing"
CALL_STATE_ANSWERING = "answering"
CALL_STATE_IN_CALL = "in_call"
CALL_STATE_ENDING = "ending"
CALL_STATE_ERROR = "error"

CALL_STATES = (
    CALL_STATE_IDLE,
    CALL_STATE_RINGING,
    CALL_STATE_ANSWERING,
    CALL_STATE_IN_CALL,
    CALL_STATE_ENDING,
    CALL_STATE_ERROR,
)

_ACTIVE_CALL_STATES = frozenset(
    {
        CALL_STATE_RINGING,
        CALL_STATE_ANSWERING,
        CALL_STATE_IN_CALL,
        CALL_STATE_ENDING,
    }
)

_ALLOWED_PANELS = frozenset({"entrance", "gate"})
_ALLOWED_ERRORS = frozenset(
    {
        "listener_failure",
        "listener_stopped_during_call",
    }
)


@dataclass(frozen=True)
class CallStateSnapshot:
    state: str
    panel: str | None
    event_id: str | None
    started_at: str | None
    conversation_active: bool
    last_error: str | None


class ComelitCallStateTracker:
    """Pure in-memory call lifecycle derived only from bounded runtime evidence."""

    def __init__(self) -> None:
        self._state = CALL_STATE_IDLE
        self._panel: str | None = None
        self._event_id: str | None = None
        self._started_at: str | None = None
        self._conversation_active = False
        self._last_error: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def active(self) -> bool:
        return self._state in _ACTIVE_CALL_STATES

    def snapshot(self) -> CallStateSnapshot:
        return CallStateSnapshot(
            state=self._state,
            panel=self._panel,
            event_id=self._event_id,
            started_at=self._started_at,
            conversation_active=self._conversation_active,
            last_error=self._last_error,
        )

    def reset(self) -> bool:
        changed = self.snapshot() != CallStateSnapshot(
            state=CALL_STATE_IDLE,
            panel=None,
            event_id=None,
            started_at=None,
            conversation_active=False,
            last_error=None,
        )
        self._state = CALL_STATE_IDLE
        self._panel = None
        self._event_id = None
        self._started_at = None
        self._conversation_active = False
        self._last_error = None
        return changed

    def begin(self, *, panel: str, event_id: str, started_at: str) -> bool:
        if panel not in _ALLOWED_PANELS:
            raise ValueError("unsupported_call_panel")
        if not event_id:
            raise ValueError("missing_call_event_id")
        if not started_at:
            raise ValueError("missing_call_started_at")

        next_snapshot = CallStateSnapshot(
            state=CALL_STATE_RINGING,
            panel=panel,
            event_id=event_id,
            started_at=started_at,
            conversation_active=False,
            last_error=None,
        )
        changed = self.snapshot() != next_snapshot
        self._state = next_snapshot.state
        self._panel = next_snapshot.panel
        self._event_id = next_snapshot.event_id
        self._started_at = next_snapshot.started_at
        self._conversation_active = next_snapshot.conversation_active
        self._last_error = next_snapshot.last_error
        return changed

    def remote_release(self) -> bool:
        """End only from a backend-observed remote release boundary."""
        return self.reset()

    def fail_active(self, reason: str) -> bool:
        if not self.active:
            return False
        if reason not in _ALLOWED_ERRORS:
            raise ValueError("unsupported_call_error")

        next_snapshot = CallStateSnapshot(
            state=CALL_STATE_ERROR,
            panel=self._panel,
            event_id=self._event_id,
            started_at=self._started_at,
            conversation_active=False,
            last_error=reason,
        )
        changed = self.snapshot() != next_snapshot
        self._state = next_snapshot.state
        self._conversation_active = False
        self._last_error = reason
        return changed
