#!/usr/bin/env python3
"""P116 R41 v4 no-ring official-app readiness preflight runner.

LIVE-CAPABLE BUT OPERATOR-GATED. This file is implemented and tested offline; merely
having it in the repository authorizes no live execution.

When the exact approval token is present, the runner may:
* open one persistent read-only filtered adb logcat stream;
* issue one listener stop request for the bounded preflight;
* issue one listener start request during normal restoration;
* poll the existing listener status surface.

It never places a physical or synthetic ring, never starts media, never reloads or
restarts Home Assistant, and never clears logcat.

Freshness is defined by a host-local sequence in one uninterrupted filtered logcat
process. "-T 1" only limits startup backlog and is never the attempt cursor.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import re
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
MAX_OPERATIONAL_TIMEOUT_SECONDS = 240
RESTORE_TIMEOUT_SECONDS = 45
STATUS_SAMPLE_GAP_SECONDS = 2.0
READY_STABILITY_SECONDS = 1.0
_ALLOWED_CONTROL_ACTIONS = frozenset({"status", "stop", "start"})
_ALLOWED_UI_STATES = frozenset({"CONNECTED", "CONNECTING", "NOT_CONNECTED", "UNKNOWN"})
_ATTEMPT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

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


def _private_file_ok(path: Path) -> None:
    st = path.stat()
    if stat.S_IMODE(st.st_mode) != 0o600 or st.st_uid != os.geteuid():
        raise RuntimeError("private_file_metadata_invalid")


def read_control_url(path: Path) -> str:
    _private_file_ok(path)
    value = path.read_text(encoding="utf-8").strip()
    if not value.startswith(("http://", "https://")):
        raise RuntimeError("control_url_scheme_invalid")
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        raise RuntimeError("control_url_shape_invalid")
    return value


def read_ui_state(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip().upper()
    except FileNotFoundError:
        return None
    return value if value in _ALLOWED_UI_STATES else "UNKNOWN"


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


class ControlClient:
    def __init__(
        self,
        url: str,
        *,
        curl_path: str = "curl",
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
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
                self._url,
            ],
            check=False, text=True, capture_output=True,
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
        self._cursor_model = cursor_model
        self._adb = adb_path
        self._serial = serial
        self._buffer = cursor_model.SafeLogEventBuffer()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._reader_failed = False

    @property
    def alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and self._thread is not None
            and self._thread.is_alive()
            and not self._reader_failed
        )

    def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("logcat_already_started")
        self._proc = subprocess.Popen(
            build_adb_logcat_command(self._adb, self._serial),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
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
                stable_cursor = cursor
                stable_since = time.monotonic()
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
        self._proc = None


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
    ui = getattr(readiness.OfficialAppUiConnectionState, ui_state)
    observation = readiness.ReadinessObservation(
        ui_state=ui,
        listener_state=readiness.ListenerState.PAUSED,
        ring_budget_available=False,
        registration_ready_seen=True if fresh.registration_ready_fresh_scalar else False,
    )
    v3 = readiness.ReadinessObservationV3(
        system_class=readiness.AppSystemClass.LEGACY_VIP,
        observation=observation,
        fresh_registration=fresh,
    )
    verdict = readiness.evaluate_readiness_v3(v3)
    if verdict.physical_ring_allowed:
        raise RuntimeError("ring_budget_invariant_broken")
    return verdict


def _failsafe_child(run_root: Path) -> int:
    """Detached infrastructure recovery only; at most one recovery start."""
    control_file = run_root / "control-url"
    pause_file = run_root / "pause-started"
    disarm_file = run_root / "failsafe-disarm"
    outcome_file = run_root / "failsafe-outcome"
    curl_path = os.environ.get("R41_FAILSAFE_CURL", "curl")

    try:
        control = ControlClient(read_control_url(control_file), curl_path=curl_path)
        while not pause_file.exists():
            if disarm_file.exists():
                _write_private(outcome_file, "DISARMED_BEFORE_PAUSE\n")
                return 0
            time.sleep(1)

        down_since: float | None = None
        while True:
            if disarm_file.exists():
                _write_private(outcome_file, "DISARMED_NORMAL\n")
                return 0
            try:
                ready = status_ready(control.post("status"))
            except Exception:
                ready = False
            now = time.monotonic()
            if ready:
                down_since = None
            elif down_since is None:
                down_since = now
            elif now - down_since >= FAILSAFE_CONTINUOUS_DOWN_SECONDS:
                # Exactly one recovery write; no retry.
                try:
                    control.post("start", timeout=40)
                    _write_private(outcome_file, "RECOVERY_START_SENT_ONCE\n")
                except Exception:
                    _write_private(outcome_file, "RECOVERY_START_ATTEMPT_FAILED\n")
                return 0
            time.sleep(5)
    except Exception:
        try:
            _write_private(outcome_file, "FAILSAFE_ERROR\n")
        except Exception:
            pass
        return 1


def arm_failsafe(run_root: Path, control_url: str, curl_path: str) -> subprocess.Popen[str]:
    _write_private(run_root / "control-url", control_url + "\n")
    env = os.environ.copy()
    env["R41_FAILSAFE_CURL"] = curl_path
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--_failsafe-child", str(run_root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )


def disarm_failsafe(run_root: Path, proc: subprocess.Popen[str] | None) -> str:
    _write_private(run_root / "failsafe-disarm", "true\n")
    if proc is not None:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            return "DISARM_SIGNALLED_CHILD_STILL_RUNNING"
    outcome = run_root / "failsafe-outcome"
    try:
        return outcome.read_text(encoding="utf-8").strip() or "DISARMED"
    except FileNotFoundError:
        return "DISARMED_NO_CHILD_OUTCOME"


def restore_listener_once(control: ControlClient, state: AttemptState) -> bool:
    """One normal recovery start, followed only by status polling."""
    state.last_step = "RESTORE_LISTENER"
    state.listener_resume_count += 1
    try:
        control.post("start", timeout=40)
    except Exception:
        return False
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
    print("PHYSICAL_RING_COUNT=0")
    print("SYNTHETIC_RING_COUNT=0")
    print("RING_BUDGET_CONSUMED=false")
    print("DOOR_ACTIONS=0")
    print("GATE_ACTIONS=0")
    print("MEDIA_ACTIONS=0")
    print("HA_RESTARTS=0")
    print("HA_RELOADS=0")
    print("AUTOMATIC_EXPERIMENT_RETRY=false")
    print(f"LAST_STEP={state.last_step}")
    print(f"RESULT={state.result}")
    print("NEXT_LIVE_AUTHORIZED=false")
    print("=== END COMELIT P116 R41 V4 NO-RING PREFLIGHT ===")


def run_attempt(args: argparse.Namespace) -> int:
    state = AttemptState()
    timeout_seconds = validate_timeout_seconds(args.timeout_seconds)
    control: ControlClient | None = None
    logcat: PersistentSafeLogcat | None = None
    failsafe: subprocess.Popen[str] | None = None
    run_root: Path | None = None
    exit_code = 1

    try:
        state.last_step = "APPROVAL"
        if os.environ.get("R41_APPROVAL", "") != APPROVAL_TOKEN:
            raise AttemptEnd(64, "BLOCKED_APPROVAL_REQUIRED")
        state.approval_granted = True
        if os.geteuid() != 0:
            raise AttemptEnd(65, "BLOCKED_ROOT_REQUIRED")
        if not _ATTEMPT_RE.fullmatch(args.attempt_id):
            raise AttemptEnd(66, "BLOCKED_ATTEMPT_ID_INVALID")

        cursor_model, readiness = load_models()
        control_url = read_control_url(Path(args.control_url_file))
        control = ControlClient(control_url, curl_path=args.curl)

        run_root = Path(args.run_root) / args.attempt_id
        run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        os.chmod(run_root, 0o700)
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

        state.last_step = "CAPTURE_PRE_PAUSE_CURSOR"
        state.pre_pause_log_cursor = logcat.capture_cursor()
        _write_private(run_root / "pause-started", "true\n")

        state.last_step = "PAUSE_LISTENER"
        state.pause_maybe_accepted = True
        state.listener_pause_count = 1
        try:
            control.post("stop", timeout=20)
        except Exception:
            raise AttemptEnd(22, "BLOCKED_LISTENER_PAUSE_AMBIGUOUS")
        if not sample_twice(control, status_paused):
            raise AttemptEnd(23, "BLOCKED_LISTENER_PAUSE_NOT_CONFIRMED")

        # Reject stale operator input written before pause confirmation.
        try:
            ui_file.unlink()
        except FileNotFoundError:
            pass
        print("R41_OPERATOR_UI_STATE_SAMPLE_NOW=true")

        state.last_step = "WAIT_APP_READY"
        deadline = time.monotonic() + timeout_seconds
        candidate_since: float | None = None
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
                            state.result = "PASS_APP_READY_PREFLIGHT"
                            exit_code = 0
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
            state.result = "BLOCKED_APP_NOT_READY"
            exit_code = 20

    except AttemptEnd as end:
        state.result = end.result
        exit_code = end.code
    except KeyboardInterrupt:
        state.result = "BLOCKED_INTERRUPTED"
        exit_code = 130
    except Exception as exc:
        state.result = f"FAIL_{type(exc).__name__.upper()}"
        exit_code = 1
    finally:
        if state.pause_maybe_accepted and control is not None:
            if not restore_listener_once(control, state):
                state.result = "FAIL_LISTENER_RESTORE"
                exit_code = 90
            elif run_root is not None and failsafe is not None:
                state.failsafe_outcome = disarm_failsafe(run_root, failsafe)
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
    p.add_argument("--_failsafe-child", metavar="RUN_ROOT", default=None)
    args = p.parse_args(argv)
    if args._failsafe_child is None and (not args.control_url_file or not args.adb_serial):
        p.error("--control-url-file and --adb-serial are required")
    return args


def _install_signal_handlers() -> None:
    def _interrupt(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args._failsafe_child is not None:
        return _failsafe_child(Path(args._failsafe_child))
    _install_signal_handlers()
    return run_attempt(args)


if __name__ == "__main__":
    raise SystemExit(main())
