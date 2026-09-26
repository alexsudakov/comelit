# MSL-V1 — Comelit media startup latency and listener reuse (research result)

TASK_ID=`COMELIT-MEDIA-STARTUP-LATENCY-AND-LISTENER-REUSE-V1`
BRANCH=`research/media-startup-latency-listener-reuse`
BASE_SHA=`c1f69d3ccdbe3b37aca63263970a99838909a8fa` (`origin/main` == `origin/stable/1.5.19` == tag `1.5.19`)
STATUS=`LIVE_PARTIAL` — baseline measured twice, Variant A live-tested, Variant B implemented but its live proof is blocked by a research-harness gap
LIVE_BUDGET=`8/15`

This document is authored by the orchestrator from live evidence collected on CT120. It does not
supersede any historical `Pxx` artifact and rewrites no past result.

## 1. Scope and definition of the measurement

Two architectural branches were investigated for the entrance on-demand video startup:

- **A — optimize the current cold-start path**: listener pause → separate self-activation media
  bootstrap → RTP → HA Stream/HLS.
- **B — remove the cold bootstrap**: perform an idle entrance media open *inside* the already READY
  persistent listener process, on its already-established upstream session, and close it media-only.

Measurement instrument: `MSL-V1`, a single-clock harness that reports every startup stage as
`MSL_T<NN>_<NAME>_MONO_MS` millisecond timestamps on one shared monotonic clock base
(`safety-poc/research/media/v1/entrance_msl_v1_latency_instrumentation_transform.py`,
`safety-poc/research/media/v1/ct120_run_msl_v1_baseline_live.sh`). Independent RTP witness: a UDP sink
bound to the loopback video/audio ports (17899 / 17808), separate from the helper's own counters.

`MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START`. T19..T24 (HA Stream worker, HLS part,
segment, playlist, local HLS HTTP fetch) are reported `N/A`: the restricted HA gateway exposes only
`status`/`check` (`logs` returns `COMELIT_HA_GATEWAY=DENY`), so HLS-stage timing cannot be observed
without a production deploy, which this task does not authorize.

## 2. Measured baseline

Two independent live attempts of the current production-shaped path (listener pause → separate native
media helper → cloud P2P → ICE → PseudoTCP → ViP/UAUT → CTPP → RTPC media open → `0x001A` → RTP).

| Stage | Attempt 1 (ms) | Attempt 2 (ms) |
| --- | --- | --- |
| T00 research start | 19 | 16 |
| T05 OAuth access token available | 1730 | 1590 |
| T01 listener stop requested | 1859 | 1713 |
| T02 listener runtime confirmed stopped | 2019 | 1887 |
| T03 native media helper process start | 2032 | 1900 |
| T04 local SDP offer ready | 2152 | 1941 |
| T06 cloud P2P request start | not emitted | not emitted |
| T07 cloud P2P response / remote SDP written | not emitted | not emitted |
| T08 ICE connected | 5145 | 5763 |
| T09 PseudoTCP open | 5150 | 5769 |
| T10 ViP/UAUT ready | 5335 | 5953 |
| T11 CTPP registration ready | 5516 | 6133 |
| T12 RTPC media open control ready | 10604 | 11233 |
| T13 initial `0x001A` sent | 10905 | 11533 |
| T14 device structural ACK / media acceptance | 11104 | 11734 |
| T15 MEDIA_ACTIVE | 11104 | 11734 |
| T16 first audio RTP | 11125 | 11753 |
| T17 first video RTP | 11225 | 11873 |
| T18 first SPS/PPS/IDR | 11244 | 11873 |

```text
BASELINE_ATTEMPTS=2
BASELINE_START_TO_FIRST_VIDEO_RTP_MS=9193, 9973   (T03 -> T17)
BASELINE_START_TO_DECODABLE_VIDEO_MS=9212, 9973   (T03 -> T18)
BASELINE_START_TO_HLS_READY_MS=N/A (HA gateway `logs` denied)
MEDIA_ACTIVE_DURATION_SECONDS=75 (both attempts, bounded observation)
INDEPENDENT_RTP_WITNESS=3649 video / 3795 audio datagrams (attempt 1)
HELPER_SELF_COUNTERS=P80_VIDEO_RTP_PACKETS > 3600, P116_VIDEO_SPS_COUNT=21, VIDEO_RTP_PAST_75S=true
```

### Phase decomposition (attempt 1, % of start→decodable)

| Interval | ms | Share |
| --- | --- | --- |
| T11 CTPP registered → T12 RTPC media open control ready | 5088 (attempt 2: 5100) | **55 %** |
| T04 local offer ready → T08 ICE connected (includes the cloud P2P round trip) | 2993 (attempt 2: 3822) | 33 % |
| T12 → T14 (`0x001A` sent → structural ACK) | 499 | 5 % |
| T09 → T10 ViP/UAUT | 185 | 2 % |
| T10 → T11 CTPP registration | 181 | 2 % |
| T15 → T17 MEDIA_ACTIVE → first video RTP | 121 | 1 % |
| T08 → T09 PseudoTCP open | 5 | 0.05 % |
| T17 → T18 first video RTP → first SPS/PPS/IDR | 19 | 0.2 % |

```text
BASELINE_DOMINANT_STAGE=RTPC_MEDIA_OPEN_CONTROL_PATH (T11->T12, ~5.09-5.10 s, ~55 %)
BASELINE_SECOND_STAGE=CLOUD_P2P_AND_ICE_WINDOW (T04->T08, 2.99-3.82 s, ~33 %)
BASELINE_FAST_STAGES=PseudoTCP (5 ms), ViP/UAUT (~185 ms), CTPP (~181 ms), post-ACK media (~140 ms)
```

Conclusion: the startup cost is concentrated **inside the preceding network/session establishment and
the RTPC media-open control path**, not in HA Stream/HLS, and not in the tunnel layers themselves.

## 3. Variant A — optimization of the current path

Investigated and implemented in the harness as `MSL_VARIANT_A=YES`:

- removed the pre-cloud diagnostic helper-log dump from the critical path
  (`MSL_A_DEFERRED_HOLDER_LOG=true`);
- overlapped the credential-readiness preflight with the helper's ICE gathering
  (`MSL_A_CREDENTIAL_PREFLIGHT_RC=0`);
- added the previously missing cloud-P2P boundary markers `T06`/`T07` so a future attempt can attribute
  the T04→T08 window;
- preserved the named ordering constraint `offer SDP exists before the single cloud P2P request`;
- `MSL_VARIANT_A=NO` reproduces the measured baseline path unchanged
  (`MSL_A_BASELINE_PATH_UNCHANGED=true`).

Live result (one attempt):

| Interval | Baseline | Variant A |
| --- | --- | --- |
| T04 → T08 (cloud P2P + ICE window) | 2993 / 3822 | 2959 |
| T11 → T12 (RTPC media open control path) | 5088 / 5100 | 5108 |
| **T03 → T17 (start → first video RTP)** | **9193 / 9973** | **9139** |
| T03 → T18 (start → decodable) | 9212 / 9973 | 9139 |

```text
VARIANT_A_RESULT=REJECTED
VARIANT_A_START_TO_VIDEO_MS=9139
VARIANT_A_KEY_CHANGE=deferred pre-cloud holder-log dump + overlapped credential preflight + T06/T07 markers
```

The gain (9193 → 9139 ms, ~0.6 %; 9973 → 9139 ms, ~8 % against the slower baseline) is inside the
observed attempt-to-attempt variance of the ICE/P2P window and is therefore **not** a demonstrated
improvement. Variant A is rejected as a latency solution. Its only retained value is observability
(the T06/T07 boundary markers). The two dominant intervals were not attacked within this task: both live
in the native helper's session establishment and RTPC control path, not in the orchestration layer that
Variant A could touch safely.

## 4. Variant B — idle self-activation inside the READY persistent listener

### 4.1 Investigation result (read-only, current lineage)

```text
LISTENER_HAS_RTP_RECV=true
LISTENER_HAS_MEDIA_CHANNEL_ALLOC=true
LISTENER_HAS_RTPC_MEDIA_OPEN=true
LISTENER_HAS_MEDIA_TEARDOWN_WITHOUT_TUNNEL_CLOSE=true
MEDIA_OPEN_EXECUTION_SITE=listener_process   (only the listener owns the live NiceAgent, PseudoTCP
                                              framing, v4_ctpp_channel_id, channel allocator and the
                                              single p12_tx_pending slot)
OLD_BLOCKER_1 (R29C bare mediareq26 on v4_ctpp_channel_id)      = SUPERSEDED
OLD_BLOCKER_2 (no media RX channel identity in a separate helper)= SUPERSEDED for the listener process
OLD_BLOCKER_3 (no STOP/close marker after the R57 canary)        = SUPERSEDED (R58)
OLD_BLOCKER_4 (single p12_tx_pending blocks a multi-frame open)  = STILL_VALID, engineered around by
                                                                   P76/P78 TX-completion serialization
MISSING_PRIMITIVES=idle control-file poll; READY-state idle trigger inside the listener; idle media-open
                   state machine reusing the R42 allocator + P80 forwarding driven by the P76/P78
                   self-activation sequence (not the R54 inbound-call trigger); one-shot idle media
                   STOP integrated with p12_tx_pending/R58 close semantics; normalized reuse counters
FEASIBILITY=FEASIBLE_WITH_BOUNDED_NEW_WORK
```

The old R29/R37-era blocker was **not** carried forward unchecked: three of its four components are
superseded by later findings, and the surviving one is already engineered around.

### 4.2 Implementation result

`safety-poc/research/media/v1/entrance_msl_v1_idle_listener_media_transform.py` composes the current
listener chain and adds an idle-media overlay inside the already READY listener process:

- control files `/run/comelit-p2p/msl-b-start-idle-media` and `/run/comelit-p2p/msl-b-stop-idle-media`
  (root-only `0600`), accepted only when `v4_listener_ready`, `pseudotcp_open`, `v4_registered` and
  `v4_ctpp_channel_id != 0`;
- a media-open state machine serialized through `p12_tx_completed()` (RTPC media channel open → TX
  completion → `0x001A` self-activation → acceptance), then P80 forwarding, then a media-only close with
  the R58 close semantics that preserves the tunnel;
- a fail-closed ring/call collision policy (reject-busy; never a second upstream session; no retry);
- normalized reuse counters (`MSL_B_CLOUD_NEGOTIATION_COUNT`, `MSL_B_ICE_BOOTSTRAP_COUNT`,
  `MSL_B_PSEUDOTCP_OPEN_COUNT`, `MSL_B_CTPP_REGISTRATION_COUNT`, `MSL_B_MEDIA_SESSION_COUNT`,
  `MSL_B_SECOND_MEDIA_SESSION`, `MSL_B_RECONNECT_COUNT_DELTA`, `MSL_B_TUNNEL_PRESERVED`, …), each with a
  REAL/MUTATED flip proof in the focused tests;
- no Door/Gate reachability; no new bootstrap path
  (`MSL_B_NO_NEW_SESSION_PATH=true`, `MSL_B_NO_DOOR_GATE_PATH=true`).

`MSL_B_TRANSFORM_DETERMINISTIC=true`, generated source
`fa24e6c5594c9d04eed410f3e54d08d3a27eae8dbca4a5570e19df8dad5602ca`, candidate built offline in the CT120
Alpine 3.24.1 musl chroot:
`MSL_B_MUSL_INTERPRETER_GATE=PASS`, `NO_GLIBC_DEPENDENCY=PASS`, `NO_NEW_RUNTIME_DEPENDENCY=PASS`,
candidate binary `961652ac48a24175cb0bed7c977f9605d402a16ce7f7e2044d47729436dd2668`,
`MSL_B_CANDIDATE_EXECUTED=false` in the offline build.

### 4.3 Why the live proof is blocked

The bound live runner (`safety-poc/research/media/v1/ct120_run_msl_v1_variant_b_live.sh`) starts a
*research* listener process on CT120 (the HA listener is stopped first and restored afterwards, so only
one upstream session ever exists), then triggers the idle media control. Result of the bounded attempt:

```text
MSL_B_BUILD_RC=0
MSL_B_RESEARCH_LISTENER_READY=FAIL
LISTENER_READY_WAIT_SECONDS=35
MSL_B_RUN_CLASSIFICATION=NOT_RUN
LIVE_INVOCATIONS=1
MSL_B_LISTENER_READY_BEFORE=true
MSL_B_LISTENER_READY_AFTER=true
MEDIA_TEARDOWN=UNCERTAIN
CAMPAIGN_PROCESSES_REMAINING=NONE
DOOR_ACTIONS_SENT=0 / GATE_ACTIONS_SENT=0 / SECOND_MEDIA_SESSION=false
```

The research listener's own log shows it completing only its ICE gathering
(`ICE_ATTACH_RECV=PASS`, `ICE_GATHER_START=PASS`, `ICE_GATHER=PASS`, `ICE_COMPONENTS=1`) and stopping
there — no ICE connectivity, no PseudoTCP, no CTPP, no `v4_registered`, therefore never READY.

```text
VARIANT_B_BLOCKER=RESEARCH_HARNESS_LACKS_LISTENER_SESSION_BOOTSTRAP_PROVIDER
```

In production the persistent listener's upstream session is bootstrapped by the HA runtime Python layer
(`custom_components/comelit/runtime.py`: the local offer is transformed and the cloud P2P negotiation
produces the remote SDP handed to the listener). The CT120 research harness has such a provider for the
*media helper* (the base wrapper) but **not** for the research listener. The blocker is therefore in the
harness, not in the listener process and not in the Variant B design; it is removable by adding a
listener-side bootstrapper to the research harness (mirroring the runtime's offer-transform + cloud-P2P +
remote-SDP provisioning), without any production deploy.

Per the task's stop conditions this is reported as a blocker with proof rather than being papered over:
the idle-media capability itself was never exercised on the panel, so no claim is made about Variant B's
protocol result or its latency.

## 5. Live attempt inventory (`LIVE_MEDIA_ATTEMPTS_USED=8/15`)

| # | Attempt | Question | Classification |
| --- | --- | --- | --- |
| 1 | `baseline-01` | baseline timeline | `PREFLIGHT_ABORT_NO_MEDIA_BOUNDARY` — `set -u` unbound `local` self-reference |
| 2 | `baseline-02` | baseline timeline | `PREFLIGHT_GATE_FAIL` — launcher passed a stale expected commit vs the CT120 clone HEAD |
| 3 | `baseline-03` | baseline timeline | `INSTRUMENT_ABORT_NO_PROTOCOL_INTERACTION` — wrapper shebang displaced by injected instrumentation (dash `set -o pipefail`), `WRAPPER_RC=2` |
| 4 | `baseline-04` | baseline timeline | `INSTRUMENT_ABORT_NO_PROTOCOL_INTERACTION` — shared clock base deleted by the wrapper's run-dir wipe, `WRAPPER_RC=20` |
| 5 | `baseline-05` | baseline timeline | **usable measurement** — 3649/3795 sink datagrams, full stage timeline |
| 6 | `variant_b-06` | idle media inside READY listener | `RESEARCH_LISTENER_NOT_READY` — harness lacks the listener session bootstrap provider |
| 7 | `baseline-07` | baseline reproducibility | **usable measurement** — second independent timeline |
| 8 | `variant_a-08` | optimized cold start | **usable measurement** — `T03→T17 = 9139 ms`, gain within variance |

