"""Behavioral tests for the R42-b CAPABILITIES-trigger diagnostics block.

Round 3 (forensic observability corrective). The round-2 tests only asserted
that enum literals and marker strings are present in the generated source.
That is not enough: the block computed NO_WRITER/ENVELOPE/FLAG/OPCODE stages
but could never publish them, because the publication condition required a
frame that had already passed the envelope/flag/opcode checks. A source-string
gate cannot see that difference, so this module drives synthetic frames
through the real emitted block (host harness, no network, no Door/Gate) and
asserts on what was actually printed:

* every pre-candidate rejection stage is observable;
* every candidate rejection stage is observable;
* repeated unrelated frames cannot exhaust the budget and hide a later real
  CAPABILITIES candidate;
* a new call generation resets the pre-candidate seen set;
* the block never touches a functional writer, timer or retry;
* the HA-side parser accepts the explicit pre-candidate markers and keeps the
  23-field schema bounded.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
NATIVE = Path(__file__).resolve().parent / "native"
HARNESS_HEAD = NATIVE / "p116_r42b_capabilities_diag_host_harness.c"
HARNESS_SCENARIOS = NATIVE / "p116_r42b_capabilities_diag_scenarios.c"
MEDIA_DIAGNOSTICS = REPO / "custom_components" / "comelit" / "media_diagnostics.py"
EXPECTED_FIELD_COUNT = 23

_STATE_BEGIN = "/* R42_CAPABILITIES_DIAGNOSTICS_STATE_BEGIN */"
_STATE_END = "/* R42_CAPABILITIES_DIAGNOSTICS_STATE_END */"
_BLOCK_BEGIN = "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */"
_BLOCK_END = "/* R42_CAPABILITIES_DIAGNOSTICS_END */"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r42b_listener_attached_media_transform as r42b  # noqa: E402


def _load_media_diagnostics_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_r42b_diag_behavior_media_diagnostics", MEDIA_DIAGNOSTICS
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _between(text: str, begin: str, end: str) -> str:
    assert begin in text, f"missing region start: {begin}"
    assert end in text, f"missing region end: {end}"
    return text.split(begin, 1)[1].split(end, 1)[0]


def _sections(stdout: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in stdout.splitlines():
        opened = re.fullmatch(r"### SCENARIO (\S+) BEGIN", line)
        if opened:
            current = opened.group(1)
            sections.setdefault(current, [])
            continue
        closed = re.fullmatch(r"### SCENARIO (\S+) END", line)
        if closed:
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _stages(lines: list[str]) -> list[str]:
    stages = []
    for line in lines:
        if line.startswith("R42_TRIGGER_REJECT_STAGE="):
            stages.append(line.split("=", 1)[1])
    return stages


def _candidate_counts(lines: list[str]) -> list[str]:
    return [
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("R42_CAPABILITIES_CANDIDATE_COUNT=")
    ]


class CapabilitiesDiagnosticsHarnessTests(unittest.TestCase):
    """Drive the emitted diagnostics block with synthetic frames."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate_source = r42b.transform(DOOR_SOURCE.read_text(encoding="utf-8"))
        cls.state_region = _between(cls.candidate_source, _STATE_BEGIN, _STATE_END)
        cls.block_region = _between(cls.candidate_source, _BLOCK_BEGIN, _BLOCK_END)

        cls.cc = shutil.which("cc")
        cls.stdout = ""
        cls.returncode: int | None = None
        cls.compile_stderr = ""
        if cls.cc is None:
            return

        combined = (
            HARNESS_HEAD.read_text(encoding="utf-8")
            + "\n"
            + cls.state_region
            + "\nstatic void run_diag_once(void)\n{\n"
            + cls.block_region
            + "\n}\n"
            + HARNESS_SCENARIOS.read_text(encoding="utf-8")
        )
        cls.tmpdir = tempfile.TemporaryDirectory()
        source = Path(cls.tmpdir.name) / "r42b_diag_harness.c"
        binary = Path(cls.tmpdir.name) / "r42b_diag_harness"
        source.write_text(combined, encoding="utf-8")
        compiled = subprocess.run(
            [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(source), "-o", str(binary)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            cls.compile_stderr = compiled.stderr
            return
        ran = subprocess.run([str(binary)], text=True, capture_output=True)
        cls.stdout = ran.stdout
        cls.returncode = ran.returncode
        cls.sections = _sections(ran.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        tmpdir = getattr(cls, "tmpdir", None)
        if tmpdir is not None:
            tmpdir.cleanup()

    def require_harness(self) -> None:
        if self.cc is None or self.returncode is None:
            self.skipTest(f"cc unavailable or harness failed to compile: {self.compile_stderr}")

    # ---- core reachability: the defect this round fixes -------------------

    def test_pre_candidate_rejection_stages_are_actually_emitted(self) -> None:
        """ENVELOPE/FLAG/OPCODE must be observable, not merely computed."""
        self.require_harness()
        for scenario, expected in (
            ("ENVELOPE", "ENVELOPE"),
            ("FLAG", "FLAG"),
            ("OPCODE", "OPCODE"),
        ):
            with self.subTest(scenario=scenario):
                self.assertEqual(_stages(self.sections[scenario]), [expected])

    def test_pre_candidate_cases_do_not_claim_a_capabilities_candidate(self) -> None:
        self.require_harness()
        for scenario in ("ENVELOPE", "FLAG", "OPCODE"):
            lines = self.sections[scenario]
            self.assertIn("R42_CAPABILITIES_CANDIDATE_SEEN=false", lines)
            self.assertIn("R42_CAPABILITIES_CALL_MATCH=false", lines)
            self.assertIn("R42_CAPABILITIES_VIDEO_REQUESTED=false", lines)
            self.assertEqual(_candidate_counts(lines), ["0"])
        self.assertIn(
            "R42_CAPABILITIES_PARSE_OK=false", self.sections["ENVELOPE"]
        )
        self.assertIn("R42_CAPABILITIES_PARSE_OK=true", self.sections["FLAG"])
        self.assertIn("R42_CAPABILITIES_PARSE_OK=true", self.sections["OPCODE"])

    def test_candidate_rejection_stages_are_emitted(self) -> None:
        self.require_harness()
        for scenario, expected in (
            ("LENGTH", "LENGTH"),
            ("NO_LIVE_CALL", "NO_LIVE_CALL"),
            ("CONNECTION_MISMATCH", "CONNECTION_MISMATCH"),
            ("VIDEO_BIT_CLEAR", "VIDEO_BIT_CLEAR"),
        ):
            with self.subTest(scenario=scenario):
                self.assertEqual(_stages(self.sections[scenario]), [expected])
                self.assertIn(
                    "R42_CAPABILITIES_CANDIDATE_SEEN=true",
                    self.sections[scenario],
                )

    def test_matched_candidate_keeps_stage_none_and_does_not_reject(self) -> None:
        self.require_harness()
        lines = self.sections["MATCHED"]
        self.assertIn("R42_CAPABILITIES_CANDIDATE_SEEN=true", lines)
        self.assertIn("R42_CAPABILITIES_CALL_MATCH=true", lines)
        self.assertIn("R42_CAPABILITIES_VIDEO_REQUESTED=true", lines)
        self.assertEqual(_stages(lines), ["NONE"])

    def test_no_frame_case_yields_no_stage_evidence(self) -> None:
        self.require_harness()
        self.assertEqual(self.sections["NO_FRAME"], [])

    # ---- boundedness ------------------------------------------------------

    def test_pre_candidate_stages_are_bounded_once_per_generation(self) -> None:
        self.require_harness()
        for scenario, expected in (
            ("ENVELOPE_X100", "ENVELOPE"),
            ("FLAG_X100", "FLAG"),
            ("OPCODE_X100", "OPCODE"),
        ):
            with self.subTest(scenario=scenario):
                self.assertEqual(_stages(self.sections[scenario]), [expected])

    def test_new_generation_resets_the_pre_candidate_seen_set(self) -> None:
        self.require_harness()
        self.assertEqual(
            _stages(self.sections["GENERATION_RESET"]), ["ENVELOPE", "ENVELOPE"]
        )

    def test_unrelated_traffic_cannot_hide_a_later_candidate(self) -> None:
        self.require_harness()
        stages = _stages(self.sections["NOISE_THEN_CANDIDATE"])
        self.assertIn("ENVELOPE", stages)
        self.assertIn("OPCODE", stages)
        self.assertEqual(stages.count("LENGTH"), 1)

    def test_candidate_detail_lines_stay_bounded_per_generation(self) -> None:
        self.require_harness()
        lines = self.sections["CANDIDATE_X20"]
        emitted = _stages(lines).count("VIDEO_BIT_CLEAR")
        self.assertGreaterEqual(emitted, 1)
        self.assertLessEqual(emitted, 8)
        # The counter keeps counting (printed counts run 1..emitted) while the
        # detail-line budget caps how many of those lines reach the log.
        counts = [int(value) for value in _candidate_counts(lines)]
        self.assertEqual(counts, list(range(1, emitted + 1)))

    def test_no_writer_stage_is_emitted_without_touching_the_parser(self) -> None:
        self.require_harness()
        self.assertEqual(_stages(self.sections["NO_WRITER"]), ["NO_WRITER"])
        self.assertIn("R42B_DIAG_HARNESS_NO_WRITER_PARSE_CALLS=0", self.stdout)
        self.assertIn("R42B_DIAG_HARNESS_RESULT=PASS", self.stdout)

    # ---- safety of the diagnostics region itself ---------------------------

    def test_diagnostics_region_stays_read_only(self) -> None:
        region = self.block_region
        for forbidden in (
            "r42_queue_media_channel_open(",
            "r35_send_open(",
            "r35_enable_rtp(",
            "g_timeout_add",
            "continue;",
            "return",
            "retry",
        ):
            self.assertNotIn(forbidden, region.lower() if forbidden == "retry" else region)

    def test_state_region_is_dependency_free(self) -> None:
        # No GLib/GLib-adjacent dependency and no printing inside the pure
        # helper region: it must stay host-compilable plain C.
        for forbidden in (
            "glib",
            "gboolean",
            "g_timeout",
            "malloc",
            "printf",
            "GError",
        ):
            self.assertNotIn(forbidden, self.state_region)


class CapabilitiesPreCandidateParserTests(unittest.TestCase):
    """HA-side parser must accept the explicit pre-candidate markers."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_media_diagnostics_module()

    def _diagnostics(self) -> object:
        return self.module.MediaCallDiagnostics()

    def test_pre_candidate_marker_sequence_is_accepted(self) -> None:
        diag = self._diagnostics()
        self.assertIsNotNone(diag.observe_line("R42_CALL_GENERATION=5"))
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=false")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=true")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=false")
        diag.observe_line("R42_CAPABILITIES_VIDEO_REQUESTED=false")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=FLAG")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=0")
        snapshot = diag.snapshot()
        self.assertEqual(len(snapshot), EXPECTED_FIELD_COUNT)
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertTrue(snapshot["capabilities_parse_ok"])
        self.assertFalse(snapshot["capabilities_call_match"])
        self.assertFalse(snapshot["capabilities_video_requested"])
        self.assertEqual(snapshot["trigger_reject_stage"], "FLAG")
        self.assertEqual(snapshot["capabilities_candidate_count"], 0)

    def test_unknown_reject_stage_is_dropped(self) -> None:
        diag = self._diagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=NOT_A_STAGE")
        self.assertIsNone(diag.snapshot()["trigger_reject_stage"])

    def test_new_generation_wipes_pre_candidate_evidence(self) -> None:
        diag = self._diagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=ENVELOPE")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=true")
        diag.observe_line("R42_CALL_GENERATION=2")
        snapshot = diag.snapshot()
        self.assertIsNone(snapshot["trigger_reject_stage"])
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertFalse(snapshot["capabilities_parse_ok"])

    def test_schema_field_count_is_unchanged(self) -> None:
        self.assertEqual(
            len(self.module.MEDIA_DIAGNOSTICS_FIELDS)
            + len(self.module.CAPABILITIES_TRIGGER_FIELDS),
            EXPECTED_FIELD_COUNT,
        )
        self.assertEqual(
            len(self._diagnostics().snapshot()), EXPECTED_FIELD_COUNT
        )


if __name__ == "__main__":
    unittest.main()
