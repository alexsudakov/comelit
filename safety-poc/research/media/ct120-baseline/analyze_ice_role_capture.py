#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import struct

PCAP_MAGIC_LE_USEC = b"\xd4\xc3\xb2\xa1"
PCAP_MAGIC_BE_USEC = b"\xa1\xb2\xc3\xd4"
PCAP_MAGIC_LE_NSEC = b"\x4d\x3c\xb2\xa1"
PCAP_MAGIC_BE_NSEC = b"\xa1\xb2\x3c\x4d"

DLT_RAW = 101
DLT_EN10MB = 1

STUN_COOKIE = 0x2112A442
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_SUCCESS = 0x0101
STUN_BINDING_ERROR = 0x0111

ATTR_PRIORITY = 0x0024
ATTR_USE_CANDIDATE = 0x0025
ATTR_ICE_CONTROLLED = 0x8029
ATTR_ICE_CONTROLLING = 0x802A


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Offline classifier for ICE Binding request roles and nomination "
            "in a successful Comelit capture. It never prints USERNAME, "
            "credentials, transaction IDs or ICE tie-breakers."
        )
    )
    p.add_argument("pcap", type=Path)
    p.add_argument("--local-ip", required=True)
    p.add_argument("--peer-ip", default=None)
    p.add_argument("--limit", type=int, default=80)
    return p.parse_args()


def pcap_format(header: bytes) -> tuple[str, float]:
    magic = header[:4]
    if magic == PCAP_MAGIC_LE_USEC:
        return "<", 1_000_000.0
    if magic == PCAP_MAGIC_BE_USEC:
        return ">", 1_000_000.0
    if magic == PCAP_MAGIC_LE_NSEC:
        return "<", 1_000_000_000.0
    if magic == PCAP_MAGIC_BE_NSEC:
        return ">", 1_000_000_000.0
    raise SystemExit("PCAP_FORMAT=UNSUPPORTED")


def ipv4_packet(frame: bytes, linktype: int) -> bytes | None:
    if linktype == DLT_RAW:
        return frame
    if linktype == DLT_EN10MB:
        if len(frame) < 14:
            return None
        if struct.unpack("!H", frame[12:14])[0] != 0x0800:
            return None
        return frame[14:]
    return None


def udp_payload(ip: bytes) -> tuple[str, int, str, int, bytes] | None:
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + 8 or ip[9] != 17:
        return None
    total_len = struct.unpack("!H", ip[2:4])[0]
    if total_len == 0 or total_len > len(ip):
        total_len = len(ip)
    src = str(ipaddress.IPv4Address(ip[12:16]))
    dst = str(ipaddress.IPv4Address(ip[16:20]))
    udp = ip[ihl:total_len]
    if len(udp) < 8:
        return None
    sport, dport, ulen = struct.unpack("!HHH", udp[:6])
    if ulen < 8:
        return None
    end = min(len(udp), ulen)
    return src, sport, dst, dport, udp[8:end]


def parse_stun(payload: bytes) -> dict[str, object] | None:
    if len(payload) < 20:
        return None
    msg_type, msg_len, cookie = struct.unpack("!HHI", payload[:8])
    if cookie != STUN_COOKIE:
        return None
    if msg_type not in (STUN_BINDING_REQUEST, STUN_BINDING_SUCCESS, STUN_BINDING_ERROR):
        return None
    end = 20 + msg_len
    if end > len(payload):
        return None

    attrs: set[int] = set()
    pos = 20
    while pos + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", payload[pos : pos + 4])
        pos += 4
        if pos + attr_len > end:
            return None
        attrs.add(attr_type)
        pos += (attr_len + 3) & ~3

    if msg_type == STUN_BINDING_REQUEST:
        kind = "BINDING_REQUEST"
    elif msg_type == STUN_BINDING_SUCCESS:
        kind = "BINDING_SUCCESS"
    else:
        kind = "BINDING_ERROR"

    role = "NONE"
    if ATTR_ICE_CONTROLLING in attrs and ATTR_ICE_CONTROLLED in attrs:
        role = "BOTH_INVALID"
    elif ATTR_ICE_CONTROLLING in attrs:
        role = "CONTROLLING"
    elif ATTR_ICE_CONTROLLED in attrs:
        role = "CONTROLLED"

    return {
        "kind": kind,
        "role": role,
        "use_candidate": ATTR_USE_CANDIDATE in attrs,
        "priority": ATTR_PRIORITY in attrs,
    }


