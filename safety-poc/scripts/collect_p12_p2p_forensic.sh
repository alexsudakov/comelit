#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
HOLDER_ROOT=/root/comelit-vip-poc/bin
SOURCE="$HOLDER_ROOT/comelit_ice_offer_holder.c"
BINARY="$HOLDER_ROOT/comelit_ice_offer_holder"
WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
ORIGINAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ -n "$ORIGINAL_BRANCH" ]] || { echo "P12_P2P_FORENSIC_REQUIRES_NAMED_BRANCH=true"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_P2P_FORENSIC_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/p12-p2p-forensic-${STAMP}"
EVIDENCE_REL="evidence/p12-p2p-forensic/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "P12_P2P_FORENSIC_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=5
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$ORIGINAL_BRANCH
SOURCE_HEAD=$ORIGINAL_HEAD
PUBLIC_SAFE=true
SOURCE_EXECUTED=false
BINARY_EXECUTED=false
WRAPPER_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
EOF

identity_line() {
    local label="$1" path="$2"
    if [[ -f "$path" ]]; then
        printf '%s_PRESENT=true\n' "$label"
        printf '%s_MODE=%s\n' "$label" "$(stat -c '%a' "$path")"
        printf '%s_BYTES=%s\n' "$label" "$(stat -c '%s' "$path")"
        printf '%s_MTIME_EPOCH=%s\n' "$label" "$(stat -c '%Y' "$path")"
        printf '%s_SHA256=%s\n' "$label" "$(sha256sum "$path" | awk '{print $1}')"
    else
        printf '%s_PRESENT=false\n' "$label"
    fi
}

marker_bool_source() {
    local label="$1" pattern="$2" path="$3"
    if [[ -f "$path" ]] && grep -Eq "$pattern" "$path"; then
        printf '%s=true\n' "$label"
    else
        printf '%s=false\n' "$label"
    fi
}

marker_bool_binary() {
    local label="$1" pattern="$2" path="$3"
    if [[ -f "$path" ]] && strings -a "$path" 2>/dev/null | grep -Eq "$pattern"; then
        printf '%s=true\n' "$label"
    else
        printf '%s=false\n' "$label"
    fi
}

{
    echo "=== CURRENT HOLDER IDENTITY ==="
    identity_line HOLDER_SOURCE "$SOURCE"
    identity_line HOLDER_BINARY "$BINARY"
    identity_line P2P_WRAPPER "$WRAPPER"
    echo "SOURCE_BINARY_CONTENT_EMITTED=false"
    echo "WRAPPER_CONTENT_EMITTED=false"

    if [[ -f "$WRAPPER" ]]; then
        if bash -n "$WRAPPER" >/dev/null 2>&1; then
            echo "P2P_WRAPPER_SHELL_PARSE=PASS"
        else
            echo "P2P_WRAPPER_SHELL_PARSE=FAIL"
        fi
    fi

    holder_count=0
    if [[ -f "$BINARY" ]]; then
        holder_count="$(pgrep -f -- "^${BINARY}([[:space:]]|$)" 2>/dev/null | wc -l | tr -d ' ' || true)"
    fi
    echo "ACTIVE_HOLDER_PROCESS_COUNT=${holder_count:-0}"
    echo "PROCESS_ARGUMENTS_EMITTED=false"
} > "$EVIDENCE_DIR/current_identity.txt"

{
    echo "=== CURRENT SOURCE SAFE MARKERS ==="
    marker_bool_source SOURCE_HAS_P2P_SUCCESS_MARKER 'P2P_RESULT|P2P_CLOUD_NEGOTIATION' "$SOURCE"
    marker_bool_source SOURCE_HAS_ICE_MARKER 'P2_ICE_CONNECTIVITY|ICE_READY|SELECTED_PAIR' "$SOURCE"
    marker_bool_source SOURCE_HAS_PSEUDOTCP_MARKER 'P2_PSEUDOTCP_OPEN|PSEUDOTCP_OPEN' "$SOURCE"
    marker_bool_source SOURCE_HAS_ECHO_MARKER 'P2_VIP_ECHO_ACK|VIP_ECHO_ACK' "$SOURCE"
    marker_bool_source SOURCE_HAS_UAUT_OPEN_MARKER 'P2_VIP_UAUT_OPEN|VIP_UAUT_OPEN_RESPONSE' "$SOURCE"
    marker_bool_source SOURCE_HAS_UAUT_AUTH_MARKER 'UAUT.*(AUTH|ACCESS)|VIP_UAUT_ACCESS|response-code' "$SOURCE"
    marker_bool_source SOURCE_HAS_UCFG_MARKER 'UCFG|CONFIGURATION|config-data' "$SOURCE"
    marker_bool_source SOURCE_HAS_CLEAN_CLOSE_MARKER 'CLOSE.*UAUT|UAUT.*CLOSE|CLEAN_TEARDOWN' "$SOURCE"
    marker_bool_source SOURCE_HAS_CTPP_SYMBOL 'CTPP' "$SOURCE"
    marker_bool_source SOURCE_HAS_DOOR_ACTUATOR_SYMBOL 'OPEN_DOOR|open_door|create_door_message' "$SOURCE"
    echo "MATCHING_SOURCE_LINES_EMITTED=false"
} > "$EVIDENCE_DIR/source_markers.txt"

{
    echo "=== CURRENT BINARY SAFE MARKERS ==="
    marker_bool_binary BINARY_HAS_P2P_SUCCESS_MARKER 'P2P_RESULT|P2P_CLOUD_NEGOTIATION' "$BINARY"
    marker_bool_binary BINARY_HAS_ICE_MARKER 'P2_ICE_CONNECTIVITY|ICE_READY|SELECTED_PAIR' "$BINARY"
    marker_bool_binary BINARY_HAS_PSEUDOTCP_MARKER 'P2_PSEUDOTCP_OPEN|PSEUDOTCP_OPEN' "$BINARY"
    marker_bool_binary BINARY_HAS_ECHO_MARKER 'P2_VIP_ECHO_ACK|VIP_ECHO_ACK' "$BINARY"
    marker_bool_binary BINARY_HAS_UAUT_OPEN_MARKER 'P2_VIP_UAUT_OPEN|VIP_UAUT_OPEN_RESPONSE' "$BINARY"
    marker_bool_binary BINARY_HAS_UAUT_AUTH_MARKER 'UAUT.*(AUTH|ACCESS)|VIP_UAUT_ACCESS|response-code' "$BINARY"
    marker_bool_binary BINARY_HAS_UCFG_MARKER 'UCFG|CONFIGURATION|config-data' "$BINARY"
    marker_bool_binary BINARY_HAS_CTPP_SYMBOL 'CTPP' "$BINARY"
    marker_bool_binary BINARY_HAS_DOOR_ACTUATOR_SYMBOL 'OPEN_DOOR|open_door|create_door_message' "$BINARY"
    echo "MATCHING_BINARY_STRINGS_EMITTED=false"
} > "$EVIDENCE_DIR/binary_markers.txt"

{
    echo "=== WRAPPER SAFE MARKERS ==="
    marker_bool_source WRAPPER_HAS_P2P_MARKER 'P2P_RESULT|P2P_CLOUD_NEGOTIATION' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_ICE_MARKER 'P2_ICE_CONNECTIVITY' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_PSEUDOTCP_MARKER 'P2_PSEUDOTCP_OPEN' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_ECHO_MARKER 'P2_VIP_ECHO_ACK' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_UAUT_OPEN_MARKER 'P2_VIP_UAUT_OPEN' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_UAUT_AUTH_MARKER 'UAUT.*(AUTH|ACCESS)|VIP_UAUT_ACCESS' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_UCFG_MARKER 'UCFG|CONFIGURATION' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_CTPP_SYMBOL 'CTPP' "$WRAPPER"
    marker_bool_source WRAPPER_HAS_DOOR_ACTUATOR_SYMBOL 'OPEN_DOOR|open_door|create_door_message' "$WRAPPER"
    echo "WRAPPER_LINES_EMITTED=false"
} > "$EVIDENCE_DIR/wrapper_markers.txt"

{
    echo "=== HOLDER SOURCE BACKUPS ==="
    count=0
    baseline_candidates=0
    shopt -s nullglob
    for path in "$HOLDER_ROOT"/comelit_ice_offer_holder.c.bak.*; do
        count=$((count + 1))
        base="$(basename "$path")"
        sha="$(sha256sum "$path" | awk '{print $1}')"
        has_open=false; has_auth=false; has_ucfg=false; has_actuator=false
        grep -Eq 'P2_VIP_UAUT_OPEN|VIP_UAUT_OPEN_RESPONSE' "$path" && has_open=true || true
        grep -Eq 'UAUT.*(AUTH|ACCESS)|VIP_UAUT_ACCESS|response-code' "$path" && has_auth=true || true
        grep -Eq 'UCFG|CONFIGURATION|config-data' "$path" && has_ucfg=true || true
        grep -Eq 'OPEN_DOOR|open_door|create_door_message|CTPP' "$path" && has_actuator=true || true
        [[ "$has_open" == true && "$has_auth" == false && "$has_ucfg" == false && "$has_actuator" == false ]] && baseline_candidates=$((baseline_candidates + 1))
        echo "SOURCE_BACKUP name=$base sha256=$sha uaut_open=$has_open uaut_auth=$has_auth ucfg=$has_ucfg actuator_symbol=$has_actuator"
    done
    echo "SOURCE_BACKUP_COUNT=$count"
    echo "UAUT_OPEN_ONLY_BASELINE_CANDIDATE_COUNT=$baseline_candidates"

    bcount=0
    for path in "$HOLDER_ROOT"/comelit_ice_offer_holder.bak.*; do
        bcount=$((bcount + 1))
        echo "BINARY_BACKUP name=$(basename "$path") sha256=$(sha256sum "$path" | awk '{print $1}') bytes=$(stat -c '%s' "$path")"
    done
    echo "BINARY_BACKUP_COUNT=$bcount"
    echo "BACKUP_CONTENT_EMITTED=false"
} > "$EVIDENCE_DIR/backups.txt"

{
    echo "=== TOOLCHAIN / LINKAGE METADATA ==="
    command -v cc >/dev/null 2>&1 && echo "CC_PRESENT=true" || echo "CC_PRESENT=false"
    command -v pkg-config >/dev/null 2>&1 && echo "PKG_CONFIG_PRESENT=true" || echo "PKG_CONFIG_PRESENT=false"
    if [[ -f "$BINARY" ]]; then
        echo "BINARY_FILE_TYPE=$(file -b "$BINARY" | sed 's/[[:space:]]\+/ /g')"
        ldd "$BINARY" 2>/dev/null | awk '{print $1}' | grep -E '^(libnice|libglib|libgio|libgobject|libc|libm|libpthread|linux-vdso)' | sort -u | sed 's/^/LINKED_LIBRARY_NAME=/' || true
    fi
    echo "TOOLCHAIN_COMMANDS_NETWORKED=false"
} > "$EVIDENCE_DIR/toolchain.txt"

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "P12_P2P_FORENSIC_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
    echo "P12_P2P_FORENSIC_SAFETY_SCAN=FAIL"
    exit 1
fi

cat >> "$EVIDENCE_DIR/MANIFEST.txt" <<'EOF'
P12_P2P_FORENSIC_SECRET_SCAN=PASS
P12_P2P_FORENSIC_SAFETY_SCAN=PASS
P12_P2P_FORENSIC_COLLECTION=PASS
EOF

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "P12_P2P_EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect P12 P2P holder forensic ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "P12_P2P_EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "P12_P2P_EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "P12_P2P_EVIDENCE_PATH=$EVIDENCE_REL"
echo "PUBLIC_SAFE_EVIDENCE=PASS"
echo "SOURCE_EXECUTED=false"
echo "BINARY_EXECUTED=false"
echo "WRAPPER_EXECUTED=false"
echo "SECRETS_CONTENT_READ=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
echo "P12_P2P_FORENSIC_COLLECTION=PASS"
