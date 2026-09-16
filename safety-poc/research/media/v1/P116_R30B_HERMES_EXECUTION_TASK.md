# P116 / R30B — задача Hermes/Codex

Статус: **готово к исполнению / offline-only**

TASK_ID=`COMELIT-P116-R30B-OFFLINE-CALL-TRANSACTION-EXECUTION`

Основной контракт: `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_EXECUTION_CONTRACT.md`

Родительское исследование: `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md`

## Задача

Выполни R30B как полностью offline DEV/RESEARCH-задачу. Hermes должен быть только оркестратором; все изменения исполняемого кода, тестов, скриптов и итерационные исправления выполняет Codex CLI.

Цель — построить и проверить offline-модель call-scoped CTP transaction для входящего звонка, которая:

1. разбирает полный CTP INVITE внутри уже существующего внешнего CTPP handle;
2. сохраняет отдельное состояние входящей call transaction;
3. моделирует ACK только через intercepted writer;
4. не позволяет перейти к media OPEN до semantic capability/alerting barrier;
5. выделяет ровно один synthetic media-channel id;
6. строит существующий доказанный 26-байтный media OPEN body и оборачивает его в полный 60-байтный call-bound CTP packet;
7. строит STOP только после OPEN, с тем же media-channel id, и также оборачивает его в полный CTP packet;
8. никогда не выполняет network TX, Door/Gate, self-activation, repeat/refresh, HA deploy/restart.

## Обязательный bootstrap

Работай только из свежего `origin/main`.

```text
REPOSITORY_PATH=/home/hermes/repos/comelit
SOURCE_OF_TRUTH=origin/main
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
HERMES_ROLE=ORCHESTRATOR_ONLY
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
NETWORK_TX_ALLOWED=false
DOOR_ALLOWED=false
GATE_ALLOWED=false
HA_DEPLOY_ALLOWED=false
HA_RESTART_ALLOWED=false
```

Сначала:

- `git fetch origin main`;
- зафиксируй фактический `origin/main` SHA;
- создай отдельную ветку/worktree от свежего `origin/main`;
- не продолжай старую research-ветку;
- remote должен оставаться credential-free;
- не выводи токен или credential contents.

Перед изменениями обязательно прочитай:

```text
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_EXECUTION_CONTRACT.md
safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md
safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md
safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md
safety-poc/research/media/v1/entrance_p116_r30_call_ctp_envelope_model.py
safety-poc/tests/test_p116_r30_call_ctp_envelope_recovery.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/research/media/v1/entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py
safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
```

## Жёсткий executor gate

До любых изменений выполни preflight Codex.

Обязательно зафиксируй в отчёте:

```text
CODEX_COMMAND_PRESENT=true|false
CODEX_VERSION=<version-or-unavailable>
ACTUAL_EXECUTOR=codex-cli|other|unavailable
```

Если `command -v codex` не проходит или фактический executor не `codex-cli`, немедленно остановись:

```text
RESULT=BLOCKED_EXECUTOR_UNAVAILABLE
```

Hermes не имеет права в этом случае сам писать код, использовать другой coding agent или обходить gate.

## Что должен сделать Codex

Реализовать исполняемую offline-модель и focused tests по контракту R30B. Ожидаемые файлы:

```text
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/tests/test_p116_r30b_offline_call_transaction.py
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
```

Дополнительный research-only transform/generator допускается только если без него нельзя доказать структурную эквивалентность существующему helper lineage.

Запрещено менять:

```text
custom_components/comelit/**
docs/intercom-media-session-architecture.md
docs/ha-integration-target-architecture.md
README.md
```

## Ключевые технические требования

Не смешивай три идентификатора:

```text
outer CTPP handle
CTP connection id входящей call transaction
logical call id внутри INVITE
```

`outer_ctpp_handle` никогда не должен использоваться как call connection id.

Direction-bit правило `connection ^ 0x8000`, известное из публичной реализации, разрешено только как offline candidate/corroborating behavior. Оно должно остаться явно помеченным:

```text
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
```

Не превращай это правило в доказанный native constant.

Sequence/ack должны храниться отдельными полями. Не переноси старый `previous_client_ctpp_sequence` как один 32-битный sequence scalar. Runtime seed должен быть synthetic/injected; нельзя брать literal из capture как protocol constant.

Capability/alerting до media OPEN моделируй как semantic ordering barrier. Не придумывай wire bytes. Если в репозитории найдётся уже доказанный exact builder — можно использовать его только со ссылками на lineage и отдельными тестами.

Media-channel id:

- один на call;
- выделяется после signaling barrier;
- non-zero;
- OPEN сохраняет его;
- STOP использует тот же id;
- duplicate allocation/OPEN/STOP и STOP-before-OPEN должны fail closed.

OPEN/STOP mediareq26 body используй из уже доказанного R29E/R29C lineage. Не создавай новый layout.

