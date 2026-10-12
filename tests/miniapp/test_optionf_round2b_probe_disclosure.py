from __future__ import annotations

from pathlib import Path
import logging
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import (  # noqa: E402
    _FakeProcess,
    _listener_instance,
    _load_component_module,
    _media_instance,
    load_plain_module,
    run_listener_replay,
    run_media_replay,
)


ring_probe_log = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_probe_log.py", "ring_probe_log"
)
ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
runtime = _load_component_module(str(ROOT), "runtime")
media_transport = _load_component_module(str(ROOT), "media_transport")
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _probe_messages(caplog):
    return [
        record.message
        for record in caplog.records
        if record.message.startswith(ring_probe_log.RING_PROBE_LOG_PREFIXES)
    ]


def _complete_messages(caplog):
    return [
        message
        for message in _probe_messages(caplog)
        if message.startswith(ring_probe_log.RING_PROBE_COMPLETE_PREFIX)
    ]


def _listener():
    instance, _events, _call_state = _listener_instance(runtime, False)
    return instance


def _media():
    instance, _events, _call_state, _shadow = _media_instance(media_transport, False)
    return instance


def _feed(instance, lines: list[str]) -> None:
    for line in lines:
        instance._remember_native_marker(line)


def _complete_batch(*, phase: str = "INITIAL") -> list[str]:
    return [
        f"V4_RING_PHASE={phase}",
        "V4_RING_PEER_CONNECTION=1234",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
    ]


def _fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _insert_probe_batch(lines: list[str]) -> list[str]:
    insert_after = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if line.startswith("V4_RING_FRAME_SHA256=")
        ),
        next(
            index
            for index, line in enumerate(lines)
            if line.startswith("V4_RING_OBSERVED=")
        ),
    )
    return lines[:insert_after] + _complete_batch() + lines[insert_after:]


def test_probe_key_sets_match_reader_allowlists():
    assert (
        ring_probe_log.RING_PROBE_KEYS
        == runtime._RING_PROBE_MARKER_KEYS
        == media_transport._RING_PROBE_MARKER_KEYS
    )


def test_t1_listener_complete_initial_batch_emits_one_bounded_line(caplog):
    instance = _listener()

    with caplog.at_level(logging.INFO):
        _feed(instance, _complete_batch())

    assert _probe_messages(caplog) == [
        "Comelit ring identity probe; owner=listener phase=INITIAL "
        "peer_connection=1234 body_32_35=1234abcd"
    ]


def test_t2_media_complete_initial_batch_emits_owner_media(caplog):
    instance = _media()

    with caplog.at_level(logging.INFO):
        _feed(instance, _complete_batch())

    messages = _probe_messages(caplog)
    assert len(messages) == 1
    assert "owner=media" in messages[0]
    assert "peer_connection=1234" in messages[0]
    assert "body_32_35=1234abcd" in messages[0]


def test_t3_retransmit_phase_is_disclosed(caplog):
    instance = _listener()

    with caplog.at_level(logging.INFO):
        _feed(instance, _complete_batch(phase="RETRANSMIT"))

    messages = _probe_messages(caplog)
    assert len(messages) == 1
    assert "phase=RETRANSMIT" in messages[0]


def test_t4_peer_connection_wrong_length_is_not_disclosed(caplog):
    with caplog.at_level(logging.INFO):
        for peer in ("123", "12345", "123456"):
            _feed(
                _listener(),
                [
                    "V4_RING_PHASE=INITIAL",
                    f"V4_RING_PEER_CONNECTION={peer}",
                    "V4_RING_BODY_32_35=1234abcd",
                    "V4_RING_PARSE_STATUS=OK",
                ],
            )

    rendered = "\n".join(_probe_messages(caplog))
    assert _complete_messages(caplog) == []
    for peer in ("123", "12345", "123456"):
        assert peer not in rendered


