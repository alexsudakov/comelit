#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"

LEGACY_ROOT=/root/comelit-poc
LEGACY_SOURCE="$LEGACY_ROOT/comelit_client.py"
CANONICAL_ROOT=/root/comelit-vip-poc
CANONICAL_PACKAGE="$CANONICAL_ROOT/comelit_vip"
ARTIFACT_ROOT=/root/comelit-artifacts
RUNTIME_ROOT=/opt/comelit-door-safety-poc
CURRENT_LINK="$RUNTIME_ROOT/current"

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
ORIGINAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"

if [[ -z "$ORIGINAL_BRANCH" ]]; then
    echo "COLLECTOR_REQUIRES_NAMED_BRANCH=true"
    exit 1
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "COLLECTOR_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/ct120-${STAMP}"
EVIDENCE_REL="evidence/ct120/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup_on_error() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "COLLECTOR_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup_on_error EXIT

write_manifest() {
    {
        echo "EVIDENCE_SCHEMA=1"
        echo "COLLECTED_AT_UTC=$STAMP"
        echo "SOURCE_BRANCH=$ORIGINAL_BRANCH"
        echo "SOURCE_HEAD=$ORIGINAL_HEAD"
        echo "COLLECTOR_BRANCH=$EVIDENCE_BRANCH"
        echo "PUBLIC_SAFE=true"
        echo "SOURCE_EXECUTED=false"
        echo "SECRETS_CONTENT_READ=false"
        echo "CREDENTIAL_VALUES_COLLECTED=false"
        echo "REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false"
        echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
        echo "PHYSICAL_DOOR_ACTION=false"
    } > "$EVIDENCE_DIR/MANIFEST.txt"
}

write_toolchain() {
    {
        echo "=== TOOLCHAIN ==="
        uname -srmo 2>/dev/null || true
        python3 --version 2>&1 || true
        git --version 2>&1 || true
        if command -v dpkg-query >/dev/null 2>&1; then
            dpkg-query -W -f='${Package}=${Version}\n' python3 git sqlite3 libglib2.0-0 libnice10 2>/dev/null || true
        fi
        echo "CPU_COUNT=$(nproc 2>/dev/null || echo unknown)"
        if [[ -r /proc/meminfo ]]; then
            awk '/^MemTotal:/ {print "MEM_TOTAL_KB="$2}' /proc/meminfo
        fi
    } > "$EVIDENCE_DIR/toolchain.txt"
}

write_git_state() {
    {
        echo "=== GIT STATE ==="
        echo "REPO_ROOT=$REPO_ROOT"
        echo "ORIGINAL_BRANCH=$ORIGINAL_BRANCH"
        echo "ORIGINAL_HEAD=$ORIGINAL_HEAD"
        origin="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
        if [[ "$origin" == *github.com* ]]; then
            repo_path="${origin##*github.com}"
            repo_path="${repo_path#[:/]}"
            echo "REMOTE_HOST=github.com"
            echo "REMOTE_REPO_PATH=$repo_path"
        elif [[ -n "$origin" ]]; then
            echo "REMOTE_HOST=non-github"
            echo "REMOTE_REPO_PATH=redacted"
        else
            echo "REMOTE_HOST=missing"
        fi
        echo "WORKTREE_WAS_CLEAN=true"
    } > "$EVIDENCE_DIR/git_state.txt"
}

write_runtime_release() {
    {
        echo "=== RUNTIME RELEASE ==="
        if [[ -L "$CURRENT_LINK" || -e "$CURRENT_LINK" ]]; then
            current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
            echo "CURRENT_PRESENT=true"
            echo "CURRENT_TARGET=$current"
            if [[ -n "$current" && -f "$current/MANIFEST.sha256" ]]; then
                echo "MANIFEST_SHA256_FILE=$(sha256sum "$current/MANIFEST.sha256" | awk '{print $1}')"
            fi
            if [[ -n "$current" && -f "$current/pyproject.toml" ]]; then
                awk -F'"' '/^version = / {print "PYPROJECT_VERSION="$2; exit}' "$current/pyproject.toml" || true
            fi
        else
            echo "CURRENT_PRESENT=false"
        fi
        echo "RUNTIME_TREE_CONTENT_READ=false_except_version_metadata"
    } > "$EVIDENCE_DIR/runtime_release.txt"
}

