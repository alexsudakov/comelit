#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_rtpc_control_media_state_contract as p75
import entrance_rtpc_target_id_static_contract as p73
from entrance_device_video_ack_pcap_forensic import VipFrame


PCAP = Path("/home/hermes/comelit-p70-codex/input/pcap/self_activation.pcap")


def open_body(target: int, trailer: int = 1, name: bytes = b"RTPC") -> bytes:
    return (
        b"\xcd\xab\x01\x00\x07\x00\x00\x00"
        + name
        + target.to_bytes(2, "little")
        + bytes((trailer,))
    )


def response_body(target: int) -> bytes:
    return p75.build_rtpc_response(target)


def frame(direction: str, packet: int, body: bytes) -> VipFrame:
    return VipFrame(direction, packet, packet, float(packet), 0, bytes(body))


def p68_style_fixture() -> list[VipFrame]:
    return [
        frame("DEVICE_TO_CLIENT", 205, open_body(0x5678)),
        frame("CLIENT_TO_DEVICE", 206, open_body(0x1234)),
        frame("CLIENT_TO_DEVICE", 206, open_body(0x1235)),
        frame("DEVICE_TO_CLIENT", 207, response_body(0x1234)),
        frame("CLIENT_TO_DEVICE", 208, response_body(0x5678)),
        frame("DEVICE_TO_CLIENT", 209, response_body(0x1235)),
    ]


