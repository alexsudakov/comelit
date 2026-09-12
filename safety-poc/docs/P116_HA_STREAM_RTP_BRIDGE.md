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

## P116 R13C single-IDR closure (2026-09-12)

R13C выполнен только offline, без socket/network/live/HA deploy. Исходный
артефакт: `.p116-evidence/private/p115-run5/video.rtpdatagrams`,
`sha256=76c8e173fa38e4f8b9fbba50b66899c292b802065240b17740d0db2a6b43373b`,
framing `uint16_be_length_prefixed_rtp_payloads`, mode `600`.

Конструкция варианта детерминированная: parser читает RTP PT99, группирует
H264 NAL в access units по RTP timestamp/marker, находит второй AU с IDR и
удаляет только RTP datagrams этого AU. Payload bytes вне этого AU не меняются;
слепого byte patching нет. Derived stream записан вне Git:
`.p116-evidence/private/p115-run5/video.single-idr.r13c.rtpdatagrams`,
mode `600`, `sha256=f2aa0b671baaf55005b6a242419f48a9358bb448aaa2c4c4cec2c16462e490c6`.

Идентификация удаленного IDR:

| Scalar | Value |
|---|---|
| `SOURCE_RTP_DATAGRAMS` | `1538` |
| `SOURCE_ACCESS_UNITS` | `745` |
| `SOURCE_IDR_AU_COUNT` | `2` |
| `SECOND_IDR_AU_INDEX` | `8` |
| `SECOND_IDR_RTP_SEQ_RANGE` | `4916-4921` |
| `SECOND_IDR_RTP_TS_RANGE` | `3606231252-3606231252` |
| `SECOND_IDR_NAL_TYPES` | `5` |
| `SECOND_IDR_PACKET_COUNT` | `6` |

Валидация single-IDR variant под `/tmp/comelit-r13-pyav/bin/python`
(`PyAV 17.0.1`, `libavformat 62.3.100`):

| Marker | Value |
|---|---|
| `SINGLE_IDR_VARIANT_VALID` | `true` |
| `IDR_AU_COUNT` | `1` |
| `SPS_COUNT` | `9` |
| `PPS_COUNT` | `9` |
| `PYAV_OPEN` | `true` |
| `VIDEO_STREAM_FOUND` | `true` |
| `CODEC_EXTRADATA_SIZE` | `28` |
| `VIDEO_TIME_BASE` | `1/1200000` |
| `DECODED_FRAME_COUNT_SAMPLE` | `3` |
| `FIRST_KEYFRAME_FOUND` | `true` |
| `FIRST_KEYFRAME_DTS` | `0` |
| `FIRST_KEYFRAME_PTS` | `0` |
| `MUX_FIRST_KEYFRAME` | `PASS` |
| `MP4_INIT_WRITTEN` | `true` |
| `FIRST_MOOF_WRITTEN` | `true` |
| `FIRST_MDAT_WRITTEN` | `true` |
| `FIRST_SEGMENT_OBJECT_CREATED` | `true` |
| `FIRST_LL_HLS_PART_CREATED` | `true` |
| `FIRST_PART_HAS_KEYFRAME` | `true` |
| `HLS_PLAYLIST_CAN_EXPOSE_OPEN_SEGMENT` | `true` |
| `TIMESTAMP_VALIDATOR_DROPS` | `15` |

Решения:

| Decision | Value | Rationale |
|---|---|---|
| `SECOND_IDR_REQUIRED_FOR_FIRST_PART` | `false` | Single-IDR stream still creates the first LL-HLS Part with init/moof/mdat and first-part keyframe. |
| `SECOND_IDR_REQUIRED_FOR_SEGMENT_CLOSE` | `true` | HA 2026.9.1 `StreamMuxer.mux_packet` closes a normal segment only on a later video keyframe after `min_segment_duration`; without a second keyframe this static close condition is not met. |
| `D2_SINGLE_IDR_HYPOTHESIS_STATUS` | `closed` | The "no image because no second IDR is available for the first part" hypothesis is rejected for first-part creation. It remains separate from full segment closure. |

## P116 R13C official-app capture plan

Цель будущего owner-approved capture: сравнить
`OFFICIAL_APP_POST_ACTIVE_EVENTS` и `OUR_HELPER_POST_ACTIVE_EVENTS` вокруг
media-active и проверить, есть ли client feedback или post-active scheduler,
которого нет у helper. Capture не выполняется в R13C; требуется отдельное
решение владельца.

Required window: `>=5 s before media-active and >=60 s after`, in both
directions. `TRACE_REQUIRED_DIRECTIONS=client_to_device,device_to_client`.
Начальная точка `media-active` фиксируется монотонным временем из локального
capture runner; wall-clock используется только для внешней корреляции и не
попадает в доказательства как identifier.

