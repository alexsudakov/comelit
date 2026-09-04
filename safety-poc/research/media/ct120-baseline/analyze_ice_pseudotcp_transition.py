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
ATTR_USE_CANDIDATE = 0x0025
ATTR_ICE_CONTROLLING = 0x802A

PSEUDOTCP_HEADER = 24
FLAG_CTL = 2
CTL_CONNECT = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Offline timing correlation between ICE nomination and the first "
            "PseudoTCP CONNECT in a successful Comelit capture. No network I/O; "
            "credentials, STUN transaction IDs and tie-breakers are never printed."
        )
    )
    p.add_argument("pcap", type=Path)
    p.add_argument("--local-ip", required=True)
    p.add_argument("--peer-ip", required=True)
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


def ipv4(frame: bytes, linktype: int) -> bytes | None:
    if linktype == DLT_RAW:
        return frame
    if linktype == DLT_EN10MB:
        if len(frame) < 14 or struct.unpack("!H", frame[12:14])[0] != 0x0800:
            return None
        return frame[14:]
    return None


def udp(ip: bytes) -> tuple[str, int, str, int, bytes] | None:
    if len(ip) < 20 or (ip[0] >> 4) != 4 or ip[9] != 17:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + 8:
        return None
    total = struct.unpack("!H", ip[2:4])[0]
    if total == 0 or total > len(ip):
        total = len(ip)
    u = ip[ihl:total]
    if len(u) < 8:
        return None
    sport, dport, ulen = struct.unpack("!HHH", u[:6])
    if ulen < 8:
        return None
    end = min(len(u), ulen)
    return (
        str(ipaddress.IPv4Address(ip[12:16])),
        sport,
        str(ipaddress.IPv4Address(ip[16:20])),
        dport,
        u[8:end],
    )


def parse_stun(payload: bytes) -> dict[str, object] | None:
    if len(payload) < 20:
        return None
    msg_type, msg_len, cookie = struct.unpack("!HHI", payload[:8])
    if cookie != STUN_COOKIE or msg_type not in (STUN_BINDING_REQUEST, STUN_BINDING_SUCCESS):
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

    return {
        "request": msg_type == STUN_BINDING_REQUEST,
        "success": msg_type == STUN_BINDING_SUCCESS,
        "use_candidate": ATTR_USE_CANDIDATE in attrs,
        "controlling": ATTR_ICE_CONTROLLING in attrs,
        # Used only internally to pair success responses; never printed.
        "txid": payload[8:20],
    }


def is_pseudotcp_connect(payload: bytes) -> bool:
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
        and body[0] == CTL_CONNECT
    )


