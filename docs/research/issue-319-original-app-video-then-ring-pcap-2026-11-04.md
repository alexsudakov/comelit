# Issue #319 — official Comelit app PCAP: preview followed by incoming call

**Date:** 2026-11-04  
**Status:** `OFFLINE_PCAP_PARSED / TARGET_OVERLAP_NOT_REPRODUCED / P0-A_NOT_FIXED / P0-B_NOT_FIXED`  
**Scope:** owner-supplied original Android-app capture, independent offline packet inspection; no Hermes, no application instrumentation, no replay, no live HA operation, no production source change.

> **Owner observation, 2026-11-04, separate from this capture:** The owner retested the original Android application and confirmed that displayed video **does interrupt during an incoming call**. This supersedes the prior user-reported *uninterrupted-video assumption* in Issue #319. It is a direct UI observation, not synchronized new packet evidence. In this existing capture, media was already stopped 12.7 s before the later inbound INVITE; these two facts must not be conflated.

## 1. Source, integrity and privacy

- Input: user-provided `PCAPdroid_04_нояб._12_06_55 (1).pcap` (filename is not a proof of capture start time).
- **SHA-256:** `a77103a1c55330b7245e33a0003b877897308efa278e48574265411327775bc5`
- Size: **3,834,193 bytes**.
- Classic PCAP v2.4, LINKTYPE_RAW_IP=101, microsecond timestamps, snaplen=32768.
- Timestamp window **2026-11-04 09:07:02.392612 UTC – 09:10:14.025823 UTC**, **191.633 seconds**.
- Total **6,759 IPv4 packets**, UDP **6,403**, TCP **356**; malformed/IP-fragment transport records **0** in this parser.
- Passive decode: IPv4/UDP → selected single peer UDP 5-tuple → PseudoTCP 24-byte header, sequence-sorted byte reassembly with retransmit conflict detection → Viper `0x0006` header → CTP envelope (length/trailer checked) → opcode/direction and observed RTP-over-Viper frame shapes. **Reassembled PseudoTCP application bytes were contiguous in both directions (3,776 client and 7,611 device bytes); 225 Viper control frames, 52 valid CTP envelopes**.
- Raw bytes, IPs, account/user identifiers, peer IDs, channel IDs, connection words, credentials, cloud/user/push tokens, home-network addresses and payloads **excluded** from this public report. The raw PCAP is **not** stored in the public repository. A private GitHub destination would be required for the user's separate raw-file archival request.

## 2. Decisive conclusion

**This capture does not contain an incoming Ring while the prior on-demand preview is still active.**

The original Android client **initiated** preview first, received ~59.5 s H.264 RTP, then **sent its own CTP RELEASE** and media STOP. A **different, device-initiated CTP INVITE** arrived **12.712 s after the previous CTP RELEASE** (12.742 s after the last video RTP).

The single underlying peer UDP 5-tuple and reconstructed PseudoTCP stream persisted across both call transactions, and both INVITEs were observed on the same CTPP control channel; however the **old media channel was already stopped** and the two call-scoped CTP connection identities were distinct. This proves the ordinary sequential handover at transport level, **not** the target live preview→Ring transition.

No RTP video or audio was identified after the inbound INVITE, and no inbound-call `MEDIAREQ26 OPEN` (`0x0011`, 26-byte body, `action=0x14`) was found in the second call; instead a **10-byte** media-request/control message was observed. This does not establish a broken call: the application was not observed answering or requesting video, and the capture alone cannot prove user-interface state.

## 3. Exact protocol timeline

All times are **UTC** and independently computed from captured packet timestamps.

