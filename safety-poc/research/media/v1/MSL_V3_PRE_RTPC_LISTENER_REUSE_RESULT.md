# MSL-V3 — same-session pre-RTPC activation: preamble proven against the panel, RTPC acceptance still absent

TASK_ID=`COMELIT-MSL-V3-SAME-SESSION-PRE-RTPC-ACTIVATION`
BRANCH=`research/media-startup-listener-reuse-v3`
BASE_HEAD=`d0c43024174ecfe66f32fe131d3a1100e0a3f3d9` (V2 final head)
CANDIDATE_SHA=`ba8f399` (frozen; attempts 2 and 3 ran the same unmodified candidate)

The V1 and V2 result documents are untouched. No production code, entity or configuration changed.

## 1. Verdict

```text
RESEARCH_LISTENER_BOOTSTRAP (V2)                     reused, still proven
PRE_RTPC_PREAMBLE_IMPLEMENTED=true                   and live-proven against the real panel
PRE_RTPC_PREAMBLE_COMPLETE (attempt 3)               true
DEVICE_RTPC_OPEN_OBSERVED                            false
RTPC_ACCEPTANCE_IN_IDLE_SESSION                      NOT PROVEN
VIDEO_RTP / DECODABLE_VIDEO                          false
V3_MEDIA_ATTEMPTS_USED=3/4                           (attempt 4 not used, per the directive)
CLI_INVOCATIONS_USED=2/2
VARIANT_B_PROTOCOL_LIVE_PROVEN=false
RESULT=BLOCKED_WITH_PROOF
```

The V3 hypothesis is partially confirmed and partially refuted, and both halves are useful:

- **Confirmed:** the idle path *was* entering RTPC too early. With the proven pre-RTPC self-activation
  preamble restored, the panel answers the idle session — it responded to `0x0028`, to the client `0x0008`,
  sent its own `0x0008` and its own `0x0002`, and the client's structural acknowledgements were transmitted
  for each. This falsifies any reading that an idle listener session cannot get device responses at all.
- **Refuted:** restoring the full proven preamble is *not sufficient* for the panel to answer the RTPC
  exchange. After both RTPC opens, the panel sends nothing at all.

## 2. The preamble is real and reproducible

Two independent live attempts (1 and 3) produced the same ordered sequence with microsecond monotonic stamps:

```text
attempt 1   V3_0028_QUEUED 6633131 -> V3_0028_ACK_OBSERVED 6742801 -> V3_CLIENT_0008_ACK_OBSERVED 6850727
            -> V3_DEVICE_0008_OBSERVED 7447830 -> V3_DEVICE_0002_OBSERVED 7649305 -> V3_RTPC_BEGIN 7649325

attempt 3   V3_0028_QUEUED 6070722 -> V3_0028_ACK_OBSERVED 6088771 -> V3_CLIENT_0008_ACK_OBSERVED 6191820
            -> V3_DEVICE_0008_OBSERVED 6788684 -> V3_DEVICE_0002_OBSERVED 6988825 -> V3_RTPC_BEGIN 6988860
```

Attempt 3 phase decomposition (user request -> RTPC begin, microseconds):

```text
request -> 0x0028 queued          27 us
0x0028 TX -> device 0x0028 ACK   118 ms
client 0x0008 TX -> ACK          103 ms
device 0x0008 -> device 0x0002   201 ms
device 0x0002 ACK -> RTPC begin    5 us
total preamble                   918 ms   (attempt 1: 1016 ms)
```

The preamble is the user-visible cost of this path and it is ~0.9-1.0 s; it is a real protocol exchange, not
a local wait.

## 3. Where it stops — the exact first boundary

```text
MSL_B_RTPC_WINDOW_INBOUND_COUNT=0
MSL_B_RTPC_WINDOW_OPEN_SCHEMA_COUNT=0
MSL_B_RTPC_WINDOW_RESPONSE_SCHEMA_COUNT=0
MSL_B_RTPC_WINDOW_PAIRED_RESPONSE_COUNT=0
MSL_B_RTPC_WINDOW_REJECTED_COUNT=0
MSL_B_RTPC_OPEN_2_SENT=true
MSL_B_VIDEO_SINK_DATAGRAMS=0 / MSL_B_AUDIO_SINK_DATAGRAMS=0
R42_CAPABILITIES_VIDEO_REQUESTED=false
```

```text
FIRST_DIVERGENCE=DEVICE_RTPC_OPEN_NOT_OBSERVED
SECOND_BOUNDARY_FACT=NO_INBOUND_RTPC_CONTROL_FRAMES_AT_ALL (count 0, not a classification problem)
EARLY_RESPONSE_NOT_OBSERVED=true
RTPC_CONTROL_INCOMPLETE=true
CAPABILITIES_VIDEO_NOT_REQUESTED=true
CALL_TRANSACTION_REQUIRED=NOT_PROVEN
```

