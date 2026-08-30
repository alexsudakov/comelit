#!/usr/bin/env bash
# =============================================================================
# CT120 manual non-actuating P13 preflight + public-safe evidence collection
#
# Запуск ОТ ROOT на CT120 (авторизованный путь, переданный оператором):
#
#   export P13_EXPECTED_WRAPPER_SHA256="<sha256 от root:/usr/local/sbin/comelit-p13-door-wrapper>"
#   bash /root/comelit-git/safety-poc/scripts/ct120_p13_preflight_manual.sh
#
# Что делает:
#   1. гарантирует ветку feat/p13-one-shot-actuation и чистый worktree
#   2. запускает p13_actuation_preflight.sh (non-actuating)
#   3. собирает публично-безопасное evidence (только хэши/маркеры)
#   4. ПУШИТ evidence-ветку evidence/p13-preflight-<STAMP>
#   5. НИКАКОГО физического Door send и actuator-команд не выполняет
#
# Требования к среде CT120:
#   - root (EUID=0)
#   - репозиторий /root/comelit-git (клон alexsudakov/comelit)
#   - wrapper: /usr/local/sbin/comelit-p13-door-wrapper (mode 700, root)
#   - payload: /root/comelit-p13-actuator-prep/real-door-payloads.json (mode 600)
#   - git push-токен с правами на alexsudakov/comelit:
#       export GITHUB_TOKEN_COMELIT="<token>"
#     (или GIT_ASKPASS, настроенный на CT120)
# =============================================================================
set -Eeuo pipefail
umask 077

REPO_ROOT="${COMELIT_REPO_ROOT:-/root/comelit-git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPECTED_BRANCH=feat/p13-one-shot-actuation

[[ "${EUID}" -eq 0 ]] || { echo "CT120_P13_MANUAL_REQUIRES_ROOT=true"; exit 1; }

echo "CT120_P13_MANUAL_START=true"

# ---- 0. identity -----------------------------------------------------------
cd "$REPO_ROOT"
git fetch origin --prune 2>/dev/null || true
git checkout -q "$EXPECTED_BRANCH" 2>/dev/null || git checkout -q -b "$EXPECTED_BRANCH" origin/"$EXPECTED_BRANCH"
HEAD="$(git rev-parse HEAD)"
TREE="$(git rev-parse HEAD^{tree})"
[[ -z "$(git status --porcelain)" ]] || { echo "CT120_P13_MANUAL_WORKTREE_DIRTY=true"; exit 1; }
echo "CT120_P13_MANUAL_HEAD=$HEAD"
echo "CT120_P13_MANUAL_TREE=$TREE"

# ---- 1. non-actuating preflight ---------------------------------------------
if ! bash "$POC_ROOT/scripts/p13_actuation_preflight.sh" | tee /tmp/p13_preflight_$HEAD.log; then
    echo "CT120_P13_MANUAL_PREFLIGHT=FAIL"
    exit 1
fi
echo "CT120_P13_MANUAL_PREFLIGHT=PASS"

# ---- 2. collect public-safe evidence (hashes/markers only) -------------------
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO_ROOT/evidence/p13-preflight-$STAMP"
mkdir -p "$EVIDENCE_DIR"

cp /tmp/p13_preflight_$HEAD.log "$EVIDENCE_DIR/preflight.log"
chmod 600 "$EVIDENCE_DIR/preflight.log"

# дополнительные маркеры: только хэши/факты, без значений identity
{
    echo "P13_PREFLIGHT_EVIDENCE_STAMP=$STAMP"
    echo "P13_PREFLIGHT_EVIDENCE_HEAD=$HEAD"
    echo "P13_PREFLIGHT_EVIDENCE_TREE=$TREE"
    echo "P13_PREFLIGHT_WRAPPER_SHA256=${P13_EXPECTED_WRAPPER_SHA256:-UNSET}"
    PAYLOAD_SHA="$(sha256sum /root/comelit-p13-actuator-prep/real-door-payloads.json 2>/dev/null | awk '{print $1}')"
    echo "P13_PREFLIGHT_PAYLOAD_SHA256=${PAYLOAD_SHA:-UNSET}"
    echo "P13_PREFLIGHT_AUDIT_VERIFIED=$(grep -c 'AUDIT_SINK_VERIFIED=PASS' /tmp/p13_preflight_$HEAD.log || true)"
    echo "P13_PREFLIGHT_ACTUATION_IMPLEMENTED=$(grep -c 'ACTUATION_TRANSPORT_IMPLEMENTED=true' /tmp/p13_preflight_$HEAD.log || true)"
    echo "P13_PREFLIGHT_PHYSICAL_DOOR_ACTION=false"
    echo "P13_PREFLIGHT_ACTUATOR_COMMAND_ATTEMPTED=false"
    echo "P13_PREFLIGHT_EXPLICIT_LIVE_TEST_APPROVAL=false"
    echo "P13_PREFLIGHT_LIVE_TEST_READY=false"
} > "$EVIDENCE_DIR/MANIFEST.txt"
chmod 600 "$EVIDENCE_DIR/MANIFEST.txt"

# ---- 3. commit + push evidence branch ----------------------------------------
cd "$REPO_ROOT"
git add "evidence/p13-preflight-$STAMP/"
git -c user.name="hermes" -c user.email="hermes@localhost" commit -q -m "evidence: P13 non-actuating preflight $STAMP (HEAD $HEAD)"

if [[ -n "${GITHUB_TOKEN_COMELIT:-}" ]]; then
    cat > /tmp/git-askpass-p13.sh <<EOF
#!/bin/bash
printf '%s\n' "\${GITHUB_TOKEN_COMELIT:-}"
EOF
    chmod 700 /tmp/git-askpass-p13.sh
    GIT_ASKPASS=/tmp/git-askpass-p13.sh GIT_TERMINAL_PROMPT=0 \
        git push origin "evidence/p13-preflight-$STAMP" 2>&1 | tail -2
    rm -f /tmp/git-askpass-p13.sh
else
    echo "CT120_P13_MANUAL_PUSH_SKIPPED=true (GITHUB_TOKEN_COMELIT не задан)"
fi

echo "CT120_P13_MANUAL_EVIDENCE_DIR=$EVIDENCE_DIR"
echo "CT120_P13_MANUAL_COMPLETE=true"
echo "P13_NON_ACTUATING_PREFLIGHT=PASS"
echo "PHYSICAL_DOOR_ACTION=false"
echo "EXPLICIT_LIVE_TEST_APPROVAL=false"
echo "LIVE_TEST_READY=false"
