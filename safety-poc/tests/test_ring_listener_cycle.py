from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.ring_listener_cycle import (
    ListenerCycleError,
    ListenerCycleState,
    parse_listener_cycle_text,
)


def base(
    *,
    registered: str = "true",
    ready: str = "true",
    reset: str = "false",
    rc: str = "0",
) -> str:
    return "\n".join(
        (
            f"REGISTERED={registered}",
            f"LISTENER_READY={ready}",
            f"PSEUDOTCP_RESET={reset}",
            f"LAST_WRAPPER_RC={rc}",
        )
    )


class ListenerCycleTests(unittest.TestCase):

    def test_long_no_ring_cycle_is_ready_no_ring(self):
        cycle = parse_listener_cycle_text(
            base()
            + "\nV4_RING_OBSERVED=false\n"
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.READY_NO_RING,
        )
        self.assertIsNone(cycle.ring)
        self.assertFalse(cycle.should_emit_ring)
        self.assertTrue(cycle.reconnect_allowed)

    def test_proven_entrance_ring_is_emitted(self):
        cycle = parse_listener_cycle_text(
            base()
            + "\n"
            + "\n".join(
                (
                    "V4_RING_OBSERVED=true",
                    "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                    "V4_RING_KIND=CALL_INIT",
                    "V4_RING_DOOR=entrance",
                    "V4_RING_SOURCE=00000643",
                )
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.RING_OBSERVED,
        )
        self.assertIsNotNone(cycle.ring)
        self.assertEqual(cycle.ring.door, "entrance")
        self.assertTrue(cycle.should_emit_ring)
        self.assertTrue(cycle.reconnect_allowed)

    def test_pseudotcp_reset_is_explicit_reset_state(self):
        cycle = parse_listener_cycle_text(
            base(reset="true", rc="1")
            + "\nV4_RING_OBSERVED=false\n"
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.RESET,
        )
        self.assertTrue(cycle.reconnect_allowed)

    def test_nonzero_process_exit_is_failed(self):
        cycle = parse_listener_cycle_text(
            base(rc="1")
            + "\nV4_RING_OBSERVED=false\n"
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.FAILED,
        )
        self.assertTrue(cycle.reconnect_allowed)

    def test_not_ready_clean_exit_is_not_ready(self):
        cycle = parse_listener_cycle_text(
            base(
                registered="false",
                ready="false",
            )
            + "\nV4_RING_OBSERVED=false\n"
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.NOT_READY,
        )
        self.assertFalse(cycle.reconnect_allowed)

    def test_ready_without_registration_fails_closed(self):
        with self.assertRaisesRegex(
            ListenerCycleError,
            "ready_without_registration",
        ):
            parse_listener_cycle_text(
                base(
                    registered="false",
                    ready="true",
                )
                + "\nV4_RING_OBSERVED=false\n"
            )

    def test_ring_without_ready_listener_fails_closed(self):
        with self.assertRaisesRegex(
            ListenerCycleError,
            "ring_without_ready_listener",
        ):
            parse_listener_cycle_text(
                base(
                    registered="true",
                    ready="false",
                )
                + "\n"
                + "\n".join(
                    (
                        "V4_RING_OBSERVED=true",
                        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                        "V4_RING_KIND=CALL_INIT",
                        "V4_RING_DOOR=entrance",
                        "V4_RING_SOURCE=00000643",
                    )
                )
            )

    def test_missing_rc_fails_closed(self):
        with self.assertRaisesRegex(
            ListenerCycleError,
            "missing_wrapper_rc",
        ):
            parse_listener_cycle_text(
                "\n".join(
                    (
                        "REGISTERED=true",
                        "LISTENER_READY=true",
                        "PSEUDOTCP_RESET=false",
                        "V4_RING_OBSERVED=false",
                    )
                )
            )

    def test_missing_ring_observed_marker_fails_closed(self):
        with self.assertRaisesRegex(
            ListenerCycleError,
            "missing_markers:V4_RING_OBSERVED",
        ):
            parse_listener_cycle_text(
                "\n".join(
                    (
                        "REGISTERED=true",
                        "LISTENER_READY=true",
                        "PSEUDOTCP_RESET=false",
                        "LAST_WRAPPER_RC=0",
                    )
                )
            )

    def test_invalid_ring_is_wrapped_fail_closed(self):
        with self.assertRaisesRegex(
            ListenerCycleError,
            "invalid_ring:",
        ):
            parse_listener_cycle_text(
                base()
                + "\n"
                + "\n".join(
                    (
                        "V4_RING_OBSERVED=true",
                        "V4_RING_DIRECTION=CLIENT_TO_DEVICE",
                        "V4_RING_KIND=CALL_INIT",
                        "V4_RING_DOOR=entrance",
                        "V4_RING_SOURCE=00000643",
                    )
                )
            )

    def test_ring_then_reset_preserves_event_and_reconnects(self):
        cycle = parse_listener_cycle_text(
            base(reset="true", rc="1")
            + "\n"
            + "\n".join(
                (
                    "V4_RING_OBSERVED=true",
                    "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                    "V4_RING_KIND=CALL_INIT",
                    "V4_RING_DOOR=entrance",
                    "V4_RING_SOURCE=00000643",
                )
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.RESET,
        )
        self.assertTrue(cycle.should_emit_ring)
        self.assertEqual(cycle.ring.door, "entrance")
        self.assertTrue(cycle.reconnect_allowed)

    def test_ring_then_wrapper_failure_preserves_event_and_reconnects(self):
        cycle = parse_listener_cycle_text(
            base(rc="1")
            + "\n"
            + "\n".join(
                (
                    "V4_RING_OBSERVED=true",
                    "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                    "V4_RING_KIND=CALL_INIT",
                    "V4_RING_DOOR=entrance",
                    "V4_RING_SOURCE=00000643",
                )
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.FAILED,
        )
        self.assertTrue(cycle.should_emit_ring)
        self.assertEqual(cycle.ring.door, "entrance")
        self.assertTrue(cycle.reconnect_allowed)


if __name__ == "__main__":
    unittest.main()
