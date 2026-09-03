from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import re
import shlex
from uuid import uuid4

from aiohttp import ClientSession
from homeassistant.core import HomeAssistant

from .cloud import ComelitCloudError, async_negotiate_p2p
from .ring_event import RingObservationError, parse_v4_safe_ring
from .sdp import ComelitSdpError, transform_offer

_LOGGER = logging.getLogger(__name__)

_NATIVE_ROOT = Path("/config/comelit-native-stage")
_NATIVE_BINARY = _NATIVE_ROOT / "comelit-v4"
_NATIVE_LIB = _NATIVE_ROOT / "lib"
_SOURCE_SECRETS = Path("/config/comelit/secrets.env")
_HELPER_SECRETS = Path("/root/.config/comelit/secrets.env")
_RUN_DIR = Path("/run/comelit-p2p")
_OFFER_FILE = _RUN_DIR / "offer.sdp"
_REMOTE_FILE = _RUN_DIR / "remote.sdp"
_STOP_FILE = _RUN_DIR / "stop"

_REQUIRED_CREDENTIALS = (
    "COMELIT_DUUID",
    "COMELIT_VIP_TOKEN",
    "COMELIT_OAUTH_ACCESS_TOKEN",
)
_RING_KEYS = {
    "V4_RING_OBSERVED",
    "V4_RING_DIRECTION",
    "V4_RING_KIND",
    "V4_RING_DOOR",
    "V4_RING_SOURCE",
}
_HEX32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


class ComelitRingRuntimeError(RuntimeError):
    """Direct incoming-ring runtime cannot complete safely."""


def _read_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            parts = shlex.split(value, posix=True)
        except ValueError:
            parts = [value]
        if len(parts) == 1:
            value = parts[0]
        result[key] = value
    return result


def _prepare_credentials() -> dict[str, str]:
    if not _SOURCE_SECRETS.is_file():
        raise ComelitRingRuntimeError("credential_file_missing")

    env = _read_env_file(_SOURCE_SECRETS)
    missing = [key for key in _REQUIRED_CREDENTIALS if not env.get(key)]
    if missing:
        raise ComelitRingRuntimeError("credentials_incomplete")

    vip_token = env["COMELIT_VIP_TOKEN"]
    if not _HEX32_RE.fullmatch(vip_token):
        raise ComelitRingRuntimeError("vip_token_shape_invalid")

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

    return env


def _read_offer() -> bytes:
    return _OFFER_FILE.read_bytes()


