#!/usr/bin/env python3
"""P116/R41 v4 no-ring official-app readiness preflight.

LIVE-CAPABLE, BUT NOT LIVE-AUTHORIZED BY ITS PRESENCE.  The public entrypoint
does no runtime work unless the exact one-attempt approval token is supplied.
The private child is capability-gated by inherited pipes and is the sole owner
of the one permitted listener ``start`` request.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Callable

BASE_R40H_SHA = "f317bc1145b4165db0ef3677ebba777edd6780d1"
APPROVAL_TOKEN = "I_APPROVE_R41_V4_NO_RING_PREFLIGHT_ONCE"
FAILSAFE_CONTINUOUS_DOWN_SECONDS = 300
FAILSAFE_MAX_LIFETIME_BEFORE_PAUSE_SECONDS = 30
FAILSAFE_MAX_LIFETIME_AFTER_PAUSE_SECONDS = 600
MAX_OPERATIONAL_TIMEOUT_SECONDS = 240
RESTORE_TIMEOUT_SECONDS = 50
STATUS_SAMPLE_GAP_SECONDS = 2.0
READY_STABILITY_SECONDS = 1.0
FAILSAFE_POLL_SECONDS = 5.0
FAILSAFE_ARM_TIMEOUT_SECONDS = 5.0
MAX_LOGCAT_LINE_BYTES = 512
_ALLOWED_CONTROL_ACTIONS = frozenset({"status", "stop", "start"})
_ALLOWED_UI_STATES = frozenset({"CONNECTED", "CONNECTING", "NOT_CONNECTED", "UNKNOWN"})
_ATTEMPT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SUBPROCESS_ENV_ALLOWLIST = frozenset(
    {
        "PATH", "LANG", "LC_ALL", "TZ", "ADB_VENDOR_KEYS",
        "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
    }
)

_RESEARCH_DIR = Path(__file__).resolve().parent
_CURSOR_MODEL_PATH = _RESEARCH_DIR / "entrance_p116_r41_persistent_logcat_cursor.py"
_READINESS_MODEL_PATH = _RESEARCH_DIR / "entrance_p116_r40h_official_app_readiness_model.py"


class AttemptEnd(RuntimeError):
    def __init__(self, code: int, result: str) -> None:
        super().__init__(result)
        self.code = code
        self.result = result


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def load_models():
    return (
        _load(_CURSOR_MODEL_PATH, "p116_r41_v4_cursor_model"),
        _load(_READINESS_MODEL_PATH, "p116_r40h_readiness_model_dep_from_r41_v4"),
    )


def validate_timeout_seconds(value: int) -> int:
    if value <= 0 or value > MAX_OPERATIONAL_TIMEOUT_SECONDS:
        raise ValueError("timeout_outside_operational_safety_bound")
    return value


def build_adb_logcat_command(adb_path: str, serial: str) -> list[str]:
    if not serial or any(ch in serial for ch in ("\x00", "\n", "\r")):
        raise ValueError("invalid_adb_serial")
    return [
        adb_path, "-s", serial, "logcat", "-v", "brief", "-T", "1", "-s",
        "ComelitStatus:I", "ViperSocketReaderRun:E", "*:S",
    ]


def _private_fd_ok(fd: int) -> None:
    st = os.fstat(fd)
    if (
        not stat.S_ISREG(st.st_mode)
        or stat.S_IMODE(st.st_mode) != 0o600
        or st.st_uid != os.geteuid()
    ):
        raise RuntimeError("private_file_metadata_invalid")


def _read_private(path: Path, max_bytes: int) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _private_fd_ok(fd)
        if os.fstat(fd).st_size > max_bytes:
            raise RuntimeError("private_file_too_large")
        raw = os.read(fd, max_bytes + 1)
        if len(raw) > max_bytes:
            raise RuntimeError("private_file_too_large")
        return raw.decode("utf-8")
    finally:
        os.close(fd)


def read_control_url(path: Path) -> str:
    value = _read_private(path, 4096).strip()
    if not value.startswith(("http://", "https://")):
        raise RuntimeError("control_url_scheme_invalid")
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        raise RuntimeError("control_url_shape_invalid")
    if not value.isascii():
        raise RuntimeError("control_url_non_ascii")
    return value


def read_ui_state(path: Path) -> str | None:
    try:
        value = _read_private(path, 32).strip().upper()
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError, UnicodeError):
        return "UNKNOWN"
    return value if value in _ALLOWED_UI_STATES else "UNKNOWN"


def _write_private(path: Path, text: str, *, exclusive: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def prepare_run_root(base: Path, attempt_id: str) -> Path:
    if not base.is_absolute():
        raise RuntimeError("run_root_must_be_absolute")
    try:
        base.mkdir(mode=0o700)
    except FileExistsError:
        pass
    st = base.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or st.st_uid != os.geteuid():
        raise RuntimeError("run_root_metadata_invalid")
    run_root = base / attempt_id
    run_root.mkdir(mode=0o700)
    return run_root


def _subprocess_env() -> dict[str, str]:
    """Do not propagate the approval capability or loader/Python injection."""
    return {key: value for key, value in os.environ.items() if key in _SUBPROCESS_ENV_ALLOWLIST}


class ControlClient:
    def __init__(self, url: str, *, curl_path: str = "curl", run: Callable = subprocess.run) -> None:
        self._url = url
        self._curl = curl_path
        self._run = run

    def post(self, action: str, timeout: int = 10) -> dict[str, object]:
        if action not in _ALLOWED_CONTROL_ACTIONS:
            raise ValueError("control_action_not_allowed")
        cp = self._run(
            [
                self._curl, "--silent", "--show-error", "--fail-with-body",
                "--connect-timeout", "5", "--max-time", str(timeout),
                "--header", "Content-Type: application/json",
                "--data", json.dumps({"action": action}, separators=(",", ":")),
                "--config", "-",
            ],
            input=f"url = {json.dumps(self._url)}\n",
            env=_subprocess_env(), check=False, text=True, capture_output=True,
        )
        if cp.returncode != 0:
            raise RuntimeError(f"control_{action}_failed")
        try:
            data = json.loads(cp.stdout)
        except Exception as exc:
            raise RuntimeError(f"control_{action}_invalid_json") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"control_{action}_invalid_shape")
        return data


def status_ready(data: dict[str, object]) -> bool:
    return (
        data.get("ok") is True
        and data.get("supervisor_running") is True
        and data.get("running") is True
        and data.get("listener_ready") is True
        and data.get("last_error") in (None, "")
    )


def status_paused(data: dict[str, object]) -> bool:
    return (
        data.get("ok") is True
        and data.get("supervisor_running") is False
        and data.get("running") is False
        and data.get("listener_ready") is False
    )


def sample_twice(control: ControlClient, predicate: Callable[[dict[str, object]], bool]) -> bool:
    try:
        first = predicate(control.post("status"))
        time.sleep(STATUS_SAMPLE_GAP_SECONDS)
        second = predicate(control.post("status"))
        return first and second
    except Exception:
        return False


class PersistentSafeLogcat:
    def __init__(self, cursor_model, *, adb_path: str, serial: str) -> None:
        self._buffer = cursor_model.SafeLogEventBuffer()
        self._adb = adb_path
        self._serial = serial
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._reader_failed = False

    @property
    def alive(self) -> bool:
        return (
            self._proc is not None and self._proc.poll() is None
            and self._thread is not None and self._thread.is_alive()
            and not self._reader_failed and self._buffer.healthy
        )

    def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("logcat_already_started")
        self._proc = subprocess.Popen(
            build_adb_logcat_command(self._adb, self._serial),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=False, bufsize=0, start_new_session=True, env=_subprocess_env(),
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                raw = self._proc.stdout.readline(MAX_LOGCAT_LINE_BYTES + 1)
                if not raw:
                    return
                if len(raw) > MAX_LOGCAT_LINE_BYTES:
                    # Drain the rest of this rejected line in bounded chunks;
                    # never retain or reduce a partial device-controlled line.
                    while raw and not raw.endswith(b"\n"):
                        raw = self._proc.stdout.readline(MAX_LOGCAT_LINE_BYTES + 1)
                    self._reader_failed = True
                    return
                line = raw.decode("utf-8")
                with self._lock:
                    self._buffer.ingest_brief_line(line)
        except Exception:
            self._reader_failed = True

    def wait_started(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        stable_cursor = -1
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            if not self.alive:
                return False
            with self._lock:
                cursor = self._buffer.cursor
            if cursor != stable_cursor:
                stable_cursor, stable_since = cursor, time.monotonic()
            if time.monotonic() - stable_since >= 0.5:
                return True
            time.sleep(0.05)
        return self.alive

    def capture_cursor(self) -> int:
        with self._lock:
            return self._buffer.capture_cursor()

    def fresh_verdict(self, cursor: int):
        with self._lock:
            return self._buffer.evaluate_after(cursor)

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=3)
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._proc = None


@dataclasses.dataclass
class FailsafeHandle:
    proc: subprocess.Popen[str]
    heartbeat_fd: int

    def close_heartbeat(self) -> None:
        if self.heartbeat_fd >= 0:
            os.close(self.heartbeat_fd)
            self.heartbeat_fd = -1


@dataclasses.dataclass
class AttemptState:
    approval_granted: bool = False
    adb_live_invocations: int = 0
    listener_pause_count: int = 0
    listener_resume_count: int = 0
    pause_maybe_accepted: bool = False
    listener_ready_after: bool = False
    pre_pause_log_cursor: int = -1
    ui_state: str = "UNKNOWN"
    fresh_registration_ready: bool = False
    transport_failure_after_transition: bool = False
    official_app_ready: str = "UNPROVEN"
    physical_ring_allowed: bool = False
    failsafe_armed: bool = False
    failsafe_outcome: str = "NOT_ARMED"
    result: str = "FAIL_NOT_STARTED"
    last_step: str = "START"


def evaluate_gate(readiness, ui_state: str, fresh):
    observation = readiness.ReadinessObservation(
        ui_state=getattr(readiness.OfficialAppUiConnectionState, ui_state),
        listener_state=readiness.ListenerState.PAUSED,
        ring_budget_available=False,
        registration_ready_seen=True if fresh.registration_ready_fresh_scalar else False,
    )
    verdict = readiness.evaluate_readiness_v3(
        readiness.ReadinessObservationV3(
            system_class=readiness.AppSystemClass.LEGACY_VIP,
            observation=observation,
            fresh_registration=fresh,
        )
    )
    if verdict.physical_ring_allowed:
        raise RuntimeError("ring_budget_invariant_broken")
    return verdict


def _parent_gone(heartbeat_fd: int) -> bool:
    readable, _, _ = select.select([heartbeat_fd], [], [], 0)
    return bool(readable) and os.read(heartbeat_fd, 1) == b""


def _send_listener_start_once(control: ControlClient, outcome: Path, reason: str) -> int:
    """The runner's single listener-start invocation site."""
    try:
        control.post("start", timeout=40)
        marker = f"{reason}_START_SENT_ONCE"
    except Exception:
        marker = f"{reason}_START_ATTEMPT_FAILED"
    _write_private(outcome, marker + "\n")
    return 0


