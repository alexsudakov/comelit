#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
PROD_ROOT=/opt/comelit-door-safety-poc/p14
RELEASES="$PROD_ROOT/releases"
CURRENT="$PROD_ROOT/current"
PREVIOUS="$PROD_ROOT/previous"
RETIRED="$PROD_ROOT/retired"
ENV_DIR=/root/.config/comelit
ENV_FILE="$ENV_DIR/p14-ha-bridge.env"
RUNTIME_DIR=/root/comelit-p14-ha-bridge
UNIT=/etc/systemd/system/comelit-p14-ha-bridge.service
UNIT_NAME=comelit-p14-ha-bridge.service
RUNNER_DEST=/usr/local/sbin/comelit-p14-production-runner
P13_PROD=/opt/comelit-door-safety-poc/p13
P13_RELEASE_ID=p13-415edb4525e4-50c0a916f73e-b6a10c68773a
P13_RELEASE="$P13_PROD/releases/$P13_RELEASE_ID"
P13_HEAD=0dace902d2cef1478cddea0f9d4cd36fcddb3837
P13_TREE=415edb4525e46601cd0ef1249fc0965927b1ac29
TARGET_FP=832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce
HOLDER_SHA=50c0a916f73ec810f131be1f48f47761a2cc69b9d06107d121519f97c538b450
WRAPPER_SHA=bf36b381f4921871f0b4df0820548b8943b935f1dfcd1521ceb79001dab71aa9
PAYLOAD_SHA=0d0159f9cc562c1c67bc362b192a30d3fabd634b2b92c3a96d8f318ecd842832

STEP=START
STAGE=""
RELEASE=""
RELEASE_CREATED=false
CURRENT_CHANGED=false
PREVIOUS_CHANGED=false
OLD_CURRENT=""
OLD_PREVIOUS=""
OLD_PREVIOUS_PRESENT=false
RUNNER_CHANGED=false
RUNNER_BACKUP=""
ENV_CHANGED=false
ENV_BACKUP=""
UNIT_CHANGED=false
UNIT_BACKUP=""
UNIT_EXISTED=false
SERVICE_STATE_CAPTURED=false
OLD_SERVICE_ENABLED=false
OLD_SERVICE_ACTIVE=false

