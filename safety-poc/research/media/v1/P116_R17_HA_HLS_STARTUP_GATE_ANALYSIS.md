# P116 R17 — HA HLS startup gate analysis

## Status

```text
PHASE=P116_R17
MODE=RESEARCH_OFFLINE
HA_CORE_VERSION=2026.9.1
FUNCTIONAL_FIX_IMPLEMENTED=false
LIVE_RUN_EXECUTED=false
HA_DEPLOY=NOT_RUN
HA_RESTART=NOT_RUN
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
```

R17 separates the two already observed failure domains:

```text
D1_MEDIA_LIFETIME = RTP stops after ~35-36 s
D2_HA_STARTUP_RENDER = no user-visible frame appears at all
```

R16's media-request lease hypothesis can explain D1, but it cannot explain D2.
R17 therefore analyses the exact Home Assistant 2026.9.1 HLS startup path.

## Existing evidence entering R17

Production P116 attempts prove that valid RTP reaches the local HA bridge for
approximately 35-36 seconds. The HA stream worker's eventual error is the
steady-state `Error demuxing stream`, not an open/startup error. Earlier static
analysis established that this error occurs after HA has opened the SDP source,
found the video stream, found the first video keyframe, repaired initial timing,
constructed the muxer, and muxed the first keyframe.

P77/P115 offline evidence independently proves that the wrapped PT99 stream can
be depacketized and decoded as H.264. R13C further proved that a single-IDR
variant can produce MP4 init data, a first moof/mdat and a first LL-HLS Part.

The missing inference was: `first LL-HLS Part exists` does **not** imply that the
Home Assistant frontend can obtain its initial HLS playlist.

## Exact HA 2026.9.1 HLS endpoint

Home Assistant 2026.9.1 registers HLS provider URLs as:

```text
/api/hls/{token}/master_playlist.m3u8
```

A camera's standard HLS stream URL is therefore the master playlist endpoint.

The exact `HlsMasterPlaylistView.handle()` implementation contains an explicit
startup gate:

```text
# Make sure at least two segments are ready (last one may not be complete)
if not track.sequences and not await track.recv():
    return 404
if len(track.sequences) == 1 and not await track.recv():
    return 404
```

Therefore the initial master playlist is not returned when only one HLS Segment
object exists, even if that segment already contains valid LL-HLS Parts.

`HlsMasterPlaylistView.render()` also derives bitrate/codecs from
`track.sequences[-2]`, i.e. the previous/complete segment.

## How HA creates the second Segment

The exact 2026.9.1 `StreamMuxer.mux_packet()` closes the current segment only
when a later video packet satisfies all of:

```text
packet.is_keyframe
packet.dts is non-zero
(packet.dts - segment_start_dts) * time_base >= min_segment_duration
```

When that later keyframe arrives, HA calls `flush(..., last_part=True)` and then
`reset(packet.dts)`, which creates the next Segment lifecycle.

Normal LL-HLS Part creation inside the first segment does not create a second
Segment object.

Default HA stream configuration has LL-HLS enabled, target segment duration 6 s
and `min_segment_duration = 6 - 0.1 = 5.9 s`.

## Consequence for the Comelit stream

The official-app R14 capture had two IDRs essentially at startup and no later
IDR after 1 second. P116 production forensics likewise did not establish a clean
later IDR/keyframe suitable for normal HLS segment closure.

Thus the following sequence is consistent with all current observations:

```text
Comelit RTP starts
-> HA opens SDP
-> HA finds first keyframe
-> HA muxes first keyframe
-> HA creates init + first LL-HLS Part(s)
-> no later keyframe after >=5.9 s
-> first HLS segment never closes during live media
-> second HLS Segment object is never created
-> master_playlist.m3u8 remains blocked waiting for segment #2
-> frontend never receives a playable HLS master/media startup path
-> user sees zero visible video
-> independently, D1 stops RTP around 36 s
-> stream worker later times out while demuxing
```

