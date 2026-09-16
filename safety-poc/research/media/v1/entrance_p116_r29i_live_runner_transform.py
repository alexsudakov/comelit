#!/usr/bin/env python3
"""Deterministically transform the merged R29C live runner into the R29I runner.

The overlay is research-only. It switches candidate generation to the R29I
pre-open-idle transform, makes UDP sinks direct children of the runner so they
can be joined deterministically, treats missing final counters after join as a
tooling failure, and separates ring prompt evidence from observed CALL_INIT.
"""
from __future__ import annotations

import argparse
from pathlib import Path


BASE_RUNNER = Path(__file__).with_name("ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def _replace_region(text: str, start: str, next_start: str, replacement: str, label: str) -> str:
    s = text.find(start)
    if s < 0:
        raise RuntimeError(f"{label}: start anchor missing")
    e = text.find(next_start, s)
    if e < 0:
        raise RuntimeError(f"{label}: end anchor missing")
    return text[:s] + replacement.rstrip() + "\n\n" + text[e:]


_START_UDP_SINK = r'''start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local first_file="$3"
    local label="$4"
    local pid_var="$5"
    local status_file="$RUN_ROOT/${label,,}.sink-status.json"
    python3 "$RUN_ROOT/r29i-udp-sink.py" \
      --port "$port" \
      --count-file "$count_file" \
      --first-file "$first_file" \
      --status-file "$status_file" \
      --deadline-seconds "$R29C_OUTER_TIMEOUT_SECONDS" \
      > "$count_file.stdout" 2>&1 &
    local sink_pid=$!
    printf -v "$pid_var" '%s' "$sink_pid"
}'''


_FINALIZE_SINKS = r'''finalize_sinks() {
    [ "$SINKS_FINALIZED" = false ] || return 0
    SINKS_FINALIZED=true
    local pid
    local join_failed=0
    for pid in "$VIDEO_SINK_PID" "$AUDIO_SINK_PID"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$VIDEO_SINK_PID" "$AUDIO_SINK_PID"; do
        [ -n "$pid" ] || { join_failed=1; continue; }
        if ! wait "$pid" 2>/dev/null; then
            join_failed=1
        fi
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            join_failed=1
        fi
    done

    SINK_FINAL_VIDEO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/video.count" UNKNOWN)"
    SINK_FINAL_AUDIO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/audio.count" UNKNOWN)"
    if [ "$join_failed" -eq 0 ] &&
       [[ "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" =~ ^[0-9]+$ ]] &&
       [[ "$SINK_FINAL_AUDIO_RTP_DATAGRAMS" =~ ^[0-9]+$ ]]; then
        VIDEO_SINK_FINALIZED=true
        AUDIO_SINK_FINALIZED=true
        SINK_FINALIZATION_GATE=PASS
    else
        VIDEO_SINK_FINALIZED=false
        AUDIO_SINK_FINALIZED=false
        SINK_FINALIZATION_GATE=FAIL
    fi

    VIDEO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
    VIDEO_RTP_DATAGRAMS_SINK="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_RTP_DATAGRAMS_SINK="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
    if [ "$SINK_FINALIZATION_GATE" = PASS ] &&
       [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" != NOT_REACHED ]; then
        if [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" = "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" ]; then
            RTP_COUNTER_CONSISTENCY=PASS
        else
            RTP_COUNTER_CONSISTENCY=FAIL
        fi
    else
        RTP_COUNTER_CONSISTENCY=NOT_COMPARABLE
    fi
}'''


def transform(text: str) -> str:
    text = _replace_once(
        text,
        "TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py\n",
        "TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py\n"
        "R29I_SINK_HELPER_REL=safety-poc/research/media/v1/entrance_p116_r29i_udp_sink.py\n",
        "R29I transform path",
    )
    text = _replace_once(
        text,
        "RING_BUDGET_USED=0\nOPEN_BUDGET_USED=0\nSTOP_BUDGET_USED=0\n",
        "RING_BUDGET_USED=0\n"
        "RING_PROMPT_ISSUED_COUNT=0\n"
        "CALL_INIT_OBSERVED_COUNT=0\n"
        "PHYSICAL_RING_REPORTED_BY_USER=UNKNOWN\n"
        "OPEN_BUDGET_USED=0\nSTOP_BUDGET_USED=0\n",
        "R29I ring evidence variables",
    )
    text = _replace_once(
        text,
        "AUDIO_FINAL_DATAGRAM_COUNT=UNKNOWN\n",
        "AUDIO_FINAL_DATAGRAM_COUNT=UNKNOWN\nSINK_FINALIZATION_GATE=UNKNOWN\n",
        "R29I sink finalization gate",
    )

    text = _replace_region(text, "start_udp_sink() {", "stop_pid() {", _START_UDP_SINK, "R29I start_udp_sink")
    text = _replace_region(text, "finalize_sinks() {", "sink_bound() {", _FINALIZE_SINKS, "R29I finalize_sinks")

    text = _replace_once(
        text,
        '    VIDEO_SINK_PID="$(start_udp_sink "$MEDIA_VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$RUN_ROOT/video.first" VIDEO)"\n'
        '    AUDIO_SINK_PID="$(start_udp_sink "$MEDIA_AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$RUN_ROOT/audio.first" AUDIO)"\n',
        '    start_udp_sink "$MEDIA_VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$RUN_ROOT/video.first" VIDEO VIDEO_SINK_PID\n'
        '    start_udp_sink "$MEDIA_AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$RUN_ROOT/audio.first" AUDIO AUDIO_SINK_PID\n',
        "R29I direct-child sink launch",
    )

    text = _replace_once(
        text,
        '    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BLOB=FAIL"\n',
        '    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BLOB=FAIL"\n'
        '    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$R29I_SINK_HELPER_REL" > "$RUN_ROOT/r29i-udp-sink.py" || fail "R29I_SINK_HELPER_BLOB=FAIL"\n',
        "R29I sink helper provenance copy",
    )
    text = _replace_once(
        text,
        '    bash -n "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BASH_N=FAIL"\n',
        '    bash -n "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BASH_N=FAIL"\n'
        '    python3 -m py_compile "$RUN_ROOT/r29i-udp-sink.py" || fail "R29I_SINK_HELPER_COMPILE_GATE=FAIL"\n',
        "R29I sink helper compile gate",
    )
    text = _replace_once(
        text,
        '    cmp -s "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" || fail "R29C_BUILDER_WORKTREE_BLOB_GATE=FAIL"\n',
        '    cmp -s "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" || fail "R29C_BUILDER_WORKTREE_BLOB_GATE=FAIL"\n'
        '    cmp -s "$RUN_ROOT/r29i-udp-sink.py" "$REPO/$R29I_SINK_HELPER_REL" || fail "R29I_SINK_HELPER_WORKTREE_BLOB_GATE=FAIL"\n',
        "R29I sink helper worktree gate",
    )

    text = _replace_once(
        text,
        '    echo "COMELIT R29C RING NOW"\n',
        '    RING_PROMPT_ISSUED_COUNT=1\n'
        '    RING_BUDGET_USED=1\n'
        '    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"\n'
        '    echo "RING_BUDGET_USED=$RING_BUDGET_USED"\n'
        '    echo "COMELIT R29I RING NOW"\n',
        "R29I ring prompt evidence",
    )
    text = _replace_once(
        text,
        '    CALL_INIT_OBSERVED=true\n    CALL_SOURCE=entrance\n    RING_BUDGET_USED=1\n'
        '    echo "CALL_INIT_OBSERVED=true"\n    echo "CALL_SOURCE=entrance"\n    echo "RING_BUDGET_USED=$RING_BUDGET_USED"\n',
        '    CALL_INIT_OBSERVED=true\n    CALL_INIT_OBSERVED_COUNT=1\n    CALL_SOURCE=entrance\n'
        '    echo "CALL_INIT_OBSERVED=true"\n    echo "CALL_INIT_OBSERVED_COUNT=$CALL_INIT_OBSERVED_COUNT"\n'
        '    echo "CALL_SOURCE=entrance"\n    echo "RING_BUDGET_USED=$RING_BUDGET_USED"\n',
        "R29I CALL_INIT evidence",
    )
    text = _replace_once(
        text,
        'costs_block() {\n'
        '    echo "R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN"\n'
        '    echo "R29C_LIVE_AUTHORIZED=$R29C_LIVE_AUTHORIZED"\n'
        '    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"\n'
        '    echo "RING_BUDGET_USED=$RING_BUDGET_USED"\n'
        '    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"\n',
        'costs_block() {\n'
        '    echo "R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN"\n'
        '    echo "R29C_LIVE_AUTHORIZED=$R29C_LIVE_AUTHORIZED"\n'
        '    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"\n'
        '    echo "RING_BUDGET_USED=$RING_BUDGET_USED"\n'
        '    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"\n'
        '    echo "CALL_INIT_OBSERVED_COUNT=$CALL_INIT_OBSERVED_COUNT"\n'
        '    echo "PHYSICAL_RING_REPORTED_BY_USER=$PHYSICAL_RING_REPORTED_BY_USER"\n'
        '    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"\n',
        "R29I costs evidence",
    )

    text = _replace_once(
        text,
        'classify() {\n    if [ -n "$EARLY_RESULT" ]; then\n',
        'classify() {\n'
        '    if [ "$SINK_FINALIZATION_GATE" = FAIL ]; then\n'
        '        RESULT_CASE=E\n'
        '        RESULT=INCONCLUSIVE_TOOLING_FAILURE\n'
        '        echo "RESULT_CASE=$RESULT_CASE"\n'
        '        return 0\n'
        '    fi\n'
        '    if [ -n "$EARLY_RESULT" ]; then\n',
        "R29I sink tooling classification",
    )
    text = _replace_once(
        text,
        '    echo "AUDIO_FINAL_DATAGRAM_COUNT=$AUDIO_FINAL_DATAGRAM_COUNT"\n',
        '    echo "AUDIO_FINAL_DATAGRAM_COUNT=$AUDIO_FINAL_DATAGRAM_COUNT"\n'
        '    echo "SINK_FINALIZATION_GATE=$SINK_FINALIZATION_GATE"\n',
        "R29I final sink gate marker",
    )

    for marker in (
        'VIDEO_SINK_PID="$(start_udp_sink',
        'AUDIO_SINK_PID="$(start_udp_sink',
    ):
        if marker in text:
            raise RuntimeError(f"R29I_RUNNER_GATE=FAIL forbidden={marker}")
    for marker in (
        "R29I_SINK_HELPER_REL=",
        "SINK_FINALIZATION_GATE=FAIL",
        "RING_PROMPT_ISSUED_COUNT=",
        "CALL_INIT_OBSERVED_COUNT=",
        "COMELIT R29I RING NOW",
    ):
        if marker not in text:
            raise RuntimeError(f"R29I_RUNNER_GATE=FAIL missing={marker}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=BASE_RUNNER)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(transform(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
