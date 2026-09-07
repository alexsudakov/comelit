#!/usr/bin/env python3
"""Offline cross-capture forensic for unresolved entrance media-signaling fields.

P61/P62 reduced the remaining unknown client signaling bytes to three fields:

* CLIENT_000A[10:12]
* CLIENT_001A[10:12]
* CLIENT_001A[24:33]

P63 compares those fields across two independent official-app self-activation
captures.  The first capture is the frozen baseline.  The second capture must be
different and must contain one unambiguous client 0x000a and one client 0x001a
frame on the selected ViP flow.

Only equality/change relationships and session-independence markers are emitted.
No field values, request ids, protocol addresses, endpoints, RTP identifiers,
raw/hex/base64 payload, or media bytes are emitted.  No network I/O is performed
and no signaling is sent.
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

RTP_OFFSET = 8


@dataclass(frozen=True)
class SessionEvidence:
    request_id: int
    client_000a_sequence: int
    client_001a_sequence: int
    client_000a_field_10_11: bytes
    client_001a_field_10_11: bytes
    client_001a_field_24_32: bytes
    device_000a_field_10_11: bytes
    uplink_rtp_sequence: int
    uplink_rtp_timestamp: int
    uplink_rtp_ssrc: int
    uplink_wrapper: bytes


@dataclass(frozen=True)
class FieldComparison:
    label: str
    same_across_captures: bool
    mirrors_device_000a_in_baseline: bool | None
    mirrors_device_000a_in_second: bool | None


@dataclass(frozen=True)
class ComparisonResult:
    changed_session_markers: tuple[str, ...]
    unchanged_session_markers: tuple[str, ...]
    independence_pass: bool
    fields: tuple[FieldComparison, ...]


def _find_unique(
    frames: Iterable[VipFrame], *, direction: str, action: int, body_len: int
) -> VipFrame:
    matches = [
        frame
        for frame in frames
        if frame.direction == direction
        and frame.action == action
        and frame.body_length == body_len
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {direction} action=0x{action:04x} body_len={body_len}, found {len(matches)}"
        )
    return matches[0]


def _first_uplink_pt8(datagrams, *, client, device, boundary_packet: int):
    matches = []
    for item in _opaque(datagrams, boundary_packet):
        if item.source != client or item.target != device or len(item.payload) <= RTP_OFFSET:
            continue
        inner = item.payload[RTP_OFFSET:]
        meta = _parse_rtp_v2_shape(inner)
        if meta is None or meta.payload_type != 8:
            continue
        timestamp = int.from_bytes(inner[4:8], "big")
        matches.append((item.packet_number, item.payload[:RTP_OFFSET], meta, timestamp))
    if not matches:
        raise ValueError("no client-to-device PT8 wrapped RTP after client 0x001a")
    matches.sort(key=lambda item: item[0])
    return matches[0]


def extract_session(pcap: Path) -> SessionEvidence:
    capture = load_capture(pcap)
    analysis = select_vip_flow(capture)
    frames = tuple(collect_extended_vip_frames(analysis))

    c000a = _find_unique(
        frames, direction="CLIENT_TO_DEVICE", action=0x000A, body_len=44
    )
    d000a = _find_unique(
        frames, direction="DEVICE_TO_CLIENT", action=0x000A, body_len=44
    )
    c001a = _find_unique(
        frames, direction="CLIENT_TO_DEVICE", action=0x001A, body_len=60
    )
    if not (c000a.request_id == d000a.request_id == c001a.request_id):
        raise ValueError("target frames do not share one CTPP request id")
    if c000a.sequence is None or c001a.sequence is None:
        raise ValueError("target frame sequence missing")

    datagrams = _read_selected_datagrams(
        pcap, client=analysis.client, device=analysis.device
    )
    _packet, wrapper, meta, timestamp = _first_uplink_pt8(
        datagrams,
        client=analysis.client,
        device=analysis.device,
        boundary_packet=c001a.last_packet,
    )

    return SessionEvidence(
        request_id=c000a.request_id,
        client_000a_sequence=c000a.sequence,
        client_001a_sequence=c001a.sequence,
        client_000a_field_10_11=c000a.body[10:12],
        client_001a_field_10_11=c001a.body[10:12],
        client_001a_field_24_32=c001a.body[24:33],
        device_000a_field_10_11=d000a.body[10:12],
        uplink_rtp_sequence=meta.sequence,
        uplink_rtp_timestamp=timestamp,
        uplink_rtp_ssrc=meta.ssrc,
        uplink_wrapper=wrapper,
    )


def compare_sessions(baseline: SessionEvidence, second: SessionEvidence) -> ComparisonResult:
    marker_pairs = (
        ("CTPP_REQUEST_ID", baseline.request_id, second.request_id),
        ("CLIENT_000A_SEQUENCE", baseline.client_000a_sequence, second.client_000a_sequence),
        ("CLIENT_001A_SEQUENCE", baseline.client_001a_sequence, second.client_001a_sequence),
        ("UPLINK_RTP_SEQUENCE", baseline.uplink_rtp_sequence, second.uplink_rtp_sequence),
        ("UPLINK_RTP_TIMESTAMP", baseline.uplink_rtp_timestamp, second.uplink_rtp_timestamp),
        ("UPLINK_RTP_SSRC", baseline.uplink_rtp_ssrc, second.uplink_rtp_ssrc),
        ("UPLINK_WRAPPER", baseline.uplink_wrapper, second.uplink_wrapper),
    )
    changed = tuple(label for label, left, right in marker_pairs if left != right)
    unchanged = tuple(label for label, left, right in marker_pairs if left == right)

    fields = (
        FieldComparison(
            label="CLIENT_000A_10_11",
            same_across_captures=(baseline.client_000a_field_10_11 == second.client_000a_field_10_11),
            mirrors_device_000a_in_baseline=(baseline.client_000a_field_10_11 == baseline.device_000a_field_10_11),
            mirrors_device_000a_in_second=(second.client_000a_field_10_11 == second.device_000a_field_10_11),
        ),
        FieldComparison(
            label="CLIENT_001A_10_11",
            same_across_captures=(baseline.client_001a_field_10_11 == second.client_001a_field_10_11),
            mirrors_device_000a_in_baseline=None,
            mirrors_device_000a_in_second=None,
        ),
        FieldComparison(
            label="CLIENT_001A_24_32",
            same_across_captures=(baseline.client_001a_field_24_32 == second.client_001a_field_24_32),
            mirrors_device_000a_in_baseline=None,
            mirrors_device_000a_in_second=None,
        ),
    )

    # Require multiple independent session markers to change before treating the
    # second capture as evidence about protocol constants.
    independence_pass = len(changed) >= 2
    return ComparisonResult(changed, unchanged, independence_pass, fields)


def report(result: ComparisonResult) -> str:
    lines = [
        "=== COMELIT ENTRANCE CROSS-CAPTURE SIGNALING FIELD FORENSIC ===",
        "BASELINE_PCAP_SHA256_GATE=PASS",
        "SECOND_PCAP_DISTINCT=true",
        f"SESSION_CHANGED_MARKER_COUNT={len(result.changed_session_markers)}",
        f"SESSION_UNCHANGED_MARKER_COUNT={len(result.unchanged_session_markers)}",
    ]
    for label in result.changed_session_markers:
        lines.append(f"SESSION_MARKER label={label} relation=CHANGED")
    for label in result.unchanged_session_markers:
        lines.append(f"SESSION_MARKER label={label} relation=SAME")
    lines.append(
        f"SESSION_INDEPENDENCE_GATE={'PASS' if result.independence_pass else 'FAIL'}"
    )

    constant_candidates = 0
    session_candidates = 0
    for field in result.fields:
        classification = (
            "PROTOCOL_CONSTANT_CANDIDATE"
            if field.same_across_captures and result.independence_pass
            else "SESSION_DEPENDENT_CANDIDATE"
            if not field.same_across_captures and result.independence_pass
            else "INCONCLUSIVE"
        )
        if classification == "PROTOCOL_CONSTANT_CANDIDATE":
            constant_candidates += 1
        elif classification == "SESSION_DEPENDENT_CANDIDATE":
            session_candidates += 1
        lines.append(
            "TARGET_FIELD_COMPARISON "
            f"label={field.label} same_across_captures={str(field.same_across_captures).lower()} "
            f"classification={classification}"
        )
        if field.mirrors_device_000a_in_baseline is not None:
            lines.append(
                "TARGET_FIELD_MIRROR "
                f"label={field.label} baseline={str(field.mirrors_device_000a_in_baseline).lower()} "
                f"second={str(field.mirrors_device_000a_in_second).lower()}"
            )

    lines.extend(
        [
            f"PROTOCOL_CONSTANT_CANDIDATE_COUNT={constant_candidates}",
            f"SESSION_DEPENDENT_CANDIDATE_COUNT={session_candidates}",
            "CROSS_CAPTURE_CONSTANT_EVIDENCE="
            + (
                "PASS"
                if result.independence_pass and constant_candidates == len(result.fields)
                else "PARTIAL"
                if result.independence_pass and constant_candidates > 0
                else "NONE"
            ),
            "LIVE_BODY_GENERATION_CONTRACT=REVIEW_REQUIRED",
            "FIELD_VALUES_EMITTED=false",
            "REQUEST_ID_VALUES_EMITTED=false",
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
            "=== END COMELIT ENTRANCE CROSS-CAPTURE SIGNALING FIELD FORENSIC ===",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-pcap", type=Path, required=True)
    parser.add_argument("--second-pcap", type=Path, required=True)
    parser.add_argument("--expected-baseline-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    baseline_sha = hashlib.sha256(args.baseline_pcap.read_bytes()).hexdigest()
    second_sha = hashlib.sha256(args.second_pcap.read_bytes()).hexdigest()
    if baseline_sha != args.expected_baseline_sha256.lower():
        print("BASELINE_PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2
    if second_sha == baseline_sha:
        print("SECOND_PCAP_DISTINCT=false")
        print("SESSION_INDEPENDENCE_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    try:
        baseline = extract_session(args.baseline_pcap)
        second = extract_session(args.second_pcap)
        result = compare_sessions(baseline, second)
    except ValueError as exc:
        print(f"CROSS_CAPTURE_GATE=FAIL reason={type(exc).__name__}")
        print("FIELD_VALUES_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 4

    print(report(result))
    return 0 if result.independence_pass else 5


if __name__ == "__main__":
    raise SystemExit(main())
