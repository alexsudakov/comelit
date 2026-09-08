#!/bin/bash
# Future CT120 P79 cloud-only listener concurrency probe.
set -uo pipefail
umask 077

REPO="${P79_REPO:-/root/comelit-door-diag-repo}"
REMOTE_REF=refs/remotes/origin/main
BASE_MAIN_SHA=9a931c96ab04cc5e489e4c539b98d3b8c699d957
P79_REVIEW_COMMIT_SHA="${P79_REVIEW_COMMIT_SHA:-}"
P79_INSTALLED_WRAPPER_SHA256="${P79_INSTALLED_WRAPPER_SHA256:-}"

SENTINEL=/root/.comelit-p79-live-consumed
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
POST_RESULT_OBSERVATION_SECONDS=30
STATUS_POLL_INTERVAL_SECONDS=5
POST_RESULT_STATUS_SAMPLES=6
HA_PORT="${P79_HA_PORT:-8123}"
HA_WEBHOOK_URL="http://127.0.0.1:${HA_PORT}/api/webhook/comelit-ha-ring-test-control-v1"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p79-cloud-concurrency-$STAMP"
DETAIL_LOG="$RUN_ROOT/detail.log"
CLASSIFIER_OUT="$RUN_ROOT/classifier.out"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p79-cloud-only"
P79_NATIVE_RUN_DIR="$RUN_ROOT/native-run"
P79_LAUNCHER_REL=safety-poc/research/listener/v1/ct120_run_p79_cloud_concurrency_probe.sh
P79_CLASSIFIER_REL=safety-poc/research/listener/v1/p79_cloud_concurrency_classifier.py
P79_CLASSIFIER_TERMINAL_MARKERS=(
    P79_CLOUD_CONCURRENCY
    P79_LISTENER_STABILITY
    P79_TIMEOUT_RECONNECT_ASSOCIATION
    P79_RUN_RESULT
)

echo 'P79_SENTINEL_CONSUMED=false'
echo 'P79_LIVE_INVOCATION_LIMIT=1'
echo 'P79_WRAPPER_INVOCATIONS=0'
echo 'AUTOMATIC_RETRY=false'
echo 'P79_AUTO_RETRY=false'
echo 'P79_LISTENER_CONTROL_MODE=STATUS_ONLY'
echo 'ICE_CONNECTIVITY_SKIPPED=true'
echo 'PSEUDOTCP_SKIPPED=true'
echo 'CTPP_APPLICATION_SIGNALING_SKIPPED=true'
echo 'DOOR_ACTION_SENT=false'
echo 'SELF_ACTIVATION_SENT=false'
echo 'MEDIA_SIGNALING_SENT=false'
echo 'RAW_SDP_EMITTED=false'
echo 'RAW_PAYLOAD_EMITTED=false'

blocked() {
    echo "$1"
    echo 'P79_RUN_RESULT=BLOCKED'
    exit 2
}

