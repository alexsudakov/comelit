#!/usr/bin/env python3
"""P116/R29I pre-open idle lifetime hardening for the R29C live candidate.

R29H bounded the post-OPEN lifetime but intentionally kept the inherited
entrance signaling timeout fail-closed before OPEN.  Live evidence then showed
that the inherited one-shot timeout can fire while the registered research
listener is merely waiting for a human ring, before any CALL_INIT exists.

R29I narrows that timeout ownership: only the idle state
REGISTERED_READY + v4_registered + no call transaction + no OPEN treats the
inherited entrance-signaling timeout as stale and removes that timer source.
The runner's bounded ring watchdog remains the owner of the human wait window.
All non-idle/pre-OPEN failures keep the R29H fail-closed path.

This transform is research-only.  It performs no network I/O and never runs a
candidate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


DEFAULT_SOURCE = r29c.DEFAULT_SOURCE

_TIMEOUT_OLD = """    if (r29h_defer_inherited_main_loop_quit(
            \"ENTRANCE_SIGNALING_TIMEOUT\",
            (guint)entrance_signal_stage))
        return G_SOURCE_REMOVE;
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}"""

_TIMEOUT_NEW = """    /* R29I: the inherited signaling timer is not the owner of the
     * human waiting-for-ring interval.  Suppress it only while this process is
     * still the registered idle listener and no call transaction has begun.
     * A lost registration or any begun call falls through to the existing
     * R29H fail-closed behavior. */
    if (r29_listener_registered_ready &&
        v4_registered &&
        r29_attached_media_state == R29_LISTENER_REGISTERED_READY &&
        !r29_call_transaction_created &&
        !r29_call_transaction_active &&
        !r29c_registered_ctpp_mediareq26_open_sent) {
        printf(\"R29I_WAITING_FOR_RING_TIMEOUT_SUPPRESSED=true\\n\");
        printf(\"R29I_WAITING_FOR_RING_BOUNDED_BY_RUNNER=true\\n\");
        fflush(stdout);
        return G_SOURCE_REMOVE;
    }
    if (r29h_defer_inherited_main_loop_quit(
            \"ENTRANCE_SIGNALING_TIMEOUT\",
            (guint)entrance_signal_stage))
        return G_SOURCE_REMOVE;
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_r29i_gates(candidate: str) -> None:
    required = (
        "R29I_WAITING_FOR_RING_TIMEOUT_SUPPRESSED=true",
        "R29I_WAITING_FOR_RING_BOUNDED_BY_RUNNER=true",
        "r29_listener_registered_ready &&",
        "v4_registered &&",
        "r29_attached_media_state == R29_LISTENER_REGISTERED_READY",
        "!r29_call_transaction_created",
        "!r29_call_transaction_active",
        "!r29c_registered_ctpp_mediareq26_open_sent",
        "r29h_defer_inherited_main_loop_quit",
        "failed = TRUE;",
        "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
        "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
        "SELF_ACTIVATION_001A_SENT_COUNT=%u",
        "R27_REPEAT_001A_SENT_COUNT=%u",
        "DOOR_ACTIONS_SENT=%u",
        "GATE_ACTIONS_SENT=%u",
        "REFRESH_LOOP_STARTED_COUNT=%u",
    )
    for marker in required:
        if marker not in candidate:
            raise RuntimeError(f"R29I_GATE=FAIL missing={marker}")

    timeout_start = candidate.index("entrance_signal_timeout_cb")
    timeout_end = candidate.index("static void\np12_tx_completed", timeout_start)
    timeout_cb = candidate[timeout_start:timeout_end]
    idle = timeout_cb.index("R29I_WAITING_FOR_RING_TIMEOUT_SUPPRESSED=true")
    inherited = timeout_cb.index("r29h_defer_inherited_main_loop_quit", idle)
    fail_closed = timeout_cb.index("failed = TRUE;", inherited)
    if not idle < inherited < fail_closed:
        raise RuntimeError("R29I_TIMEOUT_ORDER_GATE=FAIL")

    # The fix must not add any media transmission form.  The R29C transform is
    # still the sole owner of OPEN/STOP generation.
    if candidate.count("P116_R29C_TX_MEDIAREQ26_OPEN") == 0:
        raise RuntimeError("R29I_MEDIAREQ26_OPEN_LINEAGE_GATE=FAIL")
    if candidate.count("P116_R29C_TX_MEDIAREQ26_STOP") == 0:
        raise RuntimeError("R29I_MEDIAREQ26_STOP_LINEAGE_GATE=FAIL")
    if "p78_queue_rtpc_client_001a();" in candidate:
        raise RuntimeError("R29I_FORBIDDEN_R27_CALL_GATE=FAIL")


def transform(source: str, *, include_p116: bool = True) -> str:
    candidate = r29c.transform(source, include_p116=include_p116)
    candidate = _replace_once(
        candidate,
        _TIMEOUT_OLD,
        _TIMEOUT_NEW,
        "R29I waiting-for-ring timeout ownership",
    )
    _assert_r29i_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29I PREOPEN IDLE TRANSFORM ===",
            "WAITING_FOR_RING_TIMEOUT_OWNERSHIP=RUNNER_BOUNDED_WINDOW",
            "IDLE_SIGNALING_TIMEOUT_SUPPRESSION=ENABLED",
            "REAL_PREOPEN_FAILURE_FAIL_CLOSED=PRESERVED",
            "MEDIAREQ26_SEMANTICS_CHANGED=false",
            "LIVE_RUN=NOT_RUN",
            "PRODUCTION_FILES_CHANGED=0",
            "=== END COMELIT P116 R29I PREOPEN IDLE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--include-p116", action="store_true", default=True)
    parser.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8"), include_p116=args.include_p116),
        encoding="utf-8",
    )
    print("R29I_PREOPEN_IDLE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
