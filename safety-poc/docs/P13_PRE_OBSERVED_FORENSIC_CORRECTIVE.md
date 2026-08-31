# P13 pre-observed-acceptance forensic corrective

Status: **repository implemented / CT120 forensic deployment pending**.

This corrective was added after review of the first real P13 transport attempt.
It does not authorize or perform a new physical Door action.

## Why this corrective exists

The first real P13 operation proved one audited transport invocation, CTPP open,
six prepared writes, clean CTPP close and teardown, but physical observation was
unavailable and a Door-specific ACK was not proven.

Before spending the next physically observed attempt, three evidence gaps are
closed as far as possible offline:

1. reconcile the prepared standalone transaction against the primary
   `self_activation.pcap` rather than only against another implementation;
2. preserve inbound CTPP bodies from the next real run without mislabelling a
   generic channel response as a Door ACK;
3. make target provenance explicit across P12 UCFG, self-activation capture and
   the prepared payload.

## D1 primary-capture reconciliation

Tool:

`safety-poc/scripts/p13_d1_pcap_forensic.py`

Default CT120 inputs:

- `/root/comelit-artifacts/self_activation.pcap`;
- `/root/comelit-p13-actuator-prep/real-door-payloads.json`.

The tool is offline only. It imports Scapy solely to read the local PCAP; it
contains no network client or actuator call.

It:

- reassembles PseudoTCP conversation 0 by sequence number;
- removes retransmission overlap and rejects conflicting retransmissions;
- parses ViP framing only after stream reassembly;
- locates exactly one capture-confirmed active-call Door frame by:
  - opcode `0x1840`;
  - the `00 2d + address + output` semantic;
  - a public-safe SHA-256 pin of the entrance/output pair;
- reads the six root-only prepared standalone bodies;
- validates their stored length/SHA metadata;
- compares primary-capture Door semantics with the prepared bodies;
- verifies that the prepared operation suffix is the recovered standalone
  `0x1800, 0x1820, 0x18C0, 0x1800, 0x1820` sequence;
- classifies the relationship as one of:
  - `EXACT_ACTIVE_CALL_BODY_MATCH`;
  - `SEMANTIC_TARGET_MATCH_DIFFERENT_CONTEXT`;
  - `CONTRADICTION`.

The CT120 deployment additionally binds this parser to the independently
rechecked primary fixture invariants:

- outgoing ViP frames: `59`;
- incoming ViP frames: `52`;
- PseudoTCP gaps: `0/0`;
- conflicting retransmissions: `0/0`;
- one exact capture-pinned seven-byte pre-ViP prefix
  `00030100fe0100` in each selected direction;
- parser-skipped bytes: `7/7`, consisting only of that prefix;
- no extra bytes between ViP frames or after the final ViP frame.

The first CT120 forensic deployment exposed that the earlier repository
assumption `unframed reassembled bytes: 0/0` was incorrect.  Offline inspection
of the primary capture proved that both directions contain the same single
seven-byte prefix at stream offset zero, with the first ViP frame beginning at
offset seven.  The corrective treats those bytes only as a capture-pinned
framing invariant and does not assign them unproven protocol semantics.

A contradiction stops deployment before any live-capable action.

### ACK semantics

D1 does **not** equate `request_id == CTPP channel` with an ACK.

It emits:

- `P13_D1_DOOR_SPECIFIC_ACK=PROVEN` only if an inbound CTPP body itself
  carries the same capture-pinned target/output semantic;
- `NOT_DISTINGUISHABLE` when a correlatable response is indistinguishable from
  neighboring channel responses;
- `UNKNOWN` when the PCAP does not support a stronger conclusion.

A merely unique response body is not promoted to Door ACK.

The current physical state machine remains conservative unless a separate
review explicitly adopts a proven Door-specific ACK signature.

## Active-call vs standalone decision

The primary capture proves an active-call operation on this installed system.
The current P13 candidate is the recovered standalone peer/TAP sequence.

Decision rule:

- `EXACT_ACTIVE_CALL_BODY_MATCH` or
  `SEMANTIC_TARGET_MATCH_DIFFERENT_CONTEXT` **plus the expected standalone
  operation suffix** keeps standalone as an acceptable observed-test candidate;
- `CONTRADICTION` stops the observed test.

A D1 contradiction does **not** automatically switch the evening test to an
active-call implementation. The active-call path must first be implemented,
offline-tested, CI-validated and given its own non-actuating preflight.

## Root-only RX evidence for the next live run

Transform layering:

`p13_holder_transform.py`
`-> p13_holder_transform_safe.py`
`-> p13_holder_transform_evidence.py`
`-> p13_holder_transform_runtime_binding.py`

