#!/usr/bin/env python3
"""P116/R29I waiting-for-ring lifetime hardening.

Research-only transform layered on top of R29C/R29H.  The inherited
``ENTRANCE_SIGNALING_TIMEOUT`` belongs to the old self-activation transaction:
it is armed at CTPP registration together with the settle callback.  R29 turns
that settle callback into the persistent-listener READY transition, so keeping
the old 20 s timeout armed makes it terminate an otherwise healthy listener
while it is merely waiting for the first inbound CALL_INIT.

R29I fixes ownership at the source: keep the READY/settle timer, but do not arm
the obsolete self-activation signaling timeout at registration.  The bounded
human waiting window is owned by the live runner, while real transport,
registration and signaling failures remain fail-closed on their existing
paths.  mediareq26 serialization/profile/binding semantics are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform as r29c


DEFAULT_SOURCE = r29c.DEFAULT_SOURCE

_ARM_OLD = r'''                if (g_timeout_add(
                        ENTRANCE_SIGNAL_SETTLE_MS,
                        entrance_signal_start_cb,
                        NULL) == 0 ||
                    g_timeout_add(
                        ENTRANCE_SIGNAL_TIMEOUT_MS,
                        entrance_signal_timeout_cb,
                        NULL) == 0) {

                    fprintf(stderr, "ENTRANCE_SIGNALING_TIMER_START=FAIL\n");
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                }'''

_ARM_NEW = r'''                if (g_timeout_add(
                        ENTRANCE_SIGNAL_SETTLE_MS,
                        entrance_signal_start_cb,
                        NULL) == 0) {

                    fprintf(stderr, "ENTRANCE_SIGNALING_TIMER_START=FAIL\n");
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                } else {
                    printf("R29I_LEGACY_SIGNALING_TIMEOUT_ARMED=false\n");
                    printf("R29I_WAITING_FOR_RING_TIMEOUT_OWNER=RUNNER\n");
                    fflush(stdout);
                }'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (
        "R29I_LEGACY_SIGNALING_TIMEOUT_ARMED=false",
        "R29I_WAITING_FOR_RING_TIMEOUT_OWNER=RUNNER",
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R29I_PREOPEN_IDLE_MARKER_GATE=FAIL marker={marker}")

    # The obsolete timeout callback may remain compiled, but there must be no
    # registration-time source that schedules it.  This is stronger than
    # suppressing the callback after it fires: the stale transaction timer does
    # not exist while the persistent listener waits for CALL_INIT.
    timeout_schedule = r'''g_timeout_add(
                        ENTRANCE_SIGNAL_TIMEOUT_MS,
                        entrance_signal_timeout_cb,
                        NULL)'''
    if timeout_schedule in candidate:
        raise RuntimeError("R29I_LEGACY_TIMEOUT_SCHEDULE_GATE=FAIL")

    settle_schedule = r'''g_timeout_add(
                        ENTRANCE_SIGNAL_SETTLE_MS,
                        entrance_signal_start_cb,
                        NULL)'''
    if candidate.count(settle_schedule) != 1:
        raise RuntimeError("R29I_READY_SETTLE_TIMER_GATE=FAIL")

    # The inherited callback itself is intentionally retained for lineage
    # review, but without a scheduled source it cannot own waiting-for-ring.
    if candidate.count("entrance_signal_timeout_cb") != 1:
        raise RuntimeError("R29I_TIMEOUT_CALLBACK_DEFINITION_GATE=FAIL")

    # R29's settle callback is the READY transition.  It must still be present.
    for marker in (
        "RESEARCH_LISTENER_READY=true",
        "V4_RING_LISTENER_READY=true",
        "r29_capture_ready_snapshot();",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R29I_READY_PATH_GATE=FAIL missing={marker}")

    # The layer must not alter any mediareq26 wire-shape/profile anchors.
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
        _ARM_OLD,
        _ARM_NEW,
        "R29I_WAITING_FOR_RING_TIMEOUT_OWNERSHIP",
    )
    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R29I PREOPEN IDLE HARDENING ===",
            "LEGACY_SELF_ACTIVATION_SIGNALING_TIMEOUT_ARMED=false",
            "WAITING_FOR_RING_TIMEOUT_OWNER=RUNNER",
            "READY_SETTLE_TIMER_PRESERVED=true",
            "REAL_TRANSPORT_SIGNALING_FAILURE_FAIL_CLOSED=PRESERVED",
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
