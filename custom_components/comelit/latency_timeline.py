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
T09_PSEUDOTCP_OPEN: Final = "T09_PSEUDOTCP_OPEN"
T11_CTPP_READY: Final = "T11_CTPP_READY"
T12_SELF_ACTIVATION_SENT: Final = "T12_SELF_ACTIVATION_SENT"
T13_RTPC_READY: Final = "T13_RTPC_READY"
T14_MEDIA_ACTIVE: Final = "T14_MEDIA_ACTIVE"
T15_FIRST_VIDEO_RTP: Final = "T15_FIRST_VIDEO_RTP"
T16_FIRST_DECODABLE_FRAME: Final = "T16_FIRST_DECODABLE_FRAME"
T17_HA_STREAM_READY: Final = "T17_HA_STREAM_READY"
T18_HLS_PROVIDER_PRESENT: Final = "T18_HLS_PROVIDER_PRESENT"
T19_HLS_FIRST_PART: Final = "T19_HLS_FIRST_PART"
T20_HLS_FIRST_COMPLETE_SEGMENT: Final = "T20_HLS_FIRST_COMPLETE_SEGMENT"

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
        T09_PSEUDOTCP_OPEN,
        T11_CTPP_READY,
        T12_SELF_ACTIVATION_SENT,
        T13_RTPC_READY,
        T14_MEDIA_ACTIVE,
        T15_FIRST_VIDEO_RTP,
        T16_FIRST_DECODABLE_FRAME,
        T17_HA_STREAM_READY,
        T18_HLS_PROVIDER_PRESENT,
        T19_HLS_FIRST_PART,
        T20_HLS_FIRST_COMPLETE_SEGMENT,
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
        "TRANSPORT_START_TO_ICE_CONNECTED_MS",
        T04_TRANSPORT_START_BEGIN,
        T08_ICE_CONNECTED,
    ),
    ("ICE_CONNECTED_TO_CTPP_READY_MS", T08_ICE_CONNECTED, T11_CTPP_READY),
    ("CTPP_READY_TO_RTPC_READY_MS", T11_CTPP_READY, T13_RTPC_READY),
    ("RTPC_READY_TO_FIRST_VIDEO_RTP_MS", T13_RTPC_READY, T15_FIRST_VIDEO_RTP),
    (
        "FIRST_VIDEO_RTP_TO_DECODABLE_FRAME_MS",
        T15_FIRST_VIDEO_RTP,
        T16_FIRST_DECODABLE_FRAME,
    ),
    (
        "DECODABLE_FRAME_TO_HLS_FIRST_PART_MS",
        T16_FIRST_DECODABLE_FRAME,
        T19_HLS_FIRST_PART,
    ),
    (
        "HLS_FIRST_PART_TO_FIRST_COMPLETE_SEGMENT_MS",
        T19_HLS_FIRST_PART,
        T20_HLS_FIRST_COMPLETE_SEGMENT,
    ),
    ("CAMERA_REQUEST_TO_FIRST_VIDEO_RTP_MS", T00_CAMERA_REQUEST, T15_FIRST_VIDEO_RTP),
    (
        "CAMERA_REQUEST_TO_FIRST_DECODABLE_FRAME_MS",
        T00_CAMERA_REQUEST,
        T16_FIRST_DECODABLE_FRAME,
    ),
    ("CAMERA_REQUEST_TO_FIRST_HLS_PART_MS", T00_CAMERA_REQUEST, T19_HLS_FIRST_PART),
    (
        "CAMERA_REQUEST_TO_FIRST_HLS_SEGMENT_MS",
        T00_CAMERA_REQUEST,
        T20_HLS_FIRST_COMPLETE_SEGMENT,
    ),
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
        self._emitted = False

    def mark(self, boundary: str, monotonic_seconds: float) -> None:
        if boundary not in _BOUNDARY_KEYS:
            return
        if boundary in self._marks:
            return
        self._marks[boundary] = monotonic_seconds

    def has(self, boundary: str) -> bool:
        return boundary in self._marks

    @property
    def emitted(self) -> bool:
        return self._emitted

    def mark_emitted(self) -> None:
        self._emitted = True

    def is_complete(self) -> bool:
        return T20_HLS_FIRST_COMPLETE_SEGMENT in self._marks

    def _duration_ms(self, start: str, end: str) -> int | None:
        if start not in self._marks or end not in self._marks:
            return None
        delta_ms = (self._marks[end] - self._marks[start]) * 1000.0
        if delta_ms < 0:
            return None
        return int(round(delta_ms))

    def summary_fields(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, start, end in _DERIVED_FIELDS:
            value = self._duration_ms(start, end)
            result[name] = "N_A" if value is None else str(value)
        return result

    def log_line(self) -> str:
        fields = self.summary_fields()
        pairs = " ".join(f"{name}={fields[name]}" for name, _, _ in _DERIVED_FIELDS)
        return f"{LOG_MARKER} {pairs}"
