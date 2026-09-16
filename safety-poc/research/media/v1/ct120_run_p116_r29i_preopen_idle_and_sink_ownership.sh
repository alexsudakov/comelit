#!/usr/bin/env bash
# P116/R29I research-only wrapper around the promoted R29C live runner.
#
# R29I changes exactly two tooling/lifetime concerns:
#   1. build the R29I transform whose registered idle listener survives the
#      human waiting-for-ring interval;
#   2. finalize RTP sinks with an explicit bounded process-termination/join
#      contract instead of relying on `wait` for PIDs created in a command
#      substitution subshell.
#
# The inherited one-shot live safety contract, production handoff/restore,
# OPEN/STOP budgets and Comelit authorization gates remain owned by the R29C
# runner.  This file does not authorize live execution.
set -u -o pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_RUNNER="$SCRIPT_DIR/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh"

if [ ! -r "$BASE_RUNNER" ]; then
    echo "R29I_BASE_RUNNER_PRESENT=false"
    exit 2
fi

# Import functions/state without executing the inherited main().
R29C_UNIT_TEST=1
# shellcheck disable=SC1090
source "$BASE_RUNNER"
R29C_UNIT_TEST=0

TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_preopen_idle_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29i_preopen_idle_and_sink_ownership.sh
R29I_DOC_REL=safety-poc/research/media/v1/P116_R29I_PREOPEN_IDLE_AND_SINK_OWNERSHIP.md
R29I_TEST_REL=safety-poc/tests/test_p116_r29i_preopen_idle_and_sink_ownership.py
CANDIDATE_NAME=comelit-r29i-preopen-idle-registered-ctpp-mediareq26-probe
SHIM_NAME=p116_r29i_packaged_musl_holder_shim.sh
WRAPPER_NAME=comelit-p2p-cloud-probe-r29i

RING_PROMPT_ISSUED_COUNT=0
CALL_INIT_OBSERVED_COUNT=0
PHYSICAL_RING_REPORTED_BY_USER=${R29I_PHYSICAL_RING_REPORTED_BY_USER:-UNKNOWN}
SINK_JOIN_TIMEOUT_SECONDS=${R29I_SINK_JOIN_TIMEOUT_SECONDS:-5}

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

sink_process_active() {
    local pid="$1"
    local state
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/stat" ] || return 1
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    [ -n "$state" ] && [ "$state" != Z ]
}

terminate_and_join_sink() {
    local pid="$1"
    local label="$2"
    local deadline now

    [ -n "$pid" ] || {
        echo "${label}_SINK_JOIN=NO_PID"
        return 1
    }

    if sink_process_active "$pid"; then
        kill -TERM "$pid" 2>/dev/null || true
    fi

    deadline=$(( $(date +%s) + SINK_JOIN_TIMEOUT_SECONDS ))
    while sink_process_active "$pid"; do
        now="$(date +%s)"
        [ "$now" -lt "$deadline" ] || break
        sleep 0.1
    done

    if sink_process_active "$pid"; then
        kill -KILL "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            sink_process_active "$pid" || break
            sleep 0.1
        done
    fi

    if sink_process_active "$pid"; then
        echo "${label}_SINK_JOIN=FAIL"
        return 1
    fi

    echo "${label}_SINK_JOIN=PASS"
    return 0
}

