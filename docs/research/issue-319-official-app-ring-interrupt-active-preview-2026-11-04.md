# Issue #319 — original Comelit Android app: incoming Ring interrupts active preview

**Date:** 2026-11-04  
**Verdict:** `PHYSICAL_OVERLAP_CAPTURE=VALIDATED_NEAR_TRANSITION` · `VIDEO_INTERRUPTED=CAPTURE_VALIDATED` · `REMOTE_PREVIEW_RELEASE_BEFORE_NEW_INVITE=CAPTURE_VALIDATED` · `TRANSPORT_REUSED=CAPTURE_VALIDATED` · `PRODUCTION_FIX=NOT_DONE`.

> This is the **new third PCAP**, not a reupload of either preceding file. The user separately observed the original app displaying video when the doorbell rang and the video then stopping. Exact physical button-press time and screen frames were not independently recorded; packet-level claims below use only capture timestamps.

## 1. Provenance, parser and privacy

- Attachment: `PCAPdroid_04_нояб._12_41_22.pcap`. SHA256: **`c6cc6cf4ca35efe25e0564bd9c025d43bb7d5253f1ce265ce078e539fc1f6ec5`**. 762,348 bytes; classic PCAP 2.4, raw IPv4 linktype 101.
- Capture **2026-11-04 09:41:25.862757–09:45:12.524163 UTC**, duration **226.661406 s**. IPv4 packets **1,863** (UDP 1,571; TCP 292), no truncated record tail.
- Independently parsed complete capture bytes. The relevant long-lived peer UDP 5-tuple has **1,424** packets: 27 STUN and 308 PseudoTCP segments plus 1,089 Viper-framed direct datagrams. PseudoTCP directional byte streams reconstructed with sequence-based duplicate/conflict checking; **3,974** client bytes and **7,919** device bytes, each one contiguous stream, no conflicting retransmit bytes.
- Viper `0x0006` channel/body frames were decoded in both the PseudoTCP control byte stream and direct datagrams. CTP records were required to match version `0x18`, exact inner length/padding and terminal marker. **52 structurally valid CTP envelopes** were extracted; no raw frames or credentials are published.
- Raw capture is **not committed to the public repository**. This report intentionally omits private IP/ports, call connection words, device/room/user IDs, CTP logical addresses, RTSP credentials, cloud tokens and raw payloads. Checksum alone does not make private traffic safe for publication.

## 2. Primary on-wire result

**The panel actively terminated the in-progress preview call and immediately initiated a distinct incoming call on the same outer CTPP/PseudoTCP transport.** The last preview video packet preceded the peer-initiated CTP `RELEASE` by approximately **181 ms**. The device-originated `INVITE` for the incoming call followed that remote `RELEASE` by approximately **130 ms** and followed the last video packet by **311 ms**.

Consequently, no RTP video continues *through* the wire-visible incoming `INVITE`. This is not a missing overlap capture: the last RTP, the **panel-side preview RELEASE**, the next **panel-side incoming INVITE**, and the **app-side media STOP** are tightly sequenced in one existing tunnel. Combined with the owner's observation of the UI, this supports a Ring-triggered preemption pattern. **It does not prove the panel's internal reason for ceasing RTP, because physical button time and device firmware state were not captured separately.**

Crucially, the client sent old-preview media teardown commands **after the new inbound INVITE had already arrived**. A safe implementation must be able to process a new call while completing the previous media transaction. It cannot assume `old MEDIAREQ STOP` must be complete before an incoming Ring is observable.

## 3. Exact timeline (UTC, independently parsed)

