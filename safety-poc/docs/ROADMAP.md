# Comelit Door Safety PoC roadmap

This roadmap separates repository-only proofs, CT120 read-only evidence, runtime fixture acceptance, and any future live action.

## Completed baseline

- P0 protocol/call-graph research: completed read-only.
- P1 one-shot safety semantics: completed.
- P2 canonical ViP fixture bridge: completed.
- P3 symbolic Door semantic sequence: completed.
- P4 ViP outer-framing reconciliation: completed in v0.5.
- P5 Git canonicalization: completed; GitHub `main` is the canonical source.

## P6 — CTPP body layout reconciliation

Repository-only work:

- parse the public-safe legacy AST inventory into six typed write shapes;
- map the fixed builder order to `INIT_A`, primary command/confirm, `INIT_B`, final command/confirm;
- generate deterministic placeholders only where static lengths are known;
- maintain structural fingerprints without storing real Door bytes.

CT120 evidence still required:

- exact structural inventory from pinned legacy source;
- source topology for the Door message builder and dependencies;
- a later synthetic byte-oracle proof before `CTPP_BODY_LAYOUT_RECONCILIATION=PASS` may be emitted.

## P7/P8 — Synthetic body model and body reconciliation

The repository model deliberately stops at structural reconciliation. It must not claim byte-exact body equivalence until CT120 evidence establishes every dynamic/opaque component shape using synthetic values only.

## P9 — acceptance and immutable release

A final v0.6 release requires the full offline suite, static safety scan, CT120 source pins, runtime fixture gates, PR review, immutable release creation, and retained v0.5 rollback.

## P10 — CTPP control plane

Repository-only model implemented:

`CLOSED -> OPEN_REQUESTED -> OPENED -> CLOSE_REQUESTED -> CLOSED/UNKNOWN`.

It enforces one open and one close attempt, carries a typed CTPP channel binding, and never asserts a physical effect.

Still required from CT120:

- canonical `open_channel`/`close_channel` request-response evidence;
- channel-id binding proof;
- fixture-only ACK/rejection/ambiguity reconciliation.

## P11 — full offline Door transaction

Repository-only transaction model implemented:

`OPEN_CTPP -> INIT_A -> WAIT_A -> COMMAND_PRIMARY -> CONFIRM_PRIMARY -> INIT_B -> WAIT_B -> COMMAND_FINAL -> CONFIRM_FINAL -> CLOSE_CTPP`.

Six Door writes are counted separately from control-plane actions. A failure before the first Door write can be proven not sent; any failure after a Door write is ambiguous. A complete transaction without Door-specific acknowledgement remains `UNKNOWN_OUTCOME`.

Runtime fixture reconciliation is still required before `FULL_OFFLINE_DOOR_TRANSACTION=PASS`.

## P12 — real transport readiness

The repository contains an explicit readiness evaluator. Live readiness remains closed until all repository gates and all live gates are independently proven, including read-only session establishment, target binding, authentication/session lifetime, timeout mapping, audit sink, and explicit live-test approval.

No real transport implementation is added by repository-only work.

## P13 — explicit live-test gate

No live Door action is authorized by this roadmap. A future physical test requires a separate explicit decision and evidence for exact target, one-shot operation, no retry, audit, timeout handling, and abort conditions.

## P14 — Home Assistant integration

Repository-only service contract implemented for `comelit.open_door`:

- `operation_id` is mandatory;
- automatic retry is forbidden;
- `UNKNOWN_OUTCOME` must be surfaced;
- protocol acknowledgement cannot be promoted to a physical Door-state claim.

Actual Home Assistant wiring is blocked until the real transport/live gates are completed.

## Global invariants

- irreversible uncertainty boundary remains `SEND_ARMED`;
- one `operation_id` causes at most one boundary invocation;
- `UNKNOWN_OUTCOME` is terminal and never auto-retried;
- protocol ACK is not proof of relay movement;
- `physical_effect_asserted=True` is forbidden;
- fixture fault injection must never result in repeated physical sends;
- repository evidence must not contain credentials, real Door payload values, or capture packet contents.
