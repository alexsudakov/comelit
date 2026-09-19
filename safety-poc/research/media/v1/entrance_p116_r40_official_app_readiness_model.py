"""P116 R40 -- offline OFFICIAL_APP_READY / PHYSICAL_RING_ALLOWED gate model.

Reads no network, sends no packet, makes no protocol call, contacts no device. This module only
combines already-available, offline inputs (an operator's own attested observation of the official
app, the already-known listener lifecycle state, and -- purely as non-load-bearing context -- safe
transport-category scalars of the shape `entrance_p116_r39_phone_capture_trace_model.py` emits) into a
fail-closed `OFFICIAL_APP_READY` / `PHYSICAL_RING_ALLOWED` verdict.

Why an operator-attested state, not a cited in-app UI label: R40 CHILD B searched the already-staged
official-app evidence (the `P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md` SECTION 14 search
ledger, and every later R29-R37 document) for a pre-call "connected/online/registered" screen or
indicator and found none -- only call-scoped preview states (`VipCallNotConnected`,
`previewImageBytes`) that exist AFTER a call notification has already arrived. Inventing a label for a
screen nobody has proven to exist is exactly the "never invent a label" prohibition this round operates
under, so readiness here is recorded as an operator judgement call, not a cited app string.

Why network-transport scalars can never promote readiness by themselves: the R39 capture
(`P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md`) showed a persistent TLS session, STUN contact and a sustained
small-packet UDP keepalive flow for the entire 258-second paused window while the official app never
became ready. `evaluate_readiness` below never reads `NetworkContextScalars` at all -- it is accepted
only so a caller can attach it to a report -- and `assert_network_context_not_load_bearing` exists so a
test can assert that fact stays true even if the state machine is edited later.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class OperatorAppState(enum.Enum):
    """Operator judgement of the official app, reported after the operator looks at their own
    phone. Not a cited UI label (see module docstring)."""

    UNKNOWN = "unknown"
    NOT_OPENED = "not_opened"
    LOADING_OR_RECONNECTING = "loading_or_reconnecting"
    ERROR_OR_OFFLINE = "error_or_offline"
    OPERATOR_CONFIRMED_USABLE = "operator_confirmed_usable"


class ListenerState(enum.Enum):
    """Production Ring/Door listener lifecycle state, as already observed by existing read-only
    status surfaces (unchanged by this module)."""

    UNKNOWN = "unknown"
    READY = "ready"
    PAUSED = "paused"
    DOWN = "down"


REQUIRED_OPERATOR_STATE_FOR_READY = OperatorAppState.OPERATOR_CONFIRMED_USABLE


@dataclass(frozen=True)
class NetworkContextScalars:
    """Optional, auxiliary, non-load-bearing network context. Never read by `evaluate_readiness`;
    kept only so a report can carry it alongside the verdict. Mirrors the safe scalar shape of
    `entrance_p116_r39_phone_capture_trace_model.py`'s `transport_categories`."""

    tls_session_present: bool = False
    stun_present: bool = False
    udp_keepalive_present: bool = False
    peer_count: int = 0


def network_context_from_transport_categories(
    transport_categories: dict, peer_count: int = 0
) -> NetworkContextScalars:
    """Build a `NetworkContextScalars` from a trace-model `transport_categories` dict, e.g. the
    output of `entrance_p116_r39_phone_capture_trace_model.summarise_capture(...)`. Reads no network
    itself -- the dict is already-computed, offline, safe-scalar output."""

    return NetworkContextScalars(
        tls_session_present=bool(transport_categories.get("TCP_443_TLS_LIKE", 0)),
        stun_present=bool(transport_categories.get("STUN", 0)),
        udp_keepalive_present=bool(transport_categories.get("UDP_KEEPALIVE_CANDIDATE", 0)),
        peer_count=int(peer_count),
    )


@dataclass(frozen=True)
class ReadinessObservation:
    operator_app_state: OperatorAppState
    listener_state: ListenerState
    ring_budget_available: bool
    network_context: NetworkContextScalars = field(default_factory=NetworkContextScalars)


@dataclass(frozen=True)
class ReadinessVerdict:
    official_app_ready: str  # "true" | "false" | "UNPROVEN"
    physical_ring_allowed: bool
    reason: str


def evaluate_readiness(observation: ReadinessObservation) -> ReadinessVerdict:
    """Fail-closed gate. Any missing/ambiguous/unknown required signal returns UNPROVEN readiness
    and `physical_ring_allowed=False`. Ring permission is granted only when the operator has
    positively confirmed the app usable AND the listener is confirmed paused (a ring while the
    listener is READY reaches the listener, not the app -- exactly the R39 failure mode) AND a ring
    budget is available for this attempt."""

    if not isinstance(observation.operator_app_state, OperatorAppState):
        return ReadinessVerdict("UNPROVEN", False, "missing_or_ambiguous_operator_app_state")

    if observation.operator_app_state is OperatorAppState.UNKNOWN:
        return ReadinessVerdict("UNPROVEN", False, "operator_app_state_unknown")

    if observation.operator_app_state is not REQUIRED_OPERATOR_STATE_FOR_READY:
        return ReadinessVerdict("false", False, "operator_app_state_not_confirmed_usable")

    if not isinstance(observation.listener_state, ListenerState) or observation.listener_state is ListenerState.UNKNOWN:
        return ReadinessVerdict("UNPROVEN", False, "listener_state_unknown")

    if observation.listener_state is ListenerState.READY:
        return ReadinessVerdict("false", False, "listener_ready_ring_would_reach_listener_not_app")

    if observation.listener_state is ListenerState.DOWN:
        return ReadinessVerdict("false", False, "listener_down_not_a_safe_paused_window")

    # observation.listener_state is ListenerState.PAUSED from here on.
    if not observation.ring_budget_available:
        return ReadinessVerdict("true", False, "app_ready_but_ring_budget_unavailable")

    return ReadinessVerdict(
        "true", True, "operator_confirmed_usable_listener_paused_ring_budget_available"
    )


def assert_network_context_not_load_bearing(observation: ReadinessObservation) -> None:
    """Fail closed on the invariant itself: recompute the verdict with the SAME observation but with
    network context blanked out, and require the readiness/ring fields to be unchanged. Raises
    AssertionError if a future edit ever makes `evaluate_readiness` read `network_context`."""

    with_context = evaluate_readiness(observation)
    blanked = ReadinessObservation(
        operator_app_state=observation.operator_app_state,
        listener_state=observation.listener_state,
        ring_budget_available=observation.ring_budget_available,
        network_context=NetworkContextScalars(),
    )
    without_context = evaluate_readiness(blanked)
    if (with_context.official_app_ready, with_context.physical_ring_allowed) != (
        without_context.official_app_ready,
        without_context.physical_ring_allowed,
    ):
        raise AssertionError("network_context_became_load_bearing_for_readiness")
