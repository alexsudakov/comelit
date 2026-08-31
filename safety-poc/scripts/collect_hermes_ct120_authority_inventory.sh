#!/usr/bin/env bash
# Read-only inventory of the Hermes -> CT120 command authorization boundary.
#
# This collector deliberately performs no git mutation, no service reload,
# no permission/ownership changes, no network probe, and no Comelit transport.
# It emits only bounded authorization metadata; SSH key material is never printed.
set -Eeuo pipefail
umask 077

REPO=/root/comelit-git
RESTRICTED_USER=hermes-comelit

printf '%s\n' \
  'HERMES_CT120_AUTHORITY_INVENTORY_START=true' \
  'NETWORK_ACTION_PERFORMED=false' \
  'NETWORK_DOOR_ACTION_PERFORMED=false' \
  'PHYSICAL_DOOR_ACTION=false' \
  'SEND_ARMED_REACHED=false' \
  'P13_ACTUATOR_COMMAND_ATTEMPTED=false' \
  'P13_PHYSICAL_EFFECT_ASSERTED=false' \
  'RUNTIME_AUTHORITY_CHANGED=false'

if [[ "$EUID" -ne 0 ]]; then
  echo 'AUTHORITY_INVENTORY_REQUIRES_ROOT=true'
  exit 1
fi

echo 'AUTHORITY_INVENTORY_REQUIRES_ROOT=false'

safe_stat() {
  local path="$1"
  local label="$2"
  if [[ -e "$path" || -L "$path" ]]; then
    echo "${label}_PRESENT=true"
    echo "${label}_TYPE=$(stat -c '%F' "$path" 2>/dev/null || echo unknown)"
    echo "${label}_OWNER=$(stat -c '%U:%G' "$path" 2>/dev/null || echo unknown)"
    echo "${label}_MODE=$(stat -c '%a' "$path" 2>/dev/null || echo unknown)"
    if [[ -f "$path" ]]; then
      echo "${label}_SHA256=$(sha256sum "$path" | awk '{print $1}')"
    fi
  else
    echo "${label}_PRESENT=false"
  fi
}

# Exact repository identity, without changing it.
echo '=== REPOSITORY ==='
if [[ -d "$REPO/.git" ]]; then
  echo 'CT120_REPO_PRESENT=true'
  echo "CT120_REPO_BRANCH=$(git -C "$REPO" branch --show-current 2>/dev/null || echo unknown)"
  echo "CT120_REPO_HEAD=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "CT120_REPO_TREE=$(git -C "$REPO" rev-parse 'HEAD^{tree}' 2>/dev/null || echo unknown)"
  if [[ -z "$(git -C "$REPO" status --porcelain 2>/dev/null || printf 'unknown')" ]]; then
    echo 'CT120_REPO_WORKTREE_CLEAN=true'
  else
    echo 'CT120_REPO_WORKTREE_CLEAN=false'
  fi
  for rel in \
    safety-poc/scripts/p13_hermes_ct120_dispatch.sh \
    safety-poc/scripts/p13_hermes_observed_acceptance_preflight.sh \
    safety-poc/scripts/p13_hermes_observed_acceptance.sh \
    safety-poc/scripts/p13_hermes_one_shot.sh \
    safety-poc/scripts/p13_one_shot_physical_runner.sh; do
    if [[ -f "$REPO/$rel" ]]; then
      printf 'REPO_FILE_BLOB path=%s blob=%s\n' "$rel" "$(git -C "$REPO" hash-object "$REPO/$rel")"
    else
      printf 'REPO_FILE_MISSING path=%s\n' "$rel"
    fi
  done
else
  echo 'CT120_REPO_PRESENT=false'
fi

# Restricted account metadata contains no password/key material.
echo '=== RESTRICTED ACCOUNT ==='
if getent passwd "$RESTRICTED_USER" >/dev/null 2>&1; then
  echo 'RESTRICTED_OPERATOR_PRESENT=true'
  getent passwd "$RESTRICTED_USER" | awk -F: '{print "RESTRICTED_OPERATOR_UID="$3; print "RESTRICTED_OPERATOR_GID="$4; print "RESTRICTED_OPERATOR_HOME="$6; print "RESTRICTED_OPERATOR_SHELL="$7}'
else
  echo 'RESTRICTED_OPERATOR_PRESENT=false'
fi

# Relevant CT120 wrapper identities.
echo '=== WRAPPER IDENTITIES ==='
safe_stat /usr/local/sbin/comelit-smoke COMELIT_SMOKE
safe_stat /usr/local/sbin/comelit-p2p-readiness COMELIT_P2P_READINESS
safe_stat /usr/local/sbin/hermes-comelit-dispatch HERMES_COMELIT_DISPATCH
safe_stat /usr/local/sbin/hermes-comelit-dispatch.pre-door-poc-v1 HERMES_COMELIT_DISPATCH_PRE_DOOR

# Extract only command-like tokens and absolute wrapper targets from dispatcher
# source; do not print the source body or arbitrary literals.
echo '=== DISPATCHER SAFE SURFACE ==='
python3 - <<'PY'
from __future__ import annotations
from pathlib import Path
import re

for path in [Path('/usr/local/sbin/hermes-comelit-dispatch'), Path('/usr/local/sbin/hermes-comelit-dispatch.pre-door-poc-v1')]:
    if not path.is_file():
        continue
    print(f'DISPATCHER_SOURCE_PATH={path}')
    text = path.read_text(encoding='utf-8', errors='replace')
    tokens = sorted(set(re.findall(r"(?<![A-Za-z0-9_])([A-Za-z0-9][A-Za-z0-9._-]{2,})(?![A-Za-z0-9_])", text)))
    for token in tokens:
        low = token.lower()
        if 'comelit' in low or 'p13' in low or token in {'DENIED', 'readiness', 'smoke'}:
            print(f'DISPATCHER_COMMAND_TOKEN={token}')
    paths = sorted(set(re.findall(r"/(?:usr/local/sbin|opt/comelit[^\s\"']*|root/comelit-git)[A-Za-z0-9_./-]*", text)))
    for target in paths:
        print(f'DISPATCHER_ABSOLUTE_TARGET={target}')