def _failsafe_child(config: dict[str, object]) -> int:
    """Sole restore owner: perform zero or one listener ``start`` request."""
    run_root = Path(str(config["run_root"]))
    heartbeat_fd = int(config["heartbeat_fd"])
    outcome = run_root / "failsafe-outcome"
    control = ControlClient(str(config["control_url"]), curl_path=str(config["curl_path"]))
    try:
        _write_private(run_root / "failsafe-armed", "true\n", exclusive=True)
        armed_at = time.monotonic()
        while not (run_root / "pause-started").exists():
            if (run_root / "failsafe-disarm").exists() or _parent_gone(heartbeat_fd):
                _write_private(outcome, "DISARMED_BEFORE_PAUSE\n")
                return 0
            if time.monotonic() - armed_at >= FAILSAFE_MAX_LIFETIME_BEFORE_PAUSE_SECONDS:
                _write_private(outcome, "BOUNDED_PRE_PAUSE_LIFETIME_EXPIRED\n")
                return 0
            time.sleep(0.1)

        paused_at = time.monotonic()
        down_since: float | None = None
        saw_down = False
        ready_samples = 0
        while True:
            if (run_root / "failsafe-disarm").exists():
                _write_private(outcome, "DISARMED_NORMAL\n")
                return 0

            restore_requested = (run_root / "restore-request").exists()
            if restore_requested:
                # Normal cleanup takes priority over another status round.  The
                # request itself is private and only the authorized parent can
                # create it in the mode-0700 attempt directory.
                return _send_listener_start_once(control, outcome, "RESTORE")
            try:
                ready = status_ready(control.post("status"))
            except Exception:
                ready = False
            now = time.monotonic()
            if ready:
                down_since = None
                ready_samples += 1
                if saw_down and ready_samples >= 2:
                    _write_private(outcome, "RESTORED_WITHOUT_RECOVERY_START\n")
                    return 0
                if _parent_gone(heartbeat_fd) and not saw_down and ready_samples >= 2:
                    _write_private(outcome, "PARENT_GONE_LISTENER_READY\n")
                    return 0
            else:
                saw_down = True
                ready_samples = 0
                if down_since is None:
                    down_since = now

            continuous_down = down_since is not None and now - down_since >= FAILSAFE_CONTINUOUS_DOWN_SECONDS
            if continuous_down:
                # This is the only listener-start call site in the whole runner.
                return _send_listener_start_once(control, outcome, "RECOVERY")

            if now - paused_at >= FAILSAFE_MAX_LIFETIME_AFTER_PAUSE_SECONDS:
                # Do not trade a bounded orphan for an abandoned listener.  A
                # READY sample needs no action; every other/unknown state gets
                # the same sole, exactly-once recovery request.
                if ready and ready_samples >= 2:
                    _write_private(outcome, "BOUNDED_LIFETIME_EXPIRED_LISTENER_READY\n")
                    return 0
                return _send_listener_start_once(control, outcome, "BOUNDED_LIFETIME_RECOVERY")
            time.sleep(FAILSAFE_POLL_SECONDS)
    except Exception:
        try:
            _write_private(outcome, "FAILSAFE_ERROR\n")
        except Exception:
            pass
        return 1
    finally:
        os.close(heartbeat_fd)


