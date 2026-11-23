"""Offline, no Home Assistant imports, network or physical media actions."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SRC = (Path(__file__).resolve().parents[2]
       / "custom_components/comelit/media_smoke.py")
spec = importlib.util.spec_from_file_location("media_smoke", SRC)
ms = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ms)

T1 = "t_1234abcd"
T2 = "t_4567efab"


class FakeStoreBackend:
    def __init__(self):
        self.data = None
        self.silent_failure = False
        self.write_count = 0
        self.delay = None

    def __call__(self):
        return FakeStore(self)


class FakeStore:
    def __init__(self, backend):
        self.backend = backend

    async def async_load(self):
        return deepcopy(self.backend.data)

    async def async_save(self, data):
        self.backend.write_count += 1
        if self.backend.delay is not None:
            await self.backend.delay.wait()
        if not self.backend.silent_failure:
            self.backend.data = deepcopy(data)


async def new_budget(clock=None):
    b = FakeStoreBackend()
    budget = ms.DurableMediaSmokeBudget(b, clock=clock or (lambda: 100000.0))
    await budget.async_initialize_empty()
    return b, budget


def test_missing_budget_blocks_without_auto_reset():
    async def run():
        backend = FakeStoreBackend()
        budget = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000)
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_reserve(T1)
        assert backend.write_count == 0
    asyncio.run(run())


def test_successful_reserve_readback_and_completion():
    async def run():
        backend, budget = await new_budget()
        assert await budget.async_reserve(T1) == {"task_used": 1, "day_used": 1}
        assert (await budget.async_status()) == {"used_24h": 1, "limit_24h": 6, "inflight": True}
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_reserve(T2)
        await budget.async_confirm_complete(T1)
        assert (await budget.async_status())["inflight"] is False
        assert backend.write_count == 3
    asyncio.run(run())


def test_budget_task_and_global_caps_and_restart():
    async def run():
        backend, budget = await new_budget()
        for _ in range(3):
            await budget.async_reserve(T1)
            await budget.async_confirm_complete(T1)
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_reserve(T1)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000)
        for _ in range(3):
            await restarted.async_reserve(T2)
            await restarted.async_confirm_complete(T2)
        with pytest.raises(ms.SmokeBlocked):
            await restarted.async_reserve("t_ffffffff")
        assert (await restarted.async_status())["used_24h"] == 6
    asyncio.run(run())


def test_inflight_persists_after_restart_and_consumes_attempt():
    async def run():
        backend, budget = await new_budget()
        await budget.async_reserve(T1)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000)
        with pytest.raises(ms.SmokeBlocked, match="inflight"):
            await restarted.async_reserve(T1)
        assert backend.data["tasks"][T1] == 1
    asyncio.run(run())


def test_silent_store_failure_prevents_reservation():
    async def run():
        backend, budget = await new_budget()
        backend.silent_failure = True
        with pytest.raises(ms.SmokeBlocked, match="budget_write_not_confirmed"):
            await budget.async_reserve(T1)
        assert backend.data["attempts"] == []
        backend.silent_failure = False
        with pytest.raises(ms.SmokeBlocked, match="budget_sealed"):
            await budget.async_reserve(T1)
    asyncio.run(run())


def test_concurrent_reservations_are_serial_and_single_flight():
    async def run():
        backend, budget = await new_budget()
        results = await asyncio.gather(budget.async_reserve(T1), budget.async_reserve(T2), return_exceptions=True)
        assert len([v for v in results if isinstance(v, dict)]) == 1
        assert len([v for v in results if isinstance(v, ms.SmokeBlocked)]) == 1
        assert len(backend.data["attempts"]) == 1
    asyncio.run(run())


def test_clock_rollback_fails_closed():
    async def run():
        clock = [100000.0]
        backend, budget = await new_budget(lambda: clock[0])
        await budget.async_reserve(T1)
        clock[0] -= 1
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_status()
    asyncio.run(run())


def test_corrupt_budget_fails_closed():
    async def run():
        backend, budget = await new_budget()
        backend.data["tasks"]["evil"] = 999
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_reserve(T1)
    asyncio.run(run())


class FakeManager:
    def __init__(self, events):
        self.events = events
        self._teardown_unconfirmed = False
        self.phase = "inactive"
        self.leases = {}
        self.last_error = None
        self.release_started = asyncio.Event()
        self.release_gate = None
        self.open_started = asyncio.Event()
        self.open_gate = None
        self.force_stops = 0

    def status(self):
        return {"phase": self.phase, "leases": dict(self.leases),
                "active": self.active, "last_error": self.last_error}

    @property
    def active(self):
        return self.phase == "active"

    async def async_acquire(self, *, panel, reason):
        self.events.append("open")
        assert panel == "entrance"
        self.open_started.set()
        if self.open_gate is not None:
            await self.open_gate.wait()
        self.phase = "active"
        self.leases[reason] = 1
        return self.status()

    async def async_release(self, *, reason):
        self.events.append("release")
        self.release_started.set()
        if self.release_gate is not None:
            await self.release_gate.wait()
        assert self.leases.pop(reason) == 1
        self.phase = "inactive"
        return self.status()

    async def async_force_stop(self, *, reason):
        self.force_stops += 1
        raise AssertionError("cannot force-stop")


class FakeSupervisor:
    def __init__(self):
        self.ready = True

    def status(self):
        return {"state": "ready" if self.ready else "error", "listener_ready": self.ready,
                "runtime_running": self.ready, "supervisor_running": self.ready,
                "media_paused": not self.ready, "recovery_pending": False}


class FakeAttached:
    def status(self):
        return {"claimed": False, "active": False, "leases": {}}


class FakeTransport:
    def __init__(self, mgr):
        self.manager = mgr
        self.video_packet_count = 0
        self.video_forwarding = False
    @property
    def active(self):
        return self.manager.active


async def runner():
    _, budget = await new_budget()
    events = []
    m = FakeManager(events)
    sup = FakeSupervisor()
    transport = FakeTransport(m)
    r = ms.MediaSmokeCycle(budget, m, sup, transport, FakeAttached(),
                           call_state=lambda: "idle", media_child_absent=lambda: True,
                           installed_sha=lambda: "a" * 40)
    return budget, m, sup, transport, r, events


def test_preflight_requires_idle_and_known_process_state():
    async def run():
        _, m, sup, _, r, events = await runner()
        assert (await r.async_preflight())["ready"] is True
        m.leases["real_viewer"] = 1
        assert (await r.async_preflight())["ready"] is False
        m.leases.clear()
        sup.ready = False
        assert (await r.async_preflight())["ready"] is False
        assert not events
    asyncio.run(run())


def test_run_cleans_up_only_own_lease_and_releases_budget():
    async def run():
        budget, m, sup, transport, r, events = await runner()
        transport.video_forwarding = True
        async def on_packet():
            await m.open_started.wait()
            transport.video_packet_count = 1
        asyncio.create_task(on_packet())
        out = await r.async_run(T1)
        assert out["open"] == "PASS"
        assert out["close"] == "CONFIRMED_LOCAL"
        assert out["listener"] == "READY"
        assert events == ["open", "release"]
        assert m.force_stops == 0
        assert (await budget.async_status())["inflight"] is False
    asyncio.run(run())


def test_caller_cancellation_does_not_kill_owned_cycle():
    async def run():
        budget, m, _, transport, r, events = await runner()
        m.release_gate = asyncio.Event()
        # End observation immediately by allowing zero transport activity after open
        async def stop_video():
            await m.open_started.wait()
            await asyncio.sleep(0)
            m.phase = "inactive"
        # Cannot use synthetic m.phase=inactive, it would bypass release confirmation;
        # instead shorten watch to zero via module constant.
        old = ms.MAX_WATCH_SECONDS
        ms.MAX_WATCH_SECONDS = 0
        try:
            caller = asyncio.create_task(r.async_run(T1))
            await m.release_started.wait()
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert r._cycle is not None and not r._cycle.done()
            with pytest.raises(ms.SmokeBlocked):
                await r.async_run(T2)
            m.release_gate.set()
            out = await asyncio.wait_for(r._cycle, 1)
            assert out["close"] == "CONFIRMED_LOCAL"
            assert (await budget.async_status())["inflight"] is False
            assert events == ["open", "release"]
        finally:
            ms.MAX_WATCH_SECONDS = old
    asyncio.run(run())


def test_release_unconfirmed_keeps_budget_inflight_and_blocks_next():
    async def run():
        budget, m, sup, _, r, events = await runner()
        m.release_gate = asyncio.Event()
        old = ms.MAX_WATCH_SECONDS
        old_close = ms.MAX_CLOSE_SECONDS
        ms.MAX_WATCH_SECONDS = 0
        ms.MAX_CLOSE_SECONDS = 0.01
        try:
            out = await r.async_run(T1)
            assert out["close"] == "UNCONFIRMED"
            assert (await budget.async_status())["inflight"] is True
            with pytest.raises(ms.SmokeBlocked):
                await r.async_run(T2)
            assert events == ["open", "release"]
            assert m.force_stops == 0
        finally:
            ms.MAX_WATCH_SECONDS = old
            ms.MAX_CLOSE_SECONDS = old_close
            # cleanup independent suspended fake so asyncio.run can exit
            m.release_gate.set()
            if r._release is not None:
                await r._release
    asyncio.run(run())


def test_budget_key_is_not_authorization_and_no_exposed_service():
    text = SRC.read_text()
    assert "hass.services.async_register" not in text
    assert "async_force_stop" not in text
    assert "open_door" not in text
    assert "open_gate" not in text
    assert "never an authorization credential" in text


def test_untrusted_task_id_does_not_touch_store():
    async def run():
        backend, budget = await new_budget()
        count = backend.write_count
        for task in ["hello", "t_@@@", "t_1234abcd/../", "t_a", "t_ABCDEF12"]:
            with pytest.raises(ms.SmokeBlocked):
                await budget.async_reserve(task)
        assert backend.write_count == count
    asyncio.run(run())


def test_budget_rolls_window_without_resetting_per_task():
    async def run():
        clock = [100000.0]
        _, budget = await new_budget(lambda: clock[0])
        await budget.async_reserve(T1)
        await budget.async_confirm_complete(T1)
        clock[0] += ms.WINDOW_SECONDS + 1
        assert (await budget.async_reserve(T2))["day_used"] == 1
    asyncio.run(run())


def test_budget_cannot_rebootstrap_existing_state():
    async def run():
        backend, budget = await new_budget()
        with pytest.raises(ms.SmokeBlocked, match="budget_already_exists"):
            await budget.async_initialize_empty()
        await budget.async_reserve(T1)
        assert backend.data["tasks"][T1] == 1
    asyncio.run(run())


def test_unknown_child_and_unavailable_call_state_prevent_any_open():
    async def run():
        budget, m, sup, transport, _, events = await runner()
        for call_state, child in (("active", True), ("idle", None), ("idle", False)):
            cycle = ms.MediaSmokeCycle(budget, m, sup, transport, FakeAttached(),
                call_state=lambda c=call_state: c, media_child_absent=lambda v=child: v,
                installed_sha=lambda: "b" * 40)
            with pytest.raises(ms.SmokeBlocked, match="preflight"):
                await cycle.async_run(T1)
        assert not events
    asyncio.run(run())


def test_budget_failure_prevents_any_acquire():
    async def run():
        budget, m, sup, transport, cycle, events = await runner()
        budget._blocked = True
        with pytest.raises(ms.SmokeBlocked, match="budget_sealed"):
            await cycle.async_run(T1)
        assert not events
    asyncio.run(run())


def test_live_viewer_race_is_fail_closed_not_force_stopped():
    async def run():
        budget, m, sup, transport, cycle, events = await runner()
        old = ms.MAX_WATCH_SECONDS
        ms.MAX_WATCH_SECONDS = 0
        try:
            async def acquire_race(*, panel, reason):
                events.append("open")
                m.phase = "active"
                m.leases["real_viewer"] = 1
                m.leases[reason] = 1
                return m.status()
            m.async_acquire = acquire_race
            out = await cycle.async_run(T1)
            assert out["open"] == "FAIL"
            assert out["close"] == "UNCONFIRMED"
            assert m.leases == {"real_viewer": 1}
            assert m.force_stops == 0
            assert (await budget.async_status())["inflight"] is True
        finally:
            ms.MAX_WATCH_SECONDS = old
    asyncio.run(run())
