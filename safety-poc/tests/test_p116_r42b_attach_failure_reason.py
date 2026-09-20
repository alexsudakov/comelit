from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ATTACHED = REPO / "custom_components" / "comelit" / "attached_media.py"


def _load_attached_module() -> types.ModuleType:
    package_name = "_p116_attached_failure_test"
    package = types.ModuleType(package_name)
    package.__path__ = []
    sys.modules[package_name] = package

    h264 = types.ModuleType(f"{package_name}.h264_recovery")

    class H264RecoveryRtpShim:
        def __init__(self, *, input_port: int, output_port: int) -> None:
            self.input_port = input_port
            self.output_port = output_port
            self.running = False

        async def async_start(self) -> None:
            self.running = True

        async def async_stop(self) -> None:
            self.running = False

    h264.H264RecoveryRtpShim = H264RecoveryRtpShim
    sys.modules[h264.__name__] = h264

    media_transport = types.ModuleType(f"{package_name}.media_transport")
    media_transport.MEDIA_AUDIO_RTP_PORT = 17808
    media_transport.MEDIA_VIDEO_HA_RTP_PORT = 17999
    media_transport.MEDIA_VIDEO_RTP_PORT = 17899
    sys.modules[media_transport.__name__] = media_transport

    name = f"{package_name}.attached_media"
    spec = importlib.util.spec_from_file_location(name, ATTACHED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _BoundedFailureTransport:
    active = False

    def __init__(self, module: types.ModuleType) -> None:
        self._module = module

    async def async_start(self, panel: str) -> None:
        del panel
        raise self._module.ComelitAttachedMediaError(
            "attached_media_open_not_confirmed"
        )

    async def async_stop(self) -> None:
        return None


class _UnexpectedFailureTransport:
    active = False

    async def async_start(self, panel: str) -> None:
        del panel
        raise ValueError("raw unexpected detail must not escape")

    async def async_stop(self) -> None:
        return None


class AttachedMediaFailureReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_attached_module()

    def test_bounded_transport_reason_survives_session_wrapper(self) -> None:
        module = self.module
        session = module.ComelitAttachedRingMediaSession(
            _BoundedFailureTransport(module)
        )

        async def run() -> None:
            with self.assertRaises(module.ComelitAttachedMediaError) as ctx:
                await session.async_acquire(panel="entrance", reason="ring_recording")
            self.assertEqual(
                str(ctx.exception), "attached_media_open_not_confirmed"
            )
            self.assertEqual(
                session.status()["last_error"],
                "attached_media_open_not_confirmed",
            )

        asyncio.run(run())

    def test_unexpected_exception_stays_type_only(self) -> None:
        module = self.module
        session = module.ComelitAttachedRingMediaSession(
            _UnexpectedFailureTransport()
        )

        async def run() -> None:
            with self.assertRaises(module.ComelitAttachedMediaError) as ctx:
                await session.async_acquire(panel="entrance", reason="ring_recording")
            self.assertEqual(str(ctx.exception), "start_failed:ValueError")
            self.assertEqual(session.status()["last_error"], "start_failed:ValueError")
            self.assertNotIn("raw unexpected detail", str(ctx.exception))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