def _read_child_capability() -> dict[str, object]:
    """Consume the inherited one-shot pipe; direct CLI invocation has no capability."""
    raw_fd = os.environ.pop("R41_FAILSAFE_CONFIG_FD", "")
    if not raw_fd.isascii() or not raw_fd.isdigit():
        raise RuntimeError("failsafe_capability_missing")
    fd = int(raw_fd)
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        raise RuntimeError("failsafe_capability_not_pipe")
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            total += len(chunk)
            if total > 8192:
                raise RuntimeError("failsafe_capability_too_large")
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = json.loads(b"".join(chunks))
    if not isinstance(data, dict) or set(data) != {"run_root", "control_url", "curl_path", "heartbeat_fd"}:
        raise RuntimeError("failsafe_capability_invalid")
    heartbeat_fd = data["heartbeat_fd"]
    if (
        not isinstance(heartbeat_fd, int) or isinstance(heartbeat_fd, bool)
        or heartbeat_fd < 0 or heartbeat_fd == fd
        or not stat.S_ISFIFO(os.fstat(heartbeat_fd).st_mode)
    ):
        raise RuntimeError("failsafe_heartbeat_invalid")
    run_root = Path(str(data["run_root"]))
    st = run_root.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or st.st_uid != os.geteuid():
        raise RuntimeError("failsafe_run_root_invalid")
    return data


