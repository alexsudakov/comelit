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

## R11 offline handoff analysis (2026-09-12)

Два production-прогона на `ccc872512590bd70e4a1510e3ae4071cada81f25`
дали воспроизводимую подпись: RTP начинается, первый keyframe приходит почти
сразу, последовательность байт-чистая, затем upstream/media path стабильно
останавливает RTP около 35-36 секунд.

Attempt 1, 10:13:12 -> 10:23:13 local, HA camera viewer не открывался:
`P116_VIDEO_COUNT=1703`, seq `60113->61815`,
`FIRST_MONOTONIC_MS=551901537 -> LAST_MONOTONIC_MS=551936678`
(35.141 s), `FIRST_KEYFRAME_MONOTONIC_MS=551901538` (+1 ms),
`SEQ_GAPS=0`, `DUPLICATES=0`, `OUT_OF_ORDER=0`,
`TIMESTAMP_REGRESSIONS=0`, `SSRC_COUNT=1`, `SSRC_CHANGES=0`,
`PT_SET=99`, `MARKER_COUNT=901`, `SPS_COUNT=10`, `PPS_COUNT=10`,
`FUA_COUNT=1494`, `SINGLE_NAL_COUNT=209`; audio `COUNT=1764`.
`ERROR_DEMUXING=0`, что ожидаемо без viewer и без stream worker.

Attempt 2, 10:35:53.027 -> 10:36:52 local, пользователь открыл HA camera view:
`P116_VIDEO_COUNT=1749`, seq `58495->60243`,
`FIRST_TS=3663334452 -> LAST_TS=3666570852`
(3 236 400 @90 kHz = 35.96 s),
`FIRST_MONOTONIC_MS=553261571 -> LAST_MONOTONIC_MS=553297455`
(35.884 s), `FIRST_KEYFRAME_MONOTONIC_MS=553261587` (+16 ms),
`SEQ_GAPS=0`, `DUPLICATES=0`, `OUT_OF_ORDER=0`,
`TIMESTAMP_REGRESSIONS=0`, `SSRC_COUNT=1`, `SSRC_CHANGES=0`,
`PT_SET=99`, `MARKER_COUNT=920`, `FUA_COUNT=1571`,
`SINGLE_NAL_COUNT=178`, `SPS_COUNT=10`, `PPS_COUNT=10`;
audio `COUNT=1799`, `FIRST_TS=199508096 -> LAST_TS=199795776`
(287 680 @8 kHz = 35.96 s), `PT_SET=8`.

HA-side leg attempt 2:

```text
2026-09-12 10:35:53.027 INFO  (MainThread)   [custom_components.comelit.media_transport] Comelit entrance media session ACTIVE
2026-09-12 10:36:47.342 INFO  (MainThread)   [custom_components.comelit.media_transport] Comelit entrance media transport completed: p116_native_markers=[...]
2026-09-12 10:36:49.059 ERROR (stream_worker)[homeassistant.components.stream.stream.camera.comelit_entrance] Error from stream worker: Error demuxing stream (Operation timed out, /run/comelit-media/local-rtp.sdp)
2026-09-12 10:36:52.712 INFO  (MainThread)   [custom_components.comelit.runtime] Comelit ring listener READY for persistent 3300s cycle
```

Последний video RTP пакет пришел в 10:36:28.911 local; HA demux error
появился в 10:36:49.059, то есть через 20.15 s после остановки RTP.
Пользователь сообщил `no image` за примерно 30 s открытого view, включая
период, когда RTP еще шел. Deadline media path остается
`hard_limit_seconds=600`; teardown закончился `media_phase=inactive`,
`media_active=False`, forwarding False; listener probe после цикла:
`listener_ready=true`, `last_error=null`, `supervisor_running=true`;
`DOOR_ACTIONS_SENT=0`, `GATE_ACTIONS_SENT=0`.

### `/run/comelit-media/local-rtp.sdp`

`PROVEN_STATIC`: Python пишет SDP атомарно после `P80_MEDIA_ACTIVE=true`.
Файл статический, ASCII, без runtime SSRC:

```text
v=0
o=- 0 0 IN IP4 127.0.0.1
s=Comelit entrance media
c=IN IP4 127.0.0.1
t=0 0
m=video 17899 RTP/AVP 99
a=rtpmap:99 H264/90000
a=fmtp:99 packetization-mode=1
a=recvonly
m=audio 17808 RTP/AVP 8
a=rtpmap:8 PCMA/8000/1
a=recvonly
```

