#!/usr/bin/env python3
"""P116/R54: production-candidate call-adoption listener overlay.

Input lineage:
    frozen v1.5.7 listener/Door
    -> R42-b attached inbound media transform
    -> R54 call-adoption overlay

R54 reuses the R45 serializers and the canonical R53 profile state.  The only
production-specific bridge is the final peer-CAPABILITIES handler: after the
R53/R45 peer DATA ACK is emitted, it calls the existing R42 runtime media
trigger so MEDIAREQ26 OPEN still uses the runtime RTPC media RX channel.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r42b_listener_attached_media_transform as r42b
import entrance_p116_r45_call_adoption_core as r45
import entrance_p116_r53_call_adoption_profile_core as r53

BEGIN = "/* R54_CALL_ADOPTION_LISTENER_BEGIN */"
END = "/* R54_CALL_ADOPTION_LISTENER_END */"

EXPECTED_FROZEN_SHA256 = (
    "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
)

_R36_CORE_END = "/* R36_ATTACHED_MEDIA_TRIGGER_END */"
_R42_RUNTIME_END = "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */"

_ENUM_ANCHOR = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE
} P12TxKind;"""
_ENUM_REPLACEMENT = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_R54_INVITE_ACK,
    P12_TX_R54_LOCAL_CAPABILITIES,
    P12_TX_R54_LOCAL_ALERTING,
    P12_TX_R54_PEER_DATA_ACK
} P12TxKind;"""

_WRITER_ANCHOR = """    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        strcmp(semantic_kind, "MEDIA_OPEN") == 0
            ? P12_TX_R35_MEDIA_OPEN
            : P12_TX_R35_MEDIA_STOP);
"""
_WRITER_REPLACEMENT = """    P12TxKind r54_kind = P12_TX_R35_MEDIA_STOP;

    if (strcmp(semantic_kind, "MEDIA_OPEN") == 0) {
        r54_kind = P12_TX_R35_MEDIA_OPEN;
    } else if (strcmp(semantic_kind, "MEDIA_STOP") == 0) {
        r54_kind = P12_TX_R35_MEDIA_STOP;
    } else if (strcmp(semantic_kind, "CALL_INVITE_ACK") == 0) {
        r54_kind = P12_TX_R54_INVITE_ACK;
    } else if (strcmp(semantic_kind, "CALL_CAPABILITIES") == 0) {
        r54_kind = P12_TX_R54_LOCAL_CAPABILITIES;
    } else if (strcmp(semantic_kind, "CALL_ALERTING") == 0) {
        r54_kind = P12_TX_R54_LOCAL_ALERTING;
    } else if (strcmp(semantic_kind, "CALL_PEER_DATA_ACK") == 0) {
        r54_kind = P12_TX_R54_PEER_DATA_ACK;
    }

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        r54_kind);
"""

_CALL_INIT_CAPTURE_ANCHOR = """                    printf("R35_CALL_CTP_CAPTURED=true\\n");
                    printf(
                        "R42_CALL_GENERATION=%u\\n",
                        g_r35_session.call_generation
                    );
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\\n");
                }
                fflush(stdout);
"""
_CALL_INIT_CAPTURE_REPLACEMENT = """                    printf("R35_CALL_CTP_CAPTURED=true\\n");
                    printf(
                        "R42_CALL_GENERATION=%u\\n",
                        g_r35_session.call_generation
                    );
                    r54_handle_call_init(body, body_len);
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\\n");
                    r54_publish_diagnostics(&g_r54_call_adoption);
                }
                fflush(stdout);
"""

_R42_TRIGGER_ANCHOR = """                    gboolean r42_ok = r42_queue_media_channel_open();
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");
"""
_R42_TRIGGER_REPLACEMENT = """                    gboolean r42_ok = r54_handle_peer_capabilities_for_r42(&r42_view);
                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");
