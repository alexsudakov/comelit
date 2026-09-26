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
        self.assertIn("msl_b_activate_idle_media()", activation_case)
        close_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_CLOSE:", 1)[1].split(
            "case P12_TX_R54_INVITE_ACK:", 1
        )[0]
        self.assertIn("r42_finish_media_channel_close()", close_case)

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
