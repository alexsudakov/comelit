# P120 — COMELIT-ICE-GATHERING-RETRANSMISSION-FORENSIC-V1

Offline-only forensic round on the exact runtime library. Никаких изменений production,
никакого live, ни Claude, ни Codex.

## PHASE A — PROMOTION L1

- `origin/main`: `42aa134af752b72bec82074566681011d8b38e42` → **`69806e9a851e672362128081c6b0dbd4476f985d`** (fast-forward, 2 коммита).
- Перед merge: `MAIN_MOVED=false`, `FF_POSSIBLE=true`, diff scope 17 файлов (все внутри
  `custom_components/comelit/` и `safety-poc/`), Validate HACS на exact candidate SHA = success
  (run `36310651446`), focused/full/offline гейты PASS.
- Байт-идентичность с production: member-уровневый дайджест (sha256 по отсортированным
  `(sha256(file), path)`) отгруженного payload'а и дерева merged main **совпал** ⇒
  `PRODUCTION_BYTES_MATCH_MERGED_MAIN=true`, `REDEPLOY_REQUIRED=false`.
- Restart ради promotion не выполнялся; production остаётся на `69806e9a…`
  (`DEPLOYED_SHA` до и после merge один и тот же).

## PHASE B — EXACT TIMER TRACE (libnice 0.1.22)

Источник: upstream tag `0.1.22`, read-only, sha зафиксированы
(`stun/usages/timer.h`, `stun/usages/timer.c` 376e7c68…, `agent/agent.c` 691c95bf…,
`agent/discovery.c` 1b1018d0…, `agent/conncheck.c` ff44f225…, `agent/agent-priv.h` f2dbb987…).

**Дефолты (exact source, не документация):**

| константа | значение | место |
|---|---|---|
| `STUN_TIMER_DEFAULT_TIMEOUT` (RTO) | **500 ms** | `stun/usages/timer.h:146` |
| `STUN_TIMER_DEFAULT_MAX_RETRANSMISSIONS` (Rc) | **3** | `stun/usages/timer.h:154` |
| `STUN_TIMER_DEFAULT_RELIABLE_TIMEOUT` | 2000 ms | `stun/usages/timer.h:165` |

⇒ **Проверка вашей гипотезы: CONFIRMED.** RTO=500, Rc=3. При этом комментарий-документация в
`agent/agent.c:835-846` («described as 'Rc' in the RFC 5389, with a default value of 7») **устарел**:
реальная константа 0.1.22 = 3. Значение 7 из doc-комментария не действует.

**Расписание (exact):** `stun_timer_start()` (`timer.c:105`) ставит `retransmissions=1`,
`delay=initial_timeout`, deadline=now+delay. `stun_timer_refresh()` (`timer.c:137-160`):
если `retransmissions >= max` → `TIMEOUT`; иначе, если `retransmissions == max-1` → `delay /= 2`
(последняя передача укорачивается), иначе `delay *= 2`; `retransmissions++` → `RETRANSMIT`.
Счёт идёт по **попыткам**, а не по «повторам сверх первой».

Для RTO=500, Rc=3: попытки на `t=0`, `t=500`, `t=1500`, истечение транзакции на **`t=2000 ms`**.
Совпадает с `STUN_TIMER_DEFAULT_RELIABLE_TIMEOUT=2000` численно, но это независимая константа;
наша discovery-транзакция использует именно RTO/Rc-расписание (`discovery.c:269-270`,
`discovery.c:1323-1324`), а не reliable-таймер.

`EXPECTED_DISCOVERY_FAILURE_DURATION_MS=2000` — **подтверждено формулой и замером**
(production: `FIRST_SRFLX_TO_GATHER_DONE_MS=1996`).

## PHASE C — один srflx на 40 ms, но done на +1996

Модель (exact source):

1. `nice_agent_gather_candidates()` (`agent.c:3678-3708`): если приложение **не** добавляло
   локальные адреса (наш helper `nice_agent_add_local_address` не вызывает — grep = 0), libnice
   сам перечисляет **все** локальные IP (`nice_interfaces_get_local_ips`) → host-кандидат на каждый
   адрес и компонент (у нас 1 компонент ⇒ 5 host-кандидатов = 5 базовых адресов: NIC + виртуальные/
   контейнерные интерфейсы).
2. Для каждого базового адреса, имеющего host-кандидат, ставится **своя** STUN-транзакция
   `discovery_add_server_reflexive_candidate()` (`discovery.c:930-955`: цикл по
   `component->local_candidates`). ⇒ discovery-транзакций несколько, они идут параллельно.
3. Discovery-tick: `if (not_done == 0) { discovery_free(agent); agent_gathering_done(agent); }`
   (`discovery.c:1409-1424`). Неуспешный элемент удаляется **только по истечении** своего таймера
   (`else ++not_done /* discovery not expired yet */`).

⇒ `MULTIPLE_DISCOVERY_TRANSACTIONS=true`, `GATHER_DONE_WAITS_ALL_DISCOVERIES=true`.
Наблюдение (5 host / 1 srflx) означает: один базовый адрес дал srflx за ~40 ms, остальные — нет;
все они стартуют почти одновременно, поэтому «gathering done» задаётся полным расписанием
самого медленного (истекающего) элемента ⇒ ~2000 ms. Замеренные 1996 ms — это **одно полное
RTO/Rc-расписание**, а не совпадение и не «ещё один RTT».
`SUCCESSFUL_SRFLX_RESPONSE_MS=40` → успешный путь event-driven: кандидат добавляется по приходу
ответа, таймеры управляют только retransmit/expiry.
Точную идентичность pending-транзакций из имеющегося evidence установить нельзя (нет
per-transaction маркеров, IP не раскрываем); offline доказуемо: ≥1 истекающая транзакция
необходима, чтобы объяснить 1996 ms.

