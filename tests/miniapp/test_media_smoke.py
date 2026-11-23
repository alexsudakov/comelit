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

PASS_RESULT = {
    "installed_sha": "a" * 40, "status": "PASS", "open": "PASS",
    "rtp": "PASS", "close": "CONFIRMED_LOCAL", "listener": "READY",
}
FAIL_RESULT = {
    "installed_sha": "a" * 40, "status": "FAIL", "open": "FAIL",
    "rtp": "NOT_PROVEN", "close": "UNCONFIRMED", "listener": "UNKNOWN",
}

async def finalize_pass(budget, task_id):
    await budget.async_record_result(task_id, PASS_RESULT)



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
        await finalize_pass(budget, T1)
        assert (await budget.async_status())["inflight"] is False
        assert backend.write_count == 3
    asyncio.run(run())


def test_budget_task_and_global_caps_and_restart():
    async def run():
        backend, budget = await new_budget()
        for _ in range(3):
            await budget.async_reserve(T1)
            await finalize_pass(budget, T1)
        with pytest.raises(ms.SmokeBlocked):
            await budget.async_reserve(T1)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000)
        for _ in range(3):
            await restarted.async_reserve(T2)
            await finalize_pass(restarted, T2)
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
                "media_paused": not self.ready, "recovery_pending": False,
                "attached_media_busy": False}


class FakeAttached:
    def status(self):
        return {"claimed": False, "active": False, "leases": {}}


class FakeTransport:
    def __init__(self, mgr):
        self.manager = mgr
        self.video_packet_count = 0
        self.video_forwarding = False
        self.marker_unproven = False
        self.ring_observed = False
    def _stop_marker_unproven(self):
        return self.marker_unproven
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
        assert out["status"] == "PASS"
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
            # With RTP unproven, the automatic smoke budget stays sealed even
            # when the own lease was locally released.
            assert (await budget.async_status())["inflight"] is True
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
        await finalize_pass(budget, T1)
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


def test_preflight_rejects_native_attached_owner_and_unproven_stop_marker():
    async def run():
        _, m, sup, transport, r, events = await runner()
        previous = sup.status
        sup.status = lambda: {**previous(), "attached_media_busy": True}
        assert (await r.async_preflight())["ready"] is False
        sup.status = previous
        transport.marker_unproven = True
        assert (await r.async_preflight())["ready"] is False
        assert events == []
    asyncio.run(run())


def test_missing_rtp_after_clean_close_prevents_automatic_retry():
    async def run():
        budget, m, _, _, cycle, events = await runner()
        old = ms.MAX_WATCH_SECONDS
        ms.MAX_WATCH_SECONDS = 0
        try:
            result = await cycle.async_run(T1)
            assert result["open"] == "PASS"
            assert result["status"] == "FAIL"
            assert result["rtp"] == "NOT_PROVEN"
            assert result["close"] == "CONFIRMED_LOCAL"
            assert (await budget.async_status())["inflight"] is True
            with pytest.raises(ms.SmokeBlocked):
                await cycle.async_run(T2)
            assert events == ["open", "release"]
        finally:
            ms.MAX_WATCH_SECONDS = old
    asyncio.run(run())


def test_ring_arriving_during_smoke_must_not_count_as_success():
    async def run():
        budget, manager, sup, _, _, events = await runner()
        call = {"state": "idle"}
        cycle = ms.MediaSmokeCycle(
            budget, manager, sup, FakeTransport(manager), FakeAttached(),
            call_state=lambda: call["state"], media_child_absent=lambda: True,
            installed_sha=lambda: "a" * 40,
        )

        class RingPacketTransport(FakeTransport):
            def __init__(self, owner):
                self._reads = 0
                self._count = 0
                super().__init__(owner)

            @property
            def video_packet_count(self):
                self._reads += 1
                if self._reads == 2:
                    call["state"] = "ringing"
                    self.ring_observed = True
                    self._count = 1
                return self._count

            @video_packet_count.setter
            def video_packet_count(self, value):
                self._count = value

        cycle._transport = RingPacketTransport(manager)
        cycle._transport.video_forwarding = True
        out = await cycle.async_run(T1)
        assert out["open"] == "PASS"
        assert out["status"] == "FAIL"
        assert out["rtp"] == "NOT_PROVEN"
        assert out["close"] == "UNCONFIRMED"
        assert (await budget.async_status())["inflight"] is True
        assert events == ["open", "release"]
        assert manager.force_stops == 0

    asyncio.run(run())


