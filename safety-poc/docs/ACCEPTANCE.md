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

The following may be proven without CT120 runtime execution:

- the public-safe evidence collector contains no secret/capture-content reads or active Comelit probes;
- a redacted legacy inventory can be parsed into exactly six typed write shapes;
- the structural builder order is exactly binary, message, message, binary, message, message;
- those six writes map deterministically to the fixed Door semantic sequence;
- structural fingerprints never embed real Door payload values;
- the CTPP control-plane model allows at most one open and one close attempt;
- a synthetic full transaction contains one open, six Door writes, two optional waits and one close;
- failures before the first Door write are provably not sent; failures after a Door write are ambiguous;
- a complete synthetic transaction without Door-specific ACK remains `UNKNOWN_OUTCOME`;
- repository readiness and live-test readiness are separate, fail-closed gates;
- the HA service contract requires `operation_id`, forbids automatic retry, exposes `UNKNOWN_OUTCOME`, and cannot assert physical Door state;
- Git-native deployment refuses development versions and incomplete repository readiness.

## v0.6 CT120/runtime acceptance still required

Repository-only tests must **not** claim these markers. They remain pending until independent evidence is produced:

- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS` — synthetic byte-exact CTPP body oracle over the pinned source layout;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS` — canonical fixture open/close request-response contract and channel binding;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS` — canonical fixture transaction using reconciled body/control-plane models;
- final v0.6 version promotion from development version;
- immutable CT120 release install and post-promotion acceptance.

Live transport and physical Door actions are outside v0.6 offline acceptance and require separate later gates.
