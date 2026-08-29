from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable


class BuilderKind(str, Enum):
    BINARY_PACKET_BODY = "BINARY_PACKET_BODY"
    DOOR_MESSAGE = "DOOR_MESSAGE"


@dataclass(frozen=True)
class ShapeComponent:
    shape: str
    static_bytes: int | None

    def __post_init__(self) -> None:
        if not self.shape:
            raise ValueError("shape is required")
        if self.static_bytes is not None and self.static_bytes < 0:
            raise ValueError("static_bytes must be non-negative")


@dataclass(frozen=True)
class DoorWriteShape:
    ordinal: int
    source_function: str
    builder_kind: BuilderKind
    source_index: int
    source_line: int
    components: tuple[ShapeComponent, ...] = ()
    argument_shapes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("ordinal must be >= 1")
        if self.source_index < 1:
            raise ValueError("source_index must be >= 1")
        if self.source_line < 1:
            raise ValueError("source_line must be >= 1")
        if self.builder_kind == BuilderKind.BINARY_PACKET_BODY and not self.components:
            raise ValueError("binary body shape requires at least one component")
        if self.builder_kind == BuilderKind.DOOR_MESSAGE and not self.argument_shapes:
            raise ValueError("door message shape requires argument shapes")

    @property
    def known_static_bytes(self) -> int | None:
        if self.builder_kind != BuilderKind.BINARY_PACKET_BODY:
            return None
        sizes = [item.static_bytes for item in self.components]
        if any(item is None for item in sizes):
            return None
        return sum(item for item in sizes if item is not None)


@dataclass(frozen=True)
class DoorBodyShapeInventory:
    source_sha256: str
    writes: tuple[DoorWriteShape, ...]
    payload_values_extracted: bool = False
    source_executed: bool = False
    secrets_read: bool = False
    network_action_performed: bool = False
    physical_door_action: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase SHA256")
        if any((self.payload_values_extracted, self.source_executed, self.secrets_read, self.network_action_performed, self.physical_door_action)):
            raise ValueError("inventory must remain read-only and payload-redacted")
        ordinals = tuple(item.ordinal for item in self.writes)
        if ordinals != tuple(range(1, len(self.writes) + 1)):
            raise ValueError("write ordinals must be contiguous")

    def require_six_write_shape(self) -> "DoorBodyShapeInventory":
        if len(self.writes) != 6:
            raise ValueError(f"expected exactly six Door write shapes, got {len(self.writes)}")
        return self


_KEY_VALUE = re.compile(r"^([A-Z0-9_]+)=(.*)$")


def _parse_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        match = _KEY_VALUE.match(raw_line.strip())
        if match:
            result[match.group(1)] = match.group(2)
    return result


def _parse_static_bytes(value: str) -> int | None:
    return None if value == "unknown" else int(value)


