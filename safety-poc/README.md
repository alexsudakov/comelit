# Comelit Door Safety PoC — offline package (v0.6-dev)

This package proves the **safety semantics** required before any physical door action is considered:

`PREPARED -> SEND_ARMED -> SENT -> ACKED`

with conservative terminal outcomes:

- `FAILED_SAFE`: the implementation can prove no action left the boundary;
- `UNKNOWN_OUTCOME`: a send may have happened and the result cannot be proven;
- `ACKED`: protocol acknowledgement is proven; this **does not claim physical relay movement**.

## Important scope boundary

This repository contains **no working Comelit door-open transport**, no credentials, no OAuth/ViP tokens, no credential-bearing live frame builder, and no code that opens a physical door. `DisabledRealTransport` performs no network I/O and fails closed.

The purpose is to validate persistence, idempotency, crash recovery, rate limiting, audit transitions, framing/body/control-plane contracts, and the no-retry invariant with deterministic offline backends.

## Quick test

```bash
./scripts/run_offline_suite.sh
```

The suite reports repository-model PASS markers separately from runtime reconciliation gates. During v0.6 development the body/control-plane/full-transaction runtime gates intentionally remain `PENDING_*` until CT120 evidence is collected and reconciled.

## Manual scenarios

```bash
export PYTHONPATH="$PWD/src"
DB=/tmp/comelit-safety-poc.sqlite3

python3 -m comelit_safety_poc.cli --db "$DB" run \
  --operation-id demo-001 --target demo-door --scenario ack --min-interval-seconds 0

python3 -m comelit_safety_poc.cli --db "$DB" run \
  --operation-id demo-002 --target demo-door-2 \
  --scenario timeout_after_accept --min-interval-seconds 0
```

Crash boundary:

```bash
python3 -m comelit_safety_poc.cli --db "$DB" run \
  --operation-id crash-001 --target demo-door-3 \
  --scenario ack --fault crash_after_arm --min-interval-seconds 0 || true

python3 -m comelit_safety_poc.cli --db "$DB" recover
python3 -m comelit_safety_poc.cli --db "$DB" show --operation-id crash-001
```

The recovered state must be `UNKNOWN_OUTCOME`; there is no automatic retry path.

## v0.3 canonical fixture bridge

The package includes an offline-only adapter to the pinned canonical `comelit_vip` session stack. It uses `FixtureTransport` only; no network transport or Door payload is implemented. A fixture write maps to `ACCEPTED_NO_ACK`, therefore the executor persists `UNKNOWN_OUTCOME`.

## v0.4 offline Door semantic plan

v0.4 adds a symbolic Door semantic plan derived from the pinned research call graph and executes only synthetic markers through the pinned canonical `VipSession` + `FixtureTransport` stack. It does **not** execute `VipChannelSession.open_channel()`, contains no credential-bearing Door payload, performs no network I/O, and cannot assert a physical effect.

## v0.5 wire-shape reconciliation

v0.5 adds an offline wire-shape reconciliation gate. Six synthetic Door-semantic bodies are framed both by the pinned legacy research helper and by canonical `VipSession.send_frame()` through `FixtureTransport`; all match byte-exactly. A negative control proves an already-framed legacy packet would be double-framed by canonical `send_frame()`.

## v0.6 development

The v0.6 branch adds:

- public-safe CT120 evidence collection with automatic Git branch/commit/push;
- payload-redacted CTPP body-shape parsing and six-write structural reconciliation;
- deterministic synthetic placeholders for statically-sized structural components;
- an offline CTPP open/close state model;
- a full ten-step synthetic Door transaction model;
- explicit repository-vs-live readiness gates;
- a fail-safe `comelit.open_door` Home Assistant service contract.

These repository models **do not** claim byte-exact Door body reconciliation, canonical CTPP control-plane reconciliation, real transport readiness, or authorization for a physical Door test. Those remain evidence/runtime gates.
