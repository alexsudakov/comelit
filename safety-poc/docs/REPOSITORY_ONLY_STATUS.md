# v0.6 repository-only status

Base: `main` at `57d75178fce7387264db5b0cb3b182e4ec5f91c7`.

## Implemented without live actions

- public-safe CT120 plan evidence collection with automatic evidence branch/commit/push;
- corrected qualified-method legacy Door body inventory;
- literal-redacted source topology and canonical control-plane API/test topology collectors;
- typed parser for exactly six legacy Door write shapes;
- structural mapping to the fixed six semantic writes;
- deterministic synthetic placeholders for components whose static length is known;
- structural fingerprints that contain no real payload values;
- pure CTPP open/close state and channel-binding model;
- pure ten-step full Door transaction model over the existing one-shot boundary;
- conservative handling of ambiguous CTPP open (never downgraded to `PROVEN_NOT_SENT`);
- repository-vs-live readiness evaluator;
- fail-safe Home Assistant `comelit.open_door` service contract;
- Git-native immutable deployment script with development-version/readiness/test gates and rollback;
- repository-only GitHub Actions static-safety/unit/CLI/script-compile workflow;
- CT120-only sandboxed synthetic body oracle;
- CT120-only canonical CTPP open/close fixture gate;
- CT120-only full canonical 8-write transaction fixture gate;
- unified CT120 runtime-gate runner and marker aggregation;
- documentation and unit-test coverage for all repository models.

## Evidence v1 review

Evidence commit `153e1864d947e9ff0a5386f2d60b4b87d117c239` proved public-safe collector invariants, legacy/canonical source pins, runtime v0.5 identity, operator-boundary identities, and passive network shape. Its body inventory selected the top-level `open_door` wrapper instead of the class method, so the v1 body report is explicitly not accepted for P6.

## Corrected evidence v2

Evidence commit `db92d166a5c63aebe6f58b186cb5ab32baea5d96` was collected from feature HEAD `67ebc220d01d60e645acf14422c633846bb7a979` and corrects the v1 selector defect.

It proves, without emitting literal payload values:

- `IconaBridgeClient._open_door_init` performs one binary write built from 10 components, one CTPP open, and two waits;
- `IconaBridgeClient.open_door` performs four `create_door_message(confirm)` writes plus one 10-component binary write and two waits;
- the combined legacy Door sequence contains exactly six Door writes;
- all Door binary writes use the opened channel id as the ViP request id;
- canonical `VipChannelSession.open_channel` and `close_channel` use typed control-codec messages and `_send_control -> encode_control_message -> VipSession.send_frame`;
- canonical control-codec structures include typed open/close request/response channel ids and response words;
- canonical fixture tests include capture-derived local open and local open+close coverage;
- no source, secret, real Door payload value, active Comelit probe, or physical Door action was collected by the evidence bundle.

## Runtime gates prepared but not yet executed on CT120

The repository now contains `scripts/run_ct120_runtime_gates.sh`, which will later run:

1. repository offline safety suite;
2. pinned legacy synthetic body oracle with all network-facing instance methods replaced by in-memory doubles;
3. pinned canonical capture-based session tests;
4. CTPP-specific canonical fixture open/close;
5. full canonical `OPEN_CTPP -> six synthetic data frames -> CLOSE_CTPP` fixture;
6. combined repository readiness evaluation.

Expected runtime markers are:

- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS`;
- `REPOSITORY_READY=true`.

These markers are intentionally not claimed from repository code alone.

## Still blocked

- final `0.6.0` version and immutable deployment remain blocked until the CT120 runtime gates pass;
- real transport remains unimplemented;
- read-only real-session proof, target binding, authentication/session lifetime, timeout mapping, live audit, and explicit live-test approval remain later P12/P13 gates;
- actual Home Assistant wiring remains blocked by those live gates.

## Next sequence

1. Keep repository CI green on the exact feature HEAD.
2. Run `scripts/run_ct120_runtime_gates.sh` on CT120.
3. Review all generated gate reports and hashes.
4. Fix repository/runtime-fixture defects if any; do not weaken safety gates.
5. When all repository gates pass, update version to final `0.6.0`, review the PR, and merge.
6. Deploy the immutable offline v0.6 release from the merged Git commit, retaining v0.5 rollback.
7. Only after that begin P12 read-only real-transport readiness work; live Door action remains a separate explicit gate.
