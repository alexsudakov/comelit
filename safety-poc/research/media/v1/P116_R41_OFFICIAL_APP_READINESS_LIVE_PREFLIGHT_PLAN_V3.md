# P116 R41 v3 — Official-App Readiness Live Preflight (contract, no runner, no live execution)

Status: **document only**. `NEXT_LIVE_AUTHORIZED=false`. Provenance: successor to
`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md` (R41 v2), produced by round R40H
(`P116_R40H_FRESH_REGISTRATION_RECEIVER_LIVENESS.md`, base `b9ebcd04cb0e86e64af41666fe8e27d0fc191d2c`).
R41 v1 and v2 are **not** rewritten and remain valid historical records of the contract as it stood before
R40H's fresh-registration and native-keepalive evidence existed. This document supersedes both
operationally — a future live round should follow v3 — because v2 accepted a current-state
`registration_ready_seen`/`CONNECTED` read with no freshness requirement, which R40H CHILD G found
`R40G_MODEL_SEMANTICS=TOO_PERMISSIVE` for exactly the silent-staleness scenario R40G's own CHILD D had
already flagged as unresolved.

## 1. Purpose

Unchanged from v1/v2: sample `OFFICIAL_APP_READY` **without ever spending the physical-ring budget**, so a
future, separately authorized live round can decide up front whether a ring attempt is worth attempting. A
`PASS` here is evidence for a subsequent authorization request, not an authorization itself.

## 2. The core distinction this version adds

v1/v2 sampled one thing: the app's **current** state at the moment the operator looks (`CURRENT_UI_STATE` —
the literal `ToolbarDeviceConnectionStatus` label on `DoorEntryContentFragment`). R40H CHILD A proved that a
current `REGISTERED`/`CONNECTED` reading, by itself, cannot distinguish "the app just successfully registered
because our listener released the resource" from "the app has shown `REGISTERED` continuously since before
this attempt even began, for reasons unrelated to anything we did" (R40G CHILD D's silent-staleness case).
v3 therefore requires **both**, treated as genuinely separate pieces of evidence:

* `CURRENT_UI_STATE` — unchanged: the literal toolbar read, `OfficialAppUiConnectionState.CONNECTED`.
* `FRESH_ATTEMPT_EVIDENCE` — new: a `FreshRegistrationVerdict`
  (`entrance_p116_r40h_registration_log_model.evaluate_fresh_registration`) computed **only** from logcat
  lines timestamped strictly after this specific attempt's `PRE_PAUSE_LOG_CURSOR` (R40H CHILD B), whose
  `registration_ready_fresh_scalar` must be `True`.

A `CURRENT_UI_STATE=CONNECTED` sample with no accompanying fresh, uninvalidated transition after the cursor
is **not** sufficient under v3 — `entrance_p116_r40h_official_app_readiness_model.evaluate_readiness_v3`
refuses to produce a readiness verdict at all in that case (`UNPROVEN`), rather than falling back to v2's
weaker current-state gate.

## 3. Preconditions

All of R41 v2 section 2's preconditions, unchanged (fresh explicit operator authorization; listener `READY`
before the attempt; bounded listener failsafe armed; explicit operator-approved
`OPERATIONAL_APP_READY_TIMEOUT_SECONDS` strictly below the 300s failsafe ceiling with margin; confirmed
`LEGACY_VIP` system class), **plus**:

* The operator/runner must capture `PRE_PAUSE_LOG_CURSOR` (R40H CHILD B: a host-observed monotonic position
  in an already-running, tag-filtered `adb logcat -v time -T "<timestamp>" -s ComelitStatus:I
  ViperSocketReaderRun:E` stream, or an equivalent device monotonic-time cursor) **before** the listener
  pause begins, so that every event counted as "fresh" this attempt is provably not left over from a prior
  attempt or from before this round's observation window opened.

## 4. Contract (steps)

```text
1. listener state before          -> must be READY on >=2 samples; if not, ABORT before any pause
2. failsafe armed                 -> existing continuous-down mechanism, unchanged
3. capture PRE_PAUSE_LOG_CURSOR   -> new (R40H CHILD B): note the current logcat cursor position for
                                      tags ComelitStatus:I and ViperSocketReaderRun:E, before pausing
4. bounded pause if required      -> pause only for the minimum window needed to sample readiness;
                                      confirmed on >=2 samples, same evidence shape as R39 section 4
5. operator opens the official app's door-entry screen (DoorEntryContentFragment)
6. CURRENT_UI_STATE sampled       -> operator reads the literal VIP toolbar connection icon and reports
                                      it as an OfficialAppUiConnectionState value -- unchanged from v2
7. FRESH_ATTEMPT_EVIDENCE sampled -> if a future round has implemented the CHILD B logcat reader, collect
                                      every ComelitStatus:I / ViperSocketReaderRun:E line emitted after
                                      PRE_PAUSE_LOG_CURSOR, reduce each with reduce_raw_line, and compute
                                      evaluate_fresh_registration(events, PRE_PAUSE_LOG_CURSOR); otherwise
                                      this step cannot be completed and the attempt proceeds to step 9 as
                                      BLOCKED_APP_NOT_READY (fresh evidence absent is not fresh evidence
                                      true -- fail closed, no reader is not treated as a pass)
8. evaluate                       -> feed {system_class=LEGACY_VIP, observation={ui_state, listener_state=
                                      PAUSED, ring_budget_available=false, registration_ready_seen}, fresh_
                                      registration=<step 7 result>} into
                                      entrance_p116_r40h_official_app_readiness_model.evaluate_readiness_v3
9. bounded timeout                -> OPERATIONAL_APP_READY_TIMEOUT_SECONDS from SECTION 3; on timeout, on
                                      a missing/negative fresh_registration result, or on an
                                      UNKNOWN/NOT_CONNECTED-at-timeout UI sample: proceed to step 10 as
                                      BLOCKED_APP_NOT_READY
10. NO physical ring               -> no ring is ever placed by this preflight, regardless of the sampled
                                      value or evaluate_readiness_v3's output
11. restore listener               -> unconditionally, regardless of SUCCESS/FAIL/TIMEOUT, first action
                                      after step 8/9/10 conclude
12. verify READY                   -> confirm listener_ready/running/supervisor_running all true again
                                      before touching the failsafe
13. disarm failsafe                -> only after step 12 is confirmed
14. report                         -> BLOCKED_APP_NOT_READY or PASS_APP_READY_PREFLIGHT (SECTION 6)
```

