#!/usr/bin/env python3
"""P119: L1 remote.sdp wait removal + gathering-stage diagnostic markers.

Two independent, bounded changes to the generated production native source:

1. L1: ``remote_sdp_check_cb`` no longer waits for two additional stable-size
   polls before reading ``remote.sdp``; the first successful non-empty
   ``g_stat`` is read immediately (the single-writer/startup-unlink
   invariants make partial or stale visibility impossible).
2. Diagnostic-only monotonic-ms stage markers (G0-G6, RSP_VISIBLE/RSP_LOADED)
   splitting the ICE gathering window, consumed by
   ``custom_components/comelit/latency_timeline.py`` and
   ``media_transport.py``.

Both changes are implemented as a new downstream transform
(``entrance_p119_remote_sdp_l1_gather_diag_transform.py``), composed on top
of the existing, untouched R65 production candidate -- never as a direct
edit of the frozen raw source file
(``safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c``),
whose exact bytes are pinned as a frozen anchor by many unrelated rounds
(R18, R20, R27, R35-R37, R54, R57, R58, P29, ...). This mirrors exactly how
the settle-candidate round before it layered its own change in via
``entrance_device_video_ack_observation_transform.py``.

This module proves both changes structurally against the real, regenerated
production source (never against a hand-written excerpt), and proves the
new native-only timeline arithmetic in isolation.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
MEDIA_DIR = ROOT / "safety-poc" / "research" / "media" / "v1"
DOOR_SOURCE = (
    ROOT
    / "safety-poc"
    / "research"
    / "door"
    / "v1_5_7"
    / "comelit-v4-persistent-ctpp-door.c"
)

sys.path.insert(0, str(MEDIA_DIR))
from entrance_p119_remote_sdp_l1_gather_diag_transform import (  # noqa: E402
    transform as p119_transform,
)
import entrance_p116_r57_native_failure_attribution_transform as r57_transform  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mvp1_local_sdp_readiness_corrective as transport_fixture  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


latency_timeline = _load("comelit_latency_timeline_p119", COMPONENT / "latency_timeline.py")

GENERATED_SOURCE_SHA256 = (
    "2f8137e988437c779a0f3bb1c9904c81cbe2d13641efa2e6a070054116dd43ed"
)
GENERATED_SOURCE_BYTES = 251588
BASE_SOURCE_SHA256 = "4448e8368bd6275a2cd398c35ef171d012f315d2bb5bd05daf2e33a13d4c0001"

MONOTONIC_MARKERS = (
    "G0_NATIVE_PROCESS_START_MONOTONIC_MS",
    "G1_NICE_AGENT_READY_MONOTONIC_MS",
    "G2_GATHER_CALL_MONOTONIC_MS",
    "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS",
    "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS",
    "G5_GATHER_DONE_MONOTONIC_MS",
    "G6_OFFER_WRITTEN_MONOTONIC_MS",
    "RSP_VISIBLE_MONOTONIC_MS",
    "RSP_LOADED_MONOTONIC_MS",
)
COUNT_MARKERS = (
    "G3_HOST_CANDIDATE_COUNT",
    "G4_SRFLX_CANDIDATE_COUNT",
)
NEW_MARKERS = MONOTONIC_MARKERS[:4] + (COUNT_MARKERS[0],) + MONOTONIC_MARKERS[4:5] + (
    COUNT_MARKERS[1],
) + MONOTONIC_MARKERS[5:]
# NEW_MARKERS is exactly, in the same order the native helper prints them:
# G0, G1, G2, G3(mono), G3_COUNT, G4(mono), G4_COUNT, G5, G6, RSP_VISIBLE, RSP_LOADED
assert NEW_MARKERS == (
    "G0_NATIVE_PROCESS_START_MONOTONIC_MS",
    "G1_NICE_AGENT_READY_MONOTONIC_MS",
    "G2_GATHER_CALL_MONOTONIC_MS",
    "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS",
    "G3_HOST_CANDIDATE_COUNT",
    "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS",
    "G4_SRFLX_CANDIDATE_COUNT",
    "G5_GATHER_DONE_MONOTONIC_MS",
    "G6_OFFER_WRITTEN_MONOTONIC_MS",
    "RSP_VISIBLE_MONOTONIC_MS",
    "RSP_LOADED_MONOTONIC_MS",
)

_FORBIDDEN_SUBSTRINGS = (
    "candidate:",
    "ice-ufrag",
    "ice-pwd",
    "password",
    "ufrag",
    "a=",
    "m=",
    "o=",
    "c=",
)
_IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_LONG_DIGIT_RUN_RE = re.compile(r"\d{4,}")


def _marker_call_site(source: str, marker: str) -> str:
    """The exact printf(...) call-site text for one marker.

    Scoped deliberately: every negative content assertion below runs only
    against this small snippet, never the whole ~250KB generated source
    (which legitimately contains many of the forbidden substrings elsewhere,
    e.g. in the SDP/ICE code the markers are diagnosing).
    """
    anchor = f'"{marker}='
    pos = source.index(anchor)
    start = source.rindex("printf(", 0, pos)
    end = source.index(");", pos) + 2
    return source[start:end]


class P119GeneratedSourceIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_source = DOOR_SOURCE.read_text(encoding="utf-8")
        cls.generated = p119_transform(cls.base_source, include_p116=True)

    def test_generated_source_matches_recorded_identity(self) -> None:
        encoded = self.generated.encode("utf-8")
        self.assertEqual(len(encoded), GENERATED_SOURCE_BYTES)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), GENERATED_SOURCE_SHA256)
        self.assertNotEqual(GENERATED_SOURCE_SHA256, BASE_SOURCE_SHA256)


class P119L1RemoteSdpWaitRemovalTests(unittest.TestCase):
    """PART 1: the redundant remote.sdp stability wait is gone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = p119_transform(
            DOOR_SOURCE.read_text(encoding="utf-8"), include_p116=True
        )

    def test_stability_statics_are_gone(self) -> None:
        self.assertNotIn("remote_stable_ticks", self.generated)
        self.assertNotIn("remote_last_size", self.generated)

    def test_poll_registration_unchanged(self) -> None:
        idx = self.generated.index("remote_sdp_check_cb,")
        window = self.generated[max(0, idx - 80) : idx]
        self.assertIn("g_timeout_add(", window)
        self.assertIn("100,", window)

    def test_read_path_is_intact(self) -> None:
        for needle in (
            "g_file_get_contents(",
            "REMOTE_SDP_READ=FAIL",
            "chmod(",
            "REMOTE_SDP_BYTES=",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.generated)

    def test_stability_comment_is_gone(self) -> None:
        self.assertNotIn("Require the size to be stable", self.generated)

    def test_stat_guard_is_immediately_followed_by_the_read(self) -> None:
        guard = (
            "    if (g_stat(REMOTE_FILE, &st) != 0 ||\n"
            "        st.st_size <= 0) {\n"
            "\n"
            "        return G_SOURCE_CONTINUE;\n"
            "    }\n"
        )
        self.assertEqual(self.generated.count(guard), 1)
        guard_end = self.generated.index(guard) + len(guard)
        read_call = self.generated.index("if (!g_file_get_contents(", guard_end)
        between = self.generated[guard_end:read_call]
        self.assertNotIn("remote_last_size", between)
        self.assertNotIn("remote_stable_ticks", between)
        self.assertNotIn("if (", between)
        self.assertIn("RSP_VISIBLE_MONOTONIC_MS", between)


