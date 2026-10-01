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

Every binary WebSocket message is one access unit. Protocol v2 separates the
camera media clock from Home Assistant receive/send monotonic clocks:

```text
offset  size  field
0       1     uint8   protocol_version = 2
1       1     uint8   flags: bit0=KEY, bit1=DELTA, bit2=PTS_VALID
2       2     uint16  reserved = 0
4       4     uint32  sequence
8       8     uint64  media_pts_us
16      8     uint64  source_elapsed_us
24      8     uint64  send_elapsed_us
32      4     uint32  payload_length
36      N     bytes   H.264 Annex-B access unit
```

`source_elapsed_us` is measured from the first H.264 access unit received by
the HA adapter. `send_elapsed_us` is measured from the first binary send. Both
use the HA monotonic clock and therefore require no wall-clock synchronization
with the phone.

Constants:

```text
WEBCODECS_HEADER_BYTES=36
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
source_open
source_packet
hello
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
source_open
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

OBSERVED: Telegram Android WebView supports the required WebCodecs APIs and
decoded a real synthetic Annex-B H.264 frame during the manual capability
canary. The first 1.7.24 ordinary-camera live run also decoded 599/599 H.264
access units from `camera.dvor_1` with zero sequence gaps and visually smooth
playback.

The client reports `codedWidth`/`codedHeight`, `visibleRect`, and
`displayWidth`/`displayHeight` separately. It does not enforce exact dimensions.

## Measurement Definitions

The tab measures network/transport/decoder behavior, not physical
glass-to-glass latency.

The 1.7.24 field named `ACCUMULATED_LAG` mixed camera/PyAV PTS progression
with browser arrival progression and therefore was not a valid WSS/CloudPub
backlog metric. The first live run reported roughly 15 seconds in that field
while simultaneously showing 599/599 decoded frames, zero sequence gaps, no
backlog stop, and visually smooth playback. That value is retained only as
historical evidence and is replaced by protocol-v2 drift domains.

Protocol v2 reports:

```text
media_elapsed =
    current_media_pts - first_media_pts

source_elapsed =
    current_source_elapsed - first_source_elapsed

send_elapsed =
    current_send_elapsed - first_send_elapsed

arrival_elapsed =
    client_receive_time - first_client_receive_time

SOURCE_PTS_DRIFT =
    source_elapsed - media_elapsed

SERVER_QUEUE_DRIFT =
    send_elapsed - source_elapsed

TRANSPORT_DRIFT =
    arrival_elapsed - send_elapsed
```

`SOURCE_PTS_DRIFT` shows divergence between camera media PTS and the HA
monotonic receive cadence.

`SERVER_QUEUE_DRIFT` shows relative growth between receipt of an AU by HA and
the point at which that AU begins its WebSocket send.

`TRANSPORT_DRIFT` is the metric relevant to WSS/CloudPub accumulation. It
compares client receive progression with the HA send progression and requires
no synchronized wall clocks.

No hard latency threshold is encoded in the canary. Functional PASS is reported
separately from `TRANSPORT_BACKLOG_OBSERVED`; the latter remains `unknown`
until the measured drift is interpreted after a production run.

`DECODE_*` measures from the timestamp immediately before `VideoDecoder.decode`
for an access unit to the corresponding `VideoDecoder` output callback. The
client pairs decode calls and output callbacks with a FIFO because this canary
expects decoder output in submitted access-unit order.

`RECEIVE_TO_DRAW_*` measures the broader client-side post-receive contribution
from binary message receipt to `VideoFrame` draw callback.

Startup milestones are now distinct:

- `SOURCE_OPEN_MS`: client-observed receipt of the control marker emitted
  after `H264AccessUnitSource.open()` succeeds;
- `FIRST_SOURCE_PACKET_MS`: client-observed receipt of the first real H.264 AU
  marker;
- `FIRST_BINARY_MS`: first binary AU received by the browser;
- `FIRST_DECODED_FRAME_MS`: first `VideoFrame` output.

The block also reports `SOURCE_STARTUP_MS`,
`SOURCE_PACKET_TO_BINARY_MS`, and `BINARY_TO_DECODE_MS`.

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


## 1.7.24 Production Evidence And Corrective

OBSERVED on 2026-10-01, first bounded live run:

```text
ENTITY_ID=camera.dvor_1
RESULT=PASS
ZERO_TRANSCODE=true
UNITS_RECEIVED=599
FRAMES_DECODED=599
KEYFRAMES_RECEIVED=12
SEQUENCE_GAPS=0
WS_CONNECT_MS=156.3
FIRST_DECODED_FRAME_MS=5784.6
DECODE_P50_MS=5.3
DECODE_P95_MS=16.4
MAX_DECODE_QUEUE=14
BACKLOG_STOP=false
DROPPED_UNITS=0
```

User observation: the video appeared quickly after source startup and played
smoothly without visible stutter.

The intended `camera.parking_6048` target was not actually selected. The run
used `camera.dvor_1` because the WebCodecs viewer DOM was being rebuilt during
periodic Mini App HA-state refresh. That rebuild closed the select dropdown and
reset result scrolling.

PROVEN_STATIC root cause: `host.js` refreshes HA state periodically;
`comelit-card` forwards `hass` and `cameras` into the WebCodecs viewer; the
1.7.24 viewer setters performed a full `shadowRoot.innerHTML` render while
idle. The corrective keeps the DOM stable for semantically unchanged camera
lists, preserves selection/result scroll/last frame across background refresh,
and updates controls/counters in place.

The 1.7.24 `ACCUMULATED_LAG≈15s` observation is not interpreted as network
delay because its definition mixed camera PTS with browser arrival time. The
v2 timing fields above replace that ambiguity before the next production
architecture decision.

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

- Corrected protocol-v2 `TRANSPORT_DRIFT` behavior on the owner's phone/network.
- A clean 60-second canary with the intended `camera.parking_6048` target.
- Whether this path should replace any production playback path.