def _write_remote(remote: str) -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = _REMOTE_FILE.with_suffix(".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_text(remote, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, _REMOTE_FILE)
    finally:
        os.umask(old_umask)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _touch_stop() -> None:
    _RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    _STOP_FILE.touch(mode=0o600, exist_ok=True)


def _native_gate() -> None:
    if not _NATIVE_BINARY.is_file():
        raise ComelitRingRuntimeError("native_binary_missing")
    if not os.access(_NATIVE_BINARY, os.X_OK):
        raise ComelitRingRuntimeError("native_binary_not_executable")
    if not _NATIVE_LIB.is_dir():
        raise ComelitRingRuntimeError("native_library_dir_missing")


class ComelitRingRuntime:
    """One bounded direct-HA incoming-ring listener cycle.

    The frozen V4.2 helper remains bounded to 180 seconds and exits after a
    ring.  This runtime deliberately does not reconnect yet: persistent
    registration is deferred until simultaneous-client compatibility is
    tested with the official app and physical monitor.
    """

    def __init__(self, hass: HomeAssistant, session: ClientSession) -> None:
        self._hass = hass
        self._session = session
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._offer_ready = asyncio.Event()
        self._listener_ready = asyncio.Event()
        self._ring_lines: list[str] = []
        self._ring_emitted = False
        self._stopping = False

    @property
    def listener_ready(self) -> bool:
        return self._listener_ready.is_set()

    async def async_start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._offer_ready.clear()
        self._listener_ready.clear()
        self._ring_lines.clear()
        self._ring_emitted = False
        self._task = self._hass.async_create_task(
            self._async_run_once(),
            "comelit direct ring listener",
        )

    async def async_stop(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.returncode is None:
            try:
                await self._hass.async_add_executor_job(_touch_stop)
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()

        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._process = None

    async def _async_run_once(self) -> None:
        try:
            await self._async_run_cycle()
        except asyncio.CancelledError:
            raise
        except (ComelitRingRuntimeError, ComelitCloudError, ComelitSdpError) as exc:
            _LOGGER.error("Comelit ring listener stopped: %s", exc)
        except Exception:
            _LOGGER.exception("Unexpected Comelit ring listener failure")
        finally:
            self._process = None

    async def _async_run_cycle(self) -> None:
        await self._hass.async_add_executor_job(_native_gate)
        credentials = await self._hass.async_add_executor_job(_prepare_credentials)

        child_env = os.environ.copy()
        child_env["LD_LIBRARY_PATH"] = str(_NATIVE_LIB)

        process = await asyncio.create_subprocess_exec(
            str(_NATIVE_BINARY),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=child_env,
        )
        self._process = process
        reader_task = self._hass.async_create_task(
            self._async_read_output(process),
            "comelit ring helper output",
        )

        try:
            offer_wait = asyncio.create_task(self._offer_ready.wait())
            process_wait = asyncio.create_task(process.wait())
            done, pending = await asyncio.wait(
                {offer_wait, process_wait},
                timeout=15,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

            if offer_wait not in done or not offer_wait.result():
                if process.returncode is not None:
                    raise ComelitRingRuntimeError(
                        f"native_exited_before_offer:{process.returncode}"
                    )
                raise ComelitRingRuntimeError("offer_timeout")

            raw_offer = await self._hass.async_add_executor_job(_read_offer)
            comelit_offer = transform_offer(raw_offer).decode("ascii")
            remote = await async_negotiate_p2p(
                self._session,
                device_uuid=credentials["COMELIT_DUUID"],
                vip_token=credentials["COMELIT_VIP_TOKEN"],
                oauth_access_token=credentials["COMELIT_OAUTH_ACCESS_TOKEN"],
                offer_sdp=comelit_offer,
            )
            await self._hass.async_add_executor_job(_write_remote, remote)

            rc = await process.wait()
            await reader_task
            if rc != 0 and not self._stopping:
                raise ComelitRingRuntimeError(f"native_exit:{rc}")
        finally:
            if process.returncode is None:
                await self._hass.async_add_executor_job(_touch_stop)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.terminate()
                    await process.wait()
            if not reader_task.done():
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass

    async def _async_read_output(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            raise ComelitRingRuntimeError("native_stdout_missing")

        while True:
            raw = await process.stdout.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").strip()

            if line == "ICE_GATHER=PASS":
                self._offer_ready.set()
                continue

            if line == "V4_RING_LISTENER_READY=true":
                self._listener_ready.set()
                _LOGGER.warning(
                    "Comelit ring listener READY for one bounded 180s cycle"
                )
                continue

            if "=" not in line:
                continue
            key = line.split("=", 1)[0]
            if key not in _RING_KEYS:
                continue

            self._ring_lines.append(line)
            if self._ring_emitted:
                continue

            try:
                ring = parse_v4_safe_ring(self._ring_lines)
            except RingObservationError as exc:
                # Marker sets are naturally incomplete while the helper prints
                # the five safe lines one by one.  Only evaluate once all keys
                # are present.
                present = {item.split("=", 1)[0] for item in self._ring_lines}
                if _RING_KEYS.issubset(present):
                    raise ComelitRingRuntimeError(f"ring_contract:{exc}") from exc
                continue

            if ring is None:
                continue

            present = {item.split("=", 1)[0] for item in self._ring_lines}
            if not _RING_KEYS.issubset(present):
                continue

            self._ring_emitted = True
            event = ring.as_dict()
            event["event_id"] = str(uuid4())
            event["timestamp"] = datetime.now(UTC).isoformat()
            self._hass.bus.async_fire("comelit_ring", event)
            _LOGGER.warning(
                "Comelit ring event emitted: door=%s source=%s",
                ring.door,
                ring.source,
            )
