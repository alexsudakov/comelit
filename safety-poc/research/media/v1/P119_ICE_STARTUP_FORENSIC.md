# P119 — COMELIT-PRODUCTION-CAMERA-ICE-STARTUP-FORENSIC-V1

Раунд: investigation only. `CLAUDE_CODE_INVOCATIONS=0`, `CODEX_INVOCATIONS=0`, `LIVE_RUNS=0`,
`CAMERA_OPENS=0`, deploy/restart НЕ выполнялись (единственная мутация раунда — git-промоушен
диагностики в main, см. §1).
Доказательная база: bundled native helper + его generated source (sha `4448e836…c0001`),
точный `libnice 0.1.22` (см. §2), live-строки последних двух раундов.

## 1. STEP 0 — PROMOTION диагностической инструментации

- `origin/main`: `229e027f5a16ec0bea846fe8b5b9245ef01dd994` → **`42aa134af752b72bec82074566681011d8b38e42`** (fast-forward).
- Предпроверки: `MAIN_MOVED=false`, `FF_POSSIBLE=true`, diff scope = 6 файлов (`latency_timeline.py`,
  `media_transport.py`, p117-тесты + 3 content-sha pin), `OUTSIDE_ALLOWED=0`,
  `NATIVE_IN_DIFF=0`; native blob at main == candidate (`4ac4ac059dd0…`).
- Validate HACS на exact candidate commit: run `36305681751` = success.
- Сверка production vs merged main по содержанию: tar-stream sha обоих payload'ов совпал
  (`1cfec60ea792d59f3c87d901898c4cb8ab977e41d31c837604305a7f9642f776`), 56 файлов,
  order-independent member digest совпал (`6be6f244…b33bc9`).
  ⇒ **`PRODUCTION_REDEPLOY_REQUIRED=false`** (deploy/restart не выполнялись;
  `DEPLOYED_SHA=42aa134…` уже совпадает с merged main).

## 2. PART A — exact libnice

| поле | значение |
|---|---|
| LIBNICE_VERSION | `0.1.22-r0` (Alpine apk, из `lib/apk/db/installed` build-чрута HAOS) |
| LIBNICE_LIBRARY_SHA256 | `c54caa57a53b876d07b4d7420a7de8d1ebbe5e244f215bbd8f34f3f3e8b6c94c` (296 952 B) |
| LIBNICE_BUILD/ORIGIN | Alpine musl package внутри HAOS rootfs, использованного сборочным чрутом (`alpine-minirootfs-3.24.1-x86_64`); upstream = libnice tag `0.1.22` |
| helper NEEDED | `libnice.so.10`, `libgobject-2.0.so.0`, `libglib-2.0.so.0`, `libc.musl-x86_64.so.1` |
| runtime binding | `media_transport.py:735` → `LD_LIBRARY_PATH=<native/lib>`, т.е. грузится **bundled** `native/lib/libnice.so.10`; его sha256 **идентичен** rootfs-библиотеке выше ⇒ аудируется ровно тот бинарь, что работает |

Upstream-источник (read-only, реф `0.1.22`, sha файлов): `agent.c 691c95bf…`, `conncheck.c ff44f225…`,
`component.c b0830c45…`, `discovery.c 1b1018d0…`, `stunagent.h fb04bb85…`; фиксация в evidence-каталоге раунда.

## 3. PART B — семантика состояний (UPSTREAM_LIBNICE_DOCUMENTED)

- **CONNECTED** — у компонента есть валидная **номинированная** пара; libnice сигналит
  CONNECTED, когда обработал nomination (на controlled-стороне — USE-CANDIDATE от пира) или
  когда успешный check пометил пару nominated (`conncheck.c:2160-2220`, `priv_mark_pair_nominated`).
  Selected pair в этот момент уже существует.
- **READY** — `conn_check_update_check_list_state_for_ready()`: сигналится только если
  `nominated > 0` **И** `priv_prune_pending_checks(...) == 0`, т.е. **все остальные checks
  завершены или отpruned**. Комментарий upstream дословно: «Only go to READY if no checks are left
  in progress. If there are any that are kept, then this function will be called again when the
  conncheck tick timer finishes them all» (`conncheck.c:2203-2218`).
- **PAIR_CAN_CHANGE=true**: пара может измениться и после CONNECTED, и даже после READY —
  найденная/ретраимая пара с более высоким приоритетом переводит компонент из READY назад в
  CONNECTED («requires to pursue the conncheck», `conncheck.c:3180-3207`); разрушение сокета
  выбранной пары даёт READY→FAILED, CONNECTED→CONNECTING (`conncheck.c:4985-5000`).
  У controlling-стороны отдельный stopping-criterion «минимум 2 валидные пары»
  (`conncheck.c:879-888`) — то есть смена номинации архитектурно ожидаема.
