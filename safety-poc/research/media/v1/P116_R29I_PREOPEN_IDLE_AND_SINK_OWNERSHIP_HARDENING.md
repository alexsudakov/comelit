# P116 / R29I — pre-open idle and RTP sink ownership hardening

Status: **research / offline hardening**

## Scope

R29I addresses two tooling/lifetime defects observed after the R29H live attempt that ended with `NO_CALL_INIT_TIMEOUT` before any media request was transmitted.

It does **not** change the registered-CTPP mediareq26 OPEN/STOP payload, client media profile, channel binding, Door/Gate behavior, or any production Home Assistant code.

## 1. Waiting-for-ring lifetime ownership

The inherited entrance signaling timeout was armed before the first inbound `CALL_INIT` and could terminate an otherwise registered/ready research listener while a human was still within the bounded ring window.

R29I narrows the timeout ownership:

```text
registered + ready
+ no CALL_INIT transaction created/active
+ no mediareq26 OPEN sent
=> inherited entrance signaling timeout is not allowed to terminate the listener
```

The bounded human wait remains owned by the outer runner (`R29C_RING_MAX_SECONDS`, currently 90 seconds).

Once `CALL_INIT` starts a real call transaction, the pre-OPEN fail-closed behavior remains unchanged. Transport loss, registration loss, fatal signaling errors, and the outer runner timeout remain terminal as before.

## 2. RTP sink finalization

The inherited runner starts UDP sinks from command substitution. Such background processes are not guaranteed to remain waitable children of the main shell. R29I therefore does not treat shell `wait` as authoritative for those PIDs.

The wrapper uses deterministic exit acknowledgement:

1. send `TERM` to a started sink;
2. poll process state until it has exited (or reached zombie/terminal state);
3. only after exit, wait for the atomically written count file;
4. require a numeric final count, including explicit `0` for a zero-datagram run;
5. treat a missing/invalid final count as `INCONCLUSIVE_TOOLING_FAILURE` rather than zero or PASS.

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
