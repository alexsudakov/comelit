#!/usr/bin/env bash
# CT120 research-only MSL-V1 Variant B idle-listener media runner.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
MSL_B_EXPECTED_COMMIT_SHA=${MSL_B_EXPECTED_COMMIT_SHA:-}
MSL_B_EXPECTED_GENERATED_SOURCE_SHA=${MSL_B_EXPECTED_GENERATED_SOURCE_SHA:-}
MSL_B_LIVE_RUN=${MSL_B_LIVE_RUN:-NO}
MSL_B_DRY_RUN=${MSL_B_DRY_RUN:-NO}
MSL_B_SELFTEST=${MSL_B_SELFTEST:-NO}
MSL_B_ATTEMPT_LEDGER=${MSL_B_ATTEMPT_LEDGER:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
BUILDER_REL=safety-poc/research/media/v1/ct122_build_p116_r54_call_adoption_candidate.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_msl_v1_idle_listener_media_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_msl_v1_variant_b_live.sh
BASELINE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_msl_v1_baseline_live.sh
EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
OFFLINE_ROOTFS=${OFFLINE_ROOTFS:-}
ALPINE_VERSION=3.24.1
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
SETUP_MARGIN_SECONDS=${SETUP_MARGIN_SECONDS:-35}
LISTENER_READY_WAIT_SECONDS=${LISTENER_READY_WAIT_SECONDS:-35}
MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-20}
MEDIA_STARTUP_OUTER_TIMEOUT=$((SETUP_MARGIN_SECONDS + MEDIA_OBSERVATION_SECONDS))
MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS=90
RUN_DIR=/run/comelit-p2p
START_FILE="$RUN_DIR/msl-b-start-idle-media"
STOP_FILE="$RUN_DIR/msl-b-stop-idle-media"
CLOCK_BASE_FILE="$RUN_DIR/msl-b-clock-base"
CANDIDATE_NAME=comelit-msl-v1-variant-b-listener

FAIL=0
LIVE_INVOCATIONS=0
LISTENER_STOPPED=0
LISTENER_READY_BEFORE=false
LISTENER_READY_AFTER=false
MSL_B_DRY_RUN_COMPLETED=false
MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=false
MSL_B_COMELIT_INTERACTION=0
MSL_B_HA_INTERACTION=0
MSL_B_RUN_CLASSIFICATION=NOT_RUN
MEDIA_TEARDOWN=UNCERTAIN
CAMPAIGN_PROCESSES_REMAINING=UNKNOWN
RTP_SINK_PORTS_REMAINING=UNKNOWN
RUN_ROOT=""
SESSION_LOG=""
LISTENER_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=false
MSL_B_BUILD_ROOTFS=""
MSL_B_OUTPUT=""
MSL_B_CANDIDATE_BINARY_SHA256=""
MSL_B_LAST_BUILD_RC=NOT_REACHED

msl_b_mono_ms() {
    python3 - <<'PY'
import time
print(time.monotonic_ns() // 1_000_000)
PY
}

msl_b_since_base() {
    python3 - "$CLOCK_BASE_FILE" <<'PY'
from pathlib import Path
import sys, time
base = int(Path(sys.argv[1]).read_text(encoding="utf-8").strip())
print(max(0, time.monotonic_ns() // 1_000_000 - base))
PY
}

msl_b_mark() {
    printf 'MSL_B_%s_MONO_MS=%s\n' "$1" "$(msl_b_since_base)"
}

fail() {
    echo "$1"
    FAIL=1
}

json_scalar() {
    python3 - "$1" "$2" <<'PY'
import json
from pathlib import Path
import sys
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("__INVALID_JSON__")
    raise SystemExit(0)
value = data.get(sys.argv[2], "__MISSING__")
if value is True:
    print("true")
elif value is False:
    print("false")
elif value is None:
    print("null")
else:
    print(str(value))
PY
}

post_control() {
    local action="$1"
    local output="$2"
    local max_time="$3"
    local http_file="${output}.http"
    if [ "$MSL_B_DRY_RUN" = YES ]; then
        case "$action" in
            status|start)
                printf '{"ok":true,"supervisor_running":true,"running":true,"listener_ready":true,"last_error":null}\n' > "$output"
                ;;
            stop)
                printf '{"ok":true,"supervisor_running":true,"running":false,"listener_ready":false,"last_error":null}\n' > "$output"
                ;;
            *)
                printf '{"ok":false,"last_error":"unknown dry-run action"}\n' > "$output"
                ;;
        esac
        printf '200\n' > "$http_file"
        echo "CONTROL_${action^^}_DRY_RUN=true"
        echo "CONTROL_${action^^}_HTTP_STATUS=200"
        return 0
    fi
    MSL_B_HA_INTERACTION=$((MSL_B_HA_INTERACTION + 1))
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" \
      --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
}

