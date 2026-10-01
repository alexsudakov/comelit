# Mini App WebCodecs live tab

Status: experimental contract  
Date: 2026-10-01  
Scope: Telegram Mini App only

## Evidence labels

- PROVEN_STATIC: source inspection or static tests.
- PROVEN_OFFLINE: pytest / node / browser-mock tests in this repository.
- OBSERVED: evidence from a real runtime canary.
- NOT_PROVEN: intentionally not proven by offline tests.
- UNVERIFIED: not checked in this phase.

## Surface

PROVEN_STATIC: the shared Comelit card renders the WebCodecs tab only when:

```text
config.webcodecs && config.webcodecs.enabled === true
```

The flag is passed by:

```text
custom_components/comelit/frontend/miniapp/host.js
```

Default Home Assistant / Lovelace usage keeps exactly:

```text
[ Домофон ] [ Видеонаблюдение ]
```

The Mini App loads the implementation from:

```text
/api/comelit/frontend/miniapp/webcodecs.js?v=1.7.5
```

Opening the tab does not connect, resolve a source, or open a camera. The stream
starts only after the user presses `Запустить тест`.

## Endpoint

```text
GET /api/comelit/miniapp/camera/{entity_id}/webcodecs
name = api:comelit:miniapp:camera_webcodecs
```

PROVEN_OFFLINE: Mini App session failures return `403` before WebSocket upgrade.
Closed pre-upgrade JSON errors use `409`:

```text
camera_not_allowed
intercom_camera_not_allowed
camera_unavailable
```

After upgrade, the only accepted first text command is:

```json
{"type":"webcodecs","value":"h264"}
```

Invalid or missing commands close with:

```text
invalid_webcodecs_command
```

The camera source is resolved only after this command with
`await camera.stream_source()`. Source URLs and credentials remain server-side.

## Source Strategy

Chosen strategy: `pyav`.

PROVEN_STATIC: `custom_components/comelit/manifest.json` already declares the
Home Assistant `stream` dependency, and HA stream installs the runtime that
provides `av`. The WebCodecs module imports `av` lazily inside the source
adapter, so HA startup does not depend on importing PyAV in this integration.

PROVEN_STATIC / PROVEN_OFFLINE: the adapter demuxes H.264 packets and converts
bitstream representation only. It performs no decode, encode, re-encode,
scaling, filter graph, fMP4, MSE, HLS, or WebRTC work in this path.

UNVERIFIED: availability of `av` inside the owner's production HA runtime was
not checked in this offline phase. Runtime absence degrades to:

```text
source_dependency_missing
```

Open/source failures degrade to:

```text
source_open_failed
source_not_h264_rtsp
```

## Binary Framing

Every binary WebSocket message is one access unit:

```text
offset  size  field
0       1     uint8   protocol_version = 1
1       1     uint8   flags: bit0=KEY, bit1=DELTA, bit2=PTS_VALID
2       2     uint16  reserved = 0
4       4     uint32  sequence
8       8     uint64  media_pts_us
16      4     uint32  payload_length
20      N     bytes   H.264 Annex-B access unit
```

Constants:

```text
WEBCODECS_HEADER_BYTES=20
WEBCODECS_MAX_UNIT_BYTES=1048576
WEBCODECS_MAX_QUEUE_UNITS=48
WEBCODECS_MAX_QUEUE_BYTES=3145728
WEBCODECS_MAX_SESSION_SECONDS=120
WEBCODECS_MAX_SESSIONS=4
```

PROVEN_OFFLINE: helpers reject wrong version, nonzero reserved, KEY and DELTA
both set, missing frame type, length mismatch, truncation, and oversized
payloads.

## Messages And Events

Text messages from server to browser are closed:

```text
hello
source
error
eos
```

`hello` fields:

```text
type
protocol
entity_id
codec
max_unit_bytes
session_max_seconds
zero_transcode
```

The codec is derived from SPS as `avc1.PPCCLL`. `zero_transcode: true` is a
server assertion tied to this copy-only adapter: the WebCodecs path has no
server-side decode, encode, re-encode, filtering, scaling, container muxing, or
transcode branch. The browser reports `ZERO_TRANSCODE` from `hello` and uses
`n/a` if an older server omits the field.

HA log events are closed:

```text
session_open
source_resolved
first_source_packet
first_binary
unit_too_large
backlog_exceeded
session_limit
source_eof
session_close
source_open_failed
```

