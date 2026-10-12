from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module


ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _ring(controller, owner, *, body: str = "1234abcd", sha: str | None = None) -> None:
    if sha is not None:
        controller.observe_native_line(owner, f"V4_RING_FRAME_SHA256={sha}")
    for line in (
        "V4_RING_PHASE=INITIAL",
        "V4_RING_PEER_CONNECTION=000a",
        f"V4_RING_BODY_32_35={body}",
        "V4_RING_PARSE_STATUS=OK",
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ):
        controller.observe_native_line(owner, line)


def _probe_records(controller):
    return controller.snapshot()["probe"]["records"]


def test_p1_listener_probe_parsing_happy_path_all_four_keys():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    record = _probe_records(controller)[-1]

    assert record["owner_kind"] == ring_shadow.SHADOW_OWNER_LISTENER
    assert record["owner_generation"] == (ring_shadow.SHADOW_OWNER_LISTENER, 1)
    assert record["phase"] == "INITIAL"
    assert record["parse_status"] == "OK"
    assert record["peer_connection_present"] is True
    assert record["body_32_35_present"] is True


def test_p2_existing_seven_golden_fixture_batch_classification_is_unchanged():
    expected = {
        "01_listener_ring_call1.golden.txt": (
            ((False, False, "entrance", "00000643", "observed", True, False),),
            False,
            1,
            0,
            1,
            0,
        ),
        "02_listener_ring_call2.golden.txt": (
            ((False, False, "entrance", "00000643", "observed", True, False),),
            False,
            1,
            0,
            1,
            0,
        ),
        "03_media_owner_ring.golden.txt": (
            ((False, False, "entrance", "00000643", "observed", False, False),),
            False,
            0,
            0,
            0,
            0,
        ),
        "04_retransmit_batch.golden.txt": (
            (
                (False, False, "entrance", "00000643", "observed", False, False),
                (False, True, "entrance", "00000643", "last_completed_batch", False, False),
            ),
            False,
            0,
            0,
            1,
            0,
        ),
        "05_malformed_incomplete.golden.txt": (
            (
                (True, False, "17", "2", "observed", False, False),
                (False, False, "gate", "00000610", "observed", False, False),
            ),
            False,
            1,
            2,
            0,
            0,
        ),
        "06_unrelated_native_stdout.golden.txt": ((), False, 0, 0, 0, 0),
        "07_two_calls_sequence.golden.txt": (
            (
                (False, False, "entrance", "00000643", "observed", True, False),
                (False, False, "entrance", "00000643", "observed", True, False),
            ),
            False,
            2,
            0,
            2,
            0,
        ),
    }
    for name, expected_summary in expected.items():
        batcher = ring_shadow.RingMarkerBatcher()
        completed = []
        for line in _lines(name):
            completed.extend(batcher.observe(line))
        snapshot = batcher.snapshot()
        summary = (
            tuple(
                (
                    batch.malformed,
                    batch.retransmit,
                    batch.door,
                    batch.source,
                    batch.identity_source,
                    batch.frame_sha_present,
                    batch.retransmit_sha_present,
                )
                for batch in completed
            ),
            batcher.pending() is not None,
            snapshot["unknown_marker_count"],
            snapshot["malformed_count"],
            snapshot["sha_marker_count"],
            snapshot["eviction_count"],
        )
        assert summary == expected_summary


def test_p3_probe_owner_attribution_listener_vs_media():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    records = _probe_records(controller)

    assert records[-2]["owner_kind"] == ring_shadow.SHADOW_OWNER_LISTENER
    assert records[-1]["owner_kind"] == ring_shadow.SHADOW_OWNER_MEDIA


def test_p4_owner_generation_attribution_and_context_join():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    record = _probe_records(controller)[-1]

    assert record["owner_generation"] == (ring_shadow.SHADOW_OWNER_MEDIA, 1)
    assert record["handoff_epoch"] == 1
    assert ring_shadow.OWNER_GENERATION_IS_CALL_IDENTITY is False
    assert ring_shadow.HANDOFF_EPOCH_IS_CALL_IDENTITY is False


def test_p5_m_to_l_stale_origin_not_protocol_identity():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    decision = controller.snapshot()["decisions"][-1]
    record = _probe_records(controller)[-1]

    assert decision["reason"] == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY
    assert decision["new_call_proven"] is False
    assert record["handoff_epoch"] == 2
    assert "identity" not in record


def test_p6_release_attribution_survives_entrance_gate_tombstone_revive_release():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=gate",
        "V4_RING_SOURCE=00000610",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "R64_TERMINAL_REMOTE_RELEASE_OBSERVED=true",
    )
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_A2