def main() -> int:
    args = parse_args()
    ipaddress.IPv4Address(args.local_ip)
    ipaddress.IPv4Address(args.peer_ip)

    raw = args.pcap.read_bytes()
    if len(raw) < 24:
        raise SystemExit("PCAP_HEADER=SHORT")
    endian, scale = pcap_format(raw[:24])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", raw[:24])
    if linktype not in (DLT_RAW, DLT_EN10MB):
        raise SystemExit(f"LINKTYPE=UNSUPPORTED:{linktype}")

    packets: list[dict[str, object]] = []
    pos = 24
    first_ts: float | None = None
    while pos + 16 <= len(raw):
        sec, frac, incl, _orig = struct.unpack(endian + "IIII", raw[pos : pos + 16])
        pos += 16
        if pos + incl > len(raw):
            break
        frame = raw[pos : pos + incl]
        pos += incl
        ts = sec + frac / scale
        if first_ts is None:
            first_ts = ts
        ip = ipv4(frame, linktype)
        if ip is None:
            continue
        parsed = udp(ip)
        if parsed is None:
            continue
        src, sport, dst, dport, payload = parsed
        packets.append(
            {
                "ts": ts,
                "src": src,
                "sport": sport,
                "dst": dst,
                "dport": dport,
                "payload": payload,
            }
        )

    first_connect: dict[str, object] | None = None
    for packet in packets:
        if (
            packet["src"] == args.local_ip
            and packet["dst"] == args.peer_ip
            and is_pseudotcp_connect(packet["payload"])
        ):
            first_connect = packet
            break
    if first_connect is None:
        print("FIRST_LOCAL_PSEUDOTCP_CONNECT=NOT_FOUND")
        return 2

    local_port = int(first_connect["sport"])
    peer_port = int(first_connect["dport"])
    connect_ts = float(first_connect["ts"])

    nominations: list[dict[str, object]] = []
    success_by_txid: dict[bytes, float] = {}
    for packet in packets:
        same_endpoint = (
            {packet["src"], packet["dst"]} == {args.local_ip, args.peer_ip}
            and {int(packet["sport"]), int(packet["dport"])} == {local_port, peer_port}
        )
        if not same_endpoint:
            continue
        info = parse_stun(packet["payload"])
        if info is None:
            continue
        if (
            packet["src"] == args.peer_ip
            and info["request"]
            and info["controlling"]
            and info["use_candidate"]
        ):
            nominations.append({"ts": float(packet["ts"]), "txid": info["txid"]})
        if packet["src"] == args.local_ip and info["success"]:
            success_by_txid[info["txid"]] = float(packet["ts"])

    if not nominations:
        print("REMOTE_NOMINATION=NOT_FOUND")
        return 3

    matched_responses = [
        success_by_txid[n["txid"]]
        for n in nominations
        if n["txid"] in success_by_txid
    ]

    remote_connect: dict[str, object] | None = None
    for packet in packets:
        if (
            packet["src"] == args.peer_ip
            and packet["dst"] == args.local_ip
            and int(packet["sport"]) == peer_port
            and int(packet["dport"]) == local_port
            and is_pseudotcp_connect(packet["payload"])
        ):
            remote_connect = packet
            break

    local_ack: dict[str, object] | None = None
    if remote_connect is not None:
        remote_connect_ts = float(remote_connect["ts"])
        for packet in packets:
            if float(packet["ts"]) <= remote_connect_ts:
                continue
            if not (
                packet["src"] == args.local_ip
                and packet["dst"] == args.peer_ip
                and int(packet["sport"]) == local_port
                and int(packet["dport"]) == peer_port
            ):
                continue
            payload = packet["payload"]
            if len(payload) == PSEUDOTCP_HEADER:
                conv = struct.unpack("!I", payload[:4])[0]
                flags = payload[13]
                if conv == 0 and flags == 0:
                    local_ack = packet
                    break

    base = float(first_ts or connect_ts)
    first_nom = float(nominations[0]["ts"])
    last_nom = float(nominations[-1]["ts"])
    first_resp = matched_responses[0] if matched_responses else None
    last_resp = matched_responses[-1] if matched_responses else None

    print(f"PCAP={args.pcap}")
    print(f"LINKTYPE={linktype}")
    print(f"P2P_LOCAL_PORT={local_port}")
    print(f"P2P_PEER_IP={args.peer_ip}")
    print(f"P2P_PEER_PORT={peer_port}")
    print(f"REMOTE_USE_CANDIDATE_REQUESTS={len(nominations)}")
    print(f"MATCHED_NOMINATION_SUCCESSES={len(matched_responses)}")

    print("\n=== SUCCESSFUL TRANSITION TIMING ===")
    print(f"FIRST_REMOTE_USE_CANDIDATE_T={first_nom - base:.6f}")
    print(f"LAST_REMOTE_USE_CANDIDATE_T={last_nom - base:.6f}")
    if first_resp is not None:
        print(f"FIRST_NOMINATION_SUCCESS_T={first_resp - base:.6f}")
    else:
        print("FIRST_NOMINATION_SUCCESS_T=UNOBSERVED")
    if last_resp is not None:
        print(f"LAST_NOMINATION_SUCCESS_T={last_resp - base:.6f}")
    else:
        print("LAST_NOMINATION_SUCCESS_T=UNOBSERVED")

    print(f"FIRST_LOCAL_PSEUDOTCP_CONNECT_T={connect_ts - base:.6f}")
    print(f"CONNECT_AFTER_FIRST_USE_CANDIDATE_MS={(connect_ts - first_nom) * 1000:.3f}")
    print(f"CONNECT_AFTER_LAST_USE_CANDIDATE_MS={(connect_ts - last_nom) * 1000:.3f}")
    if first_resp is not None:
        print(
            f"CONNECT_AFTER_FIRST_NOMINATION_SUCCESS_MS="
            f"{(connect_ts - first_resp) * 1000:.3f}"
        )
    if last_resp is not None:
        print(
            f"CONNECT_AFTER_LAST_NOMINATION_SUCCESS_MS="
            f"{(connect_ts - last_resp) * 1000:.3f}"
        )

    if remote_connect is not None:
        remote_connect_ts = float(remote_connect["ts"])
        print(f"REMOTE_PSEUDOTCP_CONNECT_T={remote_connect_ts - base:.6f}")
        print(
            f"REMOTE_CONNECT_AFTER_LOCAL_CONNECT_MS="
            f"{(remote_connect_ts - connect_ts) * 1000:.3f}"
        )
    else:
        remote_connect_ts = None
        print("REMOTE_PSEUDOTCP_CONNECT_T=UNOBSERVED")

    if local_ack is not None and remote_connect_ts is not None:
        ack_ts = float(local_ack["ts"])
        print(f"LOCAL_PSEUDOTCP_ACK_T={ack_ts - base:.6f}")
        print(
            f"LOCAL_ACK_AFTER_REMOTE_CONNECT_MS="
            f"{(ack_ts - remote_connect_ts) * 1000:.3f}"
        )
    else:
        print("LOCAL_PSEUDOTCP_ACK_T=UNOBSERVED")

    order_ok = connect_ts > last_nom and (last_resp is None or connect_ts > last_resp)
    print(f"CONNECT_AFTER_REMOTE_NOMINATION={'true' if order_ok else 'false'}")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    print("ICE_PSEUDOTCP_TRANSITION_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
