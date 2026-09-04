from __future__ import annotations

from dataclasses import dataclass

from .ring_listener_cycle import (
    ListenerCycle,
    ListenerCycleError,
    parse_listener_cycle,
)


class ProcessResultError(ValueError):
    """Process result cannot be trusted as a listener-cycle input."""


@dataclass(frozen=True)
class PassiveProcessResult:
    return_code: int
    safe_stdout: str


def _validate_return_code(return_code: int) -> None:
    if isinstance(return_code, bool):
        raise ProcessResultError(
            "invalid_return_code"
        )

    if not isinstance(return_code, int):
        raise ProcessResultError(
            "invalid_return_code"
        )

    if return_code < 0 or return_code > 255:
        raise ProcessResultError(
            "invalid_return_code"
        )


def listener_cycle_from_process_result(
    result: PassiveProcessResult,
) -> ListenerCycle:
    """
    Convert a passive listener process result to ListenerCycle.

    LAST_WRAPPER_RC is authority-owned here: it is derived from
    the actual process return code and may not be supplied by
    child stdout.
    """
    _validate_return_code(result.return_code)

    lines = result.safe_stdout.splitlines()

    for raw in lines:
        line = raw.strip()

        if not line.startswith("LAST_WRAPPER_RC="):
            continue

        raise ProcessResultError(
            "child_supplied_wrapper_rc_forbidden"
        )

    lines.append(
        f"LAST_WRAPPER_RC={result.return_code}"
    )

    try:
        return parse_listener_cycle(lines)
    except ListenerCycleError as exc:
        raise ProcessResultError(
            f"invalid_listener_cycle:{exc}"
        ) from exc
