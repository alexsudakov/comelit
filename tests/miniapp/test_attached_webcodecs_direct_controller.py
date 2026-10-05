from __future__ import annotations

import asyncio
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest


_HELPER_PATH = Path(__file__).with_name("test_controller_runtime.py")
_HELPER_NAME = "comelit_test_controller_runtime_shared"
_spec = importlib.util.spec_from_file_location(_HELPER_NAME, _HELPER_PATH)
assert _spec is not None and _spec.loader is not None
base = importlib.util.module_from_spec(_spec)
sys.modules[_HELPER_NAME] = base
_spec.loader.exec_module(base)


def _fixed_controller():
    old_controller, hass = base._controller(surveillance_label="Outside")
    base._attached_media_mod()
    module = importlib.import_module(
        "custom_components.comelit.miniapp.attached_controller"
    )
    controller = module.ComelitMiniAppController(hass, base.PKG_ROOT / "frontend")
    controller.set_entry(old_controller._entry)
    return controller, hass, module


def test_direct_attached_webcodecs_does_not_start_ha_stream_before_pyav_consumer():
    controller, hass, _module = _fixed_controller()
    coordinator = base._install_attached_ring_coordinator(hass)
    transport = coordinator.attached_transport
    provider = coordinator.attached_provider
    events = transport.events

    async def run():
        await coordinator.attached_session.async_acquire(
            panel="entrance",
            reason="camera_view",
        )

        activation_started = asyncio.Event()
        pyav_bound = asyncio.Event()

        async def gated_activation():
            events.append("activation_waiting_for_pyav")
            activation_started.set()
            await pyav_bound.wait()
            events.append("activate_miniapp_output")
            transport.activate_miniapp_output_calls += 1
            transport.miniapp_sink_active = True

        transport.async_activate_miniapp_output = gated_activation
        target = controller.get_webcodecs_camera_target("camera.comelit_entrance")
        lease = await controller.acquire_attached_webcodecs_entrance(target)

        await asyncio.wait_for(activation_started.wait(), timeout=1)
        assert lease.local_sdp_path == Path("/run/comelit-attached/miniapp.sdp")
        assert controller._miniapp_attached_resource is None
        assert provider.consumers == {}
        assert events == ["activation_waiting_for_pyav"]
        assert coordinator.attached_session.status()["leases"] == {
            "camera_view": 1,
            "miniapp_attached_view": 1,
        }

        # Model PyAV binding UDP 18099. Only then may output activation finish.
        pyav_bound.set()
        await lease.wait_activation()
        assert events == [
            "activation_waiting_for_pyav",
            "activate_miniapp_output",
        ]

        await lease.release()
        assert coordinator.attached_session.status()["leases"] == {
            "camera_view": 1
        }
        assert transport.deactivate_miniapp_output_calls == 1
        assert provider.consumers == {}
        assert provider.release_calls == []

        await coordinator.attached_session.async_release(reason="camera_view")

    asyncio.run(run())


def test_direct_attached_webcodecs_fails_closed_before_activation_when_sdp_not_ready():
    controller, hass, module = _fixed_controller()
    coordinator = base._install_attached_ring_coordinator(hass)
    transport = coordinator.attached_transport

    async def run():
        await coordinator.attached_session.async_acquire(
            panel="entrance",
            reason="camera_view",
        )
        # Starting the attached session marks both SDP files ready; model the
        # failure after that transition, immediately before WebCodecs acquire.
        transport.miniapp_local_sdp_ready = False
        target = controller.get_webcodecs_camera_target("camera.comelit_entrance")
        with pytest.raises(
            module.MiniAppOperationError,
            match="attached_webcodecs_bootstrap_not_ready",
        ):
            await controller.acquire_attached_webcodecs_entrance(target)
        assert coordinator.attached_session.status()["leases"] == {
            "camera_view": 1
        }
        assert transport.activate_miniapp_output_calls == 0
        assert coordinator.attached_provider.consumers == {}
        await coordinator.attached_session.async_release(reason="camera_view")

    asyncio.run(run())


def test_direct_attached_webcodecs_release_cancels_pending_activation_without_leak():
    controller, hass, _module = _fixed_controller()
    coordinator = base._install_attached_ring_coordinator(hass)
    transport = coordinator.attached_transport

    async def run():
        await coordinator.attached_session.async_acquire(
            panel="entrance",
            reason="camera_view",
        )
        activation_started = asyncio.Event()
        never_ready = asyncio.Event()

        async def pending_activation():
            activation_started.set()
            await never_ready.wait()

        transport.async_activate_miniapp_output = pending_activation
        target = controller.get_webcodecs_camera_target("camera.comelit_entrance")
        lease = await controller.acquire_attached_webcodecs_entrance(target)
        await asyncio.wait_for(activation_started.wait(), timeout=1)
        assert not lease.activation_task.done()

        await lease.release()
        assert lease.activation_task.cancelled()
        assert coordinator.attached_session.status()["leases"] == {
            "camera_view": 1
        }
        assert transport.deactivate_miniapp_output_calls == 1
        assert coordinator.attached_provider.consumers == {}
        await coordinator.attached_session.async_release(reason="camera_view")

    asyncio.run(run())


def test_hls_attached_viewer_keeps_existing_ha_stream_resource_path():
    controller, hass, _module = _fixed_controller()
    coordinator = base._install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run():
        await controller.async_attached_viewer_event(
            token,
            session,
            action="open",
            viewer_id="viewer_hls_direct1",
        )
        assert controller._miniapp_attached_resource is not None
        assert coordinator.attached_provider.consumers == {
            "miniapp_attached_view": 1
        }
        assert coordinator.attached_provider.events == [
            "add_provider",
            "start",
            "activate_miniapp_output",
        ]
        await controller.async_attached_viewer_event(
            token,
            session,
            action="close",
            viewer_id="viewer_hls_direct1",
        )

    asyncio.run(run())


def test_public_miniapp_controller_exports_direct_attached_variant():
    source = (base.MINIAPP_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "from .attached_controller import ComelitMiniAppController" in source
