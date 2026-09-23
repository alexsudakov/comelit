# P116 / R42 — physical official-call evidence promotion and attached inbound media runtime

## Status

This round supersedes the planned R41 official-app readiness live probe.

A user-supplied physical capture of a real incoming call to the official Comelit
application was already analyzed in the immediately preceding project dialogue.
That analysis produced the exact observations below. The raw PCAP itself is not
present in this repository/workspace for R42, so R42 does **not** claim a fresh
SHA-gated byte-level re-analysis of the capture.

Evidence lineage for this document:

```text
EVIDENCE_SOURCE=user-supplied official-app physical-call PCAP
EVIDENCE_ANALYSIS=completed in preceding Comelit project dialogue
RAW_PCAP_COMMITTED=false
PCAP_SHA256=NOT_AVAILABLE_IN_R42_WORKSPACE
R42_REANALYZED_RAW_PCAP=false
```

The implementation uses only the promoted protocol facts below and never embeds
a capture-specific channel/connection id.

## Physical call observations promoted for R42

Observed call timing:

```text
incoming INVITE                 ~23:40:03.542 MSK
MEDIAREQ26 OPEN                 ~23:40:12.227 MSK
first RTP                       ~23:40:12.622 MSK
OPEN_TO_FIRST_RTP               ~395 ms
MEDIAREQ26 STOP                 ~23:41:05.510 MSK
decoded video duration          ~51.7 s
decoded video                   H.264 RTP PT99, 320x240, ~25 fps
```

Observed live identities in that one official-app call:

```text
outer CTPP channel              0x0C42
peer call CTP connection        0x4A5A
local/app call CTP connection   0xCA5A
video RX channel                0x0C4A
```

The numeric values above are evidence only, **not runtime constants**.

The call CTP direction relation is directly observed:

```text
0x4A5A XOR 0x8000 = 0xCA5A
CALL_CTP_DIRECTION_XOR_8000=CAPTURE_VALIDATED
```

This directly corroborates the R30/R32/R35 direction transform already used by
the attached-call transaction model.

The live media identity relation is directly observed:

1. the official application opens Viper media RX channel `0x0C4A`;
2. the following call-bound `MEDIAREQ26 OPEN` contains media channel id
   `0x0C4A`;
3. inbound RTP arrives on that same Viper channel;
4. `MEDIAREQ26 STOP` later contains that same media channel id.

Therefore:

```text
LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=true
MEDIAREQ26_MEDIA_CHANNEL_SOURCE=THE_ACTUAL_OPENED_VIPER_MEDIA_RX_CHANNEL_ID
MEDIA_CHANNEL_ID_EQUALS_CALL_CTP=false
MEDIA_CHANNEL_ID_EQUALS_REGISTERED_CTPP=false
```

This closes the critical R37 identity blocker. It does **not** authorize reusing
the observed literal `0x0C4A`.

## Exact observed MEDIAREQ26 OPEN

The 26-byte body observed for the physical incoming call:

```text
00 11
14
3A
00 00 00 00
4A 0C
FF FF
00 00 00 00
20 03
E0 01
40 01
F0 00
10
00
```

Promoted field mapping:

| field | value |
|---|---:|
| opcode | `0x0011` |
| action | `0x14` OPEN |
| flags | `0x3A` |
| address | zero / tunnel form |
| media channel | runtime Viper RX channel id |
| max RTP payload | `0xFFFF` |
| channel/profile dword | `0x00000000` |
| profile halfword 0 | `0x0320` = 800 |
| profile halfword 1 | `0x01E0` = 480 |
| profile halfword 2 | `0x0140` = 320 |
| profile halfword 3 | `0x00F0` = 240 |
| profile byte 4 | `0x10` |
| final byte | `0x00` |

The independent H.264 decode is 320x240, directly corroborating the latter
`0x0140 / 0x00F0` pair. R42 preserves the other observed profile values
without inventing additional semantics for them.

## Exact observed MEDIAREQ26 STOP

The physical call confirms the already reconstructed `stop_videorx` shape:

```text
opcode=0x0011
action=0x94
flags=0x02
media_channel=<same actual Viper RX channel id>
all other media/profile fields=0
```

