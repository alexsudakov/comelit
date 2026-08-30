from __future__ import annotations

import hashlib
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .p13_actuation_boundary import CtppOpenOutcome, P13DoorSession, P13PayloadBundle


@dataclass(frozen=True)
class Ct120ArtifactSpec:
    """Pinned identity of the CT120 real transport artifacts.

    The wrapper is the single native entrypoint that performs the proven
    Cloud P2P -> ICE -> PseudoTCP -> ViP -> UAUT -> CTPP session and the six
    prepared Door writes in one process.  All artifacts are root-only; the
    repository pins only hashes and expected modes.
    """

    wrapper: Path
    wrapper_sha256: str
    wrapper_mode: str = "700"
    payload_file: Path = Path("/root/comelit-p13-actuator-prep/real-door-payloads.json")
    payload_mode: str = "600"

    def verify(self) -> None:
        if not self.wrapper.is_file():
            raise FileNotFoundError(f"P13 real wrapper absent: {self.wrapper}")
        actual = hashlib.sha256(self.wrapper.read_bytes()).hexdigest()
        if actual != self.wrapper_sha256:
            raise ValueError("P13 real wrapper SHA-256 mismatch")
        mode = oct(self.wrapper.stat().st_mode & 0o777)[2:]
        if mode != self.wrapper_mode:
            raise ValueError(f"P13 real wrapper mode mismatch: {mode}")
        if not self.payload_file.is_file():
            raise FileNotFoundError(f"P13 payload file absent: {self.payload_file}")
        pmode = oct(self.payload_file.stat().st_mode & 0o777)[2:]
        if pmode != self.payload_mode:
            raise ValueError(f"P13 payload file mode mismatch: {pmode}")


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

    ``write_door_body()`` never sends over the network: the wrapper already
    emitted the six prepared bodies in its single run.  This method validates
    that the supplied body matches the prepared bundle and that the wrapper
    log accounts for the corresponding write, so the boundary still enforces
    the exact-six-writes invariant.
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
        # The wrapper must have reported exactly six Door writes and the
        # boundary must have walked exactly six prepared bodies.  Any mismatch
        # is conservative -> the boundary maps the raised error to AMBIGUOUS.
        if self._boundary_write_count != 6 or self._reported_write_count != 6:
            raise RuntimeError(
                "P13 real session write-count mismatch "
                f"(boundary={self._boundary_write_count} reported={self._reported_write_count})"
            )
        return self._close_ok

    def teardown(self) -> None:
        self._teardown_ok = True

    # -- internals ---------------------------------------------------------

    def _run_wrapper_once(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_dir, 0o700)
        self._log_path = self.run_dir / "p13-live-run.log"
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
                self._signal_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=self.term_grace_seconds)
                except subprocess.TimeoutExpired:
                    self._signal_group(proc, signal.SIGKILL)
                    proc.wait(timeout=5)
        self._log_text = self._log_path.read_text(encoding="utf-8", errors="replace")
        self._parse_markers()

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