This explains why offline H.264 decoding succeeds while Home Assistant displays
no frame.

## R13C correction

R13C's result remains valid but its interpretation must be narrowed:

```text
SECOND_IDR_REQUIRED_FOR_FIRST_LL_HLS_PART=false
```

is still proven offline.

However:

```text
SECOND_LATE_KEYFRAME_REQUIRED_FOR_STANDARD_HA_MASTER_PLAYLIST_STARTUP
```

is strongly supported by exact HA 2026.9.1 source because the master endpoint
waits for at least two Segment objects and the normal segment transition is
keyframe-gated.

Therefore `first Part exists` was not sufficient evidence for `frontend can show
first frame`.

## Initial media playlist does not trivially bypass the gate

Using `/playlist.m3u8` directly is not an immediate fix. On an initial request
without `_HLS_part`, HA's `HlsPlaylistView.handle()` advances the requested media
sequence and waits for the next segment, effectively waiting for a complete
segment. Thus simply replacing `master_playlist.m3u8` with `playlist.m3u8` does
not safely solve startup for a one-segment/no-later-keyframe stream.

## D2 decision

```text
D2_HA_NEVER_RECEIVES_RTP=REJECTED_FOR_OBSERVED_WORKER_SESSION
D2_HA_CANNOT_IDENTIFY_H264=REJECTED_FOR_OBSERVED_WORKER_SESSION
D2_FIRST_KEYFRAME_MISSING=REJECTED_FOR_OBSERVED_WORKER_SESSION
D2_FIRST_LL_HLS_PART_IMPOSSIBLE=REJECTED_OFFLINE
D2_HLS_STARTUP_BLOCKED_BY_NO_SECOND_SEGMENT=STRONGLY_SUPPORTED_STATIC
D2_ROOT_CAUSE_STATUS=STRONGLY_PLAUSIBLE_NOT_YET_LIVE_CONFIRMED
```

## Minimal live discriminator

One bounded live observation can close D2 without payload capture. During a
single media/view cycle record only scalar HA stream-output state:

```text
STREAM_DIAGNOSTICS_CONTAINER_FORMAT=
STREAM_DIAGNOSTICS_VIDEO_CODEC=
HLS_PROVIDER_PRESENT=
HLS_SEGMENT_COUNT=
HLS_LAST_SEGMENT_PART_COUNT=
HLS_LAST_SEGMENT_INIT_BYTES=
HLS_LAST_PART_BYTES=
HLS_ANY_PART_HAS_KEYFRAME=
HLS_SECOND_SEGMENT_CREATED=
```

Expected signature if R17 is correct:

```text
video RTP packet count increases
container_format=sdp
video_codec=h264
HLS_PROVIDER_PRESENT=true
HLS_SEGMENT_COUNT=1
HLS_LAST_SEGMENT_PART_COUNT>0
HLS_LAST_SEGMENT_INIT_BYTES>0
HLS_LAST_PART_BYTES>0
HLS_SECOND_SEGMENT_CREATED=false
USER_VISIBLE_VIDEO=false
```

No raw media or HLS bytes need to be logged.

## Corrective directions after confirmation

Do not choose a production fix before the discriminator. Candidate solution
classes are:

1. obtain/induce a later true keyframe from Comelit at a safe cadence;
2. use a Comelit-specific playback/output path that does not require HA's
   two-Segment master-playlist startup gate;
3. transcode/re-keyframe locally before handing video to HA HLS.

Changing Home Assistant core globally or forcing HLS segment boundaries on
non-keyframes is not recommended as the first fix.

D1 remains separate. Extending the Comelit media lease may keep RTP alive longer
but does not by itself guarantee a later keyframe or a visible HA frame.

## Safety

```text
NO_COMELIT_LIVE=true
NO_HA_DEPLOY=true
NO_HA_RESTART=true
NO_DOOR_GATE=true
NO_RAW_MEDIA_COMMITTED=true
```
