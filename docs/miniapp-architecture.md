# Comelit Telegram Mini App architecture

Status: embedded implementation baseline  
Date: 2026-09-27  
Repository: `alexsudakov/comelit`

## 1. Ownership boundary

The Telegram Mini App is a Comelit product surface and lives entirely inside the
Home Assistant custom integration.

Production runtime:

```text
Telegram Mini App
        |
        | HTTPS
        v
Home Assistant HTTP server
        |
        v
custom_components/comelit
        |
        +-- Mini App auth/session/views
        +-- shared comelit-card.js
        +-- HA state / registry / services / camera stream
        |
        v
Comelit runtime
```

There is no standalone Comelit application server, FastAPI service, Docker
runtime, Home Assistant Long-Lived Access Token, or Home Assistant REST/WebSocket
client in the Mini App path.

`llm-home-assistant-stack`, CT120 and CT123 are not production dependencies for
the Mini App.

## 2. One UI artifact

Both Lovelace and Telegram reuse:

```text
custom_components/comelit/frontend/comelit-card.js
```

Telegram hosts the same custom element from:

```text
custom_components/comelit/miniapp/index.html
custom_components/comelit/frontend/miniapp/host.js
custom_components/comelit/frontend/miniapp/styles.css
```

The Telegram host implements only the narrow `hass` surface already consumed
by the shared card:

```text
hass.states
hass.callWS(config/entity_registry/list)
hass.callWS(config/label_registry/list)
hass.callService(button, press, ...)
window.loadCardHelpers().createCardElement(picture-entity)
```

The host adapter does not expose a general Home Assistant API.

## 3. Home Assistant HTTP boundary

The integration registers public Home Assistant views under:

```text
/api/comelit/miniapp
/api/comelit/miniapp/session
/api/comelit/miniapp/bootstrap
/api/comelit/miniapp/state
/api/comelit/miniapp/door/{entrance|gate}
/api/comelit/miniapp/camera/{entity_id}/stream
```

The index and session-establishment endpoints are intentionally reachable
without Home Assistant user authentication because Telegram users do not have a
Home Assistant access token.

All state, Door and camera endpoints enforce the integration-owned Mini App
session.

Only JavaScript/CSS assets use the existing Comelit static prefix:

```text
/api/comelit/frontend/...
```

The Mini App HTML itself is deliberately stored outside that static tree and is
served only by the dynamic `/api/comelit/miniapp` view, so the enable/configuration
gate and CSP cannot be bypassed through an alternate static URL.

## 4. Telegram authentication without a bot token

The browser sends raw `Telegram.WebApp.initData`.

The integration validates the `signature` field using Telegram's production
Ed25519 public key and the bot ID according to Telegram's documented
third-party validation algorithm:

https://core.telegram.org/bots/webapps#validating-data-for-third-party-use

The production Telegram public key is pinned in code:

```text
e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d
```

Validation also requires:

- bounded `auth_date`;
- valid Telegram user JSON;
- server-side Telegram user allowlist.

`initDataUnsafe` is never an authorization source.

The Comelit integration therefore does not require the Telegram bot token.

## 5. Short-lived in-memory sessions

After successful Telegram validation, the integration creates:

- a random opaque session token;
- a 15-minute in-memory session;
- one current random Door action nonce.

The browser receives only the session token in a cookie:

```text
HttpOnly
Secure
SameSite=Strict
Path=/api/comelit/miniapp
```

Sessions are intentionally not persisted. Home Assistant restart invalidates
them; Telegram can establish a new session from fresh `initData`.

Removing a Telegram user from the current allowlist invalidates that user's
existing session on the next protected request.

## 6. Home Assistant access

Because Mini App code executes inside `custom_components/comelit`, it uses
Home Assistant objects directly:

```text
hass.states
entity_registry
label_registry
hass.services
camera async_request_stream for ordinary surveillance cameras
internal attached Mini App HA Stream for real inbound Entrance media
```

There is no HA Long-Lived Access Token.

The browser receives only the filtered states and registry metadata required by
the Comelit card.

For the intercom Entrance during a real inbound Ring, the Mini App does not use
`async_request_stream(hass, "camera.comelit_entrance", HLS_PROVIDER)`. Home
Assistant HLS has no per-browser ownership identity: an HLS URL identifies the
HA `Stream`, not an individual viewer. The Mini App therefore owns a separate
internal attached media resource:

```text
one native attached inbound RTP transport
  -> one H264 recovery/rewrite state
  -> local RTP fan-out
       -> camera/ring SDP: attached-local-rtp.sdp, video 17999 + audio 17808
       -> Mini App SDP: attached-miniapp-rtp.sdp, video 18099 only
  -> separate HA Stream objects
       -> camera.comelit_entrance / ring snapshot-recording provider
       -> Mini App session-bound HLS proxy provider
```

The upstream Comelit call/media transaction remains single. Mini App viewers
refcount only the internal Mini App stream and the
`miniapp_attached_view` attached-session lease. Closing or expiring the last Mini
App viewer releases only Mini App ownership and requests ring-media convergence;
an ordinary HA frontend viewer keeps its independent `camera_view` lease until
the camera Stream lifecycle releases it. The browser still receives only an
opaque `/api/comelit/miniapp/media/{media_id}/...` URL, never the local SDP path
or raw HA HLS source.

The Mini App attached RTP output is registered inactive when the attached media
bridge starts. The single H264 recovery/rewrite state continues feeding the
camera/ring SDP immediately, while the Mini App video port receives no live
fan-out traffic until the Mini App attached HA Stream exists and its UDP port is
proven bound during the bounded readiness wait. Only after that proof does the
bridge snapshot a bounded decodable bootstrap and send it exactly once to the
Mini App RTP sink before marking that sink live. The bootstrap consists of the
last usable SPS, the last usable PPS, and the complete last finished IDR access
unit in rewritten RTP order. FU-A fragmented IDR access units are grouped by
SSRC and RTP timestamp until the marker packet closes the access unit; incomplete
or oversized access units are evicted instead of cached.

The real-UDP late-subscriber harness is kept out of normal pytest collection:

```bash
cd /path/to/comelit
python3 tests/miniapp/tools/late_subscriber_rtp_harness.py \
  --module custom_components/comelit/h264_recovery.py \
  --label local-fua-green \
  --join-delay 2.5 \
  --total 8.0 \
  --out /tmp/comelit-late-subscriber.json
```

## 7. Surveillance cameras

The integration option `miniapp_surveillance_label` accepts a Home Assistant
label ID or label name.

Only `camera.*` registry entries carrying that label are added to the Telegram
Mini App surveillance surface.

The intercom entrance camera is selected independently by its stable Comelit
unique ID and is not duplicated in the surveillance list.

## 8. Door/Gate safety

The browser does not choose an arbitrary Home Assistant entity for actuation.

The shared card's selected button entity is mapped client-side back to one of
two semantic routes:

```text
POST /api/comelit/miniapp/door/entrance
POST /api/comelit/miniapp/door/gate
```

The server independently resolves the current entity ID from these stable
Comelit unique IDs:

```text
comelit_main_entrance_open_door
comelit_main_gate_open_door
```

Before invoking the service, the embedded boundary requires the current entity
to be available and to report `standard_press_allowed=true`.

One accepted request performs exactly one:

```text
hass.services.async_call(
    "button",
    "press",
    {"entity_id": ...},
    blocking=True,
)
```

There is no automatic retry.

The Mini App host also explicitly never retries an action request after a
failure.

### 8.1 One-time action nonce

Each authenticated session owns one current action nonce.

A Door request must include it. The server consumes and rotates the nonce
**before** awaiting the Home Assistant service call.

Consequences:

- replaying the same HTTP request cannot invoke a second Door operation;
- a network timeout after an ambiguous operation does not trigger an automatic
  retry;
- a later explicit user click can use the newly issued nonce.

A successful software call never asserts the physical Door effect.

## 9. Camera lifecycle

The entrance camera and ordinary surveillance cameras have deliberately
separate media lifecycles.

For the Comelit entrance camera, after validating the requested camera against
the embedded allowlist, the integration calls Home Assistant's normal camera
stream API:

```text
async_request_stream(hass, entity_id, HLS_PROVIDER)
```

For `camera.comelit_entrance`, this enters the existing
`ComelitEntranceCamera.async_create_stream()` lifecycle:

```text
explicit Mini App viewer
-> HA camera stream request
-> attached Ring reuse when present
   otherwise bounded on-demand Comelit media
-> HA Stream / HLS
-> viewer removed or HLS becomes idle
-> existing camera-view cleanup
```

### 9.1 Do not expose the HA HLS capability to the WebView

Home Assistant's HLS endpoint contains a random stream capability token and is
itself intentionally usable without HA user authentication.

The embedded Mini App therefore keeps that HA HLS path server-side.

For each authorized camera open it creates a random, session-bound media grant:

```text
/api/comelit/miniapp/media/<media_id>/master_playlist.m3u8
```

The media grant stores the upstream HA HLS base path only inside Home
Assistant. Every Mini App playlist/init/segment request:

1. revalidates the current Mini App session;
2. rechecks the current bot ID and Telegram user allowlist through the session
   boundary;
3. verifies that the media grant belongs to that exact opaque session token;
4. allows only the closed HLS resource set:
   - `master_playlist.m3u8`
   - `playlist.m3u8`
   - `init.mp4`
   - numeric `segment/*.m4s`
5. proxies that resource to Home Assistant's own local HLS endpoint.

Relative HLS references keep the browser inside the Mini App proxy hierarchy,
so the underlying `/api/hls/<token>/...` capability is never serialized to
the WebView.

The media grant expires with the Mini App session. Removing a user from the
allowlist or changing the configured bot ID also prevents further proxy
requests from that session.

Ordinary labelled surveillance cameras are excluded from the Comelit entrance
media manager. Their fast live view path is:

```text
camera.stream_source()
-> Home Assistant Camera object
-> HA-managed go2rtc already running inside Home Assistant
-> restricted same-origin Comelit MSE/WSS proxy
-> Telegram Mini App video element
```

The browser endpoint is:

```text
GET /api/comelit/miniapp/camera/{entity_id}/mse
```

It is an authenticated Mini App WebSocket endpoint. The browser may send only
the closed MSE negotiation command
`{"type":"mse","value":"<bounded codec list>"}`. It never receives the camera
stream source, go2rtc base URL, go2rtc management API, internal upstream URL,
credentials, or Home Assistant HLS capability token. Upstream free-text
messages are not relayed blindly; only the bounded MSE MIME response and binary
fMP4 chunks can cross back to the WebView.

Comelit obtains the ordinary camera source only through the public Home
Assistant camera contract:

```text
await camera.stream_source()
```

For Mini App MSE, Comelit registers the validated resolved camera source directly
in the HA-managed go2rtc instance. For Home Assistant `generic` RTSP cameras,
the internal source adds `backchannel=0` so go2rtc skips its default ONVIF
backchannel DESCRIBE attempt. Ordinary surveillance viewing does not require a
camera backchannel, and avoiding that first probe prevents a failed/unsupported
backchannel request from consuming a full RTSP response timeout before go2rtc
reconnects for normal receive-only viewing. The direct source remains entirely
server-side and is never exposed to the browser. Home Assistant's own WebRTC
provider is unchanged and continues to use its native Generic Camera
compatibility behavior on WebRTC fallback.

Credentials remain owned by the original Home Assistant camera integration.
Comelit does not add options-flow URL/login/password fields, does not duplicate
credentials into the ConfigEntry, and does not persist the resolved source. The
resolved source and any internal `ffmpeg:` wrapper exist only long enough to
register a viewer-scoped stream in HA-managed go2rtc.

The internal go2rtc stream name is opaque and namespaced:

```text
comelit_miniapp_<sha256(entity_id)[:16]>
```

This avoids collision with Home Assistant's own `camera.entity_id` go2rtc
stream names and does not contain URLs, credentials, or entity-derived secrets.
The server process refcounts viewers per ordinary camera: the first viewer
registers the source with go2rtc, concurrent viewers reuse the same producer,
and the last release unregisters the Mini App stream in a `finally` cleanup
path.

There is no standalone Comelit application server, Docker container, add-on,
VM, or separate go2rtc instance in this path.

The ordinary-camera client fallback chain is:

```text
MSE -> WebRTC -> HLS
```

The success criterion for MSE and WebRTC is the first decoded/rendered video
frame, not WebSocket open, MIME negotiation, SDP answer, or remote-track
announcement.

The Mini App host provides a small `picture-entity` compatibility element
using an HTML5 `video` element.

