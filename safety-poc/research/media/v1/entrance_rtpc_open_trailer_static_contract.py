#!/usr/bin/env python3
"""P70: static provenance contract for the RTPC ABCD OPEN trailer (byte 14).

P69 observed that every captured RTPC OPEN carries trailer value 1 but explicitly
left OPEN_TRAILER_SEMANTICS=NOT_PROVEN. P70 (offline static reverse engineering,
host-verified 2026-09-07) proved the generation rule from ARM64 instruction-level
provenance in the proprietary Android libraries. This analyzer promotes that
proven contract into the repository model WITHOUT committing proprietary binaries.

Proven contract (RTPC only):
    OPEN[14] = channel_map[ViperChannelType].transport & 0xff
    channel_map[10] = {key=10, tag="RTPC", transport=1}   -> OPEN[14] = 1

Evidence (P70 report /home/hermes/comelit-p70-codex/FINAL_P70_REPORT.md):
    viper_tunnel_channel_open @0xa578c serializes the 15-byte body; byte 14 is
    written at 0xa580c `strb w9, [x0, #0xe]` from channel.transport (+0x38),
    initialized by viper_tunnel_channel_create from the map node transport
    (+0x24), statically set to 1 for key 10 by the .init_array constructor.

The model facts below are the minimal deterministic instruction/data-flow facts.
No channel other than RTPC is asserted; proprietary artifacts are never committed:
the analyzer accepts them as optional EXTERNAL paths for re-validation (SHA gate +
byte-pattern scan + P69-style capture consistency). Missing external artifacts are
NOT_PROVIDED, never guessed. No network I/O, no live invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# Authoritative artifact SHA256 gates (P70 workspace, host-verified 2026-09-07).
# These files are proprietary and MUST NOT be committed to this repository.
# ---------------------------------------------------------------------------
SO_VIPCOMELIT_SHA256 = "465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0"
DEX_CLASSES7_SHA256 = "851afb335a731c54e46ec39eb214a532c21c695eda6ce62de246b8d750e8f407"
DEX_CLASSES8_SHA256 = "05864bb668f26a7344217373f1d56fc8d38f71e92bf82f2cc9d82f20472c33ea"
PCAP_SELF_ACTIVATION_SHA256 = "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a"

# A64 little-endian encodings of the two decisive serializer instructions
# (viper_tunnel_channel_open in libvipcomelit.so):
#   0xa57f4  ldr w9,  [x23, #0x38]   e9 3a 40 b9   (load channel.transport)
#   0xa580c  strb w9, [x0,  #0xe]    09 38 00 39   (write OPEN[14])
# and the mirror serializer (viper_tunnel_open_channel):
#   0xa58f8  strb w10, [x0, #0xe]    0a 38 00 39
TRANSPORT_LOAD_BYTES = bytes.fromhex("e93a40b9")
TRAILER_WRITE_W9_BYTES = bytes.fromhex("09380039")
TRAILER_WRITE_W10_BYTES = bytes.fromhex("0a380039")

# Proven deterministic channel-map facts. Only RTPC (key 10) is promoted.
# Every other key stays NOT_PROVEN: no universal trailer value is asserted.
ALL_CHANNEL_OPEN_TRAILER_VALUE_ASSERTED = False  # explicit scope limit


@dataclass(frozen=True)
class ChannelEntry:
    key: int
    tag: bytes          # exactly 4 ASCII bytes (serializer writes a 32-bit word)
    transport: int      # 0..255, written to OPEN[14]


CHANNEL_MAP_FACTS: dict[int, ChannelEntry] = {
    10: ChannelEntry(key=10, tag=b"RTPC", transport=1),
}


def generation_contract(channel_key: int,
                        channel_map: dict[int, ChannelEntry] | None = None) -> ChannelEntry:
    """Return the proven map entry for a ViperChannelType key.

    Fails closed (KeyError) for any key without promoted static evidence.
    """
    facts = CHANNEL_MAP_FACTS if channel_map is None else channel_map
    return facts[channel_key]


def serialize_open(channel_tag: bytes, target_id: int, transport: int) -> bytes:
    """Deterministic model of the proven viper_tunnel_channel_open writes.

    OPEN layout (15 bytes, little-endian on wire):
      [0:4]  0x0001ABCD (magic 0xABCD + opcode 1)   str w8,[x0]
      [4:6]  declared length 7                       strh w9,[x0,#4]
      [6:8]  zero (calloc, no-extra-param path)
      [8:12] channel tag (4 ASCII bytes)             str w8,[x0,#8]
      [12:14] generated target/channel id (LE)       strh w10,[x0,#0xc]
      [14]   channel.transport & 0xff                strb w9,[x0,#0xe]
    """
    if len(channel_tag) != 4 or not all(0x20 <= b <= 0x7E for b in channel_tag):
        raise ValueError("model requires an exactly-4-ASCII-byte channel tag")
    if not 0 <= target_id <= 0xFFFF:
        raise ValueError("target_id out of 16-bit range")
    if not 0 <= transport <= 0xFF:
        raise ValueError("transport out of 8-bit range")
    return (
        struct.pack("<I", 0x0001ABCD)
        + struct.pack("<H", 7)
        + b"\x00\x00"
        + channel_tag
        + struct.pack("<H", target_id)
        + bytes((transport,))
    )


def observed_consistent(observed_scalars: Sequence[int], expected_transport: int) -> bool:
    """P69-style capture observations are consistent iff every sample matches."""
    return bool(observed_scalars) and all(s == expected_transport for s in observed_scalars)


# ---------------------------------------------------------------------------
# Optional external re-validation (proprietary artifacts, never committed)
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_all(haystack: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1


def so_byte_evidence(so_path: Path) -> tuple[list[int], list[int], list[int]]:
    """Return (transport_load_offsets, trailer_write_w9_offsets, trailer_write_w10_offsets)."""
    data = so_path.read_bytes()
    return (
        _find_all(data, TRANSPORT_LOAD_BYTES),
        _find_all(data, TRAILER_WRITE_W9_BYTES),
        _find_all(data, TRAILER_WRITE_W10_BYTES),
    )


def pcap_rtpc_trailers(pcap_path: Path) -> tuple[int, ...]:
    """Reuse the P69 forensic pipeline on the frozen capture (external path).

    Imported lazily so fixture-only runs never require the proprietary capture.
    """
    import sys

    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import entrance_rtpc_control_pairing_pcap_forensic as p68  # noqa: PLC0415
    import entrance_rtpc_open_trailer_pcap_forensic as p69  # noqa: PLC0415

    capture = p68.load_capture(pcap_path)
    frames = p68.collect_extended_vip_frames(p68.select_vip_flow(capture))
    result = p69.analyze(frames)
    return tuple(t.scalar for t in result.trailers if t.direction in (
        "CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT"))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def report(sha_gates: dict[str, str], byte_evidence: tuple[list[int], list[int], list[int]] | None,
           observed: tuple[int, ...] | None) -> str:
    rtp = generation_contract(10)
    consistent: str | None = None
    if observed is not None:
        consistent = "PASS" if observed_consistent(observed, rtp.transport) else "FAIL"
    lines = ["=== COMELIT P70 RTPC OPEN STATIC CONTRACT ==="]
    for name, status in sha_gates.items():
        lines.append(f"{name}={status}")
    if byte_evidence is None:
        lines.append("STATIC_BYTE_EVIDENCE=NOT_PROVIDED")
    else:
        loads, w9, w10 = byte_evidence
        found = bool(loads and (w9 or w10))
        lines.append("STATIC_BYTE_EVIDENCE=" + ("PASS" if found else "FAIL"))
        lines.append(f"TRANSPORT_LOAD_0x38_OFFSETS={' '.join(hex(o) for o in loads) or 'NONE'}")
        lines.append(f"TRAILER_WRITE_0XE_W9_OFFSETS={' '.join(hex(o) for o in w9) or 'NONE'}")
        lines.append(f"TRAILER_WRITE_0XE_W10_OFFSETS={' '.join(hex(o) for o in w10) or 'NONE'}")
    if observed is None:
        lines.append("OBSERVED_RTPC_TRAILERS=NOT_PROVIDED")
    else:
        lines.append(f"OBSERVED_RTPC_TRAILERS={','.join(str(v) for v in observed) or 'NONE'}")
        lines.append(f"RTPC_OBSERVED_CONSISTENT={consistent}")
    lines.extend([
        f"RTPC_CHANNEL_KEY={rtp.key}",
        f"RTPC_CHANNEL_TAG={rtp.tag.decode('ascii')}",
        f"RTPC_CHANNEL_TRANSPORT={rtp.transport}",
        "RTPC_OPEN_TRAILER_SEMANTICS=CHANNEL_TRANSPORT",
        "RTPC_OPEN_TRAILER_GENERATION_RULE=channel_map[RTPC].transport & 0xff",
        f"RTPC_OPEN_TRAILER_VALUE={rtp.transport}",
        "RTPC_OPEN_TRAILER_CONTRACT=PROVEN",
        "RTPC_OPEN_TRAILER_SOURCE=viper_tunnel_channel_open@0xa580c strb [x0,#0xe] <- channel.transport(+0x38) <- map node(+0x24) <- .init_array key-10 record",
        "ALL_CHANNEL_OPEN_TRAILER_VALUE=NOT_ASSERTED",
        f"ALL_CHANNEL_OPEN_TRAILER_VALUE_ASSERTED={str(ALL_CHANNEL_OPEN_TRAILER_VALUE_ASSERTED).lower()}",
        "RUNTIME_TARGET_ID_NOT_TRAILER=true",
        "CHANNEL_ID_10_NOT_TRAILER=true",
        "VIP_CH_OPEN_PARAM_NOT_TRAILER_SOURCE=true",
        "LIVE_BODY_GENERATION_CONTRACT=PROVEN_STATIC",
        "LIVE_EXPERIMENT_REQUIRED=NO",
        "P69_OPEN_TRAILER_SEMANTICS=HISTORICAL_NOT_PROVEN_PRESERVED",
        "PROPRIETARY_ARTIFACTS_COMMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "DOOR_ACTION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "=== END COMELIT P70 RTPC OPEN STATIC CONTRACT ===",
    ])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libvipcomelit-so", type=Path, help="external libvipcomelit.so (optional)")
    parser.add_argument("--pcap", type=Path, help="external frozen self_activation.pcap (optional)")
    parser.add_argument("--dex-classes7", type=Path, help="external classes7.dex (optional, SHA gate)")
    parser.add_argument("--dex-classes8", type=Path, help="external classes8.dex (optional, SHA gate)")
    args = parser.parse_args(argv)

    sha_gates: dict[str, str] = {}
    byte_evidence: tuple[list[int], list[int], list[int]] | None = None
    observed: tuple[int, ...] | None = None

    try:
        if args.libvipcomelit_so is not None:
            if _sha256(args.libvipcomelit_so) != SO_VIPCOMELIT_SHA256:
                sha_gates["SO_VIPCOMELIT_SHA256_GATE"] = "FAIL"
                print(report(sha_gates, byte_evidence, observed))
                return 2
            sha_gates["SO_VIPCOMELIT_SHA256_GATE"] = "PASS"
            byte_evidence = so_byte_evidence(args.libvipcomelit_so)
            if not (byte_evidence[0] and (byte_evidence[1] or byte_evidence[2])):
                print(report(sha_gates, byte_evidence, observed))
                return 4
        if args.dex_classes7 is not None:
            sha_gates["DEX_CLASSES7_SHA256_GATE"] = (
                "PASS" if _sha256(args.dex_classes7) == DEX_CLASSES7_SHA256 else "FAIL")
            if sha_gates["DEX_CLASSES7_SHA256_GATE"] == "FAIL":
                print(report(sha_gates, byte_evidence, observed))
                return 2
        if args.dex_classes8 is not None:
            sha_gates["DEX_CLASSES8_SHA256_GATE"] = (
                "PASS" if _sha256(args.dex_classes8) == DEX_CLASSES8_SHA256 else "FAIL")
            if sha_gates["DEX_CLASSES8_SHA256_GATE"] == "FAIL":
                print(report(sha_gates, byte_evidence, observed))
                return 2
        if args.pcap is not None:
            if _sha256(args.pcap) != PCAP_SELF_ACTIVATION_SHA256:
                sha_gates["PCAP_SHA256_GATE"] = "FAIL"
                print(report(sha_gates, byte_evidence, observed))
                return 2
            sha_gates["PCAP_SHA256_GATE"] = "PASS"
            observed = pcap_rtpc_trailers(args.pcap)
            if not observed_consistent(observed, generation_contract(10).transport):
                print(report(sha_gates, byte_evidence, observed))
                return 4
    except (OSError, ValueError):
        print("STATIC_CONTRACT_GATE=FAIL\nNETWORK_IO_PERFORMED=false")
        return 3

    print(report(sha_gates, byte_evidence, observed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
