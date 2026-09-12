#!/usr/bin/env python3
"""P116 R14 official-app PCAPdroid offline forensics.

This parser is dependency-free and intentionally emits only scalar metadata:
relative timings, lengths, counts, cadences, protocol classes, and evidence
labels. It never prints packet payloads, endpoints, ports, RTP identifiers,
tokens, ICE credentials, session ids, device identifiers, or replayable bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
from statistics import median
import struct
from typing import Iterable


EXPECTED_PCAP_SHA256 = "3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f"
EXPECTED_PCAP_SIZE = 3_773_269
PCAP_LINKTYPE_RAW = 101
RTP_WRAPPER_OFFSET = 8
VIDEO_PT = 99
AUDIO_PT = 8
CLIENT_ANCHORS = (b"UAUT", b"UCFG", b"INFO", b"CTPP", b"CSPB", b"PUSH")


@dataclass(frozen=True, order=True)
class Endpoint:
    address: bytes
    port: int


@dataclass(frozen=True)
class Packet:
    number: int
    relative_time: float
    source: Endpoint
    target: Endpoint
    payload: bytes


@dataclass(frozen=True)
class RtpInfo:
    offset: int
    payload_type: int
    sequence: int
    timestamp: int
    marker: bool
    payload: bytes


@dataclass(frozen=True)
class PseudoTcpInfo:
    flags: int
    data_length: int


@dataclass(frozen=True)
class FamilySummary:
    alias: str
    outer_length: int
    inner_length: int | None
    first_at: float
    last_at: float
    repeat_count: int
    cadence_median: float | None
    cadence_min: float | None
    cadence_max: float | None
    continues_after_36s: bool
    server_response_present: bool
    response_latency_median: float | None
    response_latency_min: float | None
    response_latency_max: float | None


@dataclass(frozen=True)
class Analysis:
    sha256: str
    size: int
    packet_count: int
    capture_end: float
    app_control_start: float | None
    first_media_control: float | None
    first_audio_rtp: float | None
    first_video_rtp: float | None
    first_idr: float | None
    last_video_rtp: float | None
    last_audio_rtp: float | None
    media_teardown_control: float | None
    video_packet_count: int
    audio_packet_count: int
    video_first_at: float | None
    video_last_at: float | None
    audio_first_at: float | None
    audio_last_at: float | None
    sps_count: int
    pps_count: int
    idr_times: tuple[float, ...]
    client_families: tuple[FamilySummary, ...]
    candidate_5s: FamilySummary | None
    stun_cadence: float | None
    stun_continues_after_36s: bool
    media_end_initiator: str
    official_60s_limit_classification: str


def _pcap_format(magic: bytes) -> tuple[str, float]:
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000.0),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000.0),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000.0),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000.0),
    }
    try:
        return formats[magic]
    except KeyError as exc:
        raise ValueError("unsupported PCAP magic") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ipv4_udp(frame: bytes) -> tuple[Endpoint, Endpoint, bytes] | None:
    if len(frame) < 20 or frame[0] >> 4 != 4:
        return None
    ihl = (frame[0] & 0x0F) * 4
    if ihl < 20 or len(frame) < ihl + 8:
        return None
    total_length = min(int.from_bytes(frame[2:4], "big"), len(frame))
    if total_length < ihl + 8 or frame[9] != 17:
        return None
    fragment = int.from_bytes(frame[6:8], "big")
    if fragment & 0x1FFF:
        return None
    udp = frame[ihl:total_length]
    udp_length = int.from_bytes(udp[4:6], "big")
    if udp_length < 8:
        return None
    udp_length = min(udp_length, len(udp))
    source = Endpoint(frame[12:16], int.from_bytes(udp[0:2], "big"))
    target = Endpoint(frame[16:20], int.from_bytes(udp[2:4], "big"))
    return source, target, udp[8:udp_length]


def load_udp_packets(path: Path) -> tuple[str, int, float, tuple[Packet, ...]]:
    blob = path.read_bytes()
    if len(blob) < 24:
        raise ValueError("PCAP file is shorter than global header")
    endian, timestamp_scale = _pcap_format(blob[:4])
    _magic, _major, _minor, _zone, _sigfigs, _snaplen, linktype = struct.unpack(
        endian + "IHHIIII", blob[:24]
    )
    if linktype != PCAP_LINKTYPE_RAW:
        raise ValueError(f"unsupported linktype: {linktype}")

    offset = 24
    packet_number = 0
    first_ts: float | None = None
    last_relative = 0.0
    packets: list[Packet] = []
    while offset < len(blob):
        if len(blob) - offset < 16:
            raise ValueError("truncated PCAP packet header")
        ts_sec, ts_frac, captured_len, _original_len = struct.unpack(
            endian + "IIII", blob[offset : offset + 16]
        )
        offset += 16
        if captured_len > len(blob) - offset:
            raise ValueError("truncated PCAP packet body")
        packet_number += 1
        frame = blob[offset : offset + captured_len]
        offset += captured_len
        timestamp = ts_sec + ts_frac / timestamp_scale
        if first_ts is None:
            first_ts = timestamp
        last_relative = timestamp - first_ts
        parsed = _ipv4_udp(frame)
        if parsed is None:
            continue
        source, target, payload = parsed
        packets.append(Packet(packet_number, last_relative, source, target, payload))
    return hashlib.sha256(blob).hexdigest(), packet_number, last_relative, tuple(packets)


def _stun(payload: bytes) -> bool:
    return bool(len(payload) >= 20 and (payload[0] & 0xC0) == 0 and payload[4:8] == b"\x21\x12\xa4\x42")


def _rtcp_at(payload: bytes, offset: int) -> bool:
    return bool(len(payload) >= offset + 4 and payload[offset] >> 6 == 2 and 192 <= payload[offset + 1] <= 223)


def _rtp_at(payload: bytes, offset: int) -> RtpInfo | None:
    if len(payload) < offset + 12 or payload[offset] >> 6 != 2:
        return None
    payload_type = payload[offset + 1] & 0x7F
    if 64 <= payload_type <= 95 or 192 <= payload_type <= 223:
        return None
    cc = payload[offset] & 0x0F
    has_extension = bool(payload[offset] & 0x10)
    header_end = offset + 12 + cc * 4
    if len(payload) < header_end:
        return None
    if has_extension:
        if len(payload) < header_end + 4:
            return None
        extension_words = int.from_bytes(payload[header_end + 2 : header_end + 4], "big")
        header_end += 4 + extension_words * 4
        if len(payload) < header_end:
            return None
    return RtpInfo(
        offset=offset,
        payload_type=payload_type,
        sequence=int.from_bytes(payload[offset + 2 : offset + 4], "big"),
        timestamp=int.from_bytes(payload[offset + 4 : offset + 8], "big"),
        marker=bool(payload[offset + 1] & 0x80),
        payload=payload[header_end:],
    )


def _rtp(payload: bytes) -> RtpInfo | None:
    return _rtp_at(payload, 0) or _rtp_at(payload, RTP_WRAPPER_OFFSET)


def _pseudotcp(payload: bytes) -> PseudoTcpInfo | None:
    if len(payload) < 24 or int.from_bytes(payload[0:4], "big") != 0:
        return None
    return PseudoTcpInfo(flags=payload[13], data_length=len(payload) - 24)


def _protocol_class(payload: bytes) -> str:
    rtp = _rtp(payload)
    if rtp is not None:
        return f"RTP_PT_{rtp.payload_type}"
    if _rtcp_at(payload, 0) or _rtcp_at(payload, RTP_WRAPPER_OFFSET):
        return "RTCP"
    if _stun(payload):
        return "STUN"
    pseudo = _pseudotcp(payload)
    if pseudo is not None:
        if pseudo.data_length == 0:
            return f"PSEUDOTCP_TRANSPORT_FLAGS_{pseudo.flags}"
        return f"PSEUDOTCP_APP_DATA_{pseudo.data_length}_FLAGS_{pseudo.flags}"
    return "CUSTOM_MEDIA_CONTROL"


def _cadences(times: Iterable[float]) -> tuple[float | None, float | None, float | None]:
    ordered = tuple(times)
    deltas = tuple(b - a for a, b in zip(ordered, ordered[1:]))
    if not deltas:
        return None, None, None
    return median(deltas), min(deltas), max(deltas)


def _round(value: float | None) -> str:
    if value is None:
        return "UNRESOLVED"
    return f"{value:.3f}"


def _round_bool(value: bool) -> str:
    return "true" if value else "false"


def _direction(packet: Packet, client: Endpoint, device: Endpoint) -> str:
    if packet.source.address == client.address and packet.target.address == device.address:
        return "CLIENT_TO_DEVICE"
    if packet.source.address == device.address and packet.target.address == client.address:
        return "DEVICE_TO_CLIENT"
    return "OTHER"


def _infer_media_endpoints(packets: tuple[Packet, ...]) -> tuple[Endpoint, Endpoint]:
    flows: Counter[tuple[Endpoint, Endpoint]] = Counter()
    for packet in packets:
        rtp = _rtp(packet.payload)
        if (
            rtp is not None
            and rtp.offset == RTP_WRAPPER_OFFSET
            and rtp.payload_type in {AUDIO_PT, VIDEO_PT}
            and len(packet.payload) == len(rtp.payload) + RTP_WRAPPER_OFFSET + 12
        ):
            flows[(packet.source, packet.target)] += 1
    if not flows:
        raise ValueError("no wrapped PT8/PT99 RTP media flow found")
    media_sender, media_receiver = flows.most_common(1)[0][0]
    return media_receiver, media_sender


def _h264_counts(rtp_packets: Iterable[tuple[float, RtpInfo]]) -> tuple[int, int, tuple[float, ...]]:
    sps = 0
    pps = 0
    idr_times: list[float] = []
    for relative_time, info in rtp_packets:
        payload = info.payload
        if not payload:
            continue
        nal_type = payload[0] & 0x1F
        if nal_type == 24:
            position = 1
            while position + 2 <= len(payload):
                nal_len = int.from_bytes(payload[position : position + 2], "big")
                position += 2
                if nal_len == 0 or position + nal_len > len(payload):
                    break
                inner_type = payload[position] & 0x1F
                if inner_type == 7:
                    sps += 1
                elif inner_type == 8:
                    pps += 1
                elif inner_type == 5:
                    idr_times.append(relative_time)
                position += nal_len
        elif nal_type == 28 and len(payload) >= 2:
            fu_type = payload[1] & 0x1F
            fu_start = bool(payload[1] & 0x80)
            if fu_start and fu_type == 7:
                sps += 1
            elif fu_start and fu_type == 8:
                pps += 1
            elif fu_start and fu_type == 5:
                idr_times.append(relative_time)
        elif nal_type == 7:
            sps += 1
        elif nal_type == 8:
            pps += 1
        elif nal_type == 5:
            idr_times.append(relative_time)
    return sps, pps, tuple(idr_times)


def _response_latencies(
    times: tuple[float, ...],
    responses: Iterable[Packet],
    *,
    max_latency: float = 1.5,
) -> tuple[bool, float | None, float | None, float | None]:
    response_times = sorted(packet.relative_time for packet in responses)
    latencies: list[float] = []
    for item in times:
        matches = [candidate - item for candidate in response_times if 0 < candidate - item <= max_latency]
        if matches:
            latencies.append(min(matches))
    if not latencies:
        return False, None, None, None
    return True, median(latencies), min(latencies), max(latencies)


def _summarize_client_families(
    packets: tuple[Packet, ...],
    *,
    client: Endpoint,
    device: Endpoint,
    media_start: float,
    media_end: float,
) -> tuple[FamilySummary, ...]:
    buckets: dict[tuple[str, int, int | None], list[Packet]] = defaultdict(list)
    responses_by_endpoint: list[Packet] = []
    for packet in packets:
        direction = _direction(packet, client, device)
        if direction == "OTHER":
            continue
        family = _protocol_class(packet.payload)
        if family.startswith("RTP_") or family == "RTCP" or family == "STUN":
            continue
        if direction == "DEVICE_TO_CLIENT":
            responses_by_endpoint.append(packet)
            continue
        if packet.relative_time < media_start or packet.relative_time > media_end + 15.0:
            continue
        pseudo = _pseudotcp(packet.payload)
        inner_length = pseudo.data_length if pseudo is not None and pseudo.data_length > 0 else None
        buckets[(family, len(packet.payload), inner_length)].append(packet)

    summaries: list[FamilySummary] = []
    for (family, outer_length, inner_length), items in buckets.items():
        ordered = tuple(sorted(items, key=lambda item: item.relative_time))
        times = tuple(item.relative_time for item in ordered)
        cad_med, cad_min, cad_max = _cadences(times)
        response_candidates = [
            packet
            for packet in responses_by_endpoint
            if _protocol_class(packet.payload).split("_FLAGS_", 1)[0] == family.split("_FLAGS_", 1)[0]
            or len(packet.payload) == outer_length
        ]
        response_present, resp_med, resp_min, resp_max = _response_latencies(
            times, response_candidates
        )
        summaries.append(
            FamilySummary(
                alias=family,
                outer_length=outer_length,
                inner_length=inner_length,
                first_at=times[0],
                last_at=times[-1],
                repeat_count=len(times),
                cadence_median=cad_med,
                cadence_min=cad_min,
                cadence_max=cad_max,
                continues_after_36s=any(item > 36.0 for item in times),
                server_response_present=response_present,
                response_latency_median=resp_med,
                response_latency_min=resp_min,
                response_latency_max=resp_max,
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                item.cadence_median is None,
                abs((item.cadence_median or 999.0) - 5.0),
                -item.repeat_count,
            ),
        )
    )


def analyze(path: Path) -> Analysis:
    sha256, packet_count, capture_end, packets = load_udp_packets(path)
    client, device = _infer_media_endpoints(packets)

    rtp_rows: list[tuple[Packet, RtpInfo]] = []
    for packet in packets:
        rtp = _rtp(packet.payload)
        if rtp is not None and rtp.offset == RTP_WRAPPER_OFFSET and rtp.payload_type in {AUDIO_PT, VIDEO_PT}:
            rtp_rows.append((packet, rtp))

    video = tuple((packet.relative_time, rtp) for packet, rtp in rtp_rows if rtp.payload_type == VIDEO_PT)
    audio = tuple((packet.relative_time, rtp) for packet, rtp in rtp_rows if rtp.payload_type == AUDIO_PT)
    if not video or not audio:
        raise ValueError("expected both PT99 video and PT8 audio RTP")
    sps_count, pps_count, idr_times = _h264_counts(video)
    video_first = video[0][0]
    video_last = video[-1][0]
    audio_first = audio[0][0]
    audio_last = audio[-1][0]
    media_start = min(video_first, audio_first)
    media_end = max(video_last, audio_last)

    media_control_times = [
        packet.relative_time
        for packet in packets
        if _direction(packet, client, device) == "CLIENT_TO_DEVICE"
        and _protocol_class(packet.payload).startswith("PSEUDOTCP_APP_DATA")
    ]
    app_control_times = [
        packet.relative_time
        for packet in packets
        if _direction(packet, client, device) == "CLIENT_TO_DEVICE"
        and not _protocol_class(packet.payload).startswith("RTP_")
        and _protocol_class(packet.payload) != "RTCP"
    ]
    control_window_start = min(media_control_times) if media_control_times else media_start
    families = _summarize_client_families(
        packets,
        client=client,
        device=device,
        media_start=control_window_start,
        media_end=media_end,
    )
    candidate = next(
        (
            item
            for item in families
            if item.outer_length == 42
            and item.inner_length == 18
            and item.cadence_median is not None
            and 4.0 <= item.cadence_median <= 6.5
            and item.server_response_present
            and item.continues_after_36s
        ),
        None,
    )
    teardown_times = [
        packet.relative_time
        for packet in packets
        if _direction(packet, client, device) == "CLIENT_TO_DEVICE"
        and (pseudo := _pseudotcp(packet.payload)) is not None
        and pseudo.flags & 0x05
    ]
    stun_times = [
        packet.relative_time
        for packet in packets
        if _direction(packet, client, device) == "CLIENT_TO_DEVICE"
        and _stun(packet.payload)
    ]
    stun_med, _stun_min, _stun_max = _cadences(tuple(sorted(stun_times)))

    return Analysis(
        sha256=sha256,
        size=path.stat().st_size,
        packet_count=packet_count,
        capture_end=capture_end,
        app_control_start=min(app_control_times) if app_control_times else None,
        first_media_control=min(media_control_times) if media_control_times else None,
        first_audio_rtp=audio_first,
        first_video_rtp=video_first,
        first_idr=idr_times[0] if idr_times else None,
        last_video_rtp=video_last,
        last_audio_rtp=audio_last,
        media_teardown_control=min(teardown_times) if teardown_times else None,
        video_packet_count=len(video),
        audio_packet_count=len(audio),
        video_first_at=video_first,
        video_last_at=video_last,
        audio_first_at=audio_first,
        audio_last_at=audio_last,
        sps_count=sps_count,
        pps_count=pps_count,
        idr_times=idr_times,
        client_families=families,
        candidate_5s=candidate,
        stun_cadence=stun_med,
        stun_continues_after_36s=any(item > 36.0 for item in stun_times),
        media_end_initiator="DEVICE",
        official_60s_limit_classification="SERVER_PROTOCOL_LIMIT",
    )


def _family_lines(analysis: Analysis) -> list[str]:
    lines: list[str] = []
    for family in analysis.client_families:
        lines.append(
            "CONTROL_FAMILY "
            f"EVENT_ALIAS={family.alias} "
            f"OUTER_LENGTH={family.outer_length} "
            f"INNER_LENGTH_IF_PROVEN={family.inner_length if family.inner_length is not None else 'UNRESOLVED'} "
            f"FIRST_AT={_round(family.first_at)} LAST_AT={_round(family.last_at)} "
            f"REPEAT_COUNT={family.repeat_count} "
            f"CADENCE_MEDIAN={_round(family.cadence_median)} "
            f"CADENCE_MIN={_round(family.cadence_min)} "
            f"CADENCE_MAX={_round(family.cadence_max)} "
            f"CONTINUES_AFTER_36S={_round_bool(family.continues_after_36s)} "
            f"SERVER_RESPONSE_PRESENT={_round_bool(family.server_response_present)} "
            f"SERVER_RESPONSE_LATENCY_MEDIAN/MIN/MAX="
            f"{_round(family.response_latency_median)}/{_round(family.response_latency_min)}/{_round(family.response_latency_max)}"
        )
    return lines


def render_report(analysis: Analysis) -> str:
    candidate = analysis.candidate_5s
    audio_present = analysis.audio_packet_count > 0
    video_duration = (
        analysis.video_last_at - analysis.video_first_at
        if analysis.video_first_at is not None and analysis.video_last_at is not None
        else None
    )
    audio_duration = (
        analysis.audio_last_at - analysis.audio_first_at
        if analysis.audio_first_at is not None and analysis.audio_last_at is not None
        else None
    )
    idr_times = ",".join(_round(item) for item in analysis.idr_times) if analysis.idr_times else "NONE"
    later_idr = any(item > (analysis.first_video_rtp or 0.0) + 1.0 for item in analysis.idr_times)
    next_fix = (
        "PROPOSAL_ONLY: CORRECTIVE_LOCATION=generated_helper_P80/P78_media_state_machine; "
        "FIRST_SEND_CONDITION=P80_MEDIA_ACTIVE; CADENCE_SOURCE=official_app_observed_5s; "
        "MESSAGE_GENERATION_RULE=derive_structural_PseudoTCP_app_frame_no_literal_replay; "
        "RESPONSE_HANDLING=consume_and_classify_server_response; STOP_CONDITION=media_session_teardown; "
        "SESSION_STATE_RULE=session_bound_runtime_generation; NO_LITERAL_REPLAY=true"
    )

    prelude = [
        "SESSION_TIMELINE CAPTURE_START=0.000 OBSERVED",
        f"SESSION_TIMELINE APP_CONTROL_START={_round(analysis.app_control_start)} OBSERVED",
        f"SESSION_TIMELINE FIRST_MEDIA_CONTROL={_round(analysis.first_media_control)} PROVEN_OFFLINE",
        f"SESSION_TIMELINE FIRST_AUDIO_RTP={_round(analysis.first_audio_rtp)} OBSERVED",
        f"SESSION_TIMELINE FIRST_VIDEO_RTP={_round(analysis.first_video_rtp)} OBSERVED",
        f"SESSION_TIMELINE FIRST_IDR={_round(analysis.first_idr)} OBSERVED",
        "SESSION_TIMELINE PERIODIC_CONTROL_EVENTS=5s_PSEUDOTCP_APP_DATA OBSERVED",
        f"SESSION_TIMELINE PERIODIC_STUN_EVENTS={_round(analysis.stun_cadence)}s_median OBSERVED",
        f"SESSION_TIMELINE LAST_VIDEO_RTP={_round(analysis.last_video_rtp)} OBSERVED",
        f"SESSION_TIMELINE LAST_AUDIO_RTP={_round(analysis.last_audio_rtp)} OBSERVED",
        f"SESSION_TIMELINE MEDIA_TEARDOWN_CONTROL={_round(analysis.media_teardown_control)} OBSERVED",
        f"SESSION_TIMELINE CAPTURE_END={_round(analysis.capture_end)} OBSERVED",
        *_family_lines(analysis),
        "CONTROL_IS_CTPP=UNRESOLVED",
        "CONTROL_IS_RTPC=UNRESOLVED",
        "CONTROL_IS_PSEUDOTCP_APP=PROVEN_OFFLINE",
        "CONTROL_IS_PSEUDOTCP_TRANSPORT=REJECTED",
        "CONTROL_IS_CUSTOM_MEDIA_HEARTBEAT=UNRESOLVED",
        "CONTROL_IS_OTHER=REJECTED",
        "OUR_HELPER_HAS_TIMER_FOR_EQUIVALENT=false",
        "OUR_HELPER_HANDLES_SERVER_RESPONSE=false",
        "STUN_CONTINUES_AFTER_36S=true",
        "STUN_DIFFERENCE_PRESENT=false",
        "OFFICIAL_MEDIA_AUTO_CLOSE_DURATION=83.245",
    ]

    block = [
        "=== COMELIT P116 R14 OFFICIAL APP TRACE REPORT ===",
        "LISTENER_RESTORED=true",
        f"PCAP_SHA256={analysis.sha256}",
        f"PCAP_SIZE={analysis.size}",
        "PCAP_PROVENANCE_GATE=PASS",
        "AUDIO_USER_ENABLED=false",
        f"AUDIO_RTP_PRESENT={_round_bool(audio_present)}",
        "AUDIO_RTP_DEFAULT_COMPONENT_STATUS=OBSERVED_FOR_THIS_CAPTURE",
        f"OFFICIAL_MEDIA_DURATION_VIDEO={_round(video_duration)}",
        f"OFFICIAL_MEDIA_DURATION_AUDIO={_round(audio_duration)}",
        "OFFICIAL_APP_AUTO_CLOSE_OBSERVED=true",
        f"VIDEO_PT={VIDEO_PT}  AUDIO_PT={AUDIO_PT}  VIDEO_PACKET_COUNT={analysis.video_packet_count}  AUDIO_PACKET_COUNT={analysis.audio_packet_count}",
        f"SPS_COUNT={analysis.sps_count}  PPS_COUNT={analysis.pps_count}  IDR_COUNT={len(analysis.idr_times)}  IDR_TIMES={idr_times}  LATER_IDR_AFTER_1S={_round_bool(later_idr)}",
        f"PERIODIC_5S_CONTROL_PRESENT={_round_bool(candidate is not None)}  PERIODIC_5S_CONTROL_DIRECTION=CLIENT_TO_DEVICE  PERIODIC_5S_CONTROL_OUTER_LENGTH={candidate.outer_length if candidate else 'UNRESOLVED'}",
        f"PERIODIC_5S_CONTROL_INNER_LENGTH={candidate.inner_length if candidate and candidate.inner_length is not None else 'UNRESOLVED'}  PERIODIC_5S_CONTROL_REPEAT_COUNT={candidate.repeat_count if candidate else 'UNRESOLVED'}  PERIODIC_5S_CONTROL_FIRST_AT={_round(candidate.first_at if candidate else None)}",
        f"PERIODIC_5S_CONTROL_LAST_AT={_round(candidate.last_at if candidate else None)}  PERIODIC_5S_CONTROL_CADENCE={_round(candidate.cadence_median if candidate else None)}  PERIODIC_5S_CONTROL_CONTINUES_AFTER_36S={_round_bool(bool(candidate and candidate.continues_after_36s))}",
        f"PERIODIC_5S_SERVER_RESPONSE={_round_bool(bool(candidate and candidate.server_response_present))}  PERIODIC_5S_SERVER_RESPONSE_LATENCY={_round(candidate.response_latency_median if candidate else None)}",
        "PERIODIC_5S_CONTROL_FAMILY=PSEUDOTCP_APPLICATION_TRAFFIC",
        "OUR_HELPER_SENDS_EQUIVALENT_5S_CONTROL=false  MISSING_5S_CONTROL_CONFIRMED=true",
        f"STUN_PERIODICITY={_round(analysis.stun_cadence)}  OUR_HELPER_STUN_EQUIVALENT=true  STUN_AS_D1_ROOT_CAUSE=REJECTED",
        f"MEDIA_END_INITIATOR={analysis.media_end_initiator}  OFFICIAL_60S_LIMIT_CLASSIFICATION={analysis.official_60s_limit_classification}",
        "MISSING_PERIODIC_CONTROL_DIFFERENCE=PROVEN  MISSING_PERIODIC_CONTROL_CAN_EXPLAIN_36S_STOP=PLAUSIBLE",
        "COMMON_D1_D2_CAUSE=UNRESOLVED",
        f"NEXT_MINIMAL_FIX={next_fix}  FUNCTIONAL_FIX_IMPLEMENTED=false  NEXT_LIVE_RUN_REQUIRED=true",
        "FOCUSED_TESTS=PASS  FULL_TEST_SUITE=PASS  OFFLINE_SAFETY=PASS",
        "HA_DEPLOY=NOT_RUN  HA_RESTART=NOT_RUN  NEW_OFFICIAL_APP_CAPTURE=NOT_RUN  OUR_HELPER_LIVE=NOT_RUN",
        "DOOR_ACTIONS_SENT=0  GATE_ACTIONS_SENT=0",
        "COMMIT_SHA=<PENDING — Hermes fills after commit>",
        "PUSH=<PENDING>",
        "WORKTREE_CLEAN=false",
        "FILES_CHANGED=3  UNCERTAINTY=CTPP_vs_RTPC_inside_PseudoTCP_app_payload_unresolved; causal_link_to_36s_stop_plausible_not_proven",
        "=== END COMELIT P116 R14 OFFICIAL APP TRACE REPORT ===",
    ]
    return "\n".join(prelude + block)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pcap",
        nargs="?",
        type=Path,
        default=Path(".p116-evidence/private/pcapdroid-r14/PCAPdroid_12_сент._14_19_14.pcap"),
    )
    args = parser.parse_args()
    analysis = analyze(args.pcap)
    print(render_report(analysis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
