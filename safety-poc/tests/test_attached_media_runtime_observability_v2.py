from pathlib import Path


def test_attached_media_exports_last_rtp_observability() -> None:
    source = Path("custom_components/comelit/attached_media.py").read_text(encoding="utf-8")
    for token in (
        '"ring_video_last_rtp_monotonic"',
        '"ring_video_last_rtp_age_seconds"',
        '"ring_video_last_rtp_packet_count"',
    ):
        assert token in source
    assert "self._last_rtp_monotonic = time.monotonic()" in source


def test_webcodecs_preserves_bounded_transport_failure_class() -> None:
    source = Path("custom_components/comelit/miniapp/webcodecs.py").read_text(encoding="utf-8")
    assert "terminal_cause" in source
    assert "source_transport_closed:" in source
    assert "type(exc).__name__" in source


def test_webcodecs_logs_bounded_transport_cause_without_raw_exception_text() -> None:
    source = Path("custom_components/comelit/miniapp/views.py").read_text(encoding="utf-8")
    assert '"source_transport_closed"' in source
    assert "transport_cause=" in source
    start = source.find("async def produce_units")
    end = source.find("source_task =", start)
    assert start >= 0 and end > start
    assert "str(exc)" not in source[start:end]
