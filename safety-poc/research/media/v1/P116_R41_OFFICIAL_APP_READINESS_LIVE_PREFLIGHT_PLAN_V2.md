# P116 R41 v2 — Official-App Readiness Live Preflight (contract, no runner, no live execution)

Status: **document only**. `NEXT_LIVE_AUTHORIZED=false`. Provenance: this is a successor to
`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md` (R41 v1), produced by round R40G
(`P116_R40G_RUNTIME_PATH_AND_READINESS.md`, base `73ef4904155951d35b78b7c791dcab1978966782`). R41 v1 is
**not** rewritten and remains a valid historical record of the contract as it stood before R40F/R40G's raw
`dex7/8/9` evidence existed. This document supersedes it operationally — a future live round should follow
v2, not v1 — because v1 was written against the abstract `OperatorAppState.OPERATOR_CONFIRMED_USABLE`
judgement call and R40's model, before R40F proved the concrete `ToolbarDeviceConnectionStatus.CONNECTED`
signal and R40G traced the dex7/dex9 runtime relationship and the mBound/silent-staleness caveats that a
faithful preflight contract must now state explicitly.

## 1. Purpose

Unchanged from v1: sample `OFFICIAL_APP_READY` **without ever spending the physical-ring budget**, so a
future, separately authorized live round can decide up front whether a ring attempt is worth attempting. A
`PASS` here is evidence for a subsequent authorization request, not an authorization itself.

## 2. Preconditions

* A fresh, separate, explicit operator authorization for this specific preflight attempt (no past approval
  carries forward — unchanged from v1).
* Production listener confirmed `READY` before the attempt starts.
* Bounded listener failsafe armed (existing autoreset path, continuous-down logic; R39/R40 cite its
  threshold as 300 s continuous-down).
* An explicit, operator-approved `OPERATIONAL_APP_READY_TIMEOUT_SECONDS` value chosen at authorization time.
  Per R40G CHILD G, `APP_READY_PROTOCOL_TIMEOUT_SECONDS` stays `UNPROVEN` from static evidence — this value
  is a **safety bound**, never an estimate of expected VIP-registration latency, and must be chosen strictly
  below the 300 s failsafe threshold with margin, so the failsafe's own autonomous action cannot race this
  contract's own "restore listener first" step (SECTION 3 step 8).
* Confirmation that the target unit is the **legacy VIP-tunnel system class** (`Systems.isLegacySystem()` /
  `apartmentId == null` in official-app terms) — R40G CHILD A proved the `RegisterStatus`/toolbar chain this
  contract samples only gates that system class; a cloud/apartmentId-registered system's `CallStart` pipeline
  is a different, push-triggered mechanism this contract does not cover. This project's on-premise
  CT120/CT122 hardware matches the legacy class.

## 3. Contract (steps)

```text
1. listener state before          -> must be READY on >=2 samples; if not, ABORT before any pause
2. failsafe armed                 -> existing continuous-down mechanism, unchanged
3. bounded pause if required      -> pause only for the minimum window needed to sample readiness;
                                      confirmed on >=2 samples (running=false, listener_ready=false,
                                      supervisor_running=false), same evidence shape as R39 section 4
4. operator opens the official app's door-entry screen (DoorEntryContentFragment)
5. readiness sampled               -> operator reads the literal VIP toolbar connection icon on that exact
                                       screen and reports it as an OfficialAppUiConnectionState value
                                       (UNKNOWN / NOT_CONNECTED / CONNECTING / CONNECTED) -- not an abstract
                                       judgement call. This is the exact ToolbarDeviceConnectionStatus label
                                       R40F CHILD B proved is bound 1:1 to ComelitStatus.RegisterStatus.
6. optional machine corroboration -> if a future round has implemented the CHILD C logcat reader
                                      (adb logcat -s ComelitStatus, filtering "VIP REGISTER CHANGED ...
                                      -> REGISTERED"), report registration_ready_seen=true/false alongside
                                      the UI sample; otherwise pass None. Per R40G CHILD D, this is NOT an
                                      independent signal from the UI read (same ComelitStatus field) --
                                      it protects against operator/tooling transcription error, not against
                                      a silently stale toolbar.
7. evaluate                       -> feed {system_class=LEGACY_VIP, ui_state, listener_state=PAUSED,
                                      ring_budget_available=false, registration_ready_seen} into
                                      entrance_p116_r40g_official_app_readiness_model.evaluate_readiness_v2
8. bounded timeout                -> OPERATIONAL_APP_READY_TIMEOUT_SECONDS from SECTION 2; on timeout or
                                      an UNKNOWN/NOT_CONNECTED-at-timeout sample: proceed to step 9 as
                                      BLOCKED_APP_NOT_READY
9. NO physical ring                -> no ring is ever placed by this preflight, regardless of the sampled
                                      value or evaluate_readiness_v2's output
10. restore listener               -> unconditionally, regardless of SUCCESS/FAIL/TIMEOUT, first action
                                      after step 7/8/9 conclude
11. verify READY                   -> confirm listener_ready/running/supervisor_running all true again
                                      before touching the failsafe
12. disarm failsafe                -> only after step 11 is confirmed
13. report                         -> BLOCKED_APP_NOT_READY or PASS_APP_READY_PREFLIGHT (SECTION 5)
```

