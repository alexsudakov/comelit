#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
MEDIA="$ROOT/safety-poc/research/media/v1"
OUT_DIR="${1:-$ROOT/safety-poc/research/media/v1/artifacts/pausable-p2p}"
SOURCE="$OUT_DIR/comelit-media-research.c"
BINARY="$OUT_DIR/comelit-media-research"

mkdir -p "$OUT_DIR"
python3 "$MEDIA/entrance_research_stage_interlock_transform.py" \
  --research \
  --source "$ROOT/safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c" \
  --output "$SOURCE"

if [[ "${RESEARCH_HOST_SELF_TEST:-0}" == "1" ]]; then
  cc "$MEDIA/research_stage_stub_helper.c" -o "$BINARY"
  chmod 700 "$BINARY"
  echo "RESEARCH_HELPER_BUILD=HOST_STUB"
  echo "RESEARCH_HELPER_BINARY=$BINARY"
  exit 0
fi

if ! command -v musl-gcc >/dev/null 2>&1; then
  echo "RESEARCH_HELPER_BUILD=FAIL_CLOSED_MUSL_UNAVAILABLE" >&2
  echo "Docker is intentionally not used in this sandbox; run the CT120 musl lane outside this worktree." >&2
  exit 78
fi

echo "RESEARCH_HELPER_BUILD=FAIL_CLOSED_REAL_MUSL_LANE_REQUIRED" >&2
echo "This sandbox build script does not invoke docker or the real panel." >&2
exit 78