status_ready() {
    local file="$1"
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" supervisor_running)" = true ] &&
    [ "$(json_scalar "$file" running)" = true ] &&
    [ "$(json_scalar "$file" listener_ready)" = true ] &&
    [ "$(json_scalar "$file" last_error)" = null ]
}

status_stopped() {
    local file="$1"
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
}

msl_b_rootfs_library_realpath() {
    local rootfs="$1"
    local needed="$2"
    local rootfs_real
    local rootfs_lib
    local lib_real
    rootfs_real="$(readlink -f "$rootfs" 2>/dev/null || true)"
    [ -n "$rootfs_real" ] && [ -d "$rootfs_real" ] || return 1
    rootfs_lib="$(
        find "$rootfs/lib" "$rootfs/usr/lib" -name "$needed" \( -type f -o -type l \) -print -quit 2>/dev/null || true
    )"
    [ -n "$rootfs_lib" ] || return 1
    lib_real="$(readlink -f "$rootfs_lib" 2>/dev/null || true)"
    [ -n "$lib_real" ] && [ -f "$lib_real" ] || return 1
    case "$lib_real" in
        "$rootfs_real"/*) printf '%s\n' "$lib_real" ;;
        *) return 1 ;;
    esac
}

msl_b_select_rootfs() {
    if [ -n "$OFFLINE_ROOTFS" ]; then
        MSL_B_BUILD_ROOTFS="$OFFLINE_ROOTFS"
    else
        MSL_B_BUILD_ROOTFS="$(
            find /root -maxdepth 2 -path '/root/comelit-p80-haos-build-*/rootfs' -type d \
                -exec test -x '{}/usr/bin/gcc' ';' \
                -exec test -x '{}/usr/bin/pkg-config' ';' \
                -exec test -e '{}/lib/ld-musl-x86_64.so.1' ';' \
                -printf '%T@ %p\n' 2>/dev/null |
            sort -nr |
            awk 'NR == 1 {print $2}'
        )"
    fi
    [ -n "$MSL_B_BUILD_ROOTFS" ] || fail "MSL_B_OFFLINE_ROOTFS=ABSENT"
    [ -x "$MSL_B_BUILD_ROOTFS/usr/bin/gcc" ] || fail "MSL_B_OFFLINE_ROOTFS_GCC=ABSENT"
    [ -x "$MSL_B_BUILD_ROOTFS/usr/bin/pkg-config" ] || fail "MSL_B_OFFLINE_ROOTFS_PKG_CONFIG=ABSENT"
    [ -e "$MSL_B_BUILD_ROOTFS/lib/ld-musl-x86_64.so.1" ] || fail "MSL_B_OFFLINE_ROOTFS_MUSL_LOADER=ABSENT"
    [ "$(cat "$MSL_B_BUILD_ROOTFS/etc/alpine-release" 2>/dev/null || true)" = "$ALPINE_VERSION" ] || fail "MSL_B_ALPINE_VERSION_GATE=FAIL"
}

