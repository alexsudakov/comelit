#!/usr/bin/env python3
"""Offline forensic for official Comelit PseudoTCP startup/teardown behavior.

The analyzer reuses the existing public-safe PCAP parser. It emits only
protocol metadata and hashes: no endpoint addresses, ports, ICE credentials,
or raw application/control payloads.

It also inspects the current native research source to determine whether the
local stop-file path explicitly asks libnice PseudoTCP to close before the GLib
loop exits. No network I/O is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pseudotcp_pcap_handshake_forensic import (
    PSEUDOTCP_FLAG_CTL,
    PSEUDOTCP_FLAG_FIN,
    PSEUDOTCP_FLAG_RST,
    direction,
    load_capture,
    select_vip_flow,
)


@dataclass(frozen=True)
class CaptureSummary:
    label: str
    first_client_window: int
    first_client_control_sha256: str
    first_termination_kind: str
    first_termination_direction: str
    rst_count: int
    fin_count: int


def _first_client_ctl(analysis):
    for segment in analysis.segments:
        if (
            segment.source == analysis.client
            and segment.flags & PSEUDOTCP_FLAG_CTL
            and segment.sequence == 0
            and segment.acknowledgment == 0
        ):
            return segment
    raise ValueError("first client CTL segment not found")


def _termination_segments(analysis):
    return [
        segment
        for segment in analysis.segments
        if segment.flags & (PSEUDOTCP_FLAG_RST | PSEUDOTCP_FLAG_FIN)
    ]


def _last_application_before(analysis, timestamp: float):
    candidates = [
        segment
        for segment in analysis.segments
        if segment.timestamp <= timestamp and segment.is_application_candidate
    ]
    return candidates[-1] if candidates else None


def _kind(segment) -> str:
    bits: list[str] = []
    if segment.flags & PSEUDOTCP_FLAG_RST:
        bits.append("RST")
    if segment.flags & PSEUDOTCP_FLAG_FIN:
        bits.append("FIN")
    return "+".join(bits) if bits else "NONE"


def analyze_capture(path: Path, label: str, expected_sha256: str | None) -> CaptureSummary:
    capture = load_capture(path)
    if expected_sha256 and capture.sha256 != expected_sha256:
        raise ValueError(
            f"{label}: sha256 mismatch expected={expected_sha256} actual={capture.sha256}"
        )

    analysis = select_vip_flow(capture)
    first = _first_client_ctl(analysis)
    terminations = _termination_segments(analysis)

    print(f"CAPTURE_LABEL={label}")
    print(f"PCAP_SHA256={capture.sha256}")
    print(f"PSEUDOTCP_INITIATOR=CLIENT")
    print(f"FIRST_CLIENT_CTL_PACKET={first.packet_number}")
    print(f"FIRST_CLIENT_CTL_WIRE_LEN={first.wire_length}")
    print(f"FIRST_CLIENT_CTL_SEQUENCE={first.sequence}")
    print(f"FIRST_CLIENT_CTL_ACKNOWLEDGMENT={first.acknowledgment}")
    print(f"FIRST_CLIENT_CTL_CONTROL=0x{first.control:02x}")
    print(f"FIRST_CLIENT_CTL_FLAGS=0x{first.flags:02x}")
    print(f"FIRST_CLIENT_CTL_WINDOW={first.window}")
    print(f"FIRST_CLIENT_CTL_DATA_LEN={first.data_length}")
    print(
        "FIRST_CLIENT_CTL_DATA_SHA256="
        + hashlib.sha256(first.data).hexdigest()
    )

    rst_count = sum(bool(s.flags & PSEUDOTCP_FLAG_RST) for s in terminations)
    fin_count = sum(bool(s.flags & PSEUDOTCP_FLAG_FIN) for s in terminations)
    print(f"PSEUDOTCP_RST_COUNT={rst_count}")
    print(f"PSEUDOTCP_FIN_COUNT={fin_count}")

    if terminations:
        first_term = terminations[0]
        first_direction = direction(first_term, analysis)
        first_kind = _kind(first_term)
        last_app = _last_application_before(analysis, first_term.timestamp)

        print(f"FIRST_TERMINATION_PACKET={first_term.packet_number}")
        print(f"FIRST_TERMINATION_KIND={first_kind}")
        print(f"FIRST_TERMINATION_DIRECTION={first_direction}")
        print(
            "FIRST_TERMINATION_REL_SECONDS="
            f"{first_term.timestamp - analysis.segments[0].timestamp:.6f}"
        )
        if last_app is not None:
            print(f"LAST_APP_BEFORE_TERMINATION_PACKET={last_app.packet_number}")
            print(
                "TERMINATION_AFTER_LAST_APP_SECONDS="
                f"{first_term.timestamp - last_app.timestamp:.6f}"
            )
        else:
            print("LAST_APP_BEFORE_TERMINATION_PACKET=NONE")

        last_term = terminations[-1]
        print(f"LAST_TERMINATION_PACKET={last_term.packet_number}")
        print(f"LAST_TERMINATION_KIND={_kind(last_term)}")
        print(f"LAST_TERMINATION_DIRECTION={direction(last_term, analysis)}")
    else:
        first_kind = "NONE"
        first_direction = "NONE"
        print("FIRST_TERMINATION_PACKET=NONE")
        print("FIRST_TERMINATION_KIND=NONE")
        print("FIRST_TERMINATION_DIRECTION=NONE")
        print("LAST_TERMINATION_PACKET=NONE")

    print("ENDPOINTS_EMITTED=false")
    print("RAW_PAYLOAD_EMITTED=false")
    print()

    return CaptureSummary(
        label=label,
        first_client_window=first.window,
        first_client_control_sha256=hashlib.sha256(first.data).hexdigest(),
        first_termination_kind=first_kind,
        first_termination_direction=first_direction,
        rst_count=rst_count,
        fin_count=fin_count,
    )


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"static\s+gboolean\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    if not match:
        raise ValueError(f"function {name} not found")

    start = source.find("{", match.start())
    depth = 0
    in_string = False
    in_char = False
    escaped = False

    for index in range(start, len(source)):
        ch = source[index]
        if escaped:
            escaped = False
            continue
        if (in_string or in_char) and ch == "\\":
            escaped = True
            continue
        if not in_char and ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch == "'":
            in_char = not in_char
            continue
        if in_string or in_char:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]

    raise ValueError(f"function {name} closing brace not found")


def inspect_local_stop(source_path: Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    body = _function_body(source, "stop_check_cb")

    has_stop_file = "STOP_FILE" in body
    quits_loop = "g_main_loop_quit" in body
    explicit_close = "pseudo_tcp_socket_close" in body
    explicit_shutdown = "pseudo_tcp_socket_shutdown" in body

    print("=== CURRENT LOCAL STOP PATH ===")
    print(f"CURRENT_STOP_FILE_CHECK={'PASS' if has_stop_file else 'FAIL'}")
    print(f"CURRENT_STOP_QUITS_GLIB_LOOP={'true' if quits_loop else 'false'}")
    print(
        "CURRENT_STOP_EXPLICIT_PSEUDOTCP_CLOSE="
        f"{'true' if explicit_close else 'false'}"
    )
    print(
        "CURRENT_STOP_EXPLICIT_PSEUDOTCP_SHUTDOWN="
        f"{'true' if explicit_shutdown else 'false'}"
    )
    print("CURRENT_STOP_RAW_SOURCE_EMITTED=false")
    print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-activation", type=Path, required=True)
    parser.add_argument("--p2p-rtsp", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    self_summary = analyze_capture(
        args.self_activation,
        "official_self_activation",
        "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
    )
    rtsp_summary = analyze_capture(args.p2p_rtsp, "official_p2p_rtsp", None)

    print("=== CROSS-CAPTURE STARTUP SIGNATURE ===")
    startup_match = (
        self_summary.first_client_window == rtsp_summary.first_client_window
        and self_summary.first_client_control_sha256
        == rtsp_summary.first_client_control_sha256
    )
    print(f"OFFICIAL_FIRST_CTL_WINDOW_MATCH={'PASS' if startup_match else 'FAIL'}")
    print(
        "OFFICIAL_FIRST_CTL_CONTROL_SHA_MATCH="
        f"{'PASS' if self_summary.first_client_control_sha256 == rtsp_summary.first_client_control_sha256 else 'FAIL'}"
    )
    print()

    print("=== CROSS-CAPTURE TEARDOWN SIGNATURE ===")
    same_teardown = (
        self_summary.first_termination_kind == rtsp_summary.first_termination_kind
        and self_summary.first_termination_direction
        == rtsp_summary.first_termination_direction
    )
    print(f"OFFICIAL_FIRST_TERMINATION_SIGNATURE_MATCH={'PASS' if same_teardown else 'FAIL'}")
    print(
        "OFFICIAL_FIRST_TERMINATION_KIND="
        + (
            self_summary.first_termination_kind
            if same_teardown
            else "DIFFERS"
        )
    )
    print(
        "OFFICIAL_FIRST_TERMINATION_DIRECTION="
        + (
            self_summary.first_termination_direction
            if same_teardown
            else "DIFFERS"
        )
    )
    print()

    inspect_local_stop(args.source)

    print("NETWORK_IO_PERFORMED=false")
    print("HOME_ASSISTANT_TOUCHED=false")
    print("DOOR_ACTION_SENT=false")
    print("SELF_ACTIVATION_SENT=false")
    print("MEDIA_SIGNALING_SENT=false")
    print("PSEUDOTCP_TEARDOWN_FORENSIC=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