Все outbound действия заканчиваются только in-memory/intercepted writer. В модели не должно быть `socket`, сетевых subprocess/curl/nc, PseudoTCP/ICE/cloud bootstrap или HA service invocation.

## Обязательный happy path

В конце offline happy-path должно быть:

```text
CALL_TRANSACTION_CAPTURE=PASS
OUTER_CTPP_HANDLE_SEPARATION=PASS
ACK_MODEL_INTERCEPTED=PASS
CALL_SIGNALING_ORDER_BARRIER=PASS
MEDIA_CHANNEL_SINGLE_ALLOCATION=PASS
FULL_CTP_MEDIA_OPEN_SERIALIZATION=PASS
FULL_CTP_MEDIA_STOP_SERIALIZATION=PASS
OPEN_STOP_MEDIA_CHANNEL_IDENTITY=PASS
PER_CALL_SEQUENCE_STATE=PASS
INTERCEPTED_ACK_WRITES=1
INTERCEPTED_MEDIA_OPEN_WRITES=1
INTERCEPTED_MEDIA_STOP_WRITES=1
NETWORK_WRITES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
LIVE_CALL_BOUND_MEDIA=NOT_PROVEN
LIVE_AUTHORIZED=false
```

## Negative tests

Обязательно проверь минимум все negative cases из раздела 13 основного R30B contract, включая malformed/truncated CTP, wrong version, non-SYN initial packet, non-INVITE SYN, outer handle reused as call id, media before barrier/allocation, invalid/duplicate media channel, duplicate OPEN, STOP before OPEN, STOP с другим channel id, duplicate STOP, forbidden self-activation/repeat, network writer reachability, Door/Gate reachability.

Также сохрани regression, доказывающий, что исторический R29C действительно отправлял bare 26-byte body на outer CTPP handle — не переписывай смысл отрицательного live результата задним числом.

## Итерационный цикл

После первой реализации Codex:

1. запусти focused R30B tests;
2. запусти полный repository offline test suite;
3. выполни static/offline safety checks репозитория;
4. разберись с каждым FAIL;
5. передай исправление обратно Codex;
6. повторяй до PASS либо доказанного BLOCKED.

Hermes не должен сам исправлять код между попытками.

## GitHub

После локального PASS:

- проверь diff и разрешённые пути;
- commit/push через credential helper проекта, не встраивая токен в remote URL;
- открой отдельный PR в `main`;
- дождись `offline-safety` и `Validate HACS`;
- если CI падает, исправления снова делает Codex в той же R30B ветке;
- не merge при красном/неизвестном обязательном gate;
- merge только после зелёных обязательных проверок и итоговой проверки scope.

## Что запрещено

В этой задаче запрещены:

```text
любая live Comelit передача
CT120 live probe
новый upstream session
Door
Gate
self-activation
media refresh/repeat
HA deploy
HA restart/reload
изменение production integration
изменение normative media architecture
сырой PCAP/APK/DEX/native artifact в commit
токен или credential content в выводе/commit/log
```

Никакая предыдущая live-авторизация не переносится на R30B.

## Итоговый отчёт Hermes

Полезный итог выведи в самом конце, после всех технических логов, отдельным блоком. Он должен содержать:

```text
TASK_ID=COMELIT-P116-R30B-OFFLINE-CALL-TRANSACTION-EXECUTION
BASE_SHA=<fresh-origin-main-at-start>
FINAL_SHA=<branch-head>
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=<version>
CHANGED_FILES=<count-and-paths>
FOCUSED_TESTS=<pass/fail-count>
FULL_OFFLINE_TESTS=<pass/fail-count>
OFFLINE_SAFETY=<PASS|FAIL|UNAVAILABLE>
VALIDATE_HACS=<PASS|FAIL|UNAVAILABLE>
PR=<number-or-none>
CALL_TRANSACTION_CAPTURE=<PASS|FAIL>
OUTER_CTPP_HANDLE_SEPARATION=<PASS|FAIL>
ACK_MODEL_INTERCEPTED=<PASS|FAIL>
CALL_SIGNALING_ORDER_BARRIER=<PASS|FAIL>
MEDIA_CHANNEL_SINGLE_ALLOCATION=<PASS|FAIL>
FULL_CTP_MEDIA_OPEN_SERIALIZATION=<PASS|FAIL>
FULL_CTP_MEDIA_STOP_SERIALIZATION=<PASS|FAIL>
OPEN_STOP_MEDIA_CHANNEL_IDENTITY=<PASS|FAIL>
PER_CALL_SEQUENCE_STATE=<PASS|FAIL>
NETWORK_WRITES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
LIVE_CALL_BOUND_MEDIA=NOT_PROVEN
LIVE_AUTHORIZED=false
RESULT=<PROVEN_OFFLINE|BLOCKED|FAIL>
```

Не продолжай к live-тесту автоматически даже при `RESULT=PROVEN_OFFLINE`.