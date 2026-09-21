# P116 R55 Post-Canary Failure Forensic

BASE_SHA=9d378883f0de916ba6767b359061cb72fe62db9a  
GENERATED_SOURCE_ANALYSED=1370e6fda24ce2a7baa6d9a1e5d12b6ac1a3534872d370ef5157e9bb453878be

## Scope and Evidence

- OBSERVED: The single physical canary emitted 10 canary evidence lines at `2026-09-21 21:00:41.981/982`, including `R54_PEER_CAPABILITY_WORD=0`, `R54_PEER_DATA_ACK_SENT=true`, and `R54_CALL_ADOPTION_FAILURE_STAGE=NONE`; it did not emit `R54_PEER_CAPABILITIES_SEEN`, `R54_PEER_VIDEO_REQUESTED`, media-open, RTP, H264, stop, close, cleanup, or ready-after lines. `.r55-evidence/live/canary-markers.txt:6` through `.r55-evidence/live/canary-markers.txt:15`; `.r55-evidence/live/canary-criteria-table.txt:13` through `.r55-evidence/live/canary-criteria-table.txt:24`.
- OBSERVED: The listener stopped later with `native_exit:6` and a bounded marker tail containing `P12_TX_QUEUE=FAIL` and final ICE/PseudoTCP true scalars. `.r55-evidence/live/canary-markers.txt:21`; `.r55-evidence/live/canary-criteria-table.txt:26`.
- PROVEN_STATIC: The analysed source hash is the real R54 build input recorded by the R54 build info. `.r55-evidence/live/R54_BUILD_INFO.txt:8`.
- PROVEN_STATIC: Exit code 6 is inherited from the frozen listener shape: both generated and frozen sources return `failed ? 6 : 0` after `g_main_loop_run`. `.r55-evidence/generated/r54-a.c:8980`, `.r55-evidence/generated/r54-a.c:9025`; `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:6449`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:6494`. Historical PRE-R54 records also include exit code 6. `docs/mvp1-entrance-canary-result.md:238`; `safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md:76`.

## R55 Corrected Premature-Publication Finding

- PROVEN_STATIC: `r54_publish_diagnostics` is defined at `.r55-evidence/generated/r54-a.c:2993` and is called from the local CALL_INIT path at `.r55-evidence/generated/r54-a.c:3028`, the peer path at `.r55-evidence/generated/r54-a.c:3050`, and the ring/capture-false region at `.r55-evidence/generated/r54-a.c:6452`.
- PROVEN_STATIC: The R54 publisher prints all fields unconditionally, including `R54_PEER_CAPABILITIES_SEEN`, `R54_PEER_CAPABILITY_WORD`, and `R54_PEER_VIDEO_REQUESTED`. `.r55-evidence/generated/r54-a.c:3004` through `.r55-evidence/generated/r54-a.c:3006`.
- PROVEN_STATIC: The ten-line live burst matches the state immediately after successful `r53_start_after_call_capture`: invite ACK, local CAPABILITIES, and local ALERTING have been queued, `local_capability_word=39`, `waiting_peer_capabilities=1`, and `call_adoption_failure_stage=R53_STAGE_NONE`. `.r55-evidence/generated/r54-a.c:2451` through `.r55-evidence/generated/r54-a.c:2485`.
- PROVEN_STATIC: Therefore the canary's `PEER_CAPABILITIES_SEEN=false`, `PEER_CAPABILITY_WORD=0`, and `PEER_VIDEO_REQUESTED=false` were captured at a moment when they could not possibly be true, so they carry NO information about the panel. The only usable negative evidence is the absence of a later publication from the peer site at `.r55-evidence/generated/r54-a.c:3050` before the process exited 13.5 s later.
- CONSEQUENCE: `PEER_CAPABILITIES_ABSENCE_PROVEN=false`. R55 must distinguish local-after-trio, after-peer-capabilities, and terminal generation-end publication phases before a second live canary can use these markers as peer evidence.

## Required Findings

1. `R54_PEER_DATA_ACK_SENT=true`

- PROVEN_STATIC: The marker is printed by `r54_publish_diagnostics` from `state->r45.inbound_ack_count > 0u`, not from a peer-specific ACK counter. `.r55-evidence/generated/r54-a.c:3007`; transform source `safety-poc/research/media/v1/entrance_p116_r54_call_adoption_listener_transform.py:126`.
- PROVEN_STATIC: `inbound_ack_count` is incremented by `r45_emit_empty_ack_for_peer_frame` for any accepted inbound frame ACK that reaches that helper. `.r55-evidence/generated/r54-a.c:2149` through `.r55-evidence/generated/r54-a.c:2187`; R45 source `safety-poc/research/media/v1/entrance_p116_r45_call_adoption_core.py:150` through `safety-poc/research/media/v1/entrance_p116_r45_call_adoption_core.py:178`.
- PROVEN_STATIC: The initial invite path calls the same helper with `CALL_INVITE_ACK`; therefore the marker can become true after the invite ACK alone, before any valid peer CAPABILITIES frame. `.r55-evidence/generated/r54-a.c:2190` through `.r55-evidence/generated/r54-a.c:2204`.
- PROVEN_STATIC: For a peer DATA ACK specifically, the frame must pass `r45_call_adoption_complete`, have exact data flags, match the current call, and have nonzero inner length before `CALL_PEER_DATA_ACK` is emitted. `.r55-evidence/generated/r54-a.c:2320` through `.r55-evidence/generated/r54-a.c:2329`; `.r55-evidence/generated/r54-a.c:2158` through `.r55-evidence/generated/r54-a.c:2163`.
- PROVEN_STATIC: The helper writer only reports `R35_<kind>_QUEUED`, and `r45_emit` returns success after invoking the writer, not after `p12_flush_tx` completes. `.r55-evidence/generated/r54-a.c:2121` through `.r55-evidence/generated/r54-a.c:2137`; `.r55-evidence/generated/r54-a.c:1910` through `.r55-evidence/generated/r54-a.c:1917`.
- PROVEN_OFFLINE: The R55 corrective test proves the generated source has this false-positive condition and no peer-only counter. `safety-poc/tests/test_p116_r55_post_canary_failure_forensic.py:27` through `safety-poc/tests/test_p116_r55_post_canary_failure_forensic.py:32`.

2. `R54_PEER_CAPABILITY_WORD=0`

- PROVEN_STATIC: `R54_PEER_CAPABILITY_WORD` is printed from `diag->peer_capability_word`. `.r55-evidence/generated/r54-a.c:3005`.
- PROVEN_STATIC: R53 state reset zeroes the diagnostics struct, including `peer_capability_word`. `.r55-evidence/generated/r54-a.c:2402` through `.r55-evidence/generated/r54-a.c:2406`.
- PROVEN_STATIC: The word is assigned only after `r36_is_capabilities_for_current_call` and `r53_peer_capability_word` both pass. `.r55-evidence/generated/r54-a.c:2530` through `.r55-evidence/generated/r54-a.c:2537`.
- OBSERVED: Because this was the local-after-trio publication, the observed zero is the reset/default value from a pre-peer snapshot, not a runtime peer value. `.r55-evidence/live/canary-criteria-table.txt:13` through `.r55-evidence/live/canary-criteria-table.txt:16`.

3. `R54_PEER_CAPABILITIES_SEEN`

- PROVEN_STATIC: The generated source contains an emission site for the marker. `.r55-evidence/generated/r54-a.c:3004`.
- PROVEN_STATIC: The marker becomes true only when the peer frame is current-call DATA, inner opcode CAPABILITIES, parseable for a word, and not already consumed. `.r55-evidence/generated/r54-a.c:2521` through `.r55-evidence/generated/r54-a.c:2537`; `.r55-evidence/generated/r54-a.c:1965` through `.r55-evidence/generated/r54-a.c:1975`; `.r55-evidence/generated/r54-a.c:2488` through `.r55-evidence/generated/r54-a.c:2498`.
- PROVEN_STATIC: The R54 listener calls the R53 peer path only after the R42 trigger prefilter has already parsed the envelope, matched current-call capabilities, and confirmed video requested. `.r55-evidence/generated/r54-a.c:6621` through `.r55-evidence/generated/r54-a.c:6629`.
- UNRESOLVED: A malformed, stale, non-video, wrong-connection, or buffered frame could traverse earlier generic PseudoTCP receive handling without reaching this marker. The absence of the marker is not an observability defect in the adoption path itself; its emission site is present and reachable, but the single live window lacks a raw-safe stage counter identifying why no accepted peer frame reached it.

4. `R54_CALL_ADOPTION_FAILURE_STAGE=NONE`

- PROVEN_STATIC: `NONE` is set after local adoption starts successfully and remains unchanged while waiting for peer capabilities. `.r55-evidence/generated/r54-a.c:2451` through `.r55-evidence/generated/r54-a.c:2485`.
- PROVEN_STATIC: The bounded R53 enum has no values for timeout/no-peer-frame, queue-busy, transport-closed, or native-exit-after-adoption. `.r55-evidence/generated/r54-a.c:2342` through `.r55-evidence/generated/r54-a.c:2351`; runtime safe-list `custom_components/comelit/runtime.py:80` through `custom_components/comelit/runtime.py:86`.
- PROVEN_STATIC: `R53_STAGE_WAITING_PEER_CAPABILITIES` is currently assigned into `call_adoption_failure_stage` as a resume/intermediate value, not strictly as a failure: duplicate same-generation start uses it at `.r55-evidence/generated/r54-a.c:2440`, and peer handling before completed local adoption uses it at `.r55-evidence/generated/r54-a.c:2527`.
- DECISION: Keep the enum value for backward bounded diagnostics in this corrective, but document the mixed contract. A corrected contract should split `call_adoption_phase` (`LOCAL_AFTER_TRIO`, `WAITING_PEER_CAPABILITIES`, `AFTER_PEER_CAPABILITIES`, `GENERATION_END`) from `call_adoption_failure_stage` (`NONE`, build/write failures, peer rejected, timeout, queue busy, transport closed). R55 implements the publication phase discriminator and terminal marker; a later contract cleanup can rename or split the R53 field with runtime allow-list changes.
- PROVEN_STATIC: `P12_TX_QUEUE=FAIL` is outside the R53/R54 failure-stage contract, produced by the generic P12 queue. `.r55-evidence/generated/r54-a.c:1330` through `.r55-evidence/generated/r54-a.c:1340`.
- PROVEN_STATIC: The contract should be extended with bounded values `PEER_CAPABILITIES_TIMEOUT`, `P12_TX_QUEUE_BUSY`, `P12_PSEUDOTCP_SEND_FAILED`, and `TRANSPORT_CLOSED_AFTER_ADOPTION`. The current enum cannot distinguish peer silence from local TX/transport failure. `.r55-evidence/generated/r54-a.c:2342` through `.r55-evidence/generated/r54-a.c:2351`; `custom_components/comelit/runtime.py:415` through `custom_components/comelit/runtime.py:418`.

5. `P12_TX_QUEUE=FAIL` and native exit 6

- PROVEN_STATIC: The only `P12_TX_QUEUE=FAIL` producer in the generated source is `p12_queue_bytes`, when `p12_tx_pending` is already true, length is zero, or length exceeds `P12_TX_MAX`. `.r55-evidence/generated/r54-a.c:1330` through `.r55-evidence/generated/r54-a.c:1340`.
- PROVEN_STATIC: Many logical writes use this queue through `p12_queue_vip_frame`: invite ACK, local CAPABILITIES, local ALERTING, peer DATA ACK, media channel OPEN, mediareq OPEN, echo replies, door writes, and other transport writes. `.r55-evidence/generated/r54-a.c:1353` through `.r55-evidence/generated/r54-a.c:1384`; `.r55-evidence/generated/r54-a.c:1877` through `.r55-evidence/generated/r54-a.c:1917`; `.r55-evidence/generated/r54-a.c:2887` through `.r55-evidence/generated/r54-a.c:2901`; `.r55-evidence/generated/r54-a.c:2927` through `.r55-evidence/generated/r54-a.c:2943`.
- UNRESOLVED: The observed marker tail does not include a P12 kind, so the failed queue subject is UNKNOWN from sanitized evidence. `.r55-evidence/live/canary-markers.txt:21`.
- PROVEN_STATIC: The send flush returns false only on non-EWOULDBLOCK PseudoTCP send error; otherwise a busy queue can remain pending without immediate send completion. `.r55-evidence/generated/r54-a.c:4229` through `.r55-evidence/generated/r54-a.c:4275`.
- PROVEN_STATIC: Several paths set `failed = TRUE` and quit the loop: writable callback failure, PseudoTCP closed callback, PseudoTCP write-packet failure, and some chained queue failures. `.r55-evidence/generated/r54-a.c:7719` through `.r55-evidence/generated/r54-a.c:7727`; `.r55-evidence/generated/r54-a.c:7731` through `.r55-evidence/generated/r54-a.c:7768`; `.r55-evidence/generated/r54-a.c:7812` through `.r55-evidence/generated/r54-a.c:7822`; `.r55-evidence/generated/r54-a.c:4134` through `.r55-evidence/generated/r54-a.c:4139`.
- PROVEN_STATIC: Queue-busy from adoption writes can directly reach `failed = TRUE` through the writable callback setter at `.r55-evidence/generated/r54-a.c:7719` through `.r55-evidence/generated/r54-a.c:7727`, because `pseudotcp_writable_cb` treats `!try_send_echo_ack() || !try_send_uaut_open() || !p12_flush_tx()` as fatal. If an adoption frame leaves `p12_tx_pending` occupied, a later `try_send_echo_ack` or `try_send_uaut_open` queue attempt can fail in `p12_queue_bytes` at `.r55-evidence/generated/r54-a.c:1330` through `.r55-evidence/generated/r54-a.c:1340`.
- PROVEN_STATIC: Queue-busy from adoption writes does not directly reach the PseudoTCP closed callback setter at `.r55-evidence/generated/r54-a.c:7731` through `.r55-evidence/generated/r54-a.c:7768`; that setter is driven by the close callback. It can only be temporally related if queue/flush behavior contributes to transport closure later.
- PROVEN_STATIC: Queue-busy from adoption writes does not directly reach the PseudoTCP write-packet setter at `.r55-evidence/generated/r54-a.c:7812` through `.r55-evidence/generated/r54-a.c:7822`; that setter requires malformed PseudoTCP wire prefix or `nice_agent_send` length failure after a flush/write attempt, not the `p12_tx_pending` guard itself.
- PROVEN_STATIC: Queue-busy from adoption writes can directly reach the chained queue-failure setter at `.r55-evidence/generated/r54-a.c:4134` through `.r55-evidence/generated/r54-a.c:4139` for chained door writes, because a queue refusal from `v4_door_queue_write` is treated as a hard failure. This is not on the R54 adoption path, but it proves the frozen main has queue-refusal-to-fatal patterns.
- CONCLUSION: `QUEUE_BUSY_CAN_REACH_FAILED_TRUE=WRITABLE_CB_DIRECT;PSEUDOTCP_CLOSED_NO_DIRECT;PSEUDOTCP_WRITE_PACKET_NO_DIRECT;CHAINED_QUEUE_FAILURE_DIRECT_NON_ADOPTION`. A TX scheduling fix or explicit flush/wait remains required before a second live canary because the R54 local trio is queued back-to-back into a single-slot P12 queue.
- UNRESOLVED: `P12_TX_QUEUE=FAIL` is temporally near exit 6, but the sanitized tail alone does not prove it directly caused `failed=true`; no labeled caller/kind or immediate failure-stage marker exists.

6. Media criteria with no line

- PROVEN_STATIC: `R42_MEDIAREQ26_OPEN_CHANNEL` is emitted only after channel-open TX completion queues mediareq OPEN and `r35_send_open` leaves `P12_TX_R35_MEDIA_OPEN` pending. `.r55-evidence/generated/r54-a.c:4161` through `.r55-evidence/generated/r54-a.c:4168`; `.r55-evidence/generated/r54-a.c:2904` through `.r55-evidence/generated/r54-a.c:2943`.
- PROVEN_STATIC: `P80_VIDEO_RTP_FORWARDING=PASS` is emitted only on the first forwarded RTP packet with payload type 99. `.r55-evidence/generated/r54-a.c:505` through `.r55-evidence/generated/r54-a.c:511`.
- PROVEN_STATIC: H264 markers are printed only in the final RTP summaries and the integration maps positive SPS/PPS/single NAL/FU-A counts to `H264_DETECTED`. `.r55-evidence/generated/r54-a.c:261` through `.r55-evidence/generated/r54-a.c:267`; `custom_components/comelit/runtime.py:439` through `custom_components/comelit/runtime.py:445`; `custom_components/comelit/media_diagnostics.py:403` through `custom_components/comelit/media_diagnostics.py:406`.
- PROVEN_STATIC: STOP and channel close markers require the media stop/close completion paths. `.r55-evidence/generated/r54-a.c:4181` through `.r55-evidence/generated/r54-a.c:4198`; `.r55-evidence/generated/r54-a.c:2978` through `.r55-evidence/generated/r54-a.c:2985`.
- PROVEN_STATIC: `R42_LISTENER_RTP_FORWARDING_ARMED=false` is emitted only when RTP is disarmed; runtime maps false to `CLEANUP_COMPLETE`. `.r55-evidence/generated/r54-a.c:562` through `.r55-evidence/generated/r54-a.c:575`; `custom_components/comelit/runtime.py:460` through `custom_components/comelit/runtime.py:461`.
- OBSERVED: None of these media criteria appeared in the live window. `.r55-evidence/live/canary-criteria-table.txt:18` through `.r55-evidence/live/canary-criteria-table.txt:24`.

7. Most probable order

- PROVEN_STATIC: The true code order for accepted CALL_INIT is capture call generation, R54 start, invite ACK enqueue, local CAPABILITIES enqueue, local ALERTING enqueue, set waiting-peer-capabilities, publish diagnostics. `.r55-evidence/generated/r54-a.c:1685` through `.r55-evidence/generated/r54-a.c:1709`; `.r55-evidence/generated/r54-a.c:2426` through `.r55-evidence/generated/r54-a.c:2485`; `.r55-evidence/generated/r54-a.c:3012` through `.r55-evidence/generated/r54-a.c:3029`.
- PROVEN_STATIC: If an accepted peer CAPABILITIES frame later arrives, the order is validate current-call capabilities, set seen/word/video, emit peer DATA ACK, then trigger R42 media open, then publish diagnostics. `.r55-evidence/generated/r54-a.c:2513` through `.r55-evidence/generated/r54-a.c:2554`; `.r55-evidence/generated/r54-a.c:3043` through `.r55-evidence/generated/r54-a.c:3051`.
- PROVEN_STATIC: Runtime logs can share one timestamp because `_observe_canary_log_marker` logs read stdout markers as criteria and de-duplicates per generation; ring parsing is batched from `_ring_lines`. `custom_components/comelit/runtime.py:420` through `custom_components/comelit/runtime.py:479`; `custom_components/comelit/runtime.py:1001` through `custom_components/comelit/runtime.py:1018`.
- PARTIAL: The observed order is CALL_INIT/local adoption diagnostics, later ring event flush, later native exit. The order among queued native stdout lines inside the same scheduler tick is static-code-derived, not timestamp-derived. The timing/order of `P12_TX_QUEUE=FAIL` relative to peer CAPABILITIES is UNDETERMINED from the single sanitized window.

8. Defect decision and corrective

- PROVEN_STATIC: An observability defect exists: `R54_PEER_DATA_ACK_SENT=true` is not trustworthy because it is derived from the invite ACK counter. `.r55-evidence/generated/r54-a.c:3007`; `.r55-evidence/generated/r54-a.c:2185` through `.r55-evidence/generated/r54-a.c:2187`; `.r55-evidence/generated/r54-a.c:2198` through `.r55-evidence/generated/r54-a.c:2203`.
- PROVEN_OFFLINE: The R55 corrective is generator-integrated in region sources, not a generated-text patch. `peer_data_ack_count` is added to R45, incremented only after `CALL_PEER_DATA_ACK`, and R54 reads that counter. `safety-poc/research/media/v1/entrance_p116_r45_call_adoption_core.py`; `safety-poc/research/media/v1/entrance_p116_r54_call_adoption_listener_transform.py`.
- PROVEN_OFFLINE: R54 now publishes `R54_DIAGNOSTICS_PHASE`, gates peer-scope fields from the `LOCAL_AFTER_TRIO` phase with `NOT_REACHED`, and emits `R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES` only in `GENERATION_END`. `safety-poc/research/media/v1/entrance_p116_r54_call_adoption_listener_transform.py`.
- PROVEN_OFFLINE: Focused tests cover (i) no peer-scope field can be published in the local phase, (ii) the peer-only ACK counter exists and is used, (iii) the generator run produces the corrected region text deterministically, and (iv) `PEER_CAPABILITIES_SEEN` can only become true through the peer validation path. `safety-poc/tests/test_p116_r55_post_canary_failure_forensic.py`.
- PROVEN_STATIC: The peer-DATA-ACK counter fix is necessary but insufficient for the round's key gate; without the phase discriminator and terminal marker, local-phase peer fields could still be misread as panel evidence.
- UNRESOLVED: No implementation defect in the peer CAPABILITIES acceptance path is proven. The reachable marker site excludes the primary suspicion that `PEER_CAPABILITIES_SEEN=false` is due to a missing emission site.

9. Hypothesis separation

- UNRESOLVED: Absence of peer CAPABILITIES is not proven causal. The same window contains `P12_TX_QUEUE=FAIL` and `native_exit:6`, and the queue failure lacks a subject label. `.r55-evidence/live/canary-markers.txt:21`.
- UNRESOLVED: A second live attempt without the R55 corrective would not prove peer behavior because the false `PEER_DATA_ACK_SENT` marker would remain ambiguous.
- PROVEN_STATIC: What would separate hypotheses: a peer-only ACK marker, queue-failure subject marker, and terminal failure-stage values for peer timeout versus TX/transport failure. These are absent from the R54 bounded enum and runtime allow-list. `.r55-evidence/generated/r54-a.c:2342` through `.r55-evidence/generated/r54-a.c:2351`; `custom_components/comelit/runtime.py:80` through `custom_components/comelit/runtime.py:86`.
- UNRESOLVED: A second live attempt after offline corrective, rebuild, and explicit release approval would prove only the next bounded observation outcome. It would not prove the original peer never responded unless the corrected peer-only marker remains false while transport stays alive and queue-failure subject markers remain absent through the peer wait window.

## Verification

- PROVEN_OFFLINE: Focused R55 tests: `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r55_post_canary_failure_forensic -v` -> Ran 6 tests; OK.
- PROVEN_OFFLINE: R53 / R43B / R43C / R45 / R46 regressions: `PYTHONPATH=safety-poc/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest safety-poc.tests.test_p116_r53_call_adoption_protocol_profile safety-poc.tests.test_p116_r43b_call_adoption_serializers safety-poc.tests.test_p116_r43c_call_adoption_host_harness safety-poc.tests.test_p116_r45_call_adoption_host_harness safety-poc.tests.test_p116_r46_post_uaut_parser_replay -v` -> Ran 66 tests; OK.
- PROVEN_OFFLINE: Parent canonical full suite command from `safety-poc/`: `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests` -> Ran 2054 tests; OK (skipped=1). This is the authoritative gate for R55; `FULL_OFFLINE_SUITE=PASS`.
- OBSERVED_SANDBOX: A noncanonical sandbox run from the repo root with `-s safety-poc/tests` observed two R29I UDP-sink errors. This is retained as an attributed sandbox observation, not the authoritative gate.
- PROVEN_OFFLINE: Static safety check: `python3 -m py_compile` on the R55 corrective and test -> PASS.
- PROVEN_OFFLINE: `git diff --check` -> clean.
- PROVEN_OFFLINE: Forbidden side-effect scan on R55 changed files -> PASS, no matches.

## Sanitization

PROVEN_STATIC: This document intentionally contains only bounded marker names, booleans, counts, line references, hashes already supplied as build identity, and enum names. It does not include raw payloads, logical addresses, CTP connection ids, tokens, auth material, or PCAP.
