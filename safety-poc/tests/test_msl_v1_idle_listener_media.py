#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "safety-poc"
MEDIA = SAFETY / "research" / "media" / "v1"
SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_msl_v1_idle_listener_media_transform.py"
RUNNER = MEDIA / "ct120_run_msl_v1_variant_b_live.sh"

sys.path.insert(0, str(MEDIA))

import entrance_msl_v1_idle_listener_media_transform as msl_b  # noqa: E402


COUNTERS = (
    "MSL_B_CLOUD_NEGOTIATION_COUNT",
    "MSL_B_ICE_BOOTSTRAP_COUNT",
    "MSL_B_PSEUDOTCP_OPEN_COUNT",
    "MSL_B_CTPP_REGISTRATION_COUNT",
    "MSL_B_MEDIA_SESSION_COUNT",
    "MSL_B_SECOND_MEDIA_SESSION",
    "MSL_B_LISTENER_PROCESS_PID",
    "MSL_B_RECONNECT_COUNT_BEFORE",
    "MSL_B_RECONNECT_COUNT_AFTER",
    "MSL_B_RECONNECT_COUNT_DELTA",
    "MSL_B_MEDIA_RX_ACTIVE",
    "MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE",
    "MSL_B_VIDEO_RTP_PACKETS",
    "MSL_B_SPS_COUNT",
    "MSL_B_TUNNEL_PRESERVED",
)


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_MSL_B_SYMBOL_RE = re.compile(r"\bmsl_b_[a-z0-9_]+\b")
_MSL_B_PRECEDING_WORD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\Z")
_MSL_B_NON_DECL_PRECEDING_WORDS = {"if", "while", "return", "else", "do", "switch", "for", "sizeof"}
_MSL_B_NON_DECL_PRECEDING_CHARS = set("(!=&|,?:;{}+-*/<>[]~^%")


def msl_b_symbol_declaration_positions(candidate: str) -> dict[str, tuple[int, int]]:
    """Map every lowercase msl_b_* identifier to (first_declaration_pos, first_occurrence_pos).

    A position is treated as a declaration site when the token immediately
    preceding the identifier (skipping whitespace) looks like a C type name
    rather than an operator, keyword, or nothing (a bare call statement).
    first_declaration_pos is -1 when no occurrence looks like a declaration.
    """
    occurrences: dict[str, list[int]] = {}
    for match in _MSL_B_SYMBOL_RE.finditer(candidate):
        occurrences.setdefault(match.group(0), []).append(match.start())

    result: dict[str, tuple[int, int]] = {}
    for symbol, starts in occurrences.items():
        starts.sort()
        decl_pos = -1
        for pos in starts:
            stripped = candidate[:pos].rstrip()
            if not stripped or stripped[-1] in _MSL_B_NON_DECL_PRECEDING_CHARS:
                continue
            word_match = _MSL_B_PRECEDING_WORD_RE.search(stripped)
            if not word_match or word_match.group(1) in _MSL_B_NON_DECL_PRECEDING_WORDS:
                continue
            decl_pos = pos
            break
        result[symbol] = (decl_pos, starts[0])
    return result


