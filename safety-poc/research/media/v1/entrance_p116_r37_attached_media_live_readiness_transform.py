#!/usr/bin/env python3
"""P116/R37 attached inbound media: live-readiness closure overlay.

This is a NEW, SEPARATE overlay transform applied to the OUTPUT of
``entrance_p116_r36_attached_media_trigger_transform.py``.  It never edits
the R36, R35, or R34/R33 files, and never re-invokes the canonical P106/P116
generator or either prior overlay with different arguments.

Why this exists (full, cited derivation:
``P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_READINESS.md``): this round's own
CHILD A closed every remaining native OPEN-field source to its EXACT origin
(RtpDispatcher::getMaxRtpPayload() -> ctor parameter at RtpDispatcher+68;
the local media-channel identity -> viper_tunnel_channel_create ->
viper_channel_get_id -> ViperTunnel::openMediaRXChannel -> RtpDispatcher+8
-> csp_send_mediareq26 body bytes 8..9; the cfg capability threshold, the
media-eligibility selector at CallFsm+840 bit2, and the TUNNEL/ADDRESS
choice itself at cfg->+288 != NULL) -- and found that EVERY ONE of them is
C++ object state living inside the SAME address space as libvipcomelit.so
(RtpDispatcher, ViperTunnel, the shared cfg_t), never carried on the wire,
and therefore unreachable by this helper: the R35/R36 candidate is a
separate musl binary that does not link libvipcomelit.so (NEEDED=
libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
only, unchanged by this round). ``LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false``
and ``ALL_OPEN_RUNTIME_FIELDS_PROVEN=false`` as a direct, evidenced
consequence -- not a missing derivation but an architectural boundary.

Per the operator's explicit, critical instruction, this overlay therefore
adds **zero** new OPEN-related code: R36's existing (already non-live-ready,
placeholder-channel-id) OPEN trigger is left completely untouched byte-for-
byte, and no function this overlay defines ever calls
``r35_allocate_media_rx_channel`` or ``r35_send_open`` (enforced by
``_assert_gates`` below, ``R37_NO_NEW_OPEN_PATH_GATE``).

What CAN be closed independently of the OPEN blocker, and is closed here
(CHILD B/C of the task):

- A real, bounded, externally-invocable STOP control (CHILD B): a
  ``GUnixSignalSource`` on SIGUSR2 (``g_unix_signal_add``, dispatched from
  the normal GLib main loop -- never a raw ``signal()`` handler doing
  protocol work, and never a ``g_timeout_add`` poll, matching R35/R36's own
  "no retry" discipline) that calls exactly one bounded dispatcher,
  ``r37_bounded_stop_request``, which does nothing but call R35's own
  ``r35_send_stop``/``r35_dispose_media_rx_channel`` -- no new writer, no
  new serializer, no new channel-allocation rule.
- Fail-closed local/media response to the two already-proven native
  protocol stop causes (CHILD C): a later CAPABILITY_REPORT clearing bit3
  (call stays alive; channel/RTP only), and RELEASE (media stop attempted
  FIRST, matching R36 SECTION 5's own finding that native ``stop_videorx()``
  fires as part of call teardown, THEN local call state is marked
  terminal -- so no stale write can ever follow a terminated call).

No file under ``custom_components/**`` is read or modified.  No live
Comelit network TX, no Door/Gate action, no synthetic/physical ring, and no
candidate execution are performed by this transform or its callers.
"""
from __future__ import annotations

import argparse
from pathlib import Path

CORE_BEGIN_MARKER = "/* R37_LIVE_READINESS_BEGIN */"
CORE_END_MARKER = "/* R37_LIVE_READINESS_END */"
WIRING_BEGIN_MARKER = "/* R37_WIRING_BEGIN */"
WIRING_END_MARKER = "/* R37_WIRING_END */"
WIRING_PROTOCOL_STOP_BEGIN_MARKER = "/* R37_WIRING_PROTOCOL_STOP_BEGIN */"
WIRING_PROTOCOL_STOP_END_MARKER = "/* R37_WIRING_PROTOCOL_STOP_END */"

