#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_rtpc_client_media_generation_contract as p72


class P72GenerationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.role_a = b"ADDRROLEA"
        self.role_b = b"ADDRROLEB"
        self.first = 0x1234
        self.second = 0x1235

    def test_rtpc_open_uses_proven_p70_transport(self) -> None:
        body = p72.build_rtpc_open(self.first)
        self.assertEqual(len(body), 15)
        self.assertEqual(body[8:12], b"RTPC")
        self.assertEqual(int.from_bytes(body[12:14], "little"), self.first)
        self.assertEqual(body[14], 1)

    def test_two_rtpc_opens_bind_distinct_sequential_runtime_ids(self) -> None:
        result = p72.build_client_media_bodies(
            rtpc_target_1=self.first,
            rtpc_target_2=self.second,
            previous_sequence_for_000a=0x22000000,
            previous_sequence_for_001a=0x33000000,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )
        self.assertEqual(result.rtpc_open_1[12:14], self.first.to_bytes(2, "little"))
        self.assertEqual(result.rtpc_open_2[12:14], self.second.to_bytes(2, "little"))
        self.assertEqual(result.client_000a[16:18], result.rtpc_open_1[12:14])
        self.assertEqual(result.client_001a[16:18], result.rtpc_open_2[12:14])
        self.assertNotEqual(result.client_000a[16:18], result.client_001a[16:18])

    def test_client_000a_matches_cross_validated_structure(self) -> None:
        body = p72.build_client_000a(
            previous_client_ctpp_sequence=0x22000000,
            rtpc_target_id=self.first,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )
        self.assertEqual(len(body), 44)
        self.assertEqual(int.from_bytes(body[0:2], "little"), 0x1840)
        self.assertEqual(int.from_bytes(body[2:6], "little"), 0x22000000)
        self.assertEqual(int.from_bytes(body[6:8], "big"), 0x000A)
        self.assertEqual(int.from_bytes(body[8:10], "big"), 0x0011)
        self.assertEqual(body[10:16], bytes((0x18, 0x02, 0, 0, 0, 0)))
        self.assertEqual(body[16:18], self.first.to_bytes(2, "little"))
        self.assertEqual(body[18:20], b"\x00\x00")
        self.assertEqual(body[20:24], b"\xff" * 4)
        self.assertEqual(body[24:33], self.role_b)
        self.assertEqual(body[33], 0)
        self.assertEqual(body[34:43], self.role_a)
        self.assertEqual(body[43], 0)

    def test_client_001a_matches_cross_validated_structure_and_geometry(self) -> None:
        body = p72.build_client_001a(
            previous_client_ctpp_sequence=0x33000000,
            rtpc_target_id=self.second,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )
        self.assertEqual(len(body), 60)
        self.assertEqual(int.from_bytes(body[0:2], "little"), 0x1840)
        self.assertEqual(int.from_bytes(body[2:6], "little"), 0x33010000)
        self.assertEqual(int.from_bytes(body[6:8], "big"), 0x001A)
        self.assertEqual(int.from_bytes(body[8:10], "big"), 0x0011)
        self.assertEqual(body[10:16], bytes((0x14, 0x32, 0, 0, 0, 0)))
        self.assertEqual(body[16:18], self.second.to_bytes(2, "little"))
        self.assertEqual(body[18:24], b"\xff\xff\x00\x00\x00\x00")
        geometry = tuple(int.from_bytes(body[offset:offset + 2], "little") for offset in (24, 26, 28, 30, 32))
        self.assertEqual(geometry, p72.REFERENCE_GEOMETRY)
        self.assertEqual(body[34:36], b"\x00\x00")
        self.assertEqual(body[36:40], b"\xff" * 4)
        self.assertEqual(body[40:49], self.role_b)
        self.assertEqual(body[49], 0)
        self.assertEqual(body[50:59], self.role_a)
        self.assertEqual(body[59], 0)

    def test_001a_sequence_wraps_as_uint32(self) -> None:
        body = p72.build_client_001a(
            previous_client_ctpp_sequence=0xFFFF8000,
            rtpc_target_id=self.second,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )
        self.assertEqual(int.from_bytes(body[2:6], "little"), 0x00008000)

    def test_invalid_or_equal_rtpc_ids_fail_closed(self) -> None:
        common = dict(
            previous_sequence_for_000a=1,
            previous_sequence_for_001a=2,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )
        with self.assertRaises(ValueError):
            p72.build_client_media_bodies(rtpc_target_1=0, rtpc_target_2=1, **common)
        with self.assertRaises(ValueError):
            p72.build_client_media_bodies(rtpc_target_1=1, rtpc_target_2=1, **common)
        with self.assertRaises(ValueError):
            p72.build_client_media_bodies(rtpc_target_1=1, rtpc_target_2=3, **common)

    def test_nonsequential_ids_are_allowed_only_for_synthetic_analysis(self) -> None:
        result = p72.build_client_media_bodies(
            rtpc_target_1=1,
            rtpc_target_2=3,
            previous_sequence_for_000a=1,
            previous_sequence_for_001a=2,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
            require_capture_sequential_ids=False,
        )
        self.assertEqual(result.rtpc_open_1[14], 1)
        self.assertEqual(result.rtpc_open_2[14], 1)

    def test_address_role_validation_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            p72.build_client_000a(
                previous_client_ctpp_sequence=1,
                rtpc_target_id=1,
                address_role_a=b"short",
                address_role_b=self.role_b,
            )
        with self.assertRaises(ValueError):
            p72.build_client_001a(
                previous_client_ctpp_sequence=1,
                rtpc_target_id=2,
                address_role_a=self.role_a,
                address_role_b=self.role_a,
            )

    def test_unpromoted_geometry_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            p72.build_client_001a(
                previous_client_ctpp_sequence=1,
                rtpc_target_id=2,
                address_role_a=self.role_a,
                address_role_b=self.role_b,
                geometry=(640, 480, 320, 240, 16),
            )

    def test_report_keeps_allocator_and_live_transmission_unproven(self) -> None:
        text = p72.report()
        self.assertIn("RTPC_TARGET_ID_ALLOCATION_CONTRACT=CALLER_SUPPLIED_NOT_PROVEN", text)
        self.assertIn("RTPC_TARGET_ID_START_VALUE=NOT_PROVEN", text)
        self.assertIn("LIVE_TRANSMISSION_AUTHORIZED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("DOOR_ACTION_SENT=false", text)

    def test_report_does_not_emit_runtime_values_or_payload(self) -> None:
        text = p72.report()
        for forbidden in ("1234", "1235", self.role_a.decode(), self.role_b.decode()):
            self.assertNotIn(forbidden, text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("MEDIA_PAYLOAD_EMITTED=false", text)

    def test_main_is_deterministic_offline_report(self) -> None:
        self.assertEqual(p72.report(), p72.report())
        self.assertEqual(p72.main(), 0)


if __name__ == "__main__":
    unittest.main()
