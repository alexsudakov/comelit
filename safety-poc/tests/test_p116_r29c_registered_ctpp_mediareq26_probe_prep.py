from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_probe.sh"
BUILDER = MEDIA / "ct120_build_p80_haos_media_helper.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


def region(text: str, start: str, end: str) -> str:
    s = text.index(start)
    e = text.index(end, s)
    return text[s:e]


def builder_p116_flags() -> set[str]:
    text = BUILDER.read_text(encoding="utf-8")
    case_region = region(
        text,
        'case "$P80_BUILD_INCLUDE_P116" in',
        '[ "$FAIL" -eq 0 ] || exit 1',
    )
    return set(re.findall(r"P80_GENERATOR_P116_ARG=(--(?:no-)?include-p116)", case_region))


def transform_cli_flags() -> set[str]:
    tree = ast.parse(TRANSFORM.read_text(encoding="utf-8"))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value in {"--include-p116", "--no-include-p116"}:
                    flags.add(arg.value)
    return flags


def spans(pattern: str, text: str) -> list[tuple[int, int]]:
    return [match.span() for match in re.finditer(pattern, text)]


def within_any_span(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in ranges)


class P116R29CRegisteredCtppMediaReq26ProbePrep(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29c.transform(SOURCE.read_text(encoding="utf-8"))
        cls.state_region = region(
            cls.generated,
            "R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN",
            "R29_LISTENER_ATTACHED_MEDIA_STATE_END",
        )
        cls.attached_region = region(
            cls.generated,
            "R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN",
            "R29_ATTACHED_MEDIA_FUNCTIONS_END",
        )
        cls.builder_region = region(
            cls.generated,
            "r29c_build_mediareq26(R29CMediaReq26State state,",
            "r29c_emit_registered_mediareq26",
        )
        cls.live_queue_region = region(
            cls.generated,
            "r29c_queue_registered_mediareq26",
            "static void\nr29_print_scalar_snapshot",
        )
        cls.selfcheck_region = region(
            cls.generated,
            "static int\n\tr29_selfcheck(void)",
            "/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */",
        )
        cls.main_region = region(
            cls.generated,
            "main(int argc, char **argv)",
            "return r29c_exit_code;",
        )
        cls.self_activation_region = region(
            cls.generated,
            "entrance_signal_queue_self_activation(void)\n{",
            "static gboolean\nentrance_signal_queue_video_event",
        )
        cls.client_001a_region = region(
            cls.generated,
            "p78_queue_rtpc_client_001a(void)\n{",
            "static gboolean\np78_begin_rtpc_control",
        )

    def shell(self, script: str) -> str:
        proc = subprocess.run(
            ["bash", "-c", script],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout

    def test_generated_source_defines_le_helpers_once(self) -> None:
        for helper in ("read_le16", "read_le32"):
            definitions = re.findall(
                rf"static\s+guint(?:16|32)\s+{helper}\s*\([^)]*\)\s*\{{",
                self.generated,
            )
            self.assertEqual(
                len(definitions),
                1,
                f"{helper} must have exactly one generated definition",
            )

    def test_generated_source_declares_le_helpers_before_first_use(self) -> None:
        helper_types = {"read_le16": "guint16", "read_le32": "guint32"}
        for helper, return_type in helper_types.items():
            definition_spans = spans(
                rf"static\s+{return_type}\s+{helper}\s*\([^)]*\)\s*\{{",
                self.generated,
            )
            prototype_spans = spans(
                rf"static\s+{return_type}\s+{helper}\s*\(\s*const\s+guint8\s+\*p\s*\)\s*;",
                self.generated,
            )
            self.assertEqual(len(definition_spans), 1, f"{helper} definition count changed")
            self.assertEqual(len(prototype_spans), 1, f"{helper} prototype count changed")

            declaration_spans = prototype_spans + definition_spans
            call_positions = [
                match.start()
                for match in re.finditer(rf"\b{helper}\s*\(", self.generated)
                if not within_any_span(match.start(), declaration_spans)
            ]
            self.assertGreater(len(call_positions), 0, f"{helper} has no call sites")
            self.assertLess(
                min(start for start, _ in declaration_spans),
                min(call_positions),
                f"{helper} must be declared before its first call site",
            )

    def test_builder_has_exact_r29a_layout_and_distinct_states(self) -> None:
        for needle in (
            "R29C_MEDIAREQ26_OPEN",
            "R29C_MEDIAREQ26_STOP",
            "R29CMediaProfile",
            "r29c_build_mediareq26(R29CMediaReq26State state,",
            "const R29CMediaProfile *profile,",
            "write_le16(out + 0, 0x1100u);",
            "out[2] = 0x14u;",
            "out[2] = 0x94u;",
            "out[3] = 0x32u;",
            "out[3] = 0x00u;",
            "write_le32(out + 4, 0u);",
            "write_le16(out + 8, r29c_saved_media_channel_id);",
            "write_le16(out + 10, profile->max_rtp_payload);",
            "write_le32(out + 12, profile->bitrate);",
            "write_le16(out + 16, profile->max_width);",
            "write_le16(out + 18, profile->max_height);",
            "write_le16(out + 20, profile->requested_width);",
            "write_le16(out + 22, profile->requested_height);",
            "out[24] = profile->fps;",
            "out[25] = profile->reserved;",
        ):
            self.assertIn(needle, self.builder_region)
        self.assertIn("r29c_external_tested_client_profile", self.state_region)

    def test_open_stop_anchors_and_explicit_profile_sources_are_explicit(self) -> None:
        for needle in (
            "prefix_0x1100:SOURCED_SHAPE_CONSTANT:disasm2-csp_send_mediareq26_mov_w8_0x1100",
            "action_0x14:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w1_0x14",
            "action_0x94:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w1_0x94",
            "flags_0x32:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w2_0x32",
            "flags_0x00:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w2_wzr",
            "address_zero_tunnel_channel_form:SOURCED_SHAPE_CONSTANT:start_videorx_x3_xzr_stop_zero_slot",
            "saved_media_channel_id:SOURCED_RUNTIME:r29c_allocator_result_persisted",
            "max_rtp_payload:CLIENT_SUPPLIED_CONFIGURATION",
            "bitrate:CLIENT_SUPPLIED_CONFIGURATION",
            "max_width:CLIENT_SUPPLIED_CONFIGURATION",
            "max_height:CLIENT_SUPPLIED_CONFIGURATION",
            "requested_width:CLIENT_SUPPLIED_CONFIGURATION",
            "requested_height:CLIENT_SUPPLIED_CONFIGURATION",
            "fps:CLIENT_SUPPLIED_CONFIGURATION",
            "reserved:CLIENT_SUPPLIED_CONFIGURATION",
            "max_rtp_payload_zero:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots",
            "media_profile_zero_tail:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots",
        ):
            self.assertIn(needle, self.attached_region)
        self.assertNotIn("flags = 0x02u;", self.generated)
        self.assertNotIn("UNSOURCED:no_helper_runtime_accessor_equivalent", self.generated)
        self.assertNotIn("UNSOURCED:no_helper_call_config_runtime_source", self.generated)

    def test_registered_ctpp_binding_is_hypothesis_and_isolated(self) -> None:
        self.assertIn("REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true", self.attached_region)
        self.assertIn("EXPERIMENTAL_REGISTERED_CTPP_BINDING_ISOLATED=true", self.attached_region)
        self.assertIn("p12_queue_vip_frame(v4_ctpp_channel_id, body, 26u, kind)", self.live_queue_region)
        self.assertIn("CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=%s", self.attached_region)
        self.assertNotIn("R29_MEDIA_OPEN_MODEL=" + "PASS", self.generated)
        self.assertNotIn("R29_MEDIA_ONLY_TEARDOWN_MODEL=" + "PASS", self.generated)

    def test_one_shot_open_stop_counters_are_separate_from_forbidden_001a_forms(self) -> None:
        for marker in (
            "SELF_ACTIVATION_001A_SENT_COUNT=%u",
            "R27_REPEAT_001A_SENT_COUNT=%u",
            "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
            "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
            "ONE_SHOT_OPEN_GATE=%s",
            "ONE_SHOT_STOP_GATE=%s",
        ):
            self.assertIn(marker, self.attached_region)
        self.assertNotIn("p12_queue_vip_frame", self.self_activation_region)
        self.assertNotIn("p12_queue_vip_frame", self.client_001a_region)
        self.assertNotIn("p78_queue_rtpc_client_001a();", self.generated)

    def test_selfcheck_is_intercepted_and_orders_required_transitions(self) -> None:
        ordered = (
            "r29_listener_registered_ready = TRUE;",
            "r29c_allocate_media_channel_id(0x0000002au)",
            "r29c_build_mediareq26(R29C_MEDIAREQ26_OPEN, profile, body)",
            "r29c_assert_open_body_semantics(body, profile)",
            "r29c_emit_registered_mediareq26(R29C_MEDIAREQ26_OPEN)",
            "r29c_waiting_for_stop = TRUE;",
            "r29c_build_mediareq26(R29C_MEDIAREQ26_STOP, profile, body)",
            "r29c_assert_stop_body_semantics(body)",
            "r29c_emit_registered_mediareq26(R29C_MEDIAREQ26_STOP)",
            "r29_media_stop_completed = TRUE;",
            "r29c_note_final_research_session_cleanup();",
            "R29C_PROBE_READY=true",
        )
        last = -1
        for needle in ordered:
            pos = self.selfcheck_region.index(needle)
            self.assertGreater(pos, last)
            last = pos
        for forbidden in ("p12_queue_vip_frame", "p12_flush_tx", "send(", "sendto(", "connect("):
            self.assertNotIn(forbidden, self.selfcheck_region)

    def test_ready_criteria_markers_present(self) -> None:
        for marker in (
            "MEDIAREQ26_OPEN_BUILDER=%s",
            "MEDIAREQ26_STOP_BUILDER=%s",
            "R29E_MEDIA_PROFILE_MODEL=CLIENT_SUPPLIED_CONFIGURATION",
            "R29C_MEDIA_PROFILE_IMPLEMENTED=true",
            "R29C_PROFILE_SOURCE=EXTERNAL_TESTED_CLIENT_PROFILE",
            "R29C_EXTERNAL_PROFILE_ACCEPTED_FOR_BOUNDED_PROBE=%s",
            "OPEN_FIELDS_HAVE_PROVEN_SOURCES=%s",
            "STOP_FIELDS_HAVE_PROVEN_SOURCES=%s",
            "SELF_ACTIVATION_PATH_UNREACHABLE=true",
            "R27_REPEAT_PATH_UNREACHABLE=true",
            "MEDIA_ONLY_STOP_RESULT=%s",
            "FINAL_RESEARCH_SESSION_CLEANUP=%s",
            "R29C_OPEN_WRITE_COMPLETED_AT_MS=%lld",
            "R29C_RTP_OBSERVATION_STARTED_AT_MS=%lld",
            "R29C_RTP_OBSERVATION_ENDED_AT_MS=%lld",
            "R29C_WAITING_FOR_STOP=%s",
            "R29C_CANDIDATE_EXIT_REASON=%s",
            "R29C_CANDIDATE_EXIT_CODE=%d",
            "R29C_CANDIDATE_EXIT_AFTER_OPEN=%s",
            "R29C_CANDIDATE_EXIT_BEFORE_STOP=%s",
            "R29C_BUILDER=%s",
            "LIVE_PROBE_PREPARED=%s",
        ):
            self.assertIn(marker, self.attached_region)

    def test_candidate_lifetime_waits_for_sigusr2_after_full_observation(self) -> None:
        ordered = (
            "r29c_queue_registered_mediareq26(R29C_MEDIAREQ26_OPEN)",
            "R29C_RTP_OBSERVATION_STARTED_AT_MS=%lld",
            "g_timeout_add_seconds(10, r29c_rtp_observation_complete_cb, NULL)",
            "OPEN_SENT_OBSERVING_RTP",
            "r29c_rtp_observation_complete_cb(gpointer data)",
            "r29_media_observation_end_ms = p116_monotonic_ms();",
            "r29c_waiting_for_stop = TRUE;",
            "entrance_signal_stage = ENTRANCE_SIGNAL_DONE;",
            "R29C_WAITING_FOR_STOP=true",
            "OPEN_SENT_WAITING_FOR_STOP",
        )
        last = -1
        for needle in ordered:
            pos = self.attached_region.index(needle, max(0, last))
            self.assertGreater(pos, last)
            last = pos
        self.assertIn("R29C_OPEN_WRITE_COMPLETED_AT_MS=%lld", self.generated)
        poll_site = self.attached_region.index("r29_sigusr2_poll_cb(gpointer data)")
        stop_call_site = self.attached_region.index("r29_media_only_teardown(\"SIGUSR2\")", poll_site)
        stop_tx_site = self.attached_region.index("r29c_queue_registered_mediareq26(R29C_MEDIAREQ26_STOP)")
        self.assertGreater(stop_call_site, poll_site)
        self.assertGreater(stop_tx_site, 0)
        for scalar in (
            "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
            "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
            "SELF_ACTIVATION_001A_SENT_COUNT=%u",
            "R27_REPEAT_001A_SENT_COUNT=%u",
            "REFRESH_LOOP_STARTED_COUNT=%u",
            "NEW_ICE_COUNT=%u",
            "NEW_CLOUD_NEGOTIATION_COUNT=%u",
            "NEW_PSEUDOTCP_COUNT=%u",
            "NEW_REGISTRATION_COUNT=%u",
        ):
            self.assertIn(scalar, self.attached_region)

    def test_candidate_exit_is_closed_enum_and_code_is_reconciled(self) -> None:
        self.assertIn("int r29c_exit_code = failed ? 6 : 0;", self.main_region)
        self.assertIn("r29c_print_candidate_exit(r29c_exit_code);", self.main_region)
        for reason in (
            '"MAIN_LOOP_RETURNED"',
            '"MAIN_LOOP_FAILED"',
            '"STOP_SENT_MAIN_LOOP_RETURNED"',
            '"OPEN_SENT_MAIN_LOOP_RETURNED_BEFORE_STOP"',
        ):
            self.assertIn(reason, self.attached_region)

    def test_runner_forbids_live_and_only_dry_runs_restore(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("LIVE_RUN=NOT_RUN", text)
        self.assertIn("R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN", text)
        self.assertIn("R29C_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN", text)
        self.assertIn("R29C_BUILDER=PASS", text)
        self.assertIn("R29C_PROBE_READY=true", text)
        self.assertIn("PRODUCTION_LISTENER_STOP_REQUESTED=false", text)
        self.assertIn("PRODUCTION_LISTENER_RESTORE_REQUESTED=false", text)
        self.assertNotIn("R29C_LIVE_AUTHORIZED=" + "true", text)

    def test_runner_utility_functions(self) -> None:
        out = self.shell(
            f"R29C_UNIT_TEST=1 bash -c 'source {RUNNER}; "
            "BUILD_PROVENANCE_LOG=/tmp/r29c-missing-build.log; "
            "build_marker GENERATED_SOURCE_SHA256 fallback'"
        )
        self.assertEqual(out.strip(), "fallback")

    def test_runner_materialisation_path_matches_builder_contract(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for path in (BUILDER, TRANSFORM, RUNNER):
            self.assertTrue(path.exists(), path)
        for marker in (
            'P80_BUILD_TRANSFORM="$TRANSFORM_REL"',
            "P80_BUILD_INCLUDE_P116=1",
            'P80_BUILD_EXPECTED_SOURCE_SHA="$R29C_EXPECTED_GENERATED_SOURCE_SHA"',
            'OUTPUT="$CANDIDATE_OUTPUT"',
            'git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$TRANSFORM_REL"',
            'git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL"',
            'cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL"',
            'cmp "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL"',
            'chroot "$rootfs" "/r29c-selfcheck/$CANDIDATE_NAME" --r29-selfcheck',
        ):
            self.assertIn(marker, text)

    def test_transform_accepts_builder_p116_generator_flags(self) -> None:
        flags = builder_p116_flags()
        self.assertEqual(flags, {"--include-p116", "--no-include-p116"})
        self.assertEqual(transform_cli_flags(), flags)

        with tempfile.TemporaryDirectory() as td:
            for flag in sorted(flags):
                output = Path(td) / f"{flag.removeprefix('--').replace('-', '_')}.c"
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(TRANSFORM),
                        "--source",
                        str(SOURCE),
                        "--output",
                        str(output),
                        flag,
                    ],
                    cwd=REPO,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertGreater(output.stat().st_size, 0)

    def test_transform_imports_are_standard_or_r29(self) -> None:
        tree = ast.parse(TRANSFORM.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                imports.add((node.module or "").split(".")[0])
        self.assertLessEqual(imports, {"argparse", "pathlib", "entrance_p116_r29_listener_attached_media_live_transform"})

    def test_parse_gates(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
