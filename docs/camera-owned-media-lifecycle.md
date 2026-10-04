# Camera-owned media lifecycle

Status: camera-owned on-demand lifecycle live-validated in HAOS; inbound Ring lifetime now follows authoritative remote close, Mini App viewer lease end, or the existing hard limit.

## Goal

The user-facing entity `camera.comelit_entrance` owns normal live-view startup and
shutdown. A separate media switch is no longer required for ordinary use.

The explicit `switch.comelit_entrance_camera` remains as a disabled-by-default deprecated diagnostic fallback for compatibility. Camera-owned automatic start/release has already been live-validated in HAOS, and current user/Telegram flows do not depend on the switch.

## Normal on-demand view

```text
HA live-stream request
  -> camera.comelit_entrance.async_create_stream()
  -> one camera_view media lease
  -> ComelitMediaSessionManager
  -> listener pause confirmed
  -> one self-activation/P2P media bootstrap
  -> shared HA Stream
  -> HLS consumer
```

The camera does not call the cloud/P2P bootstrap directly. It only acquires the
existing media-session manager, preserving its single-session, no-retry and 600-second
absolute deadline semantics.

## Real inbound Ring

A real inbound call is preferred over self-activation:

```text
CALL_INIT
  -> attached Ring media lifecycle claims inbound call transaction
  -> camera live-stream request
  -> camera_view joins ComelitAttachedRingMediaSession
  -> same upstream call transaction
  -> camera/ring HAStreamMediaProvider
  -> camera/ring HA Stream
```

Ring snapshot/recording and ordinary `camera.comelit_entrance` live view share
the camera/ring HAStreamMediaProvider and its local SDP. The Mini App attached
viewer no longer shares this HA Stream; it has a separate internal downstream
SDP/HA Stream while still sharing the same upstream Comelit attached transport.

A two-second bounded local wait covers the race where the persistent listener has
already marked inbound media busy but the Ring coordinator has not yet claimed the
attached session. This is not a network/media retry: the on-demand manager rejects the
attempt before pausing the listener or sending a media request.

## What starts media

Allowed automatic start:

- explicit HA stream request for `camera.comelit_entrance`;
- explicit camera record/play-stream request, which uses the same HA stream path.

Must not start media:

- entity-picture requests;
- thumbnail/still polling;
- Home Assistant stream preloading;
- integration startup by itself.

`use_stream_for_stills=False` prevents still polling from entering stream creation.
The integration also persists `preload_stream=False` for this camera. If a startup
preload call races past the preference check, the first such call is failed closed and
does not acquire Comelit media.

## Automatic release

Home Assistant remains the source of truth for HLS viewer idleness. The integration
does not invent a second viewer-idle timer.

The camera monitor observes the Stream provider lifecycle:

- once an HLS provider has existed, its HA idle state or provider removal ends the
  `camera_view` lease;
- if no provider appears within 65 seconds after stream creation, the lease is released;
- a camera-view lease has an independent defense-in-depth maximum of 600 seconds;
- media-owner failure ends the local stream and releases the view lease.

The on-demand `ComelitMediaSessionManager` still owns its original 600-second
absolute deadline, which is never extended by new leases.

## Shared Stream lifetime

`HAStreamMediaProvider` now has named consumer references.

Typical inbound Ring plus user viewing:

```text
CALL_INIT -> ring_media acquires attached media + shared HA Stream
Mini App Entrance viewer opens HLS through the session-bound proxy
viewer sends /api/comelit/miniapp/attached-viewer open + heartbeat
-> miniapp_attached_view acquires attached media + internal Mini App HA Stream
20-second recording completes, or is bounded-cancelled on viewer termination
ring_media remains held while a terminal condition has not occurred
remote/native media close OR last Mini App Entrance viewer close/expiry
-> ring_media releases
-> miniapp_attached_view releases its internal Mini App HA Stream
camera_view remains if an ordinary HA frontend viewer is active
last camera_view release -> attached transport stops once
```

The 20-second recording target is **not** the lifetime of the inbound call. For a real
Ring, backend-observed remote/native media close remains authoritative, but the
Mini App Entrance viewer is also represented by a bounded server-side lease:
open and heartbeat are refreshed about every 5 seconds, and the server expires
the lease after about 15 seconds without a heartbeat. Explicit Hide/destroy,
Mini App close, and `pagehide` only accelerate release; server-side expiry is
authoritative if the WebView disappears. Browser explicit close is best-effort
rather than guaranteed: fetch `keepalive` is used for terminal close, while
`sendBeacon` is avoided because it cannot carry the Mini App marker header
required by the session-gated close endpoint. `visibilitychange=hidden` is not
a terminal event.

