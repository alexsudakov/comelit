# P116 / R30D — задача Hermes/Codex: native CTP runtime integration

Статус: **готово к исполнению после merge этого contract/task PR / OFFLINE DEV ONLY**

TASK_ID=`COMELIT-P116-R30D-NATIVE-CTP-RUNTIME-INTEGRATION`

Основной контракт:

```text
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_CONTRACT.md
```

Canonical evidence:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
```

## Роли

```text
HERMES_ROLE=ORCHESTRATOR_ONLY
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
NETWORK_TX_ALLOWED=false
HA_ALLOWED=false
```

Hermes не пишет executable code и не подменяет Codex. Один bounded R30D child должен по возможности выполняться одним autonomous Codex invocation с локальным edit/test/fix loop внутри этого invocation.

## Bootstrap

Работай только от свежего `origin/main` публичного `alexsudakov/comelit`.

```text
REPOSITORY_PATH=/home/hermes/repos/comelit
SOURCE_OF_TRUTH=origin/main
```

Сначала:

1. выполни `git fetch origin main`;
2. зафиксируй фактический `origin/main` SHA;
3. проверь, что в `origin/main` уже присутствуют оба R30D документа: contract и этот task;
4. создай отдельную ветку/worktree от свежего `origin/main`;
5. не продолжай R30B/R30C worktree/branch;
6. remote должен оставаться credential-free;
7. не выводи token/credential contents.

До любых executable изменений проверь executor:

```text
CODEX_COMMAND_PRESENT=true|false
CODEX_VERSION=<version-or-unavailable>
ACTUAL_EXECUTOR=codex-cli|other|unavailable
```

Если `codex-cli` недоступен, остановись:

```text
RESULT=BLOCKED_EXECUTOR_UNAVAILABLE
```

Hermes не имеет права заменить Codex другим coding agent или написать исправление самостоятельно.

## Что прочитать Codex

Не пересказывай Codex историю P116. Передай paths и короткий task delta. Codex самостоятельно читает repository-local instructions и следующие canonical inputs:

```text
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_CONTRACT.md
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/tests/test_p116_r30b_offline_call_transaction.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
```

Не переисследовать native-библиотеки и не использовать сторонние public implementations как canonical evidence.

## Compact child contract для Codex

Передай Codex следующий смысловой delta:

```yaml
goal:
  Интегрировать native-proven CTP adoption state из R30C в offline R30B/P76 runtime models.

scope:
  read:
    - R30D contract
    - R30C result
    - R30B model/result/tests
    - P76 transform/tests
    - repository-local instructions и соседний код, необходимый для текущего goal
  write:
    - safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
    - safety-poc/tests/test_p116_r30b_offline_call_transaction.py
    - safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
    - safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
    - safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md

constraints:
  - offline only; никакого network/live/HA/listener/production
  - initial local TX sequence = inbound CTP ACK byte offset 5 verbatim
  - initial local ACK = inbound CTP sequence byte offset 4 verbatim
  - sequence/ack независимые uint8 fields
  - accepted body updates ACK = peer sequence + 1 mod 256
  - body-bearing TX sequence advances +1 mod 256 according to native lifecycle
  - empty ACK не продвигает TX sequence
  - connection id mapping classification = native proven
  - не использовать сторонний public repo как proof/acceptance input
  - сохранить fail-closed behavior и media ordering/channel invariants R30B
  - исправить P76 cross-byte carry при sequence 0xff

acceptance:
  - focused R30B tests PASS
  - focused P76 tests PASS
  - seq 0xff -> 0x00 without ACK carry PASS
  - ACK wrap independent PASS
  - empty ACK does not advance TX sequence PASS
  - connection transform does not mutate sequence/ack PASS
  - full safety-poc unittest suite PASS
  - compile/static/offline safety PASS
  - diff stays in approved write scope
  - production files changed = 0

stop_conditions:
  - нужен новый architecture choice
  - требуется расширить write scope за пределы contract
  - требуется live/network/production action
  - нужен credential/user choice/external approval
  - canonical evidence R30C оказывается недостаточным или противоречивым
