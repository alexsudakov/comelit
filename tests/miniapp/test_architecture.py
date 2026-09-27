from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_miniapp_is_embedded_in_custom_component():
    assert (ROOT / "custom_components/comelit/miniapp/views.py").is_file()
    assert (ROOT / "custom_components/comelit/frontend/miniapp/index.html").is_file()
    assert not (ROOT / "miniapp").exists()


def test_shared_card_is_the_only_intercom_ui():
    html = _read("custom_components/comelit/frontend/miniapp/index.html")
    assert "/api/comelit/frontend/comelit-card.js" in html
    assert '<comelit-card id="comelitCard">' in html
    assert not (
        ROOT / "custom_components/comelit/frontend/miniapp/comelit-card.js"
    ).exists()


def test_embedded_backend_has_no_llat_or_standalone_http_client():
    combined = "\n".join(
        _read(path)
        for path in (
            "custom_components/comelit/miniapp/controller.py",
            "custom_components/comelit/miniapp/views.py",
        )
    )
    forbidden = (
        "COMELIT_MINIAPP_HA_TOKEN",
        "Long-Lived Access Token",
        "httpx",
        "websockets.connect",
        "uvicorn",
        "FastAPI",
    )
    for token in forbidden:
        assert token not in combined


def test_door_path_is_semantic_one_shot():
    controller = _read("custom_components/comelit/miniapp/controller.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    assert 'await self.hass.services.async_call(' in controller
    assert '"button",' in controller
    assert '"press",' in controller
    assert "this method never retries" in controller
    assert "/api/comelit/miniapp/door/" in host
    assert "Never retry the Door action" in host


def test_camera_uses_home_assistant_stream_api_behind_session_proxy():
    controller = _read("custom_components/comelit/miniapp/controller.py")
    views = _read("custom_components/comelit/miniapp/views.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    assert "async_request_stream" in controller
    assert "HLS_PROVIDER" in controller
    assert "/api/comelit/miniapp/media/" in controller
    assert "MiniAppMediaView" in views
    assert "stream_camera" not in controller
    assert "/api/hls/" not in host
