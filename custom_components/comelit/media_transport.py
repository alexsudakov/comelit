from __future__ import annotations

import asyncio
from collections.abc import Callable
import hashlib
import logging
import os
from pathlib import Path
import re

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .cloud import ComelitCloudError, async_negotiate_p2p
from .media_diagnostics import MediaProgressDiagnostics
from .oauth import ComelitOAuthError, ComelitOAuthManager
from .sdp import ComelitSdpError, transform_offer

_LOGGER = logging.getLogger(__name__)

_NATIVE_ROOT = Path(__file__).resolve().parent / "native"
_MEDIA_NATIVE_BINARY = _NATIVE_ROOT / "comelit-media"
_NATIVE_LIB = _NATIVE_ROOT / "lib"
_HELPER_SECRETS = Path("/root/.config/comelit/secrets.env")
_MEDIA_RUN_DIR = Path("/run/comelit-media")
_MEDIA_OFFER_FILE = _MEDIA_RUN_DIR / "offer.sdp"
_MEDIA_REMOTE_FILE = _MEDIA_RUN_DIR / "remote.sdp"
_MEDIA_STOP_FILE = _MEDIA_RUN_DIR / "stop"
_MEDIA_LOCAL_SDP_FILE = _MEDIA_RUN_DIR / "local-rtp.sdp"

MEDIA_NATIVE_BINARY_SHA256 = (
    "91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7"
)
MEDIA_VIDEO_RTP_PORT = 17899
MEDIA_AUDIO_RTP_PORT = 17808

_HEX32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
_MEDIA_NATIVE_MARKER_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")
_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE = re.compile(
    r"^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|"
    r"REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|"
    r"FATAL|[0-9]{1,10})$"
)
_MEDIA_NATIVE_MARKER_PREFIXES = (
    "ICE_",
    "REMOTE_SDP_",
    "PSEUDOTCP_",
    "SELECTED_PAIR_",
    "V4_",
    "P12_",
    "CTPP_",
    "ENTRANCE_",
    "SELF_ACTIVATION_",
    "CLIENT_VIDEO_",
    "DEVICE_VIDEO_",
    "P78_",
    "P80_",
)
_MEDIA_NATIVE_MARKER_TAIL_LIMIT = 40
_MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS = 1.0

_LOCAL_RTP_SDP = f"""v=0\r
o=- 0 0 IN IP4 127.0.0.1\r
s=Comelit entrance media\r
c=IN IP4 127.0.0.1\r
t=0 0\r
m=video {MEDIA_VIDEO_RTP_PORT} RTP/AVP 99\r
a=rtpmap:99 H264/90000\r
a=recvonly\r
m=audio {MEDIA_AUDIO_RTP_PORT} RTP/AVP 8\r
a=rtpmap:8 PCMA/8000/1\r
a=recvonly\r
"""


class ComelitMediaTransportError(RuntimeError):
    """The native entrance media transport cannot complete safely."""


def _prepare_helper_secret(vip_token: str) -> None:
    if not _HEX32_RE.fullmatch(vip_token):
        raise ComelitMediaTransportError("vip_token_shape_invalid")

    _HELPER_SECRETS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_HELPER_SECRETS.parent, 0o700)
    tmp = _HELPER_SECRETS.with_suffix(".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_text(f"COMELIT_VIP_TOKEN={vip_token}\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, _HELPER_SECRETS)
    finally:
        os.umask(old_umask)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _remove_helper_secret() -> None:
    try:
        _HELPER_SECRETS.unlink()
    except FileNotFoundError:
        pass


