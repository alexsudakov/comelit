#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
import socket
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
TRANSPORT = COMPONENT / "media_transport.py"
SESSION = COMPONENT / "media_session.py"
BINARY = COMPONENT / "native" / "comelit-media"
RECOVERY = COMPONENT / "h264_recovery.py"
EXPECTED_NATIVE_SHA256 = "35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622"
EXPECTED_MEDIA_SESSION_SHA256 = "65fe703f5a33207502fc6a2984d5edd0712813b174d41b48c6e3e5b10423d7bc"

spec = importlib.util.spec_from_file_location("h264_recovery_lifecycle", RECOVERY)
h264_recovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h264_recovery
assert spec.loader is not None
spec.loader.exec_module(h264_recovery)


def free_udp_port() -> int:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
    except PermissionError as exc:
        raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
    try:
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def rtp(seq: int, payload: bytes) -> bytes:
    return struct.pack("!BBHII", 0x80, 99, seq, 1000, 0x01020304) + payload


class Receiver(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: object) -> None:
        self.queue.put_nowait(data)


class P116R24RecoveryShimStaticLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport = TRANSPORT.read_text(encoding="utf-8")

    def test_shim_binds_before_native_helper_launch(self) -> None:
        cycle = self.transport.split("async def _async_run_cycle", 1)[1].split(
            "async def _async_read_output", 1
        )[0]
        self.assertLess(
            cycle.index("await self._async_start_video_recovery_shim()"),
            cycle.index("process = await asyncio.create_subprocess_exec("),
        )

    def test_local_sdp_video_points_to_ha_facing_port(self) -> None:
        self.assertIn("MEDIA_VIDEO_RTP_PORT = 17899", self.transport)
        self.assertIn("MEDIA_VIDEO_HA_RTP_PORT = 17999", self.transport)
        self.assertIn("m=video {MEDIA_VIDEO_HA_RTP_PORT} RTP/AVP 99", self.transport)
        self.assertNotIn("m=video {MEDIA_VIDEO_RTP_PORT} RTP/AVP 99", self.transport)

    def test_local_sdp_audio_remains_direct_pcma(self) -> None:
        self.assertIn("MEDIA_AUDIO_RTP_PORT = 17808", self.transport)
        self.assertIn("m=audio {MEDIA_AUDIO_RTP_PORT} RTP/AVP 8", self.transport)
        self.assertIn("a=rtpmap:8 PCMA/8000/1", self.transport)

    def test_shim_closes_on_normal_stop_failure_and_cancellation_paths(self) -> None:
        self.assertIn("await self._async_stop_video_recovery_shim()", self.transport)
        self.assertGreaterEqual(
            self.transport.count("await self._async_stop_video_recovery_shim()"), 2
        )
        self.assertIn("finally:\n            self._media_active.clear()", self.transport)

    def test_local_sdp_ready_requires_running_shim(self) -> None:
        ready = self.transport.split("def local_sdp_ready", 1)[1].split(
            "@property", 1
        )[0]
        self.assertIn("shim.running", ready)
        self.assertIn("_MEDIA_LOCAL_SDP_FILE.is_file()", ready)

    def test_native_binary_and_pinned_sha_are_untouched(self) -> None:
        self.assertIn(EXPECTED_NATIVE_SHA256, self.transport)
        self.assertEqual(hashlib.sha256(BINARY.read_bytes()).hexdigest(), EXPECTED_NATIVE_SHA256)
        self.assertEqual(hashlib.sha256(SESSION.read_bytes()).hexdigest(), EXPECTED_MEDIA_SESSION_SHA256)

    def test_no_second_upstream_session_is_introduced(self) -> None:
        self.assertEqual(self.transport.count("async_negotiate_p2p("), 1)
        self.assertEqual(self.transport.count("create_subprocess_exec("), 1)


