#!/usr/bin/env python3
"""P105 offline LEN=24 fallback forensic.

This analyzer is deterministic and offline-only.  Optional capture artifacts
are accepted behind authoritative SHA256 gates; absent artifacts are reported
as NOT_PROVIDED.  It emits only structural scalars, never payload bytes,
endpoint addresses, ports, tokens, or credentials.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from entrance_p101_preactive_profile_gate_transform import transform as add_p101_runtime
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    SelectedDatagram,
    _read_selected_datagrams,
)
from pseudotcp_pcap_handshake_forensic import load_capture, select_vip_flow


DEFAULT_SOURCE = (
    HERE.parents[1] / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
)
EXPECTED_SHA256 = {
    "self_activation.pcap": "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
    "p2p_rtsp.pcap": "62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3",
}
EXIT_OK = 0
EXIT_WRONG_DIGEST = 2
EXIT_PARSE_ERROR = 3
EXIT_EVIDENCE_MISMATCH = 4


@dataclass(frozen=True)
class ReceiveFact:
    name: str
    line: int


@dataclass(frozen=True)
class DatagramShape:
    length: int
    wrapper_inner_len_le16: int
    wrapper_len_consistent: bool
    byte0_version_bits_at_0: int
    byte0_version_bits_at_8: int
    rtp_pt_at_8: int
    rtp_pt_99_or_8: bool
    rtcp_pt_at_8: int
    rtcp_pt_range: bool
    stun_magic_present: bool
    pseudotcp_header_shape: bool
    pseudotcp_flags_byte: int


@dataclass(frozen=True)
class DatagramEvidence:
    packet_number: int
    direction: str
    lane: str
    shape: DatagramShape
    offset8_wrapped_rtp: bool


@dataclass(frozen=True)
class CaptureResult:
    label: str
    sha256_status: str
    len24_count: int | None
    histograms: tuple[tuple[str, tuple[tuple[int, int], ...]], ...]
    len24: tuple[DatagramEvidence, ...]
    same_lane_non_offset8: tuple[DatagramEvidence, ...]
    verdict: str
    classification: str
    evidence: str
    hypotheses: tuple[tuple[str, str, str], ...]


def _line_of(text: str, needle: str, start: int = 0) -> int:
    index = text.find(needle, start)
    if index < 0:
        raise ValueError(f"receive-path marker not found: {needle}")
    return text.count("\n", 0, index) + 1


def _block_end(text: str, open_index: int) -> int:
    depth = 0
    in_string = False
    in_char = False
    escaped = False
    for index in range(open_index, len(text)):
        ch = text[index]
        if escaped:
            escaped = False
            continue
        if (in_string or in_char) and ch == "\\":
            escaped = True
            continue
        if not in_char and ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch == "'":
            in_char = not in_char
            continue
        if in_string or in_char:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unterminated block")


def receive_path_facts(source_text: str) -> tuple[ReceiveFact, ...]:
    candidate = add_p101_runtime(source_text)
    start = candidate.find("static void\nrecv_cb(")
    if start < 0:
        raise ValueError("recv_cb not found")
    open_i = candidate.find("{", start)
    end = _block_end(candidate, open_i)
    body = candidate[start:end]

    markers = (
        ("P80_INTERCEPT", "p80_try_forward_wrapped_rtp((const guint8 *)buf, len)"),
        ("PSEUDOTCP_NULL_EARLY_RETURN", "if (!pseudo_tcp)"),
        ("PSEUDOTCP_NOTIFY_PACKET_CALL", "pseudo_tcp_socket_notify_packet("),
        ("NOTIFY_FAILURE_BRANCH", "if (!ok)"),
        ("NOTIFY_FAILURE_FAILED_TRUE", "failed = TRUE;"),
        ("NOTIFY_FAILURE_LOOP_QUIT", "g_main_loop_quit(loop);"),
    )
    facts_list: list[ReceiveFact] = []
    search_from = start
    for name, needle in markers:
        index = candidate.find(needle, search_from)
        if index < 0:
            raise ValueError(f"receive-path marker not found: {needle}")
        facts_list.append(ReceiveFact(name, candidate.count("\n", 0, index) + 1))
        search_from = index + len(needle)
    facts = tuple(facts_list)
    ordered = [fact.line for fact in facts]
    if ordered != sorted(ordered):
        raise ValueError("receive-path markers are not in expected order")
    if body.count("pseudo_tcp_socket_notify_packet(") != 1:
        raise ValueError("receive-path notify call count mismatch")
    return facts


def _le16_at(payload: bytes, offset: int) -> int:
    if len(payload) < offset + 2:
        return 0
    return payload[offset] | (payload[offset + 1] << 8)


def _version_bits(payload: bytes, offset: int) -> int:
    if len(payload) <= offset:
        return 0
    return (payload[offset] >> 6) & 3


def pseudotcp_header_shape(payload: bytes) -> tuple[bool, int]:
    """Return the exact P105 24-byte PseudoTCP header predicate.

    Predicate: length is exactly 24, conversation is big-endian zero, the flags
    byte uses only known libnice FIN/CTL/RST bits, and the reserved bytes after
    the advertised window are all zero.  This is structural only; it does not
    prove semantic ownership of the datagram.
    """
    flags = payload[13] if len(payload) > 13 else 0
    if len(payload) != 24:
        return False, flags
    conversation_zero = payload[0:4] == b"\x00\x00\x00\x00"
    known_flags = (flags & ~0x07) == 0
    reserved_zero = payload[16:24] == b"\x00" * 8
    return conversation_zero and known_flags and reserved_zero, flags


def classify_datagram(payload: bytes) -> DatagramShape:
    inner_len = _le16_at(payload, 2)
    version0 = _version_bits(payload, 0)
    version8 = _version_bits(payload, 8)
    pt8 = payload[9] & 0x7F if len(payload) > 9 else 0
    rtcp_pt8 = payload[9] if len(payload) > 9 else 0
    pseudo_shape, flags = pseudotcp_header_shape(payload)
    return DatagramShape(
        length=len(payload),
        wrapper_inner_len_le16=inner_len,
        wrapper_len_consistent=(inner_len + 8 == len(payload)),
        byte0_version_bits_at_0=version0,
        byte0_version_bits_at_8=version8,
        rtp_pt_at_8=pt8,
        rtp_pt_99_or_8=pt8 in (99, 8),
        rtcp_pt_at_8=rtcp_pt8,
        rtcp_pt_range=(version8 == 2 and 200 <= rtcp_pt8 <= 211),
        stun_magic_present=(len(payload) >= 8 and payload[4:8] == b"\x21\x12\xa4\x42"),
        pseudotcp_header_shape=pseudo_shape,
        pseudotcp_flags_byte=flags,
    )


def offset8_wrapped_rtp(shape: DatagramShape) -> bool:
    return (
        shape.wrapper_len_consistent
        and shape.byte0_version_bits_at_8 == 2
        and shape.rtp_pt_99_or_8
    )


def hypothesis_table(shapes: tuple[DatagramShape, ...]) -> tuple[tuple[str, str, str], ...]:
    if not shapes:
        return tuple(
            (role, "NOT_DECIDABLE_OFFLINE", "no LEN=24 datagram observed")
            for role in (
                "offset-8 wrapped RTP",
                "RTCP",
                "PseudoTCP/control frame",
                "CTPP/control",
                "other already-known protocol frame",
                "malformed/unexpected input",
                "UNKNOWN",
            )
        )
    any_rtp = any(offset8_wrapped_rtp(shape) for shape in shapes)
    any_rtcp = any(shape.rtcp_pt_range for shape in shapes)
    any_pseudo = any(shape.pseudotcp_header_shape for shape in shapes)
    any_stun = any(shape.stun_magic_present for shape in shapes)
    all_no_known = all(
        not offset8_wrapped_rtp(shape)
        and not shape.rtcp_pt_range
        and not shape.pseudotcp_header_shape
        and not shape.stun_magic_present
        for shape in shapes
    )
    return (
        (
            "offset-8 wrapped RTP",
            "SUPPORTED" if any_rtp else "REFUTED",
            "wrapper len consistent, offset8 version bits are 2, and PT is 99/8"
            if any_rtp
            else "no LEN=24 datagram clears wrapper/version/PT 99-or-8 gates",
        ),
        (
            "RTCP",
            "SUPPORTED" if any_rtcp else "REFUTED",
            "offset8 version bits are 2 and packet type is in 200..211"
            if any_rtcp
            else "no LEN=24 datagram has offset8 RTCP packet-type range",
        ),
        (
            "PseudoTCP/control frame",
            "SUPPORTED" if any_pseudo else "REFUTED",
            "24-byte PseudoTCP header predicate matched"
            if any_pseudo
            else "24-byte PseudoTCP header predicate did not match",
        ),
        (
            "CTPP/control",
            "NOT_DECIDABLE_OFFLINE",
            "no payload bytes or live stream state are available to bind a CTPP semantic role",
        ),
        (
            "other already-known protocol frame",
            "SUPPORTED" if any_stun else "REFUTED",
            "STUN magic is present at datagram offset 4" if any_stun else "no STUN magic at datagram offset 4",
        ),
        (
            "malformed/unexpected input",
            "SUPPORTED" if all_no_known else "NOT_DECIDABLE_OFFLINE",
            "none of the structural known-protocol predicates matched"
            if all_no_known
            else "some known structural predicate matched but semantics remain offline-limited",
        ),
        (
            "UNKNOWN",
            "NOT_DECIDABLE_OFFLINE",
            "structural evidence is insufficient for a unique semantic classification",
        ),
    )


def verdict_for(shapes: tuple[DatagramShape, ...]) -> tuple[str, str, str]:
    if not shapes:
        return "NOT_OBSERVED", "UNKNOWN", "no LEN=24 datagram observed in gated capture"
    supported = [role for role, status, _ in hypothesis_table(shapes) if status == "SUPPORTED"]
    semantic = [role for role in supported if role != "malformed/unexpected input"]
    if len(semantic) == 1 and len(supported) == 1:
        return "PROVEN_CLASSIFIED", semantic[0], f"unique structural predicate: {semantic[0]}"
    if supported == ["malformed/unexpected input"]:
        return "OBSERVED_UNRESOLVED", "UNKNOWN", "LEN=24 observed but no known structural predicate matched"
    if supported:
        return "OBSERVED_UNRESOLVED", "UNKNOWN", "LEN=24 observed with non-unique structural predicates"
    return "OBSERVED_UNRESOLVED", "UNKNOWN", "LEN=24 observed without decisive semantic evidence"


def _direction(item: SelectedDatagram, client, device) -> str:
    if item.source == client and item.target == device:
        return "CLIENT_TO_DEVICE"
    if item.source == device and item.target == client:
        return "DEVICE_TO_CLIENT"
    return "UNKNOWN_DIRECTION"


def analyze_capture(path: Path | None) -> CaptureResult:
    if path is None:
        hypotheses = hypothesis_table(tuple())
        verdict, classification, evidence = verdict_for(tuple())
        return CaptureResult("NOT_PROVIDED", "NOT_PROVIDED", None, tuple(), tuple(), tuple(), verdict, classification, evidence, hypotheses)

    expected = EXPECTED_SHA256.get(path.name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise SystemExit(EXIT_WRONG_DIGEST)

    capture = load_capture(path)
    analysis = select_vip_flow(capture)
    datagrams = _read_selected_datagrams(path, client=analysis.client, device=analysis.device)

    pair_ids: dict[object, str] = {}
    hist: dict[str, Counter[int]] = {}
    for item in datagrams:
        key = tuple(sorted((item.source, item.target)))
        if key not in pair_ids:
            pair_ids[key] = f"LANE_{len(pair_ids) + 1}"
        lane = pair_ids[key]
        hist.setdefault(lane, Counter())[len(item.payload)] += 1

    len24_items: list[DatagramEvidence] = []
    lane_with_len24: set[str] = set()
    for item in datagrams:
        shape = classify_datagram(item.payload)
        lane = pair_ids[tuple(sorted((item.source, item.target)))]
        if len(item.payload) == 24:
            lane_with_len24.add(lane)
            len24_items.append(
                DatagramEvidence(item.packet_number, _direction(item, analysis.client, analysis.device), lane, shape, offset8_wrapped_rtp(shape))
            )

    residual: list[DatagramEvidence] = []
    for item in datagrams:
        lane = pair_ids[tuple(sorted((item.source, item.target)))]
        if lane not in lane_with_len24:
            continue
        shape = classify_datagram(item.payload)
        if not offset8_wrapped_rtp(shape):
            residual.append(
                DatagramEvidence(item.packet_number, _direction(item, analysis.client, analysis.device), lane, shape, False)
            )

    shapes = tuple(item.shape for item in len24_items)
    verdict, classification, evidence = verdict_for(shapes)
    return CaptureResult(
        path.name,
        "PASS",
        len(len24_items),
        tuple((lane, tuple(sorted(counter.items()))) for lane, counter in sorted(hist.items())),
        tuple(len24_items),
        tuple(residual[:40]),
        verdict,
        classification,
        evidence,
        hypothesis_table(shapes),
    )


def report(source_path: Path, capture_result: CaptureResult) -> str:
    source_text = source_path.read_text(encoding="utf-8")
    facts = receive_path_facts(source_text)
    lines = [
        "=== COMELIT P105 LEN24 FALLBACK FORENSIC ===",
        "PCAP_SHA256_GATE=" + capture_result.sha256_status,
        "SOURCE_RECEIVE_PATH=P101_TRANSFORMED_FROM_FROZEN_SOURCE",
    ]
    for fact in facts:
        lines.append(f"RECEIVE_PATH_FACT name={fact.name} line={fact.line}")
    lines.extend(
        [
            "LEN24_WRAPPER_NON_UNIQUE=true",
            "LEN24_NOT_STRUCTURALLY_EXCLUDED_FROM_OFFSET8_WRAPPED_RTP=true",
            "LEN24_OFFSET8_INNER_LEN_REQUIRED=16",
            f"CAPTURE_LABEL={capture_result.label}",
            f"LEN24_DATAGRAM_COUNT={capture_result.len24_count if capture_result.len24_count is not None else 'NOT_PROVIDED'}",
        ]
    )
    for lane, buckets in capture_result.histograms:
        rendered = ",".join(f"{length}:{count}" for length, count in buckets)
        lines.append(f"DATAGRAM_SIZE_HISTOGRAM lane={lane} buckets={rendered}")
    for item in capture_result.len24:
        shape = item.shape
        lines.append(
            "LEN24_DATAGRAM "
            f"packet={item.packet_number} lane={item.lane} direction={item.direction} "
            f"wrapper_inner_len_le16={shape.wrapper_inner_len_le16} "
            f"wrapper_len_consistent={str(shape.wrapper_len_consistent).lower()} "
            f"byte0_version_bits_at_0={shape.byte0_version_bits_at_0} "
            f"byte0_version_bits_at_8={shape.byte0_version_bits_at_8} "
            f"rtp_pt_at_8={shape.rtp_pt_at_8} rtcp_pt_at_8={shape.rtcp_pt_at_8} "
            f"rtcp_pt_range={str(shape.rtcp_pt_range).lower()} "
            f"stun_magic_present={str(shape.stun_magic_present).lower()} "
            f"pseudotcp_header_shape={str(shape.pseudotcp_header_shape).lower()} "
            f"pseudotcp_flags_byte={shape.pseudotcp_flags_byte} "
            f"offset8_wrapped_rtp={str(item.offset8_wrapped_rtp).lower()}"
        )
    for item in capture_result.same_lane_non_offset8:
        lines.append(
            "SAME_LANE_NON_OFFSET8 "
            f"packet={item.packet_number} lane={item.lane} direction={item.direction} "
            f"len={item.shape.length} pseudotcp_header_shape={str(item.shape.pseudotcp_header_shape).lower()} "
            f"stun_magic_present={str(item.shape.stun_magic_present).lower()}"
        )
    for role, status, reason in capture_result.hypotheses:
        lines.append(f"HYPOTHESIS role={role} status={status} reason={reason}")
    lines.extend(
        [
            f"PSEUDOTCP_LEN24_VERDICT={capture_result.verdict}",
            f"PSEUDOTCP_LEN24_CLASSIFICATION={capture_result.classification}",
            f"PSEUDOTCP_LEN24_EVIDENCE={capture_result.evidence}",
            "RAW_PAYLOAD_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "DOOR_ACTION_SENT=false",
            "=== END COMELIT P105 LEN24 FALLBACK FORENSIC ===",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--pcap", type=Path)
    args = parser.parse_args(argv)

    try:
        result = analyze_capture(args.pcap)
        print(report(args.source, result))
        return EXIT_OK
    except SystemExit:
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return EXIT_WRONG_DIGEST
    except ValueError as exc:
        print(f"FORENSIC_PARSE_ERROR={type(exc).__name__}")
        print(f"FORENSIC_PARSE_DETAIL={exc}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return EXIT_PARSE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
