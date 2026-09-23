#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[4]
CONST = REPO_ROOT / "custom_components/comelit/const.py"
CANONICAL_GATE_MISSING_EVIDENCE = (
    (
        "GATE_TARGET_SOURCE_IDENTITY_CAPTURE",
        "PARTIAL",
        "custom_components/comelit/const.py:_DOOR_TOPOLOGY_CAPABILITIES[DOOR_GATE].ring_source=00000610; custom_components/comelit/ring_event.py:GATE_SOURCE",
    ),
    ("GATE_COMMAND_SEQUENCE_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_ACK_SEMANTICS_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_SAFETY_IDEMPOTENCY_CAPTURE", "ABSENT", "not present in repository or staged evidence"),
    ("GATE_NO_RETRY_CONTRACT_EVIDENCE", "ABSENT", "not present in repository or staged evidence"),
)


class EvidenceClass(str, Enum):
    PROVEN_STATIC = "PROVEN_STATIC"
    PROVEN_OFFLINE = "PROVEN_OFFLINE"
    OBSERVED = "OBSERVED"
    UNRESOLVED = "UNRESOLVED"


class LiteralClass(str, Enum):
    PROTOCOL_CONSTANT = "PROTOCOL_CONSTANT"
    FROZEN_NATIVE_LITERAL = "FROZEN_NATIVE_LITERAL"
    RING_IDENTITY = "RING_IDENTITY"
    CAPTURE_OBSERVED_NON_PROMOTABLE = "CAPTURE_OBSERVED_NON_PROMOTABLE"


@dataclass(frozen=True)
class ProvenanceRef:
    artifact: str
    anchor: str
    door_identity: str
    evidence_class: EvidenceClass
    literal_class: LiteralClass

    def __post_init__(self) -> None:
        if not self.artifact:
            raise ValueError("provenance artifact is required")
        if not self.anchor:
            raise ValueError("provenance anchor is required")
        if not self.door_identity:
            raise ValueError("provenance door_identity is required")


@dataclass(frozen=True)
class ProfileField:
    name: str
    value: Any
    provenance: ProvenanceRef | None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("field name is required")


@dataclass(frozen=True)
class DoorActuationProfile:
    door_identity: str
    target_source_identity: ProfileField
    command_sequence: ProfileField
    channel_allocation: ProfileField
    output_address_selector: ProfileField
    ack_semantics: ProfileField
    safety_idempotency: ProfileField
    no_retry: ProfileField
    write_count_bound: ProfileField
    validated: bool

    @property
    def fields(self) -> tuple[ProfileField, ...]:
        return (
            self.target_source_identity,
            self.command_sequence,
            self.channel_allocation,
            self.output_address_selector,
            self.ack_semantics,
            self.safety_idempotency,
            self.no_retry,
            self.write_count_bound,
        )


@dataclass(frozen=True)
class ProfileVerdict:
    valid: bool
    can_emit: bool
    reasons: tuple[str, ...]
    write_count_bound: int | None
    automatic_retry_allowed: bool


def _is_capture_promoted(field: ProfileField) -> bool:
    prov = field.provenance
    if prov is None:
        return False
    return (
        prov.evidence_class == EvidenceClass.OBSERVED
        and prov.literal_class != LiteralClass.CAPTURE_OBSERVED_NON_PROMOTABLE
    )


def validate_profile(profile: DoorActuationProfile) -> ProfileVerdict:
    reasons: list[str] = []

    if profile.door_identity not in {"entrance", "gate"}:
        reasons.append("unsupported_door_identity")

    for field in profile.fields:
        if field.provenance is None:
            reasons.append(f"unattributed_field:{field.name}")
            continue
        if field.provenance.door_identity != profile.door_identity:
            reasons.append(
                "door_identity_provenance_mismatch:"
                f"{field.name}:{field.provenance.door_identity}->{profile.door_identity}"
            )
        if _is_capture_promoted(field):
            reasons.append(f"capture_literal_promoted:{field.name}")

    write_count = profile.write_count_bound.value
    if not isinstance(write_count, int) or isinstance(write_count, bool):
        reasons.append("write_count_not_integer")
        write_count_bound: int | None = None
    else:
        write_count_bound = write_count
        if not 0 < write_count <= 5:
            reasons.append("write_count_bound_out_of_range")

    if profile.no_retry.value is not True:
        reasons.append("automatic_retry_not_forbidden")

    if profile.safety_idempotency.value != "one-shot":
        reasons.append("one_shot_safety_missing")

    if not profile.validated:
        reasons.append("profile_unvalidated")

    valid = not reasons
    return ProfileVerdict(
        valid=valid,
        can_emit=valid,
        reasons=tuple(reasons),
        write_count_bound=write_count_bound,
        automatic_retry_allowed=False,
    )


