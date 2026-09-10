#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
HARNESS = ROOT / "research" / "media" / "v1" / "p109_corrected_live_orchestration.py"
PACKAGED = REPO_ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
MEDIA_TRANSPORT = REPO_ROOT / "custom_components" / "comelit" / "media_transport.py"
P108_RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p108_exact_packaged_musl_validation.sh"

EXPECTED_SHA = "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"
EXPECTED_HEAD = "977f7197f103050a9f52b43dad26af5df0c7bbf0"


import importlib.util

spec = importlib.util.spec_from_file_location("p109_harness", HARNESS)
p109 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["p109_harness"] = p109
spec.loader.exec_module(p109)


class FakeNative:
    def __init__(
        self,
        run_dir: Path,
        *,
        lines: list[str],
        write_offer: bytes | None = None,
        exit_before_lines: bool = False,
    ) -> None:
        self.run_dir = run_dir
        self.lines = list(lines)
        self._returncode = 7 if exit_before_lines else None
        self.terminated = False
        self.write_offer = write_offer
        if write_offer is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "offer.sdp").write_bytes(write_offer)

    @property
    def returncode(self) -> int | None:
        return self._returncode

    async def readline(self) -> str:
        if self.lines:
            line = self.lines.pop(0)
            if line == "__EXIT__":
                self._returncode = 9
                return ""
            return line
        self._returncode = 0
        return ""

    async def wait(self) -> int:
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 143

    def kill(self) -> None:
        self._returncode = 137


async def ok_oauth() -> str:
    return "sentinel-oauth-token"


async def failing_oauth() -> str:
    raise RuntimeError("oauth unavailable")


