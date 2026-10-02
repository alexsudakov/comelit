from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import logging
import queue
import struct
import threading
import time
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit


WEBCODECS_PROTOCOL_VERSION = 2
WEBCODECS_FLAG_KEY = 0x01
WEBCODECS_FLAG_DELTA = 0x02
WEBCODECS_FLAG_PTS_VALID = 0x04
WEBCODECS_HEADER_BYTES = 36
WEBCODECS_MAX_COMMAND_BYTES = 256
WEBCODECS_MAX_UNIT_BYTES = 1024 * 1024
WEBCODECS_MAX_QUEUE_UNITS = 48
WEBCODECS_MAX_QUEUE_BYTES = 3 * 1024 * 1024
WEBCODECS_MAX_SESSION_SECONDS = 600
WEBCODECS_ENTRANCE_MAX_SESSION_SECONDS = 600
WEBCODECS_MAX_SESSIONS = 4
WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT = 6.0

_LOGGER = logging.getLogger(__name__)

_START4 = b"\x00\x00\x00\x01"
_START3 = b"\x00\x00\x01"
_ZERO2 = b"\x00\x00"


class WebCodecsProtocolError(ValueError):
    """A bounded WebCodecs protocol validation failure."""


class WebCodecsSourceError(Exception):
    """A bounded WebCodecs H.264 source failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class WebCodecsFrame:
    sequence: int
    media_pts_us: int
    pts_valid: bool
    keyframe: bool
    payload: bytes
    source_elapsed_us: int = 0
    send_elapsed_us: int = 0


@dataclass(frozen=True, slots=True)
class H264AccessUnit:
    payload: bytes
    keyframe: bool
    media_pts_us: int | None
    codec: str | None = None
    source_elapsed_us: int = 0


@dataclass(frozen=True, slots=True)
class _H264PacketSnapshot:
    raw: bytes
    keyframe: bool
    media_pts_us: int | None


@dataclass(slots=True)
class _SessionLease:
    registry: "WebCodecsSessionRegistry"
    entity_id: str
    released: bool = False

    async def __aenter__(self) -> "_SessionLease":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.release()

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        await self.registry.release(self.entity_id)


class WebCodecsSessionRegistry:
    """Bound active experimental WebCodecs sessions."""

    def __init__(self, max_sessions: int = WEBCODECS_MAX_SESSIONS) -> None:
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()
        self._entities: set[str] = set()

    async def acquire(self, entity_id: str) -> _SessionLease:
        async with self._lock:
            if entity_id in self._entities or len(self._entities) >= self._max_sessions:
                raise WebCodecsSourceError("session_limit")
            self._entities.add(entity_id)
        return _SessionLease(self, entity_id)

    async def release(self, entity_id: str) -> None:
        async with self._lock:
            self._entities.discard(entity_id)

    def active_count(self) -> int:
        return len(self._entities)


SESSION_REGISTRY = WebCodecsSessionRegistry()


def is_rtsp_source(source: object) -> bool:
    if not isinstance(source, str):
        return False
    scheme = urlsplit(source).scheme.lower()
    return scheme in {"rtsp", "rtsps"}


def validate_webcodecs_command(data: str) -> bool:
    if len(data.encode("utf-8", "ignore")) > WEBCODECS_MAX_COMMAND_BYTES:
        return False
    try:
        import json

        payload = json.loads(data)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and set(payload) == {"type", "value"}
        and payload.get("type") == "webcodecs"
        and payload.get("value") == "h264"
    )


def encode_webcodecs_frame(frame: WebCodecsFrame) -> bytes:
    if frame.sequence < 1 or frame.sequence > 0xFFFFFFFF:
        raise WebCodecsProtocolError("invalid_sequence")
    for value in (frame.source_elapsed_us, frame.send_elapsed_us):
        if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
            raise WebCodecsProtocolError("invalid_elapsed")
    if len(frame.payload) > WEBCODECS_MAX_UNIT_BYTES:
        raise WebCodecsProtocolError("unit_too_large")
    flags = WEBCODECS_FLAG_KEY if frame.keyframe else WEBCODECS_FLAG_DELTA
    if frame.pts_valid:
        flags |= WEBCODECS_FLAG_PTS_VALID
    return (
        struct.pack(
            ">BBHIQQQI",
            WEBCODECS_PROTOCOL_VERSION,
            flags,
            0,
            frame.sequence,
            frame.media_pts_us if frame.pts_valid else 0,
            frame.source_elapsed_us,
            frame.send_elapsed_us,
            len(frame.payload),
        )
        + frame.payload
    )


def decode_webcodecs_frame(data: bytes) -> WebCodecsFrame:
    if len(data) < WEBCODECS_HEADER_BYTES:
        raise WebCodecsProtocolError("truncated_header")
    (
        version,
        flags,
        reserved,
        sequence,
        pts_us,
        source_elapsed_us,
        send_elapsed_us,
        payload_length,
    ) = struct.unpack(
        ">BBHIQQQI",
        data[:WEBCODECS_HEADER_BYTES],
    )
    if version != WEBCODECS_PROTOCOL_VERSION:
        raise WebCodecsProtocolError("wrong_version")
    if reserved != 0:
        raise WebCodecsProtocolError("reserved_not_zero")
    if bool(flags & WEBCODECS_FLAG_KEY) == bool(flags & WEBCODECS_FLAG_DELTA):
        raise WebCodecsProtocolError("invalid_frame_type")
    if flags & ~(WEBCODECS_FLAG_KEY | WEBCODECS_FLAG_DELTA | WEBCODECS_FLAG_PTS_VALID):
        raise WebCodecsProtocolError("invalid_flags")
    if payload_length > WEBCODECS_MAX_UNIT_BYTES:
        raise WebCodecsProtocolError("unit_too_large")
    payload = data[WEBCODECS_HEADER_BYTES:]
    if len(payload) != payload_length:
        raise WebCodecsProtocolError("payload_length_mismatch")
    return WebCodecsFrame(
        sequence=sequence,
        media_pts_us=pts_us,
        pts_valid=bool(flags & WEBCODECS_FLAG_PTS_VALID),
        keyframe=bool(flags & WEBCODECS_FLAG_KEY),
        payload=payload,
        source_elapsed_us=source_elapsed_us,
        send_elapsed_us=send_elapsed_us,
    )


def _annexb_nals(data: bytes) -> list[bytes]:
    indexes: list[tuple[int, int]] = []
    pos = 0
    limit = len(data)
    while pos < limit - 3:
        if data.startswith(_START4, pos):
            indexes.append((pos, 4))
            pos += 4
            continue
        if data.startswith(_START3, pos):
            indexes.append((pos, 3))
            pos += 3
            continue
        pos += 1
    result: list[bytes] = []
    for index, (start, prefix_len) in enumerate(indexes):
        nal_start = start + prefix_len
        nal_end = indexes[index + 1][0] if index + 1 < len(indexes) else len(data)
        nal = data[nal_start:nal_end]
        while nal.startswith(b"\x00"):
            nal = nal[1:]
        if nal:
            result.append(nal)
    return result


def _avcc_nals(data: bytes) -> list[bytes]:
    result: list[bytes] = []
    offset = 0
    while offset + 4 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        if size <= 0 or offset + size > len(data):
            raise WebCodecsProtocolError("invalid_avcc")
        result.append(data[offset : offset + size])
        offset += size
    if offset != len(data) or not result:
        raise WebCodecsProtocolError("invalid_avcc")
    return result


def avcc_extradata_to_annexb_nals(extradata: bytes | None) -> tuple[list[bytes], list[bytes]]:
    if not extradata:
        return [], []
    if extradata.startswith(_START4) or extradata.startswith(_START3):
        return split_sps_pps(annexb_normalize(extradata))
    if len(extradata) < 7 or extradata[0] != 1:
        return [], []
    offset = 5
    sps_count = extradata[offset] & 0x1F
    offset += 1
    sps: list[bytes] = []
    for _ in range(sps_count):
        if offset + 2 > len(extradata):
            return [], []
        size = int.from_bytes(extradata[offset : offset + 2], "big")
        offset += 2
        if size <= 0 or offset + size > len(extradata):
            return [], []
        sps.append(extradata[offset : offset + size])
        offset += size
    if offset >= len(extradata):
        return sps, []
    pps_count = extradata[offset]
    offset += 1
    pps: list[bytes] = []
    for _ in range(pps_count):
        if offset + 2 > len(extradata):
            return sps, []
        size = int.from_bytes(extradata[offset : offset + 2], "big")
        offset += 2
        if size <= 0 or offset + size > len(extradata):
            return sps, []
        pps.append(extradata[offset : offset + size])
        offset += size
    return sps, pps


def annexb_normalize(data: bytes) -> bytes:
    if data.startswith(_START4) or data.startswith(_START3):
        nals = _annexb_nals(data)
    else:
        nals = _avcc_nals(data)
    return b"".join(_START4 + nal for nal in nals)


def split_sps_pps(annexb: bytes) -> tuple[list[bytes], list[bytes]]:
    sps: list[bytes] = []
    pps: list[bytes] = []
    for nal in _annexb_nals(annexb):
        nal_type = nal[0] & 0x1F
        if nal_type == 7:
            sps.append(nal)
        elif nal_type == 8:
            pps.append(nal)
    return sps, pps


def has_idr(annexb: bytes) -> bool:
    return any((nal[0] & 0x1F) == 5 for nal in _annexb_nals(annexb))


def prepend_parameter_sets(annexb: bytes, sps: list[bytes], pps: list[bytes]) -> bytes:
    if not has_idr(annexb):
        return annexb
    present_sps, present_pps = split_sps_pps(annexb)
    prefix: list[bytes] = []
    if not present_sps:
        prefix.extend(sps)
    if not present_pps:
        prefix.extend(pps)
    if not prefix:
        return annexb
    return b"".join(_START4 + nal for nal in prefix) + annexb


def derive_avc1_codec_from_sps(sps: bytes | None) -> str | None:
    if not sps:
        return None
    nals = _annexb_nals(sps) if sps.startswith((_START4, _START3)) else [sps]
    for nal in nals:
        if len(nal) >= 4 and (nal[0] & 0x1F) == 7:
            return f"avc1.{nal[1]:02X}{nal[2]:02X}{nal[3]:02X}"
    return None


def packet_pts_us(packet: Any) -> int | None:
    pts = getattr(packet, "pts", None)
    time_base = getattr(packet, "time_base", None)
    if pts is None or time_base is None:
        return None
    try:
        return max(0, round(float(pts * time_base) * 1_000_000))
    except (TypeError, ValueError, OverflowError):
        return None


class _LoopFutureBridge:
    """Resolve one event-loop Future from the PyAV owner thread."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.future = loop.create_future()

    def set_result(self, result: Any) -> None:
        self._resolve(lambda: self.future.set_result(result))

    def set_exception(self, exc: BaseException) -> None:
        def apply_exception() -> None:
            self.future.add_done_callback(_retrieve_late_exception)
            self.future.set_exception(exc)

        self._resolve(apply_exception)

    def _resolve(self, apply: Any) -> None:
        def resolve() -> None:
            if not self.future.done():
                apply()

        try:
            self._loop.call_soon_threadsafe(resolve)
        except RuntimeError:
            return