def arm_failsafe(run_root: Path, control_url: str, curl_path: str) -> FailsafeHandle:
    config_read, config_write = os.pipe()
    heartbeat_read, heartbeat_write = os.pipe()
    env = _subprocess_env()
    env["R41_FAILSAFE_CONFIG_FD"] = str(config_read)
    config = json.dumps(
        {
            "run_root": str(run_root), "control_url": control_url,
            "curl_path": curl_path, "heartbeat_fd": heartbeat_read,
        }, separators=(",", ":"),
    ).encode("utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--_failsafe-child"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=env, pass_fds=(config_read, heartbeat_read),
        )
    except BaseException:
        for fd in (config_read, config_write, heartbeat_read, heartbeat_write):
            os.close(fd)
        raise
    os.close(config_read)
    os.close(heartbeat_read)
    try:
        try:
            os.write(config_write, config)
        finally:
            os.close(config_write)
    except BaseException:
        os.close(heartbeat_write)
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        raise
    handle = FailsafeHandle(proc, heartbeat_write)
    deadline = time.monotonic() + FAILSAFE_ARM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if (run_root / "failsafe-armed").exists():
            return handle
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    handle.close_heartbeat()
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    raise RuntimeError("failsafe_arm_not_confirmed")


def request_listener_restore_once(run_root: Path, state: AttemptState) -> None:
    state.last_step = "RESTORE_LISTENER"
    _write_private(run_root / "restore-request", "true\n", exclusive=True)


