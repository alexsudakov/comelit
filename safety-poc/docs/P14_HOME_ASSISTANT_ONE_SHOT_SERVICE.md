# P14 — Home Assistant one-shot Door service

Status: **DRAFT / NON-SERVING / NO PHYSICAL TEST**

P14 connects the already-proven P13 one-shot actuation boundary to Home Assistant without giving Hermes direct device authority and without creating a second generic shell/action executor.

## 1. Architecture

Canonical path:

```text
Hermes
  -> dialog-service authorization + owner/confirmation gate
  -> Home Assistant comelit.open_door entity service
  -> custom_components/comelit
  -> authenticated local P14 CT120 bridge
  -> canonical P13 one-shot physical runner
  -> proven P13 transport boundary
```

Forbidden paths:

```text
Hermes -> CT120 shell
Hermes -> P13 native holder
Hermes -> raw Home Assistant device authority
Dialog-service -> CT120 bridge
Home Assistant -> arbitrary CT120 command
```

Home Assistant remains the device-action execution layer. CT120 is a narrowly scoped device backend for this integration.

## 2. Home Assistant public contract

Integration domain: `comelit`

Protected entity service:

```text
comelit.open_door
```

Canonical target used by dialog-service:

```text
button.comelit_main_entrance_open_door
```

Required service field:

```text
operation_id = p13-hermes-<uuid4>
```

No caller-supplied target fingerprint, CT120 host, native command, payload, retry setting, approval token or transport parameter is accepted.

The entity intentionally rejects standard `button.press`. This prevents the standard Home Assistant button service from becoming an operation-id bypass.

## 3. CT120 bridge protocol

Endpoint:

```text
POST /v1/open-door
```

Exact JSON body:

```json
{"operation_id":"p13-hermes-<uuid4>"}
```

Any extra JSON field is rejected before execution.

Request authentication uses HMAC-SHA256 over:

```text
v1
POST
/v1/open-door
<unix timestamp>
<nonce>
<sha256(raw request body)>
```

Required headers:

```text
X-Comelit-Version: 1
X-Comelit-Timestamp: <unix seconds>
X-Comelit-Nonce: <fresh random nonce>
X-Comelit-Signature: <hmac sha256 hex>
```

The timestamp window defaults to 30 seconds. Nonces are claimed in a durable SQLite replay store **after signature/body validation and before any runner invocation**.

A successful bridge response is also authenticated. Its HMAC covers:

```text
v1
RESPONSE
/v1/open-door
<request timestamp>
<request nonce>
<sha256(raw response body)>
```

and is returned as:

```text
X-Comelit-Response-Signature: <hmac sha256 hex>
```

Home Assistant rejects an unsigned/tampered successful response as `outcome unknown; do not retry`.

The shared secret is configuration/runtime data only and must never be committed.

## 4. One-shot semantics

P14 does not create another actuation state machine. The canonical P13 journal remains authoritative.

For each accepted request:

1. validate HMAC/version/timestamp/nonce;
2. validate exact body and UUID4 operation identity;
3. durably claim nonce;
4. check whether `operation_id` already exists in the P13 journal;
5. if it exists, return the persisted/conservative state without spawning the runner;
6. if live execution is disabled, return `FAILED_SAFE` without spawning;
7. acquire the bridge process lock without waiting;
8. re-check the P13 journal;
9. invoke the canonical P13 runner at most once;
10. inspect the durable P13 journal after the child exits;
11. normalize crash residue without retry:
    - `PREPARED` -> `FAILED_SAFE`;
    - `SEND_ARMED` or `SENT` -> `UNKNOWN_OUTCOME`.

`retry_allowed=false` and `physical_effect_asserted=false` are invariant for every result.

## 5. Parallel/replay behavior

- Same signed request nonce: durable replay rejection, no runner invocation.
- Same operation ID with a new nonce: existing P13 journal state is returned, no resend.
- Different operation while another bridge invocation is active: `FAILED_SAFE / bridge_busy_no_send_attempted`.
- P13's atomic per-target rate-limit remains an additional lower-layer guard.
- No automatic HTTP retry exists in the Home Assistant client.

## 6. Live-enable boundary

The bridge defaults to:

```text
COMELIT_P14_LIVE_ENABLED=false
COMELIT_P14_BIND_HOST=127.0.0.1
```

Therefore merely installing P14 cannot perform a physical Door action.

A future live deployment must deliberately configure all of the following outside Git:

```text
COMELIT_P14_SHARED_SECRET=<root-only / HA config-entry secret>
COMELIT_P14_TARGET_FINGERPRINT=<locally pinned target>
COMELIT_P14_RUNNER=<absolute path to canonical P13 runtime runner>
COMELIT_P14_LIVE_ENABLED=true
COMELIT_P14_BIND_HOST=<private CT120 address>
```

The live `COMELIT_P14_RUNNER` must point to a **separate clean P13 runtime worktree on `feat/p13-one-shot-actuation`**. Do not point it at the P14 stacked checkout: P13 preflight intentionally requires the P13 branch and will fail closed otherwise.

P14 must not remove or weaken the P13 branch/worktree/runtime-identity/preflight gates.

## 7. Result interpretation

Bridge states are protocol/execution-boundary evidence only:

- `ACKED` — protocol acknowledgement exists;
- `FAILED_SAFE` — this operation did not cross the send boundary according to durable evidence;
- `UNKNOWN_OUTCOME` — physical result is unknown and resend is forbidden.

No state proves the physical door opened. P14 and Home Assistant must never set `physical_effect_asserted=true` from protocol evidence.

## 8. Current validation

Repository-only tests cover:

- request HMAC compatibility between HA signer and CT120 verifier;
- response HMAC compatibility and tamper rejection;
- timestamp window and durable nonce replay rejection;
- exact one-field request body;
- exact `p13-hermes-<uuid4>` operation identity;
- live-disabled no-spawn behavior;
- exact canonical runner command shape;
- duplicate operation no-spawn behavior;
- timeout after `SEND_ARMED` -> terminal `UNKNOWN_OUTCOME`;
- bridge concurrency fail-safe;
- HA service registration requires `operation_id`;
- standard `button.press` fails closed;
- HA client contains no retry loop;
- canonical HA entity/service names match dialog-service contract.

GitHub `offline-safety` must be green on the exact P14 HEAD before any deployment step.

## 9. Explicitly not done in P14 code creation

- no CT120 service installation;
- no shared-secret generation/distribution;
- no HA custom-component installation;
- no `COMELIT_P14_LIVE_ENABLED=true`;
- no Home Assistant service call against CT120;
- no Hermes serving activation;
- no physical Door attempt.

Those are separate rollout gates after code review and non-actuating deployment validation.
