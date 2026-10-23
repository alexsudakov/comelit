# Issue #319 R2 — архитектура непрерывности video при Ring

Статус: `P0-A=NOT_FIXED/NOT_PROVEN`, `P0-B=NOT_FIXED/NOT_PROVEN`.

Граница анализа: offline, без production emit, protocol write, identity
promotion, live action, второго upstream и duplicate Ring. Текущая реализация
добавляет только bounded production-inert evidence ledger.

## 1. Сравнение трёх путей

`A` — official-app live-video + Ring; `B` — HA on-demand media-owner + Ring;
`C` — HA listener-attached adopted Ring.

| Ось | A: official app | B: HA media-owner | C: HA listener-attached | Current code / R28 / R54-R57 evidence |
|---|---|---|---|---|
| CTP INVITE/ACK | Native call FSM принимает INVITE и подтверждает call transaction | `CALL_INIT` только наблюдается; ACK для active self-activation не доказан | Adopted call использует call-scoped ACK | Current: B не пишет; R28 показывает self-activation; R54/R57 показывают adoption, но не разрешают перенос в B |
| CAPABILITIES/ALERTING | Выполняются call FSM | Не доказано, что допустимы или не нужны | Выполняются принятой call transaction | Current: отсутствуют в B; R54/R57 относятся только к C |
| peer capability | Известна native FSM | В active media transaction не доказана | Получена в adopted call | R28 не доказывает call peer capability; R54/R57 не доказывают её эквивалентность |
| `0x001A` | Native FSM классифицирует ответ | initial self-activation известен; второй ответ неоднозначен | Call adoption использует доказанный контекст | Current ledger различает `STRUCTURAL_ACK`, `AMBIGUOUS`, `ABSENT`; не создаёт TX |
| MEDIAREQ26 OPEN/STOP | Call-scoped media lifecycle | Уже открыт self-activation RTPC | Открывается после adoption | R28 доказывает B OPEN; R54/R57 доказывают C OPEN/STOP, но не coexistence |
| Владение RTP-каналом | Один native owner | Media helper владеет существующим RTP | Adopted call owner открывает RTP | Current ownership не меняется; ledger не консультируется lifecycle |
| PseudoTCP terminal-notify | Обрабатывает native FSM | Может завершить helper; причина должна быть записана | Связано с adopted lifecycle | Current ledger фиксирует native exit/stop/teardown, но не влияет на terminalization |
| release/reconnect | Native call FSM | Семантика release после Ring не доказана | Call identity ограничивает release | R54/R57 не доказывают stable cross-owner identity для B |
| Граница 120 s | Native политика неизвестна | Call-state watchdog остаётся 120 s и fail-closed | Listener call watchdog известен | Current: граница не изменена; ledger только фиксирует наблюдения |

Official path и C показывают возможность одного upstream только при принятой
call transaction. B уже находится в self-activation transaction. Перенос
adoption writes из C в B был бы новым протокольным поведением, а параллельный
listener создал бы второй upstream.

## 2. Реестр инвариантов

| Инвариант | Состояние | Следствие |
|---|---|---|
| `MEDIA_OWNER_RECEIVES_CALL_INIT` | Наблюдаем диагностически | Недостаточно для emit или continuity |
| `MEDIA_OWNER_CTPP_CONNECTION_IS_CALL_ADOPTION_TARGET` | `NOT_PROVEN` | Adoption TX запрещён |
| `MEDIA_OWNER_CAN_ADOPT_CALL_WITHOUT_DROPPING_EXISTING_RTPC` | `NOT_PROVEN` | `P0-B=NOT_FIXED` |
| `CALL_MEDIA_CHANNEL_AND_SELF_ACTIVATION_CHANNEL_COEXIST` | `NOT_PROVEN` | Нельзя создавать второй RTPC channel по аналогии |
| `OFFICIAL_APP_ONDEMAND_VIDEO_SURVIVES_RING_AT_PROTOCOL_LEVEL` | `NOT_PROVEN` в доступном raw evidence | Official UX не является wire-proof |
| `INDEPENDENT_NATIVE_CALL_IDENTITY_PROVEN=false` | Fail-closed факт | `P0-A=NOT_FIXED`; generation/epoch/SHA не повышаются до identity |

