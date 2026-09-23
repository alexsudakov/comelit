#!/usr/bin/env python3
"""P116/R60 Track A post-call PseudoTCP fast-recovery forensic tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

from research.media.v1 import entrance_p116_r60_post_call_fast_recovery_model as model


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA_V1 = ROOT / "research" / "media" / "v1"
if str(MEDIA_V1) not in sys.path:
    sys.path.insert(0, str(MEDIA_V1))

from research.media.v1 import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58

DOC = ROOT / "research" / "media" / "v1" / "P116_R60_POST_CALL_FAST_RECOVERY.md"
FIXTURE = ROOT / "research" / "media" / "v1" / "P116_R59_R58_CANARY_TIMELINE_EVIDENCE.txt"
LIBNICE_EVIDENCE = ROOT / "research" / "media" / "v1" / "P116_R60_LIBNICE_0_1_22_EVIDENCE.txt"
NATIVE_BINARY = REPO / "custom_components" / "comelit" / "native" / "comelit-v4"
R63_BUILD_INFO = MEDIA_V1 / "P116_R63_BUILD_INFO.txt"
R64_BUILD_INFO = MEDIA_V1 / "P116_R64_BUILD_INFO.txt"


class R60A2WindowDecompositionTests(unittest.TestCase):
    def test_fixture_decomposition_reconciles_to_51209_ms(self) -> None:
        parts = model.decompose_post_call_window()
        self.assertEqual(parts.post_call_exit_latency_ms, 6)
        self.assertEqual(parts.first_reconnect_start_delay_ms, 5618)
        self.assertEqual(parts.first_reconnect_lifetime_ms, 34875)
        self.assertEqual(parts.between_reconnect_backoff_ms, 5155)
        self.assertEqual(parts.second_reconnect_to_ready_ms, 5555)
        self.assertEqual(parts.post_call_unavailable_ms, 51209)
        self.assertEqual(parts.sum_ms, parts.post_call_unavailable_ms)

    def test_document_carries_a2_sentinel_values(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for needle in (
            "POST_CALL_EXIT_LATENCY_MS=6",
            "FIRST_RECONNECT_START_DELAY_MS=5618",
            "FIRST_RECONNECT_LIFETIME_MS=34875",
            "BETWEEN_RECONNECT_BACKOFF_MS=5155",
            "SECOND_RECONNECT_TO_READY_MS=5555",
            "SUM_RECONCILIATION=6+5618+34875+5155+5555=51209",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, doc)


class R60A3A5PseudoTcpForensicTests(unittest.TestCase):
    def test_startup_order_proves_pseudotcp_after_ice_ready_selected_pair(self) -> None:
        source = (
            ROOT
            / "research"
            / "ring"
            / "v4_3"
            / "comelit_ice_offer_holder.v4-persistent.c"
        ).read_text(encoding="utf-8")
        start_func_idx = source.index("start_pseudotcp(void)")
        connect_idx = source.index("pseudo_tcp_socket_connect", start_func_idx)
        ready_idx = source.index("NICE_COMPONENT_STATE_READY")
        selected_idx = source.index("if (!report_selected_pair())", ready_idx)
        start_idx = source.index("if (!start_pseudotcp())", selected_idx)
        self.assertLess(start_func_idx, connect_idx)
        self.assertLess(ready_idx, selected_idx)
        self.assertLess(selected_idx, start_idx)

    def test_libnice_timer_matches_first_reconnect_lifetime_model(self) -> None:
        limit, rto_ms = model.libnice_preopen_retransmit_limit()
        self.assertEqual(limit, 30)
        self.assertEqual(rto_ms, 1000)
        parts = model.decompose_post_call_window()
        residual_startup_ms = parts.first_reconnect_lifetime_ms - (limit * rto_ms)
        self.assertGreaterEqual(residual_startup_ms, 4500)
        self.assertLessEqual(residual_startup_ms, 5500)

    def test_notify_packet_false_reasons_are_enumerated_from_upstream_source(self) -> None:
        reasons = set(model.notify_packet_false_reasons())
        self.assertEqual(
            reasons,
            {
                "LEN_GT_MAX_PACKET",
                "LEN_LT_HEADER_SIZE",
                "PARSE_HEADER_SIZE_NOT_24",
                "WRONG_CONVERSATION",
                "CLOSED_OR_FIN_ACK_WITH_DATA",
                "RST_FLAG",
                "CTL_LEN_ZERO",
                "UNKNOWN_CTL_CODE",
                "INVALID_RTT",
                "RECOVERY_RETRANSMIT_FAILURE",
                "FIN_WITH_DATA",
                "INVALID_FIN_STATE",
            },
        )

    def test_shipped_libnice_source_label_and_static_inspection_decision(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("EXTERNAL_UPSTREAM_SOURCE", doc)
        self.assertIn("SHIPPED_LIBNICE_SOURCE_SUFFICIENT=true", doc)
        self.assertIn("NEEDS_SHIPPED_SO_STATIC_INSPECTION=false", doc)
        fixture = LIBNICE_EVIDENCE.read_text(encoding="utf-8")
        self.assertIn(
            "upstream_file_sha256=d0eb851f16bf546096f8edcc9fce3b3d32cdb4f035d3d35662d615dd28920dee",
            fixture,
        )
        self.assertIn("upstream_file_bytes=80443", fixture)
        r58_binary_sha = model.production_binary_sha_from_r58_provenance()
        self.assertEqual(
            r58_binary_sha,
            "40c8a2c19fe5e792c28082ee0b1f60732cd90b5ffaa1cdb05c82575361cef762",
        )

        # R60's libnice decision is provenance for the R58 binary lineage,
        # not a permanent pin that forbids later validated native promotions.
        # When a later build is shipped, its own repository build metadata
        # becomes the current binary identity gate.
        current_build_info = (
            R64_BUILD_INFO
            if R64_BUILD_INFO.is_file()
            else R63_BUILD_INFO
            if R63_BUILD_INFO.is_file()
            else None
        )
        if current_build_info is not None:
            values = dict(
                line.split("=", 1)
                for line in current_build_info.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
            expected_current_sha = values["native_binary_sha256"]
        else:
            expected_current_sha = r58_binary_sha

        self.assertEqual(
            hashlib.sha256(NATIVE_BINARY.read_bytes()).hexdigest(),
            expected_current_sha,
        )

    def test_evidence_paths_are_ci_faithful_repo_local(self) -> None:
        self.assertTrue(model.evidence_paths_are_repo_local())
        for path in model.MODEL_EVIDENCE_PATHS:
            with self.subTest(path=path):
                resolved = path.resolve()
                self.assertTrue(resolved.is_relative_to(REPO.resolve()))
                self.assertNotIn("/.r60-evidence/", str(resolved))
                self.assertNotIn("/.r", str(resolved.relative_to(REPO.resolve())))


class R60A4A6CorrectiveVerdictTests(unittest.TestCase):
    def test_media_stop_path_has_no_pseudotcp_transport_teardown_call(self) -> None:
        generated = r58.transform(
            (
                ROOT
                / "research"
                / "door"
                / "v1_5_7"
                / "comelit-v4-persistent-ctpp-door.c"
            ).read_text(encoding="utf-8")
        )
        media_count, all_calls = model.pseudotcp_teardown_calls_on_media_stop(generated)
        self.assertEqual(media_count, 0)
        self.assertEqual(all_calls, ["pseudo_tcp_socket_close(pseudo_tcp, FALSE);"])

    def test_saved_evidence_does_not_prove_remote_release_or_call_teardown(self) -> None:
        fixture = FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn("R37_REMOTE_RELEASE_OBSERVED=true", fixture)
        self.assertNotIn("R37_CAPABILITY_CLEARED_OBSERVED=true", fixture)
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("REMOTE_RELEASE_OBSERVED=UNKNOWN", doc)
        self.assertIn("LOCAL_CALL_TEARDOWN_COMPLETE=UNKNOWN", doc)
        self.assertIn("CALL_TRANSACTION_ACTIVE_AT_EXIT=UNKNOWN", doc)
        self.assertIn("RECONNECT_TOO_EARLY_HYPOTHESIS=SUPPORTED", doc)
        self.assertIn("SERVER_SIDE_SESSION_RELEASE_DELAY_EVIDENCE=SUPPORTED", doc)

    def test_corrective_is_observability_only(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("RECOVERY_CORRECTIVE_CLASS=NO_FUNCTIONAL_CORRECTIVE", doc)
        self.assertIn("RECOVERY_CORRECTIVE_IMPLEMENTED=false", doc)
        self.assertIn("TRACK_A_DOOR_SEMANTICS_CHANGED=false", doc)
        self.assertNotIn("NETWORK_DOOR_ACTION_PERFORMED=true", doc)


class R60A7LifecycleHarnessTests(unittest.TestCase):
    def test_legacy_aggregate_gates_still_pass_from_reparsed_events(self) -> None:
        result = model.derive_lifecycle_gates(model.canonical_lifecycle_events())
        self.assertEqual(
            result.as_markers(),
            {
                "RECONNECT_LOOP_BOUNDED": "PASS",
                "NO_PARALLEL_LISTENERS": "PASS",
                "READY_AFTER_FULL_REGISTRATION": "PASS",
            },
        )

    def test_case_a_old_call_failure_reconnect_ready_and_flip(self) -> None:
        self.assertEqual(model.case_a_old_call_failure_reconnect_ready().result, "PASS")
        corrupt = [
            {"t": 0, "type": "call_closed"},
            {"t": 1, "type": "ready", "attempt": 1},
            {"t": 2, "type": "transport_failure"},
        ]
        self.assertEqual(model.case_a_old_call_failure_reconnect_ready(corrupt).result, "FAIL")

    def test_case_b_stale_reconnect_gap_visible_and_flip(self) -> None:
        self.assertEqual(model.case_b_stale_first_reconnect_visible_gap().result, "PASS")
        self.assertEqual(
            model.case_b_stale_first_reconnect_visible_gap(visible_dead_wait_ms=0).result,
            "FAIL",
        )
        self.assertEqual(
            model.case_b_stale_first_reconnect_visible_gap(functional_corrective_applied=True).result,
            "FAIL",
        )

    def test_case_c_unrelated_transport_failure_fails_closed_and_flip(self) -> None:
        self.assertEqual(model.case_c_unrelated_transport_failure_fails_closed().result, "PASS")
        self.assertEqual(
            model.case_c_unrelated_transport_failure_fails_closed(
                ["listener_ready", "transport_failure", "graceful_recycle"]
            ).result,
            "FAIL",
        )

    def test_case_d_repeated_failures_bounded_backoff_and_flip(self) -> None:
        self.assertEqual(model.case_d_repeated_failures_bounded_backoff().result, "PASS")
        self.assertEqual(
            model.case_d_repeated_failures_bounded_backoff(attempts=9).result,
            "FAIL",
        )
        self.assertEqual(
            model.case_d_repeated_failures_bounded_backoff(delays_ms=[5000, 1]).result,
            "FAIL",
        )

    def test_case_e_no_parallel_listeners_and_flip(self) -> None:
        self.assertEqual(model.case_e_no_parallel_listeners().result, "PASS")
        self.assertEqual(
            model.case_e_no_parallel_listeners(
                [{"t": 0, "type": "start"}, {"t": 1, "type": "start"}]
            ).result,
            "FAIL",
        )

    def test_case_f_ready_after_registration_and_flip(self) -> None:
        self.assertEqual(model.case_f_ready_after_complete_registration().result, "PASS")
        self.assertEqual(
            model.case_f_ready_after_complete_registration(
                [
                    {"t": 0, "type": "start", "attempt": 1},
                    {"t": 1, "type": "ready", "attempt": 1},
                ]
            ).result,
            "FAIL",
        )

    def test_case_g_door_action_ready_guard_and_flip(self) -> None:
        self.assertEqual(model.case_g_door_action_gated_by_listener_ready().result, "PASS")
        source = 'os.kill(process.pid, signal.SIGUSR1)\nif not await self.async_wait_ready(timeout=30):\n'
        self.assertEqual(model.case_g_door_action_gated_by_listener_ready(source).result, "FAIL")

    def test_case_aggregate_is_derived_from_case_results(self) -> None:
        results = model.run_lifecycle_contract_cases()
        self.assertEqual(model.lifecycle_harness_aggregate(results), "PASS")
        corrupt = dict(results)
        corrupt["CASE_A"] = model.CaseResult("CASE_A", "FAIL", {})
        self.assertEqual(model.lifecycle_harness_aggregate(corrupt), "FAIL")

    def test_harness_markers_are_not_literal_constants(self) -> None:
        source = model.__loader__.get_source(model.__name__)  # type: ignore[union-attr]
        self.assertNotIn('"CASE_A_RESULT=PASS"', source)
        self.assertNotIn('"HARNESS_AGGREGATE=PASS"', source)
        results = model.run_lifecycle_contract_cases()
        good = model.render_lifecycle_markers(results)
        corrupt = dict(results)
        corrupt["CASE_B"] = model.CaseResult("CASE_B", "FAIL", {})
        bad = model.render_lifecycle_markers(corrupt)
        self.assertEqual(good["CASE_B_RESULT"], "PASS")
        self.assertEqual(bad["CASE_B_RESULT"], "FAIL")
        self.assertEqual(bad["HARNESS_AGGREGATE"], "FAIL")

    def test_flip_reconnect_loop_bounded_to_fail(self) -> None:
        events = model.canonical_lifecycle_events()
        events.extend(
            [
                {"t": 72, "type": "start", "attempt": 4},
                {"t": 73, "type": "failure", "attempt": 4},
                {"t": 74, "type": "start", "attempt": 5},
            ]
        )
        self.assertEqual(
            model.derive_lifecycle_gates(events).reconnect_loop_bounded,
            "FAIL",
        )

    def test_flip_no_parallel_listeners_to_fail(self) -> None:
        events = model.canonical_lifecycle_events()
        events.insert(1, {"t": 1, "type": "start", "attempt": 2})
        self.assertEqual(model.derive_lifecycle_gates(events).no_parallel_listeners, "FAIL")

    def test_flip_ready_after_registration_to_fail(self) -> None:
        events = model.canonical_lifecycle_events()
        events.insert(1, {"t": 2, "type": "ready", "attempt": 2})
        self.assertEqual(
            model.derive_lifecycle_gates(events).ready_after_full_registration,
            "FAIL",
        )

    def test_cli_outputs_derived_gate_markers(self) -> None:
        proc = subprocess.run(
            [
                "python3",
                str(ROOT / "research" / "media" / "v1" / "entrance_p116_r60_post_call_fast_recovery_model.py"),
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        output = proc.stdout
        for needle in (
            "CASE_A_RESULT=PASS",
            "CASE_B_RESULT=PASS",
            "CASE_C_RESULT=PASS",
            "CASE_D_RESULT=PASS",
            "CASE_E_RESULT=PASS",
            "CASE_F_RESULT=PASS",
            "CASE_G_RESULT=PASS",
            "HARNESS_AGGREGATE=PASS",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, output)


class R60A8A9DocumentContractTests(unittest.TestCase):
    def test_expected_unavailable_and_missing_evidence_are_honest_unknowns(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("EXPECTED_POST_CALL_UNAVAILABLE_MS=UNKNOWN", doc)
        self.assertIn("RECOVERY_ROOT_CAUSE=EARLY_RECONNECT_SUPPORTED_NOT_PROVEN", doc)
        self.assertIn("MISSING_REQUIRED_EVIDENCE=remote_RELEASE_marker_or_wire_capture", doc)

    def test_document_has_required_a_sections_and_no_door_protocol_content(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for section in ("A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"):
            with self.subTest(section=section):
                self.assertIn(f"## {section}", doc)
        forbidden = (
            "button.py",
            "switch.py",
            "camera.py",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
            "startAudioTX",
        )
        for needle in forbidden:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, doc)


if __name__ == "__main__":
    unittest.main()