write_source_hashes() {
    {
        echo "=== SOURCE HASHES ==="
        for root in "$LEGACY_ROOT" "$CANONICAL_PACKAGE"; do
            if [[ ! -d "$root" ]]; then
                echo "MISSING_ROOT=$root"
                continue
            fi
            while IFS= read -r -d '' path; do
                rel="${path#$root/}"
                printf '%s  %s/%s\n' "$(sha256sum "$path" | awk '{print $1}')" "$root" "$rel"
            done < <(find "$root" -type f -name '*.py' -print0 | sort -z)
        done
        echo "SOURCE_CONTENT_EMITTED=false"
    } > "$EVIDENCE_DIR/source_hashes.txt"
}

write_artifact_metadata() {
    {
        echo "=== ARTIFACT METADATA ==="
        if [[ -d "$ARTIFACT_ROOT" ]]; then
            while IFS= read -r -d '' path; do
                rel="${path#$ARTIFACT_ROOT/}"
                case "$rel" in
                    *.pcap|*.pcapng|*.apk)
                        size="$(stat -c '%s' "$path" 2>/dev/null || echo unknown)"
                        echo "ARTIFACT path=$rel bytes=$size"
                        ;;
                esac
            done < <(find "$ARTIFACT_ROOT" -type f -print0 | sort -z)
        else
            echo "ARTIFACT_ROOT_PRESENT=false"
        fi
        echo "ARTIFACT_CONTENT_READ=false"
        echo "CAPTURE_PACKET_CONTENT_READ=false"
    } > "$EVIDENCE_DIR/artifact_metadata.txt"
}

write_operator_boundary() {
    {
        echo "=== OPERATOR BOUNDARY ==="
        for path in /usr/local/sbin/comelit-smoke /usr/local/sbin/comelit-p2p-readiness /usr/local/sbin/hermes-comelit-dispatch /usr/local/sbin/hermes-comelit-dispatch.pre-door-poc-v1; do
            if [[ -f "$path" ]]; then
                echo "FILE=$path"
                echo "MODE=$(stat -c '%a' "$path")"
                echo "SHA256=$(sha256sum "$path" | awk '{print $1}')"
            else
                echo "MISSING=$path"
            fi
        done
        if getent passwd hermes-comelit >/dev/null 2>&1; then
            echo "RESTRICTED_OPERATOR_PRESENT=true"
            echo "RESTRICTED_OPERATOR_UID=$(id -u hermes-comelit)"
        else
            echo "RESTRICTED_OPERATOR_PRESENT=false"
        fi
        if [[ -d /root/.config/comelit ]]; then
            echo "COMELIT_SECRET_DIRECTORY_PRESENT=true"
            echo "COMELIT_SECRET_DIRECTORY_MODE=$(stat -c '%a' /root/.config/comelit 2>/dev/null || echo unknown)"
        else
            echo "COMELIT_SECRET_DIRECTORY_PRESENT=false"
        fi
        echo "SECRET_DIRECTORY_LISTED=false"
        echo "SECRETS_CONTENT_READ=false"
        echo "GIT_CREDENTIAL_FILE_READ=false"
    } > "$EVIDENCE_DIR/operator_boundary.txt"
}

