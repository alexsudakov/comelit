# Comelit Door Safety PoC roadmap

This roadmap separates repository-only proofs, CT120 runtime fixture acceptance, release/deploy, read-only real-session proof, and any future live actuation.

## Completed baseline

- P0 protocol/call-graph research: completed read-only.
- P1 one-shot safety semantics: completed.
- P2 canonical ViP fixture bridge: completed.
- P3 symbolic Door semantic sequence: completed.
- P4 ViP outer-framing reconciliation: completed in v0.5.
- P5 Git canonicalization: completed; GitHub `main` is the canonical source.

## P6 — CTPP body layout reconciliation — completed offline

Repository structural inventory and CT120 synthetic byte-oracle acceptance are complete. The pinned legacy methods produce exactly six synthetic Door writes, and all six reframe byte-exactly through canonical `VipSession + FixtureTransport`.

## P7/P8 — synthetic body model and body reconciliation — completed offline

The six-write body model and reconciliation are complete for synthetic/offline inputs. The proof intentionally does not store or claim real credential-bearing Door payload bytes.

## P9 — acceptance and immutable v0.6 release — completed

Final v0.6.0 runtime gates passed on Git tree `66539b16552725943c3a5577640fd327c86e744a`. PR #2 was squash-merged to canonical `main` commit `f01d8c610daf6fe8d8fc9c02200726f684f39145` while preserving that exact tested tree.

CT120 immutable deployment completed successfully:

- current release: `/opt/comelit-door-safety-poc/releases/2026-08-29-v0.6.0-f01d8c610daf`;
- retained rollback: `/opt/comelit-door-safety-poc/releases/2026-08-29-v0.5-eba2900dc82e`;
- staged and promoted offline suites passed;
- release-content hashes passed;
- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`;
- `PHYSICAL_DOOR_ACTION=false`.

## P10 — CTPP control plane — completed offline

The state model remains:

`CLOSED -> OPEN_REQUESTED -> OPENED -> CLOSE_REQUESTED -> CLOSED/UNKNOWN`.

CT120 canonical fixture acceptance proved one typed CTPP open, channel binding `7449`, and one typed close bound to the same channel, with exactly two control writes. `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`.

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

## P12 — real transport read-only readiness — current

P12 is explicitly split from live actuation. Repository readiness, read-only real-session readiness, and live-test readiness are separate gates.

Repository-only P12 work defines the fixed application plan:

`CONNECT -> AUTHENTICATE -> LOAD_CONFIGURATION -> DISCOVER_TARGETS -> CLOSE`.

The read-only contract permits only session-control/query I/O and forbids actuator commands, credential export, automatic retry, and physical-effect assertions.

Current sub-stages:

1. **P12-A repository contract** — implement three-level readiness, fixed read-only plan, tests and public-safe evidence tooling.
2. **P12-B source inventory** — CT120 AST-only/no-network inventory of the pinned legacy connection/auth/config/discovery path and canonical session interfaces.
3. **P12-C real-session probe implementation** — only after P12-B review; must expose no actuation API.
4. **P12-D controlled read-only session proof** — establish/authenticate/query/discover/close only, with target/auth lifetime/timeout evidence.
5. **P12-E acceptance** — `READONLY_TRANSPORT_READY=true` may be reached while `LIVE_TEST_READY=false` remains mandatory.

No Door action is authorized by P12.

## P13 — one-shot actuation transport

P13 repository work is implemented on `feat/p13-one-shot-actuation`:

- fixed ten-stage actuation plan
  (`CLOUD_SIGNALING -> ICE -> PSEUDOTCP -> VIP_ECHO -> UAUT_OPEN -> UAUT_AUTH ->
  CTPP_OPEN -> DOOR_WRITES -> CTPP_CLOSE -> CLEAN_TEARDOWN`);
- `RealDoorActuationBoundary` behind the existing typed one-shot boundary with
  the five-outcome mapping (`PROVEN_NOT_SENT`, `REJECTED`, `ACCEPTED_NO_ACK`,
  `ACKED`, `AMBIGUOUS`);
- durable append-only audit sink with fsync-before-ack;
- non-actuating preflight (`scripts/p13_actuation_preflight.sh`) proving
  identity, payload mode 0600, audit durability, no conflicting process, no
  retry surface, `ACTUATION_TRANSPORT_IMPLEMENTED=true`,
  `AUDIT_SINK_VERIFIED=PASS`, while keeping `EXPLICIT_LIVE_TEST_APPROVAL=false`
  and `LIVE_TEST_READY=false`;
- offline prepared real Door payload generation
  (`scripts/prepare_p13_real_payloads.py`) with root-only output and
  SHA-256-only evidence.

No live Door action is authorized by this roadmap stage. A physical test
requires a separate explicit operator decision equivalent to
`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`, one fresh `operation_id`, exactly
one transport invocation, no automatic retry, and `UNKNOWN_OUTCOME`
classification for any post-`SEND_ARMED` ambiguity.

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
- read-only session success cannot enable actuation;
- repository/runtime evidence must not contain credentials, real Door payload values, or capture packet contents.
