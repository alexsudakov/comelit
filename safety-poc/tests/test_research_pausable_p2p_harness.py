#!/usr/bin/env python3
from __future__ import annotations

import base64
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
GENERATOR = MEDIA / "research_stage_interlock_generator.py"
HARNESS = ROOT / "safety-poc" / "tests" / "native" / "research_stage_interlock_host_harness.c"
COMPONENT = ROOT / "custom_components" / "comelit"
NATIVE_BINARY = COMPONENT / "native" / "comelit-media"
SHIPPED_SHA = "83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r65_production_media_refresh_transform as production  # noqa: E402
import entrance_research_stage_interlock_transform as interlock  # noqa: E402


REMOTE_SDP = (
    "v=0\r\n"
    "o=- 2 2 IN IP4 127.0.0.1\r\n"
    "s=Comelit research remote\r\n"
    "t=0 0\r\n"
    "a=ice-ufrag:remoteufrag\r\n"
    "a=ice-pwd:remotepassword\r\n"
    "a=candidate:1 1 UDP 2130706431 127.0.0.1 5001 typ host\r\n"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeP2P:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def __enter__(self) -> "FakeP2P":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    @property
    def url(self) -> str:
        return "fixture://p2p"


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
        cls.build = subprocess.run([str(BUILD), str(cls.tmp / "artifact")], text=True, capture_output=True, env=env)
        cls.binary = cls.tmp / "artifact" / "comelit-media-research"
        cls.binary_sha = sha256_bytes(cls.binary.read_bytes()) if cls.binary.exists() else ""
        cls.creds = cls.tmp / "creds.json"
        cls.creds.write_text(
            json.dumps(
                {
                    "device_uuid": "00000000-0000-0000-0000-000000000000",
                    "vip_token": "fixture-vip-token-not-real",
                    "oauth_access_token": "fixture-oauth-token-not-real",
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp_obj.cleanup()

    def run_runner(self, stage: int, *extra: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
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
                "160",
                "--timeout",
                "3",
                *extra,
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    def run_live_stage7(self, fake: FakeP2P, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_runner(
            7,
            "--live-stage-test",
            "--verify-musl-marker",
            "--credential-file",
            str(self.creds),
            "--p2p-url",
            fake.url,
            *extra,
        )

    def test_01_stage6_gate_waits_for_control_action_timeout(self) -> None:
        result = self.run_runner(6, "--no-auto-abort-stage6")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_ENTERED=true", result.stdout)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=TIMEOUT", result.stdout)

    def test_02_stage6_continue_works_in_fixture_lane(self) -> None:
        result = self.run_runner(7, "--stage6-continue")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE", result.stdout)
        self.assertIn("HELPER_CONTINUE_COUNT=1", result.stdout)

    def test_03_stage6_abort_cleanup(self) -> None:
        result = self.run_runner(6, "--stage6-abort")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=ABORT", result.stdout)
        self.assertIn("LOCAL_CLEANUP=true", result.stdout)

    def test_04_stage6_control_channel_loss_cleanup(self) -> None:
        result = self.run_runner(6, "--close-control-channel")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=CHANNEL_LOST", result.stdout)

    def test_05_exactly_one_fake_post_in_stage7(self) -> None:
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("POST_COUNT=1", result.stdout)

    def test_06_remote_sdp_memory_only(self) -> None:
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake)
        self.assertIn("REMOTE_SDP_RECEIVED=true", result.stdout)
        self.assertIn("REMOTE_SDP_APPLIED=false", result.stdout)

    def test_07_no_remote_sdp_file_written(self) -> None:
        remote = self.tmp / "should-not-exist.sdp"
        remote.unlink(missing_ok=True)
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake, "--remote-sdp-file", str(remote))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(remote.exists())

    def test_08_helper_is_not_resumed_in_stage7(self) -> None:
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake)
        self.assertIn("HELPER_CONTINUE_COUNT=0", result.stdout)
        self.assertNotIn("RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE", result.stdout)

    def test_09_forbidden_resume_fails(self) -> None:
        result = self.run_runner(7, "--inject-guard-marker", "RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HELPER_RESUME_GUARD=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_10_forbidden_remote_sdp_apply_fails(self) -> None:
        result = self.run_runner(7, "--inject-guard-marker", "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REMOTE_SDP_APPLY_GUARD=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_11_forbidden_ice_connected_fails(self) -> None:
        result = self.run_runner(7, "--inject-guard-marker", "RESEARCH_STAGE_9_ICE_CONNECTED")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ICE_CONNECTED_GUARD=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_12_forbidden_pseudotcp_fails(self) -> None:
        result = self.run_runner(7, "--inject-guard-marker", "RESEARCH_STAGE_10_PSEUDOTCP_OPEN")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PSEUDOTCP_GUARD=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_13_forbidden_ctpp_fails(self) -> None:
        result = self.run_runner(7, "--inject-guard-marker", "V4_CTPP_REGISTRATION=PASS")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CTPP_GUARD=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_14_forbidden_activation_rtpc_rtp_fail(self) -> None:
        cases = {
            "ENTRANCE_SELF_ACTIVATION_SENT=PASS": "SELF_ACTIVATION_GUARD",
            "P78_RTPC_OPEN_REQUESTED=true": "RTPC_GUARD",
            "P80_RTP_FORWARD=PASS": "RTP_GUARD",
        }
        for marker, guard in cases.items():
            with self.subTest(marker=marker):
                result = self.run_runner(7, "--inject-guard-marker", marker)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{guard}=FORBIDDEN_STAGE_CROSSING", result.stdout)

    def test_15_no_live_flag_network_disabled(self) -> None:
        result = self.run_runner(6)
        self.assertIn("NETWORK_IO_TO_COMELIT=0", result.stdout)
        self.assertIn("COMELIT_NETWORK_DISABLED=1", result.stdout)

    def test_16_placeholder_credential_live_flag_fails(self) -> None:
        placeholder = self.tmp / "placeholder.env"
        placeholder.write_text("VIP_TOKEN_PRESENT=true\nVIP_TOKEN_LENGTH=12\n", encoding="utf-8")
        with FakeP2P() as fake:
            result = self.run_runner(
                7,
                "--live-stage-test",
                "--verify-musl-marker",
                "--credential-file",
                str(placeholder),
                "--p2p-url",
                fake.url,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CREDENTIAL_SOURCE=PLACEHOLDER", result.stderr)

    def test_17_production_binary_identity_live_flag_fails(self) -> None:
        with FakeP2P() as fake:
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--binary",
                    str(NATIVE_BINARY),
                    "--expected-sha256",
                    SHIPPED_SHA,
                    "--stop-after-stage",
                    "7",
                    "--live-stage-test",
                    "--verify-musl-marker",
                    "--credential-file",
                    str(self.creds),
                    "--p2p-url",
                    fake.url,
                ],
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PRODUCTION_BINARY_IDENTITY=REFUSED", result.stderr)

    def test_18_research_binary_identity_mismatch_fails(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--binary",
                str(self.binary),
                "--expected-sha256",
                "0" * 64,
                "--stop-after-stage",
                "7",
            ],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESEARCH_BINARY_IDENTITY=FAIL", result.stderr)

    def test_19_second_post_attempt_configuration_fails(self) -> None:
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake, "--max-p2p-start-calls", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MAX_P2P_START_CALLS_MUST_BE_ONE=true", result.stderr)

    def test_20_sigterm_cleanup(self) -> None:
        result = self.run_runner(6, "--terminate-during-hold")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=SIGTERM", result.stdout)

    def test_21_timeout_cleanup(self) -> None:
        result = self.run_runner(6, "--no-auto-abort-stage6")
        self.assertIn("RESEARCH_TEARDOWN_DONE=true", result.stdout)
        self.assertIn("LOCAL_CLEANUP=true", result.stdout)

    def test_22_temporary_secrets_removed(self) -> None:
        with FakeP2P() as fake:
            result = self.run_live_stage7(fake)
        self.assertIn("RESEARCH_TEMP_SECRET_REMOVED=true", result.stdout)
        self.assertIn("SECRET_CLEANUP=PASS", result.stdout)

    def test_23_no_child_processes_left(self) -> None:
        result = self.run_runner(6)
        self.assertIn("RESEARCH_CHILD_PROCESSES_LEFT=0", result.stdout)

    def observer(self, text: str) -> str:
        path = self.tmp / "observer.log"
        path.write_text(text, encoding="utf-8")
        result = subprocess.run([sys.executable, str(OBSERVER), "--log-file", str(path)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_24_observer_distinguishes_listener_vs_research_helper(self) -> None:
        out = self.observer("RESEARCH_STAGE_6_LOCAL_OFFER_READY\nV4_RING_LISTENER_READY=true\n")
        self.assertIn("RESEARCH_HELPER_IGNORED_LINES=1", out)
        self.assertIn("LISTENER_READY=true", out)

    def test_25_observer_detects_pid_generation_change_when_observable(self) -> None:
        out = self.observer("listener_ready=true process_pid=100\nlistener_ready=true process_pid=101\n")
        self.assertIn("LISTENER_PID_OBSERVABLE=true", out)
        self.assertIn("LISTENER_PROCESS_PID=101", out)
        self.assertIn("OBSERVER_RECONNECT_GENERATION=1", out)

    def test_26_observer_detects_socket_generation_change_when_observable(self) -> None:
        out = self.observer("listener_ready=true socket_inode=socket:[1]\nlistener_ready=true socket_inode=socket:[2]\n")
        self.assertIn("LISTENER_SOCKET_IDENTITY_OBSERVABLE=true", out)
        self.assertIn("OBSERVER_RECONNECT_GENERATION=1", out)

    def test_26b_observer_reports_not_observable_without_capability(self) -> None:
        out = self.observer("listener_ready=true\nlistener_ready=false\n")
        self.assertIn("LISTENER_PROCESS_PID=NOT_OBSERVABLE", out)
        self.assertIn("LISTENER_SOCKET_IDENTITY=NOT_OBSERVABLE", out)
        self.assertIn("MISSING_CAPABILITY=read-only route exposing listener process pid and socket inode/transport identity", out)

    def test_27_production_generator_disabled_byte_identical(self) -> None:
        self.assertEqual(self.disabled, self.production)
        self.assertNotEqual(self.research, self.production)
        self.assertNotIn("RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED", self.research)
        self.assertIn("research_enter_stage6_pause_gate", self.research)

    def test_28_production_lifecycle_custom_component_unchanged(self) -> None:
        changed = subprocess.run(
            ["git", "diff", "--name-only", "origin/main", "--", "custom_components/comelit"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(changed.stdout.strip(), "")

    def test_29_shipped_native_binary_unchanged(self) -> None:
        self.assertEqual(sha256_bytes(NATIVE_BINARY.read_bytes()), SHIPPED_SHA)

    def test_30_full_offline_safety_static_contracts(self) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        self.assertTrue(self.binary.exists())
        self.assertIn("RESEARCH_HELPER_BUILD=HOST_STUB", self.build.stdout)
        self.assertIn("RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE", Path(MEDIA / "research_stage_stub_helper.c").read_text())
        self.assertIn("MAX_P2P_START_CALLS", Path(RUNNER).read_text())
        self.assertIn("NETWORK_IO_TO_COMELIT=0", Path(RUNNER).read_text())
        self.assertIn("NOT_OBSERVABLE", Path(OBSERVER).read_text())

    def test_generator_entrypoint_tolerates_include_p116_and_refuses_native_output(self) -> None:
        output = self.tmp / "generated.c"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--source", str(SOURCE), "--output", str(output), "--include-p116"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESEARCH_GENERATOR=RESEARCH_ONLY", result.stdout)
        forbidden = ROOT / "custom_components" / "comelit" / "native" / "forbidden.c"
        blocked = subprocess.run(
            [sys.executable, str(GENERATOR), "--source", str(SOURCE), "--output", str(forbidden)],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("RESEARCH_GENERATOR_OUTPUT_FORBIDDEN", blocked.stderr)

    def test_build_script_fails_closed_without_host_self_test_or_musl(self) -> None:
        if shutil.which("musl-gcc"):
            self.skipTest("musl-gcc present on this host")
        result = subprocess.run([str(BUILD), str(self.tmp / "fail-artifact")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 78)
        self.assertIn("FAIL_CLOSED_MUSL_UNAVAILABLE", result.stderr)

    def test_no_automatic_retry_static_harness(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
