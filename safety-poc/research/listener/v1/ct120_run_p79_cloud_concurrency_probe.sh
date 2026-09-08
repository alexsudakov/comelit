#!/bin/bash
# CT120 P79 cloud-only listener concurrency PoC.
set -uo pipefail
umask 077

REPO="${P79_REPO:-/root/comelit-door-diag-repo}"
BASE_MAIN_SHA=9a931c96ab04cc5e489e4c539b98d3b8c699d957
P79_REVIEW_COMMIT_SHA="${P79_REVIEW_COMMIT_SHA:-}"

SENTINEL=/root/.comelit-p79-live-consumed
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
EXPECTED_BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
POST_RESULT_OBSERVATION_SECONDS=20
STATUS_POLL_INTERVAL_SECONDS=5
POST_RESULT_STATUS_SAMPLES=4

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p79-cloud-concurrency-$STAMP"
DETAIL_LOG="$RUN_ROOT/detail.log"
CLASSIFIER_OUT="$RUN_ROOT/classifier.out"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p79-cloud-only"
P79_NATIVE_RUN_DIR="$RUN_ROOT/native-run"
P79_LAUNCHER_REL=safety-poc/research/listener/v1/ct120_run_p79_cloud_concurrency_probe.sh
P79_CLASSIFIER_REL=safety-poc/research/listener/v1/p79_cloud_concurrency_classifier.py

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
    git -C "$REPO" rev-parse "$1:$2" 2>/dev/null || true
}

working_blob() {
    git -C "$REPO" hash-object "$1" 2>/dev/null || true
}

status_only() {
    local output="$1"
    curl -fSs --connect-timeout 5 --max-time 10 -o "$output" \
        -H 'Content-Type: application/json' \
        -d '{"action":"status"}' \
        "$HA_WEBHOOK_URL"
}

json_scalar() {
    local input="$1" key="$2"
    python3 - "$input" "$key" <<'PY'
import json, sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("UNKNOWN")
    raise SystemExit(0)
v = d.get(sys.argv[2], "UNKNOWN")
if isinstance(v, bool): print(str(v).lower())
elif v is None: print("null")
else: print(v)
PY
}

status_summary() {
    python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("P79_STATUS_PARSE=FAIL")
    raise SystemExit(1)
for key in ("supervisor_running", "running", "listener_ready", "reconnect_count", "last_error"):
    value = d.get(key, "UNKNOWN")
    if isinstance(value, bool): value = str(value).lower()
    elif value is None: value = "null"
    print(f"P79_STATUS_{key.upper()}={value}")
PY
}

status_health_count() {
    python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(2)
count = d.get("reconnect_count")
healthy = (
    d.get("ok") is True
    and d.get("action") == "status"
    and d.get("supervisor_running") is True
    and d.get("running") is True
    and d.get("listener_ready") is True
    and isinstance(count, int)
    and not isinstance(count, bool)
    and count >= 0
)
if not healthy: raise SystemExit(3)
print(count)
PY
}

detail_marker_value() {
    local key="$1" line
    line="$(grep -E "^${key}=" "$DETAIL_LOG" | tail -n 1 || true)"
    if [[ -z "$line" && "$key" == P79_P2P_HTTP_STATUS ]]; then
        line="$(grep -E '^P2P_HTTP_STATUS=' "$DETAIL_LOG" | tail -n 1 || true)"
    fi
    if [[ -z "$line" && "$key" == P79_P2P_RESULT ]]; then
        line="$(grep -E '^P2P_RESULT=' "$DETAIL_LOG" | tail -n 1 || true)"
    fi
    if [[ -z "$line" && "$key" == P2P_CLOUD_NEGOTIATION ]]; then
        line="$(grep -E '^P2P_CLOUD_NEGOTIATION=' "$DETAIL_LOG" | tail -n 1 || true)"
    fi
    if [[ -n "$line" ]]; then printf '%s\n' "${line#*=}"; else printf '%s\n' 'NOT_REACHED'; fi
}