Privacy gate:

| Rule | Requirement |
|---|---|
| Secrets | Never carry OAuth/refresh/access/VIP tokens, ICE username/password, session IDs, device UUIDs, IP/address material beyond the proof need, raw application payload, raw RTP media, or raw H264 into repo evidence/docs. |
| Raw PCAP | If needed, raw PCAP stays outside Git only, mode `600`, SHA256 recorded, analyzed locally, then deleted or retained only by owner policy. |
| Repository evidence | Commit only sanitized scalar extracts: relative monotonic timestamp, direction, transport/channel class, protocol family, safe opcode/message type, length, repeat count, cadence, and RTP/RTCP/H264 structural counts. |
| Redaction | Numeric-only unknowns resolve to `<redacted>` unless marker-specific policy below allows them. |

Minimum extractable data per packet/message:

| Family | Scalars |
|---|---|
| Common | relative monotonic timestamp, direction, transport/channel class, protocol family, safe opcode/message type, packet/message length, repeat count, cadence |
| RTP | PT, packet counts, seq progression, timestamp progression, SSRC changes as count/change indicator only |
| RTCP | presence, packet type, direction, cadence |
| H264 | SPS count/times, PPS count/times, IDR count/times |

Post-active candidate classes to check:

| `EVENT` | `DIRECTION` | `FIRST_AT` | `LAST_AT` | `REPEAT_COUNT` | `CADENCE` | `MESSAGE_LENGTH` | `OUR_HELPER_EQUIVALENT` | `MEDIA_LIFETIME_CANDIDATE` | `IDR_FEEDBACK_CANDIDATE` | `SOURCE_EVIDENCE` |
|---|---|---|---|---|---|---|---|---|---|---|
| `REPEATING_CTPP` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE until official trace proves | NOT_PROVEN | sanitized CTPP frame class only |
| `REPEATING_RTPC` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PLAUSIBLE if opcode/timing matches feedback | sanitized RTPC envelope/opcode class |
| `PSEUDOTCP_APPLICATION_TRAFFIC` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PLAUSIBLE if post-IDR cadence aligns | length + safe flags only |
| `ACK_CONTROL` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PLAUSIBLE | ACK/control type, no payload |
| `HEARTBEAT_PING` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | NOT_PROVEN | type + cadence |
| `SESSION_RENEWAL` | client_to_device | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | NOT_PROVEN | safe renewal marker only |
| `RECEIVER_FEEDBACK` | client_to_device | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PLAUSIBLE | feedback class only |
| `RTCP_FEEDBACK` | both | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PROVEN only if RTCP feedback type is present | RTCP packet type/count/cadence |
| `KEYFRAME_IDR_REQUEST` | client_to_device | scalar | scalar | scalar | scalar | scalar | compare | PLAUSIBLE | PROVEN only with known safe IDR-request type | opcode/type class, no payload |
| `TIMER_SCHEDULER_LT_36S` | both | scalar | scalar | scalar | `<36s` | scalar | compare | PLAUSIBLE | NOT_PROVEN | repeated event cadence |
| `TRAFFIC_PAST_36S` | both | `>36s` | scalar | scalar | scalar | scalar | compare | PROVEN if official continues and helper stops | NOT_PROVEN | post-36s continuation class |

Decision rule:

| Question | Current R13C answer |
|---|---|
| `MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D1_AND_D2` | `PLAUSIBLE` |

Rationale: two helper attempts showed clean RTP then stop near 35-36 s, while
the offline single-IDR result closes the first-part-specific second-IDR
hypothesis. Missing post-active client feedback, RTCP feedback, heartbeat,
renewal, or IDR request can plausibly explain both media lifetime and keyframe
refresh behavior, but remains unproven until an official-app comparison exists.

## P116 R13C numeric redaction policy proposal

No production change is made in R13C. Existing regex `[0-9]{1,20}` is too
wide because a numeric-only value can be a session, target, account, or device
identifier. Proposed policy: unknown numerics resolve to `<redacted>`; numeric
values are exposed only for an explicit safe marker or explicit safe family.
Allowed families: packet counts, byte counts, durations, ages, seq-gap counts,
duplicate/out-of-order/timestamp-regression counts, RTP structural timestamps
when not a session identifier, PT, codec structural numbers, bounded sizes,
SPS/PPS/IDR counts, and safe timing diagnostics. A catch-all numeric allowlist
is forbidden.

Marker-specific allowlist proposal:

