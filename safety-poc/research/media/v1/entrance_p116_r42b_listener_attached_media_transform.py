#!/usr/bin/env python3
"""P116/R42-b: compose attached inbound media onto the production listener.

This transform deliberately does NOT use the P80/P106 media-helper ownership
lineage.  Its input is the frozen v1.5.7 persistent listener/Door source.

Composition:
    production v1.5.7 listener
    -> listener-owned loopback RTP bridge only
    -> R35 call-bound MEDIAREQ core/wiring
    -> R36 CAPABILITIES trigger
    -> listener-compatible R37 stop/teardown wiring
    -> R42 physical-capture-validated media-channel runtime

The resulting helper remains the single persistent listener process:
RUN_DIR stays /run/comelit-p2p, SIGUSR1 Door stays installed, the Door tick
source stays installed, no self-activation path is introduced, and SIGUSR2 is
added only as the bounded attached-media STOP control.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_p80_ha_media_runtime_transform import P80_RTP_RUNTIME
import entrance_p116_r35_attached_media_native_transform as r35
import entrance_p116_r36_attached_media_trigger_transform as r36
import entrance_p116_r37_attached_media_live_readiness_transform as r37
import entrance_p116_r42_attached_media_runtime_transform as r42

BRIDGE_BEGIN = "/* R42_LISTENER_RTP_BRIDGE_BEGIN */"
BRIDGE_END = "/* R42_LISTENER_RTP_BRIDGE_END */"

_SOCKET_INCLUDE_ANCHOR = "#include <signal.h>\n"
_RTP_STATE_ANCHOR = "static guint64 pseudotcp_app_bytes_in = 0;\n"
_RECV_SIGNATURE = """static void
recv_cb(
"""
_R35_ARM_OLD = "    p80_media_forwarding_enabled = armed ? TRUE : FALSE;\n"
_R35_ARM_NEW = "    r42_listener_rtp_arm(armed);\n"
_DOOR_SIGNAL_INSTALL = "    signal(SIGUSR1, v4_door_signal_handler);\n"

# --- P116/R42-b canary observability: bounded scalar diagnostic markers ---
#
# None of these touch Door/Gate/self-activation/capture-literal control flow.
# Each new printf pairs a call-generation marker with one already-existing
# channel-lifecycle event so the HA-side status JSON can bind every value to
# the call generation it came from (see COMELIT-P116-R42B-CANARY-OBSERVABILITY-001).
_CALL_GENERATION_CAPTURE_ANCHOR = (
    '                    printf("R35_CALL_CTP_CAPTURED=true\\n");\n'
)
_CALL_GENERATION_CAPTURE_REPLACEMENT = (
    _CALL_GENERATION_CAPTURE_ANCHOR
    + '                    printf(\n'
    + '                        "R42_CALL_GENERATION=%u\\n",\n'
    + '                        g_r35_session.call_generation\n'
    + '                    );\n'
)

_MEDIA_CHANNEL_ALLOCATED_ANCHOR = (
    '    printf("R42_MEDIA_CHANNEL_ALLOCATED=true\\n");\n'
    '    printf("R42_CAPTURE_CHANNEL_LITERAL_USED=false\\n");\n'
    '    fflush(stdout);\n'
)
_MEDIA_CHANNEL_ALLOCATED_REPLACEMENT = (
    '    printf("R42_MEDIA_CHANNEL_ALLOCATED=true\\n");\n'
    '    printf("R42_CAPTURE_CHANNEL_LITERAL_USED=false\\n");\n'
    '    printf("R42_CALL_GENERATION=%u\\n", g_r35_session.call_generation);\n'
    '    printf("R42_MEDIA_CHANNEL_ID=%u\\n", (unsigned)r42_media_channel_id);\n'
    '    fflush(stdout);\n'
)

_MEDIAREQ26_OPEN_ANCHOR = (
    '    printf("R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED\\n");\n'
    '    fflush(stdout);\n'
)
_MEDIAREQ26_OPEN_REPLACEMENT = (
    '    printf("R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED\\n");\n'
    '    printf("R42_CALL_GENERATION=%u\\n", g_r35_session.call_generation);\n'
    '    printf(\n'
    '        "R42_MEDIAREQ26_OPEN_CHANNEL=%u\\n",\n'
    '        (unsigned)r42_media_channel_id\n'
    '    );\n'
    '    fflush(stdout);\n'
)

_MEDIA_STOP_SENT_ANCHOR = (
    '                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\\n");\n'
    '                fflush(stdout);\n'
)
_MEDIA_STOP_SENT_REPLACEMENT = (
    '                printf("R42_ATTACHED_MEDIA_STOP_SENT=true\\n");\n'
    '                printf(\n'
    '                    "R42_CALL_GENERATION=%u\\n",\n'
    '                    g_r35_session.call_generation\n'
    '                );\n'
    '                printf(\n'
    '                    "R42_MEDIA_STOP_CHANNEL=%u\\n",\n'
    '                    (unsigned)r42_media_channel_id\n'
    '                );\n'
    '                fflush(stdout);\n'
)

_MEDIA_CHANNEL_CLOSED_ANCHOR = (
    '    r42_media_stage = R42_MEDIA_CLOSED;\n'
    '    r42_media_channel_id = 0u;\n'
    '    printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");\n'
    '    fflush(stdout);\n'
)
_MEDIA_CHANNEL_CLOSED_REPLACEMENT = (
    '    r42_media_stage = R42_MEDIA_CLOSED;\n'
    '    r42_media_channel_id = 0u;\n'
    '    printf("R42_CALL_GENERATION=%u\\n", g_r35_session.call_generation);\n'
    '    printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");\n'
    '    fflush(stdout);\n'
)


def add_media_diagnostics_markers(candidate: str) -> str:
    """Add bounded call-generation/channel scalar markers for HA observability.

    Every value printed here already exists as a runtime variable
    (``g_r35_session.call_generation``, ``r42_media_channel_id``); no new
    control path, no capture literal, no raw payload bytes.
    """
    generation_markers_before = candidate.count("R42_CALL_GENERATION=%u")
    out = _replace_once(
        candidate,
        _MEDIA_CHANNEL_ALLOCATED_ANCHOR,
        _MEDIA_CHANNEL_ALLOCATED_REPLACEMENT,
        "R42B canary media channel id marker",
    )
    out = _replace_once(
        out,
        _MEDIAREQ26_OPEN_ANCHOR,
        _MEDIAREQ26_OPEN_REPLACEMENT,
        "R42B canary mediareq26 open channel marker",
    )
    out = _replace_once(
        out,
        _MEDIA_STOP_SENT_ANCHOR,
        _MEDIA_STOP_SENT_REPLACEMENT,
        "R42B canary stop channel marker",
    )
    out = _replace_once(
        out,
        _MEDIA_CHANNEL_CLOSED_ANCHOR,
        _MEDIA_CHANNEL_CLOSED_REPLACEMENT,
        "R42B canary channel closed generation marker",
    )

    for needle in (
        "R42_CALL_GENERATION=%u",
        "R42_MEDIA_CHANNEL_ID=%u",
        "R42_MEDIAREQ26_OPEN_CHANNEL=%u",
        "R42_MEDIA_STOP_CHANNEL=%u",
    ):
        if needle not in out:
            raise RuntimeError(f"R42B_CANARY_MARKER_GATE=FAIL needle={needle}")
    if out.count("R42_CALL_GENERATION=%u") != generation_markers_before + 4:
        raise RuntimeError("R42B_CANARY_GENERATION_BINDING_GATE=FAIL")
    for capture_literal in ("0x0C4A", "0x4A5A", "0xCA5A"):
        if capture_literal in out:
            raise RuntimeError(
                f"R42B_CANARY_CAPTURE_LITERAL_GATE=FAIL needle={capture_literal}"
            )
    return out


# --- P116/R42-b failure-forensic observability (DEV corrective round 2) ---
#
# Bounded, READ-ONLY diagnostics for the CAPABILITIES trigger candidate
# frame. Every new marker only reads a result already computed by the
# existing, unmodified R35/R36/R42 predicates
# (r35_parse_ctp_envelope/r35_call_ready/r36_capabilities_video_requested) or
# an existing local (r42_ok); this overlay adds no second OPEN/STOP writer,
# no new decision that changes which branch runs, and no retry loop. See
# COMELIT-P116-R42B-CANARY-OBSERVABILITY-001 (DEV corrective #2, failure
# forensic round).
_CAPABILITIES_DIAG_STATE_ANCHOR = (
    "static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;\n"
)
_CAPABILITIES_DIAG_STATE_REPLACEMENT = (
    "/* R42_CAPABILITIES_DIAGNOSTICS_STATE_BEGIN */\n"
    "static unsigned r42_diag_call_generation = 0;\n"
    "static unsigned r42_diag_candidate_count = 0;\n"
    "static unsigned r42_diag_detail_lines_printed = 0;\n"
    "#define R42_DIAG_DETAIL_LINE_LIMIT 8u\n"
    "/*\n"
    " * Pre-candidate rejection stages have their OWN bounded budget: each of\n"
    " * NO_WRITER/ENVELOPE/FLAG/OPCODE is published at most ONCE per call\n"
    " * generation, so a burst of unrelated frames cannot exhaust the\n"
    " * candidate detail-line budget before a real CAPABILITIES frame arrives.\n"
    " */\n"
    "#define R42_DIAG_PRE_NO_WRITER (1u << 0)\n"
    "#define R42_DIAG_PRE_ENVELOPE  (1u << 1)\n"
    "#define R42_DIAG_PRE_FLAG      (1u << 2)\n"
    "#define R42_DIAG_PRE_OPCODE    (1u << 3)\n"
    "static unsigned r42_diag_pre_seen_mask = 0u;\n"
    "\n"
    "static unsigned\n"
    "r42_diag_pre_stage_bit(\n"
    "    int writer_present,\n"
    "    int envelope_parsed,\n"
    "    int data_flag,\n"
    "    int capabilities_opcode)\n"
    "{\n"
    "    if (!writer_present) {\n"
    "        return R42_DIAG_PRE_NO_WRITER;\n"
    "    }\n"
    "    if (!envelope_parsed) {\n"
    "        return R42_DIAG_PRE_ENVELOPE;\n"
    "    }\n"
    "    if (!data_flag) {\n"
    "        return R42_DIAG_PRE_FLAG;\n"
    "    }\n"
    "    if (!capabilities_opcode) {\n"
    "        return R42_DIAG_PRE_OPCODE;\n"
    "    }\n"
    "    return 0u;\n"
    "}\n"
    "\n"
    "static int\n"
    "r42_diag_pre_stage_should_emit(unsigned *seen_mask, unsigned stage_bit)\n"
    "{\n"
    "    if (seen_mask == 0 || stage_bit == 0u) {\n"
    "        return 0;\n"
    "    }\n"
    "    if ((*seen_mask & stage_bit) != 0u) {\n"
    "        return 0;\n"
    "    }\n"
    "    *seen_mask |= stage_bit;\n"
    "    return 1;\n"
    "}\n"
    "\n"
    "static const char *\n"
    "r42_diag_pre_stage_name(unsigned stage_bit)\n"
    "{\n"
    "    switch (stage_bit) {\n"
    "    case R42_DIAG_PRE_NO_WRITER:\n"
    '        return "NO_WRITER";\n'
    "    case R42_DIAG_PRE_ENVELOPE:\n"
    '        return "ENVELOPE";\n'
    "    case R42_DIAG_PRE_FLAG:\n"
    '        return "FLAG";\n'
    "    case R42_DIAG_PRE_OPCODE:\n"
    '        return "OPCODE";\n'
    "    default:\n"
    '        return "NONE";\n'
    "    }\n"
    "}\n"
    "/* R42_CAPABILITIES_DIAGNOSTICS_STATE_END */\n"
    + _CAPABILITIES_DIAG_STATE_ANCHOR
)

_CAPABILITIES_DIAG_TRIGGER_ANCHOR = (
    "            {\n"
    "                R35CtpEnvelopeView r42_view;\n"
    "                if (g_r35_session.writer &&\n"
)
_CAPABILITIES_DIAG_TRIGGER_BLOCK = (
    "            /* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */\n"
    "            if (r42_diag_call_generation != g_r35_session.call_generation) {\n"
    "                r42_diag_call_generation = g_r35_session.call_generation;\n"
    "                r42_diag_candidate_count = 0;\n"
    "                r42_diag_detail_lines_printed = 0;\n"
    "                r42_diag_pre_seen_mask = 0u;\n"
    "            }\n"
    "\n"
    "            {\n"
    "                int r42_diag_writer_ok = g_r35_session.writer ? 1 : 0;\n"
    "                int r42_diag_envelope_ok = 0;\n"
    "                int r42_diag_data_flag = 0;\n"
    "                int r42_diag_opcode_ok = 0;\n"
    "                int r42_diag_candidate_seen = 0;\n"
    "                int r42_diag_view_valid = 0;\n"
    "                unsigned r42_diag_pre_bit = 0u;\n"
    "                R35CtpEnvelopeView r42_diag_view;\n"
    "\n"
    "                if (r42_diag_writer_ok &&\n"
    "                    r35_parse_ctp_envelope(\n"
    "                        body, body_len, &r42_diag_view)) {\n"
    "                    r42_diag_view_valid = 1;\n"
    "                    r42_diag_envelope_ok = 1;\n"
    "                    if (r42_diag_view.flags == R35_CTP_FLAG_DATA) {\n"
    "                        r42_diag_data_flag = 1;\n"
    "                        if (r42_diag_view.inner_len >= 2u &&\n"
    "                            r35_read_be16(r42_diag_view.inner_body) ==\n"
    "                                R36_OP_CAPABILITIES) {\n"
    "                            r42_diag_opcode_ok = 1;\n"
    "                        }\n"
    "                    }\n"
    "                }\n"
    "\n"
    "                r42_diag_pre_bit = r42_diag_pre_stage_bit(\n"
    "                    r42_diag_writer_ok,\n"
    "                    r42_diag_envelope_ok,\n"
    "                    r42_diag_data_flag,\n"
    "                    r42_diag_opcode_ok);\n"
    "\n"
    "                if (r42_diag_pre_bit != 0u) {\n"
    "                    /*\n"
    "                     * Pre-candidate rejection: once per stage per\n"
    "                     * generation, on its own budget, so unrelated\n"
    "                     * traffic cannot hide a later real candidate.\n"
    "                     */\n"
    "                    if (r42_diag_pre_stage_should_emit(\n"
    "                            &r42_diag_pre_seen_mask, r42_diag_pre_bit)) {\n"
    '                        printf("R42_CAPABILITIES_CANDIDATE_SEEN=false\\n");\n'
    "                        if (r42_diag_envelope_ok) {\n"
    '                            printf("R42_CAPABILITIES_PARSE_OK=true\\n");\n'
    "                        } else {\n"
    '                            printf("R42_CAPABILITIES_PARSE_OK=false\\n");\n'
    "                        }\n"
    '                        printf("R42_CAPABILITIES_CALL_MATCH=false\\n");\n'
    '                        printf("R42_CAPABILITIES_VIDEO_REQUESTED=false\\n");\n'
    "                        printf(\n"
    '                            "R42_TRIGGER_REJECT_STAGE=%s\\n",\n'
    "                            r42_diag_pre_stage_name(r42_diag_pre_bit)\n"
    "                        );\n"
    '                        printf("R42_CAPABILITIES_CANDIDATE_COUNT=0\\n");\n'
    "                        fflush(stdout);\n"
    "                    }\n"
    "                } else if (r42_diag_view_valid) {\n"
    "                    int r42_diag_parse_ok = 1;\n"
    "                    int r42_diag_call_match = 0;\n"
    "                    int r42_diag_video_requested = 0;\n"
    '                    const char *r42_diag_stage = "NONE";\n'
    "\n"
    "                    r42_diag_candidate_seen = 1;\n"
    "                    r42_diag_candidate_count++;\n"
    "                    if (r42_diag_view.inner_len < R36_CAP_BODY_MIN_LEN) {\n"
    '                        r42_diag_stage = "LENGTH";\n'
    "                    } else if (!r35_call_ready(&g_r35_session)) {\n"
    '                        r42_diag_stage = "NO_LIVE_CALL";\n'
    "                    } else {\n"
    "                        unsigned r42_diag_local_connection =\n"
    "                            (r42_diag_view.connection ^ 0x8000u) & 0xFFFFu;\n"
    "                        r42_diag_call_match =\n"
    "                            (r42_diag_local_connection ==\n"
    "                             g_r35_session.call_ctp_connection) ? 1 : 0;\n"
    "                        if (!r42_diag_call_match) {\n"
    '                            r42_diag_stage = "CONNECTION_MISMATCH";\n'
    "                        } else {\n"
    "                            r42_diag_video_requested =\n"
    "                                r36_capabilities_video_requested(\n"
    "                                    &r42_diag_view) ? 1 : 0;\n"
    "                            if (!r42_diag_video_requested) {\n"
    '                                r42_diag_stage = "VIDEO_BIT_CLEAR";\n'
    "                            }\n"
    "                        }\n"
    "                    }\n"
    "\n"
    "                    if (r42_diag_candidate_seen &&\n"
    "                        r42_diag_detail_lines_printed <\n"
    "                            R42_DIAG_DETAIL_LINE_LIMIT) {\n"
    "                        r42_diag_detail_lines_printed++;\n"
    '                        printf("R42_CAPABILITIES_CANDIDATE_SEEN=true\\n");\n'
    "                        printf(\n"
    '                            "R42_CAPABILITIES_PARSE_OK=%s\\n",\n'
    '                            r42_diag_parse_ok ? "true" : "false"\n'
    "                        );\n"
    "                        printf(\n"
    '                            "R42_CAPABILITIES_CALL_MATCH=%s\\n",\n'
    '                            r42_diag_call_match ? "true" : "false"\n'
    "                        );\n"
    "                        printf(\n"
    '                            "R42_CAPABILITIES_VIDEO_REQUESTED=%s\\n",\n'
    '                            r42_diag_video_requested ? "true" : "false"\n'
    "                        );\n"
    "                        printf(\n"
    '                            "R42_TRIGGER_REJECT_STAGE=%s\\n",\n'
    "                            r42_diag_stage\n"
    "                        );\n"
    "                        printf(\n"
    '                            "R42_CAPABILITIES_CANDIDATE_COUNT=%u\\n",\n'
    "                            r42_diag_candidate_count\n"
    "                        );\n"
    "                        fflush(stdout);\n"
    "                    }\n"
    "                }\n"
    "            }\n"
    "            /* R42_CAPABILITIES_DIAGNOSTICS_END */\n"
    "\n"
)
_CAPABILITIES_DIAG_TRIGGER_REPLACEMENT = (
    _CAPABILITIES_DIAG_TRIGGER_BLOCK + _CAPABILITIES_DIAG_TRIGGER_ANCHOR
)

_CAPABILITIES_DIAG_RESULT_ANCHOR = (
    "                    gboolean r42_ok = r42_queue_media_channel_open();\n"
    '                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");\n'
    "                    printf(\n"
    '                        "R42_ATTACHED_TRIGGER_RESULT=%s\\n",\n'
    '                        r42_ok ? "CHANNEL_OPEN_SENT" : "REJECTED"\n'
    "                    );\n"
    '                    printf("R42_AUTOMATIC_RETRY=false\\n");\n'
    "                    fflush(stdout);\n"
)
_CAPABILITIES_DIAG_RESULT_REPLACEMENT = (
    "                    gboolean r42_ok = r42_queue_media_channel_open();\n"
    '                    printf("R42_ATTACHED_TRIGGER_MATCH=true\\n");\n'
    "                    printf(\n"
    '                        "R42_ATTACHED_TRIGGER_RESULT=%s\\n",\n'
    '                        r42_ok ? "CHANNEL_OPEN_SENT" : "REJECTED"\n'
    "                    );\n"
    "                    printf(\n"
    '                        "R42_TRIGGER_REJECT_STAGE=%s\\n",\n'
    '                        r42_ok ? "OPEN_SENT" : "QUEUE_REJECTED"\n'
    "                    );\n"
    '                    printf("R42_AUTOMATIC_RETRY=false\\n");\n'
    "                    fflush(stdout);\n"
)


def add_capabilities_trigger_diagnostics(candidate: str) -> str:
    """Add bounded, read-only CAPABILITIES-candidate-frame observability.

    Classifies every frame that structurally looks like a CAPABILITIES
    candidate (parsed CTP envelope + FLAG_DATA + inner opcode 0x0003) into
    exactly one ``R42_TRIGGER_REJECT_STAGE`` outcome, so the next canary can
    distinguish "no candidate frame arrived" from "arrived but rejected at
    envelope/flag/opcode/length/call-match/video-bit" from "matched and an
    OPEN was attempted". Nothing here changes which branch the EXISTING,
    unmodified functional trigger takes: the new code never calls
    ``continue``/``return``, never queues a frame, and never invokes
    ``r42_queue_media_channel_open`` (verified below by an unchanged call
    count) -- it only re-evaluates the same read-only predicates the
    existing trigger already calls, purely to classify and print.
    """
    queue_open_calls_before = candidate.count("r42_queue_media_channel_open(")

    out = _replace_once(
        candidate,
        _CAPABILITIES_DIAG_STATE_ANCHOR,
        _CAPABILITIES_DIAG_STATE_REPLACEMENT,
        "R42B capabilities diagnostics state",
    )
    out = _replace_once(
        out,
        _CAPABILITIES_DIAG_TRIGGER_ANCHOR,
        _CAPABILITIES_DIAG_TRIGGER_REPLACEMENT,
        "R42B capabilities candidate diagnostics",
    )
    out = _replace_once(
        out,
        _CAPABILITIES_DIAG_RESULT_ANCHOR,
        _CAPABILITIES_DIAG_RESULT_REPLACEMENT,
        "R42B capabilities trigger outcome diagnostics",
    )

    if out.count("r42_queue_media_channel_open(") != queue_open_calls_before:
        raise RuntimeError("R42B_CAPABILITIES_DIAG_NO_NEW_OPEN_CALL_GATE=FAIL")

    diag_region = out.split(
        "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */", 1
    )[1].split("/* R42_CAPABILITIES_DIAGNOSTICS_END */", 1)[0]
    if "g_timeout_add" in diag_region or "retry" in diag_region.lower():
        raise RuntimeError("R42B_CAPABILITIES_DIAG_NO_RETRY_GATE=FAIL")
    if "continue;" in diag_region or "return" in diag_region:
        raise RuntimeError("R42B_CAPABILITIES_DIAG_NO_CONTROL_FLOW_GATE=FAIL")

    for needle in (
        "R42_CAPABILITIES_CANDIDATE_SEEN=true",
        "R42_CAPABILITIES_PARSE_OK=%s",
        "R42_CAPABILITIES_CALL_MATCH=%s",
        "R42_CAPABILITIES_VIDEO_REQUESTED=%s",
        "R42_TRIGGER_REJECT_STAGE=%s",
        "R42_CAPABILITIES_CANDIDATE_COUNT=%u",
        # Pre-candidate rejection stages are published on their own
        # once-per-generation budget; without these sites a frame that fails
        # the envelope/flag/opcode checks stays invisible and the next canary
        # cannot tell "no traffic at all" from "rejected this early".
        "R42_CAPABILITIES_CANDIDATE_SEEN=false",
        "R42_CAPABILITIES_PARSE_OK=true",
        "R42_CAPABILITIES_PARSE_OK=false",
        "R42_CAPABILITIES_CALL_MATCH=false",
        "R42_CAPABILITIES_VIDEO_REQUESTED=false",
        "R42_CAPABILITIES_CANDIDATE_COUNT=0",
        "r42_diag_pre_stage_should_emit(",
        "r42_diag_pre_stage_name(",
    ):
        if needle not in out:
            raise RuntimeError(
                f"R42B_CAPABILITIES_DIAG_MARKER_GATE=FAIL needle={needle}"
            )
    # Once from the pre-candidate block, once from the candidate
    # classification block, once more from the real trigger-outcome site
    # (OPEN_SENT/QUEUE_REJECTED).
    if out.count("R42_TRIGGER_REJECT_STAGE=%s") != 3:
        raise RuntimeError("R42B_CAPABILITIES_DIAG_REJECT_STAGE_SITE_GATE=FAIL")
    if "R42_DIAG_PRE_MASK_ALL" in out:
        raise RuntimeError("R42B_CAPABILITIES_DIAG_UNBOUNDED_MASK_GATE=FAIL")

    for capture_literal in ("0x0C4A", "0x4A5A", "0xCA5A"):
        if capture_literal in out:
            raise RuntimeError(
                f"R42B_CAPABILITIES_DIAG_CAPTURE_LITERAL_GATE=FAIL "
                f"needle={capture_literal}"
            )
    return out


_LISTENER_RTP_CONTROL = r'''
/* R42_LISTENER_RTP_BRIDGE_BEGIN */
static void
r42_listener_rtp_reset_lifetime(void)
{
    p80_video_profile_seen = FALSE;
    p80_audio_profile_seen = FALSE;
    memset(p80_video_profile, 0, sizeof(p80_video_profile));
    memset(p80_audio_profile, 0, sizeof(p80_audio_profile));
    p80_video_rtp_packets = 0;
    p80_audio_rtp_packets = 0;

    memset(&p116_video_rtp, 0, sizeof(p116_video_rtp));
    p116_video_rtp.payload_type = 99u;
    p116_video_rtp.is_video = TRUE;

    memset(&p116_audio_rtp, 0, sizeof(p116_audio_rtp));
    p116_audio_rtp.payload_type = 8u;
    p116_audio_rtp.is_video = FALSE;
}

static void
r42_listener_rtp_arm(int armed)
{
    if (armed) {
        if (!p80_media_forwarding_enabled)
            r42_listener_rtp_reset_lifetime();
        p80_media_forwarding_enabled = TRUE;
        printf("R42_LISTENER_RTP_LIFETIME_RESET=true\n");
        printf("R42_LISTENER_RTP_FORWARDING_ARMED=true\n");
    } else {
        p80_media_forwarding_enabled = FALSE;
        printf("R42_LISTENER_RTP_FORWARDING_ARMED=false\n");
    }
    fflush(stdout);
}
/* R42_LISTENER_RTP_BRIDGE_END */
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _block_end(text: str, opening_brace: int) -> int:
    depth = 0
    state = "normal"
    i = opening_brace
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "normal":
            if ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "/" and nxt == "/":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        elif state in {"string", "char"}:
            if ch == "\\":
                i += 1
            elif (state == "string" and ch == '"') or (
                state == "char" and ch == "'"
            ):
                state = "normal"
        elif state == "line_comment":
            if ch == "\n":
                state = "normal"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 1
        i += 1
    raise RuntimeError("R42_LISTENER_BLOCK_PARSE=FAIL")


def _replace_recv_function(text: str) -> str:
    start = text.find(_RECV_SIGNATURE)
    if start < 0 or text.find(_RECV_SIGNATURE, start + 1) >= 0:
        raise RuntimeError("R42_LISTENER_RECV_SIGNATURE_GATE=FAIL")
    opening = text.find("{", start + len(_RECV_SIGNATURE))
    if opening < 0:
        raise RuntimeError("R42_LISTENER_RECV_OPEN_GATE=FAIL")
    end = _block_end(text, opening)
    recv = text[start:end]

    anchor = "    if (!pseudo_tcp) {\n"
    replacement = (
        "    if (p80_try_forward_wrapped_rtp((const guint8 *)buf, len))\n"
        "        return;\n\n"
        + anchor
    )
    recv = _replace_once(recv, anchor, replacement, "R42 listener RTP recv intercept")
    return text[:start] + recv + text[end:]


def add_listener_rtp_bridge(source: str) -> str:
    if BRIDGE_BEGIN in source:
        raise RuntimeError("R42_LISTENER_BRIDGE_REAPPLY_GATE=FAIL")
    if '#define RUN_DIR     "/run/comelit-p2p"' not in source:
        raise RuntimeError("R42_LISTENER_RUN_DIR_INPUT_GATE=FAIL")
    if _DOOR_SIGNAL_INSTALL not in source:
        raise RuntimeError("R42_LISTENER_DOOR_SIGNAL_INPUT_GATE=FAIL")

    out = _replace_once(
        source,
        _SOCKET_INCLUDE_ANCHOR,
        _SOCKET_INCLUDE_ANCHOR
        + "#include <sys/socket.h>\n"
        + "#include <netinet/in.h>\n",
        "R42 listener socket includes",
    )
    out = _replace_once(
        out,
        _RTP_STATE_ANCHOR,
        _RTP_STATE_ANCHOR + P80_RTP_RUNTIME + "\n" + _LISTENER_RTP_CONTROL,
        "R42 listener RTP runtime",
    )
    out = _replace_recv_function(out)

    if out.count(BRIDGE_BEGIN) != 1 or out.count(BRIDGE_END) != 1:
        raise RuntimeError("R42_LISTENER_BRIDGE_MARKER_GATE=FAIL")
    if '#define RUN_DIR     "/run/comelit-p2p"' not in out:
        raise RuntimeError("R42_LISTENER_RUN_DIR_PRESERVATION_GATE=FAIL")
    if "/run/comelit-media" in out:
        raise RuntimeError("R42_LISTENER_MEDIA_RUN_DIR_FORBIDDEN_GATE=FAIL")
    if out.count(_DOOR_SIGNAL_INSTALL) != 1:
        raise RuntimeError("R42_LISTENER_DOOR_SIGNAL_PRESERVATION_GATE=FAIL")
    return out


def add_listener_r37(r36_source: str) -> str:
    if r37.CORE_BEGIN_MARKER in r36_source:
        raise RuntimeError("R42_LISTENER_R37_REAPPLY_GATE=FAIL")
    if "R36_ATTACHED_MEDIA_TRIGGER_BEGIN" not in r36_source:
        raise RuntimeError("R42_LISTENER_R37_REQUIRES_R36_GATE=FAIL")

    out = _replace_once(
        r36_source,
        "#include <glib/gstdio.h>",
        "#include <glib/gstdio.h>\n#include <glib-unix.h>",
        "R42 listener R37 glib-unix include",
    )

    r36_core_end = "/* R36_ATTACHED_MEDIA_TRIGGER_END */"
    out = _replace_once(
        out,
        r36_core_end,
        r36_core_end + "\n\n" + r37.CORE_REGION + "\n\n" + r37.WIRING_REGION,
        "R42 listener R37 core/wiring insertion",
    )

    install = (
        _DOOR_SIGNAL_INSTALL
        + "    r37_install_bounded_stop_control();\n"
        + '    printf("R42_LISTENER_DOOR_SIGNAL_PRESERVED=true\\n");\n'
        + '    printf("R42_LISTENER_RUN_DIR=/run/comelit-p2p\\n");\n'
        + "    fflush(stdout);\n"
    )
    out = _replace_once(
        out,
        _DOOR_SIGNAL_INSTALL,
        install,
        "R42 listener R37 stop-control install",
    )

    out = _replace_once(
        out,
        r37._WIRING_PROTOCOL_STOP_ANCHOR,
        r37._WIRING_PROTOCOL_STOP_INSERTED,
        "R42 listener R37 protocol-stop insertion",
    )

    r37._assert_gates(out)

    if out.count(_DOOR_SIGNAL_INSTALL) != 1:
        raise RuntimeError("R42_LISTENER_R37_DOOR_SIGNAL_GATE=FAIL")
    if "r37_install_bounded_stop_control();" not in out:
        raise RuntimeError("R42_LISTENER_R37_STOP_INSTALL_GATE=FAIL")
    return out


def _assert_final_listener_gates(candidate: str) -> None:
    required = (
        '#define RUN_DIR     "/run/comelit-p2p"',
        "signal(SIGUSR1, v4_door_signal_handler);",
        "v4_door_tick_cb",
        'V4_DOOR_EXISTING_CTPP_REUSED=true',
        'V4_DOOR_OPERATION_WRITES_SENT=5',
        'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false',
        'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false',
        'V4_RING_LISTENER_READY=true',
        'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true',
        'R42_LISTENER_RTP_LIFETIME_RESET=true',
        'R42_ATTACHED_MEDIA_ACTIVE=true',
        'R42_MEDIA_CHANNEL_CLOSED=true',
        'P80_VIDEO_RTP_FORWARDING=PASS',
        "g_unix_signal_add(SIGUSR2",
        "R42_CALL_GENERATION=%u",
        "R42_MEDIA_CHANNEL_ID=%u",
        "R42_MEDIAREQ26_OPEN_CHANNEL=%u",
        "R42_MEDIA_STOP_CHANNEL=%u",
        "R42_CAPABILITIES_CANDIDATE_SEEN=true",
        "R42_TRIGGER_REJECT_STAGE=%s",
        "R42_CAPABILITIES_CANDIDATE_COUNT=%u",
    )
    for needle in required:
        if needle not in candidate:
            raise RuntimeError(f"R42_LISTENER_FINAL_GATE=FAIL missing={needle}")

    forbidden = (
        "/run/comelit-media",
        "signal(SIGUSR1, SIG_IGN);",
        "ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false",
        "entrance_self_activation",
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
    )
    for needle in forbidden:
        if needle in candidate:
            raise RuntimeError(f"R42_LISTENER_FINAL_FORBIDDEN_GATE=FAIL needle={needle}")

    if candidate.count("signal(SIGUSR1, v4_door_signal_handler);") != 1:
        raise RuntimeError("R42_LISTENER_FINAL_DOOR_SIGNAL_COUNT_GATE=FAIL")
    if candidate.count("r42_listener_rtp_arm(armed);") != 1:
        raise RuntimeError("R42_LISTENER_FINAL_RTP_ARM_GATE=FAIL")
    if _R35_ARM_OLD in candidate:
        raise RuntimeError("R42_LISTENER_FINAL_DIRECT_P80_ARM_GATE=FAIL")


def transform(source: str) -> str:
    bridge = add_listener_rtp_bridge(source)
    r35_source = r35.transform(bridge)
    r35_source = _replace_once(
        r35_source,
        _R35_ARM_OLD,
        _R35_ARM_NEW,
        "R42 listener R35 arm hook",
    )
    r35_source = _replace_once(
        r35_source,
        _CALL_GENERATION_CAPTURE_ANCHOR,
        _CALL_GENERATION_CAPTURE_REPLACEMENT,
        "R42B canary call generation capture marker",
    )
    r36_source = r36.transform(r35_source)
    r37_source = add_listener_r37(r36_source)
    candidate = r42.transform(r37_source)
    candidate = add_media_diagnostics_markers(candidate)
    candidate = add_capabilities_trigger_diagnostics(candidate)
    _assert_final_listener_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R42-B LISTENER ATTACHED MEDIA TRANSFORM ===",
            "BASE_LINEAGE=FROZEN_V1_5_7_PERSISTENT_LISTENER_DOOR",
            "P80_SELF_ACTIVATION_LINEAGE_USED=false",
            "RUN_DIR=/run/comelit-p2p",
            "DOOR_SIGUSR1_PRESERVED=true",
            "DOOR_TICK_PRESERVED=true",
            "ATTACHED_STOP_SIGUSR2_ADDED=true",
            "RTP_BRIDGE=LOOPBACK_ONLY",
            "RTP_LIFETIME_RESET_PER_CALL=true",
            "R35_REUSED=true",
            "R36_REUSED=true",
            "R37_CORE_REUSED_WITH_LISTENER_INSTALL=true",
            "R42_CAPTURE_VALIDATED_CHANNEL_RUNTIME_REUSED=true",
            "SELF_ACTIVATION_USED=false",
            "AUTOMATIC_RETRY=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R42-B LISTENER ATTACHED MEDIA TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        if args.output is None:
            return 0

    if args.output is None:
        parser.error("--output is required")

    args.output.write_text(
        transform(args.source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    print("R42B_LISTENER_ATTACHED_MEDIA_TRANSFORM=PASS")
    print("DOOR_SIGUSR1_PRESERVED=true")
    print("RUN_DIR=/run/comelit-p2p")
    print("P80_SELF_ACTIVATION_LINEAGE_USED=false")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
