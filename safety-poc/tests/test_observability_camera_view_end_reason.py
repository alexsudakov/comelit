from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
CAMERA = COMPONENT / "camera.py"

CAMERA_VIEW_END_REASONS = (
    "camera_view_missing",
    "media_owner_inactive",
    "camera_view_absolute_timeout",
    "stream_outputs_unavailable",
    "hls_idle",
    "last_stream_provider_removed",
    "provider_never_started",
)

_STUB_MODULES = (
    "custom_components",
    "custom_components.comelit",
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.camera",
    "homeassistant.components.camera.const",
    "homeassistant.components.stream",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_platform",
    "custom_components.comelit.attached_media",
    "custom_components.comelit.const",
    "custom_components.comelit.latency_timeline",
    "custom_components.comelit.media_session",
    "custom_components.comelit.media_transport",
    "custom_components.comelit.ring_media",
    "custom_components.comelit.camera",
)


def _install_camera_stubs() -> None:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(COMPONENT)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.comelit", comelit)

    camera_module = types.ModuleType("homeassistant.components.camera")

    class Camera:
        def __init__(self) -> None:
            self.stream = None

        @property
        def available(self) -> bool:
            return True

    class CameraEntityFeature:
        STREAM = 1

    camera_module.Camera = Camera
    camera_module.CameraEntityFeature = CameraEntityFeature
    camera_module.get_dynamic_camera_stream_settings = lambda *args, **kwargs: None
    camera_const = types.ModuleType("homeassistant.components.camera.const")
    camera_const.DATA_CAMERA_PREFS = "camera_prefs"
    stream_module = types.ModuleType("homeassistant.components.stream")
    stream_module.Stream = object
    stream_module.HLS_PROVIDER = "hls_provider"
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = RuntimeError
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object

    sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    sys.modules.setdefault("homeassistant.components", types.ModuleType("homeassistant.components"))
    sys.modules["homeassistant.components.camera"] = camera_module
    sys.modules["homeassistant.components.camera.const"] = camera_const
    sys.modules["homeassistant.components.stream"] = stream_module
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    attached_media = types.ModuleType("custom_components.comelit.attached_media")
    attached_media.ComelitAttachedMediaError = RuntimeError
    attached_media.ComelitAttachedRingMediaSession = object
    attached_media.ComelitAttachedRingMediaTransport = object
    const = types.ModuleType("custom_components.comelit.const")
    for name in (
        "DATA_ATTACHED_MEDIA_PROVIDERS",
        "DATA_ATTACHED_MEDIA_SESSIONS",
        "DATA_ATTACHED_MEDIA_TRANSPORTS",
        "DATA_MEDIA_PROVIDERS",
        "DATA_MEDIA_SESSIONS",
        "DATA_MEDIA_TRANSPORTS",
    ):
        setattr(const, name, name.lower())
    const.DOMAIN = "comelit"
    const.ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"
    const.ENTRANCE_CAMERA_UNIQUE_ID = "comelit_entrance_camera"
    latency = types.ModuleType("custom_components.comelit.latency_timeline")
    latency.CameraRequestLatencyTimeline = MagicMock
    for name in (
        "T00_CAMERA_REQUEST",
        "T01_LEASE_ACQUIRE_BEGIN",
        "T18_HA_STREAM_READY",
        "T19_HLS_PROVIDER_PRESENT",
        "T20_HLS_FIRST_PART",
        "T21_HLS_FIRST_COMPLETE_SEGMENT",
    ):
        setattr(latency, name, name)
    media_session = types.ModuleType("custom_components.comelit.media_session")
    media_session.MEDIA_PHASE_ERROR = "error"
    media_session.MEDIA_PHASE_INACTIVE = "inactive"
    media_session.ComelitMediaSessionManager = object
    media_transport = types.ModuleType("custom_components.comelit.media_transport")
    media_transport.ComelitEntranceMediaTransport = object
    ring_media = types.ModuleType("custom_components.comelit.ring_media")
    ring_media.HAStreamMediaProvider = object

    sys.modules["custom_components.comelit.attached_media"] = attached_media
    sys.modules["custom_components.comelit.const"] = const
    sys.modules["custom_components.comelit.latency_timeline"] = latency
    sys.modules["custom_components.comelit.media_session"] = media_session
    sys.modules["custom_components.comelit.media_transport"] = media_transport
    sys.modules["custom_components.comelit.ring_media"] = ring_media


