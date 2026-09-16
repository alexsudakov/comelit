#!/usr/bin/env python3
"""P116/R29I pre-open idle hardening for the registered-CTPP mediareq26 probe.

Research-only transform layered on top of R29C/R29H. It changes only the
lifetime ownership of the inherited entrance signaling timeout while the
listener is registered/ready and still waiting for the first CALL_INIT.
It does not change mediareq26 serialization, media profile values, channel
binding, or any production code.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


DEFAULT_SOURCE = r29c.DEFAULT_SOURCE

_TIMEOUT_OLD = r'''    fprintf(
        stderr,
        "ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u\n",
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

_TIMEOUT_NEW = r'''    fprintf(
        stderr,
        "ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u\n",
        (unsigned)entrance_signal_stage
    );
    if (r29_listener_registered_ready &&
        r29_attached_media_state == R29_LISTENER_REGISTERED_READY &&
        !r29_call_transaction_created &&
        !r29_call_transaction_active &&
        !r29c_registered_ctpp_mediareq26_open_sent) {
        printf("R29I_WAITING_FOR_RING_SIGNALING_TIMEOUT_DEFERRED=true\n");
        printf("R29I_WAITING_FOR_RING_STAGE=%u\n",
               (unsigned)entrance_signal_stage);
        printf("R29I_WAITING_FOR_RING_PROCESS_VALID=true\n");
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


def _assert_gates(candidate: str) -> None:
    marker = "R29I_WAITING_FOR_RING_SIGNALING_TIMEOUT_DEFERRED=true"
    if candidate.count(marker) != 1:
        raise RuntimeError("R29I_PREOPEN_IDLE_MARKER_GATE=FAIL")

    cb_start = candidate.find("entrance_signal_timeout_cb")
    if cb_start < 0:
        raise RuntimeError("R29I_TIMEOUT_CALLBACK_GATE=FAIL missing_callback")
    cb_end = candidate.find("static void\np12_tx_completed", cb_start)
    if cb_end < 0:
        raise RuntimeError("R29I_TIMEOUT_CALLBACK_GATE=FAIL missing_end_anchor")
    callback = candidate[cb_start:cb_end]

    required = (
        "r29_listener_registered_ready",
        "r29_attached_media_state == R29_LISTENER_REGISTERED_READY",
        "!r29_call_transaction_created",
        "!r29_call_transaction_active",
        "!r29c_registered_ctpp_mediareq26_open_sent",
        marker,
        "r29h_defer_inherited_main_loop_quit",
        "failed = TRUE;",
    )
    for item in required:
        if item not in callback:
            raise RuntimeError(f"R29I_TIMEOUT_CALLBACK_GATE=FAIL missing={item}")

    idle = callback.index(marker)
    post_open = callback.index("r29h_defer_inherited_main_loop_quit")
    fail_closed = callback.index("failed = TRUE;")
    if not (idle < post_open < fail_closed):
        raise RuntimeError("R29I_TIMEOUT_CALLBACK_ORDER_GATE=FAIL")

    # The layer must not alter any of the mediareq26 wire-shape/profile anchors.
    for wire_marker in (
        "MEDIAREQ26_OPEN_STRUCTURAL_LAYOUT=PASS",
        "MEDIAREQ26_STOP_STRUCTURAL_LAYOUT=PASS",
        "REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=%u",
        "REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=%u",
        "ONE_SHOT_OPEN_GATE=%s",
        "ONE_SHOT_STOP_GATE=%s",
    ):
        if wire_marker not in candidate:
            raise RuntimeError(f"R29I_MEDIAREQ26_INHERITANCE_GATE=FAIL missing={wire_marker}")


def transform(source: str, *, include_p116: bool = True) -> str:
    candidate = r29c.transform(source, include_p116=include_p116)
    candidate = _replace_once(
        candidate,
        _TIMEOUT_OLD,
        _TIMEOUT_NEW,
        "R29I_WAITING_FOR_RING_TIMEOUT",
    )
    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29I PREOPEN IDLE HARDENING ===",
            "WAITING_FOR_RING_TIMEOUT_OWNERSHIP=REGISTERED_READY_IDLE",
            "CALL_TRANSACTION_TIMEOUT_FAIL_CLOSED=PRESERVED",
            "MEDIAREQ26_SEMANTICS_CHANGED=false",
            "LIVE_RUN=NOT_RUN",
            "=== END COMELIT P116 R29I PREOPEN IDLE HARDENING ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--include-p116", action="store_true", default=True)
    args = parser.parse_args(argv)

    candidate = transform(
        args.source.read_text(encoding="utf-8"),
        include_p116=args.include_p116,
    )
    if args.output:
        args.output.write_text(candidate, encoding="utf-8")
    else:
        print(candidate, end="")
    if args.report:
        print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
