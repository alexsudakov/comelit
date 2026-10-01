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

The ordinary-camera transport has now been live-validated. The next bounded
production target is the Entrance intercom camera:

```text
camera.comelit_entrance
```

Procedure:

1. Owner opens the Telegram Mini App.
2. Owner opens `WebCodecs`.
3. Owner selects `Comelit — Камера подъезда`.
4. Owner presses `Запустить тест`.
5. One run lasts 60 seconds or until explicit `Остановить`.
6. No automatic retry is part of the canary.
7. No Door or Gate action is part of the canary.

PASS has no invented latency threshold. Minimum functional PASS criteria:

- the manager-owned on-demand Entrance media lifecycle starts once;
- WSS path works end to end;
- `VideoDecoder` produces at least one `VideoFrame`;
- no unexplained `SEQUENCE_GAPS`;
- decoder queue has no irreversible growth;
- Stop/expiry closes the local source and releases the manager lease;
- the manager then performs its existing media teardown/listener-restore
  lifecycle;
- stop reason is clean: `manual_stop`, `duration_60s`, `duration_limit`, or
  `source_eof`.

For the Entrance target the canary block additionally reports:

```text
SOURCE_KIND=comelit_entrance_rtp
INTERCOM_MEDIA_READY_MS=...
INTERCOM_MEDIA_READY_SERVER_MS=...
INTERCOM_MEDIA_TO_SOURCE_OPEN_MS=...
COMELIT_ENTRANCE_OPEN=true
COMELIT_MEDIA_STARTED=true
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

`INTERCOM_MEDIA_READY` is the boundary after
`ComelitMediaSessionManager.async_acquire(panel="entrance")` has returned
successfully and the existing transport reports both active media and a ready
local SDP. It is therefore the useful boundary for separating proprietary
Comelit bootstrap time from the local SDP/WSS/WebCodecs portion.

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
idle. The 1.7.25 corrective keeps the DOM stable for semantically unchanged
camera lists, preserves selection/result scroll/last frame across background
refresh, and updates controls/counters in place.

The 1.7.24 `ACCUMULATED_LAG≈15s` observation is not interpreted as network
delay because its definition mixed camera PTS with browser arrival time.

## 1.7.25 Parking Production Evidence

OBSERVED on 2026-10-01, bounded live run on the intended ordinary camera:

```text
ENTITY_ID=camera.parking_6048
RESULT=PASS
FUNCTIONAL_PASS=true
DURATION_S=55.9
CODEC=avc1.42002A
ZERO_TRANSCODE=true

WS_CONNECT_MS=182.8
SOURCE_OPEN_MS=4793.7
FIRST_SOURCE_PACKET_MS=4810.6
FIRST_BINARY_MS=4935.8
FIRST_DECODED_FRAME_MS=5088.5
SOURCE_STARTUP_MS=16.9
SOURCE_PACKET_TO_BINARY_MS=125.2
BINARY_TO_DECODE_MS=152.7

UNITS_RECEIVED=1404
FRAMES_DECODED=1404
KEYFRAMES_RECEIVED=21
SEQUENCE_GAPS=0

DECODE_P50_MS=131.4
DECODE_P95_MS=247.7
DECODE_MAX_MS=408.8

MAX_DECODE_QUEUE=34
SERVER_QUEUE_DRIFT_MS=-17.6
SERVER_QUEUE_DRIFT_P95_MS=-16.7
SERVER_QUEUE_DRIFT_MAX_MS=4.6
TRANSPORT_DRIFT_MS=-119.6
TRANSPORT_DRIFT_P95_MS=296.7
TRANSPORT_DRIFT_MAX_MS=537.1

CODED_SIZE=1920x1088
VISIBLE_SIZE=1920x1080
DISPLAY_SIZE=1920x1080
BACKLOG_STOP=false
DROPPED_UNITS=0
```

User observation: `Паркинг 6048` remained selected, the image appeared quickly
after source startup, and playback was smooth without visible stutter.

Interpretation:

- 1404/1404 decoded access units, zero gaps and zero drops prove the functional
  WSS/WebCodecs delivery path for a real 1080p H.264 camera.
- The roughly 4.6–4.8 second startup cost occurred before the first source AU;
  it was not caused by WebCodecs or CloudPub/WSS.
- `TRANSPORT_DRIFT` did not show irreversible positive growth over the run,
  while the visual stream remained smooth. The existing HTTPS/WSS ingress is
  therefore accepted as a viable low-latency transport candidate for the
  Entrance experiment.
- `SOURCE_PTS_DRIFT` remains a camera-clock diagnostic and is not used as a
  network-delay verdict.

## Direct Entrance WebCodecs Path

PROVEN_STATIC / implementation candidate:

```text
explicit Mini App Start
  -> existing Mini App session/auth boundary
  -> one WebCodecs session registry lease
  -> ComelitMediaSessionManager.async_acquire(
       panel="entrance",
       reason="miniapp_webcodecs"
     )
  -> existing listener pause / exclusive on-demand media bootstrap
  -> existing ComelitEntranceMediaTransport
  -> native helper PT99 H.264 RTP
  -> existing H264RecoveryRtpShim
  -> local SDP (/run/comelit-media/local-rtp.sdp)
  -> PyAV SDP/RTP demux only
  -> H.264 Annex-B access units
  -> bounded binary WSS protocol v2
  -> Telegram Android WebView VideoDecoder
  -> canvas