Summary reasons are closed:

```text
client_close
duration_limit
source_eof
source_open_failed
backlog_exceeded
session_limit
cancelled
```

No free-text source, URL, host, port, credential, cookie, token, Telegram
`initData`, SDP, candidate, or media URL is logged or serialized.

## Annex-B Handling

PROVEN_OFFLINE:

- Annex-B input with start codes is preserved.
- AVCC input with 4-byte big-endian NAL lengths is repackaged to Annex-B.
- `AVCDecoderConfigurationRecord` extradata is parsed for SPS/PPS.
- Every keyframe AU is sent with SPS/PPS in the same payload when absent.
- SPS bytes derive the `avc1.PPCCLL` codec string.

## Browser Decode

The client uses:

```text
VideoDecoder
EncodedVideoChunk
optimizeForLatency: true
canvas drawImage(VideoFrame)
```

There is no `<video>`, MediaSource, hls.js, WebRTC, container parser, or
description blob in the WebCodecs tab.

PROVEN_OFFLINE: a Playwright mock verifies support probing, binary frame
parsing, `EncodedVideoChunk` creation, decoder output drawing to canvas, frame
close, cleanup on Stop, and final canary block generation.

NOT_PROVEN: real H.264 WebCodecs decode on Telegram Android WebView. That is
the purpose of the protected production canary.

The client reports `codedWidth`/`codedHeight`, `visibleRect`, and
`displayWidth`/`displayHeight` separately. It does not enforce exact dimensions.

## Measurement Definitions

The tab measures network/transport/decoder behavior, not physical
glass-to-glass latency.

`ACCUMULATED_LAG` uses only the browser `performance.now()` time base plus media
PTS deltas:

```text
arrival_elapsed = client_receive_time - first_client_receive_time
media_elapsed   = current_media_pts - first_media_pts
lag             = arrival_elapsed - media_elapsed
```

If PTS is invalid, accumulated lag is `n/a`.

`DECODE_*` measures from the timestamp immediately before `VideoDecoder.decode`
for an access unit to the corresponding `VideoDecoder` output callback. The
client pairs decode calls and output callbacks with a FIFO because this canary
expects decoder output in submitted access-unit order; it does not report the
old synchronous `decode()` call overhead.

`RECEIVE_TO_DRAW_*` measures the broader client-side post-receive contribution
from binary message receipt to `VideoFrame` draw callback.

`SOURCE_OPEN_MS` and `FIRST_SOURCE_PACKET_MS` are equivalent in the current
protocol by construction: the server sends `hello` and `source` only when the
first H.264 access unit is available, then immediately sends that first binary
message. No separate source-open marker exists yet.

## Canary Protocol

Documented first target:

```text
camera.parking_6048
```

This target is documentation only and is not hardcoded in implementation.

Procedure:

1. Owner opens the Telegram Mini App.
2. Owner opens `WebCodecs`.
3. Owner selects `camera.parking_6048`.
4. Owner presses `Запустить тест`.
5. One run lasts 60 seconds or until explicit `Остановить`.
6. No retry is part of the canary.

PASS has no invented latency threshold. Minimum PASS criteria:

- WSS path works end to end.
- `VideoDecoder` produces at least one `VideoFrame`.
- No unexplained `SEQUENCE_GAPS`.
- Decoder queue has no irreversible growth.
- Stop/expiry completes cleanup.
- Stop reason is clean: `manual_stop`, `duration_60s`, `duration_limit`, or
  `source_eof`.

The canary block is printed in the UI and `console.log` once:

```text
=== COMELIT MINIAPP WEBCODECS LIVE CANARY ===
RESULT=PASS|FAIL
ENTITY_ID=<safe entity id>
...
COMELIT_ENTRANCE_OPEN=false
COMELIT_MEDIA_STARTED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## Deferred

- Audio.
- Containers and muxed A/V.
- GOP-aware dropping.
- Arbitrary delta-frame dropping.
- Comelit Entrance.
- Gate/intercom camera targets.
- Door/Gate actions.
- Production path replacement for MSE/WebRTC/HLS.

## Not Proven Offline

- Real Telegram Android WebView H.264 decode.
- Real camera compatibility with Annex-B WebCodecs input.
- PyAV availability in the owner production HA runtime.
- Actual end-to-end WSS performance over the owner's phone/network.
- Whether this path should replace any production playback path.
