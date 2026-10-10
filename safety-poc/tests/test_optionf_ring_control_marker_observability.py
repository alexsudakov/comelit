#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
COMPONENT = REPO / "custom_components" / "comelit"
TRANSPORT = COMPONENT / "media_transport.py"
DIAGNOSTICS = COMPONENT / "media_diagnostics.py"


def _load_transport_module() -> types.ModuleType:
    for name in (
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "custom_components",
        "custom_components.comelit",
        "custom_components.comelit.cloud",
        "custom_components.comelit.media_diagnostics",
        "custom_components.comelit.oauth",
        "custom_components.comelit.sdp",
        "custom_components.comelit.media_transport",
    ):
        sys.modules.pop(name, None)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(COMPONENT)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit

    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError

    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""

    cloud.async_negotiate_p2p = async_negotiate_p2p
    sys.modules["custom_components.comelit.cloud"] = cloud

    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sys.modules["custom_components.comelit.oauth"] = oauth

    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules["custom_components.comelit.sdp"] = sdp

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


class _FakeBus:
    def async_fire(self, *args: object, **kwargs: object) -> None:
        return None


class _FakeHass:
    def __init__(self) -> None:
        self.bus = _FakeBus()

    async def async_add_executor_job(self, func: object, *args: object) -> None:
        return None


class _FakeEntry:
    def async_create_background_task(
        self,
        hass: object,
        coro: object,
        name: str,
    ) -> asyncio.Task[object]:
        return asyncio.create_task(coro, name=name)


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [f"{line}\n".encode("utf-8") for line in lines]

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)


def _new_transport(module: types.ModuleType) -> object:
    return module.ComelitEntranceMediaTransport(
        _FakeHass(),
        object(),
        entry=_FakeEntry(),
        device_uuid="device",
        vip_token="0123456789abcdef0123456789abcdef",
        oauth=object(),
    )


async def _feed_lines(transport: object, lines: list[str]) -> None:
    await transport._async_read_output(_FakeProcess(lines))


class OptionFRingControlMarkerObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_transport_module()
        self.transport = _new_transport(self.module)

    def test_t1_v4_ring_observed_true_is_preserved(self) -> None:
        asyncio.run(_feed_lines(self.transport, ["V4_RING_OBSERVED=true"]))

        self.assertIn("V4_RING_OBSERVED=true", self.transport._native_marker_tail)
        self.assertIn(
            "V4_RING_OBSERVED=true",
            self.transport._native_protocol_markers,
        )

    def test_t2_v4_ring_kind_call_init_is_preserved_without_redaction(self) -> None:
        asyncio.run(_feed_lines(self.transport, ["V4_RING_KIND=CALL_INIT"]))

        self.assertIn("V4_RING_KIND=CALL_INIT", self.transport._native_marker_tail)
        self.assertIn(
            "V4_RING_KIND=CALL_INIT",
            self.transport._native_protocol_markers,
        )
        self.assertNotIn("V4_RING_KIND=<redacted>", self.transport._native_marker_tail)

    def test_t3_v4_ring_direction_device_to_client_is_preserved(self) -> None:
        asyncio.run(
            _feed_lines(self.transport, ["V4_RING_DIRECTION=DEVICE_TO_CLIENT"])
        )

        self.assertIn(
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            self.transport._native_protocol_markers,
        )

    def test_t4_second_001a_absent_is_preserved(self) -> None:
        asyncio.run(
            _feed_lines(self.transport, ["SECOND_001A_RESPONSE=ABSENT"])
        )

        self.assertIn(
            "SECOND_001A_RESPONSE=ABSENT",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "SECOND_001A_RESPONSE=ABSENT",
            self.transport._native_protocol_markers,
        )

    def test_t5_second_001a_ambiguous_is_preserved(self) -> None:
        asyncio.run(
            _feed_lines(self.transport, ["SECOND_001A_RESPONSE=AMBIGUOUS"])
        )

        self.assertIn(
            "SECOND_001A_RESPONSE=AMBIGUOUS",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "SECOND_001A_RESPONSE=AMBIGUOUS",
            self.transport._native_protocol_markers,
        )

    def test_t6_second_001a_structural_ack_is_preserved(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                ["SECOND_001A_ACK_CLASSIFICATION=STRUCTURAL_ACK"],
            )
        )

        self.assertIn(
            "SECOND_001A_ACK_CLASSIFICATION=STRUCTURAL_ACK",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "SECOND_001A_ACK_CLASSIFICATION=STRUCTURAL_ACK",
            self.transport._native_protocol_markers,
        )

    def test_t7_second_001a_state_scoped_structural_is_preserved(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                ["SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL"],
            )
        )

        self.assertIn(
            "SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL",
            self.transport._native_protocol_markers,
        )

    def test_t8_failure_path_logs_durable_protocol_markers(self) -> None:
        async def fail_after_capture() -> None:
            await _feed_lines(
                self.transport,
                [
                    "V4_RING_KIND=CALL_INIT",
                    "SECOND_001A_RESPONSE=ABSENT",
                    "P116_VIDEO_COUNT=1",
                ],
            )
            self.transport._capture_native_failure(6)
            raise self.module.ComelitMediaTransportError("media_native_exit:6")

        self.transport._async_run_cycle = fail_after_capture

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="ERROR",
        ) as captured:
            asyncio.run(self.transport._async_run_once())

        message = "\n".join(record.getMessage() for record in captured.records)
        self.assertIn("safe_native_markers=", message)
        self.assertIn("protocol_native_markers=", message)
        self.assertIn("V4_RING_KIND=CALL_INIT", message)
        self.assertIn("SECOND_001A_RESPONSE=ABSENT", message)

    def test_t9_unsafe_values_redact_and_unknown_prefix_drops(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                [
                    "V4_RING_KIND=CALL_INIT with extra text",
                    "SECOND_001A_RESPONSE=ABSENT_OR_MAYBE",
                    "P116_VIDEO_PAYLOAD=token secret",
                    "OPTIONF_UNKNOWN=true",
                ],
            )
        )

        self.assertIn("V4_RING_KIND=<redacted>", self.transport._native_marker_tail)
        self.assertIn(
            "SECOND_001A_RESPONSE=<redacted>",
            self.transport._native_marker_tail,
        )
        self.assertIn(
            "P116_VIDEO_PAYLOAD=<redacted>",
            self.transport._native_marker_tail,
        )
        joined = "\n".join(self.transport._native_marker_tail)
        self.assertNotIn("CALL_INIT with extra text", joined)
        self.assertNotIn("ABSENT_OR_MAYBE", joined)
        self.assertNotIn("token secret", joined)
        self.assertTrue(
            all(
                not marker.startswith("OPTIONF_UNKNOWN=")
                for marker in self.transport._native_marker_tail
            )
        )

    def test_protocol_markers_survive_tail_eviction(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                ["V4_RING_KIND=CALL_INIT"]
                + [
                    f"P116_VIDEO_COUNT={index}"
                    for index in range(
                        self.module._MEDIA_NATIVE_MARKER_TAIL_LIMIT + 5
                    )
                ],
            )
        )

        self.assertNotIn("V4_RING_KIND=CALL_INIT", self.transport._native_marker_tail)
        self.assertIn(
            "V4_RING_KIND=CALL_INIT",
            self.transport._native_protocol_markers,
        )


if __name__ == "__main__":
    unittest.main()
