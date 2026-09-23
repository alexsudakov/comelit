#!/usr/bin/env python3
"""P116/R36 attached inbound media: the OPEN trigger overlay.

This is a NEW, SEPARATE overlay transform applied to the OUTPUT of
``entrance_p116_r35_attached_media_native_transform.py``.  It never edits
the R35 transform, the R34/R33 models, or the canonical P106/P116 generator;
it never re-invokes any of them with different arguments.  Given an
already-R35-augmented candidate source as input, it returns a new candidate
with exactly one additional automatic behavior wired in.

Why this exists (see ``P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md``
for the full, cited derivation): R35 proved the call-bound MEDIAREQ26
OPEN/STOP write path byte-exact but left it completely unreachable
automatically -- nothing in the generated helper ever decided *when* to
call ``r35_send_open``. R36 turn 1 traced the native gate precisely
(``CallFsm::start_videorx`` fires only after ``CallFsm+100`` bit 3 is set,
and that bit is written verbatim from the payload of a received
CAPABILITIES message -- CTP inner opcode ``0x0003`` -- on the SAME
call-bound connection captured at CALL_INIT). R36 turn 2 closed the one
remaining gap: an independent, executable public CTP implementation
(``.r33-evidence/public-vip/viper/ctp.py:28`` -- ``OP_CAPABILITIES = 0x0003``;
``.r33-evidence/public-vip/viper/call.py:43,120-128`` -- an 8-byte DATA body
whose bytes 4..7 are exactly the capability word) independently confirms
the wire opcode and body layout this round had otherwise only derived by
pattern from native disassembly.

What this overlay adds, and nothing else:

- A dependency-free "trigger" core region (bounded by
  ``R36_ATTACHED_MEDIA_TRIGGER_BEGIN``/``_END`` markers) with two pure
  functions: one that decides whether a parsed CTP envelope is a
  CAPABILITIES message bound to the session's CURRENTLY captured call
  (fail-closed on any mismatch -- wrong connection, no live call, wrong
  flag, wrong opcode, too-short body), and one that -- ONLY if the
  capability word's bit 3 is set -- calls R35's own
  ``r35_allocate_media_rx_channel``/``r35_send_open``/``r35_enable_rtp``
  in sequence.  This region calls no R35/R34 function it doesn't already
  export, defines no new state struct, and duplicates nothing R35 already
  has: idempotency, the one-OPEN gate, the registration-handle/foreign-call
  guard, and RTP-after-OPEN ordering are all enforced by R35's existing,
  unmodified state machine -- this overlay is a thin caller, not a second
  implementation of any of those rules.
- One call-site insertion, in the SAME generic per-frame receive loop R35
  already hooked for CALL_INIT capture, immediately before the existing
  "other CTPP traffic" fallback log line -- so a matching CAPABILITIES
  frame is now specially recognized (only bounded scalars are ever
  printed) instead of silently falling through to the generic log-and-
  ignore path it hits today.

No file under ``custom_components/**`` is read or modified.  No live
Comelit network TX, no Door/Gate action, no synthetic/physical ring, and no
candidate execution are performed by this transform or its callers.
STOP remains reachable only by explicit call (``r35_send_stop``, unchanged
by this overlay) -- this round wires an automatic OPEN trigger only; the
bounded STOP trigger established by R35/R36-turn-1 (operator/bounded-timer
request) stays under external control.
"""
from __future__ import annotations

import argparse
from pathlib import Path

TRIGGER_BEGIN_MARKER = "/* R36_ATTACHED_MEDIA_TRIGGER_BEGIN */"
TRIGGER_END_MARKER = "/* R36_ATTACHED_MEDIA_TRIGGER_END */"
WIRING_TRIGGER_BEGIN_MARKER = "/* R36_WIRING_TRIGGER_BEGIN */"
WIRING_TRIGGER_END_MARKER = "/* R36_WIRING_TRIGGER_END */"

