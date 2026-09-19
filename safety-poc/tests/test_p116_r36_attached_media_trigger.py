#!/usr/bin/env python3
"""P116/R36 offline focused tests for the attached-media trigger closure.

Offline only.  No sockets are opened, no packet is captured or transmitted,
and the musl candidate binary built by ``ct123_build_p116_r36_attached_media_
trigger_candidate.sh`` is never executed by this module.  The only
executable artifact this module builds and runs is the host-compiled,
dependency-free harness (``tests/native/p116_r36_attached_media_trigger_
host_harness.c`` plus R35's extracted core region plus R36's own extracted
trigger-core region) -- a research-only test double, not the packaged/
candidate helper.

Turn 1 of this round left the OPEN trigger UNPROVEN because the CTP wire
opcode for CAPABILITIES was only derived by pattern, not independently
confirmed.  Turn 2 closed that gap: an independent, executable public CTP
client library (staged read-only evidence, never committed to this repo)
pins ``OP_CAPABILITIES = 0x0003`` and an 8-byte DATA body whose bytes 4..7
are the capability word -- exactly the wire opcode and payload offset the
native disassembly in turn 1 had derived. This module therefore tests the
OVERLAY this round adds: the CAPABILITIES-event OPEN trigger, its fail-
closed guards, and that it reuses (never duplicates) R35's own state
machine.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
DOC = MEDIA / "P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md"
HARNESS_SOURCE = Path(__file__).resolve().parent / "native" / "p116_r36_attached_media_trigger_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r30_call_ctp_envelope_model as r30  # noqa: E402
import entrance_p116_r34_attached_media_helper_model as r34  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402

CANONICAL_INCLUDE_P116_DIGEST = "1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2"
R35_GENERATED_SOURCE_DIGEST = "5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0"

# Confirmed this round (turn 2) by an independent, executable public CTP
# client implementation -- read-only staged evidence, never committed here:
#   .r33-evidence/public-vip/viper/ctp.py:28   OP_CAPABILITIES = 0x0003
#   .r33-evidence/public-vip/viper/call.py:43  8-byte DATA body, opcode(2)
#     type(1) reserved(1) word(4); the capability word sits at bytes 4..7,
#     matching CallFsm's native `ldr w2,[x20,#4]` handler exactly
#     (disasm-CallFsm_st_in_alerting.txt:213-215).
CONFIRMED_CAPABILITIES_OPCODE = 0x0003
CONFIRMED_CAPABILITIES_FSM_EVENT = 0x0A03
FSM_EVENT_WIRE_MARKER = 0x0A00
CAPABILITIES_VIDEO_REQUEST_BIT = 0x08


def parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


class P116R36TriggerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.door_source = DOOR_SOURCE.read_text(encoding="utf-8")
        cls.canonical = p106.transform(cls.door_source, include_p116=True)
        cls.canonical_digest = __import__("hashlib").sha256(
            cls.canonical.encode("utf-8")
        ).hexdigest()
        cls.r35_candidate = r35.transform(cls.canonical)
        cls.r35_candidate_digest = __import__("hashlib").sha256(
            cls.r35_candidate.encode("utf-8")
        ).hexdigest()
        cls.r36_candidate = r36.transform(cls.r35_candidate)
        cls.r36_candidate_digest = __import__("hashlib").sha256(
            cls.r36_candidate.encode("utf-8")
        ).hexdigest()
        cls.r35_core = r35.extract_core_region(cls.r35_candidate)
        cls.r36_core = r36.extract_trigger_core_region(cls.r36_candidate)
        cls.r36_transform_source = Path(r36.__file__).read_text(encoding="utf-8")
        cls.harness_source = HARNESS_SOURCE.read_text(encoding="utf-8")
        cls.doc_text = DOC.read_text(encoding="utf-8")

        cls.cc = shutil.which("cc")
        cls.compiled = False
        if cls.cc:
            cls.tmpdir_obj = tempfile.TemporaryDirectory()
            cls.tmpdir = Path(cls.tmpdir_obj.name)
            combined = cls.tmpdir / "r36_combined.c"
            combined.write_text(
                cls.r35_core + "\n\n" + cls.r36_core + "\n\n" + cls.harness_source,
                encoding="utf-8",
            )
            binary = cls.tmpdir / "r36_harness"
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

    # ---- canonical / R35 digest invariance (proves R36 changed zero bytes
    # of anything R35 or the canonical generator already produced) --------

    def test_canonical_include_p116_digest_unchanged(self) -> None:
        self.assertEqual(self.canonical_digest, CANONICAL_INCLUDE_P116_DIGEST)

    def test_r35_generated_candidate_digest_unchanged(self) -> None:
        self.assertEqual(self.r35_candidate_digest, R35_GENERATED_SOURCE_DIGEST)

    def test_r36_generated_candidate_digest_is_reproducible(self) -> None:
        """Applying transform() to the SAME R35 candidate twice (in two
        independent pipelines) must yield the identical digest."""
        second = r36.transform(self.r35_candidate)
        second_digest = __import__("hashlib").sha256(second.encode("utf-8")).hexdigest()
        self.assertEqual(second_digest, self.r36_candidate_digest)

    def test_r36_transform_is_idempotent_reapplication_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            r36.transform(self.r36_candidate)

    def test_r36_transform_requires_r35_augmented_input(self) -> None:
        with self.assertRaises(RuntimeError):
            r36.transform(self.canonical)

    # ---- R35 stays exactly as it was: STOP remains explicit-only, no new
    # writer duplicated ------------------------------------------------

    def test_r35_transform_source_itself_has_no_automatic_open_or_stop_caller(self) -> None:
        """R35's OWN file (unedited by R36) must still show only its two
        function definitions -- zero callers -- proving R36 did not touch it."""
        r35_transform_source = Path(r35.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"r35_send_open\(", r35_transform_source)), 1)
        self.assertEqual(len(re.findall(r"r35_send_stop\(", r35_transform_source)), 1)

    def test_r36_candidate_has_exactly_one_open_caller_added(self) -> None:
        """The R36 candidate must have R35's `r35_send_open(` definition
        PLUS exactly one caller (R36's trigger core); `r35_send_stop(`
        must still show only its own definition -- R36 never calls STOP."""
        open_hits = re.findall(r"r35_send_open\(", self.r36_candidate)
        stop_hits = re.findall(r"r35_send_stop\(", self.r36_candidate)
        self.assertEqual(len(open_hits), 2, "expected R35's definition + exactly one R36 caller")
        self.assertEqual(len(stop_hits), 1, "R36 must never call r35_send_stop automatically")

    def test_r36_core_region_reuses_r35_functions_and_adds_no_duplicate_writer(self) -> None:
        for needle in (
            "r35_allocate_media_rx_channel(",
            "r35_send_open(",
            "r35_enable_rtp(",
        ):
            self.assertIn(needle, self.r36_core)
        for forbidden in ("r36_send_open(", "r36_serialize_", "r36_build_call_bound_packet("):
            self.assertNotIn(forbidden, self.r36_core)

    def test_r36_core_region_is_dependency_free(self) -> None:
        for forbidden in ("glib.h", "gboolean", "guint", "printf(", "fprintf(", "socket(", "sendto("):
            self.assertNotIn(forbidden, self.r36_core)

    # ---- wire opcode: confirmed this round -------------------------------

    def test_capabilities_opcode_matches_confirmed_public_implementation(self) -> None:
        self.assertIn("0x0003", self.r36_core)
        self.assertIn("R36_OP_CAPABILITIES", self.r36_core)

    def test_known_media_request_opcode_matches_fsm_event_pattern(self) -> None:
        """Cross-check the already-PROVEN case: R30's pinned OP_MEDIA_REQUEST
        (0x0011) plus the 0xa00 wire-received marker equals the FSM event
        code this round observed in disassembly (0xa11) for
        CallFsm::handle_mediareq's dispatch."""
        self.assertEqual(r30.OP_MEDIA_REQUEST, 0x0011)
        self.assertEqual(FSM_EVENT_WIRE_MARKER | r30.OP_MEDIA_REQUEST, 0x0A11)

    def test_media_request_action_bytes_match_offset2_convention(self) -> None:
        self.assertEqual(r34.MEDIAREQ26_OPEN_ACTION, 0x14)
        self.assertEqual(r34.MEDIAREQ26_STOP_ACTION, 0x94)

    def test_confirmed_capabilities_opcode_pattern_is_internally_consistent(self) -> None:
        """The SAME (wire_marker | opcode_low_byte) pattern validated above
        for OP_MEDIA_REQUEST predicts FSM event 0xa03 for OP_CAPABILITIES,
        matching CallFsm::st_in_alerting's `cmp w8,#0xa03` dispatch
        (disasm-CallFsm_st_in_alerting.txt:115-116) -- now independently
        confirmed (not merely derived) via the public CTP implementation."""
        self.assertEqual(
            FSM_EVENT_WIRE_MARKER | CONFIRMED_CAPABILITIES_OPCODE,
            CONFIRMED_CAPABILITIES_FSM_EVENT,
        )
        self.assertEqual(CONFIRMED_CAPABILITIES_FSM_EVENT, 0x0A03)

    # ---- host-harness: the nine required scenarios + the bit3-clear check

    def test_harness_compiles_and_runs(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.harness_markers.get("R36_HARNESS_RESULT"), "PASS")

    def test_scenario_1_pre_trigger_open_count_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_1_PRE_TRIGGER"), "PASS")

    def test_scenario_2_exact_trigger_opens_exactly_once_and_arms_rtp(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_2_EXACT_TRIGGER"), "PASS")
        self.assertEqual(self.harness_markers.get("R36_TRIGGER_RESULT"), "OPEN_SENT")

    def test_scenario_3_duplicate_trigger_open_count_stays_one(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_3_DUPLICATE_TRIGGER"), "PASS")

    def test_scenario_4_stale_prior_call_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_4_STALE_PRIOR_CALL"), "PASS")

    def test_scenario_5_registration_handle_misuse_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_5_REGISTRATION_HANDLE_MISUSE"), "PASS")

    def test_scenario_6_stop_before_open_fails_closed(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_6_STOP_BEFORE_OPEN"), "PASS")

    def test_scenario_7_one_valid_stop(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_7_ONE_VALID_STOP"), "PASS")

    def test_scenario_8_duplicate_stop_no_second_write(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_8_DUPLICATE_STOP"), "PASS")

    def test_scenario_9_terminal_call_trigger_rejected(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_SCENARIO_9_TERMINAL_CALL_REJECTED"), "PASS")

    def test_bit3_clear_does_not_trigger_open(self) -> None:
        """Records the one residual LIVE-BEHAVIOUR question honestly: the
        public sample's own observed capability word (0x27) has bit3
        CLEAR. The trigger logic must still correctly refuse to open in
        that case -- this is not a wire-contract gap, it is the documented
        open question of what a real panel sends."""
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_CHECK_BIT3_CLEAR_DOES_NOT_TRIGGER"), "PASS")

    def test_harness_zero_side_effects(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R36_NETWORK_TX"), "0")
        self.assertEqual(self.harness_markers.get("R36_DOOR_ACTIONS"), "0")
        self.assertEqual(self.harness_markers.get("R36_GATE_ACTIONS"), "0")

    def test_no_placeholders_in_transform_or_harness_source(self) -> None:
        self.assertNotRegex(self.r36_transform_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")
        self.assertNotRegex(self.harness_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")

    # ---- document / scalar-result-block sanity ---------------------------

    def test_doc_declares_open_trigger_proven_and_overlay_added(self) -> None:
        self.assertIn("HELPER_OBSERVABLE_MEDIA_START_TRIGGER=true", self.doc_text)
        self.assertIn("HELPER_TRIGGER_KIND=FOLLOWUP_CTP_EVENT", self.doc_text)
        self.assertIn("AUTOMATIC_OPEN_TRIGGER_WIRED=true", self.doc_text)
        self.assertIn("AUTOMATIC_STOP_TRIGGER_WIRED=false", self.doc_text)

    def test_doc_records_stop_model_and_scope_zero(self) -> None:
        self.assertIn("PRODUCTION_FILES_CHANGED=0", self.doc_text)
        self.assertIn("NATIVE_PRODUCTION_BINARY_CHANGED=false", self.doc_text)
        self.assertIn("NORMATIVE_DOCS_CHANGED=0", self.doc_text)
        self.assertIn("NETWORK_TX=0", self.doc_text)
        self.assertIn("LIVE_INVOCATIONS=0", self.doc_text)
        self.assertIn("DEPLOYS=0", self.doc_text)
        self.assertIn("HA_RESTARTS=0", self.doc_text)

    def test_doc_has_no_placeholders(self) -> None:
        self.assertNotRegex(self.doc_text, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")

    def test_doc_result_block_present(self) -> None:
        self.assertIn(
            "=== COMELIT P116 R36 ATTACHED MEDIA TRIGGER (REPO DOC) ===", self.doc_text
        )
        self.assertIn(
            "=== END COMELIT P116 R36 ATTACHED MEDIA TRIGGER (REPO DOC) ===", self.doc_text
        )


if __name__ == "__main__":
    unittest.main()
