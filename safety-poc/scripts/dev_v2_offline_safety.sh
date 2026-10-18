#!/bin/sh
# Base-owned DEV v2 offline-safety. Keep parity with offline-safety.yml.
set -eu
cd safety-poc
python3.12 scripts/static_safety_check.py
python3.12 -m py_compile scripts/*.py
python3.12 -m compileall -q ../custom_components/comelit
node --check ../custom_components/comelit/frontend/comelit-card.js
for script in scripts/*.sh deploy/*.sh; do bash -n "$script"; done
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m unittest discover -s tests -v
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
DB="$TMP/poc.sqlite3"
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-ack --target demo-door --scenario ack --min-interval-seconds 0 >/dev/null
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-amb --target demo-door-2 --scenario timeout_after_accept --min-interval-seconds 0 >/dev/null
set +e
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-crash --target demo-door-3 --scenario ack --fault crash_after_arm --min-interval-seconds 0 >/dev/null
rc=$?
set -e
test "$rc" -eq 75
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m comelit_safety_poc.cli --db "$DB" recover >/dev/null
state="$(PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 python3.12 -m comelit_safety_poc.cli --db "$DB" show --operation-id ci-crash | python3.12 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
test "$state" = UNKNOWN_OUTCOME
