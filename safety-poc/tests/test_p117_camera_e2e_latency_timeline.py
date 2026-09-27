#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
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
SETTLE_TRANSFORM = MEDIA_DIR / "entrance_device_video_ack_observation_transform.py"
SETTLE_DEFINE_OLD = "#define ENTRANCE_SIGNAL_SETTLE_MS 4000"
SETTLE_DEFINE_NEW = "#define ENTRANCE_SIGNAL_SETTLE_MS 1000"
# Recorded generated-source identities of the settle round: the base commit's
# output and this candidate's output. The base value is what makes the
# single-token negative guard self-contained.
SETTLE_BASE_SOURCE_SHA256 = (
    "4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c"
)
SETTLE_CANDIDATE_SOURCE_SHA256 = (
    "4448e8368bd6275a2cd398c35ef171d012f315d2bb5bd05daf2e33a13d4c0001"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


latency_timeline = _load("comelit_latency_timeline", COMPONENT / "latency_timeline.py")
h264_recovery = _load("comelit_h264_recovery_p117", COMPONENT / "h264_recovery.py")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mvp1_local_sdp_readiness_corrective as transport_fixture  # noqa: E402

sys.path.insert(0, str(MEDIA_DIR))
from entrance_p116_r65_production_media_refresh_transform import (  # noqa: E402
    transform as r65_transform,
)

EXPECTED_BOUNDARIES = (
    "T00_CAMERA_REQUEST",
    "T01_LEASE_ACQUIRE_BEGIN",
    "T02_LISTENER_PAUSE_REQUESTED",
    "T03_LISTENER_PAUSED_CONFIRMED",
    "T04_TRANSPORT_START_BEGIN",
    "T05_ICE_GATHER_DONE",
    "T06_CLOUD_NEGOTIATE_BEGIN",
    "T07_REMOTE_SDP_READY",
    "T08_ICE_CONNECTED",
    "T09_PSEUDOTCP_OPEN",
    "T10_CTPP_READY",
    "T11_SIGNALING_ARMED",
    "T12_SELF_ACTIVATION_SENT",
    "T13_RTPC_BEGIN",
    "T14_RTPC_CONTROL_COMPLETE",
    "T15_MEDIA_ACTIVE",
    "T16_FIRST_VIDEO_RTP",
    "T17_FIRST_DECODABLE_FRAME",
    "T18_HA_STREAM_READY",
    "T19_HLS_PROVIDER_PRESENT",
    "T20_HLS_FIRST_PART",
    "T21_HLS_FIRST_COMPLETE_SEGMENT",
)

EXPECTED_FIELD_ORDER = (
    "CAMERA_REQUEST_TO_LISTENER_PAUSED_MS",
    "LISTENER_PAUSED_TO_TRANSPORT_START_MS",
    "TRANSPORT_START_TO_CLOUD_NEGOTIATE_MS",
    "CLOUD_NEGOTIATE_TO_REMOTE_SDP_MS",
    "REMOTE_SDP_TO_ICE_CONNECTED_MS",
    "TRANSPORT_START_TO_ICE_CONNECTED_MS",
    "ICE_CONNECTED_TO_PSEUDOTCP_OPEN_MS",
    "PSEUDOTCP_OPEN_TO_CTPP_READY_MS",
    "ICE_CONNECTED_TO_CTPP_READY_MS",
    "CTPP_READY_TO_SIGNALING_ARMED_MS",
    "SIGNALING_ARMED_TO_SELF_ACTIVATION_MS",
    "SELF_ACTIVATION_TO_RTPC_BEGIN_MS",
    "RTPC_BEGIN_TO_RTPC_COMPLETE_MS",
    "RTPC_COMPLETE_TO_FIRST_VIDEO_RTP_MS",
    "FIRST_VIDEO_RTP_TO_DECODABLE_FRAME_MS",
    "DECODABLE_FRAME_TO_HLS_FIRST_PART_MS",
    "HLS_FIRST_PART_TO_FIRST_COMPLETE_SEGMENT_MS",
    "CAMERA_REQUEST_TO_FIRST_VIDEO_RTP_MS",
    "CAMERA_REQUEST_TO_FIRST_DECODABLE_FRAME_MS",
    "CAMERA_REQUEST_TO_FIRST_HLS_PART_MS",
    "CAMERA_REQUEST_TO_FIRST_HLS_SEGMENT_MS",
)

EXPECTED_NATIVE_MARKER_MAP = {
    "ICE_GATHER=PASS": "T05_ICE_GATHER_DONE",
    "ICE_CONNECTED=PASS": "T08_ICE_CONNECTED",
    "PSEUDOTCP_OPEN=PASS": "T09_PSEUDOTCP_OPEN",
    "V4_CTPP_REGISTRATION=PASS": "T10_CTPP_READY",
    "ENTRANCE_SIGNALING_ARMED=true": "T11_SIGNALING_ARMED",
    "ENTRANCE_SELF_ACTIVATION_SENT=PASS": "T12_SELF_ACTIVATION_SENT",
    "P78_CTPP_REGISTERED_REUSED=true": "T13_RTPC_BEGIN",
    "P78_RTPC_SIGNALING_RESULT=PASS": "T14_RTPC_CONTROL_COMPLETE",
    "P80_MEDIA_ACTIVE=true": "T15_MEDIA_ACTIVE",
    "P80_VIDEO_RTP_FORWARDING=PASS": "T16_FIRST_VIDEO_RTP",
}


def _function_source(tree: ast.AST, source: str, name: str) -> str:
    node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return ast.get_source_segment(source, node) or ""


def _generate_head_source() -> str:
    return r65_transform(DOOR_SOURCE.read_text(encoding="utf-8"), include_p116=True)


def _generate_base_source() -> str:
    """Reconstruct the pre-change generated production source hermetically.

    The settle round changed exactly one C token in the generated source.
    Reverting that single token must reproduce the recorded base hash byte for
    byte -- that equality IS the proof that no other textual delta exists.
    Resolving the pre-change text from git history would not be stronger (and
    is unavailable in a shallow CI checkout), so the recorded hash is the
    anchor instead.
    """
    head_source = _generate_head_source()
    if head_source.count(SETTLE_DEFINE_NEW) != 1:
        raise AssertionError("settle candidate define is not present exactly once")
    if SETTLE_DEFINE_OLD in head_source:
        raise AssertionError("settle candidate still contains the old define")
    base_source = head_source.replace(SETTLE_DEFINE_NEW, SETTLE_DEFINE_OLD, 1)
    base_sha = hashlib.sha256(base_source.encode("utf-8")).hexdigest()
    if base_sha != SETTLE_BASE_SOURCE_SHA256:
        raise AssertionError(
            f"reverting the settle token does not reproduce the base generated "
            f"source sha256 (got {base_sha})"
        )
    return base_source


class CameraRequestLatencyTimelineTests(unittest.TestCase):
    def test_bounded_key_set_has_exactly_the_frozen_boundaries(self) -> None:
        self.assertEqual(latency_timeline.MAX_BOUNDARIES, 22)
        self.assertEqual(latency_timeline._BOUNDARY_KEYS, frozenset(EXPECTED_BOUNDARIES))
        for name in EXPECTED_BOUNDARIES:
            self.assertEqual(getattr(latency_timeline, name), name)

    def test_mark_records_only_first_observation(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark(latency_timeline.T00_CAMERA_REQUEST, 10.0)
        timeline.mark(latency_timeline.T00_CAMERA_REQUEST, 999.0)
        timeline.mark(latency_timeline.T15_MEDIA_ACTIVE, 12.0)
        fields = timeline.summary_fields()
        # T00 stayed at 10.0, T15 at 12.0 => derived 2000ms is unaffected by
        # the later, ignored 999.0 write.
        self.assertEqual(fields["CAMERA_REQUEST_TO_FIRST_VIDEO_RTP_MS"], "N_A")

    def test_unknown_boundary_is_silently_ignored(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark("NOT_A_REAL_BOUNDARY", 1.0)
        self.assertFalse(timeline.has("NOT_A_REAL_BOUNDARY"))

    def test_missing_boundary_is_reported_as_n_a(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        fields = timeline.summary_fields()
        for value in fields.values():
            self.assertEqual(value, "N_A")

    def test_full_timeline_computes_exact_integer_millisecond_offsets(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        boundaries = [getattr(latency_timeline, name) for name in EXPECTED_BOUNDARIES]
        for index, boundary in enumerate(boundaries):
            timeline.mark(boundary, 100.0 + index * 0.5)
        fields = timeline.summary_fields()
        self.assertEqual(fields["CAMERA_REQUEST_TO_LISTENER_PAUSED_MS"], "1500")
        self.assertEqual(fields["CAMERA_REQUEST_TO_FIRST_HLS_SEGMENT_MS"], "10500")
        self.assertEqual(fields["FIRST_VIDEO_RTP_TO_DECODABLE_FRAME_MS"], "500")
        self.assertTrue(timeline.is_complete())
        self.assertFalse(timeline.emitted)
        timeline.mark_emitted()
        self.assertTrue(timeline.emitted)

    def test_log_line_uses_stable_marker_and_exact_field_order(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        line = timeline.log_line()
        self.assertTrue(line.startswith("COMELIT_CAMERA_E2E_LATENCY "))
        for name, _, _ in latency_timeline._DERIVED_FIELDS:
            self.assertIn(f"{name}=N_A", line)

    def test_emitted_field_list_matches_exact_order_with_twentyone_fields(self) -> None:
        field_names = tuple(name for name, _, _ in latency_timeline._DERIVED_FIELDS)
        self.assertEqual(field_names, EXPECTED_FIELD_ORDER)
        self.assertEqual(len(EXPECTED_FIELD_ORDER), 21)
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        line = timeline.log_line()
        body = line[len("COMELIT_CAMERA_E2E_LATENCY "):]
        emitted_order = tuple(pair.split("=", 1)[0] for pair in body.split(" "))
        self.assertEqual(emitted_order, EXPECTED_FIELD_ORDER)

    def test_new_field_reports_n_a_when_only_one_endpoint_observed(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark(latency_timeline.T10_CTPP_READY, 5.0)
        # T11_SIGNALING_ARMED never observed: the new
        # CTPP_READY_TO_SIGNALING_ARMED_MS field must be N_A, never estimated.
        fields = timeline.summary_fields()
        self.assertEqual(fields["CTPP_READY_TO_SIGNALING_ARMED_MS"], "N_A")

    def test_negative_delta_from_out_of_order_marks_is_n_a(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark(latency_timeline.T00_CAMERA_REQUEST, 50.0)
        timeline.mark(latency_timeline.T03_LISTENER_PAUSED_CONFIRMED, 10.0)
        fields = timeline.summary_fields()
        self.assertEqual(fields["CAMERA_REQUEST_TO_LISTENER_PAUSED_MS"], "N_A")


class H264DecodableFrameCallbackTests(unittest.TestCase):
    def _nal(self, nal_type: int, body: bytes = b"\x80") -> bytes:
        return bytes([nal_type]) + body

    def _rtp(self, seq: int, payload: bytes, *, timestamp: int = 9000, ssrc: int = 7) -> bytes:
        first = 0x80
        header = struct.pack("!BBHII", first, 99, seq, timestamp, ssrc)
        return header + payload

    def test_callback_fires_exactly_once_after_sps_pps_then_idr(self) -> None:
        calls: list[None] = []
        rewriter = h264_recovery.H264RecoveryRewriter(
            on_decodable_frame=lambda: calls.append(None)
        )
        rewriter.rewrite_rtp_packet(self._rtp(1, self._nal(7)))
        rewriter.rewrite_rtp_packet(self._rtp(2, self._nal(8)))
        self.assertEqual(calls, [])
        idr_slice = bytes([5]) + b"\x80"
        rewriter.rewrite_rtp_packet(self._rtp(3, idr_slice))
        self.assertEqual(len(calls), 1)
        # A second IDR later (new access unit / timestamp) must not re-fire.
        rewriter.rewrite_rtp_packet(self._rtp(4, self._nal(7), timestamp=9100))
        rewriter.rewrite_rtp_packet(self._rtp(5, self._nal(8), timestamp=9100))
        rewriter.rewrite_rtp_packet(
            self._rtp(6, bytes([5]) + b"\x80", timestamp=9100)
        )
        self.assertEqual(len(calls), 1)

    def test_callback_does_not_fire_without_sps_and_pps_first(self) -> None:
        calls: list[None] = []
        rewriter = h264_recovery.H264RecoveryRewriter(
            on_decodable_frame=lambda: calls.append(None)
        )
        idr_slice = bytes([5]) + b"\x80"
        rewriter.rewrite_rtp_packet(self._rtp(1, idr_slice))
        self.assertEqual(calls, [])
        # idr_count still advances normally: the diagnostic hook never
        # changes existing rewrite/counter behavior.
        self.assertEqual(rewriter.idr_count, 1)

    def test_default_callback_is_none_and_behavior_is_unchanged(self) -> None:
        rewriter = h264_recovery.H264RecoveryRewriter()
        rewriter.rewrite_rtp_packet(self._rtp(1, self._nal(7)))
        rewriter.rewrite_rtp_packet(self._rtp(2, self._nal(8)))
        out = rewriter.rewrite_rtp_packet(self._rtp(3, bytes([5]) + b"\x80"))
        self.assertEqual(len(out), 1)
        self.assertEqual(rewriter.idr_count, 1)

    def test_shim_forwards_callback_to_rewriter(self) -> None:
        calls: list[None] = []
        shim = h264_recovery.H264RecoveryRtpShim(
            input_port=1,
            output_port=2,
            on_decodable_frame=lambda: calls.append(None),
        )
        self.assertIs(shim._rewriter._on_decodable_frame, shim._rewriter._on_decodable_frame)
        shim._rewriter.rewrite_rtp_packet(self._rtp(1, self._nal(7)))
        shim._rewriter.rewrite_rtp_packet(self._rtp(2, self._nal(8)))
        shim._rewriter.rewrite_rtp_packet(self._rtp(3, bytes([5]) + b"\x80"))
        self.assertEqual(len(calls), 1)


class MediaTransportLatencyMarkerObservationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise ``_observe_latency_marker`` without any HA/aiohttp stack."""

    async def asyncSetUp(self) -> None:
        self.media_transport = transport_fixture.media_transport
        self.transport = object.__new__(self.media_transport.ComelitEntranceMediaTransport)
        self.transport._progress = self.media_transport.MediaProgressDiagnostics()
        self.timeline = latency_timeline.CameraRequestLatencyTimeline()
        self.transport._latency_timeline = self.timeline

    async def test_no_op_when_timeline_is_unset(self) -> None:
        self.transport._latency_timeline = None
        self.transport._observe_latency_marker("ICE_GATHER=PASS")
        self.assertFalse(self.timeline.has(latency_timeline.T05_ICE_GATHER_DONE))

    async def test_native_marker_map_matches_frozen_taxonomy(self) -> None:
        actual = {
            line: boundary_value
            for line, boundary_value in self.media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES.items()
        }
        expected = {
            line: getattr(latency_timeline, name)
            for line, name in EXPECTED_NATIVE_MARKER_MAP.items()
        }
        self.assertEqual(actual, expected)

    def _mapped_marker_cases(self):
        for line, name in EXPECTED_NATIVE_MARKER_MAP.items():
            yield line, getattr(latency_timeline, name)

    async def test_each_mapped_native_marker_line_stamps_its_boundary(self) -> None:
        for line, boundary in self._mapped_marker_cases():
            with self.subTest(line=line):
                timeline = latency_timeline.CameraRequestLatencyTimeline()
                self.transport._latency_timeline = timeline
                self.transport._observe_latency_marker(line)
                self.assertTrue(timeline.has(boundary), line)

    async def test_true_ctpp_registration_marker_is_v4_ctpp_registration(self) -> None:
        # The taxonomy correction this round exists for: T10_CTPP_READY binds
        # to V4_CTPP_REGISTRATION=PASS (the real registration completion
        # inside p12_tx_completed's P12_TX_V4_ACK_PAIR case), not to
        # P78_CTPP_REGISTERED_REUSED=true (which only marks the start of the
        # later RTPC control stage, inside p78_begin_rtpc_control()).
        self.assertEqual(
            self.media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES[
                "V4_CTPP_REGISTRATION=PASS"
            ],
            latency_timeline.T10_CTPP_READY,
        )
        self.assertEqual(
            self.media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES[
                "P78_CTPP_REGISTERED_REUSED=true"
            ],
            latency_timeline.T13_RTPC_BEGIN,
        )

    async def test_unrelated_marker_line_stamps_nothing(self) -> None:
        self.transport._observe_latency_marker("P80_AUDIO_RTP_FORWARDING=PASS")
        self.assertEqual(
            [key for key in latency_timeline._BOUNDARY_KEYS if self.timeline.has(key)],
            [],
        )

    async def test_first_positive_video_rtp_packet_count_stamps_t16(self) -> None:
        self.transport._observe_latency_marker("P80_VIDEO_RTP_PACKETS=0")
        self.assertFalse(self.timeline.has(latency_timeline.T16_FIRST_VIDEO_RTP))
        self.transport._observe_latency_marker("P80_VIDEO_RTP_PACKETS=1")
        self.assertTrue(self.timeline.has(latency_timeline.T16_FIRST_VIDEO_RTP))


class NativeMarkerGeneratedSourceObservabilityTests(unittest.TestCase):
    """A marker the generated production source never prints would be
    silently unobservable; prove every mapped marker literal actually
    appears, verbatim, in the real R65-generated production source."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated_source = _generate_head_source()

    def test_every_native_marker_key_appears_verbatim_in_generated_source(self) -> None:
        media_transport = transport_fixture.media_transport
        for line in media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES:
            with self.subTest(line=line):
                self.assertIn(f'"{line}\\n"', self.generated_source, line)

    def test_video_rtp_packets_prefix_appears_in_generated_source(self) -> None:
        self.assertIn('"P80_VIDEO_RTP_PACKETS=', self.generated_source)


class SettleCandidateGateTests(unittest.TestCase):
    """PART 2: prove the one-token ENTRANCE_SIGNAL_SETTLE_MS 4000 -> 1000
    change, isolated from everything else in the generated source."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated_source = _generate_head_source()
        cls.transform_text = SETTLE_TRANSFORM.read_text(encoding="utf-8")

    def test_exactly_one_settle_define_at_1000_in_generated_source(self) -> None:
        self.assertEqual(
            self.generated_source.count(SETTLE_DEFINE_NEW), 1
        )

    def test_generated_source_identity_matches_the_recorded_candidate_sha(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.generated_source.encode("utf-8")).hexdigest(),
            SETTLE_CANDIDATE_SOURCE_SHA256,
        )

    def test_zero_occurrences_of_the_old_4000_settle_define(self) -> None:
        self.assertEqual(
            self.generated_source.count(SETTLE_DEFINE_OLD), 0
        )

    def test_timer_call_site_still_uses_the_settle_macro(self) -> None:
        self.assertIn("g_timeout_add(", self.generated_source)
        self.assertIn("ENTRANCE_SIGNAL_SETTLE_MS", self.generated_source)
        # The callback definition ("entrance_signal_start_cb(gpointer data)")
        # comes first; the actual g_timeout_add(...) call site passing the
        # bare function name as a callback pointer comes after it.
        callback_index = self.generated_source.index(
            "entrance_signal_start_cb,", self.generated_source.index(
                "entrance_signal_start_cb(gpointer data)"
            )
        )
        timer_start = self.generated_source.rindex("g_timeout_add(", 0, callback_index)
        timer_call = self.generated_source[timer_start:callback_index]
        self.assertIn("ENTRANCE_SIGNAL_SETTLE_MS", timer_call)

    def test_transform_replacement_block_contains_exactly_one_settle_literal(self) -> None:
        # SETTLE_REPLACEMENT_COUNT=1 invariant: only the state_replacement
        # text block (the block that becomes generated production source) is
        # touched. The state_anchor block above it must still read 4000,
        # since that text matches the *input* the lower overlay produces.
        anchor_start = self.transform_text.index("state_anchor = ")
        replacement_start = self.transform_text.index(
            "state_replacement = ", anchor_start
        )
        replacement_end = self.transform_text.index(
            "\n    source = _replace_once(source, state_anchor, state_replacement",
            replacement_start,
        )
        anchor_block = self.transform_text[anchor_start:replacement_start]
        replacement_block = self.transform_text[replacement_start:replacement_end]

        settle_replacement_count = replacement_block.count(
            "#define ENTRANCE_SIGNAL_SETTLE_MS 1000"
        )
        self.assertEqual(settle_replacement_count, 1)
        self.assertEqual(
            replacement_block.count("#define ENTRANCE_SIGNAL_SETTLE_MS 4000"), 0
        )
        self.assertEqual(anchor_block.count("#define ENTRANCE_SIGNAL_SETTLE_MS 4000"), 1)
        self.assertEqual(anchor_block.count("#define ENTRANCE_SIGNAL_SETTLE_MS 1000"), 0)

    def test_no_other_settle_define_copies_were_touched(self) -> None:
        # The two superseded copies of this same literal, overridden by this
        # overlay, must still read 4000 in their own source files (they never
        # reach the generated production source, but must not be silently
        # edited either).
        for other in (
            "entrance_media_observation_transform.py",
            "entrance_self_activation_signaling_transform.py",
        ):
            text = (MEDIA_DIR / other).read_text(encoding="utf-8")
            self.assertIn("#define ENTRANCE_SIGNAL_SETTLE_MS 4000", text, other)


class SettleCandidateNegativeGuardTests(unittest.TestCase):
    """Machine-checked negative guard: the settle change introduces no other
    textual delta in the generated production source."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.head_source = _generate_head_source()
        cls.base_source = _generate_base_source()

    def test_generated_source_diff_is_exactly_one_line(self) -> None:
        head_lines = self.head_source.splitlines()
        base_lines = self.base_source.splitlines()
        self.assertEqual(len(head_lines), len(base_lines))
        differing = [
            (index, base, head)
            for index, (base, head) in enumerate(zip(base_lines, head_lines))
            if base != head
        ]
        self.assertEqual(len(differing), 1, differing)
        _, base_line, head_line = differing[0]
        self.assertEqual(base_line, "#define ENTRANCE_SIGNAL_SETTLE_MS 4000")
        self.assertEqual(head_line, "#define ENTRANCE_SIGNAL_SETTLE_MS 1000")

    def test_no_door_gate_retry_timeout_ice_pseudotcp_ctpp_rtpc_delta(self) -> None:
        head_lines = set(self.head_source.splitlines())
        base_lines = set(self.base_source.splitlines())
        only_in_head = head_lines - base_lines
        only_in_base = base_lines - head_lines
        self.assertEqual(only_in_base, {"#define ENTRANCE_SIGNAL_SETTLE_MS 4000"})
        self.assertEqual(only_in_head, {"#define ENTRANCE_SIGNAL_SETTLE_MS 1000"})
        forbidden_substrings = (
            "v4_door",
            "V4_DOOR",
            "DOOR_WRITE",
            "GATE_ACTION",
            "gate_action",
            "RETRY",
            "retry",
            "TIMEOUT",
            "timeout",
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "PSEUDOTCP_",
            "CTPP_",
            "RTPC_",
        )
        for forbidden in forbidden_substrings:
            self.assertNotIn(forbidden, only_in_head, forbidden)
            self.assertNotIn(forbidden, only_in_base, forbidden)


class MediaTransportEndToEndBootstrapLatencyTests(
    transport_fixture.unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        import tempfile

        self.tmpdir = tempfile.TemporaryDirectory()
        transport_fixture._install_transport_files(
            transport_fixture.media_transport, Path(self.tmpdir.name)
        )
        self.old_subprocess = transport_fixture.media_transport.asyncio.create_subprocess_exec

    async def asyncTearDown(self) -> None:
        transport_fixture.media_transport.asyncio.create_subprocess_exec = (
            self.old_subprocess
        )
        self.tmpdir.cleanup()

    async def test_cold_bootstrap_stamps_boundaries_in_order(self) -> None:
        scenario = transport_fixture.NativeScenario()
        transport_fixture.media_transport.asyncio.create_subprocess_exec = (
            scenario.create_subprocess_exec
        )
        transport = transport_fixture._make_transport(transport_fixture.FakeHass(scenario))
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        transport.set_latency_timeline(timeline)

        start_task = asyncio.create_task(transport.async_start("entrance"))
        await asyncio.wait_for(
            asyncio.sleep(0), timeout=1
        )  # let the task begin executing
        self.assertTrue(timeline.has(latency_timeline.T04_TRANSPORT_START_BEGIN))

        # Wait until the native offer is observed (ICE_GATHER=PASS), then
        # feed the remaining upstream markers before releasing MEDIA_ACTIVE.
        while scenario.current_process is None:
            await asyncio.sleep(0)
        process = scenario.current_process
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=1)
        process.feed_line("ICE_CONNECTED=PASS")
        process.feed_line("PSEUDOTCP_OPEN=PASS")
        process.feed_line("V4_CTPP_REGISTRATION=PASS")
        process.feed_line("ENTRANCE_SIGNALING_ARMED=true")
        process.feed_line("ENTRANCE_SELF_ACTIVATION_SENT=PASS")
        process.feed_line("P78_CTPP_REGISTERED_REUSED=true")
        process.feed_line("P78_RTPC_SIGNALING_RESULT=PASS")
        scenario.release_active.set()
        await asyncio.wait_for(scenario.active_sent.wait(), timeout=1)
        process.feed_line("P80_VIDEO_RTP_FORWARDING=PASS")
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=1)

        scenario.release_sdp_write.set()
        await asyncio.wait_for(start_task, timeout=1)

        for boundary in (
            latency_timeline.T04_TRANSPORT_START_BEGIN,
            latency_timeline.T05_ICE_GATHER_DONE,
            latency_timeline.T06_CLOUD_NEGOTIATE_BEGIN,
            latency_timeline.T07_REMOTE_SDP_READY,
            latency_timeline.T08_ICE_CONNECTED,
            latency_timeline.T09_PSEUDOTCP_OPEN,
            latency_timeline.T10_CTPP_READY,
            latency_timeline.T11_SIGNALING_ARMED,
            latency_timeline.T12_SELF_ACTIVATION_SENT,
            latency_timeline.T13_RTPC_BEGIN,
            latency_timeline.T14_RTPC_CONTROL_COMPLETE,
            latency_timeline.T15_MEDIA_ACTIVE,
            latency_timeline.T16_FIRST_VIDEO_RTP,
        ):
            self.assertTrue(timeline.has(boundary), boundary)

        await transport.async_stop()
        self.assertIsNone(transport._latency_timeline)


class MediaSessionListenerPauseLatencyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.media_session = _load(
            "comelit_media_session_p117", COMPONENT / "media_session.py"
        )

    class _FakeListener:
        def __init__(self) -> None:
            self._paused = False
            self.attached_media_busy = False

        @property
        def media_paused(self) -> bool:
            return self._paused

        async def async_pause_for_media(self) -> None:
            self._paused = True

        async def async_resume_after_media(self) -> None:
            self._paused = False

    class _FakeTransport:
        def __init__(self) -> None:
            self._active = False

        @property
        def active(self) -> bool:
            return self._active

        async def async_start(self, panel: str) -> None:
            del panel
            self._active = True

        async def async_stop(self) -> None:
            self._active = False

    class _FakeTimeline:
        def __init__(self) -> None:
            self.marks: list[str] = []

        def mark(self, boundary: str, when: float) -> None:
            del when
            self.marks.append(boundary)

    async def test_pause_requested_then_confirmed_are_marked_in_order(self) -> None:
        manager = self.media_session.ComelitMediaSessionManager(
            self._FakeListener(), self._FakeTransport()
        )
        timeline = self._FakeTimeline()
        manager.set_latency_timeline(timeline)
        await manager.async_acquire(panel="entrance", reason="camera_view")
        self.assertEqual(
            timeline.marks,
            ["T02_LISTENER_PAUSE_REQUESTED", "T03_LISTENER_PAUSED_CONFIRMED"],
        )

    async def test_no_timeline_bound_is_a_silent_no_op(self) -> None:
        manager = self.media_session.ComelitMediaSessionManager(
            self._FakeListener(), self._FakeTransport()
        )
        await manager.async_acquire(panel="entrance", reason="camera_view")
        self.assertIsNone(manager._latency_timeline)

    async def test_cleared_timeline_receives_no_further_marks(self) -> None:
        manager = self.media_session.ComelitMediaSessionManager(
            self._FakeListener(), self._FakeTransport()
        )
        timeline = self._FakeTimeline()
        manager.set_latency_timeline(timeline)
        manager.set_latency_timeline(None)
        await manager.async_acquire(panel="entrance", reason="camera_view")
        self.assertEqual(timeline.marks, [])


class CameraLatencyWiringStructuralTests(unittest.TestCase):
    """AST/text structural checks, matching the existing R18/R20 test style,
    since executing camera.py end to end requires the full HA Camera/Stream
    stack that is not available offline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.camera = (COMPONENT / "camera.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.camera)

    def test_latency_timeline_import_present(self) -> None:
        self.assertIn("from .latency_timeline import", self.camera)
        self.assertIn("CameraRequestLatencyTimeline", self.camera)

    def test_t00_marked_before_camera_view_acquire_begins(self) -> None:
        create_stream = _function_source(self.tree, self.camera, "async_create_stream")
        self.assertIn("timeline.mark(T00_CAMERA_REQUEST", create_stream)
        self.assertLess(
            create_stream.index("timeline.mark(T00_CAMERA_REQUEST"),
            create_stream.index("await self._async_acquire_camera_view_media()"),
        )
        self.assertIn("timeline.mark(T18_HA_STREAM_READY", create_stream)
        self.assertIn(
            "stream.set_update_callback(self._async_handle_stream_update)",
            create_stream,
        )

    def test_t01_marked_at_entry_of_camera_view_acquire(self) -> None:
        acquire = _function_source(
            self.tree, self.camera, "_async_acquire_camera_view_media"
        )
        self.assertIn("timeline.mark(T01_LEASE_ACQUIRE_BEGIN", acquire)
        self.assertIn("MEDIA_PHASE_INACTIVE", acquire)
        self.assertIn("set_latency_timeline", acquire)

    def test_hls_boundaries_recorded_from_real_stream_update_callback(self) -> None:
        recorder = _function_source(
            self.tree, self.camera, "_record_hls_latency_boundaries"
        )
        self.assertIn("T19_HLS_PROVIDER_PRESENT", recorder)
        self.assertIn("T20_HLS_FIRST_PART", recorder)
        self.assertIn("T21_HLS_FIRST_COMPLETE_SEGMENT", recorder)
        self.assertIn("_hls_runtime_diagnostics()", recorder)
        self.assertNotIn("_CAMERA_VIEW_MONITOR_INTERVAL_SECONDS", recorder)

    def test_log_emitted_at_most_once_and_at_teardown_if_incomplete(self) -> None:
        emit = _function_source(self.tree, self.camera, "_emit_latency_log")
        self.assertIn("timeline.emitted", emit)
        self.assertIn("timeline.mark_emitted()", emit)
        release = _function_source(
            self.tree, self.camera, "_async_release_camera_view_media"
        )
        self.assertIn("_emit_latency_log", release)

    def test_log_marker_is_stable_and_greppable(self) -> None:
        self.assertIn("COMELIT_CAMERA_E2E_LATENCY", latency_timeline.LOG_MARKER)

    def test_shim_callback_wiring_present_for_first_decodable_frame(self) -> None:
        transport_source = (COMPONENT / "media_transport.py").read_text(encoding="utf-8")
        transport_tree = ast.parse(transport_source)
        shim_start = _function_source(
            transport_tree, transport_source, "_async_start_video_recovery_shim"
        )
        self.assertIn("T17_FIRST_DECODABLE_FRAME", shim_start)
        self.assertIn("on_decodable_frame=on_decodable_frame", shim_start)


if __name__ == "__main__":
    unittest.main()
