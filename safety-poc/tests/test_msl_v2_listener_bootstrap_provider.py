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


def extract_old_5s_interval_functions() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(
        r"(msl_b_marker_value\(\) \{.*?^\})\n\n(msl_b_derive_old_5s_interval\(\) \{.*?^\})\n\nprint_final_block",
        text,
        re.S | re.M,
    )
    if not match:
        raise AssertionError("msl_b_derive_old_5s_interval function block missing")
    return match.group(1) + "\n\n" + match.group(2)


def extract_bootstrap_cap_sources() -> tuple[str, str, str]:
    text = RUNNER.read_text(encoding="utf-8")
    functions = []
    for name in ("fail", "ledger_value_or_fail", "bootstrap_max_or_fail"):
        match = re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.S | re.M)
        if not match:
            raise AssertionError(f"{name} function missing")
        functions.append(match.group(0))
    default_match = re.search(r"^MSL_B_BOOTSTRAP_MAX=\$\{MSL_B_BOOTSTRAP_MAX-2\}$", text, re.M)
    if not default_match:
        raise AssertionError("MSL_B_BOOTSTRAP_MAX default assignment missing or widened")
    gate_match = re.search(
        r'if \[ "\$MSL_B_LIVE_RUN" = YES \] && \[ "\$MSL_B_BOOTSTRAP_ONLY" = YES \] '
        r'&& \[ -n "\$MSL_B_BOOTSTRAP_LEDGER" \]; then\n.*?\nfi\n',
        text,
        re.S,
    )
    if not gate_match:
        raise AssertionError("bootstrap cap gate block missing")
    return "\n\n".join(functions), default_match.group(0), gate_match.group(0)


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

    def run_provider(
        self,
        scenario: str,
        *,
        write_offer: bool = True,
        config_source: Path | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
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
            args = [
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
                "--config-source",
                str(config_source) if config_source is not None else str(root / "absent-secrets.env"),
            ]
            args.extend(extra_args)
            return subprocess.run(
                args,
                text=True,
                capture_output=True,
                env=env,
                timeout=5,
                check=False,
            )

    def test_provider_reuses_production_helpers(self) -> None:
        for marker in (
            '_load_module("custom_components.comelit.const"',
            '_load_module("custom_components.comelit.sdp"',
            '_load_module("custom_components.comelit.cloud"',
            '_load_module("custom_components.comelit.oauth"',
            "sdp.transform_offer(raw_offer)",
            "oauth.ComelitOAuthManager",
            "cloud.async_negotiate_p2p",
            "runtime._write_remote(remote)",
            "MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token",
        ):
            self.assertIn(marker, self.provider_source)
        self.assertNotIn("print(access_token", self.provider_source)
        self.assertNotIn("COMELIT_OAUTH_ACCESS_TOKEN=", self.provider_source)
        print("MSL_B_PRODUCTION_CODE_REUSED=true REAL=sdp_cloud_oauth_files_loaded_by_real_path MUTATED=token_print_scan")

    def test_provider_loads_real_files_not_stub_replicas(self) -> None:
        for real_path_fragment in (
            'component_dir / "const.py"',
            'component_dir / "sdp.py"',
            'component_dir / "cloud.py"',
            'component_dir / "oauth.py"',
        ):
            self.assertIn(real_path_fragment, self.provider_source)
        mutated = self.provider_source.replace('component_dir / "oauth.py"', 'component_dir / "OTHER.py"', 1)
        self.assertNotIn('component_dir / "oauth.py"', mutated)
        print("MSL_B_REAL_FILES_LOADED=true REAL=component_dir_oauth.py MUTATED=OTHER.py")

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

    def test_config_source_marker_always_reported(self) -> None:
        proc = self.run_provider("success")
        self.assertIn("MSL_B_BOOTSTRAP_CONFIG_SOURCE=ct120_secrets_env", proc.stdout)

    def test_missing_secrets_file_fails_closed_not_traceback(self) -> None:
        proc = self.run_provider("secrets_env_success", write_offer=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_CONFIG_SOURCE=ct120_secrets_env", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CONFIG_MISSING=secrets_file", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ConfigMissingError", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=0", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_single_credential_field_fails_closed_with_field_name(self) -> None:
        with tempfile.TemporaryDirectory() as secrets_dir:
            secrets_file = Path(secrets_dir) / "secrets.env"
            secrets_file.write_text(
                "COMELIT_DUUID=deadbeef-test-uuid\n"
                "COMELIT_VIP_TOKEN=0123456789abcdef0123456789abcdef\n",
                encoding="utf-8",
            )
            proc = self.run_provider("secrets_env_success", write_offer=False, config_source=secrets_file)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_BOOTSTRAP_CONFIG_MISSING=oauth_access_token", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ConfigMissingError", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_secrets_env_success_end_to_end_emits_markers_without_token_leak(self) -> None:
        secret_device_uuid = "deadbeef-secret-device-uuid"
        secret_vip_token = "0123456789abcdef0123456789abcdef"
        secret_access_token = "SUPER-SECRET-ACCESS-TOKEN-VALUE-MUST-NEVER-BE-PRINTED"
        with tempfile.TemporaryDirectory() as secrets_dir:
            secrets_file = Path(secrets_dir) / "secrets.env"
            secrets_file.write_text(
                f"COMELIT_DUUID={secret_device_uuid}\n"
                f"COMELIT_VIP_TOKEN={secret_vip_token}\n"
                f"COMELIT_OAUTH_ACCESS_TOKEN={secret_access_token}\n",
                encoding="utf-8",
            )
            proc = self.run_provider("secrets_env_success", write_offer=False, config_source=secrets_file)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for marker in (
            "MSL_B_BOOTSTRAP_CONFIG_SOURCE=ct120_secrets_env",
            "MSL_B_BOOTSTRAP_OFFER_READ=true",
            "MSL_B_BOOTSTRAP_TRANSFORM=PASS",
            "MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token",
            "MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1",
            "MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true",
        ):
            self.assertIn(marker, proc.stdout)
        for secret in (secret_device_uuid, secret_vip_token, secret_access_token):
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn(secret, proc.stderr)

    def test_runner_bootstrap_only_and_ledger_independence(self) -> None:
        for marker in (
            "MSL_B_BOOTSTRAP_ONLY=${MSL_B_BOOTSTRAP_ONLY:-NO}",
            "MSL_B_BOOTSTRAP_LEDGER=${MSL_B_BOOTSTRAP_LEDGER:-}",
            "MSL_B_BOOTSTRAP_MAX=${MSL_B_BOOTSTRAP_MAX-2}",
            "ledger_value_or_fail \"$MSL_B_BOOTSTRAP_LEDGER\" MSL_B_BOOTSTRAP_LEDGER \"$MSL_B_BOOTSTRAP_MAX_EFFECTIVE\"",
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
            "msl_b_derive_old_5s_interval",
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


class MslV2Old5sIntervalDerivationTests(unittest.TestCase):
    """MSL_B_OLD_5S_INTERVAL must be derived from measured markers, never asserted as a literal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.functions_src = extract_old_5s_interval_functions()

    def test_no_hardcoded_verdict_literal_outside_derivation_function(self) -> None:
        # The verdict strings legitimately appear inside msl_b_derive_old_5s_interval's
        # own conditional branches (that IS the derivation). What must never happen is
        # an unconditional echo of a verdict anywhere else in the runner, e.g. inside
        # print_final_block itself asserting a literal outcome.
        outside_function = self.runner.replace(self.functions_src, "", 1)
        for hardcoded in (
            'echo "MSL_B_OLD_5S_INTERVAL=ELIMINATED"',
            'echo "MSL_B_OLD_5S_INTERVAL=STILL_PRESENT"',
            'echo "MSL_B_OLD_5S_INTERVAL=TRANSFORMED"',
        ):
            self.assertNotIn(hardcoded, outside_function)
        self.assertIn('msl_b_derive_old_5s_interval "$SESSION_LOG"', outside_function)
        print("MSL_B_OLD_5S_INTERVAL_DERIVED_NOT_ASSERTED=true REAL=function_call MUTATED=hardcoded_literal_scan")

    def run_derivation(self, markers: dict[str, str]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "session.log"
            log.write_text(
                "\n".join(f"{key}={value}" for key, value in markers.items()) + "\n",
                encoding="utf-8",
            )
            script = self.functions_src + f'\nmsl_b_derive_old_5s_interval "{log}"\n'
            proc = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout

    def test_small_delta_with_zero_ctpp_registrations_is_eliminated(self) -> None:
        out = self.run_derivation(
            {
                "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS": "1000",
                "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS": "1050",
                "MSL_B_CTPP_REGISTRATION_COUNT": "0",
            }
        )
        self.assertIn("MSL_B_OLD_5S_INTERVAL=ELIMINATED", out)
        self.assertIn("MSL_B_OLD_5S_INTERVAL_MS=50", out)

    def test_five_second_delta_is_still_present(self) -> None:
        out = self.run_derivation(
            {
                "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS": "1000",
                "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS": "6100",
                "MSL_B_CTPP_REGISTRATION_COUNT": "0",
            }
        )
        self.assertIn("MSL_B_OLD_5S_INTERVAL=STILL_PRESENT", out)
        self.assertIn("MSL_B_OLD_5S_INTERVAL_MS=5100", out)
        self.assertIn("MSL_B_OLD_5S_INTERVAL_LOCALIZATION=NOT_LOCALIZED", out)

    def test_mid_delta_is_transformed(self) -> None:
        out = self.run_derivation(
            {
                "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS": "1000",
                "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS": "3500",
                "MSL_B_CTPP_REGISTRATION_COUNT": "0",
            }
        )
        self.assertIn("MSL_B_OLD_5S_INTERVAL=TRANSFORMED", out)
        self.assertIn("MSL_B_OLD_5S_INTERVAL_MS=2500", out)

    def test_nonzero_ctpp_registration_blocks_eliminated_verdict(self) -> None:
        out = self.run_derivation(
            {
                "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS": "1000",
                "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS": "1050",
                "MSL_B_CTPP_REGISTRATION_COUNT": "1",
            }
        )
        self.assertNotIn("MSL_B_OLD_5S_INTERVAL=ELIMINATED", out)
        print("MSL_B_OLD_5S_INTERVAL_USES_CTPP_EVIDENCE=true REAL=ctpp_count_1 MUTATED=eliminated_verdict_blocked")

    def test_missing_markers_yield_not_available(self) -> None:
        out = self.run_derivation({})
        self.assertIn("MSL_B_OLD_5S_INTERVAL=N/A", out)
        self.assertIn("MSL_B_OLD_5S_INTERVAL_DERIVATION=NOT_LOCALIZED", out)

    def test_flip_proof_thresholds_are_real(self) -> None:
        real = self.functions_src.count("-ge 4000")
        mutated = self.functions_src.replace("-ge 4000", "-ge 999999", 1).count("-ge 4000")
        self.assertGreater(real, 0)
        self.assertNotEqual(real, mutated)
        print("MSL_B_OLD_5S_INTERVAL_THRESHOLD_DERIVED=true REAL=delta_ge_4000 MUTATED=threshold_removed")


class MslV2BootstrapCapTests(unittest.TestCase):
    """MSL_B_BOOTSTRAP_MAX must gate the bootstrap-only ledger without ever
    silently widening on invalid input, and must not affect the independent
    media-attempt ledger cap (15)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.functions_src, cls.default_src, cls.gate_src = extract_bootstrap_cap_sources()

    def run_gate(
        self,
        ledger_value: str,
        bootstrap_max: str | None,
        bootstrap_only: str = "YES",
        gate_src: str | None = None,
    ) -> tuple[bool, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "bootstrap.ledger"
            ledger.write_text(f"{ledger_value}\n", encoding="utf-8")
            script = (
                "set -u -o pipefail\n"
                "FAIL=0\n"
                # Mirrors the runner's own top-of-file default (outside the
                # extracted gate block, so not part of the REAL/MUTATED diff).
                "MSL_B_BOOTSTRAP_MAX_EFFECTIVE=NOT_REACHED\n"
                + self.functions_src
                + "\n"
                + self.default_src
                + "\n"
                + (gate_src if gate_src is not None else self.gate_src)
                + 'echo "GATE_FAIL=$FAIL"\n'
                + 'echo "GATE_EFFECTIVE=$MSL_B_BOOTSTRAP_MAX_EFFECTIVE"\n'
                + 'echo "GATE_LEDGER_VALUE=${bootstrap_ledger_value:-UNSET}"\n'
            )
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            env["MSL_B_LIVE_RUN"] = "YES"
            env["MSL_B_BOOTSTRAP_ONLY"] = bootstrap_only
            env["MSL_B_BOOTSTRAP_LEDGER"] = str(ledger)
            if bootstrap_max is not None:
                env["MSL_B_BOOTSTRAP_MAX"] = bootstrap_max
            proc = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                env=env,
                timeout=5,
                check=False,
            )
            fail_line = next(line for line in proc.stdout.splitlines() if line.startswith("GATE_FAIL="))
            effective_line = next(line for line in proc.stdout.splitlines() if line.startswith("GATE_EFFECTIVE="))
            ledger_value_line = next(
                line for line in proc.stdout.splitlines() if line.startswith("GATE_LEDGER_VALUE=")
            )
            failed = fail_line == "GATE_FAIL=1"
            return failed, effective_line.split("=", 1)[1], ledger_value_line.split("=", 1)[1]

    def test_default_cap_is_two(self) -> None:
        failed, effective, ledger_value = self.run_gate("1", None)
        self.assertFalse(failed)
        self.assertEqual(effective, "2")
        self.assertEqual(ledger_value, "1")
        failed, effective, _ = self.run_gate("2", None)
        self.assertEqual(effective, "2")
        print("MSL_B_BOOTSTRAP_MAX_DEFAULT_IS_TWO=true REAL=unset_env MUTATED=n/a")

    def test_custom_cap_three_accepts_two_refuses_three(self) -> None:
        failed, effective, ledger_value = self.run_gate("2", "3")
        self.assertFalse(failed)
        self.assertEqual(effective, "3")
        self.assertEqual(ledger_value, "2")
        failed, effective, ledger_value = self.run_gate("3", "3")
        self.assertEqual(effective, "3")
        self.assertNotEqual(ledger_value, "3")
        print("MSL_B_BOOTSTRAP_MAX_RAISED_CAP_HONORED=true REAL=MSL_B_BOOTSTRAP_MAX=3 MUTATED=default_cap_2")

    def test_invalid_cap_values_fail_closed(self) -> None:
        for invalid in ("0", "-1", "abc", ""):
            failed, effective, ledger_value = self.run_gate("0", invalid)
            self.assertTrue(failed, f"MSL_B_BOOTSTRAP_MAX={invalid!r} must fail closed")
            self.assertEqual(effective, "NOT_REACHED")
            self.assertEqual(ledger_value, "UNSET")
        print(
            "MSL_B_BOOTSTRAP_MAX_INVALID_FAILS_CLOSED=true "
            "REAL=0,-1,abc,empty_all_refused MUTATED=cap_never_widened"
        )

    def test_cap_flip_proof_is_real(self) -> None:
        real = self.gate_src.count('"$MSL_B_BOOTSTRAP_MAX_EFFECTIVE"')
        mutated = self.gate_src.replace(
            '"$MSL_B_BOOTSTRAP_MAX_EFFECTIVE"', '"2"', 1
        ).count('"$MSL_B_BOOTSTRAP_MAX_EFFECTIVE"')
        self.assertGreater(real, 0)
        self.assertNotEqual(real, mutated)
        print(
            "MSL_B_BOOTSTRAP_MAX_CAP_WIRED=true "
            f"REAL={real}_effective_cap_uses MUTATED={mutated}_after_hardcoding_2"
        )

    def test_media_attempt_ledger_cap_15_unaffected(self) -> None:
        attempt_gate = re.search(
            r'if \[ "\$MSL_B_LIVE_RUN" = YES \] && \[ "\$MSL_B_BOOTSTRAP_ONLY" != YES \] '
            r'&& \[ -n "\$MSL_B_ATTEMPT_LEDGER" \]; then\n.*?\nfi\n',
            self.runner,
            re.S,
        )
        self.assertIsNotNone(attempt_gate, "media-attempt ledger gate block missing")
        self.assertIn(
            "ledger_value_or_fail \"$MSL_B_ATTEMPT_LEDGER\" MSL_B_ATTEMPT_LEDGER 15",
            attempt_gate.group(0),
        )
        self.assertNotIn("MSL_B_BOOTSTRAP_MAX", attempt_gate.group(0))
        print("MSL_B_MEDIA_ATTEMPT_CAP_15_UNAFFECTED=true REAL=literal_15_unchanged MUTATED=n/a")

    def test_media_mode_runs_with_bootstrap_counter_at_cap(self) -> None:
        # A media attempt (MSL_B_BOOTSTRAP_ONLY != YES) must never consult the
        # bootstrap-only cap: it must pass even with the bootstrap ledger
        # already sitting at (or over) MSL_B_BOOTSTRAP_MAX, and must never
        # touch bootstrap_ledger_value / MSL_B_BOOTSTRAP_MAX_EFFECTIVE.
        failed, effective, ledger_value = self.run_gate("2", None, bootstrap_only="NO")
        self.assertFalse(failed)
        self.assertEqual(effective, "NOT_REACHED")
        self.assertEqual(ledger_value, "UNSET")
        failed, effective, ledger_value = self.run_gate("99", "2", bootstrap_only="NO")
        self.assertFalse(failed)
        self.assertEqual(effective, "NOT_REACHED")
        self.assertEqual(ledger_value, "UNSET")
        print(
            "MSL_B_MEDIA_MODE_BOOTSTRAP_CAP_NOT_CONSULTED=true "
            "REAL=bootstrap_ledger_at_99_cap_2_media_mode_passes MUTATED=n/a"
        )

    def test_bootstrap_only_scoping_flip_proof(self) -> None:
        # Same ledger-at-cap scenario as above (bootstrap ledger value "2"
        # sitting at the default cap of 2), but re-run against a MUTATED gate
        # with the "$MSL_B_BOOTSTRAP_ONLY" = YES scoping condition stripped
        # back out (i.e. CHILD A CORRECTIVE-4's actual bug): the mutated
        # version must wrongly consult the bootstrap-only cap machinery for a
        # media attempt (MSL_B_BOOTSTRAP_ONLY=NO), reaching the at-cap
        # refusal branch of ledger_value_or_fail, whereas the real, scoped
        # gate never even looks at the ledger for a media attempt.
        _, real_effective, real_ledger_value = self.run_gate("2", None, bootstrap_only="NO")
        self.assertEqual(real_effective, "NOT_REACHED")
        self.assertEqual(real_ledger_value, "UNSET")

        real_condition = (
            'if [ "$MSL_B_LIVE_RUN" = YES ] && [ "$MSL_B_BOOTSTRAP_ONLY" = YES ] '
            '&& [ -n "$MSL_B_BOOTSTRAP_LEDGER" ]; then'
        )
        mutated_condition = 'if [ "$MSL_B_LIVE_RUN" = YES ] && [ -n "$MSL_B_BOOTSTRAP_LEDGER" ]; then'
        self.assertIn(real_condition, self.gate_src)
        mutated_gate = self.gate_src.replace(real_condition, mutated_condition, 1)
        self.assertNotEqual(mutated_gate, self.gate_src)

        _, mutated_effective, mutated_ledger_value = self.run_gate(
            "2", None, bootstrap_only="NO", gate_src=mutated_gate
        )
        self.assertEqual(mutated_effective, "2")
        self.assertNotEqual(mutated_ledger_value, "UNSET")
        print(
            "MSL_B_BOOTSTRAP_ONLY_SCOPING_FLIP_PROOF=true "
            f"REAL=media_mode_cap_untouched(effective={real_effective},ledger={real_ledger_value}) "
            f"MUTATED=media_mode_hits_cap_refusal(effective={mutated_effective},ledger={mutated_ledger_value})"
        )

    def test_neither_mode_increments_the_others_counter(self) -> None:
        ledger_increment_src = re.search(r"^ledger_increment\(\) \{.*?^\}", self.runner, re.S | re.M)
        self.assertIsNotNone(ledger_increment_src, "ledger_increment function missing")
        bootstrap_only_block = re.search(
            r'if \[ "\$MSL_B_BOOTSTRAP_ONLY" = YES \]; then\n(.*?)\nfi\n',
            self.runner,
            re.S,
        )
        self.assertIsNotNone(bootstrap_only_block, "bootstrap-only completion block missing")
        self.assertIn(
            'ledger_increment "$MSL_B_BOOTSTRAP_LEDGER" "$bootstrap_ledger_value"',
            bootstrap_only_block.group(1),
        )
        self.assertNotIn("MSL_B_ATTEMPT_LEDGER", bootstrap_only_block.group(1))
        after_bootstrap_only_block = self.runner[bootstrap_only_block.end():]
        self.assertIn(
            'ledger_increment "$MSL_B_ATTEMPT_LEDGER" "$attempt_ledger_value"',
            after_bootstrap_only_block,
        )
        self.assertNotIn(
            'ledger_increment "$MSL_B_BOOTSTRAP_LEDGER"',
            after_bootstrap_only_block,
        )
        print("MSL_B_LEDGER_COUNTERS_INDEPENDENT=true REAL=each_ledger_incremented_once MUTATED=cross_increment_scan")


if __name__ == "__main__":
    unittest.main()
