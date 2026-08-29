# v0.6 repository-only status

Base: `main` at `57d75178fce7387264db5b0cb3b182e4ec5f91c7`.

## Implemented without CT120 runtime evidence

- public-safe CT120 plan evidence collector with automatic evidence branch/commit/push;
- literal-redacted source topology inventory;
- pinned legacy Door body structural inventory;
- typed parser for exactly six legacy Door write shapes;
- structural mapping to the fixed six semantic writes;
- deterministic synthetic placeholders for components whose static length is known;
- structural fingerprints that contain no real payload values;
- pure CTPP open/close state and channel-binding model;
- pure ten-step full Door transaction model over the existing one-shot boundary;
- repository-vs-live readiness evaluator;
- fail-safe Home Assistant `comelit.open_door` service contract;
- Git-native immutable deployment script with development-version/readiness/test gates and rollback;
- documentation and unit-test coverage for all of the above.

## Intentionally not claimed yet

The repository currently reports these as pending rather than PASS:

- `CTPP_BODY_LAYOUT_RECONCILIATION` — requires CT120 structural evidence and a synthetic byte oracle;
- `CTPP_CONTROL_PLANE_RECONCILIATION` — requires canonical fixture request/response evidence;
- `FULL_OFFLINE_DOOR_TRANSACTION` — requires canonical fixture composition of reconciled body and control-plane layers;
- final `0.6.0` release — current version is `0.6.0.dev0` and deployment is blocked;
- any real transport/live Door capability.

## Next sequence

1. Run only `scripts/collect_plan_evidence.sh` on the exact pinned feature-branch HEAD.
2. Review the pushed evidence branch in GitHub.
3. Use that evidence to complete the remaining CT120-dependent repository implementations.
4. Run offline/runtime test scripts.
5. Review PR and finalize `0.6.0` only if all repository gates pass.
6. Deploy the immutable offline v0.6 release.
7. Keep real transport/live-test work behind later explicit gates.