def test_attached_owner_race_during_media_observation_is_not_success():
    async def run():
        budget, manager, sup, _, _, events = await runner()
        cycle = ms.MediaSmokeCycle(
            budget, manager, sup, FakeTransport(manager), FakeAttached(),
            call_state=lambda: "idle", media_child_absent=lambda: True,
            installed_sha=lambda: "a" * 40,
        )

        class AttachedPacketTransport(FakeTransport):
            def __init__(self, owner):
                self._reads = 0
                self._count = 0
                super().__init__(owner)

            @property
            def video_packet_count(self):
                self._reads += 1
                if self._reads == 2:
                    previous = sup.status
                    sup.status = lambda: {**previous(), "attached_media_busy": True}
                    self._count = 1
                return self._count

            @video_packet_count.setter
            def video_packet_count(self, value):
                self._count = value

        cycle._transport = AttachedPacketTransport(manager)
        cycle._transport.video_forwarding = True
        out = await cycle.async_run(T1)
        assert out["rtp"] == "NOT_PROVEN"
        assert (await budget.async_status())["inflight"] is True
        assert events == ["open", "release"]
        assert manager.force_stops == 0

    asyncio.run(run())


def test_two_independent_budget_controllers_share_atomic_single_flight():
    """Second controller must not race by reading same pre-reserve Store state."""
    async def run():
        backend, first = await new_budget()
        second = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
        results = await asyncio.gather(
            first.async_reserve(T1),
            second.async_reserve(T2),
            return_exceptions=True,
        )
        assert len([x for x in results if isinstance(x, dict)]) == 1
        assert len([x for x in results if isinstance(x, ms.SmokeBlocked)]) == 1
        assert len(backend.data["attempts"]) == 1
        assert sum(backend.data["tasks"].values()) == 1
        assert backend.data["inflight"] in (T1, T2)
    asyncio.run(run())


def test_store_write_timeout_seals_all_controllers_until_process_restart():
    """Uncertain late executor write cannot allow re-instantiation to reopen."""
    async def run():
        backend, first = await new_budget()
        blocker = asyncio.Event()
        backend.delay = blocker
        previous = ms.MAX_STORE_IO_SECONDS
        ms.MAX_STORE_IO_SECONDS = 0.01
        try:
            with pytest.raises(ms.SmokeBlocked, match="budget_write_not_confirmed"):
                await first.async_reserve(T1)
            second = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
            with pytest.raises(ms.SmokeBlocked, match="budget_sealed"):
                await second.async_reserve(T2)
            assert backend.data["attempts"] == []
        finally:
            blocker.set()
            ms.MAX_STORE_IO_SECONDS = previous
    asyncio.run(run())


def test_store_read_timeout_seals_all_controllers():
    class SlowLoadBackend(FakeStoreBackend):
        def __init__(self):
            super().__init__()
            self.block_load = False
            self.started = asyncio.Event()
            self.gate = asyncio.Event()

        def __call__(self):
            base = super().__call__()
            owner = self
            class SlowStore:
                async def async_load(self):
                    if owner.block_load:
                        owner.started.set()
                        await owner.gate.wait()
                    return await base.async_load()

                async def async_save(self, data):
                    return await base.async_save(data)
            return SlowStore()

    async def run():
        backend = SlowLoadBackend()
        first = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
        await first.async_initialize_empty()
        backend.block_load = True
        previous = ms.MAX_STORE_IO_SECONDS
        ms.MAX_STORE_IO_SECONDS = 0.01
        try:
            with pytest.raises(ms.SmokeBlocked, match="budget_unreadable"):
                await first.async_reserve(T1)
            assert backend.started.is_set()
            second = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
            with pytest.raises(ms.SmokeBlocked, match="budget_sealed"):
                await second.async_status()
        finally:
            backend.gate.set()
            ms.MAX_STORE_IO_SECONDS = previous
    asyncio.run(run())


