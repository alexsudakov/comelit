# P116 / R30D — native CTP runtime integration contract

Статус: **готово к исполнению / OFFLINE DEV ONLY**

TASK_ID=`COMELIT-P116-R30D-NATIVE-CTP-RUNTIME-INTEGRATION`

BASELINE_MAIN=`8f2d19c969929cf9f6b15f581d14f2a473f6ebb8`

## 1. Назначение

R30D — следующий bounded semantic child после принятого R30C.

Цель этапа — заменить оставшиеся provisional/synthetic transport assumptions в offline call-transaction path на правила CTP adoption, уже доказанные официальным native dataflow в R30C, и отдельно устранить cross-byte carry defect в историческом P76 sequence advancement.

R30D не является live-экспериментом и не должен расширяться в production integration.

```text
MODE=OFFLINE_DEV_ONLY
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
HERMES_ROLE=ORCHESTRATOR_ONLY
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
NETWORK_TX_ALLOWED=false
HA_ALLOWED=false
PRODUCTION_DEPLOY_ALLOWED=false
```

## 2. Canonical evidence

Основной источник истины для transport rules этого этапа:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
```

Родительские executable/result sources:

```text
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/tests/test_p116_r30b_offline_call_transaction.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
```

Не переисследовать native-библиотеки, если текущий main не содержит evidence, противоречащего R30C.

Сторонние public implementations не являются canonical evidence для R30D и не должны использоваться для promotion, acceptance или изменения proof classification.

## 3. Принятые R30C invariants

R30D принимает как доказанные входные факты:

```text
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
LOCAL_ID_CLASSIFICATION=B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID
CTP_WRITE_WIRE_ID_MAPPING=PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=INBOUND_CTP_PACKET_ACK_BYTE_WIRE_OFFSET_5_COPIED_VERBATIM
FIRST_LOCAL_TX_SEQUENCE_EVIDENCE=PROVEN_NATIVE
INITIAL_LOCAL_ACK_SOURCE=INBOUND_CTP_PACKET_SEQUENCE_BYTE_WIRE_OFFSET_4_COPIED_VERBATIM
INITIAL_LOCAL_ACK_EVIDENCE=PROVEN_NATIVE
ACKNOWLEDGEMENT_UPDATE_RULE=PEER_SEQUENCE_PLUS_ONE_MOD_256_ON_ACCEPTED_BODY_PACKET
ACKNOWLEDGEMENT_UPDATE_EVIDENCE=PROVEN_NATIVE
LOCAL_SEQUENCE_ADVANCEMENT_RULE=PLUS_ONE_MOD_256_PER_BODY_BEARING_SEND_ACK_GATED
LOCAL_SEQUENCE_ADVANCEMENT_EVIDENCE=PROVEN_NATIVE
SEQUENCE_STATE_OWNER=CTP_TRANSPORT_CONNECTION_OBJECT
SEQUENCE_STATE_OWNER_EVIDENCE=PROVEN_NATIVE
```

Для adopted inbound CTP connection:

```text
internal_connection_id = inbound_wire_connection_id ^ 0x8000
```

а serializer записывает этот internal id обратно в wire connection bytes big-endian.

Sequence и acknowledgement — два независимых 8-bit state fields.

## 4. Основная implementation delta

### 4.1 R30B transaction model

Файл:

```text
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
```

Нужно убрать native path dependence от произвольного caller-injected `next_tx_sequence_seed` для adopted inbound call.

Начальное transport state должно выводиться из принятого inbound CTP packet:

```text
local_tx_sequence = inbound_ack_byte_offset_5
local_acknowledgement = inbound_sequence_byte_offset_4
```

Дальнейшая эволюция должна хранить и менять sequence/ack независимо.

Body-bearing outbound send:

```text
sequence := (sequence + 1) mod 256
```

только согласно доказанному transport lifecycle. Empty ACK не должен сам по себе продвигать local TX sequence.

Accepted inbound body packet:

```text
acknowledgement := (peer_sequence + 1) mod 256
```

Не моделировать sequence/ack как общий 16/32-bit arithmetic scalar.

### 4.2 Connection-id classification

Существующее вычисление direction transform может быть сохранено по смыслу, но его статус должен быть повышен с provisional/corroborating hypothesis до native-proven contract.

При этом сохранить текущие fail-closed проверки invalid/reserved/local-zero cases. R30D не должен ослаблять negative behavior ради happy path.

### 4.3 P76 sequence advancement

Файл:

```text
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
```

Историческая операция вида:

```text
p76_write_le32(out + 2, prev + 0x00010000u)
```

структурно увеличивает sequence byte для обычных значений, но при `sequence == 0xff` допускает перенос в соседний acknowledgement byte.

Это несовместимо с native invariant независимых 8-bit fields.

R30D должен заменить composite arithmetic на byte-semantic update, который:

```text
- сохраняет connection bytes неизменными;
- увеличивает только sequence byte modulo 256;
- сохраняет acknowledgement byte неизменным, если текущий transition не является ACK update;
- не создаёт carry между sequence и acknowledgement.
```

Не менять доказанный RTPC/media body layout и не расширять P76 за пределы transport-header correction.

## 5. Обязательные boundary tests

R30D должен добавить явные regression/negative tests минимум для следующих случаев:

```text
1. inbound sequence=S, inbound ack=A
   -> initial local sequence=A
   -> initial local ack=S

