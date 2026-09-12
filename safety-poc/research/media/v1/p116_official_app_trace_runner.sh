#!/usr/bin/env bash
# P116 R13D passive official-app trace runner.
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
    printf '%s\n' "usage: $0 --iface IFACE --marker-file PATH --client-ip IP --device-ip IP [--dry-run]"
    printf '%s\n' "       $0 --authorize-passive-capture --iface IFACE --marker-file PATH --client-ip IP --device-ip IP [--retain-raw]"
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
        printf 'SCHEMA=P116_R13D_CAPTURE_PROVENANCE_V1\n'
        printf 'CAPTURE_TOOL=tcpdump\n'
        printf 'CAPTURE_TOOL_VERSION=%s\n' "$(tcpdump --version 2>/dev/null | head -n 1)"
        printf 'EXTRACT_TOOL=tshark\n'
        printf 'EXTRACT_TOOL_VERSION=%s\n' "$(tshark --version 2>/dev/null | head -n 1)"
        printf 'INTERFACE=%s\n' "$IFACE"
        printf 'FILTER=%s\n' "$FILTER_EXPR"
        printf 'START_UTC=%s\n' "$START_UTC"
        printf 'END_UTC=%s\n' "$END_UTC"
        printf 'START_MONOTONIC=%s\n' "$START_MONO"
        printf 'END_MONOTONIC=%s\n' "$END_MONO"
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
[ -n "$DEVICE_IP" ] || die "DEVICE_IP_MISSING=FAILED_SAFE"
[ "$POST_SECONDS" -ge 60 ] || die "POST_WINDOW_TOO_SMALL=FAILED_SAFE"
[ "$PRE_SECONDS" -ge 5 ] || die "PRE_WINDOW_TOO_SMALL=FAILED_SAFE"
[ "$HARD_CAP_SECONDS" -le 180 ] || die "HARD_CAP_TOO_LARGE=FAILED_SAFE"
[ "$MAX_FILE_MB" -le 512 ] || die "MAX_FILE_TOO_LARGE=FAILED_SAFE"
[ "$MAX_MESSAGE_ROWS" -le 1000 ] || die "MAX_MESSAGE_ROWS_TOO_LARGE=FAILED_SAFE"

need_tool python3
need_tool tcpdump
need_tool tshark
need_tool timeout
need_tool sha256sum

if ! ip link show "$IFACE" >/dev/null 2>&1; then
    die "CAPTURE_POINT_MISSING=FAILED_SAFE"
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

FILTER_EXPR="host $CLIENT_IP and host $DEVICE_IP"
if [ -n "$FILTER_EXTRA" ]; then
    FILTER_EXPR="($FILTER_EXPR) and ($FILTER_EXTRA)"
fi

printf 'P116_R13D_PREFLIGHT=PASS\n'
printf 'DRY_RUN=%s\n' "$DRY_RUN"
printf 'AUTHORIZED=%s\n' "$AUTHORIZED"
printf 'PASSIVE_ONLY=true\n'
printf 'BOUNDS=pre:%ss post:%ss marker_wait:%ss hard_cap:%ss max_file_mb:%s max_message_rows:%s\n' "$PRE_SECONDS" "$POST_SECONDS" "$MARKER_WAIT_SECONDS" "$HARD_CAP_SECONDS" "$MAX_FILE_MB" "$MAX_MESSAGE_ROWS"
printf 'RAW_ARTIFACT_POLICY=outside_git_mode_600_sha256_retain_or_delete_by_flag\n'
printf 'FILTER=%s\n' "$FILTER_EXPR"

if [ "$AUTHORIZED" -ne 1 ] || [ "$DRY_RUN" -eq 1 ]; then
    printf 'CAPTURE_NOT_STARTED=DRY_RUN_REQUIRES_OPERATOR_FLAG\n'
    printf 'SUMMARY_ONLY=true\n'
    exit 0
fi

RUN_ID="p116-r13d-$(date -u '+%Y%m%dT%H%M%SZ')"
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
chmod 600 "$RAW_PCAP" 2>/dev/null || true

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

MEDIA_ACTIVE_EPOCH="$(awk 'NR==1 {print $1}' "$MARKER_FILE")"
case "$MEDIA_ACTIVE_EPOCH" in
    ''|*[!0-9.]*)
        kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
        wait "$TCPDUMP_PID" >/dev/null 2>&1 || true
        die "MARKER_EPOCH_INVALID=FAILED_SAFE"
        ;;
esac

CAPTURE_SECONDS=$((PRE_SECONDS + POST_SECONDS))
[ "$CAPTURE_SECONDS" -le "$HARD_CAP_SECONDS" ] || CAPTURE_SECONDS="$HARD_CAP_SECONDS"
sleep "$CAPTURE_SECONDS"
kill "$TCPDUMP_PID" >/dev/null 2>&1 || true
wait "$TCPDUMP_PID" >/dev/null 2>&1 || true

END_UTC="$(utc_now)"
END_MONO="$(mono_now)"
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
    --media-active-epoch "$MEDIA_ACTIVE_EPOCH" \
    --max-message-rows "$MAX_MESSAGE_ROWS" \
    --output-json "$SUMMARY_JSON" \
    >/dev/null
chmod 600 "$SUMMARY_JSON"

record_provenance "$PROVENANCE" "$RAW_PCAP"

if [ "$RETAIN_RAW" -ne 1 ]; then
    rm -f "$RAW_PCAP"
fi

printf '=== P116_R13D_OFFICIAL_APP_TRACE_SUMMARY ===\n'
printf 'SUMMARY_JSON=%s\n' "$SUMMARY_JSON"
printf 'PROVENANCE=%s\n' "$PROVENANCE"
printf 'RAW_RETAINED=%s\n' "$RETAIN_RAW"
python3 - "$SUMMARY_JSON" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
for key in (
    "TOTAL_RECORDS",
    "CLIENT_TO_DEVICE_RECORDS",
    "DEVICE_TO_CLIENT_RECORDS",
    "POST36_CLIENT_TO_DEVICE_RECORDS",
    "POST36_ANY_RECORDS",
    "REPEATING_LT36S_CLASSES",
    "VIDEO_PACKET_COUNT",
    "VIDEO_PT_SET",
    "SPS_COUNT",
    "PPS_COUNT",
    "IDR_COUNT",
    "RTCP_PRESENT",
    "RTCP_PACKET_TYPES",
):
    print(f"{key}={data[key]}")
PY
