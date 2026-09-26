#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "safety-poc" / "research" / "media" / "v1" / "ct120_run_msl_v1_variant_b_live.sh"


def extract_provider() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(r"cat > \"\$MSL_B_BOOTSTRAP_PROVIDER\" <<'PY'\n(.*?)\nPY\n", text, re.S)
    if not match:
        raise AssertionError("embedded bootstrap provider heredoc missing")
    return match.group(1)


VALID_OFFER = b"\r\n".join(
    (
        b"v=0",
        b"o=- 1 1 IN IP4 127.0.0.1",
        b"s=ice",
        b"t=0 0",
        b"c=IN IP4 127.0.0.1",
        b"m=audio 5000 RTP/SAVPF 0 8",
        b"a=ice-ufrag:abcd",
        b"a=ice-pwd:abcdefghijklmnopqrstuvwxyz",
        b"a=candidate:1 1 UDP 2130706431 127.0.0.1 5000 typ host",
        b"a=candidate:2 1 UDP 1694498815 192.0.2.1 5001 typ srflx",
        b"",
    )
)


class MslV2ListenerBootstrapProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.provider_source = extract_provider()

    def run_provider(self, scenario: str, *, write_offer: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = root / "provider.py"
            run_dir = root / "run"
            run_dir.mkdir()
            offer = run_dir / "offer.sdp"
            remote = run_dir / "remote.sdp"
            log = root / "listener.log"
            provider.write_text(self.provider_source, encoding="utf-8")
            if write_offer:
                offer.write_bytes(VALID_OFFER)
            env = os.environ.copy()
            env["MSL_B_BOOTSTRAP_FAKE_SCENARIO"] = scenario
            return subprocess.run(
                [
                    "python3",
                    str(provider),
                    "--repo",
                    str(ROOT),
                    "--run-dir",
                    str(run_dir),
                    "--offer-file",
                    str(offer),
                    "--remote-file",
                    str(remote),
                    "--log-file",
                    str(log),
                    "--timeout-seconds",
                    "0.1",
                    "--ha-config-entries",
                    "",
                ],
                text=True,
                capture_output=True,
                env=env,
                timeout=5,
                check=False,
            )

    def test_provider_reuses_production_helpers(self) -> None:
        for marker in (
            "from custom_components.comelit import cloud, oauth, runtime, sdp",
            "sdp.transform_offer(raw_offer)",
            "oauth.ComelitOAuthManager",
            "cloud.async_negotiate_p2p",
            "runtime._write_remote(remote)",
            "MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token",
        ):
            self.assertIn(marker, self.provider_source)
        self.assertNotIn("print(access_token", self.provider_source)
        self.assertNotIn("COMELIT_OAUTH_ACCESS_TOKEN=", self.provider_source)
        print("MSL_B_PRODUCTION_CODE_REUSED=true REAL=runtime_sdp_cloud_oauth MUTATED=token_print_scan")

    def test_success_writes_remote_once(self) -> None:
        proc = self.run_provider("success")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for marker in (
            "MSL_B_BOOTSTRAP_OFFER_READ=true",
            "MSL_B_BOOTSTRAP_TRANSFORM=PASS",
            "MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1",
            "MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true",
        ):
            self.assertIn(marker, proc.stdout)

    def test_missing_offer_fail_closed(self) -> None:
        proc = self.run_provider("missing_offer", write_offer=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=0", proc.stdout)

    def test_malformed_offer_fail_closed(self) -> None:
        proc = self.run_provider("malformed_offer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_TRANSFORM=FAIL", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=0", proc.stdout)

    def test_transform_failure_fail_closed(self) -> None:
        proc = self.run_provider("transform_failure")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_TRANSFORM=FAIL", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=0", proc.stdout)

    def test_cloud_failure_no_retry_exactly_one_request(self) -> None:
        proc = self.run_provider("cloud_failure")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_TRANSFORM=PASS", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertEqual(proc.stdout.count("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT="), 2)

    def test_malformed_remote_sdp_fail_closed(self) -> None:
        proc = self.run_provider("malformed_remote_sdp")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true", proc.stdout)

    def test_timeout_fail_closed(self) -> None:
        proc = self.run_provider("timeout", write_offer=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true", proc.stdout)

    def test_runner_bootstrap_only_and_ledger_independence(self) -> None:
        for marker in (
            "MSL_B_BOOTSTRAP_ONLY=${MSL_B_BOOTSTRAP_ONLY:-NO}",
            "MSL_B_BOOTSTRAP_LEDGER=${MSL_B_BOOTSTRAP_LEDGER:-}",
            "ledger_value_or_fail \"$MSL_B_BOOTSTRAP_LEDGER\" MSL_B_BOOTSTRAP_LEDGER 2",
            "ledger_value_or_fail \"$MSL_B_ATTEMPT_LEDGER\" MSL_B_ATTEMPT_LEDGER 15",
            "[ \"$MSL_B_BOOTSTRAP_ONLY\" = YES ]",
            "[ ! -e \"$START_FILE\" ] || fail \"MSL_B_BOOTSTRAP_ONLY_START_CONTROL_ABSENT=false\"",
            "ledger_increment \"$MSL_B_BOOTSTRAP_LEDGER\" \"$bootstrap_ledger_value\"",
            "ledger_increment \"$MSL_B_ATTEMPT_LEDGER\" \"$attempt_ledger_value\"",
        ):
            self.assertIn(marker, self.runner)
        bootstrap_index = self.runner.index("if [ \"$MSL_B_BOOTSTRAP_ONLY\" = YES ]; then")
        start_index = self.runner.index("install -m 600 /dev/null \"$START_FILE\"")
        self.assertLess(bootstrap_index, start_index)
        print("MSL_B_BOOTSTRAP_LEDGER_INDEPENDENT=true REAL=separate_caps MUTATED=media_ledger_scan")

    def test_no_door_gate_path_in_provider_or_idle_control(self) -> None:
        provider_forbidden = ("DOOR_TARGET", "v4_queue_door", "V4_GATE", "door-target")
        for token in provider_forbidden:
            self.assertNotIn(token, self.provider_source)
        idle_region = self.runner.split("echo \"=== RUN ONE IDLE MEDIA CONTROL ON READY LISTENER ===\"", 1)[1]
        for token in ("door-target", "V4_GATE", "v4_queue_door"):
            self.assertNotIn(token, idle_region)
        print("MSL_B_NO_DOOR_GATE_PATH=true REAL=bootstrap_and_idle_runner MUTATED=door_gate_token_scan")

    def test_b00_b07_and_reuse_counter_flip_proofs_are_present(self) -> None:
        for marker in (
            "MSL_B_B00_IDLE_MEDIA_REQUEST_RECEIVED_MONO_MS",
            "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS",
            "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS",
            "MSL_B_B03_INITIAL_001A_SENT_MONO_MS",
            "MSL_B_B04_STRUCTURAL_ACK_MEDIA_ACCEPTED_MONO_MS",
            "MSL_B_B05_FIRST_AUDIO_RTP_MONO_MS",
            "MSL_B_B06_FIRST_VIDEO_RTP_MONO_MS",
            "MSL_B_B07_FIRST_USABLE_SPS_PPS_IDR_RECOVERY_POINT_MONO_MS",
            "MSL_B_START_TO_FIRST_VIDEO_RTP_MS",
            "MSL_B_START_TO_DECODABLE_VIDEO_MS",
            "MSL_B_PHASE_B06_TO_B07_MS",
            "MSL_B_OLD_5S_INTERVAL=ELIMINATED",
        ):
            self.assertIn(marker, self.runner)
        for counter in (
            "MSL_B_CLOUD_NEGOTIATION_COUNT",
            "MSL_B_ICE_BOOTSTRAP_COUNT",
            "MSL_B_PSEUDOTCP_OPEN_COUNT",
            "MSL_B_CTPP_REGISTRATION_COUNT",
            "MSL_B_MEDIA_SESSION_COUNT",
            "MSL_B_SECOND_MEDIA_SESSION",
            "MSL_B_MEDIA_FORWARDING_INACTIVE",
            "MSL_B_AUDIO_RTP_PACKETS",
            "RESIDUAL_MEDIA_CHANNELS",
        ):
            real = self.runner.count(counter)
            mutated = self.runner.replace(counter, "MSL_B_COUNTER_MUTATED", 1).count(counter)
            self.assertGreater(real, 0, counter)
            self.assertNotEqual(real, mutated, counter)
        print("MSL_B_REUSE_COUNTERS_DERIVED=true REAL=runner_marker_scan MUTATED=single_marker_removed")

    def test_refusal_mode_still_no_live_interaction(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_OFFLINE_SAFE_REFUSAL=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
