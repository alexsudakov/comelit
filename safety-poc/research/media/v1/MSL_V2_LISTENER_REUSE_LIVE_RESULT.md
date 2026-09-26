# MSL-V2 — listener session reuse: bootstrap provider proven, Variant B blocked with proof

TASK_ID=`COMELIT-MEDIA-STARTUP-LISTENER-REUSE-V2`
BRANCH=`research/media-startup-listener-reuse-v2`
BASE_HEAD=`e75db021f42d79a6761b17e23c8102d1bf58a70f`  (V1 result commit — unchanged)
`MSL_V1_MEDIA_STARTUP_LATENCY_RESULT.md` stays untouched as the historical V1 result. No historical artifact
is rewritten.

## 1. Executive summary

```text
RESEARCH_LISTENER_READY_PROVEN=true          (the V1 harness blocker is removed)
VARIANT_B_PROTOCOL_LIVE_PROVEN=false         (no media payload was ever received)
VARIANT_B_RESULT=BLOCKED_WITH_PROOF
LIVE_MEDIA_ATTEMPTS_USED=13/15               (2 attempts remain reserved for final validation, unused)
BOOTSTRAP_ONLY_LIVE_CHECKS_USED=5/5
PRODUCTION_HA_DEPLOYED=false / HA_RESTART_USED=false / custom_components untouched
```

Variant B reaches the architecture it promised — an idle media open executed inside the already-READY
persistent listener, in its existing session, with a media-only close and every reuse invariant at zero —
but it never receives a single media packet. The first proven boundary is stated in §6.

## 2. Executor lanes

```text
EXECUTOR=MULTI
codex-cli          1 partial child, interrupted by an account usage limit (work preserved in a WIP commit)
claude-code-cli    6 bounded correctives, one of them refused once by a provider safety classifier and
                   re-issued with a reworded brief
codex-cli          forensics + one corrective, then exhausted (usage window to the next day)
claude-code-cli    final implementation child
```

A claude-code session limit and a codex usage limit each paused the round; both were resumed on the
documented lane-fallback pattern rather than by weakening any requirement. One orchestrator defect was found
and fixed: the shared context handed to one codex child named the V1 worktree, so its edits were refused as
out-of-sandbox and it correctly reported a blocker instead of editing the wrong tree.

## 3. Goal 1 — the harness bootstrap gap: PROVEN

A research `comelit-v4` listener on CT120 reaches its own READY state through the production-equivalent
bootstrap: the harness reads the listener's local offer, transforms it with the production transform, obtains
an access token through the existing mechanism, performs exactly one cloud P2P negotiation and hands the
remote SDP back.

```text
MSL_B_BOOTSTRAP_CONFIG_SOURCE=ct120_secrets_env
MSL_B_BOOTSTRAP_OFFER_READ=true / MSL_B_BOOTSTRAP_TRANSFORM=PASS
MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token
MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1 / MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true
MSL_B_ICE_CONNECTED=true / MSL_B_PSEUDOTCP_OPEN=true / MSL_B_CTPP_REGISTERED=true
MSL_B_RESEARCH_LISTENER_READY=true / MSL_B_RUN_CLASSIFICATION=BOOTSTRAP_ONLY_COMPLETE
```

Production helpers are reused (`sdp.transform_offer`, `cloud.async_negotiate_p2p`, the OAuth manager, the
existing CT120 credential mechanism). No token is printed, persisted or copied; no production algorithm is
duplicated; no captured SDP is replayed.

Booster-only live checks were consumed on: a missing provenance parameter, a candidate that did not compile
(twice), a credential source pointing at Home Assistant storage that does not exist on CT120, `aiohttp`
`ClientSession` stubbed to `object` on a bare python3, and a bootstrap ledger guard applied in every live
mode. Each was fixed offline with tests before the next live check.

## 4. Baseline (V1, unchanged) and what Variant A contributed

```text
BASELINE_T03_TO_FIRST_VIDEO_MS      9193, 9973      (two independent attempts)
BASELINE_T03_TO_DECODABLE_MS        9212, 9973
BASELINE_DOMINANT_STAGE             T11->T12 CTPP registered -> RTPC media open control ready ≈ 5088-5100 ms (~55%)
SECOND_STAGE                        T04->T08 cloud P2P + ICE = 2993 / 3822 ms (~33%)
FAST_STAGES                         PseudoTCP ~5 ms, ViP/UAUT ~185 ms, CTPP ~181 ms, ack->first video ~140 ms
```

