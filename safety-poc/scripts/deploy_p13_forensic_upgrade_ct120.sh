#!/usr/bin/env bash
# CT120 root deployment for the pre-observation P13 forensic upgrade.
#
# This script is deliberately NON-ACTUATING. It performs only local/offline
# PCAP analysis, target provenance verification, native holder rebuild,
# runtime-identity recapture, and non-actuating readiness checks. It never
# invokes the observed-open gate/live runner and never reaches SEND_ARMED.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
EXPECTED_TARGET_FINGERPRINT=832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce
PCAP=/root/comelit-artifacts/self_activation.pcap
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
REPORT_DIR=/root/comelit-p13-forensic
D1_REPORT="$REPORT_DIR/d1-primary-capture.txt"
PROVENANCE_REPORT="$REPORT_DIR/target-provenance.txt"
READINESS_REPORT="$REPORT_DIR/observed-readiness.txt"

STEP=START
finish() {
    rc=$?
    printf 'P13_FORENSIC_UPGRADE_EXIT_RC=%s\n' "$rc"
    printf 'P13_FORENSIC_UPGRADE_LAST_STEP=%s\n' "$STEP"
    printf '%s\n' \
        'NETWORK_DOOR_ACTION_PERFORMED=false' \
        'PHYSICAL_DOOR_ACTION=false' \
        'SEND_ARMED_REACHED=false' \
        'P13_ACTUATOR_COMMAND_ATTEMPTED=false' \
        'P13_PHYSICAL_EFFECT_ASSERTED=false'
    trap - EXIT
    exit "$rc"
}
trap finish EXIT

printf '%s\n' \
    'P13_FORENSIC_UPGRADE_START=true' \
    'P13_FORENSIC_UPGRADE_NON_ACTUATING=true' \
    'NETWORK_DOOR_ACTION_PERFORMED=false' \
    'PHYSICAL_DOOR_ACTION=false' \
    'SEND_ARMED_REACHED=false'