| `MARKER` | `VALUE_DOMAIN` | `SAFE_TO_EXPOSE` | `RATIONALE` |
|---|---|---|---|
| `REMOTE_SDP_BYTES` | byte count | `true` | Size only; no SDP text, token, ICE credential, address, or media payload. |
| `PSEUDOTCP_APP_RX_EVENT` | bounded length + `OPEN`/`ACK` booleans | `true` | Length and safe flags support cadence analysis without payload. |
| `P80_VIDEO_RTP_PORT` | fixed local loopback port | `true` | Static loopback handoff contract marker, not remote address material. |
| `P80_AUDIO_RTP_PORT` | fixed local loopback port | `true` | Static loopback handoff contract marker, not remote address material. |
| `P80_VIDEO_RTP_PACKETS` | packet count | `true` | Bounded progress counter. |
| `P80_AUDIO_RTP_PACKETS` | packet count | `true` | Bounded progress counter. |
| `P116_VIDEO_COUNT` | packet count | `true` | RTP structural count. |
| `P116_VIDEO_FIRST_SEQ` | RTP sequence number | `true` | Structural sequence progression; not a session/device ID. |
| `P116_VIDEO_LAST_SEQ` | RTP sequence number | `true` | Structural sequence progression; not a session/device ID. |
| `P116_VIDEO_SEQ_GAPS` | count | `true` | Loss diagnostic count. |
| `P116_VIDEO_DUPLICATES` | count | `true` | Duplicate packet diagnostic count. |
| `P116_VIDEO_OUT_OF_ORDER` | count | `true` | Packet ordering diagnostic count. |
| `P116_VIDEO_FIRST_TS` | RTP timestamp | `true` | RTP structural timestamp for progression only. |
| `P116_VIDEO_LAST_TS` | RTP timestamp | `true` | RTP structural timestamp for progression only. |
| `P116_VIDEO_TIMESTAMP_REGRESSIONS` | count | `true` | Timestamp diagnostic count. |
| `P116_VIDEO_SSRC_COUNT` | count | `true` | Exposes only number of SSRCs, never SSRC value. |
| `P116_VIDEO_SSRC_CHANGES` | count | `true` | Exposes only change count, never SSRC value. |
| `P116_VIDEO_PT_SET` | RTP payload types | `true` | Codec/transport structural numbers. |
| `P116_VIDEO_MARKER_COUNT` | count | `true` | RTP marker-bit count. |
| `P116_VIDEO_FIRST_MONOTONIC_MS` | relative monotonic timing | `true` | Local timing diagnostic, not wall-clock or identifier. |
| `P116_VIDEO_LAST_MONOTONIC_MS` | relative monotonic timing | `true` | Local timing diagnostic, not wall-clock or identifier. |
| `P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS` | relative monotonic timing | `true` | Local keyframe timing diagnostic. |
| `P116_VIDEO_SPS_COUNT` | count | `true` | H264 structural count. |
| `P116_VIDEO_PPS_COUNT` | count | `true` | H264 structural count. |
| `P116_VIDEO_FUA_COUNT` | count | `true` | RTP/H264 packetization structural count. |
| `P116_VIDEO_SINGLE_NAL_COUNT` | count | `true` | RTP/H264 packetization structural count. |
| `P116_AUDIO_COUNT` | packet count | `true` | RTP structural count. |
| `P116_AUDIO_FIRST_SEQ` | RTP sequence number | `true` | Structural sequence progression; not a session/device ID. |
| `P116_AUDIO_LAST_SEQ` | RTP sequence number | `true` | Structural sequence progression; not a session/device ID. |
| `P116_AUDIO_SEQ_GAPS` | count | `true` | Loss diagnostic count. |
| `P116_AUDIO_DUPLICATES` | count | `true` | Duplicate packet diagnostic count. |
| `P116_AUDIO_OUT_OF_ORDER` | count | `true` | Packet ordering diagnostic count. |
| `P116_AUDIO_FIRST_TS` | RTP timestamp | `true` | RTP structural timestamp for progression only. |
| `P116_AUDIO_LAST_TS` | RTP timestamp | `true` | RTP structural timestamp for progression only. |
| `P116_AUDIO_TIMESTAMP_REGRESSIONS` | count | `true` | Timestamp diagnostic count. |
| `P116_AUDIO_SSRC_COUNT` | count | `true` | Exposes only number of SSRCs, never SSRC value. |
| `P116_AUDIO_SSRC_CHANGES` | count | `true` | Exposes only change count, never SSRC value. |
| `P116_AUDIO_PT_SET` | RTP payload types | `true` | Codec/transport structural numbers. |
| `P116_AUDIO_FIRST_MONOTONIC_MS` | relative monotonic timing | `true` | Local timing diagnostic, not wall-clock or identifier. |
| `P116_AUDIO_LAST_MONOTONIC_MS` | relative monotonic timing | `true` | Local timing diagnostic, not wall-clock or identifier. |
| `ENTRANCE_MEDIA_OBSERVATION_RX_EVENT` | packet/message length | `true` | Bounded receive length only; payload is not emitted. |
| `CTPP_*` unknown numeric-only value | unknown numeric | `false` | Could be session, target, account, or device identifier unless explicitly typed. |
| `RTPC_*` unknown numeric-only value | unknown numeric | `false` | Could be session, target, account, or device identifier unless explicitly typed. |
| `P80_DEVICE_*` numeric suffix/value | device/opcode marker | `false` for generic numeric value, `true` only for explicit safe opcode labels | Device/target IDs must not be exposed as generic numerics. |
| `V4_CTPP_*` unknown numeric-only value | unknown numeric | `false` | Legacy CTPP numeric values can be identifiers. |
| `SELECTED_PAIR_*` numeric-only value | ICE/network candidate detail | `false` | Can encode network or session material. |
| `ICE_*` numeric-only value | ICE/session/network diagnostic | `false` by default | Safe only if explicitly reduced to count/cadence/state. |

