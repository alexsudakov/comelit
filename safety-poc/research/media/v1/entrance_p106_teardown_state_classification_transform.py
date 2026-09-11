#!/usr/bin/env python3
"""P106 teardown-state-aware PseudoTCP notify failure classification.

This overlay composes P105 and changes only the recv_cb notify-failure
decision.  The existing failure marker remains unchanged; the added decision
is evidence-gated by libnice's documented closed-state boundary plus the
candidate's own graceful-stop state.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p105_len24_fallback_diagnostic_transform import (
    DEFAULT_SOURCE,
    transform as add_p105_runtime,
)


_NOTIFY_FAILURE_ANCHOR = """    if (!ok) {
        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET=FAIL "
            "LEN=%u\\n",
            len
        );

        failed = TRUE;

        if (loop)
            g_main_loop_quit(loop);
    }
"""

_NOTIFY_FAILURE_REPLACEMENT = """    if (!ok) {
        gboolean notify_socket_closed =
            pseudo_tcp_socket_is_closed(pseudo_tcp);
        gboolean notify_graceful_started =
            pseudotcp_graceful_stop_started;
        gboolean notify_expected_terminal =
            notify_socket_closed && notify_graceful_started;

        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET=FAIL "
            "LEN=%u\\n",
            len
        );
        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=%s\\n",
            notify_socket_closed ? "true" : "false"
        );
        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=%s\\n",
            notify_graceful_started ? "true" : "false"
        );
        fprintf(
            stderr,
            "PSEUDOTCP_NOTIFY_PACKET_CLASS=%s\\n",
            notify_expected_terminal ? "EXPECTED_TERMINAL_SHUTDOWN" : "FATAL"
        );

        if (!notify_expected_terminal) {
            failed = TRUE;

            if (loop)
                g_main_loop_quit(loop);
        }
    }
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def _strip_p116_from_packaged_binary_provenance(candidate: str) -> str:
    """Keep the P106 packaged-binary provenance source pinned to its shipped build.

    P116 instruments the P80 build path for the next native helper. The P106
    provenance test still describes the already packaged binary, whose SHA pin
    intentionally remains unchanged in this round.
    """
    for line in (
        "#define P116_RTP_TELEMETRY_CADENCE 50u\n",
        "#define P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES 12u\n",
        "#define P116_RTP_PT_WORD_BITS 128u\n",
        "#define P116_RTP_MAX_TRACKED_SSRC 8u\n",
    ):
        candidate = _replace_once(candidate, line, "", "P116 provenance define")

    state_start = candidate.index("\ntypedef struct {\n    guint8 payload_type;")
    state_end = candidate.index("\nstatic guint16\np80_read_le16", state_start)
    candidate = candidate[:state_start] + candidate[state_end:]

    funcs_start = candidate.index("\nstatic guint32\np116_read_be32")
    funcs_end = candidate.index("\nstatic gboolean\np80_rtp_v2_shape", funcs_start)
    candidate = candidate[:funcs_start] + candidate[funcs_end:]

    candidate = _replace_once(
        candidate,
        "    p116_observe_rtp(inner, inner_len, payload_type);\n\n",
        "",
        "P116 provenance observe call",
    )
    candidate = _replace_once(
        candidate,
        "    p116_print_final_rtp_summary();\n\n",
        "",
        "P116 provenance final summary",
    )
    return candidate


def transform(source: str) -> str:
    candidate = add_p105_runtime(source)
    candidate = _strip_p116_from_packaged_binary_provenance(candidate)
    return _replace_once(
        candidate,
        _NOTIFY_FAILURE_ANCHOR,
        _NOTIFY_FAILURE_REPLACEMENT,
        "P106 notify failure classifier",
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P106 TEARDOWN STATE CLASSIFICATION TRANSFORM ===",
            "P106_TEARDOWN_STATE_TRANSFORM=PASS",
            "P106_NOTIFY_CLASSIFIER=EVIDENCE_GATED",
            "P106_BLANKET_SUPPRESSION=false",
            "P106_LEN24_SPECIAL_CASE=false",
            "P106_AUTOMATIC_RETRY=false",
            "P106_SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P106 TEARDOWN STATE CLASSIFICATION TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])

    args.output.write_text(transform(source_path.read_text(encoding="utf-8")), encoding="utf-8")
    print("P106_TEARDOWN_STATE_TRANSFORM=PASS")
    print("P106_NOTIFY_CLASSIFIER=EVIDENCE_GATED")
    print("P106_BLANKET_SUPPRESSION=false")
    print("P106_LEN24_SPECIAL_CASE=false")
    print("P106_AUTOMATIC_RETRY=false")
    print("P106_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
