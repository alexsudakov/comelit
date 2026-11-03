# Issue #319 — архивная реконструкция до нового захвата официального приложения

> Дата: 2026-11-03. Статус: `PRE_CAPTURE_REVIEW_COMPLETE / P0_A_NOT_FIXED / P0_B_NOT_FIXED`. Только исследование. Ни Comelit runtime, ни Home Assistant, ни APK/PCAP не изменялись.
> Авторский режим: самостоятельный read-only анализ GitHub и ранее опубликованных результатов, **без Hermes/Codex, live-консоли и новых физических действий**.
> Source baseline: `alexsudakov/comelit` `321e9083d275e67c51bdc39f34cb814e42c59dad`, релиз `1.7.32b25`. Отдельный SHA установленной интеграции: владелец сообщил 1.7.32b25; точный установленный Git tree из HA не считывался.

## 1. Цель и границы достоверности

Цель: подготовить сравнение трёх **различных** сценариев: (A) официальный/эквивалентный самостоятельный просмотр без Ring, (B) обычный входящий Ring, (C) **официальное Android-приложение: видео уже открыто, затем физический Ring**, который владелец запишет отдельно.

Это обзор **ранее сохранённых отчётов, исходников, фикстур, issue-комментариев и APK static-analysis findings**, а не повторная проверка сырых PCAP/APK/DEX и не выполнение Hermes. Сырые R42 PCAP и прежние закрытые CT120/CT122 archives не были доступны напрямую через GitHub; существующие SHA256 взяты из архивных отчётов, а не вычислены повторно здесь. Нельзя писать `RAW_PCAP_REANALYZED=true` или `APK_REVERSED_NOW=true`.