`REDACTION_NUMERIC_POLICY=unknown_numeric_redacted_marker_specific_allowlist`
and `MARKER_SPECIFIC_ALLOWLIST_PROPOSAL=true`.

## P116 R13D official-app trace capture tooling (2026-09-12)

R13D остается `OFFLINE_ONLY`: tooling authored, capture not executed.
Production SHA `0970b9c88fd47ddf83a397b0228c5d4bbef92423` не трогается; deploy,
restart, OAuth refresh, door/gate actions, helper media session и keepalive/IDR
fixes запрещены. `custom_components/**` не меняется.

Top-level runner:
`safety-poc/research/media/v1/p116_official_app_trace_runner.sh`.
Extractor:
`safety-poc/research/media/v1/p116_official_app_trace_extractor.py`.
Runner по умолчанию выполняет только dry-run preflight. Единственный путь к
реальному passive capture требует явный operator flag
`--authorize-passive-capture`; в этом раунде этот режим не запускался.

### Feasibility table

| Capture point | OBSERVABLE_AT | VISIBLE_LAYERS | CAN_SEE_P2P/UDP_MEDIA | CAN_SEE_PROTOCOL_FAMILY | CAN_SEE_MESSAGE_TYPE | VERDICT | Reason |
|---|---|---|---|---|---|---|---|
| `(a) LAN capture at HA/CT122/CT120 host` | Только если official app / panel flow реально проходит через этот host или mirror interface уже доставляет эти frames | L2/L3/L4 metadata; plaintext application only if protocol is not encrypted and visible on the interface; TLS gives TLS_RECORD_METADATA only | `true` only for transiting/mirrored UDP; `false` for direct Wi-Fi/AP path outside host | `true` for RTP/RTCP/STUN/TURN/TCP/UDP/TLS family by ports/dissector | `METADATA_ONLY` for TLS; `true` only for plaintext safe opcode classes | `METADATA_ONLY` or `INFEASIBLE` | Обычный HA host не является L2 transit point for phone-to-device traffic. Он годится только если оператор заранее подтверждает mirror/tap or routing through this host. |
| `(b) mirrored/SPAN port on switch or AP` | Switch/AP mirror that receives phone and entrance-device traffic | L2/L3/L4 metadata, RTP/RTCP structural fields, TLS record metadata; plaintext only if protocol itself plaintext | `true` if mirror covers phone radio/VLAN and device port/VLAN | `true` for transport/protocol family and cadence | `METADATA_ONLY` for TLS; `true` for RTCP packet types and plaintext safe classes | `FEASIBLE` | Best passive point: no traffic modification, sees both directions, can prove continuation past 36 s and cadence below 36 s. |
| `(c) router-side capture` | Router/firewall packet capture for the relevant LAN/VLAN | L3/L4 metadata, TLS record metadata; sometimes no same-LAN switched traffic | `true` only if traffic routes through router; `false` for same-subnet switched P2P | `true` for routed flows | `METADATA_ONLY` for encrypted control; RTCP types only if media is routed and decoded | `METADATA_ONLY` | Useful if official app uses cloud/TURN/routed paths. Often misses direct same-LAN phone-to-device frames. |
| `(d) phone-side capture` | Operator device OS-level capture app or OS packet trace | Device-local L3/L4 metadata, possible TLS record metadata, possible VPN capture constraints | `true` for flows visible to OS capture; platform-dependent for local Wi-Fi and media sockets | `true` for endpoint/cadence/family if OS exposes packets | `METADATA_ONLY` for TLS; plaintext only if app traffic is not encrypted | `FEASIBLE` but operator-dependent | Passive from network perspective, but requires operator device setup and privacy review. Documented as an option, not required by repo tooling. |
| `(e) TLS-terminating observation` | Proxy/MITM/decryption endpoint | Would expose plaintext only by changing trust/flow or using secrets | N/A | N/A | N/A | `INFEASIBLE` / `NOT_ALLOWED` | Not allowed: it modifies traffic and/or requires secrets. R13D permits passive observation only. |

