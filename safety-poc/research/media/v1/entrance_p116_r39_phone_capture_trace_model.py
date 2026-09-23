"""P116 R39 — offline phone-capture trace model (classic pcap v2.4, LINKTYPE=101 Raw IP).

Purpose: turn one operator-provided phone-side capture (PCAPdroid export) into a bounded,
safe-scalar summary that can be committed. Everything here is offline: no sockets, no
network calls, no capture, no device contact, no protocol TX.

Safety contract (enforced by construction, see `assert_safe_summary`):

* never emits packet payload bytes, hexdumps, addresses (IPv4/IPv6), hostnames or SNI;
* never emits opaque peer identifiers -- remote peers appear as trace-local aliases
  (`R1`, `R2`, ...) assigned by first appearance and stable only within one trace;
* never extracts credentials, tokens or SDP;
* emits only: counts, durations, protocol/transport categories, direction roles,
  port numbers, byte counts and bounded booleans;
* fails closed (`PcapParseError`) on malformed, truncated or unsupported input instead of
  guessing.

CLI:  python3 entrance_p116_r39_phone_capture_trace_model.py <capture.pcap> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Iterable

LINKTYPE_RAW_IP = 101

PCAP_MAGIC_US_LE = b"\xd4\xc3\xb2\xa1"
PCAP_MAGIC_US_BE = b"\xa1\xb2\xc3\xd4"
PCAP_MAGIC_NS_LE = b"\x4d\x3c\xb2\xa1"
PCAP_MAGIC_NS_BE = b"\xa1\xb2\x3c\x4d"

PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"

IPPROTO_ICMP = 1
IPPROTO_TCP = 6
IPPROTO_UDP = 17

TLS_LIKE_PORT = 443
DNS_PORT = 53
STUN_PORT = 3478
KNOWN_KEEPALIVE_PORTS = frozenset({28450})

_IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_HEXDUMP_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[\s:]){8,}")
_HEXWORD_RE = re.compile(r"\b0x[0-9a-fA-F]{4,}\b")


class PcapParseError(RuntimeError):
    """Fail-closed parse failure: the input cannot be interpreted safely."""


@dataclass
class PacketRecord:
    ts_seconds: float
    included_length: int
    original_length: int
    data: bytes


@dataclass(frozen=True)
class FlowKey:
    protocol: str
    remote_alias: str
    local_port: int
    remote_port: int
    direction: str


@dataclass
class FlowStat:
    packets: int = 0
    payload_bytes: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    tcp_syn: int = 0
    tcp_ack: int = 0
    tcp_fin: int = 0
    tcp_rst: int = 0
    tcp_psh: int = 0
    transport_category: str = "OTHER"


@dataclass
class TraceSummary:
    capture_format: str = "classic-pcap"
    byte_order: str = ""
    timestamp_resolution: str = ""
    snaplen: int = 0
    linktype: int = 0
    packet_count: int = 0
    ipv4_packets: int = 0
    ipv6_packets: int = 0
    malformed_packets: int = 0
    protocol_counts: Counter = field(default_factory=Counter)
    transport_categories: Counter = field(default_factory=Counter)
    peer_count: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    inbound_packets: int = 0
    outbound_packets: int = 0
    flows: "OrderedDict[FlowKey, FlowStat]" = field(default_factory=OrderedDict)

    @property
    def duration_seconds(self) -> float:
        if self.packet_count == 0:
            return 0.0
        return round(self.last_ts - self.first_ts, 2)


def _read_header(blob: bytes) -> tuple[str, str, str, int, int, int]:
    if len(blob) < 24:
        raise PcapParseError("truncated_capture_header")
    magic = blob[:4]
    if magic == PCAPNG_MAGIC:
        raise PcapParseError("unsupported_capture_format_pcapng")
    if magic in (PCAP_MAGIC_US_LE, PCAP_MAGIC_US_BE):
        endian, resolution = ("little", "microsecond")
    elif magic in (PCAP_MAGIC_NS_LE, PCAP_MAGIC_NS_BE):
        endian, resolution = ("little", "nanosecond")
    else:
        raise PcapParseError("unsupported_capture_magic")

    order = "<" if magic in (PCAP_MAGIC_US_LE, PCAP_MAGIC_NS_LE) else ">"
    if order == ">":
        endian = "big"
    _, version_major, version_minor, _tz, _sig, snaplen, linktype = struct.unpack(
        order + "IHHiIII", blob[:24]
    )
    if version_major != 2 or version_minor not in (4, 0, 1, 2, 3):
        raise PcapParseError("unsupported_pcap_version")
    if linktype != LINKTYPE_RAW_IP:
        raise PcapParseError("unsupported_linktype_%d" % linktype)
    return (
        "classic-pcap-%d.%d" % (version_major, version_minor),
        endian,
        resolution,
        snaplen,
        linktype,
        8 if resolution == "nanosecond" else 6,
    )


def iter_records(blob: bytes) -> tuple[dict, list[PacketRecord]]:
    """Return (pcap_header, records). Raises PcapParseError on malformed input."""
    capture_format, endian, resolution, snaplen, linktype, _ = _read_header(blob)
    order = "<" if endian == "little" else ">"
    divisor = 1_000_000_000.0 if resolution == "nanosecond" else 1_000_000.0

    records: list[PacketRecord] = []
    offset = 24
    while offset < len(blob):
        if offset + 16 > len(blob):
            raise PcapParseError("truncated_packet_header")
        ts_sec, ts_frac, incl_len, orig_len = struct.unpack(order + "IIII", blob[offset : offset + 16])
        offset += 16
        if incl_len > snaplen or incl_len == 0:
            raise PcapParseError("invalid_included_length")
        if offset + incl_len > len(blob):
            raise PcapParseError("truncated_packet_payload")
        data = blob[offset : offset + incl_len]
        offset += incl_len
        records.append(
            PacketRecord(
                ts_seconds=ts_sec + ts_frac / divisor,
                included_length=incl_len,
                original_length=orig_len,
                data=data,
            )
        )
    if not records:
        raise PcapParseError("empty_capture")
    return (
        {
            "capture_format": capture_format,
            "byte_order": endian,
            "timestamp_resolution": resolution,
            "snaplen": snaplen,
            "linktype": linktype,
        },
        records,
    )


def _classify(protocol: str, remote_port: int, local_port: int) -> str:
    if protocol == "UDP":
        if remote_port == DNS_PORT or local_port == DNS_PORT:
            return "DNS"
        if remote_port == STUN_PORT or local_port == STUN_PORT:
            return "STUN"
        if remote_port in KNOWN_KEEPALIVE_PORTS or local_port in KNOWN_KEEPALIVE_PORTS:
            return "UDP_KEEPALIVE_CANDIDATE"
        return "UDP_OTHER"
    if protocol == "TCP":
        if remote_port == TLS_LIKE_PORT or local_port == TLS_LIKE_PORT:
            return "TCP_443_TLS_LIKE"
        if remote_port == DNS_PORT or local_port == DNS_PORT:
            return "DNS_TCP"
        return "TCP_OTHER"
    return protocol


def analyze(records: Iterable[PacketRecord], header: dict) -> TraceSummary:
    summary = TraceSummary(
        capture_format=str(header.get("capture_format", "classic-pcap")),
        byte_order=str(header.get("byte_order", "")),
        timestamp_resolution=str(header.get("timestamp_resolution", "")),
        snaplen=int(header.get("snaplen", 0)),
        linktype=int(header.get("linktype", 0)),
    )

    address_counter: Counter = Counter()
    parsed: list[tuple[float, int, bytes, bytes, bytes]] = []

    for record in records:
        data = record.data
        if not data:
            summary.malformed_packets += 1
            continue
        version = data[0] >> 4
        if version == 6:
            summary.ipv6_packets += 1
            continue
        if version != 4 or len(data) < 20:
            summary.malformed_packets += 1
            continue
        header_len = (data[0] & 0x0F) * 4
        if header_len < 20 or header_len > len(data):
            summary.malformed_packets += 1
            continue
        protocol = data[9]
        src = data[12:16]
        dst = data[16:20]
        address_counter[src] += 1
        address_counter[dst] += 1
        parsed.append((record.ts_seconds, protocol, src, dst, data[header_len:]))
        summary.ipv4_packets += 1

    if not parsed:
        raise PcapParseError("no_parseable_ipv4_packets")

    client_address = address_counter.most_common(1)[0][0]
    aliases: dict[bytes, str] = {}

    def alias_for(address: bytes) -> str:
        if address not in aliases:
            aliases[address] = "R%d" % (len(aliases) + 1)
        return aliases[address]

    for ts, protocol, src, dst, payload in parsed:
        outbound = src == client_address
        remote = dst if outbound else src
        if protocol == IPPROTO_UDP and len(payload) >= 8:
            src_port, dst_port = struct.unpack("!HH", payload[:4])
            name = "UDP"
        elif protocol == IPPROTO_TCP and len(payload) >= 20:
            src_port, dst_port = struct.unpack("!HH", payload[:4])
            name = "TCP"
        elif protocol == IPPROTO_ICMP:
            summary.protocol_counts["ICMP"] += 1
            continue
        else:
            summary.protocol_counts["IP_OTHER_%d" % protocol] += 1
            continue

        local_port, remote_port = (src_port, dst_port) if outbound else (dst_port, src_port)
        key = FlowKey(
            protocol=name,
            remote_alias=alias_for(remote),
            local_port=int(local_port),
            remote_port=int(remote_port),
            direction="CLIENT_TO_REMOTE" if outbound else "REMOTE_TO_CLIENT",
        )
        stat = summary.flows.get(key)
        if stat is None:
            stat = FlowStat(first_ts=ts, last_ts=ts)
            summary.flows[key] = stat
        stat.packets += 1
        stat.payload_bytes += len(payload)
        stat.last_ts = ts
        stat.transport_category = _classify(name, int(remote_port), int(local_port))

        if name == "TCP":
            flags = payload[13]
            stat.tcp_syn += 1 if flags & 0x02 else 0
            stat.tcp_ack += 1 if flags & 0x10 else 0
            stat.tcp_fin += 1 if flags & 0x01 else 0
            stat.tcp_rst += 1 if flags & 0x04 else 0
            stat.tcp_psh += 1 if flags & 0x08 else 0

        summary.protocol_counts[name] += 1
        summary.transport_categories[stat.transport_category] += 1
        if outbound:
            summary.outbound_packets += 1
        else:
            summary.inbound_packets += 1
        summary.first_ts = ts if summary.packet_count == 0 else min(summary.first_ts, ts)
        summary.last_ts = max(summary.last_ts, ts)
        summary.packet_count += 1

    if summary.packet_count == 0:
        raise PcapParseError("no_transport_packets")
    summary.peer_count = len(aliases)
    return summary


def to_safe_dict(summary: TraceSummary) -> dict:
    flows = []
    for key, stat in sorted(summary.flows.items(), key=lambda item: -item[1].packets)[:40]:
        flows.append(
            {
                "protocol": key.protocol,
                "direction": key.direction,
                "remote_alias": key.remote_alias,
                "local_port": key.local_port,
                "remote_port": key.remote_port,
                "transport_category": stat.transport_category,
                "packets": stat.packets,
                "payload_bytes": stat.payload_bytes,
                "span_seconds": round(stat.last_ts - stat.first_ts, 2),
                "tcp_flags": {
                    "syn": stat.tcp_syn,
                    "ack": stat.tcp_ack,
                    "fin": stat.tcp_fin,
                    "rst": stat.tcp_rst,
                    "psh": stat.tcp_psh,
                }
                if key.protocol == "TCP"
                else {},
            }
        )
    return {
        "capture_format": summary.capture_format,
        "byte_order": summary.byte_order,
        "timestamp_resolution": summary.timestamp_resolution,
        "snaplen": summary.snaplen,
        "linktype": summary.linktype,
        "packet_count": summary.packet_count,
        "ipv4_packets": summary.ipv4_packets,
        "ipv6_packets": summary.ipv6_packets,
        "malformed_packets": summary.malformed_packets,
        "protocol_counts": dict(sorted(summary.protocol_counts.items())),
        "transport_categories": dict(sorted(summary.transport_categories.items())),
        "outbound_packets": summary.outbound_packets,
        "inbound_packets": summary.inbound_packets,
        "peer_count": summary.peer_count,
        "duration_seconds": summary.duration_seconds,
        "flow_count": len(summary.flows),
        "flows": flows,
    }


def assert_safe_summary(payload: dict) -> None:
    """Fail closed if a rendered summary would leak addresses or payload bytes."""
    blob = json.dumps(payload, sort_keys=True)
    if _IPV4_RE.search(blob):
        raise PcapParseError("address_leak_in_summary")
    if _HEXDUMP_RE.search(blob):
        raise PcapParseError("hexdump_leak_in_summary")
    if _HEXWORD_RE.search(blob):
        raise PcapParseError("raw_word_leak_in_summary")
    lowered = blob.lower()
    for token in ("token", "bearer", "authorization", "password", "secret", "sdp=", "v="):
        if token in lowered:
            raise PcapParseError("credential_like_token_in_summary")


def summarise_capture(path: str) -> dict:
    with open(path, "rb") as handle:
        blob = handle.read()
    header, records = iter_records(blob)
    summary = analyze(records, header)
    payload = to_safe_dict(summary)
    assert_safe_summary(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline safe-scalar summary of a raw-IP pcap capture.")
    parser.add_argument("capture", help="path to a classic pcap file (LINKTYPE=101)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        payload = summarise_capture(args.capture)
    except (OSError, PcapParseError) as exc:
        print("R39_TRACE_MODEL_RESULT=FAILED_SAFE reason=%s" % exc)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("R39_TRACE_MODEL_RESULT=OK")
        for key in (
            "capture_format",
            "linktype",
            "packet_count",
            "ipv4_packets",
            "ipv6_packets",
            "malformed_packets",
            "outbound_packets",
            "inbound_packets",
            "peer_count",
            "duration_seconds",
            "flow_count",
        ):
            print("%s=%s" % (key.upper(), payload[key]))
        print("PROTOCOL_COUNTS=%s" % json.dumps(payload["protocol_counts"], sort_keys=True))
        print("TRANSPORT_CATEGORIES=%s" % json.dumps(payload["transport_categories"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
