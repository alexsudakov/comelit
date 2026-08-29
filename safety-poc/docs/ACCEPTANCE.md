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

## v0.6 repository-only acceptance

The following may be proven without live/runtime actions:

- the public-safe evidence collectors contain no secret/capture-content reads or active Comelit probes;
- corrected evidence uses qualified `IconaBridgeClient` method selection rather than an ambiguous function-name search;
- the pinned legacy AST layout contains exactly six Door writes in builder order: binary, message, message, binary, message, message;
- the two binary writes each contain 10 source components and use the opened channel id as ViP request id;
- those six writes map deterministically to the fixed Door semantic sequence;
- structural fingerprints never embed real Door payload values;
- the CTPP control-plane model allows at most one open and one close attempt;
- a synthetic full transaction contains one open, six Door writes, two optional waits and one close;
- a failure before any control/boundary attempt can be `PROVEN_NOT_SENT`;
- an explicit rejected/not-opened control result can fail safe without emitting Door data;
- an ambiguous CTPP open is `AMBIGUOUS -> UNKNOWN_OUTCOME` even when zero Door data frames were emitted;
- any failure after a Door write is ambiguous;
- a complete synthetic transaction without Door-specific ACK remains `UNKNOWN_OUTCOME`;
- repository readiness and live-test readiness are separate, fail-closed gates;
- the HA service contract requires `operation_id`, forbids automatic retry, exposes `UNKNOWN_OUTCOME`, and cannot assert physical Door state;
- Git-native deployment refuses development versions, non-main branches, origin/main divergence, incomplete runtime readiness, and runtime reports for a different Git tree/version.

## v0.6 corrected evidence v2

Public-safe evidence commit `db92d166a5c63aebe6f58b186cb5ab32baea5d96` establishes the structural inputs used by the runtime gates:

- qualified legacy methods are selected;
- `_open_door_init`: 1 binary write, 10 components, 1 open, 2 waits;
- `open_door`: 4 message writes + 1 binary write, 10 binary components, 2 waits;
- canonical control structures include typed open/close request/response channel ids and response words;
- canonical `_send_control` encodes a control message and sends it through `VipSession.send_frame`;
- canonical fixture tests include capture-derived local open and local open+close tests;
- evidence collection emitted no real Door payload values, secrets, active Comelit probes, or physical action.

## v0.6 CT120/runtime acceptance still required

Repository CI must **not** claim these markers. They are emitted only by `scripts/run_ct120_runtime_gates.sh` after the corresponding CT120 fixture proof succeeds:

- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS` — pinned legacy methods execute only with deterministic synthetic inputs and intercepted in-memory I/O; six generated frames reframe byte-exactly through the pinned canonical `VipSession + FixtureTransport` stack;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS` — canonical fixture executes `open_channel("CTPP") -> close_channel(same id)` using typed synthetic responses;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS` — one canonical fixture session performs `OPEN_CTPP -> six synthetic data frames -> CLOSE_CTPP` with exactly eight writes;
- `CT120_RUNTIME_GATES=PASS` and `REPOSITORY_READY=true` — all repository/runtime gates are combined successfully;
- runtime evidence records exact `RUNTIME_GATE_TREE_SHA` and `RUNTIME_GATE_VERSION` and is published to a public-safe evidence branch.

## v0.6 release/deploy acceptance

- final version must be `0.6.0`, not a development version;
- the final candidate must be runtime-tested again after the version change;
- deployment is permitted only from clean `main == origin/main`;
- deployed Git tree SHA and version must equal the tested runtime evidence tree/version;
- release files are produced from `git archive HEAD:safety-poc`, not from untracked/ignored working-tree content;
- staged and promoted releases both pass the offline suite and release-content hashes;
- v0.5 remains the rollback target until v0.6 post-promotion acceptance completes.

Live transport and physical Door actions are outside v0.6 offline acceptance and require separate later gates.