Если official-app control channel зашифрован TLS, extractor still can prove
only timing/length/cadence/endpoint-role evidence:
`TLS_RECORD_METADATA`, relative times, direction, frame length, repeat count,
cadence, whether client-to-device traffic continues after 36 s, and whether a
periodic class repeats with cadence `<36s`. Это достаточно, чтобы доказать
`traffic continuing past 36 s` или `periodicity <36 s`. Это не доказывает
message type/opcode, session renewal semantics, IDR request semantics, or
application payload meaning.

### Operator protocol

1. Operator selects a passive observation point and verifies it can see both
   phone/client and entrance-device endpoints.
2. start capture first: runner preflight must pass and capture begins before
   the operator opens camera in the official app.
3. Operator opens the entrance camera in the official app and holds rendering;
   hold it >=60-90 s after media-active if the app keeps rendering.
4. Operator writes marker file on the capture host with first field
   `media_active_epoch` seconds. This is a bounded file marker, not chat and not
   a network trigger.
5. Runner captures a bounded window: default `PRE_SECONDS=5`,
   `POST_SECONDS=90`, `HARD_CAP_SECONDS=125`, `MAX_FILE_MB=256`,
   `MAX_MESSAGE_ROWS=200`.
6. Runner stops capture, writes raw artifact outside Git with mode `600`,
   records SHA256/size/provenance, runs offline sanitisation/extraction on the
   capture host, and prints only scalar summary.
7. Raw PCAP is deleted unless `--retain-raw` is explicitly supplied by the
   operator. Retained raw artifacts remain outside Git, mode `600`, with SHA256
   recorded.

The runner is passive only: no injection, spoofing, traffic modification,
replay, MITM, door/gate action, helper media session, HA deploy, HA restart, or
OAuth refresh. If capture point/tooling/path is missing, it fails closed with
`CAPTURE_POINT_MISSING=FAILED_SAFE` or equivalent `FAILED_SAFE` status.

### Extraction fields

Per post-active message/family the extractor implements:

| Field | Meaning |
|---|---|
| `RELATIVE_TIME` | Seconds relative to operator `media_active_epoch`. |
| `DIRECTION` | `CLIENT_TO_DEVICE`, `DEVICE_TO_CLIENT`, or `UNKNOWN_DIRECTION` from configured endpoints. |
| `TRANSPORT_CLASS` | `UDP`, `TCP`, or `OTHER`. |
| `PROTOCOL_FAMILY` | `RTP`, `RTCP`, `STUN_TURN`, `TLS_RECORD_METADATA`, `TCP_METADATA`, `UDP_METADATA`, `CTPP`, `RTPC`, `PSEUDOTCP`, or safe dissector family. |
| `SAFE_MESSAGE_TYPE` | Structural class only, e.g. `RTP_PT_99`, `RTCP_PT_206`, `TLS_RECORD_METADATA`; no payload-derived secret. |
| `MESSAGE_LENGTH` | Frame or transport length scalar. |
| `REPEAT_COUNT` | Count in same safe class bucket. |
| `FIRST_AT` | First relative time in bucket. |
| `LAST_AT` | Last relative time in bucket. |
| `CADENCE` | Median inter-arrival for repeated bucket, or `NONE`. |

Candidate classes to inspect: `CTPP`, `RTPC`, `PSEUDOTCP_APPLICATION_TRAFFIC`,
`ACK_CONTROL`, `HEARTBEAT_PING`, `SESSION_RENEWAL`, `RECEIVER_FEEDBACK`,
`RTCP_FEEDBACK`, `KEYFRAME_IDR_REQUEST`, `STUN_TURN_KEEPALIVE`,
`REPEATING_EVENT_LT36S`, and `CLIENT_TO_DEVICE_AFTER_36S`.

RTP/H264 scalars implemented:
`VIDEO_PACKET_COUNT`, `VIDEO_PT_SET`, `VIDEO_SSRC_CHANGE_COUNT`,
`VIDEO_FIRST_TS`, `VIDEO_LAST_TS`, `SPS_COUNT`, `PPS_COUNT`, `IDR_COUNT`,
`IDR_TIMES`.