The RTPC window counters are the decisive new evidence: the earlier concern that an early device RESPONSE was
being dropped by an over-strict matcher is now answered — the idle path received **zero** inbound RTPC control
frames in that window, so there was nothing to mis-classify. The classification port that came out of CLI
invocation #2 is still correct and necessary, but it is not the cause of the silence.

## 4. Structural finding from source (not a live proof)

The production media path opens the media channel only after a real video-CAPABILITIES negotiation, gated by
`r36_is_capabilities_for_current_call` and `r36_capabilities_video_requested`
(`entrance_p116_r36_attached_media_trigger_transform.py:104-120`), and `r36_is_capabilities_for_current_call`
reaches `r35_call_ready`, which requires `call_transaction_alive`
(`entrance_p116_r35_attached_media_native_transform.py:437-441`). The idle path's own ring-collision guard
requires `call_transaction_alive` to be false before it will run at all
(`entrance_msl_v1_idle_listener_media_transform.py:815,980`). The two conditions are mutually exclusive in
the current architecture, which is consistent with `R42_CAPABILITIES_VIDEO_REQUESTED=false` in every live
attempt.

This is a source-level finding and is reported as such. It does **not** establish
`CALL_TRANSACTION_REQUIRED=true`: that claim would need independent evidence about the panel's acceptance,
which no attempt produced.

Allowed conclusion from this round:

```text
FULL_PROVEN_PREAMBLE_STILL_INSUFFICIENT_FOR_IDLE_SESSION_RTPC_ACCEPTANCE
```

## 5. Attempt ledger (historical, not rewritten)

```text
V3_ATTEMPT_1  protocol run      preamble complete, RTPC begin, panel silent on RTPC, no RTP
V3_ATTEMPT_2  external bootstrap abort - MSL_B_BOOTSTRAP_FAILURE_DETAIL=ComelitCloudError:remote_sdp_missing,
              RUN_CLASSIFICATION=NOT_RUN, PANEL_PROTOCOL_INTERACTION=false, PROTOCOL_VERDICT=NONE
V3_ATTEMPT_3  authorized exact-SHA re-run of ba8f399 - protocol verdict obtained (see §3)
V3_ATTEMPT_4  NOT USED
MAX_V3_ATTEMPTS=4
```

Attempt 2 was classified as `EXTERNAL_BOOTSTRAP_ABORT`, not as a protocol or media failure, and the candidate
`ba8f399` was re-run unmodified. The re-run reached the protocol boundary, so the aborted attempt did not
leave a verdict gap.

## 6. What is proven and reusable

```text
- the READY-listener bootstrap (V2) still works; the re-run reached READY on the first try
- the proven pre-RTPC self-activation preamble can be executed inside the READY listener session:
  0x0028 -> ACK -> client 0x0008 -> ACK -> device 0x0008 -> ACK -> device 0x0002 -> ACK -> RTPC begin
- the panel does answer in-session, so the idle-session premise itself holds
- reuse invariants held in every attempt that reached the protocol boundary
- the RTPC-window diagnostics (inbound / open-schema / response-schema / paired / rejected) settle, in one
  run, whether the panel answered at all
```

## 7. Safety

```text
DOOR_ACTIONS=0 / GATE_ACTIONS=0 / PHYSICAL_RING_ACTIONS=0 / AUTOMATIC_PROTOCOL_RETRY=false
SECOND_MEDIA_SESSION=false / SECOND_UPSTREAM_SESSION=false
NEW_CLOUD_NEGOTIATION_AFTER_READY=0 / NEW_ICE_BOOTSTRAP_AFTER_READY=0
NEW_PSEUDOTCP_OPEN_AFTER_READY=0 / NEW_CTPP_REGISTRATION_AFTER_READY=0
LISTENER_PROCESS_UNCHANGED=true / UPSTREAM_SESSION_UNCHANGED=true / TUNNEL_PRESERVED=true
after every attempt: production listener RUNNING=true, READY=true, ATTACHED_MEDIA_OPEN=false,
CALL_STATE=idle, residual processes none, residual sockets none, campaign fail-closed stop not required
HA_RESTART_USED=false / PRODUCTION_DEPLOYED=false / custom_components/** unchanged
```

## 8. Limits and next boundary

The open question is no longer about ordering or about the listener's ability to reuse its session. It is why
the panel does not answer the RTPC exchange for an idle (no-call) media open, while it answers every frame of
the pre-RTPC self-activation exchange. The source-level finding in §4 names a candidate mechanism (a
call-gated video-capability negotiation that the idle path structurally cannot perform), but it is not
live-proven and `CALL_TRANSACTION_REQUIRED` remains `NOT_PROVEN`.

Anything further needs a new decision about how to test the panel's acceptance of an idle media open — a new
live budget and either a different implementation strategy inside the listener process or evidence this round
does not have.
