"""Bounded, diagnostic-only camera E2E latency timeline.

Two independent clock sources feed this module:

* Observation-time boundaries (the ``T*`` keys, recorded via ``mark()``) are
  stamped by the Python asyncio event loop's own monotonic clock at the
  moment each native stdout line or HA-side event is *observed*.
* Native gathering-stage boundaries (the ``G*``/``RSP_*`` keys, recorded via
  ``mark_native()``) are the raw integer millisecond values the native
  helper itself printed, taken from its own ``g_get_monotonic_time()``.

Both clocks are ``CLOCK_MONOTONIC`` on the same host, so they are never
mixed: every derived field here differences either two ``T*`` observation
stamps or two native ``G*``/``RSP_*`` values, never one of each. This keeps
each derived duration meaningful without relying on cross-process clock
synchronization guarantees beyond "same host, same monotonic clock".
"""

from __future__ import annotations

from typing import Final

T00_CAMERA_REQUEST: Final = "T00_CAMERA_REQUEST"
T01_LEASE_ACQUIRE_BEGIN: Final = "T01_LEASE_ACQUIRE_BEGIN"
T02_LISTENER_PAUSE_REQUESTED: Final = "T02_LISTENER_PAUSE_REQUESTED"
T03_LISTENER_PAUSED_CONFIRMED: Final = "T03_LISTENER_PAUSED_CONFIRMED"
T04_TRANSPORT_START_BEGIN: Final = "T04_TRANSPORT_START_BEGIN"
T05_ICE_GATHER_DONE: Final = "T05_ICE_GATHER_DONE"
T06_CLOUD_NEGOTIATE_BEGIN: Final = "T06_CLOUD_NEGOTIATE_BEGIN"
T07_REMOTE_SDP_READY: Final = "T07_REMOTE_SDP_READY"
T08_ICE_CONNECTED: Final = "T08_ICE_CONNECTED"
T08B_ICE_READY: Final = "T08B_ICE_READY"
T09_PSEUDOTCP_OPEN: Final = "T09_PSEUDOTCP_OPEN"
T10_CTPP_READY: Final = "T10_CTPP_READY"
T11_SIGNALING_ARMED: Final = "T11_SIGNALING_ARMED"
T12_SELF_ACTIVATION_SENT: Final = "T12_SELF_ACTIVATION_SENT"
T13_RTPC_BEGIN: Final = "T13_RTPC_BEGIN"
T14_RTPC_CONTROL_COMPLETE: Final = "T14_RTPC_CONTROL_COMPLETE"
T15_MEDIA_ACTIVE: Final = "T15_MEDIA_ACTIVE"
T16_FIRST_VIDEO_RTP: Final = "T16_FIRST_VIDEO_RTP"
T17_FIRST_DECODABLE_FRAME: Final = "T17_FIRST_DECODABLE_FRAME"
T18_HA_STREAM_READY: Final = "T18_HA_STREAM_READY"
T19_HLS_PROVIDER_PRESENT: Final = "T19_HLS_PROVIDER_PRESENT"
T20_HLS_FIRST_PART: Final = "T20_HLS_FIRST_PART"
T21_HLS_FIRST_COMPLETE_SEGMENT: Final = "T21_HLS_FIRST_COMPLETE_SEGMENT"

_BOUNDARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        T00_CAMERA_REQUEST,
        T01_LEASE_ACQUIRE_BEGIN,
        T02_LISTENER_PAUSE_REQUESTED,
        T03_LISTENER_PAUSED_CONFIRMED,
        T04_TRANSPORT_START_BEGIN,
        T05_ICE_GATHER_DONE,
        T06_CLOUD_NEGOTIATE_BEGIN,
        T07_REMOTE_SDP_READY,
        T08_ICE_CONNECTED,
        T08B_ICE_READY,
        T09_PSEUDOTCP_OPEN,
        T10_CTPP_READY,
        T11_SIGNALING_ARMED,
        T12_SELF_ACTIVATION_SENT,
        T13_RTPC_BEGIN,
        T14_RTPC_CONTROL_COMPLETE,
        T15_MEDIA_ACTIVE,
        T16_FIRST_VIDEO_RTP,
        T17_FIRST_DECODABLE_FRAME,
        T18_HA_STREAM_READY,
        T19_HLS_PROVIDER_PRESENT,
        T20_HLS_FIRST_PART,
        T21_HLS_FIRST_COMPLETE_SEGMENT,
    }
)

MAX_BOUNDARIES: Final[int] = len(_BOUNDARY_KEYS)

LOG_MARKER: Final = "COMELIT_CAMERA_E2E_LATENCY"