fail() {
    echo "$1"
    echo 'P79_RUN_RESULT=FAIL'
    exit 1
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

json_scalar() {
    local input="$1"
    local key="$2"
    python3 - "$input" "$key" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("UNKNOWN")
    raise SystemExit(0)
value = data.get(sys.argv[2], "UNKNOWN")
if isinstance(value, bool):
    print(str(value).lower())
elif value is None:
    print("null")
else:
    print(str(value))
PY
}

status_summary() {
    local input="$1"
    python3 - "$input" <<'PY'
import json
import sys
from hashlib import sha256
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("P79_STATUS_PARSE=FAIL")
    raise SystemExit(0)
markers = data.get("last_native_failure_markers") or []
if not isinstance(markers, list):
    markers = []
safe = [str(item) for item in markers if isinstance(item, str)]
digest = sha256("\n".join(safe).encode("utf-8", errors="replace")).hexdigest()
for key in (
    "supervisor_running",
    "running",
    "listener_ready",
    "reconnect_count",
    "last_native_exit_code",
):
    value = data.get(key, "UNKNOWN")
    if isinstance(value, bool):
        value = str(value).lower()
    elif value is None:
        value = "null"
    print(f"P79_STATUS_{key.upper()}={value}")
print(f"P79_STATUS_NATIVE_MARKER_COUNT={len(safe)}")
print(f"P79_STATUS_NATIVE_MARKER_SHA256={digest}")
PY
}

detail_marker_value() {
    local key="$1"
    local line

    line="$(grep -E "^${key}=" "$DETAIL_LOG" | tail -n 1 || true)"
    if [[ -z "$line" && "$key" == P79_P2P_HTTP_STATUS ]]; then
        line="$(grep -E '^P2P_HTTP_STATUS=' "$DETAIL_LOG" | tail -n 1 || true)"
    fi
    if [[ -z "$line" && "$key" == P79_P2P_RESULT ]]; then
        line="$(grep -E '^P2P_RESULT=' "$DETAIL_LOG" | tail -n 1 || true)"
    fi
    if [[ -n "$line" ]]; then
        printf '%s\n' "${line#*=}"
    else
        printf '%s\n' 'NOT_REACHED'
    fi
}

derive_cloud_only_wrapper() {
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$P79_NATIVE_RUN_DIR" <<'PY'
from pathlib import Path
import os
import sys

source = Path(sys.argv[1])
output = Path(sys.argv[2])
run_dir = sys.argv[3]
text = source.read_text(encoding="utf-8")
run_line = 'RUN="' + '/run/comelit-p2p' + '"'
if text.count(run_line) != 1:
    raise SystemExit("P79_BASE_WRAPPER_RUN_ANCHOR=FAIL")
text = text.replace(run_line, 'RUN="$P79_NATIVE_RUN_DIR"', 1)
anchor = 'echo "=== WAIT SAME NICEAGENT / ICE ==="'
if anchor not in text:
    print("P79_CLOUD_ONLY_WRAPPER_ANCHOR=FAIL")
    raise SystemExit(3)
start = text.index(anchor)
replacement = '''echo "P79_CLOUD_ONLY_EXIT_AFTER_REMOTE_SDP=true"
echo "ICE_CONNECTIVITY_SKIPPED=true"
echo "PSEUDOTCP_SKIPPED=true"
echo "CTPP_APPLICATION_SIGNALING_SKIPPED=true"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"
echo "RAW_SDP_EMITTED=false"
echo "RAW_PAYLOAD_EMITTED=false"

touch "$RUN/stop"
wait "$HOLDER_PID" 2>/dev/null || true
trap - EXIT
exit 0
'''
text = text[:start] + replacement
prefix = f'P79_NATIVE_RUN_DIR={run_dir!r}\n'
output.write_text(prefix + text, encoding="utf-8")
os.chmod(output, 0o700)
PY
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
        os.write(fd, b"CONSUMED_BEFORE_P79_CLOUD_INVOCATION\n")
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
        echo 'P79_SENTINEL_PREEXISTING=true'
        echo 'P79_RUN_RESULT=BLOCKED'
        exit 2
    fi
    if [[ "$rc" -ne 0 ]]; then
        blocked 'P79_SENTINEL_CREATE=FAIL'
    fi

    echo 'P79_SENTINEL_PREEXISTING=false'
    echo 'P79_SENTINEL_CONSUMED=true'
}

collect_post_result_status() {
    local idx
    local output
    for idx in $(seq 1 "$POST_RESULT_STATUS_SAMPLES"); do
        output="$RUN_ROOT/listener-post-${idx}.json"
        if status_only "$output"; then
            echo "P79_LISTENER_POST_STATUS_${idx}=OBSERVED"
            status_summary "$output"
        else
            echo "P79_LISTENER_POST_STATUS_${idx}=FAIL"
        fi
        sleep "$STATUS_POLL_INTERVAL_SECONDS"
    done
}

[[ "${EUID}" -eq 0 ]] || blocked 'P79_PREFLIGHT=BLOCKED reason=ROOT_REQUIRED'

for command in git python3 curl sha256sum timeout grep awk sed install hostname; do
    command -v "$command" >/dev/null 2>&1 || blocked "P79_PREFLIGHT=BLOCKED reason=MISSING_$command"
done

if [[ -e "$SENTINEL" ]]; then
    blocked 'P79_SENTINEL_PREEXISTING=true'
fi
echo 'P79_SENTINEL_PREEXISTING=false'

[[ -d "$REPO/.git" ]] || blocked 'P79_PREFLIGHT=BLOCKED reason=REPO_MISSING'
[[ -n "$P79_REVIEW_COMMIT_SHA" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_REVIEW_COMMIT_SHA_EMPTY'

remote_main="$(git -C "$REPO" rev-parse "$REMOTE_REF" 2>/dev/null || true)"
[[ "$remote_main" == "$P79_REVIEW_COMMIT_SHA" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=ORIGIN_MAIN_NOT_REVIEW_COMMIT'

local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
[[ "$local_head" == "$P79_REVIEW_COMMIT_SHA" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=LOCAL_HEAD_NOT_REVIEW_COMMIT'

git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN_SHA" "$P79_REVIEW_COMMIT_SHA" || blocked 'P79_REVIEW_PIN=FAIL reason=BASE_NOT_ANCESTOR'

review_launcher_blob="$(repo_blob "$P79_REVIEW_COMMIT_SHA" "$P79_LAUNCHER_REL")"
review_classifier_blob="$(repo_blob "$P79_REVIEW_COMMIT_SHA" "$P79_CLASSIFIER_REL")"
[[ -n "$review_launcher_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_LAUNCHER_NOT_PINNED'
[[ -n "$review_classifier_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_CLASSIFIER_NOT_PINNED'
[[ "$(working_blob "$P79_LAUNCHER_REL")" == "$review_launcher_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_LAUNCHER_WORKTREE_MISMATCH'
[[ "$(working_blob "$P79_CLASSIFIER_REL")" == "$review_classifier_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_CLASSIFIER_WORKTREE_MISMATCH'
echo 'P79_REVIEW_PIN=PASS'

case "$(hostname -s 2>/dev/null || hostname)" in
    ct120|CT120) echo 'P79_CT120_IDENTITY=PASS' ;;
    *) blocked 'P79_PREFLIGHT=BLOCKED reason=CT120_IDENTITY_MISMATCH' ;;
esac

[[ -f "$BASE_WRAPPER" ]] || blocked 'P79_INSTALLED_WRAPPER_SHA_GATE=ABSENT'
[[ -n "$P79_INSTALLED_WRAPPER_SHA256" ]] || blocked 'P79_INSTALLED_WRAPPER_SHA_GATE=UNKNOWN'
base_wrapper_actual="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
[[ "$base_wrapper_actual" == "$P79_INSTALLED_WRAPPER_SHA256" ]] || blocked 'P79_INSTALLED_WRAPPER_SHA_GATE=MISMATCH'
echo "P79_INSTALLED_WRAPPER_SHA_GATE=$base_wrapper_actual"
echo 'P79_P2P_WRAPPER_SOURCE=/usr/local/sbin/comelit-p2p-cloud-probe'

install -d -m 700 "$RUN_ROOT" "$P79_NATIVE_RUN_DIR" || blocked 'P79_PREFLIGHT=BLOCKED reason=SCRATCH_CREATE'
: >"$DETAIL_LOG" || blocked 'P79_PREFLIGHT=BLOCKED reason=DETAIL_LOG_CREATE'
chmod 600 "$DETAIL_LOG" || blocked 'P79_PREFLIGHT=BLOCKED reason=DETAIL_LOG_MODE'
derive_cloud_only_wrapper || blocked 'P79_CLOUD_ONLY_WRAPPER_DERIVATION=FAIL'
bash -n "$CANDIDATE_WRAPPER" || blocked 'P79_CLOUD_ONLY_WRAPPER_BASH_N=FAIL'
[[ -x "$CANDIDATE_WRAPPER" ]] || blocked 'P79_CLOUD_ONLY_WRAPPER_MODE=FAIL'
echo 'P79_CLOUD_ONLY_WRAPPER_DERIVATION=PASS'

status_preflight="$RUN_ROOT/listener-preflight.json"
status_only "$status_preflight" || blocked 'P79_LISTENER_STATUS_PREFLIGHT=BLOCKED reason=STATUS_REQUEST'
echo 'P79_LISTENER_STATUS_PREFLIGHT=OBSERVED'
status_summary "$status_preflight"

echo 'P79_PREFLIGHT=PASS'

status_before="$RUN_ROOT/listener-before.json"
status_only "$status_before" || blocked 'P79_LISTENER_STATUS_BEFORE=BLOCKED reason=STATUS_REQUEST'
echo 'P79_LISTENER_STATUS_BEFORE=OBSERVED'
status_summary "$status_before"
echo "P79_RECONNECT_COUNT_BEFORE=$(json_scalar "$status_before" reconnect_count)"
echo "P79_LISTENER_READY_BEFORE=$(json_scalar "$status_before" listener_ready)"

consume_sentinel

echo 'P79_WRAPPER_INVOCATIONS=1'
timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" \
    2>&1 | tee -a "$DETAIL_LOG"
wrapper_rc=${PIPESTATUS[0]}
echo "P79_WRAPPER_RC=$wrapper_rc"

status_after="$RUN_ROOT/listener-after.json"
if status_only "$status_after"; then
    echo 'P79_LISTENER_STATUS_AFTER=OBSERVED'
    status_summary "$status_after"
else
    echo 'P79_LISTENER_STATUS_AFTER=FAIL'
fi
echo "P79_RECONNECT_COUNT_AFTER=$(json_scalar "$status_after" reconnect_count)"
echo "P79_LISTENER_READY_AFTER=$(json_scalar "$status_after" listener_ready)"

collect_post_result_status

p2p_http_status="$(detail_marker_value 'P79_P2P_HTTP_STATUS')"
p2p_result="$(detail_marker_value 'P79_P2P_RESULT')"
remote_sdp_present="$(detail_marker_value 'REMOTE_SDP_PRESENT')"
cloud_negotiation="$(detail_marker_value 'P2P_CLOUD_NEGOTIATION')"

if [[ "$p2p_result" == "NOT_REACHED" ]]; then
    # In this wrapper lineage, the derived cloud-only candidate can exit 0 only
    # after the path that already emitted REMOTE_SDP_PRESENT=true; all failure
    # branches exit nonzero before that point.
    if [[ "$wrapper_rc" -eq 0 && "$remote_sdp_present" == "true" ]]; then
        p2p_result=SUCCESS
    elif [[ "$wrapper_rc" -eq 124 ]]; then
        p2p_result=TIMEOUT
    elif [[ "$cloud_negotiation" == "PASS" ]]; then
        p2p_result=SUCCESS
    elif [[ "$cloud_negotiation" == "FAIL" || "$cloud_negotiation" == "INCOMPLETE" ]]; then
        p2p_result=FAIL
    fi
fi

echo "P79_P2P_HTTP_STATUS=$p2p_http_status"
echo "P79_P2P_RESULT=$p2p_result"
echo "REMOTE_SDP_PRESENT=$remote_sdp_present"

python3 - "$REPO/$P79_CLASSIFIER_REL" "$p2p_result" "$remote_sdp_present" "$status_before" "$status_after" <<'PY' | tee "$CLASSIFIER_OUT"
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("p79_classifier", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

samples = []
for raw in sys.argv[4:]:
    try:
        samples.append(json.loads(Path(raw).read_text(encoding="utf-8")))
    except Exception:
        samples.append({})

p2p_result = sys.argv[2]
terminal_present = p2p_result != "NOT_REACHED"
result = module.classify(
    p2p_result=None if not terminal_present else p2p_result,
    remote_sdp_present=sys.argv[3],
    listener_samples=samples,
    terminal_marker_present=terminal_present,
)
for key, value in result.as_markers().items():
    print(module.marker_line(key, value))
PY
classifier_rc=${PIPESTATUS[0]}
[[ "$classifier_rc" -eq 0 ]] || fail 'P79_CLASSIFIER=FAIL'

process_rc="$(grep -E '^P79_PROCESS_RC=' "$CLASSIFIER_OUT" | tail -n 1 | awk -F= '{print $2}')"

case "$process_rc" in
    0) exit 0 ;;
    1) exit 1 ;;
    2) exit 2 ;;
    *) exit 1 ;;
esac