Evidence: `custom_components/comelit/media_transport.py:35` задает
`MEDIA_VIDEO_RTP_PORT=17899`, `:36` задает `MEDIA_AUDIO_RTP_PORT=17808`,
`:64-76` содержит `_LOCAL_RTP_SDP`, `:149-150` пишет
`_MEDIA_LOCAL_SDP_FILE` как ASCII. `local_sdp_ready` зависит от active state и
существования файла (`:246-251`), а фактическая запись выполняется после
active wait (`:551-572`). Dynamic parts: нет dynamic ports и нет advertised
SSRC; только факт наличия файла зависит от runtime media activation.

### Helper local RTP sink

`PROVEN_OFFLINE`: helper composition forwards accepted inner RTP to loopback
UDP targets. Static generator evidence:
`safety-poc/research/media/v1/entrance_p80_ha_media_runtime_transform.py:99-112`
defines `P80_VIDEO_RTP_PORT=17899`, `P80_AUDIO_RTP_PORT=17808`, sockets and
targets; `:471-481` creates an AF_INET/SOCK_DGRAM socket and sets
`sin_port=htons(port)`, `sin_addr=INADDR_LOOPBACK`; `:484-499` accepts only
RTP v2 PT99/PT8; `:509-536` selects video/audio target by payload type and
calls `sendto()` with the inner RTP bytes; `:600-604` emits
`P80_MEDIA_ACTIVE=true` and the two local port markers. Installed binary
strings also contain `P80_VIDEO_RTP_PORT=%u`, `P80_AUDIO_RTP_PORT=%u`,
`P80_VIDEO_RTP_FORWARDING=PASS`, `P80_AUDIO_RTP_FORWARDING=PASS`,
`P80_MEDIA_ACTIVE=true`, `P116_%s_PT_SET=`.

### HA stream consumption

`NOT_PROVEN`: this repository does not vendor Home Assistant Core stream code.
The local component evidence proves the advertised source path and readiness,
but cannot statically substantiate which sockets HA stream binds/connects,
which payload types its PyAV/FFmpeg build accepts for this SDP, or the precise
internal branch behind `Operation timed out` for a local SDP source. Therefore
claims about HA demux internals are intentionally left unproven in this round.

### Evidence labels and hypotheses

`HANDOFF_SDP_PORT_MATCH=PROVEN_STATIC`: SDP ports 17899/17808 match the helper
composition and installed marker strings.

`HANDOFF_PT_MATCH=PROVEN_OFFLINE`: live markers show video `PT_SET=99` and
audio `PT_SET=8`; helper source accepts only PT99/PT8 and SDP advertises those
payload types.

`HANDOFF_SSRC_MATCH=NOT_PROVEN`: SDP has no `a=ssrc`, while live RTP had one
stable SSRC per stream. No static HA evidence here proves whether HA needs or
ignores SSRC for this SDP.

`HANDOFF_DIRECTION_MATCH=PROVEN_STATIC`: SDP says `recvonly`; helper sends RTP
with `sendto()` to loopback UDP ports. Expected direction is helper as sender,
HA/FFmpeg as UDP receiver.

`HANDOFF_EXPECTED_TO_DELIVER_PACKETS=UNDETERMINED`: static ports/PT/address and
direction line up, and live native telemetry proves forwarding counters grew,
but this repo cannot prove that HA actually bound those UDP ports in the same
namespace or consumed packets before timeout.

