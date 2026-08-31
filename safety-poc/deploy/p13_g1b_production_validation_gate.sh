#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SELF="$(readlink -f "${BASH_SOURCE[0]}")"

PROD_ROOT=/opt/comelit-door-safety-poc/p13
CURRENT="$PROD_ROOT/current"

RUN_DIR=/root/comelit-p13-run
STATE="$RUN_DIR/g1b-production-validation-v1.state"
LOCK="$RUN_DIR/g1b-production-validation-v1.lock"

APPROVAL=I_APPROVE_P13_G1B_IMMUTABLE_PRODUCTION_DOOR_TEST

verify_installed_identity() {
    [[ -L "$CURRENT" ]]
    CURRENT_REAL="$(readlink -f "$CURRENT")"

    SOURCE_GATE="$CURRENT_REAL/repo/deploy/p13_g1b_production_validation_gate.sh"
    RUNNER="$CURRENT_REAL/repo/deploy/p13_g1b_production_validation_runner.sh"
    MANIFEST="$CURRENT_REAL/RELEASE.env"

    [[ -f "$SOURCE_GATE" && -f "$RUNNER" && -f "$MANIFEST" ]]

    [[ "$(sha256sum "$SELF" | awk '{print $1}')" \
       == "$(sha256sum "$SOURCE_GATE" | awk '{print $1}')" ]]

    (
        cd "$CURRENT_REAL"
        sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
    )

    RELEASE_ID="$(
        awk -F= '$1=="P13_RELEASE_ID"{print substr($0,length($1)+2); exit}' \
          "$MANIFEST"
    )"

    [[ -n "$RELEASE_ID" ]]
}

[[ "${EUID}" -eq 0 ]]

MODE="${1:-}"

case "$MODE" in
    readiness)
        [[ $# -eq 1 ]]

        verify_installed_identity

        if [[ -f "$STATE" ]]; then
            echo 'P13_G1B_GATE_STATE=CONSUMED'
            echo 'P13_G1B_RESEND_ALLOWED=false'
        else
            echo 'P13_G1B_GATE_STATE=UNUSED'
            echo 'P13_G1B_RESEND_ALLOWED=true'
        fi

        bash "$RUNNER" preflight

        echo 'P13_G1B_GATE_IDENTITY=PASS'
        echo 'P13_G1B_GATE_MODE=READINESS'
        echo 'P13_G1B_PHYSICAL_ACTION=false'
        echo 'SEND_ARMED_REACHED=false'
        ;;

    open)
        [[ $# -eq 2 ]]

        [[ "$2" == "$APPROVAL" ]] || {
            echo 'P13_G1B_APPROVAL=REJECTED'
            echo 'P13_G1B_RESEND_ALLOWED=false'
            exit 64
        }

        verify_installed_identity

        install -d -m 700 -o root -g root "$RUN_DIR"
        touch "$LOCK"
        chmod 600 "$LOCK"
        chown root:root "$LOCK"

        exec 9>"$LOCK"

        if ! flock -n 9; then
            echo 'P13_G1B_CONCURRENT_INVOCATION=true'
            exit 75
        fi

        if [[ -f "$STATE" ]]; then
            echo 'P13_G1B_GATE_STATE=CONSUMED'
            echo 'P13_G1B_RESEND_ALLOWED=false'
            exit 73
        fi

        # Full non-actuating immutable-release preflight happens before
        # consuming the one-shot physical validation gate.
        bash "$RUNNER" preflight

        OPERATION_ID="$(
          python3 - <<'PY'
import uuid
print("p13-g1b-" + str(uuid.uuid4()))
PY
        )"

        # Durable irreversible G1B gate consumption occurs BEFORE any
        # SEND-capable runner handoff.
        python3 - "$STATE" "$OPERATION_ID" "$RELEASE_ID" <<'PY'
import os
import sys
from pathlib import Path

state = Path(sys.argv[1])
operation_id = sys.argv[2]
release_id = sys.argv[3]

if state.exists():
    raise SystemExit("P13_G1B_STATE_ALREADY_EXISTS")

tmp = state.with_name(state.name + f".tmp.{os.getpid()}")

data = (
    "P13_G1B_GATE_STATE=CONSUMED_BEFORE_LIVE_ENTRYPOINT\n"
    f"P13_G1B_OPERATION_ID={operation_id}\n"
    f"P13_G1B_RELEASE_ID={release_id}\n"
)

fd = os.open(
    tmp,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    0o600,
)

try:
    os.write(fd, data.encode("utf-8"))
    os.fsync(fd)
finally:
    os.close(fd)

os.replace(tmp, state)

dfd = os.open(str(state.parent), os.O_RDONLY)
try:
    os.fsync(dfd)
finally:
    os.close(dfd)
PY

        echo 'P13_G1B_APPROVAL=GRANTED'
        echo 'P13_G1B_GATE_STATE=CONSUMED_BEFORE_LIVE_ENTRYPOINT'
        echo "P13_G1B_OPERATION_ID=$OPERATION_ID"
        echo "P13_G1B_RELEASE_ID=$RELEASE_ID"
        echo 'P13_G1B_RESEND_ALLOWED=false'
        echo 'P13_G1B_AUTO_RETRY_ALLOWED=false'
        echo 'P13_G1B_WARNING=PHYSICAL_DOOR_MAY_OPEN'

        # Exactly one live-capable handoff. No retry path exists.
        exec env \
          P13_G1B_INTERNAL_ARM=G1B_SINGLE_USE_GATE_CONSUMED \
          bash "$RUNNER" execute "$OPERATION_ID"
        ;;

    *)
        echo 'P13_G1B_GATE=DENIED'
        exit 126
        ;;
esac
