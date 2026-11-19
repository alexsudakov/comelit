"""Issue #319: the media owner must publish only native-suppressed observations.

The native helper prints ``V4_RING_PHASE=...`` for every attempt of a call and
prints the five-key observation only after ``v4_ring_is_retransmit()`` dropped
the retransmissions (same body SHA256 inside the helper's dedup window).
These tests pin that contract on the Python side: probes alone never produce an
event, retransmissions inside one batch never produce a second event.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"


def _load_package() -> types.ModuleType:
    name = "comelit_issue319_observation_proof"
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


def _probe(phase: str, body: str = "6a66ae04") -> list[str]:
    return [
        f"V4_RING_PHASE={phase}",
        "V4_RING_MONOTONIC_MS=862907802",
        "V4_RING_PEER_CONNECTION=5e3a",
        f"V4_RING_BODY_32_35={body}",
        "V4_RING_PARSE_STATUS=OK",
    ]


def _observation(door: str = "entrance", source: str = "00000643") -> list[str]:
    return [
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        f"V4_RING_DOOR={door}",
        f"V4_RING_SOURCE={source}",
    ]


def test_probe_stream_alone_never_produces_an_event():
    buffer = RingObservationBuffer()
    produced = [
        buffer.feed(line)
        for line in _probe("INITIAL") + _probe("RETRANSMIT") * 4
    ]
    assert [item for item in produced if item is not None] == []


def test_one_observation_batch_yields_one_event():
    buffer = RingObservationBuffer()
    produced = [buffer.feed(line) for line in _observation()]
    events = [item for item in produced if item is not None]
    assert len(events) == 1
    assert events[0].door == "entrance"
    assert events[0].source == "00000643"
    assert events[0].kind == "CALL_INIT"
    assert events[0].direction == "DEVICE_TO_CLIENT"


def test_retransmission_probes_inside_a_batch_do_not_duplicate_the_event():
    buffer = RingObservationBuffer()
    stream = _observation()[:3] + _probe("RETRANSMIT") + _observation()[3:]
    produced = [buffer.feed(line) for line in stream]
    assert len([item for item in produced if item is not None]) == 1


def test_incomplete_batch_is_discarded_and_the_next_batch_wins():
    buffer = RingObservationBuffer()
    broken = _observation()[:4]  # OBSERVED, DIRECTION, KIND, DOOR (no SOURCE)
    produced = [buffer.feed(line) for line in broken]
    produced += [buffer.feed(line) for line in _observation()]
    events = [item for item in produced if item is not None]
    assert len(events) == 1


def test_listener_timeout_marker_never_produces_an_event():
    buffer = RingObservationBuffer()
    produced = [
        buffer.feed("V4_RING_OBSERVED=false"),
        buffer.feed("V4_RING_DIRECTION=DEVICE_TO_CLIENT"),
        buffer.feed("V4_RING_KIND=CALL_INIT"),
        buffer.feed("V4_RING_DOOR=entrance"),
        buffer.feed("V4_RING_SOURCE=00000643"),
    ]
    assert [item for item in produced if item is not None] == []


def test_two_calls_produce_two_events():
    buffer = RingObservationBuffer()
    first = [buffer.feed(line) for line in _observation()]
    second = [buffer.feed(line) for line in _observation()]
    events = [item for item in first + second if item is not None]
    assert len(events) == 2


@pytest.mark.parametrize("direction", ["CLIENT_TO_DEVICE", ""])
def test_invalid_direction_is_rejected(direction):
    buffer = RingObservationBuffer()
    lines = _observation()
    lines[1] = f"V4_RING_DIRECTION={direction}"
    produced = [buffer.feed(line) for line in lines]
    assert [item for item in produced if item is not None] == []