def wait_listener_ready(control: ControlClient, state: AttemptState) -> bool:
    deadline = time.monotonic() + RESTORE_TIMEOUT_SECONDS
    consecutive = 0
    while time.monotonic() < deadline:
        try:
            if status_ready(control.post("status")):
                consecutive += 1
                if consecutive >= 2:
                    state.listener_ready_after = True
                    return True
            else:
                consecutive = 0
        except Exception:
            consecutive = 0
        time.sleep(2)
    return False


def disarm_failsafe(run_root: Path, handle: FailsafeHandle) -> str:
    _write_private(run_root / "failsafe-disarm", "true\n")
    handle.close_heartbeat()
    try:
        handle.proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(handle.proc.pid, signal.SIGTERM)
        handle.proc.wait(timeout=3)
        return "DISARMED_CHILD_TERMINATED"
    return read_failsafe_outcome(run_root)


def read_failsafe_outcome(run_root: Path) -> str:
    try:
        return _read_private(run_root / "failsafe-outcome", 128).strip() or "DISARMED"
    except FileNotFoundError:
        return "DISARMED_NO_CHILD_OUTCOME"


def record_start_attempt(state: AttemptState, outcome: str) -> None:
    if "START_SENT_ONCE" in outcome or "START_ATTEMPT_FAILED" in outcome:
        state.listener_resume_count = 1


def print_final(state: AttemptState, timeout_seconds: int) -> None:
    print("=== COMELIT P116 R41 V4 NO-RING PREFLIGHT ===")
    print(f"BASE_R40H_SHA={BASE_R40H_SHA}")
    print(f"APPROVAL_GRANTED={'true' if state.approval_granted else 'false'}")
    print(f"OPERATIONAL_TIMEOUT_SECONDS={timeout_seconds}")
    print(f"ADB_LIVE_INVOCATIONS={state.adb_live_invocations}")
    print(f"LISTENER_PAUSE_COUNT={state.listener_pause_count}")
    print(f"LISTENER_RESUME_COUNT={state.listener_resume_count}")
    print(f"LISTENER_READY_AFTER={'true' if state.listener_ready_after else 'false'}")
    print(f"FAILSAFE_ARMED={'true' if state.failsafe_armed else 'false'}")
    print(f"FAILSAFE_OUTCOME={state.failsafe_outcome}")
    print(f"PRE_PAUSE_SAFE_EVENT_CURSOR={state.pre_pause_log_cursor}")
    print(f"CURRENT_UI_STATE={state.ui_state}")
    print(f"FRESH_REGISTRATION_READY={'true' if state.fresh_registration_ready else 'false'}")
    print(f"TRANSPORT_FAILURE_AFTER_TRANSITION={'true' if state.transport_failure_after_transition else 'false'}")
    print(f"OFFICIAL_APP_READY={state.official_app_ready}")
    print(f"PHYSICAL_RING_ALLOWED={'true' if state.physical_ring_allowed else 'false'}")
    for marker in (
        "PHYSICAL_RING_COUNT=0", "SYNTHETIC_RING_COUNT=0", "RING_BUDGET_CONSUMED=false",
        "DOOR_ACTIONS=0", "GATE_ACTIONS=0", "MEDIA_ACTIONS=0", "HA_RESTARTS=0",
        "HA_RELOADS=0", "AUTOMATIC_EXPERIMENT_RETRY=false",
    ):
        print(marker)
    print(f"LAST_STEP={state.last_step}")
    print(f"RESULT={state.result}")
    print("NEXT_LIVE_AUTHORIZED=false")
    print("=== END COMELIT P116 R41 V4 NO-RING PREFLIGHT ===")


