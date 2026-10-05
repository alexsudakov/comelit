#!/usr/bin/env python3
"""P121: gather-only ``stun-initial-timeout`` override (250 ms) with fail-closed restore.

Structural proof against the real regenerated production source (never a hand-written
excerpt), plus the diff-scope, safety and instrumentation invariants of the round.

Forensic basis (exact libnice 0.1.22 sources, see P120): ``stun-initial-timeout`` (RTO) is
used only by the discovery/gathering timers, never by ICE connectivity checks
(``agent/conncheck.c`` computes its own timer), so shortening it for the gathering window
cannot change check behaviour. With RTO=250 and the untouched default Rc=3 the exact
schedule from ``stun/usages/timer.c`` is attempts at 0/250/750 with expiry at 1000 ms
(previously 2000 ms), i.e. the unanswered discovery transactions die ~1000 ms earlier.

The change is delivered as a new downstream transform overlay
(``entrance_p121_gather_initial_timeout_transform.py``) composed on top of the P119
candidate; the frozen raw source file is never edited.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
MEDIA_DIR = ROOT / "safety-poc" / "research" / "media" / "v1"
DOOR_SOURCE = (
    ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
)

sys.path.insert(0, str(MEDIA_DIR))
from entrance_p119_remote_sdp_l1_gather_diag_transform import (  # noqa: E402
    transform as p119_transform,
)
from entrance_p121_gather_initial_timeout_transform import (  # noqa: E402
    transform as p121_transform,
)

P119_SOURCE_SHA = "c4ebe732effb7e8c4b497f5fbd37dbb1619839496face4975b42f12d1f7bd961"
P121_SOURCE_SHA = "ebdd16ddcdccadb7469ed6fd1dbe213ffb845266b107657dcfbe860ffc6ed269"
SET_MARKER = "GATHER_INITIAL_TIMEOUT_SET_MS=250"
RESTORED_MARKER = "GATHER_INITIAL_TIMEOUT_RESTORED_MS=500"

P119_MARKERS = (
    "G0_NATIVE_PROCESS_START_MONOTONIC_MS=",
    "G1_NICE_AGENT_READY_MONOTONIC_MS=",
    "G2_GATHER_CALL_MONOTONIC_MS=",
    "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS=",
    "G3_HOST_CANDIDATE_COUNT=",
    "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS=",
    "G4_SRFLX_CANDIDATE_COUNT=",
    "G5_GATHER_DONE_MONOTONIC_MS=",
    "G6_OFFER_WRITTEN_MONOTONIC_MS=",
    "RSP_VISIBLE_MONOTONIC_MS=",
    "RSP_LOADED_MONOTONIC_MS=",
)

# Every line the overlay is allowed to insert, as exact stripped fragments.
ALLOWED_INSERTED_LINES = {
    "static gboolean gather_initial_timeout_restored = FALSE;",
    "/*",
    "*/",
    "static void",
    "gather_initial_timeout_restore(void)",
    "{",
    "}",
    "if (gather_initial_timeout_restored)",
    "return;",
    "if (!agent)",
    "gather_initial_timeout_restored = TRUE;",
    "g_object_set(",
    "agent,",
    '"stun-initial-timeout",',
    "500,",
    "250,",
    "NULL",
    ");",
    'printf("GATHER_INITIAL_TIMEOUT_RESTORED_MS=500\\n");',
    'printf("GATHER_INITIAL_TIMEOUT_SET_MS=250\\n");',
    "fflush(stdout);",
    "gather_initial_timeout_restore();",
}

ALLOWED_INSERTED_COMMENT_FRAGMENTS = (
    "* Gather-only stun-initial-timeout override: set to 250 ms immediately",
    "* before nice_agent_gather_candidates(), restored to the libnice default",
    "* (500 ms) exactly once via this idempotent helper. Called on every path",
    "* out of gathering/connectivity so the restore is fail-closed. Never",
    "* used by ICE connectivity checks (agent/conncheck.c computes its own",
    "* timer independently from an unrelated retransmission-count property",
    "* this override never touches).",
)


def _generate(transform) -> str:
    return transform(DOOR_SOURCE.read_text(encoding="utf-8"), include_p116=True)


class P121GeneratedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p119_source = _generate(p119_transform)
        cls.source = _generate(p121_transform)
        cls.diff = list(
            difflib.unified_diff(
                cls.p119_source.splitlines(),
                cls.source.splitlines(),
                lineterm="",
                n=0,
            )
        )
        cls.inserted = [
            line[1:].strip()
            for line in cls.diff
            if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
        ]
        cls.removed = [
            line[1:].strip()
            for line in cls.diff
            if line.startswith("-") and not line.startswith("---") and line[1:].strip()
        ]

    def test_baseline_and_candidate_source_identities(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.p119_source.encode("utf-8")).hexdigest(), P119_SOURCE_SHA
        )
        self.assertEqual(
            hashlib.sha256(self.source.encode("utf-8")).hexdigest(), P121_SOURCE_SHA
        )

    # --- 1. the 250 ms set happens before the gather call -------------------------

    def test_set_call_and_marker_precede_the_gather_call(self) -> None:
        source = self.source
        set_index = source.index('"stun-initial-timeout",\n        250')
        marker_index = source.index(SET_MARKER)
        gather_index = source.index("nice_agent_gather_candidates(", marker_index)
        self.assertLess(set_index, marker_index)
        self.assertLess(marker_index, gather_index)
        # nothing but whitespace/fflush between the marker and the gather call
        between = source[marker_index + len(SET_MARKER) : gather_index]
        self.assertRegex(between, r'^\\n"\);\n    fflush\(stdout\);\n\n    if \(!')
        self.assertEqual(source.count(SET_MARKER), 1)

    # --- 2. restore at gathering-done --------------------------------------------

    def test_restore_is_the_first_statement_of_candidate_gathering_done_cb(self) -> None:
        definition = self.source.index(
            "static void\ncandidate_gathering_done_cb("
        )
        body = self.source[definition:]
        brace = body.index("{")
        call_index = body.index("gather_initial_timeout_restore();")
        # between the opening brace and the restore call there may be nothing but whitespace
        self.assertEqual(body[brace + 1 : call_index].strip(), "")
        following = body[call_index:]
        # the restore precedes every other statement of the callback
        for later in ("printf(", "g_object_set(", "g_file_get_contents(", "chmod("):
            self.assertLess(call_index, following.index(later) if later in following else len(body))

    def test_restore_helper_sets_the_libnice_default_and_announces_it_once(self) -> None:
        helper_start = self.source.index("gather_initial_timeout_restore(void)")
        helper = self.source[helper_start:]
        helper_body = helper[: helper.index("\n}\n")]
        self.assertIn('"stun-initial-timeout",\n        500', helper_body)
        self.assertEqual(helper_body.count('"stun-initial-timeout"'), 1)
        self.assertEqual(self.source.count(RESTORED_MARKER), 1)
        self.assertIn('printf("%s\\n");' % RESTORED_MARKER, self.source)
        # idempotent: a static guard returns early, and the flag is set before the write
        self.assertIn("static gboolean gather_initial_timeout_restored = FALSE;", self.source)
        self.assertIn("if (gather_initial_timeout_restored)\n        return;", helper_body)
        self.assertIn("if (!agent)\n        return;", helper_body)
        self.assertLess(
            helper_body.index("gather_initial_timeout_restored = TRUE;"),
            helper_body.index('"stun-initial-timeout"'),
        )

    # --- 3. fail-closed restore on all paths -------------------------------------

    def test_restore_is_called_on_all_four_paths(self) -> None:
        source = self.source
        self.assertEqual(source.count("gather_initial_timeout_restore();"), 4)
        # a) gathering-done
        self.assertIn("candidate_gathering_done_cb(", source)
        # b) gather-start failure branch
        fail_index = source.index("ICE_GATHER_START=FAIL")
        self.assertIn(
            "gather_initial_timeout_restore();",
            source[fail_index : fail_index + 600],
        )
        # c) FAILED component state
        failed_index = source.index("ICE_CONNECTIVITY=FAIL")
        self.assertIn(
            "gather_initial_timeout_restore();",
            source[max(0, failed_index - 2000) : failed_index + 400],
        )
        # d) teardown catch-all: immediately after the main loop returns
        loop_index = source.index("g_main_loop_run(loop);")
        tail = source[loop_index:]
        self.assertLess(tail.index("gather_initial_timeout_restore();"), 120)

    # --- 4/5. nothing else changed ------------------------------------------------

    def test_retransmission_timeout_and_other_timers_are_never_written(self) -> None:
        for forbidden in (
            '"stun-max-retransmissions"',
            '"timer-ta"',
            '"stun-reliable-timeout"',
            '"nomination-mode"',
            '"controlling-mode",\n        TRUE',
        ):
            self.assertNotIn(forbidden, self.source)
        self.assertNotIn('"stun-max-retransmissions"', self.source)

    def test_exactly_two_property_writes_were_added_and_both_target_the_initial_timeout(
        self,
    ) -> None:
        before = self.p119_source.count("g_object_set(")
        after = self.source.count("g_object_set(")
        self.assertEqual(after, before + 2)
        new_writes = [
            line for line in self.inserted if line == '"stun-initial-timeout",'
        ]
        self.assertEqual(len(new_writes), 2)

    def test_connectivity_check_semantics_cannot_be_reached_by_this_change(self) -> None:
        # no inserted line may mention the check machinery or any of its knobs
        forbidden = (
            "conncheck",
            "priv_compute",
            "timer_ta",
            "nomination",
            "controll",
            "pseudotcp",
            "ctpp",
            "rtpc",
            "stun_server",
            "relay",
            "local_address",
        )
        for line in self.inserted:
            if line.startswith("*") or line.startswith("/*"):
                continue  # documentation comment, not code
            lowered = line.lower()
            for token in forbidden:
                self.assertNotIn(token, lowered, msg=f"unexpected token {token!r} in {line!r}")
        # runtime order matters, not file order: within the gathering-done callback the
        # restore happens before the offer is written/announced, and the connectivity
        # checks can only start after the remote candidates are imported (which requires
        # the parent to have written remote.sdp, i.e. strictly after gathering-done).
        definition = self.source.index("static void\ncandidate_gathering_done_cb(")
        callback = self.source[definition:]
        self.assertLess(
            callback.index("gather_initial_timeout_restore();"),
            callback.index("G6_OFFER_WRITTEN_MONOTONIC_MS"),
        )
        self.assertIn("nice_agent_gather_candidates(", self.source)

    # --- 6. P119 diagnostics intact ----------------------------------------------

    def test_p119_diagnostics_are_intact(self) -> None:
        for marker in P119_MARKERS:
            self.assertEqual(self.source.count(marker), 1, msg=marker)
        for marker in ("RSP_VISIBLE_MONOTONIC_MS=", "RSP_LOADED_MONOTONIC_MS="):
            self.assertEqual(self.source.count(marker), 1, msg=marker)
        # the L1 change and settle are untouched by this round
        self.assertNotIn("remote_stable_ticks", self.source)
        self.assertIn("#define ENTRANCE_SIGNAL_SETTLE_MS 1000", self.source)

    # --- 7. bounded diff scope ----------------------------------------------------

    def test_generated_diff_is_limited_to_the_expected_scope(self) -> None:
        self.assertEqual(self.removed, [])
        for line in self.inserted:
            if line in ALLOWED_INSERTED_LINES:
                continue
            self.assertTrue(
                any(fragment == line for fragment in ALLOWED_INSERTED_COMMENT_FRAGMENTS),
                msg=f"unexpected inserted line: {line!r}",
            )
        self.assertEqual(
            len([l for l in self.inserted if l == "gather_initial_timeout_restore();"]), 4
        )

    def test_new_marker_lines_carry_no_network_credential_or_sdp_content(self) -> None:
        pattern = re.compile(
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|candidate:|ufrag|ice-pwd|password|:[0-9]{4,5}|a="
        )
        for line in self.inserted:
            if "printf(" in line:
                self.assertIsNone(pattern.search(line), msg=line)


class P121InstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.timeline = (COMPONENT / "latency_timeline.py").read_text(encoding="utf-8")
        cls.transport = (COMPONENT / "media_transport.py").read_text(encoding="utf-8")

    def test_transport_parses_both_new_markers(self) -> None:
        self.assertIn("GATHER_INITIAL_TIMEOUT_SET_MS", self.transport)
        self.assertIn("GATHER_INITIAL_TIMEOUT_RESTORED_MS", self.transport)

    def test_timeline_exposes_the_three_new_fields(self) -> None:
        for field in (
            "GATHER_INITIAL_TIMEOUT_SET_MS",
            "GATHER_INITIAL_TIMEOUT_RESTORED_MS",
            "GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED",
        ):
            self.assertIn(field, self.timeline)
        self.assertIn('"true" if GATHER_INITIAL_TIMEOUT_RESTORED_MS in self._native', self.timeline)

    def test_field_order_pin_covers_the_new_fields(self) -> None:
        p117_test = (
            ROOT / "safety-poc" / "tests" / "test_p117_camera_e2e_latency_timeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"GATHER_INITIAL_TIMEOUT_SET_MS",', p117_test)
        self.assertIn('"GATHER_INITIAL_TIMEOUT_RESTORED_MS",', p117_test)
        self.assertIn('"GATHER_INITIAL_TIMEOUT_RESTORE_CONFIRMED",', p117_test)
        self.assertIn("len(EXPECTED_FIELD_ORDER), 38", p117_test)


if __name__ == "__main__":
    unittest.main()
