from __future__ import annotations

import hashlib
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .p13_actuation_boundary import CtppOpenOutcome, P13DoorSession, P13PayloadBundle

EXPECTED_WRITE_COUNT = 6


@dataclass(frozen=True)
class Ct120ArtifactSpec:
    """Pinned identity of the CT120 real transport artifacts.

    The wrapper is the single native entrypoint that performs the proven
    Cloud P2P -> ICE -> PseudoTCP -> ViP -> UAUT -> CTPP session and the six
    prepared Door writes in one process.  All artifacts are root-only; the
    repository pins only hashes and expected modes.  Both the wrapper and the
    payload must be owned by uid 0.
    """

    wrapper: Path
    wrapper_sha256: str
    wrapper_mode: str = "700"
    payload_file: Path = Path("/root/comelit-p13-actuator-prep/real-door-payloads.json")
    payload_mode: str = "600"
    require_root_owner: bool = True

    def verify(self) -> None:
        if not self.wrapper.is_file():
            raise FileNotFoundError(f"P13 real wrapper absent: {self.wrapper}")
        actual = hashlib.sha256(self.wrapper.read_bytes()).hexdigest()
        if actual != self.wrapper_sha256:
            raise ValueError("P13 real wrapper SHA-256 mismatch")
        mode = oct(self.wrapper.stat().st_mode & 0o777)[2:]
        if mode != self.wrapper_mode:
            raise ValueError(f"P13 real wrapper mode mismatch: {mode}")
        if self.require_root_owner and self.wrapper.stat().st_uid != 0:
            raise ValueError("P13 real wrapper owner must be uid 0")
        if not self.payload_file.is_file():
            raise FileNotFoundError(f"P13 payload file absent: {self.payload_file}")
        pmode = oct(self.payload_file.stat().st_mode & 0o777)[2:]
        if pmode != self.payload_mode:
            raise ValueError(f"P13 payload file mode mismatch: {pmode}")
        if self.require_root_owner and self.payload_file.stat().st_uid != 0:
            raise ValueError("P13 payload file owner must be uid 0")


