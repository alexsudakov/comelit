#!/usr/bin/env bash
# Future CT120 P78 one-shot entrance-media live-closure launcher.
#
# The launcher is fail-closed until the reviewed/merged main commit SHA is
# supplied through P78_REVIEW_COMMIT_SHA and P78_REVIEWED_LIVE_RUN=YES.
# It never stops/restarts the persistent listener and permits one live wrapper
# invocation guarded by an atomic one-shot sentinel.
set -u -o pipefail
umask 077

REPO="${P78_REPO:-/root/comelit-door-diag-repo}"
REMOTE_REF=refs/remotes/origin/main
BASE_MAIN_SHA=661f9d4c26350f2fdbce0a1c55b04ad1e5c86ee2
P78_REVIEW_COMMIT_SHA="${P78_REVIEW_COMMIT_SHA:-}"

SENTINEL=/root/.comelit-p78-live-consumed
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
CAPTURE_WINDOW_SECONDS=12
CAPTURE_DLT=LINUX_SLL2
HA_WEBHOOK_URL="${P78_HA_CONTROL_WEBHOOK:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"

BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh
BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
SOURCE_BLOB=c6bdfc17edbfb58d6d87c0c6e9dd58082752734b
SIGNAL_TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py
SIGNAL_TRANSFORM_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30
ACK_TRANSFORM_REL=safety-poc/research/media/v1/entrance_device_video_ack_observation_transform.py
ACK_TRANSFORM_BLOB=5a87e2531c2cef0297d8a7e84d75f9d4f2182311
P76_TRANSFORM_REL=safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
P76_TRANSFORM_BLOB=e00c1b59b3bed5b9c2c745616c2a44c43b49c1d6
P77_ORACLE_REL=safety-poc/research/media/v1/entrance_p77_offset8_h264_extraction_contract.py
P77_ORACLE_BLOB=e19a8d139e1efbbb52b108e89d5e5d2a6276130f
WRAPPER_TEMPLATE_REL=safety-poc/deploy/p13_wrapper_template.sh
WRAPPER_TEMPLATE_BLOB=04594421ffde94ef3bbcb1a2434e256db52d7516
P78_LAUNCHER_REL=safety-poc/research/media/v1/ct120_run_entrance_p78_one_shot_live_closure.sh
P78_TRANSFORM_REL=safety-poc/research/media/v1/entrance_p78_rtpc_media_live_stage_transform.py
P78_VERIFIER_REL=safety-poc/research/media/v1/entrance_p78_capture_verifier.py

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p78-live-closure-$STAMP"
DETAIL_LOG="$RUN_ROOT/detail.log"
CANDIDATE_C="$RUN_ROOT/p78_candidate.c"
CANDIDATE_HOLDER="$RUN_ROOT/comelit_ice_offer_holder_p78"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p78"
PCAP_PATH="$RUN_ROOT/p78-media.pcap"
MEDIA_OUT="$RUN_ROOT/media-out"

echo 'LISTENER_CHANGED=NO'
echo 'P78_SENTINEL_CONSUMED=false'
echo 'DOOR_ACTION_SENT_COUNT=0'
echo 'AUTOMATIC_RETRY=false'
echo 'SECOND_CTPP_OPEN=false'
echo 'LIVE_INVOCATIONS=0'
echo 'P78_LISTENER_CONTROL_MODE=STATUS_ONLY'
echo 'P78_LISTENER_STOP_START_RESTART=false'
echo 'P78_LIVE_INVOCATION_LIMIT=1'
echo 'P78_AUTO_RETRY=false'
echo 'P78_CTPP_REGISTERED_REUSED=true'
echo 'P78_SECOND_CTPP_OPEN=false'
echo 'P78_DEVICE_0008_ACK_GATE_PROVEN=false'
echo 'P78_MEDIA_PAYLOAD_STDOUT=false'
echo 'P78_RAW_PAYLOAD_EMITTED=false'
echo 'P78_DOOR_ACTION_SENT=false'
echo 'P78_HOME_ASSISTANT_CORE_STOPPED=false'
echo 'P78_HOME_ASSISTANT_CORE_RESTARTED=false'
echo 'P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
echo 'P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false'
echo 'P78_DECODE_REQUIRED=true'
echo "P78_MEDIA_CAPTURE_DLT=$CAPTURE_DLT"

