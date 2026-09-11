#!/usr/bin/env bash
# COMELIT P115 bounded live entrance-media runner.
# DEFAULT MODE: PAUSE_FOR_MEDIA_VIA_TEST_HARNESS.
#
# TEMPORARY_TEST_HARNESS=true. This CT120 runner cannot call the production
# Home Assistant-only lifecycle methods directly:
# custom_components/comelit/supervisor.py:149 async_pause_for_media()
# custom_components/comelit/supervisor.py:159 _async_stop_locked(LISTENER_STATE_PAUSED_MEDIA)
# custom_components/comelit/supervisor.py:170 async_resume_after_media()
# custom_components/comelit/supervisor.py:181 _async_start_locked()
# custom_components/comelit/supervisor.py:183 _async_stop_locked()
# custom_components/comelit/test_control.py:57 start -> supervisor.async_start()
# custom_components/comelit/test_control.py:73 stop -> supervisor.async_stop()
# The webhook stop/start pair is a temporary bounded test harness that reaches
# the same runtime stop/start substrate, but it is not identical to production:
# reported state label differs (paused_media vs stopped), and Door fail-closed
# media gating is enforced by the integration, not by this harness.
# PRODUCTION_LIFECYCLE_VALIDATED=false until the in-HA media switch validates
# switch -> manager -> pause/transport inside Home Assistant.

set -u -o pipefail
umask 077

BASE_SHA=5b134f19c29bd7b739b0ec3358b58480cf16f174
REPO="${REPO:-/root/comelit-door-diag-repo}"
CT120_IP=192.168.1.85
HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-/root/comelit-artifacts}"
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
P115_BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media
PACKAGED_LIB_REL=custom_components/comelit/native/lib
P115_PACKAGED_BINARY_SHA256=91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7
P115_PACKAGED_BINARY_BYTES=257152
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED_CSV=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
MEDIA_VIDEO_RTP_PORT=17899
MEDIA_AUDIO_RTP_PORT=17808
MEDIA_SESSION_TIMEOUT_SECONDS=45
OUTER_TIMEOUT_SECONDS=75
LIVE_WINDOW_SECONDS=40
P115_LIVE_INVOCATION_LIMIT=1
P115_AUTOMATIC_RETRY=false
P115_BLIND_RETRY=false
P115_LISTENER_MODE="${P115_LISTENER_MODE:-PAUSE_FOR_MEDIA_VIA_TEST_HARNESS}"
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0

FAIL=0
SUMMARY_PRINTED=0
P115_PREFLIGHT_ONLY=false
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$ARTIFACT_ROOT/p115-live-$STAMP"
MEDIA_DIR="$RUN_ROOT/media"
EXTRACT_ROOT="$RUN_ROOT/extracted"
NATIVE_ROOT="$EXTRACT_ROOT/custom_components/comelit/native"
PACKAGED_BINARY="$NATIVE_ROOT/comelit-media"
PACKAGED_LIB_DIR="$NATIVE_ROOT/lib"
RUNTIME_ABI_GATE=FAIL
P115_BASE_WRAPPER_SHA_GATE=FAIL
P115_PACKAGED_BINARY_SHA_GATE=FAIL
P115_RUNTIME_ABI_GATE=FAIL
P115_PACKAGED_BINARY_SHA_BEFORE_RUN=NONE
P115_PACKAGED_BINARY_SHA_AFTER_RUN=NONE
RUNTIME_ROOT=NONE
RUNTIME_LOADER=NONE
RUNTIME_LIBRARY_PATH=NONE
CANDIDATE_WRAPPER=""
HOLDER_SHIM=""
LOG="$RUN_ROOT/helper.stdout-stderr.log"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
WRAPPER_PID=""
MEDIA_PID=""
MEDIA_RC=NOT_REACHED
LIVE_INVOCATIONS=0
MEDIA_PHASE_ACTIVE=UNKNOWN
P80_MEDIA_ACTIVE_OBSERVED=false
VIDEO_P114_MARKER_MAX=NONE
AUDIO_P114_MARKER_MAX=NONE
VIDEO_PACKET_PROGRESS=UNKNOWN
AUDIO_PACKET_PROGRESS=UNKNOWN
VIDEO_RTP_DATAGRAMS=0
AUDIO_RTP_DATAGRAMS=0
P115_H264_SPS_COUNT=0
P115_H264_PPS_COUNT=0
P115_H264_IDR_COUNT=0
P115_H264_FU_A_COUNT=0
P115_H264_STAP_A_COUNT=0
P115_JPEG_RESULT=FAIL
P115_SHORT_VIDEO_RESULT=FAIL
FFPROBE_H264=FAIL
TEARDOWN_CONFIDENCE=UNKNOWN
UPSTREAM_MEDIA_ACTIVE_AT_EXIT=UNKNOWN
LISTENER_READY_BEFORE=false
LISTENER_READY_AFTER=UNKNOWN
LISTENER_RECONNECT_COUNT_BEFORE=UNKNOWN
LISTENER_RECONNECT_COUNT_AFTER=UNKNOWN
LISTENER_PAUSE_FOR_MEDIA_ALLOWED=true
LISTENER_PAUSED_ONLY_DURING_MEDIA=false
LISTENER_PAUSE_COUNT=0
LISTENER_START_COUNT=0
LISTENER_RESTORE_READY=NOT_ATTEMPTED
LISTENER_RESTART_SUPPRESSED=false
LISTENER_STOPPED_FOR_MEDIA=false
LISTENER_RESTORE_ATTEMPTED=false
LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=false
P115_PRE_MEDIA_AMBIGUOUS=false
TEMPORARY_TEST_HARNESS=true
HARNESS_EQUIVALENCE=PROVEN_STATIC
HARNESS_NOT_IDENTICAL_TO_PRODUCTION="reported_state_label_differs_paused_media_vs_stopped;door_fail_closed_media_gating_is_enforced_by_integration_not_harness"
PRODUCTION_LIFECYCLE_VALIDATED=false
P115_RESULT=FAIL
PACKAGED_MUSL_PROCESS_REMAINING=UNKNOWN
OBSERVATION_SECONDS=0
FFMPEG_PRESENT=false
FFPROBE_PRESENT=false
NETWORK_IO_PERFORMED=false
LIVE_INVOCATIONS_THIS_TASK=0
BINARY_REBUILT=false
BINARY_SUBSTITUTED=false
HA_DEPLOYED=false
HA_RESTARTED=false
LISTENER_ACTION_ADDED=false

