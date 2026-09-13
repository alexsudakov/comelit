from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import struct
from typing import Any

RTP_VERSION = 2
H264_PAYLOAD_TYPE = 99
MAX_SAFE_COUNTER = (1 << 63) - 1


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


def _sei_recovery_point_is_zero(nal_payload_after_header: bytes) -> bool:
    rbsp = _remove_emulation_prevention(nal_payload_after_header)
    pos = 0
    while pos < len(rbsp):
        payload_type = 0
        while pos < len(rbsp) and rbsp[pos] == 0xFF:
            payload_type += 255
            pos += 1
        if pos >= len(rbsp):
            return False
        payload_type += rbsp[pos]
        pos += 1

        payload_size = 0
        while pos < len(rbsp) and rbsp[pos] == 0xFF:
            payload_size += 255
            pos += 1
        if pos >= len(rbsp):
            return False
        payload_size += rbsp[pos]
        pos += 1

        if payload_size > len(rbsp) - pos:
            return False
        payload = rbsp[pos : pos + payload_size]
        pos += payload_size
        if payload_type != 6:
            continue
        try:
            reader = _BitReader(payload)
            recovery_frame_cnt = reader.read_ue()
        except ValueError:
            return False
        return recovery_frame_cnt == 0
    return False


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


class H264RecoveryRewriter:
    def __init__(self, *, payload_type: int = H264_PAYLOAD_TYPE) -> None:
        self._payload_type = payload_type
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
            if _sei_recovery_point_is_zero(nal_payload_after_header):
                if not au.seen_recovery_point_sei:
                    self.existing_recovery_count = _inc(self.existing_recovery_count)
                au.seen_recovery_point_sei = True
            return False
        if nal_type == 5:
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
        if au.seen_recovery_point_sei or au.injected_recovery_point:
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
        if not payload:
            self._mark_malformed("malformed_h264_payload")
            return False
        au = self._au(rtp)
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
                    return False
                nal_len = struct.unpack_from("!H", payload, pos)[0]
                pos += 2
                if nal_len == 0 or pos + nal_len > len(payload):
                    self._mark_malformed("malformed_stap_a")
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
                return False
            fu_header = payload[1]
            start = bool(fu_header & 0x80)
            reconstructed_type = fu_header & 0x1F
            if not start:
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
        output_transport: asyncio.DatagramTransport,
    ) -> None:
        self._rewriter = rewriter
        self._output_transport = output_transport
        self.last_error: str | None = None

    def datagram_received(self, data: bytes, addr: Any) -> None:
        try:
            for packet in self._rewriter.rewrite_rtp_packet(data):
                self._output_transport.sendto(packet)
        except Exception:
            self.last_error = "rewrite_exception"
            self._rewriter.last_error = "rewrite_exception"
            self._rewriter.malformed_count = _inc(self._rewriter.malformed_count)

    def error_received(self, exc: Exception) -> None:
        self.last_error = "udp_error"
        self._rewriter.last_error = "udp_error"


class H264RecoveryRtpShim:
    def __init__(
        self,
        *,
        input_port: int,
        output_port: int,
        host: str = "127.0.0.1",
        endpoint_factory: Callable[..., Awaitable[tuple[asyncio.DatagramTransport, Any]]]
        | None = None,
    ) -> None:
        self._host = host
        self._input_port = input_port
        self._output_port = output_port
        self._endpoint_factory = endpoint_factory
        self._rewriter = H264RecoveryRewriter()
        self._input_transport: asyncio.DatagramTransport | None = None
        self._output_transport: asyncio.DatagramTransport | None = None
        self._protocol: RecoveryRtpShimProtocol | None = None

    @property
    def running(self) -> bool:
        return self._input_transport is not None and self._output_transport is not None

    @property
    def input_port(self) -> int:
        return self._input_port

    @property
    def output_port(self) -> int:
        return self._output_port

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
        output_transport: asyncio.DatagramTransport | None = None
        protocol: RecoveryRtpShimProtocol | None = None
        check_transport, _ = await endpoint_factory(
            asyncio.DatagramProtocol,
            local_addr=(self._host, self._output_port),
        )
        check_transport.close()
        await asyncio.sleep(0)
        try:
            output_transport, _ = await endpoint_factory(
                asyncio.DatagramProtocol,
                remote_addr=(self._host, self._output_port),
            )
            protocol = RecoveryRtpShimProtocol(self._rewriter, output_transport)
            input_transport, _ = await endpoint_factory(
                lambda: protocol,
                local_addr=(self._host, self._input_port),
            )
        except BaseException:
            if input_transport is not None:
                input_transport.close()
            if output_transport is not None:
                output_transport.close()
            self._input_transport = None
            self._output_transport = None
            self._protocol = None
            raise
        self._protocol = protocol
        self._input_transport = input_transport
        self._output_transport = output_transport

    async def async_stop(self) -> None:
        input_transport = self._input_transport
        output_transport = self._output_transport
        self._input_transport = None
        self._output_transport = None
        self._protocol = None
        if input_transport is not None:
            input_transport.close()
        if output_transport is not None:
            output_transport.close()
        await asyncio.sleep(0)
