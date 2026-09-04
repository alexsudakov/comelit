#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BASE="$HERE/run_v43_transport_probe_selected_pair_start.sh"
TMP=/root/comelit-v43-relay-selected-pair-wrapper
PATCHED="$TMP/run.sh"

for cmd in python3 bash; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

[[ -f "$BASE" ]] || {
    echo 'SELECTED_PAIR_BASE=FAIL'
    exit 11
}

rm -rf "$TMP"
mkdir -m 700 "$TMP"

python3 - "$BASE" "$PATCHED" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")

required = (
    'PSEUDOTCP_START_AT_SELECTED_PAIR=true',
    'SOURCE_DOOR_ACTION=ABSENT',
    'BINARY_DOOR_ACTION=ABSENT',
    'MEDIA_ACTION_SENT=false',
    'DOOR_ACTION_SENT=false',
)
for marker in required:
    if marker not in src:
        raise SystemExit(f'BASE_CONTRACT=FAIL missing={marker}')
print('BASE_CONTRACT=PASS')

old = 'REMOTE="$RUN/remote.sdp"\n'
new = 'REMOTE="$RUN/remote.sdp"\nREMOTE_FULL="$OUT/remote.full.sdp"\n'
if src.count(old) != 1:
    raise SystemExit(f'REMOTE_VAR_PATCH=FAIL count={src.count(old)}')
src = src.replace(old, new, 1)
print('REMOTE_VAR_PATCH=PASS')

old = 'python3 "$CLOUD" "$COMELIT_OFFER" "$REMOTE" >"$CLOUD_LOG" 2>&1 || RC=$?'
new = 'python3 "$CLOUD" "$COMELIT_OFFER" "$REMOTE_FULL" >"$CLOUD_LOG" 2>&1 || RC=$?'
if src.count(old) != 1:
    raise SystemExit(f'CLOUD_TARGET_PATCH=FAIL count={src.count(old)}')
src = src.replace(old, new, 1)
print('CLOUD_TARGET_PATCH=PASS')

anchor = "echo 'CLOUD_GATE=PASS'\n\necho\necho '=== WAIT FOR PASSIVE LISTENER READY ==='"
insert = r'''echo 'CLOUD_GATE=PASS'

echo
echo '=== FILTER REMOTE SDP TO RELAY CANDIDATE ONLY ==='
python3 - "$REMOTE_FULL" "$REMOTE" <<'PYFILTER'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding='utf-8')
lines = [
    line.strip()
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if line.strip()
]
candidates = [line for line in lines if line.startswith('a=candidate:')]
relay = []
for line in candidates:
    parts = line.split()
    try:
        idx = parts.index('typ')
    except ValueError:
        continue
    if idx + 1 < len(parts) and parts[idx + 1].lower() == 'relay':
        relay.append(line)

if len(relay) != 1:
    raise SystemExit(
        f'RELAY_FILTER=FAIL relay_count={len(relay)} total_candidates={len(candidates)}'
    )

out = [line for line in lines if not line.startswith('a=candidate:')]
insert_at = next(
    (i for i, line in enumerate(out) if line.startswith('a=ice-role:')),
    len(out),
)
out.insert(insert_at, relay[0])

data = ('\r\n'.join(out) + '\r\n').encode('ascii')
tmp = dst.with_suffix('.tmp')
old_umask = os.umask(0o077)
try:
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)
finally:
    os.umask(old_umask)
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass

parts = relay[0].split()
typ_idx = parts.index('typ')
print('RELAY_FILTER=PASS')
print(f'REMOTE_CANDIDATES_ORIGINAL={len(candidates)}')
print('REMOTE_CANDIDATES_FILTERED=1')
print(f'REMOTE_RELAY_ADDRESS={parts[4]}')
print(f'REMOTE_RELAY_PORT={parts[5]}')
print(f'REMOTE_RELAY_TYPE={parts[typ_idx + 1]}')
PYFILTER

echo
echo '=== WAIT FOR PASSIVE LISTENER READY ===' '''

if src.count(anchor) != 1:
    raise SystemExit(f'RELAY_INSERT_PATCH=FAIL count={src.count(anchor)}')
src = src.replace(anchor, insert, 1)
print('RELAY_INSERT_PATCH=PASS')

Path(sys.argv[2]).write_text(src, encoding='utf-8')
PY

chmod 700 "$PATCHED"

echo 'RELAY_SELECTED_PAIR_WRAPPER=PASS'
echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_ACTION_SENT=false'

exec bash "$PATCHED"
