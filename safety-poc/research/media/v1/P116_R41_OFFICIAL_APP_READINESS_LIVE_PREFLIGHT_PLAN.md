# P116 R41 — Official-App Readiness Live Preflight (contract, no runner, no live execution)

Status: **document only**. `NEXT_LIVE_AUTHORIZED=false`. This document defines the contract a future,
separately authorized R41 round would implement and run. It performs no listener action, no capture, no
ring, no Door/Gate action and no device contact itself. It does not supersede
`P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md`, which remains the canonical statement of why R39 failed
to observe a call and of the ordered no-repeat procedure; this document narrows that plan into an explicit
preflight contract that wires in the gate model closed by
`P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md` CHILD I
(`entrance_p116_r40_official_app_readiness_model.py`).

## 1. Purpose

Sample `OFFICIAL_APP_READY` **without ever spending the physical-ring budget**, so that a future,
separately authorized live round can decide up front whether a ring attempt is worth attempting at all. A
preflight that reaches `PASS_APP_READY_PREFLIGHT` proves only that the gate was satisfied at sample time —
it is evidence for a subsequent live-ring round's authorization request, not an authorization itself.

## 2. Preconditions

* A fresh, separate, explicit operator authorization for this specific preflight attempt (per
  `services/dialog-service/project-context/comelit/PROJECT_CONTEXT.md` section 34: no past approval carries
  forward to a new round).
* Production listener confirmed `READY` before the attempt starts.
* Bounded listener failsafe armed (existing autoreset path, continuous-down logic, same mechanism R39 used).
* An explicit, operator-approved `APP_READY_TIMEOUT_SECONDS` value chosen at authorization time — R40 CHILD
  G left this `UNPROVEN` from offline evidence alone; R41 must not silently default it.

## 3. Contract (steps)

```text
1. listener state before          -> must be READY on >=2 samples; if not, ABORT before any pause
2. failsafe armed                 -> existing continuous-down mechanism, unchanged
3. bounded pause if required      -> pause only for the minimum window needed to sample readiness;
                                      confirmed on >=2 samples (running=false, listener_ready=false,
                                      supervisor_running=false), same evidence shape as R39 section 4
4. operator opens the official app
5. readiness sampled              -> operator reports OperatorAppState at each sample, fed into
                                      entrance_p116_r40_official_app_readiness_model.evaluate_readiness
                                      alongside listener_state=PAUSED and ring_budget_available=false
                                      (the preflight NEVER sets ring_budget_available=true -- see SECTION 4)
6. NO physical ring               -> no ring is ever placed by this preflight, regardless of the sampled
                                      OFFICIAL_APP_READY value
7. restore listener                -> unconditionally, regardless of SUCCESS/FAIL/TIMEOUT, first action
                                      after step 5/6 conclude
8. verify READY                    -> confirm listener_ready/running/supervisor_running all true again
                                      before touching the failsafe
9. disarm failsafe                 -> only after step 8 is confirmed
10. report                         -> BLOCKED_APP_NOT_READY or PASS_APP_READY_PREFLIGHT (SECTION 4)
```

## 4. Why the preflight can never consume the ring budget

`entrance_p116_r40_official_app_readiness_model.evaluate_readiness` is called in this preflight with
`ring_budget_available` fixed to `false` for the entire attempt (a code-level invariant a future R41 runner
must enforce, not merely a documented intention): the model's own logic means the best possible outcome of
that call is `official_app_ready="true"`, `physical_ring_allowed=False` (`reason="app_ready_but_ring_budget_unavailable"`).
No physical ring is ever placed by this preflight regardless of the sampled state, so no code path in this
contract can produce `physical_ring_allowed=True` while a real ring is possible. This is intentional
redundancy with SECTION 3 step 6, not a substitute for it.

## 5. Outcomes

* **`BLOCKED_APP_NOT_READY`** — the readiness timeout elapsed, or the operator reported
  `ERROR_OR_OFFLINE`/`NOT_OPENED`/`UNKNOWN` at timeout. `RING_BUDGET_CONSUMED=false`. This is exactly the
  case R39 hit; it must not cost a ring, and it does not here.
* **`PASS_APP_READY_PREFLIGHT`** — the operator reported `OPERATOR_CONFIRMED_USABLE` while the listener was
  confirmed `PAUSED`, inside the timeout. `RING_BUDGET_CONSUMED=false` (SECTION 4). This outcome does
  **not** authorize R42 or any subsequent live-ring round automatically: it is evidence a human operator can
  use to decide whether to separately authorize a bounded, one-ring live round under the existing R39/R40
  baseline safety contract (`services/dialog-service/project-context/comelit/PROJECT_CONTEXT.md` sections
  11–13), not a self-authorizing trigger.

In both outcomes: one pause, one resume, no retry, no synthetic ring, no Door/Gate action, `NEXT_LIVE_AUTHORIZED=false`
until a new explicit operator authorization is given for a ring-spending round specifically.

## 6. What this document does not authorize

No runner script exists for this contract in this round; none is created by R40. No live execution is
authorized by this document. A future round that implements the runner must independently re-derive its own
`LIVE_AUTHORIZED`/`CANDIDATE_HELPER_EXECUTED`-style gates before any live step, per the same discipline
R27–R30H already established for this repository's other live-candidate runners.

```text
=== COMELIT P116 R41 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
BASE_R40_DOC=P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md
GATE_MODEL=entrance_p116_r40_official_app_readiness_model.py
RUNNER_CREATED=false
LIVE_EXECUTED=false
RING_BUDGET_CONSUMED=false
NEXT_LIVE_AUTHORIZED=false
RESULT=CONTRACT_ONLY
=== END COMELIT P116 R41 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===
```
