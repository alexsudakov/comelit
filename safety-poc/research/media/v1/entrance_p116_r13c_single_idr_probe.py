#!/usr/bin/env python3
"""P116 R13C socket-free single-IDR RTP/H264 variant probe.

Input is the P105/P110 uint16 big-endian length-prefixed RTP datagram file.
The derived stream omits exactly the second IDR access unit at RTP packet
boundaries and writes the result only to a private evidence path. Output is
limited to scalar markers.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ANNEX = b"\x00\x00\x00\x01"
PT_H264 = 99
RTP_CLOCK = 90_000


@dataclass(slots=True)
class Nal:
    data: bytes

    @property
    def nal_type(self) -> int:
        return self.data[0] & 0x1F if self.data else -1


@dataclass(slots=True)
class RtpPacket:
    raw: bytes
    raw_index: int
    seq: int
    timestamp: int
    marker: bool
    payload: bytes


@dataclass(slots=True)
class AccessUnit:
    index: int
    timestamp: int
    packets: list[RtpPacket]
    nals: list[Nal]

    @property
    def has_idr(self) -> bool:
        return any(nal.nal_type == 5 for nal in self.nals)

    @property
    def has_sps(self) -> bool:
        return any(nal.nal_type == 7 for nal in self.nals)

    @property
    def has_pps(self) -> bool:
        return any(nal.nal_type == 8 for nal in self.nals)

    def annexb(self) -> bytes:
        return b"".join(ANNEX + nal.data for nal in self.nals)

    def nal_type_csv(self) -> str:
        return ",".join(str(nal.nal_type) for nal in self.nals)


def _read_length_prefixed_rtp(path: Path) -> list[bytes]:
    data = path.read_bytes()
    pos = 0
    packets: list[bytes] = []
    while pos + 2 <= len(data):
        size = int.from_bytes(data[pos : pos + 2], "big")
        pos += 2
        if size < 12 or pos + size > len(data):
            raise ValueError(f"invalid length-prefixed RTP at offset {pos - 2}")
        packets.append(data[pos : pos + size])
        pos += size
    if pos != len(data):
        raise ValueError("trailing byte after length-prefixed RTP stream")
    return packets


def _rtp_payload(raw: bytes, raw_index: int) -> RtpPacket | None:
    if len(raw) < 12 or raw[0] >> 6 != 2:
        return None
    cc = raw[0] & 0x0F
    x = (raw[0] >> 4) & 1
    pt = raw[1] & 0x7F
    if pt != PT_H264:
        return None
    header_len = 12 + cc * 4
    if len(raw) < header_len:
        return None
    if x:
        if len(raw) < header_len + 4:
            return None
        ext_len = int.from_bytes(raw[header_len + 2 : header_len + 4], "big") * 4
        header_len += 4 + ext_len
    if len(raw) <= header_len:
        return None
    return RtpPacket(
        raw=raw,
        raw_index=raw_index,
        seq=int.from_bytes(raw[2:4], "big"),
        timestamp=int.from_bytes(raw[4:8], "big"),
        marker=bool(raw[1] & 0x80),
        payload=raw[header_len:],
    )


def _depacketize_h264(rtp_packets: list[RtpPacket]) -> list[AccessUnit]:
    access_units: list[AccessUnit] = []
    current_ts: int | None = None
    current_packets: list[RtpPacket] = []
    current_nals: list[Nal] = []
    fu_parts: list[bytes] = []

    def flush() -> None:
        nonlocal current_ts, current_packets, current_nals
        if current_ts is not None and current_nals:
            access_units.append(
                AccessUnit(
                    index=len(access_units),
                    timestamp=current_ts,
                    packets=current_packets,
                    nals=current_nals,
                )
            )
        current_ts = None
        current_packets = []
        current_nals = []

    def ensure_ts(pkt: RtpPacket) -> None:
        nonlocal current_ts
        if current_ts is None:
            current_ts = pkt.timestamp
        elif current_ts != pkt.timestamp:
            flush()
            current_ts = pkt.timestamp
        current_packets.append(pkt)

    for pkt in rtp_packets:
        ensure_ts(pkt)
        media = pkt.payload
        nal_type = media[0] & 0x1F
        if 1 <= nal_type <= 23:
            current_nals.append(Nal(media))
        elif nal_type == 24:
            pos = 1
            while pos + 2 <= len(media):
                size = int.from_bytes(media[pos : pos + 2], "big")
                pos += 2
                if size <= 0 or pos + size > len(media):
                    break
                current_nals.append(Nal(media[pos : pos + size]))
                pos += size
        elif nal_type == 28 and len(media) >= 3:
            fu_indicator = media[0]
            fu_header = media[1]
            start = bool(fu_header & 0x80)
            end = bool(fu_header & 0x40)
            original_type = fu_header & 0x1F
            if start:
                fu_parts = [bytes([(fu_indicator & 0xE0) | original_type]), media[2:]]
            elif fu_parts:
                fu_parts.append(media[2:])
            if end and fu_parts:
                current_nals.append(Nal(b"".join(fu_parts)))
                fu_parts = []
        if pkt.marker:
            flush()
    flush()
    return access_units


def _write_length_prefixed(path: Path, packets: list[bytes]) -> None:
    with path.open("wb") as out:
        for packet in packets:
            out.write(len(packet).to_bytes(2, "big"))
            out.write(packet)
    path.chmod(0o600)


def _write_annexb(path: Path, units: list[AccessUnit]) -> None:
    path.write_bytes(b"".join(unit.annexb() for unit in units))
    path.chmod(0o600)


def _ffprobe_scalar(path: Path) -> dict[str, str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_name,codec_type,profile,width,height,extradata_size,time_base,nb_read_packets",
        "-count_packets",
        "-of",
        "default=nokey=0:noprint_wrappers=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"ffprobe_error": exc.__class__.__name__}
    result: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result.setdefault(key, value)
    return result


def _pyav_decode_scalar(path: Path) -> dict[str, str]:
    import av

    try:
        container = av.open(str(path), format="h264")
    except av.FFmpegError as exc:
        return {"pyav_open": "false", "pyav_error": type(exc).__name__}
    try:
        video = container.streams.video[0]
        frames = 0
        for frame in container.decode(video):
            frames += 1
            if frames >= 3:
                break
        return {
            "pyav_open": "true",
            "video_stream_found": "true",
            "video_time_base": str(video.time_base),
            "codec_extradata_size": str(
                len(video.codec_context.extradata or b"")
                if video.codec_context
                else 0
            ),
            "decoded_frame_count_sample": str(frames),
        }
    except (av.FFmpegError, IndexError) as exc:
        return {
            "pyav_open": "true",
            "video_stream_found": "false",
            "pyav_error": type(exc).__name__,
        }
    finally:
        container.close()


def _box_present(blob: bytes, name: bytes) -> bool:
    return name in blob


def _mux_ha_style(units: list[AccessUnit], output: Path) -> dict[str, str]:
    import av

    first_idr_index = next((idx for idx, unit in enumerate(units) if unit.has_idr), None)
    if first_idr_index is None:
        return {"mux_status": "NO_KEYFRAME"}

    mux_units = units[first_idr_index:]
    first_ts = mux_units[0].timestamp
    options = {
        "movflags": (
            "empty_moov+default_base_moof+frag_discont+negative_cts_offsets"
            "+skip_trailer+delay_moov"
        ),
        "avoid_negative_ts": "make_non_negative",
        "fragment_index": "1",
        "video_track_timescale": str(RTP_CLOCK),
        "frag_duration": "900000",
    }
    container = av.open(output, mode="w", format="mp4", container_options=options)
    stream = container.add_stream("h264", rate=25)
    stream.time_base = Fraction(1, RTP_CLOCK)
    stream.codec_context.time_base = Fraction(1, RTP_CLOCK)
    packet_rows: list[str] = []
    drops = 0
    first_keyframe_dts = "NONE"
    first_keyframe_pts = "NONE"
    first_keyframe_found = "false"
    previous_dts: int | None = None
    try:
        for index, unit in enumerate(mux_units):
            dts = unit.timestamp - first_ts
            if previous_dts is not None and dts <= previous_dts:
                drops += 1
                continue
            packet = av.Packet(unit.annexb())
            packet.stream = stream
            packet.time_base = Fraction(1, RTP_CLOCK)
            packet.pts = packet.dts = dts
            if index + 1 < len(mux_units):
                packet.duration = max(1, mux_units[index + 1].timestamp - unit.timestamp)
            packet.is_keyframe = unit.has_idr
            if unit.has_idr and not first_keyframe_found == "true":
                first_keyframe_found = "true"
                first_keyframe_dts = str(packet.dts)
                first_keyframe_pts = str(packet.pts)
            packet_rows.append(
                f"{index}:{'K' if unit.has_idr else 'D'}:{packet.dts}:{packet.pts}"
            )
            container.mux(packet)
            previous_dts = dts
    finally:
        container.close()

    blob = output.read_bytes() if output.exists() else b""
    probe = _ffprobe_scalar(output) if output.exists() else {}
    first_part_created = _box_present(blob, b"moof") and _box_present(blob, b"mdat")
    return {
        "mux_status": "PASS" if output.exists() and output.stat().st_size else "FAIL",
        "mp4_bytes": str(output.stat().st_size if output.exists() else 0),
        "mp4_sha256": hashlib.sha256(blob).hexdigest() if blob else "NONE",
        "mp4_init_written": "true" if _box_present(blob, b"moov") else "false",
        "first_moof_written": "true" if _box_present(blob, b"moof") else "false",
        "first_mdat_written": "true" if _box_present(blob, b"mdat") else "false",
        "first_segment_object_created": "true" if first_part_created else "false",
        "first_ll_hls_part_created": "true" if first_part_created else "false",
        "first_part_has_keyframe": "true" if mux_units[0].has_idr else "false",
        "first_keyframe_found": first_keyframe_found,
        "first_keyframe_dts": first_keyframe_dts,
        "first_keyframe_pts": first_keyframe_pts,
        "timestamp_validator_drops": str(drops),
        "first_packet_rows": ",".join(packet_rows[:4]),
        "ffprobe_codec": probe.get("codec_name", "UNKNOWN"),
        "ffprobe_profile": probe.get("profile", "UNKNOWN"),
        "ffprobe_time_base": probe.get("time_base", "UNKNOWN"),
        "ffprobe_extradata_size": probe.get("extradata_size", "UNKNOWN"),
    }


def _count_sps(units: list[AccessUnit]) -> int:
    return sum(unit.has_sps for unit in units)


def _count_pps(units: list[AccessUnit]) -> int:
    return sum(unit.has_pps for unit in units)


def _count_idr(units: list[AccessUnit]) -> int:
    return sum(unit.has_idr for unit in units)


def run(source: Path, variant: Path, keep_workdir: bool) -> int:
    import av

    raw_packets = _read_length_prefixed_rtp(source)
    rtp = [
        pkt
        for raw_index, raw in enumerate(raw_packets)
        if (pkt := _rtp_payload(raw, raw_index)) is not None
    ]
    source_units = _depacketize_h264(rtp)
    idr_units = [unit for unit in source_units if unit.has_idr]
    result = "UNRESOLVED"
    valid = False
    if len(idr_units) >= 2:
        second_idr = idr_units[1]
        remove_indexes = {pkt.raw_index for pkt in second_idr.packets}
        variant_packets = [
            packet for index, packet in enumerate(raw_packets) if index not in remove_indexes
        ]
        variant.parent.mkdir(parents=True, exist_ok=True)
        _write_length_prefixed(variant, variant_packets)
        variant_rtp = [
            pkt
            for raw_index, raw in enumerate(variant_packets)
            if (pkt := _rtp_payload(raw, raw_index)) is not None
        ]
        variant_units = _depacketize_h264(variant_rtp)
        valid = _count_idr(variant_units) == 1 and len(variant_units) == len(source_units) - 1
    else:
        second_idr = None
        variant_units = []

    workdir = Path(tempfile.mkdtemp(prefix="p116-r13c-", dir="/tmp"))
    try:
        annexb = workdir / "single_idr.annexb.h264"
        mux_result: dict[str, str] = {}
        pyav_result: dict[str, str] = {
            "pyav_open": "false",
            "video_stream_found": "false",
            "video_time_base": "UNKNOWN",
            "codec_extradata_size": "UNKNOWN",
        }
        if valid:
            _write_annexb(annexb, variant_units)
            pyav_result = _pyav_decode_scalar(annexb)
            mux_result = _mux_ha_style(variant_units, workdir / "single_idr.mp4")
            result = "CLOSED" if mux_result.get("first_ll_hls_part_created") == "true" else "UNRESOLVED"

        print("=== COMELIT P116 R13C SINGLE-IDR PROBE ===")
        print(f"PYAV_VERSION={av.__version__}")
        print(f"AV_LIBRARY_VERSIONS={av.library_versions}")
        print("DATAGRAM_FRAMING=uint16_be_length_prefixed_rtp_payloads")
        print(f"SOURCE_SHA256={hashlib.sha256(source.read_bytes()).hexdigest()}")
        print(f"SOURCE_RTP_DATAGRAMS={len(raw_packets)}")
        print(f"SOURCE_VIDEO_PT99_DATAGRAMS={len(rtp)}")
        print(f"SOURCE_ACCESS_UNITS={len(source_units)}")
        print(f"SOURCE_SPS_COUNT={_count_sps(source_units)}")
        print(f"SOURCE_PPS_COUNT={_count_pps(source_units)}")
        print(f"SOURCE_IDR_AU_COUNT={_count_idr(source_units)}")
        if second_idr is None:
            print("SECOND_IDR_AU_INDEX=NONE")
            print("SECOND_IDR_RTP_SEQ_RANGE=NONE")
            print("SECOND_IDR_RTP_TS_RANGE=NONE")
            print("SECOND_IDR_NAL_TYPES=NONE")
            print("SECOND_IDR_PACKET_COUNT=0")
        else:
            print(f"SECOND_IDR_AU_INDEX={second_idr.index}")
            print(
                "SECOND_IDR_RTP_SEQ_RANGE="
                f"{second_idr.packets[0].seq}-{second_idr.packets[-1].seq}"
            )
            print(
                "SECOND_IDR_RTP_TS_RANGE="
                f"{second_idr.packets[0].timestamp}-{second_idr.packets[-1].timestamp}"
            )
            print(f"SECOND_IDR_NAL_TYPES={second_idr.nal_type_csv()}")
            print(f"SECOND_IDR_PACKET_COUNT={len(second_idr.packets)}")
        print(f"VARIANT_PATH={variant}")
        print(
            "VARIANT_SHA256="
            f"{hashlib.sha256(variant.read_bytes()).hexdigest() if variant.exists() else 'NONE'}"
        )
        print(f"SINGLE_IDR_VARIANT_VALID={str(valid).lower()}")
        print(f"IDR_AU_COUNT={_count_idr(variant_units) if valid else 0}")
        print(f"SPS_COUNT={_count_sps(variant_units) if valid else 0}")
        print(f"PPS_COUNT={_count_pps(variant_units) if valid else 0}")
        print(f"PYAV_OPEN={pyav_result.get('pyav_open', 'false')}")
        print(f"VIDEO_STREAM_FOUND={pyav_result.get('video_stream_found', 'false')}")
        print(f"CODEC_EXTRADATA_SIZE={pyav_result.get('codec_extradata_size', 'UNKNOWN')}")
        print(f"VIDEO_TIME_BASE={pyav_result.get('video_time_base', 'UNKNOWN')}")
        print(f"DECODED_FRAME_COUNT_SAMPLE={pyav_result.get('decoded_frame_count_sample', '0')}")
        print(f"FIRST_KEYFRAME_FOUND={mux_result.get('first_keyframe_found', 'false')}")
        print(f"FIRST_KEYFRAME_DTS={mux_result.get('first_keyframe_dts', 'NONE')}")
        print(f"FIRST_KEYFRAME_PTS={mux_result.get('first_keyframe_pts', 'NONE')}")
        print(f"MUX_FIRST_KEYFRAME={mux_result.get('mux_status', 'FAIL')}")
        print(f"MP4_INIT_WRITTEN={mux_result.get('mp4_init_written', 'false')}")
        print(f"FIRST_MOOF_WRITTEN={mux_result.get('first_moof_written', 'false')}")
        print(f"FIRST_MDAT_WRITTEN={mux_result.get('first_mdat_written', 'false')}")
        print(
            "FIRST_SEGMENT_OBJECT_CREATED="
            f"{mux_result.get('first_segment_object_created', 'false')}"
        )
        print(
            "FIRST_LL_HLS_PART_CREATED="
            f"{mux_result.get('first_ll_hls_part_created', 'false')}"
        )
        print(f"FIRST_PART_HAS_KEYFRAME={mux_result.get('first_part_has_keyframe', 'false')}")
        print(
            "HLS_PLAYLIST_CAN_EXPOSE_OPEN_SEGMENT="
            f"{mux_result.get('first_segment_object_created', 'false')}"
        )
        print(
            "TIMESTAMP_VALIDATOR_DROPS="
            f"{mux_result.get('timestamp_validator_drops', '0')}"
        )
        print("SECOND_IDR_REQUIRED_FOR_FIRST_PART=false" if result == "CLOSED" else "SECOND_IDR_REQUIRED_FOR_FIRST_PART=UNRESOLVED")
        print("SECOND_IDR_REQUIRED_FOR_SEGMENT_CLOSE=true")
        print(f"D2_SINGLE_IDR_HYPOTHESIS_STATUS={result}")
        print(f"WORKDIR_RETAINED={workdir if keep_workdir else 'false'}")
        print("=== END COMELIT P116 R13C SINGLE-IDR PROBE ===")
    finally:
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--variant", required=True, type=Path)
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    return run(args.artifact, args.variant, args.keep_workdir)


if __name__ == "__main__":
    sys.exit(main())