Playback is capability-driven. The integration bundles pinned `hls.js 1.7.3`
under the existing same-origin Comelit frontend path. Telegram Desktop / Android
WebViews that expose MediaSource use hls.js; native HLS remains the fallback for
platforms such as Safari/iOS. No third-party JavaScript is fetched at runtime.

The hls.js instance is destroyed when the viewer is removed. Fatal playback
errors stop that viewer and are surfaced to the user instead of automatically
reopening the Comelit camera session.

## 10. Home Assistant options

The Comelit Options Flow contains:

```text
Enable Telegram Mini App
Telegram bot ID
Allowed Telegram user IDs
Home Assistant camera label
```

No Telegram bot token and no Home Assistant token are stored.

The Mini App route is fail-closed until:

- Mini App is enabled;
- bot ID is valid;
- at least one allowed Telegram user ID is configured.

## 11. External HTTPS

Telegram still requires the Mini App URL to be reachable by the Telegram
WebView over HTTPS in production.

The target URL is the Home Assistant URL itself, for example:

```text
https://<external-home-assistant-host>/api/comelit/miniapp
```

The external HTTPS mechanism is an installation concern (for example Home
Assistant Cloud or a reverse proxy), not a separate Comelit application
runtime.

## 12. Deployment boundary

Repository implementation does not by itself:

- enable the Mini App option;
- configure Telegram BotFather;
- publish or change an external Home Assistant URL;
- restart production Home Assistant;
- invoke Door/Gate;
- open a production camera session.

Those remain explicit deployment and acceptance steps.


## Surveillance live view: WebCodecs primary with legacy HA fallbacks

Ordinary Home Assistant surveillance cameras remain a separate lifecycle domain
from the Comelit entrance camera, but the normal Telegram Mini App viewer now
reuses the already live-validated direct WebCodecs transport as its primary
playback path.

Primary path:

```text
Telegram Mini App
  -> authenticated /api/comelit/miniapp/camera/{entity_id}/webcodecs
  -> camera.stream_source()
  -> PyAV H.264 demux/repackaging only
  -> bounded Annex-B WSS protocol v2
  -> VideoDecoder
  -> canvas
```

The resolved camera source remains server-side. The browser never receives the
RTSP URL, source credentials, Home Assistant stream capability, or go2rtc
management access. This path does not decode, encode, scale, filter, remux to
fMP4, or otherwise transcode video on Home Assistant.

The production viewer is embedded and auto-starts only after the user enters
«Видеонаблюдение» or explicitly selects an ordinary camera. Leaving the tab
disconnects the viewer and releases the RTSP/PyAV source. There is no camera
preload.

The server-side ordinary WebCodecs session is bounded to 600 seconds. The
diagnostic canary remains client-bounded to 60 seconds. For embedded ordinary
viewing, a server duration limit or another terminal source/decoder/WSS failure
disconnects the primary viewer and mounts the existing legacy viewer.

Legacy fallback order remains:

```text
MSE -> WebRTC -> HLS
```

The MSE path still resolves `camera.stream_source()` server-side, registers an
opaque stream with Home Assistant-managed go2rtc, and proxies only the bounded
MSE protocol. If MSE fails, the legacy viewer may use Home Assistant's
registered WebRTC provider and finally the existing session-bound HLS proxy.
These paths are retained as fallbacks rather than removed.

Periodic Home Assistant state refreshes and semantically unchanged card renders
must preserve the connected embedded WebCodecs node. Selecting another camera,
leaving the surveillance tab, explicit card reconfiguration, or terminal
fallback may replace it.

The Comelit entrance camera continues to use its separately validated
manager-owned WebCodecs lifecycle. Its 600-second media-manager ceiling remains
authoritative and does not trigger an automatic HLS restart.

### Entrance warm tab park

When an explicitly opened Entrance WebCodecs viewer switches from
`Домофон` to `Видеонаблюдение`, the Mini App does not keep the hidden
browser viewer alive. Before disconnecting that viewer it acquires one bounded
manager lease:

```text
miniapp_webcodecs_park
```

The browser-side Entrance resources are then released before ordinary
surveillance starts:

```text
Entrance canvas / VideoDecoder
-> PyAV reader
-> Entrance WebSocket
-> disconnected
```

