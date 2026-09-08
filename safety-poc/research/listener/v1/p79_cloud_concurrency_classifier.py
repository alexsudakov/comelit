#!/usr/bin/env python3
"""Pure classifier for the COMELIT-P79 cloud/listener concurrency PoC."""

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
    P79_CLOUD_CONCURRENCY: str
    P79_LISTENER_STABILITY: str
    P79_TIMEOUT_RECONNECT_ASSOCIATION: str
    P79_RUN_RESULT: str
    process_rc: int

    def as_markers(self) -> dict[str, str]:
        return {
            "P79_CLOUD_CONCURRENCY": self.P79_CLOUD_CONCURRENCY,
            "P79_LISTENER_STABILITY": self.P79_LISTENER_STABILITY,
            "P79_TIMEOUT_RECONNECT_ASSOCIATION": self.P79_TIMEOUT_RECONNECT_ASSOCIATION,
            "P79_RUN_RESULT": self.P79_RUN_RESULT,
            "P79_PROCESS_RC": str(self.process_rc),
        }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _sample_valid(sample: Mapping[str, Any] | None) -> bool:
    if not isinstance(sample, Mapping):
        return False
    return (
        isinstance(sample.get("supervisor_running"), bool)
        and isinstance(sample.get("running"), bool)
        and isinstance(sample.get("listener_ready"), bool)
        and _as_int(sample.get("reconnect_count")) is not None
    )


def _sample_running(sample: Mapping[str, Any]) -> bool:
    return _as_bool(sample.get("supervisor_running")) and _as_bool(sample.get("running"))


def _sample_ready(sample: Mapping[str, Any]) -> bool:
    return _as_bool(sample.get("listener_ready"))


def reconnect_count_changed(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> bool | None:
    if not _sample_valid(before) or not _sample_valid(after):
        return None
    before_count = _as_int(before.get("reconnect_count"))
    after_count = _as_int(after.get("reconnect_count"))
    assert before_count is not None and after_count is not None
    return after_count != before_count


def listener_remained_running(samples: Sequence[Mapping[str, Any]]) -> bool:
    return bool(samples) and all(_sample_valid(sample) and _sample_running(sample) for sample in samples)


def listener_ready_returned_or_stayed(samples: Sequence[Mapping[str, Any]]) -> bool:
    return bool(samples) and _sample_valid(samples[-1]) and _sample_ready(samples[-1])


def _unknown() -> Classification:
    return Classification(
        P79_CLOUD_CONCURRENCY="UNKNOWN",
        P79_LISTENER_STABILITY="UNKNOWN",
        P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
        P79_RUN_RESULT="UNKNOWN_OUTCOME",
        process_rc=RUN_RESULT_TO_PROCESS_RC["UNKNOWN_OUTCOME"],
    )


def classify(
    *,
    p2p_result: str | None,
    remote_sdp_present: bool | str | None,
    before_sample: Mapping[str, Any] | None = None,
    post_samples: Sequence[Mapping[str, Any]] | None = None,
    listener_samples: Sequence[Mapping[str, Any]] | None = None,
    preflight_blocked: bool = False,
    terminal_marker_present: bool = True,
) -> Classification:
    """Classify one P79 cloud request against a bounded listener observation window.

    `before_sample` + `post_samples` is the preferred API. `listener_samples` is
    retained only for compatibility with the original offline tests: its first
    item is the baseline and the remaining items are post-result observations.
    """

    if preflight_blocked:
        return Classification(
            P79_CLOUD_CONCURRENCY="BLOCKED",
            P79_LISTENER_STABILITY="NOT_EVALUATED",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
            P79_RUN_RESULT="BLOCKED",
            process_rc=RUN_RESULT_TO_PROCESS_RC["BLOCKED"],
        )

    if before_sample is None and listener_samples is not None:
        before_sample = listener_samples[0] if listener_samples else None
        post_samples = list(listener_samples[1:]) if len(listener_samples) > 1 else []

    posts = list(post_samples or [])

    if not terminal_marker_present or p2p_result is None:
        return _unknown()

    # A P79 PASS is meaningful only if the listener was healthy at the baseline
    # and every intended post-result sample is parseable.
    if not _sample_valid(before_sample) or not posts or not all(_sample_valid(s) for s in posts):
        return _unknown()

    assert before_sample is not None
    baseline_count = _as_int(before_sample.get("reconnect_count"))
    assert baseline_count is not None

    baseline_healthy = _sample_running(before_sample) and _sample_ready(before_sample)
    remained_running = all(_sample_running(sample) for sample in posts)
    final_ready = _sample_ready(posts[-1])
    reconnect_changed = any(_as_int(sample.get("reconnect_count")) != baseline_count for sample in posts)

    normalized_result = p2p_result.strip().upper()
    has_remote_sdp = _as_bool(remote_sdp_present)

    if normalized_result == "SUCCESS" and has_remote_sdp:
        if baseline_healthy and remained_running and not reconnect_changed and final_ready:
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
        if reconnect_changed:
            return Classification(
                P79_CLOUD_CONCURRENCY="INCONCLUSIVE",
                P79_LISTENER_STABILITY="NOT_PROVEN",
                P79_TIMEOUT_RECONNECT_ASSOCIATION="OBSERVED",
                P79_RUN_RESULT="INCONCLUSIVE",
                process_rc=RUN_RESULT_TO_PROCESS_RC["INCONCLUSIVE"],
            )
        return Classification(
            P79_CLOUD_CONCURRENCY="INCONCLUSIVE_TRANSIENT_TIMEOUT",
            P79_LISTENER_STABILITY=(
                "PROVEN" if baseline_healthy and remained_running and final_ready else "NOT_PROVEN"
            ),
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_OBSERVED",
            P79_RUN_RESULT="INCONCLUSIVE_TRANSIENT_TIMEOUT",
            process_rc=RUN_RESULT_TO_PROCESS_RC["INCONCLUSIVE_TRANSIENT_TIMEOUT"],
        )

    if normalized_result == "FAIL":
        return Classification(
            P79_CLOUD_CONCURRENCY="FAIL",
            P79_LISTENER_STABILITY="NOT_PROVEN",
            P79_TIMEOUT_RECONNECT_ASSOCIATION="NOT_EVALUATED",
            P79_RUN_RESULT="FAIL",
            process_rc=RUN_RESULT_TO_PROCESS_RC["FAIL"],
        )

    return _unknown()


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