- **DATA_ALLOWED_AT_CONNECTED=conditional**: send-путь libnice гейтится наличием
  `component->selected_pair.local` и `selected_pair.remote_consent.have`, **а не состоянием READY**
  (`agent.c:5675+`); `nice_agent_attach_recv()` также не требует READY (`agent.c:6511+`).
  Формального требования «PseudoTCP только после READY» в libnice для нашего режима нет:
  libnice создаёт СВОЙ PseudoTCP лишь в `reliable`-режиме (`agent.c:6600-6617`), мы его не включаем
  и ведём PseudoTCP сами. ⇒ Отсюда: **PROJECT_CODE_ASSUMPTION** — гейт по READY выбран нашим
  кодом, а не навязан библиотекой; но READY — единственная гарантия, что выбор пары финален.

## 4. PART C — наш state callback (generated source, `component_state_changed_cb`)

- печатает `ICE_COMPONENT_STATE=<name>` на каждое изменение;
- **CONNECTED**: только `ice_connected = TRUE` и `printf("ICE_CONNECTED=PASS")`. Больше ничего:
  `report_selected_pair()` здесь **не** вызывается, selected pair не запрашивается,
  PseudoTCP не стартует;
- **READY**: `ice_connected=TRUE; ice_ready=TRUE;` → печатает `ICE_CONNECTED=PASS` и `ICE_READY=PASS`
  → **обязательный** `report_selected_pair()` (иначе `SELECTED_PAIR=FAIL` + quit) → **`start_pseudotcp()`**
  (иначе `PSEUDOTCP_START=FAIL` + quit);
- **FAILED**: `ICE_CONNECTIVITY=FAIL` + quit.

`CURRENT_START_GATE=READY`. В CONNECTED-ветке доступен факт «пара номинирована» (иначе libnice бы
не сигналил CONNECTED), но наш код её ещё не читал и никаких guard'ов не проверял.

## 5. PART D — источник 1989 ms (CONNECTED→READY)

`CONNECTED_TO_READY_DELAY_SOURCE` = **дренаж ICE-checklist'а**: на момент nomination у нас ещё
оставались checks in progress; READY не сигналится, пока `priv_prune_pending_checks() != 0`.
Пары, стоящие в triggered-check queue, при pruning **не удаляются** (`conncheck.c:3043-3120`),
поэтому их STUN-транзакции обязаны доехать по таймеру. Upstream-документация прямо связывает
это с STUN-таймером: «The timeout of each STUN request is doubled for each retransmission, so the
choice of this value has a direct impact on the time needed to move from the CONNECTED state to
the READY state, and on the time needed to complete the GATHERING state»
(`agent.c:830-846`, `Rc` default = 7). Наш helper **не переопределяет** ни `stun-initial-timeout`,
ни `stun-max-retransmissions`, ни `timer-ta` (grep по generated source = 0 совпадений) ⇒ работают
дефолты libnice.

`ARTIFICIAL_LOCAL_WAIT=false`, `NETWORK_CHECKLIST_WAIT=true`.
UNRESOLVED_OFFLINE: точное числовое значение дефолтного RTO (не влияет на вывод; шаг задаётся
связкой RTO×2^n при Rc=7).

## 6. PART E — источник 2092 ms (TRANSPORT_START→ICE_GATHER_DONE)

Последовательность (generated source): spawn helper → `g_main_loop_new` → `nice_agent_new` →
`g_object_set(controlling-mode=FALSE, ice-udp=TRUE, ice-tcp=FALSE, upnp=FALSE,
stun-server="192.248.183.213", stun-server-port=3478)` → `nice_agent_add_stream(1)` →
`gather` → печать `ICE_GATHER_START=PASS` → после `candidate-gathering-done` запись `offer.sdp`
(chmod 0600) и `ICE_GATHER=PASS`.
- host-кандидаты добавляются синхронно; **srflx требует STUN round trip** с тем же RTO/Rc-таймером
  (`discovery.c:269-274`, `1320-1324`); gathering считается завершённым только когда все компоненты
  закончили discovery → `agent_gathering_done` (`discovery.c:1421`);
- TURN локально не используется (комментарий в коде «no local TURN allocation»), UPnP выключен;
- дополнительного обращения к облаку до gathering нет (STUN-сервер — константа), т.е. 2092 ms —
  это boot helper (musl-загрузка glib/gio/gnutls-замыкания) + gathering, а не лишний cloud-call;
- offer пишется **только после** gathering-done (раньше — нельзя: кандидаты должны быть в SDP).

