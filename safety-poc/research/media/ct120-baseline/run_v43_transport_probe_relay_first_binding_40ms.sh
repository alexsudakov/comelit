#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BASE="$HERE/run_v43_transport_probe_selected_pair_start.sh"
TMP=/root/comelit-v43-relay-first-binding-wrapper
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

python3 - "$BASE" "$PATCHED" "$HERE" <<'PY'
from pathlib import Path
import sys

src_path = Path(sys.argv[1])
dst_path = Path(sys.argv[2])
source_here = sys.argv[3]
src = src_path.read_text(encoding="utf-8")

required = (
    'PSEUDOTCP_START_AT_SELECTED_PAIR=true',
    '"new-selected-pair"',
    'new_selected_pair_cb',
    'SOURCE_DOOR_ACTION=ABSENT',
    'BINARY_DOOR_ACTION=ABSENT',
    'MEDIA_ACTION_SENT=false',
    'DOOR_ACTION_SENT=false',
)
for marker in required:
    if marker not in src:
        raise SystemExit(f'BASE_CONTRACT=FAIL missing={marker}')
print('BASE_CONTRACT=PASS')

old_here = 'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
new_here = f'HERE="{source_here}"\n'
if src.count(old_here) != 1:
    raise SystemExit(f'HERE_PATCH=FAIL count={src.count(old_here)}')
src = src.replace(old_here, new_here, 1)
print('HERE_PATCH=PASS')

# Replace the selected-pair callback with a capture-derived transition:
# first inbound peer Binding Request, then a 40 ms one-shot delay before
# initiating PseudoTCP. The successful capture showed local CONNECT 40.683 ms
# after the first nomination success and 41.092 ms after the first peer
# USE-CANDIDATE request.
start = src.find('static void\nnew_selected_pair_cb(')
end = src.find('\n\n\nstatic void\ncomponent_state_changed_cb(', start)
if start < 0 or end < 0:
    raise SystemExit('CALLBACK_PATCH=FAIL')

callback = r'''static gboolean
pseudotcp_start_after_first_binding_cb(gpointer data)
{
    (void)data;

    if (pseudotcp_started)
        return G_SOURCE_REMOVE;

    printf("PSEUDOTCP_START_AFTER_FIRST_BINDING_MS=40\n");

    if (!start_pseudotcp()) {
        fprintf(stderr, "PSEUDOTCP_START_AFTER_FIRST_BINDING=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
    }

    fflush(stdout);
    return G_SOURCE_REMOVE;
}


static void
initial_binding_request_received_cb(
    NiceAgent *nice_agent,
    guint sid,
    gpointer data)
{
    static gboolean scheduled = FALSE;

    (void)nice_agent;
    (void)data;

    if (sid != stream_id)
        return;

    printf("ICE_INITIAL_BINDING_REQUEST_RECEIVED=true\n");

    if (!pseudotcp_started && !scheduled) {
        scheduled = TRUE;
        printf("PSEUDOTCP_START_SCHEDULED_MS=40\n");
        g_timeout_add(
            40,
            pseudotcp_start_after_first_binding_cb,
            NULL
        );
    }

    fflush(stdout);
}
'''
src = src[:start] + callback + src[end:]
print('CALLBACK_PATCH=PASS')

old_signal = '''    g_signal_connect(\n        agent,\n        "new-selected-pair",\n        G_CALLBACK(\n            new_selected_pair_cb\n        ),\n        NULL\n    );\n'''
new_signal = '''    g_signal_connect(\n        agent,\n        "initial-binding-request-received",\n        G_CALLBACK(\n            initial_binding_request_received_cb\n        ),\n        NULL\n    );\n'''
if src.count(old_signal) != 1:
    raise SystemExit(f'SIGNAL_PATCH=FAIL count={src.count(old_signal)}')
src = src.replace(old_signal, new_signal, 1)
print('SIGNAL_PATCH=PASS')

# Keep the original passive v4_3 transport logic and only change the probe
# bookkeeping labels so the result is unambiguous.
src = src.replace(
    "echo '=== BUILD SELECTED-PAIR-START TRANSPORT PROBE ==='",
    "echo '=== BUILD FIRST-BINDING-40MS TRANSPORT PROBE ==='",
)
src = src.replace(
    "SELECTED_PAIR_TRANSPORT_READY=PASS",
    "FIRST_BINDING_TRANSPORT_READY=PASS",
)
src = src.replace(
    "SELECTED_PAIR_TRANSPORT_READY=FAIL",
    "FIRST_BINDING_TRANSPORT_READY=FAIL",
)
src = src.replace(
    "SELECTED_PAIR_TRANSPORT_PROBE=PASS",
    "FIRST_BINDING_TRANSPORT_PROBE=PASS",
)

# Update the log selection to include the first-binding transition markers.
old_grep = "ICE_NEW_SELECTED_PAIR|SELECTED_PAIR|PSEUDOTCP_RX_BEFORE_START|PSEUDOTCP_START_AT_SELECTED_PAIR|PSEUDOTCP_CONVERSATION"
new_grep = "ICE_INITIAL_BINDING_REQUEST_RECEIVED|SELECTED_PAIR|PSEUDOTCP_RX_BEFORE_START|PSEUDOTCP_START_SCHEDULED_MS|PSEUDOTCP_START_AFTER_FIRST_BINDING_MS|PSEUDOTCP_CONVERSATION"
if old_grep not in src:
    raise SystemExit('LOG_FILTER_PATCH=FAIL')
src = src.replace(old_grep, new_grep, 1)
print('LOG_FILTER_PATCH=PASS')

# Send the cloud result to a private full-SDP file first; the helper consumes
# a relay-only copy below.
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

dst_path.write_text(src, encoding='utf-8')
PY

chmod 700 "$PATCHED"

echo 'RELAY_FIRST_BINDING_40MS_WRAPPER=PASS'
echo 'CAPTURE_DERIVED_DELAY_MS=40'
echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_ACTION_SENT=false'

exec bash "$PATCHED"