If the viewer terminates during recording, the coordinator first asks the HA
Stream recording task to stop/cancel in bounded fashion. A non-empty partial
file is reported as `truncated`; otherwise the recording result is `failed`.
Only then does `ring_media` release its attached-media lease and camera/ring HA
Stream consumer. Mini App close/expiry does not release `camera_view`. The
ordinary camera monitor remains the sole owner of camera-view release, so a
dashboard/frontend viewer can continue on the camera/ring stream after the Mini
App exits. The existing R58/SIGUSR2 stop path runs only after the last attached
session owner is gone. A 600-second defense-in-depth ceiling remains in case
neither remote close nor viewer termination is observed.

## HLS viewer identity and explicit Mini App ownership

Home Assistant Core does not expose a per-viewer registry for HLS clients on
the camera stream path used here. In HA 2026.9.2,
`homeassistant/components/stream/__init__.py` tracks one HLS output per
`Stream` and per format with `_outputs: dict[str, StreamOutput]`; `outputs()`
returns those format outputs, and `add_provider()` reuses `self._outputs[fmt]`
when the output already exists.

HLS idle is shared per track/provider, not per browser client:
`homeassistant/components/stream/hls.py` refreshes the track with
`track.idle_timer.awake()`, `homeassistant/components/stream/core.py` owns the
`IdleTimer`, and `homeassistant/components/stream/const.py` sets
`OUTPUT_IDLE_TIMEOUT = 30`. That idle timer is not ownership evidence and must
not be used as a per-viewer signal.

The `/api/hls/<token>/...` path identifies the `Stream` by its
`access_token`, not a client. `homeassistant/components/stream/__init__.py`
builds `endpoint_url()` from the stream `access_token`, and
`homeassistant/components/stream/core.py` looks up the stream by that token.

The camera contract shares that same stream. In
`homeassistant/components/camera/__init__.py`, Home Assistant documents that
there is at most one stream, meaning one decode worker, per camera.
`async_request_stream(hass, entity_id, fmt)` calls `stream.add_provider(fmt)`
and returns `stream.endpoint_url(fmt)`. Therefore the Mini App and an ordinary
HA frontend/dashboard HLS viewer receive the same HA camera stream.

HA 2026.9.2 has per-session identity for WebRTC through
`camera/__init__.py` `async_handle_web_rtc_offer(..., session_id)` and
`close_webrtc_session(session_id)`. The HLS and attached-camera path has no
equivalent client identity.

The integration therefore does not infer ordinary HA viewers from
`provider.consumers`, HLS idle, or `/api/hls/<token>/...` traffic. Instead, Mini
App attached viewing is represented by an explicit owned resource:

```text
native attached inbound RTP video 17899
  -> one H264RecoveryRtpShim / one rewrite state
  -> fan-out to camera/ring video 17999
  -> fan-out to Mini App video 18099
```

The camera/ring SDP remains `attached-local-rtp.sdp` with video 17999 and audio
17808. The Mini App SDP is `attached-miniapp-rtp.sdp` with video 18099 only; the
Mini App browser player is muted and no second Comelit audio transport is
created. These ports are distinct, so two HA Stream objects never read the same
local UDP sink.

TEST1 on release 1.7.32b1 showed the Mini App HLS stream can fail even when the
main attached HA path is healthy. In that production window the normal attached
path delivered Telegram snapshots and completed a 25.807 s MP4 recording, while
the separate Mini App HLS resource never reached a first frame. The root cause
was late subscription on the Mini App RTP sink: SPS/PPS and the FU-A fragmented
IDR access unit had already been sent before the Mini App HA Stream worker bound
`attached-miniapp-rtp.sdp`. The fix keeps one upstream Comelit transport and one
H.264 rewrite pipeline, but adds a bounded per-sink bootstrap replay. FU-A
access units are cached only once the RTP marker closes the access unit.

Activation follows production ordering: `add_provider(HLS)` starts the HLS
output, `Stream.start()` spawns the HA Stream worker, the readiness gate polls
for the Mini App UDP port in `/proc/net/udp{,6}`, and then the sink is
activated. The readiness gate is bounded and fail-open. If readiness is not
observed before the deadline, or procfs cannot be read, the Mini App sink is
activated anyway so live RTP is not blacked out.

Mini App OPEN acquires `miniapp_attached_view`, creates/reuses the internal Mini
App HA Stream, and increments a viewer refcount. Closing one of multiple Mini
App viewers decrements only that refcount. Closing or expiring the last Mini App
viewer closes the internal Mini App stream, releases `miniapp_attached_view`,
and requests `ring_media` stop. If `camera_view` is still present, the upstream
attached transport remains active; only the later camera-view release reaches
zero attached-session leases and performs exactly one transport stop.

## Switch migration

For the transition release:

```text
switch.comelit_entrance_camera
  deprecated=true
  replacement_entity_id=camera.comelit_entrance
  entity_registry_enabled_default=false
```

Existing installations may keep the already-enabled switch until the next cleanup
release. New/clean entity registry setups should not expose it by default.

HAOS live validation of automatic camera start and automatic release has passed. The switch can therefore be removed in a later compatibility-cleanup release once existing installations no longer need the fallback. Current Ring/Telegram automation must not reference it.
