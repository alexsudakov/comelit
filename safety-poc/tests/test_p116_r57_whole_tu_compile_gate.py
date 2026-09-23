#!/usr/bin/env python3
"""P116/R57 whole-translation-unit compile gate (build-blocking corrective).

The first R57 candidate failed the orchestrator's musl build with
``BUILD_RC=1`` and 11 errors -- ``implicit declaration of function
'p116_record_failure'``, ``'P116_FAILURE_P80_RTP_FORWARD' undeclared``,
``static declaration of 'p116_record_failure' follows non-static
declaration``. The cause was pure C declaration order: the generated R57
overlay emitted its typedefs, enums and helpers only at the late R54 anchor
(~line 3550 of the generated translation unit) while the earliest
instrumented call site is ``p80_try_forward_wrapped_rtp()`` at ~line 463.

Regenerating the .c and diffing text does not catch that class of defect:
the text is well-formed, it is the declaration order that is wrong. This
module is the missing check. It regenerates the real candidate through the
real transform and compiles the ENTIRE translation unit:

    cc -std=gnu11 -fsyntax-only -Wall -Wextra \\
       -Werror=implicit-function-declaration -Werror=implicit-int \\
       -I safety-poc/tests/native/whole_tu_stub_include <generated.c>

MODE: ``-fsyntax-only`` (parse + type-check every function in the unit,
produce no object code). This is deliberate: the offline sandbox has no
Alpine/musl glib-2.0 + libnice dev headers, so a full ``cc -c`` cannot run
here -- the orchestrator's musl container build remains the authoritative
one. ``-fsyntax-only`` is sufficient for this defect class because
undeclared identifiers, implicit declarations, conflicting redeclarations,
static/non-static conflicts and use-before-declaration are all front-end
errors emitted before any code generation.

ASSERTS (all of which the first R57 candidate failed):
  * exit status 0 -- no compiler error anywhere in the translation unit;
  * no ``error:`` diagnostic line at all;
  * none of the declaration-order diagnostics: ``implicit declaration``,
    ``undeclared``, ``conflicting types``, ``static declaration of``;
  * non-vacuity: the same command is proven to FAIL on (a) the exact
    pre-fix ordering (the early declaration block relocated to the late
    anchor, reproducing the candidate that failed the musl build) and
    (b) a minimal synthetic use-before-declaration unit.

No network I/O, no execution of the generated source, no binary produced.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r57_native_failure_attribution_transform as r57  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

# Documented gate mode: syntax/type checking only, whole translation unit.
COMPILE_MODE = "fsyntax-only"
COMPILE_FLAGS = (
    "-std=gnu11",
    "-fsyntax-only",
    "-Wall",
    "-Wextra",
    "-Werror=implicit-function-declaration",
    "-Werror=implicit-int",
)

TU_FILENAME = "r57-whole-tu.c"

DECLARATION_ORDER_DIAGNOSTICS = (
    "implicit declaration",
    "undeclared",
    "conflicting types",
    "static declaration of",
)

# The 26 sites the R57 overlay instruments; `failed = TRUE;` must not move.
EXPECTED_FAILED_TRUE_SITES = 26

# Write surfaces the orchestrator pinned on the generated source. R57 is
# strictly additive observability: none of these counts may change.
EXPECTED_WRITE_SURFACE_COUNTS = {
    "p12_queue_bytes(": 3,
    "p12_queue_vip_frame(": 13,
    "pseudo_tcp_socket_send(": 3,
    "p12_flush_tx(": 22,
    "r42_queue_media_channel_open(": 2,
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compile_whole_tu(text: str) -> subprocess.CompletedProcess:
    """Compile one translation unit with the documented gate mode."""
    with tempfile.TemporaryDirectory(prefix="p116-r57-tu-") as tmp:
        tu = Path(tmp) / TU_FILENAME
        tu.write_text(text, encoding="utf-8")
        return subprocess.run(
            [CC, *COMPILE_FLAGS, "-I", str(STUB_INCLUDE), str(tu)],
            text=True,
            capture_output=True,
        )


def _relocate_declarations_to_late_anchor(text: str) -> str:
    """Reproduce the first R57 candidate's ordering exactly.

    Moves the early declaration block (typedefs, enum constants, static
    prototypes) back to the late R54 anchor, i.e. leaves the earliest
    instrumented call sites with no visible declaration -- the defect class
    that failed the orchestrator's musl build.
    """
    start = text.index(r57.DECLS_BEGIN)
    end = text.index(r57.DECLS_END) + len(r57.DECLS_END)
    block = text[start:end]
    stripped = text.replace(block + "\n\n", "", 1)
    assert block not in stripped, "relocation control did not remove the early block"
    return stripped.replace(r57.BEGIN, r57.BEGIN + "\n" + block, 1)


def _first_call_offset(text: str, needle: str) -> int:
    pos = text.find(needle)
    if pos < 0:
        raise AssertionError(f"missing first-use needle: {needle}")
    return pos


class P116R57WholeTuCompileGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.generated = r57.transform(cls.source)
        cls.generated_sha = _sha256(cls.generated)
        cls.diagnostics_cache: dict[str, subprocess.CompletedProcess] = {}

    def compile_cached(self, key: str, text_factory) -> subprocess.CompletedProcess:
        if key not in self.diagnostics_cache:
            self.diagnostics_cache[key] = compile_whole_tu(text_factory())
        return self.diagnostics_cache[key]

    def require_cc(self) -> None:
        if not CC:
            self.skipTest(
                "no C compiler (cc/gcc/clang) on this host; whole-TU compile "
                "gate not executed -- the orchestrator's musl build remains "
                "authoritative"
            )

    # -- declaration order in the generated source -----------------------

    def test_declarations_precede_first_instrumented_use(self) -> None:
        generated = self.generated
        decls_end = generated.index(r57.DECLS_END)
        for first_use in (
            "p116_record_failure(P116_FAILURE_",
            'p116_emit_timeout_observability("',
            "p116_emit_native_exit_summary(failed)",
        ):
            with self.subTest(first_use=first_use):
                self.assertLess(decls_end, _first_call_offset(generated, first_use))

    def test_every_declaration_is_emitted_exactly_once(self) -> None:
        generated = self.generated
        for needle in (
            "} P116NativeFailureId;",
            "} P116NativeFailurePhase;",
            "static void p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase);",
        ):
            with self.subTest(needle=needle):
                self.assertEqual(generated.count(needle), 1)
        # The late definitions block must not restate the typedefs/enums:
        # a duplicated enumerator is a C redeclaration error.
        defs = generated.split(r57.BEGIN, 1)[1].split(r57.END, 1)[0]
        self.assertNotIn("typedef enum", defs)

    def test_generated_source_is_deterministic(self) -> None:
        self.assertEqual(r57.transform(self.source), self.generated)
        self.assertEqual(_sha256(r57.transform(self.source)), self.generated_sha)

    def test_protocol_write_surfaces_unchanged(self) -> None:
        for needle, expected in EXPECTED_WRITE_SURFACE_COUNTS.items():
            with self.subTest(needle=needle):
                self.assertEqual(self.generated.count(needle), expected)
        self.assertEqual(self.generated.count("failed = TRUE;"), EXPECTED_FAILED_TRUE_SITES)

    # -- the gate itself -------------------------------------------------

    def test_whole_tu_compiles_with_stub_headers(self) -> None:
        self.require_cc()
        result = self.compile_cached("generated", lambda: self.generated)

        self.assertIn("-fsyntax-only", COMPILE_FLAGS)
        self.assertEqual(
            result.returncode,
            0,
            "whole-TU compile gate failed:\n" + result.stderr[:4000],
        )
        error_lines = [l for l in result.stderr.splitlines() if ": error:" in l]
        self.assertEqual(error_lines, [])
        for diagnostic in DECLARATION_ORDER_DIAGNOSTICS:
            with self.subTest(diagnostic=diagnostic):
                self.assertNotIn(diagnostic, result.stderr)

    def test_gate_catches_the_original_declaration_order_defect(self) -> None:
        """Negative control: the pre-fix ordering must FAIL this gate."""
        self.require_cc()
        broken = self.compile_cached(
            "pre_fix_ordering",
            lambda: _relocate_declarations_to_late_anchor(self.generated),
        )

        self.assertNotEqual(
            broken.returncode,
            0,
            "gate did not catch the original declaration-order defect",
        )
        stderr = broken.stderr
        self.assertIn("implicit declaration", stderr)
        self.assertIn("p116_record_failure", stderr)
        self.assertIn("undeclared", stderr)
        self.assertIn("P116_FAILURE_P80_RTP_FORWARD", stderr)

    def test_gate_catches_synthetic_use_before_declaration(self) -> None:
        """The mode itself rejects use-before-declaration, independent of
        the generator: a minimal unit with the same shape must fail."""
        self.require_cc()
        synthetic = (
            "static void synth_caller(void)\n"
            "{\n"
            "    synth_record(SYNTH_FAILURE_STARTUP);\n"
            "}\n"
            "\n"
            "typedef enum { SYNTH_FAILURE_NONE = 0, SYNTH_FAILURE_STARTUP } SynthId;\n"
            "static void synth_record(SynthId id) { (void)id; }\n"
            "static void synth_entry(void) { synth_caller(); }\n"
        )
        result = compile_whole_tu(synthetic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implicit declaration", result.stderr)
        self.assertIn("SYNTH_FAILURE_STARTUP", result.stderr)

    def test_gate_is_not_vacuous_about_the_stub_headers(self) -> None:
        """A unit that includes the stubbed glib header must compile, so a
        green gate cannot be explained away by silently missing headers."""
        self.require_cc()
        probe = (
            '#include <glib.h>\n#include <nice/agent.h>\n#include <nice/pseudotcp.h>\n'
            "static gboolean probe_ok = FALSE;\n"
            "static void probe_use(void) { g_main_loop_quit(NULL); (void)probe_ok; }\n"
        )
        result = compile_whole_tu(probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stderr.splitlines():
            if "glib.h" in line and "No such file" in line:
                self.fail("stub glib.h was not used")


if __name__ == "__main__":
    unittest.main()
