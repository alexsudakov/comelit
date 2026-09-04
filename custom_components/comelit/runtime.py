from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import re
import signal
from uuid import uuid4

from aiohttp import ClientSession
from homeassistant.core import HomeAssistant

from .cloud import ComelitCloudError, async_negotiate_p2p
from .const import EVENT_RING
from .ring_event import RingObservationError, parse_v4_safe_ring
from .sdp import ComelitSdpError, transform_offer

_LOGGER = logging.getLogger(__name__)

_NATIVE_ROOT = Path("/config/comelit-native-stage")
_NATIVE_BINARY = _NATIVE_ROOT / "comelit-v4"
_NATIVE_LIB = _NATIVE_ROOT / "lib"
_HELPER_SECRETS = Path("/root/.config/comelit/secrets.env")
_RUN_DIR = Path("/run/comelit-p2p")
_OFFER_FILE = _RUN_DIR / "offer.sdp"
_REMOTE_FILE = _RUN_DIR / "remote.sdp"
_STOP_FILE = _RUN_DIR / "stop"

_DOOR_STATES = {
    "ACKED",
    "REJECTED",
    "REJECTED_NOT_READY",
    "FAILED_SAFE",
    "UNKNOWN_OUTCOME",
}

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


def _prepare_helper_secret(vip_token: str) -> None:
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