# ---------------------------------------------------------------------------
# Dependency-free trigger-decision core.
#
# Wire opcode and body layout: CROSS-VALIDATED this round between native
# disassembly (CallFsm::st_in_alerting dispatching FSM event 0xa03 to a
# handler that stores the received message's offset-4 word verbatim into
# CallFsm+100, `.r33-evidence/native-disasm/disasm-CallFsm_st_in_alerting.txt:
# 115-116,213-215,231-244`) and an independent, executable public CTP client
# (`.r33-evidence/public-vip/viper/ctp.py:28` OP_CAPABILITIES=0x0003;
# `.r33-evidence/public-vip/viper/call.py:43,120-128` 8-byte DATA body,
# capability word at bytes 4..7).  The envelope reader itself
# (`r35_parse_ctp_envelope`) is R35's, reused unmodified -- this region adds
# no new envelope parsing, only a decision on top of R35's existing parse.
# ---------------------------------------------------------------------------
CORE_REGION = r'''/* R36_ATTACHED_MEDIA_TRIGGER_BEGIN */
/*
 * P116/R36 attached inbound media: the OPEN trigger.
 *
 * Dependency-free by the same rule as R35's core region: no GLib/libnice
 * header, no network/socket primitive, no printf/fprintf.  Every decision
 * here is a pure function of an already-parsed R35CtpEnvelopeView and an
 * R35AttachedMediaSession*, so a host test can drive it without the
 * packaged helper runtime, exactly like R35's own core region.
 */
#define R36_OP_CAPABILITIES        0x0003u
#define R36_CAP_VIDEO_REQUEST_BIT  0x08u
#define R36_CAP_BODY_MIN_LEN       5u

/* Fail-closed on every axis this round can prove: wrong CTP flag (not a
 * DATA frame), inner opcode not CAPABILITIES, body too short to hold the
 * capability word, no currently-valid call on this session
 * (r35_call_ready), or a connection that -- after the SAME direction
 * transform r35_capture_call_ctp_id already applies -- does not match the
 * call this session actually captured (stale/prior/foreign call). None of
 * these checks duplicate an R35 rule; r35_call_ready is called, not
 * re-implemented. */
static int r36_is_capabilities_for_current_call(
    const R35AttachedMediaSession *s,
    const R35CtpEnvelopeView *view) {
    unsigned local_connection;
    if (!s || !view) return 0;
    if (view->flags != R35_CTP_FLAG_DATA) return 0;
    if (view->inner_len < R36_CAP_BODY_MIN_LEN) return 0;
    if (r35_read_be16(view->inner_body) != R36_OP_CAPABILITIES) return 0;
    if (!r35_call_ready(s)) return 0;
    local_connection = (view->connection ^ 0x8000u) & 0xFFFFu;
    return local_connection == s->call_ctp_connection ? 1 : 0;
}

static int r36_capabilities_video_requested(const R35CtpEnvelopeView *view) {
    if (!view || view->inner_len < R36_CAP_BODY_MIN_LEN) return 0;
    return (view->inner_body[4] & R36_CAP_VIDEO_REQUEST_BIT) != 0u ? 1 : 0;
}

/* Idempotent, fail-closed, no-retry trigger.  Every early return is a
 * pre-existing R35 guard (R35_ERR_*) reached through R35's own exported
 * functions -- r35_allocate_media_rx_channel, r35_send_open,
 * r35_enable_rtp -- never bypassed and never duplicated.  A rejected
 * attempt is not retried by this function or by its caller: the wiring
 * call site below calls this once per received frame, and a frame that
 * does not satisfy r36_is_capabilities_for_current_call never reaches it.
 *
 * media_channel_id is NOT a proven native field: R33/R34/R35 already
 * record the real local RTP-receiver channel/port as an unproven local
 * runtime field (P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md
 * SECTION 2), and this overlay does not close that gap. It reuses the
 * session's own call connection id as a stable, real, already-unique-
 * per-call local reference (never an invented network value) so that the
 * one-OPEN/idempotency machinery below is exercised meaningfully; a
 * future round that recovers the real local media-channel identity should
 * replace this call-connection-id reuse, not the trigger logic around it.
 */
static R35Result r36_trigger_open_from_capabilities(
    R35AttachedMediaSession *s,
    const R35CtpEnvelopeView *view) {
    R35MediaRequestSources src;
    unsigned channel_id;
    R35Result rc;
    if (!s || !view) return R35_ERR_BAD_ARGUMENT;
    if (!r36_capabilities_video_requested(view)) return R35_ERR_BAD_ARGUMENT;

    channel_id = s->call_ctp_connection;
    if (!(s->channel_allocated && s->channel_generation == s->call_generation)) {
        rc = r35_allocate_media_rx_channel(s, channel_id, channel_id);
        if (rc != R35_OK) return rc;
    }

    memset(&src, 0, sizeof(src));
    src.form = R35_FORM_TUNNEL;
    src.video_request = 1;      /* proven: this is exactly the bit3 checked above */
    src.profile_selector = 0;   /* UNPROVEN local cfg field, unchanged by R36 */
    src.media_channel_id = channel_id;
    src.max_rtp_payload = 0;    /* UNPROVEN local RtpDispatcher field, unchanged by R36 */
    src.channel_profile_word = 0;

    rc = r35_send_open(s, &src, 0);
    if (rc != R35_OK) return rc;

    (void)r35_enable_rtp(s, channel_id);
    return R35_OK;
}
/* R36_ATTACHED_MEDIA_TRIGGER_END */'''