derive_cloud_only_wrapper() {
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$P79_NATIVE_RUN_DIR" <<'PY'
from pathlib import Path
import os, shlex, sys
source = Path(sys.argv[1])
output = Path(sys.argv[2])
run_dir = sys.argv[3]
text = source.read_text(encoding="utf-8")
if not text.startswith("#!/bin/bash\n"):
    raise SystemExit("P79_BASE_WRAPPER_SHEBANG=FAIL")
run_line = 'RUN="' + '/run/comelit-p2p' + '"'
if text.count(run_line) != 1:
    raise SystemExit("P79_BASE_WRAPPER_RUN_ANCHOR=FAIL")
# Equivalent to the old derivation contract RUN="$P79_NATIVE_RUN_DIR", but
# substituted as a literal so the generated script remains self-contained.
text = text.replace(run_line, f"RUN={shlex.quote(run_dir)}", 1)
anchor = 'echo "=== WAIT SAME NICEAGENT / ICE ==="'
if anchor not in text:
    print("P79_CLOUD_ONLY_WRAPPER_ANCHOR=FAIL")
    raise SystemExit(3)
if text.count(anchor) != 1:
    raise SystemExit("P79_CLOUD_ONLY_WRAPPER_ANCHOR_COUNT=FAIL")
start = text.index(anchor)
replacement = '''echo "P79_CLOUD_ONLY_EXIT_AFTER_REMOTE_SDP=true"
echo "ICE_CONNECTIVITY_SKIPPED=true"
echo "PSEUDOTCP_SKIPPED=true"
echo "CTPP_APPLICATION_SIGNALING_SKIPPED=true"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"
touch "$RUN/stop"
wait "$HOLDER_PID" 2>/dev/null || true
trap - EXIT
exit 0
'''
text = text[:start] + replacement
output.write_text(text, encoding="utf-8")
os.chmod(output, 0o700)
PY
}

consume_sentinel() {
    python3 - "$SENTINEL" <<'PY'
import os, sys
path = sys.argv[1]
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(76)
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
PY
    local rc=$?
    if [[ "$rc" -eq 76 ]]; then blocked 'P79_SENTINEL_PREEXISTING=true'; fi
    [[ "$rc" -eq 0 ]] || blocked 'P79_SENTINEL_CREATE=FAIL'
    echo 'P79_SENTINEL_CONSUMED=true'
}

collect_post_result_status() {
    local idx output
    for idx in $(seq 1 "$POST_RESULT_STATUS_SAMPLES"); do
        sleep "$STATUS_POLL_INTERVAL_SECONDS"
        output="$RUN_ROOT/listener-post-${idx}.json"
        if status_only "$output"; then
            echo "P79_LISTENER_POST_STATUS_${idx}=OBSERVED"
            status_summary "$output" || true
        else
            printf '{}\n' >"$output"
            echo "P79_LISTENER_POST_STATUS_${idx}=FAIL"
        fi
    done
}

[[ "${EUID}" -eq 0 ]] || blocked 'P79_PREFLIGHT=BLOCKED reason=ROOT_REQUIRED'
for command in git python3 curl sha256sum timeout grep awk install hostname head; do
    command -v "$command" >/dev/null 2>&1 || blocked "P79_PREFLIGHT=BLOCKED reason=MISSING_$command"
done

if [[ -e "$SENTINEL" ]]; then
    blocked 'P79_SENTINEL_PREEXISTING=true'
fi
echo 'P79_SENTINEL_PREEXISTING=false'

