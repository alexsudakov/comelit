#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import struct

PSEUDOTCP_HEADER = 24
FLAG_CTL = 2
CTL_CONNECT = 0

CAND_RE = re.compile(
    r"^a=candidate:(\S+)\s+"
    r"(\d+)\s+"
    r"(UDP|TCP)\s+"
    r"(\d+)\s+"
    r"(\S+)\s+"
    r"(\d+)\s+"
    r"typ\s+"
    r"(\S+)"
    r"(?:\s+(.*))?$",
    re.IGNORECASE,
)


def pcap_endian(data: bytes) -> str:
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        return "<"
    if magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        return ">"
    raise SystemExit("PCAP_FORMAT=UNSUPPORTED")


def udp_ipv4(pkt: bytes):
    if len(pkt) < 28 or (pkt[0] >> 4) != 4:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    if ihl < 20 or len(pkt) < ihl + 8 or pkt[9] != 17:
        return None
    total = struct.unpack("!H", pkt[2:4])[0]
    if total == 0 or total > len(pkt):
        total = len(pkt)
    udp = pkt[ihl:total]
    if len(udp) < 8:
        return None
    sport, dport, ulen = struct.unpack("!HHH", udp[:6])
    if ulen < 8:
        return None
    end = min(len(udp), ulen)
    return (
        str(ipaddress.IPv4Address(pkt[12:16])),
        sport,
        str(ipaddress.IPv4Address(pkt[16:20])),
        dport,
        udp[8:end],
    )


def is_initial_connect(payload: bytes) -> bool:
    if len(payload) < PSEUDOTCP_HEADER + 1:
        return False
    conv, seq, ack = struct.unpack("!III", payload[:12])
    flags = payload[13]
    body = payload[PSEUDOTCP_HEADER:]
    return (
        conv == 0
        and seq == 0
        and ack == 0
        and flags == FLAG_CTL
        and bool(body)
        and body[0] == CTL_CONNECT
    )


def capture_remote_endpoint(pcap: Path, local_ip: str):
    raw = pcap.read_bytes()
    if len(raw) < 24:
        raise SystemExit("PCAP_HEADER=SHORT")
    endian = pcap_endian(raw)
    linktype = struct.unpack(endian + "I", raw[20:24])[0]
    if linktype != 101:
        raise SystemExit(f"LINKTYPE=UNSUPPORTED:{linktype}")

    pos = 24
    while pos + 16 <= len(raw):
        _sec, _frac, incl_len, _orig_len = struct.unpack(
            endian + "IIII", raw[pos : pos + 16]
        )
        pos += 16
        if pos + incl_len > len(raw):
            break
        pkt = raw[pos : pos + incl_len]
        pos += incl_len
        parsed = udp_ipv4(pkt)
        if parsed is None:
            continue
        src, sport, dst, dport, payload = parsed
        if src == local_ip and is_initial_connect(payload):
            return dst, dport
    raise SystemExit("CAPTURE_INITIAL_CONNECT=NOT_FOUND")


def parse_candidates(remote_sdp: Path):
    result = []
    for raw in remote_sdp.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith("a=candidate:"):
            continue
        m = CAND_RE.match(line)
        if not m:
            continue
        result.append(
            {
                "foundation": m.group(1),
                "component": int(m.group(2)),
                "transport": m.group(3).upper(),
                "priority": int(m.group(4)),
                "address": m.group(5),
                "port": int(m.group(6)),
                "type": m.group(7).lower(),
            }
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap", type=Path)
    ap.add_argument("remote_sdp", type=Path)
    ap.add_argument("--capture-local-ip", required=True)
    args = ap.parse_args()

    if not args.pcap.is_file():
        raise SystemExit(f"PCAP_MISSING={args.pcap}")
    if not args.remote_sdp.is_file():
        raise SystemExit(f"REMOTE_SDP_MISSING={args.remote_sdp}")

    remote_ip, remote_port = capture_remote_endpoint(
        args.pcap, args.capture_local_ip
    )
    candidates = parse_candidates(args.remote_sdp)

    print("CAPTURE_INITIAL_CONNECT=PASS")
    print(f"CAPTURE_REMOTE_IP={remote_ip}")
    print(f"CAPTURE_REMOTE_PORT={remote_port}")
    print(f"REMOTE_CANDIDATE_COUNT={len(candidates)}")

    for i, cand in enumerate(
        sorted(candidates, key=lambda c: c["priority"], reverse=True), 1
    ):
        ip_match = cand["address"] == remote_ip
        exact_match = ip_match and cand["port"] == remote_port
        print(
            "CAND_%02d type=%s priority=%d address=%s port=%d "
            "capture_ip_match=%s capture_endpoint_match=%s"
            % (
                i,
                cand["type"],
                cand["priority"],
                cand["address"],
                cand["port"],
                str(ip_match).lower(),
                str(exact_match).lower(),
            )
        )

    same_ip = [c for c in candidates if c["address"] == remote_ip]
    exact = [
        c
        for c in candidates
        if c["address"] == remote_ip and c["port"] == remote_port
    ]

    print(
        "CAPTURE_REMOTE_IP_PRESENT_IN_LIVE_REMOTE_SDP="
        + str(bool(same_ip)).lower()
    )
    print(
        "CAPTURE_REMOTE_ENDPOINT_PRESENT_IN_LIVE_REMOTE_SDP="
        + str(bool(exact)).lower()
    )
    if same_ip:
        print(
            "CAPTURE_REMOTE_IP_CANDIDATE_TYPES="
            + ",".join(sorted({str(c["type"]) for c in same_ip}))
        )
    else:
        print("CAPTURE_REMOTE_IP_CANDIDATE_TYPES=NONE")

    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    print("CAPTURE_ENDPOINT_REMOTE_SDP_COMPARE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