fail() {
    echo "$1"
    echo 'P78_RUN_RESULT=FAIL'
    exit "${2:-1}"
}

repo_blob() {
    local commit="$1"
    local rel="$2"
    git -C "$REPO" rev-parse "$commit:$rel" 2>/dev/null || true
}

working_blob() {
    local rel="$1"
    git -C "$REPO" hash-object "$rel" 2>/dev/null || true
}

status_only() {
    local output="$1"
    curl -sS --max-time 10 -o "$output" \
        -H 'Content-Type: application/json' \
        -d '{"action":"status"}' \
        "$HA_WEBHOOK_URL"
}

require_status_running_ready() {
    local output="$1"
    python3 - "$output" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
ok = (
    data.get("ok") is True
    and data.get("action") == "status"
    and data.get("supervisor_running") is True
    and data.get("running") is True
    and data.get("listener_ready") is True
    and data.get("last_error") is None
)
raise SystemExit(0 if ok else 1)
PY
}

detail_marker_value() {
    local key="$1"
    local line

    line="$(grep -E "^${key}=" "$DETAIL_LOG" | tail -n 1 || true)"
    if [[ -n "$line" ]]; then
        printf '%s\n' "${line#*=}"
    else
        printf '%s\n' 'NOT_REACHED'
    fi
}

emit_detail_marker() {
    local launcher_key="$1"
    local holder_key="$2"
    printf '%s=%s\n' "$launcher_key" "$(detail_marker_value "$holder_key")"
}

emit_holder_results() {
    emit_detail_marker 'P78_SELF_ACTIVATION_SENT' 'ENTRANCE_SELF_ACTIVATION_SENT'
    emit_detail_marker 'P78_CLIENT_VIDEO_EVENT_SENT' 'ENTRANCE_VIDEO_EVENT_SENT'
    emit_detail_marker 'P78_DEVICE_0008_EVENT' 'ENTRANCE_DEVICE_VIDEO_EVENT'
    emit_detail_marker 'P78_DEVICE_0008_ACK_SENT' 'P78_DEVICE_0008_ACK_SENT'
    emit_detail_marker 'P78_RTPC_OPEN_1_SENT' 'P78_RTPC_OPEN_1_SENT'
    emit_detail_marker 'P78_RTPC_OPEN_2_SENT' 'P78_RTPC_OPEN_2_SENT'
    emit_detail_marker 'P78_RTPC_DEVICE_OPEN_OBSERVED' 'P78_RTPC_DEVICE_OPEN_OBSERVED'
    emit_detail_marker 'P78_RTPC_CLIENT_RESPONSE_SENT' 'P78_RTPC_CLIENT_RESPONSE_SENT'
    emit_detail_marker 'P78_RTPC_DEVICE_RESPONSE_1' 'P78_RTPC_DEVICE_RESPONSE_1'
    emit_detail_marker 'P78_RTPC_DEVICE_RESPONSE_2' 'P78_RTPC_DEVICE_RESPONSE_2'
    emit_detail_marker 'P78_RTPC_CLIENT_000A_SENT' 'P78_RTPC_CLIENT_000A_SENT'
    emit_detail_marker 'P78_RTPC_CLIENT_001A_SENT' 'P78_RTPC_CLIENT_001A_SENT'
    emit_detail_marker 'P78_RTPC_SIGNALING_RESULT' 'P78_RTPC_SIGNALING_RESULT'
}

verifier_marker_value() {
    local key="$1"
    local file="$2"
    local line

    line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
    if [[ -n "$line" ]]; then
        printf '%s\n' "${line#*=}"
    else
        printf '%s\n' 'NOT_PROVIDED'
    fi
}

emit_verifier_final_markers() {
    local verifier_output="$1"
    local key

    for key in \
        P78_H264_ORACLE \
        P78_DECODE_REQUESTED \
        P78_FFPROBE_STATUS \
        P78_FFMPEG_DECODE_STATUS \
        P78_SCRATCH_JPEG_CREATED \
        P78_SCRATCH_JPEG_COUNT \
        P78_DECODE_STATUS
    do
        printf '%s=%s\n' "$key" "$(verifier_marker_value "$key" "$verifier_output")"
    done
}

