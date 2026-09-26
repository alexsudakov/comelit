#!/usr/bin/env python3
"""Offline exercise for the MSL-V2 bootstrap provider's real live path.

The live bootstrap-only check on CT120 got past the offer read, the SDP
transform and the OAuth token lookup, made one real cloud request, and then
raised a bare TypeError turning the cloud response into a written remote SDP
-- with no detail, because nothing offline had ever driven that part of the
provider with a real, correctly-shaped session object. These tests do:
importing nothing re-implemented, they run the provider's own
cloud.async_negotiate_p2p / cloud._validate_remote_sdp / runtime._write_remote
calls against a real synthetic offer file and a fake HTTP transport that
implements the same session.post()-as-async-context-manager interface
aiohttp.ClientSession provides.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_msl_v2_listener_bootstrap_provider import ROOT, VALID_OFFER, extract_provider


FAKE_DEVICE_UUID = "deadbeef-live-path-device-uuid"
FAKE_VIP_TOKEN = "0123456789abcdef0123456789abcdef"
FAKE_ACCESS_TOKEN = "SUPER-SECRET-LIVE-PATH-ACCESS-TOKEN-MUST-NEVER-BE-PRINTED"


def run_live_path_provider(
    provider_source: str,
    scenario: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    root = Path(tempfile.mkdtemp(prefix="msl-b-live-path-"))
    provider = root / "provider.py"
    run_dir = root / "run"
    run_dir.mkdir()
    offer = run_dir / "offer.sdp"
    remote = run_dir / "remote.sdp"
    log = root / "listener.log"
    provider.write_text(provider_source, encoding="utf-8")
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
        "2",
        "--config-source",
        str(root / "absent-secrets.env"),
        "--device-uuid",
        FAKE_DEVICE_UUID,
        "--vip-token",
        FAKE_VIP_TOKEN,
        "--oauth-access-token",
        FAKE_ACCESS_TOKEN,
    ]
    proc = subprocess.run(
        args,
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
        check=False,
    )
    return proc, remote


class MslV2LivePathOfflineExerciseTests(unittest.TestCase):
    """Exercises the real cloud.async_negotiate_p2p / _validate_remote_sdp /
    runtime._write_remote chain against a fake HTTP transport, not a
    re-implementation of any of them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.provider_source = extract_provider()

    def test_live_path_success_writes_validated_remote_sdp_mode_600(self) -> None:
        proc, remote = run_live_path_provider(self.provider_source, "live_path_success")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for marker in (
            "MSL_B_BOOTSTRAP_OFFER_READ=true",
            "MSL_B_BOOTSTRAP_TRANSFORM=PASS",
            "MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token",
            "MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1",
            "MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true",
        ):
            self.assertIn(marker, proc.stdout)
        self.assertTrue(remote.exists())
        mode = stat.S_IMODE(remote.stat().st_mode)
        self.assertEqual(mode, 0o600)
        written = remote.read_text(encoding="utf-8")
        self.assertIn("a=ice-ufrag:", written)
        self.assertIn("a=ice-pwd:", written)
        self.assertIn("a=candidate:", written)

    def test_live_path_non200_status_fails_closed_with_bounded_detail(self) -> None:
        proc, remote = run_live_path_provider(self.provider_source, "live_path_http_status")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(remote.exists())
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertEqual(proc.stdout.count("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT="), 2)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ComelitCloudHttpError", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAILURE_DETAIL=ComelitCloudHttpError:http_status:503", proc.stdout)

    def test_live_path_malformed_response_body_fails_closed_with_bounded_detail(self) -> None:
        proc, remote = run_live_path_provider(self.provider_source, "live_path_malformed_body")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(remote.exists())
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertEqual(proc.stdout.count("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT="), 2)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ComelitCloudError", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAILURE_DETAIL=ComelitCloudError:response_not_json", proc.stdout)

    def test_live_path_response_missing_data_fails_closed_with_bounded_detail(self) -> None:
        proc, remote = run_live_path_provider(self.provider_source, "live_path_missing_data")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(remote.exists())
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertEqual(proc.stdout.count("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT="), 2)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ComelitCloudError", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAILURE_DETAIL=ComelitCloudError:data_not_object", proc.stdout)

    def test_live_path_missing_sdp_in_response_fails_closed_with_bounded_detail(self) -> None:
        proc, remote = run_live_path_provider(self.provider_source, "live_path_missing_sdp")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(remote.exists())
        self.assertIn("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1", proc.stdout)
        self.assertEqual(proc.stdout.count("MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT="), 2)
        self.assertIn("MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=ComelitCloudError", proc.stdout)
        self.assertIn("MSL_B_BOOTSTRAP_FAILURE_DETAIL=ComelitCloudError:remote_sdp_missing", proc.stdout)

    def test_live_path_failures_never_leak_credentials_or_tokens(self) -> None:
        for scenario in (
            "live_path_http_status",
            "live_path_malformed_body",
            "live_path_missing_data",
            "live_path_missing_sdp",
        ):
            proc, _remote = run_live_path_provider(self.provider_source, scenario)
            for secret in (FAKE_DEVICE_UUID, FAKE_VIP_TOKEN, FAKE_ACCESS_TOKEN):
                self.assertNotIn(secret, proc.stdout, scenario)
                self.assertNotIn(secret, proc.stderr, scenario)
            self.assertNotIn("Traceback", proc.stdout, scenario)
            self.assertNotIn("Traceback", proc.stderr, scenario)

    def test_live_path_failure_detail_message_is_bounded(self) -> None:
        proc, _remote = run_live_path_provider(self.provider_source, "live_path_http_status")
        detail_lines = [
            line for line in proc.stdout.splitlines() if line.startswith("MSL_B_BOOTSTRAP_FAILURE_DETAIL=")
        ]
        self.assertEqual(len(detail_lines), 1)
        _, _, payload = detail_lines[0].partition("=")
        exc_class, _, message = payload.partition(":")
        self.assertEqual(exc_class, "ComelitCloudHttpError")
        self.assertLessEqual(len(message), 120)


