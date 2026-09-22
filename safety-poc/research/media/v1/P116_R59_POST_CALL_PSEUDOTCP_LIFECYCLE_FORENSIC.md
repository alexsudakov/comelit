# P116 R59 post-call PseudoTCP lifecycle forensic

Дата: 2026-09-22. Анализ только offline/static по уже сохраненным артефактам. Native C, `native/comelit-v4`, R58 stop/cleanup contract, R56 local-trio scheduling, call adoption, peer-capability predicate, media OPEN, Door/Gate не менялись.

## 1. PSEUDOTCP_NOTIFY_PACKET path

`PROVEN_OFFLINE` `PSEUDOTCP_NOTIFY_PACKET_EXACT_CONDITION=NOTIFY_PACKET_RETURNED_FALSE_ON_INBOUND_UDP_PACKET`.

Точный внешний путь задан собранной live-форензикой: generated source `pseudotcp_recv_cb` принимает UDP packet и вызывает `pseudo_tcp_socket_notify_packet(pseudo_tcp, buf, len)`. Если вызов вернул `FALSE`, кандидат ставит `P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET`, `failed = TRUE` и делает `g_main_loop_quit`. Это inbound UDP receive path, а не HA stop path.

`UNRESOLVED` Внутреннюю ветку libnice 0.1.22 в `pseudotcp.c` offline прочитать не удалось: локальный поиск по `/root/comelit-p80-haos-build-*/rootfs`, apk cache и локальным копиям source не дал readable `pseudotcp.c`. Поэтому запрещено уточнять libnice-internal reject branch догадкой.

`MISSING_REQUIRED_EVIDENCE`: readable libnice 0.1.22 `pseudotcp.c` с конкретной веткой, где `pseudo_tcp_socket_notify_packet()` возвращает `FALSE`.

## 2. Second-cycle STARTUP close

`OBSERVED` Второй цикл завершился `P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED`, `P116_NATIVE_FAILURE_PHASE=STARTUP`, `P116_NATIVE_FAILURE_COUNT=2` в 21:27:35.418. В сохраненном HA tail нет call/media markers для этого свежего процесса.

`UNRESOLVED` Был ли PseudoTCP уже `OPEN`, из safe markers не доказано. Native печатает `PSEUDOTCP_CLOSED_BEFORE_OPEN` / `PSEUDOTCP_CLOSED_AFTER_OPEN`, но они сегодня на stderr и не попадают в `safe_native_markers`.

`OBSERVED` Registration completeness для второго процесса не доказана: следующий fresh READY появился только в 21:27:46.128, уже после еще одного reconnect. Timing budget по сохраненному tail: 21:26:55.543 reconnect attempt #1, 21:27:35.418 second-cycle native failure, 21:27:35.573 reconnect attempt #2, 21:27:46.128 READY.

## 3. 5-second backoff

`OBSERVED` Измеренная цепочка: 21:26:54.925 first failure, 21:26:55.543 supervisor reconnect log count=1, 21:27:35.418 second failure, 21:27:35.573 reconnect log count=2, 21:27:46.128 fresh READY.

`UNRESOLVED` `RECONNECT_TOO_EARLY_HYPOTHESIS=UNKNOWN`. Корреляция не является причинностью: сохраненный tail показывает 5-second policy и последующий STARTUP close, но не доказывает, что именно ранний reconnect вызвал close.

## 4. Call termination semantics

`PROVEN_STATIC` `media CLOSED != call CLOSED`. R58 доказал media close/cleanup, но call transaction terminality в этой модели означает inbound RELEASE path.

`PROVEN_STATIC` По заданному факту orchestrator: `r35_teardown_call()` имеет один call site в generated candidate, внутри `r37_handle_remote_release()` для inbound RELEASE opcode `0x000E`. Значит call transaction teardown выполняется только после inbound RELEASE.

`UNRESOLVED` `CALL_TRANSACTION_TERMINAL_BEFORE_PSEUDOTCP_EXIT=UNKNOWN`. Решающий marker: `R37_REMOTE_RELEASE_OBSERVED=true` до `P116_NATIVE_FAILURE_*`.