## Viper media channel generation

P73/P74 already proved the native generic Viper allocator and RTPC channel map:

```text
candidate_id =
    ((high_halfword << 15) | low15_counter) & 0xffff

next_low15 =
    (low15_counter + 1) & 0x7fff

collision => advance to next candidate

RTPC map:
    key=10
    tag="RTPC"
    transport=1
```

The persistent helper owns its own Viper tunnel and already tracks its own
allocated channel ids. R42 therefore creates a fresh helper-local RTPC media
channel using the proven runtime allocator/open format. It does not call or
share state with the official application's `libvipcomelit.so` process and
does not attempt to predict the official application's numeric id.

R42 runtime rule:

```text
CALL_INIT captures call transaction
→ CAPABILITIES video-request trigger
→ allocate fresh helper-local Viper RTPC id
→ Viper RTPC OPEN(id)
→ call-bound MEDIAREQ26 OPEN(media_channel=id, observed profile)
→ arm existing P80 RTP demux/loopback forwarding
→ HA consumes listener-owned RTP
→ call end / capability clear / bounded SIGUSR2
→ call-bound MEDIAREQ26 STOP(media_channel=id)
→ Viper channel CLOSE(id)
→ listener continues registered
```

## Production lifecycle split

R42 intentionally keeps two media lifecycles:

### Manual/on-demand camera

Unchanged P115 path:

```text
HA camera switch
→ ComelitMediaSessionManager
→ pause persistent listener
→ separate self-activation media session
→ teardown
→ resume persistent listener
```

### Physical incoming call

New R42 attached path:

```text
persistent listener receives CALL_INIT
→ same persistent session stays alive
→ same call transaction owns MEDIAREQ26
→ helper opens one RX media channel
→ RTP forwarded locally
→ ring snapshot/recording consumes attached stream
→ STOP + channel close
→ persistent listener remains alive
```

No second cloud/P2P bootstrap and no listener pause are allowed for this path.

The existing synthetic-ring control is intentionally kept on the old P115
self-activation path because a synthetic event has no real inbound call CTP
transaction to attach to.

## Safety and retry contract

```text
ONE_MEDIA_ATTEMPT_PER_CALL_GENERATION=true
AUTOMATIC_MEDIA_RETRY=false
CAPTURE_CHANNEL_LITERAL_USED=false
SECOND_P2P_SESSION=false
SECOND_CTPP_OPEN=false
SELF_ACTIVATION_USED_FOR_PHYSICAL_RING=false
LISTENER_PAUSED_FOR_PHYSICAL_RING=false
DOOR_ACTION_SENT=false
GATE_ACTION_SENT=false
```

The old R36 placeholder path that substituted the call CTP id for the media
channel id remains historical research code, but R42 intercepts the matching
video-capability trigger first and consumes it. It must never reach network TX
for an R42-handled call.

## Separate early media observation

The same user capture also contained an earlier short session around 23:35:49,
roughly two seconds of H.264 plus RTP PT8 (G.711 A-law), with adjacent channel
ids `0x55B2/0x55B3`. R42 does not use that session as evidence for the physical
CALL_INIT transaction and does not promote those numeric ids.

## Door

No Door/Gate operation occurred in this physical-call capture. Existing Door
`UNKNOWN_OUTCOME` evidence is unchanged and remains a separate workstream.

## R41 disposition

```text
R41_LIVE_EXECUTION=SUPERSEDED
R41_LIVE_REQUIRED=false
REASON=PHYSICAL_OFFICIAL_APP_CALL_CAPTURE_ALREADY_OBTAINED
```

R41's offline artifacts may remain as historical readiness research; they are
not a prerequisite for the R42 implementation or its future physical canary.

## Next live boundary

R42 itself is development/offline verification only.

The next live operation, after build/deploy and a separate explicit approval,
is one physical incoming-call canary of **our** implementation:

```text
listener receives call
→ runtime RTPC media RX channel
→ call-bound MEDIAREQ26 OPEN
→ RTP PT99 received/forwarded
→ STOP
→ RTPC channel closed
→ listener remains READY
```

No Door/Gate action is part of that canary.
