#!/usr/bin/env python3
"""P116/R58 attached-media STOP cleanup corrective tests."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
from unittest import mock
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
RUNTIME = REPO / "custom_components" / "comelit" / "runtime.py"
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r58_attached_media_stop_cleanup_host_harness.c"
DOC_R57 = MEDIA / "P116_R57_CANARY2_LIVE_RESULT.md"
DOC_R58 = MEDIA / "P116_R58_ATTACHED_MEDIA_STOP_CLEANUP_CORRECTIVE.md"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r57_native_failure_attribution_transform as r57  # noqa: E402
import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58  # noqa: E402

EXPECTED_FROZEN_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
EXPECTED_HARNESS = {
    "R58_STOP_NORMAL_PATH": "PASS",
    "R58_STOP_QUEUE_BUSY": "PASS",
    "R58_STOP_DUPLICATE_HA_STOP": "PASS",
    "R58_REMOTE_RELEASE_BEFORE_SIGUSR2": "PASS",
    "R58_REMOTE_RELEASE_AFTER_SIGUSR2": "PASS",
    "R58_SIGUSR2_AFTER_CLOSED": "PASS",
    "R58_STOP_WRITE_FAILURE": "PASS",
    "R58_STOP_FLUSH_TIMEOUT": "PASS",
    "R58_GENERATION_REPLACEMENT": "PASS",
    "R58_EXACTLY_ONE_PROTOCOL_STOP": "PASS",
    "R58_HOST_HARNESS_RESULT": "PASS",
    "R58_STOP_COUNT_MAX": "1",
    "R58_STOP_FLUSHED_BEFORE_CLOSED": "true",
    "R58_HA_CLOSE_CONFIRMATION_REACHED": "true",
    "R58_NO_FALSE_STOP_TIMEOUT": "true",
    "R58_NETWORK_TX": "0",
    "R58_DOOR_ACTIONS": "0",
    "R58_GATE_ACTIONS": "0",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    return begin + text.split(begin, 1)[1].split(end, 1)[0] + end


def _markers(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def _load_runtime_module() -> types.ModuleType:
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

    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.runtime",
        RUNTIME,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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
    runtime._ring_lines = []
    runtime._media_diagnostics = module.MediaCallDiagnostics()
    return runtime


async def _feed_runtime_lines(runtime: object, lines: list[str]) -> None:
    await runtime._async_read_output(_FakeProcess(lines))


class P116R58AttachedMediaStopCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r57_generated = r57.transform(cls.source)
        cls.generated_a = r58.transform(cls.source)
        cls.generated_b = r58.transform(cls.source)
        cls.generated_sha = _sha256(cls.generated_a)
        cls.region = (
            _extract(cls.generated_a, r58.DECLS_BEGIN, r58.DECLS_END)
            + "\n\n"
            + _extract(cls.generated_a, r58.BEGIN, r58.END)
        )
        cls.cc = shutil.which("cc")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            tmp = Path(cls.tmp_obj.name)
            combined = tmp / "r58_harness.c"
            combined.write_text(
                HARNESS.read_text(encoding="utf-8").replace(
                    "/* R58_GENERATED_REGION_INSERT_HERE */",
                    cls.region,
                ),
                encoding="utf-8",
            )
            binary = tmp / "r58_harness"
            result = subprocess.run(
                [
                    cls.cc,
                    "-std=c99",
                    "-Wall",
                    "-Wextra",
                    "-pedantic",
                    str(combined),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
            )
            cls.compile_stderr = result.stderr
            if result.returncode == 0:
                cls.compiled = True
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_stdout = run.stdout
                cls.harness_returncode = run.returncode
                cls.harness_markers = _markers(run.stdout)
            else:
                cls.harness_markers = {}

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    def test_frozen_source_sha_and_determinism(self) -> None:
        self.assertEqual(_sha256(self.source), EXPECTED_FROZEN_SHA256)
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(_sha256(self.generated_a), self.generated_sha)

    def test_cli_sha_is_cwd_independent_and_deterministic(self) -> None:
        script = Path(r58.__file__).resolve()
        cmd = [sys.executable, str(script), "--source", str(SOURCE), "--sha256"]
        a = subprocess.run(cmd, cwd="/tmp", text=True, capture_output=True, check=True)
        b = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, check=True)
        self.assertEqual(a.stdout.strip(), b.stdout.strip())
        self.assertEqual(a.stdout.strip(), self.generated_sha)

    def test_anchor_gates_and_reapply_fire(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "R58_REAPPLY_GATE=FAIL"):
            r58.transform(self.generated_a)
        for name, anchor in r58._ANCHORS:
            with self.subTest(anchor=name):
                bad = self.r57_generated.replace(anchor, "", 1)
                with mock.patch.object(r58.r57, "transform", return_value=bad):
                    with self.assertRaisesRegex(RuntimeError, f"R58_{name}_ANCHOR_GATE=FAIL"):
                        r58.transform("ignored")
                dup = self.r57_generated + "\n" + anchor
                with mock.patch.object(r58.r57, "transform", return_value=dup):
                    with self.assertRaisesRegex(RuntimeError, f"R58_{name}_ANCHOR_GATE=FAIL"):
                        r58.transform("ignored")

    def test_generated_source_shape(self) -> None:
        self.assertIn("candidate = r57.transform(source)", Path(r58.__file__).read_text())
        self.assertEqual(self.generated_a.count('printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");'), 1)
        self.assertIn("r58_stop_publish_closed();\n            break;", self.generated_a)
        self.assertIn("r58_stop_drive(&g_r35_session);\n    fflush(stdout);", self.generated_a)
        self.assertEqual(_extract(self.generated_a, r58.BEGIN, r58.END).count("r35_send_stop("), 1)

    def test_harness_compiles_empty_stderr_and_passes(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        for key, value in EXPECTED_HARNESS.items():
            with self.subTest(key=key):
                self.assertEqual(self.harness_markers.get(key), value, self.harness_stdout)

    def test_runtime_r58_marker_plumbing_and_sanitizer(self) -> None:
        module = _load_runtime_module()
        self.assertIn("R58_", module._NATIVE_MARKER_PREFIXES)
        self.assertEqual(
            module._P116_MARKER_VOCABULARIES["R58_STOP_PHASE"],
            frozenset(
                {
                    "NONE",
                    "REQUESTED",
                    "WAIT_TX_SLOT",
                    "ENQUEUED",
                    "FLUSHED",
                    "RTP_DISARMED",
                    "DISPOSED",
                    "CLOSED",
                    "REMOTE_RELEASE",
                    "FAILED",
                }
            ),
        )
        self.assertEqual(module._P116_MARKER_VOCABULARIES["R58_CLOSED_BOUNDARY"], frozenset({"LOCAL_DISPOSAL_AFTER_STOP_FLUSH"}))
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R58_STOP_CLOSED"], "STOP_CLOSED")
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R58_STOP_FAILED"], "STOP_FAILED")
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R42_MEDIA_CHANNEL_CLOSED"], "CHANNEL_CLOSED")
        self.assertEqual(module._CANARY_OBSERVABILITY_MARKERS["R58_STOP_PHASE"], "STOP_PHASE")

        runtime = _runtime_instance(module)
        runtime._remember_native_marker("R58_STOP_PHASE=NOT_A_PHASE")
        runtime._remember_native_marker("R58_STOP_PHASE=ENQUEUED")
        runtime._remember_native_marker("X58_STOP_PHASE=ENQUEUED")
        self.assertIn("R58_STOP_PHASE=<redacted>", runtime._native_marker_tail)
        self.assertIn("R58_STOP_PHASE=ENQUEUED", runtime._native_marker_tail)
        self.assertNotIn("X58_STOP_PHASE=ENQUEUED", runtime._native_marker_tail)

    def test_stop_phase_value_keyed_dedup_resets_per_generation(self) -> None:
        module = _load_runtime_module()
        runtime = _runtime_instance(module)
        lines = [
            "R42_CALL_GENERATION=1",
            "R58_STOP_PHASE=REQUESTED",
            "R58_STOP_PHASE=REQUESTED",
            "R58_STOP_PHASE=ENQUEUED",
            "R58_STOP_PHASE=ENQUEUED",
            "R58_STOP_CLOSED=true",
            "R58_STOP_CLOSED=true",
            "R42_CALL_GENERATION=2",
            "R58_STOP_PHASE=REQUESTED",
        ]
        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(_feed_runtime_lines(runtime, lines))
        output = "\n".join(cm.output)
        self.assertEqual(output.count("Comelit canary evidence STOP_PHASE marker=R58_STOP_PHASE value=REQUESTED"), 2)
        self.assertEqual(output.count("Comelit canary evidence STOP_PHASE marker=R58_STOP_PHASE value=ENQUEUED"), 1)
        self.assertEqual(output.count("Comelit canary evidence STOP_CLOSED marker=R58_STOP_CLOSED value=true"), 1)

    def test_live_success_path_markers_and_r56_ordering_preserved(self) -> None:
        for needle in (
            'printf("R54_INVITE_ACK_SENT=%s\\n"',
            'printf("R54_LOCAL_CAPABILITIES_SENT=%s\\n"',
            'printf("R54_LOCAL_ALERTING_SENT=%s\\n"',
            'printf("R54_PEER_DATA_ACK_FLUSHED=%s\\n"',
            "R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED",
            "LOCAL_ALERTING_FLUSHED_BEFORE_WAIT_PEER_CAPABILITIES=true",
            "PEER_DATA_ACK_FLUSHED_BEFORE_MEDIA_TRIGGER=true",
        ):
            with self.subTest(needle=needle):
                self.assertEqual(self.generated_a.count(needle), self.r57_generated.count(needle))

    def test_no_forbidden_surface_in_new_files(self) -> None:
        files = (Path(r58.__file__), HARNESS, Path(__file__), DOC_R57, DOC_R58)
        forbidden = (
            "start" + "AudioTX",
            "entrance_" + "self_activation",
            "P12_TX_ENTRANCE_" + "SELF_ACTIVATION",
            "signal(SIGUSR1, " + "SIG_IGN);",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                with self.subTest(path=path.name, needle=needle):
                    self.assertNotIn(needle, text)
        self.assertNotIn("P12_TX_ENTRANCE_" + "SELF_ACTIVATION", self.generated_a)

    def test_docs_exist_and_contain_required_key_blocks(self) -> None:
        r57_doc = DOC_R57.read_text(encoding="utf-8")
        for line in (
            "CALL_ADOPTION_LIVE_PROVEN=true",
            "PEER_CAPABILITIES_LIVE_PROVEN=true",
            "PEER_CAPABILITY_WORD=0x0000001b",
            "PEER_DATA_ACK_FLUSHED=true",
            "SAME_SESSION_MEDIA_OPEN_LIVE_PROVEN=true",
            "RTP_LIVE_PROVEN=true",
            "H264_LIVE_PROVEN=true",
            "USER_VISIBLE_VIDEO_DELIVERY_PROVEN=true",
            "USER_VISIBLE_SCREENSHOT_DELIVERY_PROVEN=true",
            "DOOR_LIVE_TESTED=false",
            "GATE_LIVE_TESTED=false",
        ):
            self.assertIn(line, r57_doc)
        r58_doc = DOC_R58.read_text(encoding="utf-8")
        for line in (
            "STOP_FAILURE_BOUNDARY=DISPOSE_NO_CLOSED_MARKER",
            "MEDIA_STOP_SHARES_P12_TX_QUEUE=true",
            "MEDIA_STOP_USES_R56_SCHEDULER=false",
            "REMOTE_RELEASE_CAN_CLOSE_WITHOUT_SIGUSR2_STOP=true",
            "HA_STOP_TIMEOUT_SECONDS=10",
            "HA_STOP_TIMEOUT_IS_CAUSAL=false",
            "STREAM_WORKER_ERROR_CAUSAL=false",
            "CORRECTED_GENERATED_SOURCE_SHA256=",
            "BUILD_MUSL=RUN_BY_ORCHESTRATOR",
        ):
            self.assertIn(line, r58_doc)


if __name__ == "__main__":
    unittest.main()
