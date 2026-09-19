"""P116 R40H -- narrow overlay on the R40G `evaluate_readiness_v2` official-app readiness gate.

Reads no network, sends no packet, makes no protocol call, contacts no device. Does not rewrite
`entrance_p116_r40g_official_app_readiness_model.py` (R40G stays intact and importable); this module
wraps it and adds exactly one new, load-bearing precondition R40H CHILD A/G found missing.

R40H CHILD G verdict: `R40G_MODEL_SEMANTICS=TOO_PERMISSIVE`. R40G's `evaluate_readiness_v2` accepts a
`registration_ready_seen` scalar sampled as a simple *current-state* boolean (`RegisterStatus ==
REGISTERED` at sample time), with no freshness requirement and no cross-check against the independent
transport-failure signal R40H CHILD E/F found (`ViperSocketReaderRunnable`'s "VIPER SOCKET CONNECTION
LOST", a different tag/thread than `ComelitStatus.regStatus`). A stale `REGISTERED` value that predates
the observation window entirely -- R40G CHILD D's silent-staleness risk -- can still pass v2's gate
unchanged, because v2 never asks *when* the state last changed.

This overlay adds a mandatory, fail-closed precondition: a `FreshRegistrationVerdict` (from
`entrance_p116_r40h_registration_log_model`, itself derived only from logcat lines strictly after this
attempt's `PRE_PAUSE_LOG_CURSOR`) whose `registration_ready_fresh_scalar` is `True`. Absent that, the
overlay refuses to produce a readiness verdict at all -- a current `CONNECTED` UI read is not, by
itself, sufficient. Every other gate (system class, listener state, ring budget, the R40G/R40F
fail-closed logic) is reused unmodified by delegation to `evaluate_readiness_v2`, never duplicated.
"""

from __future__ import annotations

import dataclasses as _dataclasses
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

_R40G_PATH = Path(__file__).resolve().parent / "entrance_p116_r40g_official_app_readiness_model.py"
_LOG_MODEL_PATH = Path(__file__).resolve().parent / "entrance_p116_r40h_registration_log_model.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


_r40g = _load(_R40G_PATH, "p116_r40g_readiness_model_dep_from_r40h")
_log_model = _load(_LOG_MODEL_PATH, "p116_r40h_registration_log_model_dep")

# Re-exported unchanged from R40G/R40F -- this module never redefines these types.
AppSystemClass = _r40g.AppSystemClass
OfficialAppUiConnectionState = _r40g.OfficialAppUiConnectionState
ListenerState = _r40g.ListenerState
ReadinessObservation = _r40g.ReadinessObservation
ReadinessVerdict = _r40g.ReadinessVerdict
FreshRegistrationVerdict = _log_model.FreshRegistrationVerdict


@dataclass(frozen=True)
class ReadinessObservationV3:
    system_class: AppSystemClass
    observation: ReadinessObservation
    fresh_registration: FreshRegistrationVerdict


_FRESH_VERDICT_REQUIRED_FIELDS = (
    "fresh_registered_transition_seen",
    "registration_ready_fresh_scalar",
    "transport_failure_after_transition",
)


def _structural_fresh_verdict(fresh):
    """Structural (duck-typed) validation of the fresh-registration verdict.

    Deliberately NOT an `isinstance` check on a specific class object: this module and its tests load
    `entrance_p116_r40h_registration_log_model.py` under different `importlib` spec names, which
    produces two distinct class objects for the same source file. Coupling the gate to class identity
    would make readiness depend on the caller's module-loading details instead of on evidence, so the
    gate validates the three load-bearing fields instead. `None`, or an object missing any of them, is
    still refused fail-closed by the caller.
    """

    if fresh is None:
        return None
    if not all(hasattr(fresh, field) for field in _FRESH_VERDICT_REQUIRED_FIELDS):
        return None
    return fresh


def evaluate_readiness_v3(observation_v3: ReadinessObservationV3) -> ReadinessVerdict:
    """Fail-closed gate, per R40H CHILD G. Requires
    `fresh_registration.registration_ready_fresh_scalar is True` -- a current CONNECTED UI read /
    `registration_ready_seen=True` sample with no fresh, uninvalidated transition observed after this
    attempt's log cursor is refused outright, not merely down-weighted. Only once that precondition
    holds does this function delegate to R40G's `evaluate_readiness_v2` for every other gate.

    The fresh transition is the strictly stronger form of the same underlying field R40G CHILD D showed
    `registration_ready_seen` reads (`ComelitStatus.RegisterStatus`), so when it holds this overlay
    supplies `registration_ready_seen=True` to the delegated gate rather than leaving the older,
    weaker current-state scalar unsampled -- otherwise the delegated gate would report `UNPROVEN`
    purely because of the superseded scalar, not because of any missing evidence."""

    fresh = _structural_fresh_verdict(observation_v3.fresh_registration)
    if fresh is None:
        return ReadinessVerdict("UNPROVEN", False, "missing_or_ambiguous_fresh_registration_evidence")

    if not fresh.registration_ready_fresh_scalar:
        reason = (
            "transport_failure_after_fresh_transition_registration_not_trustworthy"
            if fresh.transport_failure_after_transition
            else "no_fresh_registered_transition_observed_after_attempt_boundary_current_state_insufficient"
        )
        return ReadinessVerdict("UNPROVEN", False, reason)

    if observation_v3.observation.registration_ready_seen is False:
        return ReadinessVerdict(
            "false", False, "machine_registration_signal_contradicts_fresh_registration_transition"
        )

    v2_obs = _r40g.ReadinessObservationV2(
        system_class=observation_v3.system_class,
        observation=_dataclasses.replace(observation_v3.observation, registration_ready_seen=True),
    )
    verdict = _r40g.evaluate_readiness_v2(v2_obs)
    if verdict.official_app_ready == "true":
        return ReadinessVerdict(
            verdict.official_app_ready,
            verdict.physical_ring_allowed,
            verdict.reason + "_fresh_registration_confirmed_per_r40h",
        )
    return verdict
