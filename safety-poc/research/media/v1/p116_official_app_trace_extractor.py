#!/usr/bin/env python3
"""P116 R13D official-app trace scalar extractor.

Input is a sanitized TSV field export, normally produced by tshark from a raw
PCAP on the capture host. The extractor never reads or prints packet payloads.
It emits only counts, timings, lengths, structural RTP/RTCP/H264 classes, and
comparison templates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable


FIELD_NAMES = (
    "frame.time_epoch",
    "frame.len",
    "ip.src",
    "ip.dst",
    "ipv6.src",
    "ipv6.dst",
    "udp.srcport",
    "udp.dstport",
    "tcp.srcport",
    "tcp.dstport",
    "_ws.col.Protocol",
    "rtp.p_type",
    "rtp.ssrc",
    "rtp.timestamp",
    "rtcp.pt",
    "h264.nal_unit_type",
    "tcp.len",
    "udp.length",
)

REQUIRED_MESSAGE_FIELDS = (
    "RELATIVE_TIME",
    "DIRECTION",
    "TRANSPORT_CLASS",
    "PROTOCOL_FAMILY",
    "SAFE_MESSAGE_TYPE",
    "MESSAGE_LENGTH",
    "REPEAT_COUNT",
    "FIRST_AT",
    "LAST_AT",
    "CADENCE",
)

SUMMARY_KEYS = (
    "SCHEMA",
    "INPUT_SHA256",
    "INPUT_SIZE",
    "TOTAL_RECORDS",
    "CLIENT_TO_DEVICE_RECORDS",
    "DEVICE_TO_CLIENT_RECORDS",
    "POST36_CLIENT_TO_DEVICE_RECORDS",
    "POST36_ANY_RECORDS",
    "REPEATING_LT36S_CLASSES",
    "MESSAGE_FAMILY_ROWS",
    "VIDEO_PACKET_COUNT",
    "VIDEO_PT_SET",
    "VIDEO_SSRC_CHANGE_COUNT",
    "VIDEO_FIRST_TS",
    "VIDEO_LAST_TS",
    "SPS_COUNT",
    "PPS_COUNT",
    "IDR_COUNT",
    "IDR_TIMES",
    "RTCP_PRESENT",
    "RTCP_DIRECTION_SET",
    "RTCP_PACKET_TYPES",
    "RTCP_FIRST_AT",
    "RTCP_LAST_AT",
    "RTCP_REPEAT_COUNT",
    "COMPARISON_TEMPLATE_READY",
    "PRIVACY_GATE",
)

COMPARISON_EVENTS = (
    "CTPP",
    "RTPC",
    "PSEUDOTCP_APPLICATION_TRAFFIC",
    "ACK_CONTROL",
    "HEARTBEAT_PING",
    "SESSION_RENEWAL",
    "RECEIVER_FEEDBACK",
    "RTCP_FEEDBACK",
    "KEYFRAME_IDR_REQUEST",
    "STUN_TURN_KEEPALIVE",
    "REPEATING_EVENT_LT36S",
    "CLIENT_TO_DEVICE_AFTER_36S",
)


@dataclass(frozen=True)
class Row:
    relative_time: float
    direction: str
    transport_class: str
    protocol_family: str
    safe_message_type: str
    message_length: int
    rtp_pt: str
    rtp_ssrc: str
    rtp_timestamp: str
    rtcp_pt: str
    h264_nal_types: tuple[str, ...]


def _csv_set(values: Iterable[str]) -> str:
    clean = sorted({value for value in values if value not in {"", "UNKNOWN"}})
    return ",".join(clean) if clean else "NONE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_value(value: str) -> str:
    for part in value.replace(",", ";").split(";"):
        part = part.strip()
        if part:
            return part
    return ""


def _all_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.replace(",", ";").split(";") if part.strip())


def _safe_int(value: str, default: int = 0) -> int:
    value = _first_value(value)
    try:
        return int(value)
    except ValueError:
        return default


def _safe_float(value: str, default: float = 0.0) -> float:
    value = _first_value(value)
    try:
        return float(value)
    except ValueError:
        return default


def _direction(src: str, dst: str, client_ip: str, device_ip: str) -> str:
    if client_ip and device_ip:
        if src == client_ip and dst == device_ip:
            return "CLIENT_TO_DEVICE"
        if src == device_ip and dst == client_ip:
            return "DEVICE_TO_CLIENT"
    return "UNKNOWN_DIRECTION"


def _protocol_family(protocol: str, udp_src: str, udp_dst: str, tcp_src: str, tcp_dst: str) -> str:
    upper = protocol.upper()
    ports = {udp_src, udp_dst, tcp_src, tcp_dst}
    if "RTCP" in upper:
        return "RTCP"
    if "RTP" in upper:
        return "RTP"
    if "STUN" in upper or "TURN" in upper:
        return "STUN_TURN"
    if "TLS" in upper or "SSL" in upper:
        return "TLS_RECORD_METADATA"
    if "TCP" in upper and "RTPC" in upper:
        return "RTPC"
    if "CTPP" in upper:
        return "CTPP"
    if "PSEUDOTCP" in upper or "PSEUDO" in upper:
        return "PSEUDOTCP"
    if "TCP" in upper:
        return "TCP_METADATA"
    if "UDP" in upper:
        if "3478" in ports or "5349" in ports:
            return "STUN_TURN"
        return "UDP_METADATA"
    return upper or "UNKNOWN"


def _safe_message_type(family: str, row: dict[str, str]) -> str:
    if family == "RTP":
        pt = _first_value(row.get("rtp.p_type", ""))
        return f"RTP_PT_{pt}" if pt else "RTP"
    if family == "RTCP":
        pt = _first_value(row.get("rtcp.pt", ""))
        return f"RTCP_PT_{pt}" if pt else "RTCP"
    if family in {"TLS_RECORD_METADATA", "TCP_METADATA", "UDP_METADATA"}:
        return family
    if family == "STUN_TURN":
        return "STUN_TURN_METADATA"
    return family


def read_rows(path: Path, *, client_ip: str, device_ip: str, media_active_epoch: float) -> list[Row]:
    rows: list[Row] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, fieldnames=FIELD_NAMES, delimiter="\t")
        for raw in reader:
            epoch = _safe_float(raw.get("frame.time_epoch", ""))
            src = _first_value(raw.get("ip.src", "")) or _first_value(raw.get("ipv6.src", ""))
            dst = _first_value(raw.get("ip.dst", "")) or _first_value(raw.get("ipv6.dst", ""))
            udp_src = _first_value(raw.get("udp.srcport", ""))
            udp_dst = _first_value(raw.get("udp.dstport", ""))
            tcp_src = _first_value(raw.get("tcp.srcport", ""))
            tcp_dst = _first_value(raw.get("tcp.dstport", ""))
            protocol = raw.get("_ws.col.Protocol", "")
            family = _protocol_family(protocol, udp_src, udp_dst, tcp_src, tcp_dst)
            transport = "UDP" if udp_src or udp_dst else "TCP" if tcp_src or tcp_dst else "OTHER"
            length = _safe_int(raw.get("frame.len", "")) or _safe_int(raw.get("udp.length", "")) or _safe_int(raw.get("tcp.len", ""))
            rows.append(
                Row(
                    relative_time=round(epoch - media_active_epoch, 6),
                    direction=_direction(src, dst, client_ip, device_ip),
                    transport_class=transport,
                    protocol_family=family,
                    safe_message_type=_safe_message_type(family, raw),
                    message_length=length,
                    rtp_pt=_first_value(raw.get("rtp.p_type", "")),
                    rtp_ssrc=_first_value(raw.get("rtp.ssrc", "")),
                    rtp_timestamp=_first_value(raw.get("rtp.timestamp", "")),
                    rtcp_pt=_first_value(raw.get("rtcp.pt", "")),
                    h264_nal_types=_all_values(raw.get("h264.nal_unit_type", "")),
                )
            )
    return rows


def family_rows(rows: list[Row], *, max_rows: int) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row.relative_time < 0:
            continue
        key = (
            row.direction,
            row.transport_class,
            row.protocol_family,
            row.safe_message_type,
            row.message_length,
        )
        buckets[key].append(row.relative_time)

    result: list[dict[str, object]] = []
    for key, times in sorted(buckets.items(), key=lambda item: (item[0], item[1][0]))[:max_rows]:
        intervals = [b - a for a, b in zip(times, times[1:])]
        cadence = round(median(intervals), 6) if intervals else "NONE"
        direction, transport, family, message_type, length = key
        result.append(
            {
                "RELATIVE_TIME": round(times[0], 6),
                "DIRECTION": direction,
                "TRANSPORT_CLASS": transport,
                "PROTOCOL_FAMILY": family,
                "SAFE_MESSAGE_TYPE": message_type,
                "MESSAGE_LENGTH": length,
                "REPEAT_COUNT": len(times),
                "FIRST_AT": round(times[0], 6),
                "LAST_AT": round(times[-1], 6),
                "CADENCE": cadence,
            }
        )
    return result


def summarize(rows: list[Row], *, input_path: Path, max_message_rows: int) -> dict[str, object]:
    message_rows = family_rows(rows, max_rows=max_message_rows)
    video_rows = [row for row in rows if row.protocol_family == "RTP" and row.rtp_pt]
    rtcp_rows = [row for row in rows if row.protocol_family == "RTCP"]
    rtcp_times = [row.relative_time for row in rtcp_rows]
    rtcp_dirs = [row.direction for row in rtcp_rows]
    rtcp_pts = [row.rtcp_pt for row in rtcp_rows]
    video_timestamps = [int(row.rtp_timestamp) for row in video_rows if row.rtp_timestamp.isdigit()]
    video_ssrcs = [row.rtp_ssrc for row in video_rows if row.rtp_ssrc]
    ssrc_change_count = sum(1 for a, b in zip(video_ssrcs, video_ssrcs[1:]) if a != b)
    nal_times: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for nal in row.h264_nal_types:
            nal_times[nal].append(row.relative_time)
    repeating = [
        item["SAFE_MESSAGE_TYPE"]
        for item in message_rows
        if isinstance(item["CADENCE"], float) and item["CADENCE"] < 36.0 and item["REPEAT_COUNT"] > 1
    ]
    comparison_template = [
        {
            "EVENT": event,
            "OFFICIAL_APP_SENDS": "UNRESOLVED",
            "OUR_HELPER_SENDS": "UNRESOLVED",
            "CADENCE": "UNRESOLVED",
            "CONTINUES_AFTER_36S": "UNRESOLVED",
            "MEDIA_LIFETIME_CANDIDATE": "NOT_PROVEN",
            "IDR_FEEDBACK_CANDIDATE": "NOT_PROVEN",
        }
        for event in COMPARISON_EVENTS
    ]
    verdict_template = {
        "MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D1": "UNRESOLVED",
        "MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D2": "UNRESOLVED",
        "COMMON_D1_D2_CAUSE": "UNRESOLVED",
    }
    return {
        "SCHEMA": "P116_R13D_OFFICIAL_APP_TRACE_SCALARS_V1",
        "INPUT_SHA256": _sha256(input_path),
        "INPUT_SIZE": input_path.stat().st_size,
        "TOTAL_RECORDS": len(rows),
        "CLIENT_TO_DEVICE_RECORDS": sum(row.direction == "CLIENT_TO_DEVICE" for row in rows),
        "DEVICE_TO_CLIENT_RECORDS": sum(row.direction == "DEVICE_TO_CLIENT" for row in rows),
        "POST36_CLIENT_TO_DEVICE_RECORDS": sum(row.direction == "CLIENT_TO_DEVICE" and row.relative_time > 36.0 for row in rows),
        "POST36_ANY_RECORDS": sum(row.relative_time > 36.0 for row in rows),
        "REPEATING_LT36S_CLASSES": _csv_set(repeating),
        "MESSAGE_FAMILY_ROWS": message_rows,
        "VIDEO_PACKET_COUNT": len(video_rows),
        "VIDEO_PT_SET": _csv_set(row.rtp_pt for row in video_rows),
        "VIDEO_SSRC_CHANGE_COUNT": ssrc_change_count,
        "VIDEO_FIRST_TS": video_timestamps[0] if video_timestamps else "NONE",
        "VIDEO_LAST_TS": video_timestamps[-1] if video_timestamps else "NONE",
        "SPS_COUNT": len(nal_times.get("7", [])),
        "PPS_COUNT": len(nal_times.get("8", [])),
        "IDR_COUNT": len(nal_times.get("5", [])),
        "IDR_TIMES": [round(value, 6) for value in nal_times.get("5", [])],
        "RTCP_PRESENT": bool(rtcp_rows),
        "RTCP_DIRECTION_SET": _csv_set(rtcp_dirs),
        "RTCP_PACKET_TYPES": _csv_set(rtcp_pts),
        "RTCP_FIRST_AT": round(rtcp_times[0], 6) if rtcp_times else "NONE",
        "RTCP_LAST_AT": round(rtcp_times[-1], 6) if rtcp_times else "NONE",
        "RTCP_REPEAT_COUNT": len(rtcp_rows),
        "COMPARISON_TEMPLATE": comparison_template,
        "CLOSING_VERDICT_TEMPLATE": verdict_template,
        "COMPARISON_TEMPLATE_READY": True,
        "PRIVACY_GATE": "SCALAR_ONLY_NO_PAYLOAD_NO_IDENTIFIERS",
    }


def _validate_summary(summary: dict[str, object]) -> None:
    missing = [key for key in SUMMARY_KEYS if key not in summary]
    if missing:
        raise SystemExit(f"missing summary keys: {','.join(missing)}")
    for row in summary["MESSAGE_FAMILY_ROWS"]:
        missing_row = [key for key in REQUIRED_MESSAGE_FIELDS if key not in row]
        if missing_row:
            raise SystemExit(f"missing message row keys: {','.join(missing_row)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract scalar-only P116 R13D official-app trace metadata.")
    parser.add_argument("--input-tsv", required=True, type=Path)
    parser.add_argument("--client-ip", default="")
    parser.add_argument("--device-ip", default="")
    parser.add_argument("--media-active-epoch", required=True, type=float)
    parser.add_argument("--max-message-rows", type=int, default=200)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    rows = read_rows(
        args.input_tsv,
        client_ip=args.client_ip,
        device_ip=args.device_ip,
        media_active_epoch=args.media_active_epoch,
    )
    summary = summarize(rows, input_path=args.input_tsv, max_message_rows=args.max_message_rows)
    _validate_summary(summary)
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.write_text(text + "\n", encoding="utf-8")
        args.output_json.chmod(0o600)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
