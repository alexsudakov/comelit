# P116 R18 — HA HLS runtime diagnostics

## Purpose

Diagnose D2 (`RTP present but zero visible video in Home Assistant`) independently
from D1 (`upstream RTP stops around 36 seconds`).

The working R17 hypothesis is that Home Assistant 2026.9.1 can mux the first
incomplete LL-HLS segment/parts but the standard `master_playlist.m3u8` startup
path waits for a second segment. With no later H264 keyframe after the startup
IDRs, segment 0 may remain incomplete and segment 1 may never be created.

This diagnostic branch is intentionally based on the exact currently deployed
production SHA `0970b9c88fd47ddf83a397b0228c5d4bbef92423`, not on later research
commits, so deploying it cannot accidentally promote unrelated R12-R17 code.

## Authorized live scope

Owner authorization for this round covers exactly:

```text
HA_DIAGNOSTIC_DEPLOY=AUTHORIZED_ONCE
HA_RESTART=AUTHORIZED_ONCE
COMELIT_MEDIA_DIAGNOSTIC_SESSION=AUTHORIZED_ONCE
DOOR_ACTIONS=FORBIDDEN
GATE_ACTIONS=FORBIDDEN
```

The diagnostic patch must not change Comelit signaling, RTP forwarding, native
helper behavior, media lease/keepalive behavior, or HLS generation behavior.
It only exposes bounded scalar state from the already-existing HA `Stream` and
HLS provider.

## Safe runtime evidence

Expose/log only these scalar fields:

```text
ha_stream_created
ha_stream_available
ha_stream_worker_error_count
ha_stream_start_worker_count
ha_stream_container_format
ha_stream_video_codec
hls_provider_present
hls_segment_count
hls_part_count
hls_init_bytes
hls_first_part_bytes
hls_first_part_has_keyframe
hls_first_segment_complete
hls_second_segment_created
```

Never expose:

```text
stream access token
HLS endpoint URL
packet/media payload
RTP/SSRC identifiers
OAuth/session/ICE material
```

## Decision gate

Primary D2 signature:

```text
video_packet_count > 0
hls_provider_present = true
hls_segment_count = 1
hls_part_count > 0
hls_init_bytes > 0
hls_first_part_bytes > 0
hls_first_part_has_keyframe = true
hls_first_segment_complete = false
hls_second_segment_created = false
user_visible_video = false
```

If observed while RTP is still arriving, classify:

```text
D2_HA_MASTER_PLAYLIST_STARTUP_GATE=PROVEN_LIVE
```

If `hls_segment_count == 0` while RTP and the HA stream worker are active, the
problem lies earlier in PyAV/mux/part creation.

If `hls_segment_count >= 2` and parts/init exist while the user still sees no
video, the problem lies later in playlist/HTTP/frontend playback and the R17
startup-gate hypothesis is rejected for that session.

## Safety

This round does not request any Door/Gate operation, OAuth refresh, official-app
capture, protocol keepalive implementation, video-request lease implementation,
or native binary rebuild.
