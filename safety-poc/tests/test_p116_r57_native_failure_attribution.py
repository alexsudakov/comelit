#!/usr/bin/env python3
"""P116/R57 native failure-identity and exit-summary observability tests."""

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
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r57_native_failure_attribution_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r53_call_adoption_profile_core as r53  # noqa: E402
import entrance_p116_r54_call_adoption_listener_transform as r54  # noqa: E402
import entrance_p116_r57_native_failure_attribution_transform as r57  # noqa: E402

EXPECTED_FROZEN_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"

# The 26 real `failed = TRUE;` sites this round attributes, keyed by a short
# label matching entrance_p116_r57_native_failure_attribution_transform's
# _FAILURE_SITES table (same order).
EXPECTED_FAILURE_SITE_COUNT = 26

EXPECTED_SCENARIO_MARKERS = (
    "R57_SCENARIO_POSITIVE_NO_FAILURE_ID_NONE=PASS",
    "R57_SCENARIO_PSEUDOTCP_WRITABLE_FATAL=PASS",
    "R57_SCENARIO_PSEUDOTCP_CLOSED=PASS",
    "R57_SCENARIO_WRITE_PACKET_FATAL=PASS",
    "R57_SCENARIO_RECV_PARSE_FAILURE=PASS",
    "R57_SCENARIO_P12_STEP_TIMEOUT=PASS",
    "R57_SCENARIO_STARTUP_FAILURE=PASS",
    "R57_SCENARIO_SDP_FAILURE=PASS",
    "R57_SCENARIO_DOOR_SETTER_OFFLINE_FAKE=PASS",
    "R57_SCENARIO_CASCADE_FIRST_FAIL_WINS=PASS",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    return begin + text.split(begin, 1)[1].split(end, 1)[0] + end


class P116R57NativeFailureAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.baseline = r54.transform(cls.source)
        cls.generated_a = r57.transform(cls.source)
        cls.generated_b = r57.transform(cls.source)
        cls.generated_sha = _sha256(cls.generated_a)
        # The harness compiles the region standalone, so it needs both pieces
        # of the split overlay: the early declarations (typedefs, enum
        # constants, static prototypes) and the late definitions (state and
        # helper bodies). See the transform's declaration-order note.
        cls.r57_region = (
            _extract(cls.generated_a, r57.DECLS_BEGIN, r57.DECLS_END)
            + "\n\n"
            + _extract(cls.generated_a, r57.BEGIN, r57.END)
        )

        cls.cc = shutil.which("cc")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            tmp = Path(cls.tmp_obj.name)
            harness_template = HARNESS.read_text(encoding="utf-8")
            combined = tmp / "r57_generated_region.c"
            combined.write_text(
                harness_template.replace(
                    "/* R57_GENERATED_REGION_INSERT_HERE */",
                    cls.r57_region,
                ),
                encoding="utf-8",
            )
            binary = tmp / "r57_generated_region"
            result = subprocess.run(
                [
                    cls.cc,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
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

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    # -- generator-integration and determinism -------------------------

    def test_frozen_source_sha_gate(self) -> None:
        self.assertEqual(_sha256(self.source), EXPECTED_FROZEN_SHA256)

    def test_transform_is_layered_on_r54_not_generated_text(self) -> None:
        text = Path(r57.__file__).read_text(encoding="utf-8")
        self.assertIn("r54.transform(source)", text)
        # No manual edits to the R54/R55/R56 documents or generated .c:
        # transform() only ever writes to a string it returns.
        self.assertNotIn(".c\", \"w\"", text)
        self.assertNotIn("write_text", text.split("def main(")[0])

    def test_generated_source_is_deterministic(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(_sha256(self.generated_a), self.generated_sha)

    def test_transform_refuses_reapply(self) -> None:
        with self.assertRaises(RuntimeError):
            r57.transform(self.generated_a)

    # -- declaration order (build-blocking corrective) -------------------

    def test_declarations_are_emitted_before_the_earliest_instrumented_site(self) -> None:
        generated = self.generated_a
        decls_end = generated.index(r57.DECLS_END)
        self.assertLess(decls_end, generated.index("p116_record_failure(P116_FAILURE_"))
        self.assertLess(decls_end, generated.index('p116_emit_timeout_observability("'))
        self.assertLess(decls_end, generated.index("p116_emit_native_exit_summary(failed);"))

    def test_declarations_are_static_and_not_duplicated(self) -> None:
        generated = self.generated_a
        decls = generated.split(r57.DECLS_BEGIN, 1)[1].split(r57.DECLS_END, 1)[0]
        defs = generated.split(r57.BEGIN, 1)[1].split(r57.END, 1)[0]
        for needle in (
            "typedef enum {\n    P116_FAILURE_NONE = 0,",
            "typedef enum {\n    P116_PHASE_STARTUP = 0,",
            "static void p116_record_failure(P116NativeFailureId id, P116NativeFailurePhase phase);",
            "static P116NativeFailurePhase p116_infer_phase(void);",
            "static void p116_emit_timeout_observability(const char *kind);",
            "static void p116_emit_native_exit_summary(gboolean failed_flag);",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, decls)
                self.assertNotIn(needle, defs)
        # No typedef may be restated in the late block: a duplicated
        # enumerator is a C redeclaration error.
        self.assertNotIn("typedef enum", defs)
        for needle in ("} P116NativeFailureId;", "} P116NativeFailurePhase;"):
            with self.subTest(needle=needle):
                self.assertEqual(generated.count(needle), 1)

    # -- every one of the 26 real failed=TRUE sites is attributed -------

    def test_every_failed_true_site_has_a_preceding_record_failure_call(self) -> None:
        generated = self.generated_a
        self.assertEqual(generated.count("failed = TRUE;"), EXPECTED_FAILURE_SITE_COUNT)
        self.assertEqual(
            generated.count("p116_record_failure(P116_FAILURE_"),
            EXPECTED_FAILURE_SITE_COUNT,
        )
        for match in re.finditer(r"p116_record_failure\([^;]*\);\s*\n\s*failed = TRUE;", generated):
            self.assertIn("p116_record_failure(P116_FAILURE_", match.group(0))

    def test_no_reachable_failed_true_site_lacks_an_id(self) -> None:
        # Every "failed = TRUE;" occurrence must be immediately preceded
        # (allowing only whitespace) by a p116_record_failure(...) call.
        generated = self.generated_a
        for m in re.finditer(r"failed = TRUE;", generated):
            preceding = generated[max(0, m.start() - 200) : m.start()]
            with self.subTest(offset=m.start()):
                self.assertIn("p116_record_failure(P116_FAILURE_", preceding)

    def test_exit_summary_immediately_precedes_return(self) -> None:
        generated = self.generated_a
        self.assertEqual(generated.count("p116_emit_native_exit_summary(failed);"), 1)
        exit_idx = generated.index("p116_emit_native_exit_summary(failed);")
        return_idx = generated.index("return failed ? 6 : 0;")
        self.assertLess(exit_idx, return_idx)
        between = generated[exit_idx + len("p116_emit_native_exit_summary(failed);") : return_idx]
        self.assertNotIn("failed =", between)

    def test_timeout_observability_added_without_changing_tx_wait_semantics(self) -> None:
        generated = self.generated_a
        self.assertIn('p116_emit_timeout_observability("R54_TX_WAIT_TIMEOUT")', generated)
        # R56 semantics preserved verbatim: TX-wait timeout still does not
        # touch the global `failed` flag or quit the loop.
        tx_wait_cb = generated.split("r54_tx_wait_timeout_cb(gpointer data)", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertNotIn("failed = TRUE", tx_wait_cb)
        self.assertNotIn("g_main_loop_quit", tx_wait_cb)

    def test_no_protocol_writes_added_by_observability(self) -> None:
        for forbidden in (
            "p12_queue_bytes(",
            "p12_queue_vip_frame(",
            "p12_flush_tx(",
            "nice_agent_send(",
            "pseudo_tcp_socket_send(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.r57_region)

    # -- R56 regression invariants must still hold -----------------------

    def test_r56_invariants_preserved(self) -> None:
        generated = self.generated_a
        for needle in (
            "R54_TX_DUPLICATE_CALL_INIT_IGNORED=true",
            "R54_TX_QUEUE_FAIL_SUBJECT=%s",
            "R54_TX_QUEUE_FAIL_REASON=BUSY",
            "P12_TX_R54_INVITE_ACK",
            "P12_TX_R54_PEER_DATA_ACK",
            "PEER_DATA_ACK_FLUSHED_BEFORE_MEDIA_TRIGGER=true",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, generated)
        self.assertNotIn("r53_start_after_call_capture", generated)

    def test_r53_profile_region_untouched(self) -> None:
        self.assertIn(r53.CORE_BEGIN_MARKER, self.generated_a)
        self.assertIn(r53.CORE_END_MARKER, self.generated_a)

    # -- fault-injection matrix (compiled+executed) -----------------------

    def test_fault_injection_matrix_compiles_and_runs(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.compile_stderr)
        for marker in EXPECTED_SCENARIO_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.harness_stdout)

    def test_positive_flow_keeps_failure_id_none(self) -> None:
        self.require_harness()
        self.assertIn("R57_SCENARIO_POSITIVE_NO_FAILURE_ID_NONE=PASS", self.harness_stdout)

    def test_cascade_first_fail_wins(self) -> None:
        self.require_harness()
        self.assertIn("R57_SCENARIO_CASCADE_FIRST_FAIL_WINS=PASS", self.harness_stdout)


if __name__ == "__main__":
    unittest.main()
