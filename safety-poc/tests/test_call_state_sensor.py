from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
if str(COMPONENT) not in sys.path:
    sys.path.insert(0, str(COMPONENT))

from call_state import (  # noqa: E402
    CALL_STATE_ERROR,
    CALL_STATE_IDLE,
    CALL_STATE_RINGING,
    CALL_STATES,
    ComelitCallStateTracker,
)


class CallStateTrackerTests(unittest.TestCase):
    def test_initial_state_is_idle(self) -> None:
        tracker = ComelitCallStateTracker()
        snapshot = tracker.snapshot()

        self.assertEqual(snapshot.state, CALL_STATE_IDLE)
        self.assertIsNone(snapshot.panel)
        self.assertIsNone(snapshot.event_id)
        self.assertIsNone(snapshot.started_at)
        self.assertFalse(snapshot.conversation_active)
        self.assertIsNone(snapshot.last_error)

    def test_begin_ring_preserves_only_safe_identity(self) -> None:
        tracker = ComelitCallStateTracker()

        changed = tracker.begin(
            panel="entrance",
            event_id="event-123",
            started_at="2026-09-24T19:00:00+00:00",
        )

        self.assertTrue(changed)
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.state, CALL_STATE_RINGING)
        self.assertEqual(snapshot.panel, "entrance")
        self.assertEqual(snapshot.event_id, "event-123")
        self.assertEqual(snapshot.started_at, "2026-09-24T19:00:00+00:00")
        self.assertFalse(snapshot.conversation_active)
        self.assertIsNone(snapshot.last_error)

    def test_gate_is_a_valid_call_panel(self) -> None:
        tracker = ComelitCallStateTracker()
        tracker.begin(
            panel="gate",
            event_id="gate-event",
            started_at="2026-09-24T19:00:00+00:00",
        )
        self.assertEqual(tracker.snapshot().panel, "gate")

    def test_invalid_panel_fails_closed(self) -> None:
        tracker = ComelitCallStateTracker()
        with self.assertRaisesRegex(ValueError, "unsupported_call_panel"):
            tracker.begin(
                panel="unknown",
                event_id="event",
                started_at="2026-09-24T19:00:00+00:00",
            )

    def test_remote_release_is_authoritative_terminal_boundary(self) -> None:
        tracker = ComelitCallStateTracker()
        tracker.begin(
            panel="entrance",
            event_id="event-123",
            started_at="2026-09-24T19:00:00+00:00",
        )

        self.assertTrue(tracker.remote_release())
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.state, CALL_STATE_IDLE)
        self.assertIsNone(snapshot.panel)
        self.assertIsNone(snapshot.event_id)
        self.assertIsNone(snapshot.started_at)

    def test_listener_failure_is_bounded_and_only_applies_to_active_call(self) -> None:
        tracker = ComelitCallStateTracker()
        self.assertFalse(tracker.fail_active("listener_failure"))

        tracker.begin(
            panel="entrance",
            event_id="event-123",
            started_at="2026-09-24T19:00:00+00:00",
        )
        self.assertTrue(tracker.fail_active("listener_failure"))
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.state, CALL_STATE_ERROR)
        self.assertEqual(snapshot.last_error, "listener_failure")

        with self.assertRaisesRegex(ValueError, "unsupported_call_error"):
            fresh = ComelitCallStateTracker()
            fresh.begin(
                panel="entrance",
                event_id="event-456",
                started_at="2026-09-24T19:00:00+00:00",
            )
            fresh.fail_active("raw_exception_text")

    def test_future_full_duplex_states_are_reserved_but_not_synthesized(self) -> None:
        self.assertEqual(
            CALL_STATES,
            (
                "idle",
                "ringing",
                "answering",
                "in_call",
                "ending",
                "error",
            ),
        )


class CallStateIntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (COMPONENT / "runtime.py").read_text(encoding="utf-8")
        cls.sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        cls.const = (COMPONENT / "const.py").read_text(encoding="utf-8")

    def test_runtime_begins_only_non_synthetic_ring_state(self) -> None:
        self.assertIn('event.get("synthetic") is not True', self.runtime)
        self.assertIn("self._call_state_tracker().begin(", self.runtime)

    def test_runtime_terminal_state_comes_from_remote_release_markers(self) -> None:
        for marker in (
            "R37_REMOTE_RELEASE_OBSERVED=true",
            "R64_POST_CALL_REMOTE_RELEASE_OBSERVED=true",
            "R64_TERMINAL_REMOTE_RELEASE_OBSERVED=true",
        ):
            self.assertIn(marker, self.runtime)
        self.assertIn("self._call_state_tracker().remote_release()", self.runtime)

    def test_media_close_does_not_end_call_state(self) -> None:
        close_block = self.runtime.split(
            'if line == "R42_MEDIA_CHANNEL_CLOSED=true":', 1
        )[1].split("continue", 1)[0]
        self.assertIn("self._attached_media_open.clear()", close_block)
        self.assertIn("self._notify_status()", close_block)
        self.assertNotIn("remote_release", close_block)
        self.assertNotIn("_call_state.reset", close_block)

    def test_no_frontend_or_runtime_wallclock_call_timeout(self) -> None:
        tracker = (COMPONENT / "call_state.py").read_text(encoding="utf-8")
        combined = tracker + "\n" + self.runtime
        self.assertNotIn("call_timeout", combined)
        self.assertNotIn("ring_timeout", combined)

    def test_sensor_identity_and_attributes_are_stable(self) -> None:
        self.assertIn('CALL_STATE_UNIQUE_ID = "comelit_call_state"', self.const)
        self.assertIn('CALL_STATE_ENTITY_ID = "sensor.comelit_call_state"', self.const)
        self.assertIn("class ComelitCallStateSensor", self.sensor)
        for attribute in (
            '"panel"',
            '"event_id"',
            '"started_at"',
            '"media_attached"',
            '"conversation_active"',
            '"last_error"',
        ):
            self.assertIn(attribute, self.sensor)


if __name__ == "__main__":
    unittest.main()