## 4. Why the preflight can never consume the ring budget

`entrance_p116_r40g_official_app_readiness_model.evaluate_readiness_v2` is called with
`ring_budget_available` fixed to `false` for the entire attempt (a code-level invariant a future runner must
enforce, not merely document). Delegating to R40F's unmodified `evaluate_readiness`, the best possible
outcome is `official_app_ready="true"`, `physical_ring_allowed=False`
(`reason="app_ready_but_ring_budget_unavailable..."`). No physical ring is ever placed regardless of the
sampled state. This is intentional redundancy with SECTION 3 step 9, not a substitute for it.

## 5. Outcomes

* **`BLOCKED_APP_NOT_READY`** — the operational timeout elapsed, the sampled `ui_state` was
  `NOT_CONNECTED`/`CONNECTING`/`UNKNOWN` at timeout, `system_class` could not be confirmed `LEGACY_VIP`, or
  `registration_ready_seen` was explicitly sampled `False` (machine signal contradicts a `CONNECTED` UI
  read — fail-closed per R40F CHILD H's original precedence, unchanged). `RING_BUDGET_CONSUMED=false`.
* **`PASS_APP_READY_PREFLIGHT`** — the operator reported `CONNECTED` while the listener was confirmed
  `PAUSED` and the system class was confirmed `LEGACY_VIP`, inside the timeout, and (if sampled)
  `registration_ready_seen` was not `False`. `RING_BUDGET_CONSUMED=false` (SECTION 4). This outcome does
  **not** authorize R42 or any subsequent live-ring round automatically — it remains evidence a human
  operator can use to decide whether to separately authorize a bounded, one-ring live round, not a
  self-authorizing trigger. It also does **not** rule out the CHILD D silent-transport-staleness case: a
  `PASS` here means the app's own last-known state was `CONNECTED` at sample time, not that the underlying
  VIP tunnel is provably still alive at ring time.

In both outcomes: one pause, one resume, no retry, no synthetic ring, no Door/Gate action,
`NEXT_LIVE_AUTHORIZED=false` until a new explicit operator authorization is given for a ring-spending round
specifically.

## 6. What this document does not authorize

No runner script exists for this contract in this round; none is created by R40G. No live execution is
authorized. A future round that implements the runner must independently re-derive its own
`LIVE_AUTHORIZED`/`CANDIDATE_HELPER_EXECUTED`-style gates before any live step, per the same discipline
R27–R30H, R40 and R40F already established for this repository's other live-candidate runners, and must
implement the CHILD C logcat reader (if it chooses to populate `registration_ready_seen` at all) as a
read-only `adb logcat` filter — no APK modification, no root, no Frida/Xposed, per R40G CHILD C's explicit
preference for the least invasive available mechanism.

```text
=== COMELIT P116 R41 V2 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
BASE_R40G_DOC=P116_R40G_RUNTIME_PATH_AND_READINESS.md
SUPERSEDES=P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md (v1, unchanged, not rewritten)
GATE_MODEL=entrance_p116_r40g_official_app_readiness_model.py (evaluate_readiness_v2, delegates to R40F's evaluate_readiness)
RUNNER_CREATED=false
LIVE_EXECUTED=false
RING_BUDGET_CONSUMED=false
NEXT_LIVE_AUTHORIZED=false
RESULT=CONTRACT_ONLY
=== END COMELIT P116 R41 V2 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
```