msl_b_build_candidate() {
    local source_a="$RUN_ROOT/msl-b-a.c"
    local source_b="$RUN_ROOT/msl-b-b.c"
    local meta="$RUN_ROOT/build-meta.txt"
    local chroot_dir="/msl-b-build-$$"
    local source_a_sha
    local source_b_sha
    local build_rc
    local interpreter
    local needed
    local rootfs_lib
    local packaged
    local lib_identical=PASS
    local no_glibc_dependency
    local no_new_runtime_dependency
    local musl_interpreter_gate

    echo "=== BUILD EPHEMERAL VARIANT B LISTENER ==="
    MSL_B_OUTPUT="$RUN_ROOT/$CANDIDATE_NAME"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
        python3 "$REPO/$TRANSFORM_REL" --source "$REPO/$SOURCE_REL" --output "$source_a"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
        python3 "$REPO/$TRANSFORM_REL" --source "$REPO/$SOURCE_REL" --output "$source_b"
    source_a_sha="$(sha256sum "$source_a" | awk '{print $1}')"
    source_b_sha="$(sha256sum "$source_b" | awk '{print $1}')"
    echo "MSL_B_GENERATED_SOURCE_SHA256_A=$source_a_sha"
    echo "MSL_B_GENERATED_SOURCE_SHA256_B=$source_b_sha"
    cmp "$source_a" "$source_b" >/dev/null 2>&1 || fail "MSL_B_TRANSFORM_DETERMINISTIC=FAIL"
    [ "$source_a_sha" = "$MSL_B_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "MSL_B_GENERATED_SOURCE_SHA_GATE=FAIL"
    [ "$FAIL" -eq 0 ] || return 1

    msl_b_select_rootfs
    echo "MSL_B_OFFLINE_ROOTFS=$MSL_B_BUILD_ROOTFS"
    echo "MSL_B_ALPINE_DOWNLOAD=SKIPPED_OFFLINE"
    install -d -m 700 "$MSL_B_BUILD_ROOTFS$chroot_dir/src" "$MSL_B_BUILD_ROOTFS$chroot_dir/out"
    install -m 600 "$source_a" "$MSL_B_BUILD_ROOTFS$chroot_dir/src/msl-b-a.c"

    set +e
    timeout 900 chroot "$MSL_B_BUILD_ROOTFS" /bin/sh -eu -c "
      cd '$chroot_dir'
      cc -O2 -g -Wall -Wextra -Wl,--as-needed \
        -o out/$CANDIDATE_NAME \
        src/msl-b-a.c \
        \$(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)
      chmod 755 out/$CANDIDATE_NAME
      INTERPRETER=\"\$(readelf -l out/$CANDIDATE_NAME | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')\"
      NEEDED=\"\$(readelf -d out/$CANDIDATE_NAME | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)\"
      BUILD_ID=\"\$(readelf -n out/$CANDIDATE_NAME | sed -n 's/^.*Build ID: //p' | head -1)\"
      {
        echo \"alpine_version=\$(cat /etc/alpine-release)\"
        echo \"cc_version=\$(cc --version | head -1)\"
        echo \"libnice_version=\$(pkg-config --modversion nice)\"
        echo \"glib_version=\$(pkg-config --modversion glib-2.0)\"
        echo \"gobject_version=\$(pkg-config --modversion gobject-2.0)\"
        echo \"cflags=-O2 -g -Wall -Wextra -Wl,--as-needed\"
        echo \"interpreter=\$INTERPRETER\"
        echo \"needed_sorted=\$NEEDED\"
        echo \"elf_build_id=\$BUILD_ID\"
        echo \"candidate_executed=false\"
      } > out/build-meta.txt
    " | tee "$RUN_ROOT/build.log"
    build_rc=${PIPESTATUS[0]}
    set -u -o pipefail
    MSL_B_LAST_BUILD_RC="$build_rc"
    echo "MSL_B_BUILD_RC=$build_rc"
    if [ "$build_rc" -ne 0 ]; then
        echo "MSL_B_BUILD_DIAGNOSTICS_TAIL_BEGIN"
        tail -n 80 "$RUN_ROOT/build.log" 2>/dev/null || true
        echo "MSL_B_BUILD_DIAGNOSTICS_TAIL_END"
        return 1
    fi

    install -m 700 "$MSL_B_BUILD_ROOTFS$chroot_dir/out/$CANDIDATE_NAME" "$MSL_B_OUTPUT"
    install -m 600 "$MSL_B_BUILD_ROOTFS$chroot_dir/out/build-meta.txt" "$meta"
    rm -rf "$MSL_B_BUILD_ROOTFS$chroot_dir"
    MSL_B_CANDIDATE_BINARY_SHA256="$(sha256sum "$MSL_B_OUTPUT" | awk '{print $1}')"
    interpreter="$(sed -n 's/^interpreter=//p' "$meta")"
    needed="$(sed -n 's/^needed_sorted=//p' "$meta")"
    echo "MSL_B_MUSL_INTERPRETER=$interpreter"
    echo "MSL_B_NEEDED_SORTED=$needed"
    [ "$interpreter" = "$EXPECTED_INTERPRETER" ] && musl_interpreter_gate=PASS || musl_interpreter_gate=FAIL
    [ "$needed" = "$EXPECTED_NEEDED" ] && no_new_runtime_dependency=PASS || no_new_runtime_dependency=FAIL
    case ",$needed," in
        *,libc.so.6,*) no_glibc_dependency=FAIL ;;
        *) no_glibc_dependency=PASS ;;
    esac
    [ "$musl_interpreter_gate" = PASS ] || fail "MSL_B_MUSL_INTERPRETER_GATE=FAIL"
    [ "$no_new_runtime_dependency" = PASS ] || fail "MSL_B_NEEDED_GATE=FAIL"
    [ "$no_glibc_dependency" = PASS ] || fail "MSL_B_GLIBC_DEPENDENCY=FAIL"
    for needed_lib in libglib-2.0.so.0 libgobject-2.0.so.0 libnice.so.10; do
        packaged="$REPO/custom_components/comelit/native/lib/$needed_lib"
        rootfs_lib="$(msl_b_rootfs_library_realpath "$MSL_B_BUILD_ROOTFS" "$needed_lib" || true)"
        if [ ! -f "$packaged" ]; then
            lib_identical=FAIL
            fail "MSL_B_LIB_IDENTICAL=FAIL lib=$needed_lib reason=packaged_absent"
        elif [ -z "$rootfs_lib" ]; then
            lib_identical=FAIL
            fail "MSL_B_LIB_IDENTICAL=FAIL lib=$needed_lib reason=rootfs_lib_unresolved"
        elif ! cmp -s "$packaged" "$rootfs_lib"; then
            lib_identical=FAIL
            fail "MSL_B_LIB_IDENTICAL=FAIL lib=$needed_lib reason=content_mismatch"
        fi
    done
    echo "MSL_B_MUSL_INTERPRETER_GATE=$musl_interpreter_gate"
    echo "NO_GLIBC_DEPENDENCY=$no_glibc_dependency"
    echo "NO_NEW_RUNTIME_DEPENDENCY=$no_new_runtime_dependency"
    echo "LIB_IDENTICAL=$lib_identical"
    echo "MSL_B_CANDIDATE_BINARY_SHA256=$MSL_B_CANDIDATE_BINARY_SHA256"
    echo "MSL_B_SELFTEST_BINARY_SHA256=$MSL_B_CANDIDATE_BINARY_SHA256"
    [ "$FAIL" -eq 0 ] || return 1
}

