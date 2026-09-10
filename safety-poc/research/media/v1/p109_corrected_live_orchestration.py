#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Awaitable, Callable, Iterable, Protocol


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGED_BINARY = REPO_ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
EXPECTED_PR106_HEAD = "977f7197f103050a9f52b43dad26af5df0c7bbf0"
EXPECTED_PACKAGED_SHA256 = (
    "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"
)
P108_MISSING_CLOUD_BOOTSTRAP = "PROVEN_STATIC"


def _load_repo_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_module:{relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_sdp = _load_repo_module("p109_comelit_sdp", "custom_components/comelit/sdp.py")
ComelitSdpError = _sdp.ComelitSdpError
transform_offer = _sdp.transform_offer


class ComelitCloudError(RuntimeError):
    """Offline equivalent of production ComelitCloudError for validation failures."""


def validate_remote_sdp(remote: str) -> None:
    """Byte-equivalent to custom_components/comelit/cloud.py::_validate_remote_sdp."""
    lines = [
        line.strip()
        for line in remote.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]
    has_ufrag = any(line.startswith("a=ice-ufrag:") for line in lines)
    has_pwd = any(line.startswith("a=ice-pwd:") for line in lines)
    has_candidate = any(line.startswith("a=candidate:") for line in lines)
    if not (has_ufrag and has_pwd and has_candidate):
        raise ComelitCloudError("remote_sdp_incomplete")


class P109HarnessError(RuntimeError):
    pass


class NativeSession(Protocol):
    async def readline(self) -> str:
        ...

    async def wait(self) -> int:
        ...

    def terminate(self) -> None:
        ...

    def kill(self) -> None:
        ...

    @property
    def returncode(self) -> int | None:
        ...


NativeFactory = Callable[[Path], Awaitable[NativeSession]]
OAuthProvider = Callable[[], Awaitable[str]]
CloudNegotiator = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class P109Gates:
    current_head: str = EXPECTED_PR106_HEAD
    expected_head: str = EXPECTED_PR106_HEAD
    packaged_binary: Path = PACKAGED_BINARY
    expected_sha256: str = EXPECTED_PACKAGED_SHA256
    runtime_abi_gate: bool = True
    door_available: bool = False
    gate_available: bool = False


@dataclass
class P109Result:
    status: str
    classification: str
    markers: dict[str, str] = field(default_factory=dict)
    cloud_call_count: int = 0
    remote_written: bool = False
    remote_mode: str = "NOT_WRITTEN"
    error: str = "NONE"
    secret_output_gate: str = "PASS"
    one_cloud_negotiation_gate: str = "PASS"
    no_retry_gate: str = "PASS"
    door_gate: str = "PASS"
    gate_media_gate: str = "PASS"
    teardown_fail_closed_gate: str = "PASS"


SAFE_MARKER_KEYS = {
    "ICE_GATHER",
    "P78_RTPC_SIGNALING_RESULT",
    "P80_DEVICE_ACK_000A_OBSERVED",
    "P80_DEVICE_ACK_001A_OBSERVED",
    "P80_POST_001A_ACK_GATE",
    "P80_MEDIA_ACTIVE",
    "P80_VIDEO_RTP_FORWARDING",
    "P80_AUDIO_RTP_FORWARDING",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_offer_fixture() -> bytes:
    return (
        b"v=0\r\n"
        b"o=- 1 1 IN IP4 0.0.0.0\r\n"
        b"s=ice\r\n"
        b"t=0 0\r\n"
        b"c=IN IP4 192.0.2.10\r\n"
        b"m=audio 45678 RTP/AVP 0\r\n"
        b"a=ice-ufrag:rawufrag\r\n"
        b"a=ice-pwd:rawpassword0123456789\r\n"
        b"a=candidate:1 1 UDP 2130706431 192.0.2.10 45678 typ host\r\n"
        b"a=candidate:2 1 UDP 1694498815 198.51.100.20 45678 typ srflx raddr 192.0.2.10 rport 45678\r\n"
    )


def remote_sdp_fixture() -> str:
    return (
        "v=0\r\n"
        "o=- 2 2 IN IP4 0.0.0.0\r\n"
        "s=ice\r\n"
        "t=0 0\r\n"
        "a=ice-ufrag:remoteufrag\r\n"
        "a=ice-pwd:remotepassword0123456789\r\n"
        "a=candidate:1 1 UDP 2130706431 203.0.113.30 50000 typ host\r\n"
    )


def _remember_marker(markers: dict[str, str], line: str) -> None:
    if "=" not in line:
        return
    key, value = line.split("=", 1)
    if key in SAFE_MARKER_KEYS and value in {"PASS", "FAIL", "true", "false", "NOT_REACHED"}:
        markers[key] = value


def _atomic_write_remote(path: Path, remote: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_text(remote, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        os.umask(old_umask)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _assert_static_gates(gates: P109Gates) -> None:
    if gates.current_head != gates.expected_head:
        raise P109HarnessError("head_mismatch")
    if not gates.packaged_binary.is_file():
        raise P109HarnessError("packaged_binary_missing")
    if sha256_file(gates.packaged_binary) != gates.expected_sha256:
        raise P109HarnessError("packaged_binary_sha256_mismatch")
    if not gates.runtime_abi_gate:
        raise P109HarnessError("runtime_abi_mismatch")
    if gates.door_available:
        raise P109HarnessError("door_unavailable_required")
    if gates.gate_available:
        raise P109HarnessError("gate_unavailable_required")


async def run_corrected_orchestration(
    *,
    run_dir: Path,
    gates: P109Gates,
    native_factory: NativeFactory,
    oauth_provider: OAuthProvider,
    cloud_negotiator: CloudNegotiator,
    device_uuid: str,
    vip_token: str,
    timeout_seconds: float = 1.0,
    sentinel_secrets: Iterable[str] = (),
) -> P109Result:
    markers: dict[str, str] = {}
    cloud_call_count = 0
    remote_path = run_dir / "remote.sdp"
    offer_path = run_dir / "offer.sdp"
    session: NativeSession | None = None
    outputs: list[str] = []

    def finish(status: str, classification: str, error: str = "NONE") -> P109Result:
        secret_text = "\n".join(outputs + [status, classification, error])
        secret_gate = "PASS"
        for secret in sentinel_secrets:
            if secret and secret in secret_text:
                secret_gate = "FAIL"
        mode = "NOT_WRITTEN"
        if remote_path.exists():
            mode = oct(stat.S_IMODE(remote_path.stat().st_mode))
        return P109Result(
            status=status,
            classification=classification,
            markers=dict(markers),
            cloud_call_count=cloud_call_count,
            remote_written=remote_path.exists(),
            remote_mode=mode,
            error=error,
            secret_output_gate=secret_gate,
            one_cloud_negotiation_gate="PASS" if cloud_call_count <= 1 else "FAIL",
            no_retry_gate="PASS" if cloud_call_count <= 1 else "FAIL",
            door_gate="PASS" if not gates.door_available else "FAIL",
            gate_media_gate="PASS" if not gates.gate_available else "FAIL",
            teardown_fail_closed_gate="PASS" if status != "SUCCESS" or markers.get("P80_MEDIA_ACTIVE") == "true" else "FAIL",
        )

    try:
        _assert_static_gates(gates)
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for stale in (offer_path, remote_path, run_dir / "stop"):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass

        session = await native_factory(run_dir)

        async def next_line() -> str:
            return await asyncio.wait_for(session.readline(), timeout=timeout_seconds)

        while True:
            if session.returncode is not None:
                return finish(
                    "FAIL",
                    "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED",
                    f"media_native_exited_before_offer:{session.returncode}",
                )
            line = await next_line()
            if not line:
                rc = await session.wait()
                return finish(
                    "FAIL",
                    "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED",
                    f"media_native_exited_before_offer:{rc}",
                )
            outputs.append(line)
            _remember_marker(markers, line)
            if line == "ICE_GATHER=PASS":
                break

        try:
            raw_offer = offer_path.read_bytes()
            comelit_offer = transform_offer(raw_offer).decode("ascii")
        except (OSError, UnicodeError, ComelitSdpError) as exc:
            return finish("FAIL", "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED", f"offer_transform_failed:{type(exc).__name__}")

        try:
            oauth_access_token = await oauth_provider()
        except Exception as exc:
            return finish("FAIL", "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED", f"oauth_failed:{type(exc).__name__}")

        try:
            cloud_call_count += 1
            remote = await cloud_negotiator(
                device_uuid=device_uuid,
                vip_token=vip_token,
                oauth_access_token=oauth_access_token,
                offer_sdp=comelit_offer,
            )
            validate_remote_sdp(remote)
        except Exception as exc:
            return finish("FAIL", "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED", f"cloud_bootstrap_failed:{type(exc).__name__}")

        _atomic_write_remote(remote_path, remote)

        while True:
            if session.returncode is not None:
                return finish(
                    "FAIL",
                    "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED",
                    f"media_native_exited_before_active:{session.returncode}",
                )
            line = await next_line()
            if not line:
                rc = await session.wait()
                return finish(
                    "FAIL",
                    "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED",
                    f"media_native_exited_before_active:{rc}",
                )
            outputs.append(line)
            _remember_marker(markers, line)
            if line == "P80_MEDIA_ACTIVE=true":
                break

        required = {
            "P80_DEVICE_ACK_000A_OBSERVED": "PASS",
            "P80_DEVICE_ACK_001A_OBSERVED": "PASS",
            "P80_POST_001A_ACK_GATE": "PASS",
            "P80_MEDIA_ACTIVE": "true",
            "P80_VIDEO_RTP_FORWARDING": "PASS",
            "P80_AUDIO_RTP_FORWARDING": "PASS",
        }
        while any(markers.get(key) != value for key, value in required.items()):
            line = await next_line()
            if not line:
                break
            outputs.append(line)
            _remember_marker(markers, line)

        if all(markers.get(key) == value for key, value in required.items()):
            return finish("SUCCESS", "CORRECTED_ORCHESTRATION_COMPLETED")
        return finish("FAIL", "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED", "media_markers_incomplete")
    except TimeoutError:
        return finish("FAIL", "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED", "timeout")
    except P109HarnessError as exc:
        return finish("FAIL", "PRE_EXECUTION_GATE_FAILED", str(exc))
    finally:
        if session is not None and session.returncode is None:
            try:
                (run_dir / "stop").touch(mode=0o600, exist_ok=True)
            except OSError:
                pass
            session.terminate()


def classify_run4_forensic(
    *,
    offer_exists: bool,
    remote_exists: bool,
    native_exited: bool,
    markers: dict[str, str],
) -> str:
    if (
        offer_exists
        and not remote_exists
        and native_exited
        and markers.get("P78_RTPC_SIGNALING_RESULT", "NOT_REACHED") == "NOT_REACHED"
        and markers.get("P80_MEDIA_ACTIVE", "NOT_REACHED") == "NOT_REACHED"
    ):
        return "ORCHESTRATION_BOOTSTRAP_MISSING_OR_FAILED"
    return "OTHER"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P109 offline corrected orchestration harness")
    parser.add_argument("--offline-self-test", action="store_true")
    return parser.parse_args()


async def _offline_self_test() -> int:
    class SelfTestNative:
        def __init__(self, run_dir: Path) -> None:
            self._lines = asyncio.Queue()
            self._returncode = None
            (run_dir / "offer.sdp").write_bytes(raw_offer_fixture())
            for line in (
                "ICE_GATHER=PASS",
                "P80_DEVICE_ACK_000A_OBSERVED=PASS",
                "P80_DEVICE_ACK_001A_OBSERVED=PASS",
                "P80_POST_001A_ACK_GATE=PASS",
                "P80_MEDIA_ACTIVE=true",
                "P80_VIDEO_RTP_FORWARDING=PASS",
                "P80_AUDIO_RTP_FORWARDING=PASS",
            ):
                self._lines.put_nowait(line)

        @property
        def returncode(self) -> int | None:
            return self._returncode

        async def readline(self) -> str:
            return await self._lines.get()

        async def wait(self) -> int:
            self._returncode = 0
            return 0

        def terminate(self) -> None:
            self._returncode = 0

        def kill(self) -> None:
            self._returncode = 137

    async def native_factory(run_dir: Path) -> NativeSession:
        return SelfTestNative(run_dir)

    async def oauth() -> str:
        return "sentinel-oauth-token"

    async def cloud(**_: str) -> str:
        return remote_sdp_fixture()

    with tempfile.TemporaryDirectory() as tmp:
        result = await run_corrected_orchestration(
            run_dir=Path(tmp),
            gates=P109Gates(),
            native_factory=native_factory,
            oauth_provider=oauth,
            cloud_negotiator=cloud,
            device_uuid="offline-device",
            vip_token="sentinel-vip-token",
            sentinel_secrets=("sentinel-oauth-token", "sentinel-vip-token"),
        )
    print(f"P109_OFFLINE_SELF_TEST={result.status}")
    print(f"P109_CLASSIFICATION={result.classification}")
    print(f"ONE_CLOUD_NEGOTIATION_GATE={result.one_cloud_negotiation_gate}")
    print(f"SECRET_OUTPUT_GATE={result.secret_output_gate}")
    return 0 if result.status == "SUCCESS" else 1


def main() -> int:
    args = _parse_args()
    if args.offline_self_test:
        return asyncio.run(_offline_self_test())
    print("P109_OFFLINE_ONLY=true")
    print("BINARY_EXECUTED=false")
    print("NETWORK_IO_PERFORMED=false")
    print(f"P108_MISSING_CLOUD_BOOTSTRAP={P108_MISSING_CLOUD_BOOTSTRAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
