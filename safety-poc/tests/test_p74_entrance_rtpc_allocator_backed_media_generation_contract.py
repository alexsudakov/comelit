#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import inspect
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_rtpc_allocator_backed_media_generation_contract as p74
import entrance_rtpc_target_id_static_contract as p73


class P74AllocatorBackedMediaGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.role_a = b"ADDRROLEA"
        self.role_b = b"ADDRROLEB"
        self.common = dict(
            ctpp_seq_000a=0x22000000,
            ctpp_seq_001a=0x33000000,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )

    def build(self, state: p73.AllocatorState) -> p74.AllocatorBackedClientMediaBodies:
        return p74.build_from_allocator_state(state, **self.common)

    def test_normal_two_allocations_compose_all_bodies(self) -> None:
        result = self.build(p73.new_tunnel_state(0x1234))
        self.assertEqual(result.allocation_1.target_id, 0x1234)
        self.assertEqual(result.allocation_2.target_id, 0x1235)
        self.assertEqual(len(result.rtpc_open_1), 15)
        self.assertEqual(len(result.rtpc_open_2), 15)
        self.assertEqual(len(result.client_000a), 44)
        self.assertEqual(len(result.client_001a), 60)

    def test_no_collision_sequential_relation_is_observed_not_required(self) -> None:
        result = self.build(p73.new_tunnel_state(0x2345))
        first = result.allocation_1.target_id
        second = result.allocation_2.target_id
        self.assertNotEqual(first, second)
        delta = (second - first) & 0xFFFF
        if delta == 1:
            self.assertTrue(p73.sequential_ids_naturally_explained([first, second]))

    def test_collision_before_first_allocation_skips_and_binds_000a(self) -> None:
        state = p73.AllocatorState(low15_counter=0x0100, in_use_ids={0x0100})
        result = self.build(state)
        self.assertEqual(result.allocation_1.target_id, 0x0101)
        self.assertEqual(result.allocation_1.collisions, 1)
        self.assertEqual(result.rtpc_open_1[12:14], (0x0101).to_bytes(2, "little"))
        self.assertEqual(result.client_000a[16:18], (0x0101).to_bytes(2, "little"))

    def test_collision_between_first_and_second_allocation_does_not_require_plus_one(self) -> None:
        state = p73.AllocatorState(low15_counter=0x0200, in_use_ids={0x0201})
        result = self.build(state)
        self.assertEqual(result.allocation_1.target_id, 0x0200)
        self.assertEqual(result.allocation_2.target_id, 0x0202)
        self.assertEqual(((result.allocation_2.target_id - result.allocation_1.target_id) & 0xFFFF), 2)
        self.assertEqual(result.client_001a[16:18], (0x0202).to_bytes(2, "little"))

    def test_low15_wrap_preserves_mgmt_collision_semantics(self) -> None:
        result = self.build(p73.new_tunnel_state(0x7FFF))
        self.assertEqual(result.allocation_1.target_id, 0x7FFF)
        self.assertEqual(result.allocation_2.low15_used, 1)
        self.assertEqual(result.allocation_2.target_id, 1)
        self.assertEqual(result.allocation_2.collisions, 1)

    def test_runtime_constructor_state_skips_mgmt_id_zero(self) -> None:
        result = p74.build_from_runtime_rand_value(0, **self.common)
        self.assertEqual(result.allocation_1.target_id, 1)
        self.assertEqual(result.allocation_1.collisions, 1)
        self.assertEqual(result.rtpc_open_1[12:14], (1).to_bytes(2, "little"))

    def test_allocator_exhaustion_fails_closed(self) -> None:
        state = p73.AllocatorState(low15_counter=1, in_use_ids={0, *range(2, 0x8000)})
        with self.assertRaises(RuntimeError):
            self.build(state)

    def test_open_1_binds_to_allocation_1(self) -> None:
        result = self.build(p73.new_tunnel_state(0x3456))
        self.assertEqual(int.from_bytes(result.rtpc_open_1[12:14], "little"), result.allocation_1.target_id)

    def test_open_2_binds_to_allocation_2(self) -> None:
        result = self.build(p73.new_tunnel_state(0x3456))
        self.assertEqual(int.from_bytes(result.rtpc_open_2[12:14], "little"), result.allocation_2.target_id)

    def test_client_000a_binds_to_allocation_1(self) -> None:
        result = self.build(p73.new_tunnel_state(0x4567))
        self.assertEqual(int.from_bytes(result.client_000a[16:18], "little"), result.allocation_1.target_id)

    def test_client_001a_binds_to_allocation_2(self) -> None:
        result = self.build(p73.new_tunnel_state(0x4567))
        self.assertEqual(int.from_bytes(result.client_001a[16:18], "little"), result.allocation_2.target_id)

    def test_report_emits_no_runtime_target_values_or_raw_payloads(self) -> None:
        text = p74.report()
        for forbidden in ("1234", "1235", "ADDRROLEA", "ADDRROLEB", "abcd", "RTPC0001"):
            self.assertNotIn(forbidden, text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("MEDIA_PAYLOAD_EMITTED=false", text)
        self.assertIn("RTPC_TARGET_IDS_CALLER_SUPPLIED=false", text)

    def test_public_composition_api_has_no_caller_supplied_target_ids(self) -> None:
        for name in ("build_from_allocator_state", "build_from_runtime_rand_value"):
            params = inspect.signature(getattr(p74, name)).parameters
            forbidden = {"rtpc_target_1", "rtpc_target_2", "target_id_1", "target_id_2", "first_id", "second_id"}
            self.assertTrue(forbidden.isdisjoint(params))
        result = p74.build_from_runtime_rand_value(0x9234, **self.common)
        self.assertEqual(result.allocation_1.target_id, 0x1234)

    def test_report_live_and_network_markers_are_false(self) -> None:
        text = p74.report()
        for marker in (
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "NETWORK_IO_PERFORMED=false",
            "DNS_LOOKUP_PERFORMED=false",
            "P2P_ICE_STUN_TURN_PERFORMED=false",
            "PSEUDOTCP_PERFORMED=false",
            "CTPP_SIGNALING_SENT=false",
            "RTPC_SIGNALING_SENT=false",
            "DOOR_ACTION_SENT=false",
            "CAMERA_MEDIA_SESSION_STARTED=false",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("LIVE_TRANSMISSION_AUTHORIZED=true", text)
        self.assertNotIn("NETWORK_IO_PERFORMED=true", text)

    def test_main_is_deterministic_offline_report(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p74.main(), 0)
        self.assertEqual(out.getvalue().strip(), p74.report())
        self.assertIn("OUTBOUND_RTPC_MEDIA_BODY_GENERATION_CONTRACT=PROVEN_OFFLINE_COMPOSED", out.getvalue())


if __name__ == "__main__":
    unittest.main()
