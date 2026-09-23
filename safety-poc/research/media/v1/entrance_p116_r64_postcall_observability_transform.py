#!/usr/bin/env python3
"""P116/R64: bounded post-call and terminal transport observability.

R64 composes the shipped R63 source and changes no protocol bytes, scheduling,
timeouts, retry policy, Door/Gate semantics, channel allocation, or transport
control flow. It only publishes bounded scalar snapshots needed to attribute
an intermittent post-call listener outage.

Two snapshots are emitted:
* POST_CALL: immediately after the R58 authoritative media CLOSED boundary.
* TERMINAL: immediately before the existing R57 native-exit summary.

R37 RELEASE/capability-clear observations are latched per call generation
before their handlers run, so the POST_CALL snapshot cannot lose a synchronous
teardown event. Existing PseudoTCP close markers are not changed.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r63_gate_peer_tap_actuation_transform as r63


BEGIN = "/* R64_POSTCALL_OBSERVABILITY_BEGIN */"
END = "/* R64_POSTCALL_OBSERVABILITY_END */"

_LATE_ANCHOR = "/* R54_CALL_ADOPTION_LISTENER_END */"

_R64_REGION = r'''/* R64_POSTCALL_OBSERVABILITY_BEGIN */
static unsigned g_r64_generation = 0u;
static gboolean g_r64_remote_release_observed = FALSE;
static gboolean g_r64_capability_cleared_observed = FALSE;

static void
r64_reset_for_generation(void)
{
    if (g_r64_generation == g_r35_session.call_generation)
        return;
    g_r64_generation = g_r35_session.call_generation;
    g_r64_remote_release_observed = FALSE;
    g_r64_capability_cleared_observed = FALSE;
}

static void
r64_note_remote_release(void)
{
    r64_reset_for_generation();
    g_r64_remote_release_observed = TRUE;
}

static void
r64_note_capability_cleared(void)
{
    r64_reset_for_generation();
    g_r64_capability_cleared_observed = TRUE;
}

static void
r64_publish_post_call_snapshot(void)
{
    r64_reset_for_generation();
    printf("R64_POST_CALL_REMOTE_RELEASE_OBSERVED=%s\n",
        g_r64_remote_release_observed ? "true" : "false");
    printf("R64_POST_CALL_CAPABILITY_CLEARED_OBSERVED=%s\n",
        g_r64_capability_cleared_observed ? "true" : "false");
    printf("R64_POST_CALL_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R64_POST_CALL_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    printf("R64_POST_CALL_TX_PENDING=%s\n", p12_tx_pending ? "true" : "false");
    printf("R64_POST_CALL_CALL_READY=%s\n",
        r35_call_ready(&g_r35_session) ? "true" : "false");
    printf("R64_POST_CALL_PSEUDOTCP_OPEN=%s\n", pseudotcp_open ? "true" : "false");
    printf("R64_POST_CALL_SNAPSHOT=true\n");
    fflush(stdout);
}

static void
r64_publish_terminal_snapshot(void)
{
    r64_reset_for_generation();
    printf("R64_TERMINAL_REMOTE_RELEASE_OBSERVED=%s\n",
        g_r64_remote_release_observed ? "true" : "false");
    printf("R64_TERMINAL_CAPABILITY_CLEARED_OBSERVED=%s\n",
        g_r64_capability_cleared_observed ? "true" : "false");
    printf("R64_TERMINAL_TX_STATE=%s\n", r54_tx_state_name(g_r54_tx_state));
    printf("R64_TERMINAL_TX_SUBJECT=%s\n", r54_tx_subject_name(g_r54_tx_last_subject));
    printf("R64_TERMINAL_TX_PENDING=%s\n", p12_tx_pending ? "true" : "false");
    printf("R64_TERMINAL_CALL_READY=%s\n",
        r35_call_ready(&g_r35_session) ? "true" : "false");
    printf("R64_TERMINAL_PSEUDOTCP_OPEN=%s\n", pseudotcp_open ? "true" : "false");
    printf("R64_TERMINAL_SNAPSHOT=true\n");
    fflush(stdout);
}
/* R64_POSTCALL_OBSERVABILITY_END */'''

_CAPABILITY_ANCHOR = '''                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);'''
_CAPABILITY_REPLACEMENT = '''                        r64_note_capability_cleared();
                        R35Result r37_rc = r37_handle_capability_cleared(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);'''

_RELEASE_ANCHOR = '''                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);'''
_RELEASE_REPLACEMENT = '''                        r64_note_remote_release();
                        R35Result r37_rc = r37_handle_remote_release(
                            &g_r35_session, &g_r37_telemetry, R35_FORM_TUNNEL);'''

_POST_CALL_ANCHOR = '''    r42_finish_media_channel_close();
}
/* R58_STOP_CLEANUP_END */'''
_POST_CALL_REPLACEMENT = '''    r42_finish_media_channel_close();
    r64_publish_post_call_snapshot();
}
/* R58_STOP_CLEANUP_END */'''

_TERMINAL_ANCHOR = '''    p116_emit_native_exit_summary(failed);

    return failed ? 6 : 0;'''
_TERMINAL_REPLACEMENT = '''    r64_publish_terminal_snapshot();
    p116_emit_native_exit_summary(failed);

    return failed ? 6 : 0;'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R64_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("R64_REAPPLY_GATE=FAIL")

    candidate = r63.transform(source)
    candidate = _replace_once(
        candidate,
        _LATE_ANCHOR,
        _LATE_ANCHOR + "\n\n" + _R64_REGION,
        "REGION",
    )
    candidate = _replace_once(
        candidate,
        _CAPABILITY_ANCHOR,
        _CAPABILITY_REPLACEMENT,
        "CAPABILITY_NOTE",
    )
    candidate = _replace_once(
        candidate,
        _RELEASE_ANCHOR,
        _RELEASE_REPLACEMENT,
        "RELEASE_NOTE",
    )
    candidate = _replace_once(
        candidate,
        _POST_CALL_ANCHOR,
        _POST_CALL_REPLACEMENT,
        "POST_CALL_SNAPSHOT",
    )
    candidate = _replace_once(
        candidate,
        _TERMINAL_ANCHOR,
        _TERMINAL_REPLACEMENT,
        "TERMINAL_SNAPSHOT",
    )

    if candidate.count(BEGIN) != 1 or candidate.count(END) != 1:
        raise RuntimeError("R64_MARKER_GATE=FAIL")
    for marker in (
        "R64_POST_CALL_SNAPSHOT=true",
        "R64_TERMINAL_SNAPSHOT=true",
        "R64_POST_CALL_TX_STATE=%s",
        "R64_TERMINAL_TX_STATE=%s",
        "PSEUDOTCP_CLOSED_BEFORE_OPEN=true",
        "PSEUDOTCP_CLOSED_AFTER_OPEN=true",
    ):
        if marker not in candidate:
            raise RuntimeError(f"R64_OBSERVABILITY_GATE=FAIL marker={marker}")

    # R64 is observability-only: it must not add any protocol writer, retry,
    # signal, timeout, or transport-close call.
    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    for forbidden in (
        "p12_queue_bytes(",
        "p12_queue_vip_frame(",
        "pseudo_tcp_socket_send(",
        "nice_agent_send(",
        "g_timeout_add(",
        "g_timeout_add_seconds(",
        "os.kill",
        "signal(",
        "pseudo_tcp_socket_close(",
        "r35_send_stop(",
        "r35_send_open(",
    ):
        if forbidden in region:
            raise RuntimeError(f"R64_OBSERVABILITY_ONLY_GATE=FAIL forbidden={forbidden}")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    safety_poc_root = Path(__file__).resolve().parents[3]
    source_path = args.source or (
        safety_poc_root
        / "research"
        / "door"
        / "v1_5_7"
        / "comelit-v4-persistent-ctpp-door.c"
    )
    candidate = transform(source_path.read_text(encoding="utf-8"))

    if args.sha256:
        print(hashlib.sha256(candidate.encode("utf-8")).hexdigest())
        return 0
    if args.output is None:
        parser.error("--output is required unless --sha256 is used")

    args.output.write_text(candidate, encoding="utf-8")
    print("R64_POSTCALL_OBSERVABILITY_TRANSFORM=PASS")
    print(
        "R64_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    )
    print("R64_PROTOCOL_BEHAVIOR_CHANGED=false")
    print("R64_RECONNECT_POLICY_CHANGED=false")
    print("R64_AUTOMATIC_RETRY_ADDED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
