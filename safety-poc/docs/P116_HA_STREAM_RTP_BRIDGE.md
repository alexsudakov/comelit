# P116 HA Stream RTP Bridge

Задача: `COMELIT-P116-HA-STREAM-RTP-BRIDGE`. Фаза: `EXECUTION_MODE=OFFLINE_ONLY`.
Base: `origin/main = 41d317bfe0a626d7093bc906789b561f3bf47e58` (merge PR #109).
Ветка: `fix/p116-ha-stream-rtp-bridge`.

## Static conclusion

The Comelit helper forwards RTP PT99 H264 and PT8 PCMA to loopback ports
17899/17808. PT99 includes H264 single NAL and FU-A packetization, so SDP must
declare non-interleaved H264 packetization:

`a=fmtp:99 packetization-mode=1`

This fixes the RFC 6184 SDP/RTP description mismatch. FFmpeg 6.1.1/7.1.1
depacketizer code is permissive for FU-A: `packetization_mode` is parsed from
fmtp, but `h264_handle_packet` handles FU-A without enforcing that field.
Therefore absent `packetization-mode=1` is a contract defect, not a proven
standalone explanation for the observed HA timeout.

## HA Stream error state

The observed HA text is the later worker error, after the input container has
opened, a video stream exists, the first keyframe was found, and
`muxer.mux_packet(first_keyframe)` completed. The timeout occurs while reading
the next demuxed packet with `timeout=SOURCE_TIMEOUT` (30 seconds). Offline
static evidence does not prove whether the next-packet timeout is caused by
RTP loss, timestamp cadence, missing later media, or muxer/extradata behavior.

## Host-verified offline results (2026-09-11)

Все значения — фактический вывод host-прогонов, не предположения.

| Проверка | Команда | Результат |
|---|---|---|
| Focused (P80 x3 + P116) | `unittest tests.test_p80_media_transport_static_contract tests.test_p80_ha_media_entity_wiring tests.test_p80_ha_media_runtime_transform tests.test_p116_ha_stream_rtp_bridge -q` | `Ran 43 tests ... OK` |
| Full suite | `env PYTHONPATH=safety-poc/src python3 -m unittest discover -s tests -q` | `Ran 1194 tests ... OK` |
| py_compile | `python3 -m compileall -q ../custom_components/comelit` | PASS |
| Static safety | `python3 scripts/static_safety_check.py` | PASS (`NETWORK_IMPORTS_PRESENT=false`, `COMELIT_ENDPOINTS_PRESENT=false`, 29 файлов) |
| diff check | `git diff --check` | PASS |

Baseline до правок на том же SHA: `Ran 1185 tests ... OK` (полный набор использует
`PYTHONPATH=safety-poc/src`; без него падает `test_control_plane_model` — ожидаемое свойство CI-обвязки).

### Offline RTP/SDP harness

`python3 safety-poc/research/media/v1/entrance_p116_sdp_rtp_bridge_harness.py --run`
(loopback `127.0.0.1` only, синтетический H264 от host ffmpeg 6.1.1, только скаляры).
В sandbox Codex UDP-сокет недоступен (`socket_create:PermissionError`), поэтому прогон выполняет
оркестратор на хосте. Синтетический поток: 12 access units, SPS/PPS/IDR присутствуют,
`profile_level_id=42c01e`, 21 single-NAL RTP-пакет / 575 FU-A-пакетов.

Приёмные скаляры (RED = без `a=fmtp`, GREEN = `packetization-mode=1`, SPROP = полный fmtp):

| Вариант | packetization | status | demux_error | avcC | extradata_size | codec/profile/resolution |
|---|---|---|---|---|---|---|
| RED | single / FU-A | ok | none | true | 39 | h264 / Constrained Baseline / 320x240 |
| GREEN | single / FU-A | ok | none | true | 39 | h264 / Constrained Baseline / 320x240 |
| SPROP | single / FU-A | ok | none | true | 38 | h264 / Constrained Baseline / 320x240 |

Выводы из этого прогона:
- FFmpeg НЕ энфорсит `packetization_mode` для FU-A: RED и GREEN дают идентичный приёмный результат.
  Значит исправление SDP — корректность контракта, а не самостоятельное объяснение таймаута.
- In-band SPS/PPS достаточно для extradata (`extradata_size=39`) и для fMP4 `avcC` в remux-пути
  (`-c:v copy`) ⇒ `profile-level-id`/`sprop-parameter-sets` для этого пути НЕ обязательны.
  Ограничение: проверено на host ffmpeg 6.1.1; встроенный в HA 2026.9.1 FFmpeg/PyAV не верифицирован.

### Harness metric caveats (исправленная трактовка)

- `reassembled_aus` — это **sender-side параметр** `_run_variant(..., reassembled_aus: int)`,
  то есть входная закладка харнесса. Она одинакова во всех вариантах, включая провалившийся,
  и НЕ является доказательством приёма. Как приёмный evidence её использовать нельзя.
- `demux_error=process_timeout` выставляется по `terminated=="killed"`, т.е. это «ffmpeg не
  завершился в бюджете харнесса», а не собственная ошибка FFmpeg с текстом таймаута.
- В killed-варианте выходной файл не создаётся, поэтому `avcc_present=false`/`extradata_size=0`
  там НЕ означают отсутствие extradata; читать эти поля можно только при `status=ok`.
- Приемлемые приёмные метрики: `status`, `demux_error`, `terminated`, `ffmpeg_rc`, а также поля
  `ffprobe` при наличии выходного файла.
- Вариант `production-audio-silence-fua` (video + объявленная молчащая `m=audio 17808` + окно
  тишины 1200 мс) привёл к зависанию ffmpeg и `terminated=killed`. Это воспроизведение КЛАССА
  отказа, но НЕ состояние production (в P115 аудио-пакеты растут), поэтому как root cause он не
  принимается.

### Scalar decision rule (контракт раунда 2, сохранено)

- `NOT_REQUIRED`: RED-вариант без fmtp даёт валидный fMP4-выход с `avcc_present=true`
  и ненулевым `extradata_size`.
- `REQUIRED`: RED без валидного init/extradata, а sprop-вариант даёт валидный fMP4 `avcC`.
- `UNRESOLVED`: харнесс не запускается или не различает состояния.

Host-прогон (таблица выше) попадает в `NOT_REQUIRED` ⇒ `SPS_PPS_REQUIREMENT=NOT_REQUIRED`.
T4 (детерминизм session-derived параметров) — `NOT_APPLICABLE`: session-derived путь не добавлялся.
Если бы host-результат дал `REQUIRED`, T4 обязан был стать тестом детерминированной валидации
`profile-level-id`/`sprop-parameter-sets`.

## SPS/PPS

FFmpeg SDP `sprop-parameter-sets` is the SDP path that seeds H264 extradata.
По host-прогону выше in-band SPS/PPS достаточно для remux/fMP4-avcC, поэтому
session-derived `sprop-parameter-sets` в этой фазе НЕ реализуется
(`SPS_PPS_REQUIREMENT=NOT_REQUIRED` для проверенного пути). Запиненный native helper не
менялся: `comelit-media` и `MEDIA_NATIVE_BINARY_SHA256`
(`91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7`) неизменны.

## Native build provenance

Packaged native pin:

- `MEDIA_NATIVE_BINARY_SHA256=91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7`
- `GENERATED_SOURCE_SHA256=0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79`
- Generator: `safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py`
  (P106 teardown-state classification composition), not the standalone P80 transform.

Reproducibility is now an explicit CT120 builder gate: set
`P80_BUILD_EXPECTED_SOURCE_SHA=<sha256>` and the build fails closed with
`P80_BUILD_EXPECTED_SOURCE_SHA_GATE=FAIL expected=<expected> actual=<actual>` if
the selected generator emits different C. Every builder run records
`P80_BUILD_TRANSFORM=`, `P80_BUILD_EXPECTED_SOURCE_SHA=`,
`GENERATED_SOURCE_SHA256=`, and `NATIVE_BINARY_SHA256=` in `build-meta.txt`.

For the current P116 instrumented build, the generated C and native binary are
expected to have new hashes because P116 RTP telemetry changes the generated
source. Оркестратор/следующий раунд должен заполнить фактические значения:

- `P116_GENERATED_SOURCE_SHA256=<P116_HEAD_GENERATED_SOURCE_SHA256>`
- `P116_NATIVE_BINARY_SHA256=<P116_HEAD_NATIVE_BINARY_SHA256>`

## Readiness

The local SDP file is atomically written only after the native process reports
media active. HA camera stream creation additionally requires
`transport.local_sdp_ready`, and cleanup removes the SDP on stop/final failure.
Before readiness, `stream_source()` returns `None` and no HA Stream is created.

## Round 3 native RTP telemetry

Owner decision: semantic RTP telemetry is collected inside the native helper
transform chain. External packet taps on `127.0.0.1:17899/17808` are not used:
the helper already sees every accepted inner RTP packet immediately before and
after the forwarding call, without adding a second UDP consumer or depending on
the HA Core network namespace.

The instrumentation is diagnostic-only. It parses RTP headers and, for PT99
H264 only, the first NAL header byte or FU-A indicator/header pair. It never
prints or stores raw RTP payload, SPS/PPS contents, base64, hex dumps, OAuth
material, or session material. The existing forwarding call remains:
`sendto(*fd, inner, inner_len, 0, (const struct sockaddr *)target, sizeof(*target))`.
Telemetry is updated after that call succeeds, using the same `inner` and
`inner_len`, and does not allocate sockets, create threads, read files, or drive
media lifecycle state.

Emission scheme:

- First observation: summary is emitted when a VIDEO or AUDIO stream reaches
  packet count 1.
- Bounded periodic summary: cadence is `P116_RTP_TELEMETRY_CADENCE=50`; periodic
  summaries are capped by `P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES=12` per
  stream, so P116 log growth is bounded independent of session length.
- Final summary: both VIDEO and AUDIO summaries are emitted once during normal
  helper teardown before process exit.

VIDEO markers:
`P116_VIDEO_COUNT`, `P116_VIDEO_FIRST_SEQ`, `P116_VIDEO_LAST_SEQ`,
`P116_VIDEO_SEQ_GAPS`, `P116_VIDEO_DUPLICATES`,
`P116_VIDEO_OUT_OF_ORDER`, `P116_VIDEO_FIRST_TS`, `P116_VIDEO_LAST_TS`,
`P116_VIDEO_TIMESTAMP_REGRESSIONS`, `P116_VIDEO_SSRC_COUNT`,
`P116_VIDEO_SSRC_CHANGES`, `P116_VIDEO_PT_SET`,
`P116_VIDEO_MARKER_COUNT`, `P116_VIDEO_FIRST_MONOTONIC_MS`,
`P116_VIDEO_LAST_MONOTONIC_MS`,
`P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS`, `P116_VIDEO_SPS_COUNT`,
`P116_VIDEO_PPS_COUNT`, `P116_VIDEO_FUA_COUNT`,
`P116_VIDEO_SINGLE_NAL_COUNT`.

AUDIO markers:
`P116_AUDIO_COUNT`, `P116_AUDIO_FIRST_SEQ`, `P116_AUDIO_LAST_SEQ`,
`P116_AUDIO_SEQ_GAPS`, `P116_AUDIO_DUPLICATES`,
`P116_AUDIO_OUT_OF_ORDER`, `P116_AUDIO_FIRST_TS`, `P116_AUDIO_LAST_TS`,
`P116_AUDIO_TIMESTAMP_REGRESSIONS`, `P116_AUDIO_SSRC_COUNT`,
`P116_AUDIO_SSRC_CHANGES`, `P116_AUDIO_PT_SET`,
`P116_AUDIO_FIRST_MONOTONIC_MS`, `P116_AUDIO_LAST_MONOTONIC_MS`.

Python side: `P116_` is admitted only into the bounded native marker tail with
the scalar-safe value allowlist. These markers are not media-state-driving:
activation remains exclusively `P80_MEDIA_ACTIVE=true`, and progress entities
continue to advance only from the legacy `P80_*_RTP_PACKETS` markers.

### Live correlation plan

Use one bounded production validation run and correlate scalar timestamps/events
in this order:

`MEDIA_START -> FIRST_VIDEO_RTP -> FIRST_KEYFRAME -> HA_STREAM_WORKER_START -> FIRST_HLS_OUTPUT_IF_ANY -> ERROR_DEMUXING_STREAM_IF_ANY -> LAST_VIDEO_RTP -> MEDIA_STOP -> LISTENER_READY_AFTER`

Decision classes from the owner:

- A: native VIDEO telemetry shows no packet gap, no timestamp regression, a
  first keyframe, and continuing RTP after HA worker start, but HA still times
  out. This points above native forwarding: HA demux/remux, SDP/extradata, or
  stream worker behavior.
- B: VIDEO has gaps, duplicates, out-of-order packets, SSRC churn, or timestamp
  regressions around the worker timeout. This points to native bridge input or
  upstream media continuity.
- C: VIDEO reaches a keyframe and then stops while AUDIO continues or both media
  stop before `MEDIA_STOP`. This points to device/upstream media production or
  lifecycle timing, not HA decoding alone.
- D: native telemetry is healthy through `MEDIA_STOP` and HA emits HLS output.
  This resolves the P116 failure class for the tested build as not reproduced.

## Открытые вопросы (для bounded production validation)

- Точный триггер `Operation timed out` на чтении следующего пакета после первого keyframe
  статически/оффлайн не доказан: не измерены непрерывность, порядок и таймстемпы внутреннего RTP
  после первого keyframe, а также фактическая пригодность аудио-потока.
- Требуется один bounded live-замер semantic RTP telemetry (только скаляры, без payload) на
  immutable SHA этой ветки.
