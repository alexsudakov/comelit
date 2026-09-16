# P116 R29I — Pre-open idle lifetime and RTP sink ownership hardening

Status: research-only offline hardening. No live authorization is granted by this artifact.

## Motivation

The previous live attempt reached a clean production handoff and one registered research session, but the research candidate exited before any `CALL_INIT` was accepted. The inherited entrance signaling timer fired while the candidate was only waiting for a human ring:

```text
RESEARCH_LISTENER_READY=true
-> WAITING_FOR_RING
-> ENTRANCE_SIGNALING_TIMEOUT=true STAGE=1
-> MAIN_LOOP_FAILED / exit 6
-> CALL_INIT_OBSERVED=false
```

R29H intentionally kept every pre-OPEN entrance-signaling timeout fail-closed. Live evidence showed that this rule conflated two lifecycle domains: an idle registered listener waiting for a call and an actual signaling transaction.

The same run also reproduced an instrumentation defect: both RTP sinks were reported started/finalized, while `video.count` and `audio.count` were absent. The promoted runner starts sink processes inside command substitution; those PIDs are not guaranteed to be waitable children of the main runner shell.

## R29I lifetime rule

The human waiting-for-ring interval is owned by the runner's existing bounded ring watchdog (maximum 90 seconds), not by the inherited entrance signaling timer.

The inherited timeout is suppressed only when all of the following are true:

```text
listener_registered_ready
AND v4_registered
AND attached_media_state == REGISTERED_READY
AND call_transaction_created == false
AND call_transaction_active == false
AND registered_ctpp_mediareq26_open_sent == false
```

In that exact state the timer source is stale relative to the research listener and is removed without terminating the main loop.

Any lost registration, already-started call transaction, non-idle media state or other non-idle condition falls through to the existing R29H behavior. Therefore fail-closed behavior remains for real pre-OPEN signaling/transport failures and for a signaling timeout after a call transaction begins.

No reconnect, rebootstrap, ring retry, media refresh or second OPEN/STOP is introduced.

## RTP sink ownership rule

The existing `start_udp_sink` topology is retained so the hardening covers the exact live topology already exercised. Because the PID is produced by a command-substitution subshell, R29I does not use shell `wait` as proof of finalization.

Instead, finalization uses a bounded process-termination contract:

```text
TERM sink
-> observe /proc/<pid>/stat until process is gone or zombie
-> bounded KILL fallback only if required
-> only then read final count file
```

A successfully started sink must materialize its count file even when the final value is zero. Missing final evidence after successful start and bounded join is a tooling failure, not `0` and not a successful finalization.

The count file remains atomically written by the sink after its receive loop exits.

## Ring evidence semantics

The research report now distinguishes three facts:

```text
RING_PROMPT_ISSUED_COUNT
PHYSICAL_RING_REPORTED_BY_USER
CALL_INIT_OBSERVED_COUNT
```

Only the first and third are directly observable by the runner. `PHYSICAL_RING_REPORTED_BY_USER` defaults to `UNKNOWN` and may only be supplied by orchestration/user evidence. `RING_BUDGET_USED` retains its historical meaning of an accepted `CALL_INIT` and is explicitly labelled as not being a physical-press counter.

## Safety invariants

R29I does not change mediareq26 serialization, profile selection or binding semantics. The following remain unchanged:

```text
OPEN_MAX_COUNT=1
STOP_MAX_COUNT=1
SELF_ACTIVATION_001A_SENT_COUNT=0
R27_REPEAT_001A_SENT_COUNT=0
REFRESH_LOOP_STARTED_COUNT=0
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
```

The phase is offline-only until a separate future user authorization explicitly grants another one-shot live attempt.