| Time UTC | Relative from capture start | Direction / event | Interpretation |
| --- | ---: | --- | --- |
| **09:43:36.668161** | +130.805404 s | App → panel, CTP `INVITE` (`0x0001`) | On-demand preview call A begins |
| 09:43:36.935551 | +131.072794 s | App → panel, `CAPABILITIES` (`0x0003`), local word `0x27` | Call A signaling |
| 09:43:37.319666 | +131.456909 s | Panel → app, `CAPABILITIES`, peer word `0x1b` | Call A signaling |
| 09:43:38.344649 | +132.481892 s | First inbound audio RTP PT8 | Preview audio starts |
| **09:43:38.643628** | +132.780871 s | App → panel, 26-byte `MEDIAREQ OPEN` (`0x0011`, action `0x14`) | Call A video RX setup |
| 09:43:38.984523 | +133.121766 s | First inbound video RTP PT99 | H.264 preview video starts |
| **09:43:49.554724** | +143.691967 s | Last audio RTP PT8 | Preview audio stops |
| **09:43:49.555399** | +143.692642 s | Last video RTP PT99 | Preview video stops |
| **09:43:49.736134** | +143.873377 s | **Panel → app, CTP `RELEASE` (`0x000e`) on call A** | Panel-initiated preview call release |
| **09:43:49.866117** | +144.003360 s | **Panel → app, NEW CTP `INVITE` (`0x0001`) on distinct call B** | New incoming call after just-ended preview |
| 09:43:49.866503 | +144.003746 s | App → panel, old call A media control `0x0011`, action `0x98`, 10-byte body | Old media teardown **after** new `INVITE` |
| 09:43:49.984706 | +144.121949 s | App → panel, ACK and local `CAPABILITIES` word `0x27` on call B | New call adopted on existing CTPP |
| 09:43:50.086820 | +144.224063 s | Panel → app, old call A media control action `0x98` | Old media reply overlaps new-call signaling |
| 09:43:50.232102 | +144.369345 s | App → panel, old call A `MEDIAREQ26 STOP` action `0x94` | Old video RX teardown, after incoming `INVITE` |
| 09:43:50.334536 | +144.471779 s | Panel → app, new call B `CAPABILITIES` word `0x1b` | New call signaling progresses |
| 09:43:50.437280 | +144.574523 s | App → panel, call B `ALERTING` (`0x000a`) | Standard inbound call handling |
| 09:43:50.788859 | +144.926102 s | App → panel, call B short media control (`0x0011`, action `0x18`, 10-byte body) | **Not** a 26-byte video OPEN |
| **09:44:49.245779** | +203.383022 s | App → panel, call B `RELEASE` | New call ends after approximately 59.38 s |
| 09:44:49.571156 | +203.708399 s | App → panel, call B short media control action `0x98` | Call teardown |
| 09:45:12.524163 | +226.661406 s | End of capture | Same transport had continued operating |

## 4. Media evidence

| Stream | RTP PT | Inbound packets | First | Last | Span | Within-stream sequence evidence |
| --- | ---: | ---: | --- | --- | ---: | --- |
| Audio G.711 A-law | 8 | **558** | 09:43:38.344649 | 09:43:49.554724 | 11.210 s | One observed sequence jump of 2; no duplicate seq |
| Video H.264 | 99 | **496** | 09:43:38.984523 | 09:43:49.555399 | 10.571 s | 496 consecutive RTP sequence numbers, 265 distinct RTP timestamps |

Both media tracks are **panel → app**, carried in separate Viper channels on the same peer UDP flow. No further PT99/PT8 media packets were seen **after 09:43:49.555399**, during call B, or after call B closed, within this capture.

Absence of subsequent media packets is packet-bounded. It does not demonstrate the Android UI animation or whether a cached still frame remained displayed. A 26-byte call-B `MEDIAREQ OPEN` and incoming call-B RTP were **not observed**. This one experiment does not establish that the official app could not show call-preview media in a different UI state or after explicit Answer.

## 5. Transport and ownership conclusions

