# Offline acceptance contract

All items are mandatory:

1. Success path emits exactly: `PREPARED, SEND_ARMED, SENT, ACKED`.
2. One `operation_id` can cause at most one transport invocation.
3. `DefinitelyNotSent` terminates `FAILED_SAFE`.
4. Timeout/ambiguous send terminates `UNKNOWN_OUTCOME`.
5. Accepted send without acknowledgement terminates `UNKNOWN_OUTCOME`.
6. Crash in `PREPARED` recovers `FAILED_SAFE`, with zero sends.
7. Crash in `SEND_ARMED` recovers `UNKNOWN_OUTCOME`, with zero automatic retries.
8. Crash in `SENT` recovers `UNKNOWN_OUTCOME`, with zero automatic retries.
9. Rate limit blocks before transport invocation.
10. Real transport remains unimplemented and performs no network I/O.
11. Test suite prints `OFFLINE_SUITE=PASS`.
12. A typed boundary request fixes `attempt_number=1`; other values are rejected.
13. Boundary outcome mapping preserves the existing executor state semantics.
14. Boundary evidence cannot assert a physical actuator effect.
15. Duplicate `operation_id` cannot invoke the typed boundary twice.
16. Static safety scanning covers every Python source module in the package.

## v0.3

- canonical eight-file `comelit_vip` source hashes must match the pinned contract;
- full fixture stack must construct;
- exactly one synthetic fixture write must map to `ACCEPTED_NO_ACK`;
- executor state must be `UNKNOWN_OUTCOME`;
- duplicate operation id must not produce a second write;
- no network or physical action is permitted.

## v0.4

- research source hash and canonical ViP source hashes must remain pinned;
- the fixed semantic plan has 9 ordered steps: 1 channel precondition, 6 synthetic writes, 2 optional waits;
- the canonical channel-open primitive is not executed in v0.4;
- a complete six-write semantic fixture emission maps to `ACCEPTED_NO_ACK -> UNKNOWN_OUTCOME`;
- a fault after any partial write maps to `AMBIGUOUS`;
- a fault before the first write maps to `PROVEN_NOT_SENT`;
- duplicate operation id cannot execute the semantic plan twice;
- no credential-bearing payload, network transport, protocol ACK, or physical effect is permitted.

## v0.5 acceptance

- pinned canonical and legacy source hashes must match;
- six synthetic write steps use one CTPP channel id (`7449`);
- legacy framing and canonical fixture output are byte-exact equal for all six writes;
- measured framing delta is 8 bytes;
- double-framing negative control adds exactly one additional 8-byte header;
- no real Door payload is present;
- no canonical channel open is executed;
- complete fixture reconciliation maps to `UNKNOWN_OUTCOME` through the executor;
- failure after the third write maps to `AMBIGUOUS`;
- duplicate `operation_id` does not invoke the reconciliation boundary twice;
- no network or physical action occurs.

## v0.6 repository acceptance

- public-safe collectors contain no secret/capture-content reads or active Comelit probes;
- qualified `IconaBridgeClient` method selection is mandatory;
- pinned legacy structure contains exactly six Door writes in order: binary, message, message, binary, message, message;
- the two binary writes each contain 10 source components and use the opened channel id as ViP request id;
- structural fingerprints never embed real Door payload values;
- CTPP model allows at most one open and one close attempt;
- only a failure before any control/boundary attempt may be `PROVEN_NOT_SENT`;
- explicit rejected/not-opened control result may fail safe before Door data;
- ambiguous CTPP open is `AMBIGUOUS -> UNKNOWN_OUTCOME` even when zero Door data frames were emitted;
- any failure after a Door write is ambiguous;
- complete synthetic transaction without Door-specific ACK remains `UNKNOWN_OUTCOME`;
- repository readiness and live-test readiness are separate fail-closed gates;
- HA contract requires `operation_id`, forbids automatic retry, exposes `UNKNOWN_OUTCOME`, and cannot assert physical Door state;
- deployment refuses development versions, non-main branches, origin/main divergence, incomplete runtime readiness, or runtime reports for a different Git tree/version.

## v0.6 source/evidence inputs

Corrected public-safe structural evidence commit `db92d166a5c63aebe6f58b186cb5ab32baea5d96` establishes the pinned structural inputs used by runtime gates.

Development-candidate runtime evidence commit `8abec1e5c5dfe8759764fbd59296027039865d21`, from Git tree `7c30d9fd09a991f9a6946537423068991ef3cb25` and version `0.6.0.dev0`, established:

- repository offline suite PASS (79 tests);
- canonical capture-based session suite PASS (13 tests);
- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS` with exactly six legacy synthetic writes and six byte-exact canonical reframes;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS` with exactly two typed control writes and CTPP channel binding `7449`;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS` with exactly eight fixture writes = two control + six Door data;
- `CT120_RUNTIME_GATES=PASS`;
- `REPOSITORY_READY=true`;
- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`;
- no secrets read, network action or physical Door action.

That development evidence proves the implementation path but is not deploy evidence for the final tree.

## v0.6 final CT120/runtime acceptance required

Repository CI must not fabricate CT120 markers. Before PR merge/deploy, `scripts/run_ct120_runtime_gates.sh` must run on the exact final `0.6.0` tree and emit a new public-safe evidence branch containing:

- `RUNTIME_GATE_VERSION=0.6.0`;
- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS`;
- `CT120_RUNTIME_GATES=PASS`;
- `REPOSITORY_READY=true`;
- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`;
- `SECRETS_READ=false`;
- `NETWORK_ACTION_PERFORMED=false`;
- `PHYSICAL_DOOR_ACTION=false`.

The evidence `RUNTIME_GATE_TREE_SHA` must equal the final feature-tree SHA. No repository content may change after this final runtime PASS and before merge.

## v0.6 release/deploy acceptance

- package version is exactly `0.6.0`;
- deployment is permitted only from clean `main == origin/main`;
- merged `main` tree SHA must equal the final tested runtime tree SHA (squash-merge commit identity may differ, tree content may not);
- deployed version must equal tested runtime version;
- release files are produced from `git archive HEAD:safety-poc`, not untracked/ignored working-tree content;
- staged and promoted releases both pass the offline suite and release-content hashes;
- v0.5 remains rollback target until v0.6 post-promotion acceptance completes.

Live transport and physical Door actions are outside v0.6 offline acceptance and require separate later P12/P13 gates.