def test_store_confirmation_timeout_does_not_reopen_inflight():
    async def run():
        backend, first = await new_budget()
        await first.async_reserve(T1)
        backend.delay = asyncio.Event()
        previous = ms.MAX_STORE_IO_SECONDS
        ms.MAX_STORE_IO_SECONDS = 0.01
        try:
            with pytest.raises(ms.SmokeBlocked, match="budget_write_not_confirmed"):
                await finalize_pass(first, T1)
            assert backend.data["inflight"] == T1
            second = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
            with pytest.raises(ms.SmokeBlocked, match="budget_sealed"):
                await second.async_reserve(T2)
        finally:
            backend.delay.set()
            ms.MAX_STORE_IO_SECONDS = previous
    asyncio.run(run())


def test_bounded_receipt_survives_new_controller_and_omits_extra_fields():
    async def run():
        backend, budget = await new_budget()
        await budget.async_reserve(T1)
        receipt = dict(PASS_RESULT, unsafe_token="never_store_this", sdp="secret")
        await budget.async_record_result(T1, receipt)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
        stored = await restarted.async_receipts(T1)
        assert len(stored) == 1
        assert stored[0]["task"] == T1
        assert stored[0]["status"] == "PASS"
        assert stored[0]["installed_sha"] == "a" * 40
        assert "unsafe_token" not in str(stored)
        assert "secret" not in str(backend.data)
        assert (await restarted.async_status())["inflight"] is False
    asyncio.run(run())


def test_failed_receipt_is_durable_but_does_not_unlock_open():
    async def run():
        backend, budget = await new_budget()
        await budget.async_reserve(T1)
        await budget.async_record_result(T1, FAIL_RESULT)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
        assert (await restarted.async_receipts(T1))[-1]["status"] == "FAIL"
        with pytest.raises(ms.SmokeBlocked, match="inflight"):
            await restarted.async_reserve(T2)
    asyncio.run(run())


def test_crash_before_result_keeps_durable_inflight_receipt():
    async def run():
        backend, budget = await new_budget()
        await budget.async_reserve(T1)
        restarted = ms.DurableMediaSmokeBudget(backend, clock=lambda: 100000.0)
        receipts = await restarted.async_receipts(T1)
        assert len(receipts) == 1 and receipts[0]["status"] == "INFLIGHT"
        assert receipts[0]["open"] == "NOT_EXECUTED"
        with pytest.raises(ms.SmokeBlocked, match="inflight"):
            await restarted.async_reserve(T2)
    asyncio.run(run())


def test_receipt_cannot_claim_pass_without_confirmed_close():
    async def run():
        backend, budget = await new_budget()
        await budget.async_reserve(T1)
        incorrect = dict(PASS_RESULT, close="UNCONFIRMED")
        with pytest.raises(ms.SmokeBlocked, match="receipt_claims_unproven_success"):
            await budget.async_record_result(T1, incorrect)
        assert (await budget.async_receipts(T1))[-1]["status"] == "INFLIGHT"
        assert (await budget.async_status())["inflight"] is True
    asyncio.run(run())


def test_receipts_are_bounded_without_resetting_historical_task_quota():
    async def run():
        clock = [100000.0]
        backend, budget = await new_budget(lambda: clock[0])
        for index in range(ms.MAX_RECEIPTS + 2):
            task = "t_" + format(index + 1, "08x")
            await budget.async_reserve(task)
            await finalize_pass(budget, task)
            clock[0] += ms.WINDOW_SECONDS + 1
        assert len(backend.data["receipts"]) == ms.MAX_RECEIPTS
        assert len(backend.data["tasks"]) == ms.MAX_RECEIPTS + 2
        assert (await budget.async_receipts("t_00000001")) == []
    asyncio.run(run())


