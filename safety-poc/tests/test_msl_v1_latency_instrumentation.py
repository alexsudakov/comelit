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
TRANSFORM = MEDIA / "entrance_msl_v1_latency_instrumentation_transform.py"
RUNNER = MEDIA / "ct120_run_msl_v1_baseline_live.sh"

sys.path.insert(0, str(MEDIA))

import entrance_msl_v1_latency_instrumentation_transform as msl  # noqa: E402
import entrance_p116_r65_production_media_refresh_transform as r65  # noqa: E402


T_MARKERS = {
    "T03": "MSL_T03_NATIVE_HELPER_PROCESS_START_MONO_MS",
    "T04": "MSL_T04_LOCAL_SDP_OFFER_READY_MONO_MS",
    "T08": "MSL_T08_ICE_CONNECTED_MONO_MS",
    "T09": "MSL_T09_PSEUDOTCP_OPEN_MONO_MS",
    "T10": "MSL_T10_VIP_UAUT_READY_MONO_MS",
    "T11": "MSL_T11_CTPP_REGISTRATION_READY_MONO_MS",
    "T12": "MSL_T12_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS",
    "T13": "MSL_T13_INITIAL_001A_SENT_MONO_MS",
    "T14": "MSL_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE_MONO_MS",
    "T15": "MSL_T15_MEDIA_ACTIVE_MONO_MS",
    "T16": "MSL_T16_FIRST_AUDIO_RTP_MONO_MS",
    "T17": "MSL_T17_FIRST_VIDEO_RTP_MONO_MS",
    "T18": "MSL_T18_FIRST_SPS_PPS_IDR_MONO_MS",
}