Variant A (cold-path optimizations) measured `9139 ms`, inside the run-to-run spread of the baseline
(`9193/9973`), and is therefore `REJECTED` as a latency improvement. Its value was observability: the T06/T07
cloud markers and moving the holder-log dump off the critical path.

## 5. Variant B — what was implemented and what it proved

Implemented candidate (in-tree, offline-verified): an idle self-activation media open executed inside the
already-READY listener process via a one-shot control file, using the existing RTPC media-open path, the
existing single-transmit-slot discipline, and a media-only close.

Structural results (attempts 10, 11, 13 — the architecture is consistent across all three):

```text
MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true
MSL_B_MEDIA_CHANNEL_ALLOCATED=true
R42_LISTENER_RTP_FORWARDING_ARMED=true
MSL_B_CLOUD_NEGOTIATION_COUNT=0 / MSL_B_ICE_BOOTSTRAP_COUNT=0
MSL_B_PSEUDOTCP_OPEN_COUNT=0 / MSL_B_CTPP_REGISTRATION_COUNT=0
MSL_B_MEDIA_SESSION_COUNT=1 / MSL_B_SECOND_MEDIA_SESSION=false / MSL_B_SECOND_UPSTREAM_SESSION=false
MSL_B_LISTENER_PROCESS_PID before == after
MSL_B_TUNNEL_PRESERVED=true / MSL_B_RECONNECT_COUNT_DELTA=0
MEDIA_TEARDOWN=CONFIRMED (attempts 10/11) / UNCERTAIN (attempt 13, see §6)
DOOR_ACTIONS_SENT=0 / GATE_ACTIONS_SENT=0 / PHYSICAL_RING_ACTIONS=0
```

No media payload in any attempt:

```text
MSL_B_VIDEO_RTP_PACKETS=0 / MSL_B_AUDIO_RTP_PACKETS=0 / MSL_B_SPS_COUNT=0
MSL_B_VIDEO_SINK_DATAGRAMS=0 / MSL_B_AUDIO_SINK_DATAGRAMS=0
```

### Rejected hypotheses

- `1bf6479` (media-active published on local transmit completion, no device acknowledgement) was rejected as
  an acceptance signal: `MEDIA_ACTIVE=true` with `VIDEO_RTP_PACKETS=0` is not a successful media open.
  Acknowledgement gating is kept permanently.
- The receive path was initially armed lazily on the first received packet; it was moved to the arm path and
  then, per the forensic answer, back to **after** the device acknowledgement — matching the proven order.
- Matcher strictness was tested: no `0x1800`/`body_len 32`/matching-`request_id` frame was ever observed
  after `0x001A`, so no matcher predicate was the cause (`Q5=NONE_OBSERVED`). Address-role orientation was
  not proven inverted.
- `CALL_TRANSACTION_REQUIRED` was **not** concluded. The evidence does not prove that a call transaction is
  required, and it is reported as `NOT_PROVEN`.

### First semantic divergence (forensic pass, offline)

After the RTPC media channel open completes, the proven cold path runs *device RTPC open → client response →
device responses → client `0x000A` → post-000A ack cycle* before `0x001A`. The idle path queued `0x001A`
straight from local open completion (`entrance_msl_v1_idle_listener_media_transform.py:490-519`), so the
device had no reason to emit the structural acknowledgement and no payload ever followed.

That sequence was then implemented in the idle path (channel open transmit, second open transmit, wait for
device open, client response, wait for device responses, client `0x000A`, wait for device `0x000A`, device-000A
acknowledgement transmit, wait for device ack, only then the self-activation transmit), with a flip-proven
test per step, media-active still acknowledgement-gated, the receive path registered after the
acknowledgement, and the reuse counters untouched.

## 6. Attempt 13 and the exact proven boundary

Attempt 13 (code `7b04b67`, generated source `c5d6be84…`) is the first attempt in which the idle path walked
the proven pre-`0x001A` sequence. Microsecond stage resolution now works
(`B01A_RTPC_OPEN_1_SENT_MONO_US=5686334`, `B02_..._READY_MONO_US=5686339`, 5 µs apart).

