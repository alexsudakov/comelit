#!/usr/bin/env python3
"""P70: compose independent evidence for deterministic RTPC OPEN generation.

P66 already establishes that the two client RTPC targets are runtime-generated
correlation IDs. P69 establishes the 15-byte RTPC OPEN envelope/pairing while
observing (but intentionally not interpreting) body byte 14.

P70 adds one independent, frozen implementation provenance record showing that
the same ViP OPEN field is a trailing byte, that RTPC uses value 1, and that
channel-open request IDs are allocated locally and sequentially. This promotes
a generation rule without claiming the semantic meaning of the trailing byte.

The module is offline only. It performs no network I/O or signaling.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path

import entrance_rtpc_control_open_contract_pcap_forensic as p66
import entrance_rtpc_open_trailer_pcap_forensic as p69


@dataclass(frozen=True)
class IndependentGenerationEvidence:
    repository: str
    ref: str
    protocol_reference_path: str
    encoder_path: str
    allocator_path: str
    field_name: str
    ordinary_default: int
    rtpc_value: int
    rtpc_open_call_count: int
    sequential_local_allocator: bool


DEFAULT_INDEPENDENT_EVIDENCE = IndependentGenerationEvidence(
    repository="antoiba86/hass-comelit-intercom-local",
    ref="826d2c941cbe110ce3887494ae37fcaccd17bae0",
    protocol_reference_path="protocol_reference_mnestrud_6701W.md",
    encoder_path="custom_components/comelit_intercom_local/protocol.py",
    allocator_path="custom_components/comelit_intercom_local/client.py",
    field_name="trailing_byte",
    ordinary_default=0,
    rtpc_value=1,
    rtpc_open_call_count=2,
    sequential_local_allocator=True,
)


@dataclass(frozen=True)
class Result:
    structural_pairing_ok: bool
    runtime_id_generation_ok: bool
    runtime_ids_sequential: bool
    independent_trailing_evidence_ok: bool
    independent_allocator_evidence_ok: bool
    observed_rtpc_trailer_value: int | None
    trailer_generation_contract_ok: bool
    client_target_generation_contract_ok: bool
    open_body_generation_contract_ok: bool


def _independent_trailing_evidence_ok(evidence: IndependentGenerationEvidence) -> bool:
    return bool(
        evidence.repository
        and len(evidence.ref) == 40
        and evidence.protocol_reference_path
        and evidence.encoder_path
        and evidence.field_name == "trailing_byte"
        and evidence.ordinary_default == 0
        and evidence.rtpc_value == 1
        and evidence.rtpc_open_call_count >= 2
    )


def _independent_allocator_evidence_ok(evidence: IndependentGenerationEvidence) -> bool:
    return bool(
        evidence.repository
        and len(evidence.ref) == 40
        and evidence.allocator_path
        and evidence.sequential_local_allocator
    )


def analyze(
    id_result: p66.Result,
    trailer_result: p69.Result,
    evidence: IndependentGenerationEvidence = DEFAULT_INDEPENDENT_EVIDENCE,
) -> Result:
    trailer_values = tuple(item.scalar for item in trailer_result.trailers)
    observed_value = (
        trailer_values[0]
        if len(trailer_values) == 3 and len(set(trailer_values)) == 1
        else None
    )

    independent_trailing_ok = _independent_trailing_evidence_ok(evidence)
    independent_allocator_ok = _independent_allocator_evidence_ok(evidence)

    trailer_generation_ok = bool(
        trailer_result.structural_pairing_ok
        and trailer_result.client_trailers_equal
        and trailer_result.all_trailers_equal
        and observed_value == evidence.rtpc_value == 1
        and independent_trailing_ok
    )

    client_target_generation_ok = bool(
        id_result.runtime_generation_contract_ok
        and id_result.request_ids_sequential
        and trailer_result.client_ids_ok
        and trailer_result.peer_id_distinct
        and independent_allocator_ok
    )

    open_body_generation_ok = bool(
        trailer_result.structural_pairing_ok
        and trailer_generation_ok
        and client_target_generation_ok
    )

    return Result(
        structural_pairing_ok=trailer_result.structural_pairing_ok,
        runtime_id_generation_ok=id_result.runtime_generation_contract_ok,
        runtime_ids_sequential=id_result.request_ids_sequential,
        independent_trailing_evidence_ok=independent_trailing_ok,
        independent_allocator_evidence_ok=independent_allocator_ok,
        observed_rtpc_trailer_value=observed_value,
        trailer_generation_contract_ok=trailer_generation_ok,
        client_target_generation_contract_ok=client_target_generation_ok,
        open_body_generation_contract_ok=open_body_generation_ok,
    )


def report(result: Result) -> str:
    observed = (
        str(result.observed_rtpc_trailer_value)
        if result.observed_rtpc_trailer_value is not None
        else "NOT_UNIQUE"
    )
    lines = [
        "=== COMELIT P70 RTPC OPEN GENERATION CONTRACT ===",
        f"P69_STRUCTURAL_PAIRING_CONTRACT={'PASS' if result.structural_pairing_ok else 'NOT_PROVEN'}",
        f"P66_RUNTIME_ID_GENERATION_CONTRACT={'PASS' if result.runtime_id_generation_ok else 'NOT_PROVEN'}",
        f"RUNTIME_IDS_SEQUENTIAL={str(result.runtime_ids_sequential).lower()}",
        f"INDEPENDENT_TRAILING_EVIDENCE={'PASS' if result.independent_trailing_evidence_ok else 'NOT_PROVEN'}",
        f"INDEPENDENT_ALLOCATOR_EVIDENCE={'PASS' if result.independent_allocator_evidence_ok else 'NOT_PROVEN'}",
        f"OPEN_TRAILER_OBSERVED_VALUE={observed}",
        f"RTPC_OPEN_TRAILING_GENERATION_CONTRACT={'PASS' if result.trailer_generation_contract_ok else 'NOT_PROVEN'}",
        "OPEN_TRAILER_SEMANTICS=NOT_PROVEN",
        f"CLIENT_TARGET_GENERATION_CONTRACT={'PASS' if result.client_target_generation_contract_ok else 'NOT_PROVEN'}",
        f"RTPC_OPEN_BODY_GENERATION_CONTRACT={'PASS' if result.open_body_generation_contract_ok else 'NOT_PROVEN'}",
        "LIVE_RUN_AUTHORIZED=false",
        "INDEPENDENT_EVIDENCE_FETCHED_AT_RUNTIME=false",
        "REQUEST_ID_VALUES_EMITTED=false",
        "OTHER_CONTROL_BODY_VALUES_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "DOOR_ACTION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "=== END COMELIT P70 RTPC OPEN GENERATION CONTRACT ===",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != p66.EXPECTED_PCAP_SHA256:
            print("PCAP_SHA256_GATE=FAIL")
            print("NETWORK_IO_PERFORMED=false")
            return 2

        capture = p66.load_capture(args.pcap)
        if capture.sha256 != p66.EXPECTED_PCAP_SHA256:
            print("PCAP_SHA256_GATE=FAIL")
            print("NETWORK_IO_PERFORMED=false")
            return 2

        analysis = p66.select_vip_flow(capture)
        frames = p66.collect_extended_vip_frames(analysis)
        datagrams = p66._read_selected_datagrams(
            args.pcap,
            client=analysis.client,
            device=analysis.device,
        )
        id_result = p66.analyze(frames, p66._rtp_wrappers(datagrams))
        trailer_result = p69.analyze(frames)
        result = analyze(id_result, trailer_result)
    except (OSError, ValueError):
        print("P70_FORENSIC_GATE=FAIL")
        print("REQUEST_ID_VALUES_EMITTED=false")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print("PCAP_SHA256_GATE=PASS")
    print(report(result))
    return 0 if result.open_body_generation_contract_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