The park lease keeps the already-established Comelit on-demand media transport
alive for **60 seconds**. Returning to `Домофон` within that bound acquires a
new `miniapp_webcodecs` viewer lease first and only then releases
`miniapp_webcodecs_park`. The manager therefore never reaches zero leases
during the hand-off and does not repeat the cold P2P/PseudoTCP/CTPP bootstrap.

If the user does not return within 60 seconds, the park lease expires. With no
other media lease, the existing `ComelitMediaSessionManager` performs its
normal full teardown and restores the persistent listener. The existing
600-second absolute manager deadline remains authoritative and can terminate a
park earlier.

This is deliberately **not** a newly invented proprietary RTPC pause/resume
operation. During the bounded park, the WebView receives and decodes no
Entrance video, but the existing Comelit upstream media transport in Home
Assistant remains active. A future protocol-level
`stop RTP -> keep CTPP -> reopen RTP` optimization requires separate live
evidence before production use.

Explicit camera close, Mini App close, terminal Entrance WebCodecs failure, and
Entrance HLS fallback do not request the warm park and retain their normal
teardown/fallback semantics.

### Entrance attached Ring viewer lease

During real inbound Ring media, the Mini App Entrance viewer is the HLS/HA
Stream path, not the on-demand Entrance WebCodecs path. The WebCodecs request is
allowed to fail closed with `intercom_media_busy` while the already-attached
inbound transport feeds Home Assistant Stream and HLS.

That HLS viewer is represented by a session-bound server lease:

```text
POST /api/comelit/miniapp/attached-viewer
  action=open | heartbeat | close
  viewer_id=<browser-generated opaque id>
```

The endpoint uses the existing Mini App session cookie and marker header. It
does not accept an entity id, source URL, SDP, event id, or any transport stop
primitive from the browser. `close` is idempotent. Multiple viewer ids in the
same Mini App session refcount independently; attached Ring teardown is
requested only when the last relevant Entrance viewer is gone.

For the Mini App attached HLS path, the controller adds the HLS provider and
starts the internal HA Stream before activating the Mini App RTP sink. This lets
the HA Stream worker bind the Mini App RTP port before the recovery bridge sends
the bounded bootstrap. The readiness check is the Mini App RTP port appearing
in `/proc/net/udp` or `/proc/net/udp6`, which is the point where the HA Stream
worker has opened the SDP and bound the UDP socket. The wait is bounded and
fail-closed: if the port is not observed before the deadline, or procfs cannot
prove readiness, the Mini App sink is not activated and no bootstrap packet is
sent. The request is rejected with the bounded internal reason
`miniapp_attached_consumer_not_ready`; the internal Mini App HA Stream,
provider consumer, and `miniapp_attached_view` lease are released. The ordinary
HA camera/ring sink is untouched, and the upstream attached transport remains
governed only by any leases still present.

TEST1 on release 1.7.32b1 proved why that ordering matters. A real inbound Ring
created exactly one upstream Comelit media transport and the main attached HA
path was healthy: Telegram snapshots were delivered and a 25.807 s MP4
recording completed. The separate Mini App HLS resource still showed no first
frame because it was a late RTP subscriber. The initial SPS/PPS STAP-A packet
and the FU-A fragmented IDR access unit had already passed before the Mini App
HA Stream bound its port, leaving only undecodable P-fragments for that sink.
The recovery cache therefore stores a bounded per-sink bootstrap and closes
fragmented H.264 access units on the RTP marker bit, not on a single FU-A
packet.

The browser sends heartbeat about every 5 seconds. The server expires a lease
after about 15 seconds without heartbeat, so WebView loss is bounded even if
`pagehide` or disconnect cleanup is not delivered. Explicit close remains
best-effort: `pagehide` and element disconnect use fetch `keepalive`, but
`sendBeacon` is not used because the close endpoint must retain the Mini App
marker header and session gate. `visibilitychange=hidden` is not terminal
because short system overlays and tab switches must not close media.

When the last lease is released or expires, the controller asks
`RingMediaCoordinator.async_request_stop(viewer_closed|viewer_lease_expired)`.
The HTTP view never calls attached-media `async_force_stop` or native transport
cleanup directly. The coordinator owns the ordered cleanup: bounded recording
stop/cancel, release of the `ring_media` lease and stream consumer, and release
of the Mini App's own `miniapp_attached_view` lease and internal HA Stream. It
does not release `camera_view`; the normal camera Stream lifecycle remains the
only owner of that lease. The final attached-session lease release drives the
existing attached-media R58/SIGUSR2 stop path.