```text
MSL_B_RTPC_OPEN_2_SENT=true
MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_US=5686339
(no B03A_001A_QUEUED, no B03B_001A_TX_COMPLETED, no B04_DEVICE_ACK_OBSERVED)
MSL_B_VIDEO_RTP_PACKETS=0 / MSL_B_VIDEO_SINK_DATAGRAMS=0
```

Precise first proven boundary: **after the idle path sent both RTPC open requests and reached control-ready,
the device never produced the OPEN/RESPONSE that the proven sequence waits for**, so the state machine
stopped at `WAIT_DEVICE_OPEN`, `0x001A` was (correctly) never queued, no acknowledgement was observed and no
payload followed.

```text
VARIANT_B_FIRST_BOUNDARY=DEVICE_OPEN_NOT_OBSERVED_AFTER_RTPC_OPEN_IN_IDLE_PATH
VARIANT_B_BOUNDARY_CATEGORY=OTHER_EXACT_BOUNDARY
DEVICE_ACK_NOT_OBSERVED=true                     (the 001A acknowledgement was never reached)
PANEL_REJECTED_IDLE_MEDIA_SEQUENCE=NOT_PROVEN    (the panel did not answer, but rejection is not proven)
REQUIRED_CALL_TRANSACTION=NOT_PROVEN
MEDIA_ONLY_TEARDOWN=PASS (attempts 10/11) / UNCERTAIN (attempt 13 - the open never completed)
```

Note the ordering: attempt 13 stalled **earlier** in the protocol than attempts 10/11 (which reached a local
open completion). The new sequence is therefore a change of the observed boundary, not an improvement in
outcome; the honest statement is that the idle path now asks the device for the same exchange the proven path
asks for, and the device does not answer it.

## 7. Safety across the whole round

```text
DOOR_ACTIONS=0 / GATE_ACTIONS=0 / PHYSICAL_RING_ACTIONS=0
SECOND_MEDIA_SESSION=false / SECOND_UPSTREAM_SESSION=false
no literal packet replay / no automatic retry / no token or raw payload emitted
HA_PRODUCTION_DEPLOYED=false / HA_RESTART_USED=false
custom_components/**  unchanged (empty diff against origin/main)
after every attempt: production listener RUNNING=true, READY=true, ATTACHED_MEDIA_OPEN=false,
                     CALL_STATE=idle, no residual campaign processes or sockets on CT120
```

`MEDIA_TEARDOWN=UNCERTAIN` in attempt 13 is reported as such rather than rounded up to a pass; the
production-side state was independently verified clean after it, which is why no fail-closed campaign stop
was declared.

## 8. Live attempt ledger

```text
LIVE_MEDIA_ATTEMPTS_USED=13/15
  #1-#4   harness defects, no media boundary reached (conservatively counted)
  #5      first measured baseline
  #6      second baseline
  #7      Variant A measurement -> REJECTED
  #8      first Variant B attempt, research listener not ready
  #9      refusal at a precondition (no media session started)
  #10     Variant B media attempt - arming stage not started, no packets
  #11     Variant B media attempt - arming confirmed, MEDIA_ACTIVE reported, no packets
  #12     Variant B media attempt - acknowledgement gating armed, no packets
  #13     Variant B media attempt - proven pre-001A sequence walked, device OPEN not observed
  #14,#15 UNUSED - reserved for two independent final validations; no working candidate exists to validate
BOOTSTRAP_ONLY_LIVE_CHECKS_USED=5/5
```

## 9. What is not done / next approval boundary

```text
VARIANT_B_PROTOCOL_LIVE_PROVEN=false
PRODUCTION_END_TO_END_HA_LATENCY_PROVEN=false        (HA Stream/HLS stages never observable without a deploy)
no protocol latency comparison is claimed            (no Variant B payload exists to measure)
PRODUCTION_IMPLEMENTATION_READY=false                (no production integration change; custom_components untouched)
production deploy and HA restart were never requested or performed
```

The remaining question is why the device does not answer the RTPC open exchange when it arrives in an
established, otherwise healthy listener session. That is a protocol question about the device's acceptance
of an idle open, not a harness question, and answering it would need either a different implementation
strategy inside the listener process or evidence this round does not have.

## 10. Rollback implications

Nothing to roll back: no production code, entity, integration or configuration changed. The branch carries
research tooling, the instrumented candidate and this document only. The reusable assets for a future round
are: the listener bootstrap provider (production-equivalent, proven), the semantic diagnostics counters and
ack-reject counters, the microsecond stage clock contract, and the documented boundary above.
