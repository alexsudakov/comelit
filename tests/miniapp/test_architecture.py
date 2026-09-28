from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_miniapp_is_embedded_in_custom_component():
    assert (ROOT / "custom_components/comelit/miniapp/views.py").is_file()
    assert (ROOT / "custom_components/comelit/miniapp/index.html").is_file()
    assert not (ROOT / "custom_components/comelit/frontend/miniapp/index.html").exists()
    assert not (ROOT / "miniapp").exists()


def test_shared_card_is_the_only_intercom_ui():
    html = _read("custom_components/comelit/miniapp/index.html")
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


def test_miniapp_bundles_hls_player_for_non_native_webviews():
    html = _read("custom_components/comelit/miniapp/index.html")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    vendor = ROOT / "custom_components/comelit/frontend/miniapp/vendor/hls.min.js"
    license_file = (
        ROOT / "custom_components/comelit/frontend/miniapp/vendor/hls-LICENSE.txt"
    )

    assert vendor.is_file()
    assert vendor.stat().st_size > 100_000
    assert license_file.is_file()
    assert "/api/comelit/frontend/miniapp/vendor/hls.min.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert "HlsClass.isSupported()" in host
    assert "enableWorker: false" in host
    assert 'video.canPlayType("application/vnd.apple.mpegurl")' in host
    assert "this._hls.destroy()" in host


def test_miniapp_session_failures_do_not_use_ha_raised_401_path():
    views = _read("custom_components/comelit/miniapp/views.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert "raise web.HTTPUnauthorized" not in views
    assert "HTTPForbidden" in views
    assert "Home Assistant's global" in views
    assert "error?.status === 403" in host
    assert "Сессия Mini App завершена." in host


def test_surveillance_video_is_bounded_to_mobile_viewport():
    styles = _read("custom_components/comelit/frontend/miniapp/styles.css")

    assert "miniapp-video-shell.surveillance" in styles
    assert "height: min(34dvh, 320px)" in styles
    assert "object-fit: contain" in styles


def test_surveillance_prefers_session_bound_ha_webrtc_with_hls_fallback():
    controller = _read("custom_components/comelit/miniapp/controller.py")
    views = _read("custom_components/comelit/miniapp/views.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert "StreamType.WEB_RTC" in controller
    assert "get_webrtc_surveillance_camera" in controller
    assert "MiniAppCameraWebRTCView" in views
    assert "/api/comelit/miniapp/camera/{entity_id}/webrtc" in views
    assert "camera.close_webrtc_session(session_id)" in views
    assert "new RTCPeerConnection" in host
    assert "new WebSocket(url)" in host
    assert "_fallbackToHls" in host
    assert "isIntercomCameraEntity(entityId)" in host


def test_webrtc_status_waits_for_actual_first_decoded_frame():
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert "requestVideoFrameCallback" in host
    assert "_markFirstWebRTCFrame" in host
    assert "peer.getStats()" in host
    assert "bytesReceived" in host
    assert "framesDecoded" in host
    assert "track получен, ждём кадр" in host
    assert "первый кадр " in host


def test_webrtc_negotiation_buffers_ice_until_provider_session_ready():
    views = _read("custom_components/comelit/miniapp/views.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert '"type": "session"' in views
    assert "_pendingLocalCandidates" in host
    assert "_webrtcSessionReady" in host
    assert 'peer.addTransceiver("audio"' in host
    assert 'peer.addTransceiver("video"' in host
    assert "offerToReceiveAudio: true" in host
    assert "offerToReceiveVideo: true" in host
    assert "new RTCIceCandidate" in host
    assert 'state === "failed"' in host
    assert "_fallbackToHls(entityId, generation)" in host


def test_webrtc_session_id_precedes_provider_offer_and_zero_rtp_falls_back():
    views = _read("custom_components/comelit/miniapp/views.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    offer_pos = views.index("async_handle_async_webrtc_offer")
    session_pos = views.index('"type": "session"')
    assert session_pos < offer_pos
    assert "ICE " in host
    assert 'elapsed >= 10' in host
    assert 'bytesReceived === 0' in host
    assert '["new", "checking", "disconnected", "failed"]' in host
    assert "fallback HLS" in host
