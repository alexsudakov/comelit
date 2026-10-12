#!/usr/bin/env python3
"""Shared V4 ring opaque body probe overlay."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

BEGIN = "/* R68_RINGID_PROBE_BEGIN */"
END = "/* R68_RINGID_PROBE_END */"
SENTINEL = "V4_RING_BODY_32_35"

_HELPER_ANCHOR = """static gboolean
v4_ring_is_retransmit(
    const guint8 *body,
    guint body_len)
{
"""

_FRAME_SHA_ANCHOR = """        printf("V4_RING_FRAME_SHA256=%s\\n", digest);
"""

_RETRANSMIT_SHA_ANCHOR = """        printf("V4_RING_RETRANSMIT_SHA256=%s\\n", digest);
"""

_HELPER = r'''/* R68_RINGID_PROBE_BEGIN */
static void
v4_ring_probe_emit(const guint8 *body, guint body_len, const char *phase)
{
    guint16 peer_connection;

    printf("V4_RING_PHASE=%s\n", phase ? phase : "UNKNOWN");

    if (!body || body_len < 4u) {
        printf("V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH\n");
        fflush(stdout);
        return;
    }

    peer_connection = ((guint16)body[2] << 8) | (guint16)body[3];
    printf("V4_RING_PEER_CONNECTION=%04x\n", (unsigned)peer_connection);

    if (body_len < 36u) {
        printf("V4_RING_BODY_32_35=----\n");
        printf("V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH\n");
        fflush(stdout);
        return;
    }

    /* body[32..35] is an opaque call-identity CANDIDATE; semantics unproven. */
    printf(
        "V4_RING_BODY_32_35=%02x%02x%02x%02x\n",
        (unsigned)body[32],
        (unsigned)body[33],
        (unsigned)body[34],
        (unsigned)body[35]
    );
    printf("V4_RING_PARSE_STATUS=OK\n");
    fflush(stdout);
}
/* R68_RINGID_PROBE_END */

'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R68_RINGID_PROBE_ANCHOR_GATE=FAIL label={label} count={count}")
    return text.replace(old, new, 1)


def apply_probe(text: str) -> str:
    if SENTINEL in text:
        raise RuntimeError("RINGID_PROBE_REAPPLY_GATE=FAIL")

    candidate = _replace_once(text, _HELPER_ANCHOR, _HELPER + _HELPER_ANCHOR, "helper")
    candidate = _replace_once(
        candidate,
        _FRAME_SHA_ANCHOR,
        _FRAME_SHA_ANCHOR + '        v4_ring_probe_emit(body, body_len, "INITIAL");\n',
        "initial phase",
    )
    candidate = _replace_once(
        candidate,
        _RETRANSMIT_SHA_ANCHOR,
        _RETRANSMIT_SHA_ANCHOR + '        v4_ring_probe_emit(body, body_len, "RETRANSMIT");\n',
        "retransmit phase",
    )

    for marker in (
        BEGIN,
        END,
        "V4_RING_PHASE=%s",
        'v4_ring_probe_emit(body, body_len, "INITIAL");',
        'v4_ring_probe_emit(body, body_len, "RETRANSMIT");',
        "V4_RING_PEER_CONNECTION=%04x",
        "V4_RING_BODY_32_35=%02x%02x%02x%02x",
        "V4_RING_BODY_32_35=----",
        "V4_RING_PARSE_STATUS=OK",
        "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R68_RINGID_PROBE_FINAL_GATE=FAIL missing={marker}")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    output = apply_probe(args.source.read_text(encoding="utf-8"))
    args.output.write_text(output, encoding="utf-8")
    print("RINGID_PROBE_CORE=PASS")
    print("RINGID_PROBE_SOURCE_SHA256=" + hashlib.sha256(output.encode("utf-8")).hexdigest())
    print("RAW_RING_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
