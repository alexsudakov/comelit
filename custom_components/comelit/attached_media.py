from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from .h264_recovery import H264RecoveryRtpShim
from .media_transport import (
    MEDIA_AUDIO_RTP_PORT,
    MEDIA_VIDEO_HA_RTP_PORT,
    MEDIA_VIDEO_MINIAPP_RTP_PORT,
    MEDIA_VIDEO_RTP_PORT,
)

_LOGGER = logging.getLogger(__name__)
_ATTACHED_RUN_DIR = Path("/run/comelit-p2p")
_ATTACHED_LOCAL_SDP_FILE = _ATTACHED_RUN_DIR / "attached-local-rtp.sdp"
_ATTACHED_MINIAPP_SDP_FILE = _ATTACHED_RUN_DIR / "attached-miniapp-rtp.sdp"
_ATTACHED_MEDIA_OPEN_TIMEOUT_SECONDS = 15.0
_ATTACHED_MEDIA_STOP_TIMEOUT_SECONDS = 10.0
_MINIAPP_UDP_LISTENER_WAIT_TIMEOUT_SECONDS = 1.5
_MINIAPP_UDP_LISTENER_WAIT_INTERVAL_SECONDS = 0.02

_LOCAL_RTP_SDP = f"""v=0\r
o=- 0 0 IN IP4 127.0.0.1\r
s=Comelit attached inbound ring media\r
c=IN IP4 127.0.0.1\r
t=0 0\r
m=video {MEDIA_VIDEO_HA_RTP_PORT} RTP/AVP 99\r
a=rtpmap:99 H264/90000\r
a=fmtp:99 packetization-mode=1\r
a=recvonly\r
m=audio {MEDIA_AUDIO_RTP_PORT} RTP/AVP 8\r
a=rtpmap:8 PCMA/8000/1\r
a=recvonly\r
"""

_MINIAPP_RTP_SDP = f"""v=0\r
o=- 0 0 IN IP4 127.0.0.1\r
s=Comelit Mini App attached inbound ring media\r
c=IN IP4 127.0.0.1\r
t=0 0\r
m=video {MEDIA_VIDEO_MINIAPP_RTP_PORT} RTP/AVP 99\r
a=rtpmap:99 H264/90000\r
a=fmtp:99 packetization-mode=1\r
a=recvonly\r
"""


class AttachedRingRuntime(Protocol):
    @property
    def running(self) -> bool: ...

    @property
    def listener_ready(self) -> bool: ...

    @property
    def attached_media_open(self) -> bool: ...

    async def async_wait_attached_media_open(self, timeout: float) -> bool: ...

    async def async_wait_attached_media_closed(self, timeout: float) -> bool: ...

    async def async_stop_attached_media(self, timeout: float) -> bool: ...


class ComelitAttachedMediaError(RuntimeError):
    """The call-bound attached inbound media lifecycle failed safely."""


def _write_local_sdps() -> None:
    _ATTACHED_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = _ATTACHED_LOCAL_SDP_FILE.with_suffix(".tmp")
    tmp.write_text(_LOCAL_RTP_SDP, encoding="ascii")
    tmp.chmod(0o600)
    tmp.replace(_ATTACHED_LOCAL_SDP_FILE)
    miniapp_tmp = _ATTACHED_MINIAPP_SDP_FILE.with_suffix(".tmp")
    miniapp_tmp.write_text(_MINIAPP_RTP_SDP, encoding="ascii")
    miniapp_tmp.chmod(0o600)
    miniapp_tmp.replace(_ATTACHED_MINIAPP_SDP_FILE)


