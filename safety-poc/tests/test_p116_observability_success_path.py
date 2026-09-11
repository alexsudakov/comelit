#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
TRANSPORT = COMPONENT / "media_transport.py"
DIAGNOSTICS = COMPONENT / "media_diagnostics.py"


def _install_stub_modules() -> None:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(COMPONENT)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.comelit", comelit)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules.setdefault("aiohttp", aiohttp)

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.core", core)

    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError

    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""

    cloud.async_negotiate_p2p = async_negotiate_p2p
    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules.setdefault("custom_components.comelit.cloud", cloud)
    sys.modules.setdefault("custom_components.comelit.oauth", oauth)
    sys.modules.setdefault("custom_components.comelit.sdp", sdp)


def _load_transport_module():
    _install_stub_modules()
    diag_spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.media_diagnostics",
        DIAGNOSTICS,
    )
    assert diag_spec is not None and diag_spec.loader is not None
    diagnostics = importlib.util.module_from_spec(diag_spec)
    sys.modules[diag_spec.name] = diagnostics
    diag_spec.loader.exec_module(diagnostics)

    transport_spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.media_transport",
        TRANSPORT,
    )
    assert transport_spec is not None and transport_spec.loader is not None
    transport = importlib.util.module_from_spec(transport_spec)
    sys.modules[transport_spec.name] = transport
    transport_spec.loader.exec_module(transport)
    return transport


media_transport = _load_transport_module()


class P116ObservabilitySuccessPathTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = MagicMock()
        settings.enable_live_media = False
        settings.enable_door = False
        settings.enable_gate = False
        self.transport = media_transport.ComelitEntranceMediaTransport(
            MagicMock(),
            MagicMock(),
            entry=MagicMock(),
            device_uuid="device",
            vip_token="0123456789abcdef0123456789abcdef",
            oauth=MagicMock(),
        )

    def test_success_summary_emits_one_bounded_ha_log_after_sanitized_tail(self) -> None:
        for index in range(45):
            self.transport._remember_native_marker(f"P116_VIDEO_COUNT={index}")
        self.transport._remember_native_marker("P116_VIDEO_PT_SET=8,99")
        self.transport._remember_native_marker("P116_UNKNOWN=token secret")
        self.transport._remember_native_marker("P80_MEDIA_ACTIVE=true")

        self.assertLessEqual(
            len(self.transport._native_marker_tail),
            media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT,
        )
        self.assertIn("P116_UNKNOWN=<redacted>", self.transport._native_marker_tail)

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="INFO",
        ) as captured:
            self.transport._emit_native_success_summary()

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn("p116_native_markers=", message)
        self.assertIn("P116_VIDEO_PT_SET=8,99", message)
        self.assertIn("P116_UNKNOWN=<redacted>", message)
        self.assertNotIn("token secret", message)
        self.assertNotIn("P80_MEDIA_ACTIVE=true", message)

    def test_native_markers_do_not_emit_per_packet_logs(self) -> None:
        with patch.object(media_transport._LOGGER, "info") as info:
            for index in range(10):
                self.transport._remember_native_marker(f"P116_VIDEO_COUNT={index}")
            info.assert_not_called()

            self.transport._emit_native_success_summary()
            info.assert_called_once()

    def test_failure_capture_still_preserves_safe_native_markers(self) -> None:
        self.transport._remember_native_marker("P116_VIDEO_COUNT=1")
        self.transport._remember_native_marker("P116_VIDEO_PAYLOAD=deadbeef")
        self.transport._capture_native_failure(7)

        self.assertEqual(self.transport.last_native_exit_code, 7)
        self.assertEqual(
            self.transport.last_native_failure_markers,
            [
                "P116_VIDEO_COUNT=1",
                "P116_VIDEO_PAYLOAD=<redacted>",
            ],
        )

    def test_p116_markers_are_not_media_activation_drivers(self) -> None:
        self.transport._remember_native_marker("P116_VIDEO_COUNT=1")
        self.transport._remember_native_marker("P116_AUDIO_COUNT=1")

        self.assertFalse(self.transport._media_active.is_set())
        self.assertFalse(self.transport.active)
        self.assertEqual(self.transport._progress.video_packet_count, 0)
        self.assertEqual(self.transport._progress.audio_packet_count, 0)

    def test_success_path_waits_for_reader_before_summary_emission(self) -> None:
        source = TRANSPORT.read_text(encoding="utf-8")
        run_cycle = source.split("async def _async_run_cycle", 1)[1].split(
            "async def _async_read_output", 1
        )[0]

        self.assertLess(
            run_cycle.index("await reader"),
            run_cycle.index("self._emit_native_success_summary()"),
        )
        self.assertLess(
            run_cycle.index("self._emit_native_success_summary()"),
            run_cycle.index("self._capture_native_failure(rc)"),
        )
        self.assertIn("if self._stopping:", run_cycle)


if __name__ == "__main__":
    unittest.main()