# (output field name, start boundary, end boundary)
_DERIVED_FIELDS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "CAMERA_REQUEST_TO_LISTENER_PAUSED_MS",
        T00_CAMERA_REQUEST,
        T03_LISTENER_PAUSED_CONFIRMED,
    ),
    (
        "LISTENER_PAUSED_TO_TRANSPORT_START_MS",
        T03_LISTENER_PAUSED_CONFIRMED,
        T04_TRANSPORT_START_BEGIN,
    ),
    (
        "TRANSPORT_START_TO_ICE_GATHER_DONE_MS",
        T04_TRANSPORT_START_BEGIN,
        T05_ICE_GATHER_DONE,
    ),
    (
        "ICE_GATHER_DONE_TO_CLOUD_NEGOTIATE_MS",
        T05_ICE_GATHER_DONE,
        T06_CLOUD_NEGOTIATE_BEGIN,
    ),
    (
        "TRANSPORT_START_TO_CLOUD_NEGOTIATE_MS",
        T04_TRANSPORT_START_BEGIN,
        T06_CLOUD_NEGOTIATE_BEGIN,
    ),
    (
        "CLOUD_NEGOTIATE_TO_REMOTE_SDP_MS",
        T06_CLOUD_NEGOTIATE_BEGIN,
        T07_REMOTE_SDP_READY,
    ),
    (
        "REMOTE_SDP_TO_ICE_CONNECTED_MS",
        T07_REMOTE_SDP_READY,
        T08_ICE_CONNECTED,
    ),
    (
        "TRANSPORT_START_TO_ICE_CONNECTED_MS",
        T04_TRANSPORT_START_BEGIN,
        T08_ICE_CONNECTED,
    ),
    (
        "ICE_CONNECTED_TO_PSEUDOTCP_OPEN_MS",
        T08_ICE_CONNECTED,
        T09_PSEUDOTCP_OPEN,
    ),
    (
        "ICE_CONNECTED_TO_ICE_READY_MS",
        T08_ICE_CONNECTED,
        T08B_ICE_READY,
    ),
    (
        "ICE_READY_TO_PSEUDOTCP_OPEN_MS",
        T08B_ICE_READY,
        T09_PSEUDOTCP_OPEN,
    ),
    (
        "PSEUDOTCP_OPEN_TO_CTPP_READY_MS",
        T09_PSEUDOTCP_OPEN,
        T10_CTPP_READY,
    ),
    ("ICE_CONNECTED_TO_CTPP_READY_MS", T08_ICE_CONNECTED, T10_CTPP_READY),
    (
        "CTPP_READY_TO_SIGNALING_ARMED_MS",
        T10_CTPP_READY,
        T11_SIGNALING_ARMED,
    ),
    (
        "SIGNALING_ARMED_TO_SELF_ACTIVATION_MS",
        T11_SIGNALING_ARMED,
        T12_SELF_ACTIVATION_SENT,
    ),
    (
        "SELF_ACTIVATION_TO_RTPC_BEGIN_MS",
        T12_SELF_ACTIVATION_SENT,
        T13_RTPC_BEGIN,
    ),
    (
        "RTPC_BEGIN_TO_RTPC_COMPLETE_MS",
        T13_RTPC_BEGIN,
        T14_RTPC_CONTROL_COMPLETE,
    ),
    (
        "RTPC_COMPLETE_TO_FIRST_VIDEO_RTP_MS",
        T14_RTPC_CONTROL_COMPLETE,
        T16_FIRST_VIDEO_RTP,
    ),
    (
        "FIRST_VIDEO_RTP_TO_DECODABLE_FRAME_MS",
        T16_FIRST_VIDEO_RTP,
        T17_FIRST_DECODABLE_FRAME,
    ),
    (
        "DECODABLE_FRAME_TO_HLS_FIRST_PART_MS",
        T17_FIRST_DECODABLE_FRAME,
        T20_HLS_FIRST_PART,
    ),
    (
        "HLS_FIRST_PART_TO_FIRST_COMPLETE_SEGMENT_MS",
        T20_HLS_FIRST_PART,
        T21_HLS_FIRST_COMPLETE_SEGMENT,
    ),
    ("CAMERA_REQUEST_TO_FIRST_VIDEO_RTP_MS", T00_CAMERA_REQUEST, T16_FIRST_VIDEO_RTP),
    (
        "CAMERA_REQUEST_TO_FIRST_DECODABLE_FRAME_MS",
        T00_CAMERA_REQUEST,
        T17_FIRST_DECODABLE_FRAME,
    ),
    ("CAMERA_REQUEST_TO_FIRST_HLS_PART_MS", T00_CAMERA_REQUEST, T20_HLS_FIRST_PART),
    (
        "CAMERA_REQUEST_TO_FIRST_HLS_SEGMENT_MS",
        T00_CAMERA_REQUEST,
        T21_HLS_FIRST_COMPLETE_SEGMENT,
    ),
)

