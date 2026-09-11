#!/usr/bin/env python3
"""Offline SDP/RTP bridge harness for P116.

The script creates a synthetic H264 Annex-B stream with host ffmpeg, packetizes
its SPS/PPS/IDR NAL units into RTP PT99, then feeds ffmpeg over loopback SDP
variants. It prints scalar outcomes only: no payload dumps and no capture data.
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path


VIDEO_PORT = 17899
AUDIO_PORT = 17808
PAYLOAD_TYPE = 99
CLOCK_RATE = 90_000
SSRC = 0x11611699
GREEN_FMTP = "packetization-mode=1"
SPROP_FMTP_TEMPLATE = "packetization-mode=1; profile-level-id={profile}; sprop-parameter-sets={sps},{pps}"
SEND_DURATION_SECONDS = 5.0
FFMPEG_TIMEOUT_SECONDS = 9.0


def _run(args: list[str], *, cwd: Path | None = None, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _generate_annexb(work: Path) -> bytes:
    out = work / "synthetic.h264"
    cmd = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=1",
        "-frames:v",
        "4",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-x264-params",
        "repeat-headers=1:keyint=1:min-keyint=1:scenecut=0",
        "-f",
        "h264",
        str(out),
    ]
    result = _run(cmd, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(f"generate_h264_failed:{result.stderr.strip()[:160]}")
    return out.read_bytes()


def _annexb_nals(data: bytes) -> list[bytes]:
    starts: list[tuple[int, int]] = []
    i = 0
    while i < len(data) - 3:
        if data[i : i + 3] == b"\x00\x00\x01":
            starts.append((i, 3))
            i += 3
        elif data[i : i + 4] == b"\x00\x00\x00\x01":
            starts.append((i, 4))
            i += 4
        else:
            i += 1
    nals: list[bytes] = []
    for index, (start, prefix_len) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(data)
        nal = data[start + prefix_len : end]
        if nal:
            nals.append(nal)
    return nals


def _profile_level_id(sps: bytes) -> str:
    if len(sps) < 4 or sps[0] & 0x1F != 7:
        return "unknown"
    return f"{sps[1]:02x}{sps[2]:02x}{sps[3]:02x}"


def _access_units(nals: list[bytes]) -> list[list[bytes]]:
    units: list[list[bytes]] = []
    current: list[bytes] = []
    current_has_vcl = False
    for nal in nals:
        nal_type = nal[0] & 0x1F
        starts_new = nal_type == 9 or (current_has_vcl and nal_type in {7, 8, 6, 5, 1})
        if starts_new and current:
            units.append(current)
            current = []
            current_has_vcl = False
        current.append(nal)
        if nal_type in {1, 5}:
            current_has_vcl = True
    if current:
        units.append(current)
    return [unit for unit in units if any((nal[0] & 0x1F) in {1, 5} for nal in unit)]


def _rtp_header(sequence: int, timestamp: int, marker: bool) -> bytes:
    return bytes(
        (
            0x80,
            (0x80 if marker else 0x00) | PAYLOAD_TYPE,
            (sequence >> 8) & 0xFF,
            sequence & 0xFF,
            (timestamp >> 24) & 0xFF,
            (timestamp >> 16) & 0xFF,
            (timestamp >> 8) & 0xFF,
            timestamp & 0xFF,
            (SSRC >> 24) & 0xFF,
            (SSRC >> 16) & 0xFF,
            (SSRC >> 8) & 0xFF,
            SSRC & 0xFF,
        )
    )


def _packetize_single(units: list[list[bytes]]) -> list[tuple[int, bool, bytes]]:
    packets: list[tuple[int, bool, bytes]] = []
    for unit_index, unit in enumerate(units):
        timestamp = unit_index * CLOCK_RATE
        for nal_index, nal in enumerate(unit):
            packets.append((timestamp, nal_index == len(unit) - 1, nal))
    return packets


def _packetize_fu_a(units: list[list[bytes]]) -> list[tuple[int, bool, bytes]]:
    packets: list[tuple[int, bool, bytes]] = []
    chunk = 48
    for unit_index, unit in enumerate(units):
        timestamp = unit_index * CLOCK_RATE
        for nal_index, nal in enumerate(unit):
            nal_type = nal[0] & 0x1F
            unit_marker = nal_index == len(unit) - 1
            if nal_type in {1, 5} and len(nal) > chunk:
                nri = nal[0] & 0x60
                fu_indicator = nri | 28
                body = nal[1:]
                offset = 0
                while offset < len(body):
                    piece = body[offset : offset + chunk]
                    start = offset == 0
                    offset += len(piece)
                    end = offset >= len(body)
                    fu_header = (0x80 if start else 0x00) | (0x40 if end else 0x00) | nal_type
                    packets.append((timestamp, unit_marker and end, bytes((fu_indicator, fu_header)) + piece))
            else:
                packets.append((timestamp, unit_marker, nal))
    return packets


def _sdp(path: Path, fmtp: str | None, *, production_shaped: bool = False) -> None:
    lines = [
        "v=0",
        "o=- 0 0 IN IP4 127.0.0.1",
        "s=Comelit P116 synthetic media",
        "c=IN IP4 127.0.0.1",
        "t=0 0",
        f"m=video {VIDEO_PORT} RTP/AVP {PAYLOAD_TYPE}",
        f"a=rtpmap:{PAYLOAD_TYPE} H264/90000",
    ]
    if fmtp is not None:
        lines.append(f"a=fmtp:{PAYLOAD_TYPE} {fmtp}")
    lines.append("a=recvonly")
    if production_shaped:
        lines.extend(
            [
                f"m=audio {AUDIO_PORT} RTP/AVP 8",
                "a=rtpmap:8 PCMA/8000/1",
                "a=recvonly",
            ]
        )
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def _send_packets(
    packets: list[tuple[int, bool, bytes]],
    stop: threading.Event,
    *,
    ready_delay: float = 0.1,
    duration: float = SEND_DURATION_SECONDS,
    silence_after_first_keyframe_ms: int = 0,
) -> None:
    time.sleep(ready_delay)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sequence = 1
        timestamp_base = CLOCK_RATE
        timestamp_span = max((timestamp for timestamp, _, _ in packets), default=0) + CLOCK_RATE
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and not stop.is_set():
            sent_keyframe = False
            for timestamp, marker, payload in packets:
                if stop.is_set():
                    break
                sock.sendto(
                    _rtp_header(sequence, timestamp_base + timestamp, marker) + payload,
                    ("127.0.0.1", VIDEO_PORT),
                )
                sequence = 1 if sequence >= 65535 else sequence + 1
                nal_type = payload[0] & 0x1F
                if marker and nal_type in {5, 28}:
                    sent_keyframe = True
                    if silence_after_first_keyframe_ms > 0:
                        time.sleep(silence_after_first_keyframe_ms / 1000)
                        return
                time.sleep(0.002)
            timestamp_base += timestamp_span
            if not sent_keyframe:
                time.sleep(0.02)
    finally:
        sock.close()


def _loopback_udp_available() -> tuple[bool, str]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as exc:
        return False, f"socket_create:{exc.__class__.__name__}"
    try:
        sock.sendto(b"\x00", ("127.0.0.1", 9))
    except OSError as exc:
        return False, f"socket_send:{exc.__class__.__name__}"
    finally:
        sock.close()
    return True, "ok"


def _probe(path: Path) -> dict[str, str]:
    result = _run(
        [
            "/usr/bin/ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-print_format",
            "json",
            str(path),
        ],
        timeout=10,
    )
    if result.returncode != 0:
        return {"probe": "fail", "probe_error": result.stderr.strip()[:120]}
    data = json.loads(result.stdout)
    stream = data.get("streams", [{}])[0]
    return {
        "probe": "ok",
        "codec": str(stream.get("codec_name")),
        "profile": str(stream.get("profile")),
        "width": str(stream.get("width")),
        "height": str(stream.get("height")),
        "extradata_size": str(stream.get("extradata_size", "0")),
    }


def _run_ffmpeg(cmd: list[str], timeout: float) -> tuple[int, str, str, str]:
    process = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr, "graceful"
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=2)
            return process.returncode if process.returncode is not None else -15, stdout, stderr, "killed"
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return process.returncode if process.returncode is not None else -9, stdout, stderr, "killed"


def _run_variant(
    work: Path,
    name: str,
    fmtp: str | None,
    packets: list[tuple[int, bool, bytes]],
    reassembled_aus: int,
    *,
    production_shaped: bool = False,
    silence_after_first_keyframe_ms: int = 0,
) -> dict[str, str]:
    sdp = work / f"{name}.sdp"
    out = work / f"{name}.mp4"
    _sdp(sdp, fmtp, production_shaped=production_shaped)
    stop = threading.Event()
    sender = threading.Thread(
        target=_send_packets,
        args=(packets, stop),
        kwargs={"silence_after_first_keyframe_ms": silence_after_first_keyframe_ms},
        daemon=True,
    )
    sender.start()
    cmd = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-protocol_whitelist",
        "file,udp,rtp",
        "-analyzeduration",
        "1000000",
        "-probesize",
        "1000000",
        "-t",
        "4",
        "-i",
        str(sdp),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-frames:v",
        "3",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "-f",
        "mp4",
        "-y",
        str(out),
    ]
    start = time.monotonic()
    returncode, _stdout, stderr, terminated = _run_ffmpeg(cmd, timeout=FFMPEG_TIMEOUT_SECONDS)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    stop.set()
    sender.join(timeout=1)
    status = "ok" if returncode == 0 else "fail"
    demux_error = "none"
    stderr_lower = stderr.lower()
    if terminated == "killed":
        demux_error = "process_timeout"
    elif "operation timed out" in stderr_lower or "timeout" in stderr_lower:
        demux_error = "timeout"
    elif "could not find codec parameters" in stderr_lower:
        demux_error = "codec_parameters"
    elif returncode != 0:
        demux_error = "ffmpeg_error"
    scalars = {
        "variant": name,
        "status": status,
        "demux_error": demux_error,
        "elapsed_ms": str(elapsed_ms),
        "ffmpeg_rc": str(returncode),
        "terminated": terminated,
        "reassembled_aus": str(reassembled_aus),
        "sdp_fmtp": "absent" if fmtp is None else fmtp.split(";", 1)[0],
        "avcc_present": "false",
        "extradata_size": "0",
        "codec": "unknown",
        "profile": "unknown",
        "width": "0",
        "height": "0",
        "production_shaped": "true" if production_shaped else "false",
        "video_silence_after_keyframe_ms": str(silence_after_first_keyframe_ms),
    }
    if out.exists() and out.stat().st_size > 0:
        data = out.read_bytes()
        scalars["avcc_present"] = "true" if b"avcC" in data else "false"
        scalars.update(_probe(out))
    return scalars


def _print_scalars(prefix: str, values: dict[str, str]) -> None:
    body = " ".join(f"{key}={values[key]}" for key in sorted(values))
    print(f"{prefix} {body}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="execute loopback ffmpeg proof")
    parser.add_argument(
        "--video-silence-after-keyframe-ms",
        type=int,
        default=1200,
        help="production-shaped SDP variant video silence window after first keyframe",
    )
    args = parser.parse_args()
    if not args.run:
        print(
            "HOST_RUN_COMMAND=python3 safety-poc/research/media/v1/"
            "entrance_p116_sdp_rtp_bridge_harness.py --run"
        )
        print(
            "HOST_RUN_DESCRIPTION=synthetic H264 RTP PT99 RED/GREEN/SPROP loopback "
            "remux proof with scalar output only"
        )
        return 0
    if shutil.which("/usr/bin/ffmpeg") is None or shutil.which("/usr/bin/ffprobe") is None:
        print("HARNESS_STATUS=NOT_RUN reason=ffmpeg_or_ffprobe_missing")
        return 2

    with tempfile.TemporaryDirectory(prefix="p116-rtp-") as tmp:
        work = Path(tmp)
        annexb = _generate_annexb(work)
        nals = _annexb_nals(annexb)
        units = _access_units(nals)
        sps = next((nal for nal in nals if nal[0] & 0x1F == 7), b"")
        pps = next((nal for nal in nals if nal[0] & 0x1F == 8), b"")
        idr_count = sum(1 for nal in nals if nal[0] & 0x1F == 5)
        single = _packetize_single(units)
        fua = _packetize_fu_a(units)
        sprop = SPROP_FMTP_TEMPLATE.format(
            profile=_profile_level_id(sps),
            sps=base64.b64encode(sps).decode("ascii"),
            pps=base64.b64encode(pps).decode("ascii"),
        )
        _print_scalars(
            "HARNESS_INPUT",
            {
                "nal_units": str(len(nals)),
                "access_units": str(len(units)),
                "sps": "present" if sps else "absent",
                "pps": "present" if pps else "absent",
                "idr_count": str(idr_count),
                "single_rtp_packets": str(len(single)),
                "fua_rtp_packets": str(len(fua)),
                "profile_level_id": _profile_level_id(sps),
            },
        )
        udp_ok, udp_reason = _loopback_udp_available()
        if not udp_ok:
            print(f"HARNESS_STATUS=NOT_RUN reason={udp_reason}")
            print(
                "HOST_RUN_COMMAND=python3 safety-poc/research/media/v1/"
                "entrance_p116_sdp_rtp_bridge_harness.py --run"
            )
            print(
                "HOST_RUN_DESCRIPTION=synthetic H264 RTP PT99 RED/GREEN/SPROP loopback "
                "remux proof with scalar output only"
            )
            return 2
        for packetization, packets in (("single", single), ("fua", fua)):
            _print_scalars(
                f"HARNESS_RED_{packetization.upper()}",
                _run_variant(work, f"red-{packetization}", None, packets, len(units)),
            )
            _print_scalars(
                f"HARNESS_GREEN_{packetization.upper()}",
                _run_variant(work, f"green-{packetization}", GREEN_FMTP, packets, len(units)),
            )
            _print_scalars(
                f"HARNESS_SPROP_{packetization.upper()}",
                _run_variant(work, f"sprop-{packetization}", sprop, packets, len(units)),
            )
        _print_scalars(
            "HARNESS_AUDIO_SILENCE_VARIANT",
            _run_variant(
                work,
                "production-audio-silence-fua",
                GREEN_FMTP,
                fua,
                len(units),
                production_shaped=True,
                silence_after_first_keyframe_ms=max(0, args.video_silence_after_keyframe_ms),
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