class P116R24RecoveryShimLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_shim_forwards_on_loopback_and_closes_on_normal_stop(self) -> None:
        input_port = free_udp_port()
        output_port = free_udp_port()
        loop = asyncio.get_running_loop()
        receiver = Receiver()
        shim = h264_recovery.H264RecoveryRtpShim(
            input_port=input_port,
            output_port=output_port,
        )
        receiver_transport = None
        try:
            try:
                await shim.async_start()
            except PermissionError as exc:
                raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
            receiver_transport, _ = await loop.create_datagram_endpoint(
                lambda: receiver,
                local_addr=("127.0.0.1", output_port),
            )
            send_transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                remote_addr=("127.0.0.1", input_port),
            )
            try:
                packet = rtp(1, b"\x67\x80")
                send_transport.sendto(packet)
                received = await asyncio.wait_for(receiver.queue.get(), timeout=2)
            finally:
                send_transport.close()
            self.assertEqual(received, packet)
            self.assertTrue(shim.running)
        finally:
            await shim.async_stop()
            if receiver_transport is not None:
                receiver_transport.close()
        self.assertFalse(shim.running)

    async def test_repeated_start_stop_does_not_leak_input_port(self) -> None:
        input_port = free_udp_port()
        output_port = free_udp_port()
        for _ in range(2):
            shim = h264_recovery.H264RecoveryRtpShim(
                input_port=input_port,
                output_port=output_port,
            )
            try:
                await shim.async_start()
            except PermissionError as exc:
                raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
            self.assertTrue(shim.running)
            await shim.async_stop()
            self.assertFalse(shim.running)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", input_port))
        except PermissionError as exc:
            raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
        finally:
            try:
                sock.close()
            except UnboundLocalError:
                pass

    async def test_shim_closes_on_startup_failure(self) -> None:
        input_port = free_udp_port()
        output_port = free_udp_port()
        occupied_input = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            occupied_input.bind(("127.0.0.1", input_port))
        except PermissionError as exc:
            occupied_input.close()
            raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc

        shim = h264_recovery.H264RecoveryRtpShim(
            input_port=input_port,
            output_port=output_port,
        )
        try:
            with self.assertRaises(OSError):
                await shim.async_start()
            self.assertFalse(shim.running)

            output_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                output_probe.bind(("127.0.0.1", output_port))
            except PermissionError as exc:
                raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
            finally:
                output_probe.close()
        finally:
            occupied_input.close()
            await shim.async_stop()

        await shim.async_start()
        self.assertTrue(shim.running)
        await shim.async_stop()
        self.assertFalse(shim.running)

    async def test_shim_closes_on_cancellation_after_output_bind(self) -> None:
        input_port = free_udp_port()
        output_port = free_udp_port()
        loop = asyncio.get_running_loop()
        output_endpoint_created = False

        async def endpoint_factory(*args: object, **kwargs: object) -> tuple[object, object]:
            nonlocal output_endpoint_created
            if kwargs.get("remote_addr") == ("127.0.0.1", output_port):
                output_endpoint_created = True
                return await loop.create_datagram_endpoint(*args, **kwargs)
            if kwargs.get("local_addr") == ("127.0.0.1", input_port):
                self.assertTrue(output_endpoint_created)
                raise asyncio.CancelledError()
            return await loop.create_datagram_endpoint(*args, **kwargs)

        shim = h264_recovery.H264RecoveryRtpShim(
            input_port=input_port,
            output_port=output_port,
            endpoint_factory=endpoint_factory,
        )
        try:
            with self.assertRaises(asyncio.CancelledError):
                await shim.async_start()
        except PermissionError as exc:
            raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc

        self.assertTrue(output_endpoint_created)
        self.assertFalse(shim.running)
        input_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            input_probe.bind(("127.0.0.1", input_port))
        except PermissionError as exc:
            raise unittest.SkipTest("sandbox_loopback_udp_denied") from exc
        finally:
            input_probe.close()

        fresh = h264_recovery.H264RecoveryRtpShim(
            input_port=input_port,
            output_port=output_port,
        )
        await fresh.async_start()
        self.assertTrue(fresh.running)
        await fresh.async_stop()
        self.assertFalse(fresh.running)


if __name__ == "__main__":
    unittest.main()