def _load_camera_module():
    previous = {name: sys.modules.get(name) for name in _STUB_MODULES}
    _install_camera_stubs()
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.camera",
        CAMERA,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, old_module in previous.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module
    return module


camera_mod = _load_camera_module()


class CameraViewEndReasonDiagnosticTests(unittest.TestCase):
    def _camera(self):
        manager = MagicMock()
        manager.phase = "inactive"
        manager.hard_limit_seconds = 600
        manager.status.return_value = {
            "active": False,
            "phase": "inactive",
            "expires_at": None,
            "remaining_seconds": 0,
            "listener_paused": False,
        }
        transport = MagicMock()
        transport.video_forwarding = False
        transport.audio_forwarding = False
        transport.video_packet_count = 0
        transport.audio_packet_count = 0
        transport.video_last_packet_age_seconds = None
        transport.audio_last_packet_age_seconds = None
        transport.video_recovery_diagnostics.return_value = {}
        transport.native_runtime_identity_diagnostics.return_value = {
            "native_binary_sha256": "unreadable",
            "native_binary_expected_sha256": "0" * 64,
            "native_binary_sha256_match": False,
        }
        transport.native_marker_diagnostics.return_value = {
            "refresh_sent_count": None,
            "refresh_last_index": None,
            "refresh_cadence_seconds": None,
            "refresh_last_monotonic_ms": None,
            "refresh_overlap": None,
            "refresh_retry": None,
            "refresh_fail_closed": None,
        }
        camera = camera_mod.ComelitEntranceCamera(
            manager,
            transport,
            media_provider=MagicMock(),
        )

        async def reset_stream() -> None:
            camera.stream = None

        async def release_media() -> bool:
            camera._camera_view_owner = None
            return True

        camera._async_reset_stream = reset_stream
        camera._async_release_camera_view_media = release_media
        camera._hls_runtime_diagnostics = lambda: {}
        camera._hls_http_boundary_diagnostics = lambda: {}
        return camera

    def test_end_reason_is_last_only_and_readable_after_teardown(self) -> None:
        camera = self._camera()

        async def run() -> None:
            for reason in CAMERA_VIEW_END_REASONS:
                result = await camera._async_end_camera_view(reason)
                self.assertTrue(result)
                attrs = camera.extra_state_attributes
                self.assertEqual(attrs["camera_view_last_end_reason"], reason)
                self.assertRegex(
                    attrs["camera_view_last_end_at"],
                    r"^\d{4}-\d{2}-\d{2}T.*\+00:00$",
                )

        asyncio.run(run())
        self.assertEqual(
            camera.extra_state_attributes["camera_view_last_end_reason"],
            CAMERA_VIEW_END_REASONS[-1],
        )

    def test_new_diagnostics_are_sanitized_scalars(self) -> None:
        camera = self._camera()
        asyncio.run(camera._async_end_camera_view("hls_idle"))
        attrs = camera.extra_state_attributes
        for key in (
            "native_binary_sha256",
            "native_binary_expected_sha256",
            "camera_view_last_end_reason",
            "camera_view_last_end_at",
            "refresh_sent_count",
            "refresh_fail_closed",
        ):
            value = attrs[key]
            self.assertFalse(isinstance(value, (list, dict, bytes, bytearray)))
            self.assertNotIn("/home/", str(value))
            self.assertNotIn("/tmp/", str(value))
            self.assertNotIn("secret", str(value).lower())


if __name__ == "__main__":
    unittest.main()