# Override the inherited finalizer.  start_udp_sink is intentionally left
# unchanged so this function exercises the exact R29G/R29H topology where the
# PID is returned from a command-substitution subshell.  Such a PID is not a
# waitable child of the main runner; bounded TERM + /proc state observation is
# therefore the explicit join contract.  Count files are read only afterwards.
finalize_sinks() {
    [ "$SINKS_FINALIZED" = false ] || return 0

    local video_join=false
    local audio_join=false

    if terminate_and_join_sink "$VIDEO_SINK_PID" VIDEO; then
        video_join=true
    fi
    if terminate_and_join_sink "$AUDIO_SINK_PID" AUDIO; then
        audio_join=true
    fi

    if [ "$video_join" = true ] && [ -f "$RUN_ROOT/video.count" ]; then
        VIDEO_SINK_FINALIZED=true
        SINK_FINAL_VIDEO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/video.count" UNKNOWN)"
        VIDEO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
        VIDEO_RTP_DATAGRAMS_SINK="$SINK_FINAL_VIDEO_RTP_DATAGRAMS"
    else
        VIDEO_SINK_FINALIZED=false
        SINK_FINAL_VIDEO_RTP_DATAGRAMS=UNKNOWN
        VIDEO_FINAL_DATAGRAM_COUNT=UNKNOWN
        VIDEO_RTP_DATAGRAMS_SINK=UNKNOWN
        [ "$VIDEO_SINK_STARTED" != true ] || fail "R29I_VIDEO_SINK_FINAL_COUNT_MISSING=true"
    fi

    if [ "$audio_join" = true ] && [ -f "$RUN_ROOT/audio.count" ]; then
        AUDIO_SINK_FINALIZED=true
        SINK_FINAL_AUDIO_RTP_DATAGRAMS="$(read_sink_count "$RUN_ROOT/audio.count" UNKNOWN)"
        AUDIO_FINAL_DATAGRAM_COUNT="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
        AUDIO_RTP_DATAGRAMS_SINK="$SINK_FINAL_AUDIO_RTP_DATAGRAMS"
    else
        AUDIO_SINK_FINALIZED=false
        SINK_FINAL_AUDIO_RTP_DATAGRAMS=UNKNOWN
        AUDIO_FINAL_DATAGRAM_COUNT=UNKNOWN
        AUDIO_RTP_DATAGRAMS_SINK=UNKNOWN
        [ "$AUDIO_SINK_STARTED" != true ] || fail "R29I_AUDIO_SINK_FINAL_COUNT_MISSING=true"
    fi

    if [ "$VIDEO_SINK_FINALIZED" = true ] && [ "$AUDIO_SINK_FINALIZED" = true ]; then
        SINKS_FINALIZED=true
    else
        SINKS_FINALIZED=false
    fi

    if is_uint "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" &&
       is_uint "$SINK_FINAL_VIDEO_RTP_DATAGRAMS"; then
        if [ "$CANDIDATE_REPORTED_VIDEO_RTP_PACKETS" = "$SINK_FINAL_VIDEO_RTP_DATAGRAMS" ]; then
            RTP_COUNTER_CONSISTENCY=PASS
        else
            RTP_COUNTER_CONSISTENCY=FAIL
        fi
    else
        RTP_COUNTER_CONSISTENCY=NOT_COMPARABLE
    fi

    echo "VIDEO_SINK_FINALIZED=$VIDEO_SINK_FINALIZED"
    echo "VIDEO_FINAL_DATAGRAM_COUNT=$VIDEO_FINAL_DATAGRAM_COUNT"
    echo "AUDIO_SINK_FINALIZED=$AUDIO_SINK_FINALIZED"
    echo "AUDIO_FINAL_DATAGRAM_COUNT=$AUDIO_FINAL_DATAGRAM_COUNT"
    echo "R29I_FINAL_COUNTERS_READ_AFTER_JOIN=true"
}

# Override only the polling wrapper to make ring evidence semantics explicit.
# Invocation of this function follows the literal `COMELIT R29C RING NOW`
# prompt in inherited main(), so entering it proves the prompt was issued.  A
# physical press remains orchestration/user evidence and is never inferred from
# absence/presence of CALL_INIT.
wait_for_call_init() {
    local timeout_seconds="$1"
    local iterations poll
    RING_PROMPT_ISSUED_COUNT=1
    iterations="$(python3 - "$timeout_seconds" <<'PY'
import math
import sys
print(max(1, math.ceil(float(sys.argv[1]) * 2)))
PY
)"
    for poll in $(seq 1 "$iterations"); do
        if [ "$(last_marker CALL_TRANSACTION_CREATED "")" = true ]; then
            CALL_INIT_OBSERVED_COUNT=1
            return 0
        fi
        if marker_present 'R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true'; then
            return 1
        fi
        sleep 0.5
    done
    return 1
}

