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
        protocol_markers = (
            "V4_CTPP_OPEN_SENT=PASS",
            "P78_RTPC_OPEN_1_SENT=PASS",
            "P78_RTPC_OPEN_2_SENT=PASS",
            "ICE_GATHER=PASS",
            "ICE_CONNECTED=PASS",
            "ICE_READY=PASS",
            "ICE_CONNECTED_FINAL=true",
            "ICE_READY_FINAL=true",
            "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS",
            "P80_MEDIA_ACTIVE=true",
            "PSEUDOTCP_STATE=READY",
            "CONVERSATION_STATE=OPEN",
            "REMOTE_SDP_BYTES=1234",
        )
        for marker in protocol_markers:
            self.transport._remember_native_marker(marker)
        for index in range(45):
            self.transport._remember_native_marker(f"P116_VIDEO_COUNT={index}")
        self.transport._remember_native_marker("P116_VIDEO_PT_SET=8,99")
        self.transport._remember_native_marker("P116_UNKNOWN=token secret")

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
        self.assertIn("protocol_native_markers=", message)
        self.assertIn("protocol_native_marker_timing=", message)
        self.assertIn("p116_native_markers=", message)
        for marker in protocol_markers:
            self.assertIn(marker, message)
        self.assertIn("P116_VIDEO_PT_SET=8,99", message)
        self.assertIn("P116_UNKNOWN=<redacted>", message)
        self.assertNotIn("token secret", message)

    def test_protocol_marker_timing_counts_repeated_keys(self) -> None:
        with patch.object(media_transport.time, "monotonic", side_effect=[10.0, 10.5, 11.0]):
            self.transport._remember_native_marker("ICE_READY_FINAL=true")
            self.transport._remember_native_marker("ICE_READY_FINAL=true")
            self.transport._remember_native_marker("P80_MEDIA_ACTIVE=true")

        self.assertEqual(
            self.transport._native_protocol_marker_timing["ICE_READY_FINAL"],
            (2, 10000, 10500),
        )
        self.assertEqual(
            self.transport._native_protocol_marker_timing["P80_MEDIA_ACTIVE"],
            (1, 11000, 11000),
        )

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="INFO",
        ) as captured:
            self.transport._emit_native_success_summary()

        message = captured.records[0].getMessage()
        self.assertIn("ICE_READY_FINAL#2@10000-10500", message)
        self.assertIn("P80_MEDIA_ACTIVE#1@11000-11000", message)

    def test_protocol_marker_timestamps_are_non_decreasing(self) -> None:
        with patch.object(media_transport.time, "monotonic", side_effect=[20.0, 19.0]):
            self.transport._remember_native_marker("PSEUDOTCP_OPEN_FINAL=true")
            self.transport._remember_native_marker("PSEUDOTCP_OPEN_FINAL=true")

        self.assertEqual(
            self.transport._native_protocol_marker_timing["PSEUDOTCP_OPEN_FINAL"],
            (2, 20000, 20000),
        )

    def test_protocol_markers_survive_later_p116_progress_flood(self) -> None:
        self.transport._remember_native_marker("V4_CTPP_OPEN_SENT=PASS")
        self.transport._remember_native_marker("P78_RTPC_OPEN_1_SENT=PASS")
        self.transport._remember_native_marker("ICE_READY_FINAL=true")
        self.transport._remember_native_marker("REMOTE_SDP_BYTES=1234")
        for index in range(media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT + 25):
            self.transport._remember_native_marker(f"P116_VIDEO_COUNT={index}")

        self.assertNotIn(
            "V4_CTPP_OPEN_SENT=PASS",
            self.transport._native_marker_tail,
        )
        self.assertLessEqual(
            len(self.transport._native_protocol_markers),
            media_transport._MEDIA_NATIVE_PROTOCOL_MARKER_LIMIT,
        )

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="INFO",
        ) as captured:
            self.transport._emit_native_success_summary()

        message = captured.records[0].getMessage()
        self.assertIn("V4_CTPP_OPEN_SENT=PASS", message)
        self.assertIn("P78_RTPC_OPEN_1_SENT=PASS", message)
        self.assertIn("ICE_READY_FINAL=true", message)
        self.assertIn("REMOTE_SDP_BYTES=1234", message)

    def test_protocol_summary_storage_and_line_are_bounded(self) -> None:
        limit = media_transport._MEDIA_NATIVE_PROTOCOL_MARKER_LIMIT
        for index in range(limit + 20):
            self.transport._remember_native_marker(f"REMOTE_SDP_BYTES={index}")

        self.assertEqual(len(self.transport._native_protocol_markers), limit)
        self.assertLessEqual(
            len(self.transport._native_protocol_marker_timing),
            media_transport._MEDIA_NATIVE_PROTOCOL_TIMING_LIMIT,
        )
        self.assertLessEqual(
            sum(len(item) + 2 for item in self.transport._format_protocol_marker_timing()),
            media_transport._MEDIA_NATIVE_PROTOCOL_TIMING_LINE_LIMIT + 2,
        )
        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="INFO",
        ) as captured:
            self.transport._emit_native_success_summary()

        self.assertEqual(len(captured.records), 1)
        self.assertLess(len(captured.records[0].getMessage()), 4096)

    def test_protocol_marker_timing_family_cap_is_bounded(self) -> None:
        keys = (
            "ICE_READY_FINAL",
            "ICE_CONNECTED_FINAL",
            "PSEUDOTCP_OPEN_FINAL",
            "PSEUDOTCP_STARTED_FINAL",
            "P80_MEDIA_ACTIVE",
            "P80_VIDEO_RTP_FORWARDING",
            "P80_AUDIO_RTP_FORWARDING",
            "P80_DEVICE_ACK_000A_OBSERVED",
            "P80_DEVICE_ACK_001A_OBSERVED",
        )
        for index in range(media_transport._MEDIA_NATIVE_PROTOCOL_TIMING_LIMIT + 10):
            key = keys[index % len(keys)]
            self.transport._remember_native_marker(f"{key}_{index}=PASS")

        self.assertEqual(
            len(self.transport._native_protocol_marker_timing),
            media_transport._MEDIA_NATIVE_PROTOCOL_TIMING_LIMIT,
        )

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
        self.transport._remember_native_marker("REMOTE_SDP_LOADED=token secret")
        self.transport._capture_native_failure(7)

        self.assertEqual(self.transport.last_native_exit_code, 7)
        self.assertEqual(
            self.transport.last_native_failure_markers,
            [
                "P116_VIDEO_COUNT=1",
                "P116_VIDEO_PAYLOAD=<redacted>",
                "REMOTE_SDP_LOADED=<redacted>",
            ],
        )

    def test_p116_markers_are_not_media_activation_drivers(self) -> None:
        self.transport._remember_native_marker("P116_VIDEO_COUNT=1")
        self.transport._remember_native_marker("P116_AUDIO_COUNT=1")
        self.transport._remember_native_marker("ICE_READY=PASS")
        self.transport._remember_native_marker("REMOTE_SDP_BYTES=1234")

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
