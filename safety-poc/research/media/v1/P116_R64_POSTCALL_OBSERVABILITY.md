# P116 R64 — Post-call transport observability corrective

Date: 2026-09-23. Scope: offline observability only. No Home Assistant deploy,
restart, physical ring, self-activation, Door action, Gate action, or Comelit
network operation is performed by this round.

## Trigger

A previous physical-call canary reproduced an approximately 51.2 second
listener outage:

```
media CLOSED
-> PSEUDOTCP_NOTIFY_PACKET / native exit 6
-> reconnect #1
-> PSEUDOTCP_CLOSED during STARTUP
-> reconnect #2
-> READY
```

A later owner-initiated physical ring on 1.5.9 did not reproduce the outage:
R58 media cleanup reached CLOSED, listener READY was never lost, and reconnect
count did not change. Therefore ordinary post-call media cleanup is not a
deterministic cause of the 51 second outage.

## Corrective

R64 changes observability only.

At the authoritative R58 post-call media CLOSED boundary the native helper
publishes one bounded snapshot:

```
R64_POST_CALL_REMOTE_RELEASE_OBSERVED
R64_POST_CALL_CAPABILITY_CLEARED_OBSERVED
R64_POST_CALL_TX_STATE
R64_POST_CALL_TX_SUBJECT
R64_POST_CALL_TX_PENDING
R64_POST_CALL_CALL_READY
R64_POST_CALL_PSEUDOTCP_OPEN
R64_POST_CALL_SNAPSHOT
```

Immediately before the existing R57 native-exit summary it publishes the
equivalent terminal snapshot:

```
R64_TERMINAL_REMOTE_RELEASE_OBSERVED
R64_TERMINAL_CAPABILITY_CLEARED_OBSERVED
R64_TERMINAL_TX_STATE
R64_TERMINAL_TX_SUBJECT
R64_TERMINAL_TX_PENDING
R64_TERMINAL_CALL_READY
R64_TERMINAL_PSEUDOTCP_OPEN
R64_TERMINAL_SNAPSHOT
```

The already-existing native discriminators
`PSEUDOTCP_CLOSED_BEFORE_OPEN=true` and
`PSEUDOTCP_CLOSED_AFTER_OPEN=true` are surfaced through the same bounded HA
logger and read-only status payload.

R37 remote RELEASE and capability-clear observations are latched per call
generation before their handlers run. This prevents a synchronous teardown
from producing a post-call snapshot before the discriminator is recorded.

## HA status surface

`runtime.status()` exposes:

```
post_call_observability.transport_state
post_call_observability.snapshot
post_call_observability.terminal_snapshot
post_call_observability.pseudotcp_closed_before_open
post_call_observability.pseudotcp_closed_after_open
```

Only fixed-vocabulary TX state/subject values and booleans are accepted.
No addresses, channel ids, payloads, credentials, SDP, tokens, or raw frames
are added.

## Behavioural invariants

R64 does not add or change:

- protocol writers or protocol bodies;
- P12 scheduling;
- CTPP/CSPB allocation;
- media OPEN/STOP semantics;
- PseudoTCP close behaviour;
- reconnect delay or reconnect policy;
- timeouts;
- automatic retries;
- Entrance Door semantics;
- Gate semantics.

The existing R63 Gate profile and R58 media cleanup remain in the source chain.

## Intended next live evidence

After normal HACS/HAOS installation, no deliberate failure reproduction is
required. On a normal call the POST_CALL snapshot should be visible. If the
intermittent outage occurs naturally, POST_CALL + TERMINAL + P116 failure
markers + BEFORE_OPEN/AFTER_OPEN should distinguish at least:

- remote terminal close observed before transport failure;
- capability-clear teardown;
- late transport close after a completed post-call boundary;
- startup/reconnect close before PseudoTCP OPEN;
- a non-terminal transport failure.

No causal classification is made from timing alone.
