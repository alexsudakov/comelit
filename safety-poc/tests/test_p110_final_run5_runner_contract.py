#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p110_final_run5_runner.sh"
SHIM = ROOT / "research" / "media" / "v1" / "p111_packaged_musl_holder_shim.sh"
P105_RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p105_entrance_media_live.sh"
P108_RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p108_exact_packaged_musl_validation.sh"
P109_HARNESS = ROOT / "research" / "media" / "v1" / "p109_corrected_live_orchestration.py"
PACKAGED = REPO_ROOT / "custom_components" / "comelit" / "native" / "comelit-media"

EXPECTED_HEAD = "977f7197f103050a9f52b43dad26af5df0c7bbf0"
EXPECTED_PACKAGED_SHA = "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"
EXPECTED_BASE_WRAPPER_SHA = "a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9"


def drive_script(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", body],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def function_body(text: str, name: str) -> str:
    return text.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]


class P111CorrectedRun5RunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.shim = SHIM.read_text(encoding="utf-8")
        cls.p105 = P105_RUNNER.read_text(encoding="utf-8")
        cls.p108 = P108_RUNNER.read_text(encoding="utf-8")
        cls.p109 = P109_HARNESS.read_text(encoding="utf-8")

    def test_runner_and_shim_are_executable_and_syntax_clean(self) -> None:
        self.assertTrue(os.stat(RUNNER).st_mode & 0o111)
        self.assertTrue(os.stat(SHIM).st_mode & 0o111)
        for path in (RUNNER, SHIM):
            result = subprocess.run(["bash", "-n", str(path)], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaged_pr106_identity_and_research_delivery_are_explicit(self) -> None:
        self.assertIn(f"EXPECTED_PR106_HEAD={EXPECTED_HEAD}", self.runner)
        self.assertIn("REPO=\"${REPO:-/root/comelit-door-diag-pr106}\"", self.runner)
        self.assertIn("RESEARCH_ARTIFACT_ROOT=", self.runner)
        self.assertIn("RUNNER_SELF_SHA256=\"$(sha256sum \"$RUNNER_EXECUTED_PATH\"", self.runner)
        self.assertIn("local source=\"$RESEARCH_ARTIFACT_ROOT/$HOLDER_SHIM_REL\"", self.runner)
        self.assertIn("PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media", self.runner)
        self.assertIn("PACKAGED_BINARY_REBUILT=false", self.runner)
        self.assertIn("PACKAGED_BINARY_SUBSTITUTED=false", self.runner)
        self.assertEqual(hashlib.sha256(PACKAGED.read_bytes()).hexdigest(), EXPECTED_PACKAGED_SHA)

    def test_base_wrapper_sha_and_p105_anchor_rewrite_are_required(self) -> None:
        self.assertIn("BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe", self.runner)
        self.assertIn(f"BASE_WRAPPER_SHA256={EXPECTED_BASE_WRAPPER_SHA}", self.runner)
        self.assertIn("assert_base_wrapper_identity", self.runner)
        self.assertIn("BASE_WRAPPER_GATE=PASS", self.runner)
        self.assertIn("needle = '\"$BASE/bin/comelit_ice_offer_holder\"'", self.runner)
        self.assertIn("HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=PASS", self.runner)
        self.assertIn("HOLDER_TERMINAL_RESULT=EXPECTED_SHUTDOWN", self.runner)
        self.assertIn("text.replace(legacy_run_dir, media_run_dir)", self.runner)
        self.assertIn("BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe", self.p105)

    def test_holder_shim_only_verifies_and_execs_packaged_musl_binary(self) -> None:
        self.assertIn(f"PACKAGED_BINARY_SHA256={EXPECTED_PACKAGED_SHA}", self.shim)
        self.assertIn('PR106_CHECKOUT="${P111_PR106_CHECKOUT:?}"', self.shim)
        self.assertIn('RUNTIME_LOADER="$RUNTIME_ROOT/lib/ld-musl-x86_64.so.1"', self.shim)
        self.assertIn('exec "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$PACKAGED_BINARY"', self.shim)
        self.assertIn("P111_SHIM_MUSL_EXEC_GATE=PASS", self.shim)
        for forbidden in ("aiohttp", "curl", "socket", "offer.sdp", "remote.sdp", "comelit_cloud_probe", "transform_offer"):
            self.assertNotIn(forbidden, self.shim)

    def test_no_new_python_live_cloud_dependency_or_direct_elf_live_client(self) -> None:
        live_tail = self.runner.split("=== EXACTLY ONE P111 P105/RUN3 BASE WRAPPER LIVE INVOCATION ===", 1)[1]
        live_invocation = live_tail.split("WRAPPER_PID=$!", 1)[0]
        self.assertIn('"$CANDIDATE_WRAPPER"', live_invocation)
        self.assertNotIn('"$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH"', live_invocation)
        self.assertNotIn("p110_run5_bootstrap.py", self.runner)
        self.assertNotIn("aiohttp", self.runner)
        self.assertNotIn("cloud.async_negotiate_p2p(", self.runner)
        self.assertEqual(self.runner.count("P2P_CLOUD_PROBE_RC=0"), 1)
        self.assertEqual(re.findall(r"^LIVE_INVOCATIONS=1$", self.runner, re.MULTILINE), ["LIVE_INVOCATIONS=1"])

    def test_rtp_sinks_start_before_live_wrapper_and_postprocess_before_gate(self) -> None:
        live = self.runner.index("=== EXACTLY ONE P111 P105/RUN3 BASE WRAPPER LIVE INVOCATION ===")
        self.assertLess(self.runner.index("start_udp_sink video", live - 400), live)
        self.assertLess(self.runner.index("start_udp_sink audio", live - 400), live)
        tail = self.runner[live:]
        self.assertLess(tail.index("stop_sink_if_needed \"$VIDEO_SINK_PID\""), tail.index("collect_log_markers"))
        self.assertLess(tail.index("collect_log_markers"), tail.index("postprocess_media"))
        self.assertLess(tail.index("postprocess_media"), tail.index("validate_media_success_contract"))

    def test_media_capture_and_depacketizer_are_ported_with_required_accounting(self) -> None:
        for name in ("start_udp_sink", "depacketize_h264", "postprocess_media"):
            self.assertIn(f"{name}() {{", self.runner)
        depacketizer = function_body(self.runner, "depacketize_h264")
        for marker in ("PT_H264 = 99", "nal_type == 24", "nal_type == 28", "P111_H264_FU_A_COUNT", "P111_H264_STAP_A_COUNT"):
            self.assertIn(marker, depacketizer)
        postprocess = function_body(self.runner, "postprocess_media")
        for marker in ("ffprobe -v error -f h264", "-frames:v 1", "-an -t 5 -c:v copy", "P111_JPEG_RESULT", "P111_SHORT_VIDEO_RESULT"):
            self.assertIn(marker, postprocess)

    def test_media_fixture_capture_and_mock_postprocess_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = textwrap.dedent(
                f"""
                P110_SOURCE_ONLY=1 source {RUNNER}
                RUN_ROOT={tmp}
                MEDIA_DIR={tmp}/media
                mkdir -p "$MEDIA_DIR"
                VIDEO_RTP_PORT=27991
                AUDIO_RTP_PORT=27992
                P111_RTP_CAPTURE_FIXTURE_NO_SOCKET=1
                run_rtp_capture_selftest
                echo VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS
                echo AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS
                echo RTP_CAPTURE_SELFTEST=$RTP_CAPTURE_SELFTEST
                echo MEDIA_POSTPROCESS_SELFTEST=$MEDIA_POSTPROCESS_SELFTEST
                """
            )
            result = drive_script(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RTP_CAPTURE_SELFTEST=PASS", result.stdout)
            self.assertIn("MEDIA_POSTPROCESS_SELFTEST=PASS", result.stdout)
            stats = Path(tmp) / "rtp-selftest" / "h264.stats"
            self.assertIn("P111_H264_SPS_COUNT=1", stats.read_text(encoding="utf-8"))
            self.assertIn("P111_H264_PPS_COUNT=1", stats.read_text(encoding="utf-8"))
            self.assertIn("P111_H264_IDR_COUNT=1", stats.read_text(encoding="utf-8"))

    def test_media_success_contract_rejects_zero_or_missing_media(self) -> None:
        body = function_body(self.runner, "validate_media_success_contract")
        for required in (
            'VIDEO_RTP_DATAGRAMS" -gt 0',
            'AUDIO_RTP_DATAGRAMS" -gt 0',
            'H264_SPS_COUNT" -gt 0',
            'H264_PPS_COUNT" -gt 0',
            'H264_IDR_COUNT" -gt 0',
            'FFPROBE_H264" = PASS',
            'JPEG_RESULT" = PASS',
            'SHORT_VIDEO_RESULT" = PASS',
        ):
            self.assertIn(required, body)
        script = textwrap.dedent(
            f"""
            P110_SOURCE_ONLY=1 source {RUNNER}
            LIVE_INVOCATIONS=1; CLOUD_NEGOTIATION_COUNT=1; CTPP_OPEN_COUNT=1; SECOND_CTPP_OPEN=false
            P78_RTPC_SIGNALING_RESULT=PASS; P80_DEVICE_ACK_000A_OBSERVED=PASS; P80_DEVICE_ACK_001A_OBSERVED=PASS
            P80_POST_001A_ACK_GATE=PASS; P80_PREACTIVE_MEDIA_DEMUX=PASS; P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS
            P80_MEDIA_ACTIVE=true; P80_VIDEO_RTP_FORWARDING=PASS; P80_AUDIO_RTP_FORWARDING=PASS
            H264_SPS_COUNT=1; H264_PPS_COUNT=1; H264_IDR_COUNT=1; FFPROBE_H264=PASS; JPEG_RESULT=PASS; SHORT_VIDEO_RESULT=PASS
            PACKAGED_BINARY_SHA_BEFORE_RUN=x; PACKAGED_BINARY_SHA_AFTER_RUN=x; PACKAGED_MUSL_PROCESS_REMAINING=NONE
            UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false; TEARDOWN_CONFIDENCE=CONFIRMED; LISTENER_READY_AFTER=PASS
            P110_DOOR_RESULT_COUNT=0; P110_GATE_TOKEN_COUNT=0
            VIDEO_RTP_DATAGRAMS=0; AUDIO_RTP_DATAGRAMS=1
            validate_media_success_contract || true
            echo MEDIA_SUCCESS_CONTRACT_GATE=$MEDIA_SUCCESS_CONTRACT_GATE
            """
        )
        result = drive_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MEDIA_SUCCESS_CONTRACT_GATE=FAIL", result.stdout)

    def test_prelive_gates_precede_listener_action(self) -> None:
        gate = self.runner.index("FAIL_CLOSED_PRELIVE_GATE=PASS")
        listener = self.runner.index('post_control status "$RUN_ROOT/listener-status-before.json" 10')
        self.assertLess(gate, listener)
        for marker in (
            "P110_PR106_OPEN_GATE=FAIL",
            "P110_PR106_HEAD_GATE=FAIL",
            "P110_REMOTE_PR106_HEAD_GATE=FAIL",
            "PACKAGED_BINARY_SHA_GATE=FAIL",
            "MUSL_ABI_GATE=FAIL",
            "BASE_WRAPPER_GATE=FAIL",
            "P110_RUNNER_SHA256_GATE=FAIL",
            "HOLDER_SHIM_SHA_GATE=FAIL",
            "RTP_CAPTURE_SELFTEST=FAIL",
            "MEDIA_POSTPROCESS_SELFTEST=FAIL",
            "P110_SECRETS_MODE_GATE=FAIL",
        ):
            self.assertIn(marker, self.runner)

    def test_no_retry_no_door_gate_secret_leak_and_fail_closed_teardown(self) -> None:
        for forbidden in ("for attempt", "while retry", "until retry", "AUTOMATIC_RETRY=true", "OPEN_DOOR", "open_door"):
            self.assertNotIn(forbidden, self.runner)
            self.assertNotIn(forbidden, self.shim)
        for text in (self.runner, self.shim):
            self.assertNotIn("cat \"$SECRETS_FILE\"", text)
            self.assertNotIn("source $SECRETS_FILE", text)
            self.assertNotIn(". $SECRETS_FILE", text)
            self.assertNotIn("Authorization=", text)
        restore = function_body(self.runner, "restore_listener")
        self.assertLess(restore.index('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]'), restore.index("post_control start"))
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", restore)

    def test_run4_regression_still_documented(self) -> None:
        self.assertIn("P108_MISSING_CLOUD_BOOTSTRAP = \"PROVEN_STATIC\"", self.p109)
        live_invocation = self.p108.split("=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ===", 1)[1]
        live_invocation = live_invocation.split("MEDIA_PID=$!", 1)[0]
        for missing in ("transform_offer", "async_negotiate_p2p", "remote.sdp", "oauth"):
            self.assertNotIn(missing, live_invocation)


if __name__ == "__main__":
    unittest.main()