def parse_legacy_body_shape_inventory(text: str) -> DoorBodyShapeInventory:
    values = _parse_key_values(text)
    if values.get("LEGACY_DOOR_BODY_SHAPE_INVENTORY") != "PASS":
        raise ValueError("inventory PASS marker missing")
    required_false = {
        "PAYLOAD_LITERAL_VALUES_EXTRACTED": "false",
        "SOURCE_EXECUTED": "false",
        "SECRETS_READ": "false",
        "NETWORK_ACTION_PERFORMED": "false",
        "PHYSICAL_DOOR_ACTION": "false",
    }
    for key, expected in required_false.items():
        if values.get(key) != expected:
            raise ValueError(f"unsafe or missing inventory marker: {key}")

    source_sha256 = values.get("SOURCE_SHA256", "")
    writes: list[DoorWriteShape] = []
    ordinal = 0

    for function_name in ("_open_door_init", "open_door"):
        block_pattern = re.compile(
            rf"FUNCTION={re.escape(function_name)}\n(?P<body>.*?)(?=\nFUNCTION=|\nLEGACY_DOOR_BODY_SHAPE_INVENTORY=PASS|\Z)",
            re.S,
        )
        match = block_pattern.search(text)
        if not match:
            raise ValueError(f"missing inventory block: {function_name}")
        block = _parse_key_values(match.group(0))
        binary_count = int(block.get("BINARY_BODY_BUILDER_CALLS", "0"))
        message_count = int(block.get("DOOR_MESSAGE_BUILDER_CALLS", "0"))
        local: list[tuple[int, BuilderKind, int, tuple[ShapeComponent, ...], tuple[str, ...]]] = []

        for index in range(1, binary_count + 1):
            line = int(block[f"BODY_CALL_{index}_LINE"])
            count = int(block[f"BODY_CALL_{index}_COMPONENTS"])
            components = tuple(
                ShapeComponent(
                    shape=block[f"BODY_CALL_{index}_COMPONENT_{component}_SHAPE"],
                    static_bytes=_parse_static_bytes(block[f"BODY_CALL_{index}_COMPONENT_{component}_STATIC_BYTES"]),
                )
                for component in range(1, count + 1)
            )
            local.append((line, BuilderKind.BINARY_PACKET_BODY, index, components, ()))

        for index in range(1, message_count + 1):
            line = int(block[f"DOOR_MESSAGE_CALL_{index}_LINE"])
            argc = int(block[f"DOOR_MESSAGE_CALL_{index}_ARGC"])
            raw_shapes = block.get(f"DOOR_MESSAGE_CALL_{index}_ARG_SHAPES", "")
            argument_shapes = tuple(raw_shapes.split("|")) if raw_shapes else ()
            if len(argument_shapes) != argc:
                raise ValueError(f"door-message argument shape count mismatch: {function_name}#{index}")
            local.append((line, BuilderKind.DOOR_MESSAGE, index, (), argument_shapes))

        for line, kind, source_index, components, argument_shapes in sorted(local):
            ordinal += 1
            writes.append(DoorWriteShape(
                ordinal=ordinal,
                source_function=function_name,
                builder_kind=kind,
                source_index=source_index,
                source_line=line,
                components=components,
                argument_shapes=argument_shapes,
            ))

    return DoorBodyShapeInventory(source_sha256=source_sha256, writes=tuple(writes)).require_six_write_shape()


def deterministic_placeholder(shape: str, length: int, *, salt: int = 0) -> bytes:
    if length < 0:
        raise ValueError("length must be non-negative")
    seed = (sum(shape.encode("utf-8")) + salt) % 251 + 1
    return bytes(((seed + offset) % 251) + 1 for offset in range(length))


def synthesize_known_binary_body(write: DoorWriteShape) -> bytes:
    if write.builder_kind != BuilderKind.BINARY_PACKET_BODY:
        raise ValueError("only binary-body writes can be synthesized from static sizes")
    if write.known_static_bytes is None:
        raise ValueError("binary-body write contains dynamic-size components")
    return b"".join(
        deterministic_placeholder(component.shape, component.static_bytes or 0, salt=index)
        for index, component in enumerate(write.components, 1)
    )


def summarize_inventory(inventory: DoorBodyShapeInventory) -> Iterable[str]:
    yield f"CTPP_BODY_MODEL_SOURCE_SHA256={inventory.source_sha256}"
    yield f"CTPP_BODY_MODEL_WRITE_COUNT={len(inventory.writes)}"
    yield "CTPP_BODY_MODEL_PAYLOAD_VALUES_PRESENT=false"
    for write in inventory.writes:
        yield f"WRITE_{write.ordinal}_BUILDER={write.builder_kind.value}"
        yield f"WRITE_{write.ordinal}_SOURCE_FUNCTION={write.source_function}"
        yield f"WRITE_{write.ordinal}_SOURCE_LINE={write.source_line}"
        static = write.known_static_bytes
        yield f"WRITE_{write.ordinal}_KNOWN_STATIC_BYTES={'unknown' if static is None else static}"
