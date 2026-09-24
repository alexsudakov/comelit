from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]


def _install_ha_stubs() -> None:
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_comelit_modules():
    _install_ha_stubs()
    custom_components = sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = sys.modules.setdefault(
        "custom_components.comelit",
        types.ModuleType("custom_components.comelit"),
    )
    package.__path__ = [str(ROOT / "custom_components" / "comelit")]
    const = _load_module(
        "custom_components.comelit.const",
        ROOT / "custom_components" / "comelit" / "const.py",
    )
    media_session = _load_module(
        "custom_components.comelit.media_session",
        ROOT / "custom_components" / "comelit" / "media_session.py",
    )
    ring_media = _load_module(
        "custom_components.comelit.ring_media",
        ROOT / "custom_components" / "comelit" / "ring_media.py",
    )
    return const, media_session, ring_media


const, media_session, ring_media = _load_comelit_modules()


JPEG_1 = b"\xff\xd8frame-1\xff\xd9"
JPEG_2 = b"\xff\xd8frame-2\xff\xd9"
JPEG_3 = b"\xff\xd8frame-3\xff\xd9"


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, dict(payload)))


class FakeConfig:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    def is_allowed_path(self, path: str) -> bool:
        return self.allowed


class FakeHass:
    def __init__(self, *, path_allowed: bool = True) -> None:
        self.bus = FakeBus()
        self.data = {"stream": {"settings": object(), "streams": []}}
        self.config = FakeConfig(allowed=path_allowed)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeManager:
    def __init__(self) -> None:
        self._active = False
        self.acquire_calls = 0
        self.release_calls = 0
        self.force_stop_calls = 0
        self.fail_acquire = False
        self.events: list[str] = []
        self.remote_closed = asyncio.Event()

    @property
    def active(self) -> bool:
        return self._active

    async def async_acquire(self, *, panel: str, reason: str) -> dict[str, object]:
        self.events.append(f"acquire:{panel}:{reason}")
        self.acquire_calls += 1
        if self.fail_acquire:
            raise media_session.ComelitMediaSessionError("start_failed")
        self._active = True
        return {"active": True}

    async def async_release(self, *, reason: str) -> dict[str, object]:
        self.events.append(f"release:{reason}")
        self.release_calls += 1
        self._active = False
        return {"active": False}

    async def async_force_stop(self, *, reason: str) -> dict[str, object]:
        self.events.append(f"force_stop:{reason}")
        self.force_stop_calls += 1
        self._active = False
        self.remote_closed.set()
        return {"active": False}

    async def async_wait_inactive(self, timeout: float) -> bool:
        if not self._active:
            return True
        try:
            await asyncio.wait_for(self.remote_closed.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    def close_remote(self) -> None:
        self._active = False
        self.remote_closed.set()


class FakeSnapshotProvider:
    def __init__(self, frames: list[bytes], *, slow: bool = False) -> None:
        self.frames = frames
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.two_snapshots = asyncio.Event()
        self.slow = slow
        self.closed = False

    async def async_capture_jpeg(self) -> bytes | None:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.slow:
                await asyncio.sleep(0.02)
            index = min(self.calls - 1, len(self.frames) - 1)
            frame = self.frames[index]
            if self.calls >= 2:
                self.two_snapshots.set()
            return frame
        finally:
            self.in_flight -= 1

    async def async_close(self) -> None:
        self.closed = True


class FakeRecordingProvider:
    def __init__(
        self,
        state: str,
        *,
        wait_for: asyncio.Event | None = None,
        delay: float = 0.0,
        clock: "FakeClock | None" = None,
        advance_seconds: float = 0.0,
    ) -> None:
        self.state = state
        self.wait_for = wait_for
        self.delay = delay
        self.clock = clock
        self.advance_seconds = advance_seconds
        self.calls = 0
        self.target_seconds: int | None = None
        self.stop_event_seen = False

    async def async_record_mp4(
        self,
        path: Path,
        *,
        target_seconds: int,
        stop_event: asyncio.Event,
    ) -> str:
        self.calls += 1
        self.target_seconds = target_seconds
        if self.wait_for is not None:
            await self.wait_for.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        self.stop_event_seen = stop_event.is_set()
        if self.state != const.RECORDING_STATE_FAILED:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp4")
        if self.clock is not None:
            self.clock.advance(self.advance_seconds)
        return self.state


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RaisingRecordingProvider:
    async def async_record_mp4(
        self,
        path: Path,
        *,
        target_seconds: int,
        stop_event: asyncio.Event,
    ) -> str:
        raise RuntimeError("recorder failed")


class MVP1IntegrationRingMediaTests(unittest.IsolatedAsyncioTestCase):
    def make_coordinator(
        self,
        tmp: Path,
        *,
        snapshot: FakeSnapshotProvider | None = None,
        recording: FakeRecordingProvider | None = None,
        manager: FakeManager | None = None,
        clock: FakeClock | None = None,
        remote_authoritative: bool = False,
        hard_limit_seconds: int = const.RING_MEDIA_HARD_LIMIT_SECONDS,
    ):
        hass = FakeHass()
        manager = manager or FakeManager()
        snapshot = snapshot or FakeSnapshotProvider([JPEG_1, JPEG_2])
        recording = recording or FakeRecordingProvider(
            const.RECORDING_STATE_COMPLETED,
            wait_for=snapshot.two_snapshots,
        )
        tasks: list[asyncio.Task[None]] = []

        def task_factory(coro, name):
            task = asyncio.create_task(coro, name=name)
            tasks.append(task)
            return task

        coordinator = ring_media.RingMediaCoordinator(
            hass,
            manager,
            snapshot_provider=snapshot,
            recording_provider=recording,
            media_root=tmp,
            remote_close_waiter=(
                manager.async_wait_inactive if remote_authoritative else None
            ),
            hard_limit_seconds=hard_limit_seconds,
            task_factory=task_factory,
            monotonic_clock=clock or ring_media.monotonic,
        )
        return coordinator, hass, manager, snapshot, recording, tasks

    async def test_snapshot_and_recording_use_one_session_and_safe_paths(self) -> None:
        with self.subTest("constant_targets"):
            self.assertEqual(const.SNAPSHOT_REFRESH_TARGET_SECONDS, 1)
            self.assertEqual(const.RECORDING_TARGET_SECONDS, 20)

        with self.subTest("lifecycle"):
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                clock = FakeClock()
                snapshot = FakeSnapshotProvider([JPEG_1, JPEG_2])
                recording = FakeRecordingProvider(
                    const.RECORDING_STATE_COMPLETED,
                    wait_for=snapshot.two_snapshots,
                    clock=clock,
                    advance_seconds=20.0,
                )
                coordinator, hass, manager, snapshot, recording, tasks = self.make_coordinator(
                    root,
                    snapshot=snapshot,
                    recording=recording,
                    clock=clock,
                )
                event_id = "event-123"

                started = await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: event_id,
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                self.assertTrue(started)
                await tasks[0]

                self.assertEqual(manager.acquire_calls, 1)
                self.assertEqual(manager.release_calls, 1)
                self.assertEqual(recording.calls, 1)
                self.assertEqual(recording.target_seconds, 20)
                self.assertEqual(snapshot.max_in_flight, 1)
                self.assertTrue(snapshot.closed)

                snapshot_events = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_SNAPSHOT_UPDATED
                ]
                event_types = [event_type for event_type, _ in hass.bus.events]
                self.assertLess(
                    event_types.index(const.EVENT_SNAPSHOT_UPDATED),
                    event_types.index(const.EVENT_RECORDING_COMPLETE),
                )
                self.assertGreaterEqual(len(snapshot_events), 2)
                self.assertEqual(
                    [payload[const.ATTR_SEQUENCE] for payload in snapshot_events],
                    [1, 2],
                )
                self.assertEqual(
                    snapshot_events[0][const.ATTR_SNAPSHOT_PATH],
                    str(root / "comelit" / "rings" / event_id / "latest.jpg"),
                )
                self.assertEqual(
                    (root / "comelit" / "rings" / event_id / "latest.jpg").read_bytes(),
                    JPEG_2,
                )
                self.assertFalse(
                    (root / "comelit" / "rings" / event_id / ".latest.jpg.tmp").exists()
                )
                self.assertEqual(
                    snapshot_events[0][const.ATTR_CAMERA_ENTITY],
                    const.ENTRANCE_CAMERA_ENTITY_ID,
                )
                for payload in snapshot_events:
                    self.assertNotIn("token", repr(payload).lower())
                    self.assertNotIn("chat", repr(payload).lower())

                recording_events = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_RECORDING_COMPLETE
                ]
                self.assertEqual(len(recording_events), 1)
                recording_event = recording_events[0]
                self.assertEqual(recording_event[const.ATTR_EVENT_ID], event_id)
                self.assertEqual(recording_event[const.ATTR_STATE], const.RECORDING_STATE_COMPLETED)
                self.assertEqual(recording_event[const.ATTR_DURATION_TARGET_SECONDS], 20)
                self.assertEqual(recording_event[const.ATTR_DURATION_ACTUAL_SECONDS], 20.0)
                self.assertEqual(
                    recording_event[const.ATTR_RECORDING_PATH],
                    str(root / "comelit" / "rings" / event_id / "recording.mp4"),
                )

    async def test_real_ring_recording_completion_does_not_end_attached_call(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            manager = FakeManager()
            snapshot = FakeSnapshotProvider([JPEG_1])
            recording = FakeRecordingProvider(const.RECORDING_STATE_COMPLETED)
            coordinator, hass, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                snapshot=snapshot,
                recording=recording,
                manager=manager,
                remote_authoritative=True,
            )
            await coordinator.async_start_for_ring(
                {
                    const.ATTR_EVENT_ID: "event-remote-owned",
                    const.ATTR_DOOR: const.DOOR_ENTRANCE,
                }
            )

            for _ in range(100):
                if any(
                    event_type == const.EVENT_RECORDING_COMPLETE
                    for event_type, _ in hass.bus.events
                ):
                    break
                await asyncio.sleep(0)
            else:
                self.fail("recording completion event was not emitted")

            self.assertFalse(tasks[0].done())
            self.assertTrue(manager.active)
            self.assertEqual(manager.release_calls, 0)
            self.assertTrue(coordinator.status()["remote_call_lifetime_authoritative"])
            self.assertEqual(
                coordinator.status()["ring_media_hard_limit_seconds"],
                const.RING_MEDIA_HARD_LIMIT_SECONDS,
            )

            manager.close_remote()
            await tasks[0]

            self.assertEqual(manager.release_calls, 1)
            self.assertEqual(coordinator.status()["ring_end_reason"], "remote_closed")
            recording_events = [
                payload
                for event_type, payload in hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ]
            self.assertEqual(len(recording_events), 1)

    async def test_real_ring_remote_wait_is_bounded_by_hard_limit(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            manager = FakeManager()
            recording = FakeRecordingProvider(const.RECORDING_STATE_COMPLETED)
            coordinator, _, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                recording=recording,
                manager=manager,
                remote_authoritative=True,
                hard_limit_seconds=0.05,
            )
            await coordinator.async_start_for_ring(
                {
                    const.ATTR_EVENT_ID: "event-hard-limit",
                    const.ATTR_DOOR: const.DOOR_ENTRANCE,
                }
            )
            await asyncio.wait_for(tasks[0], timeout=1.0)

            self.assertEqual(manager.force_stop_calls, 1)
            self.assertEqual(manager.release_calls, 1)
            self.assertEqual(coordinator.status()["ring_end_reason"], "hard_limit")

    async def test_recording_truncated_and_failed_are_terminal_without_crash(self) -> None:
        import tempfile

        for state in (const.RECORDING_STATE_TRUNCATED, const.RECORDING_STATE_FAILED):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                snapshot = FakeSnapshotProvider([JPEG_1])
                recording = FakeRecordingProvider(state, delay=0.01)
                coordinator, hass, manager, _, _, tasks = self.make_coordinator(
                    Path(td),
                    snapshot=snapshot,
                    recording=recording,
                )
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: f"event-{state}",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                await tasks[0]
                event = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_RECORDING_COMPLETE
                ][0]
                self.assertEqual(event[const.ATTR_STATE], state)
                self.assertGreaterEqual(event[const.ATTR_DURATION_ACTUAL_SECONDS], 0)
                self.assertEqual(manager.release_calls, 1)

    async def test_short_successful_recorder_return_is_truncated(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            clock = FakeClock()
            snapshot = FakeSnapshotProvider([JPEG_1])
            recording = FakeRecordingProvider(
                const.RECORDING_STATE_COMPLETED,
                clock=clock,
                advance_seconds=4.25,
            )
            coordinator, hass, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                snapshot=snapshot,
                recording=recording,
                clock=clock,
            )
            await coordinator.async_start_for_ring(
                {
                    const.ATTR_EVENT_ID: "event-short-completed",
                    const.ATTR_DOOR: const.DOOR_ENTRANCE,
                }
            )
            await tasks[0]
            event = [
                payload
                for event_type, payload in hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ][0]
            self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_TRUNCATED)
            self.assertEqual(event[const.ATTR_DURATION_ACTUAL_SECONDS], 4.25)
            self.assertEqual(manager.release_calls, 1)

    async def test_media_start_failure_emits_failed_and_restores_ownership(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            manager = FakeManager()
            manager.fail_acquire = True
            coordinator, hass, manager, _, _, tasks = self.make_coordinator(Path(td), manager=manager)
            await coordinator.async_start_for_ring(
                {
                    const.ATTR_EVENT_ID: "event-start-failed",
                    const.ATTR_DOOR: const.DOOR_ENTRANCE,
                }
            )
            await tasks[0]
            event = [
                payload
                for event_type, payload in hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ][0]
            self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_FAILED)
            self.assertEqual(manager.release_calls, 0)

    async def test_raising_recorder_emits_failed_and_still_releases(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            snapshot = FakeSnapshotProvider([JPEG_1])
            coordinator, hass, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                snapshot=snapshot,
                recording=RaisingRecordingProvider(),
            )
            old_disabled = ring_media._LOGGER.disabled
            ring_media._LOGGER.disabled = True
            try:
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: "event-raising-recorder",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                await tasks[0]
            finally:
                ring_media._LOGGER.disabled = old_disabled
            event = [
                payload
                for event_type, payload in hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ][0]
            self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_FAILED)
            self.assertEqual(manager.release_calls, 1)

    async def test_ha_stream_provider_missing_record_method_fails_closed(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamWithoutRecord:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def async_get_image(self) -> bytes:
                return JPEG_1

            async def stop(self) -> None:
                pass

        async def fake_dynamic_settings(hass, entity_id):
            return object()

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamWithoutRecord
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        old_disabled = ring_media._LOGGER.disabled
        ring_media._LOGGER.disabled = True
        try:
            hass = FakeHass()
            manager = FakeManager()
            manager._active = True
            provider = ring_media.HAStreamMediaProvider(hass, manager, FakeTransport())
            state = await provider.async_record_mp4(
                Path("/tmp/mvp1i-missing-record.mp4"),
                target_seconds=20,
                stop_event=asyncio.Event(),
            )
            self.assertEqual(state, const.RECORDING_STATE_FAILED)
        finally:
            ring_media._LOGGER.disabled = old_disabled
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_ha_stream_provider_disallowed_path_fails_before_recording(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamWithRecord:
            calls = 0

            def __init__(self, *args, **kwargs) -> None:
                pass

            async def async_record(self, *args, **kwargs) -> None:
                FakeStreamWithRecord.calls += 1

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamWithRecord
        ring_media.get_dynamic_camera_stream_settings = lambda hass, entity_id: object()
        try:
            hass = FakeHass(path_allowed=False)
            manager = FakeManager()
            manager._active = True
            provider = ring_media.HAStreamMediaProvider(hass, manager, FakeTransport())
            state = await provider.async_record_mp4(
                Path("/tmp/not-allowed/recording.mp4"),
                target_seconds=20,
                stop_event=asyncio.Event(),
            )
            self.assertEqual(state, const.RECORDING_STATE_FAILED)
            self.assertEqual(provider.last_failure_reason, "recording_path_not_allowlisted")
            self.assertEqual(FakeStreamWithRecord.calls, 0)
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_ha_stream_provider_calls_proven_record_signature(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamWithRecord:
            calls: list[tuple[str, int, int]] = []
            init_count = 0

            def __init__(self, *args, **kwargs) -> None:
                FakeStreamWithRecord.init_count += 1

            async def async_get_image(self) -> bytes:
                return JPEG_1

            async def async_record(
                self,
                video_path: str,
                duration: int = 30,
                lookback: int = 5,
            ) -> None:
                FakeStreamWithRecord.calls.append((video_path, duration, lookback))
                Path(video_path).parent.mkdir(parents=True, exist_ok=True)
                Path(video_path).write_bytes(b"mp4")

            async def stop(self) -> None:
                pass

        async def fake_dynamic_settings(hass, entity_id):
            return object()

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamWithRecord
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                hass = FakeHass()
                manager = FakeManager()
                manager._active = True
                provider = ring_media.HAStreamMediaProvider(hass, manager, FakeTransport())
                target = Path(td) / "recording.mp4"
                self.assertEqual(await provider.async_capture_jpeg(), JPEG_1)
                state = await provider.async_record_mp4(
                    target,
                    target_seconds=20,
                    stop_event=asyncio.Event(),
                )
                self.assertEqual(state, const.RECORDING_STATE_COMPLETED)
                self.assertEqual(FakeStreamWithRecord.calls, [(str(target), 20, 0)])
                self.assertEqual(FakeStreamWithRecord.init_count, 1)
                self.assertEqual(len(hass.data["stream"]["streams"]), 1)
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_recorder_exception_with_final_file_is_truncated(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamRaisesWithFinal:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def async_get_image(self) -> bytes:
                return JPEG_1

            async def async_record(self, video_path: str, **kwargs) -> None:
                Path(video_path).parent.mkdir(parents=True, exist_ok=True)
                Path(video_path).write_bytes(b"partial mp4")
                clock.advance(6.5)
                raise RuntimeError("stream ended")

            async def stop(self) -> None:
                pass

        async def fake_dynamic_settings(hass, entity_id):
            return object()

        import tempfile

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamRaisesWithFinal
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            with tempfile.TemporaryDirectory() as td:
                clock = FakeClock()
                hass = FakeHass()
                manager = FakeManager()
                provider = ring_media.HAStreamMediaProvider(
                    hass,
                    manager,
                    FakeTransport(),
                )
                tasks: list[asyncio.Task[None]] = []

                def task_factory(coro, name):
                    task = asyncio.create_task(coro, name=name)
                    tasks.append(task)
                    return task

                coordinator = ring_media.RingMediaCoordinator(
                    hass,
                    manager,
                    snapshot_provider=provider,
                    recording_provider=provider,
                    media_root=Path(td),
                    task_factory=task_factory,
                    monotonic_clock=clock,
                )
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: "event-partial-raise",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                await tasks[0]
                event = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_RECORDING_COMPLETE
                ][0]
                self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_TRUNCATED)
                self.assertEqual(event[const.ATTR_DURATION_ACTUAL_SECONDS], 6.5)
                self.assertEqual(manager.release_calls, 1)
                recording_path = Path(event[const.ATTR_RECORDING_PATH])
                self.assertEqual(recording_path.read_bytes(), b"partial mp4")
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_recorder_exception_without_final_file_is_failed_reason_safe(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamRaisesWithoutFinal:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def async_get_image(self) -> bytes:
                return JPEG_1

            async def async_record(self, video_path: str, **kwargs) -> None:
                clock.advance(3.0)
                raise RuntimeError("stream ended")

            async def stop(self) -> None:
                pass

        async def fake_dynamic_settings(hass, entity_id):
            return object()

        import tempfile

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamRaisesWithoutFinal
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            with tempfile.TemporaryDirectory() as td:
                clock = FakeClock()
                hass = FakeHass()
                manager = FakeManager()
                provider = ring_media.HAStreamMediaProvider(
                    hass,
                    manager,
                    FakeTransport(),
                )
                tasks: list[asyncio.Task[None]] = []

                def task_factory(coro, name):
                    task = asyncio.create_task(coro, name=name)
                    tasks.append(task)
                    return task

                coordinator = ring_media.RingMediaCoordinator(
                    hass,
                    manager,
                    snapshot_provider=provider,
                    recording_provider=provider,
                    media_root=Path(td),
                    task_factory=task_factory,
                    monotonic_clock=clock,
                )
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: "event-no-file-raise",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                await tasks[0]
                event = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_RECORDING_COMPLETE
                ][0]
                self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_FAILED)
                self.assertEqual(event["reason"], "recorder_exception")
                self.assertEqual(event[const.ATTR_DURATION_ACTUAL_SECONDS], 3.0)
                self.assertEqual(manager.release_calls, 1)
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_recorder_tmp_only_is_not_a_usable_retained_file(self) -> None:
        class FakeTransport:
            local_sdp_path = Path("/tmp/local.sdp")
            local_sdp_ready = True

        class FakeStreamRaisesWithTmpOnly:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def async_get_image(self) -> bytes:
                return JPEG_1

            async def async_record(self, video_path: str, **kwargs) -> None:
                Path(video_path).parent.mkdir(parents=True, exist_ok=True)
                Path(f"{video_path}.tmp").write_bytes(b"partial tmp")
                raise RuntimeError("stream ended")

            async def stop(self) -> None:
                pass

        async def fake_dynamic_settings(hass, entity_id):
            return object()

        import tempfile

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStreamRaisesWithTmpOnly
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            with tempfile.TemporaryDirectory() as td:
                hass = FakeHass()
                manager = FakeManager()
                provider = ring_media.HAStreamMediaProvider(
                    hass,
                    manager,
                    FakeTransport(),
                )
                tasks: list[asyncio.Task[None]] = []

                def task_factory(coro, name):
                    task = asyncio.create_task(coro, name=name)
                    tasks.append(task)
                    return task

                coordinator = ring_media.RingMediaCoordinator(
                    hass,
                    manager,
                    snapshot_provider=provider,
                    recording_provider=provider,
                    media_root=Path(td),
                    task_factory=task_factory,
                )
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: "event-tmp-only",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
                await tasks[0]
                event = [
                    payload
                    for event_type, payload in hass.bus.events
                    if event_type == const.EVENT_RECORDING_COMPLETE
                ][0]
                recording_path = Path(event[const.ATTR_RECORDING_PATH])
                self.assertEqual(event[const.ATTR_STATE], const.RECORDING_STATE_FAILED)
                self.assertFalse(recording_path.exists())
                self.assertTrue(Path(f"{recording_path}.tmp").exists())
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic

    async def test_duplicate_ring_does_not_start_second_lifecycle(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            snapshot = FakeSnapshotProvider([JPEG_1, JPEG_2])
            recording = FakeRecordingProvider(
                const.RECORDING_STATE_COMPLETED,
                wait_for=snapshot.two_snapshots,
            )
            coordinator, _, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                snapshot=snapshot,
                recording=recording,
            )
            event = {
                const.ATTR_EVENT_ID: "event-dup",
                const.ATTR_DOOR: const.DOOR_ENTRANCE,
            }
            self.assertTrue(await coordinator.async_start_for_ring(event))
            self.assertFalse(await coordinator.async_start_for_ring(event))
            await tasks[0]
            self.assertEqual(manager.acquire_calls, 1)
            self.assertEqual(recording.calls, 1)

    async def test_unload_cancels_and_releases_active_lifecycle(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            snapshot = FakeSnapshotProvider([JPEG_1], slow=True)
            never = asyncio.Event()
            recording = FakeRecordingProvider(
                const.RECORDING_STATE_COMPLETED,
                wait_for=never,
            )
            coordinator, hass, manager, _, _, tasks = self.make_coordinator(
                Path(td),
                snapshot=snapshot,
                recording=recording,
            )
            await coordinator.async_start_for_ring(
                {
                    const.ATTR_EVENT_ID: "event-unload",
                    const.ATTR_DOOR: const.DOOR_ENTRANCE,
                }
            )
            while manager.acquire_calls == 0:
                await asyncio.sleep(0)

            await coordinator.async_shutdown()

            self.assertFalse(coordinator.running)
            self.assertEqual(manager.release_calls, 1)
            self.assertTrue(tasks[0].cancelled())
            terminal = [
                payload
                for event_type, payload in hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ][0]
            self.assertEqual(terminal[const.ATTR_STATE], const.RECORDING_STATE_TRUNCATED)

    def test_safe_path_rejects_unsafe_event_id(self) -> None:
        with self.assertRaises(ValueError):
            ring_media.safe_ring_media_paths(Path("/media"), "../token")

    async def test_ring_coordinator_uses_named_stream_consumer_when_supported(self) -> None:
        class FakeSharedMediaProvider:
            def __init__(self) -> None:
                self.acquire_reasons: list[str] = []
                self.release_reasons: list[str] = []
                self.close_calls = 0
                self.last_failure_reason = None

            async def async_acquire_consumer(self, reason: str) -> None:
                self.acquire_reasons.append(reason)

            async def async_release_consumer(self, reason: str) -> None:
                self.release_reasons.append(reason)

            async def async_capture_jpeg(self) -> bytes | None:
                return JPEG_1

            async def async_record_mp4(
                self,
                path: Path,
                *,
                target_seconds: int,
                stop_event: asyncio.Event,
            ) -> str:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp4")
                return const.RECORDING_STATE_COMPLETED

            async def async_close(self) -> None:
                self.close_calls += 1

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            hass = FakeHass()
            manager = FakeManager()
            provider = FakeSharedMediaProvider()
            tasks: list[asyncio.Task[None]] = []

            def task_factory(coro, name):
                task = asyncio.create_task(coro, name=name)
                tasks.append(task)
                return task

            coordinator = ring_media.RingMediaCoordinator(
                hass,
                manager,
                snapshot_provider=provider,
                recording_provider=provider,
                media_root=Path(td),
                task_factory=task_factory,
            )
            self.assertTrue(
                await coordinator.async_start_for_ring(
                    {
                        const.ATTR_EVENT_ID: "event-shared-provider",
                        const.ATTR_DOOR: const.DOOR_ENTRANCE,
                    }
                )
            )
            await tasks[0]

            self.assertEqual(provider.acquire_reasons, ["ring_media"])
            self.assertEqual(provider.release_reasons, ["ring_media"])
            self.assertEqual(provider.close_calls, 0)

    async def test_shared_ha_stream_provider_closes_only_after_last_consumer(self) -> None:
        class FakeSharedStream:
            def __init__(self) -> None:
                self.stop_calls = 0

            async def stop(self) -> None:
                self.stop_calls += 1

        hass = FakeHass()
        manager = FakeManager()
        provider = ring_media.HAStreamMediaProvider(
            hass,
            manager,
            transport=object(),
        )
        stream = FakeSharedStream()
        provider._stream = stream

        await provider.async_acquire_consumer("ring_media")
        await provider.async_acquire_consumer("camera_view")
        self.assertEqual(
            provider.consumers,
            {"ring_media": 1, "camera_view": 1},
        )

        await provider.async_release_consumer("ring_media")
        self.assertIs(provider.stream, stream)
        self.assertEqual(stream.stop_calls, 0)
        self.assertEqual(provider.consumers, {"camera_view": 1})

        # A legacy/direct cleanup request must not stop a stream still owned by
        # the live camera consumer.
        await provider.async_close()
        self.assertIs(provider.stream, stream)
        self.assertEqual(stream.stop_calls, 0)

        await provider.async_release_consumer("camera_view")
        self.assertIsNone(provider.stream)
        self.assertEqual(stream.stop_calls, 1)
        self.assertEqual(provider.consumers, {})

    def test_existing_contract_constants_are_unchanged(self) -> None:
        self.assertEqual(const.EVENT_RING, "comelit_ring")
        self.assertEqual(const.EVENT_DOOR_OPERATION, "comelit_door_operation")
        self.assertEqual(const.ENTRANCE_CAMERA_ENTITY_ID, "camera.comelit_entrance")
        self.assertEqual(const.ENTRANCE_MEDIA_SWITCH_ENTITY_ID, "switch.comelit_entrance_camera")
        self.assertIn(const.DOOR_ENTRANCE, const.SUPPORTED_DOORS)
        self.assertIn(const.DOOR_GATE, const.SUPPORTED_DOORS)
        gate = const.resolve_door_capability(const.DOOR_GATE, media_paused=False)
        self.assertTrue(gate.actuation_profile_validated)
        self.assertTrue(gate.press_allowed)
        self.assertFalse(gate.blocked_reason)


if __name__ == "__main__":
    unittest.main()