write_passive_network_shape() {
    python3 - "$EVIDENCE_DIR/passive_network_shape.txt" <<'PY'
from __future__ import annotations
from pathlib import Path
import subprocess
import sys

out = Path(sys.argv[1])
lines = ["=== PASSIVE NETWORK SHAPE ==="]
net = Path("/sys/class/net")
if net.is_dir():
    for interface in sorted(net.iterdir(), key=lambda p: p.name):
        try:
            state = (interface / "operstate").read_text().strip()
        except OSError:
            state = "unknown"
        lines.append(f"INTERFACE name={interface.name} state={state}")

def endpoint_port(value: str) -> str:
    if value in {"*", "*:*"}:
        return "*"
    if value.startswith("[") and "]:" in value:
        return value.rsplit(":", 1)[-1]
    return value.rsplit(":", 1)[-1] if ":" in value else "unknown"

for args, proto in ((["ss", "-Htan"], "tcp"), (["ss", "-Huan"], "udp")):
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        lines.append("SS_PRESENT=false")
        break
    for raw in proc.stdout.splitlines():
        parts = raw.split()
        if len(parts) < 5:
            continue
        state = parts[0] if proto == "tcp" else "UNCONN"
        local = parts[-2]
        peer = parts[-1]
        lines.append(f"SOCKET proto={proto} state={state} local_port={endpoint_port(local)} peer_port={endpoint_port(peer)}")

try:
    proc = subprocess.run(["ip", "-4", "route", "show", "default"], check=False, capture_output=True, text=True)
    count = sum(1 for line in proc.stdout.splitlines() if line.strip())
    lines.append(f"IPV4_DEFAULT_ROUTE_COUNT={count}")
except FileNotFoundError:
    lines.append("IP_COMMAND_PRESENT=false")

lines += [
    "IP_ADDRESSES_EMITTED=false",
    "MAC_ADDRESSES_EMITTED=false",
    "ACTIVE_NETWORK_PROBES=false",
    "PASSIVE_NETWORK_SHAPE=PASS",
]
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

write_python_packages() {
    {
        echo "=== PYTHON PACKAGES ==="
        python3 -m pip list --format=freeze 2>/dev/null || true
    } > "$EVIDENCE_DIR/python_packages.txt"
}

write_source_topology() {
    paths=()
    for path in "$LEGACY_SOURCE" "$CANONICAL_PACKAGE/application_session.py" "$CANONICAL_PACKAGE/channel_session.py" "$CANONICAL_PACKAGE/control_codec.py" "$CANONICAL_PACKAGE/fixture_transport.py" "$CANONICAL_PACKAGE/transport.py" "$CANONICAL_PACKAGE/vip_codec.py" "$CANONICAL_PACKAGE/vip_session.py"; do
        [[ -f "$path" ]] && paths+=("$path")
    done
    python3 "$SCRIPT_DIR/safe_source_topology.py" "${paths[@]}" > "$EVIDENCE_DIR/source_topology.txt"
}

write_body_inventory() {
    python3 "$SCRIPT_DIR/legacy_body_shape_inventory.py" > "$EVIDENCE_DIR/legacy_body_shape_inventory.txt"
}

write_symbol_locations() {
    python3 - "$LEGACY_ROOT" "$CANONICAL_ROOT" "$EVIDENCE_DIR/symbol_locations.txt" <<'PY'
from __future__ import annotations
import ast
from pathlib import Path
import sys

roots = [Path(sys.argv[1]), Path(sys.argv[2])]
out = Path(sys.argv[3])
wanted = {
    "open_door", "_open_door_init", "create_door_message", "_create_binary_packet_from_buffers",
    "_write_packet", "_read_response", "open_channel", "close_channel", "send_frame", "recv_event",
    "authenticate", "connect",
}
rows = ["=== SYMBOL LOCATIONS ==="]
for root in roots:
    if not root.is_dir():
        continue
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            rows.append(f"PARSE_ERROR path={path} type={type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
                rows.append(f"SYMBOL name={node.name} kind={'async' if isinstance(node, ast.AsyncFunctionDef) else 'sync'} path={path} line={node.lineno}")
rows += ["SOURCE_EXECUTED=false", "SOURCE_LINES_EMITTED=false", "LITERAL_VALUES_EMITTED=false"]
out.write_text("\n".join(rows) + "\n", encoding="utf-8")
PY
}

public_safety_scan() {
    if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
        echo "PUBLIC_EVIDENCE_SECRET_SCAN=FAIL"
        exit 1
    fi
    echo "PUBLIC_EVIDENCE_SECRET_SCAN=PASS" >> "$EVIDENCE_DIR/MANIFEST.txt"

    if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|REAL_DOOR_PAYLOAD_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
        echo "PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=FAIL"
        exit 1
    fi
    echo "PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=PASS" >> "$EVIDENCE_DIR/MANIFEST.txt"
}

write_manifest
write_toolchain
write_git_state
write_runtime_release
write_source_hashes
write_artifact_metadata
write_operator_boundary
write_passive_network_shape
write_python_packages
write_source_topology
write_body_inventory
write_symbol_locations
public_safety_scan

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check

if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect public-safe CT120 plan inventory ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "EVIDENCE_PATH=$EVIDENCE_REL"
echo "PUBLIC_SAFE_EVIDENCE=PASS"
echo "SECRETS_CONTENT_READ=false"
echo "REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "PHYSICAL_DOOR_ACTION=false"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
echo "PLAN_EVIDENCE_COLLECTION=PASS"
