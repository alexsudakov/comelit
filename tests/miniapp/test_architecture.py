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


def test_miniapp_diagnostics_have_closed_schema_and_session_gate():
    diagnostics = _read("custom_components/comelit/miniapp/diagnostics.py")
    views = _read("custom_components/comelit/miniapp/views.py")

    assert "EVENTS = (" in diagnostics
    assert "PLAYER_STATES = (" in diagnostics
    assert "FALLBACK_REASONS = (" in diagnostics
    assert "HLS_ERROR_KINDS = (" in diagnostics
    assert "_REDACTION_GUARD = re.compile" in diagnostics
    assert "free_text" not in diagnostics
    assert "message" not in diagnostics
    assert "sdp" in diagnostics
    assert "a=candidate" in diagnostics
    assert "initdata" in diagnostics
    assert "token" in diagnostics
    assert "format_log_line" in diagnostics
    assert "payload.get('event')" not in diagnostics

    assert "MiniAppCameraDiagnosticsView" in views
    assert "/api/comelit/miniapp/camera/{entity_id}/diagnostics" in views
    assert "api:comelit:miniapp:camera_diagnostics" in views
    assert "self._require_session(request)" in views
    assert "self._require_miniapp_marker(request)" in views
    assert "loads_limited(body)" in views
    assert 'invalid_diagnostics_event' in views
    assert "_LOGGER.info(line)" in views
    assert "register_view(MiniAppCameraDiagnosticsView(controller))" in views
    assert "COMELIT_MINIAPP_HA_TOKEN" not in diagnostics + views
    assert "Long-Lived Access Token" not in diagnostics + views


def test_surveillance_video_is_bounded_to_mobile_viewport():
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert "miniapp-video-shell.surveillance" in host
    assert "height: clamp(180px, 34dvh, 320px)" in host
    assert "object-fit: contain" in host
    assert 'this.attachShadow({mode: "open"})' in host
    assert "this.shadowRoot.replaceChildren(style, content)" in host


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


def test_surveillance_prefers_mse_then_webrtc_then_hls_for_ordinary_cameras():
    controller = _read("custom_components/comelit/miniapp/controller.py")
    views = _read("custom_components/comelit/miniapp/views.py")
    go2rtc = _read("custom_components/comelit/miniapp/go2rtc.py")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    docs = _read("docs/miniapp-architecture.md")

    assert "camera.stream_source()" in docs
    assert "HA-managed go2rtc" in docs
    assert "MSE -> WebRTC -> HLS" in docs
    assert "MiniAppCameraMSEView" in views
    assert "/api/comelit/miniapp/camera/{entity_id}/mse" in views
    assert "MSE_MAX_COMMAND_BYTES" in views
    assert "invalid_mse_command" in views
    assert "stream_source = await camera.stream_source()" in controller
    assert "comelit_miniapp_" in controller
    assert 'getattr(self._hass, "data", {})' in go2rtc
    assert "go2rtc_client" not in go2rtc
    assert "_openMSE(entityId, generation)" in host
    assert "_openWebRTC(entityId, generation)" in host
    assert "_fallbackToHls" in host


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
    assert "const mediaStartTime = performance.now()" in host
    assert 'mediaElapsed >= 5' in host
    assert 'mediaElapsed >= 8' in host
    assert 'bytesReceived === 0' in host
    assert '["new", "checking", "disconnected", "failed"]' in host
    assert "fallback HLS" in host
    assert 'offerSdp += "a=" + candidate.candidate + "\\r\\n"' in host


def test_video_viewport_uses_explicit_stage_and_playback_mode_guard():
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert ".miniapp-video-stage" in host
    assert "height: clamp(180px, 34dvh, 320px)" in host
    assert "width: 100%; height: 100%" in host
    assert "object-fit: contain" in host
    assert 'stage.className = "miniapp-video-stage"' in host
    assert 'this._playbackMode = "webrtc"' in host
    assert 'this._playbackMode = "hls"' in host
    assert 'this._playbackMode !== "webrtc"' in host
    assert "misreported as a successful WebRTC frame" in host


def test_miniapp_frontend_assets_are_release_versioned_and_stage_is_contained():
    html = _read("custom_components/comelit/miniapp/index.html")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")

    assert "styles.css?v=1.7.5" in html
    assert "comelit-card.js?v=1.7.5" in html
    assert "hls.min.js?v=1.7.5" in html
    assert "webcodecs.js?v=1.7.5" in html
    assert "host.js?v=1.7.5" in html
    assert "contain: layout paint size" in host
    assert "overflow: hidden" in host


