#!/usr/bin/env python3
"""P127 passive RELEASE transaction probe overlay (offline transform only).

The overlay replaces R37's active RELEASE branch with diagnostic observation.
It reuses the R35 envelope parser and the R37 opcode predicate, performs no
protocol write, STOP, teardown, Door/Gate action, or production Ring emit.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

CTP_VERSION = 0x18
CTP_FLAG_DATA = 0x40
CTP_FLAG_FIN = 0x20
RELEASE_OPCODE = 0x000E
RETRANSMIT_WINDOW_SECONDS = 15

CORE_BEGIN_MARKER = "/* P127_RELEASE_PROBE_BEGIN */"
CORE_END_MARKER = "/* P127_RELEASE_PROBE_END */"
WIRING_BEGIN_MARKER = "/* P127_RELEASE_PROBE_WIRING_BEGIN */"
WIRING_END_MARKER = "/* P127_RELEASE_PROBE_WIRING_END */"


@dataclass(frozen=True)
class CtpEnvelope:
    flags: int
    connection: int
    inner_body: bytes


def parse_release_envelope(
    payload: bytes,
    *,
    outer_channel: int,
    expected_outer_channel: int,
    expected_local_connection: int,
) -> CtpEnvelope | None:
    """Executable oracle for the C predicate; malformed input fails closed."""
    if len(payload) < 32 or payload[1] != CTP_VERSION:
        return None
    if payload[0] not in {CTP_FLAG_DATA, CTP_FLAG_FIN}:
        return None
    inner_len = int.from_bytes(payload[6:8], "big")
    body_end = 8 + inner_len
    padding = (-inner_len) % 4
    trailer = body_end + padding
    if len(payload) != trailer + 24:
        return None
    if payload[body_end:trailer] != b"\x00" * padding:
        return None
    if payload[trailer : trailer + 4] != b"\xff" * 4:
        return None
    if inner_len < 2:
        return None
    connection = int.from_bytes(payload[2:4], "big")
    local_connection = connection ^ 0x8000
    if not 0 < outer_channel <= 0xFFFF:
        return None
    if outer_channel != expected_outer_channel:
        return None
    if connection in {0, 0x7FFF, 0xFFFF}:
        return None
    if local_connection != expected_local_connection:
        return None
    inner_body = payload[8:body_end]
    # The opcode is in inner_body[0..1].  Header bytes 6..7 are only length.
    if int.from_bytes(inner_body[0:2], "big") != RELEASE_OPCODE:
        return None
    return CtpEnvelope(payload[0], connection, inner_body)


def classify_repetition(
    previous: tuple[int, int, float] | None,
    *,
    channel: int,
    connection: int,
    observed_at: float,
) -> str:
    """Return a diagnostic candidate, never a proven call identity."""
    if previous is None:
        return "UNKNOWN"
    old_channel, old_connection, old_at = previous
    if (
        (old_channel, old_connection) == (channel, connection)
        and 0 <= observed_at - old_at <= RETRANSMIT_WINDOW_SECONDS
    ):
        return "RETRANSMIT_CANDIDATE"
    return "UNKNOWN"


CORE_REGION = r'''/* P127_RELEASE_PROBE_BEGIN */
static int p127_is_passive_release(
    const unsigned char *payload,
    unsigned payload_len,
    unsigned outer_channel,
    const R35AttachedMediaSession *session,
    R35CtpEnvelopeView *view) {
    unsigned body_end, padding, i, local_connection;
    if (!payload || !session || !view) return 0;
    /* R35 owns structural length/trailer parsing. */
    if (!r35_parse_ctp_envelope(payload, payload_len, view)) return 0;
    if (view->version != R35_CTP_VERSION) return 0;
    if (view->flags != R35_CTP_FLAG_DATA && view->flags != R37_CTP_FLAG_FIN) return 0;
    if (view->inner_len < 2u) return 0;
    body_end = 8u + view->inner_len;
    padding = (4u - (view->inner_len % 4u)) % 4u;
    for (i = 0u; i < padding; ++i) {
        if (payload[body_end + i] != 0u) return 0;
    }
    if (outer_channel == 0u || outer_channel > 0xffffu) return 0;
    if (outer_channel != (session->outer_ctpp_handle & 0xffffu)) return 0;
    if (view->connection == 0u || view->connection == 0x7fffu ||
        view->connection == 0xffffu) return 0;
    local_connection = (view->connection ^ 0x8000u) & 0xffffu;
    if (local_connection != session->call_ctp_connection) return 0;
    /* R37's RELEASE predicate, applied to inner_body -- never header length. */
    return r35_read_be16(view->inner_body) == R37_OP_RELEASE;
}
/* P127_RELEASE_PROBE_END */'''

PASSIVE_RELEASE_BRANCH = r'''                    if (r37_on_current_call &&
                        (r37_view.flags == R35_CTP_FLAG_DATA || r37_view.flags == R37_CTP_FLAG_FIN) &&
                        r37_view.inner_len >= 2u &&
                        r35_read_be16(r37_view.inner_body) == R37_OP_RELEASE) {

                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);

                        printf("R37_REMOTE_RELEASE_OBSERVED=true\n");
                        printf(
                            "R37_PROTOCOL_STOP_RESULT=%s\n",
                            r37_rc == R35_OK ? "STOP_SENT" : "NO_OP"
                        );
                        fflush(stdout);

                        p12_consume_post_ack(
                            frame_len
                        );

                        continue;
                    }'''

PASSIVE_RELEASE_REPLACEMENT = r'''                    /* P127_RELEASE_PROBE_WIRING_BEGIN */
                    if (p127_is_passive_release(
                            body, body_len, (unsigned)v4_ctpp_channel_id,
                            &g_r35_session, &r37_view)) {
                        static unsigned p127_last_channel;
                        static unsigned p127_last_connection;
                        static gint64 p127_last_observed_us;
                        gint64 p127_now_us = g_get_monotonic_time();
                        const char *p127_classification = "UNKNOWN";
                        if (p127_last_observed_us > 0 &&
                            p127_last_channel == (unsigned)v4_ctpp_channel_id &&
                            p127_last_connection == r37_view.connection &&
                            p127_now_us >= p127_last_observed_us &&
                            p127_now_us - p127_last_observed_us <= 15 * G_USEC_PER_SEC) {
                            p127_classification = "RETRANSMIT_CANDIDATE";
                        }
                        printf(
                            "P127_CTP_TRANSACTION=%04x:%04x:%s\n",
                            (unsigned)v4_ctpp_channel_id,
                            r37_view.connection,
                            p127_classification
                        );
                        printf("P127_CALL_IDENTITY=UNKNOWN\n");
                        fflush(stdout);
                        p127_last_channel = (unsigned)v4_ctpp_channel_id;
                        p127_last_connection = r37_view.connection;
                        p127_last_observed_us = p127_now_us;
                    }
                    /* P127_RELEASE_PROBE_WIRING_END */'''


def transform(r37_source: str) -> str:
    if CORE_BEGIN_MARKER in r37_source:
        raise RuntimeError("P127_REAPPLY_GATE=FAIL")
    if "R37_WIRING_PROTOCOL_STOP_BEGIN" not in r37_source:
        raise RuntimeError("P127_REQUIRES_R37_OVERLAY_GATE=FAIL")
    if r37_source.count(PASSIVE_RELEASE_BRANCH) != 1:
        raise RuntimeError("P127_R37_RELEASE_BRANCH_GATE=FAIL")
    candidate = r37_source.replace(
        "/* R37_LIVE_READINESS_END */",
        "/* R37_LIVE_READINESS_END */\n\n" + CORE_REGION,
        1,
    ).replace(PASSIVE_RELEASE_BRANCH, PASSIVE_RELEASE_REPLACEMENT, 1)
    wiring = candidate.split(WIRING_BEGIN_MARKER, 1)[1].split(WIRING_END_MARKER, 1)[0]
    for forbidden in (
        "r37_handle_remote_release(", "r35_send_stop(",
        "r35_teardown_call(", "p12_queue_vip_frame(", "p12_consume_post_ack(",
    ):
        if forbidden in wiring:
            raise RuntimeError(f"P127_PASSIVE_GATE=FAIL forbidden={forbidden}")
    return candidate


def report() -> str:
    return "\n".join((
        "P127_SCOPE=OFFLINE_TRANSFORM_ONLY",
        "RELEASE_OBSERVATION=PASSIVE",
        "RETRANSMIT_CLASSIFICATION=RETRANSMIT_CANDIDATE",
        "CALL_IDENTITY=UNKNOWN",
        "PROTOCOL_TX=0", "STOP=0", "TEARDOWN=0",
        "PRODUCTION_RING_EMIT=false", "DOOR_ACTIONS=0", "GATE_ACTIONS=0",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    candidate = transform(args.source.read_text(encoding="utf-8"))
    if args.output:
        args.output.write_text(candidate, encoding="utf-8")
    else:
        print(candidate, end="")
    if args.report:
        print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