class Ct120RealP13Session(P13DoorSession):
    """Concrete CT120 real actuation session.

    Exactly one wrapper invocation performs the whole proven transaction:
    Cloud signaling -> ICE -> PseudoTCP -> ViP -> UAUT open/auth -> CTPP open ->
    six prepared Door writes -> CTPP close -> teardown.  There is no retry
    loop in this adapter, and a single ``operation_id`` maps to a single
    invocation.

    The wrapper protocol is typed markers on stdout:

    - ``P13_CTPP_OPEN_OUTCOME=OPENED|AMBIGUOUS|PROVEN_NOT_OPENED|REJECTED``
    - ``P13_DOOR_WRITE_COUNT=N``
    - ``P13_CTPP_CLOSE=PASS|FAIL``
    - ``P13_TEARDOWN=PASS``

    The wrapper's markers are validated as one consistent transaction report.
    A nonzero exit status or a timeout makes the result AMBIGUOUS even when
    markers look complete, because the process may have transmitted after the
    last observable marker.  ``teardown()`` never synthesizes PASS: it can
    only report what the wrapper actually emitted.
    """

    def __init__(
        self,
        spec: Ct120ArtifactSpec,
        bundle: P13PayloadBundle,
        *,
        run_dir: Path = Path("/root/comelit-p13-run"),
        timeout_seconds: float = 120.0,
        term_grace_seconds: float = 5.0,
        dry_init: bool = False,
    ):
        self.spec = spec
        self.bundle = bundle
        self.run_dir = Path(run_dir)
        self.timeout_seconds = timeout_seconds
        self.term_grace_seconds = term_grace_seconds
        self.started = False
        self._log_path: Path | None = None
        self._log_text = ""
        self._open_outcome: CtppOpenOutcome | None = None
        self._reported_write_count = 0
        self._boundary_write_count = 0
        self._close_ok = False
        self._teardown_ok = False
        self._process_rc: int | None = None
        self._timeout_observed = False
        self._report_valid = False
        if dry_init:
            self.spec.verify()
            self.bundle.verify()

    # -- identity / dry initialization ------------------------------------

    def dry_initialize(self) -> dict[str, str]:
        """Non-actuating proof that the real adapter is installed and pinned."""
        self.spec.verify()
        self.bundle.verify()
        return {
            "P13_REAL_ADAPTER_CONSTRUCTED": "true",
            "P13_REAL_WRAPPER_PRESENT": "true",
            "P13_REAL_WRAPPER_SHA256": self.spec.wrapper_sha256,
            "P13_REAL_ADAPTER_BOUND_HEAD": "verified",
        }

    # -- typed session protocol -------------------------------------------

    def open_ctpp(self) -> CtppOpenOutcome:
        if self.started:
            raise AssertionError("P13 real session already started; one invocation only")
        self.started = True
        self._run_wrapper_once()
        if self._open_outcome is not None:
            return self._open_outcome
        # No typed open marker: the process died/timed out after the open
        # request may have been transmitted -> conservative.
        return CtppOpenOutcome.AMBIGUOUS

    def write_door_body(self, body_hex: str) -> None:
        # The wrapper already emitted all six prepared bodies in its single
        # run.  This method validates that the boundary is walking the exact
        # prepared bodies in order, so the boundary still enforces the
        # exact-six-writes invariant locally.
        if self._boundary_write_count >= self.bundle.write_count:
            raise RuntimeError("P13 real session write count exceeds prepared bundle")
        digest = hashlib.sha256(bytes.fromhex(body_hex)).hexdigest()
        expected = self.bundle.write_sha256[self._boundary_write_count]
        if digest != expected:
            raise RuntimeError("P13 real session body does not match prepared bundle")
        self._boundary_write_count += 1

    def close_ctpp(self) -> bool:
        # The wrapper must have reported exactly six Door writes, the boundary
        # must have walked exactly six prepared bodies, the wrapper process
        # must have exited cleanly, and the report must be consistent.  Any
        # mismatch is conservative -> the boundary maps the raised error to
        # AMBIGUOUS.
        if not self._report_valid:
            raise RuntimeError("P13 real session wrapper report is not a consistent transaction")
        if self._boundary_write_count != EXPECTED_WRITE_COUNT or self._reported_write_count != EXPECTED_WRITE_COUNT:
            raise RuntimeError(
                "P13 real session write-count mismatch "
                f"(boundary={self._boundary_write_count} reported={self._reported_write_count})"
            )
        return self._close_ok

    def teardown(self) -> bool:
        # Never synthesize PASS: report only what the wrapper actually proved.
        return self._teardown_ok

    # -- internals ---------------------------------------------------------

    def _run_wrapper_once(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_dir, 0o700)
        self._log_path = self.run_dir / "p13-live-run.log"
        timeout_occurred = False
        with self._log_path.open("wb") as output:
            os.chmod(self._log_path, 0o600)
            proc = subprocess.Popen(
                [str(self.spec.wrapper)],
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            try:
                proc.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                timeout_occurred = True
                self._signal_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=self.term_grace_seconds)
                except subprocess.TimeoutExpired:
                    self._signal_group(proc, signal.SIGKILL)
                    proc.wait(timeout=5)
        self._process_rc = proc.returncode
        self._timeout_observed = timeout_occurred
        self._log_text = self._log_path.read_text(encoding="utf-8", errors="replace")
        self._parse_markers()
        self._validate_report()

    def _signal_group(self, proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    def _parse_markers(self) -> None:
        for line in self._log_text.splitlines():
            line = line.strip()
            if line.startswith("P13_CTPP_OPEN_OUTCOME="):
                raw = line.split("=", 1)[1]
                try:
                    self._open_outcome = CtppOpenOutcome(raw)
                except ValueError:
                    self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            elif line.startswith("P13_DOOR_WRITE_COUNT="):
                try:
                    self._reported_write_count = int(line.split("=", 1)[1])
                except ValueError:
                    self._reported_write_count = 0
            elif line.startswith("P13_CTPP_CLOSE=PASS"):
                self._close_ok = True
            elif line.startswith("P13_TEARDOWN=PASS"):
                self._teardown_ok = True

    def _validate_report(self) -> None:
        """Validate the wrapper result as one consistent transaction report.

        Fail-closed rules (all map to AMBIGUOUS, never to a successful or
        proven-not-sent classification):

        - timeout or nonzero exit after potentially sending => AMBIGUOUS
        - PROVEN_NOT_OPENED or REJECTED with write count > 0 => AMBIGUOUS
        - missing/invalid open marker => AMBIGUOUS
        - OPENED with partial writes (not exactly six) => AMBIGUOUS
        - six writes with missing/failed close => AMBIGUOUS
        - six writes with missing teardown => AMBIGUOUS
        """
        if self._timeout_observed or self._process_rc != 0:
            # The process may have transmitted after the last observable
            # marker; a crashed or timed-out run is never a proven clean
            # transaction.
            self._report_valid = False
            self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            self._close_ok = False
            self._teardown_ok = False
            return

        if self._open_outcome is None:
            self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            self._report_valid = False
            return

        if self._open_outcome in (CtppOpenOutcome.PROVEN_NOT_OPENED, CtppOpenOutcome.REJECTED):
            if self._reported_write_count > 0:
                # Contradictory report: claims no open yet counts Door writes.
                self._open_outcome = CtppOpenOutcome.AMBIGUOUS
                self._report_valid = False
                return
            self._report_valid = True
            return

        if self._open_outcome == CtppOpenOutcome.AMBIGUOUS:
            self._report_valid = False
            return

        # OPENED: exactly six writes, clean close, proven teardown required.
        if self._reported_write_count != EXPECTED_WRITE_COUNT:
            self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            self._report_valid = False
            return
        if not self._close_ok:
            self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            self._report_valid = False
            return
        if not self._teardown_ok:
            self._open_outcome = CtppOpenOutcome.AMBIGUOUS
            self._report_valid = False
            return
        self._report_valid = True