[[ -d "$REPO/.git" ]] || blocked 'P79_PREFLIGHT=BLOCKED reason=REPO_MISSING'
[[ -n "$P79_REVIEW_COMMIT_SHA" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_REVIEW_COMMIT_SHA_EMPTY'
local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
[[ "$local_head" == "$P79_REVIEW_COMMIT_SHA" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=LOCAL_HEAD_NOT_REVIEW_COMMIT'
git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN_SHA" "$P79_REVIEW_COMMIT_SHA" || blocked 'P79_REVIEW_PIN=FAIL reason=BASE_NOT_ANCESTOR'
review_launcher_blob="$(repo_blob "$P79_REVIEW_COMMIT_SHA" "$P79_LAUNCHER_REL")"
review_classifier_blob="$(repo_blob "$P79_REVIEW_COMMIT_SHA" "$P79_CLASSIFIER_REL")"
[[ "$(working_blob "$P79_LAUNCHER_REL")" == "$review_launcher_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_LAUNCHER_WORKTREE_MISMATCH'
[[ "$(working_blob "$P79_CLASSIFIER_REL")" == "$review_classifier_blob" ]] || blocked 'P79_REVIEW_PIN=FAIL reason=P79_CLASSIFIER_WORKTREE_MISMATCH'
echo 'P79_REVIEW_PIN=PASS'

case "$(hostname -s 2>/dev/null || hostname)" in
    ct120|CT120) echo 'P79_CT120_IDENTITY=PASS' ;;
    *) blocked 'P79_PREFLIGHT=BLOCKED reason=CT120_IDENTITY_MISMATCH' ;;
esac

[[ -f "$BASE_WRAPPER" ]] || blocked 'P79_INSTALLED_WRAPPER_SHA_GATE=ABSENT'
base_wrapper_actual="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
[[ "$base_wrapper_actual" == "$EXPECTED_BASE_WRAPPER_SHA256" ]] || blocked 'P79_INSTALLED_WRAPPER_SHA_GATE=MISMATCH'
echo 'P79_INSTALLED_WRAPPER_SHA_GATE=PASS'
echo 'P79_P2P_WRAPPER_SOURCE=/usr/local/sbin/comelit-p2p-cloud-probe'

install -d -m 700 "$RUN_ROOT" "$P79_NATIVE_RUN_DIR" || blocked 'P79_PREFLIGHT=BLOCKED reason=SCRATCH_CREATE'
: >"$DETAIL_LOG" || blocked 'P79_PREFLIGHT=BLOCKED reason=DETAIL_LOG_CREATE'
chmod 600 "$DETAIL_LOG" || blocked 'P79_PREFLIGHT=BLOCKED reason=DETAIL_LOG_MODE'
derive_cloud_only_wrapper || blocked 'P79_CLOUD_ONLY_WRAPPER_DERIVATION=FAIL'
[[ "$(head -n 1 "$CANDIDATE_WRAPPER")" == '#!/bin/bash' ]] || blocked 'P79_CLOUD_ONLY_WRAPPER_SHEBANG=FAIL'
bash -n "$CANDIDATE_WRAPPER" || blocked 'P79_CLOUD_ONLY_WRAPPER_BASH_N=FAIL'
[[ -x "$CANDIDATE_WRAPPER" ]] || blocked 'P79_CLOUD_ONLY_WRAPPER_MODE=FAIL'
echo 'P79_CLOUD_ONLY_WRAPPER_DERIVATION=PASS'

status_preflight="$RUN_ROOT/listener-preflight.json"
status_only "$status_preflight" || blocked 'P79_LISTENER_STATUS_PREFLIGHT=BLOCKED reason=STATUS_REQUEST'
preflight_count="$(status_health_count "$status_preflight")" || blocked 'P79_LISTENER_PRE_LIVE_HEALTH=FAIL stage=preflight'
echo 'P79_LISTENER_STATUS_PREFLIGHT=RUNNING_READY'

status_before="$RUN_ROOT/listener-before.json"
status_only "$status_before" || blocked 'P79_LISTENER_STATUS_BEFORE=BLOCKED reason=STATUS_REQUEST'
before_count="$(status_health_count "$status_before")" || blocked 'P79_LISTENER_PRE_LIVE_HEALTH=FAIL stage=before'
[[ "$before_count" == "$preflight_count" ]] || blocked 'P79_LISTENER_BASELINE_RECONNECT_STABLE=false'
echo 'P79_LISTENER_PRE_LIVE_HEALTH=PASS'
echo 'P79_LISTENER_BASELINE_RECONNECT_STABLE=true'
echo "P79_RECONNECT_COUNT_BEFORE=$before_count"
echo "P79_LISTENER_READY_BEFORE=$(json_scalar "$status_before" listener_ready)"
echo 'P79_PREFLIGHT=PASS'

consume_sentinel

echo 'P79_WRAPPER_INVOCATIONS=1'
timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" 2>&1 | tee -a "$DETAIL_LOG"
wrapper_rc=${PIPESTATUS[0]}
echo "P79_WRAPPER_RC=$wrapper_rc"

status_after="$RUN_ROOT/listener-after.json"
if status_only "$status_after"; then
    echo 'P79_LISTENER_STATUS_AFTER=OBSERVED'
    status_summary "$status_after" || true
else
    printf '{}\n' >"$status_after"
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
    if [[ "$wrapper_rc" -eq 0 && "$remote_sdp_present" == "true" ]]; then
        p2p_result=SUCCESS
    elif [[ "$wrapper_rc" -eq 124 ]]; then
        p2p_result=TIMEOUT
    elif [[ "$cloud_negotiation" == "PASS" ]]; then
        p2p_result=SUCCESS
    elif [[ "$cloud_negotiation" == "FAIL" ]]; then
        p2p_result=FAIL
    fi
fi

echo "P79_P2P_HTTP_STATUS=$p2p_http_status"
echo "P79_P2P_RESULT=$p2p_result"
echo "REMOTE_SDP_PRESENT=$remote_sdp_present"

python3 - "$REPO/$P79_CLASSIFIER_REL" "$p2p_result" "$remote_sdp_present" \
    "$status_before" "$status_after" \
    "$RUN_ROOT/listener-post-1.json" "$RUN_ROOT/listener-post-2.json" \
    "$RUN_ROOT/listener-post-3.json" "$RUN_ROOT/listener-post-4.json" <<'PY' | tee "$CLASSIFIER_OUT"
import importlib.util, json, sys
from pathlib import Path
module_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("p79_classifier", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
def load(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: return {}
before = load(sys.argv[4])
posts = [load(path) for path in sys.argv[5:]]
p2p_result = sys.argv[2]
terminal_present = p2p_result != "NOT_REACHED"
result = module.classify(
    p2p_result=None if not terminal_present else p2p_result,
    remote_sdp_present=sys.argv[3],
    before_sample=before,
    post_samples=posts,
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
