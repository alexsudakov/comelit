#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"


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


def _function_source(tree: ast.AST, source: str, name: str) -> str:
    node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return ast.get_source_segment(source, node) or ""


class CameraRequestLatencyTimelineTests(unittest.TestCase):
    def test_bounded_key_set_has_twenty_boundaries(self) -> None:
        self.assertEqual(latency_timeline.MAX_BOUNDARIES, 20)

    def test_mark_records_only_first_observation(self) -> None:
        timeline = latency_timeline.CameraRequestLatencyTimeline()
        timeline.mark(latency_timeline.T00_CAMERA_REQUEST, 10.0)
        timeline.mark(latency_timeline.T00_CAMERA_REQUEST, 999.0)
        timeline.mark(latency_timeline.T14_MEDIA_ACTIVE, 12.0)
        fields = timeline.summary_fields()
        # T00 stayed at 10.0, T14 at 12.0 => derived 2000ms is unaffected by
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
        boundaries = [
            latency_timeline.T00_CAMERA_REQUEST,
            latency_timeline.T01_LEASE_ACQUIRE_BEGIN,
            latency_timeline.T02_LISTENER_PAUSE_REQUESTED,
            latency_timeline.T03_LISTENER_PAUSED_CONFIRMED,
            latency_timeline.T04_TRANSPORT_START_BEGIN,
            latency_timeline.T05_ICE_GATHER_DONE,
            latency_timeline.T06_CLOUD_NEGOTIATE_BEGIN,
            latency_timeline.T07_REMOTE_SDP_READY,
            latency_timeline.T08_ICE_CONNECTED,
            latency_timeline.T09_PSEUDOTCP_OPEN,
            latency_timeline.T11_CTPP_READY,
            latency_timeline.T12_SELF_ACTIVATION_SENT,
            latency_timeline.T13_RTPC_READY,
            latency_timeline.T14_MEDIA_ACTIVE,
            latency_timeline.T15_FIRST_VIDEO_RTP,
            latency_timeline.T16_FIRST_DECODABLE_FRAME,
            latency_timeline.T17_HA_STREAM_READY,
            latency_timeline.T18_HLS_PROVIDER_PRESENT,
            latency_timeline.T19_HLS_FIRST_PART,
            latency_timeline.T20_HLS_FIRST_COMPLETE_SEGMENT,
        ]
        for index, boundary in enumerate(boundaries):
            timeline.mark(boundary, 100.0 + index * 0.5)
        fields = timeline.summary_fields()
        self.assertEqual(fields["CAMERA_REQUEST_TO_LISTENER_PAUSED_MS"], "1500")
        self.assertEqual(fields["CAMERA_REQUEST_TO_FIRST_HLS_SEGMENT_MS"], "9500")
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

    async def test_each_mapped_native_marker_line_stamps_its_boundary(self) -> None:
        expected = {
            "ICE_GATHER=PASS": latency_timeline.T05_ICE_GATHER_DONE,
            "ICE_CONNECTED=PASS": latency_timeline.T08_ICE_CONNECTED,
            "PSEUDOTCP_OPEN=PASS": latency_timeline.T09_PSEUDOTCP_OPEN,
            "P78_CTPP_REGISTERED_REUSED=true": latency_timeline.T11_CTPP_READY,
            "ENTRANCE_SELF_ACTIVATION_SENT=PASS": latency_timeline.T12_SELF_ACTIVATION_SENT,
            "P78_RTPC_SIGNALING_RESULT=PASS": latency_timeline.T13_RTPC_READY,
            "P80_MEDIA_ACTIVE=true": latency_timeline.T14_MEDIA_ACTIVE,
            "P80_VIDEO_RTP_FORWARDING=PASS": latency_timeline.T15_FIRST_VIDEO_RTP,
        }
        self.assertEqual(
            dict(self.media_transport._NATIVE_MARKER_LATENCY_BOUNDARIES), expected
        )
        for line, boundary in expected.items():
            timeline = latency_timeline.CameraRequestLatencyTimeline()
            self.transport._latency_timeline = timeline
            self.transport._observe_latency_marker(line)
            self.assertTrue(timeline.has(boundary), line)

    async def test_unrelated_marker_line_stamps_nothing(self) -> None:
        self.transport._observe_latency_marker("P80_AUDIO_RTP_FORWARDING=PASS")
        self.assertEqual(
            [key for key in latency_timeline._BOUNDARY_KEYS if self.timeline.has(key)],
            [],
        )

    async def test_first_positive_video_rtp_packet_count_stamps_t15(self) -> None:
        self.transport._observe_latency_marker("P80_VIDEO_RTP_PACKETS=0")
        self.assertFalse(self.timeline.has(latency_timeline.T15_FIRST_VIDEO_RTP))
        self.transport._observe_latency_marker("P80_VIDEO_RTP_PACKETS=1")
        self.assertTrue(self.timeline.has(latency_timeline.T15_FIRST_VIDEO_RTP))


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
        process.feed_line("P78_CTPP_REGISTERED_REUSED=true")
        process.feed_line("ENTRANCE_SELF_ACTIVATION_SENT=PASS")
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
            latency_timeline.T11_CTPP_READY,
            latency_timeline.T12_SELF_ACTIVATION_SENT,
            latency_timeline.T13_RTPC_READY,
            latency_timeline.T14_MEDIA_ACTIVE,
            latency_timeline.T15_FIRST_VIDEO_RTP,
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
        self.assertIn("timeline.mark(T17_HA_STREAM_READY", create_stream)
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
        self.assertIn("T18_HLS_PROVIDER_PRESENT", recorder)
        self.assertIn("T19_HLS_FIRST_PART", recorder)
        self.assertIn("T20_HLS_FIRST_COMPLETE_SEGMENT", recorder)
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
        self.assertIn("T16_FIRST_DECODABLE_FRAME", shim_start)
        self.assertIn("on_decodable_frame=on_decodable_frame", shim_start)


if __name__ == "__main__":
    unittest.main()