| UTC timestamp | Relative time | Observed event | Classification |
| --- | ---: | --- | --- |
| 09:07:07–09:07:09 | ~+5 s | STUN/PseudoTCP and Viper control established | CAPTURE-VALIDATED |
| 09:07:45.573 | +43.181 s | Client → panel CTP `INVITE` (`opcode=0x0001`, `flags=0xc0`) | ON_DEMAND_PREVIEW_INIT |
| 09:07:45.827 | +43.434 s | Client → panel CAPABILITIES (`0x0003`, local word `0x27`) | CAPTURE-VALIDATED |
| 09:07:46.437 | +44.044 s | Panel → client CAPABILITIES (`0x0003`, peer word `0x1b`) | CAPTURE-VALIDATED |
| 09:07:47.309 | +44.916 s | Client → panel `MEDIAREQ26 OPEN`, `opcode=0x0011`, `action=0x14`, body len 26 | PREVIEW_MEDIA_OPEN |
| 09:07:47.412 | +45.020 s | First RTP audio PT8 | CAPTURE-VALIDATED |
| 09:07:47.557 | +45.164 s | First RTP video PT99 | CAPTURE-VALIDATED |
| 09:08:46.952 | +104.559 s | Last RTP audio PT8 | CAPTURE-VALIDATED |
| 09:08:47.027 | +104.634 s | Last RTP video PT99 | CAPTURE-VALIDATED |
| 09:08:47.056 | +104.664 s | **Client → panel CTP RELEASE** (`opcode=0x000e`), first transaction | CLIENT_RELEASE_PREVIEW |
| 09:08:47.344 | +104.952 s | Client → panel media control `0x0011`, `action=0x98`, body len 10 | MEDIA_TEARDOWN |
| 09:08:47.537 | +105.144 s | Client → panel `MEDIAREQ26 STOP`, `action=0x94`, body len 26 | MEDIA_STOP |
| **09:08:59.768** | **+117.376 s** | **Panel → client new CTP INVITE** (`0x0001`, `flags=0xc0`) | **INCOMING_CALL_AFTER_PREVIEW_STOP** |
| 09:08:59.789 | +117.396 s | Client ACKs the new INVITE | CAPTURE-VALIDATED |
| 09:08:59.968 | +117.576 s | Client CAPABILITIES `0x27` on the distinct second call CTP connection | CAPTURE-VALIDATED |
| 09:09:00.006 | +117.614 s | Panel CAPABILITIES `0x1b` on the second call connection | CAPTURE-VALIDATED |
| 09:09:00.362 | +117.969 s | Client ALERTING `opcode=0x000a` | CAPTURE-VALIDATED |
| 09:09:00.557 | +118.165 s | Client short media control `0x0011`, action `0x18`, 10-byte body; **not** a 26-byte video OPEN | CAPTURE-VALIDATED, media effect UNKNOWN |
| 09:09:59.018 | +176.626 s | Client RELEASE (`0x000e`) of second call | CAPTURE-VALIDATED |
| 09:09:59.332 | +176.939 s | Client media control `0x0011`, action `0x98`, 10-byte body | CAPTURE-VALIDATED |
| 09:10:14.025 | +191.633 s | Capture ends; transport/control still seen near end | CAPTURE-VALIDATED |

The second CTP INVITE is the strongest packet-level evidence for a new inbound call. The owner's physical button-press timestamp was not independently synchronized to PCAP. No Android screen recording is provided, so **user-visible video continuity is NOT_PROVEN**.

## 4. RTP proof and observed absence of overlap

Both RTP streams were received **device → phone** in the same peer flow and decoded by matching the Viper `0x0006` frame length, an 8-byte Viper prefix and RTP version 2 at offset 8.

| Track | RTP PT | Packets | First–last (relative) | Sequence continuity | Notes |
| --- | ---: | ---: | --- | --- | --- |
| Video H.264 | 99 | **2,913** | +45.164 to +104.634 s (**59.470 s**) | **no missing sequence numbers within the captured span** | 1,490 distinct RTP timestamps (~25/s); 16 SPS, 16 PPS; FU-A and slices detected |
| Audio PCMA G.711 A-law | 8 | **2,981** | +45.020 to +104.559 s (**59.539 s**) | **no missing sequence numbers within the captured span** | audio packets with same consistent stream identity |

**RTP_AFTER_NEW_INBOUND_INVITE=0** in the captured peer packets; **NEW_INBOUND_MEDIAREQ26_OPEN=0**. This is not evidence of interrupted *active* preview, because that preview ended first. Nor does it prove that a phone screen did or did not display a stale final frame.

The first call's duration from outgoing INVITE to client RELEASE was **61.483 s**; video lasted ~59.5 s. This is consistent with a possible one-minute preview lifetime but **timeout policy is not proven** by one run. A user/UI-driven closure or other native timer could have the same trace.

## 5. Transport and call identity

