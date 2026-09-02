from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.ring_event import (
    CALL_INIT,
    DEVICE_TO_CLIENT,
    ENTRANCE,
    ENTRANCE_SOURCE,
    GATE,
    GATE_SOURCE,
    RingEvent,
    RingObservationError,
    parse_v4_safe_ring,
    parse_v4_safe_ring_text,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "ring_call_init_entrance.safe.txt"
)


def ring_text(
    *,
    observed: str = "true",
    direction: str = DEVICE_TO_CLIENT,
    kind: str = CALL_INIT,
    door: str = ENTRANCE,
    source: str = ENTRANCE_SOURCE,
) -> str:
    return "\n".join(
        (
            f"V4_RING_OBSERVED={observed}",
            f"V4_RING_DIRECTION={direction}",
            f"V4_RING_KIND={kind}",
            f"V4_RING_DOOR={door}",
            f"V4_RING_SOURCE={source}",
        )
    )


class RingEventTests(unittest.TestCase):

    def test_live_proven_entrance_fixture(self):
        event = parse_v4_safe_ring_text(
            FIXTURE.read_text(encoding="utf-8")
        )

        self.assertEqual(
            event,
            RingEvent(
                direction=DEVICE_TO_CLIENT,
                kind=CALL_INIT,
                door=ENTRANCE,
                source=ENTRANCE_SOURCE,
            ),
        )

    def test_no_ring_returns_none(self):
        self.assertIsNone(
            parse_v4_safe_ring_text(
                "V4_RING_OBSERVED=false\n"
            )
        )

    def test_absent_observed_marker_returns_none(self):
        self.assertIsNone(
            parse_v4_safe_ring(
                [
                    "V4_CTPP_REGISTRATION=PASS",
                    "V4_RING_LISTENER_READY=true",
                ]
            )
        )

    def test_gate_closed_mapping_is_accepted(self):
        event = parse_v4_safe_ring_text(
            ring_text(
                door=GATE,
                source=GATE_SOURCE,
            )
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.door, GATE)
        self.assertEqual(event.source, GATE_SOURCE)

    def test_unknown_source_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "unknown_ring_source",
        ):
            parse_v4_safe_ring_text(
                ring_text(
                    source="99999999",
                )
            )

    def test_source_door_mismatch_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "source_door_mismatch",
        ):
            parse_v4_safe_ring_text(
                ring_text(
                    door=GATE,
                    source=ENTRANCE_SOURCE,
                )
            )

    def test_client_to_device_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "unsupported_direction",
        ):
            parse_v4_safe_ring_text(
                ring_text(
                    direction="CLIENT_TO_DEVICE",
                )
            )

    def test_unknown_kind_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "unsupported_ring_kind",
        ):
            parse_v4_safe_ring_text(
                ring_text(
                    kind="UNKNOWN",
                )
            )

    def test_incomplete_observed_event_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "missing_markers",
        ):
            parse_v4_safe_ring_text(
                "\n".join(
                    (
                        "V4_RING_OBSERVED=true",
                        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
                    )
                )
            )

    def test_invalid_observed_value_fails_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "invalid_ring_observed_marker",
        ):
            parse_v4_safe_ring_text(
                ring_text(
                    observed="maybe",
                )
            )

    def test_conflicting_source_markers_fail_closed(self):
        with self.assertRaisesRegex(
            RingObservationError,
            "conflicting_marker:V4_RING_SOURCE",
        ):
            parse_v4_safe_ring_text(
                ring_text()
                + "\nV4_RING_SOURCE=00000610\n"
            )

    def test_unrelated_safe_markers_are_ignored(self):
        event = parse_v4_safe_ring_text(
            "ICE_CONNECTED=PASS\n"
            + ring_text()
            + "\nPHYSICAL_DOOR_ACTION=false\n"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.door, ENTRANCE)


if __name__ == "__main__":
    unittest.main()