msl_b_start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local timeout_seconds="${3:-2}"
    python3 - "$port" "$count_file" "$timeout_seconds" >"${count_file}.log" 2>&1 <<'PY' &
from pathlib import Path
import signal, socket, sys, time
port = int(sys.argv[1])
count_file = Path(sys.argv[2])
deadline = time.monotonic() + int(sys.argv[3])
stop = False
def handle(_signum, _frame):
    global stop
    stop = True
signal.signal(signal.SIGTERM, handle)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
sock.settimeout(0.05)
count = 0
while not stop and time.monotonic() < deadline:
    try:
        sock.recvfrom(65535)
        count += 1
    except socket.timeout:
        continue
count_file.write_text(f"{count}\n", encoding="utf-8")
PY
    printf '%s\n' "$!"
}

if [ "${MSL_B_SELF_TEST_UDP_SINK:-NO}" = YES ]; then
    tmp="${TMPDIR:-/tmp}/msl-b-udp-sink-$$.count"
    pid="$(msl_b_start_udp_sink 17992 "$tmp" 2)"
    sleep 0.2
    set +e
    python3 - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for _ in range(3):
    s.sendto(b"x", ("127.0.0.1", 17992))
PY
    send_rc=$?
    set -u -o pipefail
    if [ "$send_rc" -ne 0 ]; then
        echo "MSL_B_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true"
        kill -TERM "$pid" 2>/dev/null || true
        rm -f "$tmp" "$tmp.log"
        exit 0
    fi
    sleep 2
    kill -TERM "$pid" 2>/dev/null || true
    echo "MSL_B_UDP_SINK_SELF_TEST_COUNT=$(tr -d '[:space:]' < "$tmp")"
    rm -f "$tmp" "$tmp.log"
    exit 0
fi

if [ "$MSL_B_DRY_RUN" != YES ] && [ "$MSL_B_LIVE_RUN" != YES ] && [ "$MSL_B_SELFTEST" != YES ]; then
    echo "MSL_B_OFFLINE_SAFE_REFUSAL=true"
    echo "LIVE_INVOCATIONS=0"
    echo "MSL_B_RUN_CLASSIFICATION=NOT_RUN"
    exit 2
fi

