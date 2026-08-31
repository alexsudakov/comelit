#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

EXPECTED_BRANCH=feat/p14-ha-one-shot-service
EXPECTED_P13_BRANCH=feat/p13-one-shot-actuation
INSTALL_ROOT=/opt/comelit-p14
ENV_DIR=/root/.config/comelit
ENV_FILE="$ENV_DIR/p14-ha-bridge.env"
RUNTIME_DIR=/root/comelit-p14-ha-bridge
UNIT=/etc/systemd/system/comelit-p14-ha-bridge.service
IDENTITY_FILE=/root/comelit-p13-runtime-identity.json

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
P13_RUNTIME_ROOT="${P14_P13_RUNTIME_ROOT:-/root/comelit-git}"
P13_RUNNER="$P13_RUNTIME_ROOT/safety-poc/scripts/p13_one_shot_physical_runner.sh"

[[ "${EUID}" -eq 0 ]] || { echo "P14_INSTALL_REQUIRES_ROOT=true"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo "P14_INSTALL_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P14_INSTALL_WORKTREE_CLEAN=false"
    exit 1
}

# The actuation artifact stays in a separate clean P13 runtime worktree. P14
# never changes that branch gate and never executes the runner from its own
# stacked checkout.
[[ -d "$P13_RUNTIME_ROOT/.git" || -f "$P13_RUNTIME_ROOT/.git" ]] || {
    echo "P14_P13_RUNTIME_REPO=ABSENT"
    exit 1
}
[[ "$(git -C "$P13_RUNTIME_ROOT" branch --show-current)" == "$EXPECTED_P13_BRANCH" ]] || {
    echo "P14_P13_RUNTIME_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$P13_RUNTIME_ROOT" status --porcelain)" ]] || {
    echo "P14_P13_RUNTIME_WORKTREE_CLEAN=false"
    exit 1
}
[[ -f "$P13_RUNNER" ]] || { echo "P14_P13_RUNNER_PRESENT=false"; exit 1; }
[[ -f "$IDENTITY_FILE" ]] || { echo "P14_RUNTIME_IDENTITY_PRESENT=false"; exit 1; }

TARGET_FP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["payload"]["target_fingerprint"])' "$IDENTITY_FILE")"
[[ "$TARGET_FP" =~ ^[0-9a-f]{64}$ ]] || { echo "P14_TARGET_BINDING=FAIL"; exit 1; }

P14_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
P14_TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
P13_HEAD="$(git -C "$P13_RUNTIME_ROOT" rev-parse HEAD)"
P13_TREE="$(git -C "$P13_RUNTIME_ROOT" rev-parse HEAD^{tree})"

echo "P14_DISABLED_INSTALL_START=true"
echo "P14_DISABLED_INSTALL_NON_ACTUATING=true"
echo "P14_INSTALL_HEAD=$P14_HEAD"
echo "P14_INSTALL_TREE=$P14_TREE"
echo "P14_P13_RUNTIME_HEAD=$P13_HEAD"
echo "P14_P13_RUNTIME_TREE=$P13_TREE"

install -d -o root -g root -m 0755 "$INSTALL_ROOT" "$INSTALL_ROOT/scripts" "$INSTALL_ROOT/src"
rm -rf "$INSTALL_ROOT/src/comelit_safety_poc"
cp -a "$POC_ROOT/src/comelit_safety_poc" "$INSTALL_ROOT/src/"
install -o root -g root -m 0755 "$POC_ROOT/scripts/p14_ha_bridge_server.py" "$INSTALL_ROOT/scripts/p14_ha_bridge_server.py"
find "$INSTALL_ROOT/src/comelit_safety_poc" -type d -exec chmod 0755 {} +
find "$INSTALL_ROOT/src/comelit_safety_poc" -type f -exec chmod 0644 {} +
chown -R root:root "$INSTALL_ROOT"

install -d -o root -g root -m 0700 "$ENV_DIR" "$RUNTIME_DIR"

if [[ -e "$ENV_FILE" ]]; then
    [[ "$(stat -c '%u' "$ENV_FILE")" == "0" ]] || { echo "P14_ENV_OWNER=FAIL"; exit 1; }
    chmod 0600 "$ENV_FILE"
    # Existing configuration is never silently changed. In particular an
    # already live-enabled file cannot be reused by this disabled installer.
    grep -qx 'COMELIT_P14_LIVE_ENABLED=false' "$ENV_FILE" || {
        echo "P14_ENV_EXISTING_NOT_DISABLED=true"
        exit 1
    }
    grep -q '^COMELIT_P14_SHARED_SECRET=.' "$ENV_FILE" || { echo "P14_ENV_SECRET=ABSENT"; exit 1; }
else
    SHARED_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    cat >"$ENV_FILE" <<EOF
COMELIT_P14_SHARED_SECRET=$SHARED_SECRET
COMELIT_P14_TARGET_FINGERPRINT=$TARGET_FP
COMELIT_P14_RUNNER=$P13_RUNNER
COMELIT_P14_JOURNAL=/root/comelit-p13-run/p13-one-shot.sqlite3
COMELIT_P14_REPLAY_DB=/root/comelit-p14-ha-bridge/replay.sqlite3
COMELIT_P14_MIN_INTERVAL=10
COMELIT_P14_MAX_CLOCK_SKEW=30
COMELIT_P14_RUNNER_TIMEOUT=120
COMELIT_P14_BIND_HOST=127.0.0.1
COMELIT_P14_BIND_PORT=18014
COMELIT_P14_LIVE_ENABLED=false
EOF
    chmod 0600 "$ENV_FILE"
fi

cat >"$UNIT" <<'EOF'
[Unit]
Description=Comelit P14 Home Assistant Bridge (one-shot protected)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
UMask=0077
EnvironmentFile=/root/.config/comelit/p14-ha-bridge.env
ExecStart=/usr/bin/python3 /opt/comelit-p14/scripts/p14_ha_bridge_server.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/root/comelit-p14-ha-bridge /root/comelit-p13-run /root/comelit-p13-audit

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT"

systemctl daemon-reload
systemctl enable --now comelit-p14-ha-bridge.service >/dev/null

# Local health only. No signed open_door request is emitted by this installer.
HEALTH="$(curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18014/healthz)"
python3 - "$HEALTH" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
assert obj.get("ok") is True
assert obj.get("protocol_version") == 1
assert obj.get("live_enabled") is False
PY

echo "P14_BRIDGE_HEALTH=PASS"
echo "P14_BRIDGE_BIND=127.0.0.1:18014"
echo "P14_BRIDGE_LIVE_ENABLED=false"
echo "P14_SHARED_SECRET_EMITTED=false"
echo "P14_TARGET_FINGERPRINT_EMITTED=false"
echo "P14_RUNNER_INVOCATION_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "P14_DISABLED_INSTALL_COMPLETE=true"
