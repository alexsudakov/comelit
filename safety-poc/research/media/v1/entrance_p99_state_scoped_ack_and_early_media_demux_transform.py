#!/usr/bin/env python3
"""P99: state-scope post-000A ACK binding and protect early raw media.

P98 live evidence proves two facts at the same boundary:

* while waiting for the device ACK of client 0x000A, the panel emits a
  same-CTPP 32-byte structural 0x1800/0x0000/0xffff ACK;
* immediately afterwards an ICE datagram of length 180 reaches recv_cb and is
  rejected by PseudoTCP before the post-ACK cycle can advance.

The frozen P52 timeline binds ACKs by the nearest outstanding opposite-direction
non-ACK frame; the reversed address-tail relation is supporting capture evidence,
not a reusable session identifier.  The live ACK has the proven structural shape
but does not satisfy the capture-derived tail equality against our generated
0x000A body.  Therefore P99 uses the runtime state machine as the primary binding:
there is exactly one outstanding client action while each ACK gate is armed.
The tail relation remains diagnostic only.

P80 currently attempts offset-8 RTP classification only after MEDIA_ACTIVE.  A
valid wrapped RTP datagram arriving during the bounded post-000A ACK cycle would
therefore be passed to PseudoTCP and terminate the session.  P99 arms a narrow
pre-active demux after the client ACK for device 0x000A is physically sent.  It
consumes only packets that already satisfy the P77/P80 offset-8 RTP shape and PT
99/8 contract.  Such early packets are dropped, never forwarded, until the final
0x001A ACK gate makes media active.  Non-media packets still go to PseudoTCP.

No raw bytes, address values, sequence values, identifiers, second CTPP OPEN,
retry, or Door path are introduced.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p98_rebind_client_000a_sequence_transform import (
    DEFAULT_SOURCE,
    transform as add_p98_runtime,
)


_STATE_OLD = """static gboolean p97_signaling_finished = FALSE;

static gboolean p97_store_device_000a_roles"""

_STATE_NEW = """static gboolean p97_signaling_finished = FALSE;

/* P99 narrow pre-active raw-media demux. */
static gboolean p99_preactive_media_demux_armed = FALSE;
static guint64 p99_preactive_media_packets = 0;

static gboolean p97_store_device_000a_roles"""

_RESET_OLD = """            p98_device_0002_ack_sequence = 0;
            p98_device_0002_ack_sequence_valid = FALSE;
"""

_RESET_NEW = """            p98_device_0002_ack_sequence = 0;
            p98_device_0002_ack_sequence_valid = FALSE;
            p99_preactive_media_demux_armed = FALSE;
            p99_preactive_media_packets = 0;
"""

_ACK_SENT_OLD = r'''        case P97_TX_DEVICE_000A_ACK:
            p97_client_ack_000a_sent = TRUE;
            printf("P80_DEVICE_000A_ACK_SENT=PASS\n");
            printf("P80_DEVICE_000A_ACK_SEQUENCE_EMITTED=false\n");
            fflush(stdout);
'''

_ACK_SENT_NEW = r'''        case P97_TX_DEVICE_000A_ACK:
            p97_client_ack_000a_sent = TRUE;
            p99_preactive_media_demux_armed = TRUE;
            printf("P80_DEVICE_000A_ACK_SENT=PASS\n");
            printf("P80_DEVICE_000A_ACK_SEQUENCE_EMITTED=false\n");
            printf("P80_PREACTIVE_MEDIA_DEMUX_ARMED=true\n");
            fflush(stdout);
'''

_CLASSIFIER_START_OLD = r'''    if (!p80_media_forwarding_enabled || !packet)
        return FALSE;

    p91_media_rx_total++;
'''

_CLASSIFIER_START_NEW = r'''    if (!packet)
        return FALSE;

    gboolean p99_active_forward = p80_media_forwarding_enabled;
    if (!p99_active_forward && !p99_preactive_media_demux_armed)
        return FALSE;

    if (p99_active_forward)
        p91_media_rx_total++;
'''

_CLASSIFIER_WRAPPER_COUNT_OLD = """    p91_media_wrapper_len_match++;

    const guint8 *inner = packet + 8u;
"""

_CLASSIFIER_WRAPPER_COUNT_NEW = """    if (p99_active_forward)
        p91_media_wrapper_len_match++;

    const guint8 *inner = packet + 8u;