Current decision: `H1_SUPPORTED=false`, `H2_SUPPORTED=false`,
`HYPOTHESIS_STATUS=UNDETERMINED`. H1 ("HA receives no packets") is weakened by
the static handoff match but not falsified. H2 ("HA receives packets but cannot
demux them") is consistent with the HA error text and user-visible no-image
report, but not proven because this repo has no HA stream internals and no
read-only packet-consumption evidence from HA. The single distinguishing check
is not available statically in this repo: a future bounded live run must
observe whether the HA/FFmpeg process has bound `127.0.0.1:17899/17808` and
whether UDP packets reach that socket during the active window, without
payload capture. If a native-side fix is required, it belongs in the helper
composition around
`safety-poc/research/media/v1/entrance_p80_ha_media_runtime_transform.py:471-536`;
no native/helper change is implemented in R11.

### Evidence channels and limits

Native marker channel: one bounded HA log line now includes protocol markers
(`CTPP`, `RTPC`, `ICE`, `P80` gates, `P80_MEDIA_ACTIVE`,
`PSEUDOTCP`/`CONVERSATION`, `REMOTE_SDP_BYTES`) plus trailing P116 RTP
counters. Limit: marker values are scalar/redacted and do not contain raw
RTP/H264 or per-packet payload.

Recorder/entity channel: recorder dumps can show integration-visible state
(`media_phase`, active/forwarding flags, listener readiness, last error).
Limit: entity attributes cannot prove HA stream-worker socket binding,
received datagrams, decoder state, or PyAV/FFmpeg demux branch.

Open questions: did HA/FFmpeg bind both local UDP ports before first RTP; did
it receive any datagrams; if yes, whether failure is SDP/extradata, RTP/H264
format, audio leg behavior, timestamp handling, or upstream stop after ~36 s.

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
(`SPS_PPS_REQUIREMENT=NOT_REQUIRED` для проверенного пути).
P116-пин теперь указывает на установленный воспроизводимый native helper:
`MEDIA_NATIVE_BINARY_SHA256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622`.

## Native build provenance

Pinned P116 native artifact:

```
canonical_generator=entrance_p106_teardown_state_classification_transform.py (include_p116=1)
generated_source_sha256=93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66
generator_tree_commit=6fe4413861e7f597bb2f05f445eeb6513d7e8406
toolchain=Alpine 3.24.1 chroot (cached), cc (Alpine 15.2.0) 15.2.0, glib/gobject 2.88.1, libnice 0.1.22
flags=-O2 -g -Wall -Wextra -Wl,--as-needed
interpreter=/lib/ld-musl-x86_64.so.1
needed=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
binary_sha256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
size=270184
mode=755
glibc_interpreter=ABSENT
P116_STRING_COUNT=26
gates=MUSL_INTERPRETER_GATE=PASS, NO_GLIBC_DEPENDENCY=PASS, NO_NEW_RUNTIME_DEPENDENCY=PASS, LIB_IDENTICAL=PASS
reproducibility=two independent clean builds produced byte-identical 35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
historical=f17ad2d6efbe002335a658c075da84677ced44246d556afe80953a8f59129841 same source vs pinned 91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7 -> HISTORICAL_HASH_MISMATCH_CLASS=NON_RUNTIME_BUILD_METADATA
```

The historical packaged hash
`91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7`
does not reproduce byte-for-byte from the same historical source because of
non-runtime build metadata: BuildID, DWARF, and build-path strings differ.
Runtime sections and ABI are identical for that historical comparison:
`.text`, `.rodata`, `.data`, dynamic section, interpreter, NEEDED libraries,
symbols, relocations, and PT_LOAD geometry match.

Packaged native pin:

- `MEDIA_NATIVE_BINARY_SHA256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622`
- `GENERATED_SOURCE_SHA256=93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66`
- Generator: `safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py`
  (P106 teardown-state classification composition, `include_p116=1`), not the standalone P80 transform.

The generator has an explicit P116 provenance switch:

| Mode | Generator invocation | Builder env | Generated source SHA256 |
|---|---|---|---|
| Historical/reproduction | no flag, or `--no-include-p116` | `P80_BUILD_INCLUDE_P116=0` (default) | `0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79` |
| P116/current | `--include-p116` | `P80_BUILD_INCLUDE_P116=1` | `93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66` |

The programmatic API remains `transform(source, *, include_p116=False)`, so direct
historical generator use without a flag continues to emit the pinned historical C.
The CT120 builder default is also historical: `P80_BUILD_INCLUDE_P116=${P80_BUILD_INCLUDE_P116:-0}`.
P116 telemetry builds must opt in explicitly with `P80_BUILD_INCLUDE_P116=1`; the
builder records that value in `build-meta.txt` and in the summary.

Reproducibility is now an explicit CT120 builder gate: set
`P80_BUILD_EXPECTED_SOURCE_SHA=<sha256>` and the build fails closed with
`P80_BUILD_EXPECTED_SOURCE_SHA_GATE=FAIL expected=<expected> actual=<actual>` if
the selected generator emits different C. Every builder run records
`P80_BUILD_TRANSFORM=`, `P80_BUILD_INCLUDE_P116=`, `P80_BUILD_EXPECTED_SOURCE_SHA=`,
`GENERATED_SOURCE_SHA256=`, and `NATIVE_BINARY_SHA256=` in `build-meta.txt`.

Provenance table for historical evidence and the current P116 pin:

| Build | Canonical generator commit | include_p116 | Generated source SHA256 | Toolchain identity | Binary SHA256 | Build gates |
|---|---|---:|---|---|---|---|
| Packaged historical pin | `6fe4413861e7f597bb2f05f445eeb6513d7e8406` | `0` | `0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79` | Alpine `3.24.1`, GCC `(Alpine 15.2.0) 15.2.0`, musl interpreter `/lib/ld-musl-x86_64.so.1`, C flags `-O2 -g -Wall -Wextra -Wl,--as-needed`, NEEDED `libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10` | `91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7` | Historical reference only after P116 pin |
| Rebuilt historical source evidence | `6fe4413861e7f597bb2f05f445eeb6513d7e8406` | `0` | `0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79` | Same runtime toolchain identity as packaged pin; BuildID/debug path metadata differ | `f17ad2d6efbe002335a658c075da84677ced44246d556afe80953a8f59129841` | Runtime equivalence PASS; hash mismatch class `NON_RUNTIME_BUILD_METADATA` |
| P116 current pin | `6fe4413861e7f597bb2f05f445eeb6513d7e8406` | `1` | `93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66` | Alpine `3.24.1`, GCC `(Alpine 15.2.0) 15.2.0`, glib/gobject `2.88.1`, libnice `0.1.22`, musl interpreter `/lib/ld-musl-x86_64.so.1`, C flags `-O2 -g -Wall -Wextra -Wl,--as-needed`, NEEDED `libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10` | `35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622` | MUSL_INTERPRETER_GATE PASS; NO_GLIBC_DEPENDENCY PASS; NO_NEW_RUNTIME_DEPENDENCY PASS; LIB_IDENTICAL PASS; two clean builds byte-identical |

Pinned vs rebuilt-historical binary diagnosis: full-file SHA256 is not
reproducible, but runtime semantics are equivalent. `.text`, `.rodata`,
`.data`, `.bss`, PT_LOAD geometry, dynamic section, interpreter, NEEDED
libraries, symbols, and relocations match. Differences are BuildID and
non-loadable DWARF/debug metadata: the packaged build embeds `/repo/.p114-build`
paths, while the rebuild embeds `/src` paths. The 32-byte file size delta is
accounted for by shorter debug/path metadata and the resulting section-header
offset shift, not by runtime code or data.

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

## R12 protocol periodicity and 36 s stop forensics

`PROVEN_STATIC`: the HA log success line now preserves the existing
`protocol_native_markers=[...]` and `p116_native_markers=[...]` fields, and adds
`protocol_native_marker_timing=[KEY#count@first_ms-last_ms, ...]`. The timing
summary is keyed by safe marker family/key, uses the same redacted marker
admission path, is capped to 80 families and a 2048-character compact list, and
is emitted only once at normal media-cycle completion.

`PROVEN_OFFLINE`: the generated P80 helper declares media active after the
post-000A/001A structural ACK gate and then owns no periodic CTPP/RTPC renewal
loop. Its media-active function emits `P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT`
and `P80_MEDIA_AUTO_CLOSE_3000MS=false`, enables forwarding, and leaves accepted
PT99/PT8 RTP to `sendto()` loopback. Non-media datagrams continue to the existing
PseudoTCP path. The only 3-second timers in the generated media path are the
pre-active missing-device-ACK fail-closed gates; no generated 30-40 s forwarding
timer was found.

`NOT_PROVEN`: this repository does not contain enough official-app viewing trace
after media start to prove a required periodic media renewal/keepalive cadence or
to prove that adding such a periodic send would extend the stream. The candidate
cause consistent with the new native-app fact is: after the one-shot ACK/media
start exchange, our helper stops sending client-side RTPC/CTPP/media-lifetime
traffic that the native app likely continues sending while viewing. The
corrective location, if that hypothesis is validated, is the generated helper
composition/state machine around
`safety-poc/research/media/v1/entrance_p80_ha_media_runtime_transform.py` and its
P97/P78 RTPC composition chain, not the HA Python wrapper alone.

`IDR_CADENCE_ON_OUR_PATH=initial_only_observed`: live P116 telemetry recorded the
first keyframe at +1 ms / +16 ms in two R11 runs while SPS/PPS repeated ten
times over roughly 35-36 seconds. R12 live evidence again reports repeated
SPS/PPS and no clean second-IDR proof. The generated helper only classifies IDR
NAL type 5/FU-A type 5; no protocol request or decoder-feedback path for
requesting a fresh IDR is proven in this repo.

`HA_STREAM_SOURCE_CONTRACT=PROVEN_STATIC`: `camera.py` hands HA Stream the string
path returned by `transport.local_sdp_path` only while the manager is active and
`transport.local_sdp_ready` is true, and constructs `Stream(...,
pyav_options={"protocol_whitelist": "file,udp,rtp"}, ...)`. The current SDP is
loopback RTP/AVP PT99/PT8 with `a=recvonly` on both m-lines and no `a=ssrc`.
Because HA Core is not vendored in this repo, whether missing `a=ssrc` matters
for HA's demuxer remains `NOT_PROVEN`; direction is statically consistent with
helper-as-sender and HA/FFmpeg-as-receiver.

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

## R13 HA render path + media lifetime forensics

`BASE_SHA=139c2b78c8a0dfd9bc5ed521a66c9c522e3a5da8`. Эта итерация была
строго offline: live Comelit/HA restart/deploy/OAuth/Door/Gate не выполнялись,
`custom_components/**` и `.p116-evidence/**` не изменялись, native binary не
запускался.

### D2 chain

`RTP PT99 -> FFmpeg RTP demux = PROVEN_STATIC`: staged SDP/bridge contract
использует PT99 H264/90000 на `127.0.0.1:17899`, а FFmpeg 6.1.1/7.1.1
`rtpdec_h264.c` парсит `packetization-mode` и обрабатывает FU-A (`case 28`)
без проверки этого поля. `sprop-parameter-sets` является статическим SDP-путем
к `codecpar->extradata`; in-band SPS/PPS пригодность для HA PyAV в этой среде
не закрыта, потому что `import av` отсутствует.

`FFmpeg RTP demux -> av.Packet = UNRESOLVED_INPUT_UNAVAILABLE`: локально нет
PyAV и нет raw RTP capture. Можно доказать только C-код RTP depacketizer и
старый host-harness результат; нельзя измерить `packet.dts`, `packet.pts`,
`packet.time_base`, `packet.is_keyframe` для текущего production потока.

`av.Packet -> TimestampValidator = PROVEN_STATIC`: `TimestampValidator` в
`.p116-evidence/stream/worker.py` отбрасывает пакеты без DTS до
`MAX_MISSING_DTS + 1`, отбрасывает non-monotonic DTS, и бросает
`StreamWorkerError` только при большом разрыве DTS. Наблюдаемая ошибка
`Error demuxing stream (...)` находится после успешного поиска первого
keyframe и после `muxer.mux_packet(first_keyframe)`.

`TimestampValidator -> first_keyframe = OBSERVED`: HA лог R11/R12 указывает на
поздний `Error demuxing stream (...)`, а staged worker достигает этого текста
только после `first_keyframe = next(...)` и успешного mux первого keyframe.

`first_keyframe -> StreamMuxer.reset() -> mux_packet(first_keyframe) =
OBSERVED`: тот же observed branch доказывает прохождение этих переходов до
ошибки чтения следующего пакета.

`subsequent mux_packet() = UNRESOLVED_INPUT_UNAVAILABLE`: ошибка возникает на
`next(container_packets)`, поэтому локально не доказано, был ли следующий
валидный video packet отдан muxer, был ли он отфильтрован validator, или PyAV
заблокировался до выдачи пакета.

`MP4 fragment bytes -> StreamMuxer.create_segment() -> Segment.async_add_part()
= NOT_PROVEN`: staged muxer создает `Segment` только когда `delay_moov`/FFmpeg
передвинул `BytesIO` и затем вызывает `async_add_part(Part(...))`. Но без PyAV
и capture нельзя доказать, что первый `moof/mdat` реально был записан на
production packet sequence.

`HLS playlist/part availability = UNRESOLVED_INPUT_UNAVAILABLE`: staged
`core.py` содержит `Segment.render_hls()`, но provider layer
`.p116-evidence/stream/hls.py` отсутствует. Для закрытия нужны `HlsStreamOutput`
и view/segment/part handlers из `stream/hls.py`.

Скалярный вывод: `D2_FIRST_LL_HLS_PART_CREATED=UNRESOLVED`,
`VIDEO_CODEC_EXTRADATA_AVAILABLE_BEFORE_MUX=UNRESOLVED_INPUT_UNAVAILABLE`,
`VIDEO_TIME_BASE=UNRESOLVED_INPUT_UNAVAILABLE`,
`FIRST_KEYFRAME_DTS_PTS_VALID=OBSERVED`, `NEXT_VIDEO_PACKET_DTS_PTS_VALID=UNRESOLVED`,
`TIMESTAMP_VALIDATOR_DROPS=NOT_PROVEN`, `MUX_FIRST_KEYFRAME=PASS`,
`MP4_INIT_WRITTEN=NOT_PROVEN`, `FIRST_MOOF_WRITTEN=NOT_PROVEN`,
`FIRST_SEGMENT_OBJECT_CREATED=NOT_PROVEN`, `FIRST_PART_CREATED=NOT_PROVEN`,
`FIRST_PART_HAS_KEYFRAME=NOT_PROVEN`,
`HLS_PLAYLIST_CAN_EXPOSE_OPEN_SEGMENT=UNRESOLVED_INPUT_UNAVAILABLE`.

`PCMA_BLOCKS_VIDEO_MUX=false`: staged HA `stream/const.py` supports only
`{"aac", "mp3"}` audio. `worker.py` sets `audio_stream = None` when the codec
name is outside that set, so PT8/PCMA cannot be a required output mux dependency
for video in this HA path.

LL-HLS default path: `ll_hls=True`, segment duration default `6`, part duration
default `1`, `min_segment_duration=5.9`, `frag_duration=900000` microseconds
for 1s parts, `delay_moov` enabled. A second keyframe after `min_segment_duration`
is statically required to close the first full `Segment`. A second IDR is
`NOT_PROVEN` as required for the first playable `Part`; that depends on actual
first `moof/mdat` emission and `stream/hls.py` open-part exposure.

Offline reproduction: `python3 safety-poc/research/media/v1/entrance_p116_sdp_rtp_bridge_harness.py --run`
generated synthetic input (`access_units=12`, `idr_count=12`, SPS/PPS present)
but stopped at `HARNESS_STATUS=NOT_RUN reason=socket_create:PermissionError`.
Therefore V1/V2/V3/V4 decisive `NO_PART -> PART_CREATED` or
`NO_PLAYABLE_OUTPUT -> PLAYABLE_OUTPUT` transitions were not run in this
sandbox.

### D1 outbound inventory

Required conclusion: `OUR_RTP_STOP_AROUND_36S=PROVEN_FOR_3_P116_SESSIONS`,
`PERIODIC_CLIENT_TRAFFIC_REQUIRED=NOT_PROVEN`,
`KEEPALIVE_MESSAGE_TYPE=NOT_PROVEN`.

Generated helper inventory after `P80_MEDIA_ACTIVE=true`:

`EVENT=P80 media active markers`, `DIRECTION=stdout only`,
`FIRST_OBSERVED=immediate`, `CADENCE=once`, `SOURCE_EVIDENCE=entrance_p80...:600-607`,
`OUR_HELPER_SENDS_IT=false`, `LIFETIME_CAUSALITY=NOT_PROVEN`,
`IDR_CAUSALITY=NOT_PROVEN`.

`EVENT=PT99/PT8 RTP loopback forwarding`, `DIRECTION=helper -> HA localhost UDP`,
`FIRST_OBSERVED=first accepted RTP`, `CADENCE=inbound-RTP-driven`,
`SOURCE_EVIDENCE=entrance_p80...:529-575`, `OUR_HELPER_SENDS_IT=true`,
`LIFETIME_CAUSALITY=NOT_PROVEN`, `IDR_CAUSALITY=NOT_PROVEN`.

`EVENT=P80 RTP packet progress markers`, `DIRECTION=stdout only`,
`FIRST_OBSERVED=packet 1`, `CADENCE=1 then every 50 per stream`,
`SOURCE_EVIDENCE=entrance_p80...:547-575`, `OUR_HELPER_SENDS_IT=false`,
`LIFETIME_CAUSALITY=NOT_PROVEN`, `IDR_CAUSALITY=NOT_PROVEN`.

`EVENT=non-media PseudoTCP receive path`, `DIRECTION=device -> helper/libnice`,
`FIRST_OBSERVED=whenever non-media datagram arrives`, `CADENCE=input-driven`,
`SOURCE_EVIDENCE=entrance_p80...:612-622 plus inherited PseudoTCP code`,
`OUR_HELPER_SENDS_IT=false`, `LIFETIME_CAUSALITY=PLAUSIBLE`,
`IDR_CAUSALITY=PLAUSIBLE`.

`EVENT=P97/P92 missing ACK timers`, `DIRECTION=internal fail-closed timer`,
`FIRST_OBSERVED=before media-active only`, `CADENCE=one-shot 3s gates`,
`SOURCE_EVIDENCE=entrance_p97...:204-227; entrance_p92...:121-133`,
`OUR_HELPER_SENDS_IT=false`, `LIFETIME_CAUSALITY=NOT_PROVEN`,
`IDR_CAUSALITY=NOT_PROVEN`.

Repo capture artifacts contain an official-app teardown signature at about
35.098s in `self_activation.pcap` and 47.284s in `p2p_rtsp.pcap`, plus
media-bearing non-PseudoTCP RTP and residual PseudoTCP app traffic. They do not
contain a local frozen P77 raw RTP artifact, and they do not prove a repeating
CTPP/RTPC heartbeat, RTCP feedback, PLI/FIR, keyframe request, or session-renewal
message. `MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D1_AND_D2=PLAUSIBLE`, because a
post-active official-client feedback loop could both extend media lifetime and
request/trigger decodable/keyframe cadence, but no local artifact proves it.

### Redaction audit

Текущий value regex разрешает booleans, PASS/FAIL-style enums, `FATAL`, `NONE`,
decimal scalars and comma-separated small integer sets. Поэтому часть safe
enum/scalar markers is redacted today.

`SAFE_REDACTION_EXPANSION=` exact proposal:
`^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|FATAL|NONE|HOME_ASSISTANT|STATE_SCOPED_STRUCTURAL|NOT_MATCHED|ACTIVE|PREACTIVE|DISCONNECTED|GATHERING|CONNECTING|CONNECTED|READY|FAILED|[0-9]{1,20}|[0-9]{1,3}(?:,[0-9]{1,3}){0,127})$`

Rationale: `P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT`,
`P80_DEVICE_ACK_000A_BINDING=STATE_SCOPED_STRUCTURAL`,
`P80_DEVICE_ACK_000A_TAIL_RELATION=PASS|NOT_MATCHED`,
`P80_DEVICE_ACK_001A_*` same domain,
`P80_WRAPPER_PROFILE_MISMATCH_STATE=ACTIVE|PREACTIVE`,
`PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=true|false`,
`PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=true|false`,
`PSEUDOTCP_NOTIFY_PACKET_CLASS=EXPECTED_TERMINAL_SHUTDOWN|FATAL`,
`ICE_COMPONENT_STATE=DISCONNECTED|GATHERING|CONNECTING|CONNECTED|READY|FAILED`,
`PSEUDOTCP_CLOSED_CALLBACK=true` are bounded enums/scalars. Values that could
carry SDP, ICE credentials, selected pair addresses, tokens, channel ids beyond
numeric scalars, raw payload, or free text remain redacted. No catch-all pattern
is proposed; tests keep secret-shaped sentinels rejected.

### Missing gates

`MINIMAL_MISSING_INPUTS`: exact HA 2026.9.1 `stream/hls.py` and PyAV/FFmpeg
environment; V1-V5 raw RTP replay capture such as CT120
`media/video.rtpdatagrams`; one official-app trace from 5s before media-active
to at least 60s after, both directions, containing packet timing, direction,
protocol class (CTPP/RTPC/PseudoTCP/STUN/TURN/RTP/RTCP), safe message type/opcode
and length, and H264 semantic scalars (SPS/PPS/IDR counts), without OAuth tokens,
ICE credentials, raw media payloads, addresses beyond anonymized endpoint roles,
or session secrets.

`UNRESOLVED_INPUT_GATES`: first HA LL-HLS part creation, first `moof/mdat`
creation under PyAV, first part keyframe flag, open-segment playlist exposure,
next video packet DTS/PTS validity, timestamp-validator drop count, V1/V2/V3/V4
offline variant outcome, and any causal keepalive/IDR-request message.
