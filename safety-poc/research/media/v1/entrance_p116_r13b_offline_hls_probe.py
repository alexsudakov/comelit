#!/usr/bin/env python3
"""P116 R13B socket-free RTP/H264 to HA-style fMP4 probe.

The input is the P105/P110 length-prefixed RTP datagram file:
uint16 big-endian length followed by one UDP payload, repeated.
Only scalar facts are printed; raw media bytes are written only to a private
temporary directory unless --keep-workdir is used.
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

import av


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
class AccessUnit:
    timestamp: int
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


@dataclass(slots=True)
class RtpPacket:
    seq: int
    timestamp: int
    marker: bool
    payload: bytes


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


def _rtp_payload(packet: bytes) -> RtpPacket | None:
    if packet[0] >> 6 != 2:
        return None
    cc = packet[0] & 0x0F
    x = (packet[0] >> 4) & 1
    pt = packet[1] & 0x7F
    if pt != PT_H264:
        return None
    header_len = 12 + cc * 4
    if len(packet) < header_len:
        return None
    if x:
        if len(packet) < header_len + 4:
            return None
        ext_len = int.from_bytes(packet[header_len + 2 : header_len + 4], "big") * 4
        header_len += 4 + ext_len
    if len(packet) <= header_len:
        return None
    return RtpPacket(
        seq=int.from_bytes(packet[2:4], "big"),
        timestamp=int.from_bytes(packet[4:8], "big"),
        marker=bool(packet[1] & 0x80),
        payload=packet[header_len:],
    )


def _depacketize_h264(rtp_packets: list[RtpPacket]) -> list[AccessUnit]:
    access_units: list[AccessUnit] = []
    current_ts: int | None = None
    current: list[Nal] = []
    fu_parts: list[bytes] = []

    def flush() -> None:
        nonlocal current, current_ts
        if current_ts is not None and current:
            access_units.append(AccessUnit(current_ts, current))
        current = []
        current_ts = None

    def ensure_ts(timestamp: int) -> None:
        nonlocal current_ts
        if current_ts is None:
            current_ts = timestamp
        elif current_ts != timestamp:
            flush()
            current_ts = timestamp

    for pkt in rtp_packets:
        ensure_ts(pkt.timestamp)
        media = pkt.payload
        nal_type = media[0] & 0x1F
        if 1 <= nal_type <= 23:
            current.append(Nal(media))
        elif nal_type == 24:
            pos = 1
            while pos + 2 <= len(media):
                size = int.from_bytes(media[pos : pos + 2], "big")
                pos += 2
                if size <= 0 or pos + size > len(media):
                    break
                current.append(Nal(media[pos : pos + size]))
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
                current.append(Nal(b"".join(fu_parts)))
                fu_parts = []
        if pkt.marker:
            flush()
    flush()
    return access_units


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


def _box_present(blob: bytes, name: bytes) -> bool:
    return name in blob


def _mux_ha_style(
    units: list[AccessUnit],
    output: Path,
    *,
    inject_second_idr: bool,
) -> dict[str, str]:
    first_idr_index = next((idx for idx, unit in enumerate(units) if unit.has_idr), None)
    if first_idr_index is None:
        return {"mux_status": "NO_KEYFRAME"}

    mux_units = units[first_idr_index:]
    if inject_second_idr and len(mux_units) > 1:
        injected_ts = mux_units[0].timestamp + RTP_CLOCK
        injected = AccessUnit(injected_ts, list(mux_units[0].nals))
        mux_units = [mux_units[0], injected, *mux_units[1:]]

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
    try:
        previous_dts: int | None = None
        drops = 0
        first_keyframe_pts_valid = "NO"
        next_video_pts_valid = "NO"
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
            if index == 0 and unit.has_idr and packet.pts is not None and packet.dts is not None:
                first_keyframe_pts_valid = "YES"
            elif index > 0 and packet.pts is not None and packet.dts is not None:
                next_video_pts_valid = "YES"
            packet_rows.append(
                f"{index}:{'K' if unit.has_idr else 'D'}:{packet.dts}:{packet.pts}"
            )
            container.mux(packet)
            previous_dts = dts
    finally:
        container.close()

    blob = output.read_bytes() if output.exists() else b""
    probe = _ffprobe_scalar(output) if output.exists() else {}
    return {
        "mux_status": "PASS" if output.exists() and output.stat().st_size else "FAIL",
        "mp4_bytes": str(output.stat().st_size if output.exists() else 0),
        "mp4_sha256": hashlib.sha256(blob).hexdigest() if blob else "NONE",
        "first_moof": "YES" if _box_present(blob, b"moof") else "NO",
        "first_mdat": "YES" if _box_present(blob, b"mdat") else "NO",
        "mp4_init": "YES" if _box_present(blob, b"moov") else "NO",
        "first_part_created": "YES" if _box_present(blob, b"moof") and _box_present(blob, b"mdat") else "NO",
        "first_part_has_keyframe": "YES" if mux_units[0].has_idr else "NO",
        "first_keyframe_dts_pts_valid": first_keyframe_pts_valid,
        "next_video_packet_dts_pts_valid": next_video_pts_valid,
        "timestamp_validator_drops": str(drops),
        "first_packet_rows": ",".join(packet_rows[:4]),
        "ffprobe_codec": probe.get("codec_name", "UNKNOWN"),
        "ffprobe_profile": probe.get("profile", "UNKNOWN"),
        "ffprobe_time_base": probe.get("time_base", "UNKNOWN"),
        "ffprobe_extradata_size": probe.get("extradata_size", "UNKNOWN"),
    }


def run(path: Path, keep_workdir: bool) -> int:
    packets = _read_length_prefixed_rtp(path)
    rtp = [pkt for raw in packets if (pkt := _rtp_payload(raw)) is not None]
    units = _depacketize_h264(rtp)
    workdir = Path(tempfile.mkdtemp(prefix="p116-r13b-", dir="/tmp"))
    try:
        annexb = workdir / "video.annexb.h264"
        _write_annexb(annexb, units)
        base = _mux_ha_style(units, workdir / "v1.mp4", inject_second_idr=False)
        injected = _mux_ha_style(units, workdir / "v2.mp4", inject_second_idr=True)
        print("=== COMELIT P116 R13B OFFLINE HLS PROBE ===")
        print(f"PYAV_VERSION={av.__version__}")
        print(f"AV_LIBRARY_VERSIONS={av.library_versions}")
        print("DATAGRAM_FRAMING=uint16_be_length_prefixed_rtp_payloads")
        print(f"RTP_DATAGRAMS={len(packets)}")
        print(f"VIDEO_PT99_DATAGRAMS={len(rtp)}")
        print(f"ACCESS_UNITS={len(units)}")
        print(f"SPS_COUNT={sum(unit.has_sps for unit in units)}")
        print(f"PPS_COUNT={sum(unit.has_pps for unit in units)}")
        print(f"IDR_ACCESS_UNITS={sum(unit.has_idr for unit in units)}")
        print(f"FIRST_ACCESS_UNIT_HAS_IDR={units[0].has_idr if units else False}")
        if len(units) > 1:
            print(f"FIRST_TWO_AU_TS_DELTA={units[1].timestamp - units[0].timestamp}")
        for prefix, result in (("V1", base), ("V2", injected)):
            for key in sorted(result):
                if key == "mp4_sha256":
                    continue
                print(f"{prefix}_{key.upper()}={result[key]}")
        print(f"WORKDIR_RETAINED={workdir if keep_workdir else 'false'}")
        print("=== END COMELIT P116 R13B OFFLINE HLS PROBE ===")
    finally:
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    return run(args.artifact, args.keep_workdir)


if __name__ == "__main__":
    sys.exit(main())
