from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import struct
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
WEBCODECS_MAX_SESSION_SECONDS = 120
WEBCODECS_MAX_SESSIONS = 4

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


class H264AccessUnitSource:
    """Closeable copy-only H.264 packet source."""

    def __init__(
        self,
        container: Any,
        iterator: Any,
        *,
        sps: list[bytes],
        pps: list[bytes],
        codec: str | None,
    ) -> None:
        self._container = container
        self._iterator = iterator
        self._sps = sps
        self._pps = pps
        self._codec = codec
        self._closed = False
        self._first_unit_ns: int | None = None

    @classmethod
    async def open(cls, source: str) -> "H264AccessUnitSource":
        try:
            import av
        except ImportError as exc:
            raise WebCodecsSourceError("source_dependency_missing") from exc

        def _open_container():
            return av.open(
                source,
                mode="r",
                format="rtsp",
                options={"rtsp_transport": "tcp"},
                timeout=5.0,
            )

        try:
            container = await asyncio.to_thread(_open_container)
        except Exception as exc:
            raise WebCodecsSourceError("source_open_failed") from exc

        try:
            video_stream = next(
                (
                    stream
                    for stream in container.streams
                    if getattr(stream, "type", None) == "video"
                    and getattr(stream.codec_context, "name", "").lower() == "h264"
                ),
                None,
            )
            if video_stream is None:
                raise WebCodecsSourceError("source_not_h264_rtsp")

            extradata = getattr(video_stream.codec_context, "extradata", None)
            sps, pps = avcc_extradata_to_annexb_nals(extradata)
            codec = derive_avc1_codec_from_sps(sps[0] if sps else None)
            return cls(
                container,
                container.demux(video_stream),
                sps=sps,
                pps=pps,
                codec=codec,
            )
        except Exception:
            container.close()
            raise

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
        packet = await asyncio.to_thread(lambda: next(self._iterator, None))
        if packet is None:
            raise StopAsyncIteration
        raw = bytes(packet)
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
        keyframe = bool(getattr(packet, "is_keyframe", False)) or has_idr(annexb)
        if keyframe:
            annexb = prepend_parameter_sets(annexb, self._sps, self._pps)
        return H264AccessUnit(
            payload=annexb,
            keyframe=keyframe,
            media_pts_us=packet_pts_us(packet),
            codec=self._codec,
            source_elapsed_us=source_elapsed_us,
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._container.close()


async def open_h264_access_unit_source(source: str) -> H264AccessUnitSource:
    return await H264AccessUnitSource.open(source)


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
        "source_open",
        "first_source_packet",
        "first_binary",
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
