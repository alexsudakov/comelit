#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
sys.path.insert(0, str(MEDIA))

import entrance_rtpc_allocator_backed_media_generation_contract as p74
import entrance_rtpc_control_media_runtime_transform as p76
import entrance_rtpc_control_media_state_contract as p75
import entrance_rtpc_target_id_static_contract as p73


def open_body(target: int) -> bytes:
    return b"\xcd\xab\x01\x00\x07\x00\x00\x00RTPC" + target.to_bytes(2, "little") + b"\x01"


def response_body(target: int) -> bytes:
    return p75.build_rtpc_response(target)


def parse_emit(stdout: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for line in stdout.splitlines():
        if line.startswith("EMIT "):
            _, kind, hex_body = line.split()
            out[kind] = bytes.fromhex(hex_body)
    return out


def parse_alloc(stdout: str) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for line in stdout.splitlines():
        if line.startswith("ALLOC "):
            parts = line.split()
            ordinal = int(parts[1])
            target = int(parts[2].split("=")[1])
            collisions = int(parts[3].split("=")[1])
            out[ordinal] = (target, collisions)
    return out


class P76RtpcControlMediaRuntimeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = Path(p76.__file__).read_text(encoding="utf-8")
        cls.candidate = p76.transform(cls.original)
        cls.harness_source = p76.harness_source()
        cls.role_a = b"ADDRROLEA"
        cls.role_b = b"ADDRROLEB"
        cls.common = dict(
            ctpp_seq_000a=0x22000000,
            ctpp_seq_001a=0x33000000,
            address_role_a=cls.role_a,
            address_role_b=cls.role_b,
        )
        cls.cc = shutil.which("cc")
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.tmpdir = Path(cls.tmpdir_obj.name)
        cls.harness_c = cls.tmpdir / "p76_harness.c"
        cls.harness_bin = cls.tmpdir / "p76_harness"
        cls.harness_c.write_text(cls.harness_source, encoding="utf-8")
        cls.compiled = False
        if cls.cc:
            subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(cls.harness_c), "-o", str(cls.harness_bin)],
                check=True,
                text=True,
                capture_output=True,
            )
            cls.compiled = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmpdir_obj.cleanup()

    def run_harness(self, scenario: str, rand_result: int = 0x9234) -> subprocess.CompletedProcess[str]:
        if not self.compiled:
            self.skipTest("cc unavailable")
        return subprocess.run(
            [str(self.harness_bin), "--scenario", scenario, "--rand-result", str(rand_result)],
            check=True,
            text=True,
            capture_output=True,
        )

    def oracle(self, rand_result: int = 0x9234, *, occupied: set[int] | None = None):
        state = p73.new_tunnel_state(p73.seed_from_runtime_prng(rand_result))
        if occupied:
            state.in_use_ids.update(occupied)
        return p74.build_from_allocator_state(state, **self.common)

    def test_transform_composes_p46_reviewed_chain(self) -> None:
        self.assertIn("ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true", self.candidate)
        self.assertIn("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS", self.candidate)
        self.assertIn("C_RUNTIME_BASE=P46_REVIEWED_TRANSFORM_CHAIN", self.candidate)

    def test_runtime_section_is_shared_by_candidate_and_harness(self) -> None:
        self.assertIn(p76.P76_RUNTIME_C_SECTION.strip(), self.candidate)
        self.assertIn(p76.P76_RUNTIME_C_SECTION.strip(), self.harness_source)
        self.assertIn("#define P76_STANDALONE_HARNESS 1", self.harness_source)

    def test_report_contains_required_markers(self) -> None:
        text = p76.report()
        for marker in (
            "RTPC_C_RUNTIME_PARITY_CONTRACT=PROVEN_OFFLINE",
            "REGISTERED_CTPP_REUSED=true",
            "SECOND_CTPP_OPEN=false",
            "RTPC_TARGET_ALLOCATOR=P73_PARITY",
            "RTPC_OPEN_GENERATION=P74_PARITY",
            "RTPC_CONTROL_STATE_MACHINE=P75_PARITY",
            "CLIENT_RESPONSE_DEVICE_OPEN_BINDING=PROVEN",
            "CLIENT_000A_ALLOCATION_BINDING=PROVEN",
            "CLIENT_001A_ALLOCATION_BINDING=PROVEN",
            "CONTROL_TOTAL_ORDER_REQUIRED=false",
            "COLLISION_SKIP_SUPPORTED=true",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "P46_P75_HISTORY=PRESERVED",
        ):
            self.assertIn(marker, text)

    def test_transform_source_is_offline_and_adds_no_launcher(self) -> None:
        for forbidden in ("import socket", "urllib", "requests", "aiohttp", "subprocess", "ct120_launch_"):
            self.assertNotIn(forbidden, self.transform_text)
        self.assertNotIn("ct120_launch_", self.harness_source)

    def test_static_safety_gate_for_harness_source(self) -> None:
        forbidden = (
            " socket(",
            " connect(",
            " getaddrinfo(",
            " gethostbyname(",
            "STUN",
            "TURN",
            "NiceAgent",
            "PseudoTcpSocket",
            "pseudo_tcp_socket",
            "ct120_launch_",
            "v4_door_signal_handler",
            "v4_door_tick_cb",
            "V4_DOOR_WRITE",
            "H264",
            "RTP_PAYLOAD",
            "rtp_",
        )
        for symbol in forbidden:
            self.assertNotIn(symbol, self.harness_source)
        for marker in ("HARNESS_NETWORK_CAPABLE=false", "LIVE_INVOCATIONS=0", "DOOR_ACTION_SENT=false"):
            self.assertIn(marker, self.harness_source)

    def test_candidate_preserves_no_second_ctpp_and_door_negative_markers(self) -> None:
        self.assertIn("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("ENTRANCE_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("DOOR_ACTION_SENT=false", self.candidate)

    def test_c_harness_compiles_with_plain_cc(self) -> None:
        if not self.compiled:
            self.skipTest("cc unavailable")
        self.assertTrue(self.harness_bin.exists())

    def test_canonical_harness_outputs_match_python_oracle_bytes(self) -> None:
        result = self.run_harness("canonical")
        emitted = parse_emit(result.stdout)
        expected = self.oracle()
        self.assertEqual(emitted["CLIENT_OPEN_1"], expected.rtpc_open_1)
        self.assertEqual(emitted["CLIENT_OPEN_2"], expected.rtpc_open_2)
        self.assertEqual(emitted["CLIENT_RESPONSE_DEVICE_OPEN"], response_body(0x4567))
        self.assertEqual(emitted["CLIENT_000A"], expected.client_000a)
        self.assertEqual(emitted["CLIENT_001A"], expected.client_001a)
        self.assertIn("STATE COMPLETE true", result.stdout)

    def test_canonical_allocator_targets_bind_to_open_and_media(self) -> None:
        result = self.run_harness("canonical")
        emitted = parse_emit(result.stdout)
        allocs = parse_alloc(result.stdout)
        first, second = allocs[1][0], allocs[2][0]
        self.assertEqual(emitted["CLIENT_OPEN_1"][12:14], first.to_bytes(2, "little"))
        self.assertEqual(emitted["CLIENT_OPEN_2"][12:14], second.to_bytes(2, "little"))
        self.assertEqual(emitted["CLIENT_000A"][16:18], first.to_bytes(2, "little"))
        self.assertEqual(emitted["CLIENT_001A"][16:18], second.to_bytes(2, "little"))

    def test_alternative_response_interleaving_passes_and_matches_oracle(self) -> None:
        result = self.run_harness("alternative")
        emitted = parse_emit(result.stdout)
        expected = self.oracle()
        self.assertEqual(emitted["CLIENT_OPEN_1"], expected.rtpc_open_1)
        self.assertEqual(emitted["CLIENT_OPEN_2"], expected.rtpc_open_2)
        self.assertEqual(emitted["CLIENT_000A"], expected.client_000a)
        self.assertEqual(emitted["CLIENT_001A"], expected.client_001a)
        self.assertIn("STATE COMPLETE true", result.stdout)

    def test_collision_skip_is_exercised_and_binds_actual_result(self) -> None:
        rand_result = 0x9234
        seed = p73.seed_from_runtime_prng(rand_result)
        result = self.run_harness("collision", rand_result)
        emitted = parse_emit(result.stdout)
        expected = self.oracle(rand_result, occupied={seed + 1})
        allocs = parse_alloc(result.stdout)
        self.assertEqual(allocs[1], (expected.allocation_1.target_id, expected.allocation_1.collisions))
        self.assertEqual(allocs[2], (expected.allocation_2.target_id, expected.allocation_2.collisions))
        self.assertEqual(allocs[2][1], 1)
        self.assertEqual(emitted["CLIENT_OPEN_2"], expected.rtpc_open_2)
        self.assertEqual(emitted["CLIENT_001A"], expected.client_001a)

    def test_constructor_seed_zero_skips_mgmt_id_zero(self) -> None:
        result = self.run_harness("canonical", 0)
        allocs = parse_alloc(result.stdout)
        self.assertEqual(allocs[1], (1, 1))
        self.assertEqual(allocs[2], (2, 0))

    def assertFailureScenario(self, scenario: str, marker: str) -> None:
        result = self.run_harness(scenario)
        self.assertIn(f"ERROR {marker}", result.stdout)
        self.assertIn("HARNESS_NETWORK_CAPABLE=false", result.stdout)

    def test_fail_closed_malformed_device_open(self) -> None:
        self.assertFailureScenario("malformed-open", "MALFORMED_OPEN")

    def test_fail_closed_malformed_response(self) -> None:
        self.assertFailureScenario("malformed-response", "MALFORMED_RESPONSE")

    def test_fail_closed_response_before_open(self) -> None:
        self.assertFailureScenario("response-before-open", "RESPONSE_BEFORE_OPEN")

    def test_fail_closed_unknown_response_target(self) -> None:
        self.assertFailureScenario("unknown-response", "UNKNOWN_RESPONSE_TARGET")

    def test_fail_closed_duplicate_response(self) -> None:
        self.assertFailureScenario("duplicate-response", "DUPLICATE_RESPONSE")

    def test_fail_closed_reused_client_target(self) -> None:
        self.assertFailureScenario("reused-client-target", "REUSED_CLIENT_TARGET")

    def test_fail_closed_allocator_exhaustion(self) -> None:
        self.assertFailureScenario("allocator-exhaustion", "ALLOCATOR_EXHAUSTED")

    def test_fail_closed_client_response_without_device_open(self) -> None:
        self.assertFailureScenario("client-response-without-device-open", "CLIENT_RESPONSE_WITHOUT_DEVICE_OPEN")

    def test_fail_closed_bad_000a_binding(self) -> None:
        self.assertFailureScenario("bad-000a-binding", "BAD_000A_BINDING")

    def test_fail_closed_bad_001a_binding(self) -> None:
        self.assertFailureScenario("bad-001a-binding", "BAD_001A_BINDING")

    def test_fail_closed_second_ctpp_open_attempt(self) -> None:
        self.assertFailureScenario("second-ctpp-open", "SECOND_CTPP_OPEN")

    def test_fail_closed_door_entrypoint(self) -> None:
        self.assertFailureScenario("door-entrypoint", "DOOR_ENTRYPOINT_REACHABLE")

    def test_partial_state_is_not_complete(self) -> None:
        self.assertFailureScenario("partial-complete", "PARTIAL_COMPLETE")

    def test_capture_target_ids_are_not_constants_in_new_artifacts(self) -> None:
        for text in (self.transform_text, self.harness_source, p76.report()):
            for forbidden in ("7459", "26395", "0x1d23", "0x671b"):
                self.assertNotIn(forbidden.lower(), text.lower())
        self.assertIn("CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false", p76.report())


if __name__ == "__main__":
    unittest.main()