Точный недостающий объединённый invariant:

```text
ACTIVE_SELF_ACTIVATION_CALL_INIT_PRESERVES_RTP_WITHOUT_ADOPTION_TX_AND_HAS_STABLE_CROSS_OWNER_CALL_IDENTITY
```

Он требует одновременно: роста RTP в том же helper/ICE/PseudoTCP/CTPP/RTPC
после `CALL_INIT` без call-adoption TX; одинаковой immutable identity у initial
и retransmit одного Ring; различимой identity у следующего Ring; и release,
завершающего ровно соответствующий call.

## 3. Решение D1/D2/D3

| Решение | Вердикт | Обоснование |
|---|---|---|
| D1: in-place call adoption в CTPP-сессии media owner | `REJECT` | Требует protocol writes (ACK/CAPABILITIES/ALERTING/peer ACK/MEDIAREQ26) и доказанного coexistence с уже открытым self-activation RTPC; ни то, ни другое не доказано |
| D2: confirmed-teardown-first перенос просмотра в listener-attached call stream | `REJECT` | Не непрерывность: teardown gap; плюс identity/dedup-риск на возобновлённом listener |
| D3: fail-closed плюс bounded diagnostics | `SELECTED` | Сохраняет текущие ownership, emit и protocol boundaries; делает следующий тест атрибутируемым |

## 4. Минимальная решающая проверка

Один отдельно авторизованный физический Ring во время уже активного on-demand
video достаточен для проверки continuity-инварианта. До Ring фиксируются один
helper, ICE, PseudoTCP, CTPP, RTPC и RTP counter. После Ring без listener start
и без protocol write должны быть получены: `CALL_INIT`, явные
`SECOND_001A_RESPONSE` и `ACK_CLASSIFICATION`, `REFRESH_FAIL_CLOSED`, строго
растущий RTP counter, неизменные channel counts, затем native exit code,
stop reason, `teardown_confirmed=true` и `listener_resumed=true`. Любой новый
upstream/RTPC, TX, exit до роста RTP, неоднозначный ACK или потеря teardown
evidence даёт `NO_GO`.

Эта одна проверка не доказывает различимость identity между двумя физическими
calls. Для снятия `P0-A` нужна отдельная последующая пара calls. До этого
`INDEPENDENT_NATIVE_CALL_IDENTITY_PROVEN=false` и production emit запрещён.

## 5. Production-inert ledger

`custom_components/comelit/ring_episode.py` принимает только allowlisted
scalar-маркеры и lifecycle-факты. Он хранит monotonic offsets, caps,
`dropped_invalid`, `unattributed` и `evicted` accounting. `media_transport.py`
передаёт native exit; `media_session.py` передаёт stop reason, teardown и
listener resume. Исключения локализуются `RingShadowHook`; payload/credentials
не сохраняются. Ни start/stop, ни watchdog, ни Ring classification не читают
ledger. Статические поля `production_effect=false` и
`protocol_write_performed=false` описывают эту границу.

### 5.1 Generation-scoped episode handle

Эпизод открывается только в `RingShadowController.note_state(media,
"media_transport_start")` после инкремента `_owner_generation`, с явным
`owner_generation` и внутренним `episode_id`. Все native-строки и lifecycle-
факты передаются вместе с generation; несовпадение или отсутствие контекста
увеличивает `unattributed` и не мутирует активный эпизод. Эпизод закрывается
детерминированно: `listener_resumed`/`resume_failed` (bounded terminal marker),
`replaced` при новом media-start, либо `reset`. Late-события после seal
отклоняются и учитываются как `unattributed`, а не приклеиваются к новому
эпизоду. `ABSENT` больше не значение по умолчанию: не наблюдавшееся поле
остаётся `None`, `ABSENT` ставится только явным маркером.
`reset()` симметрично очищает эпизоды, события, счётчики и `episode_id`.
Каждый новый transport создаёт собственный ledger и не подменяет чужой
(handoff не требуется: ledger не является общим состоянием между сессиями).
