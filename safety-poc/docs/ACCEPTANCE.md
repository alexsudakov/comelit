# Safety and readiness acceptance contract

## Core invariants

All items are mandatory:

1. Success path emits exactly `PREPARED, SEND_ARMED, SENT, ACKED`.
2. One `operation_id` can cause at most one transport invocation.
3. `DefinitelyNotSent` terminates `FAILED_SAFE`.
4. Timeout/ambiguous send terminates `UNKNOWN_OUTCOME`.
5. Accepted send without acknowledgement terminates `UNKNOWN_OUTCOME`.
6. Crash in `PREPARED` recovers `FAILED_SAFE`, with zero sends.
7. Crash in `SEND_ARMED` or `SENT` recovers `UNKNOWN_OUTCOME`, with zero automatic retries.
8. Rate limit blocks before transport invocation.
9. Boundary request fixes `attempt_number=1`.
10. Boundary evidence cannot assert a physical actuator effect.
11. Duplicate operation ids cannot invoke the boundary twice.
12. Static safety scanning covers every Python source module in the package.
13. Protocol acknowledgement is never proof of physical relay movement.

## v0.3–v0.5 completed offline gates

- canonical ViP source hashes are pinned;
- canonical fixture bridge is offline-only;
- fixed Door semantic plan contains six synthetic writes and two optional waits;
- all six v0.5 synthetic writes use one CTPP channel id (`7449`);
- legacy framing and canonical fixture output are byte-exact equal for all six writes;
- framing delta is 8 bytes and the double-framing negative control adds exactly one extra header;
- no real Door payload, network action or physical effect is part of these releases.

## v0.6 completed acceptance

Public-safe structural evidence and CT120 runtime gates established:

- qualified legacy method selection;
- exactly six Door writes in source order;
- synthetic byte-oracle reconciliation for all six writes;
- canonical CTPP open/close fixture reconciliation;
- full offline transaction with exactly eight fixture writes = two control + six Door data;
- conservative CTPP-open ambiguity handling;
- repository readiness separated from live-test readiness;
- fail-safe HA service contract;
- Git-tree/version-bound immutable deployment.

Final v0.6.0 runtime evidence was collected on Git tree `66539b16552725943c3a5577640fd327c86e744a`. PR #2 was squash-merged to `main` commit `f01d8c610daf6fe8d8fc9c02200726f684f39145` with that exact tree preserved.

CT120 immutable deployment completed to:

`/opt/comelit-door-safety-poc/releases/2026-08-29-v0.6.0-f01d8c610daf`

with rollback retained at:

`/opt/comelit-door-safety-poc/releases/2026-08-29-v0.5-eba2900dc82e`.

Staged and promoted offline suites and release-content hashes passed. The deployed release still records:

- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`;
- `PHYSICAL_DOOR_ACTION=false`.

## P12-A repository acceptance — read-only contract

Repository-only P12 work must prove all of the following without a network action:

- readiness is split into `REPOSITORY_READY`, `READONLY_TRANSPORT_READY`, and `LIVE_TEST_READY`;
- `READONLY_TRANSPORT_READY` cannot become true unless repository readiness is already true;
- `LIVE_TEST_READY` cannot become true unless read-only readiness is already true;
- fixed read-only application plan is exactly `CONNECT -> AUTHENTICATE -> LOAD_CONFIGURATION -> DISCOVER_TARGETS -> CLOSE`;
- session-control/query I/O is allowed, but actuator-command capability is forbidden;
- credential export is forbidden;
- automatic retry is forbidden;
- physical-effect assertion is forbidden;
- a complete read-only session proof becomes false if any actuator attempt, credential emission, automatic retry or physical-effect assertion is observed;
- no new real network backend is introduced during P12-A.

The transport architecture is independently constrained to the already proven P2P stack:

`cloud signaling -> same-agent ICE -> PseudoTCP -> ViP -> UAUT -> UCFG -> clean teardown`.

Direct TCP may not be promoted to the primary P12 path. Media activation and CTPP/Door actuation are outside this proof.

Expected repository markers:

- `P12_READONLY_SESSION_CONTRACT_TESTS=PASS`;
- `P12_READONLY_SOURCE_INVENTORY_TESTS=PASS`;
- `P12_P2P_TRANSPORT_CONTRACT_TESTS=PASS`;
- `P12_TRANSPORT_PRIMARY_PATH=CLOUD_P2P_ICE_PSEUDOTCP_VIP`;
- `REAL_TRANSPORT_IMPLEMENTED=false`;
- `READONLY_TRANSPORT_READY=false`;
- `ACTUATION_TRANSPORT_IMPLEMENTED=false`;
- `LIVE_TEST_READY=false`.

## P12-B CT120 source-evidence acceptance — completed no-network inventory

`scripts/collect_p12_readonly_evidence.sh` must publish a public-safe evidence branch and inventory only source/runtime metadata for:

- legacy connect/preflight/shutdown/auth/configuration/target-discovery methods;
- the top-level read-only discovery wrapper;
- canonical transport/session/channel/application interfaces;
- selected statically visible timeout values;
- current immutable release identity;
- credential-directory metadata only (presence, mode and file count).

Mandatory evidence markers:

- `P12_READONLY_SOURCE_INVENTORY=PASS`;
- `PUBLIC_SAFE_EVIDENCE=PASS`;
- `SECRETS_CONTENT_READ=false`;
- `CREDENTIAL_VALUES_COLLECTED=false`;
- `REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false`;
- `ACTIVE_COMELIT_NETWORK_PROBES=false`;
- `ACTUATOR_COMMAND_ATTEMPTED=false`;
- `PHYSICAL_DOOR_ACTION=false`.

Literal endpoint values, credential filenames/content, tokens and real Door payload bytes must not be emitted.

## P12-C CT120 P2P-holder forensic acceptance — no network

Before any credential-bearing probe, `scripts/collect_p12_p2p_forensic.sh` must establish the current research-runtime state without executing the holder or wrapper.

It must collect only hashes/metadata and boolean marker presence for:

- current P2P holder C source;
- current holder binary;
- current P2P wrapper;
- historical holder source/binary backups;
- toolchain/linkage names;
- active-holder process count without process arguments.

It must answer whether the current holder/wrapper includes the previously proven P2P/ICE/PseudoTCP/ECHO/UAUT-open stages, whether incomplete UAUT-auth/UCFG work is already present, and whether CTPP/Door actuator symbols have entered that path.

Mandatory safety markers:

- `PUBLIC_SAFE_EVIDENCE=PASS`;
- `SOURCE_EXECUTED=false`;
- `BINARY_EXECUTED=false`;
- `WRAPPER_EXECUTED=false`;
- `SECRETS_CONTENT_READ=false`;
- `ACTIVE_COMELIT_NETWORK_PROBES=false`;
- `ACTUATOR_COMMAND_ATTEMPTED=false`;
- `PHYSICAL_DOOR_ACTION=false`;
- `P12_P2P_FORENSIC_COLLECTION=PASS`.

No source line, binary string, wrapper line, process argument, endpoint value or credential value may be published.

## P12-D real read-only session acceptance — later explicit stage

Only after P12-C forensic evidence is reviewed may a controlled real read-only probe be prepared. The accepted sequence is fixed as:

`cloud signaling -> ICE -> PseudoTCP -> ECHO ACK -> UAUT OPEN -> UAUT access=200 -> UCFG read -> clean teardown`.

Read-only readiness requires independently verified markers for the session proof, read-only scope, target discovery/binding semantics, authentication/session lifetime and timeout mapping. No successful P12 result may set `LIVE_TEST_READY=true` by itself.

## P13 live-only acceptance

A physical Door test is outside P12. It additionally requires:

- `ACTUATION_TRANSPORT_IMPLEMENTED=true` from a separately reviewed implementation;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=true` from the operator;
- exact target, one-shot semantics, no automatic retry, timeout handling and abort conditions.

No repository-only commit or read-only probe may set the explicit approval marker on behalf of the operator.

## P13 repository acceptance — one-shot actuation contract

Repository-only P13 work must prove all of the following without a network
action or physical Door action:

- the fixed actuation plan is exactly
  `CLOUD_SIGNALING -> ICE -> PSEUDOTCP -> VIP_ECHO -> UAUT_OPEN -> UAUT_AUTH ->
  CTPP_OPEN -> DOOR_WRITES -> CTPP_CLOSE -> CLEAN_TEARDOWN`;
- `attempt_number=1` only, enforced by `TransportRequest`;
- one `operation_id` can cause at most one transport invocation;
- duplicate operation ids never send again;
- `SEND_ARMED` remains the irreversible ambiguity boundary, persisted before
  the single transport call;
- post-`SEND_ARMED` uncertainty => `UNKNOWN_OUTCOME`, never retried
  automatically;
- protocol ACK is never proof of physical relay movement;
- `physical_effect_asserted=true` is forbidden in every evidence type;
- a durable append-only audit journal records transport attempts and outcomes
  with fsync before acknowledgement;
- the non-actuating preflight keeps `EXPLICIT_LIVE_TEST_APPROVAL=false` and
  `LIVE_TEST_READY=false`;
- prepared real Door payload bodies stay root-only (mode 0600), are never
  committed, and are never emitted to stdout/evidence/Codex context;
- credentials are never exported, committed, or sent to external model context.

Expected repository markers:

- `P13_ACTUATION_TRANSPORT_MODEL_TESTS=PASS`;
- `P13_AUDIT_SINK_TESTS=PASS`;
- `P13_ACTUATION_BOUNDARY_TESTS=PASS`;
- `P13_ONE_SHOT_EXECUTOR_INTEGRATION_TESTS=PASS`;
- `P13_ACTUATION_PREFLIGHT_TESTS=PASS`;
- `P13_REAL_PAYLOAD_PREP_TESTS=PASS`;
- `P13_PRIMARY_PATH=CLOUD_P2P_ICE_PSEUDOTCP_VIP_CTPP`;
- `P13_ATTEMPT_NUMBER_FIXED=1`;
- `P13_AUTO_RETRY_ALLOWED=false`;
- `P13_PHYSICAL_EFFECT_ASSERTION_ALLOWED=false`;
- `ACTUATION_TRANSPORT_IMPLEMENTED=true`;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=false`;
- `LIVE_TEST_READY=false`.

P13 repository readiness cannot open the live-test gate: the operator approval
marker is set only by the operator at the final physical execution step.
