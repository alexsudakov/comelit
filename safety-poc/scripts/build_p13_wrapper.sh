#!/usr/bin/env bash
# =============================================================================
# Deterministic P13 wrapper build/install procedure (CT120, root).
#
# Chain of provenance (reviewable in Git):
#
#   deploy/p13_wrapper_template.sh            <- reviewed, versioned template
#   + scripts/build_p13_wrapper.sh           <- reviewed build procedure
#   + pinned native holder identity          <- verified against expected SHA
#   => installed /usr/local/sbin/comelit-p13-door-wrapper
#   => independently derived expected SHA-256
#   => deploy/p13_wrapper_manifest.json      <- Git-reviewed manifest
#   => preflight compares installed wrapper against the manifest SHA
#
# The expected SHA is derived by this build from the reviewed template + pinned
# holder, and is recorded in the Git-tracked manifest BEFORE any preflight.
# The operator never computes the expected SHA from the installed file.
#
# Usage (root, on CT120, in the repo):
#   export P13_HOLDER_PATH=/root/comelit-p13-native/comelit_p13_holder
#   export P13_HOLDER_SHA256=<sha256 of the holder artifact>
#   bash safety-poc/scripts/build_p13_wrapper.sh
#
# After the build, commit deploy/p13_wrapper_manifest.json so the expected
# identity is reviewed and pinned in Git.
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TEMPLATE="$REPO_ROOT/safety-poc/deploy/p13_wrapper_template.sh"
MANIFEST="$REPO_ROOT/safety-poc/deploy/p13_wrapper_manifest.json"
DEST=/usr/local/sbin/comelit-p13-door-wrapper
HOLDER_PATH="${P13_HOLDER_PATH:-}"
HOLDER_SHA256="${P13_HOLDER_SHA256:-}"

[[ "${EUID}" -eq 0 ]] || { echo "P13_BUILD_REQUIRES_ROOT=true"; exit 1; }
[[ -n "$HOLDER_PATH" && -n "$HOLDER_SHA256" ]] || { echo "P13_BUILD_HOLDER_IDENTITY_MISSING=true"; exit 1; }
[[ -f "$TEMPLATE" ]] || { echo "P13_BUILD_TEMPLATE_ABSENT=true"; exit 1; }
[[ -x "$HOLDER_PATH" ]] || { echo "P13_BUILD_HOLDER_ABSENT=true"; exit 1; }

ACTUAL_HOLDER_SHA="$(sha256sum "$HOLDER_PATH" | awk '{print $1}')"
[[ "$ACTUAL_HOLDER_SHA" == "$HOLDER_SHA256" ]] || { echo "P13_BUILD_HOLDER_SHA256=FAIL"; exit 1; }

TEMPLATE_SHA256="$(sha256sum "$TEMPLATE" | awk '{print $1}')"

# Substitute the holder path into the template and install.
sed "s|__P13_HOLDER_PATH__|$HOLDER_PATH|g" "$TEMPLATE" > "$DEST"
chmod 700 "$DEST"
chown root:root "$DEST"

INSTALLED_SHA256="$(sha256sum "$DEST" | awk '{print $1}')"

# Record the independently derived expected identity in the Git-tracked manifest.
cat > "$MANIFEST" <<EOF
{
  "schema": 1,
  "status": "BUILT",
  "template_sha256": "$TEMPLATE_SHA256",
  "holder_sha256": "$HOLDER_SHA256",
  "wrapper_sha256": "$INSTALLED_SHA256",
  "build_procedure": "safety-poc/scripts/build_p13_wrapper.sh",
  "destination": "/usr/local/sbin/comelit-p13-door-wrapper"
}
EOF
chmod 644 "$MANIFEST"

echo "P13_BUILD_COMPLETE=true"
echo "P13_WRAPPER_TEMPLATE_SHA256=$TEMPLATE_SHA256"
echo "P13_WRAPPER_HOLDER_SHA256=$HOLDER_SHA256"
echo "P13_WRAPPER_INSTALLED_SHA256=$INSTALLED_SHA256"
echo "P13_WRAPPER_MANIFEST=$MANIFEST"
echo "P13_NEXT_STEP=commit deploy/p13_wrapper_manifest.json"
