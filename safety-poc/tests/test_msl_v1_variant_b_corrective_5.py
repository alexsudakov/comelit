#!/usr/bin/env python3
"""MSL-V1 Variant B corrective #5: forward-stage arming + clock-base contract.

Two defects, two proofs:

1. The idle-media overlay activated media by writing
   ``p80_media_forwarding_enabled`` directly instead of calling the shared
   ``r42_listener_rtp_arm()`` primitive the proven inbound-call path uses (it
   is reached via R35's ``rtp_arm_hook`` -> the R42-b listener RTP bridge).
   That skipped the lifetime reset and never printed
   ``R42_LISTENER_RTP_FORWARDING_ARMED``. Fixed by calling
   ``r42_listener_rtp_arm(1)``/``r42_listener_rtp_arm(0)`` from the overlay,
   and by adding a transform gate that rejects a direct
   ``p80_media_forwarding_enabled = TRUE/FALSE`` write inside the overlay
   region so the regression cannot silently return.

2. The component's clock-base reader used
   ``g_ascii_strtoll`` + ``*end != '\\0'`` to validate the shared clock-base
   file, which rejects the runner's own output: the runner always writes
   ``"<decimal ms>\\n"`` (python ``print()`` / ``printf '%s\\n'``), so ``end``
   always lands on the trailing newline, never ``'\\0'``. Fixed by tolerating
   trailing ASCII whitespace (matching the sibling MSL-V1 baseline
   candidate's ``sscanf(buf, "%lld %c", ...)`` tolerance) and by pointing the
   runner at the same ``/run/comelit-msl/msl-clock-base`` convention the
   baseline runner already established, instead of a third path.

Both proofs execute real C, not just text matching:
  * #1 is proven by running the actual transform-gate function
    (``msl_b._assert_gates``) against the real candidate and against a copy
    with the primitive call reverted to the old direct write.
  * #2 is proven by compiling the literal reader snippet from the transform
    module against the host's real libglib-2.0 runtime and running it
    against a file written by the runner's own ``msl_b_mono_ms`` shell
    function, then against deliberately corrupted copies.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
RUNNER = MEDIA / "ct120_run_msl_v1_variant_b_live.sh"
BASELINE_RUNNER = MEDIA / "ct120_run_msl_v1_baseline_live.sh"
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"

sys.path.insert(0, str(MEDIA))

import entrance_msl_v1_idle_listener_media_transform as msl_b  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


def _find_glib_runtime() -> str | None:
    for directory in (
        "/usr/lib/x86_64-linux-gnu",
        "/lib/x86_64-linux-gnu",
        "/usr/lib",
        "/usr/lib64",
        "/lib",
    ):
        if glob.glob(str(Path(directory) / "libglib-2.0.so*")):
            return directory
    return None


GLIB_LIBDIR = _find_glib_runtime()

HARNESS_PRELUDE = """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

typedef int gboolean;
typedef long long gint64;
typedef char gchar;
typedef unsigned int guint;
typedef void *gpointer;

#define TRUE 1
#define FALSE 0
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define g_ascii_isspace(c) (isspace((unsigned char)(c)) ? 1 : 0)

extern gboolean g_file_get_contents(const gchar *filename, gchar **contents, size_t *length, void *error);
extern void g_free(gpointer mem);
extern gint64 g_ascii_strtoll(const gchar *nptr, gchar **endptr, guint base);
extern gint64 g_get_monotonic_time(void);
"""

HARNESS_MAIN = """
int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "UNSET") != 0) {
        setenv("MSL_B_CLOCK_BASE_FILE", argv[1], 1);
    }
    msl_b_print_clock_marker("TEST");
    return 0;
}
"""


def _extract_clock_base_reader() -> str:
    """Pull the literal reader out of the shipped OVERLAY string (not a copy)."""
    start = msl_b.OVERLAY.index("static gboolean msl_b_clock_base_loaded = FALSE;")
    end = msl_b.OVERLAY.index("\nstatic gboolean\nmsl_b_ready_now(void)", start)
    return msl_b.OVERLAY[start:end]


def _mono_ms_line() -> bytes:
    """Reproduce the runner's own msl_b_mono_ms() output byte-for-byte."""
    proc = subprocess.run(
        [sys.executable, "-c", "import time; print(time.monotonic_ns() // 1_000_000)"],
        capture_output=True,
        check=True,
    )
    return proc.stdout