# ---------------------------------------------------------------------------
# Dependency-free core: the bounded STOP dispatcher and the two protocol-
# stop-cause handlers.  Every one of these functions is a thin caller of
# R35's own exported, unmodified functions (r35_call_ready, r35_send_stop,
# r35_dispose_media_rx_channel, r35_teardown_call); none of them define a
# second writer, serializer, or channel-allocation rule, and none of them
# ever calls r35_allocate_media_rx_channel or r35_send_open (see
# R37_NO_NEW_OPEN_PATH_GATE in _assert_gates).
# ---------------------------------------------------------------------------
CORE_REGION = r'''/* R37_LIVE_READINESS_BEGIN */
/*
 * P116/R37 attached inbound media: live-readiness closure.
 *
 * CHILD A of this round's task (the remaining native OPEN runtime-field
 * sources -- cfg capability threshold cfg->+16, tunnel-busy RtpDispatcher+
 * 136, the media-eligibility selector CallFsm+840 bit2, the TUNNEL/ADDRESS
 * choice cfg->+288 != NULL, the profile-selector CallFsm+812, max RTP
 * payload RtpDispatcher::getMaxRtpPayload(), and -- critically -- the local
 * media RX channel identity viper_tunnel_channel_create ->
 * ViperTunnel::openMediaRXChannel -> RtpDispatcher+8) is NOT closed by this
 * region or by any R37 file: every one of those fields was traced this
 * round to its exact native source (P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_
 * READINESS.md SECTION 1) and every one of them is C++ object state inside
 * the SAME process as libvipcomelit.so, never carried on the wire, and not
 * reachable by this helper (a separate musl binary that does not link
 * libvipcomelit.so). This region therefore adds NO new OPEN wiring: R36's
 * existing OPEN trigger is untouched, and no function below ever calls
 * r35_allocate_media_rx_channel or r35_send_open.
 */
#define R37_OP_RELEASE        0x000Eu
#define R37_CTP_FLAG_FIN      0x20u

typedef struct {
    unsigned bounded_stop_request_received_count;
    unsigned call_bound_media_stop_sent_count;
    unsigned rtp_disarmed_count;
    unsigned media_rx_channel_disposed_count;
    unsigned duplicate_stop_request_ignored_count;
} R37BoundedStopTelemetry;

/* The single stop-and-dispose sequence every stop cause below funnels
 * through: exactly one r35_send_stop call (RTP disarm is already part of
 * that call -- R35's own r35_send_stop invokes the rtp_arm_hook with 0),
 * then exactly one r35_dispose_media_rx_channel call.  Every early return
 * is one of R35's own existing R35Result gates -- this function adds no new
 * idempotency mechanism, it relies on R35's (stop_sent/stop_count,
 * R35_ERR_SECOND_STOP; open_sent, R35_ERR_STOP_BEFORE_OPEN). */
static R35Result r37_stop_and_dispose(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    R35Result rc;
    int already_stopped;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    already_stopped = s->stop_sent;
    rc = r35_send_stop(s, form, s->channel_id);
    if (rc != R35_OK) {
        /* Once a stop has already succeeded, R35's own gates reject any
         * further attempt on the same channel -- R35_ERR_SECOND_STOP if
         * called again before disposal, or R35_ERR_STALE_CHANNEL if called
         * after this function's own disposal step below already ran (the
         * common case, since disposal happens immediately). Both are the
         * SAME semantic event from this function's point of view: a
         * duplicate, already-handled stop request, not a fresh rejection
         * for some other reason. */
        if (already_stopped) t->duplicate_stop_request_ignored_count += 1u;
        return rc;
    }
    t->call_bound_media_stop_sent_count += 1u;
    t->rtp_disarmed_count += 1u;
    rc = r35_dispose_media_rx_channel(s, s->channel_id);
    if (rc == R35_OK) t->media_rx_channel_disposed_count += 1u;
    return rc;
}

/* CHILD B: the real, bounded, explicitly-invocable STOP control.  Exactly
 * one external request is ever effective per media lifetime -- a second
 * call is rejected by R35's own stop_sent/stop_count gate without a second
 * write.  A request that arrives after the call transaction is already
 * gone (REMOTE_CALL_TERMINATED, see r37_handle_remote_release below) is
 * rejected HERE, before reaching r35_send_stop, by the same r35_call_ready
 * check r35_send_stop itself would apply -- this makes the "stale,
 * terminated call" rejection observable via
 * bounded_stop_request_received_count without ever attempting a write. */
static R35Result r37_bounded_stop_request(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    t->bounded_stop_request_received_count += 1u;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    return r37_stop_and_dispose(s, t, form);
}

/* CHILD C item 1: a LATER CAPABILITY_REPORT clearing bit3 (native:
 * CallFsm::st_in_alerting's SAME event-0xa03 handler re-evaluates flags100
 * and calls stop_videorx() when bit3 is now clear --
 * P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md SECTION 5). The call
 * itself is NOT over: call/listener state is deliberately left untouched
 * here (no r35_teardown_call) -- only channel/RTP state changes, matching
 * CHILD D's preservation requirement. This is an ADDITIONAL fail-closed
 * safety net, not a substitute for the explicit bounded STOP above. */
static R35Result r37_handle_capability_cleared(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    return r37_stop_and_dispose(s, t, form);
}

/* CHILD C item 2 and the required race rule: REMOTE_CALL_TERMINATED => no
 * stale media write => local state cleanup / exact native-equivalent
 * behaviour. R36 SECTION 5 found stop_videorx() is called as PART of
 * native call-teardown on RELEASE (local FSM event 0xb0e; wire OP_RELEASE=
 * 0x000E, .r33-evidence/public-vip/viper/ctp.py:30) -- i.e. native
 * sequencing stops media BEFORE the call transaction is gone. This
 * function performs the SAME order: attempt exactly one stop-and-dispose
 * FIRST while r35_call_ready(s) is still true, THEN mark the call
 * terminal. Once r35_teardown_call has run, r35_call_ready(s) is false and
 * every subsequent r37_bounded_stop_request/r37_handle_capability_cleared
 * call is rejected with R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER -- no stale
 * write can ever reach r35_send_stop after this function returns, which is
 * exactly how the race named in CHILD C (remote RELEASE arriving before
 * the operator's explicit bounded STOP) resolves: the later operator
 * request is received (counted) and rejected, never written. */
static R35Result r37_handle_remote_release(
    R35AttachedMediaSession *s,
    R37BoundedStopTelemetry *t,
    int form) {
    R35Result rc = R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (!s || !t) return R35_ERR_BAD_ARGUMENT;
    if (r35_call_ready(s)) {
        rc = r37_stop_and_dispose(s, t, form);
    }
    r35_teardown_call(s);
    return rc;
}
/* R37_LIVE_READINESS_END */'''