The safe transform already removed the old per-write ACK dependency and matches
the recovered peer/TAP cadence:

- register write;
- about 200 ms register settle;
- five operation writes back-to-back;
- about 1 s post-write settle;
- CTPP close.

The evidence transform does **not** alter that timing.

For every inbound frame after CTPP has opened whose `request_id` equals the
actual CTPP channel id, the generated holder writes to its normal holder log:

- monotonic timestamp;
- P13 stage;
- request id;
- body length;
- SHA-256(body);
- full body hex.

Marker:

`P13_CTPP_RX_EVIDENCE ...`

The real session redirects holder stdout/stderr into:

`/root/comelit-p13-run/p13-live-run.log`

mode `0600`. Unknown holder lines are not propagated by the Python adapter into
Hermes/public evidence.

The semantic marker is now explicitly:

`P13_DOOR_RESPONSE_SEEN=true`

and **not** `ACKED=true`.

The frozen evidence from the first attempt does not need an erratum: its public
classification already states `UNKNOWN_OUTCOME`, `SENT_TO_ACKED_COUNT=0` and
`Door-specific acknowledgement unproven`.

## Target provenance gate

Tool:

`safety-poc/scripts/p13_target_provenance.py`

It verifies three independent layers:

1. **Apartment/session identity**
   - exact P12 UCFG SHA-256;
   - unique apt-address hash;
   - unique apt-subaddress hash.
2. **Actuator identity**
   - the prepared six-body bundle contains the self-activation-capture-pinned
     `entrance|output` semantic;
   - the prepared target fingerprint equals the reviewed target fingerprint.
3. **Current UCFG action metadata**
   - missing/empty `opendoor-actions` => `P13_UCFG_OUTPUT_INDEX=ABSENT`, visible
     but non-blocking;
   - present peer action with the capture-pinned output => `MATCH`;
   - present contradictory/non-peer/incomplete action metadata => `MISMATCH`,
     hard failure.

This deliberately preserves `ABSENT != MISMATCH`.

## CT120 deployment

Non-actuating deployment entrypoint:

`safety-poc/scripts/deploy_p13_forensic_upgrade_ct120.sh`

It performs, in order:

1. exact branch/local-origin/clean-worktree checks;
2. input/permission checks;
3. corrective unit tests;
4. D1 primary-PCAP analysis and primary-fixture invariant gate;
5. target-provenance gate;
6. evidence-enabled safe native holder rebuild;
7. P13 runtime identity recapture;
8. existing non-actuating P13 preflight;
9. existing observed-acceptance readiness, including a positive
   `P13_HERMES_OBSERVED_GATE_UNUSED=true` check;
10. stop.

It never calls `comelit-p13-observed-open`, the observed live gate, the physical
runner, or the native holder as a live Comelit process.

Success marker:

`P13_FORENSIC_UPGRADE_DEPLOY=PASS`

with:

- `NETWORK_DOOR_ACTION_PERFORMED=false`;
- `PHYSICAL_DOOR_ACTION=false`;
- `SEND_ARMED_REACHED=false`;
- `P13_ACTUATOR_COMMAND_ATTEMPTED=false`;
- `P13_PHYSICAL_EFFECT_ASSERTED=false`.

## Gate generation / reset rule

The existing observed gate remains single-use. This corrective adds no reset
path.

If a future gate generation is consumed before an apparent transport result:

- forensic proof of `SEND_ARMED=false` and zero transport invocations may justify
  creating a **new gate generation**;
- if `SEND_ARMED=true` or the send state is ambiguous, no re-arm/reset is
  allowed.

## Physical observation protocol

Before a future observed attempt:

- the operator is already at the intended entrance;
- the door is explicitly checked closed/latched immediately before the command;
- the command is initiated through Hermes while the operator remains at the
  entrance.

Record separately:

- `DOOR_LATCHED_BEFORE_TEST=true`;
- `RELAY_CLICK_OBSERVED=true|false|unknown`;
- `DOOR_RELEASE_OBSERVED=true|false|unknown`;
- approximate latency if observable;
- final `PHYSICAL_OBSERVATION=OPENED|NOT_OPENED|UNAVAILABLE`.

A later ordinary/intercom control check after `NOT_OPENED` must have a separate
timestamp so its physical effect cannot be confused with P13.

## Current boundary

Repository implementation and GitHub CI can validate the corrective code, but
actual D1/provenance results for the real PCAP/payload must not be claimed until
the CT120 deployment entrypoint has run successfully.

No new physical approval is implied by this document or by deployment.
