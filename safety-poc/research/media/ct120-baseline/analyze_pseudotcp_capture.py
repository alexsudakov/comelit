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

PSEUDOTCP_HEADER = 24
FLAG_FIN = 1
FLAG_CTL = 2
FLAG_RST = 4
CTL_CONNECT = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Offline, dependency-free classifier for PseudoTCP packets in a pcap. "
            "It prints transport shape only; it never performs network I/O."
        )
    )
    p.add_argument("pcap", type=Path)
    p.add_argument(
        "--local-ip",
        default=None,
        help="Optional capture-side local IPv4 address for LOCAL/REMOTE labels.",
    )
    p.add_argument("--limit", type=int, default=40)
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
        ethertype = struct.unpack("!H", frame[12:14])[0]
        if ethertype != 0x0800:
            return None
        return frame[14:]
    return None


def udp_payload(ip: bytes) -> tuple[str, int, str, int, bytes] | None:
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + 8:
        return None
    if ip[9] != 17:
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


def classify(payload: bytes) -> dict[str, object] | None:
    if len(payload) < PSEUDOTCP_HEADER:
        return None
    conv = struct.unpack("!I", payload[0:4])[0]
    if conv != 0:
        return None

    flags = payload[13]
    data = payload[PSEUDOTCP_HEADER:]
    # The project capture contract uses conversation 0. Restrict output to
    # packets whose flags fit the libnice PseudoTCP FIN/CTL/RST bit surface.
    if flags & ~(FLAG_FIN | FLAG_CTL | FLAG_RST):
        return None

    control = "NONE"
    if flags & FLAG_RST:
        control = "RST"
    elif flags & FLAG_CTL:
        if data and data[0] == CTL_CONNECT:
            control = "CONNECT"
        elif data:
            control = f"CTL_{data[0]}"
        else:
            control = "CTL_EMPTY"
    elif flags & FLAG_FIN:
        control = "FIN"
    elif not data:
        control = "ACK_ONLY"
    else:
        control = "DATA"

    return {
        "flags": flags,
        "data_len": len(data),
        "control": control,
        "seq_zero": struct.unpack("!I", payload[4:8])[0] == 0,
        "ack_zero": struct.unpack("!I", payload[8:12])[0] == 0,
    }


def direction(src: str, dst: str, local_ip: str | None) -> str:
    if local_ip:
        if src == local_ip:
            return "LOCAL->REMOTE"
        if dst == local_ip:
            return "REMOTE->LOCAL"
    return "EP1->EP2" if src < dst else "EP2->EP1"


def main() -> int:
    args = parse_args()
    raw = args.pcap.read_bytes()
    if len(raw) < 24:
        raise SystemExit("PCAP_HEADER=SHORT")

    endian, fraction_scale = pcap_format(raw[:24])
    _, _, _, _, _, _, linktype = struct.unpack(endian + "IHHIIII", raw[:24])
    if linktype not in (DLT_RAW, DLT_EN10MB):
        raise SystemExit(f"LINKTYPE=UNSUPPORTED:{linktype}")

    local_ip = args.local_ip
    if local_ip:
        ipaddress.IPv4Address(local_ip)

    pos = 24
    first_ts: float | None = None
    pseudo_first_ts: float | None = None
    rows: list[dict[str, object]] = []
    counts: dict[tuple[str, str], int] = {}

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
        info = classify(payload)
        if info is None:
            continue

        if pseudo_first_ts is None:
            pseudo_first_ts = ts
        d = direction(src, dst, local_ip)
        control = str(info["control"])
        counts[(d, control)] = counts.get((d, control), 0) + 1

        if len(rows) < max(1, args.limit):
            rows.append(
                {
                    "t": ts - pseudo_first_ts,
                    "direction": d,
                    "wire_len": len(payload),
                    **info,
                }
            )

    print(f"PCAP={args.pcap}")
    print(f"LINKTYPE={linktype}")
    print(f"PSEUDOTCP_PACKETS={sum(counts.values())}")
    print(f"FIRST_ROWS={len(rows)}")

    if not rows:
        print("PSEUDOTCP_CAPTURE_GATE=FAIL")
        return 2

    print("\n=== FIRST PSEUDOTCP PACKETS ===")
    for i, row in enumerate(rows, 1):
        print(
            "PKT_%02d t=%.6f dir=%s wire=%d data=%d flags=%d control=%s "
            "seq_zero=%s ack_zero=%s"
            % (
                i,
                row["t"],
                row["direction"],
                row["wire_len"],
                row["data_len"],
                row["flags"],
                row["control"],
                str(row["seq_zero"]).lower(),
                str(row["ack_zero"]).lower(),
            )
        )

    print("\n=== SUMMARY ===")
    for (d, control), count in sorted(counts.items()):
        print(f"COUNT direction={d} control={control} packets={count}")

    first = rows[0]
    print(f"FIRST_DIRECTION={first['direction']}")
    print(f"FIRST_CONTROL={first['control']}")
    print(f"FIRST_FLAGS={first['flags']}")
    print(f"FIRST_DATA_LEN={first['data_len']}")
    print("PSEUDOTCP_CAPTURE_GATE=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
