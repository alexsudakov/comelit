# P116 / R30C — задача Hermes: native CTP adoption evidence

Статус: **готово к исполнению / OFFLINE STATIC ONLY**

TASK_ID=`COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE`

Основной контракт:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_CONTRACT.md
```

Родительские результаты:

```text
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md
safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md
```

## Роль Hermes

Это исследовательская DOCS/evidence-задача. Изменять executable code / JSON / scripts не требуется.

```text
HERMES_ROLE=STATIC_EVIDENCE_ORCHESTRATOR
CODEX_REQUIRED=false
LIVE_AUTHORIZED=false
NETWORK_TX_ALLOWED=false
```

Если в ходе работы выяснится, что для получения доказательства необходимо написать/итерационно отлаживать новый executable parser/extractor/script, не делай это самостоятельно: остановись с `RESULT=BLOCKED_NEEDS_ITERATIVE_TOOLING` и перечисли точный недостающий инструмент. Тогда будет создана отдельная Codex-задача.

Обычные read-only команды `nm`, `readelf`, `objdump`/`llvm-objdump`, `strings`, `rg`, `grep`, `sed`, `awk`, `sha256sum` и bounded shell pipelines разрешены и не считаются новой реализацией протокола.

## Bootstrap

Работай только от свежего `origin/main` публичного `alexsudakov/comelit`.

```text
REPOSITORY_PATH=/home/hermes/repos/comelit
SOURCE_OF_TRUTH=origin/main
```

Перед анализом:

1. `git fetch origin main`;
2. зафиксируй фактический SHA `origin/main`;
3. создай отдельную ветку/worktree от свежего `origin/main` только для result-document;
4. не продолжай R30B worktree/branch;
5. GitHub remote должен остаться credential-free;
6. не выводи содержимое credential/token.

Прочитай в порядке:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_CONTRACT.md
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md
safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md
safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/research/media/v1/entrance_p116_r30_call_ctp_envelope_model.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
```

## Цель

Закрыть или честно локализовать два оставшихся transport unknown после R30B:

```text
1. official native inbound call CTP id mapping;
2. official native first local sequence / acknowledgement ownership and evolution.
```

Не исследуй сейчас RTP, H.264, Door/Gate, refresh, media lease или production HA lifecycle.

## CT120: только статические/read-only источники

Разрешён доступ к уже существующим исследовательским материалам CT120, в частности известным каталогам native/static evidence.

Ничего не запускать против Comelit endpoint. Не запускать research candidate, listener replacement, ICE/PseudoTCP/cloud session или live helper.

Ищи уже существующие native libraries/text-disassembly/provenance. Proprietary binaries и raw captures не копируй в Git.

Перед использованием каждого proprietary input зафиксируй в локальном evidence-log только:

```text
artifact class
локальный путь
SHA256
тип/архитектура при необходимости
```

В public result-document не публикуй приватные абсолютные пути, если они не нужны для воспроизводимости; предпочтительно указывать artifact alias + SHA256.

## Native targets

В первую очередь найди/проанализируй dataflow вокруг:

```text
VipUnitImpl::new_call_ctp_conn
VipUnitImpl::handleCtpStart
VipUnitImpl::vip_unit_accept_call
CallFsm::initNewConnectionStart
ctp_write
```

Затем функции CTP transport layer, которые:

```text
- принимают inbound CTP SYN;
- создают/находят connection object;
- вызывают new_call_ctp_conn;
- хранят local/peer connection ids;
- сериализуют wire connection field;
- хранят/обновляют TX sequence;
- хранят/обновляют RX acknowledgement.
```

Не полагайся только на names. Нужны instruction/dataflow/call-site anchors.

## Вопрос A — mapping call_ctp_id

Для inbound packet проследи:

```text
received wire bytes 2..3
-> parser / connection object
-> callback argument new_call_ctp_conn(...)
-> handleCtpStart / vip_unit_accept_call
-> CallFsm::initNewConnectionStart(call_ctp_id,...)
-> stored CallFsm call_ctp_id
-> csp_send_mediareq26
-> ctp_write(call_ctp_id,...)
-> wire serialization
```