def run_attempt(args: argparse.Namespace) -> int:
    state = AttemptState()
    timeout_seconds = args.timeout_seconds
    control = None
    logcat = None
    failsafe = None
    run_root = None
    exit_code = 1
    try:
        state.last_step = "APPROVAL"
        approval = os.environ.get("R41_APPROVAL", "")
        os.environ.pop("R41_APPROVAL", None)
        if approval != APPROVAL_TOKEN:
            raise AttemptEnd(64, "BLOCKED_APPROVAL_REQUIRED")
        state.approval_granted = True
        timeout_seconds = validate_timeout_seconds(args.timeout_seconds)
        if os.geteuid() != 0:
            raise AttemptEnd(65, "BLOCKED_ROOT_REQUIRED")
        if not _ATTEMPT_RE.fullmatch(args.attempt_id):
            raise AttemptEnd(66, "BLOCKED_ATTEMPT_ID_INVALID")

        cursor_model, readiness = load_models()
        control_url = read_control_url(Path(args.control_url_file))
        control = ControlClient(control_url, curl_path=args.curl)
        run_root = prepare_run_root(Path(args.run_root), args.attempt_id)
        ui_file = run_root / "operator-ui-state"
        print(f"R41_OPERATOR_UI_STATE_FILE={ui_file}")
        print("R41_OPERATOR_UI_STATE_ALLOWED=CONNECTED|CONNECTING|NOT_CONNECTED|UNKNOWN")

        state.last_step = "LISTENER_READY_BEFORE"
        if not sample_twice(control, status_ready):
            raise AttemptEnd(20, "BLOCKED_LISTENER_NOT_READY")

        state.last_step = "START_PERSISTENT_LOGCAT"
        logcat = PersistentSafeLogcat(cursor_model, adb_path=args.adb, serial=args.adb_serial)
        logcat.start()
        state.adb_live_invocations = 1
        if not logcat.wait_started():
            raise AttemptEnd(21, "BLOCKED_LOGCAT_NOT_STABLE")

        state.last_step = "ARM_FAILSAFE"
        failsafe = arm_failsafe(run_root, control_url, args.curl)
        state.failsafe_armed = True
        state.failsafe_outcome = "ARMED_PENDING_RECOVERY"

        _write_private(run_root / "pause-started", "true\n", exclusive=True)

        state.last_step = "PAUSE_LISTENER"
        state.pause_maybe_accepted = True
        state.listener_pause_count = 1
        try:
            control.post("stop", timeout=20)
        except Exception:
            raise AttemptEnd(22, "BLOCKED_LISTENER_PAUSE_AMBIGUOUS")
        if not sample_twice(control, status_paused):
            raise AttemptEnd(23, "BLOCKED_LISTENER_PAUSE_NOT_CONFIRMED")

        # Establish the evidence boundary only after pause is confirmed.  An
        # event racing with stop is therefore conservatively stale, never a
        # false fresh-registration proof for this attempt.
        state.last_step = "CAPTURE_POST_PAUSE_CURSOR"
        state.pre_pause_log_cursor = logcat.capture_cursor()

        try:
            ui_file.unlink()
        except FileNotFoundError:
            pass
        print("R41_OPERATOR_UI_STATE_SAMPLE_NOW=true")
        state.last_step = "WAIT_APP_READY"
        deadline = time.monotonic() + timeout_seconds
        candidate_since = None
        while time.monotonic() < deadline:
            if not logcat.alive:
                raise AttemptEnd(24, "BLOCKED_LOGCAT_STREAM_LOST")
            sampled = read_ui_state(ui_file)
            if sampled is not None:
                state.ui_state = sampled
            fresh = logcat.fresh_verdict(state.pre_pause_log_cursor)
            state.fresh_registration_ready = bool(fresh.registration_ready_fresh_scalar)
            state.transport_failure_after_transition = bool(fresh.transport_failure_after_transition)
            if state.ui_state == "CONNECTED" and state.fresh_registration_ready:
                verdict = evaluate_gate(readiness, state.ui_state, fresh)
                state.official_app_ready = verdict.official_app_ready
                state.physical_ring_allowed = bool(verdict.physical_ring_allowed)
                if verdict.official_app_ready == "true":
                    candidate_since = candidate_since or time.monotonic()
                    if time.monotonic() - candidate_since >= READY_STABILITY_SECONDS:
                        final_fresh = logcat.fresh_verdict(state.pre_pause_log_cursor)
                        final_verdict = evaluate_gate(readiness, state.ui_state, final_fresh)
                        state.fresh_registration_ready = bool(final_fresh.registration_ready_fresh_scalar)
                        state.transport_failure_after_transition = bool(final_fresh.transport_failure_after_transition)
                        state.official_app_ready = final_verdict.official_app_ready
                        state.physical_ring_allowed = bool(final_verdict.physical_ring_allowed)
                        if final_verdict.official_app_ready == "true" and not final_verdict.physical_ring_allowed:
                            state.result, exit_code = "PASS_APP_READY_PREFLIGHT", 0
                            break
                        candidate_since = None
                else:
                    candidate_since = None
            else:
                candidate_since = None
                state.official_app_ready = "UNPROVEN"
                state.physical_ring_allowed = False
            time.sleep(0.2)
        else:
            state.result, exit_code = "BLOCKED_APP_NOT_READY", 20
    except AttemptEnd as end:
        state.result, exit_code = end.result, end.code
    except KeyboardInterrupt:
        state.result, exit_code = "BLOCKED_INTERRUPTED", 130
    except Exception as exc:
        state.result, exit_code = f"FAIL_{type(exc).__name__.upper()}", 1
    finally:
        if state.pause_maybe_accepted and control is not None and run_root is not None:
            try:
                request_listener_restore_once(run_root, state)
                restored = wait_listener_ready(control, state)
            except Exception:
                restored = False
            if not restored:
                state.result, exit_code = "FAIL_LISTENER_RESTORE", 90
                if failsafe is not None:
                    failsafe.close_heartbeat()
                    state.failsafe_outcome = read_failsafe_outcome(run_root)
                    record_start_attempt(state, state.failsafe_outcome)
            elif failsafe is not None:
                state.failsafe_outcome = disarm_failsafe(run_root, failsafe)
                record_start_attempt(state, state.failsafe_outcome)
        elif run_root is not None and failsafe is not None:
            state.failsafe_outcome = disarm_failsafe(run_root, failsafe)
        if logcat is not None:
            logcat.stop()
        state.last_step = "COMPLETE" if (state.listener_ready_after or not state.pause_maybe_accepted) else state.last_step
        print_final(state, timeout_seconds)
    return exit_code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--control-url-file")
    p.add_argument("--adb-serial")
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--attempt-id", default=f"r41-{int(time.time())}-{os.getpid()}")
    p.add_argument("--run-root", default="/run/comelit-r41-v4")
    p.add_argument("--adb", default="adb")
    p.add_argument("--curl", default="curl")
    p.add_argument("--_failsafe-child", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if not args._failsafe_child and (not args.control_url_file or not args.adb_serial):
        p.error("--control-url-file and --adb-serial are required")
    return args


def _install_signal_handlers() -> None:
    def _interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv == ["--_failsafe-child"]:
        try:
            return _failsafe_child(_read_child_capability())
        except Exception:
            return 77
    # Authorization is intentionally checked before argparse validates or
    # requires runtime-bearing public arguments.  Unauthorized invocations
    # always produce the closed, machine-readable result and touch nothing.
    if os.environ.get("R41_APPROVAL", "") != APPROVAL_TOKEN:
        state = AttemptState(result="BLOCKED_APPROVAL_REQUIRED", last_step="APPROVAL")
        print_final(state, 0)
        return 64
    args = _parse_args(effective_argv)
    if args._failsafe_child:
        return 77
    _install_signal_handlers()
    return run_attempt(args)


if __name__ == "__main__":
    raise SystemExit(main())
