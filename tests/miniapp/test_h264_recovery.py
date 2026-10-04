from __future__ import annotations

import asyncio
import logging
import struct

import pytest

from custom_components.comelit import h264_recovery as h264


def _rtp_packet(
    sequence: int,
    timestamp: int,
    payload: bytes,
    *,
    marker: bool = False,
    ssrc: int = 0x12345678,
    payload_type: int = 99,
) -> bytes:
    header = bytearray(12)
    header[0] = 0x80
    header[1] = payload_type & 0x7F
    if marker:
        header[1] |= 0x80
    struct.pack_into("!H", header, 2, sequence)
    struct.pack_into("!I", header, 4, timestamp)
    struct.pack_into("!I", header, 8, ssrc)
    return bytes(header) + payload


def _seq(packet: bytes) -> int:
    return struct.unpack_from("!H", packet, 2)[0]


def _nal(packet: bytes) -> int:
    return packet[12] & 0x1F


def _fu_a(reconstructed_type: int, payload: bytes, *, start=False, end=False) -> bytes:
    fu_indicator = bytes([0x60 | 28])
    fu_header = reconstructed_type
    if start:
        fu_header |= 0x80
    if end:
        fu_header |= 0x40
    return fu_indicator + bytes([fu_header]) + payload


def _stap_a(*nals: bytes) -> bytes:
    payload = bytearray([0x78])
    for nal in nals:
        payload.extend(struct.pack("!H", len(nal)))
        payload.extend(nal)
    return bytes(payload)


class _FakeDatagramTransport:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.packets: list[bytes] = []
        self.closed = False

    def sendto(self, packet):
        if self.fail:
            raise OSError("closed")
        self.packets.append(packet)

    def close(self):
        self.closed = True


def _protocol(*, late_fail: bool = False, **kwargs):
    rewriter = h264.H264RecoveryRewriter()
    ha = _FakeDatagramTransport()
    late = _FakeDatagramTransport(fail=late_fail)
    protocol = h264.RecoveryRtpShimProtocol(
        rewriter,
        (ha, late),
        output_ports=(17999, 18099),
        inactive_output_ports=(18099,),
        **kwargs,
    )
    return protocol, rewriter, ha, late