def _remove_local_sdps() -> None:
    for path in (_ATTACHED_LOCAL_SDP_FILE, _ATTACHED_MINIAPP_SDP_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _udp_listener_bound(port: int) -> bool:
    expected = f":{port:04X}"
    for path in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            lines = Path(path).read_text(encoding="ascii").splitlines()
        except OSError:
            return False
        for line in lines[1:]:
            fields = line.split()
            if len(fields) > 1 and fields[1].upper().endswith(expected):
                return True
    return False


async def async_wait_for_udp_listener(
    port: int,
    *,
    probe: Callable[[int], bool],
    timeout_seconds: float,
    interval_seconds: float,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    deadline = monotonic_clock() + timeout_seconds
    while True:
        try:
            if probe(port):
                return True
        except OSError:
            return False
        if monotonic_clock() >= deadline:
            return False
        await sleep(min(interval_seconds, max(0.0, deadline - monotonic_clock())))


class ComelitAttachedRingMediaTransport:
    """Bridge the persistent listener's call-bound RTP into HA Stream.

    The native persistent listener owns the upstream Comelit call and opens
    the call-bound RX media channel. This transport owns only the local
    loopback RTP consumer and H264 recovery shim. It never pauses/restarts the
    listener and never performs a second cloud/P2P bootstrap.
    """

    def __init__(
        self,
        runtime: AttachedRingRuntime,
        *,
        udp_listener_probe: Callable[[int], bool] | None = None,
    ) -> None:
        self._runtime = runtime
        self._udp_listener_probe = udp_listener_probe or _udp_listener_bound
        self._active = False
        self._video_recovery_shim: H264RecoveryRtpShim | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def active(self) -> bool:
        return (
            self._active
            and self._runtime.running
            and self._runtime.attached_media_open
        )

    @property
    def local_sdp_path(self) -> Path:
        return _ATTACHED_LOCAL_SDP_FILE

    @property
    def miniapp_local_sdp_path(self) -> Path:
        return _ATTACHED_MINIAPP_SDP_FILE

    @property
    def local_sdp_ready(self) -> bool:
        shim = self._video_recovery_shim
        return (
            self.active
            and shim is not None
            and shim.running
            and _ATTACHED_LOCAL_SDP_FILE.is_file()
        )

    @property
    def miniapp_local_sdp_ready(self) -> bool:
        shim = self._video_recovery_shim
        return (
            self.active
            and shim is not None
            and shim.running
            and _ATTACHED_MINIAPP_SDP_FILE.is_file()
        )

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def diagnostics(self) -> dict[str, object]:
        shim = self._video_recovery_shim
        if shim is None:
            return {
                "attached_rtp_input_packets": 0,
                "attached_rtp_output_packets": 0,
                "attached_rtp_first_at": None,
                "attached_rtp_last_at": None,
                "attached_rtp_last_age_ms": None,
                "attached_rtp_last_error": None,
            }
        diagnostics = shim.diagnostics()
        return {
            "attached_rtp_input_packets": diagnostics.input_rtp_packets,
            "attached_rtp_output_packets": diagnostics.output_packets,
            "attached_rtp_first_at": diagnostics.first_rtp_at,
            "attached_rtp_last_at": diagnostics.last_rtp_at,
            "attached_rtp_last_age_ms": diagnostics.last_rtp_age_ms,
            "attached_rtp_last_error": diagnostics.last_error,
        }

    async def async_start(self, panel: str) -> None:
        if panel != "entrance":
            raise ComelitAttachedMediaError("unsupported_attached_media_panel")

        async with self._lock:
            if self.active:
                return
            if not self._runtime.running or not self._runtime.listener_ready:
                raise ComelitAttachedMediaError("listener_not_ready")

            self._last_error = None
            shim = H264RecoveryRtpShim(
                input_port=MEDIA_VIDEO_RTP_PORT,
                output_port=MEDIA_VIDEO_HA_RTP_PORT,
                output_ports=(
                    MEDIA_VIDEO_HA_RTP_PORT,
                    MEDIA_VIDEO_MINIAPP_RTP_PORT,
                ),
                inactive_output_ports=(MEDIA_VIDEO_MINIAPP_RTP_PORT,),
            )
            try:
                await shim.async_start()
                await asyncio.to_thread(_write_local_sdps)
                _LOGGER.info("attached_rtp_fanout_started")
                if not await self._runtime.async_wait_attached_media_open(
                    _ATTACHED_MEDIA_OPEN_TIMEOUT_SECONDS
                ):
                    raise ComelitAttachedMediaError(
                        "attached_media_open_not_confirmed"
                    )
            except Exception as exc:
                self._last_error = str(exc)
                await shim.async_stop()
                await asyncio.to_thread(_remove_local_sdps)
                raise

            self._video_recovery_shim = shim
            self._active = True

    async def async_activate_miniapp_output(self) -> None:
        async with self._lock:
            if not self.active or self._video_recovery_shim is None:
                raise ComelitAttachedMediaError("attached_media_not_active")
            shim = self._video_recovery_shim
        ready = await async_wait_for_udp_listener(
            MEDIA_VIDEO_MINIAPP_RTP_PORT,
            probe=self._udp_listener_probe,
            timeout_seconds=_MINIAPP_UDP_LISTENER_WAIT_TIMEOUT_SECONDS,
            interval_seconds=_MINIAPP_UDP_LISTENER_WAIT_INTERVAL_SECONDS,
        )
        if ready:
            _LOGGER.info("miniapp_sink_ready")
        else:
            _LOGGER.info(
                "miniapp_sink_ready_failed reason=miniapp_attached_consumer_not_ready"
            )
            raise ComelitAttachedMediaError("miniapp_attached_consumer_not_ready")
        async with self._lock:
            if not self.active or self._video_recovery_shim is not shim:
                raise ComelitAttachedMediaError("attached_media_not_active")
            await shim.async_activate_output_port(MEDIA_VIDEO_MINIAPP_RTP_PORT)

    async def async_deactivate_miniapp_output(self) -> None:
        async with self._lock:
            shim = self._video_recovery_shim
            if shim is None:
                return
            try:
                await shim.async_deactivate_output_port(MEDIA_VIDEO_MINIAPP_RTP_PORT)
            except RuntimeError:
                return

    async def async_wait_inactive(self, timeout: float) -> bool:
        """Wait until the remote/native attached media channel closes."""
        if not self.active:
            return True
        return await self._runtime.async_wait_attached_media_closed(timeout)

    async def async_stop(self) -> None:
        async with self._lock:
            stop_error: Exception | None = None
            if self._runtime.attached_media_open:
                try:
                    stopped = await self._runtime.async_stop_attached_media(
                        _ATTACHED_MEDIA_STOP_TIMEOUT_SECONDS
                    )
                    if not stopped:
                        stop_error = ComelitAttachedMediaError(
                            "attached_media_stop_not_confirmed"
                        )
                except Exception as exc:
                    stop_error = exc

            shim = self._video_recovery_shim
            self._video_recovery_shim = None
            self._active = False
            if shim is not None:
                await shim.async_stop()
            await asyncio.to_thread(_remove_local_sdps)

            if stop_error is not None:
                self._last_error = str(stop_error)
                raise stop_error


class ComelitAttachedRingMediaSession:
    """Lease the media already attached to the current inbound call.

    Unlike ComelitMediaSessionManager this class deliberately does not pause
    the persistent listener: the listener itself owns the inbound call-bound
    transaction and media channel.
    """

    def __init__(self, transport: ComelitAttachedRingMediaTransport) -> None:
        self._transport = transport
        self._lock = asyncio.Lock()
        self._panel: str | None = None
        self._leases: dict[str, int] = {}
        self._last_error: str | None = None

    @property
    def active(self) -> bool:
        return self._transport.active

    @property
    def claimed(self) -> bool:
        """Return whether this inbound call media lifecycle already has an owner.

        This is intentionally broader than active: while the first ring-media
        acquire is still waiting for the native attached channel to open, the
        lease already exists. A camera live-view request can therefore join the
        same call transaction instead of racing into a second self-activation
        bootstrap.
        """
        return self.active or bool(self._leases)

    def status(self) -> dict[str, object]:
        return {
            "panel": self._panel,
            "active": self.active,
            "claimed": self.claimed,
            "leases": dict(self._leases),
            "last_error": self._last_error,
            "listener_paused": False,
            "ownership": "attached_inbound_session",
            "miniapp_attached_viewers": self._leases.get("miniapp_attached_view", 0),
            "miniapp_attached_stream_active": self._leases.get(
                "miniapp_attached_view", 0
            )
            > 0,
            **self._transport.diagnostics(),
        }

    async def async_acquire(self, *, panel: str, reason: str) -> dict[str, object]:
        if panel != "entrance":
            raise ComelitAttachedMediaError("unsupported_attached_media_panel")
        if not reason or len(reason) > 64:
            raise ComelitAttachedMediaError("invalid_attached_media_reason")

        async with self._lock:
            if self.active:
                self._leases[reason] = self._leases.get(reason, 0) + 1
                if reason == "miniapp_attached_view":
                    _LOGGER.info("miniapp_attached_lease_acquired")
                return self.status()
            if self._leases:
                raise ComelitAttachedMediaError("attached_media_state_mismatch")

            self._panel = panel
            self._leases = {reason: 1}
            self._last_error = None
            try:
                await self._transport.async_start(panel)
            except ComelitAttachedMediaError as exc:
                # Preserve the transport's bounded machine-readable reason.
                # Wrapping it as start_failed:<ExcType> destroys the exact
                # failure class needed by call-generation diagnostics.
                self._last_error = str(exc)
                self._panel = None
                self._leases.clear()
                raise
            except Exception as exc:
                # Unexpected exceptions remain type-only: do not surface raw
                # exception text into status/diagnostics.
                self._last_error = f"start_failed:{type(exc).__name__}"
                self._panel = None
                self._leases.clear()
                raise ComelitAttachedMediaError(self._last_error) from exc
            if reason == "miniapp_attached_view":
                _LOGGER.info("miniapp_attached_lease_acquired")
            return self.status()

    async def async_activate_miniapp_output(self) -> None:
        await self._transport.async_activate_miniapp_output()

    async def async_deactivate_miniapp_output(self) -> None:
        await self._transport.async_deactivate_miniapp_output()

    async def async_wait_inactive(self, timeout: float) -> bool:
        """Wait for the authoritative inbound call media lifetime to end."""
        if not self.active:
            return True
        return await self._transport.async_wait_inactive(timeout)

    async def async_force_stop(self, *, reason: str) -> dict[str, object]:
        """Force the bounded attached-media lifecycle closed, clearing all leases."""
        if not reason or len(reason) > 64:
            raise ComelitAttachedMediaError("invalid_attached_media_reason")
        async with self._lock:
            self._leases.clear()
            try:
                await self._transport.async_stop()
            except Exception as exc:
                self._last_error = f"stop_failed:{type(exc).__name__}"
                raise ComelitAttachedMediaError(self._last_error) from exc
            self._panel = None
            return self.status()

    async def async_release(self, *, reason: str) -> dict[str, object]:
        async with self._lock:
            count = self._leases.get(reason, 0)
            if count <= 1:
                self._leases.pop(reason, None)
            else:
                self._leases[reason] = count - 1
            if reason == "miniapp_attached_view":
                _LOGGER.info("miniapp_attached_lease_released")

            if not self._leases:
                # Always tear down the local bridge when the last lease ends.
                # The remote call may have already closed media on its own,
                # which makes self.active false before HA releases its lease.
                try:
                    await self._transport.async_stop()
                except Exception as exc:
                    self._last_error = f"stop_failed:{type(exc).__name__}"
                    raise ComelitAttachedMediaError(self._last_error) from exc
                self._panel = None
            return self.status()

    async def async_shutdown(self) -> None:
        async with self._lock:
            self._leases.clear()
            if self._transport.active or self._transport.local_sdp_path.is_file():
                try:
                    await self._transport.async_stop()
                finally:
                    self._panel = None
            else:
                self._panel = None
