"""Opt-in bounded Comelit media smoke core, deliberately not exposed as a HA service.

A trusted HA-side caller must authenticate the Hermes task and enforce its
caller permissions *before* invoking this module.  A caller-supplied task_id is
only a budget key, never an authorization credential.  This module has no
Door/Gate/Ring, force-stop, deployment or restart entry point.

Not enabled or connected to HA by importing this file.  The existing media
manager remains the only owner of real media and listener recovery.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
import math
import re
import time
from typing import Any, Protocol

STORE_KEY = "comelit.media_smoke_budget"
STORE_VERSION = 1
MAX_PER_TASK = 3
MAX_PER_DAY = 6
WINDOW_SECONDS = 24 * 60 * 60
MAX_OPEN_SECONDS = 45
MAX_WATCH_SECONDS = 15
MAX_CLOSE_SECONDS = 45
_TASK_ID = re.compile(r"t_[a-f0-9]{8,32}\Z")


class SmokeBlocked(RuntimeError):
    """Safety condition unavailable; no new physical open may start."""


class SmokeStore(Protocol):
    async def async_load(self) -> dict[str, Any] | None: ...
    async def async_save(self, data: dict[str, Any]) -> None: ...


def ha_store_factory(hass: Any) -> Callable[[], SmokeStore]:
    """Factory for independent HA Store readback; does not access the device.

    The eventual HA adapter MUST create one budget instance per HA instance.
    Never instantiate competing budget controllers for the same Store key.
    """
    from homeassistant.helpers.storage import Store

    return lambda: Store(hass, STORE_VERSION, STORE_KEY)


class DurableMediaSmokeBudget:
    """Single-HA-process quota, durable read-back before any media side effect.

    Important: HA Store.async_save may LOG write failures rather than raising;
    a fresh Store instance must read back exactly the written version.  This
    is a necessary safety gate, not a guarantee against arbitrary disk loss.

    Missing/corrupt persistent state does not silently reset a used quota:
    initialization is separate from the physical run and restricted to the
    future trusted HA operator path.
    """

    def __init__(
        self,
        store_factory: Callable[[], SmokeStore],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store_factory = store_factory
        self._clock = clock
        self._lock = asyncio.Lock()
        self._blocked = False

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now) or now <= 0:
            raise SmokeBlocked("clock_untrusted")
        return now

    @staticmethod
    def _validated(data: object, now: float) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) != {
            "schema", "last_clock", "attempts", "tasks", "inflight", "sequence"
        } or type(data["schema"]) is not int or data["schema"] != STORE_VERSION:
            raise SmokeBlocked("budget_missing_or_invalid")
        last = data["last_clock"]
        if type(last) not in (int, float) or not math.isfinite(last) or last <= 0 or last > now:
            raise SmokeBlocked("clock_rollback_or_invalid")
        sequence = data["sequence"]
        if type(sequence) is not int or sequence < 0:
            raise SmokeBlocked("budget_sequence_invalid")
        attempts = data["attempts"]
        tasks = data["tasks"]
        inflight = data["inflight"]
        if not isinstance(attempts, list) or not isinstance(tasks, dict):
            raise SmokeBlocked("budget_structure_invalid")
        if len(attempts) > MAX_PER_DAY or len(tasks) > 512:
            raise SmokeBlocked("budget_overflow")
        if any(type(n) not in (float, int) or not math.isfinite(n) or n > now or n <= 0
               for n in attempts):
            raise SmokeBlocked("budget_clock_invalid")
        if any(not isinstance(k, str) or not _TASK_ID.fullmatch(k)
               or type(v) is not int or v < 1 or v > MAX_PER_TASK
               for k, v in tasks.items()):
            raise SmokeBlocked("budget_task_invalid")
        if inflight is not None and (
            not isinstance(inflight, str) or not _TASK_ID.fullmatch(inflight)
            or tasks.get(inflight, 0) < 1
        ):
            raise SmokeBlocked("budget_inflight_invalid")
        return deepcopy(data)

    async def _load(self, now: float) -> dict[str, Any]:
        if self._blocked:
            raise SmokeBlocked("budget_sealed")
        try:
            raw = await self._store_factory().async_load()
            return self._validated(raw, now)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            self._blocked = True
            raise SmokeBlocked("budget_unreadable") from exc

    async def _save_verified(self, data: dict[str, Any], now: float) -> None:
        try:
            await self._store_factory().async_save(deepcopy(data))
            # Fresh instance: no self._data shortcut. Catch silent write failure
            # and never start media without durable positive readback.
            readback = await self._store_factory().async_load()
            if self._validated(readback, now) != data:
                raise SmokeBlocked("budget_write_not_durable")
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            self._blocked = True
            raise
        except Exception as exc:
            self._blocked = True
            raise SmokeBlocked("budget_write_not_confirmed") from exc

    async def async_initialize_empty(self) -> None:
        """Explicit trusted-operator bootstrap only; not called by smoke runs.

        Must not reset an existing state. No media operations are performed.
        """
        async with self._lock:
            now = self._now()
            if self._blocked:
                raise SmokeBlocked("budget_sealed")
            try:
                existing = await self._store_factory().async_load()
            except Exception as exc:
                self._blocked = True
                raise SmokeBlocked("budget_unreadable") from exc
            if existing is not None:
                raise SmokeBlocked("budget_already_exists")
            await self._save_verified({
                "schema": STORE_VERSION, "last_clock": now, "attempts": [],
                "tasks": {}, "inflight": None, "sequence": 0
            }, now)

    async def async_status(self) -> dict[str, int | bool]:
        async with self._lock:
            now = self._now()
            data = await self._load(now)
            count = sum(x > now - WINDOW_SECONDS for x in data["attempts"])
            return {"used_24h": count, "limit_24h": MAX_PER_DAY,
                    "inflight": data["inflight"] is not None}

    async def async_reserve(self, task_id: str) -> dict[str, int]:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise SmokeBlocked("untrusted_task_id_format")
        async with self._lock:
            now = self._now()
            data = await self._load(now)
            if data["inflight"] is not None:
                raise SmokeBlocked("smoke_already_inflight")
            live = [x for x in data["attempts"] if x > now - WINDOW_SECONDS]
            task_count = data["tasks"].get(task_id, 0)
            if task_count >= MAX_PER_TASK or len(live) >= MAX_PER_DAY:
                raise SmokeBlocked("smoke_budget_exhausted")
            if task_id not in data["tasks"] and len(data["tasks"]) >= 512:
                raise SmokeBlocked("budget_task_capacity")
            data["attempts"] = [*live, now]
            data["tasks"][task_id] = task_count + 1
            data["inflight"] = task_id
            data["last_clock"] = now
            data["sequence"] += 1
            await self._save_verified(data, now)
            return {"task_used": task_count + 1, "day_used": len(live) + 1}

    async def async_confirm_complete(self, task_id: str) -> None:
        """Only caller with independently confirmed teardown may invoke this."""
        async with self._lock:
            now = self._now()
            data = await self._load(now)
            if data["inflight"] != task_id:
                raise SmokeBlocked("smoke_owner_mismatch")
            data["inflight"] = None
            data["last_clock"] = now
            data["sequence"] += 1
            await self._save_verified(data, now)


class MediaSmokeCycle:
    """One bounded OPEN → observe → own-lease CLOSE on an existing manager.

    This is a *library*, not a service, and has no runnable HA API entry point.
    In particular, the future trusted caller must provide a reliable native
    media-child check, installed identity readback and authenticated task id.
    """

    def __init__(self, budget: DurableMediaSmokeBudget, manager: Any,
                 supervisor: Any, transport: Any, attached: Any,
                 *, call_state: Callable[[], str],
                 media_child_absent: Callable[[], bool | None],
                 installed_sha: Callable[[], str | None]) -> None:
        self._budget = budget
        self._manager = manager
        self._supervisor = supervisor
        self._transport = transport
        self._attached = attached
        self._call_state = call_state
        self._media_child_absent = media_child_absent
        self._installed_sha = installed_sha
        self._cycle: asyncio.Task[dict[str, object]] | None = None
        self._release: asyncio.Task[object] | None = None

    def _idle(self) -> bool:
        m = self._manager.status()
        s = self._supervisor.status()
        a = self._attached.status()
        return (
            m.get("phase") == "inactive" and m.get("leases") == {}
            and m.get("active") is False and not m.get("last_error")
            and getattr(self._manager, "_teardown_unconfirmed", None) is False
            and s.get("state") == "ready" and s.get("listener_ready") is True
            and s.get("runtime_running") is True and s.get("supervisor_running") is True
            and s.get("media_paused") is False and s.get("recovery_pending") is False
            and s.get("attached_media_busy") is False
            and a.get("claimed") is False and a.get("active") is False
            and a.get("leases") == {} and self._call_state() == "idle"
            and self._media_child_absent() is True
            and self._transport.active is False
            and callable(getattr(self._transport, "_stop_marker_unproven", None))
            and self._transport._stop_marker_unproven() is False
            and isinstance(self._installed_sha(), str)
            and re.fullmatch(r"[0-9a-f]{40}", self._installed_sha()) is not None
        )

    def _sole_observation_owner(self, reason: str, installed_sha: str) -> bool:
        """Only packets from the current sole on-demand owner count as proof.

        A physical Ring/attached handoff can arrive after media START. RTP
        counters alone would wrongly attribute the new owner's video to smoke.
        No other owner's session is stopped based on this observation.
        """
        m = self._manager.status()
        sup = self._supervisor.status()
        attached = self._attached.status()
        return (
            m.get("phase") == "active"
            and m.get("active") is True
            and m.get("leases") == {reason: 1}
            and self._manager.active is True
            and self._transport.active is True
            and getattr(self._manager, "_teardown_unconfirmed", None) is False
            and sup.get("attached_media_busy") is False
            and sup.get("recovery_pending") is False
            and attached.get("claimed") is False
            and attached.get("active") is False
            and attached.get("leases") == {}
            and self._call_state() == "idle"
            and getattr(self._transport, "ring_observed", None) is False
            and self._transport._stop_marker_unproven() is False
            and self._installed_sha() == installed_sha
        )

    async def async_preflight(self) -> dict[str, object]:
        try:
            sha = self._installed_sha()
            allowed = self._idle() and isinstance(sha, str) and (
                re.fullmatch(r"[0-9a-f]{40}", sha) is not None
            )
        except Exception:
            allowed, sha = False, None
        return {"ready": allowed, "installed_sha": sha}

    async def async_run(self, task_id: str) -> dict[str, object]:
        """Trusted caller only. Cancellation of caller does not cancel owner task."""
        if self._cycle is not None:
            # Completed task is not a grant to reopen: each new request must
            # separately pass the durable quota and safety preflight.
            if not self._cycle.done():
                raise SmokeBlocked("smoke_already_running")
            self._cycle.result()  # observe any previous unexpected failure
        if self._release is not None and not self._release.done():
            raise SmokeBlocked("smoke_release_inflight")
        task = asyncio.create_task(self._run_owned(task_id), name="comelit_media_smoke_owned")
        self._cycle = task
        return await asyncio.shield(task)

    async def _run_owned(self, task_id: str) -> dict[str, object]:
        pre = await self.async_preflight()
        if not pre["ready"]:
            raise SmokeBlocked("smoke_preflight_denied")
        budget = await self._budget.async_reserve(task_id)
        # Upstream owner has been reserved; even an open timeout consumes budget.
        reason = f"smoke:{task_id}"
        outcome: dict[str, object] = {
            "installed_sha": pre["installed_sha"], "budget": budget,
            "open": "FAIL", "rtp": "NOT_PROVEN", "close": "UNCONFIRMED",
            "listener": "UNKNOWN",
        }
        try:
            # Recheck after the durable quota write.  An unrelated viewer
            # can arrive while the storage operation is awaiting I/O.
            if not self._idle() or self._installed_sha() != pre["installed_sha"]:
                raise SmokeBlocked("smoke_preopen_state_changed")
            async with asyncio.timeout(MAX_OPEN_SECONDS):
                opened = await self._manager.async_acquire(panel="entrance", reason=reason)
                if opened.get("phase") != "active" or not self._manager.active:
                    raise SmokeBlocked("smoke_open_not_active")
                # The manager allows joining an existing viewer lease. Smoke
                # must not claim exclusive ownership if that race happened.
                if self._manager.status().get("leases") != {reason: 1}:
                    raise SmokeBlocked("smoke_owner_race")
            outcome["open"] = "PASS"
            before = self._transport.video_packet_count
            loop = asyncio.get_running_loop()
            deadline = loop.time() + MAX_WATCH_SECONDS
            while loop.time() < deadline:
                if not self._sole_observation_owner(reason, pre["installed_sha"]):
                    break
                received = self._transport.video_packet_count > before
                if received and self._transport.video_forwarding:
                    # A Ring can arrive during the metric read itself.
                    if self._sole_observation_owner(reason, pre["installed_sha"]):
                        outcome["rtp"] = "PASS"
                    break
                if not self._transport.active:
                    break
                await asyncio.sleep(min(0.2, deadline - loop.time()))
        except (Exception, asyncio.CancelledError):
            # Do not retry. Teardown still runs below if this task owns a lease.
            pass
        finally:
            try:
                leases = self._manager.status().get("leases")
                if isinstance(leases, dict) and leases.get(reason) == 1:
                    self._release = asyncio.create_task(
                        self._manager.async_release(reason=reason),
                        name="comelit_media_smoke_release",
                    )
                    await asyncio.wait_for(asyncio.shield(self._release), MAX_CLOSE_SECONDS)
                elif not (isinstance(leases, dict) and reason not in leases):
                    raise SmokeBlocked("smoke_lease_unknown")
                if self._idle() and self._installed_sha() == pre["installed_sha"]:
                    outcome["close"] = "CONFIRMED_LOCAL"
                    outcome["listener"] = "READY"
                    # A clean local close is necessary but is not a successful
                    # smoke if OPEN or RTP failed. Seal the reserved attempt
                    # to prevent an automatic loop of failing live opens.
                    if (outcome["open"] == "PASS" and outcome["rtp"] == "PASS"
                            and getattr(self._transport, "ring_observed", None) is False):
                        await self._budget.async_confirm_complete(task_id)
            except (Exception, asyncio.CancelledError):
                # Keep persistent inflight reservation; NEVER unlock after a
                # failed/unknown close, even if a late release task finishes.
                pass
        return outcome