STEP=IDENTITY
[[ "$EUID" -eq 0 ]] || { echo 'P13_FORENSIC_UPGRADE_REQUIRES_ROOT=true'; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_FORENSIC_UPGRADE_BRANCH=FAIL'; exit 1;
}
LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$EXPECTED_BRANCH")"
[[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] || { echo 'P13_FORENSIC_UPGRADE_REMOTE_IDENTITY=FAIL'; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_FORENSIC_UPGRADE_WORKTREE_CLEAN=false'; exit 1;
}
echo "P13_FORENSIC_UPGRADE_HEAD=$LOCAL_HEAD"
echo "P13_FORENSIC_UPGRADE_TREE=$(git -C "$REPO_ROOT" rev-parse 'HEAD^{tree}')"

STEP=INPUTS
[[ -f "$PCAP" ]] || { echo 'P13_D1_PCAP_PRESENT=false'; exit 1; }
[[ -f "$PAYLOAD" ]] || { echo 'P13_PAYLOAD_PRESENT=false'; exit 1; }
[[ "$(stat -c '%u' "$PAYLOAD")" == 0 ]] || { echo 'P13_PAYLOAD_OWNER=FAIL'; exit 1; }
[[ "$(stat -c '%a' "$PAYLOAD")" == 600 ]] || { echo 'P13_PAYLOAD_MODE=FAIL'; exit 1; }
python3 -c 'import scapy.all' >/dev/null 2>&1 || {
    echo 'P13_D1_SCAPY_PRESENT=false'
    echo 'P13_D1_ACTION=install python3-scapy before retrying this non-actuating deployment'
    exit 1
}
install -d -m 700 -o root -g root "$REPORT_DIR"
printf '%s\n' 'P13_FORENSIC_UPGRADE_INPUTS=PASS'

STEP=CORRECTIVE_UNIT_TESTS
for pattern in \
    test_p13_holder_transform_evidence.py \
    test_p13_d1_pcap_forensic.py \
    test_p13_target_provenance.py; do
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s "$POC_ROOT/tests" -p "$pattern"
done
echo 'P13_FORENSIC_CORRECTIVE_UNIT_TESTS=PASS'

STEP=D1_PRIMARY_CAPTURE
python3 "$SCRIPT_DIR/p13_d1_pcap_forensic.py" \
    --pcap "$PCAP" \
    --payload "$PAYLOAD" \
    --report "$D1_REPORT"
chmod 600 "$D1_REPORT"
chown root:root "$D1_REPORT"
grep -qx 'P13_D1_FORENSIC=PASS' "$D1_REPORT" || { echo 'P13_D1_FORENSIC_GATE=FAIL'; exit 1; }
grep -qx 'P13_D1_STANDALONE_ACCEPTABLE=true' "$D1_REPORT" || { echo 'P13_D1_STANDALONE_GATE=FAIL'; exit 1; }
# Bind the parser result to the independently rechecked self_activation fixture:
# 2511/5936 application bytes yield exactly 59/52 ViP messages after one
# capture-pinned seven-byte pre-ViP prefix in each direction.  The prefix is
# treated only as an observed framing invariant; no protocol semantics are
# inferred from it.  The D1 parser also proves that the final parsed frame ends
# exactly at stream end, so no additional unframed bytes are accepted.
for required in \
    'P13_D1_SELECTED_OUT_VIP_FRAMES=59' \
    'P13_D1_SELECTED_IN_VIP_FRAMES=52' \
    'P13_D1_OUT_STREAM_GAPS=0' \
    'P13_D1_IN_STREAM_GAPS=0' \
    'P13_D1_OUT_STREAM_CONFLICTS=0' \
    'P13_D1_IN_STREAM_CONFLICTS=0' \
    'P13_D1_OUT_UNFRAMED_BYTES=7' \
    'P13_D1_IN_UNFRAMED_BYTES=7' \
    'P13_D1_OUT_CAPTURE_PREFIX=PASS' \
    'P13_D1_IN_CAPTURE_PREFIX=PASS' \
    'P13_D1_CAPTURE_PREFIX_MATCH=PASS' \
    'P13_D1_CAPTURE_PREFIX_BYTES=7'; do
    grep -qx "$required" "$D1_REPORT" || {
        echo "P13_D1_PRIMARY_CAPTURE_INVARIANT=FAIL expected=$required"
        exit 1
    }
done
echo 'P13_D1_PRIMARY_CAPTURE_INVARIANTS=PASS'
grep -E '^(P13_D1_CAPTURE_DOOR_FRAME=|P13_D1_CAPTURE_TARGET_MATCH=|P13_D1_PREPARED_WRITE_COUNT=|P13_D1_PREPARED_OPCODES=|P13_D1_PREPARED_OPERATION_SUFFIX_MATCH=|P13_D1_PREPARED_TARGET_MATCH_COUNT=|P13_D1_PREPARED_EXACT_BODY_MATCH_COUNT=|P13_D1_STANDALONE_RELATION=|P13_D1_STANDALONE_ACCEPTABLE=|P13_D1_DOOR_SPECIFIC_ACK=|P13_D1_DOOR_RESPONSE_CANDIDATE_COUNT=|P13_D1_PREVIOUS_TAP_TO_DOOR_MS=|P13_D1_DOOR_TO_NEXT_TAP_MS=|P13_D1_SELECTED_OUT_VIP_FRAMES=|P13_D1_SELECTED_IN_VIP_FRAMES=|P13_D1_OUT_UNFRAMED_BYTES=|P13_D1_IN_UNFRAMED_BYTES=|P13_D1_OUT_CAPTURE_PREFIX=|P13_D1_IN_CAPTURE_PREFIX=|P13_D1_CAPTURE_PREFIX_MATCH=|P13_D1_CAPTURE_PREFIX_BYTES=|P13_D1_FORENSIC=)' "$D1_REPORT"
echo 'P13_D1_PRIMARY_CAPTURE_GATE=PASS'

STEP=TARGET_PROVENANCE
python3 "$SCRIPT_DIR/p13_target_provenance.py" \
    --payload "$PAYLOAD" \
    --report "$PROVENANCE_REPORT"
chmod 600 "$PROVENANCE_REPORT"
chown root:root "$PROVENANCE_REPORT"
grep -qx 'P13_TARGET_PROVENANCE=PASS' "$PROVENANCE_REPORT" || { echo 'P13_TARGET_PROVENANCE_GATE=FAIL'; exit 1; }
grep -E '^(P13_APARTMENT_IDENTITY_SOURCE=|P13_APARTMENT_IDENTITY_MATCH=|P13_ENTRANCE_TARGET_SOURCE=|P13_ENTRANCE_TARGET_MATCH=|P13_PREPARED_CAPTURE_TARGET_MATCH_COUNT=|P13_UCFG_OPENDOOR_ACTION_PRESENT=|P13_UCFG_OUTPUT_INDEX=|P13_PREPARED_TARGET_FINGERPRINT_MATCH=|P13_TARGET_PROVENANCE=)' "$PROVENANCE_REPORT"
echo 'P13_TARGET_PROVENANCE_GATE=PASS'

STEP=RX_EVIDENCE_REBUILD
bash "$SCRIPT_DIR/rebuild_p13_holder_evidence.sh"

STEP=RUNTIME_IDENTITY
P13_TARGET_FINGERPRINT="$EXPECTED_TARGET_FINGERPRINT" \
    bash "$SCRIPT_DIR/p13_capture_runtime_identity.sh"
echo 'P13_FORENSIC_RUNTIME_IDENTITY=PASS'

STEP=NON_ACTUATING_PREFLIGHT
unset P13_APPROVAL P13_OPERATION_ID || true
bash "$SCRIPT_DIR/p13_actuation_preflight.sh"
echo 'P13_FORENSIC_NON_ACTUATING_PREFLIGHT=PASS'

STEP=OBSERVED_GATE_READINESS
set +e
env -u P13_APPROVAL -u P13_OPERATION_ID \
    bash "$SCRIPT_DIR/p13_hermes_observed_acceptance_preflight.sh" \
    >"$READINESS_REPORT" 2>&1
readiness_rc=$?
set -e
chmod 600 "$READINESS_REPORT"
chown root:root "$READINESS_REPORT"
cat "$READINESS_REPORT"
[[ "$readiness_rc" -eq 0 ]] || { echo "P13_FORENSIC_OBSERVED_READINESS_RC=$readiness_rc"; exit "$readiness_rc"; }
grep -qx 'P13_HERMES_OBSERVED_GATE_UNUSED=true' "$READINESS_REPORT" || { echo 'P13_FORENSIC_GATE_UNUSED=FAIL'; exit 1; }
grep -qx 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=true' "$READINESS_REPORT" || { echo 'P13_FORENSIC_OBSERVED_ACCEPTANCE_READY=FAIL'; exit 1; }
echo 'P13_FORENSIC_GATE_UNUSED=PASS'
echo 'P13_FORENSIC_OBSERVED_ACCEPTANCE_READY=PASS'

STEP=COMPLETE
printf '%s\n' \
    'P13_FORENSIC_D1_GATE=PASS' \
    'P13_FORENSIC_TARGET_PROVENANCE_GATE=PASS' \
    'P13_FORENSIC_RX_EVIDENCE_GATE=PASS' \
    'P13_FORENSIC_GATE_UNUSED=PASS' \
    'P13_FORENSIC_OBSERVED_ACCEPTANCE_READY=PASS' \
    'P13_DOOR_ACK_SEMANTICS=UNPROVEN_OR_D1_CLASSIFIED' \
    'P13_PHYSICAL_TEST_EXECUTED=false' \
    'NETWORK_DOOR_ACTION_PERFORMED=false' \
    'PHYSICAL_DOOR_ACTION=false' \
    'SEND_ARMED_REACHED=false' \
    'P13_ACTUATOR_COMMAND_ATTEMPTED=false' \
    'P13_PHYSICAL_EFFECT_ASSERTED=false' \
    'P13_FORENSIC_UPGRADE_DEPLOY=PASS'
