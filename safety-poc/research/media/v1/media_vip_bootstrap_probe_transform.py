#!/usr/bin/env python3
"""Generate a research-only media-session ViP bootstrap probe.

The candidate keeps the proven P2P/ICE/PseudoTCP and normal ViP bootstrap
(ECHO, UAUT, UCFG, CTPP/CSPB registration) but terminates immediately when the
persistent CTPP listener becomes READY.  It deliberately has no reachable Door
signal/tick path and sends no self-activation (0x0028) or video event (0x0008).

Early PseudoTCP datagrams are preserved/replayed using the already-reviewed
research transform.  This module itself performs no network I/O.
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
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    source = replay_transform(source)

    # No process signal may reach the Door state machine in this media probe.
    source = _replace_once(
        source,
        "    signal(SIGUSR1, v4_door_signal_handler);\n\n",
        '    printf("MEDIA_VIP_BOOTSTRAP_DOOR_SIGNAL_INSTALLED=false\\n");\n\n',
        "remove Door signal handler",
    )

    door_tick = """    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );

"""
    source = _replace_once(source, door_tick, "", "remove Door tick")

    # Make the advertised surface match the actual unreachable Door path.
    source = _replace_once(
        source,
        '                    "V4_DOOR_ACTION_SURFACE_PRESENT=true\\n"\n',
        '                    "V4_DOOR_ACTION_SURFACE_PRESENT=false\\n"\n',
        "Door surface marker",
    )

    # The first proven listener-ready state is the terminal success boundary.
    ready_anchor = """                printf(
                    \"V4_MEDIA_ACTION_SURFACE_PRESENT=false\\n\"
                );

"""
    ready_replacement = """                printf(
                    \"V4_MEDIA_ACTION_SURFACE_PRESENT=false\\n\"
                );

                printf(\"MEDIA_VIP_BOOTSTRAP_RESULT=PASS\\n\");
                printf(\"MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false\\n\");
                printf(\"MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false\\n\");
                printf(\"MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false\\n\");
                fflush(stdout);

                if (loop)
                    g_main_loop_quit(loop);

"""
    source = _replace_once(
        source,
        ready_anchor,
        ready_replacement,
        "listener-ready terminal boundary",
    )

    main_anchor = """int
main(void)
{
"""
    timeout_helper = r'''static gboolean
media_vip_bootstrap_timeout_cb(gpointer data)
{
    (void)data;

    if (v4_listener_ready)
        return G_SOURCE_REMOVE;

    failed = TRUE;
    fprintf(stderr, "MEDIA_VIP_BOOTSTRAP_TIMEOUT=true\n");
    printf("MEDIA_VIP_BOOTSTRAP_RESULT=TIMEOUT\n");
    printf("MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false\n");
    printf("MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false\n");
    printf("MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false\n");
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
        "bootstrap timeout callback",
    )

    long_timeout = """    g_timeout_add_seconds(
        3300,
        absolute_timeout_cb,
        NULL
    );
"""
    bounded_timeout = """    g_timeout_add_seconds(
        90,
        media_vip_bootstrap_timeout_cb,
        NULL
    );
"""
    source = _replace_once(
        source,
        long_timeout,
        bounded_timeout,
        "bounded media bootstrap timeout",
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

    print("MEDIA_VIP_BOOTSTRAP_TRANSFORM=PASS")
    print("PSEUDOTCP_EARLY_DATAGRAM_REPLAY=ENABLED")
    print("MEDIA_VIP_BOOTSTRAP_TERMINAL=V4_RING_LISTENER_READY")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("SELF_ACTIVATION_SENT=false")
    print("MEDIA_SIGNALING_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
