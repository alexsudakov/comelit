# Camera-owned media lifecycle

Status: camera-owned on-demand lifecycle live-validated in HAOS; inbound Ring lifetime now follows authoritative remote close.

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
20-second recording completes -> recording artifact/event completes
ring_media remains held while the real inbound call remains open
camera_view may join the already-warm shared HA Stream at any point
remote/native media close -> ring_media releases
camera_view releases on the same owner becoming inactive
consumers = {} -> HA Stream closes
```

The 20-second recording target is **not** the lifetime of the inbound call. For a real
Ring, backend-observed remote/native media close is authoritative. A 600-second
defense-in-depth ceiling remains in case the remote close is never observed.

Direct cleanup cannot close a shared HA Stream while a named consumer remains.

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
