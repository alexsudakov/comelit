from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import struct
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

RTP_VERSION = 2
H264_PAYLOAD_TYPE = 99
MAX_SAFE_COUNTER = (1 << 63) - 1
DEFAULT_BOOTSTRAP_MAX_PACKETS = 512
DEFAULT_BOOTSTRAP_MAX_BYTES = 1_000_000
DEFAULT_BOOTSTRAP_AU_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class RecoveryShimDiagnostics:
    running: bool
    input_packets: int
    output_packets: int
    eligible_nonidr_i_count: int
    injected_count: int
    existing_recovery_count: int
    idr_count: int
    unsupported_packet_count: int
    malformed_count: int
    last_error: str | None


@dataclass
class _RtpPacket:
    data: bytes
    header: bytes
    payload: bytes
    payload_offset: int
    payload_end: int
    payload_type: int
    marker: bool
    sequence: int
    timestamp: int
    ssrc: int
    padding: bool


@dataclass
class _AccessUnitState:
    timestamp: int
    seen_sps: bool = False
    seen_pps: bool = False
    seen_vcl: bool = False
    seen_idr: bool = False
    seen_recovery_point_sei: bool = False
    injected_recovery_point: bool = False
    unprovable_recovery_signal: bool = False


@dataclass
class _BootstrapAccessUnit:
    key: tuple[int, int]
    packets: list[bytes]
    packet_bytes: int
    has_idr: bool
    started_at: float
    first_sequence: int
    last_sequence: int


@dataclass
class _OutputSink:
    port: int | None
    transport: asyncio.DatagramTransport
    active: bool