def test_real_media_session_manager_smoke_open_and_own_release():
    """Use the real manager state machine with fake hardware boundaries."""
    import importlib.util
    actual_path = SRC.with_name("media_session.py")
    module_spec = importlib.util.spec_from_file_location(
        "media_smoke_real_manager_test", actual_path
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)

    class Listener:
        def __init__(self):
            self.media_paused = False
            self.ready = True
            self.resumed = 0

        @property
        def attached_media_busy(self):
            return False

        async def async_pause_for_media(self):
            self.media_paused = True
            self.ready = False

        async def async_resume_after_media(self):
            self.media_paused = False
            self.ready = True
            self.resumed += 1

        def status(self):
            return {
                "state": "ready" if self.ready else "paused",
                "listener_ready": self.ready,
                "runtime_running": self.ready,
                "supervisor_running": True,
                "media_paused": self.media_paused,
                "recovery_pending": False,
                "attached_media_busy": False,
            }

    class Transport:
        def __init__(self):
            self.active = False
            self.last_error = None
            self.last_native_exit_code = None
            self.video_forwarding = False
            self.ring_observed = False
            self._reads = 0
            self.stop_calls = 0

        @property
        def video_packet_count(self):
            if not self.active:
                return 0
            self._reads += 1
            return 0 if self._reads == 1 else 1

        def _stop_marker_unproven(self):
            return False

        async def async_start(self, panel):
            assert panel == "entrance"
            self.active = True
            self.video_forwarding = True

        async def async_stop(self):
            self.stop_calls += 1
            self.active = False
            self.video_forwarding = False

    async def run():
        listener = Listener()
        transport = Transport()
        manager = module.ComelitMediaSessionManager(
            listener, transport, transport_watch_interval_seconds=2.0
        )
        _, budget = await new_budget()
        cycle = ms.MediaSmokeCycle(
            budget, manager, listener, transport, FakeAttached(),
            call_state=lambda: "idle",
            media_child_absent=lambda: not transport.active,
            installed_sha=lambda: "a" * 40,
        )
        outcome = await asyncio.wait_for(cycle.async_run(T1), 3.0)
        assert outcome["status"] == "PASS"
        assert outcome["open"] == "PASS"
        assert outcome["rtp"] == "PASS"
        assert outcome["close"] == "CONFIRMED_LOCAL"
        assert manager.phase == module.MEDIA_PHASE_INACTIVE
        assert manager.status()["leases"] == {}
        assert not manager.active
        assert not transport.active
        assert transport.stop_calls == 1
        assert listener.resumed == 1
        assert listener.ready and not listener.media_paused
        receipts = await budget.async_receipts(T1)
        assert receipts[-1]["status"] == "PASS"
        assert (await budget.async_status())["inflight"] is False

    asyncio.run(run())


def test_caller_cancellation_during_real_manager_open_does_not_cancel_owner():
    """External cancellation may not abandon the manager's physical owner."""
    import importlib.util
    actual_path = SRC.with_name("media_session.py")
    module_spec = importlib.util.spec_from_file_location(
        "media_smoke_real_cancel_test", actual_path
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)

    class Listener:
        def __init__(self):
            self.media_paused = False
            self.ready = True

        @property
        def attached_media_busy(self):
            return False

        async def async_pause_for_media(self):
            self.media_paused = True
            self.ready = False

        async def async_resume_after_media(self):
            self.media_paused = False
            self.ready = True

        def status(self):
            return {
                "state": "ready" if self.ready else "paused",
                "listener_ready": self.ready,
                "runtime_running": self.ready,
                "supervisor_running": True,
                "media_paused": self.media_paused,
                "recovery_pending": False,
                "attached_media_busy": False,
            }

    class Transport:
        def __init__(self):
            self.active = False
            self.last_error = None
            self.last_native_exit_code = None
            self.video_packet_count = 0
            self.video_forwarding = False
            self.ring_observed = False
            self.started = asyncio.Event()
            self.allow_start = asyncio.Event()
            self.stop_calls = 0

        def _stop_marker_unproven(self):
            return False

        async def async_start(self, panel):
            self.started.set()
            await self.allow_start.wait()
            self.active = True

        async def async_stop(self):
            self.stop_calls += 1
            self.active = False

    async def run():
        listener = Listener()
        transport = Transport()
        manager = module.ComelitMediaSessionManager(
            listener, transport, transport_watch_interval_seconds=2.0
        )
        _, budget = await new_budget()
        cycle = ms.MediaSmokeCycle(
            budget, manager, listener, transport, FakeAttached(),
            call_state=lambda: "idle",
            media_child_absent=lambda: not transport.active,
            installed_sha=lambda: "a" * 40,
        )
        before = ms.MAX_WATCH_SECONDS
        ms.MAX_WATCH_SECONDS = 0
        try:
            caller = asyncio.create_task(cycle.async_run(T1))
            await asyncio.wait_for(transport.started.wait(), 2.0)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert cycle._cycle is not None and not cycle._cycle.done()
            transport.allow_start.set()
            outcome = await asyncio.wait_for(cycle._cycle, 3.0)
            assert outcome["status"] == "FAIL"  # RTP was not proven
            assert outcome["open"] == "PASS"
            assert outcome["close"] == "CONFIRMED_LOCAL"
            assert manager.phase == module.MEDIA_PHASE_INACTIVE
            assert manager.status()["leases"] == {}
            assert transport.stop_calls == 1
            assert listener.ready and not listener.media_paused
            assert (await budget.async_status())["inflight"] is True
        finally:
            transport.allow_start.set()
            ms.MAX_WATCH_SECONDS = before

    asyncio.run(run())


