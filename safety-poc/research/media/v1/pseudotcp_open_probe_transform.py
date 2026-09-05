#!/usr/bin/env python3
"""Generate a transport-only PseudoTCP-open research candidate.

This transform composes the early-datagram replay fix with a deliberately
narrow live boundary: prove PseudoTCP OPEN and terminate immediately.  It must
not advance into ViP ECHO/UAUT/UCFG/CTPP/CSPB, self-activation, Door, or media
signaling.

The generated C source is a CT120 research artifact only.  This module performs
no network I/O and does not modify the Home Assistant production binary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pseudotcp_prestart_replay_transform import transform as replay_transform


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _replace_function(
    text: str,
    signature: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"{label}: function signature not found")
    if text.find(signature, start + 1) >= 0:
        raise RuntimeError(f"{label}: function signature is not unique")

    brace = text.find("{", start + len(signature))
    if brace < 0:
        raise RuntimeError(f"{label}: opening brace not found")

    depth = 0
    end = None
    i = brace
    in_string = False
    in_char = False
    escaped = False

    while i < len(text):
        ch = text[i]

        if escaped:
            escaped = False
            i += 1
            continue

        if (in_string or in_char) and ch == "\\":
            escaped = True
            i += 1
            continue

        if not in_char and ch == '"':
            in_string = not in_string
            i += 1
            continue

        if not in_string and ch == "'":
            in_char = not in_char
            i += 1
            continue

        if not in_string and not in_char:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        i += 1

    if end is None:
        raise RuntimeError(f"{label}: closing brace not found")

    return text[:start] + replacement.rstrip() + text[end:]


def transform(source: str) -> str:
    source = replay_transform(source)

    state_anchor = """static gboolean pseudotcp_started = FALSE;
static gboolean pseudotcp_open = FALSE;
"""
    state_replacement = """static gboolean pseudotcp_started = FALSE;
static gboolean pseudotcp_open = FALSE;

static gboolean open_probe_timed_out = FALSE;
"""
    source = _replace_once(
        source,
        state_anchor,
        state_replacement,
        "open-probe timeout state",
    )

    opened_replacement = r'''static void
pseudotcp_opened_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)tcp;
    (void)data;

    if (pseudotcp_open)
        return;

    pseudotcp_open = TRUE;

    printf("PSEUDOTCP_OPEN=PASS\n");
    printf("PSEUDOTCP_OPEN_PROBE_RESULT=PASS\n");
    printf("PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    /* Transport proof is the terminal boundary for this experiment. */
    if (loop)
        g_main_loop_quit(loop);
}'''
    source = _replace_function(
        source,
        "static void\npseudotcp_opened_cb(",
        opened_replacement,
        "PseudoTCP opened callback",
    )

    readable_replacement = r'''static void
pseudotcp_readable_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)tcp;
    (void)data;

    /*
     * Application bytes are deliberately not consumed or parsed.  In
     * particular this probe must never answer ECHO, open UAUT, register CTPP,
     * or send self-activation/video signaling.
     */
    printf("PSEUDOTCP_OPEN_PROBE_APP_READABLE_OBSERVED=true\n");
    fflush(stdout);
}'''
    source = _replace_function(
        source,
        "static void\npseudotcp_readable_cb(",
        readable_replacement,
        "PseudoTCP readable callback",
    )

    writable_replacement = r'''static void
pseudotcp_writable_cb(
    PseudoTcpSocket *tcp,
    gpointer data)
{
    (void)tcp;
    (void)data;

    /* PseudoTCP transport ACK/SYN traffic is handled by libnice callbacks. */
    printf("PSEUDOTCP_OPEN_PROBE_WRITABLE_OBSERVED=true\n");
    fflush(stdout);
}'''
    source = _replace_function(
        source,
        "static void\npseudotcp_writable_cb(",
        writable_replacement,
        "PseudoTCP writable callback",
    )

    main_anchor = """int
main(void)
{
"""
    timeout_helper = r'''static gboolean
open_probe_timeout_cb(gpointer data)
{
    (void)data;

    if (pseudotcp_open)
        return G_SOURCE_REMOVE;

    open_probe_timed_out = TRUE;
    failed = TRUE;

    fprintf(stderr, "PSEUDOTCP_OPEN_PROBE_TIMEOUT=true\n");
    printf("PSEUDOTCP_OPEN_PROBE_RESULT=TIMEOUT\n");
    printf("PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false\n");
    printf("PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    if (loop)
        g_main_loop_quit(loop);

    return G_SOURCE_REMOVE;
}


int
main(void)
{
'''
    source = _replace_once(
        source,
        main_anchor,
        timeout_helper,
        "open-probe timeout callback",
    )

    source = _replace_once(
        source,
        "    signal(SIGUSR1, v4_door_signal_handler);\n\n",
        "    printf(\"PSEUDOTCP_OPEN_PROBE_DOOR_SIGNAL_INSTALLED=false\\n\");\n\n",
        "remove Door signal handler",
    )

    door_tick = """    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );

"""
    source = _replace_once(
        source,
        door_tick,
        "",
        "remove Door tick",
    )

    long_timeout = """    g_timeout_add_seconds(
        3300,
        absolute_timeout_cb,
        NULL
    );
"""
    bounded_timeout = """    g_timeout_add_seconds(
        45,
        open_probe_timeout_cb,
        NULL
    );
"""
    source = _replace_once(
        source,
        long_timeout,
        bounded_timeout,
        "bounded open-probe timeout",
    )

    source = _replace_once(
        source,
        "    return failed ? 6 : 0;\n}",
        """    if (pseudotcp_open)
        return 0;

    if (open_probe_timed_out)
        return 7;

    return 6;
}
""",
        "open-probe result code",
    )

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    candidate = transform(source)
    args.output.write_text(candidate, encoding="utf-8")

    print("PSEUDOTCP_OPEN_PROBE_TRANSFORM=PASS")
    print("PSEUDOTCP_EARLY_DATAGRAM_REPLAY=ENABLED")
    print("PSEUDOTCP_OPEN_IS_TERMINAL=true")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
