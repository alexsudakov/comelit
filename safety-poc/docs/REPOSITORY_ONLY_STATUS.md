# v0.6 offline implementation status

Base: `main` at `57d75178fce7387264db5b0cb3b182e4ec5f91c7`.

## Implemented without live actions

- public-safe CT120 plan evidence collection with automatic evidence branch/commit/push;
- corrected qualified-method legacy Door body inventory;
- literal-redacted source topology and canonical control-plane API/test topology collectors;
- typed parser for exactly six legacy Door write shapes;
- structural mapping to the fixed six semantic writes;
- deterministic synthetic placeholders and fingerprints containing no real Door payload values;
- pure CTPP open/close state and channel-binding model;
- pure ten-step Door transaction model over the existing one-shot boundary;
- conservative handling of ambiguous CTPP open (never downgraded to `PROVEN_NOT_SENT`);
- repository-vs-live readiness evaluator;
- fail-safe Home Assistant `comelit.open_door` service contract;
- Git-native immutable deployment with main/origin convergence, tested-tree/version binding, rollback, staged verification and promoted-release verification;
- repository-only GitHub Actions static-safety/unit/CLI/script-compile workflow;
- CT120-only sandboxed legacy synthetic body oracle;
- CT120-only canonical capture/session tests;
- CT120-only canonical CTPP open/close fixture gate;
- CT120-only full canonical 8-write transaction fixture gate;
- unified CT120 runtime-gate runner and public-safe evidence publication.

## Evidence history

Evidence v1 commit `153e1864d947e9ff0a5386f2d60b4b87d117c239` proved collector/source/runtime/operator/passive-network identities but its body selector chose the top-level `open_door` wrapper. It is retained for audit but is not accepted for P6 body-layout proof.

Corrected evidence v2 commit `db92d166a5c63aebe6f58b186cb5ab32baea5d96` proved, without literal payload values:

- qualified `IconaBridgeClient._open_door_init` and `IconaBridgeClient.open_door` selection;
- one init binary write + four message writes + one second binary write = exactly six Door writes;
- 10 structural components in each binary write and opened-channel request-id binding;
- typed canonical CTPP open/close request/response structures;
- canonical `_send_control -> encode_control_message -> VipSession.send_frame` path;
- capture-derived canonical open/open+close test coverage.

## Development-candidate CT120 runtime acceptance

Runtime evidence commit `8abec1e5c5dfe8759764fbd59296027039865d21` was produced from:

- Git SHA `3fed110624f91e2bc82097fe2b4e96fcbc6e28f4`;
- Git tree `7c30d9fd09a991f9a6946537423068991ef3cb25`;
- version `0.6.0.dev0`.

It established:

- repository offline suite: 79 tests PASS;
- pinned legacy synthetic body oracle: exactly 6 writes and 6 byte-exact canonical reframes;
- synthetic body sizes: 116, 69, 69, 95, 69, 69 bytes;
- canonical capture-based session tests: 13 PASS;
- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`;
- canonical CTPP control writes: exactly 2, channel id `7449`, typed open/close and matching binding;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`;
- full fixture transaction: 8 writes = 2 control + 6 Door data on one CTPP channel;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS`;
- `CT120_RUNTIME_GATES=PASS`;
- `REPOSITORY_READY=true`;
- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`;
- `SECRETS_READ=false`;
- `NETWORK_ACTION_PERFORMED=false`;
- `PHYSICAL_DOOR_ACTION=false`.

This closes the runtime-fixture proof for P6/P7/P8/P10/P11 on the development candidate. It does not authorize live transport or physical action.

## Final v0.6 candidate

The package version is now final `0.6.0`. Because version/docs changes alter the Git tree, the development runtime evidence cannot be used for deployment. The exact final tree must pass `scripts/run_ct120_runtime_gates.sh` again and publish a new evidence branch containing matching `RUNTIME_GATE_TREE_SHA` and `RUNTIME_GATE_VERSION=0.6.0`.

After that successful final-tree run, no repository content may change before PR merge. A squash merge is acceptable only if the resulting `main` tree is byte-identical to the tested tree; deployment checks the tree SHA and version.

## Still blocked by design

- real Comelit transport is not implemented;
- read-only real-session proof, target binding, authentication/session lifetime, timeout mapping and live audit remain P12 work;
- explicit physical-test approval remains a separate P13 gate;
- actual Home Assistant wiring to a real transport remains blocked by those gates.

## Next sequence

1. Keep repository CI green on the exact final `0.6.0` feature tree.
2. Run the unified CT120 runtime gates once on that exact tree/version.
3. Require `CT120_RUNTIME_GATES=PASS`, `REPOSITORY_READY=true`, `REAL_TRANSPORT_IMPLEMENTED=false`, `LIVE_TEST_READY=false` and matching tree/version evidence.
4. Open/review PR without changing the tested tree; merge.
5. Synchronize CT120 `main == origin/main` and verify the merged tree equals the tested tree.
6. Deploy immutable offline v0.6 using the final runtime gate report; retain v0.5 rollback until post-promotion acceptance completes.
7. Only then begin P12 read-only real-transport readiness work.