class MslV2LiveSessionRegressionTests(unittest.TestCase):
    """Regression test for the exact TypeError observed live: constructing
    the real network session from a possibly-stubbed `aiohttp` module gives
    a placeholder `object` that raises TypeError under `async with`. The fix
    builds the session with a dedicated function, independent of whatever
    `sys.modules["aiohttp"]` was stubbed to while loading cloud.py/oauth.py."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.provider_source = extract_provider()
        cls.tmp = tempfile.TemporaryDirectory()
        provider_path = Path(cls.tmp.name) / "provider_module.py"
        provider_path.write_text(cls.provider_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("msl_b_live_path_provider_module", provider_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.module = module

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("msl_b_live_path_provider_module", None)
        cls.tmp.cleanup()

    def test_old_style_stubbed_client_session_reproduces_the_original_typeerror(self) -> None:
        # This is what the live path used to do: `from aiohttp import
        # ClientSession` after a module-load-time aiohttp stub, then
        # `async with ClientSession() as session`. Confirms the failure
        # class this corrective fixed, and that it lived in session
        # construction, not in cloud.py's own parsing.
        import asyncio

        stub_client_session = self.module.SimpleNamespace(ClientSession=object, ClientError=Exception).ClientSession

        async def _old_style() -> None:
            async with stub_client_session() as _session:
                pass

        with self.assertRaises(TypeError):
            asyncio.run(_old_style())

    def test_build_live_session_without_real_aiohttp_supports_async_with(self) -> None:
        import asyncio

        session = self.module._build_live_session(False)
        self.assertIsInstance(session, self.module.UrllibHttpSession)

        async def _enter_and_exit() -> None:
            async with session:
                pass

        asyncio.run(_enter_and_exit())

    def test_have_real_aiohttp_reflects_this_sandbox_which_lacks_aiohttp(self) -> None:
        # This offline sandbox has no aiohttp installed (the same condition
        # CT120's bare python3 process is in), so the detector must say so;
        # a change that always returns True here would silently reintroduce
        # the original TypeError on every environment without aiohttp.
        # Other test modules in this same pytest process stub
        # sys.modules["aiohttp"] and never clean up, so any such stub is
        # removed for the duration of this check and restored afterwards to
        # avoid leaking state into other tests.
        saved = sys.modules.pop("aiohttp", None)
        try:
            self.assertFalse(self.module._have_real_aiohttp())
        finally:
            if saved is not None:
                sys.modules["aiohttp"] = saved


if __name__ == "__main__":
    unittest.main()