case "${1:-}" in
    --preflight-only)
        P115_PREFLIGHT_ONLY=true
        ;;
    "")
        ;;
    *)
        echo "P115_UNKNOWN_ARGUMENT=$1"
        exit 2
        ;;
esac

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

post_status() {
    local output="$1"
    local max_time="$2"
    local http_file="${output}.http"
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' --output "$output" \
      --write-out '%{http_code}\n' --data '{"action":"status"}' \
      "$HA_WEBHOOK_URL" > "$http_file"
    local rc=$?
    echo "CONTROL_STATUS_CURL_RC=$rc"
    [ -s "$http_file" ] && echo "CONTROL_STATUS_HTTP_STATUS=$(awk 'NR==1{print $1}' "$http_file")"
    return "$rc"
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
    [ "$(json_scalar "$file" supervisor_running)" = false ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
}

wait_for_listener_stopped() {
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        post_status "$RUN_ROOT/listener-status-paused-$i.json" 5 || true
        if status_stopped "$RUN_ROOT/listener-status-paused-$i.json"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_listener_ready_after_restore() {
    local i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        post_status "$RUN_ROOT/listener-status-restored-$i.json" 5 || true
        if status_ready "$RUN_ROOT/listener-status-restored-$i.json"; then
            LISTENER_RECONNECT_COUNT_AFTER="$(json_scalar "$RUN_ROOT/listener-status-restored-$i.json" reconnect_count)"
            return 0
        fi
        sleep 1
    done
    return 1
}

pre_media_quiescent() {
    if python3 - "$PACKAGED_BINARY" <<'PY'
from pathlib import Path
import sys
needle = sys.argv[1].encode()
for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
    try:
        data = cmdline.read_bytes()
    except OSError:
        continue
    if needle in data:
        raise SystemExit(1)
raise SystemExit(0)
PY
    then
        :
    else
        echo "P115_PRE_MEDIA_HELPER_PROCESS_PRESENT=true"
        return 1
    fi
    if python3 - "$MEDIA_VIDEO_RTP_PORT" "$MEDIA_AUDIO_RTP_PORT" <<'PY'
import socket
import sys
for port in map(int, sys.argv[1:]):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(1)
    finally:
        sock.close()
raise SystemExit(0)
PY
    then
        :
    else
        echo "P115_PRE_MEDIA_RTP_PORT_BOUND=true"
        return 1
    fi
    if [ -d "$RUN_DIR" ]; then
        echo "P115_STALE_RUN_DIR_PRESENT=true"
        python3 - "$RUN_DIR" <<'PY'
from pathlib import Path
import sys
import time
root = Path(sys.argv[1])
newest = root.stat().st_mtime
for path in root.rglob("*"):
    try:
        newest = max(newest, path.stat().st_mtime)
    except OSError:
        pass
age = max(0, int(time.time() - newest))
print(f"P115_STALE_RUN_DIR_AGE_SECONDS={age}")
PY
        if [ -e "$STOP_FILE" ]; then
            echo "P115_PRE_MEDIA_STOP_FILE_PRESENT=true"
            echo "P115_STALE_RUN_DIR_STOP_FILE_PRESENT=true"
        else
            echo "P115_STALE_RUN_DIR_STOP_FILE_PRESENT=false"
        fi
        if rm -rf "$RUN_DIR"; then
            echo "P115_STALE_RUN_DIR_NORMALIZED=true"
        else
            echo "P115_STALE_RUN_DIR_NORMALIZED=false"
            return 1
        fi
    else
        echo "P115_STALE_RUN_DIR_PRESENT=false"
    fi
}

required_libs_present() {
    local libdir="$1"
    [ -r "$libdir/libnice.so.10" ] &&
    [ -r "$libdir/libglib-2.0.so.0" ] &&
    [ -r "$libdir/libgobject-2.0.so.0" ]
}

extract_pinned_native_tree() {
    mkdir -p "$EXTRACT_ROOT"
    git -C "$REPO" archive "$BASE_SHA" custom_components/comelit/native | tar -x -C "$EXTRACT_ROOT"
    [ -f "$PACKAGED_BINARY" ] || fail "P115_PACKAGED_BINARY_PRESENT=false"
    [ -d "$PACKAGED_LIB_DIR" ] || fail "P115_PACKAGED_LIB_DIR_PRESENT=false"
}

assert_packaged_binary_identity() {
    local size
    P115_PACKAGED_BINARY_SHA_BEFORE_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
    size="$(wc -c < "$PACKAGED_BINARY" | awk '{print $1}')"
    echo "P115_PACKAGED_BINARY_SHA_BEFORE_RUN=$P115_PACKAGED_BINARY_SHA_BEFORE_RUN"
    echo "P115_PACKAGED_BINARY_BYTES_ACTUAL=$size"
    if [ "$P115_PACKAGED_BINARY_SHA_BEFORE_RUN" = "$P115_PACKAGED_BINARY_SHA256" ] &&
       [ "$size" = "$P115_PACKAGED_BINARY_BYTES" ]; then
        P115_PACKAGED_BINARY_SHA_GATE=PASS
    else
        P115_PACKAGED_BINARY_SHA_GATE=FAIL
        fail "P115_PACKAGED_BINARY_SHA_GATE=FAIL"
    fi
    echo "P115_PACKAGED_BINARY_SHA_GATE=$P115_PACKAGED_BINARY_SHA_GATE"
}

assert_packaged_elf_identity() {
    local interpreter needed
    interpreter="$(readelf -l "$PACKAGED_BINARY" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
    needed="$(readelf -d "$PACKAGED_BINARY" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
    echo "P115_PACKAGED_BINARY_INTERPRETER=$interpreter"
    echo "P115_PACKAGED_BINARY_NEEDED=$needed"
    [ "$interpreter" = "$EXPECTED_INTERPRETER" ] || fail "P115_ELF_INTERPRETER_GATE=FAIL"
    [ "$needed" = "$EXPECTED_NEEDED_CSV" ] || fail "P115_ELF_NEEDED_GATE=FAIL"
}

assert_packaged_binary_strings() {
    local strings_file="$RUN_ROOT/packaged.strings"
    strings -a "$PACKAGED_BINARY" > "$strings_file"
    grep -Fq 'P80_VIDEO_RTP_PACKETS=%llu' "$strings_file" || fail "P115_P114_VIDEO_MARKER_STRING_GATE=FAIL"
    grep -Fq 'P80_AUDIO_RTP_PACKETS=%llu' "$strings_file" || fail "P115_P114_AUDIO_MARKER_STRING_GATE=FAIL"
    grep -Fq 'P80_MEDIA_ACTIVE=true' "$strings_file" || fail "P115_MEDIA_ACTIVE_STRING_GATE=FAIL"
}

detect_runtime_boundary() {
    local candidate root release
    P115_RUNTIME_ABI_GATE=FAIL
    RUNTIME_ABI_GATE=FAIL
    for candidate in "${P115_TEST_RUNTIME_ROOT:-}" /root/comelit-p80-haos-build-*/rootfs /root/comelit-*-haos-build-*/rootfs /root/*alpine*/rootfs /root/*alpine*; do
        [ -n "$candidate" ] || continue
        for root in $candidate; do
            [ -d "$root" ] || continue
            [ -r "$root/etc/alpine-release" ] || continue
            [ -x "$root/lib/ld-musl-x86_64.so.1" ] || continue
            required_libs_present "$PACKAGED_LIB_DIR" || continue
            release="$(head -n 1 "$root/etc/alpine-release" 2>/dev/null || true)"
            [ -n "$release" ] || continue
            RUNTIME_ROOT="$root"
            RUNTIME_LOADER="$root/lib/ld-musl-x86_64.so.1"
            RUNTIME_LIBRARY_PATH="$PACKAGED_LIB_DIR:$root/lib:$root/usr/lib"
            P115_RUNTIME_ABI_GATE=PASS
            RUNTIME_ABI_GATE=PASS
            echo "RUNTIME_ALPINE_RELEASE=$release"
            echo "P115_RUNTIME_ABI_GATE=PASS"
            return 0
        done
    done
    echo "P115_RUNTIME_ABI_GATE=FAIL"
    return 1
}

assert_base_wrapper_identity() {
    local actual
    [ -f "$BASE_WRAPPER" ] || fail "P115_BASE_WRAPPER_PRESENT=false"
    if [ -f "$BASE_WRAPPER" ]; then
        actual="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
        echo "P115_BASE_WRAPPER_SHA256_ACTUAL=$actual"
        if [ "$actual" = "$P115_BASE_WRAPPER_SHA256" ]; then
            P115_BASE_WRAPPER_SHA_GATE=PASS
        else
            P115_BASE_WRAPPER_SHA_GATE=FAIL
            fail "P115_BASE_WRAPPER_SHA_GATE=FAIL"
        fi
    fi
    echo "P115_BASE_WRAPPER_SHA_GATE=$P115_BASE_WRAPPER_SHA_GATE"
}

prepare_holder_shim() {
    HOLDER_SHIM="$RUN_ROOT/p115_packaged_musl_holder_shim.sh"
    python3 - "$HOLDER_SHIM" <<'PY'
from pathlib import Path
import os
import sys
out = Path(sys.argv[1])
out.write_text(r'''#!/usr/bin/env bash
set -u -o pipefail
umask 077
P115_PACKAGED_BINARY_SHA256=91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7
PACKAGED_BINARY="${P115_EXTRACTED_NATIVE_ROOT:?}/comelit-media"
PACKAGED_LIB_DIR="${P115_EXTRACTED_NATIVE_ROOT:?}/lib"
RUNTIME_ROOT="${P115_RUNTIME_ROOT:?}"
RUNTIME_LOADER="$RUNTIME_ROOT/lib/ld-musl-x86_64.so.1"
RUNTIME_LIBRARY_PATH="$PACKAGED_LIB_DIR:$RUNTIME_ROOT/lib:$RUNTIME_ROOT/usr/lib"
die() { echo "$1"; exit 126; }
[ -f "$PACKAGED_BINARY" ] || die "P115_SHIM_PACKAGED_BINARY_PRESENT=false"
[ -d "$PACKAGED_LIB_DIR" ] || die "P115_SHIM_PACKAGED_LIB_DIR_PRESENT=false"
[ -x "$RUNTIME_LOADER" ] || die "P115_SHIM_MUSL_LOADER_PRESENT=false"
[ -r "$RUNTIME_ROOT/etc/alpine-release" ] || die "P115_SHIM_ALPINE_RUNTIME_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libnice.so.10" ] || die "P115_SHIM_LIBNICE_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libglib-2.0.so.0" ] || die "P115_SHIM_LIBGLIB_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libgobject-2.0.so.0" ] || die "P115_SHIM_LIBGOBJECT_PRESENT=false"
actual_sha="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
echo "P115_SHIM_PACKAGED_BINARY_SHA_BEFORE_EXEC=$actual_sha"
[ "$actual_sha" = "$P115_PACKAGED_BINARY_SHA256" ] || die "P115_SHIM_PACKAGED_BINARY_SHA_GATE=FAIL"
echo "P115_SHIM_MUSL_EXEC_GATE=PASS"
exec "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$PACKAGED_BINARY"
''', encoding="utf-8")
os.chmod(out, 0o700)
PY
    bash -n "$HOLDER_SHIM" || fail "P115_HOLDER_SHIM_PARSE_GATE=FAIL"
}

prepare_candidate_wrapper() {
    CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p115"
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$HOLDER_SHIM" <<'PY'
from pathlib import Path
import os
import sys
src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if text.count(needle) != 1:
    raise SystemExit("P115_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
legacy_run_dir = "/run/comelit-p2p"
if legacy_run_dir not in text:
    raise SystemExit("P115_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, "/run/comelit-media")
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("P115_HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=PASS")
PY
    local rc=$?
    [ "$rc" -eq 0 ] || fail "P115_WRAPPER_REWRITE_GATE=FAIL"
    bash -n "$CANDIDATE_WRAPPER" || fail "P115_WRAPPER_PARSE_GATE=FAIL"
}

start_udp_sink() {
    local label="$1"
    local port="$2"
    local datagrams="$3"
    local hist="$4"
    local count_file="$5"
    local deadline="$6"
    python3 - "$port" "$datagrams" "$hist" "$count_file" "$deadline" <<'PY' &
from collections import Counter
from pathlib import Path
import os
import signal
import socket
import sys
import time
port = int(sys.argv[1])
datagrams_path = Path(sys.argv[2])
hist_path = Path(sys.argv[3])
count_path = Path(sys.argv[4])
deadline = min(int(sys.argv[5]), 75)
stop = False
def _stop(_signum, _frame):
    global stop
    stop = True
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
sock.settimeout(0.5)
hist = Counter()
count = 0
end = time.monotonic() + deadline
with datagrams_path.open("ab") as out:
    os.chmod(datagrams_path, 0o600)
    while not stop and time.monotonic() < end:
        try:
            payload, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        count += 1
        hist[len(payload)] += 1
        out.write(len(payload).to_bytes(2, "big"))
        out.write(payload)
hist_path.write_text(
    "\n".join(f"{length} {hist[length]}" for length in sorted(hist)) + ("\n" if hist else ""),
    encoding="utf-8",
)
count_path.write_text(f"{count}\n", encoding="utf-8")
os.chmod(hist_path, 0o600)
os.chmod(count_path, 0o600)
PY
    local pid=$!
    if [ "$label" = video ]; then
        VIDEO_SINK_PID="$pid"
    else
        AUDIO_SINK_PID="$pid"
    fi
}

stop_sink_if_needed() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
}

stop_media_if_needed() {
    if [ -z "$MEDIA_PID" ] || ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        return 0
    fi
    echo "P115_STOP_FILE_WRITE_FIRST=true"
    install -d -m 700 "$RUN_DIR"
    : > "$STOP_FILE"
    chmod 600 "$STOP_FILE"
    local i
    for i in 1 2 3 4 5; do
        if ! kill -0 "$MEDIA_PID" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "P115_STOP_ESCALATION=TERM"
    kill -TERM "$MEDIA_PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$MEDIA_PID" 2>/dev/null; then
        echo "P115_STOP_ESCALATION=KILL"
        kill -KILL "$MEDIA_PID" 2>/dev/null || true
    fi
}

depacketize_h264() {
    local datagrams="$1"
    local out="$2"
    local stats="$3"
    python3 - "$datagrams" "$out" "$stats" <<'PY'
from pathlib import Path
import os
import sys
src = Path(sys.argv[1])
out = Path(sys.argv[2])
stats = Path(sys.argv[3])
ANNEX = b"\x00\x00\x00\x01"
PT_H264 = 99
payloads = []
if src.exists():
    data = src.read_bytes()
    pos = 0
    while pos + 2 <= len(data):
        size = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        if size < 12 or pos + size > len(data):
            break
        packet = data[pos:pos + size]
        pos += size
        if packet[0] >> 6 != 2:
            continue
        cc = packet[0] & 0x0F
        x = (packet[0] >> 4) & 1
        pt = packet[1] & 0x7F
        header_len = 12 + (cc * 4)
        if len(packet) < header_len:
            continue
        if x:
            if len(packet) < header_len + 4:
                continue
            ext_len = int.from_bytes(packet[header_len + 2:header_len + 4], "big") * 4
            header_len += 4 + ext_len
        if pt == PT_H264 and len(packet) > header_len:
            payloads.append(packet[header_len:])
sps = pps = idr = fua = stapa = 0
annex = bytearray()
fu_parts = []
def emit(nal: bytes) -> None:
    global sps, pps, idr
    if not nal:
        return
    t = nal[0] & 0x1F
    if t == 7:
        sps += 1
    elif t == 8:
        pps += 1
    elif t == 5:
        idr += 1
    annex.extend(ANNEX)
    annex.extend(nal)
for media in payloads:
    nal_type = media[0] & 0x1F
    if 1 <= nal_type <= 23:
        emit(media)
    elif nal_type == 24:
        stapa += 1
        pos = 1
        while pos + 2 <= len(media):
            size = int.from_bytes(media[pos:pos + 2], "big")
            pos += 2
            if size <= 0 or pos + size > len(media):
                break
            emit(media[pos:pos + size])
            pos += size
    elif nal_type == 28 and len(media) >= 3:
        fua += 1
        fu_indicator = media[0]
        fu_header_byte = media[1]
        start = bool(fu_header_byte & 0x80)
        end = bool(fu_header_byte & 0x40)
        original_type = fu_header_byte & 0x1F
        if start:
            fu_parts = [bytes([(fu_indicator & 0xE0) | original_type]), media[2:]]
        elif fu_parts:
            fu_parts.append(media[2:])
        if end and fu_parts:
            emit(b"".join(fu_parts))
            fu_parts = []
out.write_bytes(bytes(annex))
os.chmod(out, 0o600)
stats.write_text(
    "\n".join([
        f"P115_H264_SPS_COUNT={sps}",
        f"P115_H264_PPS_COUNT={pps}",
        f"P115_H264_IDR_COUNT={idr}",
        f"P115_H264_FU_A_COUNT={fua}",
        f"P115_H264_STAP_A_COUNT={stapa}",
        f"P115_VIDEO_RTP_DATAGRAMS={len(payloads)}",
    ]) + "\n",
    encoding="utf-8",
)
os.chmod(stats, 0o600)
PY
}

postprocess_media() {
    local annex="$MEDIA_DIR/video.annexb.h264"
    local stats="$MEDIA_DIR/h264.stats"
    local still="$MEDIA_DIR/still.jpg"
    local clip="$MEDIA_DIR/clip.mp4"
    [ -f "$MEDIA_DIR/video.count" ] && VIDEO_RTP_DATAGRAMS="$(awk 'NR==1{print $1}' "$MEDIA_DIR/video.count")"
    [ -f "$MEDIA_DIR/audio.count" ] && AUDIO_RTP_DATAGRAMS="$(awk 'NR==1{print $1}' "$MEDIA_DIR/audio.count")"
    depacketize_h264 "$MEDIA_DIR/video.rtpdatagrams" "$annex" "$stats" || true
    if [ -f "$stats" ]; then
        P115_H264_SPS_COUNT="$(awk -F= '/^P115_H264_SPS_COUNT=/{print $2}' "$stats")"
        P115_H264_PPS_COUNT="$(awk -F= '/^P115_H264_PPS_COUNT=/{print $2}' "$stats")"
        P115_H264_IDR_COUNT="$(awk -F= '/^P115_H264_IDR_COUNT=/{print $2}' "$stats")"
        P115_H264_FU_A_COUNT="$(awk -F= '/^P115_H264_FU_A_COUNT=/{print $2}' "$stats")"
        P115_H264_STAP_A_COUNT="$(awk -F= '/^P115_H264_STAP_A_COUNT=/{print $2}' "$stats")"
    fi
    if [ "$FFPROBE_PRESENT" = true ]; then
        ffprobe -v error -f h264 "$annex" > "$MEDIA_DIR/ffprobe.out" 2> "$MEDIA_DIR/ffprobe.err" && FFPROBE_H264=PASS || FFPROBE_H264=FAIL
    else
        : > "$MEDIA_DIR/ffprobe.out"
        : > "$MEDIA_DIR/ffprobe.err"
    fi
    chmod 600 "$MEDIA_DIR/ffprobe.out" "$MEDIA_DIR/ffprobe.err" 2>/dev/null || true
    if [ "$FFMPEG_PRESENT" = true ]; then
        if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -frames:v 1 "$still" > "$MEDIA_DIR/ffmpeg-still.out" 2> "$MEDIA_DIR/ffmpeg-still.err" &&
           [ -s "$still" ]; then
            chmod 600 "$still"
            P115_JPEG_RESULT=PASS
        else
            P115_JPEG_RESULT=FAIL
        fi
        if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -an -t 5 -c:v copy "$clip" > "$MEDIA_DIR/ffmpeg-clip.out" 2> "$MEDIA_DIR/ffmpeg-clip.err" &&
           [ -s "$clip" ]; then
            chmod 600 "$clip"
            P115_SHORT_VIDEO_RESULT=PASS
        else
            P115_SHORT_VIDEO_RESULT=FAIL
        fi
        chmod 600 "$MEDIA_DIR/ffmpeg-still.out" "$MEDIA_DIR/ffmpeg-still.err" "$MEDIA_DIR/ffmpeg-clip.out" "$MEDIA_DIR/ffmpeg-clip.err" 2>/dev/null || true
    fi
}

last_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

max_marker() {
    local key="$1"
    if [ -f "$LOG" ]; then
        awk -F= -v key="$key" '$1 == key && $2 ~ /^[0-9]+$/ { if (!found || $2 + 0 > max) { max = $2 + 0; found = 1 } } END { if (found) print max; else print "NONE" }' "$LOG"
    else
        printf 'NONE\n'
    fi
}

derive_log_markers() {
    grep -E '^P80_(VIDEO|AUDIO)_RTP_PACKETS=' "$LOG" > "$RUN_ROOT/p114-marker-lines.txt" 2>/dev/null || : > "$RUN_ROOT/p114-marker-lines.txt"
    VIDEO_P114_MARKER_MAX="$(max_marker P80_VIDEO_RTP_PACKETS)"
    AUDIO_P114_MARKER_MAX="$(max_marker P80_AUDIO_RTP_PACKETS)"
    [ "$VIDEO_P114_MARKER_MAX" != NONE ] && VIDEO_PACKET_PROGRESS=PASS || VIDEO_PACKET_PROGRESS=FAIL
    [ "$AUDIO_P114_MARKER_MAX" != NONE ] && AUDIO_PACKET_PROGRESS=PASS || AUDIO_PACKET_PROGRESS=FAIL
    if [ "$(last_marker P80_MEDIA_ACTIVE false)" = true ]; then
        P80_MEDIA_ACTIVE_OBSERVED=true
        MEDIA_PHASE_ACTIVE=true
    else
        P80_MEDIA_ACTIVE_OBSERVED=false
        MEDIA_PHASE_ACTIVE=false
    fi
}

packaged_processes_remaining() {
    if [ -n "$MEDIA_PID" ] && kill -0 "$MEDIA_PID" 2>/dev/null; then
        PACKAGED_MUSL_PROCESS_REMAINING=FOUND
    else
        PACKAGED_MUSL_PROCESS_REMAINING=NONE
    fi
}

derive_teardown_confidence() {
    packaged_processes_remaining
    if [ "$PACKAGED_MUSL_PROCESS_REMAINING" = NONE ]; then
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false
    else
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
    fi
    if [ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ] &&
       [ "$MEDIA_RC" != 124 ] &&
       [ "$MEDIA_RC" != 137 ]; then
        TEARDOWN_CONFIDENCE=CONFIRMED
    else
        TEARDOWN_CONFIDENCE=UNCERTAIN
    fi
}

post_control() {
    local action="$1"
    local body="$2"
    local output="$3"
    local max_time="$4"
    local http_file="${output}.http"
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' --output "$output" \
      --write-out '%{http_code}\n' --data "$body" \
      "$HA_WEBHOOK_URL" > "$http_file"
    local rc=$?
    echo "CONTROL_${action}_CURL_RC=$rc"
    [ -s "$http_file" ] && echo "CONTROL_${action}_HTTP_STATUS=$(awk 'NR==1{print $1}' "$http_file")"
    return "$rc"
}

restore_listener_if_allowed() {
    [ "$P115_LISTENER_MODE" = PAUSE_FOR_MEDIA_VIA_TEST_HARNESS ] || return 0
    [ "$LISTENER_STOPPED_FOR_MEDIA" = true ] || return 0
    [ "$LISTENER_RESTORE_ATTEMPTED" = false ] || return 0
    if [ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]; then
        LISTENER_RESTART_SUPPRESSED=true
        LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=true
        LISTENER_READY_AFTER=UNKNOWN
        LISTENER_RESTORE_READY=NOT_ATTEMPTED
        echo "LISTENER_RESTART_SUPPRESSED=true"
        echo "LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=true"
        echo "P115_STOP_ALL_LIVE_ATTEMPTS=true"
        return 90
    fi
    LISTENER_RESTORE_ATTEMPTED=true
    LISTENER_START_COUNT=1
    post_control start '{"action":"start"}' "$RUN_ROOT/listener-start.json" 35 || true
    if wait_for_listener_ready_after_restore; then
        LISTENER_READY_AFTER=true
        LISTENER_RESTORE_READY=PASS
        return 0
    fi
    LISTENER_READY_AFTER=false
    LISTENER_RESTORE_READY=FAIL
    return 1
}

derive_result() {
    P115_RESULT=FAIL
    if [ "$FAIL" -ne 0 ]; then
        P115_RESULT=FAIL
    elif [ "$LISTENER_READY_BEFORE" != true ]; then
        P115_RESULT=BLOCKED
    elif [ "$P80_MEDIA_ACTIVE_OBSERVED" = true ] &&
         [ "$VIDEO_RTP_DATAGRAMS" -gt 0 ] &&
         [ "$AUDIO_RTP_DATAGRAMS" -gt 0 ] &&
         [ "$P115_H264_SPS_COUNT" -gt 0 ] &&
         [ "$P115_H264_PPS_COUNT" -gt 0 ] &&
         [ "$P115_H264_IDR_COUNT" -gt 0 ] &&
         [ "$P115_JPEG_RESULT" = PASS ] &&
         [ "$P115_SHORT_VIDEO_RESULT" = PASS ] &&
         [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
        P115_RESULT=PASS
    elif [ "$LIVE_INVOCATIONS" -eq 1 ]; then
        P115_RESULT=PARTIAL
    fi
}

write_summary_file() {
    print_summary > "$RUN_ROOT/summary.txt"
}

print_summary() {
    [ "${1:-}" = force ] || [ "$SUMMARY_PRINTED" -eq 0 ] || return 0
    SUMMARY_PRINTED=1
    derive_result
    echo "=== P115 LIVE RUN SUMMARY ==="
    echo "P115_LIVE_RUN_ID=$STAMP"
    echo "P115_BASE_SHA=$BASE_SHA"
    echo "P115_LISTENER_MODE=$P115_LISTENER_MODE"
    echo "P115_PACKAGED_BINARY_SHA_BEFORE_RUN=$P115_PACKAGED_BINARY_SHA_BEFORE_RUN"
    echo "P115_PACKAGED_BINARY_SHA_GATE=$P115_PACKAGED_BINARY_SHA_GATE"
    echo "P115_RUNTIME_ABI_GATE=$P115_RUNTIME_ABI_GATE"
    echo "P115_BASE_WRAPPER_SHA_GATE=$P115_BASE_WRAPPER_SHA_GATE"
    echo "LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    if [ "$P115_LISTENER_MODE" = NO_LISTENER_ACTION ]; then
        echo "LISTENER_INTENTIONALLY_STOPPED=false"
    fi
    echo "LISTENER_PAUSE_FOR_MEDIA_ALLOWED=$LISTENER_PAUSE_FOR_MEDIA_ALLOWED"
    echo "LISTENER_PAUSED_ONLY_DURING_MEDIA=$LISTENER_PAUSED_ONLY_DURING_MEDIA"
    echo "LISTENER_PAUSE_COUNT=$LISTENER_PAUSE_COUNT"
    echo "LISTENER_START_COUNT=$LISTENER_START_COUNT"
    echo "LISTENER_RESTORE_READY=$LISTENER_RESTORE_READY"
    echo "LISTENER_RESTART_SUPPRESSED=$LISTENER_RESTART_SUPPRESSED"
    echo "LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=$LIVE_BLOCKED_AMBIGUOUS_TEARDOWN"
    echo "P115_PRE_MEDIA_AMBIGUOUS=$P115_PRE_MEDIA_AMBIGUOUS"
    echo "TEMPORARY_TEST_HARNESS=$TEMPORARY_TEST_HARNESS"
    echo "HARNESS_EQUIVALENCE=$HARNESS_EQUIVALENCE"
    echo "HARNESS_NOT_IDENTICAL_TO_PRODUCTION=$HARNESS_NOT_IDENTICAL_TO_PRODUCTION"
    echo "PRODUCTION_LIFECYCLE_VALIDATED=$PRODUCTION_LIFECYCLE_VALIDATED"
    echo "LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "LISTENER_RECONNECT_COUNT_BEFORE=$LISTENER_RECONNECT_COUNT_BEFORE"
    echo "LISTENER_RECONNECT_COUNT_AFTER=$LISTENER_RECONNECT_COUNT_AFTER"
    echo "LIVE_CAMERA_ATTEMPT=$LIVE_INVOCATIONS"
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "MEDIA_PHASE_ACTIVE=$MEDIA_PHASE_ACTIVE"
    echo "P80_MEDIA_ACTIVE_OBSERVED=$P80_MEDIA_ACTIVE_OBSERVED"
    echo "VIDEO_P114_MARKER_MAX=$VIDEO_P114_MARKER_MAX"
    echo "AUDIO_P114_MARKER_MAX=$AUDIO_P114_MARKER_MAX"
    echo "VIDEO_PACKET_PROGRESS=$VIDEO_PACKET_PROGRESS"
    echo "AUDIO_PACKET_PROGRESS=$AUDIO_PACKET_PROGRESS"
    echo "VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS"
    echo "AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS"
    echo "P115_H264_SPS_COUNT=$P115_H264_SPS_COUNT"
    echo "P115_H264_PPS_COUNT=$P115_H264_PPS_COUNT"
    echo "P115_H264_IDR_COUNT=$P115_H264_IDR_COUNT"
    echo "P115_JPEG_RESULT=$P115_JPEG_RESULT"
    echo "P115_SHORT_VIDEO_RESULT=$P115_SHORT_VIDEO_RESULT"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "UPSTREAM_MEDIA_ACTIVE_AT_EXIT=$UPSTREAM_MEDIA_ACTIVE_AT_EXIT"
    echo "DOOR_ACTIONS_SENT=0"
    echo "GATE_ACTIONS_SENT=0"
    echo "P115_RESULT=$P115_RESULT"
    echo "=== END P115 LIVE RUN SUMMARY ==="
}

on_exit() {
    local original_rc=$?
    stop_media_if_needed || true
    stop_sink_if_needed "$VIDEO_SINK_PID" || true
    stop_sink_if_needed "$AUDIO_SINK_PID" || true
    if [ "$LISTENER_STOPPED_FOR_MEDIA" = true ] && [ "$TEARDOWN_CONFIDENCE" = UNKNOWN ]; then
        derive_teardown_confidence
    fi
    if [ "$LISTENER_STOPPED_FOR_MEDIA" = true ] && [ "$LISTENER_RESTORE_ATTEMPTED" = false ]; then
        restore_listener_if_allowed || original_rc=$?
    fi
    if [ -n "${PACKAGED_BINARY:-}" ] && [ -f "$PACKAGED_BINARY" ]; then
        P115_PACKAGED_BINARY_SHA_AFTER_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
    fi
    print_summary
    exit "$original_rc"
}

if [ "${P115_SOURCE_ONLY:-0}" = 1 ]; then
    return 0 2>/dev/null || exit 0
fi

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "P115_LIVE_REQUIRES_ROOT=true"
    exit 1
fi

mkdir -p "$MEDIA_DIR"
chmod 700 "$RUN_ROOT" "$MEDIA_DIR"
: > "$LOG"
chmod 600 "$LOG"

for command in git tar python3 sha256sum timeout strings grep curl ip awk head wc readelf sed install date; do
    command -v "$command" >/dev/null 2>&1 || fail "P115_MISSING_COMMAND=$command"
done
command -v ffmpeg >/dev/null 2>&1 && FFMPEG_PRESENT=true
command -v ffprobe >/dev/null 2>&1 && FFPROBE_PRESENT=true

echo "P115_BASE_SHA=$BASE_SHA"
case "$P115_LISTENER_MODE" in
    PAUSE_FOR_MEDIA_VIA_TEST_HARNESS|NO_LISTENER_ACTION)
        ;;
    *)
        echo "P115_UNSUPPORTED_LISTENER_MODE=$P115_LISTENER_MODE"
        exit 2
        ;;
esac
echo "P115_LISTENER_MODE=$P115_LISTENER_MODE"
if [ "$P115_LISTENER_MODE" = NO_LISTENER_ACTION ]; then
    echo "LISTENER_INTENTIONALLY_STOPPED=false"
fi
echo "LISTENER_PAUSE_FOR_MEDIA_ALLOWED=true"
echo "P115_LIVE_INVOCATION_LIMIT=1"
echo "MEDIA_SESSION_TIMEOUT_SECONDS=45"
echo "OUTER_TIMEOUT_SECONDS=75"
echo "LIVE_WINDOW_SECONDS=40"
echo "P115_AUTOMATIC_RETRY=false"
echo "P115_BLIND_RETRY=false"
echo "DOOR_ACTIONS_SENT=0"
echo "GATE_ACTIONS_SENT=0"
echo "BINARY_REBUILT=false"
echo "BINARY_SUBSTITUTED=false"
echo "HA_DEPLOYED=false"
echo "HA_RESTARTED=false"
echo "LISTENER_ACTION_ADDED=false"
echo "TEMPORARY_TEST_HARNESS=true"
echo "HARNESS_EQUIVALENCE=PROVEN_STATIC"
echo "HARNESS_NOT_IDENTICAL_TO_PRODUCTION=$HARNESS_NOT_IDENTICAL_TO_PRODUCTION"
echo "PRODUCTION_LIFECYCLE_VALIDATED=false"

[ -d "$REPO/.git" ] || fail "P115_REPO_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    extract_pinned_native_tree || fail "P115_GIT_ARCHIVE_EXTRACT_GATE=FAIL"
fi
if [ "$FAIL" -eq 0 ]; then
    assert_packaged_binary_identity
    assert_packaged_elf_identity
    assert_packaged_binary_strings
    detect_runtime_boundary || true
    [ "$P115_RUNTIME_ABI_GATE" = PASS ] || fail "P115_RUNTIME_ABI_GATE=FAIL"
    assert_base_wrapper_identity
    prepare_holder_shim
    prepare_candidate_wrapper
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P115_PREFLIGHT=FAIL"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    exit 1
fi

echo "P115_PREFLIGHT=PASS"
if [ "$P115_PREFLIGHT_ONLY" = true ]; then
    echo "P115_PREFLIGHT_ONLY=true"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    P115_RESULT=BLOCKED
    exit 0
fi

post_status "$RUN_ROOT/listener-status-before.json" 10 || true
if status_ready "$RUN_ROOT/listener-status-before.json"; then
    LISTENER_READY_BEFORE=true
    LISTENER_RECONNECT_COUNT_BEFORE="$(json_scalar "$RUN_ROOT/listener-status-before.json" reconnect_count)"
    echo "LISTENER_READY_BEFORE=true"
    echo "LISTENER_RECONNECT_COUNT_BEFORE=$LISTENER_RECONNECT_COUNT_BEFORE"
else
    LISTENER_READY_BEFORE=false
    echo "P115_LISTENER_NOT_READY=true"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    P115_RESULT=BLOCKED
    exit 2
fi

if ! pre_media_quiescent; then
    P115_PRE_MEDIA_AMBIGUOUS=true
    echo "P115_PRE_MEDIA_AMBIGUOUS=true"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    P115_RESULT=BLOCKED
    exit 3
fi
if pre_media_quiescent; then
    echo "P115_PRE_MEDIA_QUIESCENT_AFTER_NORMALIZATION=PASS"
else
    P115_PRE_MEDIA_AMBIGUOUS=true
    echo "P115_PRE_MEDIA_QUIESCENT_AFTER_NORMALIZATION=FAIL"
    echo "P115_PRE_MEDIA_AMBIGUOUS=true"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    P115_RESULT=BLOCKED
    exit 3
fi

if [ "$P115_LISTENER_MODE" = PAUSE_FOR_MEDIA_VIA_TEST_HARNESS ]; then
    LISTENER_PAUSE_COUNT=1
    post_control stop '{"action":"stop"}' "$RUN_ROOT/listener-stop.json" 15 || true
    if wait_for_listener_stopped; then
        LISTENER_STOPPED_FOR_MEDIA=true
        LISTENER_PAUSED_ONLY_DURING_MEDIA=true
        echo "LISTENER_PAUSE_COUNT=1"
        echo "LISTENER_PAUSED_ONLY_DURING_MEDIA=true"
        echo "P115_LISTENER_PAUSE_GATE=PASS"
    else
        LISTENER_PAUSE_COUNT=1
        echo "LISTENER_PAUSE_COUNT=1"
        echo "P115_LISTENER_PAUSE_GATE=FAIL"
        echo "LIVE_INVOCATIONS_THIS_TASK=0"
        P115_RESULT=BLOCKED
        exit 4
    fi
    sleep 5
fi

rm -rf "$RUN_DIR"
install -d -m 700 "$RUN_DIR"
start_udp_sink video "$MEDIA_VIDEO_RTP_PORT" "$MEDIA_DIR/video.rtpdatagrams" "$MEDIA_DIR/video.lengths" "$MEDIA_DIR/video.count" "$OUTER_TIMEOUT_SECONDS"
start_udp_sink audio "$MEDIA_AUDIO_RTP_PORT" "$MEDIA_DIR/audio.rtpdatagrams" "$MEDIA_DIR/audio.lengths" "$MEDIA_DIR/audio.count" "$OUTER_TIMEOUT_SECONDS"

echo "=== EXACTLY ONE P115 BASE WRAPPER LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
LIVE_INVOCATIONS_THIS_TASK=1
export P115_EXTRACTED_NATIVE_ROOT="$NATIVE_ROOT"
export P115_RUNTIME_ROOT="$RUNTIME_ROOT"
timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_TIMEOUT_SECONDS}s" \
    "$CANDIDATE_WRAPPER" > "$LOG" 2>&1 &
WRAPPER_PID=$!
MEDIA_PID="$WRAPPER_PID"
NETWORK_IO_PERFORMED=true
TEARDOWN_CONFIDENCE=UNKNOWN

while [ "$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS" ]; do
    if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    OBSERVATION_SECONDS=$((OBSERVATION_SECONDS + 1))
done
echo "P115_OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
stop_media_if_needed
wait "$WRAPPER_PID" || MEDIA_RC=$?
[ "$MEDIA_RC" = NOT_REACHED ] && MEDIA_RC=0
MEDIA_PID=""
WRAPPER_PID=""

stop_sink_if_needed "$VIDEO_SINK_PID"
stop_sink_if_needed "$AUDIO_SINK_PID"
wait "$VIDEO_SINK_PID" 2>/dev/null || true
wait "$AUDIO_SINK_PID" 2>/dev/null || true
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""

derive_log_markers
derive_teardown_confidence
postprocess_media
P115_PACKAGED_BINARY_SHA_AFTER_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
[ "$P115_PACKAGED_BINARY_SHA_AFTER_RUN" = "$P115_PACKAGED_BINARY_SHA_BEFORE_RUN" ] || fail "P115_PACKAGED_BINARY_SHA_AFTER_GATE=FAIL"

if [ "$P115_LISTENER_MODE" = PAUSE_FOR_MEDIA_VIA_TEST_HARNESS ]; then
    if [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
        restore_listener_if_allowed || exit 1
    else
        LISTENER_RESTART_SUPPRESSED=true
        LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=true
        LISTENER_READY_AFTER=UNKNOWN
        LISTENER_RESTORE_READY=NOT_ATTEMPTED
        echo "LISTENER_RESTART_SUPPRESSED=true"
        echo "LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=true"
        echo "P115_STOP_ALL_LIVE_ATTEMPTS=true"
        exit 90
    fi
else
    post_status "$RUN_ROOT/listener-status-after.json" 10 || true
    if status_ready "$RUN_ROOT/listener-status-after.json"; then
        LISTENER_READY_AFTER=true
    else
        LISTENER_READY_AFTER=false
    fi
    LISTENER_RECONNECT_COUNT_AFTER="$(json_scalar "$RUN_ROOT/listener-status-after.json" reconnect_count)"
fi

write_summary_file
[ "$FAIL" -eq 0 ] || exit 1
print_summary force
trap - EXIT
exit 0
