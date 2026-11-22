"""Issue #319: the media owner publishes the native observation, once per batch.

The native helper prints probe lines for every attempt and the five-key
observation only after its retransmission filter accepted the frame, so the
Python side must never treat a probe as a call and must never add a second
deduplication layer of its own.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"


def _load_package() -> types.ModuleType:
    name = "comelit_issue319_observation"
    package = types.ModuleType(name)
    package.__path__ = [str(COMPONENT)]
    sys.modules[name] = package
    return package


def _load(package: types.ModuleType, module: str):
    spec = importlib.util.spec_from_file_location(
        f"{package.__name__}.{module}", COMPONENT / f"{module}.py"
    )
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


_PACKAGE = _load_package()
ring_observation = _load(_PACKAGE, "ring_observation")
RingObservationBuffer = ring_observation.RingObservationBuffer


def _probe(phase: str) -> list[str]:
    return [
        f"V4_RING_PHASE={phase}",
        "V4_RING_MONOTONIC_MS=862907802",
        "V4_RING_PEER_CONNECTION=5e3a",
        "V4_RING_BODY_32_35=6a66ae04",
        "V4_RING_PARSE_STATUS=OK",
    ]


def _observation() -> list[str]:
    return [
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ]


def test_probe_stream_alone_never_produces_an_event():
    buffer = RingObservationBuffer()
    produced = [
        buffer.feed(line)
        for line in _probe("INITIAL") + _probe("RETRANSMIT") * 4
    ]
    assert [item for item in produced if item is not None] == []


def test_one_observation_yields_exactly_one_event():
    buffer = RingObservationBuffer()
    produced = [buffer.feed(line) for line in _observation()]
    events = [item for item in produced if item is not None]
    assert len(events) == 1
    assert events[0].door == "entrance"
    assert events[0].kind == "CALL_INIT"


def test_two_observations_yield_two_events_without_client_dedup():
    buffer = RingObservationBuffer()
    produced = [
        buffer.feed(line) for line in _observation() + _observation()
    ]
    assert len([item for item in produced if item is not None]) == 2


def test_timeout_marker_never_produces_an_event():
    buffer = RingObservationBuffer()
    produced = [buffer.feed(line) for line in ["V4_RING_OBSERVED=false"]]
    assert [item for item in produced if item is not None] == []


def test_incomplete_batch_is_dropped_and_does_not_leak():
    buffer = RingObservationBuffer()
    produced = [
        buffer.feed(line)
        for line in ["V4_RING_OBSERVED=true", "V4_RING_DIRECTION=DEVICE_TO_CLIENT"]
        + _observation()
    ]
    events = [item for item in produced if item is not None]
    assert len(events) == 1
    assert events[0].source == "00000643"
