#!/usr/bin/env python3
"""P116 R13E official-app trace scalar extractor.

Input is a sanitized TSV field export, normally produced by tshark from a raw
PCAP on the capture host. The extractor never reads or prints packet payloads.
It emits only trace-local peer aliases, counts, timings, lengths, structural
RTP/RTCP/H264 classes, and comparison templates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
from collections import defaultdict
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
    "VIEW_RELATIVE_TIME",
    "PEER_ALIAS",
    "DIRECTION",
    "TRANSPORT_CLASS",
    "PROTOCOL_FAMILY",
    "SAFE_MESSAGE_TYPE",
    "MESSAGE_LENGTH",
    "REPEAT_COUNT",
    "FIRST_AT",
    "LAST_AT",
    "CADENCE",
    "VIEW_FIRST_AT",
    "VIEW_LAST_AT",
    "VIEW_CADENCE",
)

SUMMARY_KEYS = (
    "SCHEMA",
    "INPUT_SHA256",
    "INPUT_SIZE",
    "TOTAL_RECORDS",
    "REMOTE_PEER_COUNT",
    "CLIENT_TO_REMOTE_RECORDS",
    "REMOTE_TO_CLIENT_RECORDS",
    "UNKNOWN_DIRECTION_RECORDS",
    "POST36_CLIENT_TO_REMOTE_RECORDS",
    "POST36_ANY_RECORDS",
    "MEDIA_ACTIVE_REFERENCE",
    "FIRST_RTP_AFTER_VIEW_EPOCH",
    "VIEW_TO_FIRST_RTP_SECONDS",
    "PRE_WINDOW_GATE",
    "PRE_WINDOW_SECONDS",
    "POST_MEDIA_ACTIVE_CAPTURE_SECONDS",
    "POST_MEDIA_ACTIVE_90S_GATE",
    "POST_MEDIA_ACTIVE_60S_GATE",
    "MESSAGE_FAMILY_BUCKET_COUNT",
    "MESSAGE_FAMILY_ROWS_EMITTED",
    "MESSAGE_FAMILY_ROWS_TRUNCATED",
    "REPEATING_LT36S_CLASSES",
    "MESSAGE_FAMILY_ROWS",
    "PEER_SUMMARY",
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
    "RAW_CLIENT_IP_IN_SANITISED_SUMMARY",
    "RAW_REMOTE_IP_IN_SANITISED_SUMMARY",
    "COMPARISON_TEMPLATE_READY",
    "PRIVACY_GATE",
)

COMPARISON_EVENTS = (
    "CTPP",
    "RTPC",
    "ICE",
    "PSEUDOTCP_APPLICATION_TRAFFIC",
    "ACK_CONTROL",
    "HEARTBEAT_PING",
    "SESSION_RENEWAL",
    "RECEIVER_FEEDBACK",
    "RTCP_FEEDBACK",
    "KEYFRAME_IDR_REQUEST",
    "STUN_TURN_KEEPALIVE",
    "REPEATING_EVENT_LT36S",
    "CLIENT_TO_REMOTE_AFTER_36S",
)

IPV4_RE = re.compile(r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)")
IPV6_CANDIDATE_RE = re.compile(r"(?i)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]{0,}")


@dataclass
class Row:
    epoch: float
    view_relative_time: float
    media_relative_time: float | None
    peer_alias: str
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
    src_endpoint: str = ""
    dst_endpoint: str = ""
    remote_endpoint: str = ""

    @property
    def relative_time(self) -> float | None:
        return self.media_relative_time


def _csv_set(values: Iterable[str]) -> str:
    clean = sorted({value for value in values if value not in {"", "UNKNOWN", "NO_CLIENT_ENDPOINT"}})
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


def _round_or_none(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _direction(src: str, dst: str, client_ip: str) -> str:
    if src == client_ip:
        return "CLIENT_TO_REMOTE"
    if dst == client_ip:
        return "REMOTE_TO_CLIENT"
    return "UNKNOWN_DIRECTION"


def _remote_endpoint(src: str, dst: str, client_ip: str) -> str:
    if src == client_ip and dst:
        return dst
    if dst == client_ip and src:
        return src
    return ""


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
    if "ICE" in upper:
        return "ICE"
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


def read_rows(
    path: Path,
    *,
    client_ip: str,
    device_ip: str = "",
    operator_view_start_epoch: float,
) -> list[Row]:
    del device_ip
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
                    epoch=epoch,
                    view_relative_time=round(epoch - operator_view_start_epoch, 6),
                    media_relative_time=None,
                    peer_alias="NO_CLIENT_ENDPOINT",
                    direction=_direction(src, dst, client_ip),
                    transport_class=transport,
                    protocol_family=family,
                    safe_message_type=_safe_message_type(family, raw),
                    message_length=length,
                    rtp_pt=_first_value(raw.get("rtp.p_type", "")),
                    rtp_ssrc=_first_value(raw.get("rtp.ssrc", "")),
                    rtp_timestamp=_first_value(raw.get("rtp.timestamp", "")),
                    rtcp_pt=_first_value(raw.get("rtcp.pt", "")),
                    h264_nal_types=_all_values(raw.get("h264.nal_unit_type", "")),
                    src_endpoint=src,
                    dst_endpoint=dst,
                    remote_endpoint=_remote_endpoint(src, dst, client_ip),
                )
            )
    assign_peer_aliases(rows)
    return rows


def assign_peer_aliases(rows: list[Row]) -> None:
    aliases: dict[str, str] = {}
    for row in rows:
        remote = row.remote_endpoint
        if not remote:
            row.peer_alias = "NO_CLIENT_ENDPOINT"
            continue
        if remote not in aliases:
            aliases[remote] = f"REMOTE_PEER_{len(aliases) + 1}"
        row.peer_alias = aliases[remote]


def resolve_media_active_reference(
    rows: list[Row],
    *,
    operator_view_start_epoch: float,
) -> tuple[float | None, str]:
    candidates = [
        row.epoch
        for row in rows
        if row.protocol_family == "RTP" and row.epoch >= operator_view_start_epoch
    ]
    if not candidates:
        return None, "UNRESOLVED_NO_RTP"
    return min(candidates), "FIRST_RTP_AFTER_VIEW"


def _apply_media_reference(rows: list[Row], reference_epoch: float | None) -> None:
    for row in rows:
        row.media_relative_time = None if reference_epoch is None else round(row.epoch - reference_epoch, 6)


def _cadence(times: list[float]) -> float | str:
    intervals = [b - a for a, b in zip(times, times[1:])]
    return round(median(intervals), 6) if intervals else "NONE"


def _family_buckets(rows: list[Row]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str, str, str, int], list[Row]] = defaultdict(list)
    for row in rows:
        if row.view_relative_time < 0:
            continue
        key = (
            row.peer_alias,
            row.direction,
            row.transport_class,
            row.protocol_family,
            row.safe_message_type,
            row.message_length,
        )
        buckets[key].append(row)

    result: list[dict[str, object]] = []
    for key, bucket_rows in buckets.items():
        bucket_rows.sort(key=lambda row: row.epoch)
        media_times = [row.media_relative_time for row in bucket_rows if row.media_relative_time is not None]
        view_times = [row.view_relative_time for row in bucket_rows]
        peer_alias, direction, transport, family, message_type, length = key
        result.append(
            {
                "RELATIVE_TIME": _round_or_none(media_times[0]) if media_times else None,
                "VIEW_RELATIVE_TIME": round(view_times[0], 6),
                "PEER_ALIAS": peer_alias,
                "DIRECTION": direction,
                "TRANSPORT_CLASS": transport,
                "PROTOCOL_FAMILY": family,
                "SAFE_MESSAGE_TYPE": message_type,
                "MESSAGE_LENGTH": length,
                "REPEAT_COUNT": len(bucket_rows),
                "FIRST_AT": _round_or_none(media_times[0]) if media_times else None,
                "LAST_AT": _round_or_none(media_times[-1]) if media_times else None,
                "CADENCE": _cadence(media_times) if media_times else None,
                "VIEW_FIRST_AT": round(view_times[0], 6),
                "VIEW_LAST_AT": round(view_times[-1], 6),
                "VIEW_CADENCE": _cadence(view_times),
            }
        )
    return sorted(result, key=lambda item: (item["VIEW_FIRST_AT"], tuple(str(item[key]) for key in sorted(item))))


def family_rows(rows: list[Row], *, max_rows: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    all_rows = _family_buckets(rows)
    return all_rows, all_rows[:max_rows]


def _peer_ordinal(alias: str) -> int:
    try:
        return int(alias.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _peer_summary(rows: list[Row]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    by_alias: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if row.peer_alias.startswith("REMOTE_PEER_"):
            by_alias[row.peer_alias].append(row)
    for alias in sorted(by_alias, key=_peer_ordinal):
        peer_rows = sorted(by_alias[alias], key=lambda row: row.epoch)
        families = {row.protocol_family for row in peer_rows}
        media_times = [row.media_relative_time for row in peer_rows if row.media_relative_time is not None]
        view_times = [row.view_relative_time for row in peer_rows]
        result.append(
            {
                "PEER_ALIAS": alias,
                "FIRST_AT": _round_or_none(media_times[0]) if media_times else None,
                "LAST_AT": _round_or_none(media_times[-1]) if media_times else None,
                "CLIENT_TO_REMOTE_COUNT": sum(row.direction == "CLIENT_TO_REMOTE" for row in peer_rows),
                "REMOTE_TO_CLIENT_COUNT": sum(row.direction == "REMOTE_TO_CLIENT" for row in peer_rows),
                "POST36_CLIENT_TO_REMOTE_COUNT": sum(
                    row.direction == "CLIENT_TO_REMOTE"
                    and row.media_relative_time is not None
                    and row.media_relative_time > 36.0
                    for row in peer_rows
                ),
                "PROTOCOL_FAMILY_SET": _csv_set(families),
                "RTP_PRESENT": "RTP" in families,
                "RTCP_PRESENT": "RTCP" in families,
                "STUN_TURN_PRESENT": "STUN_TURN" in families,
                "VIEW_FIRST_AT": round(view_times[0], 6),
                "VIEW_LAST_AT": round(view_times[-1], 6),
                "UNKNOWN_DIRECTION_COUNT": sum(row.direction == "UNKNOWN_DIRECTION" for row in peer_rows),
            }
        )
    return result


def _gate_post_window(seconds: float | str, threshold: float) -> str:
    if seconds == "UNRESOLVED":
        return "UNRESOLVED"
    return "PASS" if float(seconds) >= threshold else "FAIL"


def _pre_window(capture_start_epoch: float | None, operator_view_start_epoch: float) -> tuple[str, float | str]:
    if capture_start_epoch is None:
        return "UNRESOLVED", "UNRESOLVED"
    seconds = round(operator_view_start_epoch - capture_start_epoch, 6)
    return ("PASS" if seconds >= 5.0 else "FAIL"), seconds


def _observed_endpoints(rows: list[Row]) -> set[str]:
    endpoints: set[str] = set()
    for row in rows:
        if row.src_endpoint:
            endpoints.add(row.src_endpoint)
        if row.dst_endpoint:
            endpoints.add(row.dst_endpoint)
    return endpoints


def _looks_like_ipv6(value: str) -> bool:
    try:
        ipaddress.IPv6Address(value)
        return True
    except ValueError:
        return False


def _privacy_scan(summary: dict[str, object], rows: list[Row]) -> None:
    rendered = json.dumps(summary, sort_keys=True)
    if IPV4_RE.search(rendered):
        raise SystemExit("RAW_IP_IN_SANITISED_SUMMARY=FAILED_SAFE")
    for match in IPV6_CANDIDATE_RE.finditer(rendered):
        if _looks_like_ipv6(match.group(0)):
            raise SystemExit("RAW_IP_IN_SANITISED_SUMMARY=FAILED_SAFE")
    for endpoint in _observed_endpoints(rows):
        if endpoint and endpoint in rendered:
            raise SystemExit("RAW_IP_IN_SANITISED_SUMMARY=FAILED_SAFE")


def summarize(
    rows: list[Row],
    *,
    input_path: Path,
    max_message_rows: int,
    operator_view_start_epoch: float,
    media_reference_epoch: float | None = None,
    capture_start_epoch: float | None = None,
    capture_end_epoch: float | None = None,
    device_ip: str = "",
) -> dict[str, object]:
    del device_ip
    if media_reference_epoch is None:
        reference_epoch, reference_label = resolve_media_active_reference(
            rows,
            operator_view_start_epoch=operator_view_start_epoch,
        )
    else:
        reference_epoch, reference_label = media_reference_epoch, "FIRST_RTP_AFTER_VIEW"
    _apply_media_reference(rows, reference_epoch)

    all_message_rows, emitted_message_rows = family_rows(rows, max_rows=max_message_rows)
    video_rows = [row for row in rows if row.protocol_family == "RTP" and row.rtp_pt]
    rtcp_rows = [row for row in rows if row.protocol_family == "RTCP"]
    rtcp_times = [row.media_relative_time for row in rtcp_rows if row.media_relative_time is not None]
    rtcp_dirs = [row.direction for row in rtcp_rows]
    rtcp_pts = [row.rtcp_pt for row in rtcp_rows]
    video_timestamps = [int(row.rtp_timestamp) for row in video_rows if row.rtp_timestamp.isdigit()]
    video_ssrcs = [row.rtp_ssrc for row in video_rows if row.rtp_ssrc]
    ssrc_change_count = sum(1 for a, b in zip(video_ssrcs, video_ssrcs[1:]) if a != b)
    nal_times: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for nal in row.h264_nal_types:
            if row.media_relative_time is not None:
                nal_times[nal].append(row.media_relative_time)
    repeating = [
        f"{item['PEER_ALIAS']}:{item['SAFE_MESSAGE_TYPE']}"
        for item in all_message_rows
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
    view_to_first = (
        round(reference_epoch - operator_view_start_epoch, 6)
        if reference_epoch is not None
        else "UNRESOLVED"
    )
    post_media = (
        round(capture_end_epoch - reference_epoch, 6)
        if capture_end_epoch is not None and reference_epoch is not None
        else "UNRESOLVED"
    )
    pre_gate, pre_seconds = _pre_window(capture_start_epoch, operator_view_start_epoch)
    summary: dict[str, object] = {
        "SCHEMA": "P116_R13E_OFFICIAL_APP_TRACE_SCALARS_V1",
        "INPUT_SHA256": _sha256(input_path),
        "INPUT_SIZE": input_path.stat().st_size,
        "TOTAL_RECORDS": len(rows),
        "REMOTE_PEER_COUNT": len({row.peer_alias for row in rows if row.peer_alias.startswith("REMOTE_PEER_")}),
        "CLIENT_TO_REMOTE_RECORDS": sum(row.direction == "CLIENT_TO_REMOTE" for row in rows),
        "REMOTE_TO_CLIENT_RECORDS": sum(row.direction == "REMOTE_TO_CLIENT" for row in rows),
        "UNKNOWN_DIRECTION_RECORDS": sum(row.direction == "UNKNOWN_DIRECTION" for row in rows),
        "POST36_CLIENT_TO_REMOTE_RECORDS": (
            sum(row.direction == "CLIENT_TO_REMOTE" and row.media_relative_time is not None and row.media_relative_time > 36.0 for row in rows)
            if reference_epoch is not None
            else "UNRESOLVED"
        ),
        "POST36_ANY_RECORDS": (
            sum(row.media_relative_time is not None and row.media_relative_time > 36.0 for row in rows)
            if reference_epoch is not None
            else "UNRESOLVED"
        ),
        "MEDIA_ACTIVE_REFERENCE": reference_label,
        "FIRST_RTP_AFTER_VIEW_EPOCH": round(reference_epoch, 6) if reference_epoch is not None else "UNRESOLVED",
        "VIEW_TO_FIRST_RTP_SECONDS": view_to_first,
        "PRE_WINDOW_GATE": pre_gate,
        "PRE_WINDOW_SECONDS": pre_seconds,
        "POST_MEDIA_ACTIVE_CAPTURE_SECONDS": post_media,
        "POST_MEDIA_ACTIVE_90S_GATE": _gate_post_window(post_media, 90.0),
        "POST_MEDIA_ACTIVE_60S_GATE": _gate_post_window(post_media, 60.0),
        "MESSAGE_FAMILY_BUCKET_COUNT": len(all_message_rows),
        "MESSAGE_FAMILY_ROWS_EMITTED": len(emitted_message_rows),
        "MESSAGE_FAMILY_ROWS_TRUNCATED": len(all_message_rows) > len(emitted_message_rows),
        "REPEATING_LT36S_CLASSES": _csv_set(repeating),
        "MESSAGE_FAMILY_ROWS": emitted_message_rows,
        "PEER_SUMMARY": _peer_summary(rows),
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
        "RTCP_FIRST_AT": round(rtcp_times[0], 6) if rtcp_times else None,
        "RTCP_LAST_AT": round(rtcp_times[-1], 6) if rtcp_times else None,
        "RTCP_REPEAT_COUNT": len(rtcp_rows),
        "COMPARISON_TEMPLATE": comparison_template,
        "CLOSING_VERDICT_TEMPLATE": verdict_template,
        "COMPARISON_TEMPLATE_READY": True,
        "PRIVACY_GATE": "SCALAR_ONLY_NO_PAYLOAD_NO_IDENTIFIERS",
    }
    _privacy_scan(summary, rows)
    summary["RAW_CLIENT_IP_IN_SANITISED_SUMMARY"] = False
    summary["RAW_REMOTE_IP_IN_SANITISED_SUMMARY"] = False
    return summary


def _validate_summary(summary: dict[str, object]) -> None:
    missing = [key for key in SUMMARY_KEYS if key not in summary]
    if missing:
        raise SystemExit(f"missing summary keys: {','.join(missing)}")
    for row in summary["MESSAGE_FAMILY_ROWS"]:
        missing_row = [key for key in REQUIRED_MESSAGE_FIELDS if key not in row]
        if missing_row:
            raise SystemExit(f"missing message row keys: {','.join(missing_row)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract scalar-only P116 R13E official-app trace metadata.")
    parser.add_argument("--input-tsv", required=True, type=Path)
    parser.add_argument("--client-ip", required=True)
    parser.add_argument("--device-ip", default="")
    parser.add_argument("--operator-view-start-epoch", required=True, type=float)
    parser.add_argument("--capture-start-epoch", type=float)
    parser.add_argument("--capture-end-epoch", type=float)
    parser.add_argument("--max-message-rows", type=int, default=200)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    rows = read_rows(
        args.input_tsv,
        client_ip=args.client_ip,
        device_ip=args.device_ip,
        operator_view_start_epoch=args.operator_view_start_epoch,
    )
    summary = summarize(
        rows,
        input_path=args.input_tsv,
        max_message_rows=args.max_message_rows,
        operator_view_start_epoch=args.operator_view_start_epoch,
        capture_start_epoch=args.capture_start_epoch,
        capture_end_epoch=args.capture_end_epoch,
        device_ip=args.device_ip,
    )
    _validate_summary(summary)
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.write_text(text + "\n", encoding="utf-8")
        args.output_json.chmod(0o600)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
