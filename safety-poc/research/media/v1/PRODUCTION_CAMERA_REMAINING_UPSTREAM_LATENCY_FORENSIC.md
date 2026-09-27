# COMELIT-PRODUCTION-CAMERA-REMAINING-UPSTREAM-LATENCY-V1 — forensic investigation

Дата: 2026-09-27. Статус раунда: **investigation only**, protocol/code changes НЕ выполнялись.
База: `origin/main` = `229e027f5a16ec0bea846fe8b5b9245ef01dd994` (settle=1000, production canary PASS).
Ветка: `research/production-camera-remaining-upstream-latency-v1`.

## 0. Зачем

После принятия settle=1000 (`SIGNALING_ARMED_TO_SELF_ACTIVATION_MS=1000`) settle больше не
доминирует. Задача — разложить оставшиеся участки на «наше» и «сеть/облако/панель», не меняя
протокол. Владелец: «исследовать причины первых двух участков до любых новых protocol changes».

Измеренная production-строка (live canary, один замер):

```
CAMERA_REQUEST_TO_LISTENER_PAUSED_MS=122      LISTENER_PAUSED_TO_TRANSPORT_START_MS=0
TRANSPORT_START_TO_CLOUD_NEGOTIATE_MS=2044    CLOUD_NEGOTIATE_TO_REMOTE_SDP_MS=396
REMOTE_SDP_TO_ICE_CONNECTED_MS=440            TRANSPORT_START_TO_ICE_CONNECTED_MS=2880
ICE_CONNECTED_TO_PSEUDOTCP_OPEN_MS=1993       PSEUDOTCP_OPEN_TO_CTPP_READY_MS=433
ICE_CONNECTED_TO_CTPP_READY_MS=2427           CTPP_READY_TO_SIGNALING_ARMED_MS=0
SIGNALING_ARMED_TO_SELF_ACTIVATION_MS=1000    SELF_ACTIVATION_TO_RTPC_BEGIN_MS=983
RTPC_BEGIN_TO_RTPC_COMPLETE_MS=510            RTPC_COMPLETE_TO_FIRST_VIDEO_RTP_MS=140
FIRST_VIDEO_RTP_TO_DECODABLE_FRAME_MS=0       CAMERA_REQUEST_TO_FIRST_DECODABLE_FRAME_MS=8062
```

## 1. Метод и границы доказуемости

Использован production native source, сгенерированный из того же коммита, что и отгруженный
бинарь (`GENERATED_SOURCE_SHA256=4448e836…c0001`, бинарь `ff16db0d…`), плюс Python-сторона
(`custom_components/comelit/media_transport.py`), плюс прямой замер с canary. Всё read-only,
без обращений к панели и без сети.

Метки доказуемости: `PROVEN_STATIC` (из кода), `OBSERVED` (из живого замера), `PROXY`
(измерено на эквиваленте операции, потому что `homeassistant` на хосте не импортируется),
`UNRESOLVED` (без нового замера не решается).

## 2. Окно 1 — TRANSPORT_START_TO_CLOUD_NEGOTIATE_MS = 2044 (T04→T06)

Что реально происходит между T04 и T06 (`media_transport.py`):

| шаг | где | вклад |
|---|---|---|
| `_native_gate()`: sha256 отгруженного бинаря (295 056 B) + `chmod 0700` | `media_transport.py:237-258` | PROXY ≈ **0.14 ms** (n=300) |
| `_prepare_run_dir()`, `_prepare_helper_secret()` (umask 077 → chmod 600 → `os.replace`) | `media_transport.py:145+` | PROXY ≈ **0.03 ms** |
| `_async_start_video_recovery_shim()` — bind UDP 17999/17899 | `h264_recovery.py` | PROXY ≈ **0.00 ms** |
| spawn helper (musl, libnice/glib), `g_main_loop_new`, `nice_agent_new`, `g_object_set` (ICE controlled, UDP only, **no local TURN allocation**), `add_stream`, STUN, `gather()` | generated source 8020–8150 | НЕ измерено (внутри T04→T05) |
| `candidate_gathering_done_cb` → печать `ICE_GATHER=PASS` (= T05) + запись `offer.sdp` | generated source ~7814–7980 | — |
| parent: `_read_offer`, `transform_offer`, `async_get_access_token` (сетевой вызов только если токен в окне `REFRESH_SKEW_SECONDS=300`), затем метка T06 | `media_transport.py:759-766`, `oauth.py:23` | НЕ измерено (внутри T05→T06) |
| `async_negotiate_p2p` (HTTPS в Comelit cloud) = T06→T07 | `media_transport.py:770-781` | **396 ms** OBSERVED |