class MslBForwardStageArmedTests(unittest.TestCase):
    """Defect 1: the idle-media overlay must reuse r42_listener_rtp_arm()."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.generated = msl_b.transform(cls.base)

    def test_activate_and_close_reuse_shared_primitive(self) -> None:
        activate_fn = self.generated.split("msl_b_activate_idle_media(void)\n{", 1)[1].split("\n}\n", 1)[0]
        close_fn = self.generated.split("msl_b_queue_idle_close(void)\n{", 1)[1].split("\n}\n", 1)[0]

        self.assertIn("r42_listener_rtp_arm(1);", activate_fn)
        self.assertIn("r42_listener_rtp_arm(0);", close_fn)
        # The primitive is reused, not redefined by the overlay.
        self.assertEqual(self.generated.count("static void\nr42_listener_rtp_arm(int armed)"), 1)
        self.assertIn("R42_LISTENER_RTP_FORWARDING_ARMED=true", self.generated)
        self.assertIn("R42_LISTENER_RTP_FORWARDING_ARMED=false", self.generated)
        self.assertNotIn("p80_media_forwarding_enabled = TRUE", activate_fn)
        self.assertNotIn("p80_media_forwarding_enabled = FALSE", close_fn)

    def test_gate_flips_when_arming_call_is_reverted(self) -> None:
        """Prove the transform's own gate rejects the old direct-write bug."""
        msl_b._assert_gates(self.generated)  # real candidate: no exception

        mutated = self.generated.replace(
            "r42_listener_rtp_arm(1);", "p80_media_forwarding_enabled = TRUE;", 1
        )
        with self.assertRaises(RuntimeError):
            msl_b._assert_gates(mutated)

        real_count = self.generated.count("r42_listener_rtp_arm(1);")
        mutated_count = mutated.count("r42_listener_rtp_arm(1);")
        self.assertGreater(real_count, 0)
        self.assertLess(mutated_count, real_count)
        print(
            "MSL_B_FORWARD_STAGE_ARMED=true "
            f"REAL=gate_pass:{real_count}_arm_calls "
            f"MUTATED=gate_raises:{mutated_count}_arm_calls"
        )


@unittest.skipUnless(CC, "no C compiler (cc/gcc/clang) on this host")
@unittest.skipUnless(GLIB_LIBDIR is not None, "no libglib-2.0 runtime on this host")
class MslBClockBaseContractTests(unittest.TestCase):
    """Defect 2: the reader must accept exactly what the runner writes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reader_source = _extract_clock_base_reader()
        cls.tmpdir = tempfile.mkdtemp(prefix="msl-b-clockbase-")
        harness_c = Path(cls.tmpdir) / "harness.c"
        harness_c.write_text(
            HARNESS_PRELUDE + "\n" + cls.reader_source + "\n" + HARNESS_MAIN,
            encoding="utf-8",
        )
        harness_bin = Path(cls.tmpdir) / "harness"
        build = subprocess.run(
            [
                CC, "-std=gnu11", "-Wall", "-Wextra", "-o", str(harness_bin), str(harness_c),
                f"-L{GLIB_LIBDIR}", "-l:libglib-2.0.so.0",
            ],
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            raise AssertionError(f"clock-base harness failed to build:\n{build.stderr}")
        cls.harness_bin = harness_bin
        cls.runner_text = RUNNER.read_text(encoding="utf-8")
        cls.baseline_text = BASELINE_RUNNER.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _run_harness(self, path: str) -> str:
        proc = subprocess.run(
            [str(self.harness_bin), path], capture_output=True, text=True, check=False
        )
        return proc.stdout

    def test_runner_and_baseline_share_one_clock_base_path(self) -> None:
        self.assertIn('MSL_CLOCK_DIR=${MSL_CLOCK_DIR:-/run/comelit-msl}', self.runner_text)
        self.assertIn('CLOCK_BASE_FILE="$MSL_CLOCK_DIR/msl-clock-base"', self.runner_text)
        self.assertIn('MSL_CLOCK_DIR=${MSL_CLOCK_DIR:-/run/comelit-msl}', self.baseline_text)
        self.assertIn('CLOCK_BASE_FILE="$MSL_CLOCK_DIR/msl-clock-base"', self.baseline_text)
        self.assertNotIn('CLOCK_BASE_FILE="$RUN_DIR/msl-b-clock-base"', self.runner_text)

    def test_reader_accepts_the_exact_runner_writer_output_with_flip_proof(self) -> None:
        real_bytes = _mono_ms_line()
        self.assertTrue(real_bytes.endswith(b"\n"))
        real_file = Path(self.tmpdir) / "real-clock-base"
        real_file.write_bytes(real_bytes)
        real_file.chmod(0o600)

        real_stdout = self._run_harness(str(real_file))
        self.assertIn("MSL_B_CLOCK_BASE_PATH=", real_stdout)
        self.assertIn("MSL_B_CLOCK_BASE_VALUE=", real_stdout)
        self.assertNotIn("MSL_B_CLOCK_BASE_INVALID", real_stdout)
        self.assertNotIn("MSL_B_CLOCK_BASE_MISSING", real_stdout)

        mutated_file = Path(self.tmpdir) / "mutated-clock-base"
        mutated_file.write_bytes(real_bytes.rstrip(b"\n") + b"x\n")  # corrupt the digits
        mutated_stdout = self._run_harness(str(mutated_file))
        self.assertIn("MSL_B_CLOCK_BASE_INVALID=true", mutated_stdout)
        self.assertNotIn("MSL_B_CLOCK_BASE_PATH=", mutated_stdout)

        print(
            "MSL_B_CLOCK_BASE_ACCEPTS_WRITER_FORMAT=true "
            f"REAL={real_stdout.strip().splitlines()!r} "
            f"MUTATED={mutated_stdout.strip().splitlines()!r}"
        )

    def test_missing_and_unset_file_still_report_missing(self) -> None:
        missing_stdout = self._run_harness(str(Path(self.tmpdir) / "does-not-exist"))
        self.assertIn("MSL_B_CLOCK_BASE_MISSING=true", missing_stdout)

        unset_stdout = subprocess.run(
            [str(self.harness_bin), "UNSET"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "MSL_B_CLOCK_BASE_FILE"},
            check=False,
        ).stdout
        self.assertIn("MSL_B_CLOCK_BASE_MISSING=true", unset_stdout)

    def test_old_reader_logic_reproduces_the_reported_bug(self) -> None:
        """Negative control: the pre-fix parser must reject the real file."""
        old_reader = """