def main() -> int:
    args = parse_args()
    ipaddress.IPv4Address(args.local_ip)
    if args.peer_ip:
        ipaddress.IPv4Address(args.peer_ip)

    raw = args.pcap.read_bytes()
    if len(raw) < 24:
        raise SystemExit("PCAP_HEADER=SHORT")
    endian, fraction_scale = pcap_format(raw[:24])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", raw[:24])
    if linktype not in (DLT_RAW, DLT_EN10MB):
        raise SystemExit(f"LINKTYPE=UNSUPPORTED:{linktype}")

    pos = 24
    first_ts: float | None = None
    rows: list[dict[str, object]] = []
    local_requests = 0
    remote_requests = 0
    local_controlling = 0
    local_controlled = 0
    local_use_candidate = 0
    remote_controlling = 0
    remote_controlled = 0
    remote_use_candidate = 0

    while pos + 16 <= len(raw):
        ts_sec, ts_frac, incl_len, _orig_len = struct.unpack(
            endian + "IIII", raw[pos : pos + 16]
        )
        pos += 16
        if pos + incl_len > len(raw):
            break
        frame = raw[pos : pos + incl_len]
        pos += incl_len
        ts = ts_sec + ts_frac / fraction_scale
        if first_ts is None:
            first_ts = ts

        ip = ipv4_packet(frame, linktype)
        if ip is None:
            continue
        u = udp_payload(ip)
        if u is None:
            continue
        src, sport, dst, dport, payload = u
        if src != args.local_ip and dst != args.local_ip:
            continue
        if args.peer_ip and src != args.peer_ip and dst != args.peer_ip:
            continue

        info = parse_stun(payload)
        if info is None:
            continue

        direction = "LOCAL->REMOTE" if src == args.local_ip else "REMOTE->LOCAL"
        if info["kind"] == "BINDING_REQUEST":
            if direction == "LOCAL->REMOTE":
                local_requests += 1
                if info["role"] == "CONTROLLING":
                    local_controlling += 1
                if info["role"] == "CONTROLLED":
                    local_controlled += 1
                if info["use_candidate"]:
                    local_use_candidate += 1
            else:
                remote_requests += 1
                if info["role"] == "CONTROLLING":
                    remote_controlling += 1
                if info["role"] == "CONTROLLED":
                    remote_controlled += 1
                if info["use_candidate"]:
                    remote_use_candidate += 1

        if len(rows) < max(1, args.limit):
            rows.append(
                {
                    "t": ts - (first_ts or ts),
                    "direction": direction,
                    "src_port": sport,
                    "dst_port": dport,
                    **info,
                }
            )

    print(f"PCAP={args.pcap}")
    print(f"LINKTYPE={linktype}")
    print(f"LOCAL_IP={args.local_ip}")
    if args.peer_ip:
        print(f"PEER_IP_FILTER={args.peer_ip}")
    print(f"ICE_ROWS={len(rows)}")

    if not rows:
        print("ICE_ROLE_CAPTURE_GATE=FAIL")
        return 2

    print("\n=== ICE BINDING SHAPE ===")
    for i, row in enumerate(rows, 1):
        print(
            "ICE_%02d t=%.6f dir=%s kind=%s role=%s use_candidate=%s "
            "priority=%s src_port=%d dst_port=%d"
            % (
                i,
                row["t"],
                row["direction"],
                row["kind"],
                row["role"],
                str(row["use_candidate"]).lower(),
                str(row["priority"]).lower(),
                row["src_port"],
                row["dst_port"],
            )
        )

    print("\n=== SUMMARY ===")
    print(f"LOCAL_BINDING_REQUESTS={local_requests}")
    print(f"LOCAL_ICE_CONTROLLING_REQUESTS={local_controlling}")
    print(f"LOCAL_ICE_CONTROLLED_REQUESTS={local_controlled}")
    print(f"LOCAL_USE_CANDIDATE_REQUESTS={local_use_candidate}")
    print(f"REMOTE_BINDING_REQUESTS={remote_requests}")
    print(f"REMOTE_ICE_CONTROLLING_REQUESTS={remote_controlling}")
    print(f"REMOTE_ICE_CONTROLLED_REQUESTS={remote_controlled}")
    print(f"REMOTE_USE_CANDIDATE_REQUESTS={remote_use_candidate}")

    if local_controlling and not local_controlled:
        local_role = "CONTROLLING"
    elif local_controlled and not local_controlling:
        local_role = "CONTROLLED"
    elif not local_controlling and not local_controlled:
        local_role = "UNOBSERVED"
    else:
        local_role = "MIXED"
    print(f"CAPTURE_LOCAL_ICE_ROLE={local_role}")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    print("ICE_ROLE_CAPTURE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
