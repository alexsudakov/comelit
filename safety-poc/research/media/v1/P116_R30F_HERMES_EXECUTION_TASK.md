# P116 / R30F — Hermes/Codex task: packaged R30E helper bounded live validation

Статус: **AUTHORIZED CONTROLLED LIVE / execute only after this task+contract are merged**

TASK_ID=`COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE`

Основной контракт:

```text
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_CONTRACT.md
```

Canonical parent evidence:

```text
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
safety-poc/research/media/v1/P116_R30E_CI_FINALIZATION.md
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
safety-poc/research/media/v1/P116_R27_D1_REPEAT_001A_LIVE_PROOF.md
safety-poc/research/media/v1/P116_R29F_EXIT_FORENSICS.md
```

## 1. Роли

```text
HERMES_ROLE=ORCHESTRATOR_ONLY
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
CODEX_REQUIRED=true
LIVE_AUTHORIZED=true
MAX_LIVE_INVOCATIONS=10
HA_RESTART_ALLOWED=false
HA_RELOAD_ALLOWED=false
HA_DEPLOY_ALLOWED=false
DOOR_ALLOWED=false
GATE_ALLOWED=false
```

Hermes не пишет executable code и не принимает protocol decisions за Codex.

Не останавливайся на обычных implementation/test/CI defects: Codex должен исправлять их автономно внутри утверждённого scope, а Hermes — повторно направлять их Codex при необходимости. Эскалируй пользователю только blocker, для решения которого требуется новое архитектурное/семантическое решение, расширение scope, новое live-действие за пределами этого контракта, credential или отдельное разрешение.

## 2. Bootstrap

Работать только от fresh `origin/main`.

На старте:

1. `git fetch origin main`;
2. зафиксировать фактический `origin/main` SHA;
3. убедиться, что R30E и CI finalization merged;
4. убедиться, что оба R30F docs существуют в fresh main;
5. создать отдельную branch/worktree от fresh main;
6. remote оставить credential-free;
7. repo-local credential helper настроить через `/root/.config/git/comelit.credentials` там, где нужен GitHub access;
8. token/credential не печатать.

Executor gate:

```text
CODEX_COMMAND_PRESENT=true|false
CODEX_VERSION=<version-or-unavailable>
ACTUAL_EXECUTOR=codex-cli|other|unavailable
```

Если `codex-cli` недоступен — STOP `RESULT=BLOCKED_EXECUTOR_UNAVAILABLE`.

## 3. Exact artifact

Canonical live artifact:

```text
custom_components/comelit/native/comelit-media
EXPECTED_PACKAGED_BINARY_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
EXPECTED_CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
```

Перед live Codex обязан доказать:

```text
PACKAGED_BINARY_SHA_GATE=PASS
TRANSPORT_PIN_SHA_GATE=PASS
R30E_PROVENANCE_READY_GATE=PASS
```

Никакой rebuild/candidate substitution в R30F не допускается.

## 4. Codex child lifecycle

Используй один bounded Codex context по возможности для всей задачи:

```text
inspect current main + prior runners/evidence
-> design minimal R30F exact-artifact runner
-> implement runner + static contract tests
-> dry-run/preflight
-> focused tests
-> full offline tests/static safety
-> diagnose/fix ordinary runner defects
-> live attempt 1
-> classify evidence
-> optional bounded repeat only under attempt policy
-> safe teardown/listener restore after every attempt
-> finalize redacted result doc
-> full offline regression
-> diff/scope/safety review
```

Если Codex sandbox не может обращаться к CT120/HA test-control, Hermes выполняет только exact mechanical command sequence, сформированную Codex, и возвращает полный redacted stdout/stderr тому же Codex context.

## 5. Runner implementation

Создать:

```text
safety-poc/research/media/v1/ct120_run_p116_r30f_packaged_helper_live.sh
safety-poc/tests/test_p116_r30f_packaged_helper_live_contract.py
```

Runner должен использовать existing proven primitives из R27/R29 только как implementation references. Не запускать R27 runner целиком.

