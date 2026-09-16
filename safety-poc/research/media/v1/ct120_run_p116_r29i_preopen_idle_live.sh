#!/usr/bin/env bash
# P116/R29I research-only wrapper around the bounded R29C live runner.
#
# This layer does not authorise live execution.  It hardens two tooling/lifetime
# defects observed after R29H:
#   1) the generated candidate keeps the registered/ready listener alive while
#      waiting for the first CALL_INIT (implemented by the R29I transform);
#   2) RTP sink finalization uses deterministic process-exit acknowledgement
#      instead of relying on `wait` for a process created under command
#      substitution/subshell ownership.
set -u -o pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh
R29I_RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29i_preopen_idle_live.sh
R29I_TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py
R29I_MODEL_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_model.py
R29I_TEST_REL=safety-poc/tests/test_p116_r29i_preopen_idle_and_sink_ownership.py
R29I_DOC_REL=safety-poc/research/media/v1/P116_R29I_PREOPEN_IDLE_AND_SINK_OWNERSHIP_HARDENING.md

R29C_UNIT_TEST=1
# shellcheck source=/dev/null
source "$SCRIPT_DIR/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"

RUNNER_REL="$R29I_RUNNER_REL"
TRANSFORM_REL="$R29I_TRANSFORM_REL"
CANDIDATE_NAME=comelit-r29i-registered-ctpp-mediareq26-probe
R29I_BASE_MAIN_SHA=${R29I_BASE_MAIN_SHA:-}
RING_PROMPT_ISSUED_COUNT=0
CALL_INIT_OBSERVED_COUNT=0
PHYSICAL_RING_REPORTED_BY_USER=EXTERNAL_EVIDENCE_REQUIRED
R29I_SINK_FINALIZATION_GATE=NOT_RUN

# Keep references to the inherited functions before overriding them.
eval "$(declare -f preflight_gates | sed '1s/preflight_gates/r29c_base_preflight_gates/')"
eval "$(declare -f wait_for_call_init | sed '1s/wait_for_call_init/r29c_base_wait_for_call_init/')"
eval "$(declare -f print_final_block | sed '1s/print_final_block/r29c_base_print_final_block/')"
eval "$(declare -f print_arm_block | sed '1s/print_arm_block/r29c_base_print_arm_block/')"

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
          -e "^$R29I_RUNNER_REL$" \
          -e "^$R29I_TRANSFORM_REL$" \
          -e "^$R29I_MODEL_REL$" \
          -e "^$R29I_TEST_REL$" \
          -e "^$R29I_DOC_REL$" |
        grep -v '^$' || true)"
    if [ -n "$unexpected" ]; then
        echo "R29I_MAIN_LINEAGE_UNEXPECTED=$unexpected"
        fail "R29I_MAIN_LINEAGE_GATE=FAIL"
        return 1
    fi
    echo "R29I_MAIN_LINEAGE_GATE=PASS"
}

preflight_gates() {
    command -v ps >/dev/null 2>&1 || fail "R29I_MISSING_COMMAND=ps"
    r29i_lineage_gate || return 1

    # The R29I gate above replaces the inherited R29C delta allowlist for this
    # wrapper.  Keep the inherited blob/worktree/build gates, but skip only its
    # superseded lineage-list comparison.
    local saved_main_sha="$R29C_MAIN_SHA"
    R29C_MAIN_SHA=""
    r29c_base_preflight_gates
    local rc=$?
    R29C_MAIN_SHA="$saved_main_sha"
    return "$rc"
}

wait_for_call_init() {
    RING_PROMPT_ISSUED_COUNT=$((RING_PROMPT_ISSUED_COUNT + 1))
    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"
    r29c_base_wait_for_call_init "$@"
    local rc=$?
    if [ "$rc" -eq 0 ]; then
        CALL_INIT_OBSERVED_COUNT=$((CALL_INIT_OBSERVED_COUNT + 1))
    fi
    echo "CALL_INIT_OBSERVED_COUNT=$CALL_INIT_OBSERVED_COUNT"
    return "$rc"
}

r29i_pid_exited() {
    local pid="$1"
    [ -n "$pid" ] || return 0
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    local state
    state="$(ps -o stat= -p "$pid" 2>/dev/null | awk 'NR == 1 {print $1}')"
    case "$state" in
        Z*|"") return 0 ;;
        *) return 1 ;;
    esac
}

r29i_wait_pid_exit() {
    local pid="$1"
    local polls="${2:-60}"
    local poll
    for poll in $(seq 1 "$polls"); do
        if r29i_pid_exited "$pid"; then
            return 0
        fi
        sleep 0.1
    done
    return 1
}

r29i_wait_count_file() {
    local file="$1"
    local poll
    for poll in $(seq 1 20); do
        if [ -s "$file" ] && grep -Eq '^[0-9]+$' "$file"; then
            return 0
        fi
        sleep 0.05
    done
    return 1
}

