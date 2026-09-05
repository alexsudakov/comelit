#!/usr/bin/env bash
# CT120 offline-only forensic for official PseudoTCP teardown behavior.
# No Comelit network request, no HA call, no Door, no media signaling.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
CT120_IP=192.168.1.85
SELF=/root/comelit-artifacts/self_activation.pcap
RTSP=/root/comelit-artifacts/p2p_rtsp.pcap
SELF_SHA=f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a
RTSP_SHA=62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3
ANALYZER_REL=safety-poc/research/media/v1/pseudotcp_teardown_forensic.py
HELPER_REL=safety-poc/research/media/v1/pseudotcp_pcap_handshake_forensic.py
SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c

FAIL=0

fail() {
    echo "$1"
    FAIL=1
}

if [ "${EUID}" -ne 0 ]; then
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 sha256sum ip; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "PSEUDOTCP_TEARDOWN_FORENSIC_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "PSEUDOTCP_TEARDOWN_FORENSIC_REPO_PRESENT=false"
fi

if ! ip -4 addr show | grep -Fq "$CT120_IP/"; then
    fail "PSEUDOTCP_TEARDOWN_FORENSIC_CT120_IDENTITY=FAIL"
else
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_CT120_IDENTITY=PASS"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "PSEUDOTCP_TEARDOWN_FORENSIC_REMOTE_MAIN_PRESENT=false"
fi

if [ ! -f "$SELF" ]; then
    fail "SELF_ACTIVATION_PCAP_PRESENT=false"
else
    ACTUAL_SELF_SHA=$(sha256sum "$SELF" | awk '{print $1}')
    echo "SELF_ACTIVATION_SHA256=$ACTUAL_SELF_SHA"
    if [ "$ACTUAL_SELF_SHA" = "$SELF_SHA" ]; then
        echo "SELF_ACTIVATION_IDENTITY=PASS"
    else
        fail "SELF_ACTIVATION_IDENTITY=FAIL"
    fi
fi

if [ ! -f "$RTSP" ]; then
    fail "P2P_RTSP_PCAP_PRESENT=false"
else
    ACTUAL_RTSP_SHA=$(sha256sum "$RTSP" | awk '{print $1}')
    echo "P2P_RTSP_SHA256=$ACTUAL_RTSP_SHA"
    if [ "$ACTUAL_RTSP_SHA" = "$RTSP_SHA" ]; then
        echo "P2P_RTSP_IDENTITY=PASS"
    else
        fail "P2P_RTSP_IDENTITY=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_PREFLIGHT=FAIL"
    echo "NETWORK_IO_PERFORMED=false"
    echo "HOME_ASSISTANT_TOUCHED=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"
    exit 1
fi

REMOTE_MAIN=$(git -C "$REPO" rev-parse "$REMOTE_REF")
echo "PSEUDOTCP_TEARDOWN_FORENSIC_REMOTE_MAIN=$REMOTE_MAIN"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RUN_ROOT=/root/comelit-pseudotcp-teardown-forensic-$STAMP
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

ANALYZER=$RUN_ROOT/pseudotcp_teardown_forensic.py
HELPER=$RUN_ROOT/pseudotcp_pcap_handshake_forensic.py
SOURCE=$RUN_ROOT/comelit-v4-persistent-ctpp-door.c

git -C "$REPO" show "$REMOTE_MAIN:$ANALYZER_REL" > "$ANALYZER"
A_RC=$?
git -C "$REPO" show "$REMOTE_MAIN:$HELPER_REL" > "$HELPER"
H_RC=$?
git -C "$REPO" show "$REMOTE_MAIN:$SOURCE_REL" > "$SOURCE"
S_RC=$?

echo "TEARDOWN_ANALYZER_EXTRACT_RC=$A_RC"
echo "HANDSHAKE_HELPER_EXTRACT_RC=$H_RC"
echo "CURRENT_NATIVE_SOURCE_EXTRACT_RC=$S_RC"

if [ "$A_RC" -ne 0 ] || [ "$H_RC" -ne 0 ] || [ "$S_RC" -ne 0 ]; then
    fail "PSEUDOTCP_TEARDOWN_FORENSIC_EXTRACT=FAIL"
else
    chmod 700 "$ANALYZER" "$HELPER"
    python3 -m py_compile "$ANALYZER" "$HELPER"
    COMPILE_RC=$?
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_PY_COMPILE_RC=$COMPILE_RC"
    if [ "$COMPILE_RC" -ne 0 ]; then
        FAIL=1
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    python3 "$ANALYZER" \
      --self-activation "$SELF" \
      --p2p-rtsp "$RTSP" \
      --source "$SOURCE"
    ANALYZE_RC=$?
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_ANALYZE_RC=$ANALYZE_RC"
    if [ "$ANALYZE_RC" -ne 0 ]; then
        FAIL=1
    fi
fi

echo
echo "=== FINAL ==="
echo "PSEUDOTCP_TEARDOWN_FORENSIC_RUN_ROOT=$RUN_ROOT"
echo "NETWORK_IO_PERFORMED=false"
echo "HOME_ASSISTANT_TOUCHED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$FAIL" -eq 0 ]; then
    echo "PSEUDOTCP_TEARDOWN_FORENSIC_RUNNER=PASS"
    exit 0
fi

echo "PSEUDOTCP_TEARDOWN_FORENSIC_RUNNER=FAIL"
exit 1
