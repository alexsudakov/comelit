#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ENV_FILE=/root/.config/comelit/p14-ha-bridge.env
SERVICE=comelit-p14-ha-bridge.service
PORT=18014
BIND_HOST=""

usage() {
    echo "usage: $0 --bind-host <private-ipv4>" >&2
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bind-host) BIND_HOST="$2"; shift 2 ;;
        *) usage ;;
    esac
done

[[ "${EUID}" -eq 0 ]] || { echo "P14_PRIVATE_BIND_REQUIRES_ROOT=true"; exit 1; }
[[ -n "$BIND_HOST" ]] || usage
[[ -f "$ENV_FILE" ]] || { echo "P14_ENV_PRESENT=false"; exit 1; }
[[ "$(stat -c '%u' "$ENV_FILE")" == "0" ]] || { echo "P14_ENV_OWNER=FAIL"; exit 1; }
chmod 0600 "$ENV_FILE"

# This transition is deliberately incapable of enabling actuation. Refuse to
# touch any environment that is not already exactly disabled.
grep -qx 'COMELIT_P14_LIVE_ENABLED=false' "$ENV_FILE" || {
    echo "P14_PRIVATE_BIND_ENV_NOT_DISABLED=true"
    exit 1
}

python3 - "$BIND_HOST" <<'PY'
import ipaddress, sys
addr = ipaddress.ip_address(sys.argv[1])
if addr.version != 4:
    raise SystemExit("P14_PRIVATE_BIND_IPV4_REQUIRED=true")
if not addr.is_private or addr.is_loopback or addr.is_unspecified or addr.is_multicast:
    raise SystemExit("P14_PRIVATE_BIND_ADDRESS_REJECTED=true")
PY

# Rewrite exactly the bind-host key while preserving every secret/target value
# byte-for-byte and preserving LIVE_ENABLED=false. Refuse duplicate/missing keys.
python3 - "$ENV_FILE" "$BIND_HOST" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
bind_host = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
keys = {}
for idx, line in enumerate(lines):
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, _ = line.split("=", 1)
    keys.setdefault(key, []).append(idx)

for required in ("COMELIT_P14_BIND_HOST", "COMELIT_P14_LIVE_ENABLED"):
    if len(keys.get(required, [])) != 1:
        raise SystemExit(f"P14_ENV_KEY_CARDINALITY_FAIL={required}")

live_idx = keys["COMELIT_P14_LIVE_ENABLED"][0]
if lines[live_idx] != "COMELIT_P14_LIVE_ENABLED=false":
    raise SystemExit("P14_PRIVATE_BIND_ENV_NOT_DISABLED=true")

bind_idx = keys["COMELIT_P14_BIND_HOST"][0]
lines[bind_idx] = f"COMELIT_P14_BIND_HOST={bind_host}"

tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
tmp.chmod(0o600)
tmp.replace(path)
PY

systemctl restart "$SERVICE"

# The server is now bound to the selected private address, not necessarily to
# loopback. This is a GET health probe only; no actuation endpoint is called.
HEALTH="$(curl --fail --silent --show-error --max-time 3 "http://$BIND_HOST:$PORT/healthz")"
python3 - "$HEALTH" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
assert obj.get("ok") is True
assert obj.get("protocol_version") == 1
assert obj.get("live_enabled") is False
PY

echo "P14_PRIVATE_BIND_TRANSITION=PASS"
echo "P14_BRIDGE_BIND_HOST=$BIND_HOST"
echo "P14_BRIDGE_LIVE_ENABLED=false"
echo "P14_SHARED_SECRET_EMITTED=false"
echo "P14_TARGET_FINGERPRINT_EMITTED=false"
echo "P14_OPEN_DOOR_REQUEST_SENT=false"
echo "P14_RUNNER_INVOCATION_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