- One peer UDP flow contains the entire control and media sequence.
- Reassembled PseudoTCP application sequence persists across media STOP, idle gap, new incoming INVITE, and second call RELEASE.
- Both call transactions use the same outer Viper CTPP control channel, but **different** call-scoped CTP connection words. For each call, the observed direction pair follows `local = peer XOR 0x8000`, consistent with [R42](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md).
- This confirms **distinct transaction connection IDs in this sample**. Such a connection ID is **not a globally unique native physical call identity**, nor proof that retransmits and second calls can be disambiguated across arbitrary owner restarts. This limitation remains from [R11/#319](https://github.com/alexsudakov/comelit/issues/319).
- STUN Binding packets were also observed later as normal ongoing checks. No second PseudoTCP stream or new cloud/ICE setup was identified around the inbound INVITE. Absence is bounded to this capture and decoder.

## 6. Comparison with previous official captures and HA Issue #319

| Question | Earlier official A (self-activation) | Earlier official B (R42 plain inbound Ring) | New capture (A then B, **not** overlapping) | Required C (Ring during *active* preview) |
| --- | --- | --- | --- | --- |
| Self-activation media | Supported by [R52](../../safety-poc/research/media/v1/P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md) `self_activation.pcap` | Not initial state | **Proven**: CTP outgoing INVITE + MEDIAREQ26 OPEN + PT99/PT8 | Must be active at INBOUND INVITE |
| Incoming CTP INVITE | Not in original preview-only capture | [R42](../../safety-poc/research/media/v1/P116_R42_PHYSICAL_CALL_CAPTURE_AND_ATTACHED_RUNTIME.md) observed | **Proven**, but **12.7 s after preview ended** | To be captured while PT99/PT8 still active |
| Inbound video | Not applicable | R42 MEDIAREQ26 OPEN + H.264 recorded | **No RTP after inbound INVITE; no 26-byte video OPEN** | Is video reused, rebound or briefly interrupted? |
| Upstream continuity | Different sessions/eras | Listener-associated session | **One PseudoTCP flow persists sequentially** | Same outer upstream *while both intents coexist* NOT_PROVEN |
| Notification/Ring dedup | Not applicable | R54/R57 listener-owned | New CTP pair observed; identity not globally proven | Safe per-call identity and duplicate semantics still missing |
| #319 acceptance | n/a | n/a | **NOT_REPRODUCED** | **OPEN** |

In the current Comelit `1.7.32b25` media-owner source, Ring signals are still routed to shadow only (`production_emit_allowed=false`). This packet capture is of the **official application**, so it cannot prove whether our installed HA implementation is fixed.

## 7. Proposed next evidence, no server intervention

Only if the precise on-wire transition is still needed for a safe implementation, a new owner-controlled PCAPdroid capture may start **before** opening preview; open original-app video, and trigger the **one physical Ring while the video is visibly on-screen, well before ~60 s from preview start**. Capture the moment of Ring with an approximate wallclock note or screen recording. Record to at least 15–30 s after incoming INVITE and user-observed behaviour; terminate normally, no Door/Gate. Do not ask the server to open a second upstream or introduce any synthetic protocol TX.

**Acceptance gate for capture C:**
`ACTIVE_PREVIEW_RTP_AT_RING=true` must be supported by RTP timestamps bracketed around the device's new inbound INVITE, not assumed from the existence of a prior video stream. If the original app first closes or switches media before INVITE, report precise order and do not claim uninterrupted *same-channel* RTP. Separately examine whether client releases first CTP before new INVITE and whether the original app keeps a UI frame during the gap.

Until a suitable capture is available, **no proposed code modifications and no Hermes runtime changes**. A narrow Hermes read-only follow-up is justified only when analysis of a real overlapping capture leaves a specific live HA gap.

## 8. Storage/security

This report contains only protocol classifications, counts and timing. The raw PCAP may include sensitive network routes, device IDs, authentication/camera data. Do not commit it to the public Comelit repository. The owner requested GitHub archival of raw captures; this remains **PENDING_PRIVATE_DESTINATION**. No new dedicated private evidence repo was found in the owner's connected repository list; do not deposit raw data into unrelated private source repositories. Preserve original raw SHA256 and use private restricted storage once a suitable destination is available.

`RAW_PCAP_PUBLIC=false`, `CODE_CHANGED=false`, `HERMES_USED=false`, `PHYSICAL_ACTION_BY_ASSISTANT=false`, `P0_A_FIXED=false`, `P0_B_FIXED=false`.

## 9. Owner correction and revised acceptance (2026-11-04)

**Owner observation (not PCAP-proven):** The original Comelit app's user-visible video is interrupted during a call. This supersedes the 2026-10-23 report of uninterrupted viewing in the original app. It does **not** establish exactly why the panel/client stops media, or show a new overlapping `CALL_INIT` capture. Both reuploaded PCAPs are SHA256-identical to the two prior analyzed files; no new protocol trace was supplied.

**Revised acceptance for Telegram Mini App:**

- **P0-A still BLOCKED/NOT_FIXED:** Incoming Ring must be delivered while on-demand owns the single upstream; prevent same-call duplicates without suppressing a genuine second call. `frame_sha`, CTP connection ID, episode ID and owner generation alone do not prove unique physical call identity.
- **P0-B reframe:** Continuous on-demand RTP through incoming Ring is **not mandatory** if the official app itself interrupts video. The target is a deliberate, comprehensible UI switch/stop and correct call handling; no unnecessary competing upstream, native crashes, spurious `camera_stream_unavailable`/`REFRESH_FAIL_CLOSED`, silent dropped Ring, leaked media lease, or failure to restore listener. Incoming-call video, if required, still needs proven call-scoped media ownership.
- The older observation of our helper's RTP starvation with surviving control flow is still a real symptom. The updated reference-app observation does **not** retroactively prove that our stop/error handling was correct.
- A new overlapping PCAP is **optional only if** an exact video→Ring protocol transition remains necessary. Do not force another physical trial merely to prove uninterrupted video, which is no longer a requirement. A narrower server read-only inquiry may follow only a specifically identified missing runtime fact.

**Issue lifecycle note:** Issue #319 was accidentally marked CLOSED at the documentation PR #332 merge boundary even though source code did not fix either P0; it has been reopened to preserve the accurate engineering state.