Проверь специально наличие/отсутствие преобразований:

```text
xor/eor bit 15
OR 0x8000
AND/BIC 0x7fff / 0x8000
byte swap independent from direction transform
lookup table by opaque short id
separate local_id / peer_id fields
```

В конце выбери ровно одну классификацию:

```text
A_NATIVE_CALLBACK_ID_IS_RECEIVED_WIRE_ID
B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID
C_NATIVE_CALLBACK_ID_IS_OPAQUE_INTERNAL_HANDLE
D_NATIVE_LOCAL_ID_MAPPING_NOT_PROVEN
```

Если результат A или C, отдельно объясни, какой id `ctp_write` фактически кладёт в wire header.

Не повышай публичный XOR rule до native proof без native/capture evidence.

## Вопрос B — sequence / acknowledgement

Проследи отдельно:

```text
- где создаётся initial local TX sequence для adopted inbound call;
- меняется ли sequence при пустом ACK;
- когда sequence увеличивается после body-bearing send;
- откуда берётся ACK field первого client packet;
- обновляется ли ACK как peer_sequence + 1 modulo 256;
- кто владеет state: CallFsm/CSP или CTP transport connection object.
```

Обязательные выходные поля:

```text
FIRST_LOCAL_TX_SEQUENCE_SOURCE=
LOCAL_SEQUENCE_ADVANCEMENT_RULE=
INITIAL_LOCAL_ACK_SOURCE=
ACKNOWLEDGEMENT_UPDATE_RULE=
SEQUENCE_STATE_OWNER=
```

Для каждого поставь evidence class:

```text
PROVEN_NATIVE
PROVEN_CAPTURE_RELATION
STRONGLY_SUPPORTED_EXTERNAL
NOT_PROVEN
```

## Saved captures

Если на CT120 есть уже сохранённый capture официального inbound call, разрешён только offline/read-only анализ.

Не публикуй raw packet bytes. Вместо этого сформируй redacted relation table по независимым call transactions:

```text
sample_alias
peer_connection_relation
client_connection_relation
peer_seq_relation
client_ack_relation
client_seq_transition_relation
```

Числа connection/sequence замени symbolic/relative relation, если literal не нужен для доказательства.

Одна транзакция не доказывает generation rule. Для promotion capture relation желательно минимум две независимые транзакции/сессии; иначе оставь `OBSERVED_SINGLE_SAMPLE`.

## Public external corroboration

Можно read-only сверить pinned ref:

```text
jfmlima/comelit-vip@e3714dcccadb5bf934c32ce1400d891c3cfc61bb
```

Особенно:

```text
custom_components/comelit_vip/viper/ctp.py
custom_components/comelit_vip/viper/session.py
tests/test_displacement.py
tests/fake_panel.py
```

Но итоговая классификация этого evidence не выше:

```text
STRONGLY_SUPPORTED_EXTERNAL
```

## P76 structural evidence

Отдельно проверь текущий main:

```text
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
```

Подтверди, что историческая операция `+ 0x00010000` над composite header state увеличивает именно CTP sequence byte после восстановленного R30A layout, не меняя connection/ack bytes.

Это должно дать только:

```text
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true|false
```

Она не доказывает initial seed.

## Fail closed

Если native code не позволяет однозначно связать callback short id с wire connection id:

```text
LOCAL_ID_CLASSIFICATION=D_NATIVE_LOCAL_ID_MAPPING_NOT_PROVEN
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
```

Если initial local TX sequence скрыт внутри недоступной library/connection object:

```text
FIRST_LOCAL_TX_SEQUENCE_SOURCE=NOT_PROVEN
```

Не подставляй random seed или XOR из public implementation как native truth.

## Разрешённый Git scope

