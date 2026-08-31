#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.p14_ha_bridge import (  # noqa: E402
    P14AuthenticationError,
    P14BridgeApplication,
    P14CanonicalRunner,
    P14ReplayError,
    P14ReplayStore,
    P14RequestError,
    P14RunnerConfig,
    P14SignedRequestVerifier,
    P14_MAX_BODY_BYTES,
    P14_OPEN_DOOR_PATH,
    P14_PROTOCOL_VERSION,
    sign_request,
)

DEFAULT_RUNNER = "/usr/local/sbin/comelit-p14-production-runner"
DEFAULT_JOURNAL = "/root/comelit-p13-run/p13-one-shot.sqlite3"
DEFAULT_REPLAY_DB = "/root/comelit-p14-ha-bridge/replay.sqlite3"
DEFAULT_LOCK = "/root/comelit-p14-ha-bridge/runner.lock"


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(f"P14_CONFIG_ERROR={name}_REQUIRED")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"P14_CONFIG_ERROR={name}_INVALID_BOOL")


def build_application_from_env() -> P14BridgeApplication:
    secret = _required_env("COMELIT_P14_SHARED_SECRET").encode("utf-8")
    target = _required_env("COMELIT_P14_TARGET_FINGERPRINT")
    runner_sha = _required_env("COMELIT_P14_RUNNER_SHA256")
    replay_store = P14ReplayStore(os.environ.get("COMELIT_P14_REPLAY_DB", DEFAULT_REPLAY_DB))
    verifier = P14SignedRequestVerifier(
        shared_secret=secret,
        replay_store=replay_store,
        max_clock_skew_seconds=int(os.environ.get("COMELIT_P14_MAX_CLOCK_SKEW", "30")),
    )
    runner = P14CanonicalRunner(
        P14RunnerConfig(
            runner_path=os.environ.get("COMELIT_P14_RUNNER", DEFAULT_RUNNER),
            runner_sha256=runner_sha,
            journal_path=os.environ.get("COMELIT_P14_JOURNAL", DEFAULT_JOURNAL),
            target_fingerprint=target,
            lock_path=os.environ.get("COMELIT_P14_RUNNER_LOCK", DEFAULT_LOCK),
            live_enabled=_bool_env("COMELIT_P14_LIVE_ENABLED", False),
            timeout_seconds=int(os.environ.get("COMELIT_P14_RUNNER_TIMEOUT", "150")),
            term_grace_seconds=int(os.environ.get("COMELIT_P14_TERM_GRACE", "5")),
        )
    )
    if runner.config.live_enabled:
        runner.verify_runner_identity()
    return P14BridgeApplication(verifier, runner)


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ComelitP14Bridge/1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> P14BridgeApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        return

    def _json_response(self, status: int, payload: dict[str, object], *, response_auth: tuple[str, str] | None = None) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if response_auth is not None:
            timestamp, nonce = response_auth
            signature = sign_request(self.app.verifier.shared_secret, method="RESPONSE", path=P14_OPEN_DOOR_PATH, timestamp=timestamp, nonce=nonce, body=body)
            self.send_header("X-Comelit-Version", P14_PROTOCOL_VERSION)
            self.send_header("X-Comelit-Response-Signature", signature)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != P14_OPEN_DOOR_PATH:
            self._json_response(404, {"ok": False, "error": "not_found"}); return
        if self.headers.get("Transfer-Encoding"):
            self._json_response(400, {"ok": False, "error": "transfer_encoding_forbidden"}); return
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json_response(400, {"ok": False, "error": "application_json_required"}); return
        raw_length = self.headers.get("Content-Length") or ""
        if not raw_length.isdigit():
            self._json_response(411, {"ok": False, "error": "content_length_required"}); return
        length = int(raw_length)
        if length < 2 or length > P14_MAX_BODY_BYTES:
            self._json_response(413, {"ok": False, "error": "request_body_size_invalid"}); return
        body = self.rfile.read(length)
        if len(body) != length:
            self._json_response(400, {"ok": False, "error": "request_body_truncated"}); return
        headers = {key: self.headers.get(key, "") for key in ("X-Comelit-Version", "X-Comelit-Timestamp", "X-Comelit-Nonce", "X-Comelit-Signature")}
        try:
            result = self.app.open_door(headers=headers, body=body)
        except P14ReplayError:
            self._json_response(409, {"ok": False, "error": "replay_rejected_do_not_retry"}); return
        except P14AuthenticationError:
            self._json_response(401, {"ok": False, "error": "authentication_failed"}); return
        except P14RequestError as exc:
            self._json_response(400, {"ok": False, "error": str(exc)}); return
        except Exception:
            self._json_response(500, {"ok": False, "error": "internal_outcome_unknown_do_not_retry", "retry_allowed": False, "physical_effect_asserted": False}); return
        self._json_response(200, result.as_dict(), response_auth=(headers["X-Comelit-Timestamp"], headers["X-Comelit-Nonce"]))

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self._json_response(404, {"ok": False, "error": "not_found"}); return
        runner_identity = "disabled"
        if self.app.runner.config.live_enabled:
            try:
                self.app.runner.verify_runner_identity()
            except RuntimeError:
                self._json_response(503, {"ok": False, "protocol_version": 1, "live_enabled": True, "runner_identity": "fail"}); return
            runner_identity = "pass"
        self._json_response(200, {"ok": True, "protocol_version": 1, "live_enabled": bool(self.app.runner.config.live_enabled), "runner_identity": runner_identity})


class P14HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, handler, app: P14BridgeApplication):
        super().__init__(address, handler); self.app = app


def main() -> int:
    if os.geteuid() != 0:
        print("P14_BRIDGE_REQUIRES_ROOT=true", file=sys.stderr); return 1
    app = build_application_from_env()
    bind_host = os.environ.get("COMELIT_P14_BIND_HOST", "127.0.0.1").strip()
    bind_port = int(os.environ.get("COMELIT_P14_BIND_PORT", "18014"))
    print("P14_HA_BRIDGE_START=true", flush=True)
    print(f"P14_HA_BRIDGE_BIND={bind_host}:{bind_port}", flush=True)
    print(f"P14_HA_BRIDGE_LIVE_ENABLED={str(app.runner.config.live_enabled).lower()}", flush=True)
    server = P14HTTPServer((bind_host, bind_port), BridgeHandler, app)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
