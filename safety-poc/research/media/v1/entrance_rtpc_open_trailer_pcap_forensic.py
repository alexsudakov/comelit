#!/usr/bin/env python3
"""P69: isolate the unproven RTPC OPEN trailer from structural pairing.

P68 rejected every OPEN solely because it assumed byte 14 was zero. That also
removed the OPENs from pairing and concealed their relationships. Preserve P68
unchanged, and independently test pairing using the known envelope and target
field. This does not validate the trailer or authorize generation of any body.

For this specific forensic task, emit only the single unsigned byte at OPEN
offset 14, after verifying the complete 15-byte RTPC envelope. This bounded
scalar observation is needed to replace the rejected zero assumption. Never
emit targets, other body bytes, addresses, raw payload or media. No network I/O.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path

import entrance_rtpc_control_pairing_pcap_forensic as p68


def open_envelope(body: bytes) -> bool:
    return bool(
        len(body) == 15 and p68._word(body, 0, 2) == 0xABCD
        and p68._word(body, 2, 2) == 1 and p68._word(body, 4, 4) == 7
        and p68._channel(body) != "UNKNOWN" and p68._word(body, 12, 2) != 0
    )


@dataclass(frozen=True)
class Trailer:
    packet: int
    direction: str
    ordinal: int
    scalar: int


@dataclass(frozen=True)
class Result:
    control_count: int
    open_count: int
    trailers: tuple[Trailer, ...]
    pairs: tuple[p68.Pair, ...]
    client_trailers_equal: bool
    all_trailers_equal: bool
    client_ids_ok: bool
    peer_id_distinct: bool
    structural_pairing_ok: bool


def analyze(frames) -> Result:
    ordered = tuple(sorted(frames, key=lambda f: (f.timestamp, f.first_packet)))
    if any(f.direction not in ("CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT") for f in ordered):
        raise ValueError("invalid direction")
    controls = tuple(f for f in ordered if f.request_id == 0
                     and p68.WINDOW_START <= f.first_packet <= p68.WINDOW_END)
    all_opens = tuple(f for f in ordered if f.request_id == 0 and open_envelope(f.body))
    opens = tuple(f for f in controls if open_envelope(f.body))
    responses = tuple(f for f in controls if len(f.body) == 12)
    client = tuple(f for f in opens if f.direction == "CLIENT_TO_DEVICE"
                   and f.first_packet == 206 and p68._channel(f.body) == "RTPC")
    peer = tuple(f for f in opens if f.direction == "DEVICE_TO_CLIENT"
                 and f.first_packet == 205 and p68._channel(f.body) == "RTPC")
    pairs = []
    for response in responses:
        matches = tuple(f for f in all_opens if f.direction != response.direction
                        and p68._before(f, response)
                        and f.body[12:14] == response.body[8:10])
        match = matches[0] if len(matches) == 1 else None
        pairs.append(p68.Pair(
            response.first_packet, response.direction, p68._response_shape(response.body),
            len(matches), match.first_packet if match else None,
            p68._channel(match.body) if match else "UNRESOLVED",
        ))
    ids = tuple(p68._word(f.body, 12, 2) for f in client)
    ids_ok = len(ids) == 2 and all(ids) and ids[0] != ids[1] and ((ids[1] - ids[0]) & 0xFFFF) == 1
    peer_distinct = len(peer) == 1 and len(ids) == 2 and p68._word(peer[0].body, 12, 2) not in ids
    expected = ((207, "DEVICE_TO_CLIENT", 206), (208, "CLIENT_TO_DEVICE", 205),
                (209, "DEVICE_TO_CLIENT", 206))
    pair_shape = tuple((p.response_packet, p.response_direction, p.open_packet) for p in pairs)
    structural_ok = bool(
        len(controls) == 6 and len(opens) == 3 and len(client) == 2 and len(peer) == 1
        and ids_ok and peer_distinct and pair_shape == expected
        and all(p.response_schema_ok and p.matching_open_count == 1 and p.open_channel == "RTPC" for p in pairs)
        and len({f.body[8:10] for f in responses if f.direction == "DEVICE_TO_CLIENT"}) == 2
    )
    trailers = tuple(Trailer(f.first_packet, f.direction, i, f.body[14])
                     for i, f in enumerate(opens, 1) if p68._channel(f.body) == "RTPC")
    client_equal = len(client) == 2 and client[0].body[14] == client[1].body[14]
    all_equal = len(trailers) == 3 and len({t.scalar for t in trailers}) == 1
    return Result(len(controls), len(opens), trailers, tuple(pairs), client_equal,
                  all_equal, bool(ids_ok), bool(peer_distinct), structural_ok)


def report(result: Result) -> str:
    lines = ["=== COMELIT P69 RTPC OPEN TRAILER ===",
             f"CONTROL_COUNT={result.control_count}", f"OPEN_ENVELOPE_COUNT={result.open_count}"]
    for t in result.trailers:
        lines.append(f"RTPC_OPEN_TRAILER packet={t.packet} direction={t.direction} ordinal={t.ordinal} offset=14 unsigned_scalar={t.scalar}")
    for p in result.pairs:
        packet = p.open_packet if p.open_packet is not None else "NONE"
        lines.append(f"PAIR response_packet={p.response_packet} direction={p.response_direction} response_schema={'PASS' if p.response_schema_ok else 'FAIL'} matching_open_count={p.matching_open_count} open_packet={packet} open_channel={p.open_channel}")
    lines.extend([
        f"CLIENT_OPEN_TRAILERS_EQUAL={str(result.client_trailers_equal).lower()}",
        f"ALL_THREE_OPEN_TRAILERS_EQUAL={str(result.all_trailers_equal).lower()}",
        f"CLIENT_IDS_DISTINCT_NONZERO_SEQUENTIAL={str(result.client_ids_ok).lower()}",
        f"PEER_TARGET_DISTINCT_FROM_CLIENT_TARGETS={str(result.peer_id_distinct).lower()}",
        f"RTPC_STRUCTURAL_PAIRING_CONTRACT={'PASS' if result.structural_pairing_ok else 'NOT_PROVEN'}",
        "OPEN_TRAILER_SEMANTICS=NOT_PROVEN", "LIVE_BODY_GENERATION_CONTRACT=NOT_PROVEN",
        "LIVE_RUN_AUTHORIZED_BY_ANALYZER=false", "CONTROL_TRAILER_SCALAR_EMITTED=true",
        "OTHER_CONTROL_BODY_VALUES_EMITTED=false", "REQUEST_ID_VALUES_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false", "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false", "DOOR_ACTION_SENT=false", "MEDIA_SIGNALING_SENT=false",
        "=== END COMELIT P69 RTPC OPEN TRAILER ===",
    ])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != p68.EXPECTED_PCAP_SHA256:
            print("PCAP_SHA256_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
            return 2
        capture = p68.load_capture(args.pcap)
        if capture.sha256 != p68.EXPECTED_PCAP_SHA256:
            print("PCAP_SHA256_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
            return 2
        print("PCAP_SHA256_GATE=PASS")
        frames = p68.collect_extended_vip_frames(p68.select_vip_flow(capture))
        result = analyze(frames)
    except (OSError, ValueError):
        print("FORENSIC_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
        return 3
    print(report(result))
    return 0 if result.structural_pairing_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
