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
| `switch.comelit_entrance_camera` turn_on/turn_off | Installed BASE uses `async_acquire("ha_switch")` / **`async_force_stop("ha_switch_off")`** | **Forbidden for smoke**. The experimental switch edits were reverted from this PR; do not modify this legacy UI just to add test automation |
| `MiniAppWebCodecsEntranceLease.release()` | Sets `released=True` before awaiting manager release | Do not use this flag as teardown proof; cancellation requires explicit test |
| `camera.comelit_entrance` attributes | `media_phase`, `media_active`, `attached_media_active`, `video_forwarding`, RTP counters | Safe observations, but not ownership proof |
| `sensor.comelit_listener_status` attributes | `listener_ready`, `media_paused`, `runtime_running`, `supervisor_running` | Check listener recovery after last lease |
| `comelit-v4` / `comelit-media` | Persistent Ring runtime / on-demand media helper | Do not classify persistent Ring runtime as an orphaned media process |

Gate 0 runtime report (2026-11-23): installed `comelit-ha` is a forced-command SSH gateway allowing `status|check|logs|logs-follow|deploy|rollback|restart`, but **no service-call or lease-specific action**. The configured Hermes `default` profile also has a separate broad HA SSH/Supervisor path, which is NOT a trusted project-scoped boundary. No native Hermes quota or task-bound authorization exists. Installed SHA remains `38d721b07eb4fd1e257290e7ae4869d5ca1437aa`; no physical smoke was executed.

This Draft PR now contains an **unwired library-only core** (`media_smoke.py`) and offline tests (`test_media_smoke.py`), not a registered HA service. It does not install a caller, grant permissions, bootstrap storage, or enable any live action. The media-finalization candidate still lacks Critic PASS, so its fixes cannot be assumed in production.

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

**Gate 0 — read-only installed capability inventory: PARTIAL COMPLETE.** Hermes verified gateway commands and installed identity, but the trusted task-scoped caller, HA lease API and durable quota do not exist. Root-capable HA SSH/Supervisor access cannot be treated as a safe shortcut. No physical run was authorized or executed.

