#!/usr/bin/env python3
"""P119: L1 remote.sdp wait removal + gathering-stage diagnostic markers.

This overlay is composed on top of the R65 production candidate (which
composes R27 on top of P106+P116; see
``entrance_p116_r65_production_media_refresh_transform.py``). Like every
overlay in this chain, it operates on the *generated text*, never on the
frozen raw source file
(``safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c``): that
file's own sha256 is pinned as a frozen anchor by many unrelated rounds
(R18, R20, R27, R35-R37, R54, R57, R58, P29, ...), so behavioral changes are
always layered in downstream, exactly like the settle-candidate round
(``entrance_device_video_ack_observation_transform.py``) and the R57
failure-attribution overlay did before it.

Two independent, bounded changes:

1. L1: ``remote_sdp_check_cb`` no longer waits for two additional stable-size
   polls before reading ``remote.sdp``. The single writer
   (``media_transport._atomic_write``: tmp -> chmod 0600 -> ``os.replace``)
   plus this helper's own startup ``unlink(OFFER_FILE)``/``unlink(REMOTE_FILE)``
   make partial or stale visibility impossible, so the first successful
   non-empty ``g_stat`` is read immediately. The 100 ms poll registration and
   the whole read path (``g_file_get_contents``, ``REMOTE_SDP_READ=FAIL``,
   ``chmod(REMOTE_FILE, 0600)``, ``REMOTE_SDP_BYTES=%zu``, the primitives
   import) are untouched.
2. Diagnostic-only monotonic-ms stage markers splitting the ICE gathering
   window: ``G0``-``G6`` and ``RSP_VISIBLE``/``RSP_LOADED``. Marker name +
   integer only -- no IPs, candidate strings, ports, credentials or SDP
   content. Every marker is printed exactly once, always immediately
   followed by ``fflush(stdout)``.

No protocol message, control-flow branch, retry, timeout, or ICE/PseudoTCP/
CTPP/RTPC/Door/Gate behavior is changed. The one new libnice signal
subscription (``new-candidate``) is pure observation: its handler only reads
the already-discovered local candidate list to time-stamp first-seen HOST/
SRFLX candidates, exactly the same read-only API
``candidate_gathering_done_cb`` already uses; it never accepts, nominates,
selects, or mutates ICE state.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r65_production_media_refresh_transform as r65
from entrance_p106_teardown_state_classification_transform import DEFAULT_SOURCE


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


# --- 1. drop the now-unused stability-tracking statics --------------------

_STABILITY_STATICS_OLD = (
    "static goffset remote_last_size = -1;\n"
    "static guint remote_stable_ticks = 0;\n"
    "\n"
    "\n"
)
_STABILITY_STATICS_NEW = ""

# --- 2. remote_sdp_check_cb: read on first successful stat + RSP markers --

_REMOTE_SDP_CHECK_CB_OLD = (
    "    if (g_stat(REMOTE_FILE, &st) != 0 ||\n"
    "        st.st_size <= 0) {\n"
    "\n"
    "        remote_last_size = -1;\n"
    "        remote_stable_ticks = 0;\n"
    "\n"
    "        return G_SOURCE_CONTINUE;\n"
    "    }\n"
    "\n"
    "    /*\n"
    "     * Require the size to be stable across multiple\n"
    "     * polling passes so we never parse a partially\n"
    "     * written remote.sdp.\n"
    "     */\n"
    "    if (remote_last_size != st.st_size) {\n"
    "        remote_last_size = st.st_size;\n"
    "        remote_stable_ticks = 0;\n"
    "\n"
    "        return G_SOURCE_CONTINUE;\n"
    "    }\n"
    "\n"
    "    remote_stable_ticks++;\n"
    "\n"
    "    if (remote_stable_ticks < 2)\n"
    "        return G_SOURCE_CONTINUE;\n"
    "\n"
    "    gchar *remote_sdp = NULL;\n"
    "    gsize remote_len = 0;\n"
    "    GError *error = NULL;\n"
    "\n"
    "    if (!g_file_get_contents(\n"
    "            REMOTE_FILE,\n"
    "            &remote_sdp,\n"
    "            &remote_len,\n"
    "            &error)) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "REMOTE_SDP_READ=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        if (error)\n"
    "            g_error_free(error);\n"
    "\n"
    "        failed = TRUE;\n"
    "\n"
    "        if (loop)\n"
    "            g_main_loop_quit(loop);\n"
    "\n"
    "        return G_SOURCE_REMOVE;\n"
    "    }\n"
    "\n"
    "    chmod(\n"
    "        REMOTE_FILE,\n"
    "        0600\n"
    "    );\n"
    "\n"
    "    printf(\n"
    '        "REMOTE_SDP_BYTES=%zu\\n",\n'
    "        (size_t)remote_len\n"
    "    );\n"
)

_REMOTE_SDP_CHECK_CB_NEW = (
    "    if (g_stat(REMOTE_FILE, &st) != 0 ||\n"
    "        st.st_size <= 0) {\n"
    "\n"
    "        return G_SOURCE_CONTINUE;\n"
    "    }\n"
    "\n"
    "    printf(\n"
    '        "RSP_VISIBLE_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    "    /*\n"
    "     * The single writer (media_transport._atomic_write: tmp -> chmod 0600\n"
    "     * -> os.replace) plus this helper's own startup unlink(OFFER_FILE) /\n"
    "     * unlink(REMOTE_FILE) make partial or stale visibility impossible, so\n"
    "     * the first successful appearance of a non-empty REMOTE_FILE is safe\n"
    "     * to read immediately: no writer can ever leave a half-written file\n"
    "     * visible at this path, and no earlier session's file can still be\n"
    "     * here.\n"
    "     */\n"
    "\n"
    "    gchar *remote_sdp = NULL;\n"
    "    gsize remote_len = 0;\n"
    "    GError *error = NULL;\n"
    "\n"
    "    if (!g_file_get_contents(\n"
    "            REMOTE_FILE,\n"
    "            &remote_sdp,\n"
    "            &remote_len,\n"
    "            &error)) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "REMOTE_SDP_READ=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        if (error)\n"
    "            g_error_free(error);\n"
    "\n"
    "        failed = TRUE;\n"
    "\n"
    "        if (loop)\n"
    "            g_main_loop_quit(loop);\n"
    "\n"
    "        return G_SOURCE_REMOVE;\n"
    "    }\n"
    "\n"
    "    printf(\n"
    '        "RSP_LOADED_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    "    chmod(\n"
    "        REMOTE_FILE,\n"
    "        0600\n"
    "    );\n"
    "\n"
    "    printf(\n"
    '        "REMOTE_SDP_BYTES=%zu\\n",\n'
    "        (size_t)remote_len\n"
    "    );\n"
)

# --- 3. new-candidate observation handler, inserted before the existing ---
# --- candidate_gathering_done_cb -------------------------------------------

_CANDIDATE_GATHERING_DONE_CB_ANCHOR = (
    "static void\n"
    "candidate_gathering_done_cb(\n"
    "    NiceAgent *nice_agent,\n"
    "    guint sid,\n"
    "    gpointer data)\n"
    "{"
)

_NEW_CANDIDATE_CB = (
    "/*\n"
    " * Diagnostic-only observation of the \"new-candidate\" signal.\n"
    " *\n"
    " * This handler never accepts, nominates or selects anything: it looks\n"
    " * up the just-announced candidate's type by foundation among the\n"
    " * component's already-discovered local candidates (the same read-only\n"
    " * API candidate_gathering_done_cb() already uses) purely to stamp the\n"
    " * first-seen monotonic time of each candidate class. No control flow\n"
    " * anywhere in the agent is affected by this lookup.\n"
    " */\n"
    "static gboolean g3_host_first_seen = FALSE;\n"
    "static gboolean g4_srflx_first_seen = FALSE;\n"
    "\n"
    "static void\n"
    "new_candidate_cb(\n"
    "    NiceAgent *nice_agent,\n"
    "    guint sid,\n"
    "    guint component_id,\n"
    "    gchar *foundation,\n"
    "    gpointer data)\n"
    "{\n"
    "    (void)data;\n"
    "\n"
    "    if (sid != stream_id)\n"
    "        return;\n"
    "\n"
    "    GSList *candidates =\n"
    "        nice_agent_get_local_candidates(\n"
    "            nice_agent,\n"
    "            sid,\n"
    "            component_id\n"
    "        );\n"
    "\n"
    "    gint candidate_type = -1;\n"
    "\n"
    "    for (GSList *it = candidates;\n"
    "         it != NULL;\n"
    "         it = it->next) {\n"
    "\n"
    "        NiceCandidate *candidate =\n"
    "            (NiceCandidate *)it->data;\n"
    "\n"
    "        if (g_strcmp0(\n"
    "                candidate->foundation,\n"
    "                foundation) == 0) {\n"
    "\n"
    "            candidate_type = candidate->type;\n"
    "            break;\n"
    "        }\n"
    "    }\n"
    "\n"
    "    g_slist_free_full(\n"
    "        candidates,\n"
    "        (GDestroyNotify)nice_candidate_free\n"
    "    );\n"
    "\n"
    "    if (candidate_type == NICE_CANDIDATE_TYPE_HOST &&\n"
    "        !g3_host_first_seen) {\n"
    "\n"
    "        g3_host_first_seen = TRUE;\n"
    "\n"
    "        printf(\n"
    '            "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "            (guint64)(g_get_monotonic_time() / 1000)\n"
    "        );\n"
    "        fflush(stdout);\n"
    "\n"
    "    } else if (candidate_type == NICE_CANDIDATE_TYPE_SERVER_REFLEXIVE &&\n"
    "               !g4_srflx_first_seen) {\n"
    "\n"
    "        g4_srflx_first_seen = TRUE;\n"
    "\n"
    "        printf(\n"
    '            "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "            (guint64)(g_get_monotonic_time() / 1000)\n"
    "        );\n"
    "        fflush(stdout);\n"
    "    }\n"
    "}\n"
    "\n"
    "\n"
) + _CANDIDATE_GATHERING_DONE_CB_ANCHOR

# --- 4. G5/G6 + G3/G4 candidate counts, next to the existing gather-done ---
# --- prints -----------------------------------------------------------------

_GATHER_DONE_PRINTS_OLD = (
    "    chmod(OFFER_FILE, 0600);\n"
    "\n"
    '    printf("ICE_GATHER=PASS\\n");\n'
    '    printf("ICE_ROLE=CONTROLLED\\n");\n'
    '    printf("ICE_COMPONENTS=1\\n");\n'
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_TOTAL=%u\\n",\n'
    "        total\n"
    "    );\n"
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_HOST=%u\\n",\n'
    "        host\n"
    "    );\n"
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_SRFLX=%u\\n",\n'
    "        srflx\n"
    "    );\n"
)

_GATHER_DONE_PRINTS_NEW = (
    "    chmod(OFFER_FILE, 0600);\n"
    "\n"
    "    printf(\n"
    '        "G5_GATHER_DONE_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    "    printf(\n"
    '        "G6_OFFER_WRITTEN_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    '    printf("ICE_GATHER=PASS\\n");\n'
    '    printf("ICE_ROLE=CONTROLLED\\n");\n'
    '    printf("ICE_COMPONENTS=1\\n");\n'
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_TOTAL=%u\\n",\n'
    "        total\n"
    "    );\n"
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_HOST=%u\\n",\n'
    "        host\n"
    "    );\n"
    "\n"
    "    /*\n"
    "     * Printed once here (gathering done), from the same final host\n"
    "     * count as LOCAL_CANDIDATES_HOST above -- not from the per-signal\n"
    "     * new_candidate_cb() counter, so this total cannot race the\n"
    "     * component's own candidate list.\n"
    "     */\n"
    "    printf(\n"
    '        "G3_HOST_CANDIDATE_COUNT=%u\\n",\n'
    "        host\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    "    printf(\n"
    '        "LOCAL_CANDIDATES_SRFLX=%u\\n",\n'
    "        srflx\n"
    "    );\n"
    "\n"
    "    /* Printed once here, from the same final srflx count as LOCAL_CANDIDATES_SRFLX above. */\n"
    "    printf(\n"
    '        "G4_SRFLX_CANDIDATE_COUNT=%u\\n",\n'
    "        srflx\n"
    "    );\n"
    "    fflush(stdout);\n"
)

# --- 5. G0: printed by a constructor, never inside main()'s body, so the --
# --- exact `main(void)\n{\n    setvbuf(...)` text R27 already produced is --
# --- never disturbed --------------------------------------------------------

_MAIN_ENTRY_ANCHOR = (
    "int\n"
    "main(void)\n"
    "{\n"
    "    setvbuf(stdout, NULL, _IOLBF, 0);"
)

_G0_CONSTRUCTOR = (
    "/*\n"
    " * A GCC/Clang constructor runs before main()'s body, at the earliest\n"
    " * possible point in this process's life -- earlier than any statement\n"
    " * that could be placed inside main() itself. This diagnostic marker is\n"
    " * kept out of main()'s body specifically so it cannot disturb the exact\n"
    " * `main(void)\\n{\\n    setvbuf(...)` anchor text the R27 production\n"
    " * transform matches against.\n"
    " */\n"
    "__attribute__((constructor))\n"
    "static void\n"
    "g0_native_process_start_marker(void)\n"
    "{\n"
    "    printf(\n"
    '        "G0_NATIVE_PROCESS_START_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "}\n"
    "\n"
    "\n"
) + _MAIN_ENTRY_ANCHOR

# --- 6. G1: after the agent is configured and nice_agent_add_stream --------
# --- succeeds -----------------------------------------------------------

_STREAM_CREATE_OK_OLD = (
    "        g_object_unref(agent);\n"
    "        g_main_loop_unref(loop);\n"
    "\n"
    "        return 4;\n"
    "    }\n"
    "\n"
    "    nice_agent_set_stream_name(\n"
)

_STREAM_CREATE_OK_NEW = (
    "        g_object_unref(agent);\n"
    "        g_main_loop_unref(loop);\n"
    "\n"
    "        return 4;\n"
    "    }\n"
    "\n"
    "    printf(\n"
    '        "G1_NICE_AGENT_READY_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    "    nice_agent_set_stream_name(\n"
)

# --- 7. new-candidate signal subscription + G2 at the gather call ----------

_SIGNAL_AND_GATHER_OLD = (
    "    g_signal_connect(\n"
    "        agent,\n"
    '        "component-state-changed",\n'
    "        G_CALLBACK(\n"
    "            component_state_changed_cb\n"
    "        ),\n"
    "        NULL\n"
    "    );\n"
    "\n"
    "    if (!nice_agent_gather_candidates(\n"
    "            agent,\n"
    "            stream_id)) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "ICE_GATHER_START=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        g_object_unref(agent);\n"
    "        g_main_loop_unref(loop);\n"
    "\n"
    "        return 5;\n"
    "    }\n"
    "\n"
    '    printf("ICE_GATHER_START=PASS\\n");\n'
    "    fflush(stdout);\n"
)

_SIGNAL_AND_GATHER_NEW = (
    "    g_signal_connect(\n"
    "        agent,\n"
    '        "component-state-changed",\n'
    "        G_CALLBACK(\n"
    "            component_state_changed_cb\n"
    "        ),\n"
    "        NULL\n"
    "    );\n"
    "\n"
    "    g_signal_connect(\n"
    "        agent,\n"
    '        "new-candidate",\n'
    "        G_CALLBACK(\n"
    "            new_candidate_cb\n"
    "        ),\n"
    "        NULL\n"
    "    );\n"
    "\n"
    "    if (!nice_agent_gather_candidates(\n"
    "            agent,\n"
    "            stream_id)) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "ICE_GATHER_START=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        g_object_unref(agent);\n"
    "        g_main_loop_unref(loop);\n"
    "\n"
    "        return 5;\n"
    "    }\n"
    "\n"
    "    printf(\n"
    '        "G2_GATHER_CALL_MONOTONIC_MS=%" G_GUINT64_FORMAT "\\n",\n'
    "        (guint64)(g_get_monotonic_time() / 1000)\n"
    "    );\n"
    "    fflush(stdout);\n"
    "\n"
    '    printf("ICE_GATHER_START=PASS\\n");\n'
    "    fflush(stdout);\n"
)


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("P119 requires --include-p116; --no-include-p116 is fail-closed")

    candidate = r65.transform(source, include_p116=True)

    candidate = _replace_once(
        candidate, _STABILITY_STATICS_OLD, _STABILITY_STATICS_NEW,
        "P119 drop stability-tracking statics",
    )
    candidate = _replace_once(
        candidate, _REMOTE_SDP_CHECK_CB_OLD, _REMOTE_SDP_CHECK_CB_NEW,
        "P119 remote_sdp_check_cb L1 removal + RSP markers",
    )
    candidate = _replace_once(
        candidate, _CANDIDATE_GATHERING_DONE_CB_ANCHOR, _NEW_CANDIDATE_CB,
        "P119 new_candidate_cb insertion",
    )
    candidate = _replace_once(
        candidate, _GATHER_DONE_PRINTS_OLD, _GATHER_DONE_PRINTS_NEW,
        "P119 G5/G6 + candidate-count markers",
    )
    candidate = _replace_once(
        candidate, _MAIN_ENTRY_ANCHOR, _G0_CONSTRUCTOR,
        "P119 G0 constructor",
    )
    candidate = _replace_once(
        candidate, _STREAM_CREATE_OK_OLD, _STREAM_CREATE_OK_NEW,
        "P119 G1 marker",
    )
    candidate = _replace_once(
        candidate, _SIGNAL_AND_GATHER_OLD, _SIGNAL_AND_GATHER_NEW,
        "P119 new-candidate signal + G2 marker",
    )

    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P119 REMOTE SDP L1 + GATHER DIAGNOSTIC TRANSFORM ===",
            "P119_COMPOSES=R65_PRODUCTION_MEDIA_REFRESH",
            "REMOTE_SDP_DETECTION_WAIT_REMOVED=true",
            "REMOTE_SDP_STABLE_TICKS_BEFORE=2",
            "REMOTE_SDP_STABLE_TICKS_AFTER=0",
            "POLL_INTERVAL_UNCHANGED=true",
            "PROTOCOL_MESSAGES_ADDED=false",
            "ICE_SETTINGS_CHANGED=false",
            "PSEUDOTCP_BEHAVIOR_CHANGED=false",
            "DOOR_SEMANTICS_CHANGED=false",
            "GATE_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P119 REMOTE SDP L1 + GATHER DIAGNOSTIC TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    p116 = parser.add_mutually_exclusive_group()
    p116.add_argument("--include-p116", dest="include_p116", action="store_true")
    p116.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    parser.set_defaults(include_p116=True)
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/") :])

    if not args.include_p116:
        parser.error("P119 requires --include-p116; --no-include-p116 is fail-closed")

    generated = transform(source_path.read_text(encoding="utf-8"), include_p116=True)

    if args.sha256:
        print(hashlib.sha256(generated.encode("utf-8")).hexdigest())
        return 0

    if args.output is None:
        parser.error("--output is required unless --report or --sha256 is used")
    args.output.write_text(generated, encoding="utf-8")
    print("P116_R119_REMOTE_SDP_L1_GATHER_DIAG_TRANSFORM=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
