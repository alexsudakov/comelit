#!/usr/bin/env bash
# Offline profile-aware marker gate for CT120/P80 HAOS media builds.

set -u -o pipefail

PROFILE=
GENERATED_SOURCE=
STRINGS_FILE=
BINARY=

usage() {
    echo "usage: $0 --profile LEGACY|P122 [--generated-source FILE] [--strings-file FILE|--binary FILE]" >&2
}

fail_source() {
    echo "PROFILE_SOURCE_GATE=FAIL marker=$1" >&2
    exit 1
}

fail_binary() {
    echo "PROFILE_BINARY_GATE=FAIL marker=$1" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            PROFILE="$2"
            shift 2
            ;;
        --generated-source)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            GENERATED_SOURCE="$2"
            shift 2
            ;;
        --strings-file)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            STRINGS_FILE="$2"
            shift 2
            ;;
        --binary)
            [ "$#" -ge 2 ] || { usage; exit 2; }
            BINARY="$2"
            shift 2
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

case "$PROFILE" in
    LEGACY|P122) ;;
    *)
        echo "P80_BUILD_PROFILE=INVALID value=$PROFILE" >&2
        exit 1
        ;;
esac

if [ -n "$BINARY" ] && [ -n "$STRINGS_FILE" ]; then
    echo "PROFILE_BINARY_GATE=FAIL marker=multiple_binary_inputs" >&2
    exit 2
fi

TMP_STRINGS=
cleanup() {
    if [ -n "${TMP_STRINGS:-}" ]; then
        rm -f "$TMP_STRINGS"
    fi
}
trap cleanup EXIT

if [ -n "$BINARY" ]; then
    [ -f "$BINARY" ] || fail_binary "binary_absent"
    TMP_STRINGS="$(mktemp)"
    strings -a "$BINARY" > "$TMP_STRINGS"
    STRINGS_FILE="$TMP_STRINGS"
fi

require_source_marker() {
    grep -Fq "$1" "$GENERATED_SOURCE" || fail_source "$1"
}

forbid_source_marker() {
    ! grep -Fq "$1" "$GENERATED_SOURCE" || fail_source "$1"
}

require_binary_marker() {
    grep -Fq "$1" "$STRINGS_FILE" || fail_binary "$1"
}

forbid_binary_marker() {
    ! grep -Fq "$1" "$STRINGS_FILE" || fail_binary "$1"
}

if [ -n "$GENERATED_SOURCE" ]; then
    [ -f "$GENERATED_SOURCE" ] || fail_source "generated_source_absent"
    require_source_marker '#define RUN_DIR     "/run/comelit-media"'
    forbid_source_marker 'signal(SIGUSR1, v4_door_signal_handler);'

    case "$PROFILE" in
        LEGACY)
            require_source_marker 'P80_MEDIA_ACTIVE=true'
            require_source_marker 'P80_VIDEO_RTP_FORWARDING=PASS'
            require_source_marker 'P80_AUDIO_RTP_FORWARDING=PASS'
            require_source_marker 'P78_SECOND_CTPP_OPEN=false'
            ;;
        P122)
            for marker in \
              'P80_MEDIA_ACTIVE=true' \
              'P80_DOOR_SIGNAL_ENTRYPOINT=true' \
              'P122_ONDEMAND_DOOR_SIGNAL_INSTALLED=true' \
              'P122_ONDEMAND_DOOR_PROFILE=ACTIVE_MEDIA_SINGLE' \
              'P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE' \
              'P122_ONDEMAND_DOOR_SENT=true' \
              'P122_ONDEMAND_DOOR_WRITE_COUNT=1' \
              'P122_ONDEMAND_DOOR_RESULT=%s' \
              'P122_ONDEMAND_DOOR_REJECT_GATE=%s' \
              'P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false' \
              'P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false' \
              'P78_SECOND_CTPP_OPEN=false'
            do
                require_source_marker "$marker"
            done
            forbid_source_marker 'P80_DOOR_SIGNAL_ENTRYPOINT=false'
            ;;
    esac
    echo "PROFILE_SOURCE_GATE=PASS profile=$PROFILE"
fi

if [ -n "$STRINGS_FILE" ]; then
    [ -f "$STRINGS_FILE" ] || fail_binary "strings_file_absent"
    case "$PROFILE" in
        LEGACY)
            for marker in \
              '/run/comelit-media' \
              'P80_MEDIA_ACTIVE=true' \
              'P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT' \
              'P80_MEDIA_AUTO_CLOSE_3000MS=false' \
              'P80_DOOR_SIGNAL_ENTRYPOINT=false' \
              'P80_VIDEO_RTP_FORWARDING=PASS' \
              'P80_AUDIO_RTP_FORWARDING=PASS' \
              'P80_WRAPPER_PROFILE_MISMATCH=true' \
              'P78_SECOND_CTPP_OPEN=false' \
              'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
            do
                require_binary_marker "$marker"
            done
            ;;
        P122)
            for marker in \
              '/run/comelit-media' \
              'P80_MEDIA_ACTIVE=true' \
              'P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT' \
              'P80_DOOR_SIGNAL_ENTRYPOINT=true' \
              'P122_ONDEMAND_DOOR_SIGNAL_INSTALLED=true' \
              'P122_ONDEMAND_DOOR_PROFILE=ACTIVE_MEDIA_SINGLE' \
              'P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE' \
              'P122_ONDEMAND_DOOR_SENT=true' \
              'P122_ONDEMAND_DOOR_WRITE_COUNT=1' \
              'P122_ONDEMAND_DOOR_RESULT=%s' \
              'P122_ONDEMAND_DOOR_REJECT_GATE=%s' \
              'P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false' \
              'P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false' \
              'P80_VIDEO_RTP_FORWARDING=PASS' \
              'P80_AUDIO_RTP_FORWARDING=PASS' \
              'P78_SECOND_CTPP_OPEN=false'
            do
                require_binary_marker "$marker"
            done
            forbid_binary_marker 'P80_DOOR_SIGNAL_ENTRYPOINT=false'
            ;;
    esac
    echo "PROFILE_BINARY_GATE=PASS profile=$PROFILE"
fi
