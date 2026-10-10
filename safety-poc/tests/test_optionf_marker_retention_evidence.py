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


class OptionFMarkerRetentionEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_transport_module()
        self.transport = _new_transport(self.module)

    def _set_protocol_limit(self, limit: int) -> None:
        original = self.module._MEDIA_NATIVE_PROTOCOL_MARKER_LIMIT
        self.module._MEDIA_NATIVE_PROTOCOL_MARKER_LIMIT = limit
        self.addCleanup(
            setattr,
            self.module,
            "_MEDIA_NATIVE_PROTOCOL_MARKER_LIMIT",
            original,
        )

    def _retention_evidence(self) -> str:
        return self.transport._native_protocol_marker_retention_evidence()

    def test_t1_entrance_signaling_armed_enters_protocol_storage(self) -> None:
        asyncio.run(_feed_lines(self.transport, ["ENTRANCE_SIGNALING_ARMED=true"]))

        self.assertIn(
            "ENTRANCE_SIGNALING_ARMED=true",
            self.transport._native_protocol_markers,
        )

    def test_t2_self_activation_sent_enters_protocol_storage(self) -> None:
        asyncio.run(
            _feed_lines(self.transport, ["ENTRANCE_SELF_ACTIVATION_SENT=PASS"])
        )

        self.assertIn(
            "ENTRANCE_SELF_ACTIVATION_SENT=PASS",
            self.transport._native_protocol_markers,
        )

    def test_t3_success_summary_logs_safe_native_markers(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                ["ENTRANCE_SIGNALING_ARMED=true", "P116_VIDEO_COUNT=1"],
            )
        )

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="INFO",
        ) as captured:
            self.transport._emit_native_success_summary()

        message = "\n".join(record.getMessage() for record in captured.records)
        self.assertIn("safe_native_markers=", message)
        self.assertIn("protocol_native_markers=", message)
        self.assertIn("PROTOCOL_MARKERS_SEEN_TOTAL=1", message)

    def test_t4_failure_path_keeps_safe_and_protocol_markers(self) -> None:
        async def fail_after_capture() -> None:
            await _feed_lines(
                self.transport,
                ["ENTRANCE_SELF_ACTIVATION_SENT=PASS", "P116_VIDEO_COUNT=1"],
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
        self.assertIn("ENTRANCE_SELF_ACTIVATION_SENT=PASS", message)
        self.assertIn("PROTOCOL_MARKERS_EVICTED=0", message)

    def test_t5_seen_total_counts_duplicate_occurrences_before_dedupe(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                ["REFRESH_SENT_COUNT=1", "REFRESH_SENT_COUNT=1", "REFRESH_SENT_COUNT=1"],
            )
        )

        deduped = list(dict.fromkeys(self.transport._native_protocol_markers))
        self.assertEqual(self.transport._native_protocol_markers_seen_total, 3)
        self.assertEqual(len(self.transport._native_protocol_markers), 3)
        self.assertEqual(deduped, ["REFRESH_SENT_COUNT=1"])

    def test_t6_fifo_counters_and_last_tail_are_preserved(self) -> None:
        self._set_protocol_limit(5)
        asyncio.run(
            _feed_lines(
                self.transport,
                [f"REFRESH_INDEX={index}" for index in range(8)],
            )
        )

        self.assertEqual(self.transport._native_protocol_markers_seen_total, 8)
        self.assertEqual(self.transport._native_protocol_markers_evicted, 3)
        self.assertEqual(len(self.transport._native_protocol_markers), 5)
        self.assertEqual(
            self.transport._native_protocol_markers,
            [f"REFRESH_INDEX={index}" for index in range(3, 8)],
        )
        self.assertIn("PROTOCOL_MARKERS_PRESERVED=5", self._retention_evidence())
        self.assertIn("PROTOCOL_MARKER_FIRST_PRESERVED=REFRESH_INDEX", self._retention_evidence())
        self.assertIn("PROTOCOL_MARKER_LAST_PRESERVED=REFRESH_INDEX", self._retention_evidence())
        self.assertEqual(
            self.transport._native_protocol_markers_seen_total,
            len(self.transport._native_protocol_markers)
            + self.transport._native_protocol_markers_evicted,
        )

    def test_t7_boundary_exposes_ring_marker_eviction_cutoff(self) -> None:
        self._set_protocol_limit(5)
        lines = [
            "REFRESH_SENT_COUNT=1",
            "REFRESH_INDEX=1",
            "REFRESH_CADENCE_SECONDS=20",
            "REFRESH_MONOTONIC_MS=100",
            "REFRESH_RETRY=false",
            "V4_RING_OBSERVED=true",
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            "V4_RING_KIND=CALL_INIT",
            "V4_RING_DOOR=17",
            "V4_RING_SOURCE=2",
            "V4_RING_RAW_PAYLOAD_EMITTED=false",
            "REFRESH_SENT_COUNT=2",
            "REFRESH_INDEX=2",
        ]
        asyncio.run(_feed_lines(self.transport, lines))

        self.assertEqual(
            self.transport._native_protocol_markers,
            [
                "V4_RING_DOOR=17",
                "V4_RING_SOURCE=2",
                "V4_RING_RAW_PAYLOAD_EMITTED=false",
                "REFRESH_SENT_COUNT=2",
                "REFRESH_INDEX=2",
            ],
        )
        evidence = self._retention_evidence()
        self.assertIn("PROTOCOL_MARKERS_EVICTED=8", evidence)
        self.assertIn("PROTOCOL_MARKER_FIRST_PRESERVED=V4_RING_DOOR", evidence)
        self.assertIn("PROTOCOL_MARKER_LAST_PRESERVED=REFRESH_INDEX", evidence)

    def test_t8_counters_do_not_change_run_result_or_stopping(self) -> None:
        async def fail_after_counter_marker() -> None:
            await _feed_lines(self.transport, ["ENTRANCE_SIGNALING_ARMED=true"])
            self.transport._capture_native_failure(6)
            raise self.module.ComelitMediaTransportError("media_native_exit:6")

        self.transport._async_run_cycle = fail_after_counter_marker

        with self.assertLogs(
            "custom_components.comelit.media_transport",
            level="ERROR",
        ):
            result = asyncio.run(self.transport._async_run_once())

        self.assertIsNone(result)
        self.assertEqual(self.transport._last_error, "media_native_exit:6")
        self.assertFalse(self.transport._stopping)
        self.assertEqual(self.transport._native_protocol_markers_seen_total, 1)

    def test_t9_unsafe_values_remain_redacted_for_new_prefixes(self) -> None:
        asyncio.run(
            _feed_lines(
                self.transport,
                [
                    "SELF_ACTIVATION_X=/etc/passwd",
                    "ENTRANCE_FOO=http://10.0.0.1/secret",
                    "ENTRANCE_PAYLOAD={\"token\":\"secret\"}",
                ],
            )
        )

        self.assertEqual(
            self.transport._native_marker_tail,
            [
                "SELF_ACTIVATION_X=<redacted>",
                "ENTRANCE_FOO=<redacted>",
                "ENTRANCE_PAYLOAD=<redacted>",
            ],
        )
        joined = "\n".join(self.transport._native_marker_tail)
        self.assertNotIn("/etc/passwd", joined)
        self.assertNotIn("10.0.0.1", joined)
        self.assertNotIn("secret", joined)

    def test_t10_existing_optionf_observability_contract_fixture_present(self) -> None:
        existing = ROOT / "tests" / "test_optionf_ring_control_marker_observability.py"
        self.assertTrue(existing.exists())


if __name__ == "__main__":
    unittest.main()
