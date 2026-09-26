# MSL-V2 — listener session reuse: bootstrap provider and Variant B live status

TASK_ID=`COMELIT-MEDIA-STARTUP-LISTENER-REUSE-V2`
BRANCH=`research/media-startup-listener-reuse-v2`
BASE_HEAD=`e75db021f42d79a6761b17e23c8102d1bf58a70f` (V1 result commit, preserved unchanged)
`MSL_V1_MEDIA_STARTUP_LATENCY_RESULT.md` is kept untouched as the historical V1 result; the V1 blocker is
not rewritten.

This document is authored by the orchestrator from live evidence collected on CT120. It reports partial
progress: one goal is proven, one is not yet.

## 1. Executor lanes

The round began with `codex-cli` as required by the task contract and was interrupted mid-child by an
account usage limit (`You've hit your usage limit ... try again at 16:57`). The partial work was preserved
in a WIP commit rather than reverted, and the operator redirected the round to the `claude-code-cli` lane;
that lane then completed the work in a series of bounded correctives. A later `claude-code-cli` session limit
(`resets 2:10pm UTC`) paused the round again. Reported per lane: `EXECUTOR=MULTI (codex-cli=1 partial,
claude-code-cli=6 correctives)`.

## 2. Goal 1 — remove `RESEARCH_HARNESS_LACKS_LISTENER_SESSION_BOOTSTRAP_PROVIDER`: **PROVEN**

A research `comelit-v4` listener now reaches its own READY state on CT120 through the
production-equivalent bootstrap, i.e. the harness reads the listener's local offer, transforms it with the
production transform, obtains an access token through the existing mechanism, performs exactly one cloud
P2P negotiation and hands the remote SDP back to the listener.

Bootstrap-only live check #5 evidence:

```text
MSL_B_BOOTSTRAP_CONFIG_SOURCE=ct120_secrets_env
MSL_B_BOOTSTRAP_OFFER_READ=true
MSL_B_BOOTSTRAP_TRANSFORM=PASS
MSL_B_BOOTSTRAP_TOKEN_SOURCE=ComelitOAuthManager.async_get_access_token
MSL_B_BOOTSTRAP_CLOUD_REQUEST_COUNT=1
MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true
MSL_B_ICE_CONNECTED=true
MSL_B_PSEUDOTCP_OPEN=true
MSL_B_CTPP_REGISTERED=true
MSL_B_RESEARCH_LISTENER_READY=true
MSL_B_BOOTSTRAP_RESULT=true
MSL_B_RUN_CLASSIFICATION=BOOTSTRAP_ONLY_COMPLETE
MSL_B_LISTENER_READY_AFTER=true
CAMPAIGN_PROCESSES_REMAINING=NONE
DOOR_ACTIONS_SENT=0 / GATE_ACTIONS_SENT=0
```

No idle-media control was created and no media was opened in that check. Production helpers are reused
(`sdp.transform_offer`, `cloud.async_negotiate_p2p`, the OAuth manager, the existing CT120 credential
mechanism); no production algorithm was duplicated. No token is printed, persisted or copied into any
artifact.

Defects the live checks isolated along the way (each fixed offline and proven before the next live check):

1. the candidate did not compile — overlay symbols used before their declarations, twice;
2. the shared clock base was destroyed by the wrapper's run-directory wipe;
3. the provider read Home Assistant config-entry storage (`/config/.storage/core.config_entries`), which
   does not exist on CT120;
4. after the cloud request, `async with ClientSession()` raised `TypeError` because CT120's bare python3 has
   no `aiohttp` and the loader's stub made `ClientSession` resolve to `object`;
5. the bootstrap-only ledger guard was applied in every live mode, which made the reserved final-validation
   media attempts impossible.

## 3. Goal 2 — Variant B live proof: session reuse **PROVEN**, media payload **NOT YET**

Two bounded Variant B media attempts were executed (attempts 10 and 11 of the 15-attempt budget). Both
proved the reuse architecture and both failed to deliver media. Evidence from the second attempt
(commit `1bf6479`):

