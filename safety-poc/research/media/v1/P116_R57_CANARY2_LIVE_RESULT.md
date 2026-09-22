# P116 R57 Canary #2 Live Result

Evidence path: `/home/hermes/comelit-r57-canary2-20260922/canary2-evidence.txt`.
No raw frames, payloads, tokens, addresses, or CTP ids are copied here.

```
CALL_ADOPTION_LIVE_PROVEN=true
PEER_CAPABILITIES_LIVE_PROVEN=true
PEER_CAPABILITY_WORD=0x0000001b
PEER_DATA_ACK_FLUSHED=true
SAME_SESSION_MEDIA_OPEN_LIVE_PROVEN=true
RTP_LIVE_PROVEN=true
H264_LIVE_PROVEN=true
USER_VISIBLE_VIDEO_DELIVERY_PROVEN=true
USER_VISIBLE_SCREENSHOT_DELIVERY_PROVEN=true
DOOR_LIVE_TESTED=false
GATE_LIVE_TESTED=false
```

## Timeline

| UTC | HA local | Event |
| --- | --- | --- |
| 2026-09-22 16:58:19.715 | 2026-09-22 19:58:19.715 | listener ready |
| 2026-09-22 16:58:54.710 | 2026-09-22 19:58:54.710 | ring event and call generation observed |
| 2026-09-22 16:58:54.916 | 2026-09-22 19:58:54.916 | media channel allocated, peer capabilities, peer ACK, media active |
| 2026-09-22 16:58:55.430 | 2026-09-22 19:58:55.430 | H264 detected |
| 2026-09-22 16:58:55.431 | 2026-09-22 19:58:55.431 | RTP received |
| 2026-09-22 16:59:01.012..16:59:20.265 | 2026-09-22 19:59:01.012..19:59:20.265 | user-visible screenshots updated |
| 2026-09-22 16:59:20.745 | 2026-09-22 19:59:20.745 | cleanup tail and STOP_SENT observed |
| 2026-09-22 16:59:30.743 | 2026-09-22 19:59:30.743 | HA stop timeout: `attached_media_stop_not_confirmed` |
| 2026-09-22 16:59:40.760 | 2026-09-22 19:59:40.760 | stream worker demux timeout after SDP removal |

## Criteria Evidence

| Criterion | Marker | Observed value | Timestamp |
| --- | --- | --- | --- |
| CALL_INIT_SEEN | `R42_CALL_GENERATION` | `1` | 2026-09-22 19:58:54.710 |
| CALL_ADOPTION_STARTED | `R54_CALL_ADOPTION_STARTED` | `true` | 2026-09-22 19:58:54.711 |
| INVITE_ACK_SENT | `R54_INVITE_ACK_SENT` | `true` | 2026-09-22 19:58:54.711 |
| LOCAL_CAPABILITIES_SENT | `R54_LOCAL_CAPABILITIES_SENT` | `true` | 2026-09-22 19:58:54.711 |
| LOCAL_CAPABILITY_WORD | `R54_LOCAL_CAPABILITY_WORD` | `39` | 2026-09-22 19:58:54.711 |
| LOCAL_ALERTING_SENT | `R54_LOCAL_ALERTING_SENT` | `true` | 2026-09-22 19:58:54.711 |
| WAITING_PEER_CAPABILITIES | `R54_WAITING_PEER_CAPABILITIES` | `true` | 2026-09-22 19:58:54.711 |
| PEER_CAPABILITIES_SEEN | `R54_PEER_CAPABILITIES_SEEN` | `true` | 2026-09-22 19:58:54.916 |
| PEER_CAPABILITY_WORD | `R54_PEER_CAPABILITY_WORD` | `27` | 2026-09-22 19:58:54.916 |
| PEER_VIDEO_REQUESTED | `R54_PEER_VIDEO_REQUESTED` | `true` | 2026-09-22 19:58:54.916 |
| PEER_DATA_ACK_ENQUEUED | `R54_PEER_DATA_ACK_ENQUEUED` | `true` | 2026-09-22 19:58:54.916 |
| PEER_DATA_ACK_FLUSHED | `R54_PEER_DATA_ACK_FLUSHED` | `true` | 2026-09-22 19:58:54.916 |
| PEER_DATA_ACK_SENT | `R54_PEER_DATA_ACK_SENT` | `true` | 2026-09-22 19:58:54.916 |
| MEDIAREQ26_OPEN_SENT | `R42_MEDIAREQ26_OPEN_CHANNEL` | bounded channel scalar | 2026-09-22 19:58:54.916 |
| H264_DETECTED | `P116_VIDEO_SPS_COUNT` | `1` | 2026-09-22 19:58:55.430 |
| RTP_RECEIVED | `P80_VIDEO_RTP_FORWARDING` | `PASS` | 2026-09-22 19:58:55.431 |
| CLEANUP_COMPLETE | `R42_LISTENER_RTP_FORWARDING_ARMED` | `false` | 2026-09-22 19:59:20.745 |
| STOP_SENT | `R42_ATTACHED_MEDIA_STOP_SENT` | `true` | 2026-09-22 19:59:20.745 |
| CHANNEL_CLOSED | `R42_MEDIA_CHANNEL_CLOSED` | not observed | UNKNOWN |

Door and Gate were not tested: `DOOR_LIVE_TESTED=false`, `GATE_LIVE_TESTED=false`.
No success claim may be made for either action surface from this canary.

Single remaining production blocker: attached-media cleanup did not emit the
native `R42_MEDIA_CHANNEL_CLOSED=true` marker, so HA never received the close
confirmation and timed out after the unchanged 10 second stop wait.
