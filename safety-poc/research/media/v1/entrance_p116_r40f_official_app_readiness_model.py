"""P116 R40F -- overlay on the R40 offline OFFICIAL_APP_READY / PHYSICAL_RING_ALLOWED gate model.

Reads no network, sends no packet, makes no protocol call, contacts no device. Does not rewrite
`entrance_p116_r40_official_app_readiness_model.py` (R40 stays intact and importable); this module
narrows that model's `OperatorAppState.OPERATOR_CONFIRMED_USABLE` abstraction now that R40F re-derived
CHILD A/B/C from the raw recovered `dex7/8/9` official-app sources (not available to R40) and found two
real, non-call-scoped, pre-call signals R40 could not cite:

1. A proven UI signal: `com.comelitgroup.comelit_material_design.toolbar.ToolbarDeviceConnectionStatus`
   (`NOT_CONNECTED` / `CONNECTING` / `CONNECTED`), rendered on the VIP door-entry screen's own toolbar
   (`dex7/sources/com/comelit/bigapp/fragment/doorentry/DoorEntryContentFragment.java`, via
   `ToolbarUtils.defaultVipConnectionStatusAction`), and bound 1:1 by
   `dex7/sources/com/comelit/bigapp/utilities/ToolbarUtilsKt.asToolbarConnectionStatus` to
   `com.comelit.bigapp.application.ComelitStatus$RegisterStatus` (`NONE`/`NOT_REGISTERED` ->
   `NOT_CONNECTED`, `REGISTERING` -> `CONNECTING`, `REGISTERED` -> `CONNECTED`). This is a real, cited,
   pre-call app string/icon an operator can read directly off the door-entry screen -- not an invented
   label.
2. A machine-observable signal: the same `ComelitStatus.RegisterStatus` state machine is set from a
   native bridge event, `subunit_fsm_status_change` with field `subunit_fsm_status` in
   {"registering", "fail_wait", "registered"}
   (`dex7/sources/com/comelit/bigapp/application/jsonsocket/ReadFromJsonSocket.java`), independent of any
   call object, and exposed to app code as `ComelitFlowStatus.vipConnectionStatus`
   (`kotlinx.coroutines.flow.StateFlow`) and `.vipConnectionStatusLiveData`
   (`androidx.lifecycle.LiveData`) -- both readable without decoding any VIP/CTPP payload.

R40F CHILD H therefore updates the R40 model per its own instructions ("if a UI state is proven the
operator state must match that exact proven UI state ... if both, use both"): this module replaces the
abstract `OPERATOR_CONFIRMED_USABLE` judgement call with the concrete, cited `ToolbarDeviceConnectionStatus`
enum the operator is asked to literally read off the door-entry screen, and adds an optional
`registration_ready_seen: bool | None` scalar for the machine signal -- deliberately a plain boolean, not
a payload capture, per R40F CHILD C's explicit instruction not to propose committing payload. R40's
network-context non-load-bearing invariant (TLS/STUN/UDP-keepalive alone must never unlock readiness,
the direct lesson of R39) is preserved unchanged.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class OfficialAppUiConnectionState(enum.Enum):
    """The exact, cited VIP toolbar connection status shown on the official app's own door-entry
    screen (`DoorEntryContentFragment`), per `ToolbarDeviceConnectionStatus`. Not an abstract judgement
    call -- the operator is asked to read this literal label/icon off the screen."""

    UNKNOWN = "unknown"
    NOT_CONNECTED = "not_connected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class ListenerState(enum.Enum):
    """Production Ring/Door listener lifecycle state, as already observed by existing read-only
    status surfaces (unchanged from R40)."""

    UNKNOWN = "unknown"
    READY = "ready"
    PAUSED = "paused"
    DOWN = "down"


REQUIRED_UI_STATE_FOR_READY = OfficialAppUiConnectionState.CONNECTED


@dataclass(frozen=True)
class NetworkContextScalars:
    """Optional, auxiliary, non-load-bearing network context. Never read by `evaluate_readiness`.
    Unchanged from R40 -- kept for report continuity only."""

    tls_session_present: bool = False
    stun_present: bool = False
    udp_keepalive_present: bool = False
    peer_count: int = 0


def network_context_from_transport_categories(
    transport_categories: dict, peer_count: int = 0
) -> NetworkContextScalars:
    """Build a `NetworkContextScalars` from a trace-model `transport_categories` dict. Reads no
    network itself -- the dict is already-computed, offline, safe-scalar output. Unchanged from R40."""

    return NetworkContextScalars(
        tls_session_present=bool(transport_categories.get("TCP_443_TLS_LIKE", 0)),
        stun_present=bool(transport_categories.get("STUN", 0)),
        udp_keepalive_present=bool(transport_categories.get("UDP_KEEPALIVE_CANDIDATE", 0)),
        peer_count=int(peer_count),
    )


@dataclass(frozen=True)
class ReadinessObservation:
    ui_state: OfficialAppUiConnectionState
    listener_state: ListenerState
    ring_budget_available: bool
    # None = machine signal not sampled this attempt (offline-safe default; no instrumentation
    # required). True/False = an operator or a future instrumented reader explicitly reported the
    # `ComelitFlowStatus.vipConnectionStatus` value at sample time, as the boolean
    # `RegistrationStatus == REGISTERED`. Never a payload capture.
    registration_ready_seen: Optional[bool] = None
    network_context: NetworkContextScalars = field(default_factory=NetworkContextScalars)


@dataclass(frozen=True)
class ReadinessVerdict:
    official_app_ready: str  # "true" | "false" | "UNPROVEN"
    physical_ring_allowed: bool
    reason: str


def evaluate_readiness(observation: ReadinessObservation) -> ReadinessVerdict:
    """Fail-closed gate. Any missing/ambiguous/unknown required signal returns UNPROVEN readiness and
    `physical_ring_allowed=False`.

    Precedence, per R40F CHILD H ("if both, use both"):
    1. UI state must be the proven `CONNECTED` toolbar label -- anything else (including `UNKNOWN`)
       blocks readiness exactly as R40's `OPERATOR_CONFIRMED_USABLE` did, but now anchored to a cited
       app string instead of an abstract judgement.
    2. If the machine signal (`registration_ready_seen`) was explicitly sampled and is `False`, it
       overrides a `CONNECTED` UI read (contradicting machine state wins, fail-closed) -- e.g. a stale
       or misread icon must not grant a ring. If it is `True`, it corroborates the UI signal. If it is
       `None` (not sampled), the gate proceeds on the UI signal alone, exactly as R40 did with the
       operator judgement, but the reason string records that the machine signal was not cross-checked.
    3. Listener/ring-budget gating is unchanged from R40: a ring is only permitted while the listener is
       confirmed `PAUSED` (a ring while `READY` reaches the listener, not the app -- the exact R39
       failure mode) and a ring budget is available.
    """

    if not isinstance(observation.ui_state, OfficialAppUiConnectionState):
        return ReadinessVerdict("UNPROVEN", False, "missing_or_ambiguous_ui_state")

    if observation.ui_state is OfficialAppUiConnectionState.UNKNOWN:
        return ReadinessVerdict("UNPROVEN", False, "ui_state_unknown")

    if observation.ui_state is not REQUIRED_UI_STATE_FOR_READY:
        return ReadinessVerdict("false", False, "ui_state_not_connected")

    if observation.registration_ready_seen is False:
        return ReadinessVerdict(
            "false", False, "machine_registration_signal_contradicts_connected_ui"
        )

    if not isinstance(observation.listener_state, ListenerState) or observation.listener_state is ListenerState.UNKNOWN:
        return ReadinessVerdict("UNPROVEN", False, "listener_state_unknown")

    if observation.listener_state is ListenerState.READY:
        return ReadinessVerdict("false", False, "listener_ready_ring_would_reach_listener_not_app")

    if observation.listener_state is ListenerState.DOWN:
        return ReadinessVerdict("false", False, "listener_down_not_a_safe_paused_window")

    # observation.listener_state is ListenerState.PAUSED from here on.
    if not observation.ring_budget_available:
        reason = (
            "app_ready_but_ring_budget_unavailable"
            if observation.registration_ready_seen is not None
            else "app_ready_but_ring_budget_unavailable_machine_signal_not_sampled"
        )
        return ReadinessVerdict("true", False, reason)

    reason = (
        "connected_ui_confirmed_by_machine_signal_listener_paused_ring_budget_available"
        if observation.registration_ready_seen is True
        else "connected_ui_listener_paused_ring_budget_available_machine_signal_not_sampled"
    )
    return ReadinessVerdict("true", True, reason)


def assert_network_context_not_load_bearing(observation: ReadinessObservation) -> None:
    """Fail closed on the invariant itself: recompute the verdict with the SAME observation but with
    network context blanked out, and require the readiness/ring fields to be unchanged. Raises
    AssertionError if a future edit ever makes `evaluate_readiness` read `network_context`. Unchanged
    from R40."""

    with_context = evaluate_readiness(observation)
    blanked = ReadinessObservation(
        ui_state=observation.ui_state,
        listener_state=observation.listener_state,
        ring_budget_available=observation.ring_budget_available,
        registration_ready_seen=observation.registration_ready_seen,
        network_context=NetworkContextScalars(),
    )
    without_context = evaluate_readiness(blanked)
    if (with_context.official_app_ready, with_context.physical_ring_allowed) != (
        without_context.official_app_ready,
        without_context.physical_ring_allowed,
    ):
        raise AssertionError("network_context_became_load_bearing_for_readiness")