def _retrieve_late_exception(future: asyncio.Future[Any]) -> None:
    """Mark late exceptions as retrieved without changing await delivery."""
    if not future.cancelled():
        future.exception()


async def _await_owner_future(future: asyncio.Future[Any]) -> Any:
    return await asyncio.shield(future)


def _source_open_failed(exc: BaseException) -> WebCodecsSourceError:
    error = WebCodecsSourceError("source_open_failed")
    error.__cause__ = exc
    return error


class _H264PyAVOwner:
    """Single-thread owner for one PyAV InputContainer lifecycle."""

    def __init__(
        self,
        source: str,
        *,
        input_format: str,
        options: dict[str, str],
        missing_h264_code: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._source = source
        self._input_format = input_format
        self._options = options
        self._missing_h264_code = missing_h264_code
        self._loop = loop
        self._commands: queue.Queue[tuple[str, _LoopFutureBridge]] = queue.Queue()
        self._ready = _LoopFutureBridge(loop)
        self._close_future: _LoopFutureBridge | None = None
        self._state_lock = threading.Lock()
        self._terminated = False
        self._closing = False
        self._terminal_exception: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="comelit-webcodecs-pyav",
            daemon=True,
        )
        self._thread.start()

    @property
    def ready(self) -> asyncio.Future[tuple[list[bytes], list[bytes], str | None]]:
        return self._ready.future

    def next_packet(self) -> asyncio.Future[_H264PacketSnapshot | None]:
        future = _LoopFutureBridge(self._loop)
        with self._state_lock:
            if self._terminated or self._closing or not self._thread.is_alive():
                if self._terminal_exception is None:
                    future.set_result(None)
                else:
                    future.set_exception(_source_open_failed(self._terminal_exception))
                return future.future
            self._commands.put(("next", future))
        return future.future

    def close(self) -> asyncio.Future[None]:
        with self._state_lock:
            self._closing = True
            if self._close_future is None:
                self._close_future = _LoopFutureBridge(self._loop)
                if self._terminated or not self._thread.is_alive():
                    self._close_future.set_result(None)
                    return self._close_future.future
                self._commands.put(("close", self._close_future))
            return self._close_future.future

    def join(self, timeout: float) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self) -> None:
        container: Any | None = None
        iterator: Any | None = None
        closed = False
        current_future: _LoopFutureBridge | None = None
        terminal_exception: BaseException | None = None

        def close_container() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            if container is not None:
                container.close()

        try:
            try:
                import av
            except ImportError as exc:
                raise WebCodecsSourceError("source_dependency_missing") from exc

            try:
                container = av.open(
                    self._source,
                    mode="r",
                    format=self._input_format,
                    options=self._options,
                    timeout=5.0,
                )
            except Exception as exc:
                raise WebCodecsSourceError("source_open_failed") from exc

            try:
                video_stream = next(
                    (
                        stream
                        for stream in container.streams
                        if getattr(stream, "type", None) == "video"
                        and getattr(stream.codec_context, "name", "").lower()
                        == "h264"
                    ),
                    None,
                )
                if video_stream is None:
                    raise WebCodecsSourceError(self._missing_h264_code)

                extradata = getattr(video_stream.codec_context, "extradata", None)
                sps, pps = avcc_extradata_to_annexb_nals(extradata)
                codec = derive_avc1_codec_from_sps(sps[0] if sps else None)
                iterator = container.demux(video_stream)
                self._ready.set_result((sps, pps, codec))
            except Exception:
                close_container()
                raise

            while True:
                command = self._commands.get()
                kind, future = command
                current_future = future
                if kind == "close":
                    try:
                        close_container()
                    except Exception as exc:
                        future.set_exception(exc)
                    current_future = None
                    return
                if kind != "next":
                    current_future = None
                    continue
                try:
                    packet = next(iterator, None)
                    if packet is None:
                        future.set_result(None)
                        current_future = None
                        continue
                    future.set_result(
                        _H264PacketSnapshot(
                            raw=bytes(packet),
                            keyframe=bool(getattr(packet, "is_keyframe", False)),
                            media_pts_us=packet_pts_us(packet),
                        ),
                    )
                    current_future = None
                except Exception as exc:
                    future.set_exception(exc)
                    current_future = None
        except BaseException as exc:
            terminal_exception = exc
            self._ready.set_exception(exc)
        finally:
            if not closed and container is not None:
                try:
                    close_container()
                except BaseException as exc:
                    if terminal_exception is None:
                        terminal_exception = exc
                    _LOGGER.exception("Comelit Mini App WebCodecs PyAV close failed")
            pending_error = (
                _source_open_failed(terminal_exception)
                if terminal_exception is not None
                else WebCodecsSourceError("source_open_failed")
            )
            try:
                if current_future is not None:
                    current_future.set_exception(pending_error)
            except BaseException:
                _LOGGER.exception(
                    "Comelit Mini App WebCodecs PyAV pending command resolution failed"
                )
            with self._state_lock:
                self._terminated = True
                self._terminal_exception = terminal_exception
                close_future = self._close_future
            while True:
                try:
                    pending_kind, pending_future = self._commands.get_nowait()
                except queue.Empty:
                    break
                except BaseException:
                    _LOGGER.exception(
                        "Comelit Mini App WebCodecs PyAV command drain failed"
                    )
                    break
                try:
                    if pending_kind == "close":
                        pending_future.set_result(None)
                    else:
                        pending_future.set_exception(
                            WebCodecsSourceError("source_open_failed")
                        )
                except BaseException:
                    _LOGGER.exception(
                        "Comelit Mini App WebCodecs PyAV drained command resolution failed"
                    )
            if close_future is not None:
                try:
                    close_future.set_result(None)
                except BaseException:
                    _LOGGER.exception(
                        "Comelit Mini App WebCodecs PyAV close future resolution failed"
                    )


