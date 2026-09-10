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
BOOTSTRAP = ROOT / "research" / "media" / "v1" / "p110_run5_bootstrap.py"
P105_RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p105_entrance_media_live.sh"
P108_RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p108_exact_packaged_musl_validation.sh"
P109_HARNESS = ROOT / "research" / "media" / "v1" / "p109_corrected_live_orchestration.py"
V42_WRAPPER = ROOT / "research" / "ring" / "v4_2" / "comelit-p2p-cloud-probe-v4-long-window"
PROD_TRANSPORT = REPO_ROOT / "custom_components" / "comelit" / "media_transport.py"
PROD_CLOUD = REPO_ROOT / "custom_components" / "comelit" / "cloud.py"
PROD_SDP = REPO_ROOT / "custom_components" / "comelit" / "sdp.py"
PROD_OAUTH = REPO_ROOT / "custom_components" / "comelit" / "oauth.py"
PACKAGED = REPO_ROOT / "custom_components" / "comelit" / "native" / "comelit-media"

EXPECTED_HEAD = "977f7197f103050a9f52b43dad26af5df0c7bbf0"
EXPECTED_SHA = "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"


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


class P110FinalRun5RunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        cls.p105 = P105_RUNNER.read_text(encoding="utf-8")
        cls.p108 = P108_RUNNER.read_text(encoding="utf-8")
        cls.p109 = P109_HARNESS.read_text(encoding="utf-8")
        cls.v42 = V42_WRAPPER.read_text(encoding="utf-8")
        cls.transport = PROD_TRANSPORT.read_text(encoding="utf-8")
        cls.cloud = PROD_CLOUD.read_text(encoding="utf-8")
        cls.sdp = PROD_SDP.read_text(encoding="utf-8")
        cls.oauth = PROD_OAUTH.read_text(encoding="utf-8")

    def test_runner_and_bootstrap_are_executable_and_syntax_clean(self) -> None:
        self.assertTrue(os.stat(RUNNER).st_mode & 0o111)
        self.assertTrue(os.stat(BOOTSTRAP).st_mode & 0o111)
        bash = subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
        self.assertEqual(bash.returncode, 0, bash.stderr)
        py = subprocess.run(["python3", "-m", "py_compile", str(BOOTSTRAP)], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
        self.assertEqual(py.returncode, 0, py.stderr)

    def test_reconstructs_run1_run3_wrapper_holder_bootstrap_path(self) -> None:
        self.assertIn("BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe", self.p105)
        self.assertIn("timeout --signal=TERM --kill-after=5s", self.p105)
        self.assertIn('"$BASE_WRAPPER"', self.p105)
        self.assertLess(self.v42.index('"$RUN/offer.sdp"'), self.v42.index("comelit_sdp.py"))
        self.assertLess(self.v42.index("comelit_sdp.py"), self.v42.index("comelit_cloud_probe.py"))
        self.assertLess(self.v42.index("comelit_cloud_probe.py"), self.v42.index('"$RUN/remote.sdp"'))
        self.assertEqual(self.v42.count("comelit_cloud_probe.py"), 1)
        self.assertIn("wait \"$HOLDER_PID\"", self.v42)

    def test_production_equivalence_is_protocol_level_and_uses_production_modules(self) -> None:
        self.assertIn('ENDPOINT = "https://api.comelitgroup.com/servicerest/p2p/start"', self.cloud)
        self.assertIn('TOKEN_ENDPOINT = "https://api.comelitgroup.com/o-auth-2/token"', self.oauth)
        self.assertIn("def transform_offer(raw_sdp: bytes) -> bytes:", self.sdp)
        self.assertIn("_load_module(\"p110_prod_sdp\", \"custom_components/comelit/sdp.py\")", self.bootstrap)
        self.assertIn("_load_module(\"p110_prod_cloud\", \"custom_components/comelit/cloud.py\")", self.bootstrap)
        self.assertIn("oauth.async_refresh_oauth(", self.bootstrap)
        self.assertIn("cloud.async_negotiate_p2p(", self.bootstrap)
        self.assertIn("sdp.transform_offer(raw_offer)", self.bootstrap)
        self.assertLess(self.transport.index("transform_offer(raw_offer)"), self.transport.index("async_negotiate_p2p("))
        self.assertLess(self.bootstrap.index("sdp.transform_offer(raw_offer)"), self.bootstrap.index("cloud.async_negotiate_p2p("))

    def test_packaged_binary_identity_and_abi_are_pinned(self) -> None:
        self.assertIn(f"EXPECTED_PR106_HEAD={EXPECTED_HEAD}", self.runner)
        self.assertIn(f"PACKAGED_BINARY_SHA256={EXPECTED_SHA}", self.runner)
        self.assertIn("PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media", self.runner)
        self.assertIn("PACKAGED_BINARY_REBUILT=false", self.runner)
        self.assertIn("PACKAGED_BINARY_SUBSTITUTED=false", self.runner)
        self.assertIn("EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1", self.runner)
        self.assertIn("EXPECTED_NEEDED_CSV=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10", self.runner)
        self.assertEqual(hashlib.sha256(PACKAGED.read_bytes()).hexdigest(), EXPECTED_SHA)

    def test_prelive_gates_precede_listener_action_and_include_pr_open_confirmation(self) -> None:
        gate = self.runner.index("FAIL_CLOSED_PRELIVE_GATE=PASS")
        first_listener = self.runner.index('post_control status "$RUN_ROOT/listener-status-before.json" 10')
        self.assertLess(gate, first_listener)
        for marker in (
            "P110_PR106_OPEN_GATE=FAIL",
            "P110_PR106_HEAD_GATE=FAIL",
            "P110_REMOTE_PR106_HEAD_GATE=FAIL",
            "PACKAGED_BINARY_SHA_GATE=FAIL",
            "P110_ELF_INTERPRETER_GATE=FAIL",
            "P110_ELF_NEEDED_GATE=FAIL",
            "P110_BOOTSTRAP_STATIC_SELF_TEST=FAIL",
            "P110_RUNNER_SHA256_GATE=FAIL",
            "P110_SECRETS_MODE_GATE=FAIL",
            "P110_CREDENTIAL_ORIGIN_GATE=FAIL",
        ):
            self.assertIn(marker, self.runner)

    def test_runtime_boundary_detection_uses_p80_musl_root_and_packaged_libs(self) -> None:
        self.assertIn("/root/comelit-p80-haos-build-*/rootfs", self.runner)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            libdir = repo / "custom_components" / "comelit" / "native" / "lib"
            libdir.mkdir(parents=True)
            for name in ("libnice.so.10", "libglib-2.0.so.0", "libgobject-2.0.so.0"):
                (libdir / name).write_text(name, encoding="utf-8")
            root = Path(tmp) / "rootfs"
            (root / "etc").mkdir(parents=True)
            (root / "lib").mkdir()
            (root / "usr" / "lib").mkdir(parents=True)
            (root / "etc" / "alpine-release").write_text("3.24.1\n", encoding="utf-8")
            loader = root / "lib" / "ld-musl-x86_64.so.1"
            loader.write_text("#!/bin/sh\n", encoding="utf-8")
            loader.chmod(0o755)
            result = drive_script(
                textwrap.dedent(
                    f"""
                    P110_SOURCE_ONLY=1 source {RUNNER}
                    P110_TEST_RUNTIME_ROOT={root}
                    detect_runtime_boundary {repo}
                    echo RUNTIME_ABI_GATE=$RUNTIME_ABI_GATE
                    echo RUNTIME_LOADER=$RUNTIME_LOADER
                    """
                )
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RUNTIME_ABI_GATE=PASS", result.stdout)
            self.assertIn(f"RUNTIME_LOADER={loader}", result.stdout)

    def test_single_invocation_single_cloud_negotiation_and_no_retry(self) -> None:
        self.assertEqual(re.findall(r"^LIVE_INVOCATIONS=1$", self.runner, re.MULTILINE), ["LIVE_INVOCATIONS=1"])
        self.assertEqual(self.runner.count("=== EXACTLY ONE P110 PACKAGED MUSL LIVE INVOCATION ==="), 1)
        self.assertEqual(self.runner.count("cloud.async_negotiate_p2p("), 0)
        self.assertEqual(self.bootstrap.count("cloud.async_negotiate_p2p("), 1)
        self.assertEqual(self.bootstrap.count("cloud_call_count += 1"), 1)
        for forbidden in ("for attempt", "while retry", "until retry", "AUTOMATIC_RETRY=true", "force_refresh=True"):
            self.assertNotIn(forbidden, self.runner)
            self.assertNotIn(forbidden, self.bootstrap)

    def test_run4_missing_bootstrap_regression_is_explicit(self) -> None:
        self.assertIn("P108_MISSING_CLOUD_BOOTSTRAP = \"PROVEN_STATIC\"", self.p109)
        live_invocation = self.p108.split("=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ===", 1)[1]
        live_invocation = live_invocation.split("MEDIA_PID=$!", 1)[0]
        for missing in ("transform_offer", "async_negotiate_p2p", "remote.sdp", "oauth"):
            self.assertNotIn(missing, live_invocation)
        self.assertIn("[ -s \"$RUN_DIR/offer.sdp\" ] || fail \"P110_OFFER_READY_GATE=FAIL\"", self.runner)
        self.assertIn("P110_CLOUD_BOOTSTRAP_GATE=FAIL", self.runner)
        self.assertIn("[ ! -s \"$RUN_DIR/remote.sdp\" ]", self.runner)

    def test_media_success_contract_rejects_clean_rc_without_required_media_markers(self) -> None:
        body = function_body(self.runner, "validate_media_success_contract")
        for required in (
            'P78_RTPC_SIGNALING_RESULT" = PASS',
            'P80_DEVICE_ACK_000A_OBSERVED" = PASS',
            'P80_DEVICE_ACK_001A_OBSERVED" = PASS',
            'P80_POST_001A_ACK_GATE" = PASS',
            'P80_PREACTIVE_MEDIA_DEMUX" = PASS',
            'P80_PREACTIVE_MEDIA_PROFILE_ACCEPT" = PASS',
            'P80_MEDIA_ACTIVE" = true',
            'P80_VIDEO_RTP_FORWARDING" = PASS',
            'P80_AUDIO_RTP_FORWARDING" = PASS',
            'H264_SPS_COUNT" -gt 0',
            'H264_PPS_COUNT" -gt 0',
            'H264_IDR_COUNT" -gt 0',
            'FFPROBE_H264" = PASS',
            'JPEG_RESULT" = PASS',
            'SHORT_VIDEO_RESULT" = PASS',
        ):
            self.assertIn(required, body)
        self.assertNotIn('MEDIA_RC" = 0', body)

    def test_door_gate_absence_and_teardown_fail_closed(self) -> None:
        self.assertIn("DOOR_ACTION_SENT=false", self.runner)
        self.assertIn("GATE_ACTION_SENT=false", self.runner)
        self.assertIn("[ \"$P110_DOOR_RESULT_COUNT\" -eq 0 ] || fail \"P110_DOOR_RESULT_GATE=FAIL\"", self.runner)
        self.assertIn("[ \"$P110_GATE_TOKEN_COUNT\" -eq 0 ] || fail \"P110_GATE_TOKEN_GATE=FAIL\"", self.runner)
        restore = function_body(self.runner, "restore_listener")
        self.assertLess(restore.index('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]'), restore.index("post_control start"))
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", restore)

    def test_secret_leakage_is_guarded(self) -> None:
        self.assertIn("_assert_no_secret_output(output, env)", self.bootstrap)
        self.assertIn("P110_SECRET_OUTPUT_GATE=PASS", self.bootstrap)
        for text in (self.runner, self.bootstrap):
            self.assertNotIn("cat \"$SECRETS_FILE\"", text)
            self.assertNotIn("source $SECRETS_FILE", text)
            self.assertNotIn(". $SECRETS_FILE", text)
            self.assertNotIn("Authorization=", text)

    def test_bootstrap_self_test_is_offline(self) -> None:
        result = subprocess.run([str(BOOTSTRAP), "--self-test"], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P110_BOOTSTRAP_STATIC_SELF_TEST=PASS", result.stdout)
        self.assertIn("NETWORK_IO_PERFORMED=false", result.stdout)

    def test_no_compile_checkout_fetch_or_packaged_binary_copy(self) -> None:
        for forbidden in ("git fetch", "git checkout", "pkg-config", "gcc ", "cc ", "cp \"$PACKAGED_BINARY\"", "LIVE_INVOCATIONS=2"):
            self.assertNotIn(forbidden, self.runner)
        self.assertIn("stat -c '%a' \"$SECRETS_FILE\"", self.runner)
        self.assertIn("stat", self.runner.split("for command in", 1)[1].split("; do", 1)[0])


if __name__ == "__main__":
    unittest.main()