def test_single_packet_idr_bootstrap_replays_sps_pps_and_idr_once():
    protocol, _rewriter, ha, late = _protocol()
    packets = [
        _rtp_packet(1, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(2, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(3, 270_000, b"\x65\x88", marker=True),
    ]
    for packet in packets:
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    assert late.packets == []
    assert ha.packets == packets
    assert protocol.activate_output_port(18099) is True
    assert late.packets == packets
    assert protocol.activate_output_port(18099) is True
    assert late.packets == packets


def test_fu_a_fragmented_idr_bootstrap_replays_complete_access_unit():
    protocol, _rewriter, _ha, late = _protocol()
    sps = _rtp_packet(10, 90_000, _stap_a(b"\x67\x64", b"\x68\xee"), marker=True)
    fragments = [
        _rtp_packet(11, 180_000, _fu_a(5, b"start", start=True)),
        _rtp_packet(12, 180_000, _fu_a(5, b"middle")),
        _rtp_packet(13, 180_000, _fu_a(5, b"end", end=True), marker=True),
    ]
    for packet in (sps, *fragments):
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)

    assert [_seq(packet) for packet in late.packets] == [10, 11, 12, 13]
    assert all(_nal(packet) == 28 for packet in late.packets[1:])
    assert late.packets[-1][1] & 0x80


def test_incomplete_fu_a_access_unit_is_not_cached():
    protocol, _rewriter, _ha, late = _protocol()
    packets = [
        _rtp_packet(20, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(21, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(22, 270_000, _fu_a(5, b"start", start=True)),
    ]
    for packet in packets:
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)

    assert [_seq(packet) for packet in late.packets] == [20, 21]

    protocol, _rewriter, _ha, late = _protocol()
    for packet in (
        _rtp_packet(23, 270_000, _fu_a(5, b"middle")),
        _rtp_packet(24, 270_000, _fu_a(5, b"end", end=True), marker=True),
    ):
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)
    assert late.packets == []


def test_new_sink_receives_bootstrap_before_live_and_live_after_activation():
    protocol, _rewriter, _ha, late = _protocol()
    bootstrap = [
        _rtp_packet(30, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(31, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(32, 270_000, b"\x65\x88", marker=True),
    ]
    for packet in bootstrap:
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)
    live = _rtp_packet(33, 360_000, b"\x41\xb8", marker=True)
    protocol.datagram_received(live, ("127.0.0.1", 1))

    assert late.packets == [*bootstrap, live]


def test_early_sink_keeps_existing_rewritten_packet_sequence():
    protocol, rewriter, ha, _late = _protocol()
    protocol.datagram_received(_rtp_packet(40, 90_000, b"\x67\x64"), ("127.0.0.1", 1))
    protocol.datagram_received(_rtp_packet(41, 90_000, b"\x68\xee"), ("127.0.0.1", 1))
    protocol.datagram_received(_rtp_packet(42, 90_000, b"\x41\xb8"), ("127.0.0.1", 1))

    assert rewriter.input_packets == 3
    assert rewriter.injected_count == 1
    assert rewriter.output_packets == 4
    assert [_seq(packet) for packet in ha.packets] == [40, 41, 42, 43]


def test_failing_late_sink_does_not_break_ha_sink():
    protocol, _rewriter, ha, late = _protocol(late_fail=True)
    bootstrap = _rtp_packet(50, 90_000, b"\x65\x88", marker=True)
    protocol.datagram_received(bootstrap, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)
    live = _rtp_packet(51, 180_000, b"\x41\xb8", marker=True)
    protocol.datagram_received(live, ("127.0.0.1", 1))

    assert late.packets == []
    assert ha.packets == [bootstrap, live]
    assert protocol.last_error == "fanout_send_exception"


def test_two_late_sinks_activate_independently():
    ha = _FakeDatagramTransport()
    late_a = _FakeDatagramTransport()
    late_b = _FakeDatagramTransport()
    protocol = h264.RecoveryRtpShimProtocol(
        h264.H264RecoveryRewriter(),
        (ha, late_a, late_b),
        output_ports=(17999, 18099, 18199),
        inactive_output_ports=(18099, 18199),
    )
    bootstrap = _rtp_packet(60, 90_000, b"\x65\x88", marker=True)
    protocol.datagram_received(bootstrap, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)
    live_a = _rtp_packet(61, 180_000, b"\x41\xa1", marker=True)
    protocol.datagram_received(live_a, ("127.0.0.1", 1))
    protocol.activate_output_port(18199)
    live_b = _rtp_packet(62, 270_000, b"\x41\xa2", marker=True)
    protocol.datagram_received(live_b, ("127.0.0.1", 1))

    assert late_a.packets == [bootstrap, live_a, live_b]
    assert late_b.packets == [bootstrap, live_b]


def test_bootstrap_cache_packet_and_byte_bounds_are_enforced():
    protocol, _rewriter, _ha, late = _protocol(bootstrap_max_packets=2)
    for packet in (
        _rtp_packet(70, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(71, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(72, 270_000, _fu_a(5, b"a", start=True)),
        _rtp_packet(73, 270_000, _fu_a(5, b"b")),
        _rtp_packet(74, 270_000, _fu_a(5, b"c", end=True), marker=True),
    ):
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)
    assert [_seq(packet) for packet in late.packets] == [70, 71]

    protocol, _rewriter, _ha, late = _protocol(bootstrap_max_bytes=30)
    oversized = _rtp_packet(80, 90_000, b"\x65" + (b"x" * 64), marker=True)
    protocol.datagram_received(oversized, ("127.0.0.1", 1))
    protocol.activate_output_port(18099)
    assert late.packets == []


def test_access_unit_grouping_does_not_mix_timestamps_or_ssrcs():
    protocol, _rewriter, _ha, late = _protocol()
    ssrc_a = 0xA
    ssrc_b = 0xB
    packets = [
        _rtp_packet(90, 90_000, _fu_a(5, b"a1", start=True), ssrc=ssrc_a),
        _rtp_packet(91, 90_000, _fu_a(5, b"b1", start=True), ssrc=ssrc_b),
        _rtp_packet(
            92,
            90_000,
            _fu_a(5, b"a2", end=True),
            marker=True,
            ssrc=ssrc_a,
        ),
    ]
    for packet in packets:
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    protocol.activate_output_port(18099)

    assert [_seq(packet) for packet in late.packets] == [90, 92]


def test_shim_activation_api_replays_inactive_port_once():
    async def run():
        transports: dict[int, _FakeDatagramTransport] = {}
        protocol_holder = {}

        async def endpoint_factory(factory, local_addr=None, remote_addr=None):
            if remote_addr is not None:
                port = remote_addr[1]
                transport = _FakeDatagramTransport()
                transports[port] = transport
                return transport, None
            protocol = factory()
            protocol_holder["protocol"] = protocol
            return _FakeDatagramTransport(), protocol

        shim = h264.H264RecoveryRtpShim(
            input_port=17000,
            output_port=17999,
            output_ports=(17999, 18099),
            inactive_output_ports=(18099,),
            endpoint_factory=endpoint_factory,
        )
        await shim.async_start()
        protocol_holder["protocol"].datagram_received(
            _rtp_packet(100, 90_000, b"\x65\x88", marker=True),
            ("127.0.0.1", 1),
        )
        assert transports[17999].packets
        assert transports[18099].packets == []
        await shim.async_activate_output_port(18099)
        await shim.async_activate_output_port(18099)
        await shim.async_stop()
        return transports

    transports = asyncio.run(run())
    assert [_seq(packet) for packet in transports[18099].packets] == [100]


def test_unknown_activation_port_is_rejected():
    protocol, _rewriter, _ha, _late = _protocol()

    assert protocol.activate_output_port(19000) is False


def test_shim_activation_before_start_fails():
    shim = h264.H264RecoveryRtpShim(input_port=17000, output_port=17999)

    with pytest.raises(RuntimeError, match="not_running"):
        asyncio.run(shim.async_activate_output_port(17999))


def test_deactivate_then_reactivate_replays_only_new_bootstrap_once():
    protocol, _rewriter, _ha, late = _protocol()
    old = _rtp_packet(110, 90_000, b"\x65\x88", marker=True)
    protocol.datagram_received(old, ("127.0.0.1", 1))
    assert protocol.activate_output_port(18099) is True
    assert protocol.deactivate_output_port(18099) is True

    new = _rtp_packet(111, 180_000, b"\x65\x99", marker=True)
    protocol.datagram_received(new, ("127.0.0.1", 1))
    assert protocol.activate_output_port(18099) is True
    assert protocol.activate_output_port(18099) is True

    assert late.packets == [old, new]


def test_deactivate_inactive_sink_is_noop_and_unknown_port_is_rejected():
    protocol, _rewriter, _ha, late = _protocol()

    assert protocol.deactivate_output_port(18099) is True
    assert late.packets == []
    assert protocol.deactivate_output_port(19000) is False


def test_shim_deactivation_before_start_fails():
    shim = h264.H264RecoveryRtpShim(input_port=17000, output_port=17999)

    with pytest.raises(RuntimeError, match="not_running"):
        asyncio.run(shim.async_deactivate_output_port(17999))


def test_shim_restart_does_not_replay_stale_bootstrap():
    async def run():
        transports_by_start: list[dict[int, _FakeDatagramTransport]] = []
        protocol_holder = {}

        async def endpoint_factory(factory, local_addr=None, remote_addr=None):
            if remote_addr is not None:
                if len(transports_by_start) == 0 or remote_addr[1] in transports_by_start[-1]:
                    transports_by_start.append({})
                port = remote_addr[1]
                transport = _FakeDatagramTransport()
                transports_by_start[-1][port] = transport
                return transport, None
            protocol = factory()
            protocol_holder["protocol"] = protocol
            return _FakeDatagramTransport(), protocol

        shim = h264.H264RecoveryRtpShim(
            input_port=17000,
            output_port=17999,
            output_ports=(17999, 18099),
            inactive_output_ports=(18099,),
            endpoint_factory=endpoint_factory,
        )
        await shim.async_start()
        protocol_holder["protocol"].datagram_received(
            _rtp_packet(120, 90_000, b"\x65\x88", marker=True),
            ("127.0.0.1", 1),
        )
        await shim.async_stop()
        await shim.async_start()
        await shim.async_activate_output_port(18099)
        await shim.async_stop()
        return transports_by_start

    transports_by_start = asyncio.run(run())
    assert [_seq(packet) for packet in transports_by_start[0][17999].packets] == [120]
    assert transports_by_start[1][18099].packets == []


def test_activation_bootstrap_is_not_interleaved_by_reentrant_live_packet():
    live = _rtp_packet(133, 360_000, b"\x41\xb8", marker=True)
    protocol_holder = {}

    class _ReentrantTransport(_FakeDatagramTransport):
        def __init__(self):
            super().__init__()
            self._reentered = False

        def sendto(self, packet):
            super().sendto(packet)
            if not self._reentered:
                self._reentered = True
                protocol_holder["protocol"].datagram_received(
                    live, ("127.0.0.1", 1)
                )

    ha = _FakeDatagramTransport()
    late = _ReentrantTransport()
    protocol = h264.RecoveryRtpShimProtocol(
        h264.H264RecoveryRewriter(),
        (ha, late),
        output_ports=(17999, 18099),
        inactive_output_ports=(18099,),
    )
    protocol_holder["protocol"] = protocol
    bootstrap = [
        _rtp_packet(130, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(131, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(132, 270_000, b"\x65\x88", marker=True),
    ]
    for packet in bootstrap:
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    assert protocol.activate_output_port(18099) is True

    assert late.packets == [*bootstrap, live]


def test_empty_cache_activation_diagnostics_record_current_behavior(caplog):
    protocol, _rewriter, _ha, late = _protocol()

    with caplog.at_level(
        logging.INFO,
        logger="custom_components.comelit.h264_recovery",
    ):
        assert protocol.activate_output_port(18099) is True

    assert late.packets == []
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "output_sink_activation port=18099" in text
    assert "bootstrap_packets=0" in text
    assert "bootstrap_has_sps=false" in text
    assert "bootstrap_has_pps=false" in text
    assert "bootstrap_has_complete_idr=false" in text
    assert "activation_result=activated" in text
    assert "output_sink_bootstrap_sent port=18099 attempted_packets=0" in text


def test_bootstrap_diagnostics_report_stap_sps_pps_and_complete_fua_idr():
    protocol, _rewriter, _ha, _late = _protocol()
    stap = _rtp_packet(140, 90_000, _stap_a(b"\x67\x64", b"\x68\xee"), marker=True)
    fragments = [
        _rtp_packet(141, 180_000, _fu_a(5, b"start", start=True)),
        _rtp_packet(142, 180_000, _fu_a(5, b"middle")),
        _rtp_packet(143, 180_000, _fu_a(5, b"end", end=True), marker=True),
    ]
    for packet in (stap, *fragments):
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    diagnostics = protocol._bootstrap_cache.diagnostics()

    assert diagnostics.has_sps is True
    assert diagnostics.has_pps is True
    assert diagnostics.has_complete_idr_au is True
    assert diagnostics.snapshot_packet_count == len(protocol._bootstrap_cache.snapshot())
    assert diagnostics.idr_au_packet_count == 3
    assert diagnostics.idr_ssrc == 0x12345678
    assert diagnostics.idr_timestamp == 180_000
    assert diagnostics.first_sequence == 141
    assert diagnostics.last_sequence == 143
    assert diagnostics.completed_idr_age_ms is not None


def test_bootstrap_diagnostics_report_incomplete_fua_idr_as_incomplete():
    protocol, _rewriter, _ha, _late = _protocol()
    for packet in (
        _rtp_packet(150, 90_000, b"\x67\x64", marker=True),
        _rtp_packet(151, 180_000, b"\x68\xee", marker=True),
        _rtp_packet(152, 270_000, _fu_a(5, b"start", start=True)),
    ):
        protocol.datagram_received(packet, ("127.0.0.1", 1))

    diagnostics = protocol._bootstrap_cache.diagnostics()

    assert diagnostics.has_sps is True
    assert diagnostics.has_pps is True
    assert diagnostics.has_complete_idr_au is False
    assert diagnostics.idr_au_packet_count == 0


def test_activation_twice_does_not_emit_second_bootstrap_send(caplog):
    protocol, _rewriter, _ha, _late = _protocol()
    protocol.datagram_received(
        _rtp_packet(160, 90_000, b"\x65\x88", marker=True),
        ("127.0.0.1", 1),
    )

    with caplog.at_level(
        logging.INFO,
        logger="custom_components.comelit.h264_recovery",
    ):
        assert protocol.activate_output_port(18099) is True
        assert protocol.activate_output_port(18099) is True

    messages = [record.getMessage() for record in caplog.records]
    assert sum("output_sink_bootstrap_sent port=18099" in msg for msg in messages) == 1
    assert any("activation_result=already_active" in msg for msg in messages)


def test_activation_markers_distinguish_ha_and_miniapp_ports(caplog):
    protocol, _rewriter, _ha, _late = _protocol()

    with caplog.at_level(
        logging.INFO,
        logger="custom_components.comelit.h264_recovery",
    ):
        assert protocol.activate_output_port(17999) is True
        assert protocol.activate_output_port(18099) is True

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "output_sink_activation port=17999" in text
    assert "activation_result=already_active" in text
    assert "output_sink_activation port=18099" in text
    assert "activation_result=activated" in text
    assert "output_sink_bootstrap_sent port=18099" in text
