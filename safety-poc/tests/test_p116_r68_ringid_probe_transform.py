#!/usr/bin/env python3
"""P116/R68 listener ring opaque probe transform tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
EXPECTED_FROZEN_SHA = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r68_ringid_probe_core as core  # noqa: E402
import entrance_p116_r68_ringid_probe_transform as r68  # noqa: E402


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _forbidden_name() -> str:
    return "V4_RING_" + "LOGICAL" + "_CALL_ID"


def _extract_probe_region(text: str) -> str:
    return core.BEGIN + text.split(core.BEGIN, 1)[1].split(core.END, 1)[0] + core.END


HARNESS = r'''
static void run_case(const char *name, const guint8 *body, guint body_len, const char *phase)
{
    printf("CASE=%s\n", name);
    v4_ring_probe_emit(body, body_len, phase);
}

int main(void)
{
    guint8 short3[3] = {0x00u, 0x01u, 0x12u};
    guint8 short20[20] = {0};
    guint8 full36[36] = {0};

    short20[2] = 0x12u;
    short20[3] = 0x34u;
    full36[2] = 0xabu;
    full36[3] = 0xcdu;
    full36[32] = 0x01u;
    full36[33] = 0x23u;
    full36[34] = 0x45u;
    full36[35] = 0x67u;

    run_case("SHORT3", short3, 3u, "INITIAL");
    run_case("SHORT20", short20, 20u, "RETRANSMIT");
    run_case("FULL36", full36, 36u, "INITIAL");
    return 0;
}
'''


class P116R68RingProbeTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = r68.transform(cls.source)
        cls.generated_b = r68.transform(cls.source)
        cls.generated_sha = _sha256_text(cls.generated_a)
        cls.region = _extract_probe_region(cls.generated_a)
        cls.cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        cls.compile_returncode: int | None = None
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory(prefix="p116-r68-probe-")
            tmp = Path(cls.tmp_obj.name)
            combined = tmp / "probe_harness.c"
            combined.write_text(cls._prelude() + "\n" + cls.region + "\n" + HARNESS, encoding="utf-8")
            binary = tmp / "probe_harness"
            compiled = subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            cls.compile_returncode = compiled.returncode
            cls.compile_stderr = compiled.stderr
            if compiled.returncode == 0:
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_returncode = run.returncode
                cls.harness_stdout = run.stdout

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    @staticmethod
    def _prelude() -> str:
        return r'''
#include <stdio.h>

typedef unsigned char guint8;
typedef unsigned int guint;
typedef unsigned short guint16;
static long long g_get_monotonic_time(void) { return 123000; }
'''

    def test_n1_listener_transform_once_and_deterministic(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(self.generated_sha, "566ff0e554f3f2b1c7b2c89bfc1b7b3cdbb0d40a0c1eeba79500ad6f20cba420")
        self.assertEqual(self.generated_a.count(core.BEGIN), 1)
        self.assertEqual(self.generated_a.count("static void\nv4_ring_probe_emit"), 1)
        self.assertEqual(self.generated_a.count('v4_ring_probe_emit(body, body_len, "INITIAL");'), 1)
        self.assertEqual(self.generated_a.count('v4_ring_probe_emit(body, body_len, "RETRANSMIT");'), 1)

    def test_n3_reapply_gate_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "RINGID_PROBE_REAPPLY_GATE=FAIL"):
            core.apply_probe(self.generated_a)

    def test_n4_bounds_check_and_host_harness(self) -> None:
        region = self.region
        self.assertIn("if (!body || body_len < 4u)", region)
        self.assertIn("if (body_len < 36u)", region)
        self.assertLess(region.index("if (body_len < 36u)"), region.index("(unsigned)body[32]"))
        self.assertNotRegex(
            region.split("if (body_len < 36u)", 1)[0],
            re.compile(r"body\[(3[2-5])\]"),
        )
        if not self.cc:
            self.skipTest("no host C compiler available")
        self.assertEqual(self.compile_returncode, 0, self.compile_stderr[:4000])
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertIn(
            "CASE=SHORT3\n"
            "V4_RING_PHASE=INITIAL\n"
            "V4_RING_MONOTONIC_MS=123\n"
            "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH\n",
            self.harness_stdout,
        )
        self.assertIn(
            "CASE=SHORT20\n"
            "V4_RING_PHASE=RETRANSMIT\n"
            "V4_RING_MONOTONIC_MS=123\n"
            "V4_RING_PEER_CONNECTION=1234\n"
            "V4_RING_BODY_32_35=----\n"
            "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH\n",
            self.harness_stdout,
        )
        self.assertIn(
            "CASE=FULL36\n"
            "V4_RING_PHASE=INITIAL\n"
            "V4_RING_MONOTONIC_MS=123\n"
            "V4_RING_PEER_CONNECTION=abcd\n"
            "V4_RING_BODY_32_35=01234567\n"
            "V4_RING_PARSE_STATUS=OK\n",
            self.harness_stdout,
        )

    def test_n6_listener_markers_and_no_forbidden_name(self) -> None:
        for marker in (
            "V4_RING_BODY_32_35",
            "V4_RING_PEER_CONNECTION",
            "V4_RING_PHASE",
            "V4_RING_MONOTONIC_MS",
            "V4_RING_PARSE_STATUS=OK",
            "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
            "VIDEO_PACKET_COUNT_AT_REPEAT",
            "AUDIO_PACKET_COUNT_AT_REPEAT",
            "LAST_VIDEO_RTP_MONOTONIC_MS",
            "LAST_AUDIO_RTP_MONOTONIC_MS",
            "RX_STALLED=true",
            "RTP_STALL_SECONDS=%llu",
            "p80_video_stalled || p80_audio_stalled",
            "CTPP_TRACE_DIRECTION=IN",
            "CTPP_TRACE_DIRECTION=OUT",
        ):
            self.assertIn(marker, self.generated_a)
        self.assertNotIn(_forbidden_name(), self.generated_a)
        self.assertNotIn("CTPP_TRACE_PAYLOAD", self.generated_a)
        self.assertNotIn("CTPP_TRACE_HEX", self.generated_a)

    def test_n7_frozen_pin_invariance_and_no_tracked_pin_edits(self) -> None:
        self.assertEqual(_sha256_bytes(SOURCE), EXPECTED_FROZEN_SHA)
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=no", "--", str(SOURCE.relative_to(REPO))],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        changed_existing = [line for line in status if line[:2] != "??"]
        self.assertEqual(changed_existing, [])

    def test_include_p116_and_default_listener_cli_outputs_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p116-r68-cli-") as tmp_name:
            tmp = Path(tmp_name)
            output_default = tmp / "default.c"
            output_include = tmp / "include.c"
            base_argv = [
                sys.executable,
                str(MEDIA / "entrance_p116_r68_ringid_probe_transform.py"),
                "--source",
                str(SOURCE),
            ]
            env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(MEDIA)}
            default = subprocess.run(
                [*base_argv, "--output", str(output_default)],
                text=True,
                capture_output=True,
                env=env,
            )
            include = subprocess.run(
                [*base_argv, "--output", str(output_include), "--include-p116"],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(default.returncode, 0, default.stderr + default.stdout)
            self.assertEqual(include.returncode, 0, include.stderr + include.stdout)
            self.assertEqual(output_default.read_text(encoding="utf-8"), output_include.read_text(encoding="utf-8"))
            self.assertEqual(_sha256_text(output_include.read_text(encoding="utf-8")), self.generated_sha)

    def test_no_include_p116_listener_fails_closed_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p116-r68-no-include-") as tmp_name:
            run = subprocess.run(
                [
                    sys.executable,
                    str(MEDIA / "entrance_p116_r68_ringid_probe_transform.py"),
                    "--source",
                    str(SOURCE),
                    "--output",
                    str(Path(tmp_name) / "generated.c"),
                    "--no-include-p116",
                ],
                text=True,
                capture_output=True,
                env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(MEDIA)},
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("R68 requires --include-p116", run.stderr)
            self.assertNotIn("Traceback", run.stderr + run.stdout)


if __name__ == "__main__":
    unittest.main()
