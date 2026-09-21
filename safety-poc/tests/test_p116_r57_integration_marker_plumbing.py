"""P116/R57 CORRECTIVE turn 2: integration-side marker plumbing tests.

Turn 1 (accepted) added the native `P116NativeFailureId` / `P116NativeFailurePhase`
pair, `p116_record_failure()`, and a terminal exit summary
(`P116_NATIVE_EXIT_CODE`/`P116_NATIVE_FAILURE_ID`/`P116_NATIVE_FAILURE_PHASE`/
`P116_NATIVE_FAILURE_COUNT`) plus `P116_TIMEOUT_KIND`/`P116_TIMEOUT_PHASE` --
see entrance_p116_r57_native_failure_attribution_transform.py. Without this
turn's integration change, `custom_components/comelit/runtime.py` would
silently discard every one of those markers: `P116_` was absent from
`_NATIVE_MARKER_PREFIXES`, so `_remember_native_marker()` returned before the
new keys ever reached `_native_marker_tail`/`last_native_failure_markers`
(the only failure evidence logged at `native_exit:6`), and even with the
prefix added, `_NATIVE_MARKER_SAFE_VALUE_RE` alone would have resolved every
enum value except a handful of shared literals to `<redacted>`.

This module proves, through the real ``ComelitRingRuntime`` integration code
path (``_async_read_output`` -> ``_remember_native_marker`` /
``_observe_canary_log_marker`` -> ``_capture_native_failure``), that:

1. the new `P116_` prefix and bounded vocabularies let the failure ID/phase/
   exit code/count and timeout kind/phase survive sanitization and appear
   in ``last_native_failure_markers`` at `native_exit:6`, not `<redacted>`;
2. they surface as `Comelit canary evidence <CRITERION>` log lines;
3. an out-of-vocabulary `P116_` value is redacted (kept, not silently
   dropped) and never reaches the canary-criteria log;
4. an unrelated unknown-prefix key is still dropped entirely, exactly as
   before;
5. no other marker class's sanitization was loosened as a side effect.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNTIME = REPO / "custom_components" / "comelit" / "runtime.py"
MEDIA_DIAGNOSTICS = REPO / "custom_components" / "comelit" / "media_diagnostics.py"


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
        "custom_components.comelit.runtime",
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


def _status_ready_runtime_instance(module: types.ModuleType) -> object:
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


async def _feed_lines(runtime: object, lines: list[str]) -> None:
    await runtime._async_read_output(_FakeProcess(lines))


# The exact terminal exit-summary lines p116_emit_native_exit_summary()
# prints, immediately preceded by p116_emit_timeout_observability() output,
# matching the literal formats in
# entrance_p116_r57_native_failure_attribution_transform.py.
EXIT_SUMMARY_LINES = [
    "P116_TIMEOUT_KIND=R54_TX_WAIT_TIMEOUT",
    "P116_TIMEOUT_PHASE=WAIT_PEER_CAPABILITIES",
    "P116_NATIVE_EXIT_CODE=6",
    "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
    "P116_NATIVE_FAILURE_PHASE=WAIT_PEER_CAPABILITIES",
    "P116_NATIVE_FAILURE_COUNT=1",
]

# A realistic pre-exit tail lifted from the shape documented in
# P116_R57_NATIVE_FAILURE_ATTRIBUTION_AND_SECOND_CANARY_OBSERVABILITY.md
# ("D1 -- First-canary timeline"): two suppressed ring retransmits each
# followed by an app-level receive event, then an echo classification, then
# a rejected P12 enqueue, then the fixed GENERATION_END shutdown block.
REALISTIC_PRE_EXIT_TAIL = [
    "V4_RING_RETRANSMIT_SUPPRESSED=true",
    "V4_RING_RETRANSMIT_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "PSEUDOTCP_APP_RX_EVENT=true",
    "V4_RING_RETRANSMIT_SUPPRESSED=true",
    "V4_RING_RETRANSMIT_SHA256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "PSEUDOTCP_APP_RX_EVENT=true",
    "PSEUDOTCP_APP_RX_EVENT=true",
    "P12_TX_QUEUE=FAIL",
    "ICE_OFFER_HELD=true",
    "PSEUDOTCP_OPEN_FINAL=true",
]


class P116R57NativePrefixAndVocabularyTests(unittest.TestCase):
    def test_p116_prefix_present_in_native_marker_prefixes(self) -> None:
        module = _load_runtime_module()
        self.assertIn("P116_", module._NATIVE_MARKER_PREFIXES)

    def test_bounded_vocabularies_match_the_native_enums(self) -> None:
        module = _load_runtime_module()
        self.assertEqual(
            module._P116_FAILURE_IDS,
            frozenset(
                {
                    "NONE",
                    "STARTUP",
                    "ABSOLUTE_SESSION_TIMEOUT",
                    "P12_STEP_TIMEOUT",
                    "UAUT_OPEN_TIMEOUT",
                    "RECV_PARSE",
                    "PSEUDOTCP_RECV_TRANSPORT",
                    "PSEUDOTCP_WRITABLE_TRANSPORT",
                    "PSEUDOTCP_CLOSED",
                    "PSEUDOTCP_WRITE_PACKET",
                    "PSEUDOTCP_CLOCK_CLOSED",
                    "PSEUDOTCP_NOTIFY_PACKET",
                    "ICE_CONNECTIVITY",
                    "ICE_GATHER",
                    "SDP_FILE",
                    "DOOR_WRITE",
                    "DOOR_TIMER",
                    "P80_RTP_FORWARD",
                    "OTHER",
                }
            ),
        )
        self.assertEqual(
            module._P116_FAILURE_PHASES,
            frozenset(
                {
                    "STARTUP",
                    "LISTENER_READY",
                    "CALL_ADOPTION_LOCAL",
                    "WAIT_PEER_CAPABILITIES",
                    "PEER_ACK",
                    "MEDIA_OPEN",
                    "MEDIA_ACTIVE",
                    "MEDIA_STOP",
                    "GENERATION_END",
                }
            ),
        )
        self.assertEqual(module._P116_TIMEOUT_KINDS, frozenset({"R54_TX_WAIT_TIMEOUT"}))


class P116R57ExitTailCaptureTests(unittest.TestCase):
    """Integration path: _async_read_output -> _remember_native_marker ->
    _capture_native_failure, the exact path that produced the R54 live
    canary markers and is the only source of `last_native_failure_markers`.
    """

    def test_exit_summary_markers_survive_tail_and_are_not_redacted(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        asyncio.run(_feed_lines(runtime, EXIT_SUMMARY_LINES))
        runtime._capture_native_failure(6)

        tail = runtime._last_native_failure_markers
        self.assertEqual(runtime._last_native_exit_code, 6)
        self.assertIn("P116_NATIVE_EXIT_CODE=6", tail)
        self.assertIn("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED", tail)
        self.assertIn("P116_NATIVE_FAILURE_PHASE=WAIT_PEER_CAPABILITIES", tail)
        self.assertIn("P116_NATIVE_FAILURE_COUNT=1", tail)
        self.assertIn("P116_TIMEOUT_KIND=R54_TX_WAIT_TIMEOUT", tail)
        self.assertIn("P116_TIMEOUT_PHASE=WAIT_PEER_CAPABILITIES", tail)
        for entry in tail:
            self.assertNotIn("<redacted>", entry)

    def test_exit_summary_survives_a_full_realistic_marker_tail(self) -> None:
        """The exit summary is the *last* 6 lines before native exit. Even
        with a full, realistic 10-line pre-exit tail ahead of it, the
        6 exit-summary lines must still be present under the 20-line
        _NATIVE_MARKER_TAIL_LIMIT window."""
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)
        self.assertEqual(module._NATIVE_MARKER_TAIL_LIMIT, 20)
        self.assertLessEqual(
            len(REALISTIC_PRE_EXIT_TAIL) + len(EXIT_SUMMARY_LINES),
            module._NATIVE_MARKER_TAIL_LIMIT,
        )

        asyncio.run(
            _feed_lines(runtime, REALISTIC_PRE_EXIT_TAIL + EXIT_SUMMARY_LINES)
        )
        runtime._capture_native_failure(6)

        tail = runtime._last_native_failure_markers
        self.assertIn("P116_NATIVE_EXIT_CODE=6", tail)
        self.assertIn("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED", tail)
        self.assertIn("P116_NATIVE_FAILURE_PHASE=WAIT_PEER_CAPABILITIES", tail)
        self.assertIn("P116_NATIVE_FAILURE_COUNT=1", tail)
        # Confirm they land at the newest end of the tail (exit summary is
        # the terminal output), not merely present anywhere.
        self.assertEqual(tail[-6:], EXIT_SUMMARY_LINES)

    def test_exit_summary_survives_even_when_tail_limit_is_exceeded_before_it(
        self,
    ) -> None:
        """Even if 20+ unrelated markers precede the exit summary in one
        native run, the ring-buffer eviction in _remember_native_marker()
        must still leave the exit summary (the newest entries) present."""
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        noise = [f"V4_RING_RETRANSMIT_SUPPRESSED=true" for _ in range(30)]
        asyncio.run(_feed_lines(runtime, noise + EXIT_SUMMARY_LINES))
        runtime._capture_native_failure(6)

        tail = runtime._last_native_failure_markers
        self.assertEqual(len(tail), module._NATIVE_MARKER_TAIL_LIMIT)
        self.assertIn("P116_NATIVE_EXIT_CODE=6", tail)
        self.assertIn("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED", tail)
        self.assertIn("P116_NATIVE_FAILURE_PHASE=WAIT_PEER_CAPABILITIES", tail)
        self.assertIn("P116_NATIVE_FAILURE_COUNT=1", tail)


class P116R57CanaryCriteriaMappingTests(unittest.TestCase):
    """Integration path: _async_read_output -> _observe_canary_log_marker
    -> `Comelit canary evidence <CRITERION>` log line."""

    def test_failure_markers_are_mapped_to_canary_criteria_and_logged(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        with self.assertLogs(
            "custom_components.comelit.runtime", level="INFO"
        ) as captured:
            asyncio.run(_feed_lines(runtime, EXIT_SUMMARY_LINES))

        joined = "\n".join(captured.output)
        for criterion in (
            "TIMEOUT_KIND",
            "TIMEOUT_PHASE",
            "NATIVE_EXIT_CODE",
            "NATIVE_FAILURE_ID",
            "NATIVE_FAILURE_PHASE",
            "NATIVE_FAILURE_COUNT",
        ):
            with self.subTest(criterion=criterion):
                self.assertIn(f"Comelit canary evidence {criterion}", joined)
        self.assertIn("value=PSEUDOTCP_CLOSED", joined)
        self.assertIn("value=WAIT_PEER_CAPABILITIES", joined)
        self.assertIn("value=6", joined)
        self.assertIn("value=1", joined)

    def test_success_exit_reports_exit_code_zero_and_no_failure_id(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        with self.assertLogs(
            "custom_components.comelit.runtime", level="INFO"
        ) as captured:
            asyncio.run(
                _feed_lines(
                    runtime,
                    [
                        "P116_NATIVE_EXIT_CODE=0",
                        "P116_NATIVE_FAILURE_ID=NONE",
                        "P116_NATIVE_FAILURE_PHASE=GENERATION_END",
                        "P116_NATIVE_FAILURE_COUNT=0",
                    ],
                )
            )

        joined = "\n".join(captured.output)
        self.assertIn("Comelit canary evidence NATIVE_EXIT_CODE", joined)
        self.assertIn("value=0", joined)
        self.assertIn("Comelit canary evidence NATIVE_FAILURE_ID", joined)
        self.assertIn("value=NONE", joined)


class P116R57NegativeProbeTests(unittest.TestCase):
    def test_out_of_vocabulary_failure_id_is_redacted_not_stored_verbatim(
        self,
    ) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        asyncio.run(
            _feed_lines(
                runtime,
                ["P116_NATIVE_FAILURE_ID=SOME_INVENTED_VALUE_NOT_IN_THE_ENUM"],
            )
        )
        self.assertIn(
            "P116_NATIVE_FAILURE_ID=<redacted>", runtime._native_marker_tail
        )
        self.assertNotIn(
            "P116_NATIVE_FAILURE_ID=SOME_INVENTED_VALUE_NOT_IN_THE_ENUM",
            runtime._native_marker_tail,
        )

    def test_out_of_vocabulary_failure_id_never_reaches_canary_criteria_log(
        self,
    ) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        root_logger = logging.getLogger("custom_components.comelit.runtime")
        original_level = root_logger.level
        try:
            with self.assertLogs(root_logger, level="DEBUG") as captured:
                root_logger.debug("sentinel-to-keep-assertLogs-happy")
                asyncio.run(
                    _feed_lines(
                        runtime,
                        [
                            "P116_NATIVE_FAILURE_ID=SOME_INVENTED_VALUE",
                            "P116_TIMEOUT_KIND=SOME_INVENTED_KIND",
                            "P116_TIMEOUT_PHASE=NOT_A_REAL_PHASE",
                        ],
                    )
                )
        finally:
            root_logger.setLevel(original_level)

        joined = "\n".join(captured.output)
        self.assertNotIn("Comelit canary evidence NATIVE_FAILURE_ID", joined)
        self.assertNotIn("Comelit canary evidence TIMEOUT_KIND", joined)
        self.assertNotIn("Comelit canary evidence TIMEOUT_PHASE", joined)

    def test_unrelated_unknown_prefix_key_is_still_dropped_entirely(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        asyncio.run(_feed_lines(runtime, ["P200_SOMETHING_UNRELATED=true"]))
        self.assertEqual(runtime._native_marker_tail, [])

    def test_p116_numeric_exit_code_and_count_pass_through_unredacted(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        asyncio.run(
            _feed_lines(
                runtime,
                ["P116_NATIVE_EXIT_CODE=6", "P116_NATIVE_FAILURE_COUNT=3"],
            )
        )
        self.assertIn("P116_NATIVE_EXIT_CODE=6", runtime._native_marker_tail)
        self.assertIn("P116_NATIVE_FAILURE_COUNT=3", runtime._native_marker_tail)

    def test_no_other_marker_class_is_loosened_as_a_side_effect(self) -> None:
        """The generic ICE_/PSEUDOTCP_/V4_ tail-capture regex must behave
        exactly as before (unaffected by the new per-key vocabulary lookup,
        which only applies to keys present in _P116_MARKER_VOCABULARIES):
        a bogus value for a non-P116_ key is still redacted in the tail."""
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        asyncio.run(
            _feed_lines(
                runtime,
                [
                    "ICE_GATHER=MAYBE",
                    "R54_CALL_ADOPTION_FAILURE_STAGE=TX_WAIT_TIMEOUT",
                    "V4_RING_KIND=<script>alert(1)</script>",
                ],
            )
        )
        self.assertIn("ICE_GATHER=<redacted>", runtime._native_marker_tail)
        # R54_CALL_ADOPTION_FAILURE_STAGE is not a P116_ key, so it is
        # unaffected by this round's change: it goes through the same
        # generic tail regex as before (its own whitelist only applies on
        # the separate _observe_canary_log_marker/_safe_native_marker_value
        # path, unchanged here), so a value outside that generic regex
        # still redacts in the tail exactly as pre-R57.
        self.assertIn(
            "R54_CALL_ADOPTION_FAILURE_STAGE=<redacted>",
            runtime._native_marker_tail,
        )
        self.assertIn("V4_RING_KIND=<redacted>", runtime._native_marker_tail)

    def test_r54_call_adoption_failure_stage_whitelist_still_works_on_canary_path(
        self,
    ) -> None:
        """The pre-existing canary-criteria whitelist for
        R54_CALL_ADOPTION_FAILURE_STAGE (_safe_native_marker_value) must
        remain unaffected by the new _P116_MARKER_VOCABULARIES lookup,
        which is appended after it and only matches P116_ keys."""
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)
        self.assertEqual(
            runtime._safe_native_marker_value(
                "R54_CALL_ADOPTION_FAILURE_STAGE", "TX_WAIT_TIMEOUT"
            ),
            "TX_WAIT_TIMEOUT",
        )
        self.assertIsNone(
            runtime._safe_native_marker_value(
                "R54_CALL_ADOPTION_FAILURE_STAGE", "NOT_A_REAL_STAGE"
            )
        )

    def test_p116_vocabularies_do_not_leak_into_unrelated_p116_h264_markers(
        self,
    ) -> None:
        """P116_VIDEO_SPS_COUNT etc. (the H264-evidence markers, unrelated
        to failure attribution) are not in _P116_MARKER_VOCABULARIES and
        must keep going through the generic digits-only regex."""
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)
        self.assertNotIn("P116_VIDEO_SPS_COUNT", module._P116_MARKER_VOCABULARIES)

        asyncio.run(_feed_lines(runtime, ["P116_VIDEO_SPS_COUNT=1"]))
        self.assertIn("P116_VIDEO_SPS_COUNT=1", runtime._native_marker_tail)


class P116R57MediaDiagnosticsAllowListTests(unittest.TestCase):
    """media_diagnostics.py's recognized-keys allow-list is unaffected: the
    new P116_ exit/failure/timeout keys are outside its purpose (media-call
    evidence, not native-process exit diagnostics) and are silently ignored,
    not dropped-with-error or mis-flagged."""

    def test_new_p116_exit_and_failure_keys_are_not_in_the_recognized_set(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "comelit_media_diagnostics_r57", MEDIA_DIAGNOSTICS
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for key in (
            "P116_NATIVE_EXIT_CODE",
            "P116_NATIVE_FAILURE_ID",
            "P116_NATIVE_FAILURE_PHASE",
            "P116_NATIVE_FAILURE_COUNT",
            "P116_TIMEOUT_KIND",
            "P116_TIMEOUT_PHASE",
        ):
            self.assertNotIn(key, module._RECOGNIZED_MEDIA_DIAGNOSTIC_KEYS)

    def test_observe_line_silently_ignores_them_without_mutating_snapshot(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "comelit_media_diagnostics_r57b", MEDIA_DIAGNOSTICS
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        diag = module.MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        before = diag.snapshot()

        for line in EXIT_SUMMARY_LINES:
            consumed = diag.observe_line(line)
            self.assertFalse(consumed)

        self.assertEqual(diag.snapshot(), before)


class P116R57CliCwdIndependenceTests(unittest.TestCase):
    """Small quality fix: --sha256 must resolve the frozen source relative
    to the module file, not accumulate a duplicated safety-poc/safety-poc
    path segment, regardless of the invoking process's cwd."""

    def test_sha256_cli_resolves_correctly_from_any_cwd(self) -> None:
        import subprocess
        import sys as _sys

        transform_path = (
            ROOT / "research" / "media" / "v1"
            / "entrance_p116_r57_native_failure_attribution_transform.py"
        )
        for cwd in (str(REPO), str(REPO / "safety-poc"), "/tmp"):
            with self.subTest(cwd=cwd):
                result = subprocess.run(
                    [_sys.executable, str(transform_path), "--sha256"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                # Corrective (build-blocking declaration order): the first R57
                # candidate generated db6bee61... but did not compile (its
                # typedefs/enums/helpers were emitted after the earliest
                # instrumented call site). The transform now emits its
                # declarations early, so the pinned native source hash moved to
                # the corrected value below; the CLI itself is unchanged.
                self.assertEqual(
                    result.stdout.strip(),
                    "fbd6137a5bb8b0f7258bfe69d72481c70272645aae0d4c0f0dff8c66d0b2237c",
                )


if __name__ == "__main__":
    unittest.main()
