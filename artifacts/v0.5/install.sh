#!/usr/bin/env bash
set -Eeuo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

B64="$WORK/installer.sh.gz.b64"
GZ="$WORK/installer.sh.gz"
INSTALLER="$WORK/upgrade_comelit_door_safety_poc_v0.5_ct120.sh"

EXPECTED_B64_SHA256="104e4eb7f9c30d3a149a67f47284c2f412d761ae641204540de28589855d45d5"
EXPECTED_GZ_SHA256="bf49734d211ecea73cb7d04d4cc82c0d17d09d6712dcca3a1a2062b8fe754982"
EXPECTED_INSTALLER_SHA256="7dc2adea01b6c0e87654f9263b498a3fae62761c645c91cd143cc4bebf6603a7"

cat \
  "$DIR/installer.sh.gz.b64.part00" \
  "$DIR/installer.sh.gz.b64.part01" \
  "$DIR/installer.sh.gz.b64.part02" \
  "$DIR/installer.sh.gz.b64.part03" \
  > "$B64"

actual="$(sha256sum "$B64" | awk '{print $1}')"
echo "EXPECTED_B64_SHA256=$EXPECTED_B64_SHA256"
echo "ACTUAL_B64_SHA256=$actual"
[[ "$actual" == "$EXPECTED_B64_SHA256" ]] || { echo "B64_INTEGRITY=FAIL" >&2; exit 10; }
echo "B64_INTEGRITY=PASS"

base64 -d "$B64" > "$GZ"
actual="$(sha256sum "$GZ" | awk '{print $1}')"
echo "EXPECTED_GZ_SHA256=$EXPECTED_GZ_SHA256"
echo "ACTUAL_GZ_SHA256=$actual"
[[ "$actual" == "$EXPECTED_GZ_SHA256" ]] || { echo "GZ_INTEGRITY=FAIL" >&2; exit 11; }
echo "GZ_INTEGRITY=PASS"

gzip -dc "$GZ" > "$INSTALLER"
actual="$(sha256sum "$INSTALLER" | awk '{print $1}')"
echo "EXPECTED_INSTALLER_SHA256=$EXPECTED_INSTALLER_SHA256"
echo "ACTUAL_INSTALLER_SHA256=$actual"
[[ "$actual" == "$EXPECTED_INSTALLER_SHA256" ]] || { echo "INSTALLER_INTEGRITY=FAIL" >&2; exit 12; }
echo "INSTALLER_INTEGRITY=PASS"

chmod 700 "$INSTALLER"
"$INSTALLER"