@dataclass(frozen=True)
class H264BootstrapDiagnostics:
    has_sps: bool
    has_pps: bool
    has_complete_idr_au: bool
    snapshot_packet_count: int
    snapshot_total_bytes: int
    idr_au_packet_count: int
    idr_au_total_bytes: int
    idr_ssrc: int | None
    idr_timestamp: int | None
    first_sequence: int | None
    last_sequence: int | None
    completed_idr_age_ms: int | None


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._bit = 0

    def read_bit(self) -> int:
        if self._bit >= len(self._data) * 8:
            raise ValueError("bitstream_exhausted")
        value = (self._data[self._bit // 8] >> (7 - (self._bit % 8))) & 1
        self._bit += 1
        return value

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value

    def read_ue(self) -> int:
        zeros = 0
        while self.read_bit() == 0:
            zeros += 1
            if zeros > 31:
                raise ValueError("exp_golomb_too_large")
        suffix = self.read_bits(zeros) if zeros else 0
        return (1 << zeros) - 1 + suffix


class _BitWriter:
    def __init__(self) -> None:
        self._bits: list[int] = []

    def write_bit(self, value: int) -> None:
        self._bits.append(1 if value else 0)

    def write_bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.write_bit((value >> shift) & 1)

    def write_ue(self, value: int) -> None:
        code_num = value + 1
        bits = code_num.bit_length()
        for _ in range(bits - 1):
            self.write_bit(0)
        self.write_bits(code_num, bits)

    def rbsp_bytes(self) -> bytes:
        self.write_bit(1)
        while len(self._bits) % 8:
            self.write_bit(0)
        out = bytearray(len(self._bits) // 8)
        for idx, bit in enumerate(self._bits):
            out[idx // 8] |= bit << (7 - (idx % 8))
        return bytes(out)


def _inc(value: int) -> int:
    return min(value + 1, MAX_SAFE_COUNTER)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_log_info(message: str, *args: object) -> None:
    try:
        _LOGGER.info(message, *args)
    except Exception:
        return


def _remove_emulation_prevention(data: bytes) -> bytes:
    out = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte == 0x03:
            zeros = 0
            continue
        out.append(byte)
        if byte == 0:
            zeros += 1
        else:
            zeros = 0
    return bytes(out)


def _parse_slice_header(nal_payload_after_header: bytes) -> tuple[int, int] | None:
    try:
        reader = _BitReader(_remove_emulation_prevention(nal_payload_after_header))
        first_mb_in_slice = reader.read_ue()
        slice_type = reader.read_ue()
    except ValueError:
        return None
    return first_mb_in_slice, slice_type


def _sei_recovery_point_status(nal_payload_after_header: bytes) -> tuple[bool, bool]:
    rbsp = _remove_emulation_prevention(nal_payload_after_header)
    pos = 0
    while pos < len(rbsp):
        if rbsp[pos] == 0x80 and all(byte == 0 for byte in rbsp[pos + 1 :]):
            return False, False
        payload_type = 0
        while pos < len(rbsp) and rbsp[pos] == 0xFF:
            payload_type += 255
            pos += 1
        if pos >= len(rbsp):
            return False, True
        payload_type += rbsp[pos]
        pos += 1

        payload_size = 0
        while pos < len(rbsp) and rbsp[pos] == 0xFF:
            payload_size += 255
            pos += 1
        if pos >= len(rbsp):
            return False, True
        payload_size += rbsp[pos]
        pos += 1

        if payload_size > len(rbsp) - pos:
            return False, True
        payload = rbsp[pos : pos + payload_size]
        pos += payload_size
        if payload_type != 6:
            continue
        try:
            reader = _BitReader(payload)
            recovery_frame_cnt = reader.read_ue()
        except ValueError:
            return False, True
        return recovery_frame_cnt == 0, False
    return False, False


def build_recovery_point_sei_nal() -> bytes:
    payload = _BitWriter()
    payload.write_ue(0)
    payload.write_bit(0)
    payload.write_bit(0)
    payload.write_bits(0, 2)
    payload_bytes = payload.rbsp_bytes()

    rbsp = bytearray()
    rbsp.append(6)
    rbsp.append(len(payload_bytes))
    rbsp.extend(payload_bytes)
    rbsp.append(0x80)
    return b"\x06" + bytes(rbsp)


def _parse_rtp(packet: bytes) -> _RtpPacket | None:
    if len(packet) < 12:
        return None
    first = packet[0]
    if first >> 6 != RTP_VERSION:
        return None
    padding = bool(first & 0x20)
    extension = bool(first & 0x10)
    csrc_count = first & 0x0F
    payload_offset = 12 + csrc_count * 4
    if len(packet) < payload_offset:
        return None
    if extension:
        if len(packet) < payload_offset + 4:
            return None
        extension_words = struct.unpack_from("!H", packet, payload_offset + 2)[0]
        payload_offset += 4 + extension_words * 4
        if len(packet) < payload_offset:
            return None
    payload_end = len(packet)
    if padding:
        padding_len = packet[-1]
        if padding_len == 0 or padding_len > len(packet) - payload_offset:
            return None
        payload_end -= padding_len
    payload_type = packet[1] & 0x7F
    sequence = struct.unpack_from("!H", packet, 2)[0]
    timestamp = struct.unpack_from("!I", packet, 4)[0]
    ssrc = struct.unpack_from("!I", packet, 8)[0]
    return _RtpPacket(
        data=packet,
        header=packet[:payload_offset],
        payload=packet[payload_offset:payload_end],
        payload_offset=payload_offset,
        payload_end=payload_end,
        payload_type=payload_type,
        marker=bool(packet[1] & 0x80),
        sequence=sequence,
        timestamp=timestamp,
        ssrc=ssrc,
        padding=padding,
    )


def _replace_sequence(packet: bytes, sequence: int) -> bytes:
    out = bytearray(packet)
    struct.pack_into("!H", out, 2, sequence & 0xFFFF)
    return bytes(out)


def _make_injected_packet(template: _RtpPacket, sequence: int, payload: bytes) -> bytes:
    header = bytearray(template.header)
    header[0] &= 0xDF
    header[1] &= 0x7F
    struct.pack_into("!H", header, 2, sequence & 0xFFFF)
    return bytes(header) + payload


def _h264_payload_nal_types(payload: bytes) -> tuple[set[int], bool]:
    if not payload:
        return set(), False
    nal_type = payload[0] & 0x1F
    if 1 <= nal_type <= 23:
        return {nal_type}, True
    if nal_type == 24:
        pos = 1
        nal_types: set[int] = set()
        while pos < len(payload):
            if pos + 2 > len(payload):
                return nal_types, False
            nal_len = struct.unpack_from("!H", payload, pos)[0]
            pos += 2
            if nal_len == 0 or pos + nal_len > len(payload):
                return nal_types, False
            nal_types.add(payload[pos] & 0x1F)
            pos += nal_len
        return nal_types, True
    if nal_type == 28:
        if len(payload) < 2:
            return set(), False
        return {payload[1] & 0x1F}, True
    return {nal_type}, True


def _h264_payload_has_idr_start(payload: bytes) -> bool:
    if not payload:
        return False
    nal_type = payload[0] & 0x1F
    if nal_type == 5:
        return True
    if nal_type == 24:
        pos = 1
        while pos < len(payload):
            if pos + 2 > len(payload):
                return False
            nal_len = struct.unpack_from("!H", payload, pos)[0]
            pos += 2
            if nal_len == 0 or pos + nal_len > len(payload):
                return False
            if payload[pos] & 0x1F == 5:
                return True
            pos += nal_len
        return False
    if nal_type == 28 and len(payload) >= 2:
        return bool(payload[1] & 0x80) and payload[1] & 0x1F == 5
    return False


class _H264BootstrapCache:
    def __init__(
        self,
        *,
        max_packets: int = DEFAULT_BOOTSTRAP_MAX_PACKETS,
        max_bytes: int = DEFAULT_BOOTSTRAP_MAX_BYTES,
        au_timeout_seconds: float = DEFAULT_BOOTSTRAP_AU_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_packets = max(1, max_packets)
        self._max_bytes = max(1, max_bytes)
        self._au_timeout_seconds = max(0.001, au_timeout_seconds)
        self._clock = clock
        self._last_sps: bytes | None = None
        self._last_pps: bytes | None = None
        self._last_idr_au: tuple[bytes, ...] = ()
        self._last_idr_key: tuple[int, int] | None = None
        self._last_idr_first_sequence: int | None = None
        self._last_idr_last_sequence: int | None = None
        self._last_idr_completed_at: float | None = None
        self._open_units: dict[tuple[int, int], _BootstrapAccessUnit] = {}
        self._last_key_by_ssrc: dict[int, tuple[int, int]] = {}

    def snapshot(self) -> tuple[bytes, ...]:
        packets: list[bytes] = []
        seen: set[bytes] = set()
        for packet in (self._last_sps, self._last_pps, *self._last_idr_au):
            if packet is None or packet in seen:
                continue
            packets.append(packet)
            seen.add(packet)
        return tuple(packets)

    def _cached_packets(self) -> tuple[bytes, ...]:
        return self.snapshot()

    def diagnostics(self) -> H264BootstrapDiagnostics:
        packets = self.snapshot()
        now = self._clock()
        completed_age: int | None = None
        if self._last_idr_completed_at is not None:
            completed_age = max(0, int((now - self._last_idr_completed_at) * 1000))
        idr_ssrc = self._last_idr_key[0] if self._last_idr_key is not None else None
        idr_timestamp = (
            self._last_idr_key[1] if self._last_idr_key is not None else None
        )
        return H264BootstrapDiagnostics(
            has_sps=self._last_sps is not None,
            has_pps=self._last_pps is not None,
            has_complete_idr_au=bool(self._last_idr_au),
            snapshot_packet_count=len(packets),
            snapshot_total_bytes=sum(len(packet) for packet in packets),
            idr_au_packet_count=len(self._last_idr_au),
            idr_au_total_bytes=sum(len(packet) for packet in self._last_idr_au),
            idr_ssrc=idr_ssrc,
            idr_timestamp=idr_timestamp,
            first_sequence=self._last_idr_first_sequence,
            last_sequence=self._last_idr_last_sequence,
            completed_idr_age_ms=completed_age,
        )

    def _enforce_total_bounds(self) -> None:
        while True:
            packets = self._cached_packets()
            if (
                len(packets) <= self._max_packets
                and sum(len(packet) for packet in packets) <= self._max_bytes
            ):
                return
            if self._last_idr_au:
                self._last_idr_au = ()
                self._last_idr_key = None
                self._last_idr_first_sequence = None
                self._last_idr_last_sequence = None
                self._last_idr_completed_at = None
            elif self._last_pps is not None:
                self._last_pps = None
            elif self._last_sps is not None:
                self._last_sps = None
            else:
                return

    def observe_packet(self, packet: bytes) -> None:
        rtp = _parse_rtp(packet)
        if rtp is None or rtp.payload_type != H264_PAYLOAD_TYPE:
            return
        nal_types, usable = _h264_payload_nal_types(rtp.payload)
        if not usable:
            return
        raw_nal_type = rtp.payload[0] & 0x1F if rtp.payload else 0
        if raw_nal_type != 28 and 7 in nal_types and len(packet) <= self._max_bytes:
            self._last_sps = packet
        if raw_nal_type != 28 and 8 in nal_types and len(packet) <= self._max_bytes:
            self._last_pps = packet
        self._enforce_total_bounds()
        self._observe_access_unit(rtp, packet, _h264_payload_has_idr_start(rtp.payload))

    def _observe_access_unit(
        self,
        rtp: _RtpPacket,
        packet: bytes,
        has_idr_packet: bool,
    ) -> None:
        now = self._clock()
        self._evict_expired(now)
        key = (rtp.ssrc, rtp.timestamp)
        previous_key = self._last_key_by_ssrc.get(rtp.ssrc)
        if previous_key is not None and previous_key != key:
            self._open_units.pop(previous_key, None)
        self._last_key_by_ssrc[rtp.ssrc] = key

        unit = self._open_units.get(key)
        if unit is None:
            unit = _BootstrapAccessUnit(
                key=key,
                packets=[],
                packet_bytes=0,
                has_idr=False,
                started_at=now,
                first_sequence=rtp.sequence,
                last_sequence=rtp.sequence,
            )
            self._open_units[key] = unit
        unit.packets.append(packet)
        unit.packet_bytes += len(packet)
        unit.has_idr = unit.has_idr or has_idr_packet
        unit.last_sequence = rtp.sequence

        if (
            len(unit.packets) > self._max_packets
            or unit.packet_bytes > self._max_bytes
        ):
            self._open_units.pop(key, None)
            return
        if not rtp.marker:
            return
        self._open_units.pop(key, None)
        if unit.has_idr:
            self._last_idr_au = tuple(unit.packets)
            self._last_idr_key = key
            self._last_idr_first_sequence = unit.first_sequence
            self._last_idr_last_sequence = unit.last_sequence
            self._last_idr_completed_at = now
            self._enforce_total_bounds()

    def _evict_expired(self, now: float) -> None:
        expired = [
            key
            for key, unit in self._open_units.items()
            if now - unit.started_at > self._au_timeout_seconds
        ]
        for key in expired:
            self._open_units.pop(key, None)


class H264RecoveryRewriter:
    def __init__(
        self,
        *,
        payload_type: int = H264_PAYLOAD_TYPE,
        on_decodable_frame: Callable[[], None] | None = None,
    ) -> None:
        self._payload_type = payload_type
        # Diagnostic-only: fired at most once, the first time an access unit
        # is observed with SPS+PPS already seen before its IDR slice NAL
        # (i.e. the first frame a decoder could actually decode). Never
        # consulted by the rewrite/injection logic below.
        self._on_decodable_frame = on_decodable_frame
        self._decodable_frame_signaled = False
        self._sequence_offsets: dict[int, int] = {}
        self._access_units: dict[int, _AccessUnitState] = {}
        self.input_packets = 0
        self.output_packets = 0
        self.eligible_nonidr_i_count = 0
        self.injected_count = 0
        self.existing_recovery_count = 0
        self.idr_count = 0
        self.unsupported_packet_count = 0
        self.malformed_count = 0
        self.last_error: str | None = None

    def diagnostics(self, *, running: bool = False) -> RecoveryShimDiagnostics:
        return RecoveryShimDiagnostics(
            running=running,
            input_packets=self.input_packets,
            output_packets=self.output_packets,
            eligible_nonidr_i_count=self.eligible_nonidr_i_count,
            injected_count=self.injected_count,
            existing_recovery_count=self.existing_recovery_count,
            idr_count=self.idr_count,
            unsupported_packet_count=self.unsupported_packet_count,
            malformed_count=self.malformed_count,
            last_error=self.last_error,
        )

    def _au(self, rtp: _RtpPacket) -> _AccessUnitState:
        current = self._access_units.get(rtp.ssrc)
        if current is None or current.timestamp != rtp.timestamp:
            current = _AccessUnitState(timestamp=rtp.timestamp)
            self._access_units[rtp.ssrc] = current
        return current

    def _mark_malformed(self, token: str) -> None:
        self.malformed_count = _inc(self.malformed_count)
        self.last_error = token

    def _mark_unsupported(self) -> None:
        self.unsupported_packet_count = _inc(self.unsupported_packet_count)
        self.last_error = "unsupported_packet"

    def _mark_unprovable_recovery_signal(self, au: _AccessUnitState) -> None:
        if not au.seen_vcl:
            au.unprovable_recovery_signal = True

    def _observe_nal(
        self,
        au: _AccessUnitState,
        nal_type: int,
        nal_payload_after_header: bytes,
        *,
        can_inject_before_this_packet: bool,
    ) -> bool:
        if nal_type == 7 and not au.seen_vcl:
            au.seen_sps = True
            return False
        if nal_type == 8 and not au.seen_vcl:
            au.seen_pps = True
            return False
        if nal_type == 6:
            is_recovery_point, malformed = _sei_recovery_point_status(
                nal_payload_after_header
            )
            if malformed:
                self._mark_malformed("malformed_sei")
                self._mark_unprovable_recovery_signal(au)
            if is_recovery_point:
                if not au.seen_recovery_point_sei:
                    self.existing_recovery_count = _inc(self.existing_recovery_count)
                au.seen_recovery_point_sei = True
            return False
        if nal_type == 5:
            if (
                not self._decodable_frame_signaled
                and not au.seen_idr
                and au.seen_sps
                and au.seen_pps
            ):
                self._decodable_frame_signaled = True
                if self._on_decodable_frame is not None:
                    self._on_decodable_frame()
            au.seen_vcl = True
            au.seen_idr = True
            self.idr_count = _inc(self.idr_count)
            return False
        if nal_type != 1:
            if 1 <= nal_type <= 5:
                au.seen_vcl = True
            return False

        first_vcl = not au.seen_vcl
        au.seen_vcl = True
        if not can_inject_before_this_packet or not first_vcl:
            return False
        if not au.seen_sps or not au.seen_pps:
            return False
        if (
            au.seen_recovery_point_sei
            or au.injected_recovery_point
            or au.unprovable_recovery_signal
        ):
            return False

        parsed = _parse_slice_header(nal_payload_after_header)
        if parsed is None:
            self._mark_malformed("malformed_slice_header")
            return False
        first_mb_in_slice, slice_type = parsed
        if first_mb_in_slice == 0 and slice_type % 5 == 2:
            self.eligible_nonidr_i_count = _inc(self.eligible_nonidr_i_count)
            au.injected_recovery_point = True
            return True
        return False

    def _inspect_h264_payload(self, rtp: _RtpPacket) -> bool:
        payload = rtp.payload
        au = self._au(rtp)
        if not payload:
            self._mark_malformed("malformed_h264_payload")
            self._mark_unprovable_recovery_signal(au)
            return False
        nal_type = payload[0] & 0x1F
        if 1 <= nal_type <= 23:
            return self._observe_nal(
                au,
                nal_type,
                payload[1:],
                can_inject_before_this_packet=True,
            )
        if nal_type == 24:
            pos = 1
            inject = False
            while pos < len(payload):
                if pos + 2 > len(payload):
                    self._mark_malformed("malformed_stap_a")
                    self._mark_unprovable_recovery_signal(au)
                    return False
                nal_len = struct.unpack_from("!H", payload, pos)[0]
                pos += 2
                if nal_len == 0 or pos + nal_len > len(payload):
                    self._mark_malformed("malformed_stap_a")
                    self._mark_unprovable_recovery_signal(au)
                    return False
                nal = payload[pos : pos + nal_len]
                pos += nal_len
                inject = (
                    self._observe_nal(
                        au,
                        nal[0] & 0x1F,
                        nal[1:],
                        can_inject_before_this_packet=True,
                    )
                    or inject
                )
            return inject
        if nal_type == 28:
            if len(payload) < 2:
                self._mark_malformed("malformed_fu_a")
                self._mark_unprovable_recovery_signal(au)
                return False
            fu_header = payload[1]
            start = bool(fu_header & 0x80)
            reconstructed_type = fu_header & 0x1F
            if not start:
                return False
            if reconstructed_type == 6:
                self._mark_unprovable_recovery_signal(au)
                return False
            if reconstructed_type == 1:
                return self._observe_nal(
                    au,
                    reconstructed_type,
                    payload[2:],
                    can_inject_before_this_packet=True,
                )
            return self._observe_nal(
                au,
                reconstructed_type,
                payload[2:],
                can_inject_before_this_packet=False,
            )
        self._mark_unsupported()
        if nal_type == 0 or nal_type in {25, 26, 27, 29, 30, 31}:
            self._mark_unprovable_recovery_signal(au)
        return False

    def rewrite_rtp_packet(self, packet: bytes) -> list[bytes]:
        self.input_packets = _inc(self.input_packets)
        rtp = _parse_rtp(packet)
        if rtp is None:
            self._mark_malformed("malformed_rtp")
            self.output_packets = _inc(self.output_packets)
            return [packet]

        offset = self._sequence_offsets.get(rtp.ssrc, 0)
        shifted_sequence = (rtp.sequence + offset) & 0xFFFF
        if rtp.payload_type != self._payload_type:
            self.output_packets = _inc(self.output_packets)
            return [_replace_sequence(packet, shifted_sequence)]

        inject = self._inspect_h264_payload(rtp)
        if not inject:
            self.output_packets = _inc(self.output_packets)
            return [_replace_sequence(packet, shifted_sequence)]

        injected = _make_injected_packet(
            rtp, shifted_sequence, build_recovery_point_sei_nal()
        )
        self.injected_count = _inc(self.injected_count)
        offset += 1
        self._sequence_offsets[rtp.ssrc] = offset
        original = _replace_sequence(packet, (rtp.sequence + offset) & 0xFFFF)
        self.output_packets = _inc(_inc(self.output_packets))
        return [injected, original]


class RecoveryRtpShimProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        rewriter: H264RecoveryRewriter,
        output_transports: Sequence[asyncio.DatagramTransport],
        *,
        output_ports: Sequence[int | None] | None = None,
        inactive_output_ports: Sequence[int] = (),
        bootstrap_max_packets: int = DEFAULT_BOOTSTRAP_MAX_PACKETS,
        bootstrap_max_bytes: int = DEFAULT_BOOTSTRAP_MAX_BYTES,
        bootstrap_au_timeout_seconds: float = DEFAULT_BOOTSTRAP_AU_TIMEOUT_SECONDS,
    ) -> None:
        self._rewriter = rewriter
        ports = tuple(output_ports) if output_ports is not None else ()
        if ports and len(ports) != len(output_transports):
            raise ValueError("output_ports must match output_transports")
        inactive = set(inactive_output_ports)
        self._sinks = tuple(
            _OutputSink(
                port=ports[idx] if ports else None,
                transport=transport,
                active=(ports[idx] not in inactive) if ports else True,
            )
            for idx, transport in enumerate(output_transports)
        )
        self._bootstrap_cache = _H264BootstrapCache(
            max_packets=bootstrap_max_packets,
            max_bytes=bootstrap_max_bytes,
            au_timeout_seconds=bootstrap_au_timeout_seconds,
        )
        self._activation_queues: dict[int, list[bytes]] = {}
        self._first_rtp_logged = False
        self._first_sps_logged = False
        self._first_pps_logged = False
        self._first_idr_start_logged = False
        self._first_complete_idr_logged = False
        self._input_rtp_packets = 0
        self._first_rtp_at: str | None = None
        self._last_rtp_at: str | None = None
        self._first_rtp_monotonic: float | None = None
        self._last_rtp_monotonic: float | None = None
        self._summary_emitted = False
        self.last_error: str | None = None

    def _mark_input_rtp(self, rtp: _RtpPacket, packet_len: int) -> None:
        try:
            now = _utc_now_iso()
            monotonic_now = time.monotonic()
            self._input_rtp_packets = _inc(self._input_rtp_packets)
            if self._first_rtp_at is None:
                self._first_rtp_at = now
                self._first_rtp_monotonic = monotonic_now
            self._last_rtp_at = now
            self._last_rtp_monotonic = monotonic_now
            if self._first_rtp_logged:
                return
            self._first_rtp_logged = True
            _safe_log_info(
                "shim_first_rtp at=%s ssrc=%d sequence=%d bytes=%d",
                now,
                rtp.ssrc,
                rtp.sequence,
                packet_len,
            )
        except Exception:
            return

    def _log_cache_milestones(self, rtp: _RtpPacket, packet_len: int) -> None:
        try:
            if (
                self._first_sps_logged
                and self._first_pps_logged
                and self._first_idr_start_logged
            ):
                return
            now = _utc_now_iso()
            nal_types, usable = _h264_payload_nal_types(rtp.payload)
            if not usable:
                return
            raw_nal_type = rtp.payload[0] & 0x1F if rtp.payload else 0
            if (
                not self._first_sps_logged
                and raw_nal_type != 28
                and 7 in nal_types
            ):
                self._first_sps_logged = True
                _safe_log_info(
                    "shim_first_sps_cached at=%s ssrc=%d sequence=%d bytes=%d",
                    now,
                    rtp.ssrc,
                    rtp.sequence,
                    packet_len,
                )
            if (
                not self._first_pps_logged
                and raw_nal_type != 28
                and 8 in nal_types
            ):
                self._first_pps_logged = True
                _safe_log_info(
                    "shim_first_pps_cached at=%s ssrc=%d sequence=%d bytes=%d",
                    now,
                    rtp.ssrc,
                    rtp.sequence,
                    packet_len,
                )
            if (
                not self._first_idr_start_logged
                and _h264_payload_has_idr_start(rtp.payload)
            ):
                self._first_idr_start_logged = True
                _safe_log_info(
                    "shim_first_idr_start_seen at=%s ssrc=%d sequence=%d bytes=%d",
                    now,
                    rtp.ssrc,
                    rtp.sequence,
                    packet_len,
                )
        except Exception:
            return

    def _log_complete_idr_milestone(
        self,
        before: H264BootstrapDiagnostics,
        after: H264BootstrapDiagnostics,
    ) -> None:
        try:
            if self._first_complete_idr_logged or not after.has_complete_idr_au:
                return
            if before.has_complete_idr_au:
                return
            self._first_complete_idr_logged = True
            _safe_log_info(
                "shim_first_complete_idr_cached at=%s ssrc=%d sequence=%d bytes=%d",
                _utc_now_iso(),
                after.idr_ssrc if after.idr_ssrc is not None else 0,
                after.first_sequence if after.first_sequence is not None else 0,
                after.idr_au_total_bytes,
            )
        except Exception:
            return

    def _format_age(self, age_ms: int | None) -> str:
        return str(age_ms) if age_ms is not None else "NA"

    def _bootstrap_diagnostics_safe(self) -> H264BootstrapDiagnostics:
        try:
            return self._bootstrap_cache.diagnostics()
        except Exception:
            return H264BootstrapDiagnostics(
                has_sps=False,
                has_pps=False,
                has_complete_idr_au=False,
                snapshot_packet_count=0,
                snapshot_total_bytes=0,
                idr_au_packet_count=0,
                idr_au_total_bytes=0,
                idr_ssrc=None,
                idr_timestamp=None,
                first_sequence=None,
                last_sequence=None,
                completed_idr_age_ms=None,
            )

    def _log_activation(
        self,
        *,
        port: int,
        diagnostics: H264BootstrapDiagnostics,
        queued_live_packets: int,
        activation_result: str,
    ) -> None:
        _safe_log_info(
            "output_sink_activation port=%d bootstrap_packets=%d "
            "bootstrap_bytes=%d bootstrap_has_sps=%s bootstrap_has_pps=%s "
            "bootstrap_has_complete_idr=%s bootstrap_idr_packets=%d "
            "bootstrap_age_ms=%s queued_live_packets=%d activation_result=%s",
            port,
            diagnostics.snapshot_packet_count,
            diagnostics.snapshot_total_bytes,
            str(diagnostics.has_sps).lower(),
            str(diagnostics.has_pps).lower(),
            str(diagnostics.has_complete_idr_au).lower(),
            diagnostics.idr_au_packet_count,
            self._format_age(diagnostics.completed_idr_age_ms),
            queued_live_packets,
            activation_result,
        )

    def _log_bootstrap_sent(
        self,
        *,
        port: int,
        attempted_packets: int,
        sent_packets: int,
        send_errors: int,
    ) -> None:
        _safe_log_info(
            "output_sink_bootstrap_sent port=%d attempted_packets=%d "
            "sent_packets=%d send_errors=%d",
            port,
            attempted_packets,
            sent_packets,
            send_errors,
        )

    def emit_input_summary(self) -> None:
        if self._summary_emitted:
            return
        self._summary_emitted = True
        duration_ms = 0
        if (
            self._first_rtp_monotonic is not None
            and self._last_rtp_monotonic is not None
        ):
            duration_ms = max(
                0, int((self._last_rtp_monotonic - self._first_rtp_monotonic) * 1000)
            )
        _safe_log_info(
            "input_rtp_summary input_rtp_packets=%d first_rtp_at=%s "
            "last_rtp_at=%s input_rtp_duration_ms=%d",
            self._input_rtp_packets,
            self._first_rtp_at or "NA",
            self._last_rtp_at or "NA",
            duration_ms,
        )

    def datagram_received(self, data: bytes, addr: Any) -> None:
        try:
            input_rtp = _parse_rtp(data)
            if input_rtp is not None:
                self._mark_input_rtp(input_rtp, len(data))
            for packet in self._rewriter.rewrite_rtp_packet(data):
                parsed = _parse_rtp(packet)
                if parsed is not None:
                    self._log_cache_milestones(parsed, len(packet))
                should_check_complete_idr = not self._first_complete_idr_logged
                before = (
                    self._bootstrap_diagnostics_safe()
                    if should_check_complete_idr
                    else None
                )
                self._bootstrap_cache.observe_packet(packet)
                if before is not None:
                    after = self._bootstrap_diagnostics_safe()
                    self._log_complete_idr_milestone(before, after)
                for sink in self._sinks:
                    if sink.port in self._activation_queues:
                        self._activation_queues[sink.port].append(packet)
                        continue
                    if not sink.active:
                        continue
                    try:
                        sink.transport.sendto(packet)
                    except Exception:
                        self.last_error = "fanout_send_exception"
        except Exception:
            self.last_error = "rewrite_exception"
            self._rewriter.last_error = "rewrite_exception"
            self._rewriter.malformed_count = _inc(self._rewriter.malformed_count)

    def error_received(self, exc: Exception) -> None:
        self.last_error = "udp_error"
        self._rewriter.last_error = "udp_error"

    def activate_output_port(self, port: int) -> bool:
        for sink in self._sinks:
            if sink.port != port:
                continue
            if sink.active:
                self._log_activation(
                    port=port,
                    diagnostics=self._bootstrap_diagnostics_safe(),
                    queued_live_packets=0,
                    activation_result="already_active",
                )
                return True
            bootstrap = self._bootstrap_cache.snapshot()
            bootstrap_diagnostics = self._bootstrap_diagnostics_safe()
            self._activation_queues[port] = []
            sent_packets = 0
            send_errors = 0
            self._log_activation(
                port=port,
                diagnostics=bootstrap_diagnostics,
                queued_live_packets=0,
                activation_result="activated",
            )
            try:
                for packet in bootstrap:
                    try:
                        sink.transport.sendto(packet)
                        sent_packets = _inc(sent_packets)
                    except Exception:
                        send_errors = _inc(send_errors)
                        self.last_error = "fanout_send_exception"
            finally:
                queued = self._activation_queues.pop(port, [])
            self._log_bootstrap_sent(
                port=port,
                attempted_packets=len(bootstrap),
                sent_packets=sent_packets,
                send_errors=send_errors,
            )
            sink.active = True
            for packet in queued:
                try:
                    sink.transport.sendto(packet)
                except Exception:
                    self.last_error = "fanout_send_exception"
            return True
        self._log_activation(
            port=port,
            diagnostics=self._bootstrap_diagnostics_safe(),
            queued_live_packets=0,
            activation_result="unknown_port",
        )
        return False

    def deactivate_output_port(self, port: int) -> bool:
        for sink in self._sinks:
            if sink.port != port:
                continue
            sink.active = False
            return True
        return False


class H264RecoveryRtpShim:
    def __init__(
        self,
        *,
        input_port: int,
        output_port: int,
        output_ports: Sequence[int] | None = None,
        inactive_output_ports: Sequence[int] = (),
        host: str = "127.0.0.1",
        endpoint_factory: Callable[..., Awaitable[tuple[asyncio.DatagramTransport, Any]]]
        | None = None,
        on_decodable_frame: Callable[[], None] | None = None,
        bootstrap_max_packets: int = DEFAULT_BOOTSTRAP_MAX_PACKETS,
        bootstrap_max_bytes: int = DEFAULT_BOOTSTRAP_MAX_BYTES,
        bootstrap_au_timeout_seconds: float = DEFAULT_BOOTSTRAP_AU_TIMEOUT_SECONDS,
    ) -> None:
        self._host = host
        self._input_port = input_port
        ports = tuple(output_ports) if output_ports is not None else (output_port,)
        if not ports:
            raise ValueError("output_ports must not be empty")
        if output_port not in ports:
            ports = (output_port, *ports)
        self._output_ports = tuple(dict.fromkeys(ports))
        self._inactive_output_ports = tuple(
            port for port in dict.fromkeys(inactive_output_ports) if port in ports
        )
        self._output_port = output_port
        self._endpoint_factory = endpoint_factory
        self._rewriter = H264RecoveryRewriter(on_decodable_frame=on_decodable_frame)
        self._bootstrap_max_packets = bootstrap_max_packets
        self._bootstrap_max_bytes = bootstrap_max_bytes
        self._bootstrap_au_timeout_seconds = bootstrap_au_timeout_seconds
        self._input_transport: asyncio.DatagramTransport | None = None
        self._output_transports: tuple[asyncio.DatagramTransport, ...] = ()
        self._protocol: RecoveryRtpShimProtocol | None = None

    @property
    def running(self) -> bool:
        return self._input_transport is not None and bool(self._output_transports)

    @property
    def input_port(self) -> int:
        return self._input_port

    @property
    def output_port(self) -> int:
        return self._output_port

    @property
    def output_ports(self) -> tuple[int, ...]:
        return self._output_ports

    @property
    def inactive_output_ports(self) -> tuple[int, ...]:
        return self._inactive_output_ports

    def diagnostics(self) -> RecoveryShimDiagnostics:
        diagnostics = self._rewriter.diagnostics(running=self.running)
        protocol = self._protocol
        if protocol is not None and protocol.last_error is not None:
            return RecoveryShimDiagnostics(
                running=diagnostics.running,
                input_packets=diagnostics.input_packets,
                output_packets=diagnostics.output_packets,
                eligible_nonidr_i_count=diagnostics.eligible_nonidr_i_count,
                injected_count=diagnostics.injected_count,
                existing_recovery_count=diagnostics.existing_recovery_count,
                idr_count=diagnostics.idr_count,
                unsupported_packet_count=diagnostics.unsupported_packet_count,
                malformed_count=diagnostics.malformed_count,
                last_error=protocol.last_error,
            )
        return diagnostics

    async def async_start(self) -> None:
        if self.running:
            return
        loop = asyncio.get_running_loop()
        endpoint_factory = self._endpoint_factory or loop.create_datagram_endpoint
        input_transport: asyncio.DatagramTransport | None = None
        output_transports: list[asyncio.DatagramTransport] = []
        protocol: RecoveryRtpShimProtocol | None = None
        for port in self._output_ports:
            check_transport, _ = await endpoint_factory(
                asyncio.DatagramProtocol,
                local_addr=(self._host, port),
            )
            check_transport.close()
            await asyncio.sleep(0)
        try:
            for port in self._output_ports:
                output_transport, _ = await endpoint_factory(
                    asyncio.DatagramProtocol,
                    remote_addr=(self._host, port),
                )
                output_transports.append(output_transport)
            protocol = RecoveryRtpShimProtocol(
                self._rewriter,
                output_transports,
                output_ports=self._output_ports,
                inactive_output_ports=self._inactive_output_ports,
                bootstrap_max_packets=self._bootstrap_max_packets,
                bootstrap_max_bytes=self._bootstrap_max_bytes,
                bootstrap_au_timeout_seconds=self._bootstrap_au_timeout_seconds,
            )
            input_transport, _ = await endpoint_factory(
                lambda: protocol,
                local_addr=(self._host, self._input_port),
            )
        except BaseException:
            if input_transport is not None:
                input_transport.close()
            for output_transport in output_transports:
                output_transport.close()
            self._input_transport = None
            self._output_transports = ()
            self._protocol = None
            raise
        self._protocol = protocol
        self._input_transport = input_transport
        self._output_transports = tuple(output_transports)

    async def async_stop(self) -> None:
        input_transport = self._input_transport
        output_transports = self._output_transports
        protocol = self._protocol
        if protocol is not None:
            protocol.emit_input_summary()
        self._input_transport = None
        self._output_transports = ()
        self._protocol = None
        if input_transport is not None:
            input_transport.close()
        for output_transport in output_transports:
            output_transport.close()
        await asyncio.sleep(0)

    async def async_activate_output_port(self, port: int) -> None:
        protocol = self._protocol
        if protocol is None:
            raise RuntimeError("h264_recovery_rtp_shim_not_running")
        if not protocol.activate_output_port(port):
            raise ValueError("unknown_output_port")

    async def async_deactivate_output_port(self, port: int) -> None:
        protocol = self._protocol
        if protocol is None:
            raise RuntimeError("h264_recovery_rtp_shim_not_running")
        if not protocol.deactivate_output_port(port):
            raise ValueError("unknown_output_port")
