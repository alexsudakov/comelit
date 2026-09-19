#!/usr/bin/env python3
"""P116/R37 offline focused tests for the attached-media live-readiness round.

Offline only.  No sockets are opened, no packet is captured or transmitted,
and the musl candidate binary built by ``ct122_build_p116_r37_attached_media_
candidate.sh`` is never executed by this module.  The only executable
artifact this module builds and runs is the host-compiled, dependency-free
harness (``tests/native/p116_r37_attached_media_live_readiness_host_harness.c``
plus R35's extracted core region, plus R36's extracted trigger-core region,
plus R37's own extracted core region) -- a research-only test double, not
the packaged/candidate helper.

This round's CHILD A closed the remaining native OPEN runtime-field sources
to their EXACT origin and found every one of them is C++ object state
internal to libvipcomelit.so, unreachable by this helper
(P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_READINESS.md SECTION 1/2). Per the
operator's explicit instruction, R37 therefore adds ZERO new OPEN wiring:
this module asserts that as a hard gate (no new caller of
r35_allocate_media_rx_channel/r35_send_open anywhere in the R37 regions).
What IS closed this round -- a real bounded external STOP control and
fail-closed local/media response to CAPABILITY-cleared/RELEASE -- is tested
via the 15-scenario host harness required by this round's CHILD F. Scenario
7 is REQUIRED BY THE TASK to be run exactly as specified
("call CTP used incorrectly as media-channel id => OPEN=0") and is asserted
here to FAIL, because R36's real, unedited trigger (which R37 does not and
must not rewrite) deliberately reuses the call CTP connection id as its own
documented placeholder channel id -- independent, executable confirmation
of the CHILD A finding, not a defect in this test.
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
DOC = MEDIA / "P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_READINESS.md"
HARNESS_SOURCE = Path(__file__).resolve().parent / "native" / "p116_r37_attached_media_live_readiness_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r37_attached_media_live_readiness_transform as r37  # noqa: E402

CANONICAL_INCLUDE_P116_DIGEST = "1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2"
R35_GENERATED_SOURCE_DIGEST = "5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0"
R36_GENERATED_SOURCE_DIGEST = "59262cd3ff1ff87b2ac8612fc38e5d0c3c789e6bbad9204e5a20915c237cc1b5"

# Confirmed by the independent, executable public CTP client implementation
# (read-only staged evidence, never committed here):
#   .r33-evidence/public-vip/viper/ctp.py:30   OP_RELEASE = 0x000E
OP_RELEASE = 0x000E


def parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


class P116R37LiveReadinessTests(unittest.TestCase):
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
        cls.r37_candidate = r37.transform(cls.r36_candidate)
        cls.r37_candidate_digest = __import__("hashlib").sha256(
            cls.r37_candidate.encode("utf-8")
        ).hexdigest()
        cls.r35_core = r35.extract_core_region(cls.r35_candidate)
        cls.r36_core = r36.extract_trigger_core_region(cls.r36_candidate)
        cls.r37_core = r37.extract_core_region(cls.r37_candidate)
        cls.r37_transform_source = Path(r37.__file__).read_text(encoding="utf-8")
        cls.harness_source = HARNESS_SOURCE.read_text(encoding="utf-8")
        cls.doc_text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""

        cls.cc = shutil.which("cc")
        cls.compiled = False
        if cls.cc:
            cls.tmpdir_obj = tempfile.TemporaryDirectory()
            cls.tmpdir = Path(cls.tmpdir_obj.name)
            combined = cls.tmpdir / "r37_combined.c"
            combined.write_text(
                cls.r35_core + "\n\n" + cls.r36_core + "\n\n" + cls.r37_core + "\n\n" + cls.harness_source,
                encoding="utf-8",
            )
            binary = cls.tmpdir / "r37_harness"
            result = subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            if result.returncode == 0:
                cls.compiled = True
                cls.harness_binary = binary
                cls.compile_stdout = result.stdout
                cls.compile_stderr = result.stderr
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

    # ---- compile hygiene: zero warnings, matching R35/R36's own discipline

    def test_harness_compiles_with_zero_warnings(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    # ---- canonical / R35 / R36 digest invariance (proves R37 changed zero
    # bytes of anything the canonical generator or either prior overlay
    # already produced) -------------------------------------------------

    def test_canonical_include_p116_digest_unchanged(self) -> None:
        self.assertEqual(self.canonical_digest, CANONICAL_INCLUDE_P116_DIGEST)

    def test_r35_generated_candidate_digest_unchanged(self) -> None:
        self.assertEqual(self.r35_candidate_digest, R35_GENERATED_SOURCE_DIGEST)

    def test_r36_generated_candidate_digest_unchanged(self) -> None:
        self.assertEqual(self.r36_candidate_digest, R36_GENERATED_SOURCE_DIGEST)

    def test_r37_generated_candidate_digest_is_reproducible(self) -> None:
        """Applying transform() to the SAME R36 candidate twice (in two
        independent pipelines) must yield the identical digest."""
        second = r37.transform(self.r36_candidate)
        second_digest = __import__("hashlib").sha256(second.encode("utf-8")).hexdigest()
        self.assertEqual(second_digest, self.r37_candidate_digest)

    def test_r37_transform_is_idempotent_reapplication_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            r37.transform(self.r37_candidate)

    def test_r37_transform_requires_r36_augmented_input(self) -> None:
        with self.assertRaises(RuntimeError):
            r37.transform(self.r35_candidate)
        with self.assertRaises(RuntimeError):
            r37.transform(self.canonical)

    # ---- R35/R36 stay exactly as they were: R37 never edits either file,
    # never adds a new OPEN caller --------------------------------------

    def test_r35_and_r36_transform_sources_have_no_new_open_caller(self) -> None:
        """R35's and R36's OWN files (unedited by R37) must still show
        exactly the callers they already had -- proving R37 did not touch
        either of them."""
        r35_source = Path(r35.__file__).read_text(encoding="utf-8")
        r36_source = Path(r36.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"r35_send_open\(", r35_source)), 1)
        self.assertEqual(len(re.findall(r"r35_allocate_media_rx_channel\(", r35_source)), 1)
        self.assertIn("r36_trigger_open_from_capabilities", r36_source)

    def test_r37_candidate_has_no_additional_open_caller(self) -> None:
        """The R37 candidate must have the SAME r35_send_open/
        r35_allocate_media_rx_channel caller counts as the R36 candidate:
        R35's own definition + R36's own trigger caller, and NOTHING added
        by R37 (the round's central, load-bearing gate)."""
        r36_open_hits = len(re.findall(r"r35_send_open\(", self.r36_candidate))
        r36_alloc_hits = len(re.findall(r"r35_allocate_media_rx_channel\(", self.r36_candidate))
        r37_open_hits = len(re.findall(r"r35_send_open\(", self.r37_candidate))
        r37_alloc_hits = len(re.findall(r"r35_allocate_media_rx_channel\(", self.r37_candidate))
        self.assertEqual(r37_open_hits, r36_open_hits)
        self.assertEqual(r37_alloc_hits, r36_alloc_hits)

    def test_r37_core_reuses_r35_functions_and_adds_no_duplicate_writer(self) -> None:
        for needle in (
            "r35_send_stop(",
            "r35_dispose_media_rx_channel(",
            "r35_call_ready(",
            "r35_teardown_call(",
        ):
            self.assertIn(needle, self.r37_core)
        for forbidden in (
            "r37_serialize_",
            "r37_build_call_bound_packet(",
            "r37_open_flags(",
            "r35_allocate_media_rx_channel(",
            "r35_send_open(",
        ):
            self.assertNotIn(forbidden, self.r37_core)

    def test_r37_core_region_is_dependency_free(self) -> None:
        for forbidden in ("glib.h", "gboolean", "guint", "printf(", "fprintf(", "socket(", "sendto("):
            self.assertNotIn(forbidden, self.r37_core)

    def test_r37_wiring_uses_unix_signal_source_not_polling(self) -> None:
        wiring = self.r37_candidate.split("/* R37_WIRING_BEGIN */", 1)[1].split(
            "/* R37_WIRING_END */", 1
        )[0]
        self.assertIn("g_unix_signal_add", wiring)
        self.assertNotIn("g_timeout_add", wiring)

    # ---- RELEASE opcode: confirmed by the same independent public CTP
    # implementation R36 already used for OP_CAPABILITIES ------------------

    def test_release_opcode_matches_confirmed_public_implementation(self) -> None:
        self.assertIn("0x000E", self.r37_core.replace("0x000e", "0x000E"))
        self.assertEqual(OP_RELEASE, 0x000E)

    # ---- host-harness: all 15 required scenarios --------------------------

    def test_harness_compiles_and_runs(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)

    def test_scenario_1_call_init_only_open_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_1_CALL_INIT_ONLY"), "PASS")

    def test_scenario_2_capability_bit3_clear_open_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_2_CAPABILITY_BIT3_CLEAR"), "PASS")

    def test_scenario_3_valid_capability_opens_mechanism_only(self) -> None:
        """MECHANISM-ONLY pass: proves R36's trigger and R35's one-OPEN
        machinery still work offline. Not evidence that media_channel_id is
        a proven native value -- see test_scenario_7 and the document."""
        self.require_harness()
        self.assertEqual(
            self.harness_markers.get("R37_SCENARIO_3_VALID_CAPABILITY_OPENS_MECHANISM_ONLY"), "PASS"
        )

    def test_scenario_4_missing_media_channel_id_open_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_4_MISSING_MEDIA_CHANNEL_ID"), "PASS")

    def test_scenario_5_stale_prior_media_channel_open_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_5_STALE_PRIOR_MEDIA_CHANNEL"), "PASS")

    def test_scenario_6_registered_ctpp_as_media_channel_open_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_6_REGISTERED_CTPP_AS_MEDIA_CHANNEL"), "PASS")

    def test_scenario_7_call_ctp_as_media_channel_id_fails_as_expected(self) -> None:
        """REQUIRED BY THE TASK to run exactly as specified ("call CTP used
        incorrectly as media-channel id => OPEN=0"). It FAILS against R36's
        real, unedited trigger, which deliberately reuses the call CTP
        connection id as its own documented placeholder channel id
        (P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md SECTION 6).
        This assertion locks in that honest, independent, executable
        confirmation of this round's CHILD A finding
        (LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false) -- it is not a defect to
        fix, and R37 must not silently rewrite R36's trigger to make it
        pass (prohibited: "Do not edit R35/R36 files")."""
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_7_CALL_CTP_AS_MEDIA_CHANNEL_ID"), "FAIL")
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_7_CHANNEL_ID_EQUALS_CALL_CTP"), "true")
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_7_OBSERVED_OPEN_COUNT"), "1")

    def test_scenario_8_bounded_stop_before_open_stop_zero(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_8_BOUNDED_STOP_BEFORE_OPEN"), "PASS")

    def test_scenario_9_bounded_stop_after_open_stop_one(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_9_BOUNDED_STOP_AFTER_OPEN"), "PASS")
        self.assertEqual(self.harness_markers.get("CALL_BOUND_MEDIA_STOP_SENT_COUNT"), "1")
        self.assertEqual(self.harness_markers.get("RTP_DISARMED"), "1")
        self.assertEqual(self.harness_markers.get("MEDIA_RX_CHANNEL_DISPOSED"), "1")

    def test_scenario_10_duplicate_stop_remains_one(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_10_DUPLICATE_STOP"), "PASS")

    def test_scenario_11_remote_release_before_external_stop_no_stale_write(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.harness_markers.get("R37_SCENARIO_11_REMOTE_RELEASE_BEFORE_EXTERNAL_STOP"), "PASS"
        )
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_11_STALE_WRITE_COUNT"), "0")

    def test_scenario_12_capability_clears_bit3_after_open(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_12_CAPABILITY_CLEARS_BIT3_AFTER_OPEN"), "PASS")

    def test_scenario_13_terminal_call_later_trigger(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_SCENARIO_13_TERMINAL_CALL_LATER_TRIGGER"), "PASS")

    def test_scenario_14_disposal_invalidates_channel_identity(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.harness_markers.get("R37_SCENARIO_14_DISPOSAL_INVALIDATES_CHANNEL_IDENTITY"), "PASS"
        )

    def test_scenario_15_new_call_generation_cannot_reuse_channel(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.harness_markers.get("R37_SCENARIO_15_NEW_CALL_GENERATION_CANNOT_REUSE_CHANNEL"), "PASS"
        )

    def test_release_envelope_builder_matches_parser_layout(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_CHECK_RELEASE_ENVELOPE_PARSES"), "PASS")

    def test_harness_zero_side_effects(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_NETWORK_TX"), "0")
        self.assertEqual(self.harness_markers.get("R37_DOOR_ACTIONS"), "0")
        self.assertEqual(self.harness_markers.get("R37_GATE_ACTIONS"), "0")

    def test_overall_harness_result_reflects_scenario_7_honestly(self) -> None:
        """R37_HARNESS_RESULT is FAIL overall because scenario 7 is FAIL by
        design (see test_scenario_7 above) -- the harness's own summary
        marker is not papered over."""
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R37_HARNESS_RESULT"), "FAIL")

    def test_no_placeholders_in_transform_or_harness_source(self) -> None:
        self.assertNotRegex(self.r37_transform_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")
        self.assertNotRegex(self.harness_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")

    # ---- document / scalar-result-block sanity ---------------------------

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists(), f"missing {DOC}")

    def test_doc_declares_child_a_blocked_honestly(self) -> None:
        self.assertIn("LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false", self.doc_text)
        self.assertIn("ALL_OPEN_RUNTIME_FIELDS_PROVEN=false", self.doc_text)

    def test_doc_declares_stop_path_closed(self) -> None:
        self.assertIn("REAL_BOUNDED_STOP_PATH=true", self.doc_text)

    def test_doc_records_scope_zero(self) -> None:
        self.assertIn("PRODUCTION_FILES_CHANGED=0", self.doc_text)
        self.assertIn("NATIVE_PRODUCTION_BINARY_CHANGED=false", self.doc_text)
        self.assertIn("NORMATIVE_DOCS_CHANGED=0", self.doc_text)
        self.assertIn("NETWORK_TX=0", self.doc_text)
        self.assertIn("LIVE_INVOCATIONS=0", self.doc_text)

    def test_doc_has_no_placeholders(self) -> None:
        self.assertNotRegex(self.doc_text, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")

    def test_doc_result_block_present(self) -> None:
        self.assertIn("=== COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS (REPO DOC) ===", self.doc_text)
        self.assertIn("=== END COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS (REPO DOC) ===", self.doc_text)

    def test_doc_executor_provenance_present(self) -> None:
        self.assertIn("EXECUTOR=claude-code-cli", self.doc_text)
        self.assertIn("EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true", self.doc_text)


if __name__ == "__main__":
    unittest.main()
