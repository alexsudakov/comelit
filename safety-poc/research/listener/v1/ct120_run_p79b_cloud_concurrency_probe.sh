#!/bin/bash
# CT120 P79B cloud-only listener concurrency PoC.
# P79 itself never reached the cloud call because its derived shell RUN path
# diverged from the holder's compiled /run/comelit-p2p path.
set -uo pipefail
umask 077

REPO="${P79B_REPO:-/root/comelit-door-diag-repo}"
BASE_MAIN_SHA=9a931c96ab04cc5e489e4c539b98d3b8c699d957
P79B_REVIEW_COMMIT_SHA="${P79B_REVIEW_COMMIT_SHA:-}"

OLD_P79_SENTINEL=/root/.comelit-p79-live-consumed
SENTINEL=/root/.comelit-p79b-live-consumed
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
EXPECTED_BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
STATUS_POLL_INTERVAL_SECONDS=5
POST_RESULT_STATUS_SAMPLES=4

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p79b-cloud-concurrency-$STAMP"
DETAIL_LOG="$RUN_ROOT/detail.log"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p79b-cloud-only"
P79B_LAUNCHER_REL=safety-poc/research/listener/v1/ct120_run_p79b_cloud_concurrency_probe.sh

echo 'P79B_SENTINEL_CONSUMED=false'
echo 'P79B_LIVE_INVOCATION_LIMIT=1'
echo 'P79B_WRAPPER_INVOCATIONS=0'
echo 'P79B_AUTO_RETRY=false'
echo 'P79B_LISTENER_CONTROL_MODE=STATUS_ONLY'
echo 'ICE_CONNECTIVITY_SKIPPED=true'
echo 'PSEUDOTCP_SKIPPED=true'
echo 'CTPP_APPLICATION_SIGNALING_SKIPPED=true'
echo 'DOOR_ACTION_SENT=false'
echo 'SELF_ACTIVATION_SENT=false'
echo 'MEDIA_SIGNALING_SENT=false'

blocked() {
    echo "$1"
    echo 'P79B_RUN_RESULT=BLOCKED'
    exit 2
}

fail() {
    echo "$1"
    echo 'P79B_RUN_RESULT=FAIL'
    exit 1
}

status_only() {
    local output="$1"
    curl -fSs --connect-timeout 5 --max-time 10 -o "$output" \
        -H 'Content-Type: application/json' \
        -d '{"action":"status"}' \
        "$HA_WEBHOOK_URL"
}

status_health_count() {
    python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(2)
c = d.get("reconnect_count")
ok = (
    d.get("ok") is True
    and d.get("action") == "status"
    and d.get("supervisor_running") is True
    and d.get("running") is True
    and d.get("listener_ready") is True
    and isinstance(c, int)
    and not isinstance(c, bool)
    and c >= 0
)
if not ok:
    raise SystemExit(3)
print(c)
PY
}

status_summary() {
    python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
try:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("P79B_STATUS_PARSE=FAIL")
    raise SystemExit(1)
for key in ("supervisor_running", "running", "listener_ready", "reconnect_count", "last_error"):
    v = d.get(key, "UNKNOWN")
    if isinstance(v, bool): v = str(v).lower()
    elif v is None: v = "null"
    print(f"P79B_STATUS_{key.upper()}={v}")
PY
}

detail_marker_value() {
    local key="$1" line
    line="$(grep -E "^${key}=" "$DETAIL_LOG" | tail -n 1 || true)"
    if [[ -n "$line" ]]; then printf '%s\n' "${line#*=}"; else printf '%s\n' NOT_REACHED; fi
}

