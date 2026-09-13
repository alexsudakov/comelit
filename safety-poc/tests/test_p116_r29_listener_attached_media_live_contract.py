from __future__ import annotations

import ast
import json
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
TRANSFORM = MEDIA / "entrance_p116_r29_listener_attached_media_live_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29_listener_attached_media_live.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29_listener_attached_media_live_transform as r29


def region(text: str, start: str, end: str) -> str:
    s = text.index(start)
    e = text.index(end, s)
    return text[s:e]


class P116R29ListenerAttachedMediaLiveContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_source = SOURCE.read_text(encoding="utf-8")
        cls.generated = r29.transform(cls.base_source)
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
        cls.call_init_region = region(
            cls.generated,
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            "Persistent listener:",
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
        cls.teardown_region = region(
            cls.generated,
            "static gboolean\nr29_media_only_teardown",
            "static void\nr29_sigusr2_handler",
        )
        cls.control_region = region(
            cls.generated,
            "static void\nr29_sigusr2_handler",
            "static int\nr29_selfcheck",
        )
        cls.ready_region = region(
            cls.generated,
            "r29_ctpp_registration_count++;",
            "V4_RING_LISTENER_READY=true",
        )
        cls.pseudotcp_region = region(
            cls.generated,
            "pseudotcp_open = TRUE;",
            "Do not terminate on PseudoTCP OPEN.",
        )
        cls.remote_sdp_region = region(
            cls.generated,
            "remote_sdp_check_cb(gpointer data)",
            "candidate_gathering_done_cb",
        )
        cls.ice_region = region(
            cls.generated,
            "ICE_GATHER_START=FAIL",
            "ICE_GATHER_START=PASS",
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

    def test_01_candidate_derived_from_actual_builder_lineage(self) -> None:
        self.assertIn("V4_RING_DIRECTION=DEVICE_TO_CLIENT", self.generated)
        self.assertIn("V4_RING_KIND=CALL_INIT", self.generated)
        self.assertIn('P80_RUN_DIR=/run/comelit-media', self.generated)

    def test_02_no_self_activation_path_reachable(self) -> None:
        self.assertIn("R29_SELF_ACTIVATION_DISABLED=true", self.self_activation_region)
        self.assertNotIn("p12_queue_vip_frame", self.self_activation_region)
        self.assertNotIn("P12_TX_ENTRANCE_SELF_ACTIVATION", self.self_activation_region)

    def test_03_no_r27_repeat_path_reachable(self) -> None:
        self.assertIn("R27_REPEAT_001A_SENT_COUNT=%u", self.attached_region)
        self.assertIn("R27_REPEAT_SENT_COUNT=%u", self.attached_region)

    def test_04_no_door_action_reachable(self) -> None:
        self.assertNotIn("v4_door_signal_handler", self.attached_region)
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", self.attached_region)
        self.assertIn("DOOR_ACTIONS_SENT=%u", self.attached_region)

    def test_05_no_gate_action_reachable(self) -> None:
        self.assertIn("R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true", self.attached_region)
        self.assertIn("GATE_ACTIONS_SENT=%u", self.attached_region)

    def test_06_call_init_required_before_attached_media(self) -> None:
        self.assertIn("r29_start_attached_media_from_call_init(source)", self.call_init_region)
        self.assertIn("CALL_TRANSACTION_CREATED=true", self.attached_region)

    def test_07_unknown_or_gate_source_rejected(self) -> None:
        self.assertIn("strcmp(source, V4_ENTRANCE) != 0", self.attached_region)
        self.assertIn("R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true", self.attached_region)

    def test_08_attached_media_does_not_create_ice(self) -> None:
        self.assertNotIn("nice_agent_new", self.attached_region)
        self.assertIn("NEW_ICE_BOOTSTRAP_AFTER_READY=%u", self.attached_region)

    def test_09_attached_media_does_not_invoke_cloud_negotiation(self) -> None:
        self.assertNotIn("CLOUD_NEGOTIATION=START", self.attached_region)
        self.assertIn("NEW_CLOUD_NEGOTIATION_AFTER_READY=%u", self.attached_region)

    def test_10_attached_media_does_not_open_new_pseudotcp(self) -> None:
        self.assertNotIn("pseudo_tcp_socket_new", self.attached_region)
        self.assertIn("NEW_PSEUDOTCP_AFTER_READY=%u", self.attached_region)

    def test_11_attached_media_does_not_register_new_ctpp(self) -> None:
        self.assertNotIn("V4_CTPP_REGISTRATION_INIT_SENT", self.attached_region)
        self.assertIn("NEW_REGISTRATION_AFTER_READY=%u", self.attached_region)

    def test_12_call_transaction_distinct_from_registration(self) -> None:
        self.assertIn("r29_call_transaction_active", self.state_region)
        self.assertIn("r29_listener_registered_ready", self.state_region)
        self.assertIn("CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=%s", self.attached_region)

    def test_13_rtpc_media_channels_only_after_inbound_event(self) -> None:
        self.assertIn("R29_MEDIA_OPEN_MODEL=BLOCKED", self.attached_region)
        self.assertIn("RTPC_MEDIA_CHANNELS_OPEN=%u", self.attached_region)
        self.assertNotIn("r29_rtpc_media_channels_open = 1u", self.attached_region)
        self.assertIn("DEVICE_TO_CLIENT", self.call_init_region)

    def test_14_media_teardown_does_not_stop_process(self) -> None:
        self.assertNotIn("exit(", self.teardown_region)
        self.assertNotIn("g_main_loop_quit", self.teardown_region)
        self.assertNotIn("kill(", self.teardown_region)

    def test_15_media_teardown_does_not_touch_global_stop_file(self) -> None:
        self.assertNotIn("STOP_FILE", self.teardown_region)
        self.assertNotIn("/stop", self.teardown_region)

    def test_16_media_teardown_does_not_close_persistent_pseudotcp(self) -> None:
        self.assertNotIn("pseudo_tcp_socket_close", self.teardown_region)
        self.assertNotIn("pseudotcp_begin_graceful_stop", self.teardown_region)

    def test_17_media_teardown_does_not_close_registration(self) -> None:
        self.assertNotIn("v4_registered = FALSE", self.teardown_region)
        self.assertIn("MEDIA_TEARDOWN_PRESERVES_REGISTRATION=%s", self.attached_region)

    def test_18_media_teardown_one_shot(self) -> None:
        self.assertIn("r29_media_stop_completed", self.teardown_region)
        self.assertIn("R29_MEDIA_STOP_SECOND_INVOCATION_REFUSED=true", self.teardown_region)

    def test_19_second_media_start_blocked(self) -> None:
        self.assertIn("r29_second_media_start_blocked = TRUE", self.attached_region)
        self.assertIn("R29_SECOND_MEDIA_START_BLOCKED=true", self.attached_region)

    def test_20_second_call_init_during_active_media_blocked(self) -> None:
        self.assertIn("r29_call_transaction_active", self.attached_region)
        self.assertIn("R29_SECOND_CALL_INIT_DURING_ACTIVE_MEDIA_BLOCKED=true", self.attached_region)

    def test_21_malformed_media_signaling_no_network_guess(self) -> None:
        self.assertIn("R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true", self.attached_region)
        self.assertNotIn("sendto(", self.attached_region)
        self.assertNotIn("connect(", self.attached_region)

    def test_22_cleanup_idempotent(self) -> None:
        self.assertIn("stop_candidate_if_needed", RUNNER.read_text(encoding="utf-8"))
        out = self.shell(f"R29_UNIT_TEST=1 bash -c 'source {RUNNER}; stop_pid \"\"; echo cleanup-ok'")
        self.assertIn("cleanup-ok", out)

    def test_23_outer_timeout_restores_production_path(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("trap on_exit EXIT", text)
        self.assertIn("restore_listener || rc=91", text)
        self.assertIn("R29_OUTER_TIMEOUT_SECONDS", text)

    def test_24_candidate_wrapper_executes_candidate_binary(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("run_candidate_selfcheck_in_chroot", text)
        self.assertIn('chroot "$rootfs" "/r29-selfcheck/$CANDIDATE_NAME" --r29-selfcheck', text)
        self.assertIn("R29_SELFCHECK_ROOTFS_SELECTION=P80_OFFLINE_ROOTFS_OR_NEWEST_CACHED_CHROOT_PATTERN", text)
        self.assertIn("P80_OFFLINE_ROOTFS", text)
        self.assertNotIn('"$CANDIDATE_OUTPUT" --r29-selfcheck', text)
        self.assertIn("CANDIDATE_HELPER_EXECUTED=true", self.attached_region)
        self.assertIn("R29_LIVE_PREFLIGHT_REFUSED=BLOCKED_MEDIA_MODEL", text)

    def test_25_helper_substitution_independently_verified(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("R29_WRAPPER_SUBSTITUTION_BASE_ABSENT=PASS", text)
        self.assertIn("R29_WRAPPER_SUBSTITUTION_CANDIDATE_PRESENT=PASS", text)
        self.assertIn('bash -n "$CANDIDATE_WRAPPER"', text)

    def test_26_build_provenance_logged_separately(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("BUILD_PROVENANCE_LOG", text)
        self.assertIn('tee "$BUILD_PROVENANCE_LOG"', text)
        self.assertIn("build_marker", text)

    def test_27_no_raw_secrets_addresses_or_ids_in_r29_output_regions(self) -> None:
        scalar_regions = "\n".join((self.attached_region, self.control_region))
        self.assertNotRegex(scalar_regions, r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        self.assertNotIn("SSRC=", scalar_regions)
        self.assertNotIn("SESSION_ID", scalar_regions)
        self.assertNotIn("TOKEN", scalar_regions)
        self.assertNotIn("SDP", scalar_regions)

    def test_transform_imports_are_standard_or_existing_local(self) -> None:
        tree = ast.parse(TRANSFORM.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                imports.add((node.module or "").split(".")[0])
        self.assertLessEqual(
            imports,
            {"argparse", "pathlib", "re", "entrance_p106_teardown_state_classification_transform"},
        )

    def test_transform_refuses_unknown_lineage(self) -> None:
        with self.assertRaises(RuntimeError):
            r29.transform("int main(void) { return 0; }\n")

    def test_transform_forbidden_gate_rejects_bad_generated_region(self) -> None:
        bad = self.generated.replace(
            "printf(\"R29_CLIENT_001A_DISABLED=true\\n\");",
            "p12_queue_vip_frame(0, 0, 0, P78_TX_RTPC_CLIENT_001A);",
            1,
        )
        with self.assertRaises(RuntimeError):
            r29._assert_generated_gates(bad)  # pylint: disable=protected-access

    def test_static_identifier_gate_rejects_bad_r29_identifier(self) -> None:
        bad = self.generated.replace(
            "r29_media_open_blocked = TRUE;",
            "r29_media_open_blocked = TRUE;\n    r29_synthetic_missing_identifier = TRUE;",
            1,
        )
        with self.assertRaisesRegex(RuntimeError, "R29_IDENTIFIER_GATE=FAIL.*r29_synthetic_missing_identifier"):
            r29._assert_r29_identifiers_resolved(bad)  # pylint: disable=protected-access

    def test_static_identifier_order_gate_rejects_late_base_definition(self) -> None:
        define = '#define V4_ENTRANCE     "00000643"\n'
        without_define = self.generated.replace(define, "", 1)
        bad = without_define + define
        with self.assertRaisesRegex(
            RuntimeError,
            r"R29_IDENTIFIER_ORDER_GATE=FAIL.*V4_ENTRANCE.*definition_pos=.*first_use_pos=",
        ):
            r29._assert_r29_identifiers_resolved(bad)  # pylint: disable=protected-access

    def test_static_identifier_order_gate_accepts_base_definition_before_use(self) -> None:
        r29._assert_r29_identifiers_resolved(self.generated)  # pylint: disable=protected-access

    def test_runner_selfcheck_fail_closed_before_handoff(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        selfcheck_pos = text.index("run_candidate_selfcheck_in_chroot || fail")
        blocked_pos = text.index("R29_LIVE_PREFLIGHT_REFUSED=BLOCKED_MEDIA_MODEL", selfcheck_pos)
        status_pos = text.index('STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"')
        stop_pos = text.index('post_control stop "$STOP_RESPONSE"')
        self.assertLess(selfcheck_pos, blocked_pos)
        self.assertLess(blocked_pos, status_pos)
        self.assertLess(status_pos, stop_pos)

    def test_runner_success_gate_function(self) -> None:
        out = self.shell(
            f"R29_UNIT_TEST=1 bash -c 'source {RUNNER}; "
            "evaluate_success_gate 2 true true true true 0 0 0 0; "
            "evaluate_success_gate 0 true true true true 0 0 0 0'"
        )
        self.assertEqual(out.strip().splitlines(), ["SUCCESS_GATE=true", "SUCCESS_GATE=false"])

    def test_runner_delta_function(self) -> None:
        out = self.shell(
            f"R29_UNIT_TEST=1 bash -c 'source {RUNNER}; "
            "compute_delta 4 9; compute_delta unknown 9'"
        )
        self.assertEqual(out.strip().splitlines(), ["5", "UNKNOWN"])

    def test_acceptance_metrics_are_not_literal_constants(self) -> None:
        metrics = (
            "LISTENER_PROCESS_SAME_AFTER_CALL",
            "LISTENER_PROCESS_SAME_AFTER_MEDIA",
            "ICE_BOOTSTRAP_DELTA_AFTER_READY",
            "CLOUD_NEGOTIATION_DELTA_AFTER_READY",
            "PSEUDOTCP_OPEN_DELTA_AFTER_READY",
            "CTPP_REGISTRATION_DELTA_AFTER_READY",
            "MEDIA_TEARDOWN_PRESERVES_TRANSPORT",
            "MEDIA_TEARDOWN_PRESERVES_REGISTRATION",
            "MEDIA_TEARDOWN_PRESERVES_RING_LISTENER",
            "VIDEO_RTP_OBSERVATION_SECONDS",
            "VIDEO_RTP_FIRST_AFTER_CALL_MS",
            "VIDEO_RTP_PACKETS",
            "ATTACHED_MEDIA_STARTED",
            "RTPC_MEDIA_CHANNELS_OPEN",
            "CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION",
        )
        literal = re.compile(
            r'printf\("(?:' + "|".join(map(re.escape, metrics)) + r')=(?:true|false|0)\\n"'
        )
        self.assertIsNone(literal.search(self.generated))
        for metric in metrics:
            if metric.endswith("_DELTA_AFTER_READY"):
                self.assertNotIn(metric, self.generated)
            else:
                self.assertRegex(self.generated, rf'printf\("{re.escape(metric)}=%[sullu]')

    def test_transport_counter_increments_exist_once_in_real_regions(self) -> None:
        self.assertEqual(self.generated.count("r29_ice_bootstrap_count++;"), 1)
        self.assertEqual(self.generated.count("r29_cloud_negotiation_count++;"), 1)
        self.assertEqual(self.generated.count("r29_pseudotcp_open_count++;"), 1)
        self.assertEqual(self.generated.count("r29_ctpp_registration_count++;"), 1)
        self.assertIn("r29_ice_bootstrap_count++;", self.ice_region)
        self.assertIn("r29_cloud_negotiation_count++;", self.remote_sdp_region)
        self.assertIn("r29_pseudotcp_open_count++;", self.pseudotcp_region)
        self.assertIn("r29_ctpp_registration_count++;", self.ready_region)

    def test_forbidden_emitters_are_neutralised_by_call_site_count(self) -> None:
        self.assertEqual(self.generated.count("entrance_signal_queue_self_activation(void)"), 1)
        self.assertEqual(self.generated.count("p78_queue_rtpc_client_001a(void)"), 2)
        self.assertEqual(self.generated.count("p78_queue_rtpc_client_001a();"), 0)
        self.assertNotIn("p12_queue_vip_frame", self.self_activation_region)
        self.assertNotIn("p12_queue_vip_frame", self.client_001a_region)

    def test_runner_restore_predicate_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "supervisor_running": True,
                        "running": True,
                        "listener_ready": True,
                        "last_error": None,
                    }
                ),
                encoding="utf-8",
            )
            out = self.shell(
                f"R29_UNIT_TEST=1 bash -c 'source {RUNNER}; restore_predicate {path}'"
            )
            self.assertIn("RESTORE_PREDICATE=true", out)

    def test_bash_and_python_parse(self) -> None:
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
