from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
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
    _load_module(
        "custom_components.comelit.media_session",
        ROOT / "custom_components" / "comelit" / "media_session.py",
    )
    ring_media = _load_module(
        "custom_components.comelit.ring_media",
        ROOT / "custom_components" / "comelit" / "ring_media.py",
    )
    return const, ring_media


const, ring_media = _load_comelit_modules()


class FakeConfig:
    def is_allowed_path(self, path: str) -> bool:
        return True


class FakeHass:
    def __init__(self) -> None:
        self.config = FakeConfig()
        self.data = {"stream": {"settings": object(), "streams": []}}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeManager:
    active = True


class FakeTransport:
    local_sdp_path = Path("/tmp/comelit-singleflight.sdp")
    local_sdp_ready = True


class Mvp1StreamSingleFlightCorrectiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_and_recording_share_one_stream_under_concurrent_create(self) -> None:
        jpeg = b"\xff\xd8singleflight\xff\xd9"

        class FakeStream:
            constructor_count = 0
            instances: list["FakeStream"] = []

            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs
                FakeStream.constructor_count += 1
                self.image_calls = 0
                self.record_calls = 0
                self.stop_calls = 0
                FakeStream.instances.append(self)

            async def async_get_image(self) -> bytes:
                self.image_calls += 1
                return jpeg

            async def async_record(
                self,
                video_path: str,
                duration: int = 30,
                lookback: int = 5,
            ) -> None:
                del duration, lookback
                self.record_calls += 1
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
                self.source_calls = 0
                self.first_source_entered = asyncio.Event()
                self.release_source = asyncio.Event()
                self.two_create_calls_entered = asyncio.Event()

            async def _async_create_stream(self):
                self.create_calls += 1
                if self.create_calls == 2:
                    self.two_create_calls_entered.set()
                return await super()._async_create_stream()

            async def _async_stream_source(self) -> str | None:
                self.source_calls += 1
                self.first_source_entered.set()
                await self.release_source.wait()
                return await super()._async_stream_source()

        old_stream = ring_media.Stream
        old_dynamic = ring_media.get_dynamic_camera_stream_settings
        ring_media.Stream = FakeStream
        ring_media.get_dynamic_camera_stream_settings = fake_dynamic_settings
        try:
            with tempfile.TemporaryDirectory() as td:
                provider = BarrierProvider(FakeHass(), FakeManager(), FakeTransport())
                recording_path = Path(td) / "ring.mp4"

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

                self.assertEqual(provider.create_calls, 2)
                self.assertEqual(provider.source_calls, 1)
                self.assertEqual(FakeStream.constructor_count, 1)
                self.assertIs(provider._stream, FakeStream.instances[0])
                self.assertEqual(snapshot, jpeg)
                self.assertEqual(state, const.RECORDING_STATE_COMPLETED)
                self.assertEqual(FakeStream.instances[0].image_calls, 1)
                self.assertEqual(FakeStream.instances[0].record_calls, 1)
                self.assertEqual(len(provider._hass.data["stream"]["streams"]), 1)

                shared_stream = provider._stream
                await provider.async_close()

                self.assertIsNone(provider._stream)
                self.assertEqual(shared_stream.stop_calls, 1)
        finally:
            ring_media.Stream = old_stream
            ring_media.get_dynamic_camera_stream_settings = old_dynamic


if __name__ == "__main__":
    unittest.main()