2. local sequence=0xff, ack=X
   -> следующий body-bearing sequence=0x00
   -> ack остаётся X

3. peer sequence=0xff на accepted body packet
   -> local ack=0x00
   -> local TX sequence не меняется только из-за ACK update

4. empty ACK
   -> local TX sequence не продвигается

5. connection direction transform
   -> изменяет только connection-id semantics
   -> sequence/ack не затрагиваются

6. malformed/truncated/wrong-version/non-SYN initial packet
   -> fail closed, как в R30B

7. invalid/reserved/zero derived local connection id
   -> fail closed
```

Существующие R30B negative tests по ordering, media-channel allocation, duplicate OPEN/STOP, Door/Gate/network reachability должны оставаться зелёными.

## 6. Scope

Разрешённый write scope:

```text
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/tests/test_p116_r30b_offline_call_transaction.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
```

При объективной необходимости допускается новый focused test/helper только внутри:

```text
safety-poc/research/media/v1/**
safety-poc/tests/**
```

но Codex обязан объяснить необходимость в итоговом result.

Запрещено менять:

```text
custom_components/comelit/**
docs/intercom-media-session-architecture.md
docs/ha-integration-target-architecture.md
README.md
.github/**
```

## 7. Safety boundary

Запрещены:

```text
Comelit network TX
live call/media session
ICE/PseudoTCP/cloud bootstrap
Door
Gate
self-activation
refresh/repeat
production listener stop/start/reload
HA deploy/restart/reload
production integration changes
raw PCAP/APK/DEX/native binaries in Git
credential/token output or commit
```

Никакая предыдущая live authorization не переносится на R30D.

## 8. Codex lifecycle

Один bounded R30D child по возможности выполняется одним autonomous Codex invocation.

Внутри одного invocation Codex должен самостоятельно пройти:

```text
inspect
-> implement
-> focused tests
-> diagnose/fix
-> focused tests
-> full offline acceptance
-> final diff/safety review
```

Локальные compile/test failures не являются основанием возвращаться Hermes или запускать новый Codex invocation.

Вернуть управление Hermes только при настоящем blocker/semantic boundary: необходимость расширить write scope, изменить architecture, использовать live/production action, получить credential/user choice или изменить task contract.

## 9. Acceptance

Обязательный focused acceptance:

```text
R30B focused tests = PASS
P76 focused parity tests = PASS
native-seed derivation tests = PASS
sequence 0xff -> 0x00 without ack carry = PASS
ack 0xff -> 0x00 independently = PASS
empty-ACK no-sequence-advance = PASS
connection transform isolation = PASS
```

Обязательный full acceptance:

```text
python compile/compileall relevant files = PASS
full safety-poc unittest suite = PASS
repository static/offline safety checks = PASS
no forbidden network/live path reachable = PASS
production files changed = 0
write-scope gate = PASS
```

После push/PR обязательны GitHub gates:

```text
offline-safety = SUCCESS
Validate HACS = SUCCESS
```

Merge запрещён до зелёных обязательных PR-gates.

## 10. Result contract

Итоговый result-document должен содержать минимум:

```text
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
SEQUENCE_WRAP_0XFF_TO_0X00_WITHOUT_ACK_CARRY=PASS
ACK_WRAP_0XFF_TO_0X00_INDEPENDENT=PASS
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
```

## 11. Stop condition

R30D заканчивается после доказанного offline runtime integration + tests + green PR gates.

Не переходить автоматически к live/R30E. Следующий live этап, если он останется нужен, должен получить отдельный task contract и отдельную user authorization.