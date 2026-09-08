#!/usr/bin/env python3
"""Pure classifier for COMELIT-P79 cloud-only listener concurrency evidence."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Mapping, Sequence


SAFE_MARKER_KEY_RE = re.compile(r"^[A-Z0-9_]{1,80}$")
SAFE_MARKER_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/,+@=-]{0,160}$")

RUN_RESULT_TO_PROCESS_RC = {
    "PASS": 0,
    "PARTIAL": 1,
    "INCONCLUSIVE_TRANSIENT_TIMEOUT": 1,
    "INCONCLUSIVE": 1,
    "FAIL": 1,
    "UNKNOWN_OUTCOME": 1,
    "BLOCKED": 2,
}


@dataclass(frozen=True)
class Classification:
    """Итоговая P79 классификация без live side effects."""

    P79_CLOUD_CONCURRENCY: str
    P79_LISTENER_STABILITY: str
    P79_TIMEOUT_RECONNECT_ASSOCIATION: str
    P79_RUN_RESULT: str
    process_rc: int

    def as_markers(self) -> dict[str, str]:
        return {
            "P79_CLOUD_CONCURRENCY": self.P79_CLOUD_CONCURRENCY,
            "P79_LISTENER_STABILITY": self.P79_LISTENER_STABILITY,
            "P79_TIMEOUT_RECONNECT_ASSOCIATION": (
                self.P79_TIMEOUT_RECONNECT_ASSOCIATION
            ),
            "P79_RUN_RESULT": self.P79_RUN_RESULT,
            "P79_PROCESS_RC": str(self.process_rc),
        }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sample_running(sample: Mapping[str, Any]) -> bool:
    return _as_bool(sample.get("supervisor_running")) and _as_bool(
        sample.get("running")
    )


def _sample_ready(sample: Mapping[str, Any]) -> bool:
    return _as_bool(sample.get("listener_ready"))


def reconnect_count_changed(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> bool | None:
    if before is None or after is None:
        return None
    before_count = _as_int(before.get("reconnect_count"))
    after_count = _as_int(after.get("reconnect_count"))
    if before_count is None or after_count is None:
        return None
    return after_count != before_count


def listener_remained_running(samples: Sequence[Mapping[str, Any]]) -> bool:
    return bool(samples) and all(_sample_running(sample) for sample in samples)


def listener_ready_returned_or_stayed(samples: Sequence[Mapping[str, Any]]) -> bool:
    if not samples:
        return False
    return _sample_ready(samples[-1])


def classify(
    *,
    p2p_result: str | None,
    remote_sdp_present: bool | str | None,
    listener_samples: Sequence[Mapping[str, Any]],
    preflight_blocked: bool = False,
    terminal_marker_present: bool = True,
) -> Classification:
    """Map cloud outcome and listener samples onto the P79 A-E contract."""

    if preflight_blocked:
        return Classification(
            P79_CLOUD_CONCURRENCY="BLOCKED",
            P79_LISTENER_STABILITY="NOT_EVALUATED",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
            P79_RUN_RESULT="BLOCKED",
            process_rc=RUN_RESULT_TO_PROCESS_RC["BLOCKED"],
        )

    if not terminal_marker_present or p2p_result is None:
        return Classification(
            P79_CLOUD_CONCURRENCY="UNKNOWN",
            P79_LISTENER_STABILITY="UNKNOWN",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
            P79_RUN_RESULT="UNKNOWN_OUTCOME",
            process_rc=RUN_RESULT_TO_PROCESS_RC["UNKNOWN_OUTCOME"],
        )

    before = listener_samples[0] if listener_samples else None
    after = listener_samples[-1] if listener_samples else None
    reconnect_changed = reconnect_count_changed(before, after)
    remained_running = listener_remained_running(listener_samples)
    ready_returned = listener_ready_returned_or_stayed(listener_samples)
    normalized_result = p2p_result.strip().upper()
    has_remote_sdp = _as_bool(remote_sdp_present)

    if normalized_result == "SUCCESS" and has_remote_sdp:
        if remained_running and reconnect_changed is False and ready_returned:
            return Classification(
                P79_CLOUD_CONCURRENCY="PROVEN",
                P79_LISTENER_STABILITY="PROVEN",
                P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_APPLICABLE",
                P79_RUN_RESULT="PASS",
                process_rc=RUN_RESULT_TO_PROCESS_RC["PASS"],
            )
        return Classification(
            P79_CLOUD_CONCURRENCY="PARTIAL",
            P79_LISTENER_STABILITY="NOT_PROVEN",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_APPLICABLE",
            P79_RUN_RESULT="PARTIAL",
            process_rc=RUN_RESULT_TO_PROCESS_RC["PARTIAL"],
        )

    if normalized_result == "TIMEOUT":
        if reconnect_changed is False:
            return Classification(
                P79_CLOUD_CONCURRENCY="INCONCLUSIVE_TRANSIENT_TIMEOUT",
                P79_LISTENER_STABILITY=(
                    "PROVEN" if remained_running and ready_returned else "NOT_PROVEN"
                ),
                P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_OBSERVED",
                P79_RUN_RESULT="INCONCLUSIVE_TRANSIENT_TIMEOUT",
                process_rc=RUN_RESULT_TO_PROCESS_RC[
                    "INCONCLUSIVE_TRANSIENT_TIMEOUT"
                ],
            )
        if reconnect_changed is True:
            return Classification(
                P79_CLOUD_CONCURRENCY="INCONCLUSIVE",
                P79_LISTENER_STABILITY="NOT_PROVEN",
                P79_TIMEOUT_RECONNECT_ASSOCIATION="OBSERVED",
                P79_RUN_RESULT="INCONCLUSIVE",
                process_rc=RUN_RESULT_TO_PROCESS_RC["INCONCLUSIVE"],
            )

    if normalized_result == "FAIL":
        return Classification(
            P79_CLOUD_CONCURRENCY="FAIL",
            P79_LISTENER_STABILITY="NOT_PROVEN",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
            P79_RUN_RESULT="FAIL",
            process_rc=RUN_RESULT_TO_PROCESS_RC["FAIL"],
        )

    return Classification(
        P79_CLOUD_CONCURRENCY="UNKNOWN",
        P79_LISTENER_STABILITY="UNKNOWN",
        P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
        P79_RUN_RESULT="UNKNOWN_OUTCOME",
        process_rc=RUN_RESULT_TO_PROCESS_RC["UNKNOWN_OUTCOME"],
    )


def sanitize_marker(key: str, value: object) -> tuple[str, str]:
    safe_key = key if SAFE_MARKER_KEY_RE.fullmatch(key) else "UNSAFE_MARKER_KEY"
    text = str(value)
    safe_value = text if SAFE_MARKER_VALUE_RE.fullmatch(text) else "<redacted>"
    return safe_key, safe_value


def marker_line(key: str, value: object) -> str:
    safe_key, safe_value = sanitize_marker(key, value)
    return f"{safe_key}={safe_value}"


def marker_summary(markers: Sequence[str]) -> dict[str, str]:
    joined = "\n".join(markers).encode("utf-8", errors="replace")
    return {
        "P79_NATIVE_MARKER_COUNT": str(len(markers)),
        "P79_NATIVE_MARKER_SHA256": sha256(joined).hexdigest(),
    }
