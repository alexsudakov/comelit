#!/usr/bin/env bash
# Install the minimum Hermes -> CT120 authority extension for P13 readiness and
# one separately-approved observed-open operation. This script performs NO
# Comelit transport and does NOT invoke the observed-open path.
set -Eeuo pipefail
umask 077

REPO=/root/comelit-git
BRANCH=feat/p13-one-shot-actuation
RUNTIME_SRC="$REPO/safety-poc/deploy/p13_hermes_ct120_runtime_dispatch.sh"
RUNTIME_DST=/usr/local/sbin/comelit-p13-hermes-dispatch
FRONT=/usr/local/sbin/hermes-comelit-dispatch
FRONT_BACKUP=/usr/local/sbin/hermes-comelit-dispatch.pre-p13-observed-v1
SUDOERS=/etc/sudoers.d/hermes-comelit-p13
EXPECTED_OLD_FRONT_SHA256=e4bb63d7939a67344eedbfaf9f01a8a0a9e1578a74665e4b84f169466eb62e63
APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST

[[ "$EUID" -eq 0 ]] || { echo 'P13_AUTHORITY_INSTALL_REQUIRES_ROOT=true'; exit 1; }
[[ -d "$REPO/.git" ]] || { echo 'P13_AUTHORITY_INSTALL_REPO_PRESENT=false'; exit 1; }
[[ "$(git -C "$REPO" branch --show-current)" == "$BRANCH" ]] || { echo 'P13_AUTHORITY_INSTALL_BRANCH=FAIL'; exit 1; }
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || { echo 'P13_AUTHORITY_INSTALL_WORKTREE_CLEAN=false'; exit 1; }
[[ -f "$RUNTIME_SRC" ]] || { echo 'P13_AUTHORITY_INSTALL_RUNTIME_SOURCE_PRESENT=false'; exit 1; }
[[ -f "$FRONT" ]] || { echo 'P13_AUTHORITY_INSTALL_FRONT_PRESENT=false'; exit 1; }
command -v visudo >/dev/null 2>&1 || { echo 'P13_AUTHORITY_INSTALL_VISUDO_PRESENT=false'; exit 1; }

# Fail closed unless the live front dispatcher is exactly the version inventoried
# before this authority extension. On re-run, accept only our already-installed
# front together with the preserved exact backup.
front_sha="$(sha256sum "$FRONT" | awk '{print $1}')"
if [[ ! -e "$FRONT_BACKUP" ]]; then
    [[ "$front_sha" == "$EXPECTED_OLD_FRONT_SHA256" ]] || {
        echo 'P13_AUTHORITY_INSTALL_OLD_FRONT_IDENTITY=FAIL'
        exit 1
    }
    cp -a "$FRONT" "$FRONT_BACKUP"
    chmod 755 "$FRONT_BACKUP"
    chown root:root "$FRONT_BACKUP"
else
    [[ "$(sha256sum "$FRONT_BACKUP" | awk '{print $1}')" == "$EXPECTED_OLD_FRONT_SHA256" ]] || {
        echo 'P13_AUTHORITY_INSTALL_BACKUP_IDENTITY=FAIL'
        exit 1
    }
fi

install -o root -g root -m 0755 "$RUNTIME_SRC" "$RUNTIME_DST"

front_tmp="$(mktemp /usr/local/sbin/.hermes-comelit-dispatch.p13.XXXXXX)"
sudoers_tmp="$(mktemp /etc/sudoers.d/.hermes-comelit-p13.XXXXXX)"
cleanup() { rm -f "$front_tmp" "$sudoers_tmp"; }
trap cleanup EXIT

cat >"$front_tmp" <<'EOF'
#!/usr/bin/env bash
# P13 front extension. All unrelated commands delegate to the exact preserved
# pre-P13 front dispatcher. No arbitrary command or argument forwarding exists.
set -Eeuo pipefail
umask 077
BACKUP=/usr/local/sbin/hermes-comelit-dispatch.pre-p13-observed-v1
RUNTIME=/usr/local/sbin/comelit-p13-hermes-dispatch
APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST

case "${SSH_ORIGINAL_COMMAND:-}" in
    comelit-p13-readiness)
        exec sudo -n "$RUNTIME" readiness
        ;;
    "comelit-p13-observed-open $APPROVAL")
        exec sudo -n "$RUNTIME" observed-open "$APPROVAL"
        ;;
    *)
        exec "$BACKUP"
        ;;
esac
EOF
chmod 755 "$front_tmp"
chown root:root "$front_tmp"

cat >"$sudoers_tmp" <<EOF
hermes-comelit ALL=(root) NOPASSWD: $RUNTIME_DST readiness
hermes-comelit ALL=(root) NOPASSWD: $RUNTIME_DST observed-open $APPROVAL
EOF
chmod 440 "$sudoers_tmp"
chown root:root "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null

# Publish sudoers first, then front. Until front is published there is no new SSH
# logical command; if front publication fails, existing behavior is unchanged.
mv -f "$sudoers_tmp" "$SUDOERS"
chmod 440 "$SUDOERS"
chown root:root "$SUDOERS"
visudo -cf /etc/sudoers >/dev/null
mv -f "$front_tmp" "$FRONT"
chmod 755 "$FRONT"
chown root:root "$FRONT"
trap - EXIT

# Local negative/positive authority checks. Readiness is intentionally NOT run
# here because it is root-only runtime validation and should be observed through
# the finished Hermes boundary after installation.
sudo -n -l -U hermes-comelit 2>/dev/null | grep -F "$RUNTIME_DST readiness" >/dev/null
sudo -n -l -U hermes-comelit 2>/dev/null | grep -F "$RUNTIME_DST observed-open $APPROVAL" >/dev/null

printf '%s\n' \
  'P13_HERMES_AUTHORITY_INSTALL=PASS' \
  'P13_HERMES_AUTHORITY_SSHD_CHANGED=false' \
  'P13_HERMES_AUTHORITY_KEYS_CHANGED=false' \
  'P13_HERMES_AUTHORITY_NETWORK_ACL_CHANGED=false' \
  'P13_HERMES_AUTHORITY_ARBITRARY_SHELL=false' \
  'P13_HERMES_AUTHORITY_ARBITRARY_ROOT=false' \
  'P13_HERMES_AUTHORITY_ALLOWED_READINESS=true' \
  'P13_HERMES_AUTHORITY_ALLOWED_OBSERVED_OPEN=true' \
  'P13_HERMES_AUTHORITY_PHYSICAL_ACTION=false' \
  'P13_HERMES_AUTHORITY_SEND_ARMED=false' \
  'P13_HERMES_AUTHORITY_RUNTIME_READY_FOR_HERMES_PREFLIGHT=true'
