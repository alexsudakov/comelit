#!/usr/bin/env bash
# Rebuild the existing safe P13 holder and prove the new RX evidence surface.
# No Comelit network session, Door write, or SEND_ARMED transition occurs here.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOLDER=/root/comelit-p13-native/comelit_p13_holder
HOLDER_SOURCE=/root/comelit-p13-native/comelit_p13_holder.c

printf '%s\n' \
    'P13_EVIDENCE_REBUILD_START=true' \
    'NETWORK_ACTION_PERFORMED=false' \
    'PHYSICAL_DOOR_ACTION=false' \
    'SEND_ARMED_REACHED=false'

[[ "$EUID" -eq 0 ]] || { echo 'P13_EVIDENCE_REBUILD_REQUIRES_ROOT=true'; exit 1; }

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s "$POC_ROOT/tests" -p 'test_p13_holder_transform_evidence.py'
echo 'P13_RX_EVIDENCE_UNIT_TEST=PASS'

bash "$SCRIPT_DIR/rebuild_p13_holder_safe.sh"

[[ -f "$HOLDER_SOURCE" ]] || { echo 'P13_EVIDENCE_GENERATED_SOURCE_PRESENT=false'; exit 1; }
[[ -x "$HOLDER" ]] || { echo 'P13_EVIDENCE_HOLDER_PRESENT=false'; exit 1; }

for marker in \
    'P13_CTPP_RX_EVIDENCE ts_us=' \
    'body_sha256=%s body_hex=%s' \
    'P13_DOOR_RESPONSE_SEEN=true' \
    'P13_DOOR_INBOUND_FRAME_OBSERVED=true'; do
    grep -Fq -- "$marker" "$HOLDER_SOURCE" || {
        echo "P13_EVIDENCE_SOURCE_MARKER=FAIL marker=$marker"
        exit 1
    }
done

if grep -Fq 'P13_DOOR_WRITE_%u_ACKED=true' "$HOLDER_SOURCE"; then
    echo 'P13_EVIDENCE_FALSE_ACK_MARKER_PRESENT=true'
    exit 1
fi
if grep -Fq 'P13_DOOR_WRITE_REQUEST_ID=FAIL' "$HOLDER_SOURCE"; then
    echo 'P13_EVIDENCE_PER_WRITE_RESPONSE_GATE_PRESENT=true'
    exit 1
fi

for marker in \
    'P13_CTPP_RX_EVIDENCE ts_us=' \
    'P13_DOOR_RESPONSE_SEEN=true'; do
    grep -aFq -- "$marker" "$HOLDER" || {
        echo "P13_EVIDENCE_BINARY_MARKER=FAIL marker=$marker"
        exit 1
    }
done

printf '%s\n' \
    'P13_RX_EVIDENCE_SOURCE_CONTRACT=PASS' \
    'P13_RX_EVIDENCE_BINARY_CONTRACT=PASS' \
    'P13_DOOR_ACK_SEMANTICS=UNPROVEN' \
    'P13_DOOR_RESPONSE_SEMANTICS=RESPONSE_SEEN' \
    'P13_CTPP_RX_RAW_EVIDENCE_SCOPE=ROOT_ONLY_RUNTIME_LOG' \
    'P13_SEND_TIMING_CHANGED=false' \
    'P13_AUTO_RETRY_ALLOWED=false' \
    'NETWORK_ACTION_PERFORMED=false' \
    'PHYSICAL_DOOR_ACTION=false' \
    'SEND_ARMED_REACHED=false' \
    'P13_EVIDENCE_REBUILD=PASS'
