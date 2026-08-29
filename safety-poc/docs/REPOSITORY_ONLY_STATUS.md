# v0.6 repository-only status

Base: `main` at `57d75178fce7387264db5b0cb3b182e4ec5f91c7`.

## Implemented without live/runtime actions

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
- repository-only GitHub Actions static-safety/unit/CLI workflow;
- documentation and unit-test coverage for all of the above.

## Evidence v1 review

Evidence commit `153e1864d947e9ff0a5386f2d60b4b87d117c239` proved:

- public-safe collector invariants;
- legacy/canonical source pins;
- current runtime remains immutable v0.5;
- operator wrapper identities and secret-directory mode without reading secret contents;
- passive network inventory without active probes, IP addresses or MAC addresses.

Repository review also found the v1 body inventory selected the top-level `open_door` wrapper instead of the class method. That bundle therefore cannot establish P6 body-layout acceptance. The defect was corrected before deploy/runtime testing.

## Corrected evidence still required

Run `scripts/collect_plan_evidence_v2.sh` from the exact feature-branch head. It collects:

- corrected `IconaBridgeClient._open_door_init` and `IconaBridgeClient.open_door` shapes;
- expanded starred body components when statically recoverable;
- outer-method write/read/open/close/wait counts;
- canonical `VipChannelSession`/`VipSession` method shapes;
- control-codec field shapes;
- canonical fixture-test call shapes;
- canonical Python tree hashes/sizes.

## Intentionally not claimed yet

The repository reports these as pending rather than PASS:

- `CTPP_BODY_LAYOUT_RECONCILIATION` — corrected structural evidence plus a synthetic byte oracle are required;
- `CTPP_CONTROL_PLANE_RECONCILIATION` — canonical fixture request/response evidence is required;
- `FULL_OFFLINE_DOOR_TRANSACTION` — canonical fixture composition of reconciled body and control-plane layers is required;
- final `0.6.0` release — current version is `0.6.0.dev0` and deployment is blocked;
- any real transport/live Door capability.

## Next sequence

1. Repository CI must be green on the exact feature head.
2. Run only `scripts/collect_plan_evidence_v2.sh` on CT120.
3. Review the pushed v2 evidence branch in GitHub.
4. Complete all newly unblocked repository-only body/control/transaction implementations.
5. Run CT120 offline/runtime fixture scripts.
6. Review PR and finalize `0.6.0` only if all repository gates pass.
7. Deploy the immutable offline v0.6 release, retaining v0.5 rollback.
8. Keep real transport/live-test work behind later explicit gates.
