#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -ge 1 ]] || { echo 'usage: deploy_p14.sh ct120-install|ct120-promote|ct120-disable|ha-install ...' >&2; exit 64; }
MODE="$1"; shift
case "$MODE" in
    ct120-install) exec "$SCRIPT_DIR/install_p14_production_release.sh" "$@" ;;
    ct120-promote) exec "$SCRIPT_DIR/promote_p14_live.sh" "$@" ;;
    ct120-disable) exec "$SCRIPT_DIR/disable_p14_live.sh" "$@" ;;
    ha-install) exec "$SCRIPT_DIR/install_p14_ha_component_local.sh" "$@" ;;
    *) echo 'usage: deploy_p14.sh ct120-install|ct120-promote|ct120-disable|ha-install ...' >&2; exit 64 ;;
esac
