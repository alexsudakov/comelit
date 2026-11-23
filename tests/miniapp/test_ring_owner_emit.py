from __future__ import annotations

from datetime import datetime
import importlib.util
import logging
from pathlib import Path
import sys
import types
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "custom_components" / "comelit"
FAKE_PACKAGE = "comelit_ring_owner_emit_testpkg"
FRAME_SHA = "0123456789abcdef" * 4
OTHER_SHA = "fedcba9876543210" * 4


def _load_ring_emit():
    package = types.ModuleType(FAKE_PACKAGE)
    package.__path__ = [str(PKG_ROOT)]
    sys.modules[FAKE_PACKAGE] = package

    core_name = "homeassistant.core"
    previous_core = sys.modules.get(core_name)
    core = types.ModuleType(core_name)
    core.HomeAssistant = object
    sys.modules[core_name] = core
    try:
        spec = importlib.util.spec_from_file_location(
            f"{FAKE_PACKAGE}.ring_emit",
            PKG_ROOT / "ring_emit.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_core is None:
            sys.modules.pop(core_name, None)
        else:
            sys.modules[core_name] = previous_core


ring_emit = _load_ring_emit()


class _FakeBus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_name: str, payload: dict[str, object]) -> None:
        self.fired.append((event_name, dict(payload)))


def _emitter(*, max_tokens: int = 64):
    bus = _FakeBus()
    hass = types.SimpleNamespace(bus=bus)
    dedup = ring_emit.RingEmitDedup(max_tokens=max_tokens)
    return ring_emit.MediaRingEmitter(hass, dedup), bus


def _observation(*, sha: str | None = FRAME_SHA, door: str = "entrance") -> list[str]:
    lines = []
    if sha is not None:
        lines.append(f"V4_RING_FRAME_SHA256={sha}")
    lines.extend(
        (
            "V4_RING_OBSERVED=true",
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            "V4_RING_KIND=CALL_INIT",
            f"V4_RING_DOOR={door}",
            "V4_RING_SOURCE=00000643",
        )
    )
    return lines


def _suppression_markers(caplog, level: int) -> list[str]:
    return [
        record.message
        for record in caplog.records
        if record.message.startswith("OWNER_RING_EMIT_SUPPRESSED=")
        and record.levelno >= level
    ]


def test_full_valid_batch_fires_one_runtime_ring_event():
    emitter, bus = _emitter()

    payload = emitter.emit_from_markers(_observation())

    assert payload is not None
    assert len(bus.fired) == 1
    event_name, fired = bus.fired[0]
    assert event_name == ring_emit.EVENT_RING
    assert event_name == "comelit_ring"
    assert fired == payload
    assert fired["door"] == "entrance"
    assert fired["source"] == "00000643"
    assert fired["kind"] == "CALL_INIT"
    assert fired["direction"] == "DEVICE_TO_CLIENT"
    assert fired["owner"] == "on_demand_media"
    UUID(str(fired["event_id"]))
    timestamp = datetime.fromisoformat(str(fired["timestamp"]))
    assert timestamp.utcoffset() is not None
    assert timestamp.utcoffset().total_seconds() == 0
    assert "frame_sha256" not in fired
    assert FRAME_SHA not in repr(fired)


def test_same_frame_content_is_suppressed_at_debug_level(caplog):
    emitter, bus = _emitter()

    with caplog.at_level(logging.DEBUG, logger=ring_emit.__name__):
        first = emitter.emit_from_markers(_observation())
        duplicate = emitter.emit_from_markers(_observation())

    assert first is not None
    assert duplicate is None
    assert len(bus.fired) == 1
    assert _suppression_markers(caplog, logging.DEBUG) == [
        "OWNER_RING_EMIT_SUPPRESSED=duplicate_frame"
    ]
    assert _suppression_markers(caplog, logging.WARNING) == []


def test_distinct_frame_content_publishes_a_second_event():
    emitter, bus = _emitter()

    first = emitter.emit_from_markers(_observation(sha=FRAME_SHA))
    second = emitter.emit_from_markers(_observation(sha=OTHER_SHA))

    assert first is not None and second is not None
    assert len(bus.fired) == 2
    assert bus.fired[0][1]["event_id"] != bus.fired[1][1]["event_id"]


@pytest.mark.parametrize("sha", [None, "a" * 63, "A" * 64, "g" * 64])
def test_missing_or_invalid_sha_is_suppressed_as_identity_incomplete(sha, caplog):
    emitter, bus = _emitter()

    with caplog.at_level(logging.WARNING, logger=ring_emit.__name__):
        payload = emitter.emit_from_markers(_observation(sha=sha))

    assert payload is None
    assert bus.fired == []
    assert _suppression_markers(caplog, logging.WARNING) == [
        "OWNER_RING_EMIT_SUPPRESSED=identity_incomplete"
    ]


def test_conflicting_frame_tokens_are_suppressed(caplog):
    emitter, bus = _emitter()
    batch = _observation() + [f"V4_RING_FRAME_SHA256={OTHER_SHA}"]

    with caplog.at_level(logging.WARNING, logger=ring_emit.__name__):
        payload = emitter.emit_from_markers(batch)

    assert payload is None
    assert bus.fired == []
    assert _suppression_markers(caplog, logging.WARNING) == [
        "OWNER_RING_EMIT_SUPPRESSED=parse_error"
    ]


def test_parser_error_is_suppressed(caplog):
    emitter, bus = _emitter()
    batch = _observation()
    batch[2] = "V4_RING_DIRECTION=CLIENT_TO_DEVICE"

    with caplog.at_level(logging.WARNING, logger=ring_emit.__name__):
        payload = emitter.emit_from_markers(batch)

    assert payload is None
    assert bus.fired == []
    assert _suppression_markers(caplog, logging.WARNING) == [
        "OWNER_RING_EMIT_SUPPRESSED=parse_error"
    ]


