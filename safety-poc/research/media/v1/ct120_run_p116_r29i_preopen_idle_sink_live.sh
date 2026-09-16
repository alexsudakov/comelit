#!/usr/bin/env bash
# P116/R29I research runner hardening layer.
#
# This wrapper reuses the reviewed R29C live runner but changes two research-only
# instrumentation/lifetime details:
#   1. build the R29I candidate whose registered listener can remain in bounded
#      WAITING_FOR_RING idle across the inherited entrance signaling timer;
#   2. finalize UDP sinks through an explicit count-then-done evidence contract,
#      avoiding reliance on `wait` for a process spawned from command substitution.
#
# LIVE authorization gates and one-shot media safety are inherited unchanged from R29C.
set -u -o pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER="$SCRIPT_DIR/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"

R29C_UNIT_TEST=1
# shellcheck source=/dev/null
source "$BASE_RUNNER"
unset R29C_UNIT_TEST

TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29i_preopen_idle_sink_live.sh
SINK_HELPER_REL=safety-poc/research/media/v1/r29i_udp_sink.py
RING_PROMPT_ISSUED_COUNT=0

# Preserve the base final report and append R29I evidence semantics afterwards.
eval "$(declare -f print_final_block | sed '1s/print_final_block/r29i_base_print_final_block/')"

start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local first_file="$3"
    local label="$4"
    local done_file
    done_file="${count_file%.count}.done"
    rm -f "$count_file" "$first_file" "$done_file" \
      "$count_file.tmp" "$first_file.tmp" "$done_file.tmp"
    python3 "$REPO/$SINK_HELPER_REL" \
      --port "$port" \
      --count-file "$count_file" \
      --first-file "$first_file" \
      --done-file "$done_file" \
      --timeout-seconds "$R29C_OUTER_TIMEOUT_SECONDS" \
      > "$count_file.stdout" 2>&1 &
    local sink_pid=$!
    printf '%s\n' "$sink_pid"
}

wait_for_sink_done() {
    local pid="$1"
    local done_file="$2"
    local polls=${R29I_SINK_FINALIZE_POLLS:-100}
    local poll
    for poll in $(seq 1 "$polls"); do
        if [ -f "$done_file" ]; then
            return 0
        fi
        # If the process is gone without a done marker, finalization evidence failed.
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            return 2
        fi
        sleep 0.1
    done
    return 1
}

finalize_sinks() {
    [ "$SINKS_FINALIZED" = false ] || return 0
    SINKS_FINALIZED=true

    local video_done="$RUN_ROOT/video.done"
    local audio_done="$RUN_ROOT/audio.done"
    local video_rc=0 audio_rc=0
    local pid

    for pid in "$VIDEO_SINK_PID" "$AUDIO_SINK_PID"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done

    wait_for_sink_done "$VIDEO_SINK_PID" "$video_done" || video_rc=$?
    wait_for_sink_done "$AUDIO_SINK_PID" "$audio_done" || audio_rc=$?

    if [ "$video_rc" -eq 0 ] && [ -f "$RUN_ROOT/video.count" ]; then
        VIDEO_SINK_FINALIZED=true
        SINK_FINAL_VIDEO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/video.count" UNKNOWN)"
    else
        VIDEO_SINK_FINALIZED=false
        SINK_FINAL_VIDEO_RTP_DATAGRAMS=UNKNOWN
        FAIL=1
    fi

    if [ "$audio_rc" -eq 0 ] && [ -f "$RUN_ROOT/audio.count" ]; then
        AUDIO_SINK_FINALIZED=true
        SINK_FINAL_AUDIO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/audio.count" UNKNOWN)"
    else
        AUDIO_SINK_FINALIZED=false
        SINK_FINAL_AUDIO_RTP_DATAGRAMS=UNKNOWN
        FAIL=1
    fi

    VIDEO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
    VIDEO_RTP_DATAGRAMS_SINK="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_RTP_DATAGRAMS_SINK="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"

    if [ "$VIDEO_SINK_FINALIZED" = true ] && \
       [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" != NOT_REACHED ] && \
       [ "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" != UNKNOWN ]; then
        if [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" = "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" ]; then
            RTP_COUNTER_CONSISTENCY=PASS
        else
            RTP_COUNTER_CONSISTENCY=FAIL
        fi
    else
        RTP_COUNTER_CONSISTENCY=NOT_COMPARABLE
    fi

    echo "R29I_VIDEO_SINK_JOIN_CONTRACT=$VIDEO_SINK_FINALIZED"
    echo "R29I_AUDIO_SINK_JOIN_CONTRACT=$AUDIO_SINK_FINALIZED"
}

# This function is called exactly once after the runner has emitted `COMELIT R29C RING NOW`.
# It records only what the runner itself can prove. A physical press is external evidence
# and is deliberately not inferred from CALL_INIT presence/absence.
eval "$(declare -f wait_for_call_init | sed '1s/wait_for_call_init/r29i_base_wait_for_call_init/')"
wait_for_call_init() {
    RING_PROMPT_ISSUED_COUNT=$((RING_PROMPT_ISSUED_COUNT + 1))
    r29i_base_wait_for_call_init "$@"
}

print_final_block() {
    r29i_base_print_final_block
    local call_init_count=0
    [ "$CALL_INIT_OBSERVED" = true ] && call_init_count=1
    echo "=== COMELIT P116 R29I RING EVIDENCE ==="
    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"
    echo "PHYSICAL_RING_REPORTED_BY_USER=UNAVAILABLE_TO_RUNNER"
    echo "CALL_INIT_OBSERVED_COUNT=$call_init_count"
    echo "RING_BUDGET_USED_SEMANTICS=LEGACY_ACCEPTED_CALL_INIT_COUNT"
    echo "SINK_FINALIZATION_CONTRACT=COUNT_THEN_DONE_MARKER"
    echo "=== END COMELIT P116 R29I RING EVIDENCE ==="
}

if [ "${R29I_UNIT_TEST:-0}" != 1 ]; then
    main "$@"
fi
