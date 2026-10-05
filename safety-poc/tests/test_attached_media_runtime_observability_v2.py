from pathlib import Path


def test_attached_media_exports_last_rtp_observability() -> None:
    source = Path("custom_components/comelit/attached_media.py").read_text(encoding="utf-8")
    for token in (
        '"attached_rtp_input_packets"',
        '"attached_rtp_last_at"',
        '"attached_rtp_last_age_ms"',
        '**self._transport.diagnostics()',
    ):
        assert token in source


def test_h264_shim_exports_existing_last_rtp_clock() -> None:
    source = Path("custom_components/comelit/h264_recovery.py").read_text(encoding="utf-8")
    assert "def input_diagnostics" in source
    assert "self._last_rtp_monotonic" in source
    assert "last_rtp_age_ms" in source


def test_webcodecs_logs_bounded_source_terminal_cause() -> None:
    source = Path("custom_components/comelit/miniapp/webcodecs.py").read_text(encoding="utf-8")
    assert "COMELIT_MINIAPP_WEBCODECS_SOURCE_TERMINAL" in source
    assert "terminal_cause=source_eof" in source
    assert "terminal_cause=source_transport_closed:%s" in source
    assert "type(exc).__name__" in source