def test_noncooperative_open_returns_bounded_caller_and_seals_late_success():
    """Late success after a stuck manager recovery cannot unlock next attempt."""
    async def run():
        budget, manager, _, transport, cycle, events = await runner()
        started = asyncio.Event()
        complete_start = asyncio.Event()
        observed_cancel = asyncio.Event()
        old_open = ms.MAX_OPEN_SECONDS
        old_watch = ms.MAX_WATCH_SECONDS
        old_wall = ms.MAX_CYCLE_WALL_SECONDS
        ms.MAX_OPEN_SECONDS = 0.01
        ms.MAX_WATCH_SECONDS = 0.5
        ms.MAX_CYCLE_WALL_SECONDS = 0.03

        async def stubborn_open(*, panel, reason):
            events.append("open")
            started.set()
            try:
                await complete_start.wait()
            except asyncio.CancelledError:
                # Real manager startup recovery can defer cancellation.
                observed_cancel.set()
                await complete_start.wait()
            manager.phase = "active"
            manager.leases[reason] = 1
            return manager.status()

        manager.async_acquire = stubborn_open
        transport.video_forwarding = True

        async def give_late_packet():
            await complete_start.wait()
            await asyncio.sleep(0.01)
            transport.video_packet_count = 1

        packet_task = asyncio.create_task(give_late_packet())
        try:
            with pytest.raises(ms.SmokeBlocked, match="smoke_caller_deadline"):
                await asyncio.wait_for(cycle.async_run(T1), 0.5)
            assert started.is_set()
            assert observed_cancel.is_set()
            assert cycle._cycle is not None and not cycle._cycle.done()
            assert (await budget.async_status())["inflight"] is True
            with pytest.raises(ms.SmokeBlocked, match="already_running"):
                await cycle.async_run(T2)

            # Allow the original manager owner (not a second controller) to
            # complete its late OPEN, observe video, and release its own lease.
            complete_start.set()
            late = await asyncio.wait_for(cycle._cycle, 1.0)
            await packet_task
            assert late["open"] == "PASS"
            assert late["rtp"] == "PASS"
            assert late["close"] == "CONFIRMED_LOCAL"
            assert late["status"] == "FAIL"
            assert manager.leases == {}
            assert manager.force_stops == 0
            assert (await budget.async_status())["inflight"] is True
            assert (await budget.async_receipts(T1))[-1]["status"] == "FAIL"
            with pytest.raises(ms.SmokeBlocked, match="inflight"):
                await cycle.async_run(T2)
        finally:
            complete_start.set()
            ms.MAX_OPEN_SECONDS = old_open
            ms.MAX_WATCH_SECONDS = old_watch
            ms.MAX_CYCLE_WALL_SECONDS = old_wall
            await packet_task

    asyncio.run(run())