# Native gathering-stage markers (P119): raw integer monotonic milliseconds
# printed by the native helper itself, parsed verbatim by media_transport.py
# and recorded via mark_native(). These are never observation-time stamps,
# so they are stored and differenced separately from the T*/_marks/
# _duration_ms machinery above.
G0_NATIVE_PROCESS_START_MONOTONIC_MS: Final = "G0_NATIVE_PROCESS_START_MONOTONIC_MS"
G1_NICE_AGENT_READY_MONOTONIC_MS: Final = "G1_NICE_AGENT_READY_MONOTONIC_MS"
G2_GATHER_CALL_MONOTONIC_MS: Final = "G2_GATHER_CALL_MONOTONIC_MS"
G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS: Final = "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS"
G3_HOST_CANDIDATE_COUNT: Final = "G3_HOST_CANDIDATE_COUNT"
G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS: Final = "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS"
G4_SRFLX_CANDIDATE_COUNT: Final = "G4_SRFLX_CANDIDATE_COUNT"
G5_GATHER_DONE_MONOTONIC_MS: Final = "G5_GATHER_DONE_MONOTONIC_MS"
G6_OFFER_WRITTEN_MONOTONIC_MS: Final = "G6_OFFER_WRITTEN_MONOTONIC_MS"
RSP_VISIBLE_MONOTONIC_MS: Final = "RSP_VISIBLE_MONOTONIC_MS"
RSP_LOADED_MONOTONIC_MS: Final = "RSP_LOADED_MONOTONIC_MS"

# P121: gather-only stun-initial-timeout override markers. Plain integers/
# presence, no clock semantics -- never differenced against anything, so
# they never mix with the monotonic-ms arithmetic above.
GATHER_INITIAL_TIMEOUT_SET_MS: Final = "GATHER_INITIAL_TIMEOUT_SET_MS"
GATHER_INITIAL_TIMEOUT_RESTORED_MS: Final = "GATHER_INITIAL_TIMEOUT_RESTORED_MS"
GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED: Final = (
    "GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED"
)

_NATIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        G0_NATIVE_PROCESS_START_MONOTONIC_MS,
        G1_NICE_AGENT_READY_MONOTONIC_MS,
        G2_GATHER_CALL_MONOTONIC_MS,
        G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS,
        G3_HOST_CANDIDATE_COUNT,
        G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS,
        G4_SRFLX_CANDIDATE_COUNT,
        G5_GATHER_DONE_MONOTONIC_MS,
        G6_OFFER_WRITTEN_MONOTONIC_MS,
        RSP_VISIBLE_MONOTONIC_MS,
        RSP_LOADED_MONOTONIC_MS,
        GATHER_INITIAL_TIMEOUT_SET_MS,
        GATHER_INITIAL_TIMEOUT_RESTORED_MS,
    }
)

# (output field name, start native key, end native key). Inserted, in this
# exact order, immediately after TRANSPORT_START_TO_ICE_GATHER_DONE_MS (the
# 3rd entry of _DERIVED_FIELDS above).
_NATIVE_DERIVED_FIELDS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "NATIVE_PROCESS_START_TO_NICE_AGENT_READY_MS",
        G0_NATIVE_PROCESS_START_MONOTONIC_MS,
        G1_NICE_AGENT_READY_MONOTONIC_MS,
    ),
    (
        "NICE_AGENT_READY_TO_GATHER_CALL_MS",
        G1_NICE_AGENT_READY_MONOTONIC_MS,
        G2_GATHER_CALL_MONOTONIC_MS,
    ),
    (
        "GATHER_CALL_TO_FIRST_HOST_CANDIDATE_MS",
        G2_GATHER_CALL_MONOTONIC_MS,
        G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS,
    ),
    (
        "FIRST_HOST_TO_FIRST_SRFLX_CANDIDATE_MS",
        G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS,
        G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS,
    ),
    (
        "FIRST_SRFLX_TO_GATHER_DONE_MS",
        G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS,
        G5_GATHER_DONE_MONOTONIC_MS,
    ),
    (
        "GATHER_CALL_TO_GATHER_DONE_MS",
        G2_GATHER_CALL_MONOTONIC_MS,
        G5_GATHER_DONE_MONOTONIC_MS,
    ),
    (
        "GATHER_DONE_TO_OFFER_WRITTEN_MS",
        G5_GATHER_DONE_MONOTONIC_MS,
        G6_OFFER_WRITTEN_MONOTONIC_MS,
    ),
    (
        "REMOTE_SDP_FILE_VISIBLE_TO_LOAD_MS",
        RSP_VISIBLE_MONOTONIC_MS,
        RSP_LOADED_MONOTONIC_MS,
    ),
)