def generate_symbolic_frames(profile: DoorActuationProfile) -> tuple[Mapping[str, Any], ...]:
    verdict = validate_profile(profile)
    if not verdict.valid:
        raise ValueError("profile emission refused:" + ",".join(verdict.reasons))

    sequence = profile.command_sequence.value
    if not isinstance(sequence, tuple):
        raise ValueError("command_sequence must be a tuple")
    if len(sequence) != verdict.write_count_bound:
        raise ValueError("command_sequence length does not match write_count_bound")
    return tuple(
        {
            "door": profile.door_identity,
            "ordinal": index,
            "opcode": item.get("opcode"),
            "length": item.get("length"),
            "raw_payload_bytes_emitted": False,
            "automatic_retry_allowed": False,
        }
        for index, item in enumerate(sequence, 1)
    )


def _prov(
    *,
    door: str = "entrance",
    artifact: str = "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c",
    anchor: str = "lines 227-272",
    evidence: EvidenceClass = EvidenceClass.PROVEN_STATIC,
    literal: LiteralClass = LiteralClass.FROZEN_NATIVE_LITERAL,
) -> ProvenanceRef:
    return ProvenanceRef(
        artifact=artifact,
        anchor=anchor,
        door_identity=door,
        evidence_class=evidence,
        literal_class=literal,
    )


def entrance_proven_profile() -> DoorActuationProfile:
    native = _prov()
    return DoorActuationProfile(
        door_identity="entrance",
        target_source_identity=ProfileField(
            "target_source_identity",
            {"door_target": "entrance", "panel_source": "00000643"},
            native,
        ),
        command_sequence=ProfileField(
            "command_sequence",
            (
                {"opcode": 0x00, "length": 32},
                {"opcode": 0x20, "length": 32},
                {"opcode": 0xC0, "length": 48},
                {"opcode": 0x00, "length": 32},
                {"opcode": 0x20, "length": 32},
            ),
            native,
        ),
        channel_allocation=ProfileField(
            "channel_allocation",
            "persistent-ctpp-reused",
            _prov(anchor="lines 227-237, 1017-1108"),
        ),
        output_address_selector=ProfileField(
            "output_address_selector",
            "native-frozen-entrance-selector",
            _prov(anchor="lines 240-272"),
        ),
        ack_semantics=ProfileField(
            "ack_semantics",
            "no-door-specific-ack-proof",
            _prov(anchor="lines 1947-1949, 2525-2525"),
        ),
        safety_idempotency=ProfileField(
            "safety_idempotency",
            "one-shot",
            _prov(anchor="lines 227-237, 2451-2600"),
        ),
        no_retry=ProfileField(
            "no_retry",
            True,
            _prov(anchor="lines 227-237"),
        ),
        write_count_bound=ProfileField(
            "write_count_bound",
            5,
            _prov(anchor="line 272"),
        ),
        validated=True,
    )


