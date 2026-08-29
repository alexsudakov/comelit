# Comelit Door Safety PoC roadmap

This roadmap separates repository-only proofs, CT120 runtime fixture acceptance, release/deploy, and any future live action.

## Completed baseline

- P0 protocol/call-graph research: completed read-only.
- P1 one-shot safety semantics: completed.
- P2 canonical ViP fixture bridge: completed.
- P3 symbolic Door semantic sequence: completed.
- P4 ViP outer-framing reconciliation: completed in v0.5.
- P5 Git canonicalization: completed; GitHub `main` is the canonical source.

## P6 — CTPP body layout reconciliation — completed offline

Repository structural inventory and CT120 synthetic byte-oracle acceptance are complete. The pinned legacy methods produce exactly six synthetic Door writes, and all six reframe byte-exactly through canonical `VipSession + FixtureTransport`.

Development-candidate runtime proof emitted `CTPP_BODY_LAYOUT_RECONCILIATION=PASS` without secrets, real Door payload values, network action or physical action.

## P7/P8 — synthetic body model and body reconciliation — completed offline

The six-write body model and reconciliation are complete for synthetic/offline inputs. The proof intentionally does not store or claim real credential-bearing Door payload bytes.

## P9 — acceptance and immutable v0.6 release — current

Development-candidate runtime gates passed. The repository is now versioned `0.6.0`; the exact final Git tree must be runtime-tested again because the version/documentation finalization changed the tree.

After final-tree PASS:

1. open/review PR without modifying the tested tree;
2. merge while preserving the tested tree content;
3. synchronize CT120 `main == origin/main`;
4. deploy the immutable offline v0.6 release using matching runtime evidence;
5. retain v0.5 rollback until post-promotion acceptance completes.

## P10 — CTPP control plane — completed offline

The state model remains:

`CLOSED -> OPEN_REQUESTED -> OPENED -> CLOSE_REQUESTED -> CLOSED/UNKNOWN`.

CT120 canonical fixture acceptance proved one typed `open_channel("CTPP")`, channel binding `7449`, and one typed close bound to the same channel, with exactly two control writes. `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`.

Ambiguous control-plane send is never downgraded to `PROVEN_NOT_SENT`.

## P11 — full offline Door transaction — completed offline

The transaction model is:

`OPEN_CTPP -> INIT_A -> WAIT_A -> COMMAND_PRIMARY -> CONFIRM_PRIMARY -> INIT_B -> WAIT_B -> COMMAND_FINAL -> CONFIRM_FINAL -> CLOSE_CTPP`.

CT120 fixture acceptance proved exactly 8 writes = 2 control + 6 Door data frames, all six Door frames on one CTPP channel, and matching open/close transaction boundaries. `FULL_OFFLINE_DOOR_TRANSACTION=PASS`.

Safety semantics remain conservative:

- only a failure before any control/boundary attempt may be `PROVEN_NOT_SENT`;
- explicit control rejection before Door data can fail safe;
- ambiguous CTPP open is `UNKNOWN_OUTCOME` even with zero Door data frames;
- any failure after a Door write is ambiguous;
- a complete transaction without Door-specific acknowledgement remains `UNKNOWN_OUTCOME`.

## P12 — real transport readiness — next after v0.6 deploy

The repository contains an explicit readiness evaluator. Live readiness remains closed until all live gates are independently proven, including read-only session establishment, target binding, authentication/session lifetime, timeout mapping and audit sink.

No real transport implementation is part of v0.6.

## P13 — explicit live-test gate

No live Door action is authorized by this roadmap. A future physical test requires a separate explicit decision and evidence for exact target, one-shot operation, no retry, audit, timeout handling and abort conditions.

## P14 — Home Assistant integration

Repository-only service contract is implemented for `comelit.open_door`:

- `operation_id` is mandatory;
- automatic retry is forbidden;
- `UNKNOWN_OUTCOME` must be surfaced;
- protocol acknowledgement cannot be promoted to a physical Door-state claim.

Actual Home Assistant wiring to real transport is blocked until P12/P13 are completed.

## Global invariants

- irreversible uncertainty boundary remains `SEND_ARMED`;
- one `operation_id` causes at most one boundary invocation;
- `UNKNOWN_OUTCOME` is terminal and never auto-retried;
- protocol ACK is not proof of relay movement;
- `physical_effect_asserted=True` is forbidden;
- fixture fault injection must never result in repeated physical sends;
- repository/runtime evidence must not contain credentials, real Door payload values, or capture packet contents.