def _remove_helper_secret() -> None:
    try:
        _HELPER_SECRETS.unlink()
    except FileNotFoundError:
        pass


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
    """Direct-HA incoming-ring listener runtime.

    The persistent helper keeps one registered Comelit session for up to
    3300 seconds and may emit multiple CALL_INIT events during that session.
    Automatic reconnect is handled separately by the runtime supervisor.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        *,
        device_uuid: str,
        vip_token: str,
        oauth_access_token: str,
    ) -> None:
        self._hass = hass
        self._session = session
        self._device_uuid = device_uuid
        self._vip_token = vip_token
        self._oauth_access_token = oauth_access_token
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._offer_ready = asyncio.Event()
        self._listener_ready = asyncio.Event()
        self._ring_lines: list[str] = []
        self._last_ring_event: dict[str, str] | None = None
        self._last_error: str | None = None
        self._stopping = False
        self._door_lock = asyncio.Lock()
        self._door_result_future: asyncio.Future[str] | None = None
        self._last_door_result: dict[str, object] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def listener_ready(self) -> bool:
        return self._listener_ready.is_set()

    @property
    def ring_observed(self) -> bool:
        return self._last_ring_event is not None

    @property
    def last_door_result(self) -> dict[str, object] | None:
        return dict(self._last_door_result) if self._last_door_result else None

    def status(self) -> dict[str, object]:
        event = self._last_ring_event or {}
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "ring_observed": self.ring_observed,
            "ring_door": event.get("door"),
            "ring_source": event.get("source"),
            "ring_kind": event.get("kind"),
            "ring_direction": event.get("direction"),
            "event_id": event.get("event_id"),
            "timestamp": event.get("timestamp"),
            "last_error": self._last_error,
            "door_last_operation_id": (self._last_door_result or {}).get("operation_id"),
            "door_last_state": (self._last_door_result or {}).get("state"),
        }

    async def async_start(self) -> None:
        if self.running:
            return
        self._stopping = False
        self._offer_ready.clear()
        self._listener_ready.clear()
        self._ring_lines.clear()
        self._last_ring_event = None
        self._last_error = None
        self._task = self._hass.async_create_task(
            self._async_run_once(),
            "comelit direct ring listener",
        )

    async def async_wait_ready(self, timeout: float = 30.0) -> bool:
        if self.listener_ready:
            return True

        task = self._task
        if task is None or task.done():
            return False

        ready_wait = asyncio.create_task(self._listener_ready.wait())
        try:
            done, _ = await asyncio.wait(
                {ready_wait, task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            return ready_wait in done and ready_wait.result()
        finally:
            if not ready_wait.done():
                ready_wait.cancel()
                try:
                    await ready_wait
                except asyncio.CancelledError:
                    pass

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
        self._listener_ready.clear()
        await self._hass.async_add_executor_job(_remove_helper_secret)

    async def async_open_door(self, door: str) -> dict[str, object]:
        """Execute exactly one direct Door attempt on the persistent session."""
        if door != "entrance":
            raise ComelitRingRuntimeError("unsupported_door")

        async with self._door_lock:
            if not self.running:
                await self.async_start()

            if not await self.async_wait_ready(timeout=30):
                result = {
                    "operation_id": None,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            process = self._process
            if process is None or process.returncode is not None:
                result = {
                    "operation_id": None,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            self._door_result_future = future

            # Generate the operation id immediately before the irreversible
            # one-shot boundary.  It is HA-local and is never caller supplied.
            operation_id = f"comelit-ha-{uuid4()}"
            try:
                os.kill(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                self._door_result_future = None
                result = {
                    "operation_id": operation_id,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            try:
                state = await asyncio.wait_for(asyncio.shield(future), timeout=10)
            except TimeoutError:
                state = "UNKNOWN_OUTCOME"
            finally:
                if self._door_result_future is future:
                    self._door_result_future = None

            result = {
                "operation_id": operation_id,
                "door": door,
                "state": state,
                "protocol_acked": state == "ACKED",
                "write_count": 6 if state == "ACKED" else None,
                "automatic_retry_allowed": False,
                "physical_effect_asserted": False,
            }
            self._last_door_result = dict(result)
            return result

    async def _async_run_once(self) -> None:
        try:
            await self._async_run_cycle()
        except asyncio.CancelledError:
            raise
        except (ComelitRingRuntimeError, ComelitCloudError, ComelitSdpError) as exc:
            self._last_error = str(exc)
            _LOGGER.error("Comelit ring listener stopped: %s", exc)
        except Exception as exc:
            self._last_error = f"unexpected:{type(exc).__name__}"
            _LOGGER.exception("Unexpected Comelit ring listener failure")
        finally:
            self._process = None
            self._listener_ready.clear()
            future = self._door_result_future
            if future is not None and not future.done():
                future.set_result("UNKNOWN_OUTCOME")
            await self._hass.async_add_executor_job(_remove_helper_secret)

    async def _async_run_cycle(self) -> None:
        await self._hass.async_add_executor_job(_native_gate)
        await self._hass.async_add_executor_job(
            _prepare_helper_secret, self._vip_token
        )

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
                device_uuid=self._device_uuid,
                vip_token=self._vip_token,
                oauth_access_token=self._oauth_access_token,
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
                    "Comelit ring listener READY for persistent 3300s cycle"
                )
                continue

            if line.startswith("V4_DOOR_RESULT="):
                state = line.split("=", 1)[1]
                if state not in _DOOR_STATES:
                    state = "UNKNOWN_OUTCOME"
                future = self._door_result_future
                if future is not None and not future.done():
                    future.set_result(state)
                _LOGGER.warning("Comelit Door protocol result: %s", state)
                continue

            if "=" not in line:
                continue
            key = line.split("=", 1)[0]
            if key not in _RING_KEYS:
                continue

            self._ring_lines.append(line)
            present = {item.split("=", 1)[0] for item in self._ring_lines}
            if not _RING_KEYS.issubset(present):
                continue

            batch = self._ring_lines
            self._ring_lines = []

            try:
                ring = parse_v4_safe_ring(batch)
            except RingObservationError as exc:
                raise ComelitRingRuntimeError(f"ring_contract:{exc}") from exc

            if ring is None:
                continue
            event = ring.as_dict()
            event["event_id"] = str(uuid4())
            event["timestamp"] = datetime.now(UTC).isoformat()
            self._last_ring_event = dict(event)
            self._hass.bus.async_fire(EVENT_RING, event)
            _LOGGER.warning(
                "Comelit ring event emitted: door=%s source=%s",
                ring.door,
                ring.source,
            )