def _prepare_run_dir() -> None:
    _MEDIA_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_MEDIA_RUN_DIR, 0o700)
    for path in (
        _MEDIA_OFFER_FILE,
        _MEDIA_REMOTE_FILE,
        _MEDIA_STOP_FILE,
        _MEDIA_LOCAL_SDP_FILE,
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _read_offer() -> bytes:
    return _MEDIA_OFFER_FILE.read_bytes()


def _atomic_write(path: Path, data: bytes) -> None:
    _MEDIA_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        os.umask(old_umask)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_remote(remote: str) -> None:
    _atomic_write(_MEDIA_REMOTE_FILE, remote.encode("utf-8"))


def _write_local_sdp() -> None:
    _atomic_write(_MEDIA_LOCAL_SDP_FILE, _LOCAL_RTP_SDP.encode("ascii"))


def _touch_stop() -> None:
    _MEDIA_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    _MEDIA_STOP_FILE.touch(mode=0o600, exist_ok=True)
    os.chmod(_MEDIA_STOP_FILE, 0o600)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_gate() -> None:
    if not _MEDIA_NATIVE_BINARY.is_file():
        raise ComelitMediaTransportError("media_native_binary_missing")
    try:
        actual_sha256 = _sha256_file(_MEDIA_NATIVE_BINARY)
    except OSError as exc:
        raise ComelitMediaTransportError("media_native_binary_sha256_unreadable") from exc
    if actual_sha256 != MEDIA_NATIVE_BINARY_SHA256:
        raise ComelitMediaTransportError("media_native_binary_sha256_mismatch")
    if not _NATIVE_LIB.is_dir():
        raise ComelitMediaTransportError("native_library_dir_missing")
    if not os.access(_MEDIA_NATIVE_BINARY, os.X_OK):
        try:
            os.chmod(_MEDIA_NATIVE_BINARY, 0o700)
        except OSError as exc:
            raise ComelitMediaTransportError("media_native_binary_chmod_failed") from exc
    if not os.access(_MEDIA_NATIVE_BINARY, os.X_OK):
        raise ComelitMediaTransportError("media_native_binary_not_executable")


class ComelitEntranceMediaTransport:
    """Own one native entrance media process and its cloud bootstrap.

    This class assumes the persistent listener has already been paused by
    ComelitMediaSessionManager. It never starts/stops the listener and has no
    Door entrypoint. The native helper unwraps only inbound PT99/PT8 RTP to
    loopback ports described by local_sdp_path.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        *,
        entry: ConfigEntry,
        device_uuid: str,
        vip_token: str,
        oauth: ComelitOAuthManager,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._session = session
        self._device_uuid = device_uuid
        self._vip_token = vip_token
        self._oauth = oauth
        self._task: asyncio.Task[None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._offer_ready = asyncio.Event()
        self._media_active = asyncio.Event()
        self._video_forwarding = asyncio.Event()
        self._audio_forwarding = asyncio.Event()
        self._stopping = False
        self._last_error: str | None = None
        self._native_marker_tail: list[str] = []
        self._last_native_exit_code: int | None = None
        self._last_native_failure_markers: list[str] = []
        self._progress = MediaProgressDiagnostics()
        self._status_listeners: set[Callable[[], None]] = set()
        self._status_notify_handle: asyncio.TimerHandle | None = None
        self._last_status_notify_monotonic: float | None = None

    @property
    def active(self) -> bool:
        process = self._process
        return (
            self._media_active.is_set()
            and process is not None
            and process.returncode is None
        )

    @property
    def local_sdp_path(self) -> Path:
        return _MEDIA_LOCAL_SDP_FILE

    @property
    def video_forwarding(self) -> bool:
        return self._video_forwarding.is_set()

    @property
    def audio_forwarding(self) -> bool:
        return self._audio_forwarding.is_set()

    @property
    def video_packet_count(self) -> int:
        return self._progress.video_packet_count

    @property
    def audio_packet_count(self) -> int:
        return self._progress.audio_packet_count

    @property
    def last_video_progress_monotonic(self) -> float | None:
        return self._progress.last_video_progress_monotonic

    @property
    def last_audio_progress_monotonic(self) -> float | None:
        return self._progress.last_audio_progress_monotonic

    @property
    def video_last_packet_age_seconds(self) -> float | None:
        return self._progress.video_last_packet_age_seconds

    @property
    def audio_last_packet_age_seconds(self) -> float | None:
        return self._progress.audio_last_packet_age_seconds

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_native_exit_code(self) -> int | None:
        return self._last_native_exit_code

    @property
    def last_native_failure_markers(self) -> list[str]:
        return list(self._last_native_failure_markers)

    def async_add_status_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a bounded diagnostics status listener and return its remover."""
        self._status_listeners.add(callback)

        def remove() -> None:
            self._status_listeners.discard(callback)

        return remove

    def _cancel_status_notify(self) -> None:
        handle = self._status_notify_handle
        if handle is not None:
            handle.cancel()
        self._status_notify_handle = None

    def _notify_status_now(self) -> None:
        self._status_notify_handle = None
        self._last_status_notify_monotonic = asyncio.get_running_loop().time()
        for callback in tuple(self._status_listeners):
            callback()

    def _notify_status_bounded(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        last = self._last_status_notify_monotonic
        if last is None or now - last >= _MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS:
            self._cancel_status_notify()
            self._notify_status_now()
            return
        if self._status_notify_handle is None:
            delay = _MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS - (now - last)
            self._status_notify_handle = loop.call_later(delay, self._notify_status_now)

    def _remember_native_marker(self, line: str) -> None:
        if "=" not in line:
            return
        key, value = line.split("=", 1)
        if not _MEDIA_NATIVE_MARKER_KEY_RE.fullmatch(key):
            return
        if not key.startswith(_MEDIA_NATIVE_MARKER_PREFIXES):
            return
        safe_value = (
            value
            if _MEDIA_NATIVE_MARKER_SAFE_VALUE_RE.fullmatch(value)
            else "<redacted>"
        )
        self._native_marker_tail.append(f"{key}={safe_value}")
        if len(self._native_marker_tail) > _MEDIA_NATIVE_MARKER_TAIL_LIMIT:
            del self._native_marker_tail[:-_MEDIA_NATIVE_MARKER_TAIL_LIMIT]

    def _capture_native_failure(self, returncode: int) -> None:
        self._last_native_exit_code = returncode
        self._last_native_failure_markers = list(self._native_marker_tail)

    async def async_start(self, panel: str) -> None:
        if panel != "entrance":
            raise ComelitMediaTransportError("unsupported_media_panel")
        if self.active:
            return
        if self._task is not None and not self._task.done():
            raise ComelitMediaTransportError("media_transport_start_in_progress")

        self._stopping = False
        self._last_error = None
        self._native_marker_tail.clear()
        self._last_native_exit_code = None
        self._last_native_failure_markers = []
        self._cancel_status_notify()
        self._progress.reset()
        self._last_status_notify_monotonic = None
        self._offer_ready.clear()
        self._media_active.clear()
        self._video_forwarding.clear()
        self._audio_forwarding.clear()
        self._task = self._entry.async_create_background_task(
            self._hass,
            self._async_run_once(),
            "comelit entrance media transport",
        )

        active_wait = asyncio.create_task(self._media_active.wait())
        task = self._task
        try:
            done, _ = await asyncio.wait(
                {active_wait, task},
                timeout=45,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if active_wait in done and active_wait.result() and self.active:
                return
            if task.done():
                await task
                raise ComelitMediaTransportError(
                    self._last_error or "media_transport_ended_before_active"
                )
            raise ComelitMediaTransportError("media_active_timeout")
        except Exception:
            await self.async_stop()
            raise
        finally:
            if not active_wait.done():
                active_wait.cancel()
                try:
                    await active_wait
                except asyncio.CancelledError:
                    pass

    async def async_stop(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.returncode is None:
            try:
                await self._hass.async_add_executor_job(_touch_stop)
                await asyncio.wait_for(process.wait(), timeout=8)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()

        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._task = None
        self._process = None
        self._media_active.clear()
        self._offer_ready.clear()
        self._video_forwarding.clear()
        self._audio_forwarding.clear()
        self._cancel_status_notify()
        await self._hass.async_add_executor_job(_remove_helper_secret)

    async def _async_run_once(self) -> None:
        try:
            await self._async_run_cycle()
        except asyncio.CancelledError:
            raise
        except (
            ComelitMediaTransportError,
            ComelitCloudError,
            ComelitOAuthError,
            ComelitSdpError,
        ) as exc:
            self._last_error = str(exc)
            if not self._stopping:
                if str(exc).startswith(
                    (
                        "media_native_exited_before_offer:",
                        "media_native_exited_before_active:",
                        "media_native_exit:",
                    )
                ):
                    _LOGGER.error(
                        "Comelit entrance media transport stopped: %s; "
                        "safe_native_markers=%s",
                        exc,
                        self._last_native_failure_markers,
                    )
                else:
                    _LOGGER.error("Comelit entrance media transport stopped: %s", exc)
        except Exception as exc:
            self._last_error = f"unexpected:{type(exc).__name__}"
            if not self._stopping:
                _LOGGER.exception("Unexpected Comelit entrance media failure")
        finally:
            self._media_active.clear()
            self._process = None
            await self._hass.async_add_executor_job(_remove_helper_secret)

    async def _async_run_cycle(self) -> None:
        await self._hass.async_add_executor_job(_native_gate)
        await self._hass.async_add_executor_job(_prepare_run_dir)
        await self._hass.async_add_executor_job(_prepare_helper_secret, self._vip_token)

        child_env = os.environ.copy()
        child_env["LD_LIBRARY_PATH"] = str(_NATIVE_LIB)
        process = await asyncio.create_subprocess_exec(
            str(_MEDIA_NATIVE_BINARY),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=child_env,
        )
        self._process = process
        self._reader_task = self._entry.async_create_background_task(
            self._hass,
            self._async_read_output(process),
            "comelit entrance media helper output",
        )

        try:
            offer_wait = asyncio.create_task(self._offer_ready.wait())
            process_wait = asyncio.create_task(process.wait())
            done, pending = await asyncio.wait(
                {offer_wait, process_wait},
                timeout=15,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if offer_wait not in done or not offer_wait.result():
                if process.returncode is not None:
                    reader = self._reader_task
                    if reader is not None:
                        await reader
                    self._capture_native_failure(process.returncode)
                    raise ComelitMediaTransportError(
                        f"media_native_exited_before_offer:{process.returncode}"
                    )
                raise ComelitMediaTransportError("media_offer_timeout")

            raw_offer = await self._hass.async_add_executor_job(_read_offer)
            comelit_offer = transform_offer(raw_offer).decode("ascii")
            oauth_access_token = await self._oauth.async_get_access_token()
            # No generic automatic retry here. The media lifecycle owns one
            # bootstrap attempt; token refresh is handled before this call by
            # ComelitOAuthManager according to persisted expiry metadata.
            remote = await async_negotiate_p2p(
                self._session,
                device_uuid=self._device_uuid,
                vip_token=self._vip_token,
                oauth_access_token=oauth_access_token,
                offer_sdp=comelit_offer,
            )
            await self._hass.async_add_executor_job(_write_remote, remote)

            active_wait = asyncio.create_task(self._media_active.wait())
            process_wait = asyncio.create_task(process.wait())
            done, pending = await asyncio.wait(
                {active_wait, process_wait},
                timeout=30,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if active_wait not in done or not active_wait.result():
                if process.returncode is not None:
                    reader = self._reader_task
                    if reader is not None:
                        await reader
                    self._capture_native_failure(process.returncode)
                    raise ComelitMediaTransportError(
                        f"media_native_exited_before_active:{process.returncode}"
                    )
                raise ComelitMediaTransportError("media_signaling_timeout")

            await self._hass.async_add_executor_job(_write_local_sdp)

            rc = await process.wait()
            reader = self._reader_task
            if reader is not None:
                await reader
            if not self._stopping:
                self._capture_native_failure(rc)
                raise ComelitMediaTransportError(f"media_native_exit:{rc}")
        finally:
            if process.returncode is None:
                await self._hass.async_add_executor_job(_touch_stop)
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
            reader = self._reader_task
            if reader is not None and not reader.done():
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass
            self._reader_task = None

    async def _async_read_output(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            raise ComelitMediaTransportError("media_native_stdout_missing")

        while True:
            raw = await process.stdout.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").strip()
            self._remember_native_marker(line)

            if line == "ICE_GATHER=PASS":
                self._offer_ready.set()
            elif line == "P80_MEDIA_ACTIVE=true":
                self._media_active.set()
                _LOGGER.info("Comelit entrance media session ACTIVE")
            elif line == "P80_VIDEO_RTP_FORWARDING=PASS":
                self._video_forwarding.set()
            elif line == "P80_AUDIO_RTP_FORWARDING=PASS":
                self._audio_forwarding.set()
            elif line.startswith((
                "P80_VIDEO_RTP_PACKETS=",
                "P80_AUDIO_RTP_PACKETS=",
            )):
                if self._progress.update_marker(line):
                    self._notify_status_bounded()
            elif line in {
                "P80_WRAPPER_PROFILE_MISMATCH=true",
                "P80_RTP_FORWARD_SOCKET=FAIL",
                "P80_RTP_FORWARD_SEND=FAIL",
            }:
                self._last_error = line.lower()
