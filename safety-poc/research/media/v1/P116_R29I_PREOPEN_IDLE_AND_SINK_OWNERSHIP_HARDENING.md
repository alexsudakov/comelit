# P116 R29I Pre-OPEN Idle And Sink Ownership Hardening

Status: offline research hardening; no live authorization.

## Problem reproduced by the previous live attempt

The R29H candidate correctly protected the bounded section after a real mediareq26
`OPEN`, but deliberately retained the inherited fail-closed signaling timeout before
`OPEN`. In the live attempt the research listener reached READY, then the inherited
`ENTRANCE_SIGNALING_TIMEOUT` fired while the process was still waiting for the human
ring. The process exited before `CALL_INIT`, so no mediareq26 `OPEN` was sent and the
registered-CTPP hypothesis was not tested.

The same attempt also exposed an evidence bug: UDP sinks reported started/finalized,
but final count files were absent. The R29C runner starts the sink from a Bash command
substitution. The background Python process therefore need not be a direct child of the
outer runner shell; relying on the outer shell's `wait` is not a valid ownership/join
contract.

## R29I lifetime rule

The candidate now distinguishes idle listener time from an active call transaction:

```text
registered READY
-> WAITING_FOR_RING
-> inherited entrance signaling timer may fire repeatedly without killing the listener
-> CALL_INIT accepted
-> bounded short pre-OPEN call grace protects only the same-tick timer race
-> existing fail-closed pre-OPEN behavior resumes
-> real OPEN
-> existing R29H OPEN -> observation -> STOP bounded section
```

The WAITING_FOR_RING exception applies only when all of these are true:

- listener is registered/ready;
- no call transaction has been created;
- no registered-CTPP mediareq26 OPEN has been sent;
- lifetime phase is still PRE_OPEN.

A 5000 ms post-CALL_INIT grace protects a timer callback already due in the same event
loop epoch. It does not create a reconnect, retry, refresh loop, Door/Gate action or
second OPEN. Once that bounded grace expires, the inherited pre-OPEN fail-closed path
remains intact. After real OPEN, R29H remains the owner of the bounded observation/STOP
section.

## R29I sink finalization contract

The sink process writes evidence in this strict order:

1. atomically write final datagram count, including `0`;
2. atomically write `done` marker;
3. exit.

The runner sends SIGTERM and performs a bounded wait for the `done` marker. It reads the
count only after `done`. Missing `done` or missing count after successful start is an
evidence failure and remains `UNKNOWN`; it is never coerced to zero.

This is an explicit evidence/join contract and does not rely on Bash `wait` being able to
reap a process launched inside command substitution.

## Ring evidence semantics

The runner distinguishes what it can prove:

- `RING_PROMPT_ISSUED_COUNT` — runner-side prompt count;
- `CALL_INIT_OBSERVED_COUNT` — protocol evidence accepted by the candidate;
- `PHYSICAL_RING_REPORTED_BY_USER=UNAVAILABLE_TO_RUNNER` — physical user action is external evidence and is not inferred.

Legacy `RING_BUDGET_USED` remains for compatibility and is explicitly labelled as an
accepted-CALL_INIT count, not proof that a human did or did not press the panel.

## Safety invariants

R29I does not alter mediareq26 payload/profile/binding semantics. The inherited one-shot
limits remain: at most one OPEN and at most one STOP. Self-activation 0x001A, R27 repeat,
refresh, Door and Gate paths remain forbidden in this research lane. No production HA
files are changed and no live/network operation is authorized by these artifacts.
