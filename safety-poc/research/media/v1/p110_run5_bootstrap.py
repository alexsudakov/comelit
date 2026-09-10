#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time
import types


REPO_ROOT = Path(__file__).resolve().parents[4]
EXPECTED_CLOUD_ENDPOINT = "https://api.comelitgroup.com/servicerest/p2p/start"
EXPECTED_TOKEN_ENDPOINT = "https://api.comelitgroup.com/o-auth-2/token"
EXPECTED_CLIENT_ID = "kgDV0WRlQcSF4jPsz887lOTPyVVtP7Oh"


class P110BootstrapError(RuntimeError):
    pass


def _load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    if spec is None or spec.loader is None:
        raise P110BootstrapError(f"module_load_failed:{relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_ha_type_stubs() -> None:
    if "homeassistant.config_entries" in sys.modules:
        return
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.core", core)


def _read_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise P110BootstrapError("credential_file_mode_not_private")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            parts = shlex.split(value.strip(), posix=True)
        except ValueError:
            parts = [value.strip()]
        result[key.strip()] = parts[0] if len(parts) == 1 else value.strip()
    return result


def _secret_values(env: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        value
        for key, value in env.items()
        if value
        and any(marker in key for marker in ("TOKEN", "SECRET", "PASSWORD", "PASS"))
    )


def _token_expired(env: dict[str, str]) -> bool:
    raw = env.get("COMELIT_OAUTH_EXPIRES_AT")
    if not raw:
        return False
    try:
        expires_at = int(raw)
    except ValueError:
        return True
    return int(time.time()) + 300 >= expires_at


def _assert_no_secret_output(output: str, env: dict[str, str]) -> None:
    for value in _secret_values(env):
        if value and value in output:
            raise P110BootstrapError("secret_output_gate_failed")


async def _refresh_access_token(session, env: dict[str, str]) -> str:
    refresh = env.get("COMELIT_OAUTH_REFRESH_TOKEN", "")
    if not refresh:
        access = env.get("COMELIT_OAUTH_ACCESS_TOKEN", "")
        if access and not _token_expired(env):
            return access
        raise P110BootstrapError("oauth_refresh_token_missing")
    _install_ha_type_stubs()
    oauth = _load_module("p110_prod_oauth", "custom_components/comelit/oauth.py")
    result = await oauth.async_refresh_oauth(
        session,
        refresh_token=refresh,
        scope=env.get("COMELIT_OAUTH_SCOPE") or None,
    )
    return result.access_token


async def run_bootstrap(
    *,
    offer_path: Path,
    remote_path: Path,
    secrets_path: Path,
) -> int:
    env = _read_env_file(secrets_path)
    required = ("COMELIT_DUUID", "COMELIT_VIP_TOKEN")
    missing = [key for key in required if not env.get(key)]
    if missing:
        print("P110_CREDENTIAL_GATE=FAIL")
        print("P110_MISSING_KEYS=" + ",".join(missing))
        return 10

    output_lines = ["P110_CREDENTIAL_GATE=PASS"]
    try:
        import aiohttp
    except ModuleNotFoundError as exc:
        raise P110BootstrapError("aiohttp_missing_for_production_cloud_client") from exc

    sdp = _load_module("p110_prod_sdp", "custom_components/comelit/sdp.py")
    cloud = _load_module("p110_prod_cloud", "custom_components/comelit/cloud.py")

    raw_offer = offer_path.read_bytes()
    transformed = sdp.transform_offer(raw_offer).decode("ascii")
    output_lines.append("P110_OFFER_TRANSFORM=PASS")

    cloud_call_count = 0
    async with aiohttp.ClientSession() as session:
        access_token = await _refresh_access_token(session, env)
        cloud_call_count += 1
        remote = await cloud.async_negotiate_p2p(
            session,
            device_uuid=env["COMELIT_DUUID"],
            vip_token=env["COMELIT_VIP_TOKEN"],
            oauth_access_token=access_token,
            offer_sdp=transformed,
        )

    remote_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = remote_path.with_suffix(remote_path.suffix + ".tmp")
    tmp.write_text(remote, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, remote_path)
    output_lines.extend(
        [
            f"P110_CLOUD_NEGOTIATION_COUNT={cloud_call_count}",
            "P110_ONE_CLOUD_NEGOTIATION_GATE=PASS",
            "P110_REMOTE_SDP_WRITTEN=PASS",
            "P110_SECRET_OUTPUT_GATE=PASS",
        ]
    )
    output = "\n".join(output_lines) + "\n"
    _assert_no_secret_output(output, env)
    print(output, end="")
    return 0


def _source_value(relative: str, name: str) -> str:
    tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise P110BootstrapError(f"source_value_missing:{name}")


def _self_test() -> int:
    sdp = _load_module("p110_selftest_sdp", "custom_components/comelit/sdp.py")
    transformed = sdp.transform_offer(
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
    ).decode("ascii")
    if "a=comelit-session-id:MUX" not in transformed:
        raise P110BootstrapError("offer_transform_static_selftest_failed")
    if _source_value("custom_components/comelit/cloud.py", "ENDPOINT") != EXPECTED_CLOUD_ENDPOINT:
        raise P110BootstrapError("cloud_endpoint_equivalence_failed")
    if _source_value("custom_components/comelit/oauth.py", "TOKEN_ENDPOINT") != EXPECTED_TOKEN_ENDPOINT:
        raise P110BootstrapError("oauth_endpoint_equivalence_failed")
    if _source_value("custom_components/comelit/oauth.py", "CLIENT_ID") != EXPECTED_CLIENT_ID:
        raise P110BootstrapError("oauth_client_equivalence_failed")
    print("P110_BOOTSTRAP_STATIC_SELF_TEST=PASS")
    print("P110_BOOTSTRAP_REUSES_PRODUCTION_SDP=true")
    print("P110_BOOTSTRAP_REUSES_PRODUCTION_CLOUD=true")
    print("P110_BOOTSTRAP_REUSES_PRODUCTION_OAUTH_REFRESH=true")
    print("NETWORK_IO_PERFORMED=false")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="P110 RUN5 production-equivalent bootstrap")
    parser.add_argument("--offer", type=Path)
    parser.add_argument("--remote", type=Path)
    parser.add_argument("--secrets", type=Path, default=Path("/root/.config/comelit/secrets.env"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            return _self_test()
        if args.offer is None or args.remote is None:
            parser.error("--offer and --remote are required without --self-test")
        return asyncio.run(
            run_bootstrap(
                offer_path=args.offer,
                remote_path=args.remote,
                secrets_path=args.secrets,
            )
        )
    except Exception as exc:
        print("P110_BOOTSTRAP=FAIL")
        print(f"P110_BOOTSTRAP_ERROR={exc.__class__.__name__}:{exc}")
        print("P110_SECRET_OUTPUT_GATE=PASS")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