def test_conflicting_door_markers_are_suppressed(caplog):
    emitter, bus = _emitter()
    batch = _observation()
    batch.insert(-1, "V4_RING_DOOR=gate")

    with caplog.at_level(logging.WARNING, logger=ring_emit.__name__):
        payload = emitter.emit_from_markers(batch)

    assert payload is None
    assert bus.fired == []
    assert _suppression_markers(caplog, logging.WARNING) == [
        "OWNER_RING_EMIT_SUPPRESSED=parse_error"
    ]


def test_observed_false_and_unrelated_batches_are_silent(caplog):
    emitter, bus = _emitter()
    observed_false = [
        "V4_RING_FRAME_SHA256=" + FRAME_SHA,
        "V4_RING_OBSERVED=false",
    ]

    with caplog.at_level(logging.DEBUG, logger=ring_emit.__name__):
        assert emitter.emit_from_markers(observed_false) is None
        assert emitter.emit_from_markers(["V4_RING_PHASE=INITIAL"]) is None
        assert emitter.emit_from_markers([]) is None

    assert bus.fired == []
    assert _suppression_markers(caplog, logging.DEBUG) == []


def test_dedup_evicts_only_above_its_capacity():
    dedup = ring_emit.RingEmitDedup(max_tokens=2)

    assert dedup.claim("a" * 64) is True
    assert dedup.claim("b" * 64) is True
    assert dedup.claim("a" * 64) is False
    assert dedup.claim("c" * 64) is True
    # "a" was the oldest entry and has been evicted; "b" is still remembered.
    assert dedup.claim("a" * 64) is True
    assert dedup.claim("c" * 64) is False


def test_reset_starts_a_new_session():
    emitter, bus = _emitter()

    assert emitter.emit_from_markers(_observation()) is not None
    emitter.reset()
    assert emitter.emit_from_markers(_observation()) is not None
    assert len(bus.fired) == 2


PROBE_MARKERS = (
    "V4_RING_PHASE=INITIAL",
    "V4_RING_MONOTONIC_MS=12345",
    "V4_RING_PEER_CONNECTION=4a2b",
    "V4_RING_BODY_32_35=deadbeef",
    "V4_RING_PARSE_STATUS=OK",
)


def test_batcher_completes_a_batch_in_native_order():
    """Native order: FRAME_SHA256, then R68 probe markers, then observation."""
    batcher = ring_emit.RingMarkerBatcher()
    lines = ["V4_RING_PHASE=INITIAL", f"V4_RING_FRAME_SHA256={FRAME_SHA}"]
    lines += list(PROBE_MARKERS)
    lines += _observation(sha=None)

    batches = [batcher.feed(line) for line in lines]

    assert batches[:-1] == [None] * (len(lines) - 1)
    assert batches[-1] is not None
    assert f"V4_RING_FRAME_SHA256={FRAME_SHA}" in batches[-1]
    emitter, bus = _emitter()
    assert emitter.emit_from_markers(batches[-1]) is not None
    assert len(bus.fired) == 1


def test_batcher_ignores_non_ring_lines_and_incomplete_batches():
    batcher = ring_emit.RingMarkerBatcher()

    for line in ("INFO", "V4_RING_OBSERVED=true", "V4_RING_DIRECTION=DEVICE_TO_CLIENT"):
        assert batcher.feed(line) is None
    assert batcher.feed(None) is None


def test_batcher_starts_a_new_batch_on_a_new_observation():
    batcher = ring_emit.RingMarkerBatcher()
    for line in ("V4_RING_OBSERVED=true", "V4_RING_DIRECTION=DEVICE_TO_CLIENT"):
        assert batcher.feed(line) is None

    completed = None
    for line in _observation(sha=OTHER_SHA):
        completed = batcher.feed(line) or completed

    assert completed is not None
    assert f"V4_RING_FRAME_SHA256={OTHER_SHA}" in completed
    # The stale, incomplete observation must not leak into the new batch.
    assert sum(1 for line in completed if line.startswith("V4_RING_OBSERVED=")) == 1


def test_batcher_bounded_line_limit_drops_an_overlong_batch_token():
    batcher = ring_emit.RingMarkerBatcher()
    batcher.feed(f"V4_RING_FRAME_SHA256={FRAME_SHA}")
    # Push the frame token out of the bounded window before the observation
    # markers arrive; the batch must then fail closed instead of guessing.
    for index in range(ring_emit.RingMarkerBatcher.LINE_LIMIT):
        assert batcher.feed(f"V4_RING_UNKNOWN_{index}=1") is None

    completed = None
    for line in _observation(sha=None):
        completed = batcher.feed(line) or completed

    assert completed is not None
    assert f"V4_RING_FRAME_SHA256={FRAME_SHA}" not in completed
    emitter, bus = _emitter()
    assert emitter.emit_from_markers(completed) is None
    assert bus.fired == []


def test_transport_reader_path_publishes_once_for_one_call():
    """Mirror the transport reader: one-line delay, native marker order, flush."""
    emitter, bus = _emitter()
    batcher = ring_emit.RingMarkerBatcher()
    stream = [
        "INFO",
        f"V4_RING_FRAME_SHA256={FRAME_SHA}",
        *PROBE_MARKERS,
        *_observation(sha=None),
        "STATUS",
    ]
    previous = None
    for line in stream:
        if previous is not None:
            batch = batcher.feed(previous)
            if batch is not None:
                emitter.emit_from_markers(batch)
        previous = line
    batch = batcher.feed(previous)
    if batch is not None:
        emitter.emit_from_markers(batch)

    assert len(bus.fired) == 1
