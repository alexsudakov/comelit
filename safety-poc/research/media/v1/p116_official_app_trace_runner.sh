#!/usr/bin/env bash
# P116 R13E passive official-app trace runner.
#
# Tooling only. Do not run against Comelit in this repository round.
# Default mode is dry-run preflight. The only live capture path requires the
# explicit --authorize-passive-capture operator flag on the capture host.

set -u -o pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
EXTRACTOR="$SCRIPT_DIR/p116_official_app_trace_extractor.py"

AUTHORIZED=0
DRY_RUN=1
IFACE=""
CLIENT_IP=""
DEVICE_IP=""
MARKER_FILE=""
OUT_ROOT="${OUT_ROOT:-/tmp/comelit-p116-official-app-trace}"
PRE_SECONDS=5
POST_SECONDS=90
MARKER_WAIT_SECONDS=120
HARD_CAP_SECONDS=125
MAX_FILE_MB=256
MAX_MESSAGE_ROWS=200
RETAIN_RAW=0
FILTER_EXTRA=""

usage() {
    printf '%s\n' "usage: $0 --iface IFACE --marker-file PATH --client-ip IP [--device-ip IP] [--dry-run]"
    printf '%s\n' "       $0 --authorize-passive-capture --iface IFACE --marker-file PATH --client-ip IP [--device-ip IP] [--retain-raw]"
    printf '%s\n' "operator must wait for CAPTURE_ARMED=true before opening the official-app view"
    printf '%s\n' "marker file first field is OPERATOR_VIEW_START_EPOCH written at view open"
}

die() {
    printf '%s\n' "$1" >&2
    exit 2
}

need_tool() {
    command -v "$1" >/dev/null 2>&1 || die "TOOL_MISSING=$1"
}

utc_now() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

mono_now() {
    python3 - <<'PY'
import time
print(f"{time.monotonic():.6f}")
PY
}

epoch_now() {
    python3 - <<'PY'
import time
print(f"{time.time():.6f}")
PY
}

float_compare() {
    python3 - "$1" "$2" "$3" <<'PY'
import sys
left = float(sys.argv[1])
op = sys.argv[2]
right = float(sys.argv[3])
checks = {
    "le": left <= right,
    "ge": left >= right,
    "gt": left > right,
}
raise SystemExit(0 if checks[op] else 1)
PY
}

float_eval() {
    python3 - "$@" <<'PY'
import sys
op = sys.argv[1]
if op == "add":
    print(f"{float(sys.argv[2]) + float(sys.argv[3]):.6f}")
elif op == "sub":
    print(f"{float(sys.argv[2]) - float(sys.argv[3]):.6f}")
elif op == "sleep_until":
    import time
    target = float(sys.argv[2])
    sleep_for = max(0.0, target - time.time())
    print(f"{sleep_for:.6f}")
else:
    raise SystemExit(2)
PY
}

sha_file() {
    sha256sum "$1" | awk '{print $1}'
}

size_bytes() {
    wc -c < "$1" | tr -d ' '
}