# ---------------------------------------------------------------------------
# Wiring declarations: the telemetry instance and the bounded external STOP
# control installer.  Uses g_unix_signal_add (a GLib main-loop GSource,
# dispatched from the ordinary main loop -- never raw signal-handler work,
# never a polling construct) instead of a raw signal()+flag, so no complex
# work ever runs in a POSIX signal context and no periodic check of any kind
# is added.
# ---------------------------------------------------------------------------
WIRING_REGION = r'''/* R37_WIRING_BEGIN */
static R37BoundedStopTelemetry g_r37_telemetry;

/* Dispatched by GLib's own main loop when SIGUSR2 is delivered (g_unix_
 * signal_add uses a self-pipe/signalfd internally -- this callback never
 * runs in real POSIX signal context, satisfying "no complex work inside
 * the signal handler; defer to the normal main loop"). The watch is kept
 * installed (G_SOURCE_CONTINUE) rather than removed after first use:
 * idempotency is enforced by R35's own stop_sent/stop_count gate inside
 * r37_bounded_stop_request, not by tearing down the control point, so a
 * second delivery is safely rejected rather than silently dropped. */
static gboolean
r37_bounded_stop_signal_cb(gpointer data)
{
    R35Result rc;
    (void)data;
    rc = r37_bounded_stop_request(&g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);
    printf("BOUNDED_STOP_REQUEST_RECEIVED=%u\n", g_r37_telemetry.bounded_stop_request_received_count);
    printf("R37_BOUNDED_STOP_RESULT=%s\n", rc == R35_OK ? "STOP_SENT" : "REJECTED");
    printf("CALL_BOUND_MEDIA_STOP_SENT_COUNT=%u\n", g_r37_telemetry.call_bound_media_stop_sent_count);
    printf("RTP_DISARMED=%u\n", g_r37_telemetry.rtp_disarmed_count);
    printf("MEDIA_RX_CHANNEL_DISPOSED=%u\n", g_r37_telemetry.media_rx_channel_disposed_count);
    fflush(stdout);
    return G_SOURCE_CONTINUE;
}

static void
r37_install_bounded_stop_control(void)
{
    g_unix_signal_add(SIGUSR2, r37_bounded_stop_signal_cb, NULL);
    printf("R37_BOUNDED_STOP_CONTROL_KIND=SIGUSR2_UNIX_SIGNAL_SOURCE\n");
    fflush(stdout);
}
/* R37_WIRING_END */

'''