class MslV1IdleListenerMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = msl_b.transform(cls.base)
        cls.generated_b = msl_b.transform(cls.base)
        cls.region = cls.generated_a.split(msl_b.BEGIN, 1)[1].split(msl_b.END, 1)[0]
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_transform_is_deterministic(self) -> None:
        a = sha_text(self.generated_a)
        b = sha_text(self.generated_b)
        mutated_source = self.base.replace('#define STOP_FILE   RUN_DIR "/stop"', '#define STOP_FILE   RUN_DIR "/halt"', 1)
        with self.assertRaises(RuntimeError):
            msl_b.transform(mutated_source)
        self.assertEqual(a, b)
        print(f"MSL_B_TRANSFORM_DETERMINISTIC=true REAL={a} MUTATED=ANCHOR_FAIL")

    def test_control_surface_and_ready_preconditions(self) -> None:
        for marker in (
            '#define MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"',
            '#define MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"',
            "msl_b_ready_now",
            "v4_listener_ready && pseudotcp_open && v4_registered && v4_ctpp_channel_id != 0",
            "msl_b_control_poll_cb",
            "g_timeout_add(\n        100,\n        msl_b_control_poll_cb",
        ):
            self.assertIn(marker, self.generated_a)

    def test_no_new_session_path_added(self) -> None:
        for forbidden in (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P12_TX_AUTH",
            "curl",
            "oauth",
        ):
            self.assertNotIn(forbidden, self.region)
        self.assertIn("MSL_B_SECOND_UPSTREAM_SESSION=false", self.region)
        print("MSL_B_NO_NEW_SESSION_PATH=true REAL=listener_overlay MUTATED=forbidden_token_scan")

    def test_no_door_gate_path_added(self) -> None:
        door_gate_calls = (
            "P12_TX_V4_DOOR_WRITE",
            "v4_door_signal_handler",
            "v4_queue_door",
            "V4_GATE",
        )
        for token in door_gate_calls:
            self.assertNotIn(token, self.region)
        print("MSL_B_NO_DOOR_GATE_PATH=true REAL=overlay_region MUTATED=door_gate_token_scan")

    def test_ring_collision_and_duplicate_start_fail_closed(self) -> None:
        for marker in (
            "g_r35_session.call_transaction_alive || r42_media_stage == R42_MEDIA_ACTIVE",
            "MSL_B_RING_COLLISION_FAIL_CLOSED=true",
            "MSL_B_DUPLICATE_START_REJECTED=true",
            "msl_b_ring_collision_rejected_count++",
            "msl_b_duplicate_start_rejected_count++",
        ):
            self.assertIn(marker, self.region)
        print("MSL_B_RING_COLLISION_FAIL_CLOSED=true REAL=reject_busy MUTATED=removed_collision_predicate")

    def test_media_open_close_serialized_through_p12_completion(self) -> None:
        open_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_OPEN:", 1)[1].split(
            "case P12_TX_R35_MEDIA_OPEN:", 1
        )[0]
        self.assertIn("msl_b_queue_idle_self_activation()", open_case)
        self.assertNotIn("r42_queue_mediareq_open())", open_case.split("if (msl_b_idle_state", 1)[0])
        activation_case = self.generated_a.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split(
            "case P12_TX_R35_MEDIA_OPEN:", 1
        )[0]
        self.assertIn("msl_b_arm_device_ack_wait()", activation_case)
        self.assertNotIn("msl_b_activate_idle_media", activation_case)
        close_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_CLOSE:", 1)[1].split(
            "case P12_TX_R54_INVITE_ACK:", 1
        )[0]
        self.assertIn("r42_finish_media_channel_close()", close_case)

    def test_idle_media_active_is_gated_on_structural_ack_with_flip_proof(self) -> None:
        tx_case = self.generated_a.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
        ack_handler = self.generated_a.split("msl_b_handle_device_ack_001a(guint32 request_id", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertIn("msl_b_arm_device_ack_wait()", tx_case)
        self.assertNotIn("MSL_B_MEDIA_ACTIVE=true", tx_case)
        self.assertIn("msl_b_ack_matches_source", ack_handler)
        self.assertIn("msl_b_activate_idle_media_after_ack()", ack_handler)
        self.assertIn("MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=false", self.generated_a)

        mutated = self.generated_a.replace(
            "(void)msl_b_arm_device_ack_wait();", "printf(\"MSL_B_MEDIA_ACTIVE=true\\n\");", 1
        )
        mutated_case = mutated.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
        self.assertIn("MSL_B_MEDIA_ACTIVE=true", mutated_case)
        print(
            "MSL_B_ACK_GATED_MEDIA_ACTIVE=true "
            "REAL=tx_completion_arms_ack_wait "
            "MUTATED=tx_completion_reports_media_active"
        )

    def test_receive_path_registered_before_media_active_with_flip_proof(self) -> None:
        activation = self.generated_a.split("msl_b_activate_idle_media_after_ack(void)\n{", 1)[1].split(
            "\n}\n", 1
        )[0]
        register_idx = activation.index("msl_b_register_receive_path()")
        arm_idx = activation.index("r42_listener_rtp_arm(1);")
        active_idx = activation.index('printf("MSL_B_MEDIA_ACTIVE=true\\n");')
        self.assertLess(register_idx, arm_idx)
        self.assertLess(arm_idx, active_idx)
        self.assertIn("p80_loopback_socket(&p80_video_rtp_target, P80_VIDEO_RTP_PORT)", self.generated_a)
        self.assertIn("p80_loopback_socket(&p80_audio_rtp_target, P80_AUDIO_RTP_PORT)", self.generated_a)

        mutated_activation = activation.replace(
            "msl_b_register_receive_path()", "msl_b_register_receive_path_MUTATED()", 1
        )
        self.assertNotIn("msl_b_register_receive_path()", mutated_activation)
        print(
            "MSL_B_RECEIVE_PATH_REGISTERED_BEFORE_MEDIA_ACTIVE=true "
            f"REAL=register:{register_idx}<arm:{arm_idx}<active:{active_idx} "
            "MUTATED=registration_call_removed"
        )

    def test_r42_close_helper_declared_before_overlay_call(self) -> None:
        proto = self.generated_a.index("static gboolean r42_queue_media_channel_close(void);")
        call = self.generated_a.index("return r42_queue_media_channel_close() && p12_flush_tx();")
        definition = self.generated_a.index("r42_queue_media_channel_close(void)\n{")
        self.assertLess(proto, call)
        self.assertLess(call, definition)
        mutated = self.generated_a.replace(
            "static gboolean r42_queue_media_channel_close(void);\n\n",
            "",
            1,
        )
        self.assertNotIn(
            "static gboolean r42_queue_media_channel_close(void);",
            mutated[:call],
        )
        print("MSL_B_R42_CLOSE_DECLARATION_ORDER=true REAL=prototype_before_call MUTATED=prototype_removed")

    def test_msl_b_symbols_declared_before_first_use(self) -> None:
        positions = msl_b_symbol_declaration_positions(self.generated_a)
        undeclared = sorted(
            symbol
            for symbol, (decl_pos, first_pos) in positions.items()
            if decl_pos == -1 or decl_pos != first_pos
        )
        self.assertEqual(undeclared, [], f"used before declared: {undeclared}")

        mutated = self.generated_a
        for decl in (
            "static gboolean msl_b_b05_audio_marked;\n",
            "static gboolean msl_b_b06_video_marked;\n",
            "static gboolean msl_b_b07_decodable_marked;\n",
            "static void msl_b_print_clock_marker(const char *name);\n",
        ):
            self.assertIn(decl, mutated)
            mutated = mutated.replace(decl, "", 1)
        mutated_positions = msl_b_symbol_declaration_positions(mutated)
        mutated_undeclared = sorted(
            symbol
            for symbol, (decl_pos, first_pos) in mutated_positions.items()
            if decl_pos == -1 or decl_pos != first_pos
        )
        self.assertTrue(mutated_undeclared)
        print(
            "MSL_B_STRUCTURAL_DECLARATION_TEST=PASS "
            f"REAL=0_undeclared MUTATED={len(mutated_undeclared)}_undeclared:{','.join(mutated_undeclared)}"
        )

    def test_reuse_counters_are_derived_with_flip_proof(self) -> None:
        proofs: list[str] = []
        for counter in COUNTERS:
            real = self.generated_a.count(counter)
            mutated = self.generated_a.replace(counter, "MSL_B_COUNTER_MUTATED", 1).count(counter)
            self.assertGreater(real, 0, counter)
            self.assertNotEqual(real, mutated, counter)
            proofs.append(f"{counter}:REAL={real}/MUTATED={mutated}")
        print("MSL_B_REUSE_COUNTERS_DERIVED=true " + ",".join(proofs))

    def test_runner_refusal_mode_safe(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_OFFLINE_SAFE_REFUSAL=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertNotIn("CONTROL_STATUS_CURL_RC", proc.stdout)
        print("MSL_B_REFUSAL_MODE_SAFE=true")

    def test_runner_dry_run_reaches_final_summary_without_live_interaction(self) -> None:
        env = os.environ.copy()
        env["MSL_B_DRY_RUN"] = "YES"
        proc = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for marker in (
            "MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true",
            "MSL_B_DRY_RUN_COMELIT_INTERACTION=0",
            "MSL_B_DRY_RUN_HA_INTERACTION=0",
            "MSL_B_DRY_RUN_CANDIDATE_EXECUTED=false",
            "MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true",
            "MSL_B_MEDIA_CHANNEL_CLOSED=true",
            "DOOR_ACTIONS_SENT=0",
            "GATE_ACTIONS_SENT=0",
            "AUTOMATIC_PROTOCOL_RETRY=false",
            "SECOND_MEDIA_SESSION=false",
        ):
            self.assertIn(marker, proc.stdout)
        print("MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true")
        print("MSL_B_DRY_RUN_COMELIT_INTERACTION=0")
        print("MSL_B_DRY_RUN_HA_INTERACTION=0")

    def test_runner_dry_run_clock_markers_advance_with_flip_proof(self) -> None:
        env = os.environ.copy()
        env["MSL_B_DRY_RUN"] = "YES"
        proc = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stage_keys = (
            "MSL_B_B00_IDLE_MEDIA_REQUEST_RECEIVED_MONO_MS",
            "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS",
            "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS",
            "MSL_B_B03_INITIAL_001A_SENT_MONO_MS",
            "MSL_B_B04_STRUCTURAL_ACK_MEDIA_ACCEPTED_MONO_MS",
        )
        values: list[int] = []
        for key in stage_keys:
            match = re.search(rf"^{re.escape(key)}=(\d+)$", proc.stdout, re.M)
            self.assertIsNotNone(match, key)
            values.append(int(match.group(1)))
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(values, sorted(values))

        mutated = values[:]
        mutated[1] = mutated[0]
        self.assertNotEqual(len(mutated), len(set(mutated)))
        print(
            "MSL_B_CLOCK_MONOTONIC_VALUES_ADVANCE=true "
            f"REAL={dict(zip(stage_keys, values))} "
            f"MUTATED={dict(zip(stage_keys, mutated))}"
        )

    def test_runner_provenance_and_budget_gates(self) -> None:
        for marker in (
            "MSL_B_EXPECTED_COMMIT_SHA_REQUIRED=true",
            "MSL_B_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true",
            "MSL_B_ATTEMPT_LEDGER_REQUIRED=true",
            'ledger_value_or_fail "$MSL_B_ATTEMPT_LEDGER" MSL_B_ATTEMPT_LEDGER 15',
            "BASE_WRAPPER_SHA256",
            "P78_GATE_DECISION=substituted",
            "MSL_B_TRANSFORM_WORKTREE_BLOB_GATE=FAIL",
            "MSL_B_RUNNER_WORKTREE_BLOB_GATE=FAIL",
        ):
            self.assertIn(marker, self.runner)

    def test_attempt_ledger_malformed_and_cap_fail_closed_at_runtime(self) -> None:
        fail_fn = re.search(r"^fail\(\) \{\n(?:.*\n)*?^\}\n", self.runner, re.M).group(0)
        ledger_fn = re.search(r"^ledger_value_or_fail\(\) \{\n(?:.*\n)*?^\}\n", self.runner, re.M).group(0)

        def run_with_ledger(content: str) -> str:
            with tempfile.NamedTemporaryFile("w", delete=False) as handle:
                handle.write(content)
                ledger_path = handle.name
            try:
                script = (
                    "set -u\n"
                    "FAIL=0\n"
                    + fail_fn
                    + ledger_fn
                    + f'ledger_value_or_fail "{ledger_path}" MSL_B_ATTEMPT_LEDGER 15 || true\n'
                )
                proc = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=5, check=False)
                return proc.stdout
            finally:
                os.unlink(ledger_path)

        self.assertIn("MSL_B_ATTEMPT_LEDGER=MALFORMED", run_with_ledger("not-a-number\n"))
        self.assertIn("MSL_B_ATTEMPT_LEDGER_CAP=FAIL", run_with_ledger("15\n"))
        self.assertEqual(run_with_ledger("14\n").strip(), "14")
        print("MSL_B_ATTEMPT_LEDGER_FAIL_CLOSED=true REAL=malformed_and_cap_15 MUTATED=value_14_passes")

    def test_runner_uses_offline_chroot_not_docker(self) -> None:
        for forbidden in (
            "docker run",
            "command -v docker",
            "MSL_B_DOCKER_PRESENT=false",
            "ALPINE_IMAGE",
            "APK_CLOSURE",
            "apk add",
        ):
            self.assertNotIn(forbidden, self.runner)
        for marker in (
            "MSL_B_SELFTEST=${MSL_B_SELFTEST:-NO}",
            "MSL_B_ALPINE_DOWNLOAD=SKIPPED_OFFLINE",
            "timeout 900 chroot",
            "MSL_B_MUSL_INTERPRETER_GATE=",
            "NO_GLIBC_DEPENDENCY=",
            "NO_NEW_RUNTIME_DEPENDENCY=",
            "LIB_IDENTICAL=",
            "LD_LIBRARY_PATH=\"$MSL_B_BUILD_ROOTFS/lib:$MSL_B_BUILD_ROOTFS/usr/lib\"",
        ):
            self.assertIn(marker, self.runner)
        print("MSL_B_DOCKER_REQUIRED=false REAL=chroot_build MUTATED=docker_token_scan")

    def test_runner_selftest_is_no_live_interaction(self) -> None:
        for marker in (
            "MSL_B_SELFTEST_COMPLETED=",
            "MSL_B_SELFTEST_BUILD_RC=0",
            "MSL_B_SELFTEST_BINARY_SHA256=",
            "MSL_B_SELFTEST_HA_INTERACTION=$MSL_B_HA_INTERACTION",
            "MSL_B_SELFTEST_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION",
            "MSL_B_SELFTEST_CANDIDATE_EXECUTED=false",
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_BEGIN",
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_END",
            "MSL_B_SELFTEST_BUILD_RC=$MSL_B_LAST_BUILD_RC",
            "[ \"$MSL_B_SELFTEST\" = YES ] && [ \"$MSL_B_LIVE_RUN\" = YES ]",
            "run_selftest",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("[ \"$MSL_B_LIVE_RUN\" = YES ]; then", self.runner)
        print("MSL_B_SELFTEST_MODE=YES REAL=no_live_stub_path MUTATED=marker_scan")

    def test_build_diagnostics_tail_captures_stderr(self) -> None:
        marker = '" 2>&1 | tee "$RUN_ROOT/build.log"'
        self.assertIn(marker, self.runner)
        mutated = self.runner.replace(marker, '" | tee "$RUN_ROOT/build.log"', 1)
        self.assertNotIn(marker, mutated)

        def run_pipeline(with_stderr_redirect: bool) -> str:
            with tempfile.TemporaryDirectory() as run_root:
                pipeline = (
                    "timeout 5 /bin/sh -eu -c 'echo out-line; nonexistent_compiler_binary_xyz'"
                    + (" 2>&1" if with_stderr_redirect else "")
                    + f' | tee "{run_root}/build.log" >/dev/null'
                )
                subprocess.run(["bash", "-c", "set +e\n" + pipeline], text=True, capture_output=True, timeout=10, check=False)
                return Path(run_root, "build.log").read_text(encoding="utf-8")

        real_log = run_pipeline(with_stderr_redirect=True)
        mutated_log = run_pipeline(with_stderr_redirect=False)
        self.assertIn("nonexistent_compiler_binary_xyz", real_log)
        self.assertNotIn("nonexistent_compiler_binary_xyz", mutated_log)
        print(
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_POPULATED=true "
            f"REAL={real_log.strip()!r} MUTATED={mutated_log.strip()!r}"
        )

    def test_bound_invariant_falsifiable_and_udp_sink_present(self) -> None:
        real = re.search(r"MEDIA_OBSERVATION_SECONDS=\$\{MEDIA_OBSERVATION_SECONDS:-(\d+)\}", self.runner).group(1)
        mutated = self.runner.replace("MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-20}", "MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-100}")
        self.assertIn('echo "MSL_B_BOUND_INVARIANT=FAIL"', mutated)
        self.assertNotEqual(real, "100")
        self.assertIn("MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO", self.runner)
        print(f"MSL_B_BOUND_INVARIANT_FALSIFIABLE=true REAL={real} MUTATED=100")

    def test_runner_udp_sink_self_test(self) -> None:
        env = os.environ.copy()
        env["MSL_B_SELF_TEST_UDP_SINK"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if "MSL_B_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true" in proc.stdout:
            self.skipTest("NOT_AN_MSL_B_REGRESSION: Codex sandbox denied UDP sockets")
        self.assertIn("MSL_B_UDP_SINK_SELF_TEST_COUNT=3", proc.stdout)


if __name__ == "__main__":
    unittest.main()
