#!/usr/bin/env python3
"""P116/R54 production-candidate offline gates."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import re
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
MEDIA_DIAGNOSTICS = REPO / "custom_components" / "comelit" / "media_diagnostics.py"
RUNTIME = REPO / "custom_components" / "comelit" / "runtime.py"
CANARY_DOC = MEDIA / "P116_R54_CALL_ADOPTION_PRODUCTION_CANDIDATE_DEPLOY_CANARY.md"
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r54_call_adoption_generated_region_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r42b_listener_attached_media_transform as r42b  # noqa: E402
import entrance_p116_r45_call_adoption_core as r45  # noqa: E402
import entrance_p116_r53_call_adoption_profile_core as r53  # noqa: E402
import entrance_p116_r54_call_adoption_listener_transform as r54  # noqa: E402

EXPECTED_FROZEN_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"

EXPECTED_HARNESS_MARKERS = (
    "R54_GENERATED_ORDERING",
    "R54_PEER_ACK_BEFORE_MEDIA_TRIGGER",
    "R54_RUNTIME_PEER_WORD",
    "R54_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN",
    "R54_VIDEO_BIT_CLEAR_FAIL_CLOSED",
    "R54_FOREIGN_CONNECTION_REJECTED",
    "R54_MALFORMED_PEER_CAPABILITIES_REJECTED",
    "R54_WRITE_FAILURE_FAIL_CLOSED",
    "R54_MISSING_WRITER_FAIL_CLOSED",
)

EXPECTED_R56_HARNESS_MARKERS = (
    "R56_BUSY_WAIT_SERIALIZED",
    "R56_PARTIAL_WRITE_BLOCKS_NEXT_FRAME",
    "R56_PEER_CAP_DURING_LOCAL_TX_STORED",
    "R56_DUPLICATE_CALL_INIT_NO_REPLAY",
    "R56_GENERATION_REPLACED_NO_CROSS_WRITE",
    "R56_RELEASE_TWICE_NO_DOUBLE_ENQUEUE",
    "R56_EARLY_RELEASE_SAFE",
    "R56_QUEUE_BUSY_TIMEOUT_FAIL_CLOSED",
)

CANARY_CRITERIA = (
    ("CALL_INIT_SEEN", "R42_CALL_GENERATION=10", "Comelit canary evidence CALL_INIT_SEEN"),
    ("CALL_ADOPTION_STARTED", "R54_CALL_ADOPTION_STARTED=true", "Comelit canary evidence CALL_ADOPTION_STARTED"),
    ("INVITE_ACK_SENT", "R54_INVITE_ACK_SENT=true", "Comelit canary evidence INVITE_ACK_SENT"),
    ("LOCAL_CAPABILITIES_SENT", "R54_LOCAL_CAPABILITIES_SENT=true", "Comelit canary evidence LOCAL_CAPABILITIES_SENT"),
    ("LOCAL_CAPABILITY_WORD", "R54_LOCAL_CAPABILITY_WORD=39", "Comelit canary evidence LOCAL_CAPABILITY_WORD"),
    ("LOCAL_ALERTING_SENT", "R54_LOCAL_ALERTING_SENT=true", "Comelit canary evidence LOCAL_ALERTING_SENT"),
    ("WAITING_PEER_CAPABILITIES", "R54_WAITING_PEER_CAPABILITIES=true", "Comelit canary evidence WAITING_PEER_CAPABILITIES"),
    ("PEER_CAPABILITIES_SEEN", "R54_PEER_CAPABILITIES_SEEN=true", "Comelit canary evidence PEER_CAPABILITIES_SEEN"),
    ("PEER_CAPABILITY_WORD", "R54_PEER_CAPABILITY_WORD=47", "Comelit canary evidence PEER_CAPABILITY_WORD"),
    ("PEER_VIDEO_REQUESTED", "R54_PEER_VIDEO_REQUESTED=true", "Comelit canary evidence PEER_VIDEO_REQUESTED"),
    ("PEER_DATA_ACK_SENT", "R54_PEER_DATA_ACK_SENT=true", "Comelit canary evidence PEER_DATA_ACK_SENT"),
    ("CALL_ADOPTION_FAILURE_STAGE", "R54_CALL_ADOPTION_FAILURE_STAGE=NONE", "Comelit canary evidence CALL_ADOPTION_FAILURE_STAGE"),
    ("MEDIAREQ26_OPEN_SENT", "R42_MEDIAREQ26_OPEN_CHANNEL=4110", "Comelit canary evidence MEDIAREQ26_OPEN_SENT"),
    ("RTP_RECEIVED", "P80_VIDEO_RTP_FORWARDING=PASS", "Comelit canary evidence RTP_RECEIVED"),
    ("H264_DETECTED", "P116_VIDEO_SPS_COUNT=1", "Comelit canary evidence H264_DETECTED"),
    ("STOP_SENT", "R42_ATTACHED_MEDIA_STOP_SENT=true", "Comelit canary evidence STOP_SENT"),
    ("CHANNEL_CLOSED", "R42_MEDIA_CHANNEL_CLOSED=true", "Comelit attached inbound media CLOSED"),
    ("CLEANUP_COMPLETE", "R42_LISTENER_RTP_FORWARDING_ARMED=false", "Comelit canary evidence CLEANUP_COMPLETE"),
    ("LISTENER_READY_AFTER", "V4_RING_LISTENER_READY=true", "Comelit ring listener READY"),
)

FORBIDDEN_LOG_SUBSTRINGS = (
    "COMELIT_VIP_TOKEN",
    "oauth_access_token",
    "vip_token",
    "auth",
    "token",
    "00112233445566778899aabbccddeeff",
    "192.168.",
    "10.0.",
    "payload",
    "RAW_PAYLOAD",
    "ctp_connection",
    "logical_address",
    "<script>",
    "../../etc/passwd",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    return begin + text.split(begin, 1)[1].split(end, 1)[0] + end


def _parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


def _load_media_diagnostics() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("r54_media_diagnostics", MEDIA_DIAGNOSTICS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    cloud.ComelitCloudHttpError = type(
        "ComelitCloudHttpError",
        (RuntimeError,),
        {"__init__": lambda self, status: setattr(self, "status", status)},
    )

    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""

    cloud.async_negotiate_p2p = async_negotiate_p2p
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

    sys.modules.pop("custom_components.comelit.runtime", None)
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


class P116R54CallAdoptionProductionCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = r54.transform(cls.source)
        cls.generated_b = r54.transform(cls.source)
        cls.generated_sha = _sha256(cls.generated_a)
        cls.cc = shutil.which("cc")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        cls.markers: dict[str, str] = {}

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            tmp = Path(cls.tmp_obj.name)
            harness_template = HARNESS.read_text(encoding="utf-8")
            r54_region = _extract(cls.generated_a, r54.BEGIN, r54.END)
            r54_tx_prelude = _extract(
                cls.generated_a,
                "/* R54_TX_ATTRIBUTION_BEGIN */",
                "/* R54_TX_ATTRIBUTION_END */",
            )
            combined = tmp / "r54_generated_region.c"
            combined.write_text(
                "\n\n".join(
                    (
                        _extract(cls.generated_a, r35.CORE_BEGIN_MARKER, r35.CORE_END_MARKER),
                        _extract(cls.generated_a, r36.TRIGGER_BEGIN_MARKER, r36.TRIGGER_END_MARKER),
                        _extract(cls.generated_a, r45.CORE_BEGIN_MARKER, r45.CORE_END_MARKER),
                        _extract(cls.generated_a, r53.CORE_BEGIN_MARKER, r53.CORE_END_MARKER),
                        r54_tx_prelude,
                        harness_template.replace(
                            "/* R54_GENERATED_REGION_INSERT_HERE */",
                            r54_region,
                        ),
                    )
                ),
                encoding="utf-8",
            )
            binary = tmp / "r54_generated_region"
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
                cls.markers = _parse_markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    def test_frozen_source_sha_gate(self) -> None:
        self.assertEqual(_sha256(self.source), EXPECTED_FROZEN_SHA256)

    def test_transform_refuses_missing_or_duplicated_markers(self) -> None:
        with self.assertRaises(RuntimeError):
            r54.transform(self.source.replace('signal(SIGUSR1, v4_door_signal_handler);\n', ""))
        with self.assertRaises(RuntimeError):
            r54.transform(self.source + '\nsignal(SIGUSR1, v4_door_signal_handler);\n')

    def test_generated_source_is_deterministic(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(_sha256(self.generated_a), self.generated_sha)

    def test_transform_chain_and_contract_markers(self) -> None:
        generated = self.generated_a
        for marker in (
            r35.CORE_BEGIN_MARKER,
            r36.TRIGGER_BEGIN_MARKER,
            r45.CORE_BEGIN_MARKER,
            r53.CORE_BEGIN_MARKER,
            r54.BEGIN,
            "R54_CALL_ADOPTION_STARTED=%s",
            "R54_PEER_DATA_ACK_SENT=%s",
            "R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, generated)
        self.assertNotIn("r53_start_after_call_capture", generated)
        self.assertIn("r45_accept_peer_data_and_ack(", generated)
        self.assertIn("r42_queue_media_channel_open()", generated)

    def test_single_peer_handling_owner_and_media_open_call_site(self) -> None:
        generated = self.generated_a
        r54_region = _extract(generated, r54.BEGIN, r54.END)
        self.assertEqual(
            generated.count("static int r53_handle_peer_capabilities_with_trigger("),
            1,
        )
        self.assertEqual(generated.count("r42_queue_media_channel_open()"), 1)
        self.assertIn("r54_store_pending_peer_capabilities(", r54_region)
        self.assertIn("r45_accept_peer_data_and_ack(", r54_region)
        self.assertNotIn("r53_handle_peer_capabilities_with_trigger(", r54_region)

    def test_profile_word_is_formula_not_capture_literal_or_native_claim(self) -> None:
        text = self.generated_a + "\n" + r54.report()
        self.assertIn("R53_HELPER_CAP_AUDIO_DST", text)
        self.assertIn("| R53_HELPER_CAP_AUDIO_SRC", text)
        self.assertIn("HELPER_CAPABILITY_PROFILE_VALUE=0x00000027", text)
        self.assertIn("CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false", text)
        self.assertIn("CALLFSM_840_POSSIBLY_UNINITIALIZED=true", text)
        for forbidden in (
            "CALLFSM_840_VALUE",
            "CallFsm+840 source proven",
            "00 03 49 00 27 00 00 00",
            "0003490027000000",
        ):
            self.assertNotIn(forbidden, text)

    def test_audio_boundary_and_no_forbidden_live_surfaces(self) -> None:
        for forbidden in (
            "startAudioTX",
            "PT8_GENERATOR",
            "microphone",
            "answer_call",
            "entrance_self_activation",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
            "V4_DOOR_WRITE",
            "P12_TX_V4_DOOR_WRITE,",
        ):
            with self.subTest(forbidden=forbidden):
                if forbidden in {"V4_DOOR_WRITE", "P12_TX_V4_DOOR_WRITE,"}:
                    self.assertNotIn(forbidden, _extract(self.generated_a, r54.BEGIN, r54.END))
                else:
                    self.assertNotIn(forbidden, self.generated_a)

    def test_door_preservation_assertion(self) -> None:
        generated = self.generated_a
        self.assertEqual(generated.count("signal(SIGUSR1, v4_door_signal_handler);"), 1)
        self.assertIn("v4_door_tick_cb", generated)
        self.assertIn("#define RUN_DIR     \"/run/comelit-p2p\"", generated)
        self.assertIn("R42_LISTENER_DOOR_SIGNAL_PRESERVED=true", generated)
        self.assertNotIn("signal(SIGUSR1, SIG_IGN);", generated)

    def test_generated_region_compiles_without_warnings(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    def test_generated_region_behavior_equivalence(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.markers.get("R54_HOST_HARNESS_RESULT"), "PASS")
        for key in EXPECTED_HARNESS_MARKERS:
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS", self.harness_stdout)
        self.assertEqual(self.markers.get("R54_NETWORK_TX"), "0")
        self.assertEqual(self.markers.get("R54_DOOR_ACTIONS"), "0")
        self.assertEqual(self.markers.get("R54_GATE_ACTIONS"), "0")

    def test_r56_single_slot_race_matrix_harness(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        for key in EXPECTED_R56_HARNESS_MARKERS:
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS", self.harness_stdout)
        self.assertEqual(self.markers.get("R56_ENQUEUE_WHILE_BUSY_OBSERVED"), "0")
        self.assertEqual(self.markers.get("R56_SECOND_MEDIA_OPEN_OBSERVED"), "0")

    def test_diagnostics_contract_parses_r54_markers_and_resets_per_generation(self) -> None:
        md = _load_media_diagnostics()
        diag = md.MediaCallDiagnostics(clock=lambda: "2026-09-21T00:00:00+00:00")
        for line in (
            "R42_CALL_GENERATION=10",
            "R54_CALL_ADOPTION_STARTED=true",
            "R54_INVITE_ACK_SENT=true",
            "R54_LOCAL_CAPABILITIES_SENT=true",
            "R54_LOCAL_CAPABILITY_WORD=39",
            "R54_LOCAL_ALERTING_SENT=true",
            "R54_WAITING_PEER_CAPABILITIES=true",
            "R54_PEER_CAPABILITIES_SEEN=true",
            "R54_PEER_CAPABILITY_WORD=47",
            "R54_PEER_VIDEO_REQUESTED=true",
            "R54_PEER_DATA_ACK_SENT=true",
            "R54_CALL_ADOPTION_FAILURE_STAGE=NONE",
        ):
            self.assertTrue(diag.observe_line(line), line)
        snapshot = diag.snapshot()
        self.assertTrue(snapshot["call_adoption_started"])
        self.assertTrue(snapshot["invite_ack_sent"])
        self.assertTrue(snapshot["local_capabilities_sent"])
        self.assertEqual(snapshot["local_capability_word"], 39)
        self.assertTrue(snapshot["local_alerting_sent"])
        self.assertTrue(snapshot["waiting_peer_capabilities"])
        self.assertTrue(snapshot["peer_capabilities_seen"])
        self.assertEqual(snapshot["peer_capability_word"], 47)
        self.assertTrue(snapshot["peer_video_requested"])
        self.assertTrue(snapshot["peer_data_ack_sent"])
        self.assertEqual(snapshot["call_adoption_failure_stage"], "NONE")

        self.assertTrue(diag.observe_line("R54_CALL_ADOPTION_FAILURE_STAGE=RAW_PAYLOAD:abcd"))
        self.assertEqual(diag.snapshot()["call_adoption_failure_stage"], "NONE")

        self.assertTrue(diag.observe_line("R42_CALL_GENERATION=11"))
        reset = diag.snapshot()
        self.assertFalse(reset["call_adoption_started"])
        self.assertIsNone(reset["local_capability_word"])
        self.assertIsNone(reset["peer_capability_word"])
        self.assertIsNone(reset["call_adoption_failure_stage"])

    def test_declared_canary_criteria_are_unique(self) -> None:
        criteria = [criterion for criterion, _marker, _substring in CANARY_CRITERIA]
        substrings = [substring for _criterion, _marker, substring in CANARY_CRITERIA]
        self.assertEqual(len(criteria), 19)
        self.assertEqual(len(criteria), len(set(criteria)))
        self.assertEqual(len(substrings), len(set(substrings)))

    def test_canary_criteria_emit_one_readonly_log_line_each(self) -> None:
        import asyncio

        module = _load_runtime_module()
        runtime = _runtime_instance(module)
        lines = [marker for _criterion, marker, _substring in CANARY_CRITERIA]

        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(_feed_runtime_lines(runtime, lines))

        output = "\n".join(cm.output)
        for criterion, _marker, substring in CANARY_CRITERIA:
            with self.subTest(criterion=criterion):
                self.assertIn(substring, output)
                self.assertEqual(output.count(substring), 1)
        self.assertEqual(len(cm.output), len(CANARY_CRITERIA))
        for forbidden in FORBIDDEN_LOG_SUBSTRINGS:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, output)

    def test_canary_logs_are_bounded_once_per_generation(self) -> None:
        import asyncio

        module = _load_runtime_module()
        runtime = _runtime_instance(module)
        lines = [marker for _criterion, marker, _substring in CANARY_CRITERIA]

        repeated_lines = [
            marker
            for criterion, marker, _substring in CANARY_CRITERIA
            if criterion not in {"CHANNEL_CLOSED", "LISTENER_READY_AFTER"}
        ]
        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(_feed_runtime_lines(runtime, repeated_lines + repeated_lines))

        output = "\n".join(cm.output)
        for criterion, _marker, substring in CANARY_CRITERIA:
            if criterion in {"CHANNEL_CLOSED", "LISTENER_READY_AFTER"}:
                continue
            self.assertEqual(output.count(substring), 1, substring)
        self.assertEqual(len(cm.output), len(repeated_lines))

    def test_canary_log_sanitizer_blocks_forbidden_values(self) -> None:
        import asyncio

        module = _load_runtime_module()
        runtime = _runtime_instance(module)
        poison = [
            "R42_CALL_GENERATION=10",
            "R54_LOCAL_CAPABILITY_WORD=00112233445566778899aabbccddeeff",
            "R54_PEER_CAPABILITY_WORD=<script>",
            "R54_CALL_ADOPTION_FAILURE_STAGE=RAW_PAYLOAD:abcd",
            "R42_MEDIAREQ26_OPEN_CHANNEL=../../etc/passwd",
            "P116_VIDEO_SPS_COUNT=COMELIT_VIP_TOKEN=deadbeef",
            "R42_ATTACHED_MEDIA_STOP_SENT=true;token=secret",
        ]
        with self.assertLogs("custom_components.comelit.runtime", level="INFO") as cm:
            asyncio.run(_feed_runtime_lines(runtime, poison))

        output = "\n".join(cm.output)
        self.assertIn("Comelit canary evidence CALL_INIT_SEEN", output)
        self.assertEqual(len(cm.output), 1)
        for forbidden in FORBIDDEN_LOG_SUBSTRINGS:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, output)

    def test_document_observation_table_matches_declared_canary_criteria(self) -> None:
        doc = CANARY_DOC.read_text(encoding="utf-8")
        self.assertIn("## Read-only canary observability", doc)
        for criterion, marker, substring in CANARY_CRITERIA:
            row = f"| {criterion} | `{marker.split('=', 1)[0]}` | `{substring}` |"
            with self.subTest(criterion=criterion):
                self.assertEqual(doc.count(row), 1)
        self.assertIn(
            "A criterion without an observable log line blocks the live phase",
            doc,
        )

    def test_no_forbidden_side_effect_primitives_in_new_files(self) -> None:
        files = (
            MEDIA / "entrance_p116_r54_call_adoption_listener_transform.py",
            HARNESS,
            Path(__file__).resolve(),
        )
        patterns = (
            r"\bsocket\s*\(",
            r"\bconnect\s*\(",
            r"\bsendto\s*\(",
            r"\bgetaddrinfo\s*\(",
            r"\b" + "door" + r"_action\b",
            r"\b" + "gate" + r"_action\b",
            "capture " + "literal",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
