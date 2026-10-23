# Issue #319 ROUND 2 — граница безопасной непрерывности Ring/video

Статус: `P0-A=NOT_FIXED/NOT_PROVEN`, `P0-B=NOT_FIXED/NOT_PROVEN`.

Режим этого анализа — только offline. Не выполнялись deploy, restart/reload,
управление listener или official app, открытие камеры, физический Ring,
Door/Gate, protocol write либо production emit.

## Вывод

Безопасной offline-коррекции, которая одновременно сохраняет видео, принимает
Ring ровно один раз и не использует второй upstream или новые protocol writes,
в доступных доказательствах нет.

Проблема состоит из двух независимых условий:

* `P0-A` — физический Ring во время уже активного on-demand видео должен стать
  ровно одним логическим Ring после retransmit и смены владельца;
* `P0-B` — существующий RTP должен продолжиться после `CALL_INIT` в том же
  ICE/PseudoTCP/CTPP/RTPC контексте без call-adoption TX.

Текущая реализация не доказывает ни одно условие и поэтому не включает
media-owner production emit. Добавлена только bounded корреляция уже имеющихся
безопасных scalar-маркеров вокруг media-owner `CALL_INIT`.

## Сравнение трех путей

| Путь | Владелец upstream | Что происходит при Ring | Непрерывность видео | Цена безопасности |
|---|---|---|---|---|
| Official app live-video + Ring | Один native VIP session; call и media — scoped channels внутри него | Native call FSM принимает входящую call transaction и выполняет adoption/signaling | Статически поддерживается моделью call-scoped RTPC/Connexus; raw capture именно перехода «уже открытое self-activation video → Ring» в workspace отсутствует | Нет второго upstream, но есть native call-adoption writes; это не доказательство, что их можно не делать |
| HA on-demand media-owner + Ring | Один отдельно bootstrapped self-activation helper; listener намеренно остановлен | `CALL_INIT` видит media helper, но только shadow/probe; production emit отсутствует | До Ring RTP наблюдаем, поведение после Ring без adoption TX не доказано | Второй upstream запрещен архитектурой; добавлять adoption TX нельзя без wire-proof |
| HA listener-attached adopted Ring | Persistent listener принимает `CALL_INIT`, затем call-scoped adoption открывает attached media | Ring принадлежит listener и имеет один текущий production emit route | Один upstream сохраняется; attached media открывается в принятой call transaction | Требуются доказанные INVITE ACK/CAPABILITIES/ALERTING/peer DATA ACK writes; этот путь нельзя переносить на уже активную self-activation transaction по аналогии |

Official path и listener-attached path показывают возможность одного upstream,
но оба используют принятую call transaction. HA on-demand path уже занят другой
self-activation transaction. Реплей существующей adoption-последовательности в
этом состоянии был бы новым, не доказанным протокольным поведением; запуск
listener параллельно создал бы второй upstream; простой emit по `CALL_INIT`
оставил бы открытыми и continuity, и duplicate Ring.

## Точный недостающий invariant

Машинный маркер:

```text
ACTIVE_SELF_ACTIVATION_CALL_INIT_PRESERVES_RTP_WITHOUT_ADOPTION_TX_AND_HAS_STABLE_CROSS_OWNER_CALL_IDENTITY
```

Invariant истинен только если одновременно доказано следующее:

1. `DEVICE_TO_CLIENT CALL_INIT`, полученный при активном self-activation video,
   не требует INVITE ACK, local CAPABILITIES, local ALERTING, peer DATA ACK или
   иного нового TX для продолжения уже открытого RTP;
2. после `CALL_INIT` счетчик video RTP строго растет в том же helper process и
   при неизменных ICE=1, PseudoTCP=1, CTPP=1, RTPC open set и self-activation=1;
3. один immutable native call identity одинаков у initial/retransmit и при
   listener↔media handoff, но различается у двух последовательных физических
   calls; process generation, handoff epoch и full-frame SHA такими identity не
   считаются;
4. remote release однозначно завершает ровно эту identity, не закрывая другую
   transaction и не создавая synthetic timeout Ring.

Пока любой пункт неизвестен, `P0-A` и `P0-B` остаются `NOT_PROVEN`, а безопасная
политика — `production_effect=false`.

## Минимальная решающая будущая проверка

Нужна отдельно авторизованная bounded кампания из **двух** физических Ring во
время двух on-demand video окон. Один Ring достаточен для continuity, но
математически не может доказать различимость identity между calls.

Для каждого окна до Ring фиксируются helper/process identity, ICE/PseudoTCP/
CTPP/RTPC/self-activation counts и `P80_VIDEO_RTP_PACKETS`. После Ring, без
protocol write и без listener start, требуются:

```text
media_active_call_init_count += 1
video_progress_after_last_media_call_init=true
SECOND_MEDIA_SESSION=false
ICE_NEGOTIATION_COUNT=1
PSEUDOTCP_OPEN_COUNT=1
CTPP_REGISTRATION_COUNT=1
SELF_ACTIVATION_COUNT=1
CALL_ADOPTION_TX_COUNT=0
```

Дополнительно initial и retransmit одного call должны иметь одинаковый
кандидат identity, а второй физический call — другой. Любой native exit, новый
RTPC open, переставший расти RTP, отсутствие identity-различимости или TX
делает результат `NO_GO`; автоматический retry запрещен. Проверка квалифицирует
последующую offline-реализацию, но сама не разрешает production emit, deploy,
restart или изменение identity policy.

## Реализованная production-inert диагностика

`RingShadowController.snapshot_view().continuity_probe` теперь bounded хранит
только scalar-состояние: media active, последний video packet count, число
media-owner `CALL_INIT`, baseline пакетов у последнего активного `CALL_INIT` и
факт последующего роста. Поля `probe_protocol_write_performed=false` и
`production_effect=false` являются статическими safety facts. Диагностика не
сохраняет payload, не пишет в сеть, не вызывает Ring emit и сбрасывается при
новой media generation/unload.
