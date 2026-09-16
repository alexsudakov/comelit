# P116 / R29I — pre-open idle and RTP sink ownership hardening

Status: **research / offline hardening**

## Scope

R29I addresses two tooling/lifetime defects observed after the R29H live attempt that ended with `NO_CALL_INIT_TIMEOUT` before any media request was transmitted.

It does **not** change the registered-CTPP mediareq26 OPEN/STOP payload, client media profile, channel binding, Door/Gate behavior, or any production Home Assistant code.

## 1. Waiting-for-ring lifetime ownership

The inherited `ENTRANCE_SIGNALING_TIMEOUT` is not a persistent-listener timeout. It belongs to the older self-activation transaction and is armed at CTPP registration together with that transaction's settle callback.

R29 later repurposed the settle callback into the persistent-listener READY transition, but the old 20-second signaling timeout remained armed. That stale timer could therefore terminate an otherwise healthy registered/ready research listener while a human was still inside the bounded ring window.

R29I fixes ownership at the source rather than suppressing the callback after it fires:

```text
CTPP registration
-> keep the settle/READY timer
-> do NOT arm the legacy self-activation signaling timeout
-> listener READY
-> WAITING_FOR_RING owned by outer runner (bounded 90 s)
-> CALL_INIT or runner timeout / genuine transport failure
```

The generated candidate retains the old callback for lineage review, but no timeout source schedules it in the attached-listener lane. This avoids a second subtle bug: suppressing a one-shot `G_SOURCE_REMOVE` callback while idle would also remove the source, so it could not later provide a real call-transaction timeout after `CALL_INIT`.

The call/media path is bounded independently by the runner (`R29C_OPEN_MAX_SECONDS`, RTP observation, STOP and outer timeout). Existing transport loss, PseudoTCP/registration loss and fatal signaling paths remain fail-closed. No reconnect/rebootstrap/retry is added.

## 2. RTP sink finalization

The inherited runner starts UDP sinks from command substitution. Such background processes are not guaranteed to remain waitable children of the main shell. R29I therefore does not treat shell `wait` as authoritative for those PIDs.

The wrapper uses deterministic exit acknowledgement:

1. send `TERM` to a started sink;
2. poll process state until it has exited (or reached zombie/terminal state);
3. only after terminal state, require the atomically written count file;
4. require a numeric final count, including explicit `0` for a zero-datagram run;
5. treat a missing/invalid final count as `INCONCLUSIVE_TOOLING_FAILURE` rather than zero or PASS.

The process-level regression covers both zero-datagram and non-zero-datagram cases and reads the count only after termination/finalization evidence.

## 3. Evidence semantics

The runner distinguishes:

- `RING_PROMPT_ISSUED_COUNT` — observable by the runner;
- `CALL_INIT_OBSERVED_COUNT` — observable on the protocol path;
- `PHYSICAL_RING_REPORTED_BY_USER` — external/orchestration evidence only and never inferred by the runner.

Therefore a missing `CALL_INIT` is not converted into a claim that the user did not physically press the intercom button.

## 4. Safety invariants

R29I preserves the inherited research-lane gates:

- at most one mediareq26 OPEN;
- at most one mediareq26 STOP;
- no self-activation 0x1A;
- no R27 repeat/refresh;
- no Door or Gate action;
- no HA deploy/restart/reload;
- no automatic live retry.

This phase is offline-only. A future wire attempt, if still needed, requires a separate explicit authorization.
