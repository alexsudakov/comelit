from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DEVICE_TO_CLIENT = "DEVICE_TO_CLIENT"
CALL_INIT = "CALL_INIT"

ENTRANCE = "entrance"
GATE = "gate"

ENTRANCE_SOURCE = "00000643"
GATE_SOURCE = "00000610"

SOURCE_TO_DOOR = {
    ENTRANCE_SOURCE: ENTRANCE,
    GATE_SOURCE: GATE,
}

_RING_KEYS = {
    "V4_RING_OBSERVED",
    "V4_RING_DIRECTION",
    "V4_RING_KIND",
    "V4_RING_DOOR",
    "V4_RING_SOURCE",
}


class RingObservationError(ValueError):
    """Safe V4 ring markers violate the normalized contract."""


@dataclass(frozen=True)
class RingEvent:
    direction: str
    kind: str
    door: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "direction": self.direction,
            "kind": self.kind,
            "door": self.door,
            "source": self.source,
        }


def _extract_markers(lines: Iterable[str]) -> dict[str, str]:
    markers: dict[str, str] = {}

    for raw in lines:
        line = raw.strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key not in _RING_KEYS:
            continue

        value = value.strip()
        previous = markers.get(key)

        if previous is not None and previous != value:
            raise RingObservationError(f"conflicting_marker:{key}")

        markers[key] = value

    return markers


def parse_v4_safe_ring(lines: Iterable[str]) -> RingEvent | None:
    markers = _extract_markers(lines)

    observed = markers.get("V4_RING_OBSERVED")

    if observed is None or observed == "false":
        return None

    if observed != "true":
        raise RingObservationError("invalid_ring_observed_marker")

    required = (
        "V4_RING_DIRECTION",
        "V4_RING_KIND",
        "V4_RING_DOOR",
        "V4_RING_SOURCE",
    )

    missing = [key for key in required if not markers.get(key)]

    if missing:
        raise RingObservationError(
            "missing_markers:" + ",".join(missing)
        )

    direction = markers["V4_RING_DIRECTION"]
    kind = markers["V4_RING_KIND"]
    door = markers["V4_RING_DOOR"]
    source = markers["V4_RING_SOURCE"]

    if direction != DEVICE_TO_CLIENT:
        raise RingObservationError("unsupported_direction")

    if kind != CALL_INIT:
        raise RingObservationError("unsupported_ring_kind")

    expected_door = SOURCE_TO_DOOR.get(source)

    if expected_door is None:
        raise RingObservationError("unknown_ring_source")

    if door != expected_door:
        raise RingObservationError("source_door_mismatch")

    return RingEvent(
        direction=direction,
        kind=kind,
        door=door,
        source=source,
    )


def parse_v4_safe_ring_text(text: str) -> RingEvent | None:
    return parse_v4_safe_ring(text.splitlines())