Вывод по окну 1: Python-подготовка (наш код) — **порядка десятых долей миллисекунды**, то есть
2044 ms — это boot helper'а + ICE gathering (STUN round trip с `#define STUN_SERVER
"192.248.183.213"` :3478), а не наш compute. Точная граница между «boot+STUN» и «offer read /
token» в текущей строке отсутствует: **T05 (ICE_GATHER_DONE) уже штампуется, но производного
поля для T04→T05 и T05→T06 нет** — это пробел инструментации, а не свойство протокола.

Ведущая гипотеза для 2044 ms (`UNRESOLVED`): первичный STUN-запрос требует одного RTT к
192.248.183.213 с повторами по RFC5389 (RTO 500 ms с удвоением при потере первого пакета) —
отсюда «полуторный-двойной» RTT. Проверяется только новым полем T04→T05.

## 3. Окно 2 — ICE_CONNECTED_TO_PSEUDOTCP_OPEN_MS = 1993 (T08→T09)

`PROVEN_STATIC`, generated source:

- `ICE_CONNECTED=PASS` (наша метка T08) печатается в ветке `NICE_COMPONENT_STATE_CONNECTED`
  (строка ~7307). **PseudoTCP в этой ветке не стартует.**
- `start_pseudotcp()` вызывается только в ветке `NICE_COMPONENT_STATE_READY` (~7317–7345):
  `report_selected_pair()` → `start_pseudotcp()` → `pseudo_tcp_socket_new` (~7070) →
  `notify_mtu` → `g_timeout_add(1, pseudotcp_clock_cb)` → SYN/ SYN-ACK с панелью →
  `pseudotcp_opened_cb` печатает `PSEUDOTCP_OPEN=PASS` (строка ~6674, наша метка T09).

Значит 1993 ms = (CONNECTED→READY внутри libnice, включая завершение checks/назначение пары) +
(PseudoTCP handshake RTT с панелью по выбранной паре). Оба слагаемых — сетевые/панельные;
наших фиксированных ожиданий здесь `PROVEN_STATIC` нет (в сгенерированном источнике нет ни
одного `g_usleep`/`sleep`). Разделить слагаемые можно **без нового нативного кода**:
маркер `ICE_READY=PASS` уже печатается в этой ветке и присутствует в отгруженном бинаре
(`strings` = 1).

## 4. Окно 3 — SELF_ACTIVATION_TO_RTPC_BEGIN_MS = 983 (T12→T13)

`PROVEN_STATIC` (generated source ~3330–3400): `ENTRANCE_SELF_ACTIVATION_SENT=PASS` →
`WAIT_SELF_ACK` (ответ панели) → `P12_TX_ENTRANCE_VIDEO_EVENT` → `WAIT_VIDEO_ACK` →
`ENTRANCE_DEVICE_VIDEO_ACK_SENT` → arm 3-секундного дедлайна
`g_timeout_add_seconds(3, p95_device_0002_timeout_cb)` → ожидание кадра `DEVICE_0002` →
`P95_TX_DEVICE_0002_ACK` → только там вызывается `p78_begin_rtpc_control()`.

Вывод: 983 ms — это цепочка ответов панели (ACK self-activation → video ACK → device-0002),
`PROVEN_STATIC` без собственных пауз; 3 s — это guard, а не ожидание. Оптимизировать нечего
без изменения протокола; потенциальный выигрыш может дать только параллелизация наших TX
(кандидат, требует protocol-решения владельца — вне этого раунда).

## 5. Находка L1 (наш код, количественно): квантование детекта `remote.sdp`

`PROVEN_STATIC` (generated source 7701–7745 и 8183–8187):

- helper опрашивает `remote.sdp` таймером **`g_timeout_add(100, remote_sdp_check_cb)`**;
- для импорта требуется «стабильный размер» — `remote_stable_ticks < 2 → CONTINUE`
  (`remote_last_size`/`remote_stable_ticks`, строки 1150–1151, 7713–7733).

Отсюда задержка от записи файла родителем до старта ICE-checks = (ждать ближайший тик:
0–100 ms) + 200 ms (два дополнительных тика) = **200–300 ms**.

При этом родитель пишет файл **атомарно**: `_atomic_write` (`media_transport.py:200-217`:
`tmp.write_bytes` → `chmod 0600` → `os.replace`), поэтому «частично записанный файл», против
которого и стоит правило двух тиков, **невозможен** — `PROVEN_STATIC`. То есть правило
избыточно, а его цена — 200–300 ms внутри измеренного `REMOTE_SDP_TO_ICE_CONNECTED_MS=440`:
**больше половины этого окна — наше квантование, а не сеть.**

Побочно: `stop_check_cb` тоже опрашивает STOP-файл раз в 100 ms → до 100 ms квантования на
teardown (на старт не влияет).

## 6. Итоговая атрибуция (замер canary)

| участок | ms | класс |
|---|---|---|
| listener pause → transport start | 122 | наше (оркестрация сессии) |
| Python-подготовка транспорта | ≲1 | наше (`PROXY`) |
| boot helper + ICE gathering + offer/token (T04→T06) | 2044 | сеть/облако + неразделённый пробел инструментации |
| cloud negotiate (T06→T07) | 396 | облако |
| запись remote.sdp → ICE connected (T07→T08) | 440 | **200–300 наше квантование (L1)** + остаток сеть |
| ICE connected → PseudoTCP open (T08→T09) | 1993 | сеть/панель (libnice READY + handshake) |
| PseudoTCP open → true CTPP ready | 433 | протокол/панель |
| true CTPP → signaling armed | 0 | — |
| settle (armed → self-activation) | 1000 | наше, уже оптимизировано (4000→1000) |
| self-activation → RTPC begin | 983 | панель (цепочка ACK), guard 3 s |
| RTPC begin → control complete | 510 | нативный протокол |
| RTPC → first video RTP | 140 | нативный протокол |
| first RTP → decodable frame | 0 | — |

## 7. Предлагаемый следующий инкремент (только диагностика, Python-only)

Наблюдаемость требуемых критериев уже доказана read-only: маркеры `ICE_READY=PASS`,
`ICE_GATHER=PASS`, `SELECTED_PAIR*` присутствуют в отгруженном бинаре, `ICE_CONNECTED=PASS`,
`PSEUDOTCP_OPEN=PASS` уже используются.

Спецификация (никаких protocol/lifecycle изменений, никакого rebuild):

1. Новая граница `T08B_ICE_READY` ↔ нативный `ICE_READY=PASS` (перенаблюдение; T08 остаётся на
   `ICE_CONNECTED=PASS`).
2. Новые поля строки: `TRANSPORT_START_TO_ICE_GATHER_MS` (T04→T05),
   `ICE_GATHER_TO_CLOUD_NEGOTIATE_MS` (T05→T06), `ICE_CONNECTED_TO_ICE_READY_MS` (T08→T08B),
   `ICE_READY_TO_PSEUDOTCP_OPEN_MS` (T08B→T09).
3. Все существующие поля сохраняются; `MAX_BOUNDARIES` = 23; отсутствующие концы → `N_A`.
4. Артефакт не пересобирается (`MEDIA_NATIVE_BINARY_SHA256` не меняется), поэтому это
   Python-only дельта: deploy + 1 restart + 1 camera open.

Что даст замер: разделит 2044 ms на «boot+STUN» и «offer/token», и 1993 ms на «libnice
CONNECTED→READY» и «PseudoTCP handshake». Это то, что требует владелец перед любыми
protocol-решениями.

## 8. Кандидаты-рычаги (НЕ внедрялись; каждый — отдельное решение владельца)

| id | рычаг | ожидаемый выигрыш | цена/риск | требует |
|---|---|---|---|---|
| L1 | `remote_sdp_check_cb`: убрать избыточное правило двух тиков при атомарной записи родителя (или снизить интервал опроса) | 200–300 ms | LOW wire-risk (ничего в протоколе), но это native-правка → rebuild+repin+тесты | proof that parent is the only writer (сделано: `PROVEN_STATIC`) + отдельная авторизация candidate |
| L2 | `stop_check_cb` 100 ms → меньший интервал | ≤100 ms на teardown | LOW, native | отдельная авторизация |
| L3 | параллелить `async_get_access_token` с ICE gathering | 0–1 network RTT, только при refresh | LOW, Python | сначала замер T05→T06 |
| L4 | предварительный STUN/агент (pre-warm) | до нескольких сотен ms | MEDIUM: новый lifecycle-путь, противоречит «no new setup path» | protocol-решение владельца |

Явно **не** рекомендуется до замеров: любое изменение STUN/TURN, ICE-параметров, libnice
настроек, порядка PseudoTCP/CTPP/self-activation.

## 9. Non-goals

settle=0 и event-driven settle (отложены владельцем); удаление instrumentation (сохраняется);
изменение Door/Gate; изменение HA Stream/HLS; любые live-прогоны в этом раунде.

## 10. Требуемое решение

Нужна отдельная авторизация на инкремент §7 (Python-only: candidate + deploy exact SHA +
1 restart + 1 camera open). После него — решение по L1 (native candidate, rebuild) как
следующему шагу.