RTCP scalars implemented:
`RTCP_PRESENT`, `RTCP_DIRECTION_SET`, `RTCP_PACKET_TYPES`, `RTCP_FIRST_AT`,
`RTCP_LAST_AT`, `RTCP_REPEAT_COUNT`.

### Privacy gate

Repository evidence may contain only sanitized scalars: counts, lengths,
relative timings, cadence, direction, protocol family, safe structural message
classes, SHA256, file sizes, and provenance. It must not contain raw RTP/H264,
raw application payloads, plaintext secrets, OAuth/access/refresh material, ICE
username/password, device/account identifiers, session identifiers, endpoint
material beyond proof need, or packet dumps. Summary template intentionally
uses `PRIVACY_GATE=SCALAR_ONLY_NO_PAYLOAD_NO_IDENTIFIERS`.

Raw artifacts policy: outside Git, mode `600`, SHA256 recorded, size recorded,
deleted by default or retained only by explicit operator flag.

Per-artifact provenance recorded:
capture tool/version, extraction tool/version, interface/point, start/end UTC,
start/end monotonic, filter expression, artifact SHA256, artifact size.

### Comparison template

Future comparison against our helper uses this scalar-only template:

| EVENT | OFFICIAL_APP_SENDS | OUR_HELPER_SENDS | CADENCE | CONTINUES_AFTER_36S | MEDIA_LIFETIME_CANDIDATE | IDR_FEEDBACK_CANDIDATE |
|---|---|---|---|---|---|---|
| `CTPP` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `RTPC` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `PSEUDOTCP_APPLICATION_TRAFFIC` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `ACK_CONTROL` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `HEARTBEAT_PING` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `SESSION_RENEWAL` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `RECEIVER_FEEDBACK` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `RTCP_FEEDBACK` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `KEYFRAME_IDR_REQUEST` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `STUN_TURN_KEEPALIVE` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `NOT_PROVEN` | `NOT_PROVEN` |
| `REPEATING_EVENT_LT36S` | `UNRESOLVED` | `UNRESOLVED` | `<36s` if proven | `UNRESOLVED` | `PLAUSIBLE` when official-only | `NOT_PROVEN` |
| `CLIENT_TO_DEVICE_AFTER_36S` | `UNRESOLVED` | `UNRESOLVED` | `UNRESOLVED` | `true` if proven | `PLAUSIBLE` when official-only | `NOT_PROVEN` |

Closing verdict fields:

| Verdict | Values |
|---|---|
| `MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D1` | `PROVEN`, `PLAUSIBLE`, `REJECTED`, `UNRESOLVED` |
| `MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D2` | `PROVEN`, `PLAUSIBLE`, `REJECTED`, `UNRESOLVED` |
| `COMMON_D1_D2_CAUSE` | `PROVEN`, `PLAUSIBLE`, `REJECTED`, `UNRESOLVED` |

Current R13D state: `COMELIT_OFFICIAL_APP_LIVE=NOT_RUN`,
`OUR_HELPER_MEDIA_SESSION=NOT_RUN`, `RTCP_ANALYSIS_READY=true`,
`H264_IDR_TIMING_ANALYSIS_READY=true`, `COMPARISON_TEMPLATE_READY=true`.

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

## R13B evidence enrichment

`BASE_SHA=b9934dd83b17158bac213efcc18c5ec6b4b66e87`. This iteration stayed
offline: no Comelit live session, HA deploy/restart, OAuth, Door/Gate action,
keepalive implementation, IDR-request implementation, production component edit,
native binary execution, or network I/O was performed.

### HA 2026.9.1 stream evidence

`HA_UPSTREAM_LOCAL_MATCHES=PASS`: the staged `ha-2026.9.1` files match the
orchestrator manifest SHA256 values for `hls.py`, `fmp4utils.py`, `worker.py`,
`core.py`, `const.py`, and `__init__.py`. The previous `stream/worker.py`,
`stream/core.py`, `stream/const.py`, and `stream/__init__.py` staged copies are
byte-identical to the new tag copies. `PROVEN_STATIC`: `hls.py` imports only the
local stream closure needed here: `.const`, `.core`, and `.fmp4utils`.

`PROVEN_STATIC`: default LL-HLS setup in `__init__.py:277-287` sets
`ll_hls=True`, `min_segment_duration=segment_duration - 0.1`, part duration from
`CONF_PART_DURATION`, advance-part-limit from `max(int(3 / part_duration), 3)`,
and part timeout as `2 * part_duration`. `const.py:28-29` defines non-LL target
segment duration `2.0` and adjuster `0.1`; the R13B LL-HLS runtime defaults
remain the HA config defaults already captured in R13 (`segment_duration=6`,
`part_duration=1`).