def test_t5_body_32_35_wrong_length_is_not_disclosed(caplog):
    with caplog.at_level(logging.INFO):
        for body in ("1234abc", "1234abcde"):
            _feed(
                _listener(),
                [
                    "V4_RING_PHASE=INITIAL",
                    "V4_RING_PEER_CONNECTION=1234",
                    f"V4_RING_BODY_32_35={body}",
                    "V4_RING_PARSE_STATUS=OK",
                ],
            )

    rendered = "\n".join(_probe_messages(caplog))
    assert _complete_messages(caplog) == []
    for body in ("1234abc", "1234abcde"):
        assert body not in rendered


def test_t6_non_hex_values_are_not_disclosed(caplog):
    values = ("12 4", "zzzz", "zzzzzzzz", "1234abcdx")

    with caplog.at_level(logging.INFO):
        for peer in ("12 4", "zzzz"):
            _feed(
                _listener(),
                [
                    "V4_RING_PHASE=INITIAL",
                    f"V4_RING_PEER_CONNECTION={peer}",
                    "V4_RING_BODY_32_35=1234abcd",
                    "V4_RING_PARSE_STATUS=OK",
                ],
            )
        for body in ("zzzzzzzz", "1234abcdx"):
            _feed(
                _listener(),
                [
                    "V4_RING_PHASE=INITIAL",
                    "V4_RING_PEER_CONNECTION=1234",
                    f"V4_RING_BODY_32_35={body}",
                    "V4_RING_PARSE_STATUS=OK",
                ],
            )

    rendered = "\n".join(_probe_messages(caplog))
    assert _complete_messages(caplog) == []
    for value in values:
        assert value not in rendered


def test_t7_unknown_hex_marker_keys_are_not_disclosed(caplog):
    values = ("1234", "1234abcd", "a" * 64)
    lines = [
        "V4_RING_OTHER=1234",
        "V4_RING_OTHER2=1234abcd",
        f"V4_RING_OTHER3={'a' * 64}",
    ]

    with caplog.at_level(logging.INFO):
        _feed(_listener(), lines)

    rendered = "\n".join(_probe_messages(caplog))
    assert _complete_messages(caplog) == []
    for value in values:
        assert value not in rendered


def test_t8_partial_batch_does_not_emit_complete_identity_line(caplog):
    with caplog.at_level(logging.INFO):
        _feed(
            _listener(),
            [
                "V4_RING_PHASE=INITIAL",
                "V4_RING_PEER_CONNECTION=1234",
                "V4_RING_PARSE_STATUS=OK",
            ],
        )
        _feed(
            _listener(),
            [
                "V4_RING_PHASE=INITIAL",
                "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
            ],
        )
        _feed(
            _listener(),
            [
                "V4_RING_PHASE=INITIAL",
                "V4_RING_PEER_CONNECTION=1234",
                "V4_RING_BODY_32_35=----",
                "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
            ],
        )

    messages = _probe_messages(caplog)
    assert _complete_messages(caplog) == []
    assert messages == [
        "Comelit ring identity probe incomplete; owner=listener phase=INITIAL "
        "missing=peer_connection,body_32_35",
        "Comelit ring identity probe incomplete; owner=listener phase=INITIAL "
        "missing=body_32_35",
    ]
    assert "1234" not in "\n".join(messages)


def test_t9_malformed_batch_keeps_reader_working(caplog):
    instance = _listener()
    hostile = [
        "V4_RING_PHASE=NOT_A_PHASE",
        "V4_RING_PHASE",
        "V4_RING_BODY_32_35=",
        "V4_RING_PEER_CONNECTION=0000zzzz",
        "V4_RING_PARSE_STATUS=NOPE",
        " V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
    ]

    with caplog.at_level(logging.INFO):
        _feed(instance, hostile)
        _feed(instance, _complete_batch())

    assert _probe_messages(caplog) == [
        "Comelit ring identity probe; owner=listener phase=INITIAL "
        "peer_connection=1234 body_32_35=1234abcd"
    ]