```

Codex должен сам выполнить локальный цикл:

```text
inspect -> implement -> focused verify -> diagnose -> correct -> verify -> full acceptance
```

Не возвращай управление Hermes из-за обычного compile/test failure внутри утверждённого scope.

## Особо важный regression

Обязательно доказать тестом, что независимые transport bytes не связаны арифметическим carry:

```text
before: sequence=0xff, acknowledgement=X
after body-bearing sequence advance: sequence=0x00, acknowledgement=X
```

И отдельно:

```text
peer sequence=0xff on accepted body
-> acknowledgement=0x00
-> local TX sequence unchanged только из-за ACK update
```

Старый composite `+ 0x00010000` не должен оставаться способом изменения sequence state, если он допускает перенос в ACK.

## Verification

Сначала focused checks, после локальной стабилизации — полный acceptance.

Минимум:

```text
python3 -m unittest safety-poc/tests/test_p116_r30b_offline_call_transaction.py
python3 -m unittest safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
python3 -m unittest discover -s safety-poc/tests -p 'test_*.py'
```

Если repository-local test invocation отличается, Codex может использовать корректный существующий способ, но обязан указать точные команды и результаты.

Также выполнить существующие repository static/offline safety checks и compile/compileall для изменённых Python files.

## Git/GitHub

После локального PASS Hermes:

- проверяет scope/diff;
- commit/push через штатный credential helper без токена в remote URL;
- создаёт PR в `main`, если текущая GitHub credential capability это позволяет;
- ждёт реальные PR-gates `offline-safety` и `Validate HACS`;
- не merge при FAIL/unknown/in-progress gate;
- при CI defect внутри того же scope возвращает feedback тому же R30D Codex child/context, если он ещё доступен, либо делает corrective invocation только если исходный процесс уже завершён;
- не переходит автоматически к live/R30E.

Если PR создать невозможно из-за permission, не считать задачу failed: вернуть branch/head SHA, чтобы PR мог создать оператор/ChatGPT.

## Итоговый отчёт Hermes

Полезный блок должен быть последним в выводе:

```text
=== COMELIT P116 R30D NATIVE CTP RUNTIME INTEGRATION ===
TASK_ID=COMELIT-P116-R30D-NATIVE-CTP-RUNTIME-INTEGRATION
BASE_SHA=<fresh-origin-main-at-start>
FINAL_SHA=<branch-head>
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=<version>
CHANGED_FILES=<count-and-paths>
LOCAL_CONNECTION_DIRECTION_RULE=NATIVE_PROVEN
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=INBOUND_ACK_BYTE_OFFSET_5
INITIAL_LOCAL_ACK_SOURCE=INBOUND_SEQUENCE_BYTE_OFFSET_4
SEQUENCE_STATE_OWNER=CTP_TRANSPORT_CONNECTION_OBJECT
SEQUENCE_ACK_INDEPENDENT_BYTES=true
SEQUENCE_WRAP_0XFF_TO_0X00_WITHOUT_ACK_CARRY=<PASS|FAIL>
ACK_WRAP_0XFF_TO_0X00_INDEPENDENT=<PASS|FAIL>
EMPTY_ACK_ADVANCES_TX_SEQUENCE=false
R30B_FOCUSED_TESTS=<PASS|FAIL>
P76_FOCUSED_TESTS=<PASS|FAIL>
FULL_OFFLINE_TESTS=<PASS|FAIL>
STATIC_SAFETY=<PASS|FAIL>
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
LIVE_AUTHORIZED=false
OFFLINE_SAFETY=<PASS|FAIL|UNAVAILABLE>
VALIDATE_HACS=<PASS|FAIL|UNAVAILABLE>
PR=<number-or-none>
RESULT=<PASS|BLOCKED|FAIL>
=== END COMELIT P116 R30D NATIVE CTP RUNTIME INTEGRATION ===
```

После этого STOP. Не запускать live и не начинать R30E без отдельной постановки.