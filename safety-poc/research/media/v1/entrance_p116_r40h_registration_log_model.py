"""P116 R40H -- offline, read-only reducer + freshness evaluator for the two existing production
logcat lines this round traced as load-bearing for registration freshness and transport liveness:

* `ComelitStatus.setEngineVipRegStatus` (dex7 `com.comelit.bigapp.application.ComelitStatus.java`,
  ~L209-215): `Log.i("ComelitStatus", "VIP REGISTER CHANGED " + old + " -> " + new)`.
* `ViperSocketReaderRunnable.setReconnecting` (dex7
  `com.comelit.bigapp.viper.ViperSocketReaderRunnable.java`): `Log.e("ViperSocketReaderRun",
  "VIPER SOCKET CONNECTION LOST")`, reachable only when the read loop was NOT stopped deliberately
  (`stopRequest` is checked first), and always followed in the same call by
  `ComelitStatus.setEngineViperStatus(CLOSED)` + `setEngineVipRegStatus(NOT_REGISTERED)`.

Design constraint (round instruction: never store a full logcat line). `reduce_raw_line` is a pure
function that extracts exactly `{source, from_state, to_state}` (VIP_REGISTER_TRANSITION) or `{source}`
(VIPER_TRANSPORT_FAILURE) from a line matching one of the two known-safe formats above, or returns
`None` for anything else. The original tag/message strings are never retained past this one call, and
no other field of the line (timestamp text, PID, raw casing, extra whitespace) is captured.

Sends no packet, opens no socket, invokes no subprocess/adb -- `import subprocess` does not appear in
this file. A future live reader is expected to pipe
`adb logcat -v time -T "<PRE_PAUSE_LOG_CURSOR>" -s ComelitStatus:I ViperSocketReaderRun:E` output, line
by line, through `reduce_raw_line`, assign each accepted event a monotonically increasing
`monotonic_seq` (its position in that filtered stream), and pass the resulting list plus the cursor
value to `evaluate_fresh_registration`. That adb plumbing is out of scope for `RESEARCH_OFFLINE` and is
not implemented here -- only the safe, pure reduction/evaluation logic is.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Optional, Sequence


class RegisterStatus(enum.Enum):
    """Mirrors `com.comelit.bigapp.application.ComelitStatus$RegisterStatus` exactly (R40F/R40G
    cited; re-confirmed this round at `ComelitStatus.java` L51-56)."""

    NONE = "NONE"
    NOT_REGISTERED = "NOT_REGISTERED"
    REGISTERING = "REGISTERING"
    REGISTERED = "REGISTERED"


class LogEventSource(enum.Enum):
    VIP_REGISTER_TRANSITION = "vip_register_transition"
    VIPER_TRANSPORT_FAILURE = "viper_transport_failure"


_STATE_ALTERNATION = "NONE|NOT_REGISTERED|REGISTERING|REGISTERED"
_VIP_REGISTER_RE = re.compile(
    rf"^VIP REGISTER CHANGED ({_STATE_ALTERNATION}) -> ({_STATE_ALTERNATION})$"
)
_VIPER_TRANSPORT_FAILURE_MARKER = "VIPER SOCKET CONNECTION LOST"


@dataclass(frozen=True)
class ReducedLogEvent:
    source: LogEventSource
    monotonic_seq: int
    from_state: Optional[RegisterStatus] = None
    to_state: Optional[RegisterStatus] = None


def reduce_raw_line(tag: str, message: str, monotonic_seq: int) -> Optional[ReducedLogEvent]:
    """Reduce one already-tag-labelled logcat line to a safe enum/int tuple, or `None` if it does not
    match one of the two known-safe production formats this round cited. Non-matching input
    (including any line from a tag other than the two below) is discarded, never stored -- this
    function is safe to call on an unfiltered stream even though a real reader is expected to filter
    with `-s ComelitStatus:I ViperSocketReaderRun:E` at the source already."""

    if tag == "ComelitStatus":
        m = _VIP_REGISTER_RE.match(message.strip())
        if not m:
            return None
        return ReducedLogEvent(
            source=LogEventSource.VIP_REGISTER_TRANSITION,
            monotonic_seq=monotonic_seq,
            from_state=RegisterStatus(m.group(1)),
            to_state=RegisterStatus(m.group(2)),
        )
    if tag == "ViperSocketReaderRun":
        if _VIPER_TRANSPORT_FAILURE_MARKER in message:
            return ReducedLogEvent(source=LogEventSource.VIPER_TRANSPORT_FAILURE, monotonic_seq=monotonic_seq)
        return None
    return None


@dataclass(frozen=True)
class FreshRegistrationVerdict:
    fresh_registered_transition_seen: bool
    transition_monotonic_seq: Optional[int]
    transport_failure_after_transition: bool
    registration_ready_fresh_scalar: bool
    attempt_generation: int
    reason: str


def evaluate_fresh_registration(
    events: Sequence[ReducedLogEvent], pre_pause_log_cursor: int
) -> FreshRegistrationVerdict:
    """R40H CHILD A/B/F.

    Only events with `monotonic_seq > pre_pause_log_cursor` count -- anything at or before the cursor
    is old-attempt evidence and is ignored entirely, never merely down-weighted.

    Per R40H's source-level proof (`ComelitStatus.setEngineVipRegStatus`'s `if (registerStatus !=
    status)` guard around the `Log.i` call, `ComelitStatus.java` ~L209-215): production code can only
    ever emit a "VIP REGISTER CHANGED X -> REGISTERED" line when `X != REGISTERED` -- so any such line
    after the cursor is, by construction, proof of a real transition, never a re-assertion of an
    already-REGISTERED value. This function still requires `from_state != REGISTERED` as a second,
    redundant check rather than trusting that guarantee blindly.

    A later `VIPER_TRANSPORT_FAILURE` event (only reachable on an undeliberate transport failure, and
    always followed by `setEngineVipRegStatus(NOT_REGISTERED)` in the same call -- R40H CHILD E/F)
    poisons a prior fresh claim: the transport was flagged dead by a different tag/thread than
    `ComelitStatus.regStatus` itself, which is the independent-liveness corroboration R40G could not
    find. An explicit `REGISTERED -> non-REGISTERED` transition line does the same.
    """

    post_cursor = sorted(
        (e for e in events if e.monotonic_seq > pre_pause_log_cursor), key=lambda e: e.monotonic_seq
    )

    last_fresh_seq: Optional[int] = None
    generation = 0
    for event in post_cursor:
        if event.source is LogEventSource.VIP_REGISTER_TRANSITION:
            if event.to_state is RegisterStatus.REGISTERED and event.from_state is not RegisterStatus.REGISTERED:
                last_fresh_seq = event.monotonic_seq
                generation += 1
            elif event.from_state is RegisterStatus.REGISTERED and event.to_state is not RegisterStatus.REGISTERED:
                last_fresh_seq = None
        elif event.source is LogEventSource.VIPER_TRANSPORT_FAILURE:
            last_fresh_seq = None

    if last_fresh_seq is None:
        transport_failure_after = any(
            e.source is LogEventSource.VIPER_TRANSPORT_FAILURE for e in post_cursor
        )
        return FreshRegistrationVerdict(
            fresh_registered_transition_seen=False,
            transition_monotonic_seq=None,
            transport_failure_after_transition=transport_failure_after,
            registration_ready_fresh_scalar=False,
            attempt_generation=generation,
            reason="no_uninvalidated_fresh_registered_transition_after_cursor",
        )

    # last_fresh_seq is only ever set (and left set) when no invalidating event followed it -- see
    # the loop above, where both invalidation branches immediately clear it back to None.
    return FreshRegistrationVerdict(
        fresh_registered_transition_seen=True,
        transition_monotonic_seq=last_fresh_seq,
        transport_failure_after_transition=False,
        registration_ready_fresh_scalar=True,
        attempt_generation=generation,
        reason="fresh_registered_transition_after_cursor_not_since_contradicted",
    )
