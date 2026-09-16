#!/usr/bin/env bash
# P116/R29I research runner hardening layer.
#
# This wrapper reuses the reviewed R29C live runner but changes two research-only
# instrumentation/lifetime details:
#   1. build the R29I candidate whose registered listener can remain in bounded
#      WAITING_FOR_RING idle across the inherited entrance signaling timer;
#   2. finalize UDP sinks through explicit started -> count -> done evidence,
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
MODEL_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_model.py
DOC_REL=safety-poc/research/media/v1/P116_R29I_PREOPEN_IDLE_AND_SINK_OWNERSHIP_HARDENING.md
TEST_REL=safety-poc/tests/test_p116_r29i_preopen_idle_and_sink_ownership.py
R29I_BASE_MAIN_SHA=${R29I_BASE_MAIN_SHA:-${R29C_MAIN_SHA:-}}
RING_PROMPT_ISSUED_COUNT=0

# Preserve inherited functions before overriding them.
eval "$(declare -f preflight_gates | sed '1s/preflight_gates/r29i_base_preflight_gates/')"
eval "$(declare -f print_final_block | sed '1s/print_final_block/r29i_base_print_final_block/')"
eval "$(declare -f wait_for_call_init | sed '1s/wait_for_call_init/r29i_base_wait_for_call_init/')"

r29i_lineage_gate() {
    [ -n "$R29I_BASE_MAIN_SHA" ] || {
        fail "R29I_BASE_MAIN_SHA_REQUIRED=true"
        return 1
    }
    [ -n "$REPO" ] || {
        fail "R29I_REPO_REQUIRED=true"
        return 1
    }
    [ -n "$R29C_EXPECTED_COMMIT_SHA" ] || {
        fail "R29I_EXPECTED_COMMIT_SHA_REQUIRED=true"
        return 1
    }

    local changed unexpected
    changed="$(git -C "$REPO" diff --name-only "$R29I_BASE_MAIN_SHA" "$R29C_EXPECTED_COMMIT_SHA" | sort)"
    echo "R29I_MAIN_LINEAGE_DIFF_FILES=$(printf '%s' "$changed" | tr '\n' ',')"
    unexpected="$(printf '%s\n' "$changed" |
        grep -v \
          -e "^$RUNNER_REL$" \
          -e "^$TRANSFORM_REL$" \
          -e "^$SINK_HELPER_REL$" \
          -e "^$MODEL_REL$" \
          -e "^$DOC_REL$" \
          -e "^$TEST_REL$" |
        grep -v '^$' || true)"
    if [ -n "$unexpected" ]; then
        echo "R29I_MAIN_LINEAGE_UNEXPECTED=$unexpected"
        fail "R29I_MAIN_LINEAGE_GATE=FAIL"
        return 1
    fi

    local required
    for required in \
        "$RUNNER_REL" \
        "$TRANSFORM_REL" \
        "$SINK_HELPER_REL" \
        "$MODEL_REL" \
        "$DOC_REL" \
        "$TEST_REL"
    do
        printf '%s\n' "$changed" | grep -Fxq "$required" || {
            fail "R29I_MAIN_LINEAGE_REQUIRED_FILE_MISSING=$required"
            return 1
        }
        git -C "$REPO" cat-file -e "$R29C_EXPECTED_COMMIT_SHA:$required" 2>/dev/null || {
            fail "R29I_EXPECTED_BLOB_MISSING=$required"
            return 1
        }
    done
    echo "R29I_MAIN_LINEAGE_GATE=PASS"
}

preflight_gates() {
    r29i_lineage_gate || return 1
    python3 -m py_compile \
        "$REPO/$TRANSFORM_REL" \
        "$REPO/$MODEL_REL" \
        "$REPO/$SINK_HELPER_REL" || {
        fail "R29I_PY_COMPILE_GATE=FAIL"
        return 1
    }

    # The exact R29I lineage gate above supersedes only the older R29C delta allowlist.
    # All other inherited provenance/blob/build/runtime gates remain active.
    local saved_main_sha="$R29C_MAIN_SHA"
    R29C_MAIN_SHA=""
    r29i_base_preflight_gates
    local rc=$?
    R29C_MAIN_SHA="$saved_main_sha"
    return "$rc"
}

start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local first_file="$3"
    local label="$4"
    local base started_file done_file
    base="${count_file%.count}"
    started_file="$base.started"
    done_file="$base.done"
    rm -f "$count_file" "$first_file" "$started_file" "$done_file" \
      "$count_file.tmp" "$first_file.tmp" "$started_file.tmp" "$done_file.tmp"
    python3 "$REPO/$SINK_HELPER_REL" \
      --port "$port" \
      --count-file "$count_file" \
      --first-file "$first_file" \
      --started-file "$started_file" \
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
        # A gone process without the atomically written done marker is an evidence failure.
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

    local video_started="$RUN_ROOT/video.started"
    local audio_started="$RUN_ROOT/audio.started"
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

    if [ -f "$video_started" ] && [ "$video_rc" -eq 0 ] && [ -f "$RUN_ROOT/video.count" ]; then
        VIDEO_SINK_FINALIZED=true
        SINK_FINAL_VIDEO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/video.count" UNKNOWN)"
    else
        VIDEO_SINK_FINALIZED=false
        SINK_FINAL_VIDEO_RTP_DATAGRAMS=UNKNOWN
        FAIL=1
    fi

    if [ -f "$audio_started" ] && [ "$audio_rc" -eq 0 ] && [ -f "$RUN_ROOT/audio.count" ]; then
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

# Called once after `COMELIT R29C RING NOW`; record only runner-observable evidence.
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
    echo "SINK_FINALIZATION_CONTRACT=STARTED_THEN_COUNT_THEN_DONE_MARKER"
    echo "=== END COMELIT P116 R29I RING EVIDENCE ==="
}

if [ "${R29I_UNIT_TEST:-0}" != 1 ]; then
    main "$@"
fi
