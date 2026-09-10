#!/usr/bin/env python3
"""P98: rebind client 0x000A to the latest live client CTPP sequence.

P97 live evidence proved the new client ACK for device 0x000A was transmitted,
but the device never emitted the capture-observed ACK for our client 0x000A.
The frozen official timeline also proves a sequence relation that the inherited
P78 launcher did not preserve after P95 inserted the missing device-0x0002 ACK:

    client ACK(device 0x0002)
    -> client 0x000A with sequence delta 0
    -> client ACK(device 0x000A) with sequence delta 0x01000000

P78 still generated client 0x000A from the much older entrance-video-event
sequence.  P95 had already advanced the same CTPP client sequence when it sent
the device-0x0002 ACK, but that live sequence was not handed to P78.

This overlay composes P97, stores the sequence actually generated for the P95
client ACK, and passes that sequence into the existing P76 0x000A builder.
P97 then derives the next ACK and 0x001A from that corrected live chain.

No captured sequence value is replayed or emitted.  No target/address literal,
second CTPP OPEN, automatic retry, raw payload, media payload, or Door path is
introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p97_complete_post_000a_ack_cycle_transform import (
    DEFAULT_SOURCE,
    transform as add_p97_runtime,
)


_STATE_OLD = """static guint p95_device_0002_rx_count = 0;

/* P97 post-000A ACK-cycle state. */
"""

_STATE_NEW = """static guint p95_device_0002_rx_count = 0;
static guint32 p98_device_0002_ack_sequence = 0;
static gboolean p98_device_0002_ack_sequence_valid = FALSE;

/* P97 post-000A ACK-cycle state. */
"""

_RESET_OLD = """            p95_device_0002_ack_queued = FALSE;
            p95_device_0002_ack_sent = FALSE;
            p95_rtpc_started = FALSE;
            p95_device_0002_rx_count = 0;
"""

_RESET_NEW = """            p95_device_0002_ack_queued = FALSE;
            p95_device_0002_ack_sent = FALSE;
            p95_rtpc_started = FALSE;
            p95_device_0002_rx_count = 0;
            p98_device_0002_ack_sequence = 0;
            p98_device_0002_ack_sequence_valid = FALSE;
"""

_P95_ACK_SEQUENCE_OLD = """    write_le32(
        body + 2,
        entrance_device_video_ack_sequence +
            P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK
    );
"""

_P95_ACK_SEQUENCE_NEW = """    p98_device_0002_ack_sequence =
        entrance_device_video_ack_sequence +
            P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK;
    p98_device_0002_ack_sequence_valid = TRUE;
    write_le32(body + 2, p98_device_0002_ack_sequence);
"""

_P78_SEQUENCE_CALL_OLD = """    status = p76_generate_client_exchange(
        &p78_rtpc_runtime,
        entrance_video_event_sequence,
        entrance_video_event_sequence + 0x00010000u,
"""

_P78_SEQUENCE_CALL_NEW = """    if (!p98_device_0002_ack_sequence_valid ||
        !p95_device_0002_ack_sent) {
        p78_fail_rtpc("P80_CLIENT_000A_SEQUENCE_SOURCE=FAIL");
        return FALSE;
    }

    status = p76_generate_client_exchange(
        &p78_rtpc_runtime,
        p98_device_0002_ack_sequence,
        p98_device_0002_ack_sequence,
"""

_GENERATION_SUCCESS_OLD = """    if (status != P76_OK) {
        p78_fail_rtpc("P78_RTPC_GENERATE_CLIENT_EXCHANGE=FAIL");
        return FALSE;
    }

    printf("P78_CTPP_REGISTERED_REUSED=true\\n");
"""

_GENERATION_SUCCESS_NEW = """    if (status != P76_OK) {
        p78_fail_rtpc("P78_RTPC_GENERATE_CLIENT_EXCHANGE=FAIL");
        return FALSE;
    }

    if (p78_rtpc_client_000a_len != 44u ||
        read_le32(p78_rtpc_client_000a + 2u) !=
            p98_device_0002_ack_sequence) {
        p78_fail_rtpc("P80_CLIENT_000A_SEQUENCE_REBIND=FAIL");
        return FALSE;
    }

    printf("P80_CLIENT_000A_SEQUENCE_SOURCE=DEVICE_0002_ACK\\n");
    printf("P80_CLIENT_000A_SEQUENCE_REBOUND=PASS\\n");
    printf("P80_CLIENT_000A_SEQUENCE_EMITTED=false\\n");
    fflush(stdout);

    printf("P78_CTPP_REGISTERED_REUSED=true\\n");
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p97_runtime(source)
    candidate = _replace_once(candidate, _STATE_OLD, _STATE_NEW, "P98 state")
    candidate = _replace_once(candidate, _RESET_OLD, _RESET_NEW, "P98 sequence reset")
    candidate = _replace_once(
        candidate,
        _P95_ACK_SEQUENCE_OLD,
        _P95_ACK_SEQUENCE_NEW,
        "P98 capture P95 ACK sequence",
    )
    candidate = _replace_once(
        candidate,
        _P78_SEQUENCE_CALL_OLD,
        _P78_SEQUENCE_CALL_NEW,
        "P98 P78 sequence handoff",
    )
    candidate = _replace_once(
        candidate,
        _GENERATION_SUCCESS_OLD,
        _GENERATION_SUCCESS_NEW,
        "P98 generated 000A sequence gate",
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P98 CLIENT 000A SEQUENCE REBIND ===",
            "P98_COMPOSES=P97",
            "P98_CLIENT_000A_SEQUENCE_SOURCE=P95_DEVICE_0002_ACK_LIVE_STATE",
            "P98_CLIENT_000A_DELTA_FROM_PREVIOUS_CLIENT_CTPP=0",
            "P98_P97_ACK_000A_DELTA_REMAINS=0x01000000",
            "P98_P97_001A_REBIND_REMAINS=0x00010000",
            "P98_CAPTURE_SEQUENCE_VALUES_REPLAYED=false",
            "P98_SEQUENCE_VALUES_EMITTED=false",
            "P98_AUTOMATIC_RETRY=false",
            "P98_SECOND_CTPP_OPEN=false",
            "P98_DOOR_ACTION_SENT=false",
            "P98_RAW_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P98 CLIENT 000A SEQUENCE REBIND ===",
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
    print("P98_TRANSFORM=PASS")
    print("P98_CLIENT_000A_SEQUENCE_SOURCE=P95_DEVICE_0002_ACK_LIVE_STATE")
    print("P98_CLIENT_000A_SEQUENCE_VALUES_EMITTED=false")
    print("P98_CAPTURE_SEQUENCE_VALUES_REPLAYED=false")
    print("P98_AUTOMATIC_RETRY=false")
    print("P98_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
