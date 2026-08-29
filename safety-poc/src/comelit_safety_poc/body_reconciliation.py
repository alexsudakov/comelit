from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib

from .ctpp_body_model import BuilderKind, DoorBodyShapeInventory, DoorWriteShape


class DoorSemanticWrite(str, Enum):
    INIT_A = "INIT_A"
    COMMAND_PRIMARY = "COMMAND_PRIMARY"
    CONFIRM_PRIMARY = "CONFIRM_PRIMARY"
    INIT_B = "INIT_B"
    COMMAND_FINAL = "COMMAND_FINAL"
    CONFIRM_FINAL = "CONFIRM_FINAL"


EXPECTED_BUILDERS = (
    BuilderKind.BINARY_PACKET_BODY,
    BuilderKind.DOOR_MESSAGE,
    BuilderKind.DOOR_MESSAGE,
    BuilderKind.BINARY_PACKET_BODY,
    BuilderKind.DOOR_MESSAGE,
    BuilderKind.DOOR_MESSAGE,
)


@dataclass(frozen=True)
class ReconciledWriteShape:
    semantic: DoorSemanticWrite
    legacy: DoorWriteShape
    structural_fingerprint: str

    def __post_init__(self) -> None:
        if len(self.structural_fingerprint) != 64:
            raise ValueError("structural_fingerprint must be SHA256 hex")


@dataclass(frozen=True)
class BodyShapeReconciliation:
    writes: tuple[ReconciledWriteShape, ...]
    payload_values_present: bool = False
    byte_exact_body_reconciliation_complete: bool = False

    def __post_init__(self) -> None:
        if self.payload_values_present:
            raise ValueError("repository shape reconciliation must not embed real payload values")
        if len(self.writes) != 6:
            raise ValueError("exactly six reconciled write shapes are required")


def _fingerprint(write: DoorWriteShape) -> str:
    parts = [
        write.builder_kind.value,
        write.source_function,
        str(write.source_index),
        *(f"{item.shape}:{item.static_bytes}" for item in write.components),
        *(f"ARG:{shape}" for shape in write.argument_shapes),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def reconcile_structural_inventory(inventory: DoorBodyShapeInventory) -> BodyShapeReconciliation:
    inventory.require_six_write_shape()
    actual_builders = tuple(write.builder_kind for write in inventory.writes)
    if actual_builders != EXPECTED_BUILDERS:
        raise ValueError("legacy write-builder order differs from pinned six-step Door semantic model")

    reconciled = tuple(
        ReconciledWriteShape(
            semantic=semantic,
            legacy=write,
            structural_fingerprint=_fingerprint(write),
        )
        for semantic, write in zip(DoorSemanticWrite, inventory.writes, strict=True)
    )
    return BodyShapeReconciliation(
        writes=reconciled,
        payload_values_present=False,
        byte_exact_body_reconciliation_complete=False,
    )
