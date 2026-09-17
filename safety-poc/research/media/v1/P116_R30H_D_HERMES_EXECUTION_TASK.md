# Hermes execution task — P116 / R30H-D corrected-runner repeat `0x001A` live proof

TASK_ID=`COMELIT-P116-R30H-D-REPEAT-001A-LIVE-PROOF`

MODE=`BOUNDED_LIVE_RESEARCH`

Статус пользовательского разрешения: `AUTHORIZED`.

Пользователь 2026-09-17 явно разрешил ровно один bounded live запуск corrected R27 runner на физической камере подъезда, временную остановку и обязательное восстановление persistent Comelit listener, ровно один repeat `0x001A` через 20 секунд и наблюдение до 70 секунд. Второй media-сеанс и retry запрещены. Door/Gate=0. HA restart/reload/deploy запрещены.

## 1. Модель исполнения

- Hermes — только оркестратор.
- Вся семантическая диагностика, preflight-интерпретация и авторство result-документа выполняются в одном bounded контексте Codex CLI.
- При необходимости дополнительных раундов продолжай тот же Codex session через `codex exec resume`.
- Hermes может выполнять инфраструктурные действия, прямо разрешённые этим task: Git, подготовку CT120, offline gates, безопасный listener status/stop/start, запуск принятого runner и сбор scalar evidence.
- Hermes не пишет executable-код.
- В R30H-D executable-код вообще менять нельзя.
- После единственного live invocation второй запуск запрещён при любом результате.

## 2. Обязательный bootstrap

Сначала выполнить свежий authenticated fetch `origin/main` и использовать фактический latest accepted main.

На момент создания задачи ожидаемый main:

```text
8ec80651bd56f34898222dee07e140269c9fdb94
```

Если `origin/main` новее — использовать новый accepted main, не откатывать его к указанному SHA.

Обязательно прочитать:

```text
safety-poc/research/media/v1/P116_R30H_D_REPEAT_001A_LIVE_PROOF_CONTRACT.md
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

## 3. GitHub credential boundary

На CT120 использовать только проектное credential-хранилище:

```text
/root/.config/git/comelit.credentials
```

Проверить:

```text
CREDENTIAL_FILE_EXISTS=true
CREDENTIAL_FILE_MODE=600
REMOTE_CREDENTIAL_FREE=true
```

Для локального репозитория настроить repo-local:

```bash
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

Не выводить содержимое credential-файла, токен, Authorization header или URL с токеном.

## 4. Жёсткие лимиты

```text
MAX_LIVE_INVOCATIONS=1
MAX_MEDIA_SESSIONS=1
MAX_INITIAL_001A=1
MAX_REPEAT_001A=1
MAX_TOTAL_CLIENT_001A=2
REPEAT_DELAY_SECONDS=20
MAX_MEDIA_OBSERVATION_SECONDS=70
OUTER_TIMEOUT_SECONDS=150
MAX_HA_RESTARTS=0
MAX_HA_RELOADS=0
MAX_HA_DEPLOYS=0
MAX_DOOR_ACTIONS=0
MAX_GATE_ACTIONS=0
SECOND_MEDIA_SESSION=false
AUTOMATIC_RETRY=false
PERIODIC_REFRESH_LOOP=false
```

Не менять repeat delay на 15 секунд.

## 5. Phase 1 — fresh source identity

Подготовить один полный clean clone на CT120 с `.git` каталогом, при необходимости detached checkout на accepted main.

До каких-либо live-действий получить:

```text
FRESH_MAIN_FETCHED=true
ACCEPTED_MAIN_SHA=<sha>
REPO_HEAD=<sha>
REPO_HEAD_EQUALS_ACCEPTED_MAIN=true
WORKTREE_CLEAN=true
REMOTE_CREDENTIAL_FREE=true
CREDENTIAL_FILE_MODE_OK=true
```

Если любой обязательный source gate не проходит — STOP до live.

## 6. Phase 2 — canonical/offline gates

Проверить наличие и статус R30H-C:

```text
R30H_C_RESULT_PRESENT=true
R30H_C_RESULT=PASS_EXECUTION_PATH_READY
```

Перезапустить focused contract test:

```text
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

Ожидается текущий accepted набор тестов; не фиксировать число 33 как вечный протокольный контракт, если accepted main содержит больше тестов. Требуется `OK` без новых failures.

Проверить неизменность ключевой семантики:

```text
ONE_SHOT_REPEAT_CONTRACT=PASS
MAX_INITIAL_001A=1
MAX_REPEAT_001A=1
MAX_TOTAL_CLIENT_001A=2
THIRD_001A_FAIL_CLOSED=true
ACK_TIMEOUT_RETRY=false
NO_NEW_SESSION_SETUP_PATHS=true
R27_REPEAT_DELAY_SECONDS=20
R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
```

## 7. Phase 3 — execution-path no-main gate

До остановки listener повторно выполнить принятый R30H-C offline execution-path gate или эквивалентный canonical harness из fresh main.

Обязательно получить:

```text
EXPECTED_SOURCE_SHA_GATE=PASS
CANDIDATE_BUILD=PASS
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
WRAPPER_BINDING_GATE=PASS
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
```

Проверить, что loader/candidate/library-path provenance соответствует текущему fresh-main запуску, а не старому hardcoded run-root.

Если loader gate, candidate SHA, wrapper binding или no-main proof не проходят — STOP без listener stop и без live invocation.

## 8. Phase 4 — pre-live production state

Через уже существующий безопасный control/status path проверить непосредственно перед live:

```text
LISTENER_READY_BEFORE=true
PRODUCTION_MEDIA_ACTIVE_BEFORE=false
DOOR_ACTIONS_BEFORE=0
GATE_ACTIONS_BEFORE=0
CAMPAIGN_PROCESSES_BEFORE=0
```

Допустимо использовать уже принятую exclusivity-инварианту: active production media lease не совместима с listener-ready состоянием. Не добавлять новый HA runtime-механизм только ради дополнительного скаляра.

Перед выполнением live Codex в том же bounded session должен проверить собранные факты и вернуть ровно одно решение:

```text
GO_LIVE
```

или

```text
STOP_BEFORE_LIVE=<reason>
```

Hermes не должен запускать live при `STOP_BEFORE_LIVE`.

## 9. Phase 5 — единственный live invocation

При `GO_LIVE` использовать принятый runner напрямую:

```text
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
```

Запустить ровно один раз с:

```text
R27_LIVE_RUN=YES
R27_EXPECTED_COMMIT_SHA=<accepted-main-sha>
REPO=<clean-full-clone-at-accepted-main>
```

Не запускать candidate wrapper отдельно.
Не запускать runner второй раз.
Не выполнять ручной parallel helper.

Runner должен сам:

1. собрать ephemeral candidate;
2. проверить generated-source SHA;
3. взять builder rootfs provenance;
4. скопировать musl loader только в run-root с SHA gate;
5. создать per-run launcher;
6. привязать materialized wrapper к launcher, а не raw ELF;
7. проверить listener ready;
8. остановить только persistent Comelit listener;
9. поднять localhost RTP sinks;
10. выполнить ровно один candidate-wrapper invocation;
11. разрешить существующий one-shot repeat `0x001A` около 20 s после media active при прохождении fail-closed preconditions;
12. завершить candidate;
13. восстановить persistent listener;
14. вывести финальный scalar block.

## 10. Phase 6 — evidence quality gate

После завершения runner не интерпретировать protocol scalars до проверки:

```text
LIVE_INVOCATIONS=1
R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
R27_USABLE_EVIDENCE=true
R27_HELPER_EVIDENCE_GATE=PASS
TEARDOWN_CONFIDENCE=CONFIRMED
```

Также подтвердить, что предыдущая R30H-B ошибка исполнения отсутствует:

```text
CANDIDATE_REQUIRED_FILE_NOT_FOUND=false
```

Но одно отсутствие этой ошибки не является usable evidence.

Если gate не проходит — `RESULT=INCONCLUSIVE`, scalars считать suppressed/partial и не делать вывод о repeat. Retry запрещён.

## 11. Phase 7 — protocol/repeat evidence

Если evidence quality gate проходит, извлечь из принятого runner/session output:

```text
R27_REPEAT_EXECUTED=<true|false>
INITIAL_001A_SENT_COUNT=<n>
REPEAT_001A_SENT_COUNT=<n>
TOTAL_001A_SENT_COUNT=<n>
SECOND_001A_RESPONSE=<STRUCTURAL_ACK|ABSENT|AMBIGUOUS|...>
VIDEO_RTP_BEFORE_REPEAT=<true|false>
VIDEO_PACKET_COUNT_AT_REPEAT=<n>
VIDEO_RTP_AFTER_REPEAT=<true|false>
VIDEO_RTP_PAST_35S=<true|false>
VIDEO_RTP_PAST_40S=<true|false>
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=<n>
ICE_NEGOTIATION_COUNT=<n>
PSEUDOTCP_OPEN_COUNT=<n>
CTPP_REGISTRATION_COUNT=<n>
RTPC_CLIENT_OPEN_COUNT=<n>
SELF_ACTIVATION_COUNT=<n>
HELPER_PROCESS_UNCHANGED=<true|false>
```

Зафиксировать sink packet counts как corroborating evidence, если runner их сохранил. Они не заменяют helper-lineage proof.

## 12. Phase 8 — классификация результата

Использовать только один из четырёх классов.

### PASS_REPEAT_EXTENDS_RTP

Только если доказано:

```text
R27_REPEAT_EXECUTED=true
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=2
VIDEO_RTP_BEFORE_REPEAT=true
VIDEO_RTP_AFTER_REPEAT=true
VIDEO_RTP_PAST_40S=true
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START>=40
ICE_NEGOTIATION_COUNT=1
PSEUDOTCP_OPEN_COUNT=1
CTPP_REGISTRATION_COUNT=1
RTPC_CLIENT_OPEN_COUNT=2
SELF_ACTIVATION_COUNT=1
HELPER_PROCESS_UNCHANGED=true
```

`SECOND_001A_RESPONSE=STRUCTURAL_ACK` сам по себе недостаточен.

### FAIL_REPEAT_NO_EXTENSION

Usable observation, repeat доказан ровно один раз, но video RTP не проходит >40 s threshold.

### BLOCKED_REPEAT_NOT_EXECUTED

Usable media path достигнут, но существующий fail-closed repeat gate не позволил отправить repeat.

### INCONCLUSIVE

Любой failure evidence gate, helper-lineage failure, outer timeout, execution-path problem, teardown uncertainty, listener restoration uncertainty или другой случай, не позволяющий protocol conclusion.

При любом классе второй live-run запрещён.

## 13. Phase 9 — обязательное восстановление

После единственного invocation, независимо от результата, independently prove:

```text
CAMPAIGN_PROCESSES_REMAINING=NONE
CT120_RESEARCH_HELPER_STOPPED=true
CT120_RESEARCH_SESSION_CLOSED=true
R30H_D_SESSION_CLOSED=true
TEARDOWN_CONFIDENCE=CONFIRMED
LISTENER_RUNNING_AFTER=true
LISTENER_READY_AFTER=true
PRODUCTION_MEDIA_ACTIVE=false
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
HA_RESTARTED=false
HA_RELOADED=false
HA_DEPLOYED=false
SECOND_MEDIA_SESSION=false
```

Желательно сделать два read-only post-run listener status sample для подтверждения стабильного `listener_ready=true`, если это не создаёт новый media session и не меняет HA state.

Если listener не восстановлен — не выполнять HA restart/reload. Зафиксировать `INCONCLUSIVE` и точный restoration blocker.

## 14. Phase 10 — result document

Разрешён единственный repository write после live:

```text
safety-poc/research/media/v1/P116_R30H_D_REPEAT_001A_LIVE_PROOF_RESULT.md
```

Codex в том же bounded session пишет result document по фактическим evidence.

Документ обязан разделять:

- source identity/preflight;
- R30H-C execution-path gate;
- live invocation identity;
- helper/ICE/PseudoTCP/CTPP/RTPC/media facts;
- initial/repeat `0x001A`;
- second-response classification;
- RTP before/after repeat и duration;
- teardown/listener restoration;
- forbidden actions;
- not-proven facts;
- exact result class.

Не включать токен, credentials, raw SDP, raw packet bytes, raw RTP/H264/audio, peer secrets/session identifiers или иной чувствительный runtime payload.

## 15. Phase 11 — независимая проверка Hermes

До commit Hermes обязан самостоятельно сверить result doc с сохранённым scalar/stdout evidence, а не принимать self-report Codex.

Минимум перепроверить:

```text
LIVE_INVOCATIONS
WRAPPER_RC
R27_HELPER_EVIDENCE_GATE
R27_RUN_CLASSIFICATION
R27_USABLE_EVIDENCE
R27_REPEAT_EXECUTED
INITIAL_001A_SENT_COUNT
REPEAT_001A_SENT_COUNT
TOTAL_001A_SENT_COUNT
SECOND_001A_RESPONSE
VIDEO_RTP_AFTER_REPEAT
VIDEO_RTP_PAST_40S
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START
TEARDOWN_CONFIDENCE
LISTENER_READY_AFTER
DOOR_ACTIONS_SENT
GATE_ACTIONS_SENT
```

Не усиливать классификацию сверх наблюдаемых данных.

## 16. Phase 12 — GitHub completion

После проверки:

1. убедиться, что diff содержит только result document;
2. commit;
3. push через `/root/.config/git/comelit.credentials` с repo-local helper;
4. попытаться создать PR;
5. при `createPullRequest` 403 вернуть branch и exact remote head SHA.

Не менять executable code в live child.

## 17. Обязательный финальный блок

В конце вывести:

```text
=== COMELIT P116 R30H-D REPEAT 001A LIVE PROOF ===
TASK_ID=COMELIT-P116-R30H-D-REPEAT-001A-LIVE-PROOF
BASE_SHA=<accepted-main-sha>
LIVE_AUTHORIZED=true
MAX_LIVE_INVOCATIONS=1
LIVE_INVOCATIONS=<0|1>
R30H_C_RESULT=PASS_EXECUTION_PATH_READY
EXECUTION_PATH_GATE=<PASS|FAIL|NOT_REACHED>
CANDIDATE_SOURCE_SHA256=<sha|NOT_REACHED>
CANDIDATE_BINARY_SHA256=<sha|NOT_REACHED>
WRAPPER_BINDING_GATE=<PASS|FAIL|NOT_REACHED>
R27_HELPER_EVIDENCE_GATE=<PASS|FAIL|NOT_REACHED>
R27_RUN_CLASSIFICATION=<...>
R27_USABLE_EVIDENCE=<true|false>
R27_REPEAT_DELAY_SECONDS=20
R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
R27_REPEAT_EXECUTED=<true|false|NOT_REACHED>
INITIAL_001A_SENT_COUNT=<n|NOT_REACHED>
REPEAT_001A_SENT_COUNT=<n|NOT_REACHED>
TOTAL_001A_SENT_COUNT=<n|NOT_REACHED>
SECOND_001A_RESPONSE=<...|NOT_REACHED>
VIDEO_RTP_BEFORE_REPEAT=<...|NOT_REACHED>
VIDEO_RTP_AFTER_REPEAT=<...|NOT_REACHED>
VIDEO_RTP_PAST_35S=<...|NOT_REACHED>
VIDEO_RTP_PAST_40S=<...|NOT_REACHED>
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=<n|NOT_REACHED>
ICE_NEGOTIATION_COUNT=<n|NOT_REACHED>
PSEUDOTCP_OPEN_COUNT=<n|NOT_REACHED>
CTPP_REGISTRATION_COUNT=<n|NOT_REACHED>
RTPC_CLIENT_OPEN_COUNT=<n|NOT_REACHED>
SELF_ACTIVATION_COUNT=<n|NOT_REACHED>
HELPER_PROCESS_UNCHANGED=<...|NOT_REACHED>
CAMPAIGN_PROCESSES_REMAINING=<NONE|...>
CT120_RESEARCH_HELPER_STOPPED=<true|false>
CT120_RESEARCH_SESSION_CLOSED=<true|false>
R30H_D_SESSION_CLOSED=<true|false>
TEARDOWN_CONFIDENCE=<CONFIRMED|UNCERTAIN>
LISTENER_RUNNING_AFTER=<true|false>
LISTENER_READY_AFTER=<true|false>
PRODUCTION_MEDIA_ACTIVE=<false|true|unknown>
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
HA_RESTARTED=false
HA_RELOADED=false
HA_DEPLOYED=false
SECOND_MEDIA_SESSION=false
REFRESH_LOOP=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30H_D_REPEAT_001A_LIVE_PROOF_RESULT.md
BRANCH=<branch|none>
REMOTE_HEAD=<sha|none>
PR=<number|none>
RESULT=<PASS_REPEAT_EXTENDS_RTP|FAIL_REPEAT_NO_EXTENSION|BLOCKED_REPEAT_NOT_EXECUTED|INCONCLUSIVE|STOP_BEFORE_LIVE>
=== END COMELIT P116 R30H-D REPEAT 001A LIVE PROOF ===
```

## 18. STOP

После R30H-D — STOP.

Даже при `PASS_REPEAT_EXTENDS_RTP` не внедрять production refresh, не выбирать cadence и не делать новый live run автоматически.