class P75RtpcControlMediaStateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.role_a = b"ADDRROLEA"
        self.role_b = b"ADDRROLEB"
        self.common = dict(
            ctpp_seq_000a=0x22000000,
            ctpp_seq_001a=0x33000000,
            address_role_a=self.role_a,
            address_role_b=self.role_b,
        )

    def machine_with_client_bodies(self, seed: int = 0x1234):
        machine = p75.RtpcControlMediaStateMachine()
        bodies = machine.generate_client_exchange(p73.new_tunnel_state(seed), **self.common)
        return machine, bodies

    def test_canonical_synthetic_successful_exchange(self) -> None:
        machine = p75.RtpcControlMediaStateMachine()
        machine.observe_device_open(open_body(0x5678))
        bodies = machine.generate_client_exchange(p73.new_tunnel_state(0x1234), **self.common)
        machine.observe_device_response(response_body(bodies.allocation_2.target_id))
        machine.observe_client_response_to_device_open(response_body(0x5678))
        machine.generate_client_000a()
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        machine.generate_client_001a()
        self.assertTrue(machine.is_complete())

    def test_allocator_collision_skip_before_first_client_open(self) -> None:
        machine, bodies = self.machine_with_client_bodies(0x0100)
        self.assertEqual(bodies.allocation_1.collisions, 0)
        state = p73.AllocatorState(low15_counter=0x0100, in_use_ids={0x0100})
        machine = p75.RtpcControlMediaStateMachine()
        bodies = machine.generate_client_exchange(state, **self.common)
        self.assertEqual(bodies.allocation_1.target_id, 0x0101)
        self.assertEqual(bodies.rtpc_open_1[12:14], (0x0101).to_bytes(2, "little"))

    def test_allocator_collision_skip_before_second_client_open(self) -> None:
        state = p73.AllocatorState(low15_counter=0x0200, in_use_ids={0x0201})
        machine = p75.RtpcControlMediaStateMachine()
        bodies = machine.generate_client_exchange(state, **self.common)
        self.assertEqual(bodies.allocation_1.target_id, 0x0200)
        self.assertEqual(bodies.allocation_2.target_id, 0x0202)
        self.assertEqual(bodies.allocation_2.collisions, 1)

    def test_response_pairing_independent_of_numeric_plus_one_relation(self) -> None:
        machine, bodies = self.machine_with_client_bodies(0x0200)
        self.assertEqual((bodies.allocation_2.target_id - bodies.allocation_1.target_id) & 0xFFFF, 1)
        state = p73.AllocatorState(low15_counter=0x0200, in_use_ids={0x0201})
        machine = p75.RtpcControlMediaStateMachine()
        bodies = machine.generate_client_exchange(state, **self.common)
        machine.observe_device_response(response_body(bodies.allocation_2.target_id))
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        self.assertIs(machine.snapshot.device_response_1_seen, p75.FactState.PAIRED)
        self.assertIs(machine.snapshot.device_response_2_seen, p75.FactState.PAIRED)

    def test_device_open_generates_client_response_from_that_target(self) -> None:
        machine = p75.RtpcControlMediaStateMachine()
        machine.observe_device_open(open_body(0x4567))
        self.assertEqual(machine.generate_client_response_to_device_open()[8:10], (0x4567).to_bytes(2, "little"))

    def test_p74_000a_001a_bindings_complete(self) -> None:
        machine, bodies = self.machine_with_client_bodies(0x3456)
        self.assertEqual(machine.generate_client_000a(), bodies.client_000a)
        self.assertEqual(machine.generate_client_001a(), bodies.client_001a)

    def test_synthetic_frames_from_p68_fixture_map_successfully(self) -> None:
        result = p75.validate_frames_observed_order(p68_style_fixture())
        self.assertTrue(result.observed_order_validated)
        self.assertEqual(result.client_open_count, 2)
        self.assertEqual(result.device_response_count, 2)
        self.assertEqual(result.client_response_count, 1)

    def test_real_pcap_cli_path_is_available_or_cleanly_absent(self) -> None:
        if not PCAP.exists():
            self.skipTest("external frozen pcap not staged")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = p75.main(["--pcap", str(PCAP)])
        self.assertEqual(rc, 0)
        self.assertIn("FROZEN_PCAP_SHA256_GATE=PASS", out.getvalue())
        self.assertNotIn("1234", out.getvalue())

    def test_report_payload_free_identifier_free_and_marked_offline(self) -> None:
        text = p75.report()
        for forbidden in ("1234", "1235", "5678", "ADDRROLEA", "ADDRROLEB", "cdab", "RTPC0001"):
            self.assertNotIn(forbidden, text)
        for marker in (
            "RTPC_CONTROL_STATE_MACHINE_CONTRACT=PROVEN_OFFLINE",
            "CLIENT_RTPC_OPEN_SOURCE=P74_ALLOCATOR_BACKED_GENERATION",
            "CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false",
            "CONTROL_CAUSAL_ORDER=PROVEN_PARTIAL_ORDER",
            "RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
        ):
            self.assertIn(marker, text)

    def test_response_before_matching_open_rejected(self) -> None:
        machine = p75.RtpcControlMediaStateMachine()
        with self.assertRaises(p75.ControlStateError):
            machine.observe_device_response(response_body(0x1234))

    def test_unknown_response_target_rejected(self) -> None:
        machine, _ = self.machine_with_client_bodies()
        with self.assertRaises(p75.ControlStateError):
            machine.observe_device_response(response_body(0x9999))

    def test_duplicate_device_response_rejected(self) -> None:
        machine, bodies = self.machine_with_client_bodies()
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        with self.assertRaises(p75.ControlStateError):
            machine.observe_device_response(response_body(bodies.allocation_1.target_id))

    def test_missing_response_is_incomplete_not_silent_success(self) -> None:
        machine, bodies = self.machine_with_client_bodies()
        machine.observe_device_open(open_body(0x5678))
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        machine.observe_client_response_to_device_open(response_body(0x5678))
        machine.generate_client_000a()
        machine.generate_client_001a()
        self.assertFalse(machine.is_complete())

    def test_ambiguous_response_pairing_rejected(self) -> None:
        machine, bodies = self.machine_with_client_bodies()
        duplicated = replace(bodies, allocation_2=replace(bodies.allocation_2, target_id=bodies.allocation_1.target_id))
        machine.client_bodies = duplicated
        with self.assertRaises(p75.ControlStateError):
            machine.observe_device_response(response_body(bodies.allocation_1.target_id))

    def test_second_client_open_reusing_allocation_1_rejected(self) -> None:
        _, bodies = self.machine_with_client_bodies()
        tampered = replace(bodies, rtpc_open_2=bodies.rtpc_open_1)
        with self.assertRaises(p75.ControlStateError):
            p75.validate_allocator_backed_bodies(tampered)

    def test_client_response_bound_to_device_response_target_rejected(self) -> None:
        machine, bodies = self.machine_with_client_bodies()
        machine.observe_device_open(open_body(0x5678))
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        with self.assertRaises(p75.ControlStateError):
            machine.observe_client_response_to_device_open(response_body(bodies.allocation_1.target_id))

    def test_client_000a_bound_to_allocation_2_rejected(self) -> None:
        _, bodies = self.machine_with_client_bodies()
        bad = bytearray(bodies.client_000a)
        bad[16:18] = bodies.allocation_2.target_id.to_bytes(2, "little")
        tampered = replace(bodies, client_000a=bytes(bad))
        with self.assertRaises(p75.ControlStateError):
            p75.validate_allocator_backed_bodies(tampered)

    def test_client_001a_bound_to_allocation_1_rejected(self) -> None:
        _, bodies = self.machine_with_client_bodies()
        bad = bytearray(bodies.client_001a)
        bad[16:18] = bodies.allocation_1.target_id.to_bytes(2, "little")
        tampered = replace(bodies, client_001a=bytes(bad))
        with self.assertRaises(p75.ControlStateError):
            p75.validate_allocator_backed_bodies(tampered)

    def test_valid_alternative_interleaving_is_accepted(self) -> None:
        machine = p75.RtpcControlMediaStateMachine()
        machine.observe_device_open(open_body(0x5678))
        bodies = machine.generate_client_exchange(p73.new_tunnel_state(0x1234), **self.common)
        machine.generate_client_000a()
        machine.observe_client_response_to_device_open(response_body(0x5678))
        machine.observe_device_response(response_body(bodies.allocation_2.target_id))
        machine.generate_client_001a()
        machine.observe_device_response(response_body(bodies.allocation_1.target_id))
        self.assertTrue(machine.is_complete())

    def test_malformed_abcd_open_rejected(self) -> None:
        machine = p75.RtpcControlMediaStateMachine()
        for body in (open_body(0x5678)[:14], open_body(0x5678, name=b"ECHO"), b"\xcd\xab\x01\x00"):
            with self.subTest(body=body):
                with self.assertRaises(p75.ControlStateError):
                    machine.observe_device_open(body)

    def test_malformed_abcd_response_rejected(self) -> None:
        machine, _ = self.machine_with_client_bodies()
        for body in (response_body(0x1234)[:11], b"\xcd\xab\x02\x00\x05\x00\x00\x00\x34\x12\x00\x00"):
            with self.subTest(body=body):
                with self.assertRaises(p75.ControlStateError):
                    machine.observe_device_response(body)

    def test_digest_failure_precedes_capture_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(b"not capture")
            with patch.object(p75.p68, "load_capture") as loader, redirect_stdout(io.StringIO()):
                self.assertEqual(p75.main(["--pcap", str(path)]), 2)
                loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
