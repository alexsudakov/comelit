#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "custom_components" / "comelit" / "h264_recovery.py"
spec = importlib.util.spec_from_file_location("h264_recovery", MODULE_PATH)
h264_recovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h264_recovery
assert spec.loader is not None
spec.loader.exec_module(h264_recovery)


class Bits:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def bit(self, value: int) -> None:
        self.bits.append(1 if value else 0)

    def bits_value(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bit((value >> shift) & 1)

    def ue(self, value: int) -> None:
        code_num = value + 1
        width = code_num.bit_length()
        for _ in range(width - 1):
            self.bit(0)
        self.bits_value(code_num, width)

    def rbsp(self) -> bytes:
        self.bit(1)
        while len(self.bits) % 8:
            self.bit(0)
        out = bytearray(len(self.bits) // 8)
        for idx, bit in enumerate(self.bits):
            out[idx // 8] |= bit << (7 - (idx % 8))
        return bytes(out)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.bit_pos = 0

    def bit(self) -> int:
        if self.bit_pos >= len(self.data) * 8:
            raise AssertionError("bitstream exhausted")
        value = (self.data[self.bit_pos // 8] >> (7 - self.bit_pos % 8)) & 1
        self.bit_pos += 1
        return value

    def bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.bit()
        return value

    def ue(self) -> int:
        zeros = 0
        while self.bit() == 0:
            zeros += 1
        suffix = self.bits(zeros) if zeros else 0
        return (1 << zeros) - 1 + suffix


def nal(nal_type: int, body: bytes = b"\x80") -> bytes:
    return bytes([nal_type]) + body


def slice_nal(slice_type: int, *, first_mb: int = 0, nal_type: int = 1) -> bytes:
    bits = Bits()
    bits.ue(first_mb)
    bits.ue(slice_type)
    return nal(nal_type, bits.rbsp())


def fu_a_start(nal_payload: bytes) -> bytes:
    return b"\x7c" + bytes([0x80 | (nal_payload[0] & 0x1F)]) + nal_payload[1:]


def stap_a(*nals: bytes) -> bytes:
    payload = bytearray(b"\x18")
    for item in nals:
        payload.extend(struct.pack("!H", len(item)))
        payload.extend(item)
    return bytes(payload)


def rtp(
    seq: int,
    payload: bytes,
    *,
    timestamp: int = 9000,
    ssrc: int = 0x01020304,
    pt: int = 99,
    marker: bool = False,
    extension: bool = False,
) -> bytes:
    first = 0x80 | (0x10 if extension else 0)
    header = bytearray(
        struct.pack("!BBHII", first, (0x80 if marker else 0) | pt, seq, timestamp, ssrc)
    )
    if extension:
        header.extend(struct.pack("!HHI", 0xBEDE, 1, 0xAABBCCDD))
    return bytes(header) + payload


def seq(packet: bytes) -> int:
    return struct.unpack_from("!H", packet, 2)[0]


def marker(packet: bytes) -> bool:
    return bool(packet[1] & 0x80)


def payload(packet: bytes) -> bytes:
    offset = 12
    if packet[0] & 0x10:
        words = struct.unpack_from("!H", packet, offset + 2)[0]
        offset += 4 + words * 4
    return packet[offset:]


def parse_recovery_sei(nal_bytes: bytes) -> tuple[int, int, int, int]:
    assert nal_bytes[0] & 0x1F == 6
    rbsp = nal_bytes[1:]
    pos = 0
    payload_type = 0
    while rbsp[pos] == 0xFF:
        payload_type += 255
        pos += 1
    payload_type += rbsp[pos]
    pos += 1
    payload_size = 0
    while rbsp[pos] == 0xFF:
        payload_size += 255
        pos += 1
    payload_size += rbsp[pos]
    pos += 1
    assert payload_type == 6
    reader = Reader(rbsp[pos : pos + payload_size])
    recovery_frame_cnt = reader.ue()
    exact_match_flag = reader.bit()
    broken_link_flag = reader.bit()
    changing_slice_group_idc = reader.bits(2)
    return (
        recovery_frame_cnt,
        exact_match_flag,
        broken_link_flag,
        changing_slice_group_idc,
    )


class P116R24RecoveryRewriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rewriter = h264_recovery.H264RecoveryRewriter()

    def rewrite(self, *packets: bytes) -> list[bytes]:
        out: list[bytes] = []
        for packet in packets:
            out.extend(self.rewriter.rewrite_rtp_packet(packet))
        return out

    def context(self, *, timestamp: int = 9000, ssrc: int = 0x01020304) -> tuple[bytes, bytes]:
        return (
            rtp(10, nal(7), timestamp=timestamp, ssrc=ssrc),
            rtp(11, nal(8), timestamp=timestamp, ssrc=ssrc),
        )

    def test_single_nal_sps_pps_non_idr_i_injects_once(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2)))
        self.assertEqual(len(out), 4)
        self.assertEqual(payload(out[2])[0] & 0x1F, 6)
        self.assertEqual(payload(out[3]), slice_nal(2))
        self.assertEqual(self.rewriter.injected_count, 1)

    def test_fu_a_start_non_idr_i_injects_once_with_context(self) -> None:
        sps, pps = self.context()
        original = fu_a_start(slice_nal(2))
        out = self.rewrite(sps, pps, rtp(12, original))
        self.assertEqual(len(out), 4)
        self.assertEqual(payload(out[2])[0] & 0x1F, 6)
        self.assertEqual(payload(out[3]), original)

    def test_stap_a_sps_pps_before_non_idr_i_injects_once(self) -> None:
        original = stap_a(nal(7), nal(8), slice_nal(2))
        out = self.rewrite(rtp(100, original))
        self.assertEqual(len(out), 2)
        self.assertEqual(payload(out[0])[0] & 0x1F, 6)
        self.assertEqual(payload(out[1]), original)

    def test_true_idr_does_not_inject(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2, nal_type=5)))
        self.assertEqual(len(out), 3)
        self.assertEqual(self.rewriter.idr_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_p_slice_does_not_inject(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(0)))
        self.assertEqual(len(out), 3)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_i_slice_without_sps_does_not_inject(self) -> None:
        out = self.rewrite(rtp(11, nal(8)), rtp(12, slice_nal(2)))
        self.assertEqual(len(out), 2)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_i_slice_without_pps_does_not_inject(self) -> None:
        out = self.rewrite(rtp(10, nal(7)), rtp(12, slice_nal(2)))
        self.assertEqual(len(out), 2)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_slice_exp_golomb_passes_through(self) -> None:
        sps, pps = self.context()
        bad = nal(1, b"\x00")
        out = self.rewrite(sps, pps, rtp(12, bad))
        self.assertEqual(payload(out[-1]), bad)
        self.assertEqual(self.rewriter.malformed_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_stap_a_length_passes_through(self) -> None:
        bad = b"\x18\x00\x10\x67"
        out = self.rewrite(rtp(1, bad))
        self.assertEqual(payload(out[0]), bad)
        self.assertEqual(self.rewriter.malformed_count, 1)

    def test_existing_recovery_point_sei_suppresses_duplicate(self) -> None:
        sps, pps = self.context()
        sei = h264_recovery.build_recovery_point_sei_nal()
        out = self.rewrite(sps, pps, rtp(12, sei), rtp(13, slice_nal(2)))
        self.assertEqual(len(out), 4)
        self.assertEqual(self.rewriter.existing_recovery_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_unsupported_aggregation_before_i_slice_suppresses_injection(self) -> None:
        sps, pps = self.context()
        unsupported = b"\x19\x01\x02"
        packets = [sps, pps, rtp(12, unsupported), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.unsupported_packet_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_fragmented_sei_before_i_slice_suppresses_injection(self) -> None:
        sps, pps = self.context()
        fragmented_sei = fu_a_start(nal(6, b"\x06\x01"))
        packets = [sps, pps, rtp(12, fragmented_sei), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_sei_before_i_slice_suppresses_injection(self) -> None:
        sps, pps = self.context()
        malformed_sei = nal(6, b"\x06\x02\x80")
        packets = [sps, pps, rtp(12, malformed_sei), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_stap_a_before_i_slice_suppresses_injection(self) -> None:
        sps, pps = self.context()
        malformed_stap = b"\x18\x00\x10\x67"
        packets = [sps, pps, rtp(12, malformed_stap), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.malformed_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_single_nal_sei_counts_and_passes_through(self) -> None:
        sps, pps = self.context()
        malformed_sei = nal(6, b"\x06\x02\x80")
        packets = [sps, pps, rtp(12, malformed_sei), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.malformed_count, 1)
        self.assertEqual(self.rewriter.last_error, "malformed_sei")
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_stap_a_sei_counts_once_and_passes_through(self) -> None:
        sps, pps = self.context()
        malformed_stap = stap_a(nal(6, b"\x06\x02\x80"), slice_nal(2))
        packets = [sps, pps, rtp(12, malformed_stap)]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.malformed_count, 1)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_malformed_sei_fail_closed_scope_is_timestamp_and_ssrc(self) -> None:
        ts1_sps, ts1_pps = self.context(timestamp=1, ssrc=1)
        ts2_sps, ts2_pps = self.context(timestamp=2, ssrc=1)
        other_sps, other_pps = self.context(timestamp=1, ssrc=2)
        packets = [
            ts1_sps,
            ts1_pps,
            rtp(12, nal(6, b"\x06\x02\x80"), timestamp=1, ssrc=1),
            rtp(13, slice_nal(2), timestamp=1, ssrc=1),
            ts2_sps,
            ts2_pps,
            rtp(22, slice_nal(2), timestamp=2, ssrc=1),
            other_sps,
            other_pps,
            rtp(12, slice_nal(2), timestamp=1, ssrc=2),
        ]
        out = self.rewrite(*packets)
        self.assertEqual(self.rewriter.malformed_count, 1)
        self.assertEqual(self.rewriter.last_error, "malformed_sei")
        self.assertEqual(self.rewriter.injected_count, 2)
        self.assertEqual(
            [seq(packet) for packet in out],
            [10, 11, 12, 13, 10, 11, 22, 23, 10, 11, 12, 13],
        )

    def test_unprovable_recovery_signal_scope_is_timestamp_and_ssrc(self) -> None:
        ts1_sps, ts1_pps = self.context(timestamp=1, ssrc=1)
        ts2_sps, ts2_pps = self.context(timestamp=2, ssrc=1)
        other_sps, other_pps = self.context(timestamp=1, ssrc=2)
        packets = [
            ts1_sps,
            ts1_pps,
            rtp(12, b"\x19\x01\x02", timestamp=1, ssrc=1),
            rtp(13, slice_nal(2), timestamp=1, ssrc=1),
            ts2_sps,
            ts2_pps,
            rtp(22, slice_nal(2), timestamp=2, ssrc=1),
            other_sps,
            other_pps,
            rtp(12, b"\x19\x01\x02", timestamp=1, ssrc=1),
            rtp(12, slice_nal(2), timestamp=1, ssrc=2),
        ]
        out = self.rewrite(*packets)
        original_payloads = [payload(packet) for packet in packets]
        output_original_payloads = [
            payload(packet)
            for packet in out
            if not (payload(packet)[0] & 0x1F == 6 and packet not in packets)
        ]
        self.assertEqual(output_original_payloads, original_payloads)
        self.assertEqual(self.rewriter.injected_count, 2)
        self.assertEqual(
            [seq(packet) for packet in out],
            [10, 11, 12, 13, 10, 11, 22, 23, 10, 11, 13, 12, 13],
        )

    def test_unsupported_h264_aggregation_type_is_unchanged(self) -> None:
        unsupported = b"\x19\x01\x02"
        out = self.rewrite(rtp(1, unsupported))
        self.assertEqual(payload(out[0]), unsupported)
        self.assertEqual(self.rewriter.unsupported_packet_count, 1)

    def test_nal_type_zero_before_vcl_is_unsupported_and_fail_closed(self) -> None:
        sps, pps = self.context()
        type_zero = nal(0, b"\x12\x34")
        packets = [sps, pps, rtp(12, type_zero), rtp(13, slice_nal(2))]
        out = self.rewrite(*packets)
        self.assertEqual(out, packets)
        self.assertEqual(self.rewriter.unsupported_packet_count, 1)
        self.assertEqual(self.rewriter.malformed_count, 0)
        self.assertEqual(self.rewriter.injected_count, 0)

    def test_nal_type_zero_fail_closed_scope_is_timestamp_and_ssrc(self) -> None:
        ts1_sps, ts1_pps = self.context(timestamp=1, ssrc=1)
        ts2_sps, ts2_pps = self.context(timestamp=2, ssrc=1)
        other_sps, other_pps = self.context(timestamp=1, ssrc=2)
        packets = [
            ts1_sps,
            ts1_pps,
            rtp(12, nal(0, b"\x12\x34"), timestamp=1, ssrc=1),
            rtp(13, slice_nal(2), timestamp=1, ssrc=1),
            ts2_sps,
            ts2_pps,
            rtp(22, slice_nal(2), timestamp=2, ssrc=1),
            other_sps,
            other_pps,
            rtp(12, slice_nal(2), timestamp=1, ssrc=2),
        ]
        out = self.rewrite(*packets)
        self.assertEqual(self.rewriter.unsupported_packet_count, 1)
        self.assertEqual(self.rewriter.malformed_count, 0)
        self.assertEqual(self.rewriter.injected_count, 2)
        self.assertEqual(
            [seq(packet) for packet in out],
            [10, 11, 12, 13, 10, 11, 22, 23, 10, 11, 12, 13],
        )

    def test_rtp_extension_preserved_on_inserted_and_original_packets(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2), extension=True))
        self.assertTrue(out[2][0] & 0x10)
        self.assertTrue(out[3][0] & 0x10)
        self.assertEqual(out[2][12:20], out[3][12:20])

    def test_original_marker_is_preserved(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2), marker=True))
        self.assertTrue(marker(out[-1]))

    def test_inserted_marker_is_false(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2), marker=True))
        self.assertFalse(marker(out[-2]))

    def test_timestamp_payload_type_and_ssrc_are_preserved_semantically(self) -> None:
        sps, pps = self.context(timestamp=12345, ssrc=0x11111111)
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2), timestamp=12345, ssrc=0x11111111))
        for packet in out:
            self.assertEqual(packet[1] & 0x7F, 99)
            self.assertEqual(struct.unpack_from("!I", packet, 4)[0], 12345)
            self.assertEqual(struct.unpack_from("!I", packet, 8)[0], 0x11111111)

    def test_original_payload_bytes_are_identical(self) -> None:
        sps, pps = self.context()
        original = slice_nal(2)
        out = self.rewrite(sps, pps, rtp(12, original))
        self.assertEqual(payload(out[-1]), original)

    def test_contiguous_sequence_mapping(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2)), rtp(13, nal(1, b"\x80")))
        self.assertEqual([seq(packet) for packet in out], [10, 11, 12, 13, 14])

    def test_packet_loss_gap_is_preserved(self) -> None:
        sps, pps = self.context()
        out = self.rewrite(sps, pps, rtp(12, slice_nal(2)), rtp(15, nal(1, b"\x80")))
        self.assertEqual([seq(packet) for packet in out], [10, 11, 12, 13, 16])

    def test_16_bit_sequence_wrap(self) -> None:
        sps = rtp(0xFFFE, nal(7))
        pps = rtp(0xFFFF, nal(8))
        out = self.rewrite(sps, pps, rtp(0, slice_nal(2)), rtp(1, nal(1, b"\x80")))
        self.assertEqual([seq(packet) for packet in out], [0xFFFE, 0xFFFF, 0, 1, 2])

    def test_multiple_injections_accumulate_offset(self) -> None:
        sps, pps = self.context(timestamp=1)
        sps2, pps2 = self.context(timestamp=2)
        out = self.rewrite(
            sps,
            pps,
            rtp(12, slice_nal(2), timestamp=1),
            rtp(20, sps2[12:], timestamp=2),
            rtp(21, pps2[12:], timestamp=2),
            rtp(22, slice_nal(2), timestamp=2),
            rtp(23, nal(1, b"\x80"), timestamp=2),
        )
        self.assertEqual(self.rewriter.injected_count, 2)
        self.assertEqual([seq(packet) for packet in out], [10, 11, 12, 13, 21, 22, 23, 24, 25])

    def test_state_resets_on_rtp_timestamp_change(self) -> None:
        sps, pps = self.context(timestamp=1)
        out = self.rewrite(
            sps,
            pps,
            rtp(12, slice_nal(2), timestamp=1),
            rtp(13, slice_nal(2), timestamp=2),
        )
        self.assertEqual(self.rewriter.injected_count, 1)
        self.assertEqual(len(out), 5)

    def test_independent_ssrc_state(self) -> None:
        sps, pps = self.context(ssrc=1)
        out = self.rewrite(
            sps,
            pps,
            rtp(12, slice_nal(2), ssrc=1),
            rtp(12, slice_nal(2), ssrc=2),
        )
        self.assertEqual(self.rewriter.injected_count, 1)
        self.assertEqual([seq(packet) for packet in out[-3:]], [12, 13, 12])

    def test_generated_sei_semantics_match_contract(self) -> None:
        self.assertEqual(
            parse_recovery_sei(h264_recovery.build_recovery_point_sei_nal()),
            (0, 0, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