Attempts 1–4 and 6 reached the media boundary in the runner but never exchanged a media session with the
panel; they are nonetheless counted against the budget (no `FAIL_BEFORE_VIDEO` reclassification).

## 6. Safety / closure across all live attempts

```text
DOOR_ACTIONS=0            (every attempt)
GATE_ACTIONS=0            (every attempt)
PHYSICAL_RING_ACTIONS=0
AUTOMATIC_PROTOCOL_RETRY=false
SECOND_MEDIA_SESSION=false
LISTENER_READY_BEFORE=true / LISTENER_READY_AFTER=true / LISTENER_RESTORE_OK=true (attempts 3-8)
LISTENER_RECONNECT_COUNT_DELTA=0 in the Variant B attempt; not captured in the baseline runner output
CAMPAIGN_PROCESSES_REMAINING=NONE / RTP_SINK_PORTS_REMAINING=0 (attempts 3-8)
HA_PRODUCTION_DEPLOYED=false
HA_RESTART_USED=false
```

No literal packet replay, no automatic retry, no Door/Gate path, no secret, token, raw SDP, raw RTP or
peer identifier is emitted by any artifact in this branch.

## 7. What Variant B would eliminate, and what the numbers say

If the Variant B live proof is completed, its structural claim is measured by the counters above
(`NEW_CLOUD_NEGOTIATION_AFTER_READY=0`, `NEW_ICE_BOOTSTRAP_AFTER_READY=0`,
`NEW_PSEUDOTCP_OPEN_AFTER_READY=0`, `NEW_CTPP_REGISTRATION_AFTER_READY=0`), not by latency alone. The
baseline decomposition makes the expected ceiling explicit: those four stages plus the listener
stop/start cycle account for roughly `T00..T04 + T04..T11 ≈ 5.5 s` of the `~9.2–10.0 s` start-to-video
budget, with the `~5.1 s` RTPC media-open control path additionally becoming an in-session operation
rather than a cold one. That projection is **not** a measured result and must not be used as one.

## 8. Remaining limitations

1. Variant B is implemented and builds, but its live proof is blocked; the idle-media capability has
   never been exercised on the panel.
2. Variant A is rejected as a latency solution; the two dominant intervals (ICE/P2P window, RTPC media
   open control path) were not attacked.
3. One measured baseline attempt per configuration is not a statistical sample; the ICE/P2P window moved
   by ~0.8 s between the two baseline attempts, which is larger than the Variant A gain.
4. `T06`/`T07` were added during Variant A and therefore are absent from both baseline attempts; the
   cloud-P2P and ICE portions of `T04→T08` cannot be separated in the baseline data.
5. HLS stages (`T19..T24`) are unobservable with the current restricted HA gateway.
6. In all live attempts the R65 production helper has no native self-timeout, so the runner's outer bound
   (`WRAPPER_RC=124`) terminated it and the helper's late markers had to be read from the helper log on
   CT120. This is a harness observability gap, not a protocol result.

## 9. Production deployment status and rollback

```text
PRODUCTION_HA_DEPLOYED=false
HA_RESTART_USED=false
custom_components/comelit touched by this research: NO
```

Everything in this branch is research/offline tooling plus one new native candidate. No production
integration file, no packaged binary and no HACS-visible artifact was modified, so rollback is simply not
deploying this branch. Any future productionization of Variant B would additionally require the HA-side
integration work listed in the investigation (`runtime.py`, `supervisor.py`, `media_session.py`,
`media_transport.py`, `camera.py`, `media_diagnostics.py`) behind a feature gate, plus a reviewed native
rebuild and a separate deploy/restart approval.

## 10. Next step to unblock Variant B

Add a **listener-side session bootstrap provider** to the research harness: mirror the HA runtime's
offer-transform + cloud P2P + remote-SDP provisioning for a research `comelit-v4` process, so the
research listener can reach its own READY state on CT120. Then re-run the bounded Variant B attempt and
read the reuse counters. This is bounded work inside the existing research scope; no new credential,
Door/Gate action, physical intercom action or production deployment is required.
