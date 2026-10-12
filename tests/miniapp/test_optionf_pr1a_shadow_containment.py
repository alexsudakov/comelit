from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module, load_plain_module

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)


class _BrokenController:
    def __init__(self) -> None:
        self.calls = 0

    def observe_native_line(self, owner: str, line: str) -> None:
        self.calls += 1
        raise RuntimeError("shadow failure")

    def note_state(self, owner: str, state: str) -> None:
        self.calls += 1
        raise RuntimeError("shadow failure")


class _FakeOAuth:
    def __init__(self, *args, **kwargs) -> None:
        pass


class _FakeRuntime:
    def __init__(self, *args, **kwargs) -> None:
        self.ring_shadow = kwargs.get("ring_shadow")
        self.stop_calls = 0

    def set_ring_media_coordinator(self, coordinator) -> None:
        self.ring_media = coordinator

    def set_synthetic_ring_media_coordinator(self, coordinator) -> None:
        self.synthetic_ring_media = coordinator

    async def async_stop(self) -> None:
        self.stop_calls += 1


class _FakeSupervisor:
    def __init__(self, *args, **kwargs) -> None:
        self.ring_shadow = kwargs.get("ring_shadow")
        self.start_calls = 0
        self.stop_calls = 0

    async def async_start(self) -> None:
        self.start_calls += 1

    async def async_stop(self) -> None:
        self.stop_calls += 1

    async def async_recover_attached_media_stop_failure(self) -> None:
        return None


class _FakeMediaTransport:
    def __init__(self, *args, **kwargs) -> None:
        self.ring_shadow = kwargs.get("ring_shadow")
        self.stop_calls = 0

    async def async_stop(self) -> None:
        self.stop_calls += 1


class _FakeMediaSession:
    def __init__(self, *args, **kwargs) -> None:
        self.ring_shadow = kwargs.get("ring_shadow")
        self.shutdown_calls = 0

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeAttachedTransport:
    def __init__(self, *args, **kwargs) -> None:
        pass


class _FakeAttachedSession:
    def __init__(self, *args, **kwargs) -> None:
        self.shutdown_calls = 0

    def set_stop_failure_recovery(self, callback) -> None:
        self.recovery = callback

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1

    async def async_wait_inactive(self) -> None:
        return None


class _FakeProvider:
    def __init__(self, *args, **kwargs) -> None:
        self.dispose_calls = 0

    async def async_dispose(self) -> None:
        self.dispose_calls += 1


class _FakeRingMedia:
    def __init__(self, *args, **kwargs) -> None:
        self.shutdown_calls = 0

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.forward_calls = 0
        self.unload_calls = 0

    async def async_forward_entry_setups(self, entry, platforms) -> bool:
        self.forward_calls += 1
        return True

    async def async_unload_platforms(self, entry, platforms) -> bool:
        self.unload_calls += 1
        return True


class _FakeServices:
    def async_register(self, *args, **kwargs) -> None:
        return None


class _FakeHass:
    def __init__(self) -> None:
        self.data = {}
        self.config_entries = _FakeConfigEntries()
        self.services = _FakeServices()
        self.bus = types.SimpleNamespace(async_fire=lambda *args, **kwargs: None)