def gate_unvalidated_profile() -> DoorActuationProfile:
    ring = ProvenanceRef(
        artifact="custom_components/comelit/const.py; custom_components/comelit/ring_event.py",
        anchor="const.py lines 96-100; ring_event.py lines 12-18",
        door_identity="gate",
        evidence_class=EvidenceClass.PROVEN_STATIC,
        literal_class=LiteralClass.RING_IDENTITY,
    )
    unresolved = ProvenanceRef(
        artifact="missing:GATE_ACTUATION_PROFILE_CAPTURE",
        anchor="not present in repository or staged evidence",
        door_identity="gate",
        evidence_class=EvidenceClass.UNRESOLVED,
        literal_class=LiteralClass.CAPTURE_OBSERVED_NON_PROMOTABLE,
    )
    return DoorActuationProfile(
        door_identity="gate",
        target_source_identity=ProfileField(
            "target_source_identity",
            {"ring_source": "00000610"},
            ring,
        ),
        command_sequence=ProfileField("command_sequence", (), unresolved),
        channel_allocation=ProfileField("channel_allocation", None, unresolved),
        output_address_selector=ProfileField("output_address_selector", None, unresolved),
        ack_semantics=ProfileField("ack_semantics", None, unresolved),
        safety_idempotency=ProfileField("safety_idempotency", "one-shot", unresolved),
        no_retry=ProfileField("no_retry", True, unresolved),
        write_count_bound=ProfileField("write_count_bound", 0, unresolved),
        validated=False,
    )


def entrance_profile_transferred_to_gate() -> DoorActuationProfile:
    entrance = entrance_proven_profile()
    return DoorActuationProfile(
        door_identity="gate",
        target_source_identity=entrance.target_source_identity,
        command_sequence=entrance.command_sequence,
        channel_allocation=entrance.channel_allocation,
        output_address_selector=entrance.output_address_selector,
        ack_semantics=entrance.ack_semantics,
        safety_idempotency=entrance.safety_idempotency,
        no_retry=entrance.no_retry,
        write_count_bound=entrance.write_count_bound,
        validated=True,
    )


def _load_const_from_text(text: str):
    module_name = "_r61_contract_const_text"
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    if spec is None:
        raise RuntimeError("cannot create const module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    exec(compile(text, str(CONST), "exec"), module.__dict__)
    return module


def derive_gate_capability_from_const_text(text: str) -> object:
    module = _load_const_from_text(text)
    return module.resolve_door_capability(module.DOOR_GATE, media_paused=False)


def gate_profile_artifact_present() -> bool:
    return all(status != "ABSENT" for _, status, _ in CANONICAL_GATE_MISSING_EVIDENCE)


def machine_markers() -> tuple[str, ...]:
    entrance = validate_profile(entrance_proven_profile())
    gate_capability = derive_gate_capability_from_const_text(CONST.read_text(encoding="utf-8"))
    artifact_present = gate_profile_artifact_present()
    return (
        f"ENTRANCE_PROFILE_VALIDATED={str(entrance.valid).lower()}",
        f"ENTRANCE_PROFILE_CAN_EMIT={str(entrance.can_emit).lower()}",
        f"GATE_PROFILE_ARTIFACT_PRESENT={str(artifact_present).lower()}",
        f"GATE_PROFILE_MISSING_EVIDENCE={','.join(item[0] for item in CANONICAL_GATE_MISSING_EVIDENCE)}",
        *(
            marker
            for name, status, anchor in CANONICAL_GATE_MISSING_EVIDENCE
            for marker in (
                f"{name}_STATUS={status}",
                f"{name}_ANCHOR={anchor}",
            )
        ),
        f"GATE_ACTUATION_PROFILE_VALIDATED={str(gate_capability.actuation_profile_validated and artifact_present).lower()}",
        f"GATE_STANDARD_PRESS_ALLOWED={str(gate_capability.press_allowed and artifact_present).lower()}",
        f"GATE_BLOCKED_REASON={gate_capability.blocked_reason}",
        f"GATE_RING_SOURCE={gate_capability.ring_source}",
        "LIVE_ACTIONS=0",
        "PRODUCTION_MUTATIONS=0",
        "RAW_PAYLOAD_BYTES_COMMITTED=false",
        "SECRETS_READ=false",
        "NETWORK_ACTION_PERFORMED=false",
        "ACTUATOR_COMMAND_ATTEMPTED=false",
        "PHYSICAL_DOOR_ACTION=false",
    )


if __name__ == "__main__":
    for marker in machine_markers():
        print(marker)