Ending the last Mini App viewer also deactivates the Mini App RTP sink. If the
attached media session remains alive for another lease holder, a later Mini App
viewer starts inactive again and receives a fresh bootstrap before live fan-out.
The same recovery applies after a fail-closed readiness timeout: a later Mini
App request can succeed once the UDP consumer is actually bound.

Home Assistant HLS idle cleanup (`OUTPUT_IDLE_TIMEOUT`, HA Core ref 2026.9.2)
does not fit the Mini App's 15-second viewer-loss bound by itself, so Mini App
close/expiry releases the explicit Mini App resource instead of trying to infer
ordinary HA viewers.

### HA HLS viewer identity and Mini App isolation

The Mini App attached-viewer lease is visible to the integration. Ordinary Home
Assistant frontend/dashboard HLS viewers are not. HA Core tracks one HLS output
per `Stream` and per format in
`homeassistant/components/stream/__init__.py` with
`_outputs: dict[str, StreamOutput]`; `outputs()` returns those format outputs,
and `add_provider()` reuses `self._outputs[fmt]` for an existing output.

HLS idle is shared per track/provider and refreshed by any HLS client through
`homeassistant/components/stream/hls.py` `track.idle_timer.awake()`.
`homeassistant/components/stream/core.py` owns the `IdleTimer`, and
`homeassistant/components/stream/const.py` sets `OUTPUT_IDLE_TIMEOUT = 30`.
This timer is not ownership evidence and cannot be used as a per-viewer signal.

The `/api/hls/<token>/...` URL identifies the `Stream` by its `access_token`,
not an individual client. `homeassistant/components/stream/__init__.py`
constructs `endpoint_url()` from that token, and
`homeassistant/components/stream/core.py` resolves the stream by token.

The ordinary camera path is intentionally separate from Mini App attached HLS.
In
`homeassistant/components/camera/__init__.py`, Home Assistant documents that
there is at most one stream, meaning one decode worker, per camera.
`async_request_stream(hass, entity_id, fmt)` calls `stream.add_provider(fmt)`
and then `stream.endpoint_url(fmt)`. The Mini App therefore does not use that
API for real inbound attached Entrance media; it creates an internal HA Stream
from `attached-miniapp-rtp.sdp` instead.

HA 2026.9.2 exposes per-session identity for WebRTC through
`camera/__init__.py` `async_handle_web_rtc_offer(..., session_id)` and
`close_webrtc_session(session_id)`. HLS and the attached path do not provide an
equivalent client identity.

Because Mini App has its own downstream video port and HA Stream, Mini App close
releases only Mini App ownership. If an ordinary HA viewer owns `camera_view`,
the upstream attached transport remains active until that camera lease is later
released. The integration still must not simulate a per-viewer HA HLS signal;
it relies on explicit local ownership instead.

## 12.1 WebCodecs transport and diagnostic tab

Status: live-validated for ordinary H.264 surveillance cameras and for the
Comelit Entrance path. Routing, framing, bounded cleanup, and browser behavior
also remain covered by offline tests.

The Mini App can additionally expose a third diagnostic tab, `WebCodecs`, by
passing the explicit shared card flag:

```text
webcodecs.enabled === true
```

The flag is passed only by `custom_components/comelit/frontend/miniapp/host.js`.
Default Lovelace usage does not render the diagnostic tab or panel. The normal
Mini App two-tab surface separately opts ordinary surveillance into embedded
WebCodecs primary playback with `webcodecs.surveillance_primary=true`.
Opening the diagnostic tab does not open a camera. Its only start action is the
explicit Russian UI button `Запустить тест`.

The authenticated endpoint is:

```text
GET /api/comelit/miniapp/camera/{entity_id}/webcodecs
```

It reuses the integration-owned Mini App session cookie. Missing, invalid, or
expired sessions are rejected before WebSocket upgrade with `403`, never raised
`401`. Before upgrade, the view also requires a `camera.*` entity and resolves
the camera through the ordinary surveillance guard. Closed JSON errors use
`409` and one of:

```text
camera_not_allowed
intercom_camera_not_allowed
camera_unavailable
```

