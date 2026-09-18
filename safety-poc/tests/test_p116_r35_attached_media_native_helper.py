#!/usr/bin/env python3
"""P116/R35 offline focused tests for the native attached-media candidate.

Offline only.  No sockets are opened, and the musl candidate binary produced
by ``ct122_build_p116_r35_attached_media_candidate.sh`` is never executed by
this module.  The only executable artifact this module builds and runs is
the host-compiled, dependency-free harness
(``tests/native/p116_r35_attached_media_host_harness.c`` plus the extracted
``R35_ATTACHED_MEDIA_BEGIN``/``_END`` core region) -- a research-only test
double, not the packaged/candidate helper.
"""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
HARNESS_SOURCE = Path(__file__).resolve().parent / "native" / "p116_r35_attached_media_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r30_call_ctp_envelope_model as r30  # noqa: E402
import entrance_p116_r30b_call_transaction_model as r30b  # noqa: E402
import entrance_p116_r34_attached_media_helper_model as r34  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402

CANONICAL_INCLUDE_P116_DIGEST = "1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2"


def parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


class P116R35AttachedMediaNativeHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.door_source = DOOR_SOURCE.read_text(encoding="utf-8")
        cls.canonical = p106.transform(cls.door_source, include_p116=True)
        cls.canonical_digest = __import__("hashlib").sha256(cls.canonical.encode("utf-8")).hexdigest()
        cls.candidate = r35.transform(cls.canonical)
        cls.core = r35.extract_core_region(cls.candidate)
        cls.transform_source = Path(r35.__file__).read_text(encoding="utf-8")
        cls.harness_source = HARNESS_SOURCE.read_text(encoding="utf-8")

        cls.cc = shutil.which("cc")
        cls.compiled = False
        if cls.cc:
            cls.tmpdir_obj = tempfile.TemporaryDirectory()
            cls.tmpdir = Path(cls.tmpdir_obj.name)
            combined = cls.tmpdir / "r35_combined.c"
            combined.write_text(cls.core + "\n" + cls.harness_source, encoding="utf-8")
            binary = cls.tmpdir / "r35_harness"
            result = subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            if result.returncode == 0:
                cls.compiled = True
                cls.harness_binary = binary
            else:
                cls.compile_stderr = result.stderr

        if cls.compiled:
            run = subprocess.run([str(cls.harness_binary)], text=True, capture_output=True)
            cls.harness_stdout = run.stdout
            cls.harness_returncode = run.returncode
            cls.harness_markers = parse_markers(run.stdout)
        else:
            cls.harness_stdout = ""
            cls.harness_returncode = None
            cls.harness_markers = {}

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmpdir_obj"):
            cls.tmpdir_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or harness failed to compile: {getattr(self, 'compile_stderr', '')}")

    # 0. canonical digest pin (sanity: R35 must not perturb the canonical chain)
    def test_00_canonical_include_p116_digest_pinned(self) -> None:
        self.assertEqual(self.canonical_digest, CANONICAL_INCLUDE_P116_DIGEST)

    # 1. CALL_INIT captures the correct call transaction
    def test_01_call_init_captures_direction_transformed_connection(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_CALL_CTP_CAPTURE"), "PASS")
        peer_connection = 0x1234
        expected = struct.unpack(">H", r30b.derive_native_local_connection_id(struct.pack(">H", peer_connection)))[0]
        self.assertEqual(int(self.harness_markers["R35_CALL_CTP_CONNECTION"]), expected)
        self.assertEqual(int(self.harness_markers["R35_CALL_SEQUENCE"]), 0x78)
        self.assertEqual(int(self.harness_markers["R35_CALL_ACK"]), 0x56)

    # 2. registration handle stays distinct from the call CTP id
    def test_02_registration_handle_distinct_from_call_ctp_id(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_REGISTRATION_DISTINCT"), "PASS")

    # 3. OPEN body is byte-exact
    def test_03_open_body_byte_exact_against_r34_oracle(self) -> None:
        self.require_harness()
        oracle_tunnel = r34.serialize_mediareq26_open(
            r34.default_open_sources(form=r34.MEDIAREQ26_FORM_TUNNEL, video_request=False)
        )
        harness_tunnel = bytes.fromhex(self.harness_markers["R35_OPEN_BODY_TUNNEL_NOVIDEO_HEX"])
        self.assertEqual(len(harness_tunnel), 26)
        self.assertEqual(harness_tunnel, oracle_tunnel)

        oracle_address = r34.serialize_mediareq26_open(
            r34.default_open_sources(form=r34.MEDIAREQ26_FORM_ADDRESS, video_request=True, profile_selector=True)
        )
        harness_address = bytes.fromhex(self.harness_markers["R35_OPEN_BODY_ADDRESS_VIDEO_PROFILE_HEX"])
        self.assertEqual(harness_address, oracle_address)
        parsed = r34.parse_mediareq26(harness_address)
        self.assertEqual(parsed["unknown_fields"], 0)

    # 4. the OPEN envelope is call-bound
    def test_04_open_envelope_is_call_bound(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_ENVELOPE_CALL_BOUND"), "PASS")
        envelope = bytes.fromhex(self.harness_markers["R35_ENVELOPE_OPEN_HEX"])
        self.assertEqual(len(envelope), 60)
        parsed = r30.parse_ctp_envelope(envelope)
        self.assertEqual(parsed.flags, r30.FLAG_DATA)
        self.assertNotEqual(struct.unpack(">H", parsed.connection)[0], 999)

    # 5. OPEN flags are derived from runtime source expressions
    def test_05_open_flags_are_runtime_expressions_not_literals(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_OPEN_FLAGS_ARE_EXPRESSIONS"), "PASS")
        self.assertEqual(self.harness_markers["R35_OPEN_FLAGS_TUNNEL_NOVIDEO"], "0x32")
        self.assertEqual(self.harness_markers["R35_OPEN_FLAGS_TUNNEL_VIDEO"], "0x3a")
        self.assertEqual(self.harness_markers["R35_OPEN_FLAGS_ADDRESS_NOVIDEO_NOPROFILE"], "0x30")
        self.assertEqual(self.harness_markers["R35_OPEN_FLAGS_ADDRESS_VIDEO_PROFILE"], "0x3c")
        self.assertNotIn("out[3] = (unsigned char)0x32;", self.core)
        self.assertNotIn("out[3] = 0x32;", self.core)

    # 6. at most one OPEN
    def test_06_at_most_one_open(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_AT_MOST_ONE_OPEN"), "PASS")

    # 7. RTP may arm only after a valid OPEN, never before
    def test_07_rtp_arms_only_after_open(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_RTP_NEVER_BEFORE_OPEN"), "PASS")
        self.assertEqual(self.harness_markers.get("R35_CHECK_RTP_ARM_AFTER_OPEN"), "PASS")

    # 8. STOP is byte-exact
    def test_08_stop_body_byte_exact_against_r34_oracle(self) -> None:
        self.require_harness()
        oracle_tunnel_stop = r34.serialize_mediareq26_stop(form=r34.MEDIAREQ26_FORM_TUNNEL, media_channel_id=0x3456)
        harness_tunnel_stop = bytes.fromhex(self.harness_markers["R35_STOP_BODY_TUNNEL_HEX"])
        self.assertEqual(harness_tunnel_stop, oracle_tunnel_stop)
        self.assertEqual(harness_tunnel_stop[10:], b"\x00" * 16)

        oracle_address_stop = r34.serialize_mediareq26_stop(form=r34.MEDIAREQ26_FORM_ADDRESS, media_channel_id=0x3456)
        harness_address_stop = bytes.fromhex(self.harness_markers["R35_STOP_BODY_ADDRESS_HEX"])
        self.assertEqual(harness_address_stop, oracle_address_stop)

    # 9. STOP strictly precedes local media RX teardown
    def test_09_stop_precedes_disposal(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_STOP_PRECEDES_DISPOSAL"), "PASS")
        self.assertEqual(self.harness_markers.get("R35_CHECK_DISPOSE_AFTER_STOP"), "PASS")

    # 10. at most one STOP
    def test_10_at_most_one_stop(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_AT_MOST_ONE_STOP"), "PASS")

    # 11. wrong channel id is rejected
    def test_11_wrong_channel_id_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_WRONG_CHANNEL_REJECTED"), "PASS")

    # 12. stale channel id is rejected
    def test_12_stale_channel_id_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_STALE_CHANNEL_REJECTED"), "PASS")

    # 13. a second OPEN is rejected (single focused case; all seven covered in test_24)
    def test_13_second_open_is_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_AT_MOST_ONE_OPEN"), "PASS")

    # 14. prior-call state reuse is rejected
    def test_14_prior_call_state_reuse_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_PRIOR_CALL_STATE_REUSE_REJECTED"), "PASS")

    # 15. dispose before STOP is rejected
    def test_15_dispose_before_stop_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_DISPOSE_BEFORE_STOP_REJECTED"), "PASS")

    # 16. listener / registration / PseudoTCP / call transaction preservation
    def test_16_listener_registration_pseudotcp_call_preserved(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_LISTENER_REGISTRATION_PSEUDOTCP_PRESERVED"), "PASS")

    # 17. no self-activation
    def test_17_no_self_activation_in_injected_regions(self) -> None:
        for forbidden in ("ENTRANCE_SELF_ACTIVATION", "entrance_self_activation", "P12_TX_ENTRANCE_SELF_ACTIVATION"):
            self.assertNotIn(forbidden, self.core)
        injected = self.candidate[
            self.candidate.index(r35.CORE_BEGIN_MARKER) : self.candidate.index(r35.WIRING_END_MARKER)
        ]
        for forbidden in ("ENTRANCE_SELF_ACTIVATION", "entrance_self_activation_"):
            self.assertNotIn(forbidden, injected)
        # The pre-existing self-activation lane must remain byte-for-byte
        # present and untouched elsewhere in the candidate.
        self.assertIn("ENTRANCE_SELF_ACTIVATION_SENT=PASS", self.candidate)

    # 18. no R27 repeat
    def test_18_no_r27_repeat_in_injected_regions(self) -> None:
        injected = self.candidate[
            self.candidate.index(r35.CORE_BEGIN_MARKER) : self.candidate.index(r35.WIRING_END_MARKER)
        ]
        for forbidden in ("repeat_001a", "REPEAT_001A", "r27_repeat"):
            self.assertNotIn(forbidden, injected)

    # 19/20. DOOR_ACTIONS=0, GATE_ACTIONS=0
    def test_19_door_actions_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_DOOR_ACTIONS"), "0")

    def test_20_gate_actions_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_GATE_ACTIONS"), "0")

    # 21. NETWORK_TX=0 during offline execution of every test in this module
    def test_21_network_tx_zero_and_source_stays_offline(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_NETWORK_TX"), "0")
        combined = self.transform_source + "\n" + self.harness_source
        forbidden_patterns = (
            r"(^|\n)\s*(import|from)\s+" + "so" + r"cket\b",
            r"(^|\n)\s*(import|from)\s+" + "ur" + r"llib\b",
            r"(^|\n)\s*(import|from)\s+" + "req" + r"uests\b",
            r"\b" + "cu" + r"rl\s",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.MULTILINE))
        for forbidden in (" socket(", " connect(", " sendto(", " bind(", "STUN", "TURN"):
            self.assertNotIn(forbidden, self.core)

    # 22. state cleanup on terminal call teardown
    def test_22_state_cleanup_on_terminal_call_teardown(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_STATE_CLEANUP_ON_TEARDOWN"), "PASS")

    # 23. derivation-flip test for the STALE_CHANNEL gate (the R34 gap):
    # R34 defined STALE_CHANNEL_GATE but never proved it can compute FAIL.
    def test_23_stale_channel_gate_derivation_flip(self) -> None:
        self.require_harness()
        occurrences = [line for line in self.harness_stdout.splitlines() if line.startswith("STALE_CHANNEL_GATE=")]
        self.assertEqual(occurrences, ["STALE_CHANNEL_GATE=PASS", "STALE_CHANNEL_GATE=FAIL"])

    # 24. generated-source contract tests: required markers/guards present,
    # forbidden ones absent.
    def test_24_generated_source_contract(self) -> None:
        for marker in (
            r35.CORE_BEGIN_MARKER,
            r35.CORE_END_MARKER,
            r35.WIRING_BEGIN_MARKER,
            r35.WIRING_END_MARKER,
            "R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL",
            "r35_capture_call_ctp_id",
            "r35_send_open",
            "r35_send_stop",
            "r35_dispose_media_rx_channel",
            "r35_preserve_listener_registration_pseudotcp",
            "p80_media_forwarding_enabled = armed",
        ):
            self.assertIn(marker, self.candidate)

        injected = self.candidate[
            self.candidate.index(r35.CORE_BEGIN_MARKER) : self.candidate.index(r35.WIRING_END_MARKER)
        ]
        for forbidden in (
            "-lpthread",
            "pthread_create",
            "g_timeout_add",
            "retry",
            "RETRY",
            "call_id=%",
            "channel_id=%u\\n",
            "address=%",
        ):
            self.assertNotIn(forbidden, injected)

        # No unconditional flags literal: out[3] must always be an
        # r35_open_flags(...)/r35_stop_flags(...) call result, never a bare
        # assignment of 0x32/0x30 in the serializers.
        self.assertNotRegex(self.core, r"out\[3\]\s*=\s*\(unsigned char\)0x3[02];")
        self.assertIn("r35_open_flags(src->form, src->video_request, src->profile_selector)", self.core)
        self.assertIn("r35_stop_flags(form)", self.core)

        # The canonical --include-p116 digest anchor documented alongside the
        # pinned P116 provenance must not have been altered by this overlay.
        self.assertNotIn("P106_TEARDOWN_STATE_TRANSFORM", self.core)

    # 25. host harness compiled with host cc and RUN; behavioural proof.
    def test_25_host_harness_compiles_and_runs(self) -> None:
        if not self.cc:
            self.skipTest("cc unavailable on this host")
        self.assertTrue(self.compiled, getattr(self, "compile_stderr", ""))
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.harness_markers.get("R35_HARNESS_RESULT"), "PASS")
        for i in range(1, 8):
            self.assertEqual(self.harness_markers.get(f"R35_FORBIDDEN_STATE_{i}"), "PASS")
        self.assertEqual(len(r34.second_open_forbidden_reasons()), 7)
        for i, state in enumerate(r34.second_open_forbidden_reasons(), start=1):
            self.assertEqual(self.harness_markers.get(f"R35_SECOND_OPEN_FORBIDDEN_CODE_{i}"), state.code)

    # Additional structural cross-checks (not part of the numbered 25, kept
    # small and focused).
    def test_transform_report_contains_required_markers(self) -> None:
        text = r35.report()
        for marker in (
            "OVERLAY_STEP=SEPARATE_FROM_P106_P116_CHAIN",
            "CORE_REGION_DEPENDENCY_FREE=true",
            "TRANSPORT_REUSED=p12_queue_vip_frame",
            "RTP_GATE_REUSED=p80_media_forwarding_enabled",
            "SELF_ACTIVATION_TOUCHED=false",
            "AUTOMATIC_RETRY_ADDED=false",
            "NEW_RUNTIME_DEPENDENCY_ADDED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
        ):
            self.assertIn(marker, text)

    def test_registration_ctpp_open_rejected_without_write(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R35_CHECK_REGISTRATION_HANDLE_OPEN_REJECTED"), "PASS")

    def test_transform_is_idempotent_reapplication_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            r35.transform(self.candidate)

    def test_no_placeholders_in_transform_source(self) -> None:
        self.assertNotRegex(self.transform_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")
        self.assertNotRegex(self.harness_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")


if __name__ == "__main__":
    unittest.main()
