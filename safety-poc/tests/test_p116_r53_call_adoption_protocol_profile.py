#!/usr/bin/env python3
"""P116/R53 helper capability-profile call-adoption candidate tests."""

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
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r53_call_adoption_profile_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r45_call_adoption_core as r45  # noqa: E402
import entrance_p116_r53_call_adoption_profile_core as r53  # noqa: E402


SCENARIO_MARKERS = (
    "R53_PROFILE_FLAGS_OR_VALUE",
    "R53_POSITIVE_A_OFFICIAL_PEER_WORD",
    "R53_POSITIVE_B_ALTERNATE_PEER_WORD",
    "R53_ORDER_CALL_INIT_ACK_CAP_ALERT",
    "R53_DUPLICATE_CALL_INIT_SAME_GENERATION_NO_OPEN",
    "R53_DUPLICATE_ACK_ATTEMPT_NO_OPEN",
    "R53_DUPLICATE_CAPABILITIES_NO_OPEN",
    "R53_DUPLICATE_ALERTING_NO_OPEN",
    "R53_NO_OPEN_BEFORE_PEER_CAPABILITIES",
    "R53_PEER_ACK_BEFORE_MEDIA_OPEN",
    "R53_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN",
    "R53_MUT_WRONG_ACK_FLAGS",
    "R53_MUT_WRONG_ACK_SEQUENCE",
    "R53_MUT_WRONG_ACK_ACKNOWLEDGEMENT",
    "R53_MUT_ACK_WITH_BODY_PRESENT",
    "R53_MUT_WRONG_LOCAL_CALL_TYPE_DETECTED",
    "R53_MUT_WRONG_LOCAL_RESERVED_DETECTED",
    "R53_MUT_WRONG_LOCAL_CAPABILITY_COMPUTATION_DETECTED",
    "R53_MUT_ALERTING_OPCODE_000C_DETECTED",
    "R53_MUT_WRONG_ALERTING_ARGUMENT_DETECTED",
    "R53_PEER_VIDEO_BIT_CLEAR_FAIL_CLOSED",
    "R53_PEER_OPCODE_000C_REJECTED",
    "R53_MALFORMED_PEER_CAPABILITIES_REJECTED",
    "R53_FOREIGN_CONNECTION_REJECTED",
    "R53_PRIOR_GENERATION_PEER_FRAME_REJECTED",
    "R53_ACK_WRITE_FAIL_CLOSED",
)

NEW_FILES = (
    MEDIA / "entrance_p116_r53_call_adoption_profile_core.py",
    HARNESS,
    Path(__file__).resolve(),
)

FORBIDDEN_PRIMITIVE_PATTERNS = (
    r"\b" + "sock" + r"et\s*\(",
    r"\b" + "conn" + r"ect\s*\(",
    r"\b" + "send" + r"to\s*\(",
    r"\b" + "getaddr" + r"info\s*\(",
    r"\b" + "D" + r"NS\b",
    r"\b" + "I" + r"CE\b",
    r"\b" + "S" + r"TUN\b",
    r"\b" + "T" + r"URN\b",
    r"\b" + "SIG" + r"USR1\b",
    r"\b" + "SIG" + r"USR2\b",
)


