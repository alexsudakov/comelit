# P116 R16 — video-request lease corroboration

## Status

```text
PHASE=P116_R16
MODE=RESEARCH_OFFLINE
FUNCTIONAL_FIX_IMPLEMENTED=false
LIVE_RUN_EXECUTED=false
HA_DEPLOY=NOT_RUN
HA_RESTART=NOT_RUN
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
RAW_CAPTURE_IN_GIT=0
```

This round adds an independent, public static corroboration for the repeatedly
observed ~36-second media stop. It does not modify production code and does not
promote third-party constants into the cloud/P2P runtime contract.

## Independent implementation evidence

The public `jfmlima/comelit-vip` implementation documents an outgoing Comelit
video call as:

```text
INVITE
-> open UDPM
-> capabilities/setup
-> open audio RTPC
-> open video RTPC
-> audio media request
-> video media request
-> RTP
```

Its `VideoCall` implementation contains two especially relevant statements and
behaviors:

1. a 6741W sends about 36 seconds of video per media request;
2. the client repeats the video media request every 15 seconds before that media
   lease runs out.

The implementation creates a dedicated refresh task and `_refresh_video()` calls
`_request_video()` repeatedly. Its tests explicitly describe the same behavior:
`A 6741W stops video ~36 s after the last request; repeating it keeps video
flowing.`

Source provenance:

```text
repository=jfmlima/comelit-vip
path=custom_components/comelit_vip/viper/call.py
path=tests/test_video_call.py
```

This is an independent local-panel implementation, not the official Android app
and not our cloud/P2P helper. Therefore it is `CORROBORATING_EXTERNAL_STATIC`,
not direct proof of the production topology.

## Relation to our observations

Our three P116 production media sessions stopped RTP after approximately:

```text
35.141 s
35.884 s
36.049 s
```

The close numerical match to the independently documented ~36-second lifetime is
stronger evidence for a media-request lease than a generic transport failure.
It also explains why the session can start successfully and produce valid RTP,
yet expire later.

The current helper sends its generated client video/media signaling during setup
but has no proven recurring media-request refresh contract after media becomes
active.

## Revised D1 ranking

R15 proved that the official Android capture contains missing post-active ECHO
and UDPM maintenance. R16 does not invalidate those findings, but changes the
causal priority for the ~36-second stop.

```text
D1_VIDEO_REQUEST_LEASE_REFRESH=STRONGLY_PLAUSIBLE
D1_UDPM_MEDIA_MAINTENANCE=PLAUSIBLE
D1_ECHO_SESSION_MAINTENANCE=LOWER_AS_DIRECT_VIDEO_GATE
D1_PSEUDOTCP_TRANSPORT_KEEPALIVE=REJECTED_AS_PRIMARY
```

The decisive discriminator is now the official-app trace itself: does the
official Android client repeat the client video-media request after media active,
and if so, what is its cadence and runtime derivation?

## Required offline discriminator

Before any fourth live helper attempt, re-analyse the already retained private
R14 official-app capture and its reassembled CTPP/ViP stream for repeated video
media requests after the initial media-active transition.

Report only structural/scalar facts:

```text
OFFICIAL_VIDEO_REQUEST_COUNT=
OFFICIAL_VIDEO_REQUEST_FIRST_AT=
OFFICIAL_VIDEO_REQUEST_POST_ACTIVE_COUNT=
OFFICIAL_VIDEO_REQUEST_POST_ACTIVE_TIMES=
OFFICIAL_VIDEO_REQUEST_CADENCE_MEDIAN=
OFFICIAL_VIDEO_REQUEST_BODY_SHAPE_STABLE=
OFFICIAL_VIDEO_REQUEST_DYNAMIC_FIELDS_RELATION=
HELPER_VIDEO_REQUEST_COUNT_PER_SESSION=
VIDEO_REQUEST_REFRESH_DIFFERENCE=
```

Do not emit raw bodies, endpoint addresses, session ids, credentials, channel
ids, or capture-specific identifiers.

## Decision rule

If the official-app trace proves repeated structurally equivalent video-media
requests after activation while our helper sends only the initial request, then:

```text
VIDEO_REQUEST_REFRESH_DIFFERENCE=PROVEN
PRIMARY_D1_CANDIDATE=VIDEO_REQUEST_LEASE_REFRESH
```

A corrective implementation still requires runtime generation rules to come
from static/protocol evidence rather than literal packet replay.

If the official app does not repeat the video request in this topology, the
third-party local-panel behavior remains only corroborating evidence and R15
UDPM maintenance remains the stronger direct official-app candidate.

## Why offline video decoding and a broken live protocol are compatible

The protocol defect under investigation is not `VIDEO_NEVER_STARTS` and not
`H264_IS_INVALID`. The existing P77 evidence proves that a successful media
window contains wrapped RTP carrying decodable H.264. A finite valid media
window is enough to save packets and reconstruct H.264 offline.

The layers are separate:

```text
Comelit signaling / media lease
-> wrapped RTP delivery
-> RTP depacketization / H264 reconstruction
-> ffmpeg decode
-> Home Assistant SDP/demux/LL-HLS/rendering
```

A lifetime/refresh defect can therefore terminate the first layer after roughly
36 seconds while the packets already received during that window remain fully
valid and decodable offline. This is not contradictory.

## Safety

```text
NO_LITERAL_REPLAY=true
NO_PRIVATE_CAPTURE_COMMITTED=true
NO_ANDROID_PROPRIETARY_ARTIFACT_COMMITTED=true
FOURTH_LIVE_ATTEMPT_JUSTIFIED=false
```
