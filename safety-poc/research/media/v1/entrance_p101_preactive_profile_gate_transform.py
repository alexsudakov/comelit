#!/usr/bin/env python3
"""P101: pre-active RTP demux must share the P80 wrapper-profile gate.

Supersedes
----------
P101 является корректирующим оверлеем поверх P100/P99.  P99 уже доказал
нужность узкого pre-active demux, но его первая версия потребляла ранний RTP
до вызова P80 profile gate.  Это нарушает опубликованный P80 контракт: профиль
обертки должен быть зафиксирован и проверен одинаково для видео и аудио до
любого решения о дальнейшей судьбе RTP-пакета.

Correction
----------
P101 не меняет последовательность сигналинга, не добавляет transport, retry,
Door path или новые capture constants.  Единственное runtime-изменение:
p80_profile_accept() теперь вызывается до разветвления ACTIVE/PREACTIVE.
Несовпадение профиля использует тот же fail-closed путь для обоих состояний,
а pre-active успешный пакет по-прежнему только локально потребляется и не
форвардится.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p100_p99_compile_order_transform import (
    DEFAULT_SOURCE,
    transform as add_p100_runtime,
)


_CLASSIFIER_ORDER_OLD = r'''    if (payload_type == 99u) {
        if (p99_active_forward)
            p91_media_pt99++;
    } else if (payload_type == 8u) {
        if (p99_active_forward)
            p91_media_pt8++;
    } else {
        return FALSE;
    }

    if (!p99_active_forward) {
        p99_preactive_media_packets++;
        if (p99_preactive_media_packets == 1u) {
            printf("P80_PREACTIVE_MEDIA_DEMUX=PASS\n");
            printf("P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=%u\n", payload_type);
            printf("P80_PREACTIVE_MEDIA_PAYLOAD_EMITTED=false\n");
            fflush(stdout);
        }
        return TRUE;
    }

    if (!p80_profile_accept(packet, payload_type)) {
        fprintf(stderr, "P80_WRAPPER_PROFILE_MISMATCH=true\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }
'''

_CLASSIFIER_ORDER_NEW = r'''    if (payload_type == 99u) {
        if (p99_active_forward)
            p91_media_pt99++;
    } else if (payload_type == 8u) {
        if (p99_active_forward)
            p91_media_pt8++;
    } else {
        return FALSE;
    }

    if (!p80_profile_accept(packet, payload_type)) {
        fprintf(stderr, "P80_WRAPPER_PROFILE_MISMATCH=true\n");
        fprintf(stderr, "P80_WRAPPER_PROFILE_MISMATCH_STATE=%s\n",
                p99_active_forward ? "ACTIVE" : "PREACTIVE");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return TRUE;
    }

    if (!p99_active_forward) {
        p99_preactive_media_packets++;
        if (p99_preactive_media_packets == 1u) {
            printf("P80_PREACTIVE_MEDIA_DEMUX=PASS\n");
            printf("P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS\n");
            printf("P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=%u\n", payload_type);
            printf("P80_PREACTIVE_MEDIA_PAYLOAD_EMITTED=false\n");
            fflush(stdout);
        }
        return TRUE;
    }
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p100_runtime(source)
    candidate = _replace_once(
        candidate,
        _CLASSIFIER_ORDER_OLD,
        _CLASSIFIER_ORDER_NEW,
        "P101 shared pre-active profile gate",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P101 PREACTIVE PROFILE GATE CORRECTIVE ===",
            "P101_TRANSFORM=PASS",
            "P101_COMPOSES=P100",
            "P101_PREACTIVE_PROFILE_GATE=P80_PROFILE_ACCEPT_SHARED_BOTH_STATES",
            "P101_PREACTIVE_PROFILE_MISMATCH_FAIL_CLOSED=true",
            "P101_PREACTIVE_MEDIA_FORWARD=false",
            "P101_PREACTIVE_ACTIVE_COUNTERS_UNTOUCHED=true",
            "P101_AUTOMATIC_RETRY=false",
            "P101_SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P101 PREACTIVE PROFILE GATE CORRECTIVE ===",
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

    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print("P101_TRANSFORM=PASS")
    print("P101_COMPOSES=P100")
    print("P101_PREACTIVE_PROFILE_GATE=P80_PROFILE_ACCEPT_SHARED_BOTH_STATES")
    print("P101_PREACTIVE_PROFILE_MISMATCH_FAIL_CLOSED=true")
    print("P101_PREACTIVE_MEDIA_FORWARD=false")
    print("P101_PREACTIVE_ACTIVE_COUNTERS_UNTOUCHED=true")
    print("P101_AUTOMATIC_RETRY=false")
    print("P101_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