def parse_markers(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            out[key] = value
    return out


class P116R53CallAdoptionProtocolProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cc = shutil.which("cc")
        cls.harness_source = HARNESS.read_text(encoding="utf-8")
        cls.r53_source = Path(r53.__file__).read_text(encoding="utf-8")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        cls.markers: dict[str, str] = {}

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            tmp = Path(cls.tmp_obj.name)
            combined = tmp / "r53_combined.c"
            combined.write_text(
                r35.CORE_REGION
                + "\n\n"
                + r36.CORE_REGION
                + "\n\n"
                + r45.CORE_REGION
                + "\n\n"
                + r53.CORE_REGION
                + "\n\n"
                + cls.harness_source,
                encoding="utf-8",
            )
            binary = tmp / "r53_harness"
            result = subprocess.run(
                [
                    cls.cc,
                    "-std=c99",
                    "-Wall",
                    "-Wextra",
                    "-pedantic",
                    str(combined),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
            )
            cls.compile_stderr = result.stderr
            if result.returncode == 0:
                cls.compiled = True
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_stdout = run.stdout
                cls.harness_returncode = run.returncode
                cls.markers = parse_markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    def test_harness_compiles_without_warnings(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    def test_harness_runs_and_reports_pass(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.markers.get("R53_HOST_HARNESS_RESULT"), "PASS")

    def test_profile_flags_are_explicit_or_formula(self) -> None:
        core = r53.CORE_REGION
        self.assertIn("R53_HELPER_CAP_AUDIO_DST  0x01u", core)
        self.assertIn("R53_HELPER_CAP_AUDIO_SRC  0x02u", core)
        self.assertIn("R53_HELPER_CAP_VIDEO_DST  0x04u", core)
        self.assertIn("R53_HELPER_CAP_MSTREAM    0x20u", core)
        self.assertIn("| R53_HELPER_CAP_AUDIO_SRC", core)
        self.assertEqual(self.markers.get("R53_PROFILE_FLAGS_OR_VALUE"), "PASS")

    def test_no_capture_literal_replay_blob_in_serializer_core(self) -> None:
        core = r53.CORE_REGION + "\n" + r45.CORE_REGION
        forbidden_forms = (
            "00 03 49 00 " + "27 00 00 00",
            "00034900" + "27000000",
            "{0x00u, 0x03u, 0x49u, 0x00u, "
            + "0x27u, 0x00u, 0x00u, 0x00u}",
        )
        for token in forbidden_forms:
            with self.subTest(token=token):
                self.assertNotIn(token, core)

    def test_no_native_storage_equivalence_claim(self) -> None:
        text = "\n".join(path.read_text(encoding="utf-8") for path in NEW_FILES)
        forbidden = (
            "CallFsm" + "+840 = 0x27",
            "CallFsm" + "+840 source proven",
            "CALLFSM_840" + "_VALUE",
            "NATIVE_INTERNAL" + "_STATE",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_ordering_mutation_duplicate_and_fail_closed_markers(self) -> None:
        self.require_harness()
        for key in SCENARIO_MARKERS:
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS", f"{key} not PASS")

    def test_peer_word_is_runtime_parsed_not_fixed_to_observed_fixture(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R53_POS_A_PEER_WORD"), "0x0000001b")
        self.assertEqual(self.markers.get("R53_POS_B_PEER_WORD"), "0x0000002f")
        self.assertEqual(self.markers.get("R53_POSITIVE_B_ALTERNATE_PEER_WORD"), "PASS")

    def test_peer_ack_precedes_media_trigger_in_harness_source(self) -> None:
        src = self.harness_source
        self.assertLess(src.index("r53_handle_peer_capabilities"), src.index("MEDIA_OPEN"))
        self.assertLess(src.index("CALL_PEER_DATA_ACK"), src.index("MEDIA_OPEN"))

    def test_no_forbidden_runtime_primitives_in_new_files(self) -> None:
        for path in NEW_FILES:
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_PRIMITIVE_PATTERNS:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))

    def test_bounded_diagnostics_fields_exist(self) -> None:
        core = r53.CORE_REGION
        for field in (
            "call_adoption_started",
            "invite_ack_sent",
            "local_capabilities_sent",
            "local_capability_word",
            "local_alerting_sent",
            "waiting_peer_capabilities",
            "peer_capabilities_seen",
            "peer_capability_word",
            "peer_video_requested",
            "call_adoption_failure_stage",
        ):
            with self.subTest(field=field):
                self.assertIn(field, core)

    def test_report_contract_scalars(self) -> None:
        report = r53.report()
        self.assertIn(
            "HELPER_CAPABILITY_PROFILE_SOURCE=OFFICIAL_APP_DECLARED_INTUNIT_MSTREAM_PROFILE",
            report,
        )
        self.assertIn("HELPER_CAPABILITY_PROFILE_FORMULA=AUDIO_DST|AUDIO_SRC|VIDEO_DST|MSTREAM", report)
        self.assertIn("HELPER_CAPABILITY_PROFILE_VALUE=0x00000027", report)
        self.assertIn("CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false", report)
        self.assertIn("CAPTURE_LITERAL_REPLAY_USED=false", report)
        self.assertIn("PRODUCTION_PATCH_ALLOWED=false", report)


if __name__ == "__main__":
    unittest.main()
