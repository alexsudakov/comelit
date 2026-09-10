#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p108_exact_packaged_musl_validation.sh"
PACKAGED = REPO_ROOT / "custom_components" / "comelit" / "native" / "comelit-media"

EXPECTED_SHA = "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"
EXPECTED_HEAD = "977f7197f103050a9f52b43dad26af5df0c7bbf0"

REQUIRED_SUMMARY_KEYS = [
    "P108_LIVE_RUN",
    "P108_HYPOTHESIS_ID",
    "P108_BRANCH_HEAD",
    "P108_REPO_HEAD",
    "PACKAGED_BINARY_REBUILT",
    "PACKAGED_BINARY_PATH",
    "PACKAGED_BINARY_SHA_BEFORE_RUN",
    "PACKAGED_BINARY_SHA_AFTER_RUN",
    "RUNTIME_ABI_GATE",
    "RUNTIME_LOADER",
    "RUNTIME_LIBRARY_PATH",
    "RUNTIME_ROOT",
    "STAGED_COPY_BYTE_IDENTICAL",
    "EXECUTABLE_MEDIA_PATH",
    "P108_LIVE_INVOCATION_LIMIT",
    "P108_LIVE_INVOCATIONS",
    "P108_MEDIA_RC",
    "P2_HOLDER_TERMINAL_RC",
    "P2_HOLDER_TERMINAL_RESULT",
    "P108_OBSERVATION_SECONDS",
    "LISTENER_READY_BEFORE",
    "LISTENER_STOP_GATE",
    "LISTENER_RESTORE_READY",
    "LISTENER_READY_AFTER",
    "LISTENER_RESTART_SUPPRESSED",
    "TEARDOWN_CONFIDENCE",
    "PACKAGED_MUSL_PROCESS_REMAINING",
    "UPSTREAM_MEDIA_ACTIVE_AT_EXIT",
    "P108_DOOR_RESULT_COUNT",
    "P108_GATE_TOKEN_COUNT",
    "P78_RTPC_SIGNALING_RESULT",
    "P80_DEVICE_ACK_000A_OBSERVED",
    "P80_DEVICE_ACK_001A_OBSERVED",
    "P80_POST_001A_ACK_GATE",
    "P80_PREACTIVE_MEDIA_DEMUX",
    "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT",
    "P80_MEDIA_ACTIVE",
    "P80_VIDEO_RTP_FORWARDING",
    "P80_AUDIO_RTP_FORWARDING",
    "PSEUDOTCP_NOTIFY_PACKET_CLASS",
    "PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED",
    "PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED",
    "PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE",
    "P108_H264_SPS_COUNT",
    "P108_H264_PPS_COUNT",
    "P108_H264_IDR_COUNT",
    "P108_VIDEO_RTP_DATAGRAMS",
    "P108_AUDIO_RTP_DATAGRAMS",
    "P108_FFPROBE_H264",
    "P108_JPEG_RESULT",
    "P108_JPEG_PATH",
    "P108_JPEG_SHA256",
    "P108_SHORT_VIDEO_RESULT",
    "P108_SHORT_VIDEO_PATH",
    "P108_SHORT_VIDEO_DURATION_SEC",
    "P108_SHORT_VIDEO_SHA256",
    "DOOR_ACTION_SENT",
    "GATE_ACTION_SENT",
    "AUTOMATIC_RETRY",
    "HOME_ASSISTANT_CORE_STOPPED",
    "HOME_ASSISTANT_CORE_RESTARTED",
    "SECRETS_CONTENT_EMITTED",
]


def function_body(text: str, name: str) -> str:
    return text.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]