_WIRING_INSTALL_ANCHOR = '    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\\n");\n'
_WIRING_INSTALL_INSERTED = (
    '    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\\n");\n'
    "    r37_install_bounded_stop_control();\n"
)

# ---------------------------------------------------------------------------
# Protocol-stop wiring: recognizes a later CAPABILITY_REPORT clearing bit3,
# and RELEASE, on the SAME call-bound connection R35 already captured.
# Anchored immediately after R36's own wiring insertion in the SAME generic
# per-frame receive loop, so it sees the SAME already-parsed body/body_len
# R35/R36 already use, and is checked only after R36's own capabilities-
# OPEN match has already been tried and did not match (R36's block always
# `continue`s on a match, so control only reaches here for a frame that was
# not a bit3-set CAPABILITIES OPEN trigger).
# ---------------------------------------------------------------------------
_WIRING_PROTOCOL_STOP_ANCHOR = "            /* R36_WIRING_TRIGGER_END */"
_WIRING_PROTOCOL_STOP_INSERTED = r"""            /* R36_WIRING_TRIGGER_END */

            /* R37_WIRING_PROTOCOL_STOP_BEGIN */
            {
                R35CtpEnvelopeView r37_view;
                if (g_r35_session.writer &&
                    r35_parse_ctp_envelope(body, body_len, &r37_view) &&
                    r35_call_ready(&g_r35_session)) {
                    unsigned r37_local_connection =
                        (r37_view.connection ^ 0x8000u) & 0xFFFFu;
                    int r37_on_current_call =
                        (r37_local_connection == g_r35_session.call_ctp_connection);

                    if (r37_on_current_call &&
                        r37_view.flags == R35_CTP_FLAG_DATA &&
                        r37_view.inner_len >= R36_CAP_BODY_MIN_LEN &&
                        r35_read_be16(r37_view.inner_body) == R36_OP_CAPABILITIES &&
                        (r37_view.inner_body[4] & R36_CAP_VIDEO_REQUEST_BIT) == 0u) {

                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);

                        printf("R37_CAPABILITY_CLEARED_OBSERVED=true\n");
                        printf(
                            "R37_PROTOCOL_STOP_RESULT=%s\n",
                            r37_rc == R35_OK ? "STOP_SENT" : "NO_OP"
                        );
                        fflush(stdout);

                        p12_consume_post_ack(
                            frame_len
                        );

                        continue;
                    }

                    if (r37_on_current_call &&
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
                    }
                }
            }
            /* R37_WIRING_PROTOCOL_STOP_END */"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (
        CORE_BEGIN_MARKER,
        CORE_END_MARKER,
        WIRING_BEGIN_MARKER,
        WIRING_END_MARKER,
        WIRING_PROTOCOL_STOP_BEGIN_MARKER,
        WIRING_PROTOCOL_STOP_END_MARKER,
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R37_MARKER_GATE=FAIL marker={marker} count={candidate.count(marker)}")

    begin_idx = candidate.index(CORE_BEGIN_MARKER)
    end_idx = candidate.index(CORE_END_MARKER)
    if not begin_idx < end_idx:
        raise RuntimeError("R37_MARKER_ORDER_GATE=FAIL core begin/end out of order")

    core = extract_core_region(candidate)
    for forbidden in (
        "glib.h", "nice/agent.h", "GMainLoop", "gboolean", "guint", "NiceAgent",
        "PseudoTcpSocket", "socket(", "sendto(", "printf(", "fprintf(",
    ):
        if forbidden in core:
            raise RuntimeError(f"R37_CORE_DEPENDENCY_FREE_GATE=FAIL forbidden={forbidden}")

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
            raise RuntimeError(f"R37_CORE_FORBIDDEN_SYMBOL_GATE=FAIL forbidden={forbidden}")

    # The single most important gate this round: R37 must never define a new
    # OPEN path. R36's existing trigger is the only caller of
    # r35_allocate_media_rx_channel/r35_send_open in the whole candidate.
    wiring = candidate.split(WIRING_BEGIN_MARKER, 1)[1].split(WIRING_END_MARKER, 1)[0]
    protocol_stop = candidate.split(WIRING_PROTOCOL_STOP_BEGIN_MARKER, 1)[1].split(
        WIRING_PROTOCOL_STOP_END_MARKER, 1
    )[0]
    for region_name, region in (("core", core), ("wiring", wiring), ("protocol_stop", protocol_stop)):
        for forbidden_open_call in ("r35_allocate_media_rx_channel(", "r35_send_open(", "r37_send_open("):
            if forbidden_open_call in region:
                raise RuntimeError(
                    f"R37_NO_NEW_OPEN_PATH_GATE=FAIL region={region_name} forbidden={forbidden_open_call}"
                )

    for needle in ("r35_send_stop(", "r35_dispose_media_rx_channel(", "r35_call_ready(", "r35_teardown_call("):
        if needle not in core:
            raise RuntimeError(f"R37_REUSES_R35_GATE=FAIL missing={needle}")

    for forbidden_new_writer in ("r37_serialize_", "r37_build_call_bound_packet(", "r37_open_flags("):
        if forbidden_new_writer in core:
            raise RuntimeError(f"R37_NO_DUPLICATE_WRITER_GATE=FAIL forbidden={forbidden_new_writer}")

    # No polling/backoff construct of any kind, matching R35/R36's own "no
    # retry" discipline -- the bounded STOP control is event-driven
    # (g_unix_signal_add), never a periodic check.
    if "g_timeout_add" in wiring or "g_timeout_add" in protocol_stop:
        raise RuntimeError("R37_NO_RETRY_GATE=FAIL g_timeout_add found")
    if "g_unix_signal_add" not in wiring:
        raise RuntimeError("R37_UNIX_SIGNAL_SOURCE_GATE=FAIL")
    if "r37_bounded_stop_request(" not in wiring:
        raise RuntimeError("R37_WIRING_CALLS_BOUNDED_STOP_GATE=FAIL")
    if "r37_handle_capability_cleared(" not in protocol_stop:
        raise RuntimeError("R37_WIRING_CALLS_CAPABILITY_CLEAR_GATE=FAIL")
    if "r37_handle_remote_release(" not in protocol_stop:
        raise RuntimeError("R37_WIRING_CALLS_RELEASE_GATE=FAIL")


def extract_core_region(candidate: str) -> str:
    """Return exactly the text between the R37 core BEGIN/END markers (exclusive)."""
    begin = candidate.index(CORE_BEGIN_MARKER) + len(CORE_BEGIN_MARKER)
    end = candidate.index(CORE_END_MARKER)
    if end <= begin:
        raise RuntimeError("R37_CORE_EXTRACTION_GATE=FAIL empty or inverted region")
    return candidate[begin:end]


def transform(r36_source: str) -> str:
    """Apply the R37 live-readiness overlay to an already-R36-augmented C source.

    ``r36_source`` must already be the output of
    ``entrance_p116_r36_attached_media_trigger_transform.py``'s ``transform()``;
    this function never re-invokes that transform, R35's transform, the
    canonical P106/P116 generator, or any R34/R33 model, and never touches
    their digests. It is idempotent-checked: re-applying it to its own
    output raises, matching R35/R36's own re-application discipline.
    """
    if CORE_BEGIN_MARKER in r36_source:
        raise RuntimeError("R37_REAPPLY_GATE=FAIL transform already applied")
    if "R36_ATTACHED_MEDIA_TRIGGER_BEGIN" not in r36_source or "R36_WIRING_TRIGGER_BEGIN" not in r36_source:
        raise RuntimeError("R37_REQUIRES_R36_OVERLAY_GATE=FAIL input is not R36-augmented")

    candidate = r36_source

    # Add <glib-unix.h> once, at the top include block, for g_unix_signal_add.
    candidate = _replace_once(
        candidate,
        "#include <glib/gstdio.h>",
        "#include <glib/gstdio.h>\n#include <glib-unix.h>",
        "R37_GLIB_UNIX_INCLUDE",
    )

    # Insert the dependency-free core + wiring declarations immediately after
    # R36's own trigger core, so it can reference R35/R36's types/functions
    # (R35Result, R35AttachedMediaSession, R35CtpEnvelopeView, r35_read_be16,
    # r35_call_ready, r35_send_stop, r35_dispose_media_rx_channel,
    # r35_teardown_call, g_r35_session, R36_OP_CAPABILITIES,
    # R36_CAP_BODY_MIN_LEN, R36_CAP_VIDEO_REQUEST_BIT) without redeclaring
    # any of them.
    r36_trigger_core_end = "/* R36_ATTACHED_MEDIA_TRIGGER_END */"
    candidate = _replace_once(
        candidate,
        r36_trigger_core_end,
        r36_trigger_core_end + "\n\n" + CORE_REGION + "\n\n" + WIRING_REGION,
        "R37_CORE_AND_WIRING_INSERTION",
    )

    candidate = _replace_once(
        candidate,
        _WIRING_INSTALL_ANCHOR,
        _WIRING_INSTALL_INSERTED,
        "R37_BOUNDED_STOP_INSTALL_INSERTION",
    )

    candidate = _replace_once(
        candidate,
        _WIRING_PROTOCOL_STOP_ANCHOR,
        _WIRING_PROTOCOL_STOP_INSERTED,
        "R37_WIRING_PROTOCOL_STOP_INSERTION",
    )

    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS NATIVE TRANSFORM ===",
            "OVERLAY_STEP=SEPARATE_FROM_R36_CHAIN",
            "CORE_REGION_DEPENDENCY_FREE=true",
            "NEW_OPEN_PATH_ADDED=false",
            "BOUNDED_STOP_CONTROL_KIND=SIGUSR2_UNIX_SIGNAL_SOURCE",
            "PROTOCOL_STOP_CAUSES_WIRED=CAPABILITY_CLEARED,RELEASE",
            "REUSES_R35_SEND_STOP=true",
            "REUSES_R35_DISPOSE=true",
            "REUSES_R35_TEARDOWN=true",
            "DUPLICATE_WRITER_ADDED=false",
            "AUTOMATIC_RETRY_ADDED=false",
            "NEW_RUNTIME_DEPENDENCY_ADDED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS NATIVE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to an already-R36-augmented candidate C source (output of "
        "entrance_p116_r36_attached_media_trigger_transform.py).",
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
