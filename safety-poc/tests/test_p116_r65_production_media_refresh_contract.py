#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r65_production_media_refresh_transform.py"
EXPECTED_GENERATED_SOURCE_SHA = (
    "4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c"
)

sys.path.insert(0, str(MEDIA))

import entrance_p116_r65_production_media_refresh_transform as r65_transform  # noqa: E402
import entrance_p116_r27_repeat_001a_transform as r27_transform  # noqa: E402
from entrance_p116_r65_production_media_refresh_transform import transform  # noqa: E402


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class P116R65ProductionMediaRefreshContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_source = SOURCE.read_text(encoding="utf-8")
        cls.candidate = transform(cls.base_source, include_p116=True)
        cls.sha = _sha256_text(cls.candidate)
        cls.r27_candidate = r27_transform.transform(cls.base_source, include_p116=True)

    def test_transform_composes_r27_and_requires_p116(self) -> None:
        self.assertIn(
            "import entrance_p116_r27_repeat_001a_transform as r27",
            TRANSFORM.read_text(),
        )
        with self.assertRaises(ValueError):
            transform(self.base_source, include_p116=False)

    def test_generated_source_sha_is_pinned(self) -> None:
        self.assertEqual(self.sha, EXPECTED_GENERATED_SOURCE_SHA)

    def test_live_observation_self_timeout_is_removed(self) -> None:
        # Flip: if R65 stopped stripping the R27 live-proof bound, this
        # candidate would still force-quit media ~115s after activation,
        # which is exactly the historical-cutoff defect Phase C exists to fix.
        self.assertIn("r27_live_observation_timeout_cb", self.r27_candidate)
        self.assertNotIn("r27_live_observation_timeout_cb", self.candidate)
        self.assertNotIn("R27_OBSERVATION_TIMER_START", self.candidate)

    def test_refresh_count_and_session_cap_raised_for_production(self) -> None:
        self.assertIn("#define R27_MAX_REFRESH_COUNT 4u", self.r27_candidate)
        self.assertNotIn("#define R27_MAX_REFRESH_COUNT 4u", self.candidate)
        self.assertIn("#define R27_MAX_REFRESH_COUNT 32u", self.candidate)
        self.assertIn("#define R27_MAX_SINGLE_SESSION_SECONDS 600u", self.candidate)

    def test_production_promotion_markers_present(self) -> None:
        for marker in (
            'printf("R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=true\\n");',
            'printf("R65_PRODUCTION_REFRESH=true\\n");',
            'printf("R65_REFRESH_SELF_TIMEOUT=false\\n");',
            'printf("R65_REFRESH_BOUND_BY=MANAGER_600S_DEADLINE_OR_TEARDOWN\\n");',
        ):
            self.assertIn(marker, self.candidate)
        self.assertNotIn(
            'printf("R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false\\n");', self.candidate
        )

    def test_cadence_and_safety_margin_unchanged_from_live_evidence(self) -> None:
        self.assertIn("#define R27_REFRESH_CADENCE_SECONDS 25u", self.candidate)
        self.assertIn("#define R27_CADENCE_SAFETY_MARGIN_SECONDS 11u", self.candidate)
        self.assertIn('printf("CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE\\n");', self.candidate)

    def test_single_outstanding_no_retry_and_fail_closed_are_inherited_unchanged(self) -> None:
        # These are the R27-proven safety properties; R65 must not touch them.
        for invariant in (
            "if (r27_repeat_outstanding)\n        return FALSE;",
            "r27_refresh_fail_closed = TRUE;",
            'pseudotcp_begin_graceful_stop("r27-refresh-timeout")',
            'pseudotcp_begin_graceful_stop("r27-refresh-ambiguous")',
            "r27_repeat_timer_cancelled || pseudotcp_graceful_stop_started",
        ):
            self.assertIn(invariant, self.candidate)

    def test_door_and_gate_action_paths_unreachable_from_r65_changes(self) -> None:
        # The full candidate legitimately contains Door/Gate code elsewhere in
        # the shared base source (comelit-v4's actuation paths); what must be
        # proven here is that none of it was touched or newly reached by the
        # lines R65 actually added or changed relative to R27.
        r65_only_lines = set(self.candidate.splitlines()) - set(self.r27_candidate.splitlines())
        for forbidden in ("v4_door", "V4_DOOR", "DOOR_WRITE", "GATE_ACTION", "gate_action"):
            for line in r65_only_lines:
                self.assertNotIn(forbidden, line)

    def test_no_new_upstream_session_setup_path_added(self) -> None:
        # R65 only removes a research self-timeout and raises two constants;
        # it must not add any new ICE/PseudoTCP/CTPP/RTPC/self-activation
        # setup call that R27 did not already have.
        r65_only_lines = set(self.candidate.splitlines()) - set(self.r27_candidate.splitlines())
        for forbidden in (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P78_TX_RTPC_OPEN_1",
            "P78_TX_RTPC_OPEN_2",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
        ):
            for line in r65_only_lines:
                self.assertNotIn(forbidden, line)