Issue: [#319](https://github.com/alexsudakov/comelit/issues/319). История решения и архива: [комментарий с TEST B/C/D и OBS-LIVE](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6351508533), [физический P0RING 24.10](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6383090690), [R11 и R12 gate](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6386744711).

## 2. Инвентаризация существующих трасс и первичных по происхождению данных

| Артефакт | Исходный сценарий | Зафиксировано в репозитории | Ограничение для #319 |
| --- | --- | --- | --- |
| `self_activation.pcap`, SHA256 `f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a` | Самостоятельная активация/видео | [R52](../../safety-poc/research/media/v1/P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md): 3546 packets; client local CAPABILITIES `0x27`, peer `0x1b` | Это **не** video→Ring; прежние scalar/PCAP-анализы, raw здесь не перечитан |
| `pcapdroid-r14-official-app-trace.pcap`, SHA256 `3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f` | Официальное приложение, client-initiated/outgoing transaction | [R52](../../safety-poc/research/media/v1/P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md): 6296 packets; local `0x27`, peer `0x1b` | Не доказывает Call FSM при уже активном предпросмотре |
| `r39-phone-capture.pcap`, SHA256 `5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9` | Официальное приложение, PCAPdroid | [R39](../../safety-poc/research/media/v1/P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md): 901 packets, 13:56:47–14:01:05Z | **Физический Ring в 14:02:02Z был после конца записи**; приложение не READY, непригоден для нужного перехода |
| Официальный физический входящий Ring, R42 (raw PCAP не находится в GitHub) | Входящий вызов без уже открытого просмотра | [R42](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md): INVITE, MEDIAREQ26 OPEN/STOP, H.264 PT99, ~51.7 с видео | Нет сырого PCAP для независимого повторного парсинга, не сравнивает C |
| R57 physical canary / saved HA markers | Listener-owned входящий Ring в нашем helper | [R57](../../safety-poc/research/media/v1/P116_R57_CANARY2_LIVE_RESULT.md): call adoption → peer CAPABILITIES → MEDIAREQ26 → H.264/RTP/снимки | Начальное состояние — listener, а не active P78/P80 preview; R57 stop confirmation был неполным |
| TEST B/C/D, OBS-LIVE, P0RING | Наш media-owner: активное видео → физический Ring | [Issue #319 archive](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6351508533), [P0RING](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6383090690) | Это трасса **нашего helper**, не оригинального приложения; часть raw только на CT122 |
| `p2p_rtsp.pcap`, P78 helper `p78-media.pcap`, R38 preflight | Дополнительные контрольные и helper-трассы | [R52 inventory](../../safety-poc/research/media/v1/P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md) | Не содержат доказанного video→Ring официального приложения |

Важно: R52 честно фиксирует `PHYSICAL_CALL_RAW_CAPTURE_FOUND=false` для R42 и `PHYSICAL_INBOUND_LOCAL_CAPABILITY_WORD=UNKNOWN`. Нельзя подставлять `0x27` из client-initiated sessions как **доказанный** CAPABILITIES word для inbound Ring.

## 3. Анализ APK/DEX/native статических выводов (не новый реверс)

[R28](../../safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md) содержит уже выполненный анализ официального Android SDK, DEX и native `libvipcomelit.so`:

- `CallFsm::go_in_alerting → start_videorx → RtpDispatcher::startVideoRX` может запускать входящий video RX **до** явного пользовательского answer; `PREVIEW_ANSWERS_CALL=false`.
- Данный call-scoped media RX путь проходит `ViperTunnel::openMediaRXChannel → openChannel` в существующем туннеле; сам по себе старт RX не доказывает необходимость нового cloud/ICE/PseudoTCP.
- MEDIAREQ26 OPEN использует фактически выделенный RTPC/media RX channel id; stop закрывает этот media channel, а не автоматически весь tunnel.
- **Не доказано по R28:** каким образом уже активная self-activation preview переводится в Ring и сохраняется ли тот же RTP/RTPC channel. User-visible continuous video не равно same-channel identity.

[R43](../../safety-poc/research/media/v1/P116_R43_CALL_ADOPTION_SIGNALING_FORENSIC.md) и [R42](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md) описывают normal incoming call: INVITE ACK → local CAPABILITIES → ALERTING → peer CAPABILITIES → DATA ACK → call-bound MEDIAREQ26 OPEN; отдельное принятие звонка не обязательно для initial video RX. Это **inbound listener state**, не поведение A→Ring.

## 4. Что реально делает наш код 1.7.32b25

| Контур | Исходное состояние и действия | Ring при active media |
| --- | --- | --- |
| Listener-owned | [`runtime.py`](../../custom_components/comelit/runtime.py), [`supervisor.py`](../../custom_components/comelit/supervisor.py): persistent P2P/CTPP listener | production Ring event, call state, attached media; R54/R57 call adoption |
| On-demand media-owner | [`media_session.py`](../../custom_components/comelit/media_session.py): пауза listener перед отдельным media; [`media_transport.py`](../../custom_components/comelit/media_transport.py): P78/P80 native process, wrapped RTP PT99/PT8, локальная выдача для Mini App/HA | Native ring markers поступают в [`RingShadowHook`](../../custom_components/comelit/ring_shadow.py), `production_emit_allowed=false`; **нет** production Ring emit/call adoption в уже открытом P78 состоянии |
| UI Telegram Mini App | [WebCodecs primary](../releases/1.7.27-webcodecs-primary.md), WSS/PyAV local RTP; HLS fallback | UI/lease cleanup не заменяет backend-native call FSM; нельзя автоматически открыть второй upstream |

Проверены в текущем source: `RingShadowController.observe_native_line(... production_emit_allowed=False)`; `ComelitEntranceMediaTransport._async_read_output()` переводит native marker в observability; `ComelitMediaSessionManager.async_acquire()` паузит listener; `_async_stop_locked()` восстанавливает listener после confirmed teardown. [`docs/r61-observability-contract-corrective.md`](../r61-observability-contract-corrective.md) сохраняет `HIGH_A2=OPEN` и `HIGH_3=REFRAMED`.

### Результат физического HA-теста 03.11 (передано владельцем; не Telegram Mini App)

- 17:58:01 — listener `ready`, `reconnect_count=13`, media `inactive`.
- 17:59:30 — видео реально отображалось; listener `paused_media`, media `active`, `camera_view_owner=on_demand`.
- 18:00:18 — media `inactive`, `last_stream_provider_removed` at 18:00:09 local, listener снова `ready`; `reconnect_count=13`.
- Это подтверждает нормальный **просмотр→release→listener READY**. Оно **не** подтверждает Ring внутри media и не является проверкой Telegram WebCodecs.

## 5. P0-A и P0-B — не смешивать

**P0-A (доставка нового Ring в Telegram):** в P0RING был один native INITIAL и четыре retransmit, Ring не был эмитирован в производственный HA event path. Source-level gap подтверждён. `frame_sha`, `body[32:36]`, `episode_id`, `source+door`, `peer_connection` или время **не доказаны** как уникальная идентичность физического вызова. В одной media-generation возможны два разных calls; `max one event per media session` — ошибка. Без доказанной идентичности/безопасного bounded dedup нельзя просто вызвать listener `_async_emit_ring_event()` из media-owner: эта функция меняет call state и запускает attached media, что создаёт конфликт upstream owner.

**P0-B (непрерывность видео):** P0RING observed last RTP ~10:20:00.340Z, initial Ring marker ~10:20:00.730Z, затем RTP не продолжился; refresh/structural ACK сохранялись до ~10:20:03.5Z, Mini App PyAV error 10:20:10.369Z, release 10:20:10.376Z, native close 10:20:10.500Z, listener READY ~10:20:15.818Z. Это **не** доказывает, что панель намеренно прекратила RTP или что call adoption гарантированно исправит проблему. Межсистемная точность времени INITIAL marker ограничена.

Другие старые наблюдения: TEST B `REFRESH_FAIL_CLOSED=true` при неполном Ring evidence, TEST C/D и OBS-LIVE — Ring виден, но с `REFRESH_FAIL_CLOSED=false`. Следовательно, **нельзя** сводить все исходы к одному fail-closed refresh root cause. В ноябрьском незавершённом Hermes workflow сообщалось об offline-находке возможной гонки CALL_INIT и outstanding `0x001A`; это **исторический отчёт без независимой проверки текущего native source и без опубликованного accepted fix**. Подтверждённой production-коррекции нет.

## 6. Результаты R10–R12, почему не переносим кандидата

- **R10:** [PoC](../../safety-poc/research/media/v1/ISSUE_319_R10_MEDIA_OWNER_CALL_ADAPTER_RESULT.md), PR #326 merged: Python/fake-writer моделирует ACK/CAPABILITIES/ALERTING, single P12 slot, retransmits и fail-closed. Trusted `CallIdentity` подаётся извне; это не production C, не реальный call identity и не live acceptance.
- **R11:** [Issue commentary](https://github.com/alexsudakov/comelit/issues/319#issuecomment-6386744711) — CTP connection direction mapping `peer ^ 0x8000` capture-supported, но connection ID **не равен** независимому уникальному call ID. P78 self-activation **уже использует RTPC**; новый call-bound media RX канал в R42 имеет другой жизненный цикл. Возможность same-channel resume остаётся UNPROVEN.
- **R12/R12B:** отдельные offline native candidate/worktree, **не попавшие в main**. Historical full VERIFY PASS нельзя интерпретировать как Critic PASS. Сохранились Critical/Major findings F1–F8, в R12B CR1-F1 (Phase 2 / MEDIAREQ26 OPEN reachable без подтверждённого gate) и CR1-F2 (early peer CAPABILITIES/ACK ordering). Старые freezed/HOLD результаты не переиспользовать как готовый fix.
- **Состояние 03.11:** GitHub main `321e9083…` содержит текущий безопасный shadow-only route; #319 OPEN. Для исследования здесь НЕ применялись Hermes, старые candidate patches и физические действия.

## 7. Матрица для следующего PCAP — три сценария

| Контрольная точка | A: self-activation / official client-initiated | B: original normal inbound Ring | C: original active video → Ring |
| --- | --- | --- | --- |
| До Ring | captured P2P/CTPP + RTPC, client capabilities `0x27` в старых client-initiated traces | persistent registered call receiver | **ожидается новый PCAP**, зафиксировать уже активный RTP |
| CTP INVITE / CALL_INIT | отсутствует доказанный Ring-in-video | R42 observed inbound INVITE / call-scoped CTP | **NOT_CAPTURED** |
| ACK / CAPABILITIES / ALERTING | P78 self activation имеет иной control FSM | R43/R54 listener-owned adoption | **NOT_CAPTURED:** требуется проверить порядок/базу подключения |
| `0x001A` refresh | отдельный R27 self-activation control | иной контекст; нельзя считать ACK доказательством adopted call | **NOT_CAPTURED:** искать конкуренцию с CALL_INIT |
| RTPC/media identity | P78 OPEN1/OPEN2, wrapped RTP | R42 новый RX Viper channel + MEDIAREQ26 OPEN/STOP | **NOT_CAPTURED:** сохраняется ли old RTP; новый media RX channel? |
| ICE/PseudoTCP/CTPP | один self-activation owner в нашей модели | listener registered owner | **NOT_CAPTURED:** net connection identity/reconnect по timestamps/5-tuple, не по UI |
| Видео для пользователя | preview frames observed in prior self-activation | official inbound R42 ~51.7 s / listener R57 H264 | владелец ранее сообщил continuity; **wire mechanics NOT_CAPTURED** |
| Stop/release | нормальный release и READY на HA 1.7.32b25 подтверждены | R42 MEDIAREQ26 STOP captured | **NOT_CAPTURED:** проверить end state / restore after call |

Сценарии A/B исторически собраны **на разных датах/приложениях/версиях**. Сравнение следует строить по последовательности протокольных состояний и relative timing, а не по literal connection IDs и абсолютным адресам.

## 8. Что именно требуется от нового capture C

1. Запустить PCAPdroid **до** открытия видео в официальном Android приложении, убедившись в готовности приложения и отсутствии конкурирующего HA listener/другого upstream owner. Не считать уведомление background service признаком успешного P2P READY.
2. Зафиксировать 15–20 с действительно отображаемого video, затем **один** физический вызов при незакрытом просмотре, отмеченное приблизительное время, реакцию UI без автоматических действий. По возможности запись экрана/временная шкала.
3. Записывать до завершения входящего звонка и ещё 20–30 с после. Дверь/калитку не открывать; TLS MITM/инъекции и повторные протокольные TX не нужны.
4. На анализ: original `.pcap`/`.pcapng`, checksum SHA256, часовой пояс/время открытия видео и звонка, короткое описание UI; если есть, синхронная screen recording. Проверить наличие полного звонка **внутри** capture window; иначе пометить `CAPTURE_INCOMPLETE`.
5. Установить: один или несколько cloud/P2P/bootstrap, old/new ICE/PseudoTCP/CTPP flow, decoded CALL_INIT/ACK/CAPABILITIES/ALERTING, old/new RTPC media channel, MEDIAREQ26 OPEN/STOP, RTP before/after Ring, stop/release. Если payload encrypted и недоступен для decode — поставить `NOT_OBSERVABLE`, а не делать вывод по packet size.
6. После пассивного сравнения A/B/C оформить diff FSM с точной таблицей PROVEN/INFERRED/UNKNOWN и только **затем** решить, нужен ли Hermes read-only доступ к работающему HA/native logs. До этого изменения кода не планируются.

### Хранение сырого захвата

Владелец запросил размещение будущего raw PCAP и результатов в GitHub. При этом `alexsudakov/comelit` публичен, а raw captures способны раскрывать IP/URL, идентификаторы, токены, SDP и внутреннюю сеть; проектные прежние правила запрещали помещать proprietary raw в public Git. **Этот отчёт не публикует raw**. Для будущей загрузки следует выбрать **приватное GitHub-хранилище с ограниченным доступом для сырых данных** (при необходимости Git LFS и проверка лимита размера); в публичном `comelit` оставить SHA256/provenance и обезличенные выводы. Новое решение о точном destination/raw exposure принять при получении файла; необратимо раскрывать его в public commits не требуется для исследования.

## 9. Критерии следующей исследовательской итерации

- `CAPTURE_C_HAS_VIDEO_BEFORE_RING` и `CAPTURE_C_HAS_RING_WITHIN_WINDOW` доказаны временем и packet/source evidence.
- `CAPTURE_C_CALL_IDENTITY`: строго PROVEN/NOT_PROVEN с обоснованием; не заменять frame SHA, CTP connection или media generation уникальным call ID.
- `CAPTURE_C_MEDIA_TRANSITION`: explicitly SAME_CHANNEL / CHANNEL_SWITCH / NEW_UPSTREAM / UNKNOWN, отдельно UI continuity и RTP continuity.
- `REFRESH_INTERLEAVING`: есть ли outstanding `0x001A` и как CALL_INIT сериализуется относительно него.
- `NO_SECOND_UPSTREAM`: по протокольному потоку, если исходные данные позволяют; отсутствие записи не считать доказательством.
- `P0_A` и `P0_B`: сохранять OPEN до независимой квалификации и физического приёмочного теста целевого Telegram Mini App.
- Сравнительный отчёт размещается в GitHub, без Hermes; после него отдельная задача Hermes ANALYSIS/read-only по живому серверу создаётся **только если** останется конкретный непроверяемый факт.

## 10. Итог

**PROVEN по архивам/source:** наш on-demand helper может получить CALL_INIT, но пока не маршрутизирует его в production Ring; в реальных испытаниях video RTP прекращался при продолжающемся control flow; official app static supports pre-answer preview, R54/R57 доказывает call-adoption только из listener state; обычная HA media-session в 1.7.32b25 освобождается и listener возвращается READY.

**NOT PROVEN:** точный штатный video→Ring protocol переход; неизменность upstream/media channel; корректная независимая per-call identity; причина остановки RTP в нашей implementation; разрешённый in-place reuse/способ безопасного channel switch. Новый capture C — минимальный следующий шаг. Никакие кодовые изменения и запуск Hermes в этой стадии не оправданы.
