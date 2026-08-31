#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROD_ROOT=/opt/comelit-door-safety-poc/p13
CURRENT="$PROD_ROOT/current"

FRONT=/usr/local/sbin/hermes-comelit-dispatch
FRONT_BACKUP=/usr/local/sbin/hermes-comelit-dispatch.pre-p13-g1b-v1

RUNTIME=/usr/local/sbin/comelit-p13-hermes-dispatch
G1B_GATE=/usr/local/sbin/comelit-p13-g1b-validation

SUDOERS=/etc/sudoers.d/hermes-comelit-p13
SUDOERS_BACKUP=/root/comelit-p13-run/hermes-comelit-p13.pre-g1b-v1

EXPECTED_FRONT_SHA=5661a544fc0285cb5b0203d0534303691ba452fa0801b31d27b18732d22172a4
EXPECTED_SUDOERS_SHA=74fa37e655466b584244f292164c1bdb7478ed3ec64d3b54f320a0deefab8d45

OLD_APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST
G1B_APPROVAL=I_APPROVE_P13_G1B_IMMUTABLE_PRODUCTION_DOOR_TEST

[[ "${EUID}" -eq 0 ]]
[[ -L "$CURRENT" ]]

RELEASE="$(readlink -f "$CURRENT")"

case "$RELEASE" in
    "$PROD_ROOT/releases/"*) ;;
    *) exit 1 ;;
esac

(
    cd "$RELEASE"
    sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
)

GATE_SOURCE="$RELEASE/repo/deploy/p13_g1b_production_validation_gate.sh"

[[ -f "$GATE_SOURCE" ]]
[[ "$(sha256sum "$FRONT" | awk '{print $1}')" == "$EXPECTED_FRONT_SHA" ]]
[[ "$(sha256sum "$SUDOERS" | awk '{print $1}')" == "$EXPECTED_SUDOERS_SHA" ]]

install -d -m 700 -o root -g root /root/comelit-p13-run

cp -a "$FRONT" "$FRONT_BACKUP"
cp -a "$SUDOERS" "$SUDOERS_BACKUP"
chmod 600 "$SUDOERS_BACKUP"

install -m 755 -o root -g root "$GATE_SOURCE" "$G1B_GATE"

[[ "$(sha256sum "$G1B_GATE" | awk '{print $1}')" \
   == "$(sha256sum "$GATE_SOURCE" | awk '{print $1}')" ]]

FRONT_TMP="$(mktemp /usr/local/sbin/.hermes-comelit-dispatch.g1b.XXXXXX)"
SUDOERS_TMP="$(mktemp /etc/sudoers.d/.hermes-comelit-p13.g1b.XXXXXX)"

cleanup() {
    rm -f "$FRONT_TMP" "$SUDOERS_TMP"
}
trap cleanup EXIT

cat >"$FRONT_TMP" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

BACKUP=/usr/local/sbin/hermes-comelit-dispatch.pre-p13-observed-v1
RUNTIME=$RUNTIME
G1B_GATE=$G1B_GATE

OLD_APPROVAL=$OLD_APPROVAL
G1B_APPROVAL=$G1B_APPROVAL

case "\${SSH_ORIGINAL_COMMAND:-}" in
    comelit-p13-readiness)
        exec sudo -n "\$RUNTIME" readiness
        ;;

    "comelit-p13-observed-open \$OLD_APPROVAL")
        # Historical surface remains routed only to the production deny-only
        # dispatcher. It cannot reach the old observed gate.
        exec sudo -n "\$RUNTIME" observed-open "\$OLD_APPROVAL"
        ;;

    comelit-p13-g1b-readiness)
        exec sudo -n "\$G1B_GATE" readiness
        ;;

    "comelit-p13-g1b-open \$G1B_APPROVAL")
        exec sudo -n "\$G1B_GATE" open "\$G1B_APPROVAL"
        ;;

    *)
        exec "\$BACKUP"
        ;;
esac
EOF

chmod 755 "$FRONT_TMP"
chown root:root "$FRONT_TMP"

cat >"$SUDOERS_TMP" <<EOF
hermes-comelit ALL=(root) NOPASSWD: $RUNTIME readiness
hermes-comelit ALL=(root) NOPASSWD: $RUNTIME observed-open $OLD_APPROVAL
hermes-comelit ALL=(root) NOPASSWD: $G1B_GATE readiness
hermes-comelit ALL=(root) NOPASSWD: $G1B_GATE open $G1B_APPROVAL
EOF

chmod 440 "$SUDOERS_TMP"
chown root:root "$SUDOERS_TMP"

visudo -cf "$SUDOERS_TMP" >/dev/null

# Publish sudoers first; front only becomes reachable after sudoers validates.
mv -f "$SUDOERS_TMP" "$SUDOERS"
visudo -cf /etc/sudoers >/dev/null

mv -f "$FRONT_TMP" "$FRONT"

chmod 755 "$FRONT"
chown root:root "$FRONT"

trap - EXIT

echo 'P13_G1B_HERMES_AUTHORITY_INSTALL=PASS'
echo 'P13_G1B_HERMES_AUTHORITY_TEMPORARY=true'
echo 'P13_G1B_HERMES_READINESS_ALLOWED=true'
echo 'P13_G1B_HERMES_SINGLE_USE_OPEN_ALLOWED=true'
echo 'P13_G1B_HERMES_ARBITRARY_SHELL=false'
echo 'P13_G1B_HERMES_ARBITRARY_ROOT=false'
echo 'P13_G1B_NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'P13_G1B_PHYSICAL_DOOR_ACTION=false'
echo 'SEND_ARMED_REACHED=false'
