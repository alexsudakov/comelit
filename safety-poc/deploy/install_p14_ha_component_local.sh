#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE="$REPO_ROOT/custom_components/comelit"
CONFIG_DIR=""
usage(){ echo 'usage: install_p14_ha_component_local.sh --config-dir /config' >&2; exit 64; }
while [[ $# -gt 0 ]]; do case "$1" in --config-dir) [[ $# -ge 2 ]] || usage; CONFIG_DIR="$2"; shift 2 ;; *) usage ;; esac; done
[[ -n "$CONFIG_DIR" ]] || usage
[[ -d "$CONFIG_DIR" ]] || { echo 'P14_HA_CONFIG_DIR_PRESENT=false'; exit 1; }
[[ -f "$SOURCE/manifest.json" && -f "$SOURCE/__init__.py" ]]
DEST_ROOT="$CONFIG_DIR/custom_components"; DEST="$DEST_ROOT/comelit"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; BACKUP="$CONFIG_DIR/.comelit-backup-$STAMP"; TMP="$DEST_ROOT/.comelit-stage-$STAMP-$$"; OWNER="$(stat -c '%u:%g' "$CONFIG_DIR")"
mkdir -p "$DEST_ROOT"; rm -rf "$TMP"; mkdir -p "$TMP"; cp -a "$SOURCE/." "$TMP/"
find "$TMP" -type d -exec chmod 0755 {} +; find "$TMP" -type f -exec chmod 0644 {} +; chown -R "$OWNER" "$TMP"
python3 -m compileall -q "$TMP"; find "$TMP" -type d -name __pycache__ -prune -exec rm -rf {} +
MOVED_OLD=false
rollback(){ rc=$?; if [[ $rc -ne 0 ]]; then set +e; rm -rf "$TMP"; if [[ "$MOVED_OLD" == true && -d "$BACKUP" && ! -e "$DEST" ]]; then mv "$BACKUP" "$DEST"; fi; set -e; fi; return "$rc"; }
trap rollback EXIT
if [[ -e "$DEST" ]]; then [[ -d "$DEST" ]] || { echo 'P14_HA_DEST_NOT_DIRECTORY=true'; exit 1; }; mv "$DEST" "$BACKUP"; MOVED_OLD=true; fi
mv "$TMP" "$DEST"
python3 - "$DEST/manifest.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1], encoding='utf-8')); assert obj['domain']=='comelit'; assert obj['version']=='1.0.0'; assert obj['config_flow'] is True
PY
trap - EXIT
echo 'P14_HA_COMPONENT_INSTALL=PASS'
echo "P14_HA_COMPONENT_PATH=$DEST"
echo "P14_HA_COMPONENT_BACKUP=$([[ -d "$BACKUP" ]] && echo "$BACKUP" || echo none)"
echo 'P14_HA_RESTART_REQUIRED=true'
echo 'P14_HA_SERVICE_CALL_PERFORMED=false'
echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
