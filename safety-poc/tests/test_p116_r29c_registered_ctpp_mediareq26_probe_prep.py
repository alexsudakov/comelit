from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29c_registered_ctpp_mediareq26_probe.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


def region(text: str, start: str, end: str) -> str:
    s = text.index(start)
    e = text.index(end, s)
    return text[s:e]


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
            "static gboolean\nr29c_build_mediareq26",
            "static gboolean\nr29c_emit_registered_mediareq26",
        )
        cls.live_queue_region = region(
            cls.generated,
            "r29c_queue_registered_mediareq26",
            "static void\nr29_print_scalar_snapshot",
        )
        cls.selfcheck_region = region(
            cls.generated,
            "static int\nr29_selfcheck",
            "/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */",
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

    def test_builder_has_exact_r29a_layout_and_distinct_states(self) -> None:
        for needle in (
            "R29C_MEDIAREQ26_OPEN",
            "R29C_MEDIAREQ26_STOP",
            "write_le16(out + 0, 0x1100u);",
            "out[2] = 0x14u;",
            "out[2] = 0x94u;",
            "out[3] = 0x32u;",
            "out[3] = 0x00u;",
            "write_le32(out + 4, 0u);",
            "write_le16(out + 8, r29c_saved_media_channel_id);",
        ):
            self.assertIn(needle, self.builder_region)

    def test_open_stop_anchors_and_unsourced_runtime_fields_are_explicit(self) -> None:
        for needle in (
            "prefix_0x1100:SOURCED_SHAPE_CONSTANT:disasm2-csp_send_mediareq26_mov_w8_0x1100",
            "action_0x14:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w1_0x14",
            "action_0x94:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w1_0x94",
            "flags_0x32:SOURCED_SHAPE_CONSTANT:CallFsm_start_videorx_mov_w2_0x32",
            "flags_0x00:SOURCED_SHAPE_CONSTANT:CallFsm_stop_videorx_mov_w2_wzr",
            "address_zero_tunnel_channel_form:SOURCED_SHAPE_CONSTANT:start_videorx_x3_xzr_stop_zero_slot",
            "saved_media_channel_id:SOURCED_RUNTIME:r29c_allocator_result_persisted",
            "max_rtp_payload:UNSOURCED:no_helper_runtime_accessor_equivalent",
            "media_profile_0:UNSOURCED:no_helper_call_config_runtime_source",
            "media_profile_1:UNSOURCED:no_helper_call_config_runtime_source",
            "media_profile_2:UNSOURCED:no_helper_call_config_runtime_source",
            "media_profile_3_4_5_and_reserved:UNSOURCED:no_helper_call_config_runtime_source",
            "max_rtp_payload_zero:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots",
            "media_profile_zero_tail:SOURCED_SHAPE_CONSTANT:R29A_stop_zero_payload_profile_slots",
        ):
            self.assertIn(needle, self.attached_region)
        self.assertNotIn("flags = 0x02u;", self.generated)
        self.assertNotIn("r29c_runtime_max_rtp_payload = 1200", self.generated)
        self.assertNotIn("r29c_runtime_media_profile_1 = 800", self.generated)

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
            "r29c_build_mediareq26(R29C_MEDIAREQ26_OPEN, body)",
            "R29C_OPEN_BLOCKED_UNSOURCED_FIELDS=true",
            "r29c_build_mediareq26(R29C_MEDIAREQ26_STOP, body)",
            "R29C_STOP_BLOCKED_BY_OPEN_PROVENANCE=true",
            "r29_media_stop_completed = FALSE;",
            "r29c_note_final_research_session_cleanup();",
            "R29C_PROBE_READY=false",
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
            "OPEN_FIELDS_HAVE_PROVEN_SOURCES=%s",
            "STOP_FIELDS_HAVE_PROVEN_SOURCES=%s",
            "SELF_ACTIVATION_PATH_UNREACHABLE=true",
            "R27_REPEAT_PATH_UNREACHABLE=true",
            "MEDIA_ONLY_STOP_RESULT=%s",
            "FINAL_RESEARCH_SESSION_CLEANUP=%s",
            "R29C_BUILDER=%s",
            "LIVE_PROBE_PREPARED=%s",
        ):
            self.assertIn(marker, self.attached_region)

    def test_runner_forbids_live_and_only_dry_runs_restore(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("LIVE_RUN=NOT_RUN", text)
        self.assertIn("R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN", text)
        self.assertIn("R29C_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN", text)
        self.assertIn("R29C_BUILDER=BLOCKED", text)
        self.assertIn("R29C_PROBE_READY=false", text)
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