def test_p7_snapshot_probe_fields_are_sanitized_and_bounded():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER, sha="a" * 64)
    view = controller.snapshot_view()
    rendered = repr(view)
    record = view["probe_state"]["records"][-1]

    assert "a" * 64 not in rendered
    assert "1234abcd" not in rendered
    assert "V4_RING_PHASE" not in rendered
    assert record["phase"] == "INITIAL"
    assert record["parse_status"] == "OK"
    assert record["peer_connection_present"] is True
    assert view["probe_state"]["records_maxlen"] == ring_shadow.SHADOW_MAX_PROBE_RECORDS


def test_p8_probe_records_are_bounded_with_deterministic_eviction():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for index in range(ring_shadow.SHADOW_MAX_PROBE_RECORDS + 2):
        body = f"{index:08x}"
        _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER, body=body)
    probe = controller.snapshot()["probe"]
    records = probe["records"]

    assert len(records) == ring_shadow.SHADOW_MAX_PROBE_RECORDS
    assert records[0]["sequence"] == 3
    assert records[-1]["sequence"] == ring_shadow.SHADOW_MAX_PROBE_RECORDS + 2
    assert probe["eviction_count"] == 2


def test_p9_probe_never_enters_decide_or_changes_decisions(monkeypatch):
    calls = []
    original = ring_shadow.RingEmitGuard.decide

    def spy(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(ring_shadow.RingEmitGuard, "decide", spy)
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in (
        "V4_RING_PHASE=INITIAL",
        "V4_RING_PEER_CONNECTION=000a",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    assert calls == []

    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    assert len(calls) == 1
    assert "sha_changed_vs_prev_initial" not in calls[0]
    assert "body_32_35" not in calls[0]


def test_p10_probe_parser_exception_does_not_latch_shadow_hook():
    class BrokenProbe:
        def observe_sha(self, owner, line):
            raise RuntimeError("probe failed")

        def observe(self, owner, line, *, owner_generation, handoff_epoch):
            raise RuntimeError("probe failed")

        def snapshot(self):
            return {"records": (), "pending": {}, "malformed_count": 0, "ignored_count": 0, "eviction_count": 0, "missing_status_count": 0, "record_count": 0}

    controller = ring_shadow.RingShadowController()
    controller._probe_parser = BrokenProbe()
    hook = ring_shadow.RingShadowHook(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT + 2):
        hook.observe_line("V4_RING_PHASE=INITIAL")

    assert hook.latched is False


def test_p11_sha_changed_vs_prev_initial_all_states_and_no_sha_snapshot():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER, sha="1" * 64)
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER, sha="1" * 64)
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER, sha="2" * 64)
    for line in (
        "V4_RING_FRAME_SHA256=" + "3" * 64,
        "V4_RING_PHASE=RETRANSMIT",
        "V4_RING_PEER_CONNECTION=000a",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    states = [
        record["sha_changed_vs_prev_initial"]
        for record in controller.snapshot()["probe"]["records"]
    ]

    assert states == [
        ring_shadow.SHADOW_PROBE_SHA_FIRST_IN_GENERATION,
        ring_shadow.SHADOW_PROBE_SHA_SAME,
        ring_shadow.SHADOW_PROBE_SHA_CHANGED,
        ring_shadow.SHADOW_PROBE_SHA_NOT_ADJACENT,
    ]
    assert "1" * 64 not in repr(controller.snapshot())
    assert ring_shadow.FULL_FRAME_SHA_USED_AS_CALL_IDENTITY is False


def test_p12_malformed_probe_markers_are_discarded_and_shadow_survives():
    controller = ring_shadow.RingShadowController()
    for line in (
        "V4_RING_PHASE=BAD",
        "V4_RING_PHASE=INITIAL",
        "V4_RING_PEER_CONNECTION=000A",
        "V4_RING_PHASE=INITIAL",
        "V4_RING_BODY_32_35=123",
        "V4_RING_PHASE",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    probe = controller.snapshot()["probe"]

    assert probe["malformed_count"] == 4
    assert len(probe["records"]) == 1
    assert probe["records"][0]["parse_status"] == "OK"


def test_p13_missing_probe_markers_degrade_safely():
    controller = ring_shadow.RingShadowController()
    controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, "V4_RING_PHASE=INITIAL")
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "V4_RING_PEER_CONNECTION=000a",
    )
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "V4_RING_BODY_32_35=----",
    )
    no_status = controller.snapshot()["probe"]
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
    )
    record = controller.snapshot()["probe"]["records"][-1]

    assert no_status["record_count"] == 0
    assert record["peer_connection_present"] is True
    assert record["body_32_35_present"] is False
    assert record["body_32_35_unavailable"] is True
    assert record["parse_status"] == "INSUFFICIENT_LENGTH"
