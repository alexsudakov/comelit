from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.ring_listener_cycle import (
    ListenerCycleState,
)
from comelit_safety_poc.ring_process_result import (
    PassiveProcessResult,
    ProcessResultError,
    listener_cycle_from_process_result,
)


def safe_output(
    *,
    registered: str = "true",
    ready: str = "true",
    reset: str = "false",
    ring: bool = False,
) -> str:
    lines = [
        f"REGISTERED={registered}",
        f"LISTENER_READY={ready}",
        f"PSEUDOTCP_RESET={reset}",
    ]

    if ring:
        lines.extend(
            (
                "V4_RING_OBSERVED=true",
                "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                "V4_RING_KIND=CALL_INIT",
                "V4_RING_DOOR=entrance",
                "V4_RING_SOURCE=00000643",
            )
        )
    else:
        lines.append(
            "V4_RING_OBSERVED=false"
        )

    return "\n".join(lines)


class ProcessResultBoundaryTests(unittest.TestCase):

    def test_actual_zero_return_code_produces_ready_cycle(self):
        cycle = listener_cycle_from_process_result(
            PassiveProcessResult(
                return_code=0,
                safe_stdout=safe_output(),
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.READY_NO_RING,
        )
        self.assertEqual(cycle.return_code, 0)
        self.assertFalse(cycle.should_emit_ring)

    def test_actual_nonzero_return_code_controls_failed_state(self):
        cycle = listener_cycle_from_process_result(
            PassiveProcessResult(
                return_code=7,
                safe_stdout=safe_output(),
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.FAILED,
        )
        self.assertEqual(cycle.return_code, 7)
        self.assertTrue(cycle.reconnect_allowed)

    def test_ring_survives_actual_process_failure(self):
        cycle = listener_cycle_from_process_result(
            PassiveProcessResult(
                return_code=9,
                safe_stdout=safe_output(
                    ring=True,
                ),
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.FAILED,
        )
        self.assertTrue(cycle.should_emit_ring)
        self.assertIsNotNone(cycle.ring)
        self.assertEqual(
            cycle.ring.door,
            "entrance",
        )

    def test_reset_has_priority_over_nonzero_rc(self):
        cycle = listener_cycle_from_process_result(
            PassiveProcessResult(
                return_code=3,
                safe_stdout=safe_output(
                    reset="true",
                ),
            )
        )

        self.assertEqual(
            cycle.state,
            ListenerCycleState.RESET,
        )
        self.assertTrue(cycle.reconnect_allowed)

    def test_child_cannot_supply_matching_wrapper_rc(self):
        text = (
            safe_output()
            + "\nLAST_WRAPPER_RC=0\n"
        )

        with self.assertRaisesRegex(
            ProcessResultError,
            "child_supplied_wrapper_rc_forbidden",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=0,
                    safe_stdout=text,
                )
            )

    def test_child_cannot_spoof_different_wrapper_rc(self):
        text = (
            safe_output()
            + "\nLAST_WRAPPER_RC=0\n"
        )

        with self.assertRaisesRegex(
            ProcessResultError,
            "child_supplied_wrapper_rc_forbidden",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=17,
                    safe_stdout=text,
                )
            )

    def test_negative_signal_style_return_code_fails_closed(self):
        with self.assertRaisesRegex(
            ProcessResultError,
            "invalid_return_code",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=-15,
                    safe_stdout=safe_output(),
                )
            )

    def test_return_code_above_byte_range_fails_closed(self):
        with self.assertRaisesRegex(
            ProcessResultError,
            "invalid_return_code",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=256,
                    safe_stdout=safe_output(),
                )
            )

    def test_boolean_return_code_fails_closed(self):
        with self.assertRaisesRegex(
            ProcessResultError,
            "invalid_return_code",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=True,
                    safe_stdout=safe_output(),
                )
            )

    def test_incomplete_safe_output_fails_closed(self):
        with self.assertRaisesRegex(
            ProcessResultError,
            "invalid_listener_cycle:",
        ):
            listener_cycle_from_process_result(
                PassiveProcessResult(
                    return_code=0,
                    safe_stdout=(
                        "REGISTERED=true\n"
                        "LISTENER_READY=true\n"
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
