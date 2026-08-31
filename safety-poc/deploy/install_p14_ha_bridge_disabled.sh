#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo 'P14_LEGACY_DISABLED_INSTALLER_SUPERSEDED=true'
exec "$SCRIPT_DIR/install_p14_production_release.sh" "$@"
