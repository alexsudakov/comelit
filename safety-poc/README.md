# Comelit Door Safety PoC — offline package (v0.6)

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

Repository CI proves portable safety semantics only. CT120-specific body/control-plane/full-transaction reconciliation is performed separately by `scripts/run_ct120_runtime_gates.sh` against pinned read-only research sources and canonical fixture transports.

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

## v0.6 offline reconciliation

v0.6 adds:

- public-safe CT120 evidence collection with automatic Git branch/commit/push;
- payload-redacted CTPP body-shape parsing and six-write structural reconciliation;
- a pinned legacy synthetic byte oracle proving six generated Door frames reframe byte-exactly through canonical `VipSession + FixtureTransport`;
- canonical capture-based ViP session/control tests;
- canonical `open_channel("CTPP") -> close_channel(same id)` fixture reconciliation;
- a full canonical offline `OPEN_CTPP -> six synthetic Door frames -> CLOSE_CTPP` transaction with exactly eight fixture writes;
- conservative CTPP ambiguity handling and one-shot/no-retry invariants;
- explicit repository-vs-live readiness gates;
- a fail-safe `comelit.open_door` Home Assistant service contract;
- Git-tree/version-bound immutable deployment with v0.5 rollback.

The CT120 development-candidate runtime suite established `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`, `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`, `FULL_OFFLINE_DOOR_TRANSACTION=PASS`, and `REPOSITORY_READY=true` using synthetic/fixture-only execution. The final `0.6.0` Git tree must be runtime-tested again before merge/deploy.

These proofs **do not** implement or authorize real transport, credential-bearing Door payloads, active Comelit network actions, physical relay claims, or a live Door test. `LIVE_TEST_READY=false` remains the required state for v0.6.