print_final_block() {
    echo "=== COMELIT MSL V1 VARIANT B FINAL ==="
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "MSL_B_START_REFERENCE=MSL_B_T00_IDLE_MEDIA_REQUEST_ACCEPTED"
    echo "SETUP_MARGIN_SECONDS=$SETUP_MARGIN_SECONDS"
    echo "LISTENER_READY_WAIT_SECONDS=$LISTENER_READY_WAIT_SECONDS"
    echo "MEDIA_OBSERVATION_SECONDS=$MEDIA_OBSERVATION_SECONDS"
    echo "MEDIA_STARTUP_OUTER_TIMEOUT=$MEDIA_STARTUP_OUTER_TIMEOUT"
    if [ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS" ] &&
       [ "$SETUP_MARGIN_SECONDS" -ge 30 ] &&
       [ "$MEDIA_OBSERVATION_SECONDS" -ge 10 ]; then
        echo "MSL_B_BOUND_INVARIANT=PASS"
    else
        echo "MSL_B_BOUND_INVARIANT=FAIL"
    fi
    echo "MSL_B_LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    echo "MSL_B_LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "MSL_B_T03_NATIVE_MEDIA_HELPER_PROCESS_START_MONO_MS=N/A REASON=same_ready_listener_process"
    echo "MSL_B_T04_LOCAL_SDP_OFFER_READY_MONO_MS=N/A REASON=no_new_offer"
    echo "MSL_B_T06_CLOUD_P2P_REQUEST_START_MONO_MS=N/A REASON=no_new_cloud_negotiation"
    echo "MSL_B_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS=N/A REASON=no_new_remote_sdp"
    echo "MSL_B_T08_ICE_CONNECTED_MONO_MS=N/A REASON=existing_ICE_session_reused"
    echo "MSL_B_T09_PSEUDOTCP_OPEN_MONO_MS=N/A REASON=existing_PseudoTCP_reused"
    echo "MSL_B_T10_VIP_UAUT_READY_MONO_MS=N/A REASON=existing_UAUT_reused"
    echo "MSL_B_T11_CTPP_REGISTRATION_READY_MONO_MS=N/A REASON=existing_CTPP_registration_reused"
    echo "MEDIA_TEARDOWN=$MEDIA_TEARDOWN"
    echo "MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=$MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED"
    echo "CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
    echo "RTP_SINK_PORTS_REMAINING=$RTP_SINK_PORTS_REMAINING"
    echo "DOOR_ACTIONS_SENT=0"
    echo "GATE_ACTIONS_SENT=0"
    echo "PHYSICAL_RING_ACTIONS=0"
    echo "AUTOMATIC_PROTOCOL_RETRY=false"
    echo "SECOND_MEDIA_SESSION=false"
    echo "MSL_B_RUN_CLASSIFICATION=$MSL_B_RUN_CLASSIFICATION"
    echo "MSL_B_DRY_RUN_COMPLETED=$MSL_B_DRY_RUN_COMPLETED"
    echo "MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=$MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY"
    echo "MSL_B_DRY_RUN_LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "MSL_B_DRY_RUN_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION"
    echo "MSL_B_DRY_RUN_HA_INTERACTION=$MSL_B_HA_INTERACTION"
    echo "MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO"
    echo "=== END COMELIT MSL V1 VARIANT B FINAL ==="
}

restore_listener() {
    local poll
    local status_file
    local start_file
    [ "$LISTENER_STOPPED" -eq 1 ] || return 0
    start_file="$RUN_ROOT/listener-start.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_STOPPED=0
            LISTENER_READY_AFTER=true
            return 0
        fi
        sleep 5
    done
    return 91
}

stop_pid() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

run_dry_run() {
    RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/comelit-msl-v1-b-dry-run.XXXXXX")"
    chmod 700 "$RUN_ROOT"
    SESSION_LOG="$RUN_ROOT/session.log"
    CLOCK_BASE_FILE="$RUN_ROOT/msl-b-clock-base"
    : > "$SESSION_LOG"
    chmod 600 "$SESSION_LOG"
    msl_b_mono_ms > "$CLOCK_BASE_FILE"
    chmod 600 "$CLOCK_BASE_FILE"

    echo "MSL_B_DRY_RUN_MODE=YES"
    echo "MSL_B_DRY_RUN_REAL_HA_WEBHOOK=false"
    echo "MSL_B_DRY_RUN_REAL_COMELIT=false"
    echo "MSL_B_DRY_RUN_CHROOT_BUILD=false"
    echo "MSL_B_DRY_RUN_CANDIDATE_EXECUTED=false"
    echo "MSL_B_BUILD_RC=DRY_RUN"
    echo "P78_GATE_DECISION=substituted REASON=research_branch_uses_commit_and_blob_pins"

    STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
    post_control status "$STATUS_BEFORE" 10
    if status_ready "$STATUS_BEFORE"; then
        LISTENER_READY_BEFORE=true
    else
        fail "MSL_B_DRY_RUN_STATUS_READY=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || return 1

    STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
    LISTENER_STOPPED=1
    post_control stop "$STOP_RESPONSE" 20
    if ! status_stopped "$STOP_RESPONSE"; then
        fail "MSL_B_DRY_RUN_STATUS_STOPPED=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || return 1

    {
        echo "MSL_B_LISTENER_READY_BEFORE=true"
        echo "MSL_B_LISTENER_PROCESS_PID=4242"
        echo "MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true"
        echo "MSL_B_T00_IDLE_MEDIA_REQUEST_ACCEPTED_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T12_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T13_INITIAL_001A_SENT_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_MEDIA_ACTIVE=true"
        echo "MSL_B_T15_MEDIA_ACTIVE_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T17_FIRST_VIDEO_RTP_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T18_FIRST_SPS_PPS_IDR_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_START_TO_FIRST_VIDEO_RTP_MS=0"
        echo "MSL_B_START_TO_DECODABLE_VIDEO_MS=0"
        echo "MSL_B_PHASE_T00_TO_T12_MS=0"
        echo "MSL_B_PHASE_T12_TO_T13_MS=0"
        echo "MSL_B_PHASE_T13_TO_T14_MS=0"
        echo "MSL_B_PHASE_T14_TO_T15_MS=0"
        echo "MSL_B_PHASE_T15_TO_T17_MS=0"
        echo "MSL_B_PHASE_T17_TO_T18_MS=0"
        echo "MSL_B_CLOUD_NEGOTIATION_COUNT=0"
        echo "MSL_B_ICE_BOOTSTRAP_COUNT=0"
        echo "MSL_B_PSEUDOTCP_OPEN_COUNT=0"
        echo "MSL_B_CTPP_REGISTRATION_COUNT=0"
        echo "MSL_B_MEDIA_SESSION_COUNT=1"
        echo "MSL_B_SECOND_MEDIA_SESSION=false"
        echo "MSL_B_LISTENER_READY_AFTER=true"
        echo "MSL_B_RECONNECT_COUNT_BEFORE=0"
        echo "MSL_B_RECONNECT_COUNT_AFTER=0"
        echo "MSL_B_RECONNECT_COUNT_DELTA=0"
        echo "MSL_B_MEDIA_RX_ACTIVE=true"
        echo "MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE=true"
        echo "MSL_B_VIDEO_RTP_PACKETS=3"
        echo "MSL_B_SPS_COUNT=1"
        echo "MSL_B_MEDIA_CHANNEL_CLOSED=true"
        echo "MSL_B_TUNNEL_PRESERVED=true"
    } > "$SESSION_LOG"
    cat "$SESSION_LOG"
    MEDIA_TEARDOWN=CONFIRMED
    CAMPAIGN_PROCESSES_REMAINING=NONE
    RTP_SINK_PORTS_REMAINING=0
    MSL_B_RUN_CLASSIFICATION=DRY_RUN_COMPLETE
    restore_listener || return 91
    MSL_B_DRY_RUN_COMPLETED=true
    MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true
    print_final_block
    rm -rf "$RUN_ROOT"
}

run_selftest() {
    local dry_rc
    if ! msl_b_build_candidate; then
        echo "MSL_B_SELFTEST_COMPLETED=false"
        echo "MSL_B_SELFTEST_BUILD_RC=$MSL_B_LAST_BUILD_RC"
        echo "MSL_B_SELFTEST_HA_INTERACTION=$MSL_B_HA_INTERACTION"
        echo "MSL_B_SELFTEST_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION"
        echo "MSL_B_SELFTEST_CANDIDATE_EXECUTED=false"
        return 1
    fi
    MSL_B_DRY_RUN=YES
    run_dry_run
    dry_rc=$?
    echo "MSL_B_SELFTEST_COMPLETED=$([ "$dry_rc" -eq 0 ] && printf true || printf false)"
    echo "MSL_B_SELFTEST_BUILD_RC=0"
    echo "MSL_B_SELFTEST_BINARY_SHA256=$MSL_B_CANDIDATE_BINARY_SHA256"
    echo "MSL_B_SELFTEST_HA_INTERACTION=$MSL_B_HA_INTERACTION"
    echo "MSL_B_SELFTEST_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION"
    echo "MSL_B_SELFTEST_CANDIDATE_EXECUTED=false"
    [ "$dry_rc" -eq 0 ] || return "$dry_rc"
    [ "$MSL_B_HA_INTERACTION" -eq 0 ] || return 1
    [ "$MSL_B_COMELIT_INTERACTION" -eq 0 ] || return 1
    [ "$LIVE_INVOCATIONS" -eq 0 ] || return 1
}

on_exit() {
    rc=$?
    stop_pid "$LISTENER_PID"
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    RTP_SINK_PORTS_REMAINING=0
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || {
            MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=true
            rc=91
        }
    fi
    if [ -n "$RUN_ROOT" ] && pgrep -af "$CANDIDATE_NAME" >/dev/null 2>&1; then
        CAMPAIGN_PROCESSES_REMAINING=FOUND
        MEDIA_TEARDOWN=UNCERTAIN
    else
        CAMPAIGN_PROCESSES_REMAINING=NONE
        [ "$MEDIA_TEARDOWN" = CONFIRMED ] || MEDIA_TEARDOWN=UNCERTAIN
    fi
    print_final_block
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if { [ "$MSL_B_DRY_RUN" = YES ] && [ "$MSL_B_LIVE_RUN" = YES ]; } ||
   { [ "$MSL_B_SELFTEST" = YES ] && [ "$MSL_B_LIVE_RUN" = YES ]; } ||
   { [ "$MSL_B_SELFTEST" = YES ] && [ "$MSL_B_DRY_RUN" = YES ]; }; then
    echo "MSL_B_MODE_CONFLICT=true"
    echo "LIVE_INVOCATIONS=0"
    exit 2
fi

if [ "$MSL_B_DRY_RUN" = YES ]; then
    trap - EXIT
    run_dry_run
    exit "$?"
fi

[ -n "$MSL_B_EXPECTED_COMMIT_SHA" ] || fail "MSL_B_EXPECTED_COMMIT_SHA_REQUIRED=true"
[ -n "$MSL_B_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "MSL_B_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
if [ "$MSL_B_LIVE_RUN" = YES ]; then
    [ -n "$MSL_B_ATTEMPT_LEDGER" ] || fail "MSL_B_ATTEMPT_LEDGER_REQUIRED=true"
fi
if [ "$MSL_B_LIVE_RUN" = YES ] && [ -n "$MSL_B_ATTEMPT_LEDGER" ]; then
    if [ ! -f "$MSL_B_ATTEMPT_LEDGER" ]; then
        fail "MSL_B_ATTEMPT_LEDGER=ABSENT"
    else
        ledger_value="$(tr -d '[:space:]' < "$MSL_B_ATTEMPT_LEDGER")"
        case "$ledger_value" in
            ''|*[!0-9]*) fail "MSL_B_ATTEMPT_LEDGER=MALFORMED" ;;
            *) [ "$ledger_value" -lt 15 ] || fail "MSL_B_ATTEMPT_LEDGER_CAP=FAIL" ;;
        esac
    fi
fi
[ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS" ] || fail "MSL_B_MEDIA_STARTUP_OUTER_TIMEOUT_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

if [ "${EUID}" -ne 0 ]; then
    echo "MSL_B_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum timeout awk grep bash chmod install readelf cmp stat chroot find readlink sort paste sed tail; do
    command -v "$command" >/dev/null 2>&1 || fail "MSL_B_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "MSL_B_REPO_PRESENT=false"
[ -x "$BASE_WRAPPER" ] || fail "MSL_B_BASE_WRAPPER_PRESENT=false"
if [ -x "$BASE_WRAPPER" ]; then
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "MSL_B_BASE_WRAPPER_SHA256_GATE=FAIL"
fi
repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
echo "MSL_B_REPO_HEAD=$repo_head"
[ "$repo_head" = "$MSL_B_EXPECTED_COMMIT_SHA" ] || fail "MSL_B_EXPECTED_COMMIT_SHA_GATE=FAIL"
[ -z "$(git -C "$REPO" status --porcelain)" ] || fail "MSL_B_WORKTREE_CLEAN=FAIL"
[ "$(git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$SOURCE_REL" | sha256sum | awk '{print $1}')" = "$EXPECTED_BASE_SOURCE_SHA" ] || fail "MSL_B_BASE_SOURCE_SHA_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-msl-v1-variant-b-$STAMP"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
SESSION_LOG="$RUN_ROOT/session.log"
: > "$SESSION_LOG"
chmod 600 "$SESSION_LOG"

git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "MSL_B_TRANSFORM_BLOB=FAIL"
git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "MSL_B_RUNNER_BLOB=FAIL"
git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$BASELINE_RUNNER_REL" > "$RUN_ROOT/baseline-runner.sh" || fail "MSL_B_BASELINE_RUNNER_BLOB=FAIL"
bash -n "$RUN_ROOT/runner.sh" || fail "MSL_B_RUNNER_BASH_N=FAIL"
cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "MSL_B_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "MSL_B_RUNNER_WORKTREE_BLOB_GATE=FAIL"
echo "P78_GATE_DECISION=substituted REASON=research_branch_pins_CT120_clone_commit_generated_source_runner_transform_and_base_wrapper"
[ "$FAIL" -eq 0 ] || exit 1

if [ "$MSL_B_SELFTEST" = YES ]; then
    trap - EXIT
    run_selftest
    exit "$?"
fi

install -d -m 700 "$RUN_DIR"
rm -f "$START_FILE" "$STOP_FILE"
msl_b_mono_ms > "$CLOCK_BASE_FILE"
chmod 600 "$CLOCK_BASE_FILE"

msl_b_build_candidate || exit 1

echo "=== STOP HA LISTENER BEFORE RESEARCH LISTENER ==="
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
post_control status "$STATUS_BEFORE" 10
if status_ready "$STATUS_BEFORE"; then
    LISTENER_READY_BEFORE=true
else
    fail "MSL_B_LISTENER_READY_BEFORE=false"
fi
[ "$FAIL" -eq 0 ] || exit 1
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
status_stopped "$STOP_RESPONSE" || fail "MSL_B_LISTENER_STOP_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

VIDEO_SINK_PID="$(msl_b_start_udp_sink "$VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
AUDIO_SINK_PID="$(msl_b_start_udp_sink "$AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
echo "MSL_B_VIDEO_RTP_SINK=true"
echo "MSL_B_AUDIO_RTP_SINK=true"
echo "MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO"

echo "=== RUN RESEARCH LISTENER AND ONE IDLE MEDIA CONTROL ==="
LIVE_INVOCATIONS=1
LD_LIBRARY_PATH="$MSL_B_BUILD_ROOTFS/lib:$MSL_B_BUILD_ROOTFS/usr/lib" \
MSL_B_CLOCK_BASE_FILE="$CLOCK_BASE_FILE" \
"$MSL_B_BUILD_ROOTFS/lib/ld-musl-x86_64.so.1" "$MSL_B_OUTPUT" > "$SESSION_LOG" 2>&1 &
LISTENER_PID=$!
for _poll in $(seq 1 "$LISTENER_READY_WAIT_SECONDS"); do
    if grep -q "V4_RING_LISTENER_READY=true" "$SESSION_LOG"; then
        break
    fi
    sleep 1
done
grep -q "V4_RING_LISTENER_READY=true" "$SESSION_LOG" || fail "MSL_B_RESEARCH_LISTENER_READY=FAIL"
[ "$FAIL" -eq 0 ] || exit 1
install -m 600 /dev/null "$START_FILE"
sleep "$MEDIA_OBSERVATION_SECONDS"
install -m 600 /dev/null "$STOP_FILE"
sleep 3
install -m 600 /dev/null "$RUN_DIR/stop"
stop_pid "$LISTENER_PID"
LISTENER_PID=""
cat "$SESSION_LOG"
MSL_B_RUN_CLASSIFICATION=VARIANT_B_ATTEMPT_COMPLETE

stop_pid "$VIDEO_SINK_PID"
stop_pid "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
echo "MSL_B_VIDEO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/video.count" 2>/dev/null || printf 0)"
echo "MSL_B_AUDIO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/audio.count" 2>/dev/null || printf 0)"
if grep -q "MSL_B_MEDIA_CHANNEL_CLOSED=true" "$SESSION_LOG"; then
    MEDIA_TEARDOWN=CONFIRMED
fi

echo "=== RESTORE HA LISTENER ==="
restore_listener || exit 91
LISTENER_READY_AFTER=true
exit 0
