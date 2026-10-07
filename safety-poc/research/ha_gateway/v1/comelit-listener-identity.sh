#!/bin/sh
# Read-only Comelit listener identity helper.
# COMELIT_PROC_ROOT is a fixture-only alternate proc root.  The helper appends
# fixed proc-relative paths only; it never accepts user supplied PID/path names.
#
# Source-derived identity rule:
# - custom_components/comelit/runtime.py:41 spawns the persistent listener from
#   native/comelit-v4; runtime.py:44 uses /run/comelit-p2p.
# - custom_components/comelit/media_transport.py:59 spawns the media/Mini App
#   helper from native/comelit-media; media_transport.py:62 uses
#   /run/comelit-media.
# Both production spawn sites pass zero command-line arguments, so argv/env are
# not role signals and are not read or emitted.

COMELIT_LISTENER_EXE_ALLOWLIST="/config/custom_components/comelit/native/comelit-v4 /usr/share/hassio/homeassistant/custom_components/comelit/native/comelit-v4"
COMELIT_EXCLUDED_EXE_NAMES="comelit-media comelit-media-research-stage7-v2"
COMELIT_LISTENER_RUN_DIR="/run/comelit-p2p"
EXPECTED_EXE_SHA256="${COMELIT_EXPECTED_LISTENER_SHA256:-}"
PROC_ROOT="${COMELIT_PROC_ROOT:-/proc}"

STATUS="ERROR"
LISTENER_READY="UNKNOWN"
LISTENER_PID=""
LISTENER_PROCESS_START_TICKS=""
LISTENER_PROCESS_GENERATION=""
LISTENER_EXE_SHA256=""
LISTENER_EXE_MATCHES_EXPECTED="UNKNOWN"
LISTENER_SOCKET_PRESENT="false"
LISTENER_SOCKET_PROTOCOL="NONE"
LISTENER_SOCKET_INODE=""
LISTENER_SOCKET_LOCAL=""
LISTENER_SOCKET_REMOTE="UNCONNECTED"
LISTENER_SOCKET_FINGERPRINT_SHA256=""
LISTENER_TRANSPORT_GENERATION=""
LISTENER_RUN_DIR_CORROBORATION="UNKNOWN"
MATCH_RULE=""
CANDIDATE_COUNT="0"
BOOT_ID_PRESENT="false"
PROCESS_VIEW="UNAVAILABLE"
SECRETS_EMITTED="false"
WRITES_PERFORMED="false"
QUERIES_PERFORMED="0"

emit() {
    printf '%s=%s\n' STATUS "$STATUS"
    printf '%s=%s\n' LISTENER_READY "$LISTENER_READY"
    printf '%s=%s\n' LISTENER_PID "$LISTENER_PID"
    printf '%s=%s\n' LISTENER_PROCESS_START_TICKS "$LISTENER_PROCESS_START_TICKS"
    printf '%s=%s\n' LISTENER_PROCESS_GENERATION "$LISTENER_PROCESS_GENERATION"
    printf '%s=%s\n' LISTENER_EXE_SHA256 "$LISTENER_EXE_SHA256"
    printf '%s=%s\n' LISTENER_EXE_MATCHES_EXPECTED "$LISTENER_EXE_MATCHES_EXPECTED"
    printf '%s=%s\n' LISTENER_SOCKET_PRESENT "$LISTENER_SOCKET_PRESENT"
    printf '%s=%s\n' LISTENER_SOCKET_PROTOCOL "$LISTENER_SOCKET_PROTOCOL"
    printf '%s=%s\n' LISTENER_SOCKET_INODE "$LISTENER_SOCKET_INODE"
    printf '%s=%s\n' LISTENER_SOCKET_LOCAL "$LISTENER_SOCKET_LOCAL"
    printf '%s=%s\n' LISTENER_SOCKET_REMOTE "$LISTENER_SOCKET_REMOTE"
    printf '%s=%s\n' LISTENER_SOCKET_FINGERPRINT_SHA256 "$LISTENER_SOCKET_FINGERPRINT_SHA256"
    printf '%s=%s\n' LISTENER_TRANSPORT_GENERATION "$LISTENER_TRANSPORT_GENERATION"
    printf '%s=%s\n' LISTENER_RUN_DIR_CORROBORATION "$LISTENER_RUN_DIR_CORROBORATION"
    printf '%s=%s\n' MATCH_RULE "$MATCH_RULE"
    printf '%s=%s\n' CANDIDATE_COUNT "$CANDIDATE_COUNT"
    printf '%s=%s\n' BOOT_ID_PRESENT "$BOOT_ID_PRESENT"
    printf '%s=%s\n' PROCESS_VIEW "$PROCESS_VIEW"
    printf '%s=%s\n' SECRETS_EMITTED "$SECRETS_EMITTED"
    printf '%s=%s\n' WRITES_PERFORMED "$WRITES_PERFORMED"
    printf '%s=%s\n' QUERIES_PERFORMED "$QUERIES_PERFORMED"
}