- **One existing peer PseudoTCP connection** carries preview call A, remote `RELEASE`, new incoming call B, old preview `MEDIAREQ STOP`, incoming call signaling, and eventual call B `RELEASE`. No new ICE/cloud/PseudoTCP/CTPP bootstrap is identified around the Ring transition.
- **Same outer Viper CTPP control channel** for both call A and call B. **Different call-scoped CTP connection pairs**, consistent with the per-call direction `peer XOR 0x8000` relationship described in [R42](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md). Numeric IDs intentionally withheld.
- **Single owner, overlapping control transactions:** the new call B begins before old call A finishes its media-specific STOP. This is *not* evidence of simultaneous old/new video RTP or a second upstream; it is evidence of coexistence of control-plane state during media cleanup.
- The prior hypothesis that the original app must continuously preserve an existing video RTP channel is **contradicted for this observed Ring transition**: media stops and the original app proceeds with the new call while the transport remains alive.

## 6. Comparison to prior evidence

| Evidence | Preview → incoming Ring timing | Who releases preview? | What remains connected? |
| --- | --- | --- | --- |
| [2026-11-04 previous original capture](issue-319-original-app-video-then-ring-pcap-2026-11-04.md), SHA `a77103a1…` | Incoming `INVITE` **12.712 s after** preview `RELEASE`, not an overlap | **Client/app** sent previous `RELEASE` | PseudoTCP/CTPP survived across calls |
| **This new capture**, SHA `c6cc6cf4…` | Incoming `INVITE` **0.130 s after peer `RELEASE`**, **0.311 s after last video RTP** | **Panel/device** sent preview `RELEASE` | Same PseudoTCP and CTPP; new CTP call context, old media STOP in flight |
| [R42 ordinary incoming call](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md) | No active preview in that R42 initial state | n/a | Call-scoped RTPC channel / 26-byte MEDIAREQ video OPEN had been observed in a different scenario |
| [P0RING HA media-owner case](https://github.com/alexsudakov/comelit/issues/319) | RTP starvation around Ring, followed by media error / listener recovery | Cause of original helper exit not conclusively isolated | Production event path in media-owner still shadow-only |

**Most important distinction:** the earlier PCAP was a sequential user/client-closed preview followed by Ring. This PCAP shows the panel **preempting an active preview** and creating the incoming call almost immediately. Do not merge their conclusions into a generic `normal session timeout` theory.

## 7. Implications and remaining Issue #319 acceptance gates

1. **P0-A — deliver Ring:** The current Comelit on-demand helper observes `CALL_INIT` via `RingShadowController` but uses `production_emit_allowed=False`. The new official trace supports carrying Ring into the *same owner process/transport* while a preview media teardown is underway. It does **not** prove a globally unique call ID: CTP connection pair may be used as scoped transaction evidence but cannot, by itself, serve as a durable cross-owner dedup key. A one-generation/one-ring rule could lose legitimate later calls.
2. **P0-B — controlled media stop and call transition:** Zero-gap RTP continuity is not required; a predictable interruption is consistent with the official app's observed sequence. But Ring must not be lost, the media-owner must not shut down its only PseudoTCP link **before it can process the new `INVITE`**, and old-media cleanup must not trample new-call control messages. Need one serialized writer / bounded cancellation and eventual listener-ready recovery according to actual project policy.
3. **Unproven transition mechanics:** whether `P80/R27` refresh arbitration can safely coexist with `CALL_INIT`/remote `RELEASE`, how currently packaged helper handles old call release, and whether a native call-adoption path is necessary for the target Telegram UX. These are concrete candidates for a **narrow Hermes read-only inspection** *after* owner reviews this report. No speculative TX, second upstream or immediate implementation.
4. **No new physical test is inherently required to establish reference-app video interruption**; this PCAP plus owner observation supplies it. Implementing and verifying the Comelit fix remains a separate workflow. `P0_A=NOT_FIXED`, `P0_B=NOT_FIXED`, `ISSUE319=OPEN`.

## 8. Safety / publication

`PCAP_RAW_PUBLIC=false`, `NO_HERMES=true`, `NO_PRODUCTION_CODE_CHANGE=true`, `NO_LIVE_NETWORK_TX=true`, `DOOR_GATE_TESTED=false`, `NO_HA_RESTART=true`. Raw capture and credentials remain private and are not embedded in this public GitHub document.