class H264AccessUnitSource:
    """Closeable copy-only H.264 packet source."""

    def __init__(
        self,
        owner: _H264PyAVOwner,
        *,
        sps: list[bytes],
        pps: list[bytes],
        codec: str | None,
    ) -> None:
        self._owner = owner
        self._sps = sps
        self._pps = pps
        self._codec = codec
        self._closed = False
        self._close_started = False
        self._first_unit_ns: int | None = None

    @classmethod
    async def _open(
        cls,
        source: str,
        *,
        input_format: str,
        options: dict[str, str],
        missing_h264_code: str,
    ) -> "H264AccessUnitSource":
        owner = _H264PyAVOwner(
            source,
            input_format=input_format,
            options=options,
            missing_h264_code=missing_h264_code,
            loop=asyncio.get_running_loop(),
        )
        try:
            sps, pps, codec = await _await_owner_future(owner.ready)
            return cls(
                owner,
                sps=sps,
                pps=pps,
                codec=codec,
            )
        except asyncio.CancelledError:
            await cls._close_owner(owner)
            raise
        except WebCodecsSourceError:
            owner.join(WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT)
            raise
        except Exception as exc:
            owner.join(WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT)
            raise WebCodecsSourceError("source_open_failed") from exc

    @classmethod
    async def open(cls, source: str) -> "H264AccessUnitSource":
        return await cls._open(
            source,
            input_format="rtsp",
            options={"rtsp_transport": "tcp"},
            missing_h264_code="source_not_h264_rtsp",
        )

    @classmethod
    async def open_sdp(cls, source: str) -> "H264AccessUnitSource":
        return await cls._open(
            source,
            input_format="sdp",
            options={"protocol_whitelist": "file,udp,rtp"},
            missing_h264_code="source_not_h264_sdp",
        )

    async def __aenter__(self) -> "H264AccessUnitSource":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __aiter__(self) -> "H264AccessUnitSource":
        return self

    async def __anext__(self) -> H264AccessUnit:
        if self._closed:
            raise StopAsyncIteration
        packet = await _await_owner_future(self._owner.next_packet())
        if packet is None:
            raise StopAsyncIteration
        raw = packet.raw
        if not raw:
            return await self.__anext__()
        received_ns = time.monotonic_ns()
        if self._first_unit_ns is None:
            self._first_unit_ns = received_ns
        source_elapsed_us = max(0, (received_ns - self._first_unit_ns) // 1000)
        try:
            annexb = annexb_normalize(raw)
        except WebCodecsProtocolError as exc:
            raise WebCodecsSourceError("source_open_failed") from exc
        current_sps, current_pps = split_sps_pps(annexb)
        if current_sps:
            self._sps = current_sps
            self._codec = derive_avc1_codec_from_sps(self._sps[0])
        if current_pps:
            self._pps = current_pps
        keyframe = packet.keyframe or has_idr(annexb)
        if keyframe:
            annexb = prepend_parameter_sets(annexb, self._sps, self._pps)
        return H264AccessUnit(
            payload=annexb,
            keyframe=keyframe,
            media_pts_us=packet.media_pts_us,
            codec=self._codec,
            source_elapsed_us=source_elapsed_us,
        )

    @staticmethod
    async def _close_owner(owner: _H264PyAVOwner) -> None:
        close_future = owner.close()
        completed = False
        try:
            await asyncio.wait_for(
                _await_owner_future(close_future),
                timeout=WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT,
            )
            completed = True
        except TimeoutError:
            if owner.join(0):
                return
            _LOGGER.warning(
                "Comelit Mini App WebCodecs PyAV owner did not stop within %.1fs; "
                "close remains queued on owner thread",
                WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT,
            )
            return
        finally:
            timeout = WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT if completed else 0
            owner.join(timeout)

    async def aclose(self) -> None:
        if not self._close_started:
            self._close_started = True
            self._closed = True
        await self._close_owner(self._owner)


async def open_h264_access_unit_source(source: str) -> H264AccessUnitSource:
    return await H264AccessUnitSource.open(source)


async def open_h264_sdp_access_unit_source(source: str) -> H264AccessUnitSource:
    return await H264AccessUnitSource.open_sdp(source)


async def open_h264_access_units(source: str) -> AsyncIterator[H264AccessUnit]:
    unit_source = await open_h264_access_unit_source(source)
    try:
        async for unit in unit_source:
            yield unit
    finally:
        await unit_source.aclose()


def webcodecs_log_line(
    entity_id: str,
    event: str,
    *,
    elapsed_ms: int = 0,
    units: int = 0,
    bytes_sent: int = 0,
) -> str:
    allowed = {
        "session_open",
        "source_resolved",
        "intercom_media_ready",
        "source_open",
        "first_source_packet",
        "first_binary",
        "client_close",
        "unit_too_large",
        "backlog_exceeded",
        "session_limit",
        "source_eof",
        "session_close",
        "source_open_failed",
    }
    if event not in allowed:
        raise WebCodecsProtocolError("invalid_log_event")
    return (
        f"COMELIT_MINIAPP_WEBCODECS entity={entity_id} event={event} "
        f"elapsed_ms={int(elapsed_ms)} units={int(units)} bytes={int(bytes_sent)}"
    )


def webcodecs_summary_line(
    entity_id: str,
    *,
    units: int,
    keyframes: int,
    bytes_sent: int,
    errors: int,
    reason: str,
) -> str:
    allowed_reasons = {
        "client_close",
        "duration_limit",
        "source_eof",
        "source_open_failed",
        "backlog_exceeded",
        "session_limit",
        "intercom_media_busy",
        "intercom_media_start_failed",
        "intercom_media_unavailable",
        "cancelled",
    }
    if reason not in allowed_reasons:
        raise WebCodecsProtocolError("invalid_summary_reason")
    return (
        f"COMELIT_MINIAPP_WEBCODECS_SUMMARY entity={entity_id} units={int(units)} "
        f"keyframes={int(keyframes)} bytes={int(bytes_sent)} errors={int(errors)} "
        f"reason={reason}"
    )


def monotonic_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
