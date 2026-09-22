#!/usr/bin/env python3
"""P116/R59 post-call PseudoTCP lifecycle observability tests."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import re
import sys
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNTIME = REPO / "custom_components" / "comelit" / "runtime.py"
SUPERVISOR = REPO / "custom_components" / "comelit" / "supervisor.py"
DOC = ROOT / "research" / "media" / "v1" / "P116_R59_POST_CALL_PSEUDOTCP_LIFECYCLE_FORENSIC.md"
R58_LIVE = Path("/home/hermes/r58-live")


def _install_common_stubs() -> None:
    for name in (
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "custom_components",
        "custom_components.comelit",
        "custom_components.comelit.cloud",
        "custom_components.comelit.oauth",
        "custom_components.comelit.ring_media",
        "custom_components.comelit.sdp",
        "custom_components.comelit.runtime",
        "custom_components.comelit.supervisor",
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
    comelit.__path__ = [str(REPO / "custom_components" / "comelit")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit

    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError
    cloud.ComelitCloudHttpError = RuntimeError
    cloud.async_negotiate_p2p = lambda *args, **kwargs: ""
    sys.modules["custom_components.comelit.cloud"] = cloud
    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sys.modules["custom_components.comelit.oauth"] = oauth
    ring_media = types.ModuleType("custom_components.comelit.ring_media")
    ring_media.RingMediaCoordinator = object
    sys.modules["custom_components.comelit.ring_media"] = ring_media
    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules["custom_components.comelit.sdp"] = sdp


def _load_runtime_module() -> types.ModuleType:
    _install_common_stubs()
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.runtime",
        RUNTIME,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_supervisor_module() -> types.ModuleType:
    runtime = _load_runtime_module()
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.supervisor",
        SUPERVISOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["custom_components.comelit.runtime"] = runtime
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEvent:
    def __init__(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() for line in lines]

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)


def _runtime_instance(module: types.ModuleType) -> object:
    runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
    runtime._task = None
    runtime._listener_ready = _FakeEvent()
    runtime._attached_media_busy = _FakeEvent()
    runtime._attached_media_open = _FakeEvent()
    runtime._attached_media_closed = _FakeEvent()
    runtime._last_ring_event = None
    runtime._last_error = None
    runtime._last_native_exit_code = None
    runtime._last_native_failure_markers = []
    runtime._last_door_result = None
    runtime._door_diagnostic = {}
    runtime._door_result_future = None
    runtime._ring_media = None
    runtime._native_marker_tail = []
    runtime._canary_log_generation = None
    runtime._canary_log_seen = set()
    runtime._post_call_transport_flags = {}
    runtime._post_call_transport_emitted = False
    runtime._ring_lines = []
    runtime._media_diagnostics = module.MediaCallDiagnostics()
    return runtime


async def _feed_runtime_lines(runtime: object, lines: list[str]) -> None:
    await runtime._async_read_output(_FakeProcess(lines))


class P116R59MarkerPlumbingTests(unittest.TestCase):
    def test_prefix_vocabularies_and_redaction_contract(self) -> None:
        module = _load_runtime_module()
        self.assertIn("R37_", module._NATIVE_MARKER_PREFIXES)
        self.assertEqual(
            module._P116_MARKER_VOCABULARIES["R37_PROTOCOL_STOP_RESULT"],
            frozenset({"STOP_SENT", "NO_OP"}),
        )
        self.assertEqual(
            module._P116_MARKER_VOCABULARIES["R37_BOUNDED_STOP_RESULT"],
            frozenset({"STOP_SENT", "REJECTED"}),
        )
        self.assertEqual(
            module._P116_MARKER_VOCABULARIES["R54_TX_STATE"],
            frozenset(
                {
                    "IDLE",
                    "NEED_INVITE_ACK",
                    "WAIT_INVITE_ACK_FLUSH",
                    "NEED_LOCAL_CAPABILITIES",
                    "WAIT_LOCAL_CAPABILITIES_FLUSH",
                    "NEED_LOCAL_ALERTING",
                    "WAIT_LOCAL_ALERTING_FLUSH",
                    "WAIT_PEER_CAPABILITIES",
                    "NEED_PEER_DATA_ACK",
                    "WAIT_PEER_DATA_ACK_FLUSH",
                    "MEDIA_TRIGGER_READY",
                    "TERMINAL_FAILURE",
                }
            ),
        )
        self.assertEqual(
            module._P116_MARKER_VOCABULARIES["R54_TX_SUBJECT"],
            frozenset(
                {
                    "NONE",
                    "INVITE_ACK",
                    "LOCAL_CAPABILITIES",
                    "LOCAL_ALERTING",
                    "PEER_DATA_ACK",
                    "MEDIA_OPEN",
                    "MEDIA_STOP",
                    "OTHER_EXISTING",
                }
            ),
        )

        runtime = _runtime_instance(module)
        runtime._remember_native_marker("R37_PROTOCOL_STOP_RESULT=STOP_SENT")
        runtime._remember_native_marker("R54_TX_STATE=WAIT_PEER_DATA_ACK_FLUSH")
        runtime._remember_native_marker("R54_TX_SUBJECT=MEDIA_STOP")
        runtime._remember_native_marker("R54_TX_STATE=BOGUS")
        runtime._remember_native_marker("Z59_TX_STATE=IDLE")
        self.assertIn("R37_PROTOCOL_STOP_RESULT=STOP_SENT", runtime._native_marker_tail)
        self.assertIn("R54_TX_STATE=WAIT_PEER_DATA_ACK_FLUSH", runtime._native_marker_tail)
        self.assertIn("R54_TX_SUBJECT=MEDIA_STOP", runtime._native_marker_tail)
        self.assertIn("R54_TX_STATE=<redacted>", runtime._native_marker_tail)
        self.assertNotIn("Z59_TX_STATE=IDLE", runtime._native_marker_tail)
        self.assertIsNone(runtime._safe_native_marker_value("R54_TX_STATE", "READY"))

    def test_canary_criteria_are_once_per_generation(self) -> None:
        module = _load_runtime_module()
        runtime = _runtime_instance(module)
        lines = [
            "R42_CALL_GENERATION=1",
            "R37_REMOTE_RELEASE_OBSERVED=true",
            "R37_REMOTE_RELEASE_OBSERVED=true",
            "R37_CAPABILITY_CLEARED_OBSERVED=true",
            "R37_CAPABILITY_CLEARED_OBSERVED=true",
            "R54_TX_STATE=WAIT_PEER_DATA_ACK_FLUSH",
            "R54_TX_STATE=IDLE",
            "R54_TX_SUBJECT=MEDIA_STOP",
            "R54_TX_SUBJECT=NONE",
            "R42_CALL_GENERATION=2",
            "R37_REMOTE_RELEASE_OBSERVED=true",
        ]
        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(_feed_runtime_lines(runtime, lines))
        output = "\n".join(cm.output)
        self.assertEqual(output.count("Comelit canary evidence REMOTE_RELEASE_OBSERVED"), 2)
        self.assertEqual(output.count("Comelit canary evidence CAPABILITY_CLEARED_OBSERVED"), 1)
        self.assertEqual(output.count("Comelit canary evidence TX_STATE_AT_EXIT"), 1)
        self.assertEqual(output.count("Comelit canary evidence TX_SUBJECT_AT_EXIT"), 1)


class P116R59PostCallTransportStateTests(unittest.TestCase):
    def test_derivation_table(self) -> None:
        module = _load_runtime_module()
        cases = {
            "NONE": [
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
            "MEDIA_CLOSED_CALL_OPEN": [
                "R42_CALL_GENERATION=1",
                "R58_STOP_CLOSED=true",
                "R42_MEDIA_CHANNEL_CLOSED=true",
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_NOTIFY_PACKET",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
            "MEDIA_CLOSED_REMOTE_RELEASE": [
                "R42_CALL_GENERATION=1",
                "R42_MEDIA_CHANNEL_CLOSED=true",
                "R37_REMOTE_RELEASE_OBSERVED=true",
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_NOTIFY_PACKET",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
            "MEDIA_CLOSED_TEARDOWN_COMPLETE": [
                "R42_CALL_GENERATION=1",
                "R42_MEDIA_CHANNEL_CLOSED=true",
                "R37_REMOTE_RELEASE_OBSERVED=true",
                "R58_STOP_CLOSED=true",
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_NOTIFY_PACKET",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
            "TRANSPORT_CLOSED": [
                "R42_CALL_GENERATION=1",
                "R42_MEDIA_CHANNEL_CLOSED=true",
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
            "UNKNOWN": [
                "R42_CALL_GENERATION=1",
                "R42_MEDIA_CHANNEL_CLOSED=true",
                "R37_CAPABILITY_CLEARED_OBSERVED=true",
                "P116_NATIVE_FAILURE_ID=PSEUDOTCP_NOTIFY_PACKET",
                "P116_NATIVE_FAILURE_COUNT=1",
            ],
        }
        for expected, lines in cases.items():
            with self.subTest(expected=expected):
                runtime = _runtime_instance(module)
                with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
                    asyncio.run(_feed_runtime_lines(runtime, lines))
                output = "\n".join(cm.output)
                self.assertIn(
                    "Comelit canary evidence POST_CALL_TRANSPORT_STATE "
                    f"marker=POST_CALL_TRANSPORT_STATE value={expected}",
                    output,
                )
                self.assertEqual(
                    output.count("Comelit canary evidence POST_CALL_TRANSPORT_STATE"),
                    1,
                )


class _FakeEntry:
    def async_create_background_task(self, hass: object, coro: object, name: str) -> asyncio.Task[None]:
        return asyncio.create_task(coro)


class _FakeRuntime:
    def __init__(self) -> None:
        self._running = False
        self.listener_ready = False
        self.last_error: str | None = None
        self.start_times: list[float] = []
        self.active_sessions = 0
        self.max_active_sessions = 0
        self.door_actions = 0
        self.media_actions = 0
        self.registration_complete: list[int] = []
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        return self._running

    @property
    def attached_media_busy(self) -> bool:
        return False

    async def async_start(self) -> None:
        attempt = len(self.start_times) + 1
        self.start_times.append(time.monotonic())
        self._running = True
        self.listener_ready = False
        self.last_error = None
        self.active_sessions += 1
        self.max_active_sessions = max(self.max_active_sessions, self.active_sessions)
        self._tasks.append(asyncio.create_task(self._run_attempt(attempt)))

    async def _run_attempt(self, attempt: int) -> None:
        try:
            if attempt == 1:
                await asyncio.sleep(0.02)
                self.registration_complete.append(attempt)
                self.listener_ready = True
                await asyncio.sleep(0.02)
                self.last_error = "native_exit:6"
                self.listener_ready = False
                self._running = False
            elif attempt == 2:
                await asyncio.sleep(0.02)
                self.last_error = "native_exit:6"
                self._running = False
            else:
                await asyncio.sleep(0.02)
                self.registration_complete.append(attempt)
                self.listener_ready = True
                while self._running:
                    await asyncio.sleep(0.01)
        finally:
            self.active_sessions -= 1

    async def async_stop(self) -> None:
        self._running = False
        self.listener_ready = False
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def status(self) -> dict[str, object]:
        return {
            "running": self._running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": False,
            "last_error": self.last_error,
            "last_native_exit_code": 6 if self.last_error else None,
            "last_native_failure_markers": [],
        }


class P116R59SupervisorReconnectHarnessTests(unittest.TestCase):
    def test_reconnect_delay_no_overlap_and_ready_after_registration(self) -> None:
        module = _load_supervisor_module()
        fake_runtime = _FakeRuntime()
        supervisor = module.ComelitRuntimeSupervisor(object(), fake_runtime, entry=_FakeEntry())
        ready_seen_after_registration: list[bool] = []

        def status_listener() -> None:
            if supervisor.state == module.LISTENER_STATE_READY:
                ready_seen_after_registration.append(3 in fake_runtime.registration_complete)

        supervisor.async_add_status_listener(status_listener)

        async def scenario() -> None:
            with mock.patch.object(module, "RECONNECT_DELAY_SECONDS", 0.05), mock.patch.object(
                module, "POLL_INTERVAL_SECONDS", 0.01
            ):
                with self.assertLogs("custom_components.comelit.supervisor", level="WARNING") as cm:
                    await supervisor.async_start()
                    deadline = time.monotonic() + 1.0
                    while (
                        len(fake_runtime.start_times) < 3
                        or supervisor.state != module.LISTENER_STATE_READY
                    ):
                        if time.monotonic() > deadline:
                            self.fail("supervisor did not reach READY on attempt 3")
                        await asyncio.sleep(0.01)
                    await supervisor.async_stop()
                output = "\n".join(cm.output)
                self.assertIn("RECONNECT_ATTEMPT=1", output)
                self.assertIn("RECONNECT_ATTEMPT=2", output)
                self.assertIn("RECONNECT_REASON=NATIVE_FAILURE_EXIT", output)

        asyncio.run(scenario())
        self.assertLessEqual(supervisor.reconnect_count, 2)
        self.assertEqual(fake_runtime.max_active_sessions, 1)
        self.assertEqual(fake_runtime.door_actions, 0)
        self.assertEqual(fake_runtime.media_actions, 0)
        self.assertIn(False, ready_seen_after_registration)
        self.assertTrue(ready_seen_after_registration[-1])
        self.assertGreaterEqual(fake_runtime.start_times[1] - fake_runtime.start_times[0], 0.04)
        self.assertGreaterEqual(fake_runtime.start_times[2] - fake_runtime.start_times[1], 0.04)


def _evidence_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(R58_LIVE.glob("*.txt"))
    )


def _timestamp_matches_ms(text: str, marker: str) -> list[int]:
    matches = re.findall(rf"2026-09-22 (\d\d):(\d\d):(\d\d)\.(\d{{3}}).*{re.escape(marker)}", text)
    if not matches:
        raise AssertionError(f"missing marker timestamp: {marker}")
    out: list[int] = []
    for match in matches:
        hour, minute, second, ms = (int(part) for part in match)
        out.append(((hour * 60 + minute) * 60 + second) * 1000 + ms)
    return out


class P116R59EvidenceAndRegressionTests(unittest.TestCase):
    def test_measured_post_call_unavailable_ms_matches_doc_formula(self) -> None:
        text = _evidence_text()
        # Window boundary is the *media cleanup completion*, not the crash:
        # the user-visible unavailability starts when the attached media
        # channel reports CLOSED and ends at the next fresh READY.
        closed_ms = _timestamp_matches_ms(
            text,
            "Comelit attached inbound media CLOSED",
        )[0]
        exit_ms = _timestamp_matches_ms(
            text,
            "NATIVE_FAILURE_COUNT marker=P116_NATIVE_FAILURE_COUNT value=1",
        )[0]
        ready_ms = min(
            value
            for value in _timestamp_matches_ms(
                text,
                "Comelit ring listener READY for persistent 3300s cycle",
            )
            if value > closed_ms
        )
        computed = ready_ms - closed_ms
        doc = DOC.read_text(encoding="utf-8")
        self.assertEqual(computed, 51209)
        self.assertIn("POST_CALL_UNAVAILABLE_MS=51209", doc)
        # The second, crash-anchored boundary is documented for reference only.
        self.assertEqual(ready_ms - exit_ms, 51203)
        self.assertIn("51203ms", doc)

    def test_r58_runtime_marker_contract_still_present(self) -> None:
        # Loaded by file path (not by bare module name) so the regression holds
        # under both `unittest discover -s tests` and
        # `python3 -m unittest tests.<module>` invocation styles.
        r58_path = (
            Path(__file__).resolve().parent
            / "test_p116_r58_attached_media_stop_cleanup.py"
        )
        spec = importlib.util.spec_from_file_location(
            "r59_r58_marker_regression", r58_path
        )
        assert spec is not None and spec.loader is not None
        r58_tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r58_tests)

        module = _load_runtime_module()
        self.assertEqual(
            r58_tests.EXPECTED_HARNESS["R58_HA_CLOSE_CONFIRMATION_REACHED"],
            "true",
        )
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R58_STOP_CLOSED"], "STOP_CLOSED")
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R42_MEDIA_CHANNEL_CLOSED"], "CHANNEL_CLOSED")
        runtime = _runtime_instance(module)
        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(
                _feed_runtime_lines(
                    runtime,
                    [
                        "R42_CALL_GENERATION=1",
                        "R58_STOP_PHASE=REQUESTED",
                        "R58_STOP_CLOSED=true",
                        "R42_MEDIA_CHANNEL_CLOSED=true",
                    ],
                )
            )
        output = "\n".join(cm.output)
        self.assertIn("Comelit canary evidence STOP_PHASE marker=R58_STOP_PHASE value=REQUESTED", output)
        self.assertIn("Comelit canary evidence STOP_CLOSED marker=R58_STOP_CLOSED value=true", output)
        self.assertIn("Comelit canary evidence CHANNEL_CLOSED marker=R42_MEDIA_CHANNEL_CLOSED value=true", output)

    def test_no_forbidden_surface_in_r59_files(self) -> None:
        forbidden = (
            "start" + "AudioTX",
            "entrance_" + "self_activation",
            "P12_TX_ENTRANCE_" + "SELF_ACTIVATION",
            "signal(SIGUSR1, " + "SIG_IGN);",
        )
        for path in (Path(__file__), DOC, SUPERVISOR):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                with self.subTest(path=path.name, needle=needle):
                    self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
