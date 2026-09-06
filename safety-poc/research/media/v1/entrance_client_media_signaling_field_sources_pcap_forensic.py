#!/usr/bin/env python3
"""Offline field-source forensic for client media signaling bodies.

P60 established the structural/address/copy relations for client 0x000a and
0x001a.  This analyzer narrows the remaining unknown bytes by correlating them,
in memory only, with already-observed session state:

* earlier CTPP signaling bodies on the same request id;
* nearby CONTROL frames (request id 0) around packets 205..209;
* first wrapped-RTP stream wrapper/header identifiers after packet 218;
* zero/0xff constant runs.

Only relation names, target/source positions and lengths are emitted.  No body
values, addresses, endpoint values, request ids, RTP sequence/timestamp/SSRC
values, raw/hex/base64 payload or media bytes are emitted.  No network I/O is
performed and no signaling is sent.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import _read_selected_datagrams
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _opaque
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape
from entrance_client_media_signaling_body_contract_pcap_forensic import (
    _find_anchor,
    _find_exact,
    CLIENT_000A_PACKET,
    DEVICE_000A_PACKET,
    CLIENT_001A_PACKET,
)

BOUNDARY_PACKET = 218
RTP_OFFSET = 8
MIN_COPY = 2
CONTROL_START = 205
CONTROL_END = 209


@dataclass(frozen=True)
class Relation:
    target_label: str
    target_start: int
    source_label: str
    source_start: int
    length: int
    kind: str


@dataclass(frozen=True)
class FirstRtp:
    ordinal: int
    direction: str
    payload_type: int
    wrapper: bytes
    sequence_be: bytes
    sequence_le: bytes
    timestamp_be: bytes
    timestamp_le: bytes
    ssrc_be: bytes
    ssrc_le: bytes


@dataclass(frozen=True)
class Result:
    relations: tuple[Relation, ...]
    zero_ranges: tuple[Relation, ...]
    ff_ranges: tuple[Relation, ...]
    client_000a_unresolved: tuple[int, ...]
    client_001a_unresolved: tuple[int, ...]
    first_rtp_stream_count: int


def _find_all(blob: bytes, needle: bytes) -> tuple[int, ...]:
    if not needle:
        return ()
    out: list[int] = []
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            return tuple(out)
        out.append(pos)
        start = pos + 1


def _maximal_copy_relations(target_label: str, target: bytes, source_label: str, source: bytes) -> list[Relation]:
    candidates: list[Relation] = []
    for dst in range(len(target)):
        best: Relation | None = None
        for src in range(len(source)):
            size = 0
            while dst + size < len(target) and src + size < len(source) and target[dst + size] == source[src + size]:
                size += 1
            if size >= MIN_COPY and (best is None or size > best.length):
                best = Relation(target_label, dst, source_label, src, size, "COPY")
        if best is not None:
            candidates.append(best)
    # keep only non-contained target spans, longest first
    candidates.sort(key=lambda r: (-r.length, r.target_start, r.source_label, r.source_start))
    selected: list[Relation] = []
    covered: set[int] = set()
    for item in candidates:
        span = set(range(item.target_start, item.target_start + item.length))
        if span <= covered:
            continue
        selected.append(item)
        covered |= span
    return sorted(selected, key=lambda r: (r.target_start, -r.length, r.source_label))


def _run_ranges(label: str, body: bytes, value: int, kind: str) -> list[Relation]:
    out: list[Relation] = []
    start: int | None = None
    for i, byte in enumerate(body + bytes([value ^ 0xFF])):
        if i < len(body) and byte == value:
            if start is None:
                start = i
            continue
        if start is not None:
            length = i - start
            if length >= 2:
                out.append(Relation(label, start, kind, 0, length, kind))
            start = None
    return out


def _first_rtp(datagrams, client, device) -> tuple[FirstRtp, ...]:
    groups: dict[tuple[str, int, int], tuple[int, bytes, object]] = {}
    for item in _opaque(datagrams, BOUNDARY_PACKET):
        if len(item.payload) <= RTP_OFFSET:
            continue
        inner = item.payload[RTP_OFFSET:]
        meta = _parse_rtp_v2_shape(inner)
        if meta is None:
            continue
        if item.source == client and item.target == device:
            direction = "CLIENT_TO_DEVICE"
        elif item.source == device and item.target == client:
            direction = "DEVICE_TO_CLIENT"
        else:
            continue
        key = (direction, meta.ssrc, meta.payload_type)
        groups.setdefault(key, (item.packet_number, item.payload, meta))

    ordered = sorted(groups.items(), key=lambda kv: kv[1][0])
    result: list[FirstRtp] = []
    for ordinal, ((direction, _ssrc, pt), (_packet, payload, meta)) in enumerate(ordered, start=1):
        inner = payload[RTP_OFFSET:]
        timestamp = int.from_bytes(inner[4:8], "big")
        result.append(
            FirstRtp(
                ordinal=ordinal,
                direction=direction,
                payload_type=pt,
                wrapper=payload[:RTP_OFFSET],
                sequence_be=meta.sequence.to_bytes(2, "big"),
                sequence_le=meta.sequence.to_bytes(2, "little"),
                timestamp_be=timestamp.to_bytes(4, "big"),
                timestamp_le=timestamp.to_bytes(4, "little"),
                ssrc_be=meta.ssrc.to_bytes(4, "big"),
                ssrc_le=meta.ssrc.to_bytes(4, "little"),
            )
        )
    return tuple(result)


def _rtp_relations(target_label: str, target: bytes, streams: tuple[FirstRtp, ...]) -> list[Relation]:
    out: list[Relation] = []
    for stream in streams:
        source_base = f"RTP_STREAM_{stream.ordinal}_{stream.direction}_PT{stream.payload_type}"
        patterns = (
            ("SEQ_BE", stream.sequence_be),
            ("SEQ_LE", stream.sequence_le),
            ("TS_BE", stream.timestamp_be),
            ("TS_LE", stream.timestamp_le),
            ("SSRC_BE", stream.ssrc_be),
            ("SSRC_LE", stream.ssrc_le),
            ("WRAPPER_8", stream.wrapper),
            ("WRAPPER_HEAD4", stream.wrapper[:4]),
            ("WRAPPER_TAIL4", stream.wrapper[4:8]),
        )
        for kind, needle in patterns:
            for pos in _find_all(target, needle):
                out.append(Relation(target_label, pos, source_base, 0, len(needle), kind))
    return out


def _trusted_coverage(label: str, body: bytes, relations: Iterable[Relation]) -> set[int]:
    covered: set[int] = set()
    # Structural fields, sequence, address roles and address terminators are session-derived/known.
    covered.update(range(0, 10))
    if label == "CLIENT_000A":
        covered.update(range(24, 44))
    elif label == "CLIENT_001A":
        covered.update(range(40, 60))

    for rel in relations:
        if rel.target_label != label:
            continue
        trusted = False
        if rel.kind in ("ZERO_RUN", "FF_RUN"):
            trusted = True
        elif rel.kind in ("TS_BE", "TS_LE", "SSRC_BE", "SSRC_LE", "WRAPPER_8", "WRAPPER_HEAD4", "WRAPPER_TAIL4"):
            # 4+ byte media relations are strong enough to flag as derivable candidates.
            trusted = rel.length >= 4
        elif rel.kind == "COPY":
            # Copies from observed device/control frames are runtime-derivable; copies from our own
            # client 0x000a are derivable once that frame is constructed.
            trusted = rel.length >= 4
        if trusted:
            covered.update(range(rel.target_start, min(len(body), rel.target_start + rel.length)))
    return covered


def analyze(frames: Iterable[VipFrame], *, client, device, datagrams) -> Result:
    ordered = tuple(sorted(frames, key=lambda f: (f.timestamp, f.first_packet)))
    anchor = _find_anchor(ordered)
    c000a = _find_exact(ordered, direction="CLIENT_TO_DEVICE", packet=CLIENT_000A_PACKET, action=0x000A, body_len=44)
    d000a = _find_exact(ordered, direction="DEVICE_TO_CLIENT", packet=DEVICE_000A_PACKET, action=0x000A, body_len=44)
    c001a = _find_exact(ordered, direction="CLIENT_TO_DEVICE", packet=CLIENT_001A_PACKET, action=0x001A, body_len=60)
    if not (anchor.request_id == c000a.request_id == d000a.request_id == c001a.request_id):
        raise ValueError("target frames do not share CTPP request id")

    controls = [
        f for f in ordered
        if f.request_id == 0 and CONTROL_START <= f.first_packet <= CONTROL_END
    ]
    earlier_ctpp = [
        f for f in ordered
        if f.request_id == anchor.request_id
        and f.timestamp < c000a.timestamp
        and f.body_length <= 72
    ]
    streams = _first_rtp(datagrams, client, device)

    relations: list[Relation] = []
    targets = (("CLIENT_000A", c000a.body), ("CLIENT_001A", c001a.body))
    for target_label, target in targets:
        for frame in earlier_ctpp:
            relations.extend(_maximal_copy_relations(target_label, target, f"EARLIER_CTPP_PACKET_{frame.first_packet}", frame.body))
        for frame in controls:
            relations.extend(_maximal_copy_relations(target_label, target, f"CONTROL_PACKET_{frame.first_packet}", frame.body))
        relations.extend(_rtp_relations(target_label, target, streams))

    # Explicitly include 0x001a <- client/device 0x000a relationships.
    relations.extend(_maximal_copy_relations("CLIENT_001A", c001a.body, "CLIENT_000A", c000a.body))
    relations.extend(_maximal_copy_relations("CLIENT_001A", c001a.body, "DEVICE_000A", d000a.body))

    zero_ranges: list[Relation] = []
    ff_ranges: list[Relation] = []
    for label, body in targets:
        zero_ranges.extend(_run_ranges(label, body, 0x00, "ZERO_RUN"))
        ff_ranges.extend(_run_ranges(label, body, 0xFF, "FF_RUN"))
    all_rel = tuple(relations + zero_ranges + ff_ranges)

    c000a_cov = _trusted_coverage("CLIENT_000A", c000a.body, all_rel)
    c001a_cov = _trusted_coverage("CLIENT_001A", c001a.body, all_rel)
    c000a_unresolved = tuple(i for i in range(len(c000a.body)) if i not in c000a_cov)
    c001a_unresolved = tuple(i for i in range(len(c001a.body)) if i not in c001a_cov)

    return Result(
        relations=tuple(sorted(relations, key=lambda r: (r.target_label, r.target_start, -r.length, r.source_label, r.kind))),
        zero_ranges=tuple(zero_ranges),
        ff_ranges=tuple(ff_ranges),
        client_000a_unresolved=c000a_unresolved,
        client_001a_unresolved=c001a_unresolved,
        first_rtp_stream_count=len(streams),
    )


def _positions(values: tuple[int, ...]) -> str:
    return "NONE" if not values else ",".join(str(v) for v in values)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE CLIENT MEDIA SIGNALING FIELD SOURCES PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"FIRST_RTP_STREAM_COUNT={result.first_rtp_stream_count}",
    ]
    for rel in result.relations:
        lines.append(
            "FIELD_RELATION "
            f"target={rel.target_label} target_start={rel.target_start} length={rel.length} "
            f"source={rel.source_label} source_start={rel.source_start} kind={rel.kind}"
        )
    for rel in result.zero_ranges + result.ff_ranges:
        lines.append(
            "FIELD_CONSTANT_RANGE "
            f"target={rel.target_label} start={rel.target_start} length={rel.length} kind={rel.kind}"
        )
    lines.extend([
        f"CLIENT_000A_UNRESOLVED_POSITION_COUNT={len(result.client_000a_unresolved)}",
        f"CLIENT_000A_UNRESOLVED_POSITIONS={_positions(result.client_000a_unresolved)}",
        f"CLIENT_001A_UNRESOLVED_POSITION_COUNT={len(result.client_001a_unresolved)}",
        f"CLIENT_001A_UNRESOLVED_POSITIONS={_positions(result.client_001a_unresolved)}",
        f"LIVE_BODY_GENERATION_CONTRACT={'PASS' if not result.client_000a_unresolved and not result.client_001a_unresolved else 'NOT_PROVEN'}",
        "BODY_VALUES_EMITTED=false",
        "REQUEST_ID_EMITTED=false",
        "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
        "ENDPOINT_VALUES_EMITTED=false",
        "RTP_IDENTIFIER_VALUES_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        "HEX_PAYLOAD_EMITTED=false",
        "BASE64_PAYLOAD_EMITTED=false",
        "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "DOOR_ACTION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "ACK_SIGNALING_SENT=false",
        "=== END COMELIT ENTRANCE CLIENT MEDIA SIGNALING FIELD SOURCES PCAP FORENSIC ===",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    analysis = select_vip_flow(capture)
    try:
        frames = collect_extended_vip_frames(analysis)
        datagrams = _read_selected_datagrams(args.pcap, client=analysis.client, device=analysis.device)
        result = analyze(frames, client=analysis.client, device=analysis.device, datagrams=datagrams)
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
