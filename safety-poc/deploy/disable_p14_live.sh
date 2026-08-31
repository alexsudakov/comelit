#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ENV_FILE=/root/.config/comelit/p14-ha-bridge.env
DROPIN=/etc/systemd/system/comelit-p14-ha-bridge.service.d/firewall.conf
FW_UNIT=comelit-p14-firewall.service
FW_DEST=/usr/local/sbin/comelit-p14-firewall

[[ "${EUID}" -eq 0 ]] || { echo 'P14_DISABLE_REQUIRES_ROOT=true'; exit 1; }
[[ -f "$ENV_FILE" ]]
python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text(encoding="utf-8").splitlines()
updates={"COMELIT_P14_BIND_HOST":"127.0.0.1","COMELIT_P14_LIVE_ENABLED":"false"}
seen={key:0 for key in updates}; out=[]
for line in lines:
    if "=" in line:
        key,_=line.split("=",1)
        if key in updates:
            seen[key]+=1; line=f"{key}={updates[key]}"
    out.append(line)
if any(v != 1 for v in seen.values()): raise SystemExit("P14_ENV_KEY_CARDINALITY=FAIL")
tmp=p.with_suffix(p.suffix+".tmp"); tmp.write_text("\n".join(out)+"\n",encoding="utf-8"); tmp.chmod(0o600); tmp.replace(p)
PY
chown root:root "$ENV_FILE"
rm -f "$DROPIN"
systemctl daemon-reload
systemctl restart comelit-p14-ha-bridge.service
systemctl disable --now "$FW_UNIT" >/dev/null 2>&1 || true
[[ ! -x "$FW_DEST" ]] || "$FW_DEST" stop >/dev/null 2>&1 || true
HEALTH="$(curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18014/healthz)"
python3 - "$HEALTH" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); assert obj.get("ok") is True; assert obj.get("live_enabled") is False
PY
echo 'P14_DISABLE=PASS'
echo 'P14_BRIDGE_BIND=127.0.0.1:18014'
echo 'P14_BRIDGE_LIVE_ENABLED=false'
echo 'P14_OPEN_DOOR_REQUEST_SENT=false'
echo 'P14_RUNNER_INVOCATION_ATTEMPTED=false'
echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