After upgrade the browser may send exactly one start command:

```json
{"type":"webcodecs","value":"h264"}
```

Anything else, or no command within 5 seconds, closes with
`invalid_webcodecs_command`. The camera source is resolved only after this
command using `await camera.stream_source()`. The resolved source remains
server-side and is never serialized or logged.

The first implementation uses lazy PyAV (`av`) as an in-process demuxer. This
is coupled to the existing Home Assistant `stream` dependency declared in the
Comelit manifest. The adapter demuxes H.264 packets only; it does not perform
video decode, encode, re-encode, scaling, filtering, container muxing, or
transcoding. If `av` is unavailable or opening fails, the WebSocket returns the
closed error `source_dependency_missing` or `source_open_failed` without
breaking Home Assistant startup.

The server converts H.264 access units to Annex-B. Existing Annex-B start codes
are preserved, 4-byte AVCC length prefixes are repackaged, and
`AVCDecoderConfigurationRecord` extradata is parsed for SPS/PPS. Every keyframe
access unit is sent with SPS/PPS prepended when they are not already present.
The server derives `avc1.PPCCLL` from SPS bytes and sends it in the closed
`hello` message; the codec string is not hardcoded. The same `hello` message
includes `zero_transcode: true`, asserted server-side because this adapter only
copies H.264 access units and has no decode, encode, re-encode, mux, scale, or
transcode branch.

Each binary WebSocket message is one explicitly framed access unit:

```text
36-byte big-endian header + H.264 Annex-B payload
```

Header fields are version, flags, reserved, sequence, media PTS in microseconds,
source elapsed microseconds, send elapsed microseconds, and payload length. Malformed version, flags, reserved bits, truncation, length
mismatch, or payloads larger than `WEBCODECS_MAX_UNIT_BYTES` are rejected by
pure helpers and covered by offline tests.

The path is bounded:

```text
WEBCODECS_MAX_UNIT_BYTES=1048576
WEBCODECS_MAX_QUEUE_UNITS=48
WEBCODECS_MAX_QUEUE_BYTES=3145728
WEBCODECS_MAX_SESSION_SECONDS=600
WEBCODECS_MAX_SESSIONS=4
```

At most one active WebCodecs session is allowed per camera entity, with a small
global cap. Queue overflow sends `backlog_exceeded` and closes. The unit bound
absorbs short event-loop stalls; the byte bound remains the memory cap. The
first version has no frame drop policy because arbitrary delta-frame dropping
breaks H.264 GOP dependencies. GOP-aware dropping is explicitly deferred.

Cleanup is idempotent and runs from the view `finally` path for source EOF,
source open failure, duration expiry, backlog overflow, WebSocket close, and
task cancellation. Each H.264 packet source owns one PyAV worker thread; `av.open`,
`container.demux()` iteration, packet-to-plain-value copying, and
`container.close()` for that input container all run on that owner thread in FIFO
order. Cancelling the async producer therefore cannot make the event-loop thread
close an `InputContainer` while PyAV/FFmpeg is still inside a blocking read. The
view still calls `aclose()`, but `aclose()` only queues the owner-thread close and
waits a bounded interval for the worker to finish; owner completion is delivered
to the event loop with `loop.call_soon_threadsafe()` without allocating per-source
wake file descriptors.
If a read remains blocked past the bound, control returns to the event loop and
the queued close is still performed later by the same daemon owner thread after
the bounded PyAV read timeout unblocks. The daemon owner thread is an explicit
limitation accepted here because PyAV open/read calls use the 5.0 second timeout
bound and teardown does not rely on process shutdown for normal cleanup.

The primary WebCodecs source does not call the legacy MSE/WebRTC/HLS transport
while it is healthy. Those paths remain isolated fallbacks. The WebCodecs
transport does not call Door or Gate services.

Closed, bounded log lines use:

```text
COMELIT_MINIAPP_WEBCODECS ...
COMELIT_MINIAPP_WEBCODECS_SUMMARY ...
```

They include entity id, fixed event/reason enums, elapsed milliseconds, access
unit counts, keyframe counts, byte counts, and error counts. They never include
URLs, hosts, ports, usernames, passwords, cookies, tokens, Telegram `initData`,
or camera source strings.

## 13. Mini App player diagnostics