# Passthrough counts (not durations), same insertion point as above.
_NATIVE_COUNT_FIELDS: Final[tuple[str, ...]] = (
    G3_HOST_CANDIDATE_COUNT,
    G4_SRFLX_CANDIDATE_COUNT,
)

# P121: passthrough gather-only stun-initial-timeout fields, placed
# immediately after the existing P119 gathering-stage fields above.
_GATHER_INITIAL_TIMEOUT_PASSTHROUGH_FIELDS: Final[tuple[str, ...]] = (
    GATHER_INITIAL_TIMEOUT_SET_MS,
    GATHER_INITIAL_TIMEOUT_RESTORED_MS,
)

# The exact emitted field order: the first 3 existing fields, the 10 P119
# native fields, the 3 new P121 fields, then the remaining 22 existing
# fields.
FIELD_ORDER: Final[tuple[str, ...]] = (
    tuple(name for name, _, _ in _DERIVED_FIELDS[:3])
    + tuple(name for name, _, _ in _NATIVE_DERIVED_FIELDS)
    + _NATIVE_COUNT_FIELDS
    + _GATHER_INITIAL_TIMEOUT_PASSTHROUGH_FIELDS
    + (GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED,)
    + tuple(name for name, _, _ in _DERIVED_FIELDS[3:])
)


class CameraRequestLatencyTimeline:
    """Bounded, single-session monotonic boundary recorder.

    Each boundary records only its first observation; the fixed key set
    above is the only storage this object ever holds, so it cannot grow
    across a session's lifetime. All arithmetic is derived on demand from
    already-recorded monotonic seconds, never from wall-clock time.
    """

    def __init__(self) -> None:
        self._marks: dict[str, float] = {}
        self._native: dict[str, int] = {}
        self._emitted = False

    def mark(self, boundary: str, monotonic_seconds: float) -> None:
        if boundary not in _BOUNDARY_KEYS:
            return
        if boundary in self._marks:
            return
        self._marks[boundary] = monotonic_seconds

    def mark_native(self, key: str, value_ms: int) -> None:
        if key not in _NATIVE_KEYS:
            return
        if key in self._native:
            return
        self._native[key] = value_ms

    def has(self, boundary: str) -> bool:
        return boundary in self._marks

    @property
    def emitted(self) -> bool:
        return self._emitted

    def mark_emitted(self) -> None:
        self._emitted = True

    def is_complete(self) -> bool:
        return T21_HLS_FIRST_COMPLETE_SEGMENT in self._marks

    def _duration_ms(self, start: str, end: str) -> int | None:
        if start not in self._marks or end not in self._marks:
            return None
        delta_ms = (self._marks[end] - self._marks[start]) * 1000.0
        if delta_ms < 0:
            return None
        return int(round(delta_ms))

    def _native_duration_ms(self, start: str, end: str) -> int | None:
        if start not in self._native or end not in self._native:
            return None
        delta_ms = self._native[end] - self._native[start]
        if delta_ms < 0:
            return None
        return delta_ms

    def summary_fields(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, start, end in _DERIVED_FIELDS:
            value = self._duration_ms(start, end)
            result[name] = "N_A" if value is None else str(value)
        for name, start, end in _NATIVE_DERIVED_FIELDS:
            native_value = self._native_duration_ms(start, end)
            result[name] = "N_A" if native_value is None else str(native_value)
        for name in _NATIVE_COUNT_FIELDS:
            count_value = self._native.get(name)
            result[name] = "N_A" if count_value is None else str(count_value)
        for name in _GATHER_INITIAL_TIMEOUT_PASSTHROUGH_FIELDS:
            passthrough_value = self._native.get(name)
            result[name] = "N_A" if passthrough_value is None else str(passthrough_value)
        result[GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED] = (
            "true" if GATHER_INITIAL_TIMEOUT_RESTORED_MS in self._native else "false"
        )
        return result

    def log_line(self) -> str:
        fields = self.summary_fields()
        pairs = " ".join(f"{name}={fields[name]}" for name in FIELD_ORDER)
        return f"{LOG_MARKER} {pairs}"