# ---------------------------------------------------------------------------
# Wiring insertion: one new sibling branch in the SAME generic per-frame
# receive loop R35 already hooked, placed immediately before the existing
# "other CTPP traffic" generic fallback so a genuine, bounded-and-gated
# CAPABILITIES frame is recognized instead of silently logged and dropped.
# Anchored on text that is untouched by the R35 overlay (R35 only edits
# inside the earlier CALL_INIT block), so this anchor is stable regardless
# of R35's own edit.
# ---------------------------------------------------------------------------
_WIRING_TRIGGER_ANCHOR = """            /*
             * Other CTPP traffic:
             *
             * prefix/action only.
             * Raw payload is never printed.
             */
            printf(
                "V4_CTPP_EVENT \""""

_WIRING_TRIGGER_INSERTED = """            /* R36_WIRING_TRIGGER_BEGIN */
            {
                R35CtpEnvelopeView r36_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r36_view) &&
                    r36_is_capabilities_for_current_call(&g_r35_session, &r36_view)) {

                    R35Result r36_rc =
                        r36_trigger_open_from_capabilities(&g_r35_session, &r36_view);

                    printf("R36_CAPABILITIES_OBSERVED=true\\n");
                    printf(
                        "R36_TRIGGER_RESULT=%s\\n",
                        r36_rc == R35_OK ? "OPEN_SENT" : "REJECTED"
                    );
                    fflush(stdout);

                    p12_consume_post_ack(
                        frame_len
                    );

                    continue;
                }
            }
            /* R36_WIRING_TRIGGER_END */


            /*
             * Other CTPP traffic:
             *
             * prefix/action only.
             * Raw payload is never printed.
             */
            printf(
                "V4_CTPP_EVENT \""""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (
        TRIGGER_BEGIN_MARKER,
        TRIGGER_END_MARKER,
        WIRING_TRIGGER_BEGIN_MARKER,
        WIRING_TRIGGER_END_MARKER,
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R36_MARKER_GATE=FAIL marker={marker} count={candidate.count(marker)}")

    begin_idx = candidate.index(TRIGGER_BEGIN_MARKER)
    end_idx = candidate.index(TRIGGER_END_MARKER)
    if not begin_idx < end_idx:
        raise RuntimeError("R36_MARKER_ORDER_GATE=FAIL trigger begin/end out of order")

    core = extract_trigger_core_region(candidate)
    for forbidden in (
        "glib.h", "nice/agent.h", "GMainLoop", "gboolean", "guint", "NiceAgent",
        "PseudoTcpSocket", "socket(", "sendto(", "printf(", "fprintf(",
    ):
        if forbidden in core:
            raise RuntimeError(f"R36_CORE_DEPENDENCY_FREE_GATE=FAIL forbidden={forbidden}")

    for forbidden in (
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "entrance_self_activation",
        "v4_door_signal_handler",
        "V4_DOOR_WRITE",
        "repeat_001a",
        "REPEAT_001A",
        "-lpthread",
        "pthread_create",
        "g_timeout_add",
    ):
        if forbidden in core:
            raise RuntimeError(f"R36_CORE_FORBIDDEN_SYMBOL_GATE=FAIL forbidden={forbidden}")

    # The trigger core must never define a second OPEN/STOP writer, second
    # channel-allocation rule, or second serializer: it must call R35's.
    if "r35_allocate_media_rx_channel(" not in core:
        raise RuntimeError("R36_REUSES_R35_ALLOCATE_GATE=FAIL")
    if "r35_send_open(" not in core:
        raise RuntimeError("R36_REUSES_R35_SEND_OPEN_GATE=FAIL")
    if "r35_enable_rtp(" not in core:
        raise RuntimeError("R36_REUSES_R35_ENABLE_RTP_GATE=FAIL")
    for forbidden_new_writer in ("r36_send_open(", "r36_serialize_", "r36_build_call_bound_packet("):
        if forbidden_new_writer in core:
            raise RuntimeError(f"R36_NO_DUPLICATE_WRITER_GATE=FAIL forbidden={forbidden_new_writer}")

    wiring = candidate.split(WIRING_TRIGGER_BEGIN_MARKER, 1)[1].split(WIRING_TRIGGER_END_MARKER, 1)[0]

    # STOP stays explicit-invocation-only: neither new R36 region may call
    # r35_send_stop (its own R35 function DEFINITION legitimately contains
    # the substring "r35_send_stop(" elsewhere in the file, so this check is
    # scoped to the two regions R36 actually adds, not the whole candidate).
    if "r35_send_stop(" in core or "r35_send_stop(" in wiring:
        raise RuntimeError("R36_STOP_MUST_STAY_EXPLICIT_GATE=FAIL")
    if "g_timeout_add" in wiring or "retry" in wiring.lower():
        raise RuntimeError("R36_NO_RETRY_GATE=FAIL")
    if "r36_is_capabilities_for_current_call(" not in wiring:
        raise RuntimeError("R36_WIRING_CALLS_GUARD_GATE=FAIL")


def extract_trigger_core_region(candidate: str) -> str:
    """Return exactly the text between the R36 trigger BEGIN/END markers (exclusive)."""
    begin = candidate.index(TRIGGER_BEGIN_MARKER) + len(TRIGGER_BEGIN_MARKER)
    end = candidate.index(TRIGGER_END_MARKER)
    if end <= begin:
        raise RuntimeError("R36_CORE_EXTRACTION_GATE=FAIL empty or inverted region")
    return candidate[begin:end]


def transform(r35_source: str) -> str:
    """Apply the R36 OPEN-trigger overlay to an already-R35-augmented C source.

    ``r35_source`` must already be the output of
    ``entrance_p116_r35_attached_media_native_transform.py``'s ``transform()``;
    this function never re-invokes that transform, the canonical P106/P116
    generator, or any R34/R33 model, and never touches their digests. It is
    idempotent-checked: re-applying it to its own output raises, matching
    R35's own re-application discipline.
    """
    if TRIGGER_BEGIN_MARKER in r35_source:
        raise RuntimeError("R36_REAPPLY_GATE=FAIL transform already applied")
    if "R35_ATTACHED_MEDIA_BEGIN" not in r35_source or "R35_WIRING_BEGIN" not in r35_source:
        raise RuntimeError("R36_REQUIRES_R35_OVERLAY_GATE=FAIL input is not R35-augmented")

    candidate = r35_source

    # Insert the dependency-free trigger core immediately after R35's own
    # core+wiring insertion so it can reference R35's types/functions
    # (R35Result, R35AttachedMediaSession, R35CtpEnvelopeView,
    # r35_read_be16, r35_call_ready, r35_allocate_media_rx_channel,
    # r35_send_open, r35_enable_rtp) without redeclaring any of them.
    r35_wiring_end = "/* R35_WIRING_END */"
    candidate = _replace_once(
        candidate,
        r35_wiring_end,
        r35_wiring_end + "\n\n" + CORE_REGION + "\n",
        "R36_TRIGGER_CORE_INSERTION",
    )

    candidate = _replace_once(
        candidate,
        _WIRING_TRIGGER_ANCHOR,
        _WIRING_TRIGGER_INSERTED,
        "R36_WIRING_TRIGGER_INSERTION",
    )

    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R36 ATTACHED MEDIA TRIGGER NATIVE TRANSFORM ===",
            "OVERLAY_STEP=SEPARATE_FROM_R35_CHAIN",
            "TRIGGER_CORE_DEPENDENCY_FREE=true",
            "TRIGGER_OPCODE=OP_CAPABILITIES_0x0003",
            "TRIGGER_BIT=CAP_WORD_BIT3",
            "REUSES_R35_ALLOCATE=true",
            "REUSES_R35_SEND_OPEN=true",
            "REUSES_R35_ENABLE_RTP=true",
            "DUPLICATE_WRITER_ADDED=false",
            "STOP_REMAINS_EXPLICIT_ONLY=true",
            "AUTOMATIC_RETRY_ADDED=false",
            "NEW_RUNTIME_DEPENDENCY_ADDED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R36 ATTACHED MEDIA TRIGGER NATIVE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to an already-R35-augmented candidate C source (output of "
        "entrance_p116_r35_attached_media_native_transform.py).",
    )
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