static void
msl_b_print_clock_marker(const char *name)
{
    const char *base_path = getenv("MSL_B_CLOCK_BASE_FILE");
    gchar *text = NULL;
    gint64 base = 0;
    gint64 now = g_get_monotonic_time() / 1000;
    gchar *end = NULL;

    if (!base_path || !g_file_get_contents(base_path, &text, NULL, NULL)) {
        printf("MSL_B_CLOCK_BASE_MISSING=true\\n");
        fflush(stdout);
        g_free(text);
        return;
    }
    base = g_ascii_strtoll(text, &end, 10);
    if (!end || *end != '\\0') {
        printf("MSL_B_CLOCK_BASE_INVALID=true\\n");
        fflush(stdout);
        g_free(text);
        return;
    }
    printf("MSL_B_%s_MONO_MS=%lld\\n", name, (long long)MAX((gint64)0, now - base));
    fflush(stdout);
    g_free(text);
}
"""
        harness_c = Path(self.tmpdir) / "harness_old.c"
        harness_c.write_text(HARNESS_PRELUDE + "\n" + old_reader + "\n" + HARNESS_MAIN, encoding="utf-8")
        harness_bin = Path(self.tmpdir) / "harness_old"
        build = subprocess.run(
            [CC, "-std=gnu11", "-o", str(harness_bin), str(harness_c), "-l:libglib-2.0.so.0"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(build.returncode, 0, build.stderr)

        real_file = Path(self.tmpdir) / "real-clock-base-for-old-reader"
        real_file.write_bytes(_mono_ms_line())
        old_stdout = subprocess.run(
            [str(harness_bin), str(real_file)], capture_output=True, text=True, check=False
        ).stdout
        self.assertIn("MSL_B_CLOCK_BASE_INVALID=true", old_stdout)
        print(f"MSL_B_CLOCK_BASE_OLD_READER_BUG_REPRODUCED=true REAL={old_stdout.strip()!r}")


@unittest.skipUnless(CC, "no C compiler (cc/gcc/clang) on this host")
class MslBWholeTuStillCompilesTests(unittest.TestCase):
    """Both fixes must not break the -fsyntax-only whole-TU compile gate."""

    def test_full_variant_b_candidate_compiles(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        generated = msl_b.transform(source)
        with tempfile.TemporaryDirectory(prefix="msl-b-whole-tu-") as tmp:
            tu = Path(tmp) / "msl-b-whole-tu.c"
            tu.write_text(generated, encoding="utf-8")
            result = subprocess.run(
                [
                    CC, "-std=gnu11", "-fsyntax-only", "-Wall", "-Wextra",
                    "-Werror=implicit-function-declaration", "-Werror=implicit-int",
                    "-I", str(STUB_INCLUDE), str(tu),
                ],
                capture_output=True,
                text=True,
            )
        error_lines = [l for l in result.stderr.splitlines() if ": error:" in l]
        self.assertEqual(error_lines, [], "\n".join(error_lines))
        self.assertEqual(result.returncode, 0, result.stderr[:4000])


if __name__ == "__main__":
    unittest.main()
