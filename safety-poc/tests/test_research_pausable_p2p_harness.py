#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
BUILD = MEDIA / "build_research_stage_interlock_helper.sh"
RUNNER = MEDIA / "research_pausable_p2p_runner.py"
OBSERVER = MEDIA / "listener_readonly_observer.py"
HARNESS = ROOT / "safety-poc" / "tests" / "native" / "research_stage_interlock_host_harness.c"
COMPONENT = ROOT / "custom_components" / "comelit"
NATIVE_BINARY = COMPONENT / "native" / "comelit-media"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r65_production_media_refresh_transform as production  # noqa: E402
import entrance_research_stage_interlock_transform as interlock  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ResearchPausableP2PHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.production = production.transform(cls.source, include_p116=True)
        cls.disabled = interlock.transform(cls.source, research=False)
        cls.research = interlock.transform(cls.source, research=True)
        cls.tmp_obj = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.tmp_obj.name)
        env = {"RESEARCH_HOST_SELF_TEST": "1", **dict(**__import__("os").environ)}
        cls.build = subprocess.run(
            [str(BUILD), str(cls.tmp / "artifact")],
            text=True,
            capture_output=True,
            env=env,
        )
        cls.binary = cls.tmp / "artifact" / "comelit-media-research"
        cls.binary_sha = sha256_bytes(cls.binary.read_bytes()) if cls.binary.exists() else ""

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp_obj.cleanup()

    def run_runner(self, stage: int, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--binary",
                str(self.binary),
                "--expected-sha256",
                self.binary_sha,
                "--stop-after-stage",
                str(stage),
                "--hold-ms",
                "120",
                *extra,
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_14_disabled_transform_is_byte_identical_to_production_generation(self) -> None:
        self.assertEqual(self.disabled, self.production)
        self.assertNotEqual(self.research, self.production)
        self.assertEqual(
            sha256_bytes(NATIVE_BINARY.read_bytes()),
            "83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a",
        )

    def test_research_markers_and_hard_guards_are_in_generated_source(self) -> None:
        for marker in (
            "RESEARCH_STAGE_6_LOCAL_OFFER_READY",
            "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED",
            "RESEARCH_STAGE_9_ICE_CONNECTED",
            "RESEARCH_STAGE_10_PSEUDOTCP_OPEN",
            "RESEARCH_STAGE_11_CTPP_PRE_REGISTER",
            "RESEARCH_STAGE_12_CTPP_REGISTERED",
            "RESEARCH_HOLD_ENTERED",
            "RESEARCH_TEARDOWN_BEGIN",
            "FORBIDDEN_STAGE_CROSSING",
            "SELF_ACTIVATION_SENT=false",
            "RTPC_OPENED=false",
            "RTP_STARTED=false",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.research)

    def test_stage_11_is_not_faked_as_configurable_stop(self) -> None:
        self.assertIn("STAGE_11_NOT_SEPARABLE=true", interlock.report())
        self.assertNotIn("parsed == 11", self.research)

    def test_build_script_host_self_test_materializes_stub_binary_only(self) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        self.assertTrue(self.binary.exists())
        self.assertIn("RESEARCH_HELPER_BUILD=HOST_STUB", self.build.stdout)

    def test_build_script_fails_closed_without_host_self_test_or_musl(self) -> None:
        if shutil.which("musl-gcc"):
            self.skipTest("musl-gcc present on this host")
        result = subprocess.run(
            [str(BUILD), str(self.tmp / "fail-artifact")],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 78)
        self.assertIn("FAIL_CLOSED_MUSL_UNAVAILABLE", result.stderr)

    def test_1_stop_after_stage_6_does_not_reach_stage_7(self) -> None:
        result = self.run_runner(6)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_STAGE_6_LOCAL_OFFER_READY", result.stdout)
        self.assertNotIn("RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED", result.stdout)

    def test_2_to_5_stage_boundaries_stop_before_next_stage(self) -> None:
        cases = {
            7: "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED",
            8: "RESEARCH_STAGE_9_ICE_CONNECTED",
            9: "RESEARCH_STAGE_10_PSEUDOTCP_OPEN",
            10: "RESEARCH_STAGE_12_CTPP_REGISTERED",
        }
        for stage, forbidden in cases.items():
            with self.subTest(stage=stage):
                result = self.run_runner(stage)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"RESEARCH_STOP_AFTER_STAGE={stage}", result.stdout)
                self.assertNotIn(forbidden, result.stdout)

    def test_6_stage_12_does_not_reach_self_activation(self) -> None:
        result = self.run_runner(12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_STAGE_12_CTPP_REGISTERED", result.stdout)
        self.assertIn("SELF_ACTIVATION_SENT=false", result.stdout)
        self.assertNotIn("ENTRANCE_SELF_ACTIVATION_SENT=PASS", result.stdout)

    def test_7_forbidden_stage_crossing_is_non_zero(self) -> None:
        result = self.run_runner(12, "--force-forbidden")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FORBIDDEN_STAGE_CROSSING=ENTRANCE_SIGNALING_ARMED", result.stdout)

    def test_8_hold_timeout_triggers_cleanup(self) -> None:
        result = self.run_runner(8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_TEARDOWN_REASON=timeout", result.stdout)
        self.assertIn("RESEARCH_TEARDOWN_DONE=true", result.stdout)

    def test_9_sigterm_triggers_cleanup(self) -> None:
        result = self.run_runner(9, "--terminate-during-hold")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_TEARDOWN_REASON=sigterm", result.stdout)

    def test_10_stop_file_semantics_are_not_stage_selection(self) -> None:
        self.assertIn("RESEARCH_STOP_FILE_OBSERVED=true", self.research)
        self.assertIn("RESEARCH_STOP_AFTER_STAGE", self.research)
        self.assertNotIn("RESEARCH_STOP_AFTER_STAGE=stop_file", self.research)

    def test_11_12_13_runner_proves_secret_child_and_socket_cleanup(self) -> None:
        result = self.run_runner(10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for marker in (
            "RESEARCH_TEMP_SECRET_REMOVED=true",
            "RESEARCH_CHILD_PROCESSES_LEFT=0",
            "RESEARCH_SOCKETS_CLOSED=true",
        ):
            self.assertIn(marker, result.stdout)

    def test_15_no_automatic_retry(self) -> None:
        added_lines = set(self.research.splitlines()) - set(self.production.splitlines())
        for line in added_lines:
            self.assertNotIn("RETRY", line)
        cc = shutil.which("cc")
        if not cc:
            self.skipTest("cc unavailable")
        binary = self.tmp / "native-harness"
        compile_result = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(HARNESS), "-o", str(binary)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        run = subprocess.run([str(binary)], text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("HARNESS_NO_RETRY=PASS", run.stdout)

    def test_16_production_600s_media_ceiling_unchanged(self) -> None:
        text = (COMPONENT / "media_session.py").read_text(encoding="utf-8")
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", text)
        self.assertNotIn("RESEARCH_STOP_AFTER_STAGE", text)

    def test_17_ring_door_gate_production_tests_are_unchanged_by_file_set(self) -> None:
        changed_production = subprocess.run(
            ["git", "diff", "--name-only", "origin/main", "--", "custom_components/comelit"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(changed_production.stdout.strip(), "")

    def test_runner_fails_closed_on_binary_identity_mismatch(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--binary",
                str(self.binary),
                "--expected-sha256",
                "0" * 64,
                "--stop-after-stage",
                "6",
            ],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESEARCH_BINARY_IDENTITY=FAIL", result.stderr)

    def test_listener_observer_sanitizes_identity_and_detects_conflict(self) -> None:
        status = self.tmp / "listener.json"
        status.write_text(
            json.dumps(
                {
                    "supervisor_running": True,
                    "listener_ready": True,
                    "media_paused": False,
                    "reconnect_count": 1,
                    "last_error": "none",
                    "process_pid": 123,
                    "socket_present": True,
                    "socket_inode": "socket:[999]",
                    "socket_inode_changed": True,
                    "transport_id": "transport-alpha",
                    "transport_id_changed": True,
                    "ctpp_registered": True,
                    "registration_generation": 7,
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(OBSERVER), "--status-json", str(status)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LISTENER_SOCKET_IDENTITY=", result.stdout)
        self.assertIn("LISTENER_CONFLICT_DETECTED=true", result.stdout)

    def test_red_controls_show_previous_behavior_would_fail_core_expectations(self) -> None:
        previous = self.production
        self.assertNotIn("RESEARCH_HOLD_ENTERED", previous)
        self.assertNotIn("FORBIDDEN_STAGE_CROSSING", previous)
        self.assertIn("ENTRANCE_SIGNALING_ARMED=true", previous)


if __name__ == "__main__":
    unittest.main()
