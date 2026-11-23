# Comelit — bounded live media smoke, trusted capability contract

Status: **design-only, repository-only**. Issue: [#361](https://github.com/alexsudakov/comelit/issues/361).  
Reviewed base: `38d721b07eb4fd1e257290e7ae4869d5ca1437aa` (2026-11-23).  
This document **does not install or authorize a runnable production action**.

## Why

The live incident during Ring → media handoff left the listener paused and required a Home Assistant restart. Synthetic tests alone cannot establish successful on-device media open/close; however, repeated manual camera testing is slow. The owner authorized bounded autonomous **Camera open/close tests only**, not Ring, Door/Gate, service restarts, deployment, or credential changes.

Keep offline VERIFY / independent Critic separate from any live test. A successful smoke checks the **installed** integration only, and cannot qualify an unpublished candidate. Smoke open/close cannot by itself prove the Ring → handoff → reopen path or remote session release.

## Existing source contracts (reviewed on base)

| Surface | What it actually does | Consequence |
| --- | --- | --- |
| `ComelitMediaSessionManager.async_acquire(panel="entrance", reason=...)` | Acquires an on-demand lease through the existing media manager | Reuse the manager; do not spawn the native helper directly |
| `ComelitMediaSessionManager.async_release(reason=...)` | Removes a specific lease and tears down when last lease ends | Close **only the smoke-owned lease**, then join confirmed teardown |
| `ComelitMediaSessionManager.status()` | Reports phase, active, leases, listener_paused, error | Query inside a trusted HA execution boundary; external entities alone do not expose leases |
| `switch.comelit_entrance_camera` turn_on/turn_off | `async_acquire("ha_switch")` / **`async_force_stop("ha_switch_off")`** | **Forbidden** as an automated open/close pair: force_stop can clear other leases |
| `MiniAppWebCodecsEntranceLease.release()` | Sets `released=True` before awaiting manager release | Do not use this flag as teardown proof; cancellation requires explicit test |
| `camera.comelit_entrance` attributes | `media_phase`, `media_active`, `attached_media_active`, `video_forwarding`, RTP counters | Safe observations, but not ownership proof |
| `sensor.comelit_listener_status` attributes | `listener_ready`, `media_paused`, `runtime_running`, `supervisor_running` | Check listener recovery after last lease |
| `comelit-v4` / `comelit-media` | Persistent Ring runtime / on-demand media helper | Do not classify persistent Ring runtime as an orphaned media process |

The real installed `comelit-ha` gateway permissions, its available invocation surface, and persistent trusted quota facilities **are not proven from GitHub**. The current incident's local media-finalization candidate has not passed independent Critic; do not assume a successful smoke on the deployed base.

## Required shape, not yet implemented

**Use an existing trusted HA/gateway capability first.** If it does not expose an owner-scoped acquire/release operation, propose the smallest explicit project-scoped HA action with owner/admin authorization. No arbitrary Python/terminal endpoint, generic `exec`, direct native-helper launch, new P2P client, new long-lived service, widened gateway ACL or bypass of the HA access gate.

One operator-approved Hermes *task* may request a bounded `run_media_smoke` action through the trusted boundary. Neither Developer/VERIFY/Critic nor model text gets HA tokens, VIP secrets, raw SDP or arbitrary service-call authority.

The **trusted executor**, not the model/prompt, must authenticate task/project identity, enforce quota, serialize active smoke calls and retain the owner of the in-flight operation. An asynchronous caller disconnect must not cancel smoke-owned release. If the trusted executor has no suitable durable atomic state, report a concrete blocker before choosing persistence; prefer existing native facility to a new DB/daemon.

### Budget

- Maximum **3 attempted opens per authorized task**, including failures.
- Maximum **6 attempted opens across all Comelit tasks per rolling 24-hour window**.
- Reserve/commit one attempt atomically and durably **before** any open side effect, including in concurrent requests and across worker crashes/restarts. A failed/ambiguous attempt consumes budget.
- At most **one active smoke cycle** and **one upstream media owner**. No automatic retry.
- If the quota state or trusted task identity is missing, corrupted, ambiguous, or clock consistency is invalid: **BLOCKED**, no open. A new task must not reset the global 24-hour budget.

### Preconditions before each attempt

1. Installed integration SHA / file identity and HA core health known and stable.
2. Listener READY, Ring runtime and supervisor running, `media_paused=false`, call state `idle`.
3. `media_phase=inactive`, `media_active=false`, attached media inactive, `comelit-media` process absent.
4. Manager's actual `leases` empty (not just an external `switch=off`); no other HA stream, Mini App/WebCodecs viewer, Ring/live call, or pending teardown.
5. No conflicting smoke task, no unproven release/owner, no terminal ERROR. Required signals must be observed through trusted HA-side sources.

UNKNOWN, unreadable status or changed identity implies **BLOCKED**. A process count alone is insufficient to prove exclusivity or successful release.

### Test sequence

1. Reserve one quota unit.
2. Acquire an identifiable smoke-only lease using the existing media manager. Bound acquisition/first video or RTP evidence to **45 seconds**.
3. Observe bounded media metrics for up to **15 seconds**. Distinguish a successful manager start from actual RTP/video evidence; decoding in a viewer is not implied by packet counts.
4. Release **only the exact smoke-owned lease**, then join transport teardown and listener recovery within **45 seconds**. Do not call generic `async_force_stop` to clear other consumers.
5. Confirm absence of the media helper and outstanding own lease, `media_phase=inactive`, `media_active=false`, `media_paused=false`, listener READY. Confirmed local cleanup is **not** proof of protocol-level remote release.
6. Record a bounded, redacted receipt keyed by the installed SHA and authorized task id (no token/device ID/SDP/video). If the state of other consumers changed while smoke ran, never force them closed; report PARTIAL/BLOCKED and stop future attempts.

The complete cycle is bounded by those phase deadlines, plus a small explicit orchestration overhead budget; expiry cannot silently return PASS or mark a detached operation as released.

### Failure handling

Any timeout, cancellation, lost task, `ERROR`, Ring overlap, other viewer, unknown ownership, failed release or listener resume: **stop future attempts**. Preserve tracked teardown and fail closed. No physical Ring, Door, Gate, HA restart/reload/deploy, credential rotation, force-stop of someone else's lease, or blind retry.

A test may report `OPEN=PASS` and `CLOSE=FAIL` independently. Return `NOT_EXECUTED` for stages not reached, `BLOCKED` when safety cannot be proven. A returned HA service call is not sufficient to report video or teardown PASS.

## Acceptance gates for implementation

**Gate 0 — read-only installed capability inventory:** prove the exact installed gateway/HA commands, their permissions and execution identity, trusted budget storage and safe acquisition/release boundary. This cannot be established from the source repo and is not a license to run the camera.

**Gate 1 — repository-only implementation:** add the smallest project-specific executor/HA action only if Gate 0 proves it necessary. Use existing manager/transport/supervisor. Tests must cover concurrent quota reservations, crash-before/after-open budget, task re-entry, conflicting users, Ring race, timeout/cancellation, own-lease release, late completion, no second owner, redaction and exact installed SHA. The test code must be **offline** and not actuate physical devices.

**Gate 2 — independent qualification:** full checks from `.dev/hermes-dev.yaml`, immutable exact candidate, independent Critic for changes under `custom_components/comelit/**`, and required GitHub checks. Neither a live smoke receipt nor PR CI substitutes for another.

**Gate 3 — owner-authorized activation:** installation of a qualified trusted capability requires a **separate production deploy approval**. First exercise its read-only dry run and negative access tests. Only then allow bounded actual Camera open/close within the already authorized strict limits. Never automatically exercise Ring → handoff → reopen.

## Reporting contract

```text
SMOKE=PASS|FAIL|PARTIAL|BLOCKED|NOT_EXECUTED
TASK_ID=<trusted non-secret id>
INSTALLED_SHA=<confirmed installed SHA>
BUDGET_TASK_USED=<n>/3
BUDGET_24H_USED=<n>/6
PREFLIGHT=PASS|BLOCKED
OPEN=PASS|FAIL|NOT_EXECUTED
RTP_EVIDENCE=PASS|FAIL|NOT_PROVEN
OWN_LEASE_RELEASED=PASS|FAIL|UNKNOWN
LOCAL_TEARDOWN=CONFIRMED|UNCONFIRMED
LISTENER_RECOVERY=PASS|FAIL|UNKNOWN
REMOTE_RELEASE=NOT_PROVEN|PROVEN_FROM_SPECIFIC_PROTOCOL_EVIDENCE
PHYSICAL_RING=NOT_EXECUTED
DOOR_GATE_ACTIONS=0
PRODUCTION_DEPLOY=NOT_EXECUTED
```

This specification deliberately does **not** choose a new storage mechanism, permissions elevation or live invocation endpoint until the installed runtime has been inspected. Avoid adding a second media lifecycle solely to run tests.
