#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"
test ! -e miniapp
test ! -e custom_components/comelit/frontend/miniapp/comelit-card.js
grep -Fq '/api/comelit/frontend/comelit-card.js' custom_components/comelit/miniapp/index.html
echo MINIAPP_EMBEDDED=PASS