Обязательные свойства:

- exact packaged helper path/hash;
- no candidate build;
- no source transform;
- one self-activation maximum per attempt;
- one initial media/video request maximum per attempt;
- no repeat `0x001A`;
- no refresh loop;
- no automatic media retry;
- no Door/Gate;
- cleanup trap installed before live network action;
- production listener pre/post gates;
- hard timeout;
- no raw payload/token/SDP identifier output;
- `--dry-run` with zero Comelit TX and listener untouched;
- final useful result block LAST in output.

Do not edit existing R27/R29 runners.

## 6. Production listener procedure

Before each live attempt, query existing HA test-control state and require:

```text
LISTENER_BEFORE_RUNNING=true
LISTENER_BEFORE_READY=true
LISTENER_BEFORE_LAST_ERROR=null
PRODUCTION_MEDIA_ACTIVE_BEFORE=false
```

Then, only if runner requires exclusive ownership, stop/release the Comelit production listener using the already-existing test-control mechanism.

Immediately install/retain cleanup that restores the listener even on failure, timeout or signal.

After each attempt require:

```text
LISTENER_AFTER_RUNNING=true
LISTENER_AFTER_READY=true
LISTENER_AFTER_LAST_ERROR=null
PRODUCTION_MEDIA_ACTIVE_AFTER=false
LISTENER_RESTORE=PASS
RESIDUAL_HELPER_PROCESS=false
```

If restore fails: STOP immediately. No further live attempts.

Do not restart/reload HA.

## 7. Attempt budget

`MAX_LIVE_INVOCATIONS=10` is a ceiling, not a target.

Attempt 1 is always the minimal exact-artifact attempt.

Stop after first full success.

Identical failure may be repeated only when Codex explicitly states why the repeat distinguishes transient from stable behavior and cleanup is fully green.

If the same terminal signature occurs 3 times under equivalent state/gates:

```text
TERMINAL_SIGNATURE_STABLE=true
```

STOP; do not consume remaining attempts blindly.

Diagnostic-only runner fixes are allowed between attempts only if they do not modify protocol/network semantics. Re-run offline tests before next live attempt.

Any proposal to send a new message, add retry, change ordering/cadence, repeat `0x001A`, refresh, or modify helper/source is a semantic blocker and must be returned to user instead of executed.

## 8. Required evidence

For each attempt collect redacted/scalar markers required by the contract, including exact helper execution, bootstrap/CTPP/RTPC/RTP state, helper rc/terminal stage, cleanup/listener restoration, and forbidden-action counters.

At minimum final result must make explicit:

```text
EXACT_PACKAGED_HELPER_EXECUTED=true|false
LIVE_INVOCATIONS=<n>
VIDEO_RTP_PACKET_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
AUDIO_RTP_PACKET_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
TERMINAL_STAGE=<stage>
TERMINAL_REASON=<reason>
TEARDOWN_COMPLETE=true|false
LISTENER_RESTORE=PASS|FAIL
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
REPEAT_001A_SENT_COUNT=0
REFRESH_LOOP_STARTED_COUNT=0
RETRY_MEDIA_REQUEST_COUNT=0
```

Do not invent zero/PASS for unavailable markers. Use `UNAVAILABLE_NOT_INSTRUMENTED` where appropriate.

## 9. Offline gates before first live

Minimum:

```text
bash -n safety-poc/research/media/v1/ct120_run_p116_r30f_packaged_helper_live.sh
python3 -m unittest safety-poc/tests/test_p116_r30f_packaged_helper_live_contract.py
python3 -m unittest discover -s safety-poc/tests -p 'test_*.py'
python3 safety-poc/scripts/static_safety_check.py
git diff --check
```

Plus relevant compile/CLI safety steps from `.github/workflows/offline-safety.yml`.

Dry-run is mandatory and must prove:

```text
DRY_RUN=PASS
DRY_RUN_NETWORK_TX=0
DRY_RUN_LISTENER_TOUCHED=false
```

## 10. Live command ownership

