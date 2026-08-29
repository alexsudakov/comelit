from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"


@dataclass(frozen=True)
class ReadinessGate:
    marker: str
    expected: str
    status: GateStatus
    actual: str | None


@dataclass(frozen=True)
class TransportReadinessReport:
    gates: tuple[ReadinessGate, ...]
    repository_ready: bool
    live_test_ready: bool

    @property
    def missing_or_failed(self) -> tuple[ReadinessGate, ...]:
        return tuple(gate for gate in self.gates if gate.status != GateStatus.PASS)


REPOSITORY_GATES: tuple[tuple[str, str], ...] = (
    ("CANONICAL_VIP_SOURCE_HASHES", "PASS"),
    ("LEGACY_RESEARCH_SOURCE_HASH", "PASS"),
    ("CTPP_BODY_LAYOUT_RECONCILIATION", "PASS"),
    ("CTPP_CONTROL_PLANE_RECONCILIATION", "PASS"),
    ("FULL_OFFLINE_DOOR_TRANSACTION", "PASS"),
    ("TRANSPORT_BOUNDARY_CONTRACT", "PASS"),
    ("BOUNDARY_ATTEMPT_NUMBER_FIXED", "1"),
    ("AUTO_RETRY_IMPLEMENTED", "false"),
    ("PHYSICAL_EFFECT_ASSERTION_ALLOWED", "false"),
)

LIVE_GATES: tuple[tuple[str, str], ...] = (
    ("REAL_TRANSPORT_IMPLEMENTED", "true"),
    ("REAL_TRANSPORT_READONLY_SESSION_PROOF", "PASS"),
    ("TARGET_BINDING_VERIFIED", "PASS"),
    ("AUTH_SESSION_LIFETIME_VERIFIED", "PASS"),
    ("TIMEOUT_MAPPING_VERIFIED", "PASS"),
    ("AUDIT_SINK_VERIFIED", "PASS"),
    ("EXPLICIT_LIVE_TEST_APPROVAL", "true"),
)


def evaluate_readiness(evidence: Mapping[str, str]) -> TransportReadinessReport:
    gates: list[ReadinessGate] = []
    for marker, expected in REPOSITORY_GATES + LIVE_GATES:
        actual = evidence.get(marker)
        if actual is None:
            status = GateStatus.MISSING
        elif actual == expected:
            status = GateStatus.PASS
        else:
            status = GateStatus.FAIL
        gates.append(ReadinessGate(marker, expected, status, actual))

    repo_markers = {marker for marker, _ in REPOSITORY_GATES}
    repository_ready = all(gate.status == GateStatus.PASS for gate in gates if gate.marker in repo_markers)
    live_markers = {marker for marker, _ in LIVE_GATES}
    live_test_ready = repository_ready and all(gate.status == GateStatus.PASS for gate in gates if gate.marker in live_markers)
    return TransportReadinessReport(tuple(gates), repository_ready, live_test_ready)


def parse_markers(text: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key.replace("_", "").isalnum():
            markers[key] = value
    return markers