Результат задачи — только один новый файл:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
```

Не изменять существующие файлы.

Запрещены изменения:

```text
custom_components/comelit/**
safety-poc/src/**
safety-poc/scripts/**
*.py
*.sh
*.c
docs/intercom-media-session-architecture.md
docs/ha-integration-target-architecture.md
README.md
```

Если для результата требуется изменение executable artifact — STOP.

## Safety invariants

На всём протяжении задачи:

```text
LIVE_RUN=NOT_RUN
LIVE_AUTHORIZED=false
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_DEPLOY_COUNT=0
HA_RESTART_COUNT=0
HA_RELOAD_COUNT=0
PRODUCTION_FILES_CHANGED=0
```

Не делать listener stop/start/status mutation. Read-only production status вообще не нужен для этой задачи.

## Verification result-document

В `P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md` обязательно включи:

- base SHA;
- evidence inventory;
- aliases/SHA native artifacts;
- bounded function/dataflow findings;
- local-id decision A/B/C/D;
- отдельный `ctp_write` mapping conclusion;
- sequence/ack таблицу;
- capture relation table, если использовалась;
- public external corroboration отдельно от native evidence;
- P76 structural finding;
- residual unknowns;
- следующий decision gate.

Не включай raw proprietary dumps или больше bounded disassembly, чем необходимо для проверки вывода.

## Git / PR

После result-document:

1. проверить, что diff = ровно один новый `.md`;
2. commit/push отдельной ветки;
3. открыть PR в `main`;
4. дождаться `offline-safety` и `Validate HACS`;
5. merge только при зелёных обязательных gate и чистом scope.

Если права Hermes не позволяют PR — push ветки и вернуть точный branch/SHA; PR создаст оператор/ChatGPT через доступный GitHub connector.

## Итоговый блок Hermes

Полезный итог должен быть последним:

```text
=== COMELIT P116 R30C NATIVE CTP ADOPTION EVIDENCE ===
TASK_ID=COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE
BASE_SHA=<fresh-origin-main>
FINAL_SHA=<branch-head-or-pending>
CHANGED_FILES=<must-be-one-md>
NATIVE_EVIDENCE_AVAILABLE=true|false
SAVED_CAPTURE_EVIDENCE_USED=true|false
LOCAL_ID_CLASSIFICATION=A_NATIVE_CALLBACK_ID_IS_RECEIVED_WIRE_ID|B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID|C_NATIVE_CALLBACK_ID_IS_OPAQUE_INTERNAL_HANDLE|D_NATIVE_LOCAL_ID_MAPPING_NOT_PROVEN
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN|NOT_PROVEN
CTP_WRITE_WIRE_ID_MAPPING=PROVEN|PARTIAL|NOT_PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=<value>
FIRST_LOCAL_TX_SEQUENCE_EVIDENCE=<class>
LOCAL_SEQUENCE_ADVANCEMENT_RULE=<value>
LOCAL_SEQUENCE_ADVANCEMENT_EVIDENCE=<class>
INITIAL_LOCAL_ACK_SOURCE=<value>
INITIAL_LOCAL_ACK_EVIDENCE=<class>
ACKNOWLEDGEMENT_UPDATE_RULE=<value>
ACKNOWLEDGEMENT_UPDATE_EVIDENCE=<class>
SEQUENCE_STATE_OWNER=<value>
SEQUENCE_STATE_OWNER_EVIDENCE=<class>
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true|false
PUBLIC_XOR_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
PUBLIC_ACK_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
LIVE_AUTHORIZED=false
OFFLINE_SAFETY=PASS|FAIL|UNAVAILABLE
VALIDATE_HACS=PASS|FAIL|UNAVAILABLE
PR=<number-or-none>
RESULT=PROVEN_OFFLINE|PARTIAL_OFFLINE|BLOCKED_MISSING_NATIVE_EVIDENCE|BLOCKED_NEEDS_ITERATIVE_TOOLING|FAIL
=== END COMELIT P116 R30C NATIVE CTP ADOPTION EVIDENCE ===
```

После итогового блока STOP. Не переходить к R30D и тем более к live автоматически.