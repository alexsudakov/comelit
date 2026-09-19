# P116 R39 — Official Android-app phone-side capture (documentation closure)

Round: `COMELIT-P116-R39-OFFICIAL-APP-PHONE-CAPTURE`.
Mode: authorized single live observation (one physical ring, one phone-side passive capture, one temporary
listener pause) followed by offline documentation. This document is the canonical R39 record; it is
research-only and does not change any production component.

Executor provenance: Hermes (orchestrator) authored this artifact under a one-off, explicitly bounded
operator authorization — `EXECUTOR=hermes-inline-research-closure`,
`EXECUTOR_EXCEPTION_AUTHORIZED_BY_USER=true`, `EXECUTOR_EXCEPTION_SCOPE=research-only (docs, offline
parser, offline tests, safe fixture, provenance)`. The standing rule that research/semantic
implementation goes to an external semantic executor is unchanged outside this closure.

---

## 1. What the round produced

The capture was obtained and archived, but it does **not** contain the physical call:

* the phone-side capture window is `13:56:47Z .. 14:01:05Z` (258.28 s);
* the production listener observed the only physical ring at `14:02:02.725Z` — 57 s **after** the capture
  ended, and after the listener had already been restored;
* consequently the capture holds no call setup, no media request, no RTP and no STOP;
* the official Android app never reached an app-ready state during the paused window (its own
  connectivity did not complete), so no official-app call handling could be observed at all.

No runtime OPEN value is asserted anywhere in this document: the capture did not prove one.

## 2. Canonical R39 result block

```
=== COMELIT P116 R39 OFFICIAL APP PHONE CAPTURE ===
EXECUTOR=hermes-inline-research-closure
EXECUTOR_EXCEPTION_AUTHORIZED_BY_USER=true
BASE_R37_SHA_AT_ROUND=27c4a752eba19fa11b5fee1e36aa30b92937124b
PHONE_CAPTURE_STARTED=true
PHONE_CAPTURE_COUNT=1
PHYSICAL_RING_BUDGET=1
PHYSICAL_RING_COUNT=1
RING_BUDGET_CONSUMED=true
LISTENER_PAUSE_AUTHORIZED=true
LISTENER_PAUSE_COUNT=1
FAILSAFE_ARMED=true
FAILSAFE_TRIGGERED=false
LISTENER_RESUME_COUNT=1
LISTENER_RUNNING_AFTER=true
LISTENER_READY_AFTER=true
HA_RESTARTS=0
HA_RELOADS=0
DEPLOYS=0
RESEARCH_HELPER_OPEN_SENT=0
RESEARCH_HELPER_STOP_SENT=0
CALL_INIT_OBSERVED=false
OFFICIAL_MEDIA_OPEN_OBSERVED=false
CALL_CTP_BINDING_PROVEN=false
WIRE_MEDIA_CHANNEL_VALUE_OBSERVED=false
LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false
MEDIA_CHANNEL_ID_EQUALS_CALL_CTP=UNPROVEN
MEDIA_CHANNEL_ID_EQUALS_REGISTERED_CTPP=UNPROVEN
OPEN_FLAGS_VALUE_OBSERVED=false
OPEN_FLAGS_SOURCE_PROVEN=false
CFG_THRESHOLD_VALUE_OBSERVED=false
CFG_THRESHOLD_SOURCE_PROVEN=false
PROFILE_FIELDS_VALUE_OBSERVED=false
PROFILE_FIELDS_SOURCE_PROVEN=false
MAX_RTP_PAYLOAD_VALUE_OBSERVED=false
MAX_RTP_PAYLOAD_SOURCE_PROVEN=false
TUNNEL_ADDRESS_SELECTOR_OBSERVED=false
TUNNEL_ADDRESS_SELECTOR_SOURCE_PROVEN=false
ALL_OPEN_RUNTIME_FIELDS_PROVEN=false
PLACEHOLDER_FIELDS_REMAIN=9
FIRST_RTP_OBSERVED=false
OFFICIAL_STOP_OBSERVED=false
OFFICIAL_INBOUND_MEDIA_REUSES_EXISTING_SESSION=UNPROVEN
NEW_ICE_AFTER_CALL_INIT=UNPROVEN
NEW_CLOUD_AFTER_CALL_INIT=UNPROVEN
NEW_PSEUDOTCP_AFTER_CALL_INIT=UNPROVEN
NEW_REGISTRATION_AFTER_CALL_INIT=UNPROVEN
PCAP_SHA256=5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9
RAW_PCAP_COMMITTED=false
AUTOMATIC_RETRY=false
R39_CAPTURE_HAS_RING=false
OFFICIAL_APP_READY_DURING_CAPTURE=false
R39_RESULT_DETAIL=OFFICIAL_APP_NOT_READY_AND_RING_OUTSIDE_CAPTURE_WINDOW
REQUIRED_OPERATOR_ACTION=NONE_DURING_CAPTURE
PR=NONE
MERGED=false
RESULT=BLOCKED_OPERATOR_ACTION_REQUIRED
=== END COMELIT P116 R39 OFFICIAL APP PHONE CAPTURE ===
```

(`PR=NONE` records the state when this artifact was written: the orchestrator pushes the branch and
attempts the stacked PR; the GitHub credential in use historically answers `403 createPullRequest`, in which
case the branch head is handed back and the stacked PR is opened externally.)

Classification notes (do not paraphrase away):

* `RESULT=BLOCKED_OPERATOR_ACTION_REQUIRED` is kept for enum compatibility; the true reason is carried by
  `R39_RESULT_DETAIL`.
* No answer/video button was required: no such event occurred. The operator was never blocked by a missing
  UI action; the blocking condition was the absence of an app-ready state before the ring.
* The ring budget is spent (`RING_BUDGET_CONSUMED=true`) — a further ring needs a new authorization.

## 3. Capture provenance and safe scalars

* Source: operator phone-side PCAPdroid export, one authorized capture.
* Format: classic PCAP v2.4, LINKTYPE=101 (Raw IP), snaplen 32768, microsecond timestamps, 228129 bytes.
* `PCAP_SHA256=5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9` (recomputed independently
  twice: on the received file and on the archived copy at CT120 `/root/r39-evidence/r39-phone-capture.pcap`,
  both mode 600, outside git).
* Packet count 901; IPv4 901, IPv6 0, malformed 0; outbound 521 / inbound 380; 8 trace-local remote peers
  (`R1..R8`, first-appearance aliases, never addresses); duration 258.28 s.
* Protocol split: TCP 661, UDP 240.
* Transport categories: `TCP_443_TLS_LIKE=574`, `UDP_KEEPALIVE_CANDIDATE=96`, `UDP_OTHER=92`, `DNS_TCP=60`,
  `DNS=26`, `STUN=26`, `TCP_OTHER=27`.
* Interpretation (bounded): during the paused window the phone kept a cloud/P2P-ish footprint — a sustained
  small-packet UDP keepalive flow, STUN contact, TLS to 443 and DNS — but no call control, no media request
  and no RTP. This is consistent with an app that never completed its readiness, and it is **not** evidence
  about the official inbound media path.
* Raw capture policy: not committed, not printed, not embedded; only the bounded scalars above and the
  parser/fixture in this repository.

## 4. Listener lifecycle and failsafe (pause → ring → restore)

Read-only evidence, in UTC:

| moment | fact |
| --- | --- |
| 13:46:47 | failsafe v1 armed on CT120 (transient unit) |
| 13:52:02 → 13:52:17 | routine listener reconnect seen as a DOWN sample; v1 exited `AUTO_RESTORE_SKIPPED_ALREADY_RUNNING` — v1 design defect, no pause had been issued yet |
| 13:56:02 | failsafe v2 armed (continuous-down ≥ 300 s logic; a flap can no longer disarm it) |
| 13:56:0x | pause via the existing ring-test-control webhook `{"action":"stop"}` (`http 200`); `running`, `listener_ready`, `supervisor_running` all false on two samples ~12 s apart |
| 13:56:47 | operator capture starts |
| 14:00:4x | explicit resume `{"action":"start"}` (`http 200`); all three true at t+4 s and t+14 s, `last_error=null` |
| 14:00:47 | failsafe v2 logged `FLAP_RECOVERED` (the explicit resume won) and never sent `start` |
| 14:01:05 | operator capture ends |
| 14:02:02.725 | physical ring observed by the production listener; ring media failed (`media_start_failed`, 0.0 s, native exit 6) — the known production signature |
| 14:02:48 | `Comelit ring listener READY for persistent 3300s cycle` |
| ~14:02 | failsafe disarmed (unit stopped, script removed, log retained mode 600) |

Pause/resume used only pre-existing mechanisms (the ring-test-control webhook reachable from CT120); no
wrapper was widened, no HA reload/restart, no deploy, no research helper, no self-activation.

## 5. DOOR FOLLOW-UP

Corrective forensic (read-only) for the window `14:02:45Z .. 14:03:15Z`; the operator reported pressing the
door-open button twice by hand. No new door test was run in this round and Door was not modified.

