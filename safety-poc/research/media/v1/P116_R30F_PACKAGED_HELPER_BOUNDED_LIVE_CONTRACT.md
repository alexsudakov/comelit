# P116 / R30F — packaged R30E helper bounded live validation contract

Статус: **AUTHORIZED BY USER / CONTROLLED LIVE ONLY**

TASK_ID=`COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE`

BASELINE_MAIN=`7f53a734d41506c6a93ce457629ab7cfa3366547`

## 1. Назначение

R30E завершил offline rebuild/provenance packaged native helper. Accepted artifact:

```text
CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
PACKAGED_BINARY_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
NATIVE_REBUILD_REQUIRED=false
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=true
ARTIFACT_PROVENANCE_READY=true
```

Пользователь отдельно одобрил следующий bounded live этап Comelit.

Цель R30F — проверить **точно этот packaged R30E artifact** на физической камере Comelit в ограниченной исследовательской сессии и получить измеряемый ответ:

1. исполняется ли exact packaged helper в live, а не исторический/пересобранный candidate;
2. проходит ли существующий self-activation/bootstrap до media/control path;
3. достигается ли зарегистрированный CTP/RTPC media path после R30D transport-state fix;
4. появляются ли реальные RTP video/audio counters;
5. корректно ли завершается media path;
6. восстанавливается ли production Comelit listener после каждой попытки.

R30F не внедряет новый protocol hypothesis и не является production HA rollout.

## 2. Разрешение и границы

```text
MODE=CONTROLLED_RESEARCH_LIVE
LIVE_AUTHORIZED=true
MAX_LIVE_INVOCATIONS=10
CT120_ALLOWED=true
COMELIT_NETWORK_TX_ALLOWED=true
ONE_SELF_ACTIVATION_PER_ATTEMPT_ALLOWED=true
INITIAL_MEDIA_REQUEST_ALLOWED=true
PRODUCTION_COMELIT_LISTENER_TEMPORARY_STOP_ALLOWED=true
PRODUCTION_COMELIT_LISTENER_RESTORE_REQUIRED=true
HA_DEPLOY_ALLOWED=false
HA_RELOAD_ALLOWED=false
HA_RESTART_ALLOWED=false
DOOR_ALLOWED=false
GATE_ALLOWED=false
REFRESH_REPEAT_ALLOWED=false
```

Явное пользовательское разрешение на R30F **не** является разрешением на restart/reload Home Assistant. Никакой новый binary в работающий HA в этой задаче не устанавливается.

## 3. Exact artifact gate

Live можно выполнять только exact packaged binary из fresh `origin/main` после R30E:

```text
custom_components/comelit/native/comelit-media
EXPECTED_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
```

Перед первой live-попыткой обязательны:

```text
PACKAGED_BINARY_SHA_GATE=PASS
TRANSPORT_PIN_SHA_GATE=PASS
R30E_PROVENANCE_READY_GATE=PASS
```

Нельзя:

- пересобирать helper для live;
- использовать R27/R29 candidate binary вместо packaged artifact;
- патчить helper/source перед запуском;
- выбирать другой binary после неудачной попытки.

Если SHA или current main расходятся с R30E evidence — STOP до live.

## 4. Previous evidence и что нельзя повторять

### 4.1 R27

`P116_R27_D1_REPEAT_001A_LIVE_PROOF.md` показал `CANDIDATE_EXECUTED=false`: wrapper фактически вызвал base helper, поэтому R27 media markers отсутствовали. R30F обязан доказать lineage exact packaged helper до интерпретации live-результата.

### 4.2 R29F

`P116_R29F_EXIT_FORENSICS.md` показал предыдущую terminal signature:

```text
registered listener ready
CALL_INIT observed
one mediareq26 OPEN queued
local signaling timeout before planned STOP
RTP counters zero
```

R30F должен сравнить новую live signature с этим baseline после R30D/R30E, но не должен автоматически добавлять новые protocol actions.

### 4.3 Запрещённое наследование экспериментов

