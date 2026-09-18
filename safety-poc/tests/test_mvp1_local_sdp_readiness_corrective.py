from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]


def _install_ha_stubs() -> None:
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    sys.modules["homeassistant.config_entries"] = config_entries


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

    cloud = types.ModuleType("custom_components.comelit.cloud")

    class ComelitCloudError(RuntimeError):
        pass

    async def async_negotiate_p2p(*args, **kwargs):
        del args, kwargs
        return "v=0\r\n"

    cloud.ComelitCloudError = ComelitCloudError
    cloud.async_negotiate_p2p = async_negotiate_p2p
    sys.modules["custom_components.comelit.cloud"] = cloud

    h264_recovery = types.ModuleType("custom_components.comelit.h264_recovery")

    class H264RecoveryRtpShim:
        running = False

        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def async_start(self) -> None:
            self.running = True

        async def async_stop(self) -> None:
            self.running = False

        def diagnostics(self):
            return types.SimpleNamespace(
                running=self.running,
                input_packets=0,
                output_packets=0,
                eligible_nonidr_i_count=0,
                injected_count=0,
                existing_recovery_count=0,
                idr_count=0,
                unsupported_packet_count=0,
                malformed_count=0,
                last_error=None,
            )

    h264_recovery.H264RecoveryRtpShim = H264RecoveryRtpShim
    sys.modules["custom_components.comelit.h264_recovery"] = h264_recovery

    oauth = types.ModuleType("custom_components.comelit.oauth")

    class ComelitOAuthError(RuntimeError):
        pass

    class ComelitOAuthManager:
        async def async_get_access_token(self) -> str:
            return "oauth-token"

    oauth.ComelitOAuthError = ComelitOAuthError
    oauth.ComelitOAuthManager = ComelitOAuthManager
    sys.modules["custom_components.comelit.oauth"] = oauth

    sdp = types.ModuleType("custom_components.comelit.sdp")

    class ComelitSdpError(RuntimeError):
        pass

    def transform_offer(raw: bytes) -> bytes:
        return raw

    sdp.ComelitSdpError = ComelitSdpError
    sdp.transform_offer = transform_offer
    sys.modules["custom_components.comelit.sdp"] = sdp

    _load_module(
        "custom_components.comelit.media_diagnostics",
        ROOT / "custom_components" / "comelit" / "media_diagnostics.py",
    )
    const = _load_module(
        "custom_components.comelit.const",
        ROOT / "custom_components" / "comelit" / "const.py",
    )
    media_session = _load_module(
        "custom_components.comelit.media_session",
        ROOT / "custom_components" / "comelit" / "media_session.py",
    )
    media_transport = _load_module(
        "custom_components.comelit.media_transport",
        ROOT / "custom_components" / "comelit" / "media_transport.py",
    )
    ring_media = _load_module(
        "custom_components.comelit.ring_media",
        ROOT / "custom_components" / "comelit" / "ring_media.py",
    )
    return const, media_session, media_transport, ring_media


const, media_session, media_transport, ring_media = _load_comelit_modules()


class FakeEntry:
    def async_create_background_task(self, hass, coro, name):
        del hass
        return asyncio.create_task(coro, name=name)


class FakeOAuth:
    async def async_get_access_token(self) -> str:
        return "oauth-token"


class FakeConfig:
    def is_allowed_path(self, path: str) -> bool:
        del path
        return True