def drive_script(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", body],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


class P108Run4ExactPackagedMuslContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_runner_is_executable_and_bash_syntax_clean(self) -> None:
        self.assertTrue(os.stat(RUNNER).st_mode & 0o111)
        result = subprocess.run(
            ["bash", "-n", str(RUNNER)],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pins_expected_packaged_identity_and_pr_head(self) -> None:
        self.assertIn(f"PACKAGED_BINARY_SHA256={EXPECTED_SHA}", self.text)
        self.assertIn(f"EXPECTED_PR_HEAD={EXPECTED_HEAD}", self.text)
        self.assertIn("PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media", self.text)
        self.assertIn("PACKAGED_BINARY_BYTES=256992", self.text)
        self.assertIn("PACKAGED_BINARY_REBUILT=false", self.text)
        self.assertEqual(hashlib.sha256(PACKAGED.read_bytes()).hexdigest(), EXPECTED_SHA)

    def test_sha_mismatch_refusal_uses_real_runner_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            binary = repo / "custom_components" / "comelit" / "native" / "comelit-media"
            libdir = binary.parent / "lib"
            libdir.mkdir(parents=True)
            binary.write_bytes(b"wrong packaged binary\n")
            script = textwrap.dedent(
                f"""
                P108_SOURCE_ONLY=1 source {RUNNER}
                FAIL=0
                assert_packaged_binary_identity {repo}
                echo FAIL=$FAIL
                """
            )
            result = drive_script(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PACKAGED_BINARY_SHA_GATE=FAIL", result.stdout)
            self.assertIn("FAIL=1", result.stdout)

    def test_runtime_boundary_detection_uses_shipped_libs_and_fails_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            libdir = repo / "custom_components" / "comelit" / "native" / "lib"
            libdir.mkdir(parents=True)
            for name in ("libnice.so.10", "libglib-2.0.so.0", "libgobject-2.0.so.0"):
                (libdir / name).write_text(name, encoding="utf-8")
            root = Path(tmp) / "alpine-root"
            (root / "etc").mkdir(parents=True)
            (root / "lib").mkdir()
            (root / "usr" / "lib").mkdir(parents=True)
            (root / "etc" / "alpine-release").write_text("3.24.1\n", encoding="utf-8")
            loader = root / "lib" / "ld-musl-x86_64.so.1"
            loader.write_text("#!/bin/sh\n", encoding="utf-8")
            loader.chmod(0o755)
            positive = drive_script(
                textwrap.dedent(
                    f"""
                    P108_SOURCE_ONLY=1 source {RUNNER}
                    P108_TEST_RUNTIME_ROOT={root}
                    detect_runtime_boundary {repo}
                    """
                )
            )
            self.assertEqual(positive.returncode, 0, positive.stderr)
            self.assertIn("RUNTIME_ABI_GATE=PASS", positive.stdout)
            self.assertIn(f"RUNTIME_LOADER={loader}", positive.stdout)
            self.assertIn(str(libdir), positive.stdout)

            missing_libs_repo = Path(tmp) / "missing-libs"
            negative = drive_script(
                textwrap.dedent(
                    f"""
                    P108_SOURCE_ONLY=1 source {RUNNER}
                    P108_TEST_RUNTIME_ROOT={root}
                    detect_runtime_boundary {missing_libs_repo}
                    """
                )
            )
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("P108_RUNTIME_ABI_GATE=FAIL", negative.stdout)

    def test_listener_actions_are_after_runtime_gate(self) -> None:
        detect = self.text.index('detect_runtime_boundary "$REPO"')
        gate = self.text.index('[ "$RUNTIME_ABI_GATE" = PASS ] || fail "P108_RUNTIME_ABI_GATE=FAIL"')
        first_listener = self.text.index('post_control status "$STATUS_BEFORE" 10')
        self.assertLess(detect, gate)
        self.assertLess(gate, first_listener)

    def test_invocation_limit_bounds_and_no_retry_are_encoded(self) -> None:
        self.assertIn("P108_LIVE_INVOCATION_LIMIT=1", self.text)
        self.assertIn("LIVE_WINDOW_SECONDS=40", self.text)
        self.assertIn("OUTER_TIMEOUT_SECONDS=75", self.text)
        self.assertIn("MEDIA_SESSION_TIMEOUT_SECONDS=45", self.text)
        self.assertIn('"$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS"', self.text)
        self.assertEqual(re.findall(r"^LIVE_INVOCATIONS=1$", self.text, re.MULTILINE), ["LIVE_INVOCATIONS=1"])
        self.assertEqual(self.text.count("=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ==="), 1)
        self.assertEqual(self.text.count('"$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH"'), 1)
        for forbidden in ("for attempt", "while retry", "until retry", "AUTOMATIC_RETRY=true"):
            self.assertNotIn(forbidden, self.text)

    def test_no_rebuild_transform_broad_kill_or_secret_printing(self) -> None:
        for forbidden in (
            "git fetch",
            "git checkout",
            "pkg-config",
            "TRANSFORM_RC",
            "P105_TRANSFORM",
            "P105_BUILD",
            "killall",
            "pkill",
            "cat $SECRETS_FILE",
            "source $SECRETS_FILE",
            ". $SECRETS_FILE",
        ):
            self.assertNotIn(forbidden, self.text)
        self.assertNotRegex(self.text, r"(^|\n)\s*(cc|gcc)\s+-")
        self.assertIn("SECRETS_CONTENT_EMITTED=false", self.text)

    def test_door_and_gate_paths_are_unreachable_and_counter_gated(self) -> None:
        live_invocation = self.text.split("=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ===", 1)[1]
        live_invocation = live_invocation.split("MEDIA_PID=$!", 1)[0]
        for forbidden in ("--door", "--gate", "OPEN_DOOR", "open_door", "create_door_message"):
            self.assertNotIn(forbidden, live_invocation)
        for forbidden in ("OPEN_DOOR", "open_door", "create_door_message"):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("P108_DOOR_RESULT_COUNT", self.text)
        self.assertIn("P108_GATE_TOKEN_COUNT", self.text)
        self.assertIn('[ "$P108_DOOR_RESULT_COUNT" -eq 0 ] || fail "P108_DOOR_RESULT_GATE=FAIL"', self.text)
        self.assertIn('[ "$P108_GATE_TOKEN_COUNT" -eq 0 ] || fail "P108_GATE_TOKEN_GATE=FAIL"', self.text)
        self.assertIn("P108_EXTERNAL_DOOR_SIGNAL_GATE=PASS", self.text)
        self.assertIn("GATE_ACTION_SENT=false", self.text)

    def test_restore_listener_only_after_confirmed_teardown(self) -> None:
        restore_body = function_body(self.text, "restore_listener")
        self.assertIn('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]', restore_body)
        self.assertLess(
            restore_body.index('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]'),
            restore_body.index("post_control start"),
        )
        live_tail = self.text.rsplit("derive_teardown_confidence", 1)[1]
        self.assertIn('if [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then', live_tail)
        self.assertLess(live_tail.index("restore_listener"), live_tail.index("postprocess_media"))

    def test_restore_gate_behaviour_uses_real_runner_function(self) -> None:
        script = textwrap.dedent(
            f"""
            P108_SOURCE_ONLY=1 source {RUNNER}
            post_control() {{ echo SHOULD_NOT_START; return 0; }}
            LISTENER_STOPPED=1
            TEARDOWN_CONFIDENCE=UNCERTAIN
            RUN_ROOT=/tmp/p108-test
            restore_listener
            echo rc=$?
            """
        )
        result = drive_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", result.stdout)
        self.assertIn("LISTENER_RESTORE_FINAL_GATE=FAIL", result.stdout)
        self.assertIn("rc=90", result.stdout)
        self.assertNotIn("SHOULD_NOT_START", result.stdout)

    def test_open_and_door_accounting_drive_extracted_runner_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "live.log"
            log.write_text(
                "\n".join(
                    [
                        "P78_RTPC_OPEN_1_SENT=PASS",
                        "P78_RTPC_OPEN_2_SENT=PASS",
                        "V4_CTPP_OPEN_SENT=PASS",
                        "V4_DOOR_RESULT=FAIL",
                        "GATE_ACTION_SENT=true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            script = textwrap.dedent(
                f"""
                P108_SOURCE_ONLY=1 source {RUNNER}
                LOG={log}
                collect_log_markers
                echo CTPP_OPEN_COUNT=$CTPP_OPEN_COUNT
                echo SECOND_CTPP_OPEN=$SECOND_CTPP_OPEN
                echo RTPC_OPEN_TOTAL_COUNT=$RTPC_OPEN_TOTAL_COUNT
                echo P108_DOOR_RESULT_COUNT=$P108_DOOR_RESULT_COUNT
                echo P108_GATE_TOKEN_COUNT=$P108_GATE_TOKEN_COUNT
                """
            )
            result = drive_script(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            self.assertEqual(values["CTPP_OPEN_COUNT"], "1")
            self.assertEqual(values["SECOND_CTPP_OPEN"], "false")
            self.assertEqual(values["RTPC_OPEN_TOTAL_COUNT"], "2")
            self.assertEqual(values["P108_DOOR_RESULT_COUNT"], "1")
            self.assertEqual(values["P108_GATE_TOKEN_COUNT"], "1")

    def test_marker_contract_complete(self) -> None:
        block = self.text.split('echo "=== COMELIT P108 RUN4 EXACT PACKAGED MUSL SUMMARY ==="', 1)[1]
        block = block.split('echo "=== END COMELIT P108 RUN4 EXACT PACKAGED MUSL SUMMARY ==="', 1)[0]
        keys = re.findall(r'echo "([A-Z0-9_]+)=', block)
        for key in REQUIRED_SUMMARY_KEYS:
            self.assertIn(key, keys)

    def test_p106_terminal_classification_is_report_only(self) -> None:
        collect_body = function_body(self.text, "collect_log_markers")
        derive_body = function_body(self.text, "derive_teardown_confidence")
        self.assertIn('PSEUDOTCP_NOTIFY_PACKET_CLASS="$(last_marker PSEUDOTCP_NOTIFY_PACKET_CLASS NOT_OBSERVED)"', collect_body)
        self.assertIn('PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED="$(last_marker PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED NOT_OBSERVED)"', collect_body)
        self.assertIn('PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE="$(last_marker PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE NOT_OBSERVED)"', collect_body)
        self.assertNotIn("PSEUDOTCP_NOTIFY_PACKET_CLASS", derive_body)
        self.assertNotIn("LEN=24", self.text)
        self.assertNotIn("PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN", derive_body)

    def test_packaged_binary_invocation_uses_loader_library_path_and_exact_file(self) -> None:
        self.assertIn("EXECUTABLE_MEDIA_PATH=\"$PACKAGED_BINARY\"", self.text)
        self.assertIn('"$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH"', self.text)
        self.assertIn("STAGED_COPY_BYTE_IDENTICAL=false", self.text)
        self.assertNotIn("cp \"$PACKAGED_BINARY\"", self.text)
        self.assertNotIn("cp $PACKAGED_BINARY", self.text)


if __name__ == "__main__":
    unittest.main()
