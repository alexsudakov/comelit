"""Offline contract tests for the deprecated HA media switch's own lease.

The switch used to call manager.async_force_stop(), which clears all leases.
That path must never be used by a bounded media smoke test or by a user
turning off a switch while a real camera viewer owns the transport.

This test extracts only the switch class, so the test does not import HA or
start any native Comelit helper.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path


class HomeAssistantError(Exception):
    pass


class ComelitMediaSessionError(Exception):
    pass


class _SwitchEntity:
    def async_write_ha_state(self) -> None:
        self.writes = getattr(self, "writes", 0) + 1


def _switch_class():
    path = Path(__file__).resolve().parents[2] / "custom_components/comelit/switch.py"
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    target = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ComelitEntranceMediaSwitch"
    )
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    isolated = ast.fix_missing_locations(
        ast.Module(body=[future, target], type_ignores=[])
    )
    ns = {
        "SwitchEntity": _SwitchEntity,
        "asyncio": asyncio,
        "HomeAssistantError": HomeAssistantError,
        "ComelitMediaSessionError": ComelitMediaSessionError,
        "ENTRANCE_MEDIA_SWITCH_UNIQUE_ID": "smoke-fixture",
        "ENTRANCE_MEDIA_SWITCH_ENTITY_ID": "switch.comelit_entrance_camera",
        "ENTRANCE_CAMERA_ENTITY_ID": "camera.comelit_entrance",
    }
    exec(compile(isolated, str(path), "exec"), ns)
    return ns["ComelitEntranceMediaSwitch"]


class _Manager:
    def __init__(self, leases: dict[str, int] | None = None) -> None:
        self.leases = dict(leases or {})
        self.phase = "active" if self.leases else "inactive"
        self.acquire_calls = 0
        self.release_calls = 0
        self.force_stop_calls = 0
        self.release_started = asyncio.Event()
        self.release_block: asyncio.Event | None = None
        self.fail_release_once = False
        self.error_after_release = False

    @property
    def active(self) -> bool:
        return self.phase == "active" and bool(self.leases)

    def status(self) -> dict:
        return {"phase": self.phase, "leases": dict(self.leases)}

    async def async_acquire(self, *, panel: str, reason: str) -> dict:
        self.acquire_calls += 1
        assert panel == "entrance"
        assert reason == "ha_switch"
        await asyncio.sleep(0)  # permit deterministic task interleaving
        if self.phase in {"error", "stopping"}:
            raise ComelitMediaSessionError("media_teardown_unconfirmed")
        self.leases[reason] = self.leases.get(reason, 0) + 1
        self.phase = "active"
        return self.status()

    async def async_release(self, *, reason: str) -> dict:
        self.release_calls += 1
        assert reason == "ha_switch"
        self.release_started.set()
        if self.release_block is not None:
            await self.release_block.wait()
        if self.fail_release_once:
            self.fail_release_once = False
            raise ComelitMediaSessionError("teardown_failed")
        count = self.leases.get(reason, 0)
        assert count == 1, "switch must own precisely one lease"
        self.leases.pop(reason)
        self.phase = "error" if self.error_after_release else (
            "active" if self.leases else "inactive"
        )
        return self.status()

    async def async_force_stop(self, *, reason: str) -> dict:
        self.force_stop_calls += 1
        raise AssertionError("switch must never force-stop other owners")


class _Transport:
    pass


def test_switch_releases_only_its_lease_and_preserves_existing_viewer() -> None:
    async def run():
        manager = _Manager({"miniapp_webcodecs": 1})
        switch = _switch_class()(manager, _Transport())
        assert switch.is_on is False
        await switch.async_turn_off()
        assert manager.leases == {"miniapp_webcodecs": 1}
        await switch.async_turn_on()
        assert manager.leases == {"miniapp_webcodecs": 1, "ha_switch": 1}
        assert switch.is_on is True
        await switch.async_turn_off()
        assert manager.leases == {"miniapp_webcodecs": 1}
        assert switch.is_on is False
        assert manager.force_stop_calls == 0
    asyncio.run(run())


def test_switch_on_off_are_idempotent_even_under_concurrent_calls() -> None:
    async def run():
        manager = _Manager()
        switch = _switch_class()(manager, _Transport())
        await asyncio.gather(*[switch.async_turn_on() for _ in range(5)])
        assert manager.acquire_calls == 1
        assert manager.leases == {"ha_switch": 1}
        await asyncio.gather(*[switch.async_turn_off() for _ in range(5)])
        assert manager.release_calls == 1
        assert manager.leases == {}
        assert manager.phase == "inactive"
        assert manager.force_stop_calls == 0
    asyncio.run(run())


def test_cancelled_switch_release_retains_lease_for_safe_retry() -> None:
    async def run():
        manager = _Manager()
        manager.release_block = asyncio.Event()
        switch = _switch_class()(manager, _Transport())
        await switch.async_turn_on()
        release = asyncio.create_task(switch.async_turn_off())
        await manager.release_started.wait()
        release.cancel()
        try:
            await release
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("release cancellation must propagate")
        assert manager.leases == {"ha_switch": 1}
        manager.release_block.set()
        await switch.async_turn_off()
        assert manager.release_calls == 2
        assert manager.leases == {}
        assert manager.force_stop_calls == 0
    asyncio.run(run())


def test_switch_release_failure_cannot_claim_success() -> None:
    async def run():
        manager = _Manager()
        manager.fail_release_once = True
        switch = _switch_class()(manager, _Transport())
        await switch.async_turn_on()
        try:
            await switch.async_turn_off()
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("failed release must raise")
        assert switch.is_on is True
        assert manager.leases == {"ha_switch": 1}
        await switch.async_turn_off()
        assert manager.leases == {}
    asyncio.run(run())


def test_switch_treats_unconfirmed_teardown_as_error() -> None:
    async def run():
        manager = _Manager()
        manager.error_after_release = True
        switch = _switch_class()(manager, _Transport())
        await switch.async_turn_on()
        try:
            await switch.async_turn_off()
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("ERROR phase cannot be reported as a safe close")
        assert manager.phase == "error"
        assert manager.force_stop_calls == 0
        try:
            await switch.async_turn_on()
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("ERROR phase must not permit another open")
    asyncio.run(run())


def test_stale_lease_reacquire_only_after_confirmed_inactive() -> None:
    async def run():
        manager = _Manager()
        switch = _switch_class()(manager, _Transport())
        await switch.async_turn_on()
        manager.leases.clear()
        manager.phase = "stopping"
        for op in (switch.async_turn_on, switch.async_turn_off):
            try:
                await op()
            except HomeAssistantError:
                pass
            else:
                raise AssertionError("unconfirmed STOPPING must block new actions")
        assert manager.acquire_calls == 1
        manager.phase = "inactive"
        await switch.async_turn_on()
        assert manager.acquire_calls == 2
        assert manager.leases == {"ha_switch": 1}
        await switch.async_turn_off()
        assert manager.leases == {}
    asyncio.run(run())


def test_switch_never_uses_force_stop_static_guard() -> None:
    path = Path(__file__).resolve().parents[2] / "custom_components/comelit/switch.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "ComelitEntranceMediaSwitch")
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "async_force_stop"
        for node in ast.walk(cls)
    )