`UNRESOLVED` `REMOTE_RELEASE_OBSERVED=UNKNOWN` в сохраненном R58 evidence, потому что HA до R59 отбрасывал `R37_` prefix.

`UNRESOLVED` `LOCAL_CALL_TEARDOWN_COMPLETE=UNKNOWN`. Решающий marker: `R37_REMOTE_RELEASE_OBSERVED=true` после возврата `r37_handle_remote_release()`; статически этот handler содержит единственный `r35_teardown_call()` path, но live marker был скрыт HA-side prefix gap.

## 5. Why masking is forbidden

`OBSERVED` Условие 1, media CLOSED: true. Markers: `R58_STOP_CLOSED=true`, `R42_MEDIA_CHANNEL_CLOSED=true`, HA log `Comelit attached inbound media CLOSED`.

`UNRESOLVED` Условие 2, call terminal: unknown. Нужен `R37_REMOTE_RELEASE_OBSERVED=true`.

`UNRESOLVED` Условие 3, no pending protocol TX: unknown в R58 saved tail, потому что `R54_TX_STATE` и `R54_TX_SUBJECT` были `<redacted>`.

`UNRESOLVED` Условие 4, remote transport close: unknown for first failure. `PSEUDOTCP_NOTIFY_PACKET` доказывает notify-packet reject, не normal remote close. `PSEUDOTCP_CLOSED` появился только во втором fresh process.

`PROVEN_OFFLINE` Маскировать exit 6 как graceful recycle запрещено, пока все четыре условия не доказаны одновременно: media CLOSED AND call terminal AND no pending protocol TX AND remote transport close.

## 6. Official-app post-call transport behaviour

`UNRESOLVED` `OFFICIAL_POST_CALL_TRANSPORT_BEHAVIOR=UNKNOWN`. В этой R59 задаче нет staged static evidence, доказывающего official-app post-call transport lifecycle. Поведение не реконструируется догадкой.

## 7. Expected process outcome

`UNRESOLVED` `EXPECTED_POST_CALL_PROCESS_OUTCOME=UNKNOWN`. Saved evidence доказывает фактический `FAILURE_EXIT_6`, но не доказывает желаемую семантику post-call lifecycle. `CONTINUE` vs `GRACEFUL_EXIT_0` vs `FAILURE_EXIT_6` требует call terminality, pending TX и remote transport close evidence.

## 8. Recovery semantics

`OBSERVED` `POST_CALL_UNAVAILABLE_MS=51209`.