restore_prior_service_state() {
    # Before CAPTURE_ROLLBACK there has been no service mutation. Early source
    # or P13-readiness failures therefore must be completely side-effect free.
    [[ "$SERVICE_STATE_CAPTURED" == true ]] || return 0

    # The new unit/process must be stopped before restoring old code/config.
    systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true

    if [[ "$UNIT_CHANGED" == true ]]; then
        if [[ "$UNIT_EXISTED" == true && -f "$UNIT_BACKUP" ]]; then
            cp -a "$UNIT_BACKUP" "$UNIT"
        else
            rm -f "$UNIT"
        fi
        systemctl daemon-reload >/dev/null 2>&1 || true
    fi

    if [[ "$UNIT_EXISTED" == true ]]; then
        if [[ "$OLD_SERVICE_ENABLED" == true ]]; then
            systemctl enable "$UNIT_NAME" >/dev/null 2>&1 || true
        else
            systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true
        fi
        if [[ "$OLD_SERVICE_ACTIVE" == true ]]; then
            systemctl start "$UNIT_NAME" >/dev/null 2>&1 || true
        else
            systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
        fi
    else
        systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
    fi
}

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        set +e

        # Stop the possibly-mutated service before changing selectors, runner
        # or environment underneath it. Restore runtime inputs first, then the
        # unit file and its exact prior enabled/active state.
        if [[ "$UNIT_CHANGED" == true ]]; then
            systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
        fi

        if [[ "$ENV_CHANGED" == true ]]; then
            if [[ -f "$ENV_BACKUP" ]]; then
                cp -a "$ENV_BACKUP" "$ENV_FILE"
            else
                rm -f "$ENV_FILE"
            fi
        fi
        if [[ "$RUNNER_CHANGED" == true ]]; then
            if [[ -f "$RUNNER_BACKUP" ]]; then
                cp -a "$RUNNER_BACKUP" "$RUNNER_DEST"
            else
                rm -f "$RUNNER_DEST"
            fi
        fi
        if [[ "$CURRENT_CHANGED" == true ]]; then
            if [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
                ln -sfn "$OLD_CURRENT" "$CURRENT"
            else
                rm -f "$CURRENT"
            fi
        fi
        if [[ "$PREVIOUS_CHANGED" == true ]]; then
            if [[ "$OLD_PREVIOUS_PRESENT" == true ]]; then
                ln -sfn "$OLD_PREVIOUS" "$PREVIOUS"
            else
                rm -f "$PREVIOUS"
            fi
        fi

        restore_prior_service_state

        [[ "$RELEASE_CREATED" == true && -d "$RELEASE" ]] && rm -rf "$RELEASE"
        [[ -z "$STAGE" ]] || rm -rf "$STAGE"
        rm -f "$ENV_FILE.tmp" "$UNIT.tmp" >/dev/null 2>&1 || true
        [[ -z "$RUNNER_BACKUP" ]] || rm -f "$RUNNER_BACKUP"
        [[ -z "$ENV_BACKUP" ]] || rm -f "$ENV_BACKUP"
        [[ -z "$UNIT_BACKUP" ]] || rm -f "$UNIT_BACKUP"
        echo 'P14_PRODUCTION_INSTALL=FAIL'
        echo "P14_PRODUCTION_INSTALL_LAST_STEP=$STEP"
        echo "P14_ROLLBACK_PRIOR_SERVICE_ENABLED=$OLD_SERVICE_ENABLED"
        echo "P14_ROLLBACK_PRIOR_SERVICE_ACTIVE=$OLD_SERVICE_ACTIVE"
        set -e
    fi
    return "$rc"
}
trap cleanup EXIT

[[ "${EUID}" -eq 0 ]] || { echo 'P14_INSTALL_REQUIRES_ROOT=true'; exit 1; }
echo 'P14_PRODUCTION_INSTALL_START=true'
echo 'P14_PRODUCTION_INSTALL_NON_ACTUATING=true'
echo 'P14_OPEN_DOOR_REQUEST_SENT=false'
echo 'P14_RUNNER_INVOCATION_ATTEMPTED=false'

STEP=SOURCE_IDENTITY
BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
case "$BRANCH" in
    main|feat/p14-ha-one-shot-service) ;;
    *) echo "P14_INSTALL_BRANCH=FAIL($BRANCH)"; exit 1 ;;
