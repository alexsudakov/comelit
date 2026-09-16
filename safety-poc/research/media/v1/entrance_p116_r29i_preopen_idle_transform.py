#!/usr/bin/env python3
"""P116/R29I hardening transform for pre-OPEN waiting-for-ring lifetime.

Research-only. Builds on the R29C registered-CTPP mediareq26 candidate and changes
only the inherited entrance signaling timeout ownership before CALL_INIT:
while the registered listener is ready and no call transaction has been created,
the timeout is treated as WAITING_FOR_RING idle and does not fail the process.
Once CALL_INIT has created a real call transaction, the inherited pre-OPEN fail-closed
behavior is retained unchanged; after OPEN the R29H bounded section remains unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c

DEFAULT_SOURCE = r29c.DEFAULT_SOURCE


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str, *, include_p116: bool = True) -> str:
    candidate = r29c.transform(source, include_p116=include_p116)

    old = '''    fprintf(
        stderr,
        "ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u\\n",
        (unsigned)entrance_signal_stage
    );
    if (r29h_defer_inherited_main_loop_quit(
            "ENTRANCE_SIGNALING_TIMEOUT",
            (guint)entrance_signal_stage))
        return G_SOURCE_REMOVE;
    failed = TRUE;
    if (loop)
        g_main_loop_quit(loop);
    return G_SOURCE_REMOVE;
}'''

    new = '''    fprintf(
        stderr,
        "ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u\\n",
        (unsigned)entrance_signal_stage
    );
    if (r29_listener_registered_ready &&
        !r29_call_transaction_created &&
        !r29_call_transaction_active &&
        !r29c_registered_ctpp_mediareq26_open_sent &&
        r29h_lifetime_phase == R29H_LIFETIME_PRE_OPEN) {
        printf("R29I_WAITING_FOR_RING_IDLE_TIMEOUT_DEFERRED=true\\n");
        printf("R29I_WAITING_FOR_RING_STAGE=%u\\n",
               (unsigned)entrance_signal_stage);
        fflush(stdout);
        return G_SOURCE_CONTINUE;
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

    candidate = _replace_once(
        candidate,
        old,
        new,
        "R29I waiting-for-ring timeout ownership",
    )

    required = (
        "REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true",
        "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
        "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
        "SELF_ACTIVATION_001A_SENT_COUNT=%u",
        "R27_REPEAT_001A_SENT_COUNT=%u",
        "DOOR_ACTIONS_SENT=%u",
        "GATE_ACTIONS_SENT=%u",
        "R29I_WAITING_FOR_RING_IDLE_TIMEOUT_DEFERRED=true",
        "!r29_call_transaction_created",
        "!r29_call_transaction_active",
        "return G_SOURCE_CONTINUE;",
    )
    for marker in required:
        if marker not in candidate:
            raise RuntimeError(f"R29I_GATE=FAIL missing={marker}")
    if "R29I_PREOPEN_CALL_GRACE_ACTIVE" in candidate:
        raise RuntimeError("R29I_GATE=FAIL unexpected pre-open call grace")
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29I PREOPEN IDLE TRANSFORM ===",
            "WAITING_FOR_RING_TIMEOUT_OWNERSHIP_FIXED=true",
            "PREOPEN_CALL_TRANSACTION_FAIL_CLOSED_PRESERVED=true",
            "POST_OPEN_R29H_BOUNDED_SECTION_PRESERVED=true",
            "MEDIAREQ26_SEMANTICS_CHANGED=false",
            "LIVE_RUN=NOT_RUN",
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
    print("R29I_WAITING_FOR_RING_TRANSFORM=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