R30F не наследует эксперимент R27 с повторным `0x001A` и не наследует refresh-loop гипотезы.

На одну попытку допускается только штатный минимальный набор действий, объективно необходимый существующему self-activation/media path:

```text
self_activation <= 1
initial_video/media_request <= 1
repeat_001A = 0
refresh_loop = 0
retry_media_request = 0
Door = 0
Gate = 0
```

Если live требует нового protocol message/retry/cadence для продвижения дальше — это новый semantic decision и текущая попытка завершается с blocker evidence.

## 5. Production listener safety

До каждой live-попытки зафиксировать через существующий HA test-control/read-only health path минимум:

```text
LISTENER_BEFORE_RUNNING=true
LISTENER_BEFORE_READY=true
LISTENER_BEFORE_LAST_ERROR=null
PRODUCTION_MEDIA_ACTIVE_BEFORE=false
```

Если precondition не выполнен — live-попытку не начинать.

Разрешено временно остановить/release только Comelit production listener через уже существующий test-control mechanism, если это необходимо для exclusive Comelit session ownership.

Запрещено:

- останавливать Home Assistant;
- restart/reload HA;
- трогать другие integrations;
- редактировать production HA files;
- оставлять listener остановленным после попытки.

Cleanup должен быть установлен до network action и выполняться на normal exit, test failure, timeout, signal/interrupt и wrapper error.

После каждой попытки обязательны:

```text
LISTENER_AFTER_RUNNING=true
LISTENER_AFTER_READY=true
LISTENER_AFTER_LAST_ERROR=null
PRODUCTION_MEDIA_ACTIVE_AFTER=false
LISTENER_RESTORE=PASS
RESIDUAL_HELPER_PROCESS=false
```

Если listener не восстановлен — немедленный STOP, дальнейшие live attempts запрещены.

## 6. Live runner

R30F должен иметь отдельный runner/launcher, а не запускать `ct120_run_p116_r27_repeat_001a_live.sh` как есть.

Runner может переиспользовать proven bootstrap, redaction, listener-stop/restore и cleanup primitives существующих R27/R29 runners, но обязан:

- исполнять exact packaged binary SHA из §3;
- не компилировать candidate;
- не выполнять second/repeat `0x001A`;
- не выполнять refresh/retry loop;
- не выполнять Door/Gate;
- выводить только scalar/redacted evidence;
- ставить cleanup до первой live network operation;
- иметь `--dry-run`/preflight, который не выполняет Comelit TX;
- иметь exact source/blob/hash gates на сам runner;
- иметь hard attempt timeout;
- сохранять полный non-secret stdout/stderr locally for classification.

Если для запуска exact packaged helper нужен wrapper, wrapper обязан materialize exact artifact path/hash and existing runtime library set; wrapper не может менять helper bytes или protocol source.

## 7. Attempt policy

Разрешено максимум 10 live invocations в рамках R30F, но **не требуется использовать все 10**.

### Attempt 1

Первая попытка — минимальный exact-artifact live без protocol modifications.

### Stop early on success

Если выполнен success gate §10, дальнейшие попытки запрещены: результат уже доказан для bounded session.

### Повтор transient signature

Идентичную попытку разрешено повторить, только если:

- cleanup/listener restore PASS;
- первая ошибка объективно может быть transient;
- Codex заранее указывает, что повтор различает transient vs stable signature.

### Stable signature rule

Если один и тот же terminal failure signature воспроизведён 3 раза при одинаковых gates/state, STOP:

```text
TERMINAL_SIGNATURE_STABLE=true
```

Нельзя тратить оставшиеся попытки на слепые повторы.

### Attempts after diagnostic-only runner correction

Исправления runner допускаются внутри утверждённого write scope, если они **не меняют protocol/network semantics**, например:

- неправильный path;
- parsing/marker extraction;
- teardown bookkeeping;
- timeout observation;
- exact artifact materialization;
- scalar diagnostics.

После такого исправления Codex обязан повторить offline tests до следующего live invocation.

