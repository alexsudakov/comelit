#!/usr/bin/env python3
"""Comelit late-subscriber RED/GREEN harness (real UDP + real ffmpeg decoders).

Topology (all loopback, no production contact):

    ffmpeg source ---> INPUT relay (counts RTP/NAL statistics, forwards)
                          |
                          v
                    H264RecoveryRtpShim.input_port        (real UDP sockets)
                          |
                    rewritten RTP fan-out
                     /                          \\
                    v                            v
          HA sink relay -> ffmpeg decoder   Mini App sink relay -> ffmpeg decoder
             (listening from t=0)              (binds late, at --join-delay)

The source is configured so the opening IDR access unit is FRAGMENTED into FU-A
packets (nal type 28): only the first fragment carries the FU 'start' bit and only
the last carries the RTP marker bit. That is the shape a real encoder produces.

Prints one JSON line with the required counters. Never prints payload bytes.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

WIDTH, HEIGHT, FPS = 1280, 720, 15
FRAME_BYTES = WIDTH * HEIGHT * 3 // 2


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def nal_info(packet: bytes):
    """Return (nal_type, fu_start, fu_end, marker) for an H264 RTP packet."""
    if len(packet) < 13:
        return None, False, False, False
    marker = bool(packet[1] & 0x80)
    nal_type = packet[12] & 0x1F
    if nal_type == 28 and len(packet) >= 14:
        fu_header = packet[13]
        return fu_header & 0x1F, bool(fu_header & 0x80), bool(fu_header & 0x40), marker
    return nal_type, False, False, marker


class Relay(asyncio.DatagramProtocol):
    """Counts RTP packets and forwards them to a downstream UDP port."""

    def __init__(self, target_port: int, *, observe_nals: bool = False) -> None:
        self.target_port = target_port
        self.observe_nals = observe_nals
        self.out_transport = None
        self.packets = 0
        self.first_sps = None
        self.first_pps = None
        self.first_idr = None
        self.nal_types: dict[int, int] = {}
        self.fu_a_packets = 0
        self.idr_fragments = 0
        self.idr_frag_start = 0
        self.idr_frag_end_marker = 0
        self.raw_frames = None

    async def async_start(self) -> None:
        loop = asyncio.get_running_loop()
        out_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=("127.0.0.1", self.target_port),
        )
        self.out_transport = out_transport

    def stop(self) -> None:
        if self.out_transport is not None:
            self.out_transport.close()
            self.out_transport = None

    def _observe(self, data: bytes) -> None:
        marker = bool(data[1] & 0x80)
        raw_type = data[12] & 0x1F
        self.nal_types[raw_type] = self.nal_types.get(raw_type, 0) + 1
        if raw_type == 28 and len(data) >= 14:
            self.fu_a_packets += 1
            fu_header = data[13]
            original_type = fu_header & 0x1F
            start = bool(fu_header & 0x80)
            end = bool(fu_header & 0x40)
            if original_type == 5:
                if start:
                    self.idr_frag_start += 1
                    if self.first_idr is None:
                        self.first_idr = self.packets
                if end and marker:
                    self.idr_frag_end_marker += 1
            return
        if raw_type == 24:
            # STAP-A: aggregated NAL units, 2-byte length prefixed.
            payload = data[12:]
            pos = 1
            while pos + 2 <= len(payload):
                nal_len = struct.unpack_from("!H", payload, pos)[0]
                pos += 2
                if nal_len == 0 or pos + nal_len > len(payload):
                    break
                aggregated_type = payload[pos] & 0x1F
                if aggregated_type == 7 and self.first_sps is None:
                    self.first_sps = self.packets
                elif aggregated_type == 8 and self.first_pps is None:
                    self.first_pps = self.packets
                elif aggregated_type == 5 and self.first_idr is None:
                    self.first_idr = self.packets
                pos += nal_len
            return
        if raw_type == 7 and self.first_sps is None:
            self.first_sps = self.packets
        elif raw_type == 8 and self.first_pps is None:
            self.first_pps = self.packets
        elif raw_type == 5 and self.first_idr is None:
            self.first_idr = self.packets

    def datagram_received(self, data: bytes, addr) -> None:
        self.packets += 1
        if self.observe_nals and len(data) > 12:
            self._observe(data)
        if self.out_transport is not None:
            try:
                self.out_transport.sendto(data)
            except Exception:
                pass


def write_sdp(path: Path, port: int) -> None:
    path.write_text(
        "v=0\n"
        "o=- 0 0 IN IP4 127.0.0.1\n"
        "s=comelit-late-subscriber-harness\n"
        "c=IN IP4 127.0.0.1\n"
        "t=0 0\n"
        f"m=video {port} RTP/AVP 99\n"
        "a=rtpmap:99 H264/90000\n",
        encoding="utf-8",
    )


def start_decoder(sdp: Path, raw_out: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-protocol_whitelist", "file,udp,rtp", "-i", str(sdp),
         "-f", "rawvideo", "-pix_fmt", "yuv420p", "-y", str(raw_out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def start_source(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
         "-f", "lavfi", "-i", f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}",
         "-t", "8", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
         "-g", "1000", "-keyint_min", "1000", "-sc_threshold", "0",
         "-profile:v", "main", "-b:v", "2000k",
         "-payload_type", "99", "-pkt_size", "1200",
         "-f", "rtp", f"rtp://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def frames(raw_out: Path) -> int:
    try:
        return raw_out.stat().st_size // FRAME_BYTES
    except FileNotFoundError:
        return 0


async def run(module_path: Path, label: str, join_delay: float, total: float) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"pr281-fua-{label}-"))
    source_port = free_port()
    input_port = free_port()
    ha_port = free_port()
    ma_port = free_port()
    ha_dec_port = free_port()
    ma_dec_port = free_port()

    ha_sdp, ma_sdp = tmp / "ha.sdp", tmp / "ma.sdp"
    write_sdp(ha_sdp, ha_dec_port)
    write_sdp(ma_sdp, ma_dec_port)
    ha_raw, ma_raw = tmp / "ha.yuv", tmp / "ma.yuv"

    module = load_module(module_path, f"h264_under_test_{label}")
    loop = asyncio.get_running_loop()

    supports_inactive = "inactive_output_ports" in inspect.signature(
        module.H264RecoveryRtpShim.__init__
    ).parameters
    kwargs = {
        "input_port": input_port,
        "output_port": ha_port,
        "output_ports": (ha_port, ma_port),
        "host": "127.0.0.1",
    }
    if supports_inactive:
        kwargs["inactive_output_ports"] = (ma_port,)
    shim = module.H264RecoveryRtpShim(**kwargs)
    await shim.async_start()

    input_relay = Relay(input_port, observe_nals=True)
    in_transport, _ = await loop.create_datagram_endpoint(
        lambda: input_relay, local_addr=("127.0.0.1", source_port)
    )
    await input_relay.async_start()

    ha_relay = Relay(ha_dec_port, observe_nals=True)
    ha_transport, _ = await loop.create_datagram_endpoint(
        lambda: ha_relay, local_addr=("127.0.0.1", ha_port)
    )
    await ha_relay.async_start()
    ha_decoder = start_decoder(ha_sdp, ha_raw)

    source = start_source(source_port)
    await asyncio.sleep(join_delay)

    ma_relay = Relay(ma_dec_port, observe_nals=True)
    ma_transport, _ = await loop.create_datagram_endpoint(
        lambda: ma_relay, local_addr=("127.0.0.1", ma_port)
    )
    await ma_relay.async_start()
    ma_decoder = start_decoder(ma_sdp, ma_raw)
    await asyncio.sleep(0.3)

    activation = getattr(shim, "async_activate_output_port", None)
    activation_used = callable(activation)
    if activation_used:
        await activation(ma_port)

    await asyncio.sleep(max(0.5, total - join_delay))

    try:
        source.terminate()
        source.wait(timeout=10)
    except Exception:
        source.kill()
    await shim.async_stop()
    for relay, transport in ((input_relay, in_transport), (ha_relay, ha_transport), (ma_relay, ma_transport)):
        relay.stop()
        transport.close()
    await asyncio.sleep(1.5)
    for proc in (ha_decoder, ma_decoder):
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    ha_frames = frames(ha_raw)
    ma_frames = frames(ma_raw)
    result = {
        "label": label,
        "module": str(module_path),
        "join_delay_seconds": join_delay,
        "SINK_ACTIVATION_API_USED": activation_used,
        # input side (proves the harness really feeds FU-A fragmented H264)
        "INPUT_RTP_PACKETS": input_relay.packets,
        "INPUT_FU_A_PACKETS": input_relay.fu_a_packets,
        "INPUT_SINGLE_NAL_PACKETS": input_relay.packets - input_relay.fu_a_packets,
        "INPUT_NAL_TYPE_HISTOGRAM": {str(k): v for k, v in sorted(input_relay.nal_types.items())},
        "INPUT_IDR_FU_A_START_FRAGMENTS": input_relay.idr_frag_start,
        "INPUT_IDR_FU_A_END_MARKER_FRAGMENTS": input_relay.idr_frag_end_marker,
        # early HA sink
        "EARLY_HA_SINK_PACKETS": ha_relay.packets,
        "EARLY_HA_SINK_FIRST_SPS_PACKET": ha_relay.first_sps,
        "EARLY_HA_SINK_FIRST_PPS_PACKET": ha_relay.first_pps,
        "EARLY_HA_SINK_FIRST_IDR_PACKET": ha_relay.first_idr,
        "EARLY_HA_SINK_DECODED_FRAMES": ha_frames,
        "EARLY_HA_SINK_DECODABLE": ha_frames > 0,
        # late Mini App sink
        "LATE_MINIAPP_SINK_PACKETS": ma_relay.packets,
        "LATE_MINIAPP_SINK_FIRST_SPS_AFTER_SUBSCRIBE": ma_relay.first_sps,
        "LATE_MINIAPP_SINK_FIRST_PPS_AFTER_SUBSCRIBE": ma_relay.first_pps,
        "LATE_MINIAPP_SINK_FIRST_IDR_AFTER_SUBSCRIBE": ma_relay.first_idr,
        "LATE_MINIAPP_SINK_DECODED_FRAMES": ma_frames,
        "LATE_MINIAPP_SINK_DECODABLE": ma_frames > 0,
        "MINIAPP_NAL_TYPE_HISTOGRAM": {str(k): v for k, v in sorted(ma_relay.nal_types.items())},
        "HA_NAL_TYPE_HISTOGRAM": {str(k): v for k, v in sorted(ha_relay.nal_types.items())},
    }
    diagnostics = getattr(shim, "diagnostics", None)
    if callable(diagnostics):
        diag = diagnostics()
        for name in ("input_packets", "output_packets", "cached_bootstrap_bytes", "idr_count"):
            if hasattr(diag, name):
                result["SHIM_" + name.upper()] = getattr(diag, name)
        for name in ("sink_bootstrap_packets", "output_sink_packets", "output_sink_active"):
            if hasattr(diag, name):
                result["SHIM_" + name.upper()] = {
                    str(k): v for k, v in (getattr(diag, name) or {}).items()
                }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--join-delay", type=float, default=2.5)
    parser.add_argument("--total", type=float, default=8.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = asyncio.run(run(Path(args.module), args.label, args.join_delay, args.total))
    line = json.dumps(result, sort_keys=True)
    print(line)
    if args.out:
        Path(args.out).write_text(line + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