def test_t10_probe_values_remain_redacted_in_marker_collections(caplog):
    listener = _listener()
    media = _media()

    with caplog.at_level(logging.INFO):
        _feed(listener, _complete_batch())
        _feed(media, _complete_batch())
        media._emit_native_success_summary()

    assert listener._native_marker_tail == []
    assert getattr(listener, "_native_protocol_markers", []) == []
    assert media._native_marker_tail == []
    assert media._native_protocol_markers == []
    rendered_collections = "\n".join(
        [
            repr(listener._native_marker_tail),
            repr(getattr(listener, "_native_protocol_markers", [])),
            repr(media._native_marker_tail),
            repr(media._native_protocol_markers),
        ]
    )
    assert "1234" not in rendered_collections
    assert "1234abcd" not in rendered_collections
    summary_messages = [
        record.message
        for record in caplog.records
        if "safe_native_markers=" in record.message
        or "protocol_native_markers=" in record.message
    ]
    assert summary_messages
    assert all("1234" not in message for message in summary_messages)
    assert all("1234abcd" not in message for message in summary_messages)


def test_t11_probe_values_absent_from_shadow_snapshot():
    controller = ring_shadow.RingShadowController()
    for line in _complete_batch():
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    rendered = repr(controller.snapshot()) + repr(controller.snapshot_view())
    assert "1234abcd" not in rendered
    assert "1234" not in rendered


def test_t12_probe_values_absent_from_failure_dump():
    instance = _listener()

    _feed(instance, _complete_batch())
    instance._last_native_failure_markers = list(instance._native_marker_tail)

    rendered = repr(instance._native_marker_tail) + repr(
        instance._last_native_failure_markers
    )
    assert "1234abcd" not in rendered
    assert "1234" not in rendered


def test_t13_global_safe_value_regexes_unchanged():
    assert (
        runtime._NATIVE_MARKER_SAFE_VALUE_RE.pattern
        == "^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|"
        "REJECTED|REJECTED_NOT_READY|FAILED_SAFE|[0-9]{1,10})$"
    )
    assert (
        media_transport._MEDIA_NATIVE_MARKER_SAFE_VALUE_RE.pattern
        == "^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|ACTIVE_MEDIA_SINGLE|"
        "UNKNOWN_OUTCOME|REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|"
        "SIGNAL_STAGE|MEDIA_FORWARDING|RTPC_STAGE|PSEUDOTCP|GRACEFUL_STOP|CTPP|"
        "TX_PENDING|REFRESH_OUTSTANDING|REFRESH_FAIL_CLOSED|INITIAL_001A|"
        "DOOR_INFLIGHT|DOOR_ALREADY_SENT|"
        "CALL_INIT|DEVICE_TO_CLIENT|ABSENT|AMBIGUOUS|STRUCTURAL_ACK|STATE_SCOPED_STRUCTURAL|"
        "FATAL|NONE|[0-9]{1,20}|[0-9]{1,3}(?:,[0-9]{1,3}){0,127})$"
    )


def test_t14_listener_production_visible_digest_unchanged_by_probe_lines():
    base_lines = _fixture_lines("01_listener_ring_call1.golden.txt")
    lines = _insert_probe_batch(base_lines)

    assert run_listener_replay(str(ROOT), lines, shadow_enabled=True) == (
        run_listener_replay(str(ROOT), base_lines, shadow_enabled=True)
    )


def test_t15_media_production_visible_digest_unchanged_by_probe_lines():
    base_lines = _fixture_lines("03_media_owner_ring.golden.txt")
    lines = _insert_probe_batch(base_lines)

    assert run_media_replay(str(ROOT), lines, shadow_enabled=True) == (
        run_media_replay(str(ROOT), base_lines, shadow_enabled=True)
    )
