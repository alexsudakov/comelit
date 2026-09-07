#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

MEDIA = Path(__file__).resolve().parents[1] / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_rtpc_target_id_static_contract as p73


class P73TargetIdAllocatorTests(unittest.TestCase):
    def test_normal_allocation_uses_current_counter_and_stores_next(self) -> None:
        state = p73.new_tunnel_state(0x1234)
        result = p73.allocate_target_id(state)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.target_id, 0x1234)
        self.assertEqual(result.low15_used, 0x1234)
        self.assertEqual(result.next_low15_counter, 0x1235)
        self.assertEqual(state.low15_counter, 0x1235)

    def test_sequential_allocation_from_runtime_seed(self) -> None:
        state = p73.new_tunnel_state(p73.seed_from_runtime_prng(0x9234))
        first, second, third = p73.allocate_many(state, 3)
        self.assertEqual([first.target_id, second.target_id, third.target_id], [0x1234, 0x1235, 0x1236])
        self.assertTrue(p73.sequential_ids_naturally_explained([first.target_id, second.target_id, third.target_id]))

    def test_low15_wraps_from_0x7fff_to_zero_and_skips_mgmt_zero(self) -> None:
        state = p73.new_tunnel_state(0x7FFF)
        first = p73.allocate_target_id(state)
        second = p73.allocate_target_id(state)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.target_id, 0x7FFF)
        self.assertEqual(second.low15_used, 1)
        self.assertEqual(second.target_id, 1)
        self.assertEqual(second.collisions, 1)

    def test_collision_skipping_walks_in_use_channel_ids(self) -> None:
        state = p73.AllocatorState(low15_counter=5, in_use_ids={5, 6, 7})
        result = p73.allocate_target_id(state)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.target_id, 8)
        self.assertEqual(result.collisions, 3)
        self.assertEqual(state.low15_counter, 9)

    def test_maximum_search_failure_advances_counter_and_allocates_nothing(self) -> None:
        occupied = set(range(p73.SEARCH_BUDGET))
        state = p73.AllocatorState(low15_counter=0, in_use_ids=occupied)
        result = p73.allocate_target_id(state)
        self.assertIsNone(result)
        self.assertEqual(state.low15_counter, p73.SEARCH_BUDGET)
        self.assertEqual(state.in_use_ids, occupied)

    def test_high_component_is_preserved_in_candidate_bit_15(self) -> None:
        low_state = p73.AllocatorState(low15_counter=0x0022, high_halfword=0)
        high_state = p73.AllocatorState(low15_counter=0x0022, high_halfword=1)
        high_odd_state = p73.AllocatorState(low15_counter=0x0022, high_halfword=0xFFFF)
        self.assertEqual(p73.allocate_target_id(low_state).target_id, 0x0022)  # type: ignore[union-attr]
        self.assertEqual(p73.allocate_target_id(high_state).target_id, 0x8022)  # type: ignore[union-attr]
        self.assertEqual(p73.allocate_target_id(high_odd_state).target_id, 0x8022)  # type: ignore[union-attr]

    def test_two_consecutive_allocations_are_distinct_without_fixed_start(self) -> None:
        for seed in (1, 0x2345, 0x7FFE):
            state = p73.new_tunnel_state(seed)
            first, second = p73.allocate_many(state, 2)
            self.assertNotEqual(first.target_id, second.target_id)
            self.assertEqual(((second.target_id - first.target_id) & 0xFFFF), 1)

    def test_serializer_linkage_puts_allocated_id_at_open_12_14(self) -> None:
        state = p73.new_tunnel_state(0x3456)
        body = p73.build_rtpc_open_from_allocator(state)
        self.assertEqual(len(body), 15)
        self.assertEqual(body[8:12], b"RTPC")
        self.assertEqual(body[12:14], (0x3456).to_bytes(2, "little"))
        self.assertEqual(body[14], 1)

    def test_no_assumption_of_fixed_global_start_value(self) -> None:
        a = p73.new_tunnel_state(0x0100)
        b = p73.new_tunnel_state(0x0200)
        self.assertNotEqual(p73.allocate_target_id(a).target_id, p73.allocate_target_id(b).target_id)  # type: ignore[union-attr]
        text = p73.report()
        self.assertIn("RTPC_TARGET_ID_START_VALUE=RUNTIME_STATE_DEPENDENT", text)
        self.assertNotIn("7459", text)
        self.assertNotIn("26395", text)

    def test_zero_can_be_allocated_only_when_no_zero_id_is_in_use(self) -> None:
        generic = p73.AllocatorState(low15_counter=0, in_use_ids=set())
        with_mgmt = p73.new_tunnel_state(0)
        self.assertEqual(p73.allocate_target_id(generic).target_id, 0)  # type: ignore[union-attr]
        self.assertEqual(p73.allocate_target_id(with_mgmt).target_id, 1)  # type: ignore[union-attr]

    def test_cli_default_and_bad_artifact_fail_closed(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p73.main([]), 0)
        self.assertIn("RTPC_TARGET_ID_ALLOCATION_CONTRACT=PROVEN_STATIC", out.getvalue())
        self.assertIn("LIVE_TRANSMISSION_AUTHORIZED=false", out.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.so"
            bad.write_bytes(b"not the proprietary library")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(p73.main(["--libvipcomelit-so", str(bad)]), 2)
            self.assertIn("SO_VIPCOMELIT_SHA256_GATE=FAIL", out.getvalue())

    def test_output_leaks_no_payloads_or_network_authorization(self) -> None:
        text = p73.report()
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("DOOR_ACTION_SENT=false", text)
        self.assertIn("MEDIA_SIGNALING_SENT=false", text)
        body = p73.serialize_open(b"RTPC", 0x1234)
        self.assertNotIn(body.hex(), text)


if __name__ == "__main__":
    unittest.main()