The Mini App can report bounded player milestones for an authorized camera
viewer:

```text
POST /api/comelit/miniapp/camera/{entity_id}/diagnostics
```

The endpoint uses the same integration-owned Mini App session cookie as the
stream and WebRTC camera endpoints. It also requires
`X-Comelit-MiniApp-Request: 1` and rejects entities outside the controller's
allowed camera set. Session failure remains `403`, not raised `401`.

The accepted event enum is:

```text
config, offer, answer, track, ice, rtp, first_frame,
first_moving_frame, mse_connect, mse_ready, mse_first_chunk,
mse_first_frame, mse_error, mse_fallback, fallback, hls_manifest,
hls_play, hls_state, hls_first_frame, hls_seek, hls_error, hls_blocked
```

Payload fields are closed and optional except `event`:

```text
event      fixed enum above
elapsed_ms integer 0..600000
stage_ms   integer 0..600000
state      fixed player-state enum or null
reason     fixed fallback-reason enum, or fixed HLS-error enum for hls_error
counters   up to 16 integer counters, keys matching ^[a-z][a-z0-9_]{0,39}$
```

Fallback reasons are:

```text
stats_deadline_checking, stats_deadline_other, ice_failed,
connection_failed, websocket_error, websocket_closed, offer_error,
answer_error, candidate_error, no_rtcpeerconnection, session_expired,
navigate, no_mediasource, mse_ws_error, mse_ws_closed,
mse_negotiation_failed, mse_unsupported_codec, mse_first_chunk_timeout,
mse_first_frame_timeout, mse_append_error, go2rtc_unavailable,
go2rtc_incompatible, go2rtc_http_error, go2rtc_ws_error,
stream_source_unavailable, invalid_mse_command, mse_registry_full
```

The diagnostics module has no free-text field. Unknown keys, unknown enum
values, nested structures, strings in counters, oversized integers, more than
16 counters, non-dict JSON, and bodies larger than 2048 bytes are rejected with
`{"error": "invalid_diagnostics_event"}`. Rejected content is never echoed.

The serializer has a defensive redaction guard and refuses to serialize values
matching:

```text
(?i)(sdp|a=candidate|\d{1,3}(\.\d{1,3}){3}|https?://|wss?://|rtsp://|bearer|cookie|initdata|token|ice-ufrag|ice-pwd|v=0|o=-|m=audio|m=video|hash=|signature|candidate:)
```

The browser reports only enums and integers. MSE diagnostics report bounded
milestones, fallback reasons, chunk counts, byte counts, queue length and
buffer length. WebRTC candidate diagnostics count
candidate types and transports from `getStats()` reports (`host`, `srflx`,
`relay`, `udp`, `tcp`) plus candidate-pair states, nomination counts, selected
pair counters, ICE gathering state, inbound RTP bytes and decoded-frame counts.
It never reads or posts ICE candidate strings, SDP, IP addresses, URLs,
cookies, `initData`, Telegram user data, RTSP URLs, go2rtc URLs, credentials,
or media bytes.

Accepted diagnostics are rate limited server-side using constants from
`custom_components/comelit/miniapp/diagnostics.py`:

```text
MAX_EVENTS_PER_SESSION = 160
MAX_EVENTS_PER_SESSION_ENTITY = 80
MAX_RATE_LIMIT_SESSIONS = 128
MAX_RATE_LIMIT_ENTITIES_PER_SESSION = 8
```

The limits allow a normal client playback attempt, which is already capped at
60 posted events, while bounding Home Assistant log volume and limiter memory.
Expired session buckets are pruned, and overflow returns:

```text
HTTP 429 {"error": "diagnostics_rate_limited"}
```

Accepted events produce exactly one Home Assistant log line:

```text
COMELIT_MINIAPP_DIAG entity=<entity> event=<event> elapsed_ms=<n> stage_ms=<n> state=<s|-> reason=<r|-> counters=<k=v,...|->
```

The summary helper uses the same closed format with:

```text
COMELIT_MINIAPP_DIAG_SUMMARY
```

Operators can retrieve a real Mini App session trace from the Home Assistant
log stream exposed by the SSH gateway by filtering for:

```text
COMELIT_MINIAPP_DIAG
COMELIT_MINIAPP_DIAG_SUMMARY
```