derive_cloud_only_wrapper() {
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$SENTINEL" <<'PY'
from pathlib import Path
import os, shlex, sys

source = Path(sys.argv[1])
output = Path(sys.argv[2])
sentinel = sys.argv[3]
text = source.read_text(encoding="utf-8")

if not text.startswith("#!/bin/bash\n"):
    raise SystemExit("P79B_BASE_WRAPPER_SHEBANG=FAIL")

# The holder binary is compiled to this path. Keep the shell wrapper on the
# same path; P79 failed because it changed only the shell side.
run_line = 'RUN="/run/comelit-p2p"'
if text.count(run_line) != 1:
    raise SystemExit("P79B_NATIVE_RUN_ANCHOR=FAIL")

# Create the P79B one-shot sentinel at the real cloud boundary, not before
# local ICE gathering. Thus a pre-cloud failure does not consume the attempt.
cloud_anchor = '''python3 \\
  "$BASE/scripts/comelit_cloud_probe.py" \\
  "$RUN/offer-comelit.sdp" \\
  "$RUN/remote.sdp"'''
if text.count(cloud_anchor) != 1:
    raise SystemExit("P79B_CLOUD_CALL_ANCHOR=FAIL")

sent = shlex.quote(sentinel)
injected = f'''if ( set -o noclobber; umask 077; printf '%s\\n' 'CONSUMED_BEFORE_P79B_CLOUD_INVOCATION' > {sent} ) 2>/dev/null; then
    echo "P79B_SENTINEL_CONSUMED=true"
else
    echo "P79B_SENTINEL_PREEXISTING=true"
    exit 76
fi
{cloud_anchor}'''
text = text.replace(cloud_anchor, injected, 1)

# A successful cloud response writes remote SDP. Stop before the base wrapper
# waits for ICE connectivity / PseudoTCP / application signalling.
wait_anchor = 'echo "=== WAIT SAME NICEAGENT / ICE ==="'
if text.count(wait_anchor) != 1:
    raise SystemExit("P79B_WAIT_ICE_ANCHOR=FAIL")
start = text.index(wait_anchor)
replacement = '''echo "P79B_CLOUD_ONLY_EXIT_AFTER_REMOTE_SDP=true"
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

collect_post_status() {
    local idx output
    for idx in $(seq 1 "$POST_RESULT_STATUS_SAMPLES"); do
        sleep "$STATUS_POLL_INTERVAL_SECONDS"
        output="$RUN_ROOT/listener-post-${idx}.json"
        if status_only "$output"; then
            echo "P79B_LISTENER_POST_STATUS_${idx}=OBSERVED"
            status_summary "$output" || true
        else
            printf '{}\n' >"$output"
            echo "P79B_LISTENER_POST_STATUS_${idx}=FAIL"
        fi
    done
}

[[ "$EUID" -eq 0 ]] || blocked 'P79B_PREFLIGHT=BLOCKED reason=ROOT_REQUIRED'
for cmd in git python3 curl sha256sum timeout grep awk install hostname head; do
    command -v "$cmd" >/dev/null 2>&1 || blocked "P79B_PREFLIGHT=BLOCKED reason=MISSING_$cmd"
done

[[ -e "$OLD_P79_SENTINEL" ]] || blocked 'P79B_PREFLIGHT=BLOCKED reason=P79_HISTORY_SENTINEL_MISSING'
[[ ! -e "$SENTINEL" ]] || blocked 'P79B_SENTINEL_PREEXISTING=true'
echo 'P79B_SENTINEL_PREEXISTING=false'

[[ -d "$REPO/.git" ]] || blocked 'P79B_PREFLIGHT=BLOCKED reason=REPO_MISSING'
[[ -n "$P79B_REVIEW_COMMIT_SHA" ]] || blocked 'P79B_REVIEW_PIN=FAIL reason=EMPTY_SHA'
local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
[[ "$local_head" == "$P79B_REVIEW_COMMIT_SHA" ]] || blocked 'P79B_REVIEW_PIN=FAIL reason=LOCAL_HEAD_MISMATCH'
git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN_SHA" "$local_head" || blocked 'P79B_REVIEW_PIN=FAIL reason=BASE_NOT_ANCESTOR'
review_blob="$(git -C "$REPO" rev-parse "$local_head:$P79B_LAUNCHER_REL" 2>/dev/null || true)"
working_blob="$(git -C "$REPO" hash-object "$P79B_LAUNCHER_REL" 2>/dev/null || true)"
[[ -n "$review_blob" && "$review_blob" == "$working_blob" ]] || blocked 'P79B_REVIEW_PIN=FAIL reason=WORKTREE_MISMATCH'
echo 'P79B_REVIEW_PIN=PASS'

case "$(hostname -s 2>/dev/null || hostname)" in
    ct120|CT120) echo 'P79B_CT120_IDENTITY=PASS' ;;
    *) blocked 'P79B_PREFLIGHT=BLOCKED reason=CT120_IDENTITY_MISMATCH' ;;
esac

actual_sha="$(sha256sum "$BASE_WRAPPER" 2>/dev/null | awk '{print $1}')"
[[ "$actual_sha" == "$EXPECTED_BASE_WRAPPER_SHA256" ]] || blocked 'P79B_INSTALLED_WRAPPER_SHA_GATE=FAIL'
echo 'P79B_INSTALLED_WRAPPER_SHA_GATE=PASS'

install -d -m 700 "$RUN_ROOT" || blocked 'P79B_PREFLIGHT=BLOCKED reason=RUN_ROOT'
: >"$DETAIL_LOG" || blocked 'P79B_PREFLIGHT=BLOCKED reason=DETAIL_LOG'
chmod 600 "$DETAIL_LOG"
derive_cloud_only_wrapper || blocked 'P79B_CLOUD_ONLY_WRAPPER_DERIVATION=FAIL'
[[ "$(head -n 1 "$CANDIDATE_WRAPPER")" == '#!/bin/bash' ]] || blocked 'P79B_CANDIDATE_SHEBANG=FAIL'
bash -n "$CANDIDATE_WRAPPER" || blocked 'P79B_CANDIDATE_BASH_N=FAIL'
echo 'P79B_CLOUD_ONLY_WRAPPER_DERIVATION=PASS'

status_preflight="$RUN_ROOT/listener-preflight.json"
status_only "$status_preflight" || blocked 'P79B_LISTENER_STATUS_PREFLIGHT=FAIL'
preflight_count="$(status_health_count "$status_preflight")" || blocked 'P79B_LISTENER_PRE_LIVE_HEALTH=FAIL stage=preflight'

status_before="$RUN_ROOT/listener-before.json"
status_only "$status_before" || blocked 'P79B_LISTENER_STATUS_BEFORE=FAIL'
before_count="$(status_health_count "$status_before")" || blocked 'P79B_LISTENER_PRE_LIVE_HEALTH=FAIL stage=before'
[[ "$before_count" == "$preflight_count" ]] || blocked 'P79B_LISTENER_BASELINE_RECONNECT_STABLE=false'
echo 'P79B_LISTENER_PRE_LIVE_HEALTH=PASS'
echo 'P79B_LISTENER_BASELINE_RECONNECT_STABLE=true'
echo "P79B_RECONNECT_COUNT_BEFORE=$before_count"
echo 'P79B_PREFLIGHT=PASS'

# This is the sole candidate invocation. The P79B sentinel is created inside
# the candidate immediately before the cloud probe, after local ICE/SDP work.
echo 'P79B_WRAPPER_INVOCATIONS=1'
timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" 2>&1 | tee -a "$DETAIL_LOG"
wrapper_rc=${PIPESTATUS[0]}
echo "P79B_WRAPPER_RC=$wrapper_rc"

if [[ "$wrapper_rc" -eq 76 ]]; then
    blocked 'P79B_SENTINEL_RACE=BLOCKED'
fi

status_after="$RUN_ROOT/listener-after.json"
if status_only "$status_after"; then
    echo 'P79B_LISTENER_STATUS_AFTER=OBSERVED'
    status_summary "$status_after" || true
else
    printf '{}\n' >"$status_after"
    echo 'P79B_LISTENER_STATUS_AFTER=FAIL'
fi
collect_post_status

p2p_http_status="$(detail_marker_value P2P_HTTP_STATUS)"
p2p_result="$(detail_marker_value P2P_RESULT)"
remote_sdp_present="$(detail_marker_value REMOTE_SDP_PRESENT)"
cloud_negotiation="$(detail_marker_value P2P_CLOUD_NEGOTIATION)"

echo "P79B_P2P_HTTP_STATUS=$p2p_http_status"
echo "P79B_P2P_RESULT=$p2p_result"
echo "P79B_REMOTE_SDP_PRESENT=$remote_sdp_present"
echo "P79B_CLOUD_NEGOTIATION=$cloud_negotiation"

python3 - "$p2p_result" "$remote_sdp_present" "$status_before" "$status_after" \
    "$RUN_ROOT/listener-post-1.json" "$RUN_ROOT/listener-post-2.json" \
    "$RUN_ROOT/listener-post-3.json" "$RUN_ROOT/listener-post-4.json" <<'PY'
import json, sys
from pathlib import Path

def load(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: return None

def valid(s):
    if not isinstance(s, dict): return False
    c=s.get("reconnect_count")
    return (
        s.get("supervisor_running") is True
        and s.get("running") is True
        and isinstance(c,int) and not isinstance(c,bool) and c>=0
    )

result=sys.argv[1].upper()
remote=sys.argv[2].lower()=="true"
before=load(sys.argv[3])
posts=[load(p) for p in sys.argv[4:]]

if not valid(before) or not posts or not all(valid(s) for s in posts):
    print("P79B_CLOUD_CONCURRENCY=UNKNOWN")
    print("P79B_LISTENER_STABILITY=UNKNOWN")
    print("P79B_RUN_RESULT=UNKNOWN_OUTCOME")
    raise SystemExit(1)

baseline=before["reconnect_count"]
reconnect=any(s["reconnect_count"] != baseline for s in posts)
running=all(s["supervisor_running"] is True and s["running"] is True for s in posts)
final_ready=posts[-1].get("listener_ready") is True
baseline_ready=before.get("listener_ready") is True

if result=="SUCCESS" and remote:
    if baseline_ready and running and not reconnect and final_ready:
        print("P79B_CLOUD_CONCURRENCY=PROVEN")
        print("P79B_LISTENER_STABILITY=PROVEN")
        print("P79B_RUN_RESULT=PASS")
        raise SystemExit(0)
    print("P79B_CLOUD_CONCURRENCY=PARTIAL")
    print("P79B_LISTENER_STABILITY=NOT_PROVEN")
    print("P79B_RUN_RESULT=PARTIAL")
    raise SystemExit(1)

if result=="TIMEOUT":
    print("P79B_CLOUD_CONCURRENCY=INCONCLUSIVE")
    print("P79B_TIMEOUT_RECONNECT_ASSOCIATION=" + ("OBSERVED" if reconnect else "NOT_OBSERVED"))
    print("P79B_LISTENER_STABILITY=" + ("PROVEN" if running and not reconnect and final_ready else "NOT_PROVEN"))
    print("P79B_RUN_RESULT=INCONCLUSIVE_TRANSIENT_TIMEOUT")
    raise SystemExit(1)

print("P79B_CLOUD_CONCURRENCY=NOT_PROVEN")
print("P79B_LISTENER_STABILITY=" + ("PROVEN" if running and not reconnect and final_ready else "NOT_PROVEN"))
print("P79B_RUN_RESULT=FAIL" if result != "NOT_REACHED" else "P79B_RUN_RESULT=PRE_CLOUD_FAILURE")
raise SystemExit(1)
PY
classifier_rc=$?
exit "$classifier_rc"
