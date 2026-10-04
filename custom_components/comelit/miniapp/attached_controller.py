from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from ..attached_media import ComelitAttachedMediaError
from .controller import (
    ComelitMiniAppController as _BaseComelitMiniAppController,
    MiniAppOperationError,
    MiniAppWebCodecsTarget,
    _MINIAPP_ATTACHED_VIEW_REASON,
)

_LOGGER = logging.getLogger(__name__)

_SAFE_ACTIVATION_REASONS = frozenset(
    {
        "miniapp_attached_consumer_not_ready",
        "attached_media_not_active",
    }
)


def _consume_activation_result(task: asyncio.Task[None]) -> None:
    """Retrieve background activation failures without leaking raw details."""
    if task.cancelled():
        return
    try:
        task.result()
    except ComelitAttachedMediaError as exc:
        reason = str(exc)
        if reason not in _SAFE_ACTIVATION_REASONS:
            reason = "attached_media_activation_failed"
        _LOGGER.info(
            "attached_webcodecs_output_activation_failed reason=%s",
            reason,
        )
    except Exception as exc:
        _LOGGER.warning(
            "attached_webcodecs_output_activation_failed type=%s",
            type(exc).__name__,
        )


@dataclass(slots=True)
class MiniAppAttachedWebCodecsEntranceLease:
    """Own one direct PyAV consumer of the attached Mini App RTP sink.

    Unlike the HLS attached-viewer resource, this lease deliberately does not
    create or start a Home Assistant Stream on the Mini App SDP.  The output
    activation task waits for PyAV to bind the UDP port, then the existing
    attached-media transport replays the cached SPS/PPS/IDR bootstrap and
    enables live RTP fan-out.
    """

    session: Any
    local_sdp_path: Path
    activation_task: asyncio.Task[None]
    released: bool = False

    async def wait_activation(self) -> None:
        """Wait until consumer readiness and RTP output activation complete."""
        await asyncio.shield(self.activation_task)

    async def release(self) -> None:
        if self.released:
            return
        self.released = True

        if not self.activation_task.done():
            self.activation_task.cancel()
        try:
            await self.activation_task
        except asyncio.CancelledError:
            pass
        except Exception:
            # The done callback already records only bounded/type-only evidence.
            pass

        try:
            await self.session.async_deactivate_miniapp_output()
        finally:
            await self.session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)


class ComelitMiniAppController(_BaseComelitMiniAppController):
    """Mini App controller with direct attached-WebCodecs UDP ownership.

    HLS keeps the existing ref-counted HA Stream resource.  Attached WebCodecs
    instead owns only the attached-session lease and reads the Mini App SDP
    directly with PyAV, so HA Stream and PyAV never bind UDP 18099 together.
    """

    async def attached_webcodecs_entrance_ready(self) -> bool:
        # A running HLS consumer already owns the Mini App UDP sink.  Do not
        # select direct WebCodecs until that resource has been released.
        if self._miniapp_attached_resource is not None:
            return False
        return await super().attached_webcodecs_entrance_ready()

    async def acquire_attached_webcodecs_entrance(
        self,
        target: MiniAppWebCodecsTarget,
    ) -> MiniAppAttachedWebCodecsEntranceLease:
        if target.kind != "entrance":
            raise MiniAppOperationError("invalid_webcodecs_target")

        async with self._attached_viewer_lock:
            if self._miniapp_attached_resource is not None:
                raise MiniAppOperationError("attached_webcodecs_session_limit")

            session, _provider = self._miniapp_attached_runtime()
            if not getattr(session, "active", False):
                raise MiniAppOperationError("attached_webcodecs_bootstrap_not_ready")

            lease_acquired = False
            try:
                await session.async_acquire(
                    panel="entrance",
                    reason=_MINIAPP_ATTACHED_VIEW_REASON,
                )
                lease_acquired = True

                # Read the already-generated Mini App SDP directly from the
                # attached transport.  Do not call provider.async_get_stream(),
                # Stream.add_provider(), or Stream.start(): those operations
                # would bind the same UDP port before PyAV and reproduce the
                # b4 source_open_failed collision.
                transport = getattr(session, "_transport", None)
                source_path = getattr(transport, "miniapp_local_sdp_path", None)
                source_ready = bool(
                    getattr(transport, "miniapp_local_sdp_ready", False)
                )
                if not source_ready or source_path is None:
                    raise MiniAppOperationError(
                        "attached_webcodecs_bootstrap_not_ready"
                    )

                path = Path(source_path)

                # Start activation concurrently.  The transport's existing
                # readiness gate waits until PyAV has bound UDP 18099 before it
                # replays bootstrap packets and enables live output.
                activation_task = self.hass.async_create_task(
                    session.async_activate_miniapp_output()
                )
                set_name = getattr(activation_task, "set_name", None)
                if callable(set_name):
                    set_name("Comelit attached WebCodecs output activation")
                activation_task.add_done_callback(_consume_activation_result)

                return MiniAppAttachedWebCodecsEntranceLease(
                    session=session,
                    local_sdp_path=path,
                    activation_task=activation_task,
                )
            except MiniAppOperationError:
                if lease_acquired:
                    await session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)
                raise
            except ComelitAttachedMediaError as exc:
                if lease_acquired:
                    await session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)
                code = str(exc)
                if code == "miniapp_attached_consumer_not_ready":
                    raise MiniAppOperationError(
                        "attached_webcodecs_bootstrap_not_ready"
                    ) from exc
                raise MiniAppOperationError("attached_webcodecs_source_failed") from exc
            except Exception as exc:
                if lease_acquired:
                    await session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)
                raise MiniAppOperationError("attached_webcodecs_source_failed") from exc