class P119NewMarkersStructuralTests(unittest.TestCase):
    """PART 2: every new marker is present, safe, and one-shot where required."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = p119_transform(
            DOOR_SOURCE.read_text(encoding="utf-8"), include_p116=True
        )

    def test_every_new_marker_appears_verbatim_exactly_once(self) -> None:
        for marker in NEW_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(self.generated.count(f'"{marker}='), 1)

    def test_monotonic_markers_use_g_get_monotonic_time(self) -> None:
        for marker in MONOTONIC_MARKERS:
            with self.subTest(marker=marker):
                call = _marker_call_site(self.generated, marker)
                self.assertIn("g_get_monotonic_time()", call)
                self.assertIn("G_GUINT64_FORMAT", call)

    def test_count_markers_use_unsigned_integer_format(self) -> None:
        for marker in COUNT_MARKERS:
            with self.subTest(marker=marker):
                call = _marker_call_site(self.generated, marker)
                self.assertIn("%u", call)
                self.assertNotIn("g_get_monotonic_time()", call)

    def test_each_marker_print_is_immediately_followed_by_fflush(self) -> None:
        for marker in NEW_MARKERS:
            with self.subTest(marker=marker):
                call = _marker_call_site(self.generated, marker)
                end = self.generated.index(call) + len(call)
                tail = self.generated[end : end + 40]
                self.assertIn("fflush(stdout);", tail)

    def test_one_shot_guards_exist_for_first_candidate_markers(self) -> None:
        self.assertIn("static gboolean g3_host_first_seen = FALSE;", self.generated)
        self.assertIn("static gboolean g4_srflx_first_seen = FALSE;", self.generated)
        self.assertEqual(self.generated.count("g3_host_first_seen = TRUE;"), 1)
        self.assertEqual(self.generated.count("g4_srflx_first_seen = TRUE;"), 1)
        self.assertIn("!g3_host_first_seen", self.generated)
        self.assertIn("!g4_srflx_first_seen", self.generated)

    def test_new_candidate_signal_handler_is_pure_observation(self) -> None:
        start = self.generated.index("new_candidate_cb(")
        body_end = self.generated.index("\n\n\nstatic void\ncandidate_gathering_done_cb")
        handler = self.generated[start:body_end]
        for forbidden in (
            "nice_agent_set_selected",
            "_nominate",
            "_accept",
            "set_remote_candidates",
        ):
            self.assertNotIn(forbidden, handler)

    def test_marker_call_sites_contain_no_network_or_credential_content(self) -> None:
        for marker in NEW_MARKERS:
            call = _marker_call_site(self.generated, marker)
            with self.subTest(marker=marker):
                for forbidden in _FORBIDDEN_SUBSTRINGS:
                    self.assertNotIn(forbidden, call)
                self.assertIsNone(_IPV4_RE.search(call))
                long_digit_runs = _LONG_DIGIT_RUN_RE.findall(call)
                self.assertTrue(
                    all(run == "1000" for run in long_digit_runs),
                    (marker, long_digit_runs),
                )


class P119R57CompatibilityTests(unittest.TestCase):
    """PART 3: R57 (entrance_p116_r57_native_failure_attribution_transform.py)
    is a structurally independent branch -- it composes R54, not R27/R65 --
    and never reaches this round's markers either way. It stays fully
    compatible because P119, like every round since the R65 lineage split
    off, never touches the raw source R57 is also rooted in."""

    def test_r57_transform_still_applies_cleanly_to_the_unchanged_raw_source(
        self,
    ) -> None:
        source = DOOR_SOURCE.read_text(encoding="utf-8")
        candidate = r57_transform.transform(source)
        self.assertIn("REMOTE_SDP_READ=FAIL", candidate)
        self.assertIn(
            "p116_record_failure(P116_FAILURE_SDP_FILE, P116_PHASE_STARTUP)", candidate
        )
        # None of the new P119 markers are expected here: R57 and P119 are
        # independent branches that never compose, by construction.
        for marker in NEW_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(f'"{marker}=', candidate)

    def test_raw_source_r57_depends_on_is_the_same_one_p119_builds_on(self) -> None:
        # Both R57 and P119 (via R65/R27/P106) are ultimately rooted in this
        # exact raw file; proving neither round diverges from it here is what
        # keeps them independently reproducible and mutually compatible.
        source = DOOR_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73",
        )


class P119NativeTimelineFieldTests(unittest.TestCase):
    """PART 5/6: the 10 new derived fields, in the specified positions,
    computed only from native monotonic values."""

    def test_field_order_has_25_previous_plus_10_new(self) -> None:
        # P121 later appends 3 more fields after these 10 (index 13-15), so
        # the total length is now 38, not 35 -- but this slice (indices 3-12)
        # is unaffected by that later insertion.
        self.assertEqual(len(latency_timeline.FIELD_ORDER), 38)
        self.assertEqual(
            latency_timeline.FIELD_ORDER[3:13],
            (
                "NATIVE_PROCESS_START_TO_NICE_AGENT_READY_MS",
                "NICE_AGENT_READY_TO_GATHER_CALL_MS",
                "GATHER_CALL_TO_FIRST_HOST_CANDIDATE_MS",
                "FIRST_HOST_TO_FIRST_SRFLX_CANDIDATE_MS",
                "FIRST_SRFLX_TO_GATHER_DONE_MS",
                "GATHER_CALL_TO_GATHER_DONE_MS",
                "GATHER_DONE_TO_OFFER_WRITTEN_MS",
                "REMOTE_SDP_FILE_VISIBLE_TO_LOAD_MS",
                "G3_HOST_CANDIDATE_COUNT",
                "G4_SRFLX_CANDIDATE_COUNT",
            ),
        )

    def test_new_fields_are_n_a_when_native_values_are_missing(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        fields = timeline.summary_fields()
        for name in latency_timeline.FIELD_ORDER[3:13]:
            with self.subTest(name=name):
                self.assertEqual(fields[name], "N_A")

    def test_new_fields_are_n_a_when_only_one_native_endpoint_present(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native(latency_timeline.G2_GATHER_CALL_MONOTONIC_MS, 1000)
        fields = timeline.summary_fields()
        self.assertEqual(fields["GATHER_CALL_TO_FIRST_HOST_CANDIDATE_MS"], "N_A")
        self.assertEqual(fields["GATHER_CALL_TO_GATHER_DONE_MS"], "N_A")

    def test_unrecognized_native_key_is_silently_ignored(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native("NOT_A_REAL_NATIVE_MARKER", 5)
        fields = timeline.summary_fields()
        self.assertEqual(fields["GATHER_CALL_TO_FIRST_HOST_CANDIDATE_MS"], "N_A")

    def test_native_mark_records_only_first_observation(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native(latency_timeline.G0_NATIVE_PROCESS_START_MONOTONIC_MS, 100)
        timeline.mark_native(latency_timeline.G0_NATIVE_PROCESS_START_MONOTONIC_MS, 999)
        timeline.mark_native(latency_timeline.G1_NICE_AGENT_READY_MONOTONIC_MS, 110)
        fields = timeline.summary_fields()
        self.assertEqual(fields["NATIVE_PROCESS_START_TO_NICE_AGENT_READY_MS"], "10")

    def test_count_fields_are_passthrough_not_durations(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native(latency_timeline.G3_HOST_CANDIDATE_COUNT, 4)
        timeline.mark_native(latency_timeline.G4_SRFLX_CANDIDATE_COUNT, 1)
        fields = timeline.summary_fields()
        self.assertEqual(fields["G3_HOST_CANDIDATE_COUNT"], "4")
        self.assertEqual(fields["G4_SRFLX_CANDIDATE_COUNT"], "1")

    def test_gather_call_to_gather_done_equals_sum_of_sub_deltas(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native(latency_timeline.G2_GATHER_CALL_MONOTONIC_MS, 1000)
        timeline.mark_native(latency_timeline.G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS, 1013)
        timeline.mark_native(latency_timeline.G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS, 1501)
        timeline.mark_native(latency_timeline.G5_GATHER_DONE_MONOTONIC_MS, 2909)
        fields = timeline.summary_fields()
        g2_g3 = int(fields["GATHER_CALL_TO_FIRST_HOST_CANDIDATE_MS"])
        g3_g4 = int(fields["FIRST_HOST_TO_FIRST_SRFLX_CANDIDATE_MS"])
        g4_g5 = int(fields["FIRST_SRFLX_TO_GATHER_DONE_MS"])
        g2_g5 = int(fields["GATHER_CALL_TO_GATHER_DONE_MS"])
        self.assertLessEqual(abs((g2_g3 + g3_g4 + g4_g5) - g2_g5), 2)

    def test_g0_to_g2_equals_sum_of_sub_deltas(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark_native(latency_timeline.G0_NATIVE_PROCESS_START_MONOTONIC_MS, 500)
        timeline.mark_native(latency_timeline.G1_NICE_AGENT_READY_MONOTONIC_MS, 512)
        timeline.mark_native(latency_timeline.G2_GATHER_CALL_MONOTONIC_MS, 521)
        fields = timeline.summary_fields()
        g0_g1 = int(fields["NATIVE_PROCESS_START_TO_NICE_AGENT_READY_MS"])
        g1_g2 = int(fields["NICE_AGENT_READY_TO_GATHER_CALL_MS"])
        g0_g2 = timeline._native_duration_ms(
            latency_timeline.G0_NATIVE_PROCESS_START_MONOTONIC_MS,
            latency_timeline.G2_GATHER_CALL_MONOTONIC_MS,
        )
        self.assertLessEqual(abs((g0_g1 + g1_g2) - g0_g2), 2)


class P119MediaTransportParsingTests(unittest.IsolatedAsyncioTestCase):
    """PART 5: media_transport.py parses the new stage markers, verbatim,
    into the timeline via mark_native() -- never as observation boundaries."""

    async def asyncSetUp(self) -> None:
        self.media_transport = transport_fixture.media_transport
        self.transport = object.__new__(self.media_transport.ComelitEntranceMediaTransport)
        self.timeline = latency_timeline.CameraRequestLatencyTimeline()
        self.transport._latency_timeline = self.timeline

    async def test_each_new_marker_line_is_parsed_into_the_native_dict(self) -> None:
        cases = (
            ("G0_NATIVE_PROCESS_START_MONOTONIC_MS=1234", "G0_NATIVE_PROCESS_START_MONOTONIC_MS", 1234),
            ("G3_HOST_CANDIDATE_COUNT=3", "G3_HOST_CANDIDATE_COUNT", 3),
            ("RSP_LOADED_MONOTONIC_MS=9999", "RSP_LOADED_MONOTONIC_MS", 9999),
        )
        for line, key, value in cases:
            with self.subTest(line=line):
                timeline = latency_timeline.CameraRequestLatencyTimeline()
                self.transport._latency_timeline = timeline
                self.transport._observe_native_stage_marker(line)
                self.assertEqual(timeline._native.get(key), value)

    async def test_new_stage_markers_never_touch_observation_boundaries(self) -> None:
        self.transport._observe_native_stage_marker("G2_GATHER_CALL_MONOTONIC_MS=42")
        self.assertEqual(
            [key for key in latency_timeline._BOUNDARY_KEYS if self.timeline.has(key)],
            [],
        )

    async def test_unrelated_line_is_a_no_op(self) -> None:
        self.transport._observe_native_stage_marker("ICE_GATHER=PASS")
        self.assertEqual(self.timeline._native, {})

    async def test_no_op_when_timeline_is_unset(self) -> None:
        self.transport._latency_timeline = None
        self.transport._observe_native_stage_marker("G0_NATIVE_PROCESS_START_MONOTONIC_MS=1")
        # No exception, and nothing to observe -- covered by not raising.


class P119IsolationTests(unittest.TestCase):
    """PART 6 item 4: settle stays 1000; existing boundaries/marker map
    untouched; only the intended L1 removal + new markers changed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = p119_transform(
            DOOR_SOURCE.read_text(encoding="utf-8"), include_p116=True
        )

    def test_settle_is_still_1000(self) -> None:
        self.assertIn("#define ENTRANCE_SIGNAL_SETTLE_MS 1000", self.generated)
        self.assertNotIn("#define ENTRANCE_SIGNAL_SETTLE_MS 4000", self.generated)

    def test_23_observation_boundaries_unchanged(self) -> None:
        self.assertEqual(latency_timeline.MAX_BOUNDARIES, 23)

    def test_existing_native_marker_map_unchanged(self) -> None:
        media_transport = transport_fixture.media_transport
        self.assertEqual(len(media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES), 11)
        for line in media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES:
            with self.subTest(line=line):
                self.assertIn(f'"{line}\\n"', self.generated)

    def test_door_ice_pseudotcp_constants_untouched(self) -> None:
        # Positive checks: the surrounding door/ICE/PseudoTCP constants this
        # change must never touch are still exactly what they were before.
        for needle in (
            "#define V4_DOOR_SETTLE_MS 1000",
            'nice_agent_set_stream_name(\n        agent,\n        stream_id,\n        "audio"',
            "#define PSEUDOTCP_CONVERSATION 0",
            "controlling-mode",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.generated)


if __name__ == "__main__":
    unittest.main()