```text
MSL_B_RESEARCH_LISTENER_READY=true
MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true
MSL_B_MEDIA_CHANNEL_ALLOCATED=true
R42_LISTENER_RTP_FORWARDING_ARMED=true
MSL_B_INITIAL_001A_STRUCTURED_FROM_SESSION_STATE=true
MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=true
MSL_B_MEDIA_ACTIVE=true

MSL_B_CLOUD_NEGOTIATION_COUNT=0
MSL_B_ICE_BOOTSTRAP_COUNT=0
MSL_B_PSEUDOTCP_OPEN_COUNT=0
MSL_B_CTPP_REGISTRATION_COUNT=0
MSL_B_MEDIA_SESSION_COUNT=1
MSL_B_SECOND_MEDIA_SESSION=false
MSL_B_SECOND_UPSTREAM_SESSION=false
MSL_B_LISTENER_PROCESS_PID before == after
MSL_B_TUNNEL_PRESERVED=true
MSL_B_RECONNECT_COUNT_DELTA=0
MSL_B_MEDIA_CLOSE_REQUESTED=true
MSL_B_MEDIA_CHANNEL_CLOSED=true
RESIDUAL_MEDIA_CHANNELS=0
MEDIA_TEARDOWN=CONFIRMED

MSL_B_VIDEO_RTP_PACKETS=0
MSL_B_AUDIO_RTP_PACKETS=0
MSL_B_SPS_COUNT=0
MSL_B_VIDEO_SINK_DATAGRAMS=0
MSL_B_AUDIO_SINK_DATAGRAMS=0
MSL_B_MEDIA_RX_ACTIVE=false
MSL_B_LISTENER_READY_AFTER=true
DOOR_ACTIONS_SENT=0 / GATE_ACTIONS_SENT=0
```

Interpretation, stated conservatively:

- The listener-reuse architecture works at the control level: an idle media open is accepted inside the
  READY listener process, executes on the existing CTPP channel with the existing single-transmit-slot
  discipline, allocates a media channel, receives a structural acknowledgement, reports media active, and
  closes media-only while the listener process, its session identity and its tunnel survive
  (`MSL_B_RECONNECT_COUNT_DELTA=0`, same process id, tunnel preserved, no residual channels).
- **No media payload has ever been received in the Variant B path**, so `VARIANT_B_PROTOCOL_LIVE_PROVEN`
  stays `false` and no latency improvement may be claimed from Variant B.
- The stage timestamps of that attempt collapsed to a single value (`B00..B04 = 5520 ms`), so the derived
  deltas and the derived `MSL_B_OLD_5S_INTERVAL=ELIMINATED` verdict from that attempt are **not** valid
  measurements. The clock-base contract itself was fixed (path `/run/comelit-msl/msl-clock-base`, reported
  value present), but the reader/writer conversion is still wrong.

## 4. The historical 5-second plateau

V1 measured `T11 CTPP registered -> T12 RTPC media open control ready ≈ 5088–5100 ms` (~55 % of
start-to-decodable). In the Variant B path CTPP registration happens during the bootstrap, **before** the
user media request, so the interval in which that plateau lived does not exist inside the media-open window:
the second attempt's derivation reports `MSL_B_OLD_5S_INTERVAL=ELIMINATED` because
`MSL_B_CTPP_REGISTRATION_COUNT=0` after READY and the corresponding interval has no counterpart.

This verdict is plausible on structural grounds but cannot be treated as a measured latency result until the
stage timestamps in the Variant B path actually advance — see §3.

## 5. Live budget

```text
LIVE_MEDIA_ATTEMPTS_USED=11/15
BOOTSTRAP_ONLY_LIVE_CHECKS_USED=5/5   (operator-extended 2 -> 3 -> 5)
RESERVED_FOR_FINAL_VALIDATION=3 attempts (13-15); operator granted +2 development attempts
```

Attempts #1-#4 were consumed by harness defects before any protocol interaction, #5 is the first measured
baseline, #6/#7 the second baseline and the rejected Variant A measurement, #8 the first Variant B attempt
(bootstrap not ready), and #9-#11 were consumed by refusals or by the two Variant B media attempts
described above. Every attempt is counted conservatively, including the ones that never exchanged a media
session with the panel.

## 6. Safety across the whole round

```text
DOOR_ACTIONS=0
GATE_ACTIONS=0
PHYSICAL_RING_ACTIONS=0
SECOND_MEDIA_SESSION=false
SECOND_UPSTREAM_SESSION=false
MEDIA_TEARDOWN=CONFIRMED
CAMPAIGN_PROCESSES_REMAINING=NONE
LISTENER_READY_AFTER=true (every attempt that reached the live boundary)
HA_PRODUCTION_DEPLOYED=false
HA_RESTART_USED=false
custom_components/**  untouched (empty diff against origin/main)
```

No literal replay, no automatic retry, no second upstream session, no secret or raw payload emitted.

## 7. Open items (current state of the round)

1. The reader/writer clock conversion must make stage timestamps strictly advance; until then Variant B
   latency is unmeasurable.
2. The reason the peer does not start streaming for an idle in-session open must be established from the
   frozen base source and the composed transforms, with the exact missing step (the proven chains perform
   more work between the peer's acknowledgement and the first received packet than the idle overlay does).
3. `VARIANT_B_PROTOCOL_LIVE_PROVEN=false`; `PRODUCTION_END_TO_END_HA_LATENCY_PROVEN=false`; no production
   deployment and no HA restart were performed, and the HA-side integration work is not started.