"""

_CLASSIFIER_RTP_COUNT_OLD = """    p91_media_inner_rtp_v2++;

    if (payload_type == 99u)
        p91_media_pt99++;
    else if (payload_type == 8u)
        p91_media_pt8++;
    else
        return FALSE;

    if (!p80_profile_accept(packet, payload_type)) {
"""

_CLASSIFIER_RTP_COUNT_NEW = r'''    if (p99_active_forward)
        p91_media_inner_rtp_v2++;

    if (payload_type == 99u) {
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
'''

_ACK_HELPER_ANCHOR = """static gboolean
p97_handle_device_ack(guint16 request_id, const guint8 *body, guint body_len)
{
"""

_ACK_HELPER_NEW = r'''static gboolean
p99_state_scoped_structural_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (request_id != v4_ctpp_channel_id || !body || body_len != 32u)
        return FALSE;
    return read_le16(body + 0u) == 0x1800u &&
        body[6] == 0x00u && body[7] == 0x00u &&
        body[8] == 0xffu && body[9] == 0xffu &&
        body[10] == 0xffu && body[11] == 0xffu;
}

static gboolean
p97_handle_device_ack(guint16 request_id, const guint8 *body, guint body_len)
{
'''

_ACK_000A_OLD = r'''    if (p97_wait_device_ack_000a &&
        p97_ack_matches_source(body, body_len,
                               p78_rtpc_client_000a,
                               p78_rtpc_client_000a_len)) {
        p97_device_ack_000a_observed = TRUE;
'''

_ACK_000A_NEW = r'''    if (p97_wait_device_ack_000a &&
        p99_state_scoped_structural_ack(request_id, body, body_len)) {
        printf("P80_DEVICE_ACK_000A_BINDING=STATE_SCOPED_STRUCTURAL\n");
        printf("P80_DEVICE_ACK_000A_TAIL_RELATION=%s\n",
               p97_ack_matches_source(body, body_len,
                                      p78_rtpc_client_000a,
                                      p78_rtpc_client_000a_len)
                   ? "PASS" : "NOT_MATCHED");
        p97_device_ack_000a_observed = TRUE;
'''

_ACK_001A_OLD = r'''    if (p97_wait_device_ack_001a &&
        p97_ack_matches_source(body, body_len,
                               p78_rtpc_client_001a,
                               p78_rtpc_client_001a_len)) {
        p97_device_ack_001a_observed = TRUE;
'''

_ACK_001A_NEW = r'''    if (p97_wait_device_ack_001a &&
        p99_state_scoped_structural_ack(request_id, body, body_len)) {
        printf("P80_DEVICE_ACK_001A_BINDING=STATE_SCOPED_STRUCTURAL\n");
        printf("P80_DEVICE_ACK_001A_TAIL_RELATION=%s\n",
               p97_ack_matches_source(body, body_len,
                                      p78_rtpc_client_001a,
                                      p78_rtpc_client_001a_len)
                   ? "PASS" : "NOT_MATCHED");
        p97_device_ack_001a_observed = TRUE;
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    candidate = add_p98_runtime(source)
    for old, new, label in (
        (_STATE_OLD, _STATE_NEW, "P99 state"),
        (_RESET_OLD, _RESET_NEW, "P99 reset"),
        (_ACK_SENT_OLD, _ACK_SENT_NEW, "P99 early demux arm"),
        (_CLASSIFIER_START_OLD, _CLASSIFIER_START_NEW, "P99 classifier start"),
        (_CLASSIFIER_WRAPPER_COUNT_OLD, _CLASSIFIER_WRAPPER_COUNT_NEW, "P99 wrapper counter"),
        (_CLASSIFIER_RTP_COUNT_OLD, _CLASSIFIER_RTP_COUNT_NEW, "P99 RTP preactive demux"),
        (_ACK_HELPER_ANCHOR, _ACK_HELPER_NEW, "P99 structural ACK helper"),
        (_ACK_000A_OLD, _ACK_000A_NEW, "P99 ACK 000A binding"),
        (_ACK_001A_OLD, _ACK_001A_NEW, "P99 ACK 001A binding"),
    ):
        candidate = _replace_once(candidate, old, new, label)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P99 STATE-SCOPED ACK AND EARLY MEDIA DEMUX ===",
            "P99_COMPOSES=P98",
            "P99_ACK_BINDING=STATE_SCOPED_STRUCTURAL_SAME_CTPP",
            "P99_ACK_TAIL_RELATION=DIAGNOSTIC_ONLY",
            "P99_PREACTIVE_MEDIA_DEMUX_ARM=AFTER_DEVICE_000A_ACK_TX",
            "P99_PREACTIVE_MEDIA_ACCEPT=OFFSET8_RTP_PT99_OR_PT8_ONLY",
            "P99_PREACTIVE_MEDIA_FORWARD=false",
            "P99_PREACTIVE_MEDIA_STORE=false",
            "P99_AUTOMATIC_RETRY=false",
            "P99_SECOND_CTPP_OPEN=false",
            "P99_DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P99 STATE-SCOPED ACK AND EARLY MEDIA DEMUX ===",
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
    print("P99_TRANSFORM=PASS")
    print("P99_ACK_BINDING=STATE_SCOPED_STRUCTURAL_SAME_CTPP")
    print("P99_ACK_TAIL_RELATION=DIAGNOSTIC_ONLY")
    print("P99_PREACTIVE_MEDIA_DEMUX=OFFSET8_RTP_PT99_OR_PT8_ONLY")
    print("P99_PREACTIVE_MEDIA_FORWARD=false")
    print("P99_AUTOMATIC_RETRY=false")
    print("P99_SECOND_CTPP_OPEN=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
