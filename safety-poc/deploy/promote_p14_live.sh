#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APPROVAL=I_APPROVE_P14_ENABLE_REUSABLE_DOOR_SERVICE
ENV_FILE=/root/.config/comelit/p14-ha-bridge.env
FW_ENV=/root/.config/comelit/p14-firewall.env
FW_DEST=/usr/local/sbin/comelit-p14-firewall
FW_UNIT=/etc/systemd/system/comelit-p14-firewall.service
BRIDGE_UNIT=/etc/systemd/system/comelit-p14-ha-bridge.service
BRIDGE_SERVICE=comelit-p14-ha-bridge.service
DROPIN_DIR=/etc/systemd/system/comelit-p14-ha-bridge.service.d
DROPIN="$DROPIN_DIR/firewall.conf"
CURRENT=/opt/comelit-door-safety-poc/p14/current
P13_READINESS=/usr/local/sbin/comelit-p13-hermes-dispatch
PORT=18014
HEALTH_READY_ATTEMPTS=20
HEALTH_PROBE_TIMEOUT_SECONDS=0.25
HEALTH_READY_INTERVAL_SECONDS=0.25
BIND_HOST=""
HA_IP=""
HEALTH=""

usage() {
    echo 'usage: promote_p14_live.sh --bind-host <ct120-private-ipv4> --ha-client-ip <ha-private-ipv4>' >&2
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bind-host)
            [[ $# -ge 2 ]] || usage
            BIND_HOST="$2"
            shift 2
            ;;
        --ha-client-ip)
            [[ $# -ge 2 ]] || usage
            HA_IP="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done

startup_diagnostics() {
    echo 'P14_LIVE_BRIDGE_STARTUP_DIAGNOSTICS_BEGIN=true' >&2
    systemctl status "$BRIDGE_SERVICE" --no-pager -l >&2 || true
    journalctl -u "$BRIDGE_SERVICE" --no-pager -n 100 -o short-iso-precise >&2 || true
    echo 'P14_LIVE_BRIDGE_STARTUP_DIAGNOSTICS_END=true' >&2
}

wait_for_live_health() {
    local attempt
    local health_url="http://$BIND_HOST:$PORT/healthz"

    HEALTH=""
    for ((attempt = 1; attempt <= HEALTH_READY_ATTEMPTS; attempt++)); do
        if ! systemctl is-active --quiet "$BRIDGE_SERVICE"; then
            echo "P14_LIVE_BRIDGE_SERVICE_INACTIVE_AT_ATTEMPT=$attempt" >&2
            startup_diagnostics
            return 1
        fi

        if HEALTH="$(curl --fail --silent --show-error \
            --max-time "$HEALTH_PROBE_TIMEOUT_SECONDS" "$health_url" 2>/dev/null)"; then
            if python3 - "$HEALTH" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
assert obj.get("ok") is True
assert obj.get("protocol_version") == 1
assert obj.get("live_enabled") is True
assert obj.get("runner_identity") == "pass"
PY
            then
                echo "P14_LIVE_BRIDGE_READINESS_ATTEMPTS=$attempt"
                return 0
            fi
            echo 'P14_LIVE_BRIDGE_HEALTH_CONTRACT_INVALID=true' >&2
            startup_diagnostics
            return 1
        fi

        sleep "$HEALTH_READY_INTERVAL_SECONDS"
    done

    echo "P14_LIVE_BRIDGE_READINESS_TIMEOUT_ATTEMPTS=$HEALTH_READY_ATTEMPTS" >&2
    startup_diagnostics
    return 1
}

[[ "${EUID}" -eq 0 ]] || {
    echo 'P14_LIVE_PROMOTION_REQUIRES_ROOT=true'
    exit 1
}
[[ "${P14_LIVE_ENABLE_APPROVAL:-}" == "$APPROVAL" ]] || {
    echo 'P14_LIVE_PROMOTION_APPROVAL=FAIL'
    exit 1
}
[[ -n "$BIND_HOST" && -n "$HA_IP" ]] || usage

[[ -L "$CURRENT" && -f "$CURRENT/RELEASE.env" && -f "$CURRENT/RELEASE_CONTENT.sha256" ]]
[[ -f "$ENV_FILE" && -f "$BRIDGE_UNIT" ]]
[[ "$(stat -c '%u:%a' "$ENV_FILE")" == '0:600' ]]
grep -Fxq 'COMELIT_P14_LIVE_ENABLED=false' "$ENV_FILE" || {
    echo 'P14_LIVE_PROMOTION_SOURCE_NOT_DISABLED=true'
    exit 1
}

python3 - "$BIND_HOST" "$HA_IP" <<'PY'
import ipaddress, sys
for name, value in (("bind", sys.argv[1]), ("ha", sys.argv[2])):
    addr = ipaddress.ip_address(value)
    if (
        addr.version != 4
        or not addr.is_private
        or addr.is_loopback
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_link_local
    ):
        raise SystemExit(f"P14_{name.upper()}_PRIVATE_IPV4=FAIL")
PY

ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$BIND_HOST" || {
    echo 'P14_BIND_HOST_NOT_ASSIGNED_TO_CT120=true'
    exit 1
}

(
    cd "$(readlink -f "$CURRENT")"
    sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
)

for marker in \
    'P14_HA_RESPONSE_REQUIRED=true' \
    'P14_STANDARD_BUTTON_PRESS_ALLOWED=false' \
    'P14_AUTO_RETRY_ALLOWED=false' \
    'P14_PHYSICAL_EFFECT_ASSERTED=false'; do
    grep -Fxq "$marker" "$CURRENT/RELEASE.env"
done

DISABLED_HEALTH="$(curl --fail --silent --show-error --max-time 3 \
    http://127.0.0.1:18014/healthz)"
python3 - "$DISABLED_HEALTH" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
assert obj.get("ok") is True
assert obj.get("protocol_version") == 1
assert obj.get("live_enabled") is False
PY
echo 'P14_LIVE_PROMOTION_DISABLED_HEALTH=PASS'

READY="$($P13_READINESS readiness)"
printf '%s\n' "$READY"
for marker in \
    'P13_PRODUCTION_RUNTIME_DISPATCH_IDENTITY=PASS' \
    'P13_PRODUCTION_RELEASE_ID=p13-415edb4525e4-50c0a916f73e-b6a10c68773a' \
    'P13_PRODUCTION_SOURCE_HEAD=0dace902d2cef1478cddea0f9d4cd36fcddb3837' \
    'P13_PRODUCTION_SOURCE_TREE=415edb4525e46601cd0ef1249fc0965927b1ac29' \
    'P13_PRODUCTION_RELEASE_CONTENT=PASS' \
    'P13_PRODUCTION_RUNTIME_ARTIFACT_IDENTITIES=PASS' \
    'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true' \
    'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false' \
    'P13_AUTO_RETRY_ALLOWED=false' \
    'P13_PHYSICAL_EFFECT_ASSERTED=false' \
    'SEND_ARMED_REACHED=false'; do
    grep -Fxq "$marker" <<<"$READY"
done

RUNNER="$(sed -n 's/^COMELIT_P14_RUNNER=//p' "$ENV_FILE")"
RUNNER_SHA="$(sed -n 's/^COMELIT_P14_RUNNER_SHA256=//p' "$ENV_FILE")"
[[ -f "$RUNNER" && "$RUNNER_SHA" =~ ^[0-9a-f]{64}$ ]]
[[ "$(stat -c '%u:%a' "$RUNNER")" == '0:700' ]]
[[ "$(sha256sum "$RUNNER" | awk '{print $1}')" == "$RUNNER_SHA" ]]

if pgrep -f -- '(^|/)comelit_p13_holder([[:space:]]|$)' >/dev/null \
    || pgrep -f -- '(^|/)comelit-p13-door-wrapper([[:space:]]|$)' >/dev/null \
    || pgrep -f -- 'p14_production_runner.sh.*--operation-id' >/dev/null; then
    echo 'P14_LIVE_PROMOTION_CONFLICTING_PROCESS=true'
    exit 1
fi

echo 'P14_LIVE_PROMOTION_PREFLIGHT=PASS'
echo 'P14_OPEN_DOOR_REQUEST_SENT=false'
echo 'P14_RUNNER_INVOCATION_ATTEMPTED=false'

ENV_BACKUP="$(mktemp /root/p14-live-env-backup.XXXXXX)"
cp -a "$ENV_FILE" "$ENV_BACKUP"

rollback() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        set +e
        cp -a "$ENV_BACKUP" "$ENV_FILE"
        rm -f "$DROPIN"
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl restart "$BRIDGE_SERVICE" >/dev/null 2>&1 || true
        systemctl disable --now comelit-p14-firewall.service >/dev/null 2>&1 || true
        "$FW_DEST" stop >/dev/null 2>&1 || true
        echo 'P14_LIVE_PROMOTION=ROLLBACK'
        set -e
    fi
    rm -f "$ENV_BACKUP"
    return "$rc"
}
trap rollback EXIT

# Firewall is installed and active before the bridge leaves loopback.
install -o root -g root -m 0700 "$CURRENT/repo/deploy/p14_firewall.sh" "$FW_DEST"
cat >"$FW_ENV.tmp" <<EOF
P14_HA_CLIENT_IP=$HA_IP
P14_BRIDGE_PORT=$PORT
EOF
chmod 600 "$FW_ENV.tmp"
chown root:root "$FW_ENV.tmp"
mv "$FW_ENV.tmp" "$FW_ENV"

cat >"$FW_UNIT.tmp" <<'EOF'
[Unit]
Description=Comelit P14 bridge source allowlist
Before=comelit-p14-ha-bridge.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/comelit-p14-firewall start
ExecStop=/usr/local/sbin/comelit-p14-firewall stop
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$FW_UNIT.tmp"
chown root:root "$FW_UNIT.tmp"
mv "$FW_UNIT.tmp" "$FW_UNIT"
systemctl daemon-reload
systemctl enable --now comelit-p14-firewall.service >/dev/null
systemctl is-active --quiet comelit-p14-firewall.service
nft list table inet comelit_p14 >/dev/null

install -d -o root -g root -m 0755 "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Unit]
Requires=comelit-p14-firewall.service
After=comelit-p14-firewall.service
EOF
chmod 644 "$DROPIN"

python3 - "$ENV_FILE" "$BIND_HOST" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
bind = sys.argv[2]
lines = p.read_text(encoding="utf-8").splitlines()
updates = {"COMELIT_P14_BIND_HOST":bind,"COMELIT_P14_LIVE_ENABLED":"true"}
seen = {key: 0 for key in updates}
out = []
for line in lines:
    if "=" in line:
        key, _ = line.split("=", 1)
        if key in updates:
            seen[key] += 1
            line = f"{key}={updates[key]}"
    out.append(line)
if any(value != 1 for value in seen.values()):
    raise SystemExit("P14_ENV_KEY_CARDINALITY=FAIL")
tmp = p.with_suffix(p.suffix + ".tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
tmp.chmod(0o600)
tmp.replace(p)
PY

chown root:root "$ENV_FILE"
systemctl daemon-reload
systemctl restart "$BRIDGE_SERVICE"
wait_for_live_health
nft list table inet comelit_p14 >/dev/null

trap - EXIT
rm -f "$ENV_BACKUP"
echo 'P14_LIVE_PROMOTION=PASS'
echo "P14_BRIDGE_BIND_HOST=$BIND_HOST"
echo 'P14_BRIDGE_PORT=18014'
echo 'P14_BRIDGE_LIVE_ENABLED=true'
echo 'P14_FIREWALL_ACTIVE=true'
echo 'P14_FIREWALL_POLICY=HA_CLIENT_PLUS_LOOPBACK_ONLY'
echo 'P14_SHARED_SECRET_EMITTED=false'
echo 'P14_OPEN_DOOR_REQUEST_SENT=false'
echo 'P14_RUNNER_INVOCATION_ATTEMPTED=false'
echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
echo 'SEND_ARMED_REACHED=false'
