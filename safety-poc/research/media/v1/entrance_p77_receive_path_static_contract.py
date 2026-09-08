#!/usr/bin/env python3
"""P77 bounded static receive-path evidence table.

The table promotes only symbol inventory and bounded disassembly observations
from the P77 harvest. It does not claim the unresolved RTPC callback call graph.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticFinding:
    component: str
    symbol: str
    address: str
    size: int | None
    status: str
    evidence: str


FINDINGS: tuple[StaticFinding, ...] = (
    StaticFinding(
        "JNI",
        "Java_com_comelitgroup_comelitvipkit_VipEngine_addReceivedPacketFromSocket",
        "0x1104c",
        156,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:261",
    ),
    StaticFinding(
        "ENGINE",
        "ComelitEngine::sysViperAddReceivedPacketFromSocket(int, char*, int)",
        "0x88940",
        268,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:1015",
    ),
    StaticFinding(
        "TUNNEL",
        "ViperTunnel::setReceivedCbk(viper_channel_str*, int (*)(viper_channel_str*, void*, void*, int), void*)",
        "0x9bc40",
        216,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:592",
    ),
    StaticFinding(
        "TUNNEL",
        "ViperTunnel::onNewIncomingChannel(viper_tunnel_str*, viper_channel_str*, unsigned int, void const*, unsigned long)",
        "0x9b938",
        776,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:772",
    ),
    StaticFinding(
        "MEDIA_RX",
        "ViperTunnel::openMediaRXChannel(int (*)(viper_channel_str*, void*, void*, int), int*, void*)",
        "0x9b2b4",
        248,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:1861",
    ),
    StaticFinding(
        "MEDIA_RX",
        "ViperTunnel::closeMediaRXChannel(viper_channel_str*, int)",
        "0x9b3ac",
        304,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:1252",
    ),
    StaticFinding(
        "RTP_RX",
        "RtpDispatcher::threadVideoRX()",
        "0x79e24",
        240,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:1280",
    ),
    StaticFinding(
        "RTP_RX",
        "RtpDispatcher::threadAudioRX()",
        "0x79f14",
        240,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:441",
    ),
    StaticFinding(
        "TEARDOWN",
        "Java_com_comelitgroup_comelitvipkit_VipEngine_closeChannel",
        "0x111ac",
        64,
        "PROVEN_STATIC_SYMBOL",
        ".p77-work/outputs/native_symbols_key.out:209",
    ),
)

UNPROVEN_CLAIMS: tuple[str, ...] = (
    "EXACT_RTPC_CALLBACK_CALL_GRAPH",
    "DEDICATED_RTPC_RECEIVE_THREAD_MODEL",
    "CONTROL_TO_OFFSET8_RTP_FIELD_BINDING",
    "LISTENER_STOP_REQUIRED",
)


def validate_contract() -> None:
    if not FINDINGS:
        raise ValueError("empty static finding table")
    for finding in FINDINGS:
        if finding.status != "PROVEN_STATIC_SYMBOL":
            raise ValueError(f"unexpected finding status: {finding.status}")
        if not finding.address.startswith("0x"):
            raise ValueError(f"address is not explicit: {finding.symbol}")
        if finding.size is not None and finding.size <= 0:
            raise ValueError(f"invalid symbol size: {finding.symbol}")
    if "LISTENER_STOP_REQUIRED" not in UNPROVEN_CLAIMS:
        raise ValueError("listener/media ownership gap must remain explicit")


def report() -> str:
    validate_contract()
    lines = [
        "=== COMELIT P77 RECEIVE PATH STATIC CONTRACT ===",
        "RTPC_RECEIVE_PATH_STATIC_PROVENANCE=PARTIAL",
        f"STATIC_FINDING_COUNT={len(FINDINGS)}",
    ]
    for finding in FINDINGS:
        lines.append(
            "STATIC_FINDING "
            f"component={finding.component} symbol={finding.symbol} "
            f"address={finding.address} size={finding.size} status={finding.status} evidence={finding.evidence}"
        )
    for claim in UNPROVEN_CLAIMS:
        lines.append(f"NOT_PROVEN={claim}")
    lines.extend(
        [
            "RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "LISTENER_STOP_REQUIRED=NOT_PROVEN",
            "=== END COMELIT P77 RECEIVE PATH STATIC CONTRACT ===",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