```
=== COMELIT R39 CORRECTIVE / DOOR FORENSIC ===
RESEARCH_DOOR_ACTIONS=0
DOOR_ACTIONS_BY_R39=0
OPERATOR_DOOR_ACTIONS=2
OPERATOR_DOOR_BUTTON_PRESSES_REPORTED=2
OPERATOR_DOOR_ACTION_SOURCE=manual
OPERATOR_DOOR_AUTOMATION=false
MACHINE_DOOR_OPERATION_COUNT=2
UNIQUE_DOOR_OPERATION_IDS=2
V4_DOOR_RESULT_COUNT=2
TWO_RESULT_LINES_EQUAL_TWO_OPERATIONS=PROVEN
DOOR_PROTOCOL_ACKED_COUNT=0
DOOR_PHYSICAL_OPEN_REPORTED_COUNT=0
AUTOMATIC_DOOR_RETRY=false
DOOR_READY_RACE=WEAKENED
DOOR_ROOT_CAUSE=UNRESOLVED
RESULT=PASS_READ_ONLY_FORENSIC
=== END COMELIT R39 CORRECTIVE / DOOR FORENSIC ===
```

Machine facts behind the block:

* Two terminal `V4_DOOR_RESULT` markers were observed in the covered log window: `14:02:56.781Z` and
  `14:03:01.284Z`, both `UNKNOWN_OUTCOME`.
* The production listener emits exactly one terminal door result per accepted operation
  (`v4_door_emit_result` followed by `v4_door_reset()`), so two terminal markers imply two accepted
  one-shot operations — `TWO_RESULT_LINES_EQUAL_TWO_OPERATIONS=PROVEN`.
* Both operations passed the listener-side readiness gate (`v4_listener_ready`, `v4_registered`,
  `v4_ctpp_channel_id != 0`, ring-listen stage, door stage idle, no pending TX); otherwise the listener would
  have answered `V4_DOOR_RESULT=REJECTED_NOT_READY`, which was never emitted.
* On the HA side `async_open_door` is serialized by `asyncio.Lock` and each invocation that crosses the gate
  mints one operation id and sends exactly one `SIGUSR1`; there is no automatic retry path, and the
  listener's pending flag is single-slot. A second press therefore waits and runs as a second sequential
  operation — it is not rejected and not dropped.
* Only one operation id is retained by the read-only status surface (the last one, redacted here as
  `comelit-ha-<uuid>`); per-attempt scalars such as `write_count`, `reject_stage`, `reject_response_word`,
  channel ids and requested/response channel equality are **not** exposed read-only and were cleared
  per-operation, so the exact write/reject path is unresolved.
* The actuator bridge on CT120 (the Door write path used by the bridge client) recorded no operation in that
  window, and the integration's own no-actuation proof fields stayed false
  (`network_door_action_performed`, `physical_door_action`, `p13_executed`, `p14_executed`).
* Operator-reported physical openings: 0. Protocol ACK proven: 0. Automatic retry: false.
* `DOOR_READY_RACE=WEAKENED`, not refuted: the readiness gate demonstrably held, so the "READY declared too
  early" variant is weakened; the protocol-level root cause remains unresolved and must not be declared
  proven from two presses plus the absence of a physical effect.

Future work (separate task, not executed here): reconstruct the exact post-`SIGUSR1` stage sequence,
`write_count` and the response/reject path from retained markers, offline, with a dedicated door-forensic
scope. No live door test is proposed by this document.

## 6. Offline R40 plan

See `P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md`: an app-readiness-gated, no-live design in which the
ring budget may only be spent after `OFFICIAL_APP_READY` is proven, with both currently unproven hypotheses
kept explicitly labelled. `NEXT_LIVE_AUTHORIZED=false`.

## 7. Round hygiene

* Live actions performed by the round: one authorized capture, one listener pause, one listener resume, one
  physical ring (operator), one passive pre-flight surface probe on CT120 (50 s, no TX, counted separately
  from the capture budget).
* Not performed: candidate execution, our media OPEN/STOP, synthetic ring, Door/Gate action, deploy,
  HA reload/restart, production source or binary change, merge, R30H-E.
* Raw evidence stays outside git; this repository holds only bounded scalars, hashes and the offline parser,
  fixture and tests.
* Review note: the focused test module deliberately contains three synthetic strings — an example address, a
  synthetic hexdump and a token-like word — used **only** as negative inputs to the privacy guard
  (`assert_safe_summary`). They are not captured data, not device identifiers and not credentials; they exist
  so that the guard's fail-closed behaviour is exercised.