Любое изменение protocol action/message/order/retry/cadence — STOP и отдельное решение.

## 8. Evidence discipline

Разрешено сохранять/публиковать только redacted/scalar evidence:

```text
boolean gates
counts
durations
return codes
state names
packet counts
total byte counts
payload type sets
marker counts
failure/terminal classification
hashes of repository artifacts
```

Не публиковать и не коммитить:

```text
OAuth/access tokens
credentials
raw SDP containing identifiers/addresses
raw CTP/RTPC/PseudoTCP payload bytes
raw RTP/H264/PCMA payload
PCAP
peer IP/port/address
DUUID/ViP token/device identifiers
session identifiers
SSRC/sequence/timestamp values when they can identify a live session
```

При необходимости сырые временные логи остаются только локально и result doc содержит redacted facts.

## 9. Required measured markers

Runner/result должен выдавать минимум:

```text
PACKAGED_BINARY_SHA_GATE
EXACT_PACKAGED_HELPER_EXECUTED
LIVE_INVOCATIONS
ATTEMPT_INDEX
LISTENER_BEFORE_RUNNING
LISTENER_BEFORE_READY
LISTENER_STOP_GATE
UPSTREAM_BOOTSTRAP_COMPLETED
ICE_GATHER
PSEUDOTCP_STARTED_FINAL
PSEUDOTCP_OPEN_FINAL
CTPP_REGISTRATION_COUNT
CALL_INIT_COUNT
SELF_ACTIVATION_SENT_COUNT
SELF_ACTIVATION_ACK_COUNT
INITIAL_MEDIA_REQUEST_SENT_COUNT
INITIAL_MEDIA_REQUEST_ACK_COUNT
RTPC_OPEN_SENT_COUNT
RTPC_OPEN_RESPONSE_COUNT
RTPC_CONTROL_EVENT_COUNT
VIDEO_RTP_PACKET_COUNT
AUDIO_RTP_PACKET_COUNT
VIDEO_RTP_STARTED
AUDIO_RTP_STARTED
MEDIA_ACTIVE_OBSERVED
HELPER_RC
TERMINAL_STAGE
TERMINAL_REASON
TEARDOWN_COMPLETE
RESIDUAL_HELPER_PROCESS
LISTENER_AFTER_RUNNING
LISTENER_AFTER_READY
LISTENER_AFTER_LAST_ERROR
LISTENER_RESTORE
DOOR_ACTIONS_SENT
GATE_ACTIONS_SENT
REPEAT_001A_SENT_COUNT
REFRESH_LOOP_STARTED_COUNT
RETRY_MEDIA_REQUEST_COUNT
```

Если helper не экспонирует конкретный marker, Codex может вывести `UNAVAILABLE_NOT_INSTRUMENTED`; нельзя подменять отсутствие измерения literal `0/PASS`.

## 10. Success gate

`RESULT=PASS` для R30F требует одной live attempt с:

```text
EXACT_PACKAGED_HELPER_EXECUTED=true
PACKAGED_BINARY_SHA_GATE=PASS
LIVE_INVOCATIONS>=1
UPSTREAM_BOOTSTRAP_COMPLETED=true
PSEUDOTCP_OPEN_FINAL=true
CTPP_REGISTRATION_COUNT>=1
INITIAL_MEDIA_REQUEST_SENT_COUNT=1
VIDEO_RTP_PACKET_COUNT>0
VIDEO_RTP_STARTED=true
TEARDOWN_COMPLETE=true
RESIDUAL_HELPER_PROCESS=false
LISTENER_RESTORE=PASS
LISTENER_AFTER_RUNNING=true
LISTENER_AFTER_READY=true
LISTENER_AFTER_LAST_ERROR=null
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
REPEAT_001A_SENT_COUNT=0
REFRESH_LOOP_STARTED_COUNT=0
RETRY_MEDIA_REQUEST_COUNT=0
```

Audio RTP >0 — дополнительный PASS marker, но отсутствие audio само по себе не отменяет успешную проверку video transport, если video gate выполнен и teardown безопасен.