consume_sentinel() {
    local rc

    python3 - "$SENTINEL" <<'PY'
import os
import sys

path = sys.argv[1]
created = False
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(76)
created = True
try:
    try:
        os.write(fd, b"CONSUMED_BEFORE_LIVE_ENTRYPOINT\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
except Exception:
    if created:
        try:
            os.unlink(path)
        except OSError:
            pass
    raise SystemExit(77)
PY
    rc=$?

    if [[ "$rc" -eq 76 ]]; then
        echo 'P78_SENTINEL_PREEXISTING=true'
        echo 'P78_RUN_RESULT=FAIL'
        exit 76
    fi
    if [[ "$rc" -ne 0 ]]; then
        fail 'P78_SENTINEL_CREATE=FAIL' 77
    fi

    echo 'P78_SENTINEL_PREEXISTING=false'
    echo 'P78_LIVE_CONSUMED_SENTINEL=CREATED_BEFORE_LIVE'
    echo 'P78_SENTINEL_CONSUMED=true'
}

[[ "${EUID}" -eq 0 ]] || fail 'P78_PREFLIGHT=FAIL reason=ROOT_REQUIRED'
mkdir -p "$RUN_ROOT" "$MEDIA_OUT" || fail 'P78_PREFLIGHT=FAIL reason=SCRATCH_CREATE'
chmod 700 "$RUN_ROOT" "$MEDIA_OUT"
: >"$DETAIL_LOG"
chmod 600 "$DETAIL_LOG"

for command in git python3 cc pkg-config sha256sum timeout grep awk curl tcpdump ffprobe ffmpeg; do
    command -v "$command" >/dev/null 2>&1 || fail "P78_PREFLIGHT=FAIL reason=MISSING_$command"
done

if [[ -e "$SENTINEL" ]]; then
    echo 'P78_SENTINEL_PREEXISTING=true'
    exit 76
fi
echo 'P78_SENTINEL_PREEXISTING=false'

[[ -d "$REPO/.git" ]] || fail 'P78_PREFLIGHT=FAIL reason=REPO_MISSING'
[[ -n "$P78_REVIEW_COMMIT_SHA" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_REVIEW_COMMIT_SHA_EMPTY'

remote_main="$(git -C "$REPO" rev-parse "$REMOTE_REF" 2>/dev/null || true)"
[[ "$remote_main" == "$P78_REVIEW_COMMIT_SHA" ]] || fail 'P78_REVIEW_PIN=FAIL reason=ORIGIN_MAIN_NOT_REVIEW_COMMIT'

local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
[[ "$local_head" == "$P78_REVIEW_COMMIT_SHA" ]] || fail 'P78_REVIEW_PIN=FAIL reason=LOCAL_HEAD_NOT_REVIEW_COMMIT'

git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN_SHA" "$P78_REVIEW_COMMIT_SHA" || fail 'P78_REVIEW_PIN=FAIL reason=BASE_NOT_ANCESTOR'

[[ "$(repo_blob "$BASE_MAIN_SHA" "$BASE_RUNNER_REL")" == "$BASE_RUNNER_BLOB" ]] || fail 'P78_BASE_RUNNER_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$SOURCE_REL")" == "$SOURCE_BLOB" ]] || fail 'P78_SOURCE_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$SIGNAL_TRANSFORM_REL")" == "$SIGNAL_TRANSFORM_BLOB" ]] || fail 'P78_SIGNAL_TRANSFORM_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$ACK_TRANSFORM_REL")" == "$ACK_TRANSFORM_BLOB" ]] || fail 'P78_ACK_TRANSFORM_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$P76_TRANSFORM_REL")" == "$P76_TRANSFORM_BLOB" ]] || fail 'P78_P76_TRANSFORM_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$P77_ORACLE_REL")" == "$P77_ORACLE_BLOB" ]] || fail 'P78_P77_ORACLE_PIN=FAIL'
[[ "$(repo_blob "$BASE_MAIN_SHA" "$WRAPPER_TEMPLATE_REL")" == "$WRAPPER_TEMPLATE_BLOB" ]] || fail 'P78_WRAPPER_TEMPLATE_PIN=FAIL'

review_launcher_blob="$(repo_blob "$P78_REVIEW_COMMIT_SHA" "$P78_LAUNCHER_REL")"
review_transform_blob="$(repo_blob "$P78_REVIEW_COMMIT_SHA" "$P78_TRANSFORM_REL")"
review_verifier_blob="$(repo_blob "$P78_REVIEW_COMMIT_SHA" "$P78_VERIFIER_REL")"

