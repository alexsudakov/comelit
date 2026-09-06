#!/usr/bin/env python3
"""Offline codec-shape forensic for Comelit offset-8 wrapped RTP.

P57/P58 proved that almost all post-218 opaque datagrams contain RTP-v2 at
byte offset 8 and form three stable streams. This analyzer performs the first
bounded codec-level inspection:

* RTP payload type 8 is reported using the static RTP/AVP mapping PCMA/8000.
* RTP payload type 99 is inspected only for H.264 packetization shape:
  single NAL units, STAP-A, and FU-A.

It never reconstructs access units, decodes video/audio, writes media files,
or emits payload bytes, sequence/timestamp/SSRC values, endpoints, or ports.
No network I/O is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path

from entrance_device_video_ack_pcap_forensic import EXPECTED_PCAP_SHA256
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import (
    BOUNDARY_PACKET,
    SelectedDatagram,
    _read_selected_datagrams,
)
from entrance_post_218_rtp_v2_shape_pcap_forensic import _parse_rtp_v2_shape
from entrance_post_218_wrapped_rtp_shape_pcap_forensic import _direction, _opaque
from pseudotcp_pcap_handshake_forensic import load_capture, select_vip_flow

RTP_OFFSET = 8
PT_PCMA = 8
PT_DYNAMIC_VIDEO = 99


@dataclass(frozen=True)
class H264Shape:
    kind: str
    nal_type: int | None
    fu_original_nal_type: int | None
    fu_start: bool
    fu_end: bool
    stap_nal_count: int


@dataclass(frozen=True)
class StreamCodecStat:
    ordinal: int
    direction: str
    payload_type: int
    packet_count: int
    media_bytes: int
    codec_class: str
    h264_single_nal_count: int
    h264_stap_a_count: int
    h264_fu_a_count: int
    h264_unrecognized_count: int
    h264_fu_start_count: int
    h264_fu_end_count: int
    h264_single_nal_types: tuple[tuple[int, int], ...]
    h264_fu_original_nal_types: tuple[tuple[int, int], ...]
    h264_stap_total_inner_nals: int


@dataclass(frozen=True)
class Result:
    opaque_count: int
    offset8_rtp_count: int
    residual_count: int
    streams: tuple[StreamCodecStat, ...]
    pt8_packet_count: int
    pt99_packet_count: int
    pt99_h264_shaped_count: int
    pt99_h264_unrecognized_count: int


def _rtp_media(payload: bytes):
    if len(payload) <= RTP_OFFSET:
        return None
    inner = payload[RTP_OFFSET:]
    meta = _parse_rtp_v2_shape(inner)
    if meta is None:
        return None
    media_start = meta.header_length
    media_end = media_start + meta.media_data_length
    media = inner[media_start:media_end]
    if len(media) != meta.media_data_length or not media:
        return None
    return meta, media


def _parse_stap_a(media: bytes) -> H264Shape | None:
    # RFC 6184 STAP-A: 1-byte indicator, then repeated 16-bit length + NAL.
    if len(media) < 4 or (media[0] & 0x1F) != 24:
        return None
    pos = 1
    count = 0
    while pos < len(media):
        if pos + 2 > len(media):
            return None
        size = int.from_bytes(media[pos:pos + 2], "big")
        pos += 2
        if size <= 0 or pos + size > len(media):
            return None
        inner_type = media[pos] & 0x1F
        if inner_type < 1 or inner_type > 23:
            return None
        pos += size
        count += 1
    if pos != len(media) or count == 0:
        return None
    return H264Shape("STAP_A", None, None, False, False, count)


def _parse_h264_shape(media: bytes) -> H264Shape | None:
    if not media:
        return None
    nal_type = media[0] & 0x1F
    if 1 <= nal_type <= 23:
        return H264Shape("SINGLE_NAL", nal_type, None, False, False, 0)
    if nal_type == 24:
        return _parse_stap_a(media)
    if nal_type == 28:
        if len(media) < 3:
            return None
        fu_header = media[1]
        original_type = fu_header & 0x1F
        if original_type < 1 or original_type > 23:
            return None
        return H264Shape(
            "FU_A",
            None,
            original_type,
            bool(fu_header & 0x80),
            bool(fu_header & 0x40),
            0,
        )
    return None


def analyze(
    datagrams: tuple[SelectedDatagram, ...],
    *,
    client,
    device,
    boundary_packet: int = BOUNDARY_PACKET,
) -> Result:
    boundary = [item for item in datagrams if item.packet_number == boundary_packet]
    if len(boundary) != 1:
        raise ValueError("expected exactly one selected-flow boundary datagram")

    opaque = _opaque(datagrams, boundary_packet)
    shaped: list[tuple[SelectedDatagram, str, object, bytes]] = []
    residual: list[SelectedDatagram] = []
    for item in opaque:
        parsed = _rtp_media(item.payload)
        if parsed is None:
            residual.append(item)
            continue
        meta, media = parsed
        shaped.append((item, _direction(item, client, device), meta, media))

    grouped: dict[tuple[str, int, int], list[tuple[SelectedDatagram, object, bytes]]] = {}
    for item, flow_direction, meta, media in shaped:
        grouped.setdefault((flow_direction, meta.ssrc, meta.payload_type), []).append((item, meta, media))

    ordered = sorted(grouped.items(), key=lambda pair: min(x[0].packet_number for x in pair[1]))
    streams: list[StreamCodecStat] = []
    pt8_count = pt99_count = pt99_shaped = pt99_unrecognized = 0

    for ordinal, ((flow_direction, _ssrc, payload_type), pairs) in enumerate(ordered, start=1):
        pairs = sorted(pairs, key=lambda x: x[0].packet_number)
        media_bytes = sum(len(media) for _, _, media in pairs)
        single_types: Counter[int] = Counter()
        fu_types: Counter[int] = Counter()
        single = stap = fu = unrecognized = fu_start = fu_end = stap_inner = 0

        if payload_type == PT_PCMA:
            codec_class = "RTP_AVP_PT8_PCMA_8000_MONO"
            pt8_count += len(pairs)
        elif payload_type == PT_DYNAMIC_VIDEO:
            pt99_count += len(pairs)
            for _item, _meta, media in pairs:
                shape = _parse_h264_shape(media)
                if shape is None:
                    unrecognized += 1
                    continue
                if shape.kind == "SINGLE_NAL":
                    single += 1
                    assert shape.nal_type is not None
                    single_types[shape.nal_type] += 1
                elif shape.kind == "STAP_A":
                    stap += 1
                    stap_inner += shape.stap_nal_count
                elif shape.kind == "FU_A":
                    fu += 1
                    assert shape.fu_original_nal_type is not None
                    fu_types[shape.fu_original_nal_type] += 1
                    fu_start += int(shape.fu_start)
                    fu_end += int(shape.fu_end)
            shaped_count = single + stap + fu
            pt99_shaped += shaped_count
            pt99_unrecognized += unrecognized
            codec_class = "H264_RTP_PACKETIZATION_SHAPED" if shaped_count and unrecognized == 0 else "H264_RTP_PACKETIZATION_PARTIAL"
        else:
            codec_class = "UNCLASSIFIED_RTP_PAYLOAD_TYPE"

        streams.append(
            StreamCodecStat(
                ordinal=ordinal,
                direction=flow_direction,
                payload_type=payload_type,
                packet_count=len(pairs),
                media_bytes=media_bytes,
                codec_class=codec_class,
                h264_single_nal_count=single,
                h264_stap_a_count=stap,
                h264_fu_a_count=fu,
                h264_unrecognized_count=unrecognized,
                h264_fu_start_count=fu_start,
                h264_fu_end_count=fu_end,
                h264_single_nal_types=tuple(sorted(single_types.items())),
                h264_fu_original_nal_types=tuple(sorted(fu_types.items())),
                h264_stap_total_inner_nals=stap_inner,
            )
        )

    return Result(
        opaque_count=len(opaque),
        offset8_rtp_count=len(shaped),
        residual_count=len(residual),
        streams=tuple(streams),
        pt8_packet_count=pt8_count,
        pt99_packet_count=pt99_count,
        pt99_h264_shaped_count=pt99_shaped,
        pt99_h264_unrecognized_count=pt99_unrecognized,
    )


def _counter_text(values: tuple[tuple[int, int], ...]) -> str:
    if not values:
        return "NONE"
    return ",".join(f"{key}:{count}" for key, count in values)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE OFFSET8 RTP CODEC SHAPE PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"BOUNDARY_PACKET={BOUNDARY_PACKET}",
        f"RTP_OFFSET={RTP_OFFSET}",
        f"OPAQUE_INPUT_COUNT={result.opaque_count}",
        f"OFFSET8_RTP_COUNT={result.offset8_rtp_count}",
        f"OFFSET8_RESIDUAL_COUNT={result.residual_count}",
        f"RTP_STREAM_COUNT={len(result.streams)}",
        f"PT8_PACKET_COUNT={result.pt8_packet_count}",
        "PT8_STATIC_RTP_AVP_MAPPING=PCMA_8000_MONO",
        f"PT99_PACKET_COUNT={result.pt99_packet_count}",
        f"PT99_H264_SHAPED_COUNT={result.pt99_h264_shaped_count}",
        f"PT99_H264_UNRECOGNIZED_COUNT={result.pt99_h264_unrecognized_count}",
        f"PT99_ALL_PACKETS_H264_SHAPED={'true' if result.pt99_packet_count > 0 and result.pt99_h264_unrecognized_count == 0 and result.pt99_h264_shaped_count == result.pt99_packet_count else 'false'}",
    ]
    for stream in result.streams:
        lines.append(
            "RTP_CODEC_STREAM "
            f"ordinal={stream.ordinal} direction={stream.direction} payload_type={stream.payload_type} "
            f"packet_count={stream.packet_count} media_bytes={stream.media_bytes} codec_class={stream.codec_class} "
            f"single_nal={stream.h264_single_nal_count} stap_a={stream.h264_stap_a_count} fu_a={stream.h264_fu_a_count} "
            f"unrecognized={stream.h264_unrecognized_count} fu_start={stream.h264_fu_start_count} fu_end={stream.h264_fu_end_count} "
            f"single_nal_types={_counter_text(stream.h264_single_nal_types)} "
            f"fu_original_nal_types={_counter_text(stream.h264_fu_original_nal_types)} "
            f"stap_inner_nals={stream.h264_stap_total_inner_nals}"
        )
    lines.extend([
        "MEDIA_ACCESS_UNITS_RECONSTRUCTED=false",
        "VIDEO_FRAMES_DECODED=false",
        "AUDIO_DECODED=false",
        "MEDIA_FILES_WRITTEN=false",
        "PAYLOAD_BYTES_EMITTED=false",
        "SEQUENCE_VALUES_EMITTED=false",
        "TIMESTAMP_VALUES_EMITTED=false",
        "SSRC_VALUES_EMITTED=false",
        "ENDPOINTS_EMITTED=false",
        "PORTS_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        "HEX_PAYLOAD_EMITTED=false",
        "BASE64_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "DOOR_ACTION_SENT=false",
        "SELF_ACTIVATION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "ACK_SIGNALING_SENT=false",
        "=== END COMELIT ENTRANCE OFFSET8 RTP CODEC SHAPE PCAP FORENSIC ===",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    analysis = select_vip_flow(capture)
    try:
        datagrams = _read_selected_datagrams(args.pcap, client=analysis.client, device=analysis.device)
        result = analyze(datagrams, client=analysis.client, device=analysis.device)
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