## PHASE D — можно ли сделать gather-only override

| вопрос | ответ | доказательство |
|---|---|---|
| свойства writable после construction | **true** | `G_PARAM_READWRITE \| G_PARAM_CONSTRUCT` (не CONSTRUCT_ONLY), сеттеры `agent.c:1737-1745` присваивают поля агента |
| транзакция копирует значения или читает динамически | **копирует на старте** | `stun_timer_start()` записывает `delay`/`max_retransmissions` в сам `StunTimer` (`timer.c:105-113`) |
| connectivity-check использует актуальные значения на момент создания | **true** | `conncheck.c:2987`: `stun_timer_start(&stun->timer, timeout, agent->stun_max_retransmissions)` |
| restore после gathering повлияет на последующие checks | **true** | то же место + отсутствие кэширования свойства (только поля агента) |
| hidden caching | **none found** | `agent-priv.h:148-149` — обычные `guint`-поля |

**Ключевая асимметрия (новое):** connectivity checks **не используют `stun_initial_timeout` вообще**.
Их таймаут считается как `priv_compute_conncheck_timer()` = `MAX(timer_ta ×
waiting_and_in_progress, STUN_TIMER_DEFAULT_TIMEOUT)` (`conncheck.c:2850-2861`, нижняя граница —
литерал 500 ms), и из свойств берётся только `stun_max_retransmissions`.
⇒ изменение `stun-initial-timeout` **структурно gather-only**: до checks дотянуться не может
(оно влияет ещё на discovery/refresh и TURN-пути: `discovery.c:269`, `discovery.c:1323`,
`agent.c:7722`). Изменение `stun-max-retransmissions` — общий knob (gather + checks), поэтому
требует restore до первой check-транзакции; окно для restore у нас большое
(gathering-done → cloud negotiate ≈386 ms → remote.sdp → checks).

`GATHER_ONLY_OVERRIDE_POSSIBLE=true`, `CONNECTIVITY_CHECK_DEFAULT_CAN_BE_RESTORED=true`.

## PHASE E — варианты (offline, не реализовывать)

Расписание/истечение (RTO, Rc): default = `2000 ms`.

| вариант | RTO / Rc при gather | истечение | ожидаемая экономия | влияет на checks | риск |
|---|---|---|---|---|---|
| **A** Rc 3→2, restore после | 500 / 2 | 750 ms | **≈1250 ms** | да, если не восстановить (restore доказуем) | medium-high |
| **B** RTO 500→250, restore после | 250 / 3 | 1000 ms | **≈1000 ms** | **нет by construction** | medium |
| **C** оба | 250 / 2 | 375 ms | **≈1625 ms** | как в A | high |
| (справочно) Rc=1 | 500 / 1 | 500 ms | ≈1500 ms | да | high (одна потеря пакета = нет srflx) |

`SUCCESSFUL_40MS_SRFLX_AFFECTED=no` для всех вариантов при RTT ~40 ms (успех event-driven и
приходит задолго до истечения), но при **более медленной сети/потере пакета** budget сокращается
и srflx может не появиться: это и есть цена. Rc=3→2 оставляет 2 попытки (0/500), RTO 250/Rc=3 —
три попытки с окном 1000 ms. 40 ms **не считать универсальным RTT**.

## PHASE F — фильтрация интерфейсов/кандидатов

libnice это умеет: если приложение добавляет ≥1 адрес через `nice_agent_add_local_address()`
(`agent.c:4030-4041`), автоматическое перечисление **выключается** (`agent.c:3682-3708`) →
«doomed» discovery на недостижимом/виртуальном интерфейсе просто не создаётся.
Но: нужно динамически доказать, какой базовый адрес является default-route/UDP-пригодным в HAOS
(контейнерные/виртуальные режимы), а это меняет набор кандидатов в offer (protocol-visible).
`CANDIDATE_FILTERING_SAFE_PROVEN=false` ⇒ не рекомендую в этом раунде; категории, которые нужно
будет доказать перед любым применением: DEFAULT_ROUTE_INTERFACE vs
NON_DEFAULT_ROUTE_INTERFACE / VIRTUAL-CONTAINER / IPV6 / LINK_LOCAL.

## L2 — заморожен

`ICE_CONNECTED_TO_ICE_READY_MS=1987` численно близок к STUN-расписанию, но это coincidence:
check-таймаут считается по `timer_ta ÷ 500` floor, а не по `stun_initial_timeout`.
Никаких изменений check-настроек, никакого PseudoTCP на CONNECTED.

## Итог

`STUN_SETTINGS_CHANGED=false`, `ICE_SETTINGS_CHANGED=false`, `LIVE_RUNS=0`, `CAMERA_OPENS=0`,
`DEPLOYMENT_CHANGES=0` (кроме git-promotion, который не меняет развёрнутые байты).
Предпочтительный следующий кандидат: **GATHER_ONLY_RETRANSMISSION_REDUCTION, вариант B**
(RTO 500→250 только на окно gathering + restore 500 после gathering-done) — единственный
вариант, который по построению не может задеть connectivity checks; ожидаемо ≈1000 ms из 1996 ms
хвоста gathering. Вариант A — как следующий шаг, если B окажется недостаточным (требует restore
до первой check-транзакции; restore доказан). Вариант C и Rc=1 — не рекомендую.