record_provenance() {
    local path="$1"
    local raw="$2"
    {
        printf 'SCHEMA=P116_R13E_CAPTURE_PROVENANCE_V1\n'
        printf 'CAPTURE_TOOL=tcpdump\n'
        printf 'CAPTURE_TOOL_VERSION=%s\n' "$(tcpdump --version 2>/dev/null | head -n 1)"
        printf 'EXTRACT_TOOL=tshark\n'
        printf 'EXTRACT_TOOL_VERSION=%s\n' "$(tshark --version 2>/dev/null | head -n 1)"
        printf 'INTERFACE=%s\n' "$IFACE"
        printf 'CAPTURE_FILTER_MODE=%s\n' "$FILTER_MODE"
        printf 'DEVICE_IP_REQUIRED=false\n'
        printf 'FILTER_IP_TERM_COUNT=%s\n' "$FILTER_IP_TERM_COUNT"
        printf 'FILTER=%s\n' "$FILTER_EXPR"
        printf 'START_UTC=%s\n' "$START_UTC"
        printf 'END_UTC=%s\n' "$END_UTC"
        printf 'START_MONOTONIC=%s\n' "$START_MONO"
        printf 'END_MONOTONIC=%s\n' "$END_MONO"
        printf 'CAPTURE_START_EPOCH=%s\n' "$CAPTURE_START_EPOCH"
        printf 'CAPTURE_END_EPOCH=%s\n' "$CAPTURE_END_EPOCH"
        printf 'OPERATOR_VIEW_START_EPOCH=%s\n' "$OPERATOR_VIEW_START_EPOCH"
        printf 'RAW_PCAP_SHA256=%s\n' "$(sha_file "$raw")"
        printf 'RAW_PCAP_SIZE=%s\n' "$(size_bytes "$raw")"
        printf 'FIELD_TSV_SHA256=%s\n' "$(sha_file "$FIELD_TSV")"
        printf 'FIELD_TSV_SIZE=%s\n' "$(size_bytes "$FIELD_TSV")"
        printf 'SUMMARY_JSON_SHA256=%s\n' "$(sha_file "$SUMMARY_JSON")"
        printf 'SUMMARY_JSON_SIZE=%s\n' "$(size_bytes "$SUMMARY_JSON")"
    } > "$path"
    chmod 600 "$path"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --authorize-passive-capture)
            AUTHORIZED=1
            DRY_RUN=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --iface)
            IFACE="${2:-}"
            shift 2
            ;;
        --client-ip)
            CLIENT_IP="${2:-}"
            shift 2
            ;;
        --device-ip)
            DEVICE_IP="${2:-}"
            shift 2
            ;;
        --marker-file)
            MARKER_FILE="${2:-}"
            shift 2
            ;;
        --out-root)
            OUT_ROOT="${2:-}"
            shift 2
            ;;
        --pre-seconds)
            PRE_SECONDS="${2:-}"
            shift 2
            ;;
        --post-seconds)
            POST_SECONDS="${2:-}"
            shift 2
            ;;
        --marker-wait-seconds)
            MARKER_WAIT_SECONDS="${2:-}"
            shift 2
            ;;
        --hard-cap-seconds)
            HARD_CAP_SECONDS="${2:-}"
            shift 2
            ;;
        --max-file-mb)
            MAX_FILE_MB="${2:-}"
            shift 2
            ;;
        --max-message-rows)
            MAX_MESSAGE_ROWS="${2:-}"
            shift 2
            ;;
        --retain-raw)
            RETAIN_RAW=1
            shift
            ;;
        --filter-extra)
            FILTER_EXTRA="${2:-}"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            usage
            die "UNKNOWN_ARGUMENT=$1"
            ;;
    esac
done

[ -n "$IFACE" ] || die "CAPTURE_POINT_MISSING=FAILED_SAFE"
[ -n "$MARKER_FILE" ] || die "MARKER_FILE_MISSING=FAILED_SAFE"
[ -n "$CLIENT_IP" ] || die "CLIENT_IP_MISSING=FAILED_SAFE"
[ "$POST_SECONDS" -ge 60 ] || die "POST_WINDOW_TOO_SMALL=FAILED_SAFE"
[ "$PRE_SECONDS" -ge 5 ] || die "PRE_WINDOW_TOO_SMALL=FAILED_SAFE"
[ "$HARD_CAP_SECONDS" -le 180 ] || die "HARD_CAP_TOO_LARGE=FAILED_SAFE"
[ "$MAX_FILE_MB" -le 512 ] || die "MAX_FILE_TOO_LARGE=FAILED_SAFE"
[ "$MAX_MESSAGE_ROWS" -le 1000 ] || die "MAX_MESSAGE_ROWS_TOO_LARGE=FAILED_SAFE"
PRE_POST_SECONDS=$((PRE_SECONDS + POST_SECONDS))
[ "$PRE_POST_SECONDS" -le "$HARD_CAP_SECONDS" ] || die "POST_WINDOW_EXCEEDS_HARD_CAP=FAILED_SAFE"

need_tool python3

if ! ip link show "$IFACE" >/dev/null 2>&1 && [ ! -e "/sys/class/net/$IFACE" ]; then
    die "CAPTURE_POINT_MISSING=FAILED_SAFE"
fi

if [ "$AUTHORIZED" -eq 1 ] && [ "$DRY_RUN" -ne 1 ]; then
    need_tool tcpdump
    need_tool tshark
    need_tool timeout
    need_tool sha256sum
fi