`OFFER_WAIT_FULL_GATHERING=true`, `EARLIER_OFFER_POSSIBLE=true (архитектурно)`,
`COMELIT_TRICKLE_SUPPORT=not_proven`.
Точный вклад boot vs STUN не разделён: кандидатные маркеры helper'а (`LOCAL_CANDIDATES_*`)
в захваченные окна не попали ⇒ это следующий по очереди bounded diagnostic, а не повод менять STUN.

## 7. PART F — можно ли параллелизовать gathering (архитектурно, без реализации)

| вариант | SUPPORTED_BY_LIBNICE | COMELIT_CLOUD_API | RISK |
|---|---|---|---|
| 1. wait full gathering (текущий) | true | proven (работает в production) | low |
| 2. offer на первом usable candidate (host-only offer) | true (можно отдать offer до discovery) | not_proven (нужен ли облаку/панели наш srflx) | medium |
| 3. trickle / add candidates later | true (`nice_agent_add_local_address`/add candidate API) | **not_proven** — инкрементальная передача кандидатов в Comelit cloud не доказана | high (и почти наверняка ломает панель) |
| 4. skip candidate class (не задавать STUN) | true (просто не ставить stun-server) | not_proven; теряется NAT-traversal | high |

Trickle ICE **не предлагается**: контракт облака не доказан.

## 8. PART G — remote.sdp polling

`REMOTE_SDP_POLL_INTERVAL_MS=100`, `STABLE_TICKS=2` ⇒ локальный оверхед 200–300 ms
(generated source `8183-8187`, `7710-7733`).
`REMOTE_SDP_STABILITY_CHECK_NEEDED=false` (PROVEN_STATIC): единственный писатель — Python-родитель,
и он пишет атомарно (`media_transport.py:200-217`: tmp → chmod 0600 → `os.replace`), а helper на
старте делает `unlink(OFFER_FILE); unlink(REMOTE_FILE)` (`8031-8032`) ⇒ прочитать «половину файла»
или stale-файл невозможно. Рекомендация (не выполнялось): заменить poll+2 ticks на **однократное
чтение при появлении файла** (exists && size>0 && успешный read) либо eventfd/inotify.
Это рекомендация, изменения не вносились.

## 9. Решения (decision matrix)

| id | PROVEN_SAFE | EXPECTED_SAVING_MS | COMPLEXITY | PROTOCOL_RISK | NEXT_EVIDENCE_REQUIRED |
|---|---|---|---|---|---|
| **L1** REMOTE_SDP_DETECTION | **true** | 200–300 | low | low | bounded regression: однократное чтение при первом атомарном появлении + (опц.) A/B-замер `REMOTE_SDP_TO_ICE_CONNECTED_MS` |
| **L2** START_PSEUDOTCP_BEFORE_READY | **false** | до ~1989 | medium | **high** | (a) доказать, что selected pair на controlled-стороне финальна уже в CONNECTED; (b) доказать, что peer принимает SYN до нашего READY; (c) определить обработку смены пары для нашего PseudoTCP. Всё требует live — сейчас запрещено |
| **L3** ICE_GATHERING_REDUCTION | **false** | 200…2092 (доля неизвестна) | medium | **high** | измерить обязательную часть: кандидатные маркеры helper'а + проверка cloud-контракта для host-only offer. STUN/TURN/кандидатов не менять |

**PRIORITY**: L2 безопасность не доказана → live-кандидат на ранний PseudoTCP **не делать**.
`NEXT_OPTIMIZATION=L1_REMOTE_SDP_DETECTION` (малый, но полностью доказанный low-risk win;
native-правка ⇒ требует отдельной авторизации + rebuild/re-pin, если пойдём в кандидаты).
L3 — только после измерения обязательной части gathering.

## 10. HLS classification

`DECODABLE_FRAME_TO_HLS_FIRST_PART_MS=73370` ⇒ **`HLS_73370_CLASSIFICATION=OBSERVATION_ARTIFACT`**
(PROVEN_STATIC): T20 штампуется в `camera.py:585-594` из **снимка diagnostics**
(`hls_first_part_bytes is not None`), т.е. это момент, когда разреженный HLS-probe *увидел* уже
существующий part, а не время его создания. Исторический baseline видел первый usable part
примерно `T16+1..2 s` через независимый 1 Hz-канал ⇒ 73 s — артефакт каденса наблюдения.
Отдельная HLS-задача в этом раунде не открывается.

## 11. Что не делалось

Никаких protocol/runtime изменений, deploy, restart, live-прогонов, открытий камеры, правок
STUN/TURN/кандидатов, PseudoTCP, settle, polling. Production не мутировался
(`DEPLOYED_SHA=42aa134…` = merged main).
