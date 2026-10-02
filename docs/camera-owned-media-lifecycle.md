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
  -> same HAStreamMediaProvider / same HA Stream
```

The shared HA Stream consumer registry prevents a second local PyAV/RTP consumer from
binding the same loopback RTP ports. Ring snapshot/recording and camera live view can
therefore coexist on one Stream object.

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
20-second recording completes, or is bounded-cancelled on viewer termination
ring_media remains held while a terminal condition has not occurred
remote/native media close OR last Mini App Entrance viewer close/expiry
-> ring_media releases
camera_view releases on the same owner becoming inactive
consumers = {} -> HA Stream closes
```

The 20-second recording target is **not** the lifetime of the inbound call. For a real
Ring, backend-observed remote/native media close remains authoritative, but the
Mini App Entrance viewer is also represented by a bounded server-side lease:
open and heartbeat are refreshed about every 5 seconds, and the server expires
the lease after about 15 seconds without a heartbeat. Explicit Hide/destroy,
Mini App close, and `pagehide` only accelerate release; server-side expiry is
authoritative if the WebView disappears.

If the viewer terminates during recording, the coordinator first asks the HA
Stream recording task to stop/cancel in bounded fashion. A non-empty partial
file is reported as `truncated`; otherwise the recording result is `failed`.
Only then does `ring_media` release its attached-media lease and HA Stream
consumer. The camera-view cleanup callback then releases `camera_view` only for
the same `attached_inbound` owner/provider. Cleanup is deferred with
`camera_view_release_deferred` only when another integration-owned named
provider consumer is still present in `HAStreamMediaProvider.consumers`; that
guard does not observe ordinary Home Assistant HLS viewers from the frontend or
dashboards. The compare-and-release path under `_camera_view_lock` drops the
final `camera_view` lease, allowing the existing R58/SIGUSR2 cleanup path to
close the inbound media transport. A 600-second defense-in-depth ceiling remains
in case neither remote close nor viewer termination is observed.

Direct cleanup cannot close a shared HA Stream while a named integration-owned
provider consumer remains.

## Known limitation: ordinary HA HLS viewers are not visible

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

The direct consequence is
`OTHER_HA_VIEWER_SURVIVES_MINIAPP_CLOSE=NOT_PROVEN`. Mini App close or lease
expiry can release `camera_view` and stop the attached transport while an
ordinary HA HLS viewer is still watching the same camera. This does not prove
that the viewer will necessarily break, because after attached media closes HA
may fail closed or request again, but there is no guarantee and the integration
must not simulate a per-viewer signal.

Open question: the Mini App attached viewer needs either its own HA-visible
owned resource, such as a separate lease/provider/stream object with explicit
acquire/release, or a per-client HLS lease that HA Core exposes to integrations.
Validation requires two independent owners: Mini App close releases only Mini
App ownership, the ordinary HA HLS client remains active, and only the last
departure or HA HLS idle produces exactly one transport stop.

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
