"""P116 R40G -- narrow overlay on the R40F offline OFFICIAL_APP_READY / PHYSICAL_RING_ALLOWED gate model.

Reads no network, sends no packet, makes no protocol call, contacts no device. Does not rewrite
`entrance_p116_r40f_official_app_readiness_model.py` (R40F stays intact and importable); this module wraps
it and adds exactly one load-bearing precondition R40G CHILD A/E found missing from that model.

R40G CHILD A traced the actual dex7 (`com.comelit.bigapp.*`, "BigApp" legacy engine) vs. dex9
(`com.comelitgroup.sdk.*` incoming-call SDK) runtime relationship with real call/import evidence (not "same
APK implies same path"): `Systems.isLegacySystem()` (`getApartmentId() == null`) is the actual runtime
switch. For a legacy, on-premise VIP-tunnel system (this project's hardware class), `CallStart` arrives over
the native JSON-socket bridge already traced by R40F, gated by `ComelitStatus.RegisterStatus` -- exactly what
R40F's model already models. For a cloud/apartmentId-registered system, `CallStart` instead arrives via
Firebase push through the dex9 `ComelitSDKAndroid`/`CallService`/`CallManager` pipeline, which never reads
`ComelitStatus.RegisterStatus` at all. R40F's model did not state this scope boundary, so as written it reads
as generally applicable to "the official app," which CHILD A disproves for the non-legacy system class.

This overlay adds an explicit `AppSystemClass` precondition: `evaluate_readiness_v2` refuses to produce a
readiness verdict at all (returns `UNPROVEN`) unless the caller states the system being evaluated is
`LEGACY_VIP` -- the only class this model, R40F's model, or the underlying `RegisterStatus`/toolbar chain
was ever evidenced against. It also corrects the machine-signal reason string R40G CHILD D found overstated:
`registration_ready_seen` and the UI read are the same underlying `ComelitStatus.RegisterStatus` field, not
independent corroboration, so a future reader must not treat "confirmed by machine signal" as ruling out the
silent-transport-staleness case CHILD D identified. No other semantics change; all of R40F's fail-closed
logic (listener gating, ring-budget gating, network-context non-load-bearing invariant) is reused unmodified
by delegation, not duplicated.
"""

from __future__ import annotations

import enum
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_R40F_PATH = Path(__file__).resolve().parent / "entrance_p116_r40f_official_app_readiness_model.py"


def _load_r40f_model():
    spec = importlib.util.spec_from_file_location("p116_r40f_readiness_model_dep", _R40F_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {_R40F_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


_r40f = _load_r40f_model()

# Re-exported unchanged from R40F -- this module never redefines these types.
OfficialAppUiConnectionState = _r40f.OfficialAppUiConnectionState
ListenerState = _r40f.ListenerState
NetworkContextScalars = _r40f.NetworkContextScalars
ReadinessObservation = _r40f.ReadinessObservation
ReadinessVerdict = _r40f.ReadinessVerdict
network_context_from_transport_categories = _r40f.network_context_from_transport_categories
assert_network_context_not_load_bearing = _r40f.assert_network_context_not_load_bearing


class AppSystemClass(enum.Enum):
    """Which of the two dex7/dex9 CallStart-triggering mechanisms R40G CHILD A found actually applies
    to the system being evaluated. `ComelitStatus.RegisterStatus` (and therefore R40F's whole readiness
    chain) only ever gates the LEGACY_VIP class."""

    UNKNOWN = "unknown"
    LEGACY_VIP = "legacy_vip"
    CLOUD_REGISTERED = "cloud_registered"


REQUIRED_SYSTEM_CLASS = AppSystemClass.LEGACY_VIP


@dataclass(frozen=True)
class ReadinessObservationV2:
    system_class: AppSystemClass
    observation: ReadinessObservation


def evaluate_readiness_v2(observation_v2: ReadinessObservationV2) -> ReadinessVerdict:
    """Fail-closed gate, per R40G CHILD E. Refuses to evaluate at all outside the one system class this
    model (and R40F's underlying evidence) was ever proven against, then delegates unchanged to R40F's
    `evaluate_readiness` -- this function adds a precondition, it does not re-implement the gate."""

    if not isinstance(observation_v2.system_class, AppSystemClass):
        return ReadinessVerdict("UNPROVEN", False, "missing_or_ambiguous_app_system_class")

    if observation_v2.system_class is AppSystemClass.UNKNOWN:
        return ReadinessVerdict("UNPROVEN", False, "app_system_class_unknown")

    if observation_v2.system_class is not REQUIRED_SYSTEM_CLASS:
        return ReadinessVerdict(
            "UNPROVEN",
            False,
            "model_scoped_to_legacy_vip_dex7_bigapp_runtime_path_cloud_registered_apartmentid_systems_use_independent_dex9_sdk_callservice_path_not_covered_by_this_model",
        )

    verdict = _r40f.evaluate_readiness(observation_v2.observation)

    if observation_v2.observation.registration_ready_seen is True and "confirmed_by_machine_signal" in verdict.reason:
        return ReadinessVerdict(
            verdict.official_app_ready,
            verdict.physical_ring_allowed,
            verdict.reason
            + "_note_machine_signal_is_same_underlying_field_as_ui_read_not_independent_corroboration_per_r40g_child_d",
        )

    return verdict