esac
git -C "$REPO_ROOT" fetch origin "$BRANCH"
LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$BRANCH")"
TREE="$(git -C "$REPO_ROOT" rev-parse 'HEAD^{tree}')"
[[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] || { echo 'P14_INSTALL_REMOTE_IDENTITY=FAIL'; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || { echo 'P14_INSTALL_WORKTREE_CLEAN=false'; exit 1; }
echo "P14_INSTALL_HEAD=$LOCAL_HEAD"
echo "P14_INSTALL_TREE=$TREE"

STEP=P13_IMMUTABLE_BOUNDARY
[[ -L "$P13_PROD/current" && "$(readlink -f "$P13_PROD/current")" == "$P13_RELEASE" ]]
[[ -f "$P13_RELEASE/RELEASE.env" && -f "$P13_RELEASE/RELEASE_CONTENT.sha256" ]]
( cd "$P13_RELEASE"; sha256sum -c RELEASE_CONTENT.sha256 >/dev/null )
for marker in \
    "P13_SOURCE_HEAD=$P13_HEAD" \
    "P13_SOURCE_TREE=$P13_TREE" \
    "P13_TARGET_FINGERPRINT=$TARGET_FP" \
    "P13_HOLDER_SHA256=$HOLDER_SHA" \
    "P13_WRAPPER_SHA256=$WRAPPER_SHA" \
    "P13_PAYLOAD_SHA256=$PAYLOAD_SHA" \
    'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true' \
    'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false' \
    'P13_AUTO_RETRY_ALLOWED=false' \
    'P13_PHYSICAL_EFFECT_ASSERTED=false'; do
    grep -Fxq "$marker" "$P13_RELEASE/RELEASE.env"
done
[[ "$(sha256sum /root/comelit-p13-native/comelit_p13_holder | awk '{print $1}')" == "$HOLDER_SHA" ]]
[[ "$(sha256sum /usr/local/sbin/comelit-p13-door-wrapper | awk '{print $1}')" == "$WRAPPER_SHA" ]]
[[ "$(sha256sum /root/comelit-p13-actuator-prep/real-door-payloads.json | awk '{print $1}')" == "$PAYLOAD_SHA" ]]
echo 'P14_P13_IMMUTABLE_BOUNDARY=PASS'

STEP=STAGE_RELEASE
RUNNER_SOURCE="$POC_ROOT/scripts/p14_production_runner.sh"
[[ -f "$RUNNER_SOURCE" ]]
RUNNER_SHA="$(sha256sum "$RUNNER_SOURCE" | awk '{print $1}')"
RELEASE_ID="p14-${TREE:0:12}-${RUNNER_SHA:0:12}"
RELEASE="$RELEASES/$RELEASE_ID"
mkdir -p "$RELEASES" "$RETIRED"
chmod 700 "$PROD_ROOT" "$RELEASES" "$RETIRED"
if [[ -d "$RELEASE" ]]; then
    ( cd "$RELEASE"; sha256sum -c RELEASE_CONTENT.sha256 >/dev/null )
    echo "P14_PRODUCTION_RELEASE_ALREADY_EXISTS=$RELEASE_ID"
else
    STAGE="$(mktemp -d "$PROD_ROOT/.stage-${RELEASE_ID}.XXXXXX")"
    chmod 700 "$STAGE"
    mkdir -p "$STAGE/repo" "$STAGE/custom_components"
    git -C "$REPO_ROOT" archive HEAD:safety-poc | tar -xf - -C "$STAGE/repo"
    git -C "$REPO_ROOT" archive HEAD:custom_components | tar -xf - -C "$STAGE/custom_components"
    cat >"$STAGE/RELEASE.env" <<EOF
P14_PRODUCTION_RELEASE_SCHEMA=1
P14_RELEASE_ID=$RELEASE_ID
P14_SOURCE_HEAD=$LOCAL_HEAD
P14_SOURCE_TREE=$TREE
P14_PRODUCTION_RUNNER_SHA256=$RUNNER_SHA
P14_P13_RELEASE_ID=$P13_RELEASE_ID
P14_P13_SOURCE_HEAD=$P13_HEAD
P14_P13_SOURCE_TREE=$P13_TREE
P14_TARGET_FINGERPRINT=$TARGET_FP
P14_HA_RESPONSE_REQUIRED=true
P14_STANDARD_BUTTON_PRESS_ALLOWED=false
P14_AUTO_RETRY_ALLOWED=false
P14_PHYSICAL_EFFECT_ASSERTED=false
P14_LIVE_DEFAULT=false
EOF
    chmod 600 "$STAGE/RELEASE.env"
    (
        cd "$STAGE"
        find . -type f ! -name RELEASE_CONTENT.sha256 -print0 | sort -z | xargs -0 sha256sum >RELEASE_CONTENT.sha256
        chmod 600 RELEASE_CONTENT.sha256
        sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
    )
    mv "$STAGE" "$RELEASE"
    STAGE=""
    RELEASE_CREATED=true
    echo "P14_PRODUCTION_RELEASE_CREATED=$RELEASE_ID"
fi

STEP=CAPTURE_ROLLBACK
if [[ -L "$CURRENT" ]]; then
    OLD_CURRENT="$(readlink -f "$CURRENT")"
    [[ -d "$OLD_CURRENT" ]]
elif [[ -e "$CURRENT" ]]; then
    echo 'P14_CURRENT_NOT_SYMLINK=true'
    exit 1
fi
if [[ -L "$PREVIOUS" ]]; then
    OLD_PREVIOUS="$(readlink -f "$PREVIOUS")"
    case "$OLD_PREVIOUS" in
        "$RELEASES"/*) OLD_PREVIOUS_PRESENT=true ;;
        *) echo 'P14_OLD_PREVIOUS_SCOPE=FAIL'; exit 1 ;;
    esac
elif [[ -e "$PREVIOUS" ]]; then
    echo 'P14_PREVIOUS_NOT_SYMLINK=true'
    exit 1
fi
if [[ -f "$RUNNER_DEST" ]]; then
    RUNNER_BACKUP="$(mktemp /root/p14-runner-backup.XXXXXX)"
    cp -a "$RUNNER_DEST" "$RUNNER_BACKUP"
fi
if [[ -f "$ENV_FILE" ]]; then
    ENV_BACKUP="$(mktemp /root/p14-env-backup.XXXXXX)"
    cp -a "$ENV_FILE" "$ENV_BACKUP"
fi
if [[ -f "$UNIT" ]]; then
    UNIT_EXISTED=true
    UNIT_BACKUP="$(mktemp /root/p14-unit-backup.XXXXXX)"
    cp -a "$UNIT" "$UNIT_BACKUP"
fi
if systemctl is-enabled "$UNIT_NAME" >/dev/null 2>&1; then
    OLD_SERVICE_ENABLED=true
fi
if systemctl is-active "$UNIT_NAME" >/dev/null 2>&1; then
    OLD_SERVICE_ACTIVE=true
fi
SERVICE_STATE_CAPTURED=true
echo "P14_PRIOR_SERVICE_ENABLED=$OLD_SERVICE_ENABLED"
echo "P14_PRIOR_SERVICE_ACTIVE=$OLD_SERVICE_ACTIVE"

STEP=PROMOTE_RELEASE
if [[ -n "$OLD_CURRENT" && "$OLD_CURRENT" != "$RELEASE" ]]; then
    case "$OLD_CURRENT" in
        "$RELEASES"/*) ln -sfn "$OLD_CURRENT" "$PREVIOUS"; PREVIOUS_CHANGED=true ;;
        *) echo 'P14_OLD_CURRENT_SCOPE=FAIL'; exit 1 ;;
    esac
fi
ln -sfn "$RELEASE" "$CURRENT"
CURRENT_CHANGED=true
install -o root -g root -m 0700 "$CURRENT/repo/scripts/p14_production_runner.sh" "$RUNNER_DEST"
RUNNER_CHANGED=true
[[ "$(sha256sum "$RUNNER_DEST" | awk '{print $1}')" == "$RUNNER_SHA" ]]

STEP=ENVIRONMENT
install -d -o root -g root -m 0700 "$ENV_DIR" "$RUNTIME_DIR"
SHARED_SECRET=""
if [[ -f "$ENV_FILE" ]]; then
    [[ "$(stat -c '%u' "$ENV_FILE")" == 0 ]]
    grep -qx 'COMELIT_P14_LIVE_ENABLED=false' "$ENV_FILE" || { echo 'P14_EXISTING_RUNTIME_MUST_BE_DISABLED_BEFORE_INSTALL=true'; exit 1; }
    SHARED_SECRET="$(sed -n 's/^COMELIT_P14_SHARED_SECRET=//p' "$ENV_FILE")"
fi
[[ -n "$SHARED_SECRET" ]] || SHARED_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
[[ "$(printf '%s' "$SHARED_SECRET" | wc -c)" -ge 32 ]]
cat >"$ENV_FILE.tmp" <<EOF
COMELIT_P14_SHARED_SECRET=$SHARED_SECRET
COMELIT_P14_TARGET_FINGERPRINT=$TARGET_FP
COMELIT_P14_RUNNER=$RUNNER_DEST
COMELIT_P14_RUNNER_SHA256=$RUNNER_SHA
COMELIT_P14_JOURNAL=/root/comelit-p13-run/p13-one-shot.sqlite3
COMELIT_P14_REPLAY_DB=/root/comelit-p14-ha-bridge/replay.sqlite3
COMELIT_P14_RUNNER_LOCK=/root/comelit-p14-ha-bridge/runner.lock
COMELIT_P14_MAX_CLOCK_SKEW=30
COMELIT_P14_RUNNER_TIMEOUT=150
COMELIT_P14_TERM_GRACE=5
COMELIT_P14_BIND_HOST=127.0.0.1
COMELIT_P14_BIND_PORT=18014
COMELIT_P14_LIVE_ENABLED=false
EOF
chmod 600 "$ENV_FILE.tmp"
chown root:root "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"
ENV_CHANGED=true

STEP=SYSTEMD
cat >"$UNIT.tmp" <<'EOF'
[Unit]
Description=Comelit P14 Home Assistant Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
UMask=0077
EnvironmentFile=/root/.config/comelit/p14-ha-bridge.env
ExecStart=/usr/bin/env PYTHONPATH=/opt/comelit-door-safety-poc/p14/current/repo/src PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 /opt/comelit-door-safety-poc/p14/current/repo/scripts/p14_ha_bridge_server.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/root/comelit-p14-ha-bridge /root/comelit-p13-run /root/comelit-p13-audit

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$UNIT.tmp"
chown root:root "$UNIT.tmp"
mv "$UNIT.tmp" "$UNIT"
UNIT_CHANGED=true
systemctl daemon-reload
systemctl enable --now "$UNIT_NAME" >/dev/null

STEP=VERIFY
HEALTH="$(curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18014/healthz)"
python3 - "$HEALTH" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); assert obj.get("ok") is True; assert obj.get("protocol_version") == 1; assert obj.get("live_enabled") is False; assert obj.get("runner_identity") == "disabled"
PY
( cd "$CURRENT"; sha256sum -c RELEASE_CONTENT.sha256 >/dev/null )
[[ "$(readlink -f "$CURRENT")" == "$RELEASE" ]]
tar -C "$CURRENT" -czf "$RUNTIME_DIR/comelit-ha-component.tar.gz" custom_components/comelit
chmod 600 "$RUNTIME_DIR/comelit-ha-component.tar.gz"
cat >"$RUNTIME_DIR/DEPLOYMENT.txt" <<EOF
P14_RELEASE_ID=$RELEASE_ID
P14_SOURCE_HEAD=$LOCAL_HEAD
P14_SOURCE_TREE=$TREE
HA_COMPONENT_BUNDLE=$RUNTIME_DIR/comelit-ha-component.tar.gz
HA_BRIDGE_PORT=18014
HA_SHARED_SECRET_SOURCE=$ENV_FILE
P14_LIVE_ENABLED=false
EOF
chmod 600 "$RUNTIME_DIR/DEPLOYMENT.txt"

STEP=COMPLETE
trap - EXIT
rm -f "$RUNNER_BACKUP" "$ENV_BACKUP" "$UNIT_BACKUP"
echo 'P14_PRODUCTION_INSTALL=PASS'
echo "P14_PRODUCTION_RELEASE_ID=$RELEASE_ID"
echo "P14_PRODUCTION_CURRENT=$(readlink -f "$CURRENT")"
echo "P14_PRODUCTION_PREVIOUS=$([[ -L "$PREVIOUS" ]] && readlink -f "$PREVIOUS" || echo none)"
echo 'P14_BRIDGE_HEALTH=PASS'
echo 'P14_BRIDGE_BIND=127.0.0.1:18014'
echo 'P14_BRIDGE_LIVE_ENABLED=false'
echo 'P14_HA_RESPONSE_REQUIRED=true'
echo 'P14_SHARED_SECRET_EMITTED=false'
echo 'P14_OPEN_DOOR_REQUEST_SENT=false'
echo 'P14_RUNNER_INVOCATION_ATTEMPTED=false'
echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
echo 'SEND_ARMED_REACHED=false'
echo 'P14_PRODUCTION_INSTALL_NON_ACTUATING=true'