"""


R54_REGION = r'''/* R54_CALL_ADOPTION_LISTENER_BEGIN */
static R53CallAdoptionProfileState g_r54_call_adoption;

static void
r54_publish_diagnostics(const R53CallAdoptionProfileState *state)
{
    const R53Diagnostics *diag;
    if (!state) return;
    diag = &state->diag;
    printf("R54_CALL_ADOPTION_STARTED=%s\n", diag->call_adoption_started ? "true" : "false");
    printf("R54_INVITE_ACK_SENT=%s\n", diag->invite_ack_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITIES_SENT=%s\n", diag->local_capabilities_sent ? "true" : "false");
    printf("R54_LOCAL_CAPABILITY_WORD=%u\n", diag->local_capability_word);
    printf("R54_LOCAL_ALERTING_SENT=%s\n", diag->local_alerting_sent ? "true" : "false");
    printf("R54_WAITING_PEER_CAPABILITIES=%s\n", diag->waiting_peer_capabilities ? "true" : "false");
    printf("R54_PEER_CAPABILITIES_SEEN=%s\n", diag->peer_capabilities_seen ? "true" : "false");
    printf("R54_PEER_CAPABILITY_WORD=%u\n", diag->peer_capability_word);
    printf("R54_PEER_VIDEO_REQUESTED=%s\n", diag->peer_video_requested ? "true" : "false");
    printf("R54_PEER_DATA_ACK_SENT=%s\n", state->r45.inbound_ack_count > 0u ? "true" : "false");
    printf("R54_CALL_ADOPTION_FAILURE_STAGE=%s\n", r53_failure_stage_name(diag->call_adoption_failure_stage));
    fflush(stdout);
}

static gboolean
r54_handle_call_init(const guint8 *body, guint body_len)
{
    R35CtpEnvelopeView invite_view;
    gboolean ok = FALSE;

    if (r35_parse_ctp_envelope(body, body_len, &invite_view)) {
        ok = r53_start_after_call_capture(
            &g_r35_session,
            &g_r54_call_adoption,
            &invite_view) ? TRUE : FALSE;
    } else {
        g_r54_call_adoption.diag.call_adoption_failure_stage =
            R53_STAGE_ACK_BUILD_FAILED;
    }

    r54_publish_diagnostics(&g_r54_call_adoption);
    return ok;
}

static gboolean
r54_trigger_r42_media_open(
    R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *peer_view)
{
    (void)session;
    (void)peer_view;
    return r42_queue_media_channel_open();
}

static gboolean
r54_handle_peer_capabilities_for_r42(const R35CtpEnvelopeView *peer_view)
{
    gboolean ok = r53_handle_peer_capabilities_with_trigger(
            &g_r35_session,
            &g_r54_call_adoption,
            peer_view,
            r54_trigger_r42_media_open) ? TRUE : FALSE;
    r54_publish_diagnostics(&g_r54_call_adoption);
    return ok;
}
/* R54_CALL_ADOPTION_LISTENER_END */
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (
        r45.CORE_BEGIN_MARKER,
        r45.CORE_END_MARKER,
        r53.CORE_BEGIN_MARKER,
        r53.CORE_END_MARKER,
        BEGIN,
        END,
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R54_MARKER_GATE=FAIL marker={marker}")

    required = (
        "r53_start_after_call_capture(",
        "r45_accept_peer_data_and_ack(",
        "r53_handle_peer_capabilities_with_trigger(",
        "r42_queue_media_channel_open()",
        "R54_CALL_ADOPTION_STARTED=%s",
        "R54_INVITE_ACK_SENT=%s",
        "R54_LOCAL_CAPABILITIES_SENT=%s",
        "R54_LOCAL_CAPABILITY_WORD=%u",
        "R54_LOCAL_ALERTING_SENT=%s",
        "R54_WAITING_PEER_CAPABILITIES=%s",
        "R54_PEER_CAPABILITIES_SEEN=%s",
        "R54_PEER_CAPABILITY_WORD=%u",
        "R54_PEER_VIDEO_REQUESTED=%s",
        "R54_PEER_DATA_ACK_SENT=%s",
        "R54_CALL_ADOPTION_FAILURE_STAGE=%s",
        "P12_TX_R54_INVITE_ACK",
        "P12_TX_R54_PEER_DATA_ACK",
    )
    for needle in required:
        if needle not in candidate:
            raise RuntimeError(f"R54_FINAL_GATE=FAIL missing={needle}")

    if candidate.count("gboolean r42_ok = r54_handle_peer_capabilities_for_r42(&r42_view);") != 1:
        raise RuntimeError("R54_R42_TRIGGER_REPLACEMENT_GATE=FAIL")
    if "gboolean r42_ok = r42_queue_media_channel_open();" in candidate:
        raise RuntimeError("R54_DIRECT_R42_TRIGGER_GATE=FAIL")
    if candidate.count("static int r53_handle_peer_capabilities_with_trigger(") != 1:
        raise RuntimeError("R54_SINGLE_PEER_CHAIN_OWNER_GATE=FAIL")
    if candidate.count("r42_queue_media_channel_open()") != 1:
        raise RuntimeError("R54_QUEUE_MEDIA_OPEN_CALL_SITE_GATE=FAIL")
    listener_region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for duplicate_chain_needle in (
        "r36_is_capabilities_for_current_call(",
        "r53_peer_capability_word(",
        "r36_capabilities_video_requested(",
        "r45_accept_peer_data_and_ack(",
    ):
        if duplicate_chain_needle in listener_region:
            raise RuntimeError(
                f"R54_DUPLICATE_PEER_CHAIN_GATE=FAIL needle={duplicate_chain_needle}"
            )
    if candidate.count("signal(SIGUSR1, v4_door_signal_handler);") != 1:
        raise RuntimeError("R54_DOOR_SIGUSR1_PRESERVATION_GATE=FAIL")
    if "v4_door_tick_cb" not in candidate:
        raise RuntimeError("R54_DOOR_TICK_PRESERVATION_GATE=FAIL")
    for forbidden in (
        "startAudioTX",
        "PT8_GENERATOR",
        "microphone",
        "entrance_self_activation",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "signal(SIGUSR1, SIG_IGN);",
    ):
        if forbidden in candidate:
            raise RuntimeError(f"R54_FORBIDDEN_GATE=FAIL needle={forbidden}")


def transform(source: str) -> str:
    if BEGIN in source or r53.CORE_BEGIN_MARKER in source:
        raise RuntimeError("R54_REAPPLY_GATE=FAIL")

    candidate = r42b.transform(source)
    candidate = _replace_once(
        candidate,
        _R36_CORE_END,
        _R36_CORE_END + "\n\n" + r45.CORE_REGION + "\n\n" + r53.CORE_REGION,
        "R54 R45/R53 dependency insertion",
    )
    candidate = _replace_once(
        candidate,
        _R42_RUNTIME_END,
        _R42_RUNTIME_END + "\n\n" + R54_REGION,
        "R54 listener bridge insertion",
    )
    candidate = _replace_once(
        candidate,
        _ENUM_ANCHOR,
        _ENUM_REPLACEMENT,
        "R54 P12 tx kind extension",
    )
    candidate = _replace_once(
        candidate,
        _WRITER_ANCHOR,
        _WRITER_REPLACEMENT,
        "R54 call signaling writer mapping",
    )
    candidate = _replace_once(
        candidate,
        _CALL_INIT_CAPTURE_ANCHOR,
        _CALL_INIT_CAPTURE_REPLACEMENT,
        "R54 CALL_INIT adoption start",
    )
    candidate = _replace_once(
        candidate,
        _R42_TRIGGER_ANCHOR,
        _R42_TRIGGER_REPLACEMENT,
        "R54 peer ACK before R42 media trigger",
    )
    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R54 CALL ADOPTION LISTENER TRANSFORM ===",
            "BASE_LINEAGE=FROZEN_V1_5_7_PERSISTENT_LISTENER_DOOR",
            "R42B_TRANSFORM_REUSED=true",
            "R45_SERIALIZERS_REUSED=true",
            "R53_PROFILE_CORE_REUSED=true",
            "HELPER_CAPABILITY_PROFILE_VALUE=0x00000027",
            "CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false",
            "CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN",
            "CALLFSM_840_POSSIBLY_UNINITIALIZED=true",
            "CAPTURE_LITERAL_REPLAY_USED=false",
            "AUDIO_TX_ADDED=false",
            "AUTOMATIC_RETRY=false",
            "ONE_MEDIA_OPEN_PER_GENERATION=true",
            "DOOR_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R54 CALL ADOPTION LISTENER TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    source = args.source.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if source_sha != EXPECTED_FROZEN_SHA256:
        raise SystemExit(f"FROZEN_BASE_SHA256_GATE=FAIL actual={source_sha}")

    if args.report:
        print(report())
        if args.output is None:
            return 0

    if args.output is None:
        parser.error("--output is required")

    args.output.write_text(transform(source), encoding="utf-8")
    print("R54_CALL_ADOPTION_LISTENER_TRANSFORM=PASS")
    print("FROZEN_BASE_SHA256_GATE=PASS")
    print("R42B_TRANSFORM_GATE=PASS")
    print("R54_TRANSFORM_GATE=PASS")
    print("DOOR_SEMANTICS_CHANGED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