def test_webcodecs_tab_is_miniapp_flag_gated_and_canvas_only():
    card = _read("custom_components/comelit/frontend/comelit-card.js")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    viewer = _read("custom_components/comelit/frontend/miniapp/webcodecs.js")
    html = _read("custom_components/comelit/miniapp/index.html")

    assert 'get("webcodecs_debug") === "1"' in host
    assert "enabled: webcodecsDebug" in host
    assert "intercom_primary: true" in host
    assert 'config.webcodecs?.enabled === true' in card
    assert 'customElements.get("miniapp-webcodecs-viewer")' in card
    assert "<miniapp-webcodecs-viewer>" in card
    assert "grid-template-columns: repeat(${webcodecsEnabled ? 3 : 2}, 1fr)" in card
    assert "WebCodecs" in card
    assert "_mountIntercomWebCodecsViewer" in card
    assert "_showIntercomLegacyFallback" in card
    assert "data-intercom-legacy-fallback" not in card
    assert "/api/comelit/frontend/miniapp/webcodecs.js" in html

    assert "Запустить тест" in viewer
    assert "Остановить" in viewer
    assert "<canvas" in viewer
    assert "<video" not in viewer
    for token in ("MediaSource", "Hls", "RTCPeerConnection", "/mse", "/webrtc"):
        assert token not in viewer


def test_shared_card_default_config_preserves_two_top_level_tabs():
    card = _read("custom_components/comelit/frontend/comelit-card.js")

    assert 'webcodecs: {' in card
    assert 'enabled: webcodecsEnabled' in card
    assert 'webcodecsEnabled ? `' in card
    assert 'data-tab="webcodecs"' in card
    assert '!(nextTab === "webcodecs" && this._webcodecsEnabled())' in card


def test_surveillance_webcodecs_primary_reuses_validated_transport_with_legacy_fallback():
    card = _read("custom_components/comelit/frontend/comelit-card.js")
    host = _read("custom_components/comelit/frontend/miniapp/host.js")
    viewer = _read("custom_components/comelit/frontend/miniapp/webcodecs.js")
    server = _read("custom_components/comelit/miniapp/webcodecs.py")

    assert "surveillance_primary: true" in host
    assert "config.webcodecs?.surveillance_primary === true" in card
    assert "_mountSurveillanceWebCodecsViewer" in card
    assert "_showSurveillanceLegacyFallback" in card
    assert "_mountLegacySurveillanceViewer" in card
    assert "Переключение на резервный MSE/WebRTC/HLS" in card
    assert "_canPreserveSurveillanceWebCodecsViewer" in card
    assert 'selectedCamera?.kind === "intercom_entrance"' in viewer
    assert "WEBCODECS_MAX_SESSION_SECONDS = 600" in server


def test_entrance_tab_switch_uses_bounded_warm_park_without_hidden_decoder():
    card = _read("custom_components/comelit/frontend/comelit-card.js")
    viewer = _read("custom_components/comelit/frontend/miniapp/webcodecs.js")
    controller = _read("custom_components/comelit/miniapp/controller.py")
    views = _read("custom_components/comelit/miniapp/views.py")

    assert "_parkAndDisconnectIntercomViewer" in card
    assert "await viewer.parkEntrance()" in card
    assert 'target.replaceChildren()' in card
    assert '"/api/comelit/miniapp/entrance/park"' in viewer
    assert "_WEBCODECS_ENTRANCE_PARK_SECONDS = 60.0" in controller
    assert 'reason=_WEBCODECS_ENTRANCE_PARK_REASON' in controller
    assert 'reason=_WEBCODECS_ENTRANCE_VIEWER_REASON' in controller
    assert "MiniAppEntranceParkView" in views


def test_entrance_webcodecs_primary_has_bounded_startup_and_hls_cleanup_barrier():
    card = _read("custom_components/comelit/frontend/comelit-card.js")
    viewer = _read("custom_components/comelit/frontend/miniapp/webcodecs.js")
    controller = _read("custom_components/comelit/miniapp/controller.py")

    assert "EMBEDDED_STARTUP_TIMEOUT_MS = 15_000" in viewer
    assert '"startup_timeout"' in viewer
    assert 'this._intercomViewerMode = "legacy"' in card
    assert "Переключение на резервный HLS" in card
    assert "_await_webcodecs_entrance_cleanup" in controller
    assert "webcodecs_cleanup_timeout" in controller
    assert "webcodecs_cleanup_conflict" in controller