`PROVEN_STATIC`: HA-style fMP4 muxing uses `movflags` containing `empty_moov`,
`default_base_moof`, `frag_discont`, `negative_cts_offsets`, `skip_trailer`, and
`delay_moov`; LL-HLS adds `frag_duration=int(part_target_duration * 9e5)`
(`worker.py:183-243`). A second keyframe at/after `min_segment_duration` is
required only to close the first full segment (`worker.py:290-299`). It is not a
static precondition for the first part: `check_flush_part()` creates a `Segment`
when `delay_moov` first moves the buffer, then flushes the moof (`worker.py:331-343`),
and `flush()` calls `Segment.async_add_part(Part(...))` (`worker.py:345-423`).

`PROVEN_STATIC`: open LL-HLS segments can be exposed in playlists. The playlist
renderer includes the most recent segment even when incomplete (`hls.py:173-180`),
renders parts for the last segment (`hls.py:235-240`), and `Segment.render_hls()`
adds a preload hint for the next part of an incomplete segment (`core.py:198-220`).

### Run5 RTP offline probe

`DATAGRAM_FRAMING=PROVEN_STATIC`: the P105 runner writes each UDP payload as a
2-byte big-endian length followed by the payload (`ct120_run_p105_entrance_media_live.sh:426-436`).
The same runner's depacketizer reads that exact framing (`:470-480`). Therefore
the staged `video.rtpdatagrams` file is length-prefixed RTP payloads, not raw
concatenated UDP payloads and not pcap.

`PROVEN_OFFLINE`: `/tmp/comelit-r13-pyav/bin/python
safety-poc/research/media/v1/entrance_p116_r13b_offline_hls_probe.py --artifact
.p116-evidence/private/p115-run5/video.rtpdatagrams` used PyAV `17.0.1` with
libavformat `(62, 3, 100)`. It parsed `1538` PT99 RTP datagrams into `745` H264
access units, with `SPS_COUNT=9`, `PPS_COUNT=9`, and `IDR_ACCESS_UNITS=2`.
The first captured access unit is not an IDR, so the probe starts muxing at the
first IDR, matching HA worker behavior that advances to the first video keyframe
before muxing (`worker.py:690-710`, `:724-738`).

`PROVEN_OFFLINE`: V1, the raw run5 keyframe cadence, produced an HA-style fMP4
file: `MUX_STATUS=PASS`, `MP4_INIT=YES`, `FIRST_MOOF=YES`, `FIRST_MDAT=YES`,
`FIRST_PART_CREATED=YES`, `FIRST_PART_HAS_KEYFRAME=YES`,
`FFPROBE_CODEC=h264`, `FFPROBE_EXTRADATA_SIZE=44`, `FFPROBE_TIME_BASE=1/90000`,
`FIRST_KEYFRAME_DTS_PTS_VALID=YES`, `NEXT_VIDEO_PACKET_DTS_PTS_VALID=YES`,
`TIMESTAMP_VALIDATOR_DROPS=16`. The drop count is from the socket-free RTP
timestamp validator equivalent in the probe; it reflects duplicate/non-advancing
access-unit timestamps before muxing and did not prevent first part creation.

`PROVEN_OFFLINE`: V2, the same stream with one injected second IDR, also produced
the first part: `MUX_STATUS=PASS`, `MP4_INIT=YES`, `FIRST_MOOF=YES`,
`FIRST_MDAT=YES`, `FIRST_PART_CREATED=YES`, `FIRST_PART_HAS_KEYFRAME=YES`,
`FFPROBE_CODEC=h264`, `FFPROBE_EXTRADATA_SIZE=44`, `FFPROBE_TIME_BASE=1/90000`,
`FIRST_KEYFRAME_DTS_PTS_VALID=YES`, `NEXT_VIDEO_PACKET_DTS_PTS_VALID=YES`,
`TIMESTAMP_VALIDATOR_DROPS=41`. Because V1 already creates the first part, the
injected second IDR is not the decisive variable for first-part creation.

`PROVEN_STATIC`: V3 video-only and V4 production SDP with advertised silent PCMA
do not change the HA output mux dependency for video. `const.py:19` supports
only `{"aac", "mp3"}` audio, and `worker.py:650-657` sets unsupported or
profile-less audio streams to `None`. Therefore PCMA does not block video muxing
in this HA path. R13B does not prove whether an SDP-level silent PCMA m-line can
affect FFmpeg's initial demux wait before video packets; the raw audio artifact
was not staged and no socket replay was used.

Scalar D2 closure:

```text
D2_FIRST_LL_HLS_PART_CREATED=YES
FIRST_PART_HAS_KEYFRAME=YES
SECOND_IDR_REQUIRED_FOR_FIRST_PART=NO
SECOND_IDR_REQUIRED_FOR_SEGMENT_CLOSE=PROVEN_STATIC
VIDEO_CODEC_EXTRADATA_AVAILABLE_BEFORE_MUX=YES
VIDEO_TIME_BASE=1/90000
FIRST_KEYFRAME_DTS_PTS_VALID=YES
NEXT_VIDEO_PACKET_DTS_PTS_VALID=YES
TIMESTAMP_VALIDATOR_DROPS=16
MUX_FIRST_KEYFRAME=PASS
MP4_INIT_WRITTEN=YES
FIRST_MOOF_WRITTEN=YES
FIRST_SEGMENT_OBJECT_CREATED=YES
FIRST_PART_CREATED=YES
HLS_PLAYLIST_CAN_EXPOSE_OPEN_SEGMENT=YES
```

`D2_ROOT_CAUSE=NOT_SECOND_IDR_FOR_FIRST_PART`: R13B proves that the staged run5
RTP can create the first LL-HLS part under PyAV 17/FFmpeg 7.1-line fMP4 muxing
without an injected second IDR. The remaining unresolved D2 causes are not input
availability gates lifted by R13B; they concern live timing/lifecycle, possible
pre-keyframe demux wait behavior, or official-client feedback that is not present
in the staged offline media.

### D1 static-only closure

`OUR_RTP_STOP_AROUND_36S=PROVEN_FOR_3_P116_SESSIONS`,
`PERIODIC_CLIENT_TRAFFIC_REQUIRED=NOT_PROVEN`, and
`KEEPALIVE_MESSAGE_TYPE=NOT_PROVEN` remain unchanged. The static outbound
inventory after `P80_MEDIA_ACTIVE=true` is complete for this repo:

`PROVEN_STATIC`: media activation emits stdout markers and enables forwarding
only (`entrance_p80_ha_media_runtime_transform.py:583-608`).

`PROVEN_STATIC`: accepted PT99/PT8 RTP is sent helper -> HA loopback UDP via
`sendto()` (`:484-545`), then bounded scalar telemetry/progress markers are
printed (`:545-575`).

`PROVEN_STATIC`: non-media data after media-active continues through the
inherited readable branch/PseudoTCP path and prints only scalar receive-event
size markers in this transform (`:612-620`). This is input-driven, not a proven
client keepalive loop.

`PROVEN_STATIC`: the only post-000A/001A timers found in the generated media
gate are pre/media-start fail-closed 3-second ACK timers
(`entrance_p97_complete_post_000a_ack_cycle_transform.py:204-227`;
`entrance_p92_wait_device_000a_before_001a_transform.py:121-133`).

Minimal official-app trace definition for the unresolved D1 question:
capture from 5 seconds before media-active until at least 60 seconds after,
both directions, with packet timing, direction, endpoint roles, protocol class
(`CTPP`, `RTPC`, `PseudoTCP`, `STUN/TURN`, `RTP`, `RTCP`), safe message
type/opcode, body length, and H264 scalar counts (`SPS`, `PPS`, `IDR`). Exclude
OAuth tokens, ICE credentials, raw media payloads, raw SDP credentials, endpoint
addresses beyond anonymized roles, channel/session identifiers beyond
redacted/stable role labels, and any JPEG/video/audio publication.

### Redaction audit follow-up

`SAFE_REDACTION_PROPOSAL=PROVEN_STATIC_PROPOSAL_ONLY`: extend the safe marker
value regex with bounded enums plus anchored shapes for structured multi-token
values:

```text
^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|FATAL|NONE|HOME_ASSISTANT|STATE_SCOPED_STRUCTURAL|NOT_MATCHED|ACTIVE|PREACTIVE|DISCONNECTED|GATHERING|CONNECTING|CONNECTED|FAILED|[0-9]{1,20}|[0-9]{1,3}(?:,[0-9]{1,3}){0,127}|[0-9]{1,5} OPEN=(?:true|false) ACK=(?:true|false)|FAIL LEN=[0-9]{1,5})$
```

The multi-token additions are deliberately anchored to the known shapes
`PSEUDOTCP_APP_RX_EVENT="%d OPEN=%s ACK=%s"` and
`PSEUDOTCP_NOTIFY_PACKET=FAIL LEN=24`; they are not catch-all text patterns.
Identifier-like, token-like, address-like, session-like, SDP-like, and free-text
values remain redacted. `NUMERIC_ALLOWANCE_RESIDUAL_RISK=OBSERVATION_ONLY`:
the numeric scalar allowance `[0-9]{1,20}` plus up-to-128-element numeric lists
is pre-existing in `custom_components/comelit/media_transport.py:41-45`, not
introduced by R13/R13B; whether that should be narrowed is a separate exposure
question and was not changed here.