class _FakeEntry:
    def __init__(self, *, entry_id: str) -> None:
        self.entry_id = entry_id
        self.data: dict[str, str] = {}

    def async_create_background_task(self, hass, coro, name):
        return asyncio.create_task(coro, name=name)


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_integration_module():
    pkg_root = ROOT / "custom_components" / "comelit"
    package_name = f"optionf_pr1a_integration_{uuid4().hex}"
    package = _install_module(package_name)
    package.__path__ = [str(pkg_root)]
    restored: dict[str, object | None] = {}
    module_names = (
        "aiohttp",
        "voluptuous",
        "homeassistant.components.http",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.typing",
        f"{package_name}.attached_media",
        f"{package_name}.client",
        f"{package_name}.media_session",
        f"{package_name}.miniapp",
        f"{package_name}.media_transport",
        f"{package_name}.oauth",
        f"{package_name}.ring_media",
        f"{package_name}.runtime",
        f"{package_name}.supervisor",
    )
    for name in module_names:
        restored[name] = sys.modules.get(name)

    _install_module("aiohttp", ClientSession=object)
    _install_module(
        "voluptuous",
        In=lambda value: value,
        Optional=lambda value: value,
        Required=lambda value: value,
        Schema=lambda value: value,
    )
    _install_module(
        "homeassistant.components.http",
        StaticPathConfig=lambda *args, **kwargs: (args, kwargs),
    )
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module(
        "homeassistant.core",
        HomeAssistant=object,
        ServiceCall=object,
        SupportsResponse=types.SimpleNamespace(OPTIONAL="optional"),
    )
    _install_module("homeassistant.exceptions", HomeAssistantError=Exception)
    _install_module(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda hass: None,
    )
    _install_module("homeassistant.helpers.typing", ConfigType=dict)
    _install_module(
        f"{package_name}.attached_media",
        ComelitAttachedRingMediaSession=_FakeAttachedSession,
        ComelitAttachedRingMediaTransport=_FakeAttachedTransport,
    )
    _install_module(f"{package_name}.client", ComelitBridgeClient=object)
    _install_module(
        f"{package_name}.media_session",
        ComelitMediaSessionManager=_FakeMediaSession,
    )
    _install_module(
        f"{package_name}.miniapp",
        ComelitMiniAppController=object,
        async_register_miniapp_views=lambda *args, **kwargs: None,
    )
    _install_module(
        f"{package_name}.media_transport",
        ComelitEntranceMediaTransport=_FakeMediaTransport,
    )
    _install_module(f"{package_name}.oauth", ComelitOAuthManager=_FakeOAuth)
    _install_module(
        f"{package_name}.ring_media",
        HAStreamMediaProvider=_FakeProvider,
        RingMediaCoordinator=_FakeRingMedia,
    )
    _install_module(f"{package_name}.runtime", ComelitRingRuntime=_FakeRuntime)
    _install_module(
        f"{package_name}.supervisor",
        ComelitRuntimeSupervisor=_FakeSupervisor,
    )

    spec = importlib.util.spec_from_file_location(
        package_name,
        pkg_root / "__init__.py",
        submodule_search_locations=[str(pkg_root)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in restored.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _fake_hass_and_entry(mod):
    hass = _FakeHass()
    entry = _FakeEntry(entry_id="entry-shadow")
    entry.data = {
        mod.CONF_DEVICE_UUID: "device",
        mod.CONF_VIP_TOKEN: "vip",
        mod.CONF_OAUTH_ACCESS_TOKEN: "access",
    }
    entry.async_create_background_task = (
        lambda hass, coro, name: asyncio.create_task(coro, name=name)
    )
    return hass, entry


def _patch_integration_runtime(monkeypatch, mod) -> None:
    monkeypatch.setattr(mod, "ComelitOAuthManager", _FakeOAuth)
    monkeypatch.setattr(mod, "ComelitRingRuntime", _FakeRuntime)
    monkeypatch.setattr(mod, "ComelitRuntimeSupervisor", _FakeSupervisor)
    monkeypatch.setattr(mod, "ComelitEntranceMediaTransport", _FakeMediaTransport)
    monkeypatch.setattr(mod, "ComelitMediaSessionManager", _FakeMediaSession)
    monkeypatch.setattr(mod, "ComelitAttachedRingMediaTransport", _FakeAttachedTransport)
    monkeypatch.setattr(mod, "ComelitAttachedRingMediaSession", _FakeAttachedSession)
    monkeypatch.setattr(mod, "HAStreamMediaProvider", _FakeProvider)
    monkeypatch.setattr(mod, "RingMediaCoordinator", _FakeRingMedia)
    monkeypatch.setattr(
        mod,
        "_register_attached_media_providers",
        lambda *args: (_FakeProvider(), _FakeProvider()),
    )


def test_shadow_init_exception_integration_setup_unaffected(monkeypatch):
    mod = _load_integration_module()
    _patch_integration_runtime(monkeypatch, mod)

    def broken_init(self):
        raise RuntimeError("init failed")

    monkeypatch.setattr(mod.ring_shadow.RingShadowController, "__init__", broken_init)
    hass, entry = _fake_hass_and_entry(mod)

    assert asyncio.run(mod.async_setup_entry(hass, entry)) is True
    domain_data = hass.data[mod.DOMAIN]
    assert domain_data["ring_shadow_controllers"][entry.entry_id] is None
    assert isinstance(domain_data[mod.DATA_RUNTIMES][entry.entry_id], _FakeRuntime)
    assert isinstance(domain_data[mod.DATA_SUPERVISORS][entry.entry_id], _FakeSupervisor)
    assert isinstance(
        domain_data[mod.DATA_MEDIA_TRANSPORTS][entry.entry_id],
        _FakeMediaTransport,
    )
    assert isinstance(domain_data[mod.DATA_MEDIA_SESSIONS][entry.entry_id], _FakeMediaSession)


def test_shadow_unload_exception_unload_unaffected(monkeypatch):
    mod = _load_integration_module()
    _patch_integration_runtime(monkeypatch, mod)
    hass, entry = _fake_hass_and_entry(mod)
    assert asyncio.run(mod.async_setup_entry(hass, entry)) is True
    controller = hass.data[mod.DOMAIN]["ring_shadow_controllers"][entry.entry_id]
    assert controller is not None

    def broken_note_state(owner, state):
        raise RuntimeError("unload shadow failed")

    monkeypatch.setattr(controller, "note_state", broken_note_state)
    assert asyncio.run(mod.async_unload_entry(hass, entry)) is True
    assert mod.DATA_RUNTIMES not in hass.data.get(mod.DOMAIN, {})


def test_shadow_snapshot_accessor_returns_sanitized_view_or_none(monkeypatch):
    mod = _load_integration_module()
    _patch_integration_runtime(monkeypatch, mod)
    hass, entry = _fake_hass_and_entry(mod)
    assert asyncio.run(mod.async_setup_entry(hass, entry)) is True
    controller = hass.data[mod.DOMAIN]["ring_shadow_controllers"][entry.entry_id]
    assert controller is not None

    controller.note_state(mod.ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ):
        controller.observe_native_line(mod.ring_shadow.SHADOW_OWNER_LISTENER, line)

    view = mod.shadow_snapshot(hass, entry.entry_id)
    assert view is not None
    rendered = repr(view)
    assert "00000643" not in rendered
    assert "V4_RING_SOURCE" not in rendered
    assert view["live_state"]["door_kind"] == ("entrance",)
    assert mod.shadow_snapshot(hass, "missing-entry") is None


class _SupervisorRuntime:
    def __init__(self) -> None:
        self.running = False
        self.listener_ready = False
        self.attached_media_busy = False
        self.start_calls = 0
        self.stop_calls = 0

    async def async_start(self) -> None:
        self.start_calls += 1
        self.running = True
        self.listener_ready = True

    async def async_stop(self) -> None:
        self.stop_calls += 1
        self.running = False
        self.listener_ready = False

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": None,
        }


class _SupervisorEntry:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []

    def async_create_background_task(self, hass, coro, name):
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task


async def _exercise_supervisor(supervisor_mod, controller):
    runtime = _SupervisorRuntime()
    entry = _SupervisorEntry()
    supervisor = supervisor_mod.ComelitRuntimeSupervisor(
        object(),
        runtime,
        entry=entry,
        ring_shadow=controller,
    )
    await supervisor.async_start()
    await supervisor.async_pause_for_media()
    await supervisor.async_resume_after_media()
    await supervisor.async_stop()
    return {
        "media_paused": supervisor.media_paused,
        "state": supervisor.state,
        "reconnect_count": supervisor.reconnect_count,
        "runtime_start_calls": runtime.start_calls,
        "runtime_stop_calls": runtime.stop_calls,
    }


def test_shadow_supervisor_hook_exception_supervisor_unchanged():
    supervisor_mod = _load_component_module(str(ROOT), "supervisor")
    broken = _BrokenController()
    baseline = asyncio.run(_exercise_supervisor(supervisor_mod, None))
    with_broken_shadow = asyncio.run(_exercise_supervisor(supervisor_mod, broken))

    assert with_broken_shadow == baseline
    assert broken.calls >= 3


class _MediaListener:
    def __init__(self) -> None:
        self.media_paused = False
        self.pause_calls = 0
        self.resume_calls = 0
        self.attached_media_busy = False

    async def async_pause_for_media(self) -> None:
        self.pause_calls += 1
        self.media_paused = True

    async def async_resume_after_media(self) -> None:
        self.resume_calls += 1
        self.media_paused = False


class _MediaTransport:
    def __init__(self) -> None:
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0

    async def async_start(self, panel: str) -> None:
        self.start_calls += 1
        self.active = True

    async def async_stop(self) -> None:
        self.stop_calls += 1
        self.active = False


async def _exercise_media_session(media_session_mod, controller):
    listener = _MediaListener()
    transport = _MediaTransport()
    tasks: list[asyncio.Task[None]] = []

    def task_factory(coro, name):
        task = asyncio.create_task(coro, name=name)
        tasks.append(task)
        return task

    manager = media_session_mod.ComelitMediaSessionManager(
        listener,
        transport,
        hard_limit_seconds=30,
        transport_watch_interval_seconds=30,
        task_factory=task_factory,
        ring_shadow=controller,
    )
    await manager.async_acquire(panel="entrance", reason="camera_view")
    active_status = manager.status()
    await manager.async_release(reason="camera_view")
    inactive_status = manager.status()
    for task in tasks:
        if not task.done():
            task.cancel()
    return {
        "active_phase": active_status["phase"],
        "inactive_phase": inactive_status["phase"],
        "listener_paused": inactive_status["listener_paused"],
        "pause_calls": listener.pause_calls,
        "resume_calls": listener.resume_calls,
        "transport_start_calls": transport.start_calls,
        "transport_stop_calls": transport.stop_calls,
    }


def test_shadow_media_hook_exception_media_unchanged():
    media_session_mod = _load_component_module(str(ROOT), "media_session")
    broken = _BrokenController()
    baseline = asyncio.run(_exercise_media_session(media_session_mod, None))
    with_broken_shadow = asyncio.run(_exercise_media_session(media_session_mod, broken))

    assert with_broken_shadow == baseline
    assert broken.calls == 2


def test_shadow_hook_latches_after_bounded_failures():
    controller = _BrokenController()
    hook = ring_shadow.RingShadowHook(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT + 2):
        hook.observe_line("V4_RING_OBSERVED=true")

    assert hook.latched is True
    assert controller.calls == ring_shadow.SHADOW_FAILURE_LATCH_LIMIT
