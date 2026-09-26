#!/usr/bin/env python3
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r65_production_media_refresh_transform as r65  # noqa: E402
import entrance_p116_r66_startup_settle_transform as r66  # noqa: E402
import entrance_msl_v5_settle_instrumentation_transform as msl_v5  # noqa: E402
from test_p116_r57_whole_tu_compile_gate import compile_whole_tu  # noqa: E402


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MslV5SettleTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r65 = r65.transform(cls.source, include_p116=True)
        cls.control = r66.transform(cls.source, include_p116=True, settle_ms=4000)
        cls.candidates = {
            value: r66.transform(cls.source, include_p116=True, settle_ms=value)
            for value in (2000, 1000, 500, 0)
        }

    def test_settle_anchor_is_unique_and_fail_closed(self) -> None:
        self.assertEqual(self.r65.count(r66.SETTLE_DEFINE), 1)
        self.assertEqual(self.r65.count(r66.SETTLE_CALL), 1)
        with self.assertRaisesRegex(RuntimeError, "settle define anchor"):
            r66._validate_r65_anchors(self.r65 + "\n#define ENTRANCE_SIGNAL_SETTLE_MS 4000\n")
        with self.assertRaisesRegex(RuntimeError, "settle define anchor"):
            r66._validate_r65_anchors(self.r65.replace(r66.SETTLE_DEFINE, "#define ENTRANCE_SIGNAL_SETTLE_MS 4001"))

    def test_allowed_values_and_r65_equivalence_at_4000(self) -> None:
        self.assertEqual(self.control, self.r65)
        self.assertEqual(r66.transform(self.source, include_p116=True, settle_ms=None), self.r65)
        with self.assertRaisesRegex(ValueError, "settle_ms must be one of"):
            r66.transform(self.source, include_p116=True, settle_ms=250)
        with self.assertRaises(ValueError):
            r66.transform(self.source, include_p116=False, settle_ms=2000)

    def test_candidates_are_deterministic_and_distinct(self) -> None:
        seen = {_sha(self.control)}
        for value, candidate in self.candidates.items():
            repeat = r66.transform(self.source, include_p116=True, settle_ms=value)
            self.assertEqual(candidate, repeat)
            self.assertEqual(candidate.count(f"#define ENTRANCE_SIGNAL_SETTLE_MS {value}"), 1)
            self.assertEqual(candidate.count(r66.SETTLE_CALL), 1)
            digest = _sha(candidate)
            self.assertNotIn(digest, seen)
            seen.add(digest)

    def test_v5_markers_bind_to_existing_hooks(self) -> None:
        candidate = self.candidates[1000]
        expected = {
            "V5_SETTLE_CONFIGURED_MS=1000": "R27_STDOUT_LINE_BUFFERED",
            "V5_CTPP_READY_US": "V4_CTPP_INITIAL_ACK_OBSERVED=true",
            "V5_SETTLE_START_US": "ENTRANCE_SIGNALING_ARMED=true",
            "V5_SIGNALING_START_US": "ENTRANCE_SIGNALING_SETTLE_COMPLETE=true",
            "V5_0028_ACK_US": "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "V5_DEVICE_0008_US": "P78_DEVICE_0008_ACK_SENT=true",
            "V5_DEVICE_0002_US": "P80_DEVICE_0002_OBSERVED=PASS",
            "V5_RTPC_BEGIN_US": "P80_DEVICE_0002_GATE=PASS",
            "V5_RTPC_CONTROL_READY_US": "P78_RTPC_OPEN_2_SENT=PASS",
            "V5_FIRST_VIDEO_RTP_US": "P80_VIDEO_RTP_FORWARDING=PASS",
            "V5_FIRST_DECODABLE_VIDEO_US": "first_keyframe_monotonic_ms = now_ms",
        }
        for marker, hook in expected.items():
            self.assertIn(marker, candidate)
            self.assertIn(hook, candidate)

    def test_no_protocol_keywords_added_by_v5_delta(self) -> None:
        diff = list(difflib.unified_diff(self.control.splitlines(), self.candidates[500].splitlines(), lineterm=""))
        additions = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
        removals = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
        allowed_add_fragments = (
            "ENTRANCE_SIGNAL_SETTLE_MS 500",
            "V5_",
            "v5_",
            "/* === V5_STARTUP_SETTLE_MARKERS",
            "static gboolean v5",
            "static void",
            "value_us",
            "if (*seen)",
            "*seen = TRUE;",
            "p116_monotonic_ms()",
            "if (v5_h264_sps_seen",
            "printf(\"%s=%lld",
            "fflush(stdout);",
            "return;",
            "{",
            "}",
        )
        for line in additions:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in removals:
                continue
            self.assertTrue(
                any(fragment in line for fragment in allowed_add_fragments),
                f"unexpected added line: {line}",
            )
        for line in removals:
            if "ENTRANCE_SIGNAL_SETTLE_MS 4000" in line:
                continue
            if line.strip() in {
                "else if (nal_type == 7u)",
                "else if (nal_type == 8u)",
            }:
                self.assertIn("} " + line.strip() + " {", self.candidates[500])
                continue
            self.assertIn(line, self.candidates[500])

    def test_msl_v5_composes_r66_and_preserves_msl_reference(self) -> None:
        candidate = msl_v5.transform(self.source, include_p116=True, settle_ms=1000)
        self.assertIn("MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START", candidate)
        self.assertIn("V5_SETTLE_CONFIGURED_MS=1000", candidate)
        self.assertIn("MSL_T17_FIRST_VIDEO_RTP_MONO_MS", candidate)

    def test_generated_v5_candidate_whole_tu_compiles(self) -> None:
        result = compile_whole_tu(self.candidates[1000])
        self.assertEqual(result.returncode, 0, result.stderr[:4000])

    def test_candidate_generator_prints_repeat_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MEDIA / "generate_msl_v5_settle_candidates.py"),
                    "--source",
                    str(SOURCE),
                    "--output-dir",
                    tmp,
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=True,
            )
        self.assertIn("V5_CANDIDATE_DETERMINISM=PASS", completed.stdout)
        for value in (2000, 1000, 500, 0):
            self.assertIn(f"V5_SETTLE_MS={value}", completed.stdout)
            self.assertIn("REPEAT_SHA256=", completed.stdout)


if __name__ == "__main__":
    unittest.main()