r29i_finalize_one_sink() {
    local label="$1"
    local pid="$2"
    local count_file="$3"
    local started="$4"

    if [ "$started" != true ]; then
        printf '%s\n' NOT_STARTED
        return 0
    fi
    if [ -z "$pid" ]; then
        printf '%s\n' FAILED_NO_PID
        return 1
    fi

    if ! r29i_pid_exited "$pid"; then
        kill -TERM "$pid" 2>/dev/null || true
    fi
    if ! r29i_wait_pid_exit "$pid" 60; then
        kill -KILL "$pid" 2>/dev/null || true
        r29i_wait_pid_exit "$pid" 20 || true
        printf '%s\n' FAILED_TIMEOUT
        return 1
    fi
    if ! r29i_wait_count_file "$count_file"; then
        printf '%s\n' FAILED_COUNT_FILE
        return 1
    fi
    printf '%s\n' PASS
}

finalize_sinks() {
    [ "$SINKS_FINALIZED" = false ] || return 0

    local video_result audio_result
    video_result="$(r29i_finalize_one_sink VIDEO "$VIDEO_SINK_PID" "$RUN_ROOT/video.count" "$VIDEO_SINK_STARTED")"
    audio_result="$(r29i_finalize_one_sink AUDIO "$AUDIO_SINK_PID" "$RUN_ROOT/audio.count" "$AUDIO_SINK_STARTED")"

    VIDEO_SINK_FINALIZED=false
    AUDIO_SINK_FINALIZED=false
    [ "$video_result" = PASS ] && VIDEO_SINK_FINALIZED=true
    [ "$audio_result" = PASS ] && AUDIO_SINK_FINALIZED=true

    SINK_FINAL_VIDEO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/video.count" UNKNOWN)"
    SINK_FINAL_AUDIO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/audio.count" UNKNOWN)"
    VIDEO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
    VIDEO_RTP_DATAGRAMS_SINK="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    AUDIO_RTP_DATAGRAMS_SINK="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"

    if [ "$VIDEO_SINK_STARTED" = true ] && [ "$VIDEO_SINK_FINALIZED" != true ]; then
        R29I_SINK_FINALIZATION_GATE=FAIL
    elif [ "$AUDIO_SINK_STARTED" = true ] && [ "$AUDIO_SINK_FINALIZED" != true ]; then
        R29I_SINK_FINALIZATION_GATE=FAIL
    elif [ "$VIDEO_SINK_STARTED" = true ] && [ "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" = UNKNOWN ]; then
        R29I_SINK_FINALIZATION_GATE=FAIL
    elif [ "$AUDIO_SINK_STARTED" = true ] && [ "$SINK_FINAL_AUDIO_RTP_DATAGRAMS" = UNKNOWN ]; then
        R29I_SINK_FINALIZATION_GATE=FAIL
    else
        R29I_SINK_FINALIZATION_GATE=PASS
    fi

    if { [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" != NOT_REACHED ] &&
         [ "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" != NOT_REACHED ] &&
         [ "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" != UNKNOWN ]; } 2>/dev/null; then
        if [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" = "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" ]; then
            RTP_COUNTER_CONSISTENCY=PASS
        else
            RTP_COUNTER_CONSISTENCY=FAIL
        fi
    else
        RTP_COUNTER_CONSISTENCY=NOT_COMPARABLE
    fi

    SINKS_FINALIZED=true
    echo "R29I_VIDEO_SINK_FINALIZE_RESULT=$video_result"
    echo "R29I_AUDIO_SINK_FINALIZE_RESULT=$audio_result"
    echo "R29I_SINK_FINALIZATION_GATE=$R29I_SINK_FINALIZATION_GATE"

    if [ "$R29I_SINK_FINALIZATION_GATE" != PASS ]; then
        RESULT_CASE=E
        RESULT=INCONCLUSIVE_TOOLING_FAILURE
        EARLY_RESULT=INCONCLUSIVE_TOOLING_FAILURE
        return 1
    fi
    return 0
}

r29i_print_evidence() {
    echo "=== COMELIT P116 R29I EVIDENCE ==="
    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"
    echo "PHYSICAL_RING_REPORTED_BY_USER=$PHYSICAL_RING_REPORTED_BY_USER"
    echo "CALL_INIT_OBSERVED_COUNT=$CALL_INIT_OBSERVED_COUNT"
    echo "R29I_SINK_FINALIZATION_GATE=$R29I_SINK_FINALIZATION_GATE"
    echo "=== END COMELIT P116 R29I EVIDENCE ==="
}

print_final_block() {
    r29i_print_evidence
    r29c_base_print_final_block
}

print_arm_block() {
    r29i_print_evidence
    r29c_base_print_arm_block
}

on_exit() {
    local rc=$?
    trap - EXIT
    if [ "$R29C_PHASE" = LIVE ] && [ "$LIVE_ATTEMPT_BUDGET_USED" -eq 1 ]; then
        close_research_session || rc=92
        restore_listener || rc=91
    else
        finalize_sinks || rc=92
        stop_pid "$WATCHDOG_PID"
    fi
    if [ "$R29C_PHASE" = LIVE ]; then
        print_final_block
    else
        print_arm_block
    fi
    exit "$rc"
}

if [ "${R29I_UNIT_TEST:-0}" != 1 ]; then
    main "$@"
fi
