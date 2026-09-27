#!/usr/bin/env python3
"""P121: gather-only ``stun-initial-timeout`` override (250 ms) + restore.

This overlay is composed on top of the P119 production candidate (which
composes R65, which composes R27 on top of P106+P116; see
``entrance_p119_remote_sdp_l1_gather_diag_transform.py``). Like every overlay
in this chain, it operates on the *generated text*, never on the frozen raw
source file
(``safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c``): that
file's own sha256 is pinned as a frozen anchor by many unrelated rounds, so
behavioral changes are always layered in downstream.

Forensic basis (libnice 0.1.22, exact sources): ``stun-initial-timeout``
(RTO) is used ONLY by the discovery/gathering timers
(``agent/discovery.c:269-270``, ``:1323-1324``) and never by ICE
connectivity checks, whose timer is computed independently
(``agent/conncheck.c:2850-2861``) and which only borrow
``stun-max-retransmissions`` (``agent/conncheck.c:2987``). Reducing RTO
during gathering therefore shortens the wait for unanswered discovery
transactions without touching the checks.

The one behavioral change:

1. Immediately before ``nice_agent_gather_candidates(...)``, set
   ``stun-initial-timeout`` to 250 ms via the normal writable GObject
   property, and print ``GATHER_INITIAL_TIMEOUT_SET_MS=250`` exactly once.
2. A single idempotent restore helper (file-scope static, guarded by a
   static flag so it fires at most once per process) sets it back to the
   libnice default of 500 ms and prints
   ``GATHER_INITIAL_TIMEOUT_RESTORED_MS=500`` exactly once, when it actually
   performs the restore. It is invoked on all four exit paths out of
   gathering/connectivity so the restore is fail-closed:
   a. the very top of ``candidate_gathering_done_cb()``;
   b. the ``nice_agent_gather_candidates(...) == FALSE`` failure branch
      (before ``g_object_unref(agent)``, so the agent is still valid);
   c. the ``NICE_COMPONENT_STATE_FAILED`` branch of
      ``component_state_changed_cb``;
   d. immediately after ``g_main_loop_run(loop)`` returns.

Nothing else changes: ``stun-max-retransmissions`` stays unset (libnice
default of 3), ``timer-ta``, ``stun-reliable-timeout``, nomination mode,
controlling/controlled role, STUN server/port, TURN, candidate
filtering/policy, offer structure, trickle behavior, connectivity checks,
PseudoTCP, CTPP, RTPC, the 1000 ms settle candidate, and Door/Gate semantics
are all untouched. The new ``g_object_set`` call is the only added property
write in the whole generated source.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p119_remote_sdp_l1_gather_diag_transform as p119
from entrance_p106_teardown_state_classification_transform import DEFAULT_SOURCE


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


# --- 1. static flag + idempotent restore helper, inserted right after the --
# --- existing pseudotcp_started/pseudotcp_open statics ----------------------

_PSEUDOTCP_STATICS_ANCHOR = (
    "static gboolean pseudotcp_started = FALSE;\n"
    "static gboolean pseudotcp_open = FALSE;\n"
    "\n"
    "/* Research-only graceful shutdown state. */"
)

_RESTORE_HELPER = (
    "static gboolean pseudotcp_started = FALSE;\n"
    "static gboolean pseudotcp_open = FALSE;\n"
    "\n"
    "static gboolean gather_initial_timeout_restored = FALSE;\n"
    "\n"
    "/*\n"
    " * Gather-only stun-initial-timeout override: set to 250 ms immediately\n"
    " * before nice_agent_gather_candidates(), restored to the libnice default\n"
    " * (500 ms) exactly once via this idempotent helper. Called on every path\n"
    " * out of gathering/connectivity so the restore is fail-closed. Never\n"
    " * used by ICE connectivity checks (agent/conncheck.c computes its own\n"
    " * timer independently from an unrelated retransmission-count property\n"
    " * this override never touches).\n"
    " */\n"
    "static void\n"
    "gather_initial_timeout_restore(void)\n"
    "{\n"
    "    if (gather_initial_timeout_restored)\n"
    "        return;\n"
    "\n"
    "    if (!agent)\n"
    "        return;\n"
    "\n"
    "    gather_initial_timeout_restored = TRUE;\n"
    "\n"
    "    g_object_set(\n"
    "        agent,\n"
    '        "stun-initial-timeout",\n'
    "        500,\n"
    "        NULL\n"
    "    );\n"
    "\n"
    '    printf("GATHER_INITIAL_TIMEOUT_RESTORED_MS=500\\n");\n'
    "    fflush(stdout);\n"
    "}\n"
    "\n"
    "/* Research-only graceful shutdown state. */"
)

# --- 2. the SET call, immediately before nice_agent_gather_candidates(...) --

_SIGNAL_AND_GATHER_OLD = (
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
)

_SIGNAL_AND_GATHER_NEW = (
    "    g_signal_connect(\n"
    "        agent,\n"
    '        "new-candidate",\n'
    "        G_CALLBACK(\n"
    "            new_candidate_cb\n"
    "        ),\n"
    "        NULL\n"
    "    );\n"
    "\n"
    "    g_object_set(\n"
    "        agent,\n"
    '        "stun-initial-timeout",\n'
    "        250,\n"
    "        NULL\n"
    "    );\n"
    "\n"
    '    printf("GATHER_INITIAL_TIMEOUT_SET_MS=250\\n");\n'
    "    fflush(stdout);\n"
    "\n"
    "    if (!nice_agent_gather_candidates(\n"
    "            agent,\n"
    "            stream_id)) {\n"
)

# --- 3. restore on the gather-start failure path, before g_object_unref -----

_GATHER_FAIL_OLD = (
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
)

_GATHER_FAIL_NEW = (
    "    if (!nice_agent_gather_candidates(\n"
    "            agent,\n"
    "            stream_id)) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "ICE_GATHER_START=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        gather_initial_timeout_restore();\n"
    "\n"
    "        g_object_unref(agent);\n"
    "        g_main_loop_unref(loop);\n"
    "\n"
    "        return 5;\n"
    "    }\n"
)

# --- 4. restore in the NICE_COMPONENT_STATE_FAILED branch -------------------

_FAILED_BRANCH_OLD = (
    "    if (state ==\n"
    "        NICE_COMPONENT_STATE_FAILED) {\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "ICE_CONNECTIVITY=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        failed = TRUE;\n"
    "\n"
    "        if (loop)\n"
    "            g_main_loop_quit(loop);\n"
    "\n"
    "        return;\n"
    "    }\n"
)

_FAILED_BRANCH_NEW = (
    "    if (state ==\n"
    "        NICE_COMPONENT_STATE_FAILED) {\n"
    "\n"
    "        gather_initial_timeout_restore();\n"
    "\n"
    "        fprintf(\n"
    "            stderr,\n"
    '            "ICE_CONNECTIVITY=FAIL\\n"\n'
    "        );\n"
    "\n"
    "        failed = TRUE;\n"
    "\n"
    "        if (loop)\n"
    "            g_main_loop_quit(loop);\n"
    "\n"
    "        return;\n"
    "    }\n"
)

# --- 5. restore as the first statement of candidate_gathering_done_cb ------

_GATHER_DONE_TOP_OLD = (
    "static void\n"
    "candidate_gathering_done_cb(\n"
    "    NiceAgent *nice_agent,\n"
    "    guint sid,\n"
    "    gpointer data)\n"
    "{\n"
    "    (void)data;\n"
    "\n"
    "    if (sid != stream_id)\n"
    "        return;\n"
)

_GATHER_DONE_TOP_NEW = (
    "static void\n"
    "candidate_gathering_done_cb(\n"
    "    NiceAgent *nice_agent,\n"
    "    guint sid,\n"
    "    gpointer data)\n"
    "{\n"
    "    gather_initial_timeout_restore();\n"
    "\n"
    "    (void)data;\n"
    "\n"
    "    if (sid != stream_id)\n"
    "        return;\n"
)

# --- 6. restore as the teardown catch-all, right after g_main_loop_run -----

_POST_LOOP_OLD = (
    "    g_main_loop_run(loop);\n"
    "\n"
    "    if (ready)\n"
    '        printf("ICE_OFFER_HELD=true\\n");\n'
)

_POST_LOOP_NEW = (
    "    g_main_loop_run(loop);\n"
    "\n"
    "    gather_initial_timeout_restore();\n"
    "\n"
    "    if (ready)\n"
    '        printf("ICE_OFFER_HELD=true\\n");\n'
)


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("P121 requires --include-p116; --no-include-p116 is fail-closed")

    candidate = p119.transform(source, include_p116=True)

    candidate = _replace_once(
        candidate, _PSEUDOTCP_STATICS_ANCHOR, _RESTORE_HELPER,
        "P121 restore helper insertion",
    )
    candidate = _replace_once(
        candidate, _SIGNAL_AND_GATHER_OLD, _SIGNAL_AND_GATHER_NEW,
        "P121 stun-initial-timeout SET before gather",
    )
    candidate = _replace_once(
        candidate, _GATHER_FAIL_OLD, _GATHER_FAIL_NEW,
        "P121 restore on gather-start failure",
    )
    candidate = _replace_once(
        candidate, _FAILED_BRANCH_OLD, _FAILED_BRANCH_NEW,
        "P121 restore on NICE_COMPONENT_STATE_FAILED",
    )
    candidate = _replace_once(
        candidate, _GATHER_DONE_TOP_OLD, _GATHER_DONE_TOP_NEW,
        "P121 restore at top of candidate_gathering_done_cb",
    )
    candidate = _replace_once(
        candidate, _POST_LOOP_OLD, _POST_LOOP_NEW,
        "P121 restore after g_main_loop_run teardown",
    )

    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P121 GATHER INITIAL TIMEOUT TRANSFORM ===",
            "P121_COMPOSES=P119_REMOTE_SDP_L1_GATHER_DIAG",
            "GATHER_ONLY=true",
            "STUN_INITIAL_TIMEOUT_SET_MS=250",
            "STUN_INITIAL_TIMEOUT_RESTORED_MS=500",
            "STUN_MAX_RETRANSMISSIONS_CHANGED=false",
            "CONNECTIVITY_CHECK_TIMER_PATH_CHANGED=false",
            "ICE_ROLE_CHANGED=false",
            "STUN_SERVER_CHANGED=false",
            "TURN_CHANGED=false",
            "CANDIDATE_FILTERING_CHANGED=false",
            "OFFER_CONTENT_LOGIC_CHANGED=false",
            "TRICKLE_CHANGED=false",
            "PSEUDOTCP_CTPP_RTPC_CHANGED=false",
            "SETTLE_MS=1000",
            "REMOTE_SDP_L1_RETAINED=true",
            "DOOR_SEMANTICS_CHANGED=false",
            "GATE_SEMANTICS_CHANGED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P121 GATHER INITIAL TIMEOUT TRANSFORM ===",
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
        parser.error("P121 requires --include-p116; --no-include-p116 is fail-closed")

    generated = transform(source_path.read_text(encoding="utf-8"), include_p116=True)

    if args.sha256:
        print(hashlib.sha256(generated.encode("utf-8")).hexdigest())
        return 0

    if args.output is None:
        parser.error("--output is required unless --report or --sha256 is used")
    args.output.write_text(generated, encoding="utf-8")
    print("P121_GATHER_INITIAL_TIMEOUT_TRANSFORM=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