```

The direct Entrance WebCodecs path deliberately does **not** call
`camera.comelit_entrance.async_create_stream()` and does not construct a Home
Assistant `Stream`. Consequently this experiment does not require HLS,
go2rtc, MSE, WebRTC, fMP4, or video transcoding.

The native helper and recovery shim are not modified. The WebCodecs source
attaches to the already-established HA-facing local RTP/SDP boundary, so the
existing recovery-point behavior remains authoritative.

PyAV is used only as an SDP/RTP demux and H.264 packet/access-unit boundary.
There is no `decode()`, encode, scale, filter, or video re-encode branch.

The local SDP path never leaves the server. The browser receives only bounded
control metadata and H.264 access units. Source URLs, local filesystem paths,
credentials, tokens, SDP text, RTP identifiers and raw protocol authorization
material are not serialized to the Mini App.

### Lifecycle and safety

The Entrance target is admitted only for the exact Comelit Entrance camera
unique id. Gate/intercom alternatives remain rejected.

The path fails closed if the on-demand manager is not inactive. It does not
start a second session on top of another on-demand consumer and it does not
reuse an attached inbound Ring transaction in this phase.

One explicit Start performs at most one manager acquire. There is no automatic
retry.

Cleanup order is:

```text
WebSocket stop/close/timeout/error
  -> cancel and close PyAV local SDP source
  -> release miniapp_webcodecs manager lease
  -> existing manager teardown
  -> existing listener resume contract
```

The existing manager remains authoritative for its 600-second absolute hard
ceiling. The Mini App canary is shorter (60 seconds), so it cannot extend that
deadline.

Door and Gate actions are outside this path and remain zero.

## Deferred

- Audio in the WebCodecs path.
- Containers and muxed A/V.
- GOP-aware dropping.
- Arbitrary delta-frame dropping.
- Gate/intercom camera target.
- Attached inbound Ring reuse by the WebCodecs tab.
- Door/Gate actions.
## 1.7.26 live-promotion boundary

The original offline phase intentionally did not claim real Telegram WebCodecs
acceptance, measured proprietary bootstrap timing, or production teardown.
Those were live-only acceptance questions. The subsequent 1.7.26 live
acceptance closed the promotion decision before the production switch below;
the earlier offline limitations remain provenance, not current blockers.

## Production Entrance viewer after 1.7.26

The 1.7.26 Entrance canary promoted the already-implemented direct
WebCodecs/WSS transport to the primary Telegram Mini App viewer in the next
production patch.

The normal Entrance viewer now uses:

```text
explicit "Показать камеру"
  -> embedded WebCodecs viewer
  -> existing /webcodecs endpoint
  -> existing ComelitMediaSessionManager
  -> existing native Entrance media + H264 recovery
  -> WSS protocol v2
  -> VideoDecoder + canvas
```

The legacy HA/HLS viewer remains a fallback only. A bounded startup/decoder/WSS
failure closes the WebCodecs client first; the HLS endpoint then waits for the
`miniapp_webcodecs` ownership to reach a safe inactive state before requesting
HA HLS. This barrier is local cleanup synchronization, not an automatic
Comelit packet/session retry. If cleanup enters the manager error state or does
not finish within the bound, HLS fails closed rather than creating overlapping
Comelit media ownership.

The embedded production player has a 15-second first-frame startup deadline.
The 600-second Entrance media hard ceiling remains authoritative and is not
converted into an automatic HLS restart.

The diagnostic WebCodecs tab and canary UI are retained for future controlled
testing but are hidden by default. They are exposed only with the explicit Mini
App URL query flag:

```text
webcodecs_debug=1
```

Without that flag the normal surface remains exactly:

```text
[ Домофон ] [ Видеонаблюдение ]
```

Door and Gate semantics are unchanged.