[[ -n "$review_launcher_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_LAUNCHER_NOT_PINNED'
[[ -n "$review_transform_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_TRANSFORM_NOT_PINNED'
[[ -n "$review_verifier_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_VERIFIER_NOT_PINNED'

[[ "$(working_blob "$P78_LAUNCHER_REL")" == "$review_launcher_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_LAUNCHER_WORKTREE_MISMATCH'
[[ "$(working_blob "$P78_TRANSFORM_REL")" == "$review_transform_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_TRANSFORM_WORKTREE_MISMATCH'
[[ "$(working_blob "$P78_VERIFIER_REL")" == "$review_verifier_blob" ]] || fail 'P78_REVIEW_PIN=FAIL reason=P78_VERIFIER_WORKTREE_MISMATCH'

[[ "$(working_blob "$BASE_RUNNER_REL")" == "$BASE_RUNNER_BLOB" ]] || fail 'P78_BASE_RUNNER_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$SOURCE_REL")" == "$SOURCE_BLOB" ]] || fail 'P78_SOURCE_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$SIGNAL_TRANSFORM_REL")" == "$SIGNAL_TRANSFORM_BLOB" ]] || fail 'P78_SIGNAL_TRANSFORM_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$ACK_TRANSFORM_REL")" == "$ACK_TRANSFORM_BLOB" ]] || fail 'P78_ACK_TRANSFORM_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$P76_TRANSFORM_REL")" == "$P76_TRANSFORM_BLOB" ]] || fail 'P78_P76_TRANSFORM_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$P77_ORACLE_REL")" == "$P77_ORACLE_BLOB" ]] || fail 'P78_P77_ORACLE_WORKTREE_PIN=FAIL'
[[ "$(working_blob "$WRAPPER_TEMPLATE_REL")" == "$WRAPPER_TEMPLATE_BLOB" ]] || fail 'P78_WRAPPER_TEMPLATE_WORKTREE_PIN=FAIL'

echo 'P78_REVIEW_PIN=PASS'

[[ "${P78_REVIEWED_LIVE_RUN:-}" == "YES" ]] || fail 'P78_PREFLIGHT=FAIL reason=REVIEWED_LIVE_RUN_ENV_REQUIRED'

# CT120 preflight proved `any` supports LINUX_SLL2 and not RAW. Re-check the
# exact DLT capability before the sentinel/live boundary without capturing.
tcpdump -i any -y "$CAPTURE_DLT" -d udp >/dev/null 2>&1 || fail 'P78_MEDIA_CAPTURE_DLT_GATE=FAIL'
echo 'P78_MEDIA_CAPTURE_DLT_GATE=PASS'
echo 'P78_PREFLIGHT=PASS'

status_before="$RUN_ROOT/listener-before.json"
status_only "$status_before"
require_status_running_ready "$status_before" || fail 'P78_LISTENER_STATUS_BEFORE=FAIL'
echo 'P78_LISTENER_STATUS_BEFORE=RUNNING_READY'

if pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    echo 'P78_BUILD_DEPS=PASS'
else
    fail 'P78_BUILD_DEPS=FAIL'
fi

python3 "$REPO/$P78_TRANSFORM_REL" \
    --source "$REPO/$SOURCE_REL" \
    --output "$CANDIDATE_C" \
    || fail 'P78_CANDIDATE_TRANSFORM=FAIL'

cc -O2 -g -Wall -Wextra "$CANDIDATE_C" \
    -o "$CANDIDATE_HOLDER" \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
    || fail 'P78_CANDIDATE_BUILD=FAIL'
chmod 700 "$CANDIDATE_HOLDER"
echo 'P78_CANDIDATE_BUILD=PASS'

[[ -f "$BASE_WRAPPER" ]] || fail 'P78_BASE_WRAPPER_PRESENT=false'
base_wrapper_actual="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
[[ "$base_wrapper_actual" == "$BASE_WRAPPER_SHA256" ]] || fail 'P78_BASE_WRAPPER_PIN=FAIL'
echo 'P78_BASE_WRAPPER_PIN=PASS'

python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_HOLDER" <<'PY'
from pathlib import Path
import os
import sys

source = Path(sys.argv[1])
output = Path(sys.argv[2])
holder = sys.argv[3]
needle = '"$BASE/bin/comelit_ice_offer_holder"'
text = source.read_text(encoding="utf-8")
if text.count(needle) != 1:
    raise SystemExit("P78_BASE_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
output.write_text(text, encoding="utf-8")
os.chmod(output, 0o700)
PY
echo 'P78_WRAPPER_DERIVATION=PASS'

capture_pid=""
cleanup_capture() {
    if [[ -n "$capture_pid" ]] && kill -0 "$capture_pid" 2>/dev/null; then
        kill -TERM "$capture_pid" 2>/dev/null || true
        wait "$capture_pid" 2>/dev/null || true
    fi
    capture_pid=""
}
trap cleanup_capture EXIT
trap 'cleanup_capture; exit 130' INT TERM HUP

timeout \
    --signal=TERM \
    --kill-after=2s \
    "${CAPTURE_WINDOW_SECONDS}s" \
    tcpdump -U -i any -y "$CAPTURE_DLT" -w "$PCAP_PATH" udp \
    >/dev/null 2>"$RUN_ROOT/tcpdump.err" &
capture_pid=$!

sleep 0.2
if ! kill -0 "$capture_pid" 2>/dev/null; then
    wait "$capture_pid" 2>/dev/null || true
    capture_pid=""
    fail 'P78_MEDIA_CAPTURE_START=FAIL'
fi

chmod 600 "$PCAP_PATH" 2>/dev/null || true
echo 'P78_MEDIA_CAPTURE_STARTED=true'
echo 'P78_MEDIA_CAPTURE_READY=true'
echo "P78_MEDIA_CAPTURE_WINDOW_SECONDS=$CAPTURE_WINDOW_SECONDS"

consume_sentinel

echo 'P78_WRAPPER_INVOCATIONS=1'
echo 'LIVE_INVOCATIONS=1'
timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" \
    2>&1 | tee -a "$DETAIL_LOG"
wrapper_rc=${PIPESTATUS[0]}
echo "P78_WRAPPER_RC=$wrapper_rc"

capture_rc=0
wait "$capture_pid" || capture_rc=$?
capture_pid=""

capture_ok=false
if [[ "$capture_rc" -eq 0 || "$capture_rc" -eq 124 ]]; then
    capture_ok=true
    echo 'P78_MEDIA_CAPTURE_BOUND=PASS'
else
    echo "P78_MEDIA_CAPTURE_BOUND=FAIL rc=$capture_rc"
fi
chmod 600 "$PCAP_PATH" 2>/dev/null || true

verifier_out="$RUN_ROOT/verifier.out"
python3 "$REPO/$P78_VERIFIER_REL" \
    --pcap "$PCAP_PATH" \
    --output-dir "$MEDIA_OUT" \
    --decode \
    | tee "$verifier_out"
verifier_rc=${PIPESTATUS[0]}
echo "P78_VERIFIER_RC=$verifier_rc"
emit_verifier_final_markers "$verifier_out"

h264_oracle="$(verifier_marker_value 'P78_H264_ORACLE' "$verifier_out")"
ffprobe_status="$(verifier_marker_value 'P78_FFPROBE_STATUS' "$verifier_out")"
ffmpeg_status="$(verifier_marker_value 'P78_FFMPEG_DECODE_STATUS' "$verifier_out")"
decode_status="$(verifier_marker_value 'P78_DECODE_STATUS' "$verifier_out")"
jpeg_count="$(verifier_marker_value 'P78_SCRATCH_JPEG_COUNT' "$verifier_out")"

status_after="$RUN_ROOT/listener-after.json"
listener_after_ok=false
if status_only "$status_after" && require_status_running_ready "$status_after"; then
    listener_after_ok=true
    echo 'P78_LISTENER_STATUS_AFTER=RUNNING_READY'
else
    echo 'P78_LISTENER_STATUS_AFTER=FAIL'
fi

emit_holder_results
terminal_result="$(detail_marker_value 'P78_RTPC_SIGNALING_RESULT')"

if [[ "$wrapper_rc" -eq 0 &&
      "$terminal_result" == "PASS" &&
      "$capture_ok" == true &&
      "$verifier_rc" -eq 0 &&
      "$h264_oracle" == "PASS" &&
      "$ffprobe_status" == "PASS" &&
      "$ffmpeg_status" == "PASS" &&
      "$decode_status" == "PASS" &&
      "$jpeg_count" == "1" &&
      "$listener_after_ok" == true ]]; then
    echo 'P78_RUN_RESULT=PASS'
else
    echo 'P78_RUN_RESULT=UNKNOWN_OUTCOME'
fi
