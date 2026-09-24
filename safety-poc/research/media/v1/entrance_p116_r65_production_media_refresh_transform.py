#!/usr/bin/env python3
"""P116/R65 production overlay: indefinite bounded same-session media refresh.

This composes the live-proven R27 repeat-0x001A candidate
(entrance_p116_r27_repeat_001a_transform, itself composed on the canonical
P106+P116 generator that already ships as custom_components/comelit/native/
comelit-media) and removes exactly the two bounds that were specific to the
bounded CT120 live-proof run rather than to production:

  1. R27's R27_MAX_LIVE_OBSERVATION_SECONDS self-termination timer, which
     force-quit the whole media session ~115s after activation so a single
     live attempt could be observed and scored. Production has no such
     self-timeout: the on-demand media lifecycle is already governed
     end-to-end by ComelitMediaSessionManager's 600s hard deadline
     (custom_components/comelit/media_session.py,
     MEDIA_SESSION_HARD_LIMIT_SECONDS) plus STOP_FILE / SIGTERM / SIGINT
     teardown, all already respected by the inherited refresh scheduler.
  2. R27's R27_MAX_REFRESH_COUNT=4 live-proof cap, raised to a defense-in-depth
     backstop sized against that same 600s deadline (see
     R65_PRODUCTION_MAX_REFRESH_COUNT below). The manager's 600s kill is the
     real governing bound; this native cap only guards against a clock or
     scheduling defect that would otherwise refresh forever.

Every safety property proven live in R27 (single outstanding refresh, no
retry after ack timeout or ambiguous response, fail-closed teardown, one
unchanged upstream ICE/PseudoTCP/CTPP/RTPC/self-activation session, no new
setup path, no Door/Gate reachability) is inherited byte-for-byte from R27
and is not re-implemented here.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r27_repeat_001a_transform as r27
from entrance_p116_r27_repeat_001a_transform import DEFAULT_SOURCE


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


# --- derive the two production anchors from the live-proven R27 constants
# instead of retyping them, so this module cannot silently drift from the
# text R27 actually generates. ---

_LIVE_OBSERVATION_TIMER_BLOCK = (
    "    if (g_timeout_add_seconds(R27_MAX_LIVE_OBSERVATION_SECONDS,\n"
    "                              r27_live_observation_timeout_cb, NULL) == 0) {\n"
    '        fprintf(stderr, "R27_OBSERVATION_TIMER_START=FAIL\\n");\n'
    "        return FALSE;\n"
    "    }\n"
)
if _LIVE_OBSERVATION_TIMER_BLOCK not in r27._MEDIA_ACTIVE_NEW:
    raise RuntimeError("R65_LIVE_OBSERVATION_ANCHOR=FAIL")

_MEDIA_ACTIVE_PRODUCTION = r27._MEDIA_ACTIVE_NEW.replace(
    _LIVE_OBSERVATION_TIMER_BLOCK, "", 1
).replace(
    'printf("R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false\\n");',
    'printf("R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=true\\n");\n'
    '    printf("R65_PRODUCTION_REFRESH=true\\n");\n'
    '    printf("R65_REFRESH_SELF_TIMEOUT=false\\n");\n'
    '    printf("R65_REFRESH_BOUND_BY=MANAGER_600S_DEADLINE_OR_TEARDOWN\\n");',
    1,
)
if _MEDIA_ACTIVE_PRODUCTION == r27._MEDIA_ACTIVE_NEW:
    raise RuntimeError("R65_MEDIA_ACTIVE_PROMOTION_ANCHOR=FAIL")

_LIVE_OBSERVATION_FORWARD_DECL = (
    "static gboolean r27_live_observation_timeout_cb(gpointer data);\n"
)
if _LIVE_OBSERVATION_FORWARD_DECL not in r27._STATE_NEW:
    raise RuntimeError("R65_LIVE_OBSERVATION_DECL_ANCHOR=FAIL")

# R27_MAX_REFRESH_COUNT=4 and R27_MAX_SINGLE_SESSION_SECONDS=120 were sized
# for one bounded CT120 live-proof attempt. Production reuses the same
# macro names (all downstream comparisons and prints already reference them
# by name) but raises their values so they describe the indefinite
# production lifecycle instead of the bounded research one:
#   floor(600 / 25) == 24 refreshes at the proven 25s cadence exhaust the
#   600s ComelitMediaSessionManager hard deadline; 32 leaves a defense-in-
#   depth margin above that so the manager's kill -- not this native
#   counter -- is always the governing bound in normal operation.
_R65_MAX_REFRESH_COUNT = 32
_R65_MAX_SESSION_SECONDS = 600  # mirrors MEDIA_SESSION_HARD_LIMIT_SECONDS

_REFRESH_COUNT_OLD = "#define R27_MAX_REFRESH_COUNT 4u\n"
_REFRESH_COUNT_NEW = (
    "/* R65: raised from the R27 live-proof cap (4) to a defense-in-depth\n"
    " * backstop above floor(600s manager deadline / 25s cadence) == 24; the\n"
    " * manager's hard timeout remains the real governing bound. */\n"
    f"#define R27_MAX_REFRESH_COUNT {_R65_MAX_REFRESH_COUNT}u\n"
)

_SESSION_CAP_OLD = "#define R27_MAX_SINGLE_SESSION_SECONDS 120u\n"
_SESSION_CAP_NEW = (
    "/* R65: mirrors ComelitMediaSessionManager.MEDIA_SESSION_HARD_LIMIT_SECONDS\n"
    " * (custom_components/comelit/media_session.py); this native value is\n"
    " * reporting-only and enforces nothing by itself. */\n"
    f"#define R27_MAX_SINGLE_SESSION_SECONDS {_R65_MAX_SESSION_SECONDS}u\n"
)


def _strip_live_observation_callback(candidate: str) -> str:
    start = candidate.index("\nstatic gboolean\nr27_live_observation_timeout_cb(gpointer data)")
    end = candidate.index("\n/* === R27_REPEAT_001A_END === */", start)
    return candidate[:start] + candidate[end:]


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("R65 requires --include-p116; --no-include-p116 is fail-closed")
    candidate = r27.transform(source, include_p116=True)
    candidate = _replace_once(
        candidate,
        r27._MEDIA_ACTIVE_NEW,
        _MEDIA_ACTIVE_PRODUCTION,
        "R65 remove live-observation self-timeout",
    )
    candidate = _replace_once(
        candidate,
        _LIVE_OBSERVATION_FORWARD_DECL,
        "",
        "R65 remove live-observation forward declaration",
    )
    candidate = _strip_live_observation_callback(candidate)
    candidate = _replace_once(
        candidate, _REFRESH_COUNT_OLD, _REFRESH_COUNT_NEW, "R65 production refresh count backstop"
    )
    candidate = _replace_once(
        candidate, _SESSION_CAP_OLD, _SESSION_CAP_NEW, "R65 production session cap mirror"
    )
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R65 PRODUCTION MEDIA REFRESH TRANSFORM ===",
            "R65_COMPOSES=R27_REPEAT_001A",
            "R65_PRODUCTION_REFRESH=true",
            "R65_REFRESH_SELF_TIMEOUT=false",
            "R65_REFRESH_BOUND_BY=MANAGER_600S_DEADLINE_OR_TEARDOWN",
            f"R65_PRODUCTION_MAX_REFRESH_COUNT={_R65_MAX_REFRESH_COUNT}",
            "REFRESH_CADENCE_SECONDS=25",
            "CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE",
            "CADENCE_SAFETY_MARGIN_SECONDS=11",
            "REFRESH_OVERLAP=false",
            "REFRESH_RETRY=false",
            "DOOR_ACTION_SENT=false",
            "GATE_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R65 PRODUCTION MEDIA REFRESH TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    p116 = parser.add_mutually_exclusive_group()
    p116.add_argument("--include-p116", dest="include_p116", action="store_true")
    p116.add_argument("--no-include-p116", dest="include_p116", action="store_false")
    parser.set_defaults(include_p116=True)
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report is used")
    if not args.include_p116:
        parser.error("R65 requires --include-p116; --no-include-p116 is fail-closed")

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    args.output.write_text(
        transform(source_path.read_text(encoding="utf-8"), include_p116=True),
        encoding="utf-8",
    )
    print("P116_R65_PRODUCTION_MEDIA_REFRESH_TRANSFORM=PASS")
    print("R65_COMPOSES=R27_REPEAT_001A")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