PY

# sshd effective settings for this user. No connection is made.
echo '=== SSHD EFFECTIVE AUTHORIZATION ==='
if command -v sshd >/dev/null 2>&1 && getent passwd "$RESTRICTED_USER" >/dev/null 2>&1; then
  sshd -T -C "user=$RESTRICTED_USER,host=localhost,addr=127.0.0.1" 2>/dev/null \
    | awk '$1 ~ /^(authorizedkeysfile|forcecommand|permittty|permituserrc|allowtcpforwarding|allowagentforwarding|x11forwarding|passwordauthentication|pubkeyauthentication)$/ {print "SSHD_EFFECTIVE_" toupper($1) "=" substr($0, index($0,$2))}' || true
else
  echo 'SSHD_EFFECTIVE_QUERY_AVAILABLE=false'
fi

# Parse authorized_keys without printing key types, public key blobs, or comments.
# Only restrictions/options and the forced command value are emitted.
echo '=== AUTHORIZED KEYS FORCED COMMANDS ==='
python3 - <<'PY'
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import pwd
import re

user = 'hermes-comelit'
paths: list[Path] = []
try:
    home = Path(pwd.getpwnam(user).pw_dir)
    paths.append(home / '.ssh' / 'authorized_keys')
except KeyError:
    pass
paths.extend([Path('/etc/ssh/authorized_keys') / user, Path('/root/.ssh/authorized_keys')])
seen: set[Path] = set()
for path in paths:
    if path in seen or not path.is_file():
        continue
    seen.add(path)
    print(f'AUTHORIZED_KEYS_PATH={path}')
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError as exc:
        print(f'AUTHORIZED_KEYS_READ_ERROR={type(exc).__name__}')
        continue
    active = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        active += 1
        digest = hashlib.sha256(line.encode()).hexdigest()
        m = re.search(r'(?:^|,)command="((?:[^"\\]|\\.)*)"', line)
        print(f'AUTHORIZED_KEY_LINE_SHA256={digest}')
        print(f'AUTHORIZED_KEY_HAS_FORCED_COMMAND={str(m is not None).lower()}')
        if m:
            command = m.group(1).replace('\\"', '"')
            print(f'AUTHORIZED_KEY_FORCED_COMMAND={command}')
        restrictions = []
        for option in ('restrict','no-port-forwarding','no-agent-forwarding','no-X11-forwarding','no-pty','no-user-rc'):
            if re.search(r'(?:^|,)' + re.escape(option) + r'(?:,|\s|$)', line):
                restrictions.append(option)
        print('AUTHORIZED_KEY_RESTRICTIONS=' + (','.join(restrictions) if restrictions else 'none-detected'))
    print(f'AUTHORIZED_KEYS_ACTIVE_LINE_COUNT={active}')
PY

# Relevant sudoers entries only. Sudoers is read, never edited.
echo '=== SUDO AUTHORIZATION ==='
python3 - <<'PY'
from pathlib import Path
import re

patterns = ('hermes-comelit','comelit-smoke','comelit-p2p-readiness','hermes-comelit-dispatch','p13_hermes')
paths = [Path('/etc/sudoers')]
sudoers_d = Path('/etc/sudoers.d')
if sudoers_d.is_dir():
    paths += sorted(p for p in sudoers_d.iterdir() if p.is_file())
for path in paths:
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        continue
    matched = []
    for idx, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if any(pat in line for pat in patterns):
            matched.append((idx, line))
    if matched:
        print(f'SUDOERS_RELEVANT_PATH={path}')
        for idx, line in matched:
            print(f'SUDOERS_RELEVANT_LINE={idx}:{line}')
PY

if command -v sudo >/dev/null 2>&1 && getent passwd "$RESTRICTED_USER" >/dev/null 2>&1; then
  sudo -n -l -U "$RESTRICTED_USER" 2>&1 \
    | grep -E '(^User |may run|NOPASSWD:|/usr/local/sbin/|/root/comelit|hermes-comelit|comelit-)' \
    | sed -E 's/[[:space:]]+/ /g' || true
fi

# Systemd units may own a broker. Emit unit names and hashes only, not secrets/env.
echo '=== SYSTEMD BROKER CANDIDATES ==='
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-unit-files --no-legend --no-pager 2>/dev/null \
    | awk 'tolower($1) ~ /(comelit|hermes)/ {print "SYSTEMD_CANDIDATE_UNIT="$1" state="$2}' || true
fi

printf '%s\n' \
  'SSH_KEY_MATERIAL_EMITTED=false' \
  'CREDENTIAL_CONTENT_EMITTED=false' \
  'GIT_MUTATION_PERFORMED=false' \
  'SERVICE_MUTATION_PERFORMED=false' \
  'PERMISSION_MUTATION_PERFORMED=false' \
  'NETWORK_ACTION_PERFORMED=false' \
  'NETWORK_DOOR_ACTION_PERFORMED=false' \
  'PHYSICAL_DOOR_ACTION=false' \
  'SEND_ARMED_REACHED=false' \
  'P13_ACTUATOR_COMMAND_ATTEMPTED=false' \
  'P13_PHYSICAL_EFFECT_ASSERTED=false' \
  'RUNTIME_AUTHORITY_CHANGED=false' \
  'HERMES_CT120_AUTHORITY_INVENTORY_COMPLETE=true'