def _extract_queue_function(candidate: str) -> str:
    start = candidate.index("static gboolean\nr27_queue_rtpc_client_001a_repeat(void)")
    end_marker = "/* === R27_REPEAT_001A_END === */"
    close = candidate.index("\n}\n", start) + len("\n}\n")
    assert close <= candidate.index(end_marker)
    return candidate[start:close]


def _extract_max_refresh_count_define(candidate: str) -> str:
    start = candidate.rindex("#define R27_MAX_REFRESH_COUNT", 0, candidate.index("R27_REPEAT_001A_END"))
    end = candidate.index("\n", start) + 1
    return candidate[start:end]


def _compile_and_run_harness(candidate: str) -> str:
    # Compiles the *actual* generated r27_queue_rtpc_client_001a_repeat
    # function and the *actual* generated R27_MAX_REFRESH_COUNT macro (not
    # reimplementations), so this proves the real generated blocking guard
    # under the real production constant, not a hand-mirrored copy.
    real_queue_fn = _extract_queue_function(candidate)
    real_define = _extract_max_refresh_count_define(candidate)
    if "R27_MAX_REFRESH_COUNT" not in real_queue_fn:
        raise AssertionError("extracted queue function does not reference R27_MAX_REFRESH_COUNT")
    if "32u" not in real_define:
        raise AssertionError(f"unexpected production refresh count define: {real_define!r}")

    harness = textwrap.dedent(
        r'''
        #include <stdint.h>
        #include <stdio.h>

        typedef int gboolean;
        typedef unsigned int guint;
        typedef uint8_t guint8;
        typedef unsigned short guint16;
        typedef void *gpointer;

        #define TRUE 1
        #define FALSE 0

        __R27_MAX_REFRESH_COUNT_DEFINE__
        static guint r27_initial_001a_sent_count = 1u;
        static guint r27_repeat_001a_sent_count;
        static gboolean r27_third_001a_blocked;
        static gboolean failed;
        static void *loop;
        static int queue_call_count;
        static guint8 r27_rtpc_client_001a_repeat[128];
        static guint r27_rtpc_client_001a_repeat_len = 60u;
        static guint16 v4_ctpp_channel_id = 7u;

        enum { R27_TX_RTPC_CLIENT_001A_REPEAT = 1 };

        static void g_main_loop_quit(void *unused) { (void)unused; }
        static gboolean p12_queue_vip_frame(guint16 c, const guint8 *b, guint l, int k)
        { (void)c; (void)b; (void)l; (void)k; queue_call_count++; return TRUE; }
        static gboolean p12_flush_tx(void) { return TRUE; }
        static void p78_fail_rtpc(const char *marker) { (void)marker; failed = TRUE; }

        __R27_QUEUE_FUNCTION__

        static gboolean
        blocked_at(guint sent_count)
        {
            r27_repeat_001a_sent_count = sent_count;
            r27_third_001a_blocked = FALSE;
            failed = FALSE;
            queue_call_count = 0;
            (void)r27_queue_rtpc_client_001a_repeat();
            return r27_third_001a_blocked;
        }

        int main(void)
        {
            /* Flip: under the R27 research cap (4) this would already be
             * blocked at sent_count==4; under the production cap this must
             * not be blocked until sent_count==R27_MAX_REFRESH_COUNT. */
            if (blocked_at(4u)) {
                fprintf(stderr, "FAIL: blocked at research-era count 4 under production cap\n");
                return 1;
            }
            if (blocked_at(10u)) {
                fprintf(stderr, "FAIL: blocked at count 10 under production cap\n");
                return 1;
            }
            if (!blocked_at(R27_MAX_REFRESH_COUNT)) {
                fprintf(stderr, "FAIL: not blocked at the production backstop count\n");
                return 1;
            }
            puts("HARNESS_PASS");
            return 0;
        }
        '''
    ).replace(
        "__R27_MAX_REFRESH_COUNT_DEFINE__", real_define
    ).replace("__R27_QUEUE_FUNCTION__", real_queue_fn)
    with tempfile.TemporaryDirectory() as tmp:
        c_path = Path(tmp) / "r65_harness.c"
        exe_path = Path(tmp) / "r65_harness"
        c_path.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["/usr/bin/cc", "-std=c99", "-Wall", "-Wextra", str(c_path), "-o", str(exe_path)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            raise AssertionError(compiled.stderr)
        completed = subprocess.run([str(exe_path)], text=True, capture_output=True)
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
        return completed.stdout


class P116R65BehaviouralHarnessTests(unittest.TestCase):
    def test_production_refresh_count_backstop_flips_from_research_cap(self) -> None:
        candidate = transform(SOURCE.read_text(encoding="utf-8"), include_p116=True)
        output = _compile_and_run_harness(candidate)
        self.assertIn("HARNESS_PASS", output)


if __name__ == "__main__":
    unittest.main()