R30F PASS доказывает только bounded CT120 live transport для exact packaged helper. Он **не** доказывает HA viewer/end-to-end Stream и не разрешает production deploy автоматически.

## 11. Failure classification

Если positive RTP не достигнут, задача может завершиться `RESULT=INCONCLUSIVE` или `RESULT=BLOCKED` при условии безопасного teardown и достаточной terminal signature.

Классификация должна различать минимум:

```text
BOOTSTRAP_FAIL
PSEUDOTCP_FAIL
CTPP_REGISTRATION_FAIL
CALL_INIT_NOT_OBSERVED
MEDIA_REQUEST_NOT_SENT
MEDIA_REQUEST_NOT_ACKED
RTPC_OPEN_NO_RESPONSE
RTPC_CONTROL_STALL
RTP_ZERO_AFTER_CONTROL_READY
HELPER_EARLY_EXIT
HELPER_TIMEOUT
LISTENER_RESTORE_FAIL
SAFETY_COUNTER_VIOLATION
UNKNOWN_REDACTED_TERMINAL
```

Не исправлять live failure добавлением новых protocol actions без нового разрешения.

## 12. Write scope

### Contract/runner preparation scope

Разрешены изменения только в:

```text
safety-poc/research/media/v1/ct120_run_p116_r30f_packaged_helper_live.sh
safety-poc/tests/test_p116_r30f_packaged_helper_live_contract.py
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
```

Дополнительный focused helper внутри `safety-poc/research/media/v1/**` или test внутри `safety-poc/tests/**` допускается только если объективно нужен runner'у и не меняет protocol semantics; необходимость зафиксировать в result.

Запрещено менять в R30F:

```text
custom_components/comelit/**
packaged native binary
R30D/R30E transforms/model source
existing R27/R29 runners
.github/**
README.md
docs/**
```

Если live выявляет необходимость исправлять helper/protocol/production integration — зафиксировать blocker; не расширять scope самостоятельно.

## 13. Offline preparation acceptance

До первой live попытки новый runner должен пройти:

```text
RUNNER_BASH_N=PASS
RUNNER_STATIC_CONTRACT_TESTS=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
GIT_DIFF_CHECK=PASS
WRITE_SCOPE_GATE=PASS
DRY_RUN=PASS
DRY_RUN_NETWORK_TX=0
DRY_RUN_LISTENER_TOUCHED=false
```

Предпочтительно runner preparation commit должен пройти repository PR gates до live execution. Если orchestration flow требует live result в той же branch, первый live запуск допускается только после Codex и Hermes независимо подтвердили все локальные offline gates и exact main/artifact SHA; PR затем обязан пройти standard CI до merge result evidence.

## 14. Live execution host

Основной live host: CT120.

Hermes имеет право механически выполнять точную command sequence, сформированную Codex, если Codex sandbox сам не имеет доступа к CT120. Все команды и redacted output возвращаются в тот же bounded Codex context.

Не просить пользователя вручную выполнять CT120 scripts, если существующий Hermes/CT120 доступ достаточен.

## 15. Result and Git/GitHub

После live:

1. Codex классифицирует evidence;
2. обновляет только R30F result doc/runner/tests в разрешённом scope;
3. повторяет offline tests;
4. Hermes проверяет scope/diff;
5. commit/push с credential-free remote и repo-local credential helper;
6. создаёт PR, если permission позволяет; иначе возвращает branch/head;
7. обязательны реальные `offline-safety=SUCCESS` и `Validate HACS=SUCCESS` перед merge result.

Live PASS/FAIL не заменяет CI.

## 16. Stop boundary

После R30F STOP.

Не выполнять автоматически:

- deploy R30E helper в HA;
- reload config entry;
- restart HA;
- открытие HA camera viewer;
- screenshot/recording test;
- новый protocol experiment;
- Door/Gate action.

Следующий HA end-to-end stage требует отдельного разрешения, особенно если нужен Home Assistant restart.