Codex constructs the exact CT120 command sequence and expected gates.

Hermes may execute it verbatim on CT120 as mechanical relay. Hermes does not edit it, add retries, choose another binary, or change protocol behavior.

The exact packaged binary may be copied/materialized to a temp live directory only after SHA verification; preserve mode and bytes. Runtime sibling libraries may be copied from the same accepted repo package. No source rebuild.

Credentials/tokens are consumed only through existing secure mechanisms; never print contents.

## 11. Write scope

Strictly follow contract §12.

Default allowed files:

```text
safety-poc/research/media/v1/ct120_run_p116_r30f_packaged_helper_live.sh
safety-poc/tests/test_p116_r30f_packaged_helper_live_contract.py
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
```

No `custom_components/comelit/**` changes.
No packaged binary changes.
No existing R27/R29 runner edits.

## 12. Result document

Create/update:

```text
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
```

The final useful Hermes block must be LAST and contain at least:

```text
=== COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
TASK_ID=COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE
BASE_SHA=<fresh-main-at-start>
FINAL_SHA=<branch-head>
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=<version>
PACKAGED_BINARY_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
PACKAGED_BINARY_SHA_GATE=<PASS|FAIL>
EXACT_PACKAGED_HELPER_EXECUTED=<true|false>
LIVE_AUTHORIZED=true
MAX_LIVE_INVOCATIONS=10
LIVE_INVOCATIONS=<n>
SUCCESSFUL_ATTEMPT=<index|none>
TERMINAL_SIGNATURE_STABLE=<true|false>
UPSTREAM_BOOTSTRAP_COMPLETED=<true|false|UNAVAILABLE_NOT_INSTRUMENTED>
PSEUDOTCP_OPEN_FINAL=<true|false|UNAVAILABLE_NOT_INSTRUMENTED>
CTPP_REGISTRATION_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
CALL_INIT_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
SELF_ACTIVATION_SENT_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
INITIAL_MEDIA_REQUEST_SENT_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
RTPC_OPEN_SENT_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
RTPC_OPEN_RESPONSE_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
VIDEO_RTP_PACKET_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
AUDIO_RTP_PACKET_COUNT=<n|UNAVAILABLE_NOT_INSTRUMENTED>
VIDEO_RTP_STARTED=<true|false|UNAVAILABLE_NOT_INSTRUMENTED>
HELPER_RC=<rc|none>
TERMINAL_STAGE=<stage>
TERMINAL_REASON=<reason>
TEARDOWN_COMPLETE=<true|false>
RESIDUAL_HELPER_PROCESS=<true|false>
LISTENER_BEFORE_READY=<true|false>
LISTENER_STOP_GATE=<PASS|FAIL|NOT_REQUIRED>
LISTENER_AFTER_READY=<true|false>
LISTENER_AFTER_LAST_ERROR=<value>
LISTENER_RESTORE=<PASS|FAIL>
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
REPEAT_001A_SENT_COUNT=0
REFRESH_LOOP_STARTED_COUNT=0
RETRY_MEDIA_REQUEST_COUNT=0
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
FULL_OFFLINE_TESTS=<PASS|FAIL>
STATIC_SAFETY=<PASS|FAIL>
OFFLINE_SAFETY=<PASS|FAIL|UNAVAILABLE>
VALIDATE_HACS=<PASS|FAIL|UNAVAILABLE>
PR=<number-or-none>
RESULT=<PASS|INCONCLUSIVE|BLOCKED|FAIL>
=== END COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
```

## 13. Git/GitHub

After local/live result and regression PASS:

- inspect diff/scope;
- commit/push through standard credential helper;
- PR to fresh main if permission allows;
- wait `offline-safety` and `Validate HACS`;
- return ordinary CI defect to same Codex context;
- no merge on fail/pending;
- if PR create permission fails, return branch/head for ChatGPT.

## 14. STOP

After R30F result, STOP.

Do not deploy/reload/restart HA, do not open HA viewer, do not start screenshot/recording validation, and do not begin a new protocol hypothesis automatically.