class FakeHass:
    def __init__(self, scenario: "NativeScenario | None" = None) -> None:
        self.scenario = scenario
        self.config = FakeConfig()
        self.data = {"stream": {"settings": object(), "streams": []}}

    async def async_add_executor_job(self, func, *args):
        name = getattr(func, "__name__", "")
        if name == "_write_local_sdp" and self.scenario is not None:
            self.scenario.sdp_write_entered.set()
            await self.scenario.release_sdp_write.wait()
        result = func(*args)
        if name == "_touch_stop" and self.scenario is not None:
            self.scenario.finish_current_process(0)
        return result


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = asyncio.StreamReader()
        self.returncode: int | None = None
        self._wait_event = asyncio.Event()

    async def wait(self) -> int:
        await self._wait_event.wait()
        assert self.returncode is not None
        return self.returncode

    def feed_line(self, line: str) -> None:
        self.stdout.feed_data(f"{line}\n".encode("utf-8"))

    def finish(self, returncode: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = returncode
        self.stdout.feed_eof()
        self._wait_event.set()

    def terminate(self) -> None:
        self.finish(-15)

    def kill(self) -> None:
        self.finish(-9)


class NativeScenario:
    def __init__(self, module=media_transport) -> None:
        self.module = module
        self.spawn_count = 0
        self.release_active = asyncio.Event()
        self.active_sent = asyncio.Event()
        self.sdp_write_entered = asyncio.Event()
        self.release_sdp_write = asyncio.Event()
        self.finish_after_active = False
        self.current_process: FakeProcess | None = None

    async def create_subprocess_exec(self, *args, **kwargs) -> FakeProcess:
        del args, kwargs
        self.spawn_count += 1
        process = FakeProcess()
        self.current_process = process
        asyncio.create_task(self._drive(process))
        return process

    async def _drive(self, process: FakeProcess) -> None:
        self.module._MEDIA_OFFER_FILE.write_bytes(b"v=0\r\n")
        process.feed_line("ICE_GATHER=PASS")
        await self.release_active.wait()
        process.feed_line("P80_MEDIA_ACTIVE=true")
        self.active_sent.set()
        if self.finish_after_active:
            process.finish(7)

    def finish_current_process(self, returncode: int) -> None:
        if self.current_process is not None:
            self.current_process.finish(returncode)


def _install_transport_files(module, tmp: Path) -> None:
    run_dir = tmp / "run"
    native_dir = tmp / "native"
    lib_dir = native_dir / "lib"
    lib_dir.mkdir(parents=True)
    binary = native_dir / "comelit-media"
    binary.write_bytes(b"dummy-native")
    binary.chmod(0o700)
    module._MEDIA_RUN_DIR = run_dir
    module._MEDIA_OFFER_FILE = run_dir / "offer.sdp"
    module._MEDIA_REMOTE_FILE = run_dir / "remote.sdp"
    module._MEDIA_STOP_FILE = run_dir / "stop"
    module._MEDIA_LOCAL_SDP_FILE = run_dir / "local-rtp.sdp"
    module._HELPER_SECRETS = tmp / "secrets.env"
    module._MEDIA_NATIVE_BINARY = binary
    module._NATIVE_LIB = lib_dir
    module.MEDIA_NATIVE_BINARY_SHA256 = hashlib.sha256(binary.read_bytes()).hexdigest()


def _make_transport(hass: FakeHass):
    return media_transport.ComelitEntranceMediaTransport(
        hass,
        session=object(),
        entry=FakeEntry(),
        device_uuid="device",
        vip_token="0123456789abcdef0123456789abcdef",
        oauth=FakeOAuth(),
    )


class FakeListener:
    def __init__(self) -> None:
        self.media_paused = False
        self.pause_count = 0
        self.resume_count = 0

    async def async_pause_for_media(self) -> None:
        self.pause_count += 1
        self.media_paused = True

    async def async_resume_after_media(self) -> None:
        self.resume_count += 1
        self.media_paused = False


class LocalSdpReadinessCorrectiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        _install_transport_files(media_transport, Path(self.tmpdir.name))
        self.old_subprocess = media_transport.asyncio.create_subprocess_exec
        self.old_startup_window = getattr(
            media_transport,
            "_MEDIA_STARTUP_WINDOW_SECONDS",
            None,
        )

    async def asyncTearDown(self) -> None:
        media_transport.asyncio.create_subprocess_exec = self.old_subprocess
        if self.old_startup_window is None:
            if hasattr(media_transport, "_MEDIA_STARTUP_WINDOW_SECONDS"):
                delattr(media_transport, "_MEDIA_STARTUP_WINDOW_SECONDS")
        else:
            media_transport._MEDIA_STARTUP_WINDOW_SECONDS = self.old_startup_window
        self.tmpdir.cleanup()

    async def test_a_delayed_sdp_readiness_blocks_async_start_until_ready(self) -> None:
        scenario = NativeScenario()
        media_transport.asyncio.create_subprocess_exec = scenario.create_subprocess_exec
        transport = _make_transport(FakeHass(scenario))

        start_task = asyncio.create_task(transport.async_start("entrance"))
        scenario.release_active.set()
        await asyncio.wait_for(scenario.active_sent.wait(), timeout=1)
        await asyncio.wait_for(scenario.sdp_write_entered.wait(), timeout=1)
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)

        self.assertTrue(transport.active)
        self.assertFalse(transport.local_sdp_ready)
        self.assertFalse(start_task.done())

        scenario.release_sdp_write.set()
        await asyncio.wait_for(start_task, timeout=1)

        self.assertTrue(transport.local_sdp_ready)
        self.assertTrue(start_task.done())
        print("TRANSPORT_ACTIVE_BEFORE_SDP=true")
        print("ASYNC_START_RETURNED_BEFORE_SDP=false")
        print("ASYNC_START_RETURNED_AFTER_SDP=true")
        await transport.async_stop()

    async def test_b_sdp_never_ready_fails_closed_without_retry(self) -> None:
        media_transport._MEDIA_STARTUP_WINDOW_SECONDS = 0.3
        scenario = NativeScenario()
        media_transport.asyncio.create_subprocess_exec = scenario.create_subprocess_exec
        transport = _make_transport(FakeHass(scenario))

        loop = asyncio.get_running_loop()
        started = loop.time()
        start_task = asyncio.create_task(transport.async_start("entrance"))
        scenario.release_active.set()
        with self.assertRaises(media_transport.ComelitMediaTransportError) as ctx:
            await start_task
        duration = loop.time() - started

        self.assertEqual(str(ctx.exception), "local_sdp_ready_timeout")
        self.assertEqual(transport.last_error, "local_sdp_ready_timeout")
        self.assertFalse(transport.active)
        self.assertFalse(transport.local_sdp_ready)
        self.assertFalse(media_transport._MEDIA_LOCAL_SDP_FILE.exists())
        self.assertFalse(transport._local_sdp_ready_event.is_set())
        self.assertEqual(scenario.spawn_count, 1)
        self.assertLess(duration, 5.0)
        print("SDP_READY_TIMEOUT_BOUNDED=PASS")
        print("SDP_READY_TIMEOUT_REASON=local_sdp_ready_timeout")
        print("SPAWN_COUNT=1")

    async def test_c_process_exit_between_active_and_sdp_ready_fails_without_hang(self) -> None:
        scenario = NativeScenario()
        scenario.finish_after_active = True
        media_transport.asyncio.create_subprocess_exec = scenario.create_subprocess_exec
        transport = _make_transport(FakeHass(scenario))

        start_task = asyncio.create_task(transport.async_start("entrance"))
        scenario.release_active.set()
        await asyncio.wait_for(scenario.active_sent.wait(), timeout=1)
        await asyncio.wait_for(scenario.sdp_write_entered.wait(), timeout=1)
        scenario.release_sdp_write.set()

        with self.assertRaises(media_transport.ComelitMediaTransportError):
            await asyncio.wait_for(start_task, timeout=1)

        self.assertFalse(transport.active)
        self.assertTrue(hasattr(transport, "_local_sdp_ready_event"))
        self.assertFalse(transport._local_sdp_ready_event.is_set())
        self.assertEqual(scenario.spawn_count, 1)
        print("PROCESS_EXIT_BEFORE_SDP_HANDLED=PASS")
        print("SPAWN_COUNT=1")

    async def test_d_manager_active_implies_sdp_ready_and_timeout_restores_listener(self) -> None:
        scenario = NativeScenario()
        media_transport.asyncio.create_subprocess_exec = scenario.create_subprocess_exec
        transport = _make_transport(FakeHass(scenario))
        listener = FakeListener()
        manager = media_session.ComelitMediaSessionManager(listener, transport)

        acquire_task = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="test")
        )
        scenario.release_active.set()
        await asyncio.wait_for(scenario.active_sent.wait(), timeout=1)
        await asyncio.wait_for(scenario.sdp_write_entered.wait(), timeout=1)
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)
        self.assertEqual(manager.phase, media_session.MEDIA_PHASE_STARTING)

        scenario.release_sdp_write.set()
        status = await asyncio.wait_for(acquire_task, timeout=1)
        self.assertTrue(status["active"])
        self.assertTrue(manager.active)
        self.assertTrue(transport.local_sdp_ready)
        print("MANAGER_ACTIVE=true")
        print("TRANSPORT_LOCAL_SDP_READY=true")
        print("MEDIA_MANAGER_ACTIVE_IMPLIES_SDP_READY=PASS")
        await manager.async_force_stop(reason="test_done")

        media_transport._MEDIA_STARTUP_WINDOW_SECONDS = 0.3
        timeout_scenario = NativeScenario()
        media_transport.asyncio.create_subprocess_exec = timeout_scenario.create_subprocess_exec
        timeout_transport = _make_transport(FakeHass(timeout_scenario))
        timeout_listener = FakeListener()
        timeout_manager = media_session.ComelitMediaSessionManager(
            timeout_listener,
            timeout_transport,
        )
        timeout_scenario.release_active.set()
        with self.assertRaises(media_session.ComelitMediaSessionError):
            await timeout_manager.async_acquire(panel="entrance", reason="timeout")

        self.assertEqual(timeout_manager.phase, media_session.MEDIA_PHASE_INACTIVE)
        self.assertFalse(timeout_listener.media_paused)
        self.assertEqual(timeout_listener.resume_count, 1)
        self.assertEqual(timeout_scenario.spawn_count, 1)

    async def test_e_preserve_single_flight_and_fail_before_sdp_ready(self) -> None:
        class FakeManager:
            active = True

        class NotReadyTransport:
            local_sdp_path = media_transport._MEDIA_LOCAL_SDP_FILE
            local_sdp_ready = False

        class ReadyTransport:
            local_sdp_path = media_transport._MEDIA_LOCAL_SDP_FILE
            local_sdp_ready = True

        class FakeStream:
            constructor_count = 0
            instances: list["FakeStream"] = []

            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs
                FakeStream.constructor_count += 1
                self.stop_calls = 0
                FakeStream.instances.append(self)

            async def async_get_image(self) -> bytes:
                return b"\xff\xd8jpeg\xff\xd9"

            async def async_record(self, video_path: str, duration: int = 30, lookback: int = 5) -> None:
                del duration, lookback
                Path(video_path).write_bytes(b"mp4")

            async def stop(self) -> None:
                self.stop_calls += 1

        async def fake_dynamic_settings(hass, entity_id):
            del hass, entity_id
            return object()

        class BarrierProvider(ring_media.HAStreamMediaProvider):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.create_calls = 0
                self.first_source_entered = asyncio.Event()
                self.release_source = asyncio.Event()
                self.two_create_calls_entered = asyncio.Event()

            async def _async_create_stream(self):
                self.create_calls += 1
                if self.create_calls == 2:
                    self.two_create_calls_entered.set()
                return await super()._async_create_stream()

            async def _async_stream_source(self) -> str | None:
                self.first_source_entered.set()
                await self.release_source.wait()
                return await super()._async_stream_source()

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStream
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            not_ready_provider = ring_media.HAStreamMediaProvider(
                FakeHass(),
                FakeManager(),
                NotReadyTransport(),
            )
            failed_state = await not_ready_provider.async_record_mp4(
                Path(self.tmpdir.name) / "not-ready.mp4",
                target_seconds=20,
                stop_event=asyncio.Event(),
            )
            self.assertEqual(failed_state, const.RECORDING_STATE_FAILED)
            self.assertEqual(not_ready_provider.last_failure_reason, "stream_unavailable")
            self.assertEqual(FakeStream.constructor_count, 0)

            provider = BarrierProvider(FakeHass(), FakeManager(), ReadyTransport())
            recording_path = Path(self.tmpdir.name) / "ready.mp4"
            snapshot_task = asyncio.create_task(provider.async_capture_jpeg())
            await asyncio.wait_for(provider.first_source_entered.wait(), timeout=1)
            recording_task = asyncio.create_task(
                provider.async_record_mp4(
                    recording_path,
                    target_seconds=20,
                    stop_event=asyncio.Event(),
                )
            )
            await asyncio.wait_for(provider.two_create_calls_entered.wait(), timeout=1)
            provider.release_source.set()
            snapshot, state = await asyncio.gather(snapshot_task, recording_task)

            self.assertEqual(snapshot, b"\xff\xd8jpeg\xff\xd9")
            self.assertEqual(state, const.RECORDING_STATE_COMPLETED)
            self.assertEqual(FakeStream.constructor_count, 1)
            self.assertIs(provider._stream, FakeStream.instances[0])
            shared_stream = provider._stream
            await provider.async_close()
            self.assertEqual(shared_stream.stop_calls, 1)
            print("STREAM_CONSTRUCTOR_COUNT=1")
            print("RETURNED_STREAM_OBJECT_IDENTICAL=true")
            print("SNAPSHOT_AND_RECORDING_SHARE_STREAM=true")
            print("ASYNC_CLOSE_SINGLE_STREAM=PASS")
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic


if __name__ == "__main__":
    unittest.main()
