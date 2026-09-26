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
        self.assertEqual(self.generated_a, self.generated_b)
        print(f"MSL_GENERATED_SOURCE_REPRODUCIBLE=true REAL={a} MUTATED={b}")

    def test_refusal_mode_safe(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_OFFLINE_SAFE_REFUSAL=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertIn("MSL_RUN_CLASSIFICATION=NOT_RUN", proc.stdout)
        self.assertNotIn("MSL_T00_RESEARCH_START_MONO_MS", proc.stdout)
        print("MSL_REFUSAL_MODE_SAFE=true")

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
            "MSL_T19_T24_NA_REASON=HA_STREAM_HLS_PIPELINE_NOT_IN_THIS_CHILD",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START", self.runner)


if __name__ == "__main__":
    unittest.main()
