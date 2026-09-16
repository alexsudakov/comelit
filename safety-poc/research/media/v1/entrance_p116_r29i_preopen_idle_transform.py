#!/usr/bin/env python3
"""P116/R29I research-only pre-open idle lifetime overlay.

R29H correctly protected the bounded post-OPEN section, but intentionally left
the inherited entrance signaling timeout fail-closed before OPEN. The next live
attempt showed that this inherited timeout can fire while the already-registered
research listener is simply waiting for a human ring, before any CALL_INIT.

R29I suppresses only that inherited timeout while the research listener is READY,
no CALL_INIT transaction has been created, and no media OPEN has been sent. The
suppression ends at CALL_INIT so pre-OPEN call-transaction timeout behavior stays
fail-closed. Real transport/registration failures are untouched, and the outer
live runner keeps bounded CALL_INIT and OPEN deadlines. The overlay performs no
network I/O and never executes the candidate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


DEFAULT_SOURCE = r29c.DEFAULT_SOURCE


_R29H_TIMEOUT_FRAGMENT = r'''    if (r29h_defer_inherited_main_loop_quit(
            "ENTRANCE_SIGNALING_TIMEOUT",
            (guint)entrance_signal_stage))
        return G_SOURCE_REMOVE;
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}'''


_R29I_TIMEOUT_FRAGMENT = r'''    if (r29_listener_registered_ready &&
        !r29_call_transaction_created &&
        !r29c_registered_ctpp_mediareq26_open_sent) {
        printf("R29I_WAITING_FOR_RING=true\n");
        printf("R29I_PREOPEN_IDLE_SIGNALING_TIMEOUT_SUPPRESSED=true\n");
        fflush(stdout);
        return G_SOURCE_REMOVE;
    }
    if (r29h_defer_inherited_main_loop_quit(
            "ENTRANCE_SIGNALING_TIMEOUT",
            (guint)entrance_signal_stage))
        return G_SOURCE_REMOVE;
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str, *, include_p116: bool = True) -> str:
    candidate = r29c.transform(source, include_p116=include_p116)
    candidate = _replace_once(
        candidate,
        _R29H_TIMEOUT_FRAGMENT,
        _R29I_TIMEOUT_FRAGMENT,
        "R29I pre-open idle signaling timeout ownership",
    )
    if candidate.count("R29I_PREOPEN_IDLE_SIGNALING_TIMEOUT_SUPPRESSED=true") != 1:
        raise RuntimeError("R29I_GATE=FAIL pre-open suppression marker count")
    if (
        "r29_listener_registered_ready &&\n"
        "        !r29_call_transaction_created &&\n"
        "        !r29c_registered_ctpp_mediareq26_open_sent"
        not in candidate
    ):
        raise RuntimeError("R29I_GATE=FAIL waiting-for-ring guard missing")
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29I PREOPEN IDLE TRANSFORM ===",
            "WAITING_FOR_RING_TIMEOUT_OWNERSHIP_FIXED=true",
            "PREOPEN_IDLE_TIMEOUT_SCOPE=READY_NO_CALL_INIT_NO_OPEN",
            "PREOPEN_CALL_TRANSACTION_TIMEOUT_FAIL_CLOSED=true",
            "TRANSPORT_FAILURE_BEHAVIOR_CHANGED=false",
            "REGISTRATION_FAILURE_BEHAVIOR_CHANGED=false",
            "MEDIAREQ26_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
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
    print("R29I_PREOPEN_IDLE_TRANSFORM=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