# Preserve inherited counters and add unambiguous evidence fields.
costs_block() {
    echo "R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN"
    echo "R29C_LIVE_AUTHORIZED=$R29C_LIVE_AUTHORIZED"
    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"
    echo "RING_BUDGET_USED=$RING_BUDGET_USED"
    echo "RING_BUDGET_MEANING=CALL_INIT_ACCEPTED_NOT_PHYSICAL_PRESS"
    echo "RING_PROMPT_ISSUED_COUNT=$RING_PROMPT_ISSUED_COUNT"
    echo "PHYSICAL_RING_REPORTED_BY_USER=$PHYSICAL_RING_REPORTED_BY_USER"
    echo "CALL_INIT_OBSERVED_COUNT=$CALL_INIT_OBSERVED_COUNT"
    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"
    echo "STOP_BUDGET_USED=$STOP_BUDGET_USED"
    echo "SELF_ACTIVATION_001A_SENT_COUNT=$SELF_ACTIVATION_001A_SENT_COUNT"
    echo "R27_REPEAT_001A_SENT_COUNT=$R27_REPEAT_001A_SENT_COUNT"
    echo "DOOR_ACTIONS_SENT=$DOOR_ACTIONS_SENT"
    echo "GATE_ACTIONS_SENT=$GATE_ACTIONS_SENT"
    echo "REFRESH_LOOP_STARTED_COUNT=$REFRESH_LOOP_STARTED_COUNT"
    echo "HA_DEPLOY_COUNT=0"
    echo "HA_RESTART_COUNT=0"
    echo "HA_RELOAD_COUNT=0"
}

# Exact R29I lineage gate.  The old R29C preflight cannot know files created
# after its promotion, so retain all of its provenance/build gates while
# allowing only this phase's four tracked files relative to R29C_MAIN_SHA.
preflight_gates() {
    [ "${EUID}" -eq 0 ] || fail "R29C_ROOT_GATE=FAIL"
    for command in git python3 curl sha256sum timeout awk grep sed bash chmod install cmp chroot find sort rm ss pgrep wc date seq; do
        command -v "$command" >/dev/null 2>&1 || fail "R29C_MISSING_COMMAND=$command"
    done
    [ -n "$REPO" ] || fail "R29C_REPO_REQUIRED=true"
    [ -n "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_REQUIRED=true"
    [ -n "$R29C_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "R29C_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
    [ -n "$R29C_MAIN_SHA" ] || fail "R29I_MAIN_SHA_REQUIRED=true"
    [ -d "$REPO/.git" ] || fail "R29C_REPO_PRESENT=false"
    [ -x "$BASE_WRAPPER" ] || fail "R29C_BASE_WRAPPER_PRESENT=false"
    [ "$FAIL" -eq 0 ] || return 1

    local actual_wrapper_sha
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "R29C_BASE_WRAPPER_SHA_GATE=FAIL"

    local repo_head
    repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "R29C_REPO_HEAD=$repo_head"
    [ "$repo_head" = "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_GATE=FAIL"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R29C_WORKTREE_CLEAN=FAIL"

    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "R29C_TRANSFORM_BLOB=FAIL"
    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BLOB=FAIL"
    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BLOB=FAIL"
    bash -n "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BASH_N=FAIL"
    bash -n "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BASH_N=FAIL"
    cmp -s "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" || fail "R29C_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
    cmp -s "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" || fail "R29C_RUNNER_WORKTREE_BLOB_GATE=FAIL"
    cmp -s "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" || fail "R29C_BUILDER_WORKTREE_BLOB_GATE=FAIL"

    local changed unexpected
    changed="$(git -C "$REPO" diff --name-only "$R29C_MAIN_SHA" "$R29C_EXPECTED_COMMIT_SHA" | sort)"
    echo "R29I_MAIN_LINEAGE_DIFF_FILES=$(printf '%s' "$changed" | tr '\n' ',')"
    unexpected="$(printf '%s\n' "$changed" |
        grep -v \
          -e "^$RUNNER_REL$" \
          -e "^$TRANSFORM_REL$" \
          -e "^$R29I_DOC_REL$" \
          -e "^$R29I_TEST_REL$" |
        grep -v '^$' || true)"
    if [ -n "$unexpected" ]; then
        fail "R29I_MAIN_LINEAGE_GATE=FAIL"
    else
        echo "R29I_MAIN_LINEAGE_GATE=PASS"
    fi

    [ "$FAIL" -eq 0 ] || return 1
    echo "R29C_PREFLIGHT=PASS"
    echo "R29I_PREFLIGHT=PASS"
}

if [ "${R29I_UNIT_TEST:-0}" != 1 ]; then
    main "$@"
fi
