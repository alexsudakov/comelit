# P78 Entrance Media One-Shot Live Closure

TASK_ID=COMELIT-P78-ENTRANCE-MEDIA-ONE-SHOT-LIVE-CLOSURE
BASE_MAIN_SHA=661f9d4c26350f2fdbce0a1c55b04ad1e5c86ee2
EXECUTION_MODE=OFFLINE_IMPLEMENTATION_ONLY
LIVE_EXECUTION_AUTHORIZED=false
C_CANDIDATE_COMPILE=NOT_AVAILABLE

## Базовая точка

Эта итерация добавляет только новые артефакты P78 поверх `661f9d4c26350f2fdbce0a1c55b04ad1e5c86ee2`. Исторические файлы P73-P77, старые трансформы, анализаторы, лаунчеры и production `custom_components/` не изменяются.

Для собственных новых файлов P78 используется константа `P78_REVIEW_COMMIT_SHA=""`. Будущий лаунчер обязан завершиться fail-closed с `P78_REVIEW_PIN=FAIL` до появления reviewed-коммита; фиктивные SHA не используются.

## Матрица grounded transport-hook

Кодовая база уже доказывает несколько границ:

- `p12_queue_vip_frame()` является проверенным writer для ViP application frame поверх зарегистрированного CTPP.
- Единственный CTPP OPEN остается в базовой регистрации; P78 не добавляет второй `open_ctpp`.
- P46 доказывает отправку ровно одного session-derived `0x1800` ACK после device `0x0008`, но причинность ACK не доказана: `DEVICE_0008_ACK_GATE_PROVEN=false`.
- P76 доказывает offline generation/state parity для RTPC OPEN x2, client RESPONSE, client `0x000A` и client `0x001A`.
- P77 доказывает offline receive/oracle path для frozen capture: media идет как non-PseudoTCP UDP с offset-8 RTP wrapper.

Остающийся новый участок P78 узкий: после P46 ACK перейти к RTPC CONTROL progression и отправить P76-generated тела через proven writer.

## Новые артефакты

`entrance_p78_rtpc_media_live_stage_transform.py` композирует цепочку P46-P76 и заменяет старый terminal observation transition после `P12_TX_ENTRANCE_DEVICE_VIDEO_ACK`. Новая стадия:

- отправляет `P78_TX_RTPC_OPEN_1` и `P78_TX_RTPC_OPEN_2` через `p12_queue_vip_frame(0, ...)`;
- принимает device RTPC OPEN на `request_id == 0`;
- отправляет `P78_TX_RTPC_CLIENT_RESPONSE` через `p12_queue_vip_frame(0, ...)`;
- принимает две device RESPONSE;
- отправляет `P78_TX_RTPC_CLIENT_000A` и `P78_TX_RTPC_CLIENT_001A` через `p12_queue_vip_frame(v4_ctpp_channel_id, ...)`;
- после завершения включает bounded observation и штатный graceful close path `pseudo_tcp_socket_close(..., FALSE)`.

`ct120_run_entrance_p78_one_shot_live_closure.sh` является top-level future launcher. Он выполняет status-only listener checks, blob-pin базовых входов к `661f9d4c`, требует непустой reviewed `P78_REVIEW_COMMIT_SHA`, проверяет `tcpdump` до sentinel, создает `/root/.comelit-p78-live-consumed` атомарно через noclobber+fsync непосредственно перед live wrapper invocation и запускает wrapper ровно один раз под `timeout --signal=TERM --kill-after=5s 75s`. Лаунчер не выполнялся в этой задаче.

`entrance_p78_capture_verifier.py` является additive verifier для caller-supplied pcap. Он импортирует P77 helpers, но не использует frozen SHA gate. Default CLI offline-safe: без `--decode` нет subprocess decode check. Отчеты содержат только semantic markers, counts и hashes reconstructed output, без raw/hex/base64 payload.

## Marker set

Основные маркеры будущего запуска:

`P78_PREFLIGHT=PASS`
`P78_LISTENER_STATUS_BEFORE=RUNNING_READY`
`P78_LISTENER_CONTROL_MODE=STATUS_ONLY`
`P78_LISTENER_STOP_START_RESTART=false`
`P78_BASE_WRAPPER_PIN=PASS`
`P78_WRAPPER_DERIVATION=PASS`
`P78_BUILD_DEPS=PASS`
`P78_CANDIDATE_BUILD=PASS`
`P78_SENTINEL_PREEXISTING=false`
`P78_LIVE_CONSUMED_SENTINEL=CREATED_BEFORE_LIVE`
`P78_LIVE_INVOCATION_LIMIT=1`
`P78_AUTO_RETRY=false`
`P78_WRAPPER_INVOCATIONS=1`
`P78_CTPP_REGISTERED_REUSED=true`
`P78_SECOND_CTPP_OPEN=false`
`P78_SELF_ACTIVATION_SENT=PASS`
`P78_CLIENT_VIDEO_EVENT_SENT=PASS`
`P78_DEVICE_0008_EVENT=PASS`
`P78_DEVICE_0008_ACK_SENT=true`
`P78_DEVICE_0008_ACK_GATE_PROVEN=false`
`P78_RTPC_OPEN_1_SENT=PASS`
`P78_RTPC_OPEN_2_SENT=PASS`
`P78_RTPC_DEVICE_OPEN_OBSERVED=PASS`
`P78_RTPC_CLIENT_RESPONSE_SENT=PASS`
`P78_RTPC_DEVICE_RESPONSE_1=PASS`
`P78_RTPC_DEVICE_RESPONSE_2=PASS`
`P78_RTPC_CLIENT_000A_SENT=PASS`
`P78_RTPC_CLIENT_001A_SENT=PASS`
`P78_RTPC_SIGNALING_RESULT=<PASS|FAIL|UNKNOWN>`
`P78_MEDIA_CAPTURE_STARTED=true`
`P78_MEDIA_CAPTURE_WINDOW_SECONDS<=12`
`P78_MEDIA_PAYLOAD_STDOUT=false`
`P78_RAW_PAYLOAD_EMITTED=false`
`P78_H264_ORACLE=<PASS|NOT_PROVIDED|REJECTED_INPUT|NOT_PROVEN>`
`P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false`
`P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false`
`P78_DOOR_ACTION_SENT=false`
`P78_HOME_ASSISTANT_CORE_STOPPED=false`
`P78_HOME_ASSISTANT_CORE_RESTARTED=false`
`P78_LISTENER_STATUS_AFTER=RUNNING_READY`
`P78_RUN_RESULT=<PASS|FAIL|UNKNOWN_OUTCOME>`

Task-level invariant markers in offline/preflight context:

`LISTENER_CHANGED=NO`
`P78_SENTINEL_CONSUMED=false`
`DOOR_ACTION_SENT_COUNT=0`
`AUTOMATIC_RETRY=false`
`SECOND_CTPP_OPEN=false`
`LIVE_INVOCATIONS=0`

## Offline tests

Добавлены focused tests:

- transform anchor counts and generated bridge markers;
- static launcher contract: sentinel, no retry loop, status-only listener checks, timeout bound, capture window, pins, marker completeness;
- verifier synthetic offset-8 RTP happy path, malformed/unknown fail-closed behavior, no raw payload report, and opt-in decode path.

Проверки выполнены offline only:

- `python3 -m py_compile` для новых Python модулей;
- `bash -n` для P78 launcher;
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_p78*.py'`;
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p '*entrance*.py'`.

Полная компиляция C-кандидата на CT122 не выполняется: отсутствуют dev headers `nice/glib`, поэтому `C_CANDIDATE_COMPILE=NOT_AVAILABLE`.

## LIVE_ONLY facts

Следующие факты остаются только для отдельного future live approval:

- реальная панель примет generated P78 RTPC CONTROL sequence;
- runtime UDP media 5-tuple появится в bounded capture window;
- новый pcap пройдет P78 verifier и даст декодируемые H264 access units;
- `0x1800` ACK действительно нужен для старта media;
- graceful close освободит upstream media resources без вреда listener readiness;
- Home Assistant listener останется `RUNNING_READY` до и после live attempt.

## References

- `P73_RTPC_TARGET_ID_STATIC_PROVENANCE.md`
- `P74_ALLOCATOR_BACKED_RTPC_MEDIA_GENERATION.md`
- `P75_RTPC_CONTROL_MEDIA_STATE_MACHINE.md`
- `P76_RTPC_C_RUNTIME_PARITY.md`
- `P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md`

## Next steps

Локальный review должен проверить новые P78 файлы, затем отдельный commit/push/PR зафиксирует `P78_REVIEW_COMMIT_SHA`. Только после этого возможен отдельный live approval. В этой задаче live run не выполняется.
