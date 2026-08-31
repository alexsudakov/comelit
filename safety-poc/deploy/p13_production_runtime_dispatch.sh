#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROD_ROOT=/opt/comelit-door-safety-poc/p13
RELEASES="$PROD_ROOT/releases"
CURRENT="$PROD_ROOT/current"

HOLDER=/root/comelit-p13-native/comelit_p13_holder
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
GATE_STATE=/root/comelit-p13-run/hermes-observed-acceptance-v1.state

marker() {
    local key="$1"
    local file="$2"

    awk -F= -v key="$key" '
        $1 == key {
            print substr($0, length(key) + 2)
            exit
        }
    ' "$file"
}

MODE="${1:-}"

case "$MODE" in
    readiness)
        [[ $# -eq 1 ]] || {
            echo 'P13_PRODUCTION_RUNTIME_DISPATCH_ARGUMENTS=DENIED'
            exit 126
        }

        [[ -L "$CURRENT" ]] || {
            echo 'P13_PRODUCTION_CURRENT_PRESENT=false'
            exit 1
        }

        RELEASE="$(readlink -f "$CURRENT")"

        case "$RELEASE" in
            "$RELEASES"/*) ;;
            *)
                echo 'P13_PRODUCTION_CURRENT_SCOPE=FAIL'
                exit 1
                ;;
        esac

        MANIFEST="$RELEASE/RELEASE.env"
        CHECKSUMS="$RELEASE/RELEASE_CONTENT.sha256"

        [[ -f "$MANIFEST" && -f "$CHECKSUMS" ]] || {
            echo 'P13_PRODUCTION_RELEASE_METADATA=FAIL'
            exit 1
        }

        (
            cd "$RELEASE"
            sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
        ) || {
            echo 'P13_PRODUCTION_RELEASE_CONTENT=FAIL'
            exit 1
        }

        RELEASE_ID="$(marker P13_RELEASE_ID "$MANIFEST")"
        SOURCE_HEAD="$(marker P13_SOURCE_HEAD "$MANIFEST")"
        SOURCE_TREE="$(marker P13_SOURCE_TREE "$MANIFEST")"

        EXPECTED_HOLDER_SHA="$(marker P13_HOLDER_SHA256 "$MANIFEST")"
        EXPECTED_WRAPPER_SHA="$(marker P13_WRAPPER_SHA256 "$MANIFEST")"
        EXPECTED_PAYLOAD_SHA="$(marker P13_PAYLOAD_SHA256 "$MANIFEST")"
        EXPECTED_DISPATCH_SHA="$(marker P13_PRODUCTION_DISPATCH_SHA256 "$MANIFEST")"

        [[ "$EXPECTED_HOLDER_SHA" =~ ^[0-9a-f]{64}$ ]]
        [[ "$EXPECTED_WRAPPER_SHA" =~ ^[0-9a-f]{64}$ ]]
        [[ "$EXPECTED_PAYLOAD_SHA" =~ ^[0-9a-f]{64}$ ]]
        [[ "$EXPECTED_DISPATCH_SHA" =~ ^[0-9a-f]{64}$ ]]

        [[ -f "$HOLDER" && -f "$WRAPPER" && -f "$PAYLOAD" ]]

        [[ "$(sha256sum "$HOLDER" | awk '{print $1}')" == "$EXPECTED_HOLDER_SHA" ]]
        [[ "$(sha256sum "$WRAPPER" | awk '{print $1}')" == "$EXPECTED_WRAPPER_SHA" ]]
        [[ "$(sha256sum "$PAYLOAD" | awk '{print $1}')" == "$EXPECTED_PAYLOAD_SHA" ]]

        [[ "$(stat -c '%u:%a' "$HOLDER")" == '0:700' ]]
        [[ "$(stat -c '%u:%a' "$WRAPPER")" == '0:700' ]]
        [[ "$(stat -c '%u:%a' "$PAYLOAD")" == '0:600' ]]

        SELF_SHA="$(sha256sum "$0" | awk '{print $1}')"
        [[ "$SELF_SHA" == "$EXPECTED_DISPATCH_SHA" ]] || {
            echo 'P13_PRODUCTION_DISPATCH_IDENTITY=FAIL'
            exit 1
        }

        [[ -f "$GATE_STATE" ]]
        [[ "$(cat "$GATE_STATE")" == 'CONSUMED_BEFORE_LIVE_ENTRYPOINT' ]]

        echo 'P13_PRODUCTION_RUNTIME_DISPATCH_IDENTITY=PASS'
        echo 'P13_PRODUCTION_RUNTIME_DISPATCH_MODE=READINESS'
        echo "P13_PRODUCTION_RELEASE_ID=$RELEASE_ID"
        echo "P13_PRODUCTION_SOURCE_HEAD=$SOURCE_HEAD"
        echo "P13_PRODUCTION_SOURCE_TREE=$SOURCE_TREE"
        echo 'P13_PRODUCTION_RELEASE_CONTENT=PASS'
        echo 'P13_PRODUCTION_RUNTIME_ARTIFACT_IDENTITIES=PASS'
        echo 'P13_OBSERVED_ACCEPTANCE_GATE_TERMINAL=CONSUMED'
        echo 'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true'
        echo 'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false'
        echo 'P13_AUTO_RETRY_ALLOWED=false'
        echo 'P13_PHYSICAL_EFFECT_ASSERTED=false'
        echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
        echo 'PHYSICAL_DOOR_ACTION=false'
        echo 'SEND_ARMED_REACHED=false'
        ;;

    observed-open)
        echo 'P13_PRODUCTION_RUNTIME_DISPATCH_MODE=OBSERVED_OPEN'
        echo 'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true'
        echo 'P13_OBSERVED_ACCEPTANCE_GATE_TERMINAL=CONSUMED'
        echo 'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false'
        echo 'P13_RESEND_ALLOWED=false'
        echo 'P13_AUTO_RETRY_ALLOWED=false'
        echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
        echo 'PHYSICAL_DOOR_ACTION=false'
        echo 'SEND_ARMED_REACHED=false'
        exit 126
        ;;

    *)
        echo 'P13_PRODUCTION_RUNTIME_DISPATCH=DENIED'
        echo 'P13_PRODUCTION_ALLOWED=readiness'
        echo 'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false'
        exit 126
        ;;
esac
