#!/usr/bin/env python3
"""Offline D1 reconciliation against the primary self-activation PCAP.

The script is intentionally non-networking.  It reads a local PCAP and the
root-only prepared P13 payload, reassembles PseudoTCP application bytes, parses
ViP frames, locates the capture-confirmed Door semantic by a public-safe target
pair hash, and compares that semantic with the six prepared standalone writes.

It also performs a conservative Door-response forensic.  A Door-specific ACK
is PROVEN only when an inbound CTPP body itself carries the same target/output
semantic.  A merely distinct response is never promoted to ACK.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import stat
from typing import Iterable

EXPECTED_PEER_TARGET_SHA256 = "ec95e794a2a16aa02fb02489d9794419f13744ba66dfcb711f8af9326ee1ff30"
EXPECTED_PAYLOAD_TARGET_FINGERPRINT = "832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce"
EXPECTED_UCFG_SHA256 = "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7"
EXPECTED_STANDALONE_SUFFIX = (0x1800, 0x1820, 0x18C0, 0x1800, 0x1820)
TAP_OPCODES = {0x1800, 0x1820, 0x18C0, 0x1840, 0x1860}
PSEUDOTCP_HEADER = 24
VIP_HEADER = 8

# Primary self_activation.pcap contains one exact seven-byte application
# prefix before the first ViP frame in BOTH selected directions.  Its protocol
# semantics are deliberately not inferred here; this is a capture-pinned
# framing invariant only.
EXPECTED_CAPTURE_PREFIX = bytes.fromhex("00030100fe0100")


@dataclass(frozen=True)
class Segment:
    seq: int
    timestamp: float
    data: bytes


@dataclass(frozen=True)
class Reassembled:
    data: bytes
    timestamps: tuple[float, ...]
    gaps: int
    conflicts: int


@dataclass(frozen=True)
class VipFrame:
    timestamp: float
    request_id: int
    body: bytes
    stream_offset: int
    direction: str

    @property
    def opcode(self) -> int | None:
        if len(self.body) < 2:
            return None
        value = int.from_bytes(self.body[:2], "little")
        return value if value in TAP_OPCODES else None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True)
class PreparedWrite:
    index: int
    body: bytes
    sha256: str
    opcode: int | None
    target_match: bool


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_pins(body: bytes) -> set[str]:
    """Return SHA256(address|output) candidates encoded by ``00 2d`` bodies.

    The captured active-call family stores an addr10 field.  Recovered legacy
    variants also exist with an 8-digit NUL-terminated address.  We accept only
    exactly eight decimal digits and never return or print the plaintext value.
    """
    pins: set[str] = set()
    marker = b"\x00\x2d"
    start = 0
    while True:
        pos = body.find(marker, start)
        if pos < 0:
            break
        field_start = pos + len(marker)
        for width in (10, 9, 8):
            end = field_start + width
            if end >= len(body):
                continue
            raw = body[field_start:end]
            addr = raw.rstrip(b"\x00")
            if len(addr) != 8 or not all(48 <= value <= 57 for value in addr):
                continue
            if raw[len(addr) :] not in (b"", b"\x00", b"\x00\x00"):
                continue
            output = body[end]
            material = addr + b"|" + str(output).encode("ascii")
            pins.add(hashlib.sha256(material).hexdigest())
        start = pos + 1
    return pins


def body_has_expected_target(body: bytes) -> bool:
    return EXPECTED_PEER_TARGET_SHA256 in pair_pins(body)


def reassemble_segments(segments: Iterable[Segment]) -> Reassembled:
    ordered = sorted((segment for segment in segments if segment.data), key=lambda value: (value.seq, value.timestamp))
    if not ordered:
        return Reassembled(b"", tuple(), 0, 0)

    bytes_by_seq: dict[int, int] = {}
    ts_by_seq: dict[int, float] = {}
    conflicts = 0
    for segment in ordered:
        for offset, value in enumerate(segment.data):
            seq = segment.seq + offset
            previous = bytes_by_seq.get(seq)
            if previous is None:
                bytes_by_seq[seq] = value
                ts_by_seq[seq] = segment.timestamp
            elif previous != value:
                conflicts += 1

    lo = min(bytes_by_seq)
    hi = max(bytes_by_seq)
    gaps = sum(1 for seq in range(lo, hi + 1) if seq not in bytes_by_seq)
    data = bytes(bytes_by_seq.get(seq, 0) for seq in range(lo, hi + 1))
    timestamps = tuple(ts_by_seq.get(seq, 0.0) for seq in range(lo, hi + 1))
    return Reassembled(data, timestamps, gaps, conflicts)


def parse_vip_stream(stream: Reassembled, direction: str) -> tuple[list[VipFrame], int]:
    frames: list[VipFrame] = []
    skipped = 0
    data = stream.data
    offset = 0
    while offset + VIP_HEADER <= len(data):
        if data[offset : offset + 2] != b"\x00\x06":
            next_offset = data.find(b"\x00\x06", offset + 1)
            if next_offset < 0:
                skipped += len(data) - offset
                break
            skipped += next_offset - offset
            offset = next_offset
            continue
        body_len = int.from_bytes(data[offset + 2 : offset + 4], "little")
        frame_len = VIP_HEADER + body_len
        if body_len > 65535 or offset + frame_len > len(data):
            break
        request_id = int.from_bytes(data[offset + 4 : offset + 8], "little")
        body = data[offset + VIP_HEADER : offset + frame_len]
        timestamp = stream.timestamps[offset] if offset < len(stream.timestamps) else 0.0
        frames.append(VipFrame(timestamp, request_id, body, offset, direction))
        offset += frame_len
    return frames, skipped


def capture_prefix_matches(
    stream: Reassembled,
    frames: list[VipFrame],
    skipped: int,
) -> bool:
    """Validate the exact capture-pinned pre-ViP prefix and full framing.

    The primary capture has one seven-byte prefix before the first ViP frame in
    each direction.  We do not assign protocol semantics to those bytes.

    This gate additionally proves that:
    - the only parser-skipped bytes are that exact prefix;
    - the first frame begins immediately after it;
    - the last parsed frame ends exactly at the end of the reassembled stream.

    Therefore extra bytes before, between, or after ViP frames fail closed.
    """
    if not frames:
        return False

    first_offset = frames[0].stream_offset
    last = frames[-1]
    framed_end = last.stream_offset + VIP_HEADER + len(last.body)

    return (
        first_offset == len(EXPECTED_CAPTURE_PREFIX)
        and skipped == len(EXPECTED_CAPTURE_PREFIX)
        and stream.data[:first_offset] == EXPECTED_CAPTURE_PREFIX
        and framed_end == len(stream.data)
    )


def load_pcap_flows(path: Path) -> dict[tuple[tuple[str, int], tuple[str, int]], dict[str, list[Segment]]]:
    # Import Scapy only here so repository CI/unit tests can exercise all pure
    # parsing/reconciliation functions without requiring Scapy.
    try:
        from scapy.all import IP, IPv6, PcapReader, UDP  # type: ignore
    except ImportError as exc:  # pragma: no cover - CT120 deployment condition
        raise RuntimeError("python3-scapy is required to read the D1 PCAP") from exc

    flows: dict[tuple[tuple[str, int], tuple[str, int]], dict[str, list[Segment]]] = {}
    with PcapReader(str(path)) as reader:
        for packet in reader:
            if UDP not in packet:
                continue
            if IP in packet:
                src = str(packet[IP].src)
                dst = str(packet[IP].dst)
            elif IPv6 in packet:
                src = str(packet[IPv6].src)
                dst = str(packet[IPv6].dst)
            else:
                continue
            udp = packet[UDP]
            payload = bytes(udp.payload)
            if len(payload) < PSEUDOTCP_HEADER or payload[:4] != b"\x00\x00\x00\x00":
                continue
            seq = int.from_bytes(payload[4:8], "big")
            app = payload[PSEUDOTCP_HEADER:]
            if not app:
                continue
            source = (src, int(udp.sport))
            target = (dst, int(udp.dport))
            key = tuple(sorted((source, target)))  # type: ignore[assignment]
            direction = "a_to_b" if source == key[0] else "b_to_a"
            flows.setdefault(key, {"a_to_b": [], "b_to_a": []})[direction].append(
                Segment(seq, float(packet.time), app)
            )
    return flows


def parse_flow_frames(
    flows: dict[tuple[tuple[str, int], tuple[str, int]], dict[str, list[Segment]]]
) -> list[tuple[tuple[tuple[str, int], tuple[str, int]], str, Reassembled, list[VipFrame], int]]:
    parsed = []
    for key, directions in flows.items():
        for direction, segments in directions.items():
            stream = reassemble_segments(segments)
            frames, skipped = parse_vip_stream(stream, direction)
            parsed.append((key, direction, stream, frames, skipped))
    return parsed


def load_prepared_payload(path: Path) -> tuple[dict, list[PreparedWrite]]:
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    if raw.get("schema") != 1:
        raise RuntimeError("P13 prepared payload schema must be 1")
    if raw.get("ucfg_sha256") != EXPECTED_UCFG_SHA256:
        raise RuntimeError("P13 prepared payload UCFG identity mismatch")
    if raw.get("target_fingerprint") != EXPECTED_PAYLOAD_TARGET_FINGERPRINT:
        raise RuntimeError("P13 prepared payload target fingerprint mismatch")
    bodies = raw.get("bodies")
    if not isinstance(bodies, list) or len(bodies) != 6:
        raise RuntimeError("P13 prepared payload must contain exactly six bodies")

    prepared: list[PreparedWrite] = []
    for index, item in enumerate(bodies, 1):
        if not isinstance(item, dict) or not isinstance(item.get("hex"), str):
            raise RuntimeError("P13 prepared body entry malformed")
        body = bytes.fromhex(item["hex"])
        digest = hashlib.sha256(body).hexdigest()
        if item.get("sha256") != digest or item.get("bytes") != len(body):
            raise RuntimeError(f"P13 prepared body {index} metadata mismatch")
        opcode_value = int.from_bytes(body[:2], "little") if len(body) >= 2 else -1
        opcode = opcode_value if opcode_value in TAP_OPCODES else None
        prepared.append(
            PreparedWrite(index, body, digest, opcode, body_has_expected_target(body))
        )
    return raw, prepared


def select_capture(
    parsed: list[tuple[tuple[tuple[str, int], tuple[str, int]], str, Reassembled, list[VipFrame], int]]
) -> tuple[
    tuple[tuple[str, int], tuple[str, int]],
    str,
    list[VipFrame],
    list[VipFrame],
    Reassembled,
    Reassembled,
    VipFrame,
    int,
    int,
]:
    candidates = []
    by_key_dir = {(key, direction): (stream, frames, skipped) for key, direction, stream, frames, skipped in parsed}
    for key, direction, stream, frames, skipped in parsed:
        for frame in frames:
            if frame.opcode == 0x1840 and body_has_expected_target(frame.body):
                candidates.append((key, direction, stream, frames, skipped, frame))
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one capture-confirmed 0x1840 Door frame, found {len(candidates)}")

    key, out_direction, out_stream, out_frames, out_skipped, door = candidates[0]
    in_direction = "b_to_a" if out_direction == "a_to_b" else "a_to_b"
    in_stream, in_frames, in_skipped = by_key_dir.get(
        (key, in_direction), (Reassembled(b"", tuple(), 0, 0), [], 0)
    )
    return (
        key,
        out_direction,
        out_frames,
        in_frames,
        out_stream,
        in_stream,
        door,
        out_skipped,
        in_skipped,
    )


def classify_ack(door: VipFrame, outbound: list[VipFrame], inbound: list[VipFrame]) -> tuple[str, int, bool]:
    same_channel_out = sorted(
        [frame for frame in outbound if frame.request_id == door.request_id and frame.timestamp >= door.timestamp],
        key=lambda frame: frame.timestamp,
    )
    next_out_ts = None
    for frame in same_channel_out:
        if frame is door:
            continue
        if frame.timestamp > door.timestamp:
            next_out_ts = frame.timestamp
            break
    deadline = door.timestamp + 1.0
    if next_out_ts is not None:
        deadline = min(deadline, next_out_ts)

    candidates = [
        frame
        for frame in inbound
        if frame.request_id == door.request_id and door.timestamp <= frame.timestamp <= deadline
    ]
    if any(body_has_expected_target(frame.body) for frame in candidates):
        return "PROVEN", len(candidates), False

    neighbor_hashes: set[str] = set()
    taps = [
        frame
        for frame in outbound
        if frame.request_id == door.request_id
        and frame.opcode in TAP_OPCODES
        and frame is not door
        and abs(frame.timestamp - door.timestamp) <= 5.0
    ]
    for tap in taps:
        upper = tap.timestamp + 1.0
        later = [
            other.timestamp
            for other in outbound
            if other.request_id == tap.request_id and other.timestamp > tap.timestamp
        ]
        if later:
            upper = min(upper, min(later))
        for frame in inbound:
            if frame.request_id == tap.request_id and tap.timestamp <= frame.timestamp <= upper:
                neighbor_hashes.add(frame.sha256)

    overlap = bool(candidates) and all(frame.sha256 in neighbor_hashes for frame in candidates)
    if candidates and overlap:
        return "NOT_DISTINGUISHABLE", len(candidates), True
    return "UNKNOWN", len(candidates), overlap


def analyze(
    outbound: list[VipFrame],
    inbound: list[VipFrame],
    door: VipFrame,
    prepared: list[PreparedWrite],
) -> dict[str, str]:
    opcodes = tuple(item.opcode for item in prepared)
    suffix_match = tuple(opcodes[-5:]) == EXPECTED_STANDALONE_SUFFIX
    target_matches = [item.index for item in prepared if item.target_match]
    exact_matches = [item.index for item in prepared if item.body == door.body]

    if exact_matches and suffix_match:
        relation = "EXACT_ACTIVE_CALL_BODY_MATCH"
        acceptable = True
    elif target_matches and suffix_match:
        relation = "SEMANTIC_TARGET_MATCH_DIFFERENT_CONTEXT"
        acceptable = True
    else:
        relation = "CONTRADICTION"
        acceptable = False

    ack, ack_candidates, overlap = classify_ack(door, outbound, inbound)

    tap_out = sorted(
        [frame for frame in outbound if frame.request_id == door.request_id and frame.opcode in TAP_OPCODES],
        key=lambda frame: frame.timestamp,
    )
    previous = [frame for frame in tap_out if frame.timestamp < door.timestamp]
    later = [frame for frame in tap_out if frame.timestamp > door.timestamp]
    prev_ms = "ABSENT" if not previous else str(round((door.timestamp - previous[-1].timestamp) * 1000.0, 3))
    next_ms = "ABSENT" if not later else str(round((later[0].timestamp - door.timestamp) * 1000.0, 3))

    opcode_text = ",".join("NONE" if opcode is None else f"0x{opcode:04x}" for opcode in opcodes)
    return {
        "P13_D1_CAPTURE_DOOR_FRAME": "PASS",
        "P13_D1_CAPTURE_DOOR_OPCODE": "0x1840",
        "P13_D1_CAPTURE_TARGET_MATCH": "PASS",
        "P13_D1_CAPTURE_DOOR_BODY_SHA256": door.sha256,
        "P13_D1_PREPARED_WRITE_COUNT": str(len(prepared)),
        "P13_D1_PREPARED_OPCODES": opcode_text,
        "P13_D1_PREPARED_OPERATION_SUFFIX_MATCH": str(suffix_match).lower(),
        "P13_D1_PREPARED_TARGET_MATCH_COUNT": str(len(target_matches)),
        "P13_D1_PREPARED_EXACT_BODY_MATCH_COUNT": str(len(exact_matches)),
        "P13_D1_STANDALONE_RELATION": relation,
        "P13_D1_STANDALONE_ACCEPTABLE": str(acceptable).lower(),
        "P13_D1_DOOR_SPECIFIC_ACK": ack,
        "P13_D1_DOOR_RESPONSE_CANDIDATE_COUNT": str(ack_candidates),
        "P13_D1_DOOR_RESPONSE_OVERLAPS_NEIGHBOR": str(overlap).lower(),
        "P13_D1_PREVIOUS_TAP_TO_DOOR_MS": prev_ms,
        "P13_D1_DOOR_TO_NEXT_TAP_MS": next_ms,
    }


def ensure_private_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} file missing: {path}")
    # PCAP may historically be root-readable 0600; payload must be strictly
    # root-owned 0600.  Ownership is enforced by the caller for payload only.


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline P13 D1 primary-capture reconciliation")
    parser.add_argument("--pcap", type=Path, default=Path("/root/comelit-artifacts/self_activation.pcap"))
    parser.add_argument("--payload", type=Path, default=Path("/root/comelit-p13-actuator-prep/real-door-payloads.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    print("P13_D1_FORENSIC_START=true")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    print("SEND_ARMED_REACHED=false")

    ensure_private_file(args.pcap, "D1 PCAP")
    ensure_private_file(args.payload, "P13 payload")
    payload_stat = args.payload.stat()
    if stat.S_IMODE(payload_stat.st_mode) != 0o600 or payload_stat.st_uid != 0:
        raise RuntimeError("P13 payload must be root-owned mode 0600")

    raw_payload, prepared = load_prepared_payload(args.payload)
    flows = load_pcap_flows(args.pcap)
    parsed = parse_flow_frames(flows)
    (
        _key,
        _out_direction,
        outbound,
        inbound,
        out_stream,
        in_stream,
        door,
        out_skipped,
        in_skipped,
    ) = select_capture(parsed)

    if out_stream.gaps or in_stream.gaps or out_stream.conflicts or in_stream.conflicts:
        raise RuntimeError(
            "selected PseudoTCP flow is not gap/conflict free: "
            f"out_gaps={out_stream.gaps} in_gaps={in_stream.gaps} "
            f"out_conflicts={out_stream.conflicts} in_conflicts={in_stream.conflicts}"
        )

    out_prefix_ok = capture_prefix_matches(
        out_stream,
        outbound,
        out_skipped,
    )
    in_prefix_ok = capture_prefix_matches(
        in_stream,
        inbound,
        in_skipped,
    )
    capture_prefix_gate = out_prefix_ok and in_prefix_ok

    result = analyze(outbound, inbound, door, prepared)
    result.update(
        {
            "P13_D1_PCAP_SHA256": sha256_file(args.pcap),
            "P13_D1_PAYLOAD_SHA256": sha256_file(args.payload),
            "P13_D1_PAYLOAD_UCFG_BINDING": "PASS" if raw_payload.get("ucfg_sha256") == EXPECTED_UCFG_SHA256 else "FAIL",
            "P13_D1_SELECTED_OUT_VIP_FRAMES": str(len(outbound)),
            "P13_D1_SELECTED_IN_VIP_FRAMES": str(len(inbound)),
            "P13_D1_OUT_STREAM_GAPS": str(out_stream.gaps),
            "P13_D1_IN_STREAM_GAPS": str(in_stream.gaps),
            "P13_D1_OUT_STREAM_CONFLICTS": str(out_stream.conflicts),
            "P13_D1_IN_STREAM_CONFLICTS": str(in_stream.conflicts),
            "P13_D1_OUT_UNFRAMED_BYTES": str(out_skipped),
            "P13_D1_IN_UNFRAMED_BYTES": str(in_skipped),
            "P13_D1_OUT_CAPTURE_PREFIX": "PASS" if out_prefix_ok else "FAIL",
            "P13_D1_IN_CAPTURE_PREFIX": "PASS" if in_prefix_ok else "FAIL",
            "P13_D1_CAPTURE_PREFIX_MATCH": "PASS" if capture_prefix_gate else "FAIL",
            "P13_D1_CAPTURE_PREFIX_BYTES": str(len(EXPECTED_CAPTURE_PREFIX)),
            "P13_D1_CAPTURE_PREFIX_SHA256": hashlib.sha256(EXPECTED_CAPTURE_PREFIX).hexdigest(),
            "P13_D1_TARGET_VALUE_EMITTED": "false",
            "P13_D1_RAW_FRAME_VALUES_EMITTED": "false",
            "NETWORK_ACTION_PERFORMED": "false",
            "PHYSICAL_DOOR_ACTION": "false",
            "SEND_ARMED_REACHED": "false",
        }
    )
    result["P13_D1_FORENSIC"] = (
        "PASS"
        if result["P13_D1_STANDALONE_ACCEPTABLE"] == "true"
        and capture_prefix_gate
        else "FAIL"
    )

    lines = [f"{key}={value}" for key, value in result.items()]
    for line in lines:
        print(line)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        args.report.chmod(0o600)

    return 0 if result["P13_D1_FORENSIC"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