class P109CorrectedLiveOrchestrationTests(unittest.TestCase):
    def run_harness(
        self,
        *,
        native: FakeNative,
        cloud=None,
        oauth=ok_oauth,
        gates: p109.P109Gates | None = None,
        timeout: float = 0.2,
    ) -> p109.P109Result:
        async def native_factory(_run_dir: Path):
            if native.write_offer is not None:
                (_run_dir / "offer.sdp").write_bytes(native.write_offer)
            return native

        async def default_cloud(**kwargs: str) -> str:
            default_cloud.calls.append(kwargs)
            return p109.remote_sdp_fixture()

        default_cloud.calls = []
        cloud_negotiator = cloud or default_cloud

        async def drive() -> p109.P109Result:
            with tempfile.TemporaryDirectory() as tmp:
                return await p109.run_corrected_orchestration(
                    run_dir=Path(tmp),
                    gates=gates or p109.P109Gates(),
                    native_factory=native_factory,
                    oauth_provider=oauth,
                    cloud_negotiator=cloud_negotiator,
                    device_uuid="offline-device",
                    vip_token="sentinel-vip-token",
                    timeout_seconds=timeout,
                    sentinel_secrets=("sentinel-oauth-token", "sentinel-vip-token"),
                )

        return asyncio.run(drive())

    def test_harness_is_executable_offline_and_does_not_run_binary(self) -> None:
        self.assertTrue(os.stat(HARNESS).st_mode & 0o111)
        syntax = subprocess.run(["python3", "-m", "py_compile", str(HARNESS)], check=False, text=True, capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        result = subprocess.run([str(HARNESS)], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P109_OFFLINE_ONLY=true", result.stdout)
        self.assertIn("BINARY_EXECUTED=false", result.stdout)
        self.assertIn("NETWORK_IO_PERFORMED=false", result.stdout)

    def test_static_proof_production_orchestration_and_p108_gap(self) -> None:
        prod = MEDIA_TRANSPORT.read_text(encoding="utf-8")
        p108 = P108_RUNNER.read_text(encoding="utf-8")
        self.assertLess(prod.index("offer_wait = asyncio.create_task(self._offer_ready.wait())"), prod.index("raw_offer = await self._hass.async_add_executor_job(_read_offer)"))
        self.assertIn('line == "ICE_GATHER=PASS"', prod)
        self.assertIn("self._offer_ready.set()", prod)
        self.assertLess(prod.index("raw_offer = await self._hass.async_add_executor_job(_read_offer)"), prod.index("comelit_offer = transform_offer(raw_offer).decode(\"ascii\")"))
        self.assertLess(prod.index("comelit_offer = transform_offer(raw_offer).decode(\"ascii\")"), prod.index("oauth_access_token = await self._oauth.async_get_access_token()"))
        self.assertLess(prod.index("oauth_access_token = await self._oauth.async_get_access_token()"), prod.index("remote = await async_negotiate_p2p("))
        self.assertLess(prod.index("remote = await async_negotiate_p2p("), prod.index("await self._hass.async_add_executor_job(_write_remote, remote)"))
        self.assertLess(prod.index("await self._hass.async_add_executor_job(_write_remote, remote)"), prod.index('line == "P80_MEDIA_ACTIVE=true"'))
        live_invocation = p108.split("=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ===", 1)[1]
        live_invocation = live_invocation.split("MEDIA_PID=$!", 1)[0]
        self.assertIn('"$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH"', live_invocation)
        for required_missing in ("transform_offer", "async_negotiate_p2p", "remote.sdp", "oauth"):
            self.assertNotIn(required_missing, live_invocation)
        self.assertEqual(p109.P108_MISSING_CLOUD_BOOTSTRAP, "PROVEN_STATIC")

    def test_positive_sequence_reuses_production_transform_and_writes_remote_0600_once(self) -> None:
        calls: list[dict[str, str]] = []
        transform_inputs: list[bytes] = []
        original_transform = p109.transform_offer

        def recording_transform(raw: bytes) -> bytes:
            transform_inputs.append(raw)
            return original_transform(raw)

        async def cloud(**kwargs: str) -> str:
            calls.append(kwargs)
            return p109.remote_sdp_fixture()

        native = FakeNative(
            Path(tempfile.mkdtemp()),
            lines=[
                "ICE_GATHER=PASS",
                "P80_DEVICE_ACK_000A_OBSERVED=PASS",
                "P80_DEVICE_ACK_001A_OBSERVED=PASS",
                "P80_POST_001A_ACK_GATE=PASS",
                "P80_MEDIA_ACTIVE=true",
                "P80_VIDEO_RTP_FORWARDING=PASS",
                "P80_AUDIO_RTP_FORWARDING=PASS",
            ],
            write_offer=p109.raw_offer_fixture(),
        )
        try:
            p109.transform_offer = recording_transform
            result = self.run_harness(native=native, cloud=cloud)
        finally:
            p109.transform_offer = original_transform
        self.assertEqual(result.status, "SUCCESS", result)
        self.assertEqual(result.cloud_call_count, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(transform_inputs, [p109.raw_offer_fixture()])
        self.assertIn("a=comelit-session-id:MUX", calls[0]["offer_sdp"])
        self.assertIn("m=audio 45678 RTP/SAVPF 0 8", calls[0]["offer_sdp"])
        self.assertTrue(result.remote_written)
        self.assertEqual(result.remote_mode, "0o600")
        self.assertEqual(result.markers["P80_MEDIA_ACTIVE"], "true")
        self.assertEqual(result.markers["P80_VIDEO_RTP_FORWARDING"], "PASS")
        self.assertEqual(result.markers["P80_AUDIO_RTP_FORWARDING"], "PASS")
        self.assertEqual(result.one_cloud_negotiation_gate, "PASS")
        self.assertEqual(result.secret_output_gate, "PASS")

    def test_no_ice_gather_means_no_cloud_negotiation(self) -> None:
        native = FakeNative(Path(tempfile.mkdtemp()), lines=["P80_DEVICE_ACK_000A_OBSERVED=PASS"], write_offer=p109.raw_offer_fixture())
        result = self.run_harness(native=native)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.cloud_call_count, 0)
        self.assertFalse(result.remote_written)

    def test_malformed_or_missing_offer_fails_closed_before_cloud(self) -> None:
        for offer in (None, b"not an sdp"):
            native = FakeNative(Path(tempfile.mkdtemp()), lines=["ICE_GATHER=PASS"], write_offer=offer)
            result = self.run_harness(native=native)
            self.assertEqual(result.status, "FAIL")
            self.assertEqual(result.cloud_call_count, 0)
            self.assertFalse(result.remote_written)
            self.assertIn("offer_transform_failed", result.error)

    def test_oauth_failure_means_no_cloud_negotiation(self) -> None:
        native = FakeNative(Path(tempfile.mkdtemp()), lines=["ICE_GATHER=PASS"], write_offer=p109.raw_offer_fixture())
        result = self.run_harness(native=native, oauth=failing_oauth)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.cloud_call_count, 0)
        self.assertFalse(result.remote_written)

    def test_cloud_failure_or_malformed_remote_means_no_remote_sdp(self) -> None:
        async def failing_cloud(**_: str) -> str:
            raise RuntimeError("cloud unavailable")

        async def malformed_cloud(**_: str) -> str:
            return "v=0\r\n"

        for cloud in (failing_cloud, malformed_cloud):
            native = FakeNative(Path(tempfile.mkdtemp()), lines=["ICE_GATHER=PASS"], write_offer=p109.raw_offer_fixture())
            result = self.run_harness(native=native, cloud=cloud)
            self.assertEqual(result.status, "FAIL")
            self.assertEqual(result.cloud_call_count, 1)
            self.assertFalse(result.remote_written)
            self.assertIn("cloud_bootstrap_failed", result.error)

    def test_cloud_call_count_gates_make_retry_impossible(self) -> None:
        text = HARNESS.read_text(encoding="utf-8")
        self.assertEqual(text.count("cloud_call_count += 1"), 1)
        self.assertNotIn("for attempt", text)
        self.assertNotIn("while retry", text)
        self.assertNotIn("force_refresh=True", text)

    def test_binary_exits_before_offer_or_active_fails(self) -> None:
        before_offer = FakeNative(Path(tempfile.mkdtemp()), lines=[], write_offer=p109.raw_offer_fixture(), exit_before_lines=True)
        result = self.run_harness(native=before_offer)
        self.assertIn("media_native_exited_before_offer", result.error)
        self.assertEqual(result.status, "FAIL")

        before_active = FakeNative(Path(tempfile.mkdtemp()), lines=["ICE_GATHER=PASS", "__EXIT__"], write_offer=p109.raw_offer_fixture())
        result = self.run_harness(native=before_active)
        self.assertIn("media_native_exited_before_active", result.error)
        self.assertEqual(result.status, "FAIL")

    def test_timeout_fails_closed(self) -> None:
        class HangingNative(FakeNative):
            async def readline(self) -> str:
                await asyncio.sleep(1)
                return ""

        native = HangingNative(Path(tempfile.mkdtemp()), lines=[], write_offer=p109.raw_offer_fixture())
        result = self.run_harness(native=native, timeout=0.01)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.error, "timeout")
        self.assertEqual(result.teardown_fail_closed_gate, "PASS")

    def test_pre_execution_gates_fail_before_native_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wrong_binary = Path(tmp) / "comelit-media"
            wrong_binary.write_bytes(b"wrong")
            cases = [
                p109.P109Gates(current_head="wrong"),
                p109.P109Gates(packaged_binary=wrong_binary),
                p109.P109Gates(runtime_abi_gate=False),
                p109.P109Gates(door_available=True),
                p109.P109Gates(gate_available=True),
            ]
            for gates in cases:
                started = False

                async def native_factory(_run_dir: Path):
                    nonlocal started
                    started = True
                    return FakeNative(Path(tempfile.mkdtemp()), lines=[], write_offer=p109.raw_offer_fixture())

                async def drive() -> p109.P109Result:
                    return await p109.run_corrected_orchestration(
                        run_dir=Path(tmp) / "run",
                        gates=gates,
                        native_factory=native_factory,
                        oauth_provider=ok_oauth,
                        cloud_negotiator=lambda **_: p109.remote_sdp_fixture(),
                        device_uuid="offline-device",
                        vip_token="sentinel-vip-token",
                    )

                result = asyncio.run(drive())
                self.assertEqual(result.classification, "PRE_EXECUTION_GATE_FAILED")
                self.assertFalse(started)

    def test_packaged_binary_identity_is_pinned_and_unchanged(self) -> None:
        self.assertEqual(p109.EXPECTED_PR106_HEAD, EXPECTED_HEAD)
        self.assertEqual(p109.EXPECTED_PACKAGED_SHA256, EXPECTED_SHA)
        self.assertEqual(hashlib.sha256(PACKAGED.read_bytes()).hexdigest(), EXPECTED_SHA)

    def test_run4_forensic_regression_classification(self) -> None:
        classification = p109.classify_run4_forensic(
            offer_exists=True,
            remote_exists=False,
            native_exited=True,
            markers={
                "P78_RTPC_SIGNALING_RESULT": "NOT_REACHED",
                "P80_MEDIA_ACTIVE": "NOT_REACHED",
            },
        )
        self.assertEqual(classification, "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED")

    def test_secret_sentinels_are_never_reported(self) -> None:
        async def cloud(**kwargs: str) -> str:
            self.assertEqual(kwargs["vip_token"], "sentinel-vip-token")
            self.assertEqual(kwargs["oauth_access_token"], "sentinel-oauth-token")
            return p109.remote_sdp_fixture()

        native = FakeNative(
            Path(tempfile.mkdtemp()),
            lines=["ICE_GATHER=PASS", "P80_MEDIA_ACTIVE=true"],
            write_offer=p109.raw_offer_fixture(),
        )
        result = self.run_harness(native=native, cloud=cloud)
        serialized = repr(result)
        self.assertNotIn("sentinel-vip-token", serialized)
        self.assertNotIn("sentinel-oauth-token", serialized)
        self.assertEqual(result.secret_output_gate, "PASS")


if __name__ == "__main__":
    unittest.main()