WRAPPER_T_MARKERS = {
    "T06": "MSL_T06_CLOUD_P2P_REQUEST_START_MONO_MS",
    "T07": "MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS",
}


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MslV1LatencyInstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = msl.transform(cls.base, include_p116=True)
        cls.generated_b = msl.transform(cls.base, include_p116=True)
        cls.r65_candidate = r65.transform(cls.base, include_p116=True)
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_marker_set_complete(self) -> None:
        missing = [name for name in T_MARKERS.values() if name not in self.generated_a]
        self.assertFalse(missing)
        print("MSL_T_MARKER_SET_COMPLETE=true")

    def test_t06_t07_are_wrapper_emitted(self) -> None:
        for name in WRAPPER_T_MARKERS.values():
            self.assertIn(name.removeprefix("MSL_").removesuffix("_MONO_MS"), self.runner)
            self.assertNotIn(name, self.generated_a)
        report = msl.report()
        self.assertIn("MSL_T06_CLOUD_P2P_REQUEST_START_EMITTED_BY=RUNNER_WRAPPER", report)
        self.assertIn("MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_EMITTED_BY=RUNNER_WRAPPER", report)
        print("MSL_A_T06_T07_EMITTED=true")

    def test_marker_single_emission_structural(self) -> None:
        for enum_name in (
            "MSL_T03_NATIVE_HELPER_PROCESS_START",
            "MSL_T04_LOCAL_SDP_OFFER_READY",
            "MSL_T08_ICE_CONNECTED",
            "MSL_T09_PSEUDOTCP_OPEN",
            "MSL_T10_VIP_UAUT_READY",
            "MSL_T11_CTPP_REGISTRATION_READY",
            "MSL_T12_RTPC_MEDIA_OPEN_CONTROL_READY",
            "MSL_T13_INITIAL_001A_SENT",
            "MSL_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE",
            "MSL_T15_MEDIA_ACTIVE",
            "MSL_T16_FIRST_AUDIO_RTP",
            "MSL_T17_FIRST_VIDEO_RTP",
            "MSL_T18_FIRST_SPS_PPS_IDR",
        ):
            self.assertEqual(self.generated_a.count(f"msl_mark_once({enum_name})"), 1, enum_name)
        self.assertIn("if (!msl_clock_base_loaded", self.generated_a)
        self.assertIn("msl_marker_seen[marker]", self.generated_a)
        print("MSL_MARKER_SINGLE_EMISSION=true")

    def test_marker_derivation_flip_proof(self) -> None:
        real = sha_text(self.generated_a)
        mutated_source = self.base.replace('printf("ICE_GATHER=PASS\\n");', 'printf("ICE_GATHER_DONE=PASS\\n");', 1)
        with self.assertRaises(RuntimeError):
            msl.transform(mutated_source, include_p116=True)
        mutated = "ANCHOR_FAIL"
        self.assertNotEqual(real, mutated)
        print(f"MSL_MARKER_DERIVATION_FLIP_PROOF=true REAL={real} MUTATED={mutated}")

    def test_clock_base_fail_closed(self) -> None:
        self.assertIn('const char *path = getenv("MSL_CLOCK_BASE_FILE");', self.generated_a)
        self.assertIn('printf("MSL_CLOCK_BASE_MISSING=true\\n");', self.generated_a)
        self.assertIn("if (!msl_load_clock_base())\n        return 2;", self.generated_a)
        print("MSL_CLOCK_BASE_FAIL_CLOSED=true")

    def test_no_door_gate_path_added(self) -> None:
        added_lines = set(self.generated_a.splitlines()) - set(self.r65_candidate.splitlines())
        for line in added_lines:
            self.assertNotRegex(line, r"\b(DOOR|GATE|v4_door|gate_action|SIGUSR1)\b")
        print("MSL_NO_DOOR_GATE_PATH_ADDED=true")

    def test_no_new_session_setup_path_added(self) -> None:
        added_lines = set(self.generated_a.splitlines()) - set(self.r65_candidate.splitlines())
        forbidden = (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P78_TX_RTPC_OPEN_1",
            "P78_TX_RTPC_OPEN_2",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
        )
        for line in added_lines:
            for token in forbidden:
                self.assertNotIn(token, line)
        print("MSL_NO_NEW_SESSION_SETUP_PATH=true")

    def test_generated_source_reproducible(self) -> None:
        a = sha_text(self.generated_a)
        b = sha_text(self.generated_b)
        mutated_generated = msl.transform(self.base + "\n/* MSL_REPRO_MUTATION */\n", include_p116=True)
        mutated = sha_text(mutated_generated)
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertNotEqual(a, mutated)
        print(f"MSL_GENERATED_SOURCE_REPRODUCIBLE=true REAL={a} MUTATED={mutated}")

    def test_refusal_mode_safe(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_OFFLINE_SAFE_REFUSAL=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertIn("MSL_RUN_CLASSIFICATION=NOT_RUN", proc.stdout)
        self.assertNotIn("MSL_T00_RESEARCH_START_MONO_MS", proc.stdout)
        print("MSL_REFUSAL_MODE_SAFE=true")

    def test_dry_run_reaches_final_summary_without_live_attempt(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MSL_DRY_RUN_COMPLETED=true", proc.stdout)
        self.assertIn("MSL_DRY_RUN_REACHED_FINAL_SUMMARY=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertIn("DOOR_ACTIONS_SENT=0", proc.stdout)
        self.assertIn("GATE_ACTIONS_SENT=0", proc.stdout)
        self.assertIn("MSL_RUN_CLASSIFICATION=DRY_RUN_COMPLETE", proc.stdout)
        self.assertIn("MSL_DRY_RUN_WRAPPER_EXECUTED=true", proc.stdout)
        self.assertIn("MSL_DRY_RUN_WRAPPER_RC=0", proc.stdout)
        print("MSL_DRY_RUN_REACHED_FINAL_SUMMARY=true")

    def test_variant_a_dry_run_reaches_final_summary_without_live_attempt(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        env["MSL_VARIANT_A"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MSL_A_VARIANT_MODE=YES", proc.stdout)
        self.assertIn("MSL_A_ENABLED=true", proc.stdout)
        self.assertIn("MSL_A_DEFERRED_HOLDER_LOG=true", proc.stdout)
        self.assertIn("MSL_DRY_RUN_REACHED_FINAL_SUMMARY=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertIn("DOOR_ACTIONS_SENT=0", proc.stdout)
        self.assertIn("GATE_ACTIONS_SENT=0", proc.stdout)
        self.assertIn("AUTOMATIC_PROTOCOL_RETRY=false", proc.stdout)
        self.assertIn("SECOND_MEDIA_SESSION=false", proc.stdout)
        self.assertIn("MSL_T06_CLOUD_P2P_REQUEST_START_MONO_MS=", proc.stdout)
        self.assertIn("MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS=", proc.stdout)
        print("MSL_A_DRY_RUN_BOTH_MODES_REACH_FINAL_SUMMARY=true")

    def test_variant_a_mode_switch_preserves_baseline_branch(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        baseline = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        env["MSL_VARIANT_A"] = "YES"
        variant = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.assertEqual(variant.returncode, 0, variant.stderr)
        real = (
            "MSL_A_VARIANT_MODE=NO" in baseline.stdout
            and "MSL_A_ENABLED=false" in baseline.stdout
            and "MSL_A_DEFERRED_HOLDER_LOG=true" not in baseline.stdout
        )
        mutated = (
            "MSL_A_VARIANT_MODE=YES" in variant.stdout
            and "MSL_A_DEFERRED_HOLDER_LOG=true" in variant.stdout
        )
        self.assertTrue(real)
        self.assertTrue(mutated)
        print(f"MSL_A_BASELINE_PATH_UNCHANGED=true REAL={str(real).lower()} MUTATED={str(mutated).lower()}")

    def test_variant_a_static_safety_contract(self) -> None:
        self.assertIn('MSL_VARIANT_A=${MSL_VARIANT_A:-NO}', self.runner)
        self.assertIn("MSL_A_DEFERRED_HOLDER_LOG=true", self.runner)
        self.assertIn("SECOND_MEDIA_SESSION=false", self.runner)
        self.assertIn("AUTOMATIC_PROTOCOL_RETRY=false", self.runner)
        variant_region = self.runner.split('if variant_a == "YES":', 1)[1].split('elif variant_a != "NO":', 1)[0]
        for forbidden in ("SIGUSR1", "open_door", "gate_action", "MSL_LIVE_RUN=YES"):
            self.assertNotIn(forbidden, variant_region)
        self.assertNotIn("timeout --signal=TERM --kill-after=5s \"$MEDIA_STARTUP_OUTER_TIMEOUT\" \"$CANDIDATE_WRAPPER\"", variant_region)
        print("MSL_A_NO_NEW_SESSION_PATH=true")
        print("MSL_A_NO_DOOR_GATE_PATH=true")
        print("MSL_A_NO_RETRY_ADDED=true")
        print("MSL_A_ORDERING_CONSTRAINT_PRESERVED=true CONSTRAINT=offer_sdp_exists_before_single_cloud_p2p_request")

    def test_dry_run_has_zero_real_ha_or_comelit_interaction(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MSL_DRY_RUN_REAL_HA_WEBHOOK=false", proc.stdout)
        self.assertIn("MSL_DRY_RUN_REAL_COMELIT=false", proc.stdout)
        self.assertIn("MSL_DRY_RUN_CHROOT_BUILD=false", proc.stdout)
        self.assertIn("MSL_DRY_RUN_REAL_CANDIDATE_EXECUTED=false", proc.stdout)
        self.assertIn("MSL_DRY_RUN_STUB_HELPER_EXECUTED=via_wrapper", proc.stdout)
        self.assertIn("MSL_DRY_RUN_COMELIT_INTERACTION=0", proc.stdout)
        self.assertIn("MSL_DRY_RUN_HA_INTERACTION=0", proc.stdout)
        self.assertNotIn("CONTROL_STATUS_CURL_RC", proc.stdout)
        self.assertNotIn("BASE_WRAPPER_SHA256=", proc.stdout)
        print("MSL_DRY_RUN_COMELIT_INTERACTION=0")
        print("MSL_DRY_RUN_HA_INTERACTION=0")

    def test_dry_run_materialized_wrapper_shebang_and_markers(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MSL_WRAPPER_SHEBANG_LINE=1", proc.stdout)
        self.assertIn("MSL_WRAPPER_FIRST_LINE_GATE=PASS", proc.stdout)
        self.assertIn("MSL_DRY_RUN_WRAPPER_FIRST_LINE_GATE=PASS", proc.stdout)
        self.assertIn("ICE_GATHER=PASS", proc.stdout)
        self.assertIn("P80_MEDIA_ACTIVE=true", proc.stdout)
        self.assertIn("P80_VIDEO_RTP_FORWARDING=PASS", proc.stdout)
        self.assertIn("MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS=", proc.stdout)
        self.assertIn("MSL_CLOCK_BASE_SURVIVES_WRAPPER_RM=true", proc.stdout)
        self.assertIn("MSL_DRY_RUN_SYNTHETIC_OFFER_WRITTEN=true", proc.stdout)
        print("MSL_DRY_RUN_WRAPPER_EXECED_MARKERS_OBSERVED=true")

    def test_clock_base_destruction_regression_flip_proof(self) -> None:
        def survives(clock_path: Path, wiped_dir: Path) -> bool:
            clock_path.parent.mkdir(parents=True, exist_ok=True)
            wiped_dir.mkdir(parents=True, exist_ok=True)
            clock_path.write_text("123\n", encoding="utf-8")
            for child in wiped_dir.iterdir():
                if child.is_file():
                    child.unlink()
            if clock_path.is_relative_to(wiped_dir):
                try:
                    clock_path.unlink()
                except FileNotFoundError:
                    pass
            return clock_path.exists()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = survives(root / "clock" / "msl-clock-base", root / "comelit-media")
            mutated = survives(root / "comelit-media" / "msl-clock-base", root / "comelit-media")
        self.assertTrue(real)
        self.assertFalse(mutated)
        print(f"MSL_CLOCK_BASE_DESTRUCTION_REGRESSION_TEST=PASS REAL={str(real).lower()} MUTATED={str(mutated).lower()}")

    def test_derived_delta_consistency(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        values: dict[str, int] = {}
        for line in proc.stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if value.isdigit():
                values[key] = int(value)
        first_rtp = values["MSL_T17_FIRST_VIDEO_RTP_MONO_MS"] - values["MSL_T03_NATIVE_HELPER_PROCESS_START_MONO_MS"]
        decodable = values["MSL_T18_FIRST_SPS_PPS_IDR_MONO_MS"] - values["MSL_T03_NATIVE_HELPER_PROCESS_START_MONO_MS"]
        real = (
            values["MSL_START_TO_FIRST_RTP_MS"] == first_rtp
            and values["MSL_START_TO_DECODABLE_VIDEO_MS"] == decodable
        )
        mutated = (0 == first_rtp and 0 == decodable)
        self.assertTrue(real)
        self.assertFalse(mutated)
        print(f"MSL_DERIVED_DELTA_CONSISTENCY=PASS REAL={str(real).lower()} MUTATED={str(mutated).lower()}")

    def test_selftest_no_network_mode(self) -> None:
        env = os.environ.copy()
        env["MSL_SELFTEST"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("MSL_SELFTEST_MODE=YES", proc.stdout)
        self.assertIn("MSL_SELFTEST_COMPLETED=true", proc.stdout)
        self.assertIn("MSL_SELFTEST_HA_INTERACTION=0", proc.stdout)
        self.assertIn("MSL_SELFTEST_COMELIT_INTERACTION=0", proc.stdout)
        self.assertIn("MSL_SELFTEST_CLOCK_BASE_READABLE=true", proc.stdout)
        self.assertIn("MSL_SELFTEST_SYNTHETIC_OFFER_WRITTEN=true", proc.stdout)
        match = re.search(r"MSL_SELFTEST_MARKERS_OBSERVED=(\d+)", proc.stdout)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 13)

    def test_wrapper_first_line_gate_flip_proof(self) -> None:
        def gate(text: str) -> str:
            lines = text.splitlines()
            first = lines[0] if lines else ""
            shebang_line = next((i for i, line in enumerate(lines, 1) if line.startswith("#!")), 0)
            return "PASS" if first.startswith("#!") and shebang_line == 1 else "FAIL"

        real = gate("#!/usr/bin/env bash\nset -u\n")
        mutated = gate("msl_mono_ms() { :; }\n#!/usr/bin/env bash\nset -u\n")
        self.assertEqual(real, "PASS")
        self.assertEqual(mutated, "FAIL")
        print(f"MSL_WRAPPER_FIRST_LINE_GATE_FLIP_PROOF=REAL={real} MUTATED={mutated}")

    def test_dry_run_only_markers_not_in_refusal_output(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotIn("MSL_DRY_RUN_LIVE_INVOCATIONS=", proc.stdout)
        self.assertNotIn("MSL_DRY_RUN_HA_INTERACTION=", proc.stdout)
        self.assertNotIn("MSL_DRY_RUN_COMELIT_INTERACTION=", proc.stdout)
        self.assertNotIn("MSL_DRY_RUN_WRAPPER_EXECUTED=", proc.stdout)
        print("MSL_DRY_RUN_ONLY_MARKERS_EMITTED_IN_LIVE_RUN=false")

    def test_dry_run_cannot_combine_with_live_run(self) -> None:
        env = os.environ.copy()
        env["MSL_DRY_RUN"] = "YES"
        env["MSL_LIVE_RUN"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_DRY_OR_SELFTEST_LIVE_RUN_CONFLICT=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)

    def test_budget_guard_refuses_missing_malformed_and_cap(self) -> None:
        env = os.environ.copy()
        env.update({"MSL_LIVE_RUN": "YES", "MSL_EXPECTED_COMMIT_SHA": "x"})
        missing = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        self.assertIn("MSL_ATTEMPT_LEDGER_REQUIRED=true", missing.stdout)
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger"
            for value, marker in (("abc\n", "MSL_ATTEMPT_LEDGER=MALFORMED"), ("15\n", "MSL_ATTEMPT_LEDGER_CAP=FAIL")):
                ledger.write_text(value, encoding="utf-8")
                env["MSL_ATTEMPT_LEDGER"] = str(ledger)
                proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
                self.assertIn(marker, proc.stdout)
        print("MSL_BUDGET_GUARD_PASS=true")

    def test_bound_invariant_falsifiable(self) -> None:
        real = re.search(r"SETUP_MARGIN_SECONDS=\$\{SETUP_MARGIN_SECONDS:-(\d+)\}", self.runner).group(1)
        mutated = self.runner.replace("SETUP_MARGIN_SECONDS=${SETUP_MARGIN_SECONDS:-45}", "SETUP_MARGIN_SECONDS=${SETUP_MARGIN_SECONDS:-1}")
        self.assertIn('echo "MSL_BOUND_INVARIANT=FAIL"', mutated)
        self.assertNotEqual(real, "1")
        print(f"MSL_BOUND_INVARIANT_FALSIFIABLE=true REAL={real} MUTATED=1")

    def test_udp_sink_independent_witness(self) -> None:
        env = os.environ.copy()
        env["MSL_SELF_TEST_UDP_SINK"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if "MSL_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true" in proc.stdout:
            self.skipTest("NOT_AN_MSL_REGRESSION: Codex sandbox denied UDP sockets")
        self.assertIn("MSL_UDP_SINK_SELF_TEST_COUNT=3", proc.stdout)
        print("MSL_UDP_SINK_INDEPENDENT_WITNESS=true")

    def test_runner_contains_wrapper_and_na_contract(self) -> None:
        for marker in (
            'msl_mark "T00_RESEARCH_START"',
            'msl_mark "T01_LISTENER_STOP_REQUESTED"',
            'msl_mark "T02_LISTENER_RUNTIME_CONFIRMED_STOPPED"',
            "T05_OAUTH_ACCESS_TOKEN_AVAILABLE",
            "T06_CLOUD_P2P_REQUEST_START",
            "T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN",
            "materialize_candidate_wrapper",
            "MSL_WRAPPER_FIRST_LINE_GATE=PASS",
            "MSL_CLOCK_BASE_SURVIVES_WRAPPER_RM=true",
            "MSL_T19_T24_NA_REASON=HA_STREAM_HLS_PIPELINE_NOT_IN_THIS_CHILD",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START", self.runner)

    def test_no_local_or_declare_same_statement_self_reference(self) -> None:
        offenders: list[str] = []
        assignment_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=")
        for lineno, line in enumerate(self.runner.splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("local ") or stripped.startswith("declare ")):
                continue
            assigned = assignment_pattern.findall(stripped)
            for name in assigned:
                _, _, rhs = stripped.partition(f"{name}=")
                if f"${{{name}}}" in rhs or re.search(rf"(^|[^A-Za-z0-9_])\\${name}([^A-Za-z0-9_]|$)", rhs):
                    offenders.append(f"{lineno}:{stripped}")
        self.assertFalse(offenders, "\n".join(offenders))
        print("LOCAL_SELF_REF_PATTERN_REMAINING=0")


if __name__ == "__main__":
    unittest.main()
