from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .ring_event import RingEvent, RingObservationError, parse_v4_safe_ring


class ListenerCycleState(str, Enum):
    NOT_READY = "NOT_READY"
    READY_NO_RING = "READY_NO_RING"
    RING_OBSERVED = "RING_OBSERVED"
    RESET = "RESET"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ListenerCycle:
    state: ListenerCycleState
    registered: bool
    ready: bool
    pseudotcp_reset: bool
    return_code: int
    ring: RingEvent | None

    @property
    def should_emit_ring(self) -> bool:
        """A proven ring survives later listener/process failure."""
        return self.ring is not None

    @property
    def reconnect_allowed(self) -> bool:
        """Reconnect policy applies only to the passive listener lifecycle."""
        return self.state in {
            ListenerCycleState.READY_NO_RING,
            ListenerCycleState.RING_OBSERVED,
            ListenerCycleState.RESET,
            ListenerCycleState.FAILED,
        }


class ListenerCycleError(ValueError):
    """Safe listener result is structurally inconsistent."""


_SAFE_KEYS = {
    "REGISTERED",
    "LISTENER_READY",
    "PSEUDOTCP_RESET",
    "LAST_WRAPPER_RC",
    "V4_RING_OBSERVED",
    "V4_RING_DIRECTION",
    "V4_RING_KIND",
    "V4_RING_DOOR",
    "V4_RING_SOURCE",
}


def _markers(lines: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}

    for raw in lines:
        line = raw.strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key not in _SAFE_KEYS:
            continue

        value = value.strip()
        previous = result.get(key)

        if previous is not None and previous != value:
            raise ListenerCycleError(
                f"conflicting_marker:{key}"
            )

        result[key] = value

    return result


def _bool_marker(
    markers: dict[str, str],
    key: str,
    *,
    default: bool = False,
) -> bool:
    value = markers.get(key)

    if value is None:
        return default

    if value == "true":
        return True

    if value == "false":
        return False

    raise ListenerCycleError(
        f"invalid_boolean_marker:{key}"
    )


def parse_listener_cycle(lines: Iterable[str]) -> ListenerCycle:
    collected = list(lines)
    markers = _markers(collected)

    required_markers = (
        "REGISTERED",
        "LISTENER_READY",
        "PSEUDOTCP_RESET",
        "V4_RING_OBSERVED",
    )

    missing = [
        key
        for key in required_markers
        if key not in markers
    ]

    if missing:
        raise ListenerCycleError(
            "missing_markers:" + ",".join(missing)
        )

    registered = _bool_marker(
        markers,
        "REGISTERED",
    )
    ready = _bool_marker(
        markers,
        "LISTENER_READY",
    )
    reset = _bool_marker(
        markers,
        "PSEUDOTCP_RESET",
    )

    rc_text = markers.get("LAST_WRAPPER_RC")

    if rc_text is None:
        raise ListenerCycleError(
            "missing_wrapper_rc"
        )

    try:
        rc = int(rc_text, 10)
    except ValueError as exc:
        raise ListenerCycleError(
            "invalid_wrapper_rc"
        ) from exc

    if rc < 0 or rc > 255:
        raise ListenerCycleError(
            "invalid_wrapper_rc"
        )

    try:
        ring = parse_v4_safe_ring(collected)
    except RingObservationError as exc:
        raise ListenerCycleError(
            f"invalid_ring:{exc}"
        ) from exc

    if ready and not registered:
        raise ListenerCycleError(
            "ready_without_registration"
        )

    if ring is not None and not ready:
        raise ListenerCycleError(
            "ring_without_ready_listener"
        )

    if reset:
        state = ListenerCycleState.RESET
    elif rc != 0:
        state = ListenerCycleState.FAILED
    elif ring is not None:
        state = ListenerCycleState.RING_OBSERVED
    elif ready:
        state = ListenerCycleState.READY_NO_RING
    else:
        state = ListenerCycleState.NOT_READY

    return ListenerCycle(
        state=state,
        registered=registered,
        ready=ready,
        pseudotcp_reset=reset,
        return_code=rc,
        ring=ring,
    )


def parse_listener_cycle_text(text: str) -> ListenerCycle:
    return parse_listener_cycle(text.splitlines())