case "$OUT_ROOT" in
    "$PWD"|"$PWD"/*)
        die "RAW_ARTIFACT_PATH_INSIDE_REPO=FAILED_SAFE"
        ;;
esac

mkdir -p "$OUT_ROOT"
chmod 700 "$OUT_ROOT"
[ -w "$OUT_ROOT" ] || die "OUTPUT_PATH_NOT_WRITABLE=FAILED_SAFE"

FREE_KB="$(df -Pk "$OUT_ROOT" | awk 'NR==2 {print $4}')"
NEEDED_KB=$((MAX_FILE_MB * 1024 + 102400))
[ "${FREE_KB:-0}" -ge "$NEEDED_KB" ] || die "DISK_SPACE_TOO_SMALL=FAILED_SAFE"

FILTER_MODE="CLIENT_ONLY"
FILTER_IP_TERM_COUNT=1
FILTER_EXPR="host $CLIENT_IP"
if [ -n "$DEVICE_IP" ]; then
    FILTER_MODE="CLIENT_DEVICE_NARROW"
    FILTER_IP_TERM_COUNT=2
    FILTER_EXPR="host $CLIENT_IP and host $DEVICE_IP"
fi
if [ -n "$FILTER_EXTRA" ]; then
    FILTER_EXPR="($FILTER_EXPR) and ($FILTER_EXTRA)"
fi

printf 'P116_R13E_PREFLIGHT=PASS\n'
printf 'DRY_RUN=%s\n' "$DRY_RUN"
printf 'AUTHORIZED=%s\n' "$AUTHORIZED"
printf 'PASSIVE_ONLY=true\n'
printf 'BOUNDS=pre:%ss post:%ss marker_wait:%ss hard_cap:%ss max_file_mb:%s max_message_rows:%s\n' "$PRE_SECONDS" "$POST_SECONDS" "$MARKER_WAIT_SECONDS" "$HARD_CAP_SECONDS" "$MAX_FILE_MB" "$MAX_MESSAGE_ROWS"
printf 'RAW_ARTIFACT_POLICY=outside_git_mode_600_sha256_retain_raw_for_one_shot\n'
printf 'RAW_RETENTION_POLICY=RECOMMENDED_RETAIN_RAW_FOR_ONE_SHOT\n'
printf 'RETAIN_RAW=%s\n' "$RETAIN_RAW"
printf 'CAPTURE_FILTER_MODE=%s\n' "$FILTER_MODE"
printf 'DEVICE_IP_REQUIRED=false\n'
printf 'FILTER_IP_TERM_COUNT=%s\n' "$FILTER_IP_TERM_COUNT"
printf 'CAPTURE_HOST_TOOLCHAIN_REQUIRED=tcpdump,tshark,python3,timeout,sha256sum\n'

if [ "$AUTHORIZED" -ne 1 ] || [ "$DRY_RUN" -eq 1 ]; then
    printf 'CAPTURE_NOT_STARTED=DRY_RUN_REQUIRES_OPERATOR_FLAG\n'
    printf 'SUMMARY_ONLY=true\n'
    exit 0
fi

RUN_ID="p116-r13e-$(date -u '+%Y%m%dT%H%M%SZ')"
RUN_DIR="$OUT_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"

RAW_PCAP="$RUN_DIR/official-app-passive.pcap"
FIELD_TSV="$RUN_DIR/official-app-fields.tsv"
SUMMARY_JSON="$RUN_DIR/official-app-summary.json"
PROVENANCE="$RUN_DIR/provenance.txt"

START_UTC="$(utc_now)"
START_MONO="$(mono_now)"

tcpdump -i "$IFACE" -n -s 0 -B 4096 -C "$MAX_FILE_MB" -W 1 -w "$RAW_PCAP" "$FILTER_EXPR" >/dev/null 2>"$RUN_DIR/tcpdump.stderr" &
TCPDUMP_PID="$!"
CAPTURE_START_EPOCH="$(epoch_now)"
chmod 600 "$RAW_PCAP" 2>/dev/null || true
if ! kill -0 "$TCPDUMP_PID" >/dev/null 2>&1; then
    wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
    die "CAPTURE_PROCESS_EXITED=FAILED_SAFE"
fi
printf 'CAPTURE_ARMED=true\n'
printf 'OPERATOR_MAY_OPEN_VIEW_NOW=true\n'
printf 'OPERATOR_INSTRUCTION=WAIT_FOR_CAPTURE_ARMED_THEN_OPEN_VIEW\n'
printf 'OPERATOR_INSTRUCTION=WRITE_MARKER_FILE_WITH_OPERATOR_VIEW_START_EPOCH_AT_VIEW_OPEN\n'

MARKER_FOUND=0
for _ in $(seq 1 "$MARKER_WAIT_SECONDS"); do
    if [ -s "$MARKER_FILE" ]; then
        MARKER_FOUND=1
        break
    fi
    sleep 1
done

if [ "$MARKER_FOUND" -ne 1 ]; then
    kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
    wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
    die "OPERATOR_MARKER_TIMEOUT=FAILED_SAFE"
fi

OPERATOR_VIEW_START_EPOCH="$(awk 'NR==1 {print $1}' "$MARKER_FILE")"
case "$OPERATOR_VIEW_START_EPOCH" in
    ''|*[!0-9.]*)
        kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
        wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
        die "MARKER_EPOCH_INVALID=FAILED_SAFE"
        ;;
esac
if ! python3 - "$OPERATOR_VIEW_START_EPOCH" <<'PY'
import sys
float(sys.argv[1])
PY
then
    kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
    wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
    die "MARKER_EPOCH_INVALID=FAILED_SAFE"
fi
NOW_EPOCH="$(epoch_now)"
if float_compare "$OPERATOR_VIEW_START_EPOCH" gt "$NOW_EPOCH"; then
    kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
    wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
    die "MARKER_EPOCH_INVALID=FAILED_SAFE"
fi
PRE_WINDOW_SECONDS="$(float_eval sub "$OPERATOR_VIEW_START_EPOCH" "$CAPTURE_START_EPOCH")"
if ! float_compare "$PRE_WINDOW_SECONDS" ge "$PRE_SECONDS"; then
    kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
    wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
    printf 'OPERATOR_VIEW_START_EPOCH=%s\n' "$OPERATOR_VIEW_START_EPOCH" >&2
    printf 'PRE_WINDOW_SECONDS=%s\n' "$PRE_WINDOW_SECONDS" >&2
    printf 'PRE_WINDOW_TOO_SHORT=FAILED_SAFE\n' >&2
    printf 'CAPTURE_VALID=false\n' >&2
    exit 2
fi
printf 'PRE_WINDOW_GATE=PASS\n'
printf 'PRE_WINDOW_SECONDS=%s\n' "$PRE_WINDOW_SECONDS"

CAPTURE_STOP_EPOCH="$(float_eval add "$CAPTURE_START_EPOCH" "$HARD_CAP_SECONDS")"
SLEEP_SECONDS="$(float_eval sleep_until "$CAPTURE_STOP_EPOCH")"
sleep "$SLEEP_SECONDS"
kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
wait "$TCPDUMP_PID" >/dev/null 2>&1 || true

END_UTC="$(utc_now)"
END_MONO="$(mono_now)"
CAPTURE_END_EPOCH="$(epoch_now)"
chmod 600 "$RAW_PCAP"

tshark -r "$RAW_PCAP" -T fields \
    -e frame.time_epoch \
    -e frame.len \
    -e ip.src \
    -e ip.dst \
    -e ipv6.src \
    -e ipv6.dst \
    -e udp.srcport \
    -e udp.dstport \
    -e tcp.srcport \
    -e tcp.dstport \
    -e _ws.col.Protocol \
    -e rtp.p_type \
    -e rtp.ssrc \
    -e rtp.timestamp \
    -e rtcp.pt \
    -e h264.nal_unit_type \
    -e tcp.len \
    -e udp.length \
    -E separator=/t \
    -E occurrence=f \
    > "$FIELD_TSV"
chmod 600 "$FIELD_TSV"

python3 "$EXTRACTOR" \
    --input-tsv "$FIELD_TSV" \
    --client-ip "$CLIENT_IP" \
    --device-ip "$DEVICE_IP" \
    --operator-view-start-epoch "$OPERATOR_VIEW_START_EPOCH" \
    --capture-start-epoch "$CAPTURE_START_EPOCH" \
    --capture-end-epoch "$CAPTURE_END_EPOCH" \
    --max-message-rows "$MAX_MESSAGE_ROWS" \
    --output-json "$SUMMARY_JSON" \
    >/dev/null
chmod 600 "$SUMMARY_JSON"

record_provenance "$PROVENANCE" "$RAW_PCAP"

if [ "$RETAIN_RAW" -ne 1 ]; then
    rm -f "$RAW_PCAP"
fi

printf '=== P116_R13E_OFFICIAL_APP_TRACE_SUMMARY ===\n'
printf 'SUMMARY_JSON=%s\n' "$SUMMARY_JSON"
printf 'PROVENANCE=%s\n' "$PROVENANCE"
printf 'RAW_RETAINED=%s\n' "$RETAIN_RAW"
python3 - "$SUMMARY_JSON" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
for key in (
    "TOTAL_RECORDS",
    "REMOTE_PEER_COUNT",
    "CLIENT_TO_REMOTE_RECORDS",
    "REMOTE_TO_CLIENT_RECORDS",
    "POST36_CLIENT_TO_REMOTE_RECORDS",
    "POST36_ANY_RECORDS",
    "MEDIA_ACTIVE_REFERENCE",
    "VIEW_TO_FIRST_RTP_SECONDS",
    "POST_MEDIA_ACTIVE_CAPTURE_SECONDS",
    "POST_MEDIA_ACTIVE_90S_GATE",
    "POST_MEDIA_ACTIVE_60S_GATE",
    "MESSAGE_FAMILY_BUCKET_COUNT",
    "MESSAGE_FAMILY_ROWS_EMITTED",
    "MESSAGE_FAMILY_ROWS_TRUNCATED",
    "REPEATING_LT36S_CLASSES",
    "VIDEO_PACKET_COUNT",
    "VIDEO_PT_SET",
    "SPS_COUNT",
    "PPS_COUNT",
    "IDR_COUNT",
    "RTCP_PRESENT",
    "RTCP_PACKET_TYPES",
    "RAW_CLIENT_IP_IN_SANITISED_SUMMARY",
    "RAW_REMOTE_IP_IN_SANITISED_SUMMARY",
):
    print(f"{key}={data[key]}")
PY