help_text() {
    cat <<'EOF'
Usage: comelit-listener-identity.sh

Zero-argument read-only helper.  It inspects a fixed /proc surface and emits
allowlisted KEY=VALUE fields for Comelit listener identity.  The deciding rule
is source-derived executable identity: production runtime.py:41 launches
native/comelit-v4 for the persistent listener, while media_transport.py:59
launches native/comelit-media for media/Mini App.  runtime.py:44 documents
/run/comelit-p2p as optional read-only corroboration; if that signal is not
observable it remains UNKNOWN.  COMELIT_PROC_ROOT may point tests at a synthetic
proc root; no PID, path, process name or socket argument is accepted.
EOF
}

unsupported_argument() {
    STATUS="UNSUPPORTED_ARGUMENT"
    MATCH_RULE="zero-argument contract"
    emit
    exit 2
}

case "$#" in
    0) ;;
    1)
        if [ "$1" = "help" ]; then
            help_text
            exit 0
        fi
        unsupported_argument
        ;;
    *) unsupported_argument ;;
esac

hash_value() {
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$1" | sha256sum | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then
        printf '%s' "$1" | openssl dgst -sha256 | awk '{print $NF}'
    else
        return 1
    fi
}

hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" 2>/dev/null | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$1" 2>/dev/null | awk '{print $NF}'
    else
        return 1
    fi
}

inc_query() {
    QUERIES_PERFORMED=$((QUERIES_PERFORMED + 1))
}

is_allowlisted_exe() {
    target="$1"
    for allowed in $COMELIT_LISTENER_EXE_ALLOWLIST; do
        [ "$target" = "$allowed" ] && return 0
    done
    return 1
}

is_excluded_exe() {
    target="$1"
    name=${target##*/}
    for excluded in $COMELIT_EXCLUDED_EXE_NAMES; do
        case "$name" in
            "$excluded"|"$excluded"-*) return 0 ;;
        esac
    done
    return 1
}

stat_start_ticks() {
    file="$1"
    [ -r "$file" ] || return 1
    sed 's/^.*) //' "$file" 2>/dev/null | awk '{print $20}'
}

hex_to_dec() {
    h="$1"
    printf '%d' "0x$h" 2>/dev/null
}

hex_ipv4_to_dec() {
    iphex="$1"
    [ "${#iphex}" -eq 8 ] || {
        printf '%s' "$iphex"
        return
    }
    b1=$(hex_to_dec "$(printf '%s' "$iphex" | cut -c7-8)")
    b2=$(hex_to_dec "$(printf '%s' "$iphex" | cut -c5-6)")
    b3=$(hex_to_dec "$(printf '%s' "$iphex" | cut -c3-4)")
    b4=$(hex_to_dec "$(printf '%s' "$iphex" | cut -c1-2)")
    printf '%s.%s.%s.%s' "$b1" "$b2" "$b3" "$b4"
}