def test_caller_timeout_during_budget_write_never_starts_late_open():
    """A delayed durable reserve must not physically OPEN after caller expiry."""
    async def run():
        backend, budget = await new_budget()
        events = []
        manager = FakeManager(events)
        transport = FakeTransport(manager)
        cycle = ms.MediaSmokeCycle(
            budget, manager, FakeSupervisor(), transport, FakeAttached(),
            call_state=lambda: "idle",
            media_child_absent=lambda: True,
            installed_sha=lambda: "a" * 40,
        )
        gate = asyncio.Event()
        backend.delay = gate
        old_wall = ms.MAX_CYCLE_WALL_SECONDS
        ms.MAX_CYCLE_WALL_SECONDS = 0.02
        try:
            with pytest.raises(ms.SmokeBlocked, match="smoke_caller_deadline"):
                await asyncio.wait_for(cycle.async_run(T1), 0.5)
            assert backend.write_count >= 2  # init + blocked reserve
            assert events == []
            gate.set()
            final = await asyncio.wait_for(cycle._cycle, 1.0)
            assert final["open"] == "FAIL"
            assert final["close"] == "UNCONFIRMED"  # no OPEN ever entered
            assert final["status"] == "FAIL"
            assert events == []
            assert (await budget.async_status())["inflight"] is True
            with pytest.raises(ms.SmokeBlocked, match="inflight"):
                await cycle.async_run(T2)
        finally:
            gate.set()
            ms.MAX_CYCLE_WALL_SECONDS = old_wall

    asyncio.run(run())


def test_cancelled_caller_during_budget_save_never_opens_camera():
    """Reservation may finish after a caller disconnect; no physical start."""
    async def run():
        backend, budget = await new_budget()
        gate = asyncio.Event()
        backend.delay = gate
        events = []
        manager = FakeManager(events)
        transport = FakeTransport(manager)
        cycle = ms.MediaSmokeCycle(
            budget, manager, FakeSupervisor(), transport, FakeAttached(),
            call_state=lambda: "idle", media_child_absent=lambda: True,
            installed_sha=lambda: "a" * 40,
        )
        caller = asyncio.create_task(cycle.async_run(T1))
        try:
            for _ in range(100):
                if backend.write_count >= 2:  # init + pending reserve
                    break
                await asyncio.sleep(0)
            assert backend.write_count >= 2
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert events == []
            gate.set()
            outcome = await asyncio.wait_for(cycle._cycle, 1)
            assert outcome["status"] == "FAIL"
            assert outcome["open"] == "FAIL"
            assert outcome["close"] == "UNCONFIRMED"
            assert events == []
            assert (await budget.async_status())["inflight"] is True
            assert (await budget.async_receipts(T1))[-1]["status"] == "FAIL"
        finally:
            gate.set()
    asyncio.run(run())


def test_cancelled_caller_during_open_cannot_rearm_after_late_rtp_pass():
    """The same owned task may cleanly finish, but lost caller seals result."""
    async def run():
        budget, manager, sup, _, _, events = await runner()
        manager.open_gate = asyncio.Event()

        class PacketTransport(FakeTransport):
            def __init__(self, owner):
                self._count = 0
                self._reads = 0
                super().__init__(owner)

            @property
            def video_packet_count(self):
                self._reads += 1
                return 0 if self._reads < 2 else 1

            @video_packet_count.setter
            def video_packet_count(self, value):
                self._count = value

        transport = PacketTransport(manager)
        transport.video_forwarding = True
        cycle = ms.MediaSmokeCycle(
            budget, manager, sup, transport, FakeAttached(),
            call_state=lambda: "idle", media_child_absent=lambda: True,
            installed_sha=lambda: "a" * 40,
        )
        caller = asyncio.create_task(cycle.async_run(T1))
        try:
            await asyncio.wait_for(manager.open_started.wait(), 1)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert cycle._cycle is not None and not cycle._cycle.done()
            manager.open_gate.set()
            outcome = await asyncio.wait_for(cycle._cycle, 1)
            assert outcome["open"] == "PASS"
            assert outcome["rtp"] == "PASS"
            assert outcome["close"] == "CONFIRMED_LOCAL"
            assert outcome["status"] == "FAIL"
            assert events == ["open", "release"]
            assert manager.leases == {}
            assert manager.force_stops == 0
            assert (await budget.async_status())["inflight"] is True
            assert (await budget.async_receipts(T1))[-1]["status"] == "FAIL"
            with pytest.raises(ms.SmokeBlocked, match="inflight"):
                await cycle.async_run(T2)
        finally:
            manager.open_gate.set()
    asyncio.run(run())
