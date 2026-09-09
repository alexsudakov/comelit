#!/usr/bin/env python3
"""P85: complete the entrance signaling state when HA-owned media becomes active.

P30 arms a 20-second one-shot signaling watchdog. Historical bounded media
observation reached ENTRANCE_SIGNAL_DONE before that watchdog fired. P80 replaces
the 3-second observation with a Home Assistant-owned media lifetime, but kept the
signaling stage at ENTRANCE_SIGNAL_OBSERVE_MEDIA; the inherited P30 watchdog then
misclassified a successful media session as a signaling timeout.

This overlay composes P83 and changes only the successful P80 media transition:
signaling is marked DONE while RTP forwarding remains independently enabled.
The existing timeout callback therefore follows its original success path and
Home Assistant remains the sole media-lifetime owner.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p83_rtpc_response_before_open_transform import (
    DEFAULT_SOURCE,
    transform as add_p83_runtime,
)


_ACTIVE_ANCHOR = r'''    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
    p80_media_forwarding_enabled = TRUE;

    printf("P80_MEDIA_ACTIVE=true\n");
'''

_ACTIVE_REPLACEMENT = r'''    /* RTPC signaling is complete here.  Finish the inherited entrance
     * signaling state so its 20-second P30 watchdog follows the existing
     * ENTRANCE_SIGNAL_DONE success path.  Media lifetime is owned by HA. */
    entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
    entrance_signaling_result = TRUE;
    p80_media_forwarding_enabled = TRUE;

    printf("P80_MEDIA_ACTIVE=true\n");
    printf("P80_SIGNALING_WATCHDOG_DISARMED=true\n");
'''


def transform(source: str) -> str:
    candidate = add_p83_runtime(source)
    count = candidate.count(_ACTIVE_ANCHOR)
    if count != 1:
        raise ValueError(f"P85 media-active anchor count: {count}")
    return candidate.replace(_ACTIVE_ANCHOR, _ACTIVE_REPLACEMENT, 1)


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P85 MEDIA SIGNALING WATCHDOG CORRECTIVE ===",
            "P85_COMPOSES=P83",
            "P85_SIGNALING_STATE_ON_MEDIA_ACTIVE=ENTRANCE_SIGNAL_DONE",
            "P85_INHERITED_SIGNALING_WATCHDOG=SUCCESS_PATH_ONLY",
            "P85_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
            "P85_MEDIA_HARD_LIMIT_SECONDS=180",
            "P85_AUTOMATIC_RETRY=false",
            "P85_SECOND_CTPP_OPEN=false",
            "P85_DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P85 MEDIA SIGNALING WATCHDOG CORRECTIVE ===",
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

    args.output.write_text(transform(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    print("P85_TRANSFORM=PASS")
    print("P85_SIGNALING_STATE_ON_MEDIA_ACTIVE=ENTRANCE_SIGNAL_DONE")
    print("P85_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    print("DOOR_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