tuple_to_addr() {
    tuple="$1"
    iphex=${tuple%:*}
    porthex=${tuple#*:}
    port=$(hex_to_dec "$porthex")
    if [ "$iphex" = "00000000" ] || [ "$iphex" = "00000000000000000000000000000000" ]; then
        ip="0.0.0.0"
    elif [ "${#iphex}" -eq 8 ]; then
        ip=$(hex_ipv4_to_dec "$iphex")
    else
        ip="$iphex"
    fi
    printf '%s:%s' "$ip" "$port"
}

socket_row_for_inode() {
    want_inode="$1"
    proto="$2"
    table="$3"
    [ -r "$table" ] || return 1
    awk -v inode="$want_inode" -v proto="$proto" 'NR > 1 && $10 == inode { print proto "|" $2 "|" $3 "|" $10 }' "$table"
}

BOOT_ID=""
if [ -r "$PROC_ROOT/sys/kernel/random/boot_id" ]; then
    inc_query
    BOOT_ID=$(sed -n '1p' "$PROC_ROOT/sys/kernel/random/boot_id" 2>/dev/null)
    [ -n "$BOOT_ID" ] && BOOT_ID_PRESENT="true"
fi

if [ ! -d "$PROC_ROOT" ]; then
    STATUS="UNSUPPORTED_NAMESPACE"
    MATCH_RULE="proc-root-unavailable"
    emit
    exit 1
fi

set -- "$PROC_ROOT"/[0-9]*
if [ "$1" = "$PROC_ROOT/[0-9]*" ]; then
    STATUS="UNSUPPORTED_NAMESPACE"
    MATCH_RULE="no-visible-processes"
    emit
    exit 1
fi

PROCESS_VIEW="AVAILABLE"
candidate_pids=""
for procdir in "$PROC_ROOT"/[0-9]*; do
    [ -d "$procdir" ] || continue
    pid=${procdir##*/}
    exe_target=$(readlink "$procdir/exe" 2>/dev/null) || continue
    inc_query
    is_excluded_exe "$exe_target" && continue
    is_allowlisted_exe "$exe_target" || continue
    candidate_pids="${candidate_pids}${pid}
"
done

CANDIDATE_COUNT=$(printf '%s' "$candidate_pids" | sed '/^$/d' | wc -l | awk '{print $1}')
MATCH_RULE="exe-allowlist-comelit-v4-source-derived"

if [ "$CANDIDATE_COUNT" -eq 0 ]; then
    STATUS="NOT_FOUND"
    emit
    exit 1
fi

if [ "$CANDIDATE_COUNT" -gt 1 ]; then
    STATUS="AMBIGUOUS"
    emit
    exit 1
fi

LISTENER_PID=$(printf '%s' "$candidate_pids" | sed -n '/^[0-9][0-9]*$/p' | sed -n '1p')
procdir="$PROC_ROOT/$LISTENER_PID"
LISTENER_PROCESS_START_TICKS=$(stat_start_ticks "$procdir/stat" || true)
inc_query

if cwd_target=$(readlink "$procdir/cwd" 2>/dev/null); then
    inc_query
    case "$cwd_target" in
        "$COMELIT_LISTENER_RUN_DIR"|"$COMELIT_LISTENER_RUN_DIR"/*)
            LISTENER_RUN_DIR_CORROBORATION="true"
            ;;
        *)
            LISTENER_RUN_DIR_CORROBORATION="false"
            ;;
    esac
fi

if [ -n "$BOOT_ID" ] && [ -n "$LISTENER_PROCESS_START_TICKS" ]; then
    LISTENER_PROCESS_GENERATION=$(hash_value "${BOOT_ID}|${LISTENER_PID}|${LISTENER_PROCESS_START_TICKS}" || true)
fi

LISTENER_EXE_SHA256=$(hash_file "$procdir/exe" || true)
if [ -n "$EXPECTED_EXE_SHA256" ] && [ -n "$LISTENER_EXE_SHA256" ]; then
    if [ "$LISTENER_EXE_SHA256" = "$EXPECTED_EXE_SHA256" ]; then
        LISTENER_EXE_MATCHES_EXPECTED="true"
    else
        LISTENER_EXE_MATCHES_EXPECTED="false"
    fi
fi

socket_inodes=""
if [ -d "$procdir/fd" ]; then
    for fd in "$procdir"/fd/*; do
        [ -e "$fd" ] || [ -L "$fd" ] || continue
        fd_target=$(readlink "$fd" 2>/dev/null) || continue
        case "$fd_target" in
            socket:\[*\])
                inode=$(printf '%s' "$fd_target" | sed 's/^socket:\[\([0-9][0-9]*\)\]$/\1/')
                socket_inodes="${socket_inodes}${inode}
"
                ;;
        esac
    done
    inc_query
fi

socket_rows=""
for inode in $(printf '%s' "$socket_inodes" | sed '/^$/d' | sort -n | uniq); do
    for spec in "udp:$PROC_ROOT/net/udp" "udp:$PROC_ROOT/net/udp6" "tcp:$PROC_ROOT/net/tcp" "tcp:$PROC_ROOT/net/tcp6"; do
        proto=${spec%%:*}
        table=${spec#*:}
        rows=$(socket_row_for_inode "$inode" "$proto" "$table" || true)
        [ -n "$rows" ] && socket_rows="${socket_rows}${rows}
"
    done
done

socket_count=$(printf '%s' "$socket_rows" | sed '/^$/d' | wc -l | awk '{print $1}')
if [ "$socket_count" -gt 1 ]; then
    STATUS="AMBIGUOUS"
    MATCH_RULE="${MATCH_RULE}; multiple-transport-sockets"
    emit
    exit 1
fi

if [ "$socket_count" -eq 1 ]; then
    row=$(printf '%s' "$socket_rows" | sed -n '/./p' | sed -n '1p')
    LISTENER_SOCKET_PRESENT="true"
    LISTENER_SOCKET_PROTOCOL=${row%%|*}
    rest=${row#*|}
    local_tuple=${rest%%|*}
    rest=${rest#*|}
    remote_tuple=${rest%%|*}
    rest=${rest#*|}
    LISTENER_SOCKET_INODE=${rest%%|*}
    LISTENER_SOCKET_LOCAL=$(tuple_to_addr "$local_tuple")
    if printf '%s' "$remote_tuple" | grep -Eq '^(00000000|00000000000000000000000000000000):0000$'; then
        LISTENER_SOCKET_REMOTE="UNCONNECTED"
    else
        LISTENER_SOCKET_REMOTE=$(tuple_to_addr "$remote_tuple")
    fi
    LISTENER_SOCKET_FINGERPRINT_SHA256=$(hash_value "${LISTENER_PROCESS_GENERATION}|${LISTENER_SOCKET_PROTOCOL}|${LISTENER_SOCKET_INODE}|${LISTENER_SOCKET_LOCAL}|${LISTENER_SOCKET_REMOTE}" || true)
    LISTENER_TRANSPORT_GENERATION="$LISTENER_SOCKET_FINGERPRINT_SHA256"
fi

STATUS="PASS"
emit
exit 0