(Numbered to 14 because step 3 — capturing the cursor — is new; steps otherwise map 1:1 onto v2's 13.)

## 5. Why the preflight can never consume the ring budget

Unchanged from v2: `ring_budget_available` is fixed to `false` for the entire attempt, a code-level
invariant a future runner must enforce, not merely document.
`entrance_p116_r40h_official_app_readiness_model.evaluate_readiness_v3` delegates (after the new freshness
precondition passes) to R40G's `evaluate_readiness_v2`, whose best possible outcome, per R40F's unmodified
`evaluate_readiness`, is `official_app_ready="true"`, `physical_ring_allowed=False`. No physical ring is ever
placed regardless of the sampled state.

## 6. Outcomes

* **`BLOCKED_APP_NOT_READY`** — the operational timeout elapsed; `system_class` could not be confirmed
  `LEGACY_VIP`; the sampled `ui_state` was `NOT_CONNECTED`/`CONNECTING`/`UNKNOWN`; `registration_ready_seen`
  was explicitly sampled `False`; **or** (new this version) `FRESH_ATTEMPT_EVIDENCE.registration_ready_fresh_scalar`
  is not `True` — including the case where no fresh-transition reader was available at all. A `CONNECTED`
  UI read with no fresh evidence is `BLOCKED_APP_NOT_READY` under v3, where it would have been a candidate
  `PASS` under v2. `RING_BUDGET_CONSUMED=false`.
* **`PASS_APP_READY_PREFLIGHT`** — the operator reported `CONNECTED` while the listener was confirmed
  `PAUSED`, the system class was confirmed `LEGACY_VIP`, **and** a fresh, uninvalidated `REGISTERED`
  transition was observed strictly after `PRE_PAUSE_LOG_CURSOR` with no subsequent
  `VIPER SOCKET CONNECTION LOST` line, inside the timeout. `RING_BUDGET_CONSUMED=false`. This outcome still
  does **not** authorize R42 or any subsequent live-ring round automatically. It also does not fully rule out
  every staleness scenario R40H found: the fresh-transition + independent-liveness check is proven strong
  for the direct/local (TCP) VIP-tunnel connection type; R40H CHILD E left the P2P/relayed connection type's
  native keepalive failure-action `UNPROVEN`, so a `PASS` sampled while the app happens to be on a P2P
  connection carries a residual, undocumented-until-now risk this contract cannot close from static evidence
  alone.

In both outcomes: one pause, one resume, no retry, no synthetic ring, no Door/Gate action,
`NEXT_LIVE_AUTHORIZED=false` until a new explicit operator authorization is given for a ring-spending round
specifically.

## 7. What this document does not authorize

No runner script exists for this contract in this round; none is created by R40H. No live execution is
authorized. A future round that implements the runner must independently re-derive its own
`LIVE_AUTHORIZED`/`CANDIDATE_HELPER_EXECUTED`-style gates before any live step, per the same discipline this
repository's other live-candidate runners already establish, and must implement the CHILD B logcat reader as
a read-only `adb logcat -T` filter — no `adb logcat -c`, no APK modification, no root, no Frida/Xposed.

```text
=== COMELIT P116 R41 V3 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
BASE_R40H_DOC=P116_R40H_FRESH_REGISTRATION_RECEIVER_LIVENESS.md
SUPERSEDES=P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md (v2, unchanged, not rewritten)
GATE_MODEL=entrance_p116_r40h_official_app_readiness_model.py (evaluate_readiness_v3, delegates to R40G's evaluate_readiness_v2)
FRESHNESS_MODEL=entrance_p116_r40h_registration_log_model.py (reduce_raw_line, evaluate_fresh_registration)
RUNNER_CREATED=false
LIVE_EXECUTED=false
RING_BUDGET_CONSUMED=false
NEXT_LIVE_AUTHORIZED=false
RESULT=CONTRACT_ONLY
=== END COMELIT P116 R41 V3 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
```