Формула (граница окна — от завершения media cleanup, а не от аварии): `fresh_READY(21:27:46.128) - attached_media_CLOSED(21:26:54.919) = 51.209s = 51209ms`.
Для справки, вторая граница: `fresh_READY(21:27:46.128) - first_native_failure_summary(21:26:54.925) = 51.203s = 51203ms`.
Декомпозиция измеренного окна: `exit#1 -> reconnect#1` 0.617s, `reconnect#1 log -> STARTUP close (exit#2)` 34.9s (процесс попытки #1 жил ~34.9s, READY за это время не печатался — значит регистрация не завершилась), `reconnect#2 log -> READY` 10.55s (из них 5s backoff + ~5.5s bootstrap до READY).

`OBSERVED` `RING_AVAILABILITY_GAP_EXISTS=true`: persistent listener was unavailable between first native failure and next READY.

`PROVEN_OFFLINE` `POTENTIAL_MISSED_RING_DURING_GAP=true` as a state model only: if the persistent listener is not READY, an inbound ring during that interval can be missed by this HA listener. No live missed ring is claimed.

## 9. Door impact

`PROVEN_STATIC` `DOOR_UNAVAILABLE_DURING_RECONNECT=true` in lifecycle terms. Door action depends on a READY persistent listener; `async_open_door` sends `SIGUSR1` to the persistent listener PID. During process exit/reconnect there is no READY listener PID to signal.

`OBSERVED` No Door/Gate action is claimed or tested in R59.

## 10. Root cause class

`UNRESOLVED` Root cause class verdict: `UNKNOWN`.

`TRANSPORT_FAILURE` is compatible with `PSEUDOTCP_NOTIFY_PACKET`/`PSEUDOTCP_CLOSED`, `RECONNECT_TOO_EARLY` is compatible with timing, and `NORMAL_REMOTE_CLOSE_MISCLASSIFIED` is possible only if the missing call-terminal and remote-close evidence appears. Current evidence is insufficient, so the corrective route is observability, not masking.

## 11. Observability corrective implemented

`PROVEN_OFFLINE` `custom_components/comelit/runtime.py` now accepts `R37_` native markers and bounded vocabularies for `R37_PROTOCOL_STOP_RESULT`, `R37_BOUNDED_STOP_RESULT`, `R54_TX_STATE`, and `R54_TX_SUBJECT`.

`PROVEN_OFFLINE` New canary criteria:

- `R37_REMOTE_RELEASE_OBSERVED=true` -> `REMOTE_RELEASE_OBSERVED`
- `R37_CAPABILITY_CLEARED_OBSERVED=true` -> `CAPABILITY_CLEARED_OBSERVED`
- `R54_TX_STATE=<bounded>` -> `TX_STATE_AT_EXIT`
- `R54_TX_SUBJECT=<bounded>` -> `TX_SUBJECT_AT_EXIT`

`PROVEN_OFFLINE` HA-derived `POST_CALL_TRANSPORT_STATE=<enum>` is emitted once per generation at native failure summary. Derivation rule:

- no observed `R42_MEDIA_CHANNEL_CLOSED=true` -> `NONE`
- media closed + `R37_CAPABILITY_CLEARED_OBSERVED=true` without remote release -> `UNKNOWN`
- media closed + `P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED` -> `TRANSPORT_CLOSED`
- media closed + `R37_REMOTE_RELEASE_OBSERVED=true` + `R58_STOP_CLOSED=true` -> `MEDIA_CLOSED_TEARDOWN_COMPLETE`
- media closed + `R37_REMOTE_RELEASE_OBSERVED=true` -> `MEDIA_CLOSED_REMOTE_RELEASE`
- media closed without the above -> `MEDIA_CLOSED_CALL_OPEN`

`PROVEN_OFFLINE` `custom_components/comelit/supervisor.py` now logs bounded reconnect markers `RECONNECT_ATTEMPT=<n>` and `RECONNECT_REASON=<LISTENER_CYCLE_ENDED|NATIVE_FAILURE_EXIT|UNKNOWN>` without changing `RECONNECT_DELAY_SECONDS=5` or restart policy.

Next live window decision markers: `R37_REMOTE_RELEASE_OBSERVED`, `R37_CAPABILITY_CLEARED_OBSERVED`, `R54_TX_STATE`, `R54_TX_SUBJECT`, `POST_CALL_TRANSPORT_STATE`, `PSEUDOTCP_CLOSED_BEFORE_OPEN`/`AFTER_OPEN` if later moved into safe stdout.

## 12. Regression and sanitisation

`PROVEN_OFFLINE` R58 stop/cleanup criteria remain: `R58_STOP_PHASE`, `R58_STOP_CLOSED`, `R58_STOP_FAILED`, `R42_MEDIA_CHANNEL_CLOSED`; value-keyed dedup remains only for `R58_STOP_PHASE`.

`safety-poc/research/media/v1/P116_R59_R58_CANARY_TIMELINE_EVIDENCE.txt` — санитизированная bounded-выжимка
таймлайна канарейки R58 (только таймстемпы и имена маркеров/событий; без payload, адресов, CTP/connection id,
токенов и сырых кадров лога). Она закоммичена как единственный источник истины для assertions раунда:
исходный каталог живых окон (`/home/hermes/r58-live`) существует только на хосте оркестратора, и привязка
теста к нему давала зелёный локальный прогон при красном CI — этот дефект был пойман и исправлен в том же
раунде (первый push: `offline-safety=failure`, `AssertionError: missing marker timestamp: Comelit attached
inbound media CLOSED`), проверка повторена симуляцией CI с недоступным каталогом живых окон.

`PROVEN_OFFLINE` Sanitisation remains bounded. The generic safe-value regex was not widened. New enum values are per-key vocabularies only; out-of-vocabulary values stay `<redacted>`. No raw ids, payloads, addresses, Door/Gate action, live TX, rebuild, deploy, HA restart, physical ring, self-activation, or new capture was performed.