**Gate 1 — repository-only implementation: IN PROGRESS (Draft PR #362, Critic requalification pending).** Original independent Critic on HEAD `89fd7fb9` reported FAIL (2 critical, 3 major). Corrective repository-only changes now share one process-local budget guard across controllers on the HA event loop, bound Store read/write, seal all controllers on uncertain I/O, and persist allowlisted, bounded redacted receipts in the **same** quota Store (schema v2). A reservation is written before any open. An interrupted or failed attempt leaves the durable in-flight marker blocked; a safe local close by itself does not authorize retry. Offline checks now include cross-controller concurrency and tests using the real Comelit manager state machine with fake hardware. This candidate has **not** been independently qualified yet. No service, trusted task-bound caller or persistent Store initialization is connected to HA.

**Gate 2 — independent qualification:** full checks from `.dev/hermes-dev.yaml`, immutable exact candidate, independent Critic for changes under `custom_components/comelit/**`, and required GitHub checks. Neither a live smoke receipt nor PR CI substitutes for another.

**Gate 3 — owner-authorized activation:** installation of a qualified trusted capability requires a **separate production deploy approval**. First exercise its read-only dry run and negative access tests. Only then allow bounded actual Camera open/close within the already authorized strict limits. Never automatically exercise Ring → handoff → reopen.


## Trusted caller boundary — proposed, not installed

The CT122 diagnosis confirms **there is no safe generic HA API route today**.
The SSH forced-command `comelit-ha` gateway has no media verb, while
`~/bin/ssh-ha` has broad HA host authority. Do not use the latter for
autonomous model-driven actuation, and do not expose a generic `ha_call_service`
token to Hermes.

The next integration must enforce two boundaries:

1. **CT122 task provenance:** only an installed, allowlisted, project-specific
   executor can obtain the current Comelit native Kanban task/run/board identity
   from a trusted worker context and revalidate its current claim. It passes a
   derived task ID; a model-provided ID is never authoritative. The executor
   receives no generic terminal/HA-service privilege and cannot invoke Door,
   Gate, Ring, deploy or restart. Reuse existing native Hermes tool enforcement,
   not an unrelated workflow or an LLM prompt-only gate.
2. **HA actuation ownership:** a narrow Comelit-owned invocation must
   independently check the same manager/supervisor/attached status and enforce
   persistent quota inside HA before calling `async_acquire`. A plain HA
   service with only `{task_id, action}` is **not authenticated**: any caller
   able to invoke it can impersonate an unrelated task. No such service is
   registered by this PR. If using the forced-command gateway, its precise
   new verb and authorization contract require independent review and
   explicit approval before changing the HA host.

The existing installed media-finalization defect is independent; qualification
of a smoke controller against an unpublished branch does not imply the HA
integration has been safely deployed. Integrating the library with HA unload,
watchdog and physical Ring overlap requires separate independent evidence.

**New repository-only review finding:** media packets are attributable to
smoke only while its on-demand lease remains the sole owner. A Ring or attached
media owner can appear between START and a packet-counter read. The test now
checks ownership both before and after RTP observation, checks
`transport.ring_observed`, and seals the attempt rather than allowing automatic
retry on overlap. A top-level result of `PASS` is emitted only after the
manager reports safe local release, the listener is READY, and the durable
budget completion is confirmed. This is still **not remote release proof**.

## Security and persistence blockers before a runnable endpoint

1. **No direct `comelit.media_smoke` service registered yet.** HA services cannot take a client-provided `task_id` as authentication. Enforce real task identity and an allowlisted caller in a trusted boundary, without giving Codex/LLM access to generic HA credentials or Door/Gate services. Do not add a generic service-call gateway verb.
2. **Store is not a transaction database.** The new core serializes all budget instances through a shared process-local guard for the one HA event loop, verifies each write with a fresh Store read, limits individual Store I/O waits, and seals the process on uncertain reads/writes. It **must not** be used with multiple HA writer processes sharing the same storage directory. A crash or ambiguous in-flight attempt blocks new opens. No fail-open reset on missing state; first initialization must be a separately authorized operator action.
3. **Lease/recovery safety remains unqualified in deployed code.** The root media-finalization incident and unmerged candidate are not fixed by this smoke library. Independent Critic must examine cancellation/late release before exposing an actual live caller.
4. **No native process/ring status guessing.** If the HA adapter cannot ground the process, call, and owner preflight, its `media_child_absent` and `call_state` hooks return UNKNOWN and the test is BLOCKED. Never replace required proof with `camera=off` or the absence of an entity.

## Independent qualification findings and residual blocker

Critic on `89fd7fb9` found five findings: missing trusted caller (critical),
unprotected concurrent budget controllers (critical), unbounded budget I/O
(major), no durable receipt (major), and inadequate real-manager/cancellation
tests (major). The code changes following that verdict target the latter four;
they **do not** retrospectively change the previous Critic FAIL.

The new budget guard is process-local, not a multi-host transactional lock.
The receipt stores only an allowlisted set of nonsecret fields and cannot
authenticate task provenance. The smoke caller now uses a bounded
`wait_for(shield(the_single_owned_cycle))` and returns a blocking verdict
when the total caller deadline is exceeded. That does NOT cancel the underlying
manager or claim native physical teardown is finished. Its owner remains
tracked, late success is converted to FAIL without unlocking the durable
reservation, and a pre-open deadline expiry blocks any new physical OPEN.
Tests cover both a manager that defers cancellation and a delayed budget
reservation. `asyncio.timeout` around OPEN still **cannot promise a hard
physical teardown bound** if the underlying `ComelitMediaSessionManager`
continues recovery. Any such uncertainty keeps admission sealed. The
runnable HA caller remains disabled until independent review proves correct
cleanup, shutdown cooperation and source identity.

The design for `alexsudakov/hermes-dev-v2#423` is now also available
in [Hermes Draft PR #425](https://github.com/alexsudakov/hermes-dev-v2/pull/425)
as repository source, since the installed Hermes fine-grained PAT may not
read private GitHub Issues. It proposes native task/run claim validation
and a project-only constrained caller, never arbitrary HA services or
model-supplied task IDs. The actual installed worker isolation, gateway
and HA service identity are **NOT_PROVEN**, so this is still a design rather
than an executable capability.

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
