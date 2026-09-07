# P75 RTPC CONTROL Media State Machine

## Status

RTPC_CONTROL_STATE_MACHINE_CONTRACT=PROVEN_OFFLINE
RTPC_MEDIA_SETUP_STATE_MACHINE=PROVEN_OFFLINE_COMPOSED
LIVE_TRANSMISSION_AUTHORIZED=false
NETWORK_IO_PERFORMED=false
DNS_LOOKUP_PERFORMED=false
P2P_ICE_STUN_TURN_PERFORMED=false
PSEUDOTCP_PERFORMED=false
CTPP_SIGNALING_SENT=false
RTPC_SIGNALING_SENT=false
DOOR_ACTION_SENT=false
CAMERA_MEDIA_SESSION_STARTED=false
RAW_PAYLOAD_EMITTED=false
PROPRIETARY_ARTIFACTS_COMMITTED=false

## Evidence Sources

P75 composes the repository's promoted offline layers and does not re-derive
the protocol from scratch.

- P51/P52: bounded media-transition timeline and ACK/media-event relationships.
- P60-P65: client 0x000A and 0x001A body relations, address-role placement,
  sequence relation, and target-id binding positions.
- P66: runtime RTPC target-id relation.
- P67: historical nearest-response reflection hypothesis rejected and
  preserved as rejected history.
- P68: typed ABCD OPEN/RESPONSE structural pairing.
- P69: OPEN trailer isolated from pairing; trailer semantics remain separate.
- P70/P71: RTPC OPEN transport contract.
- P72: composed RTPC OPEN, 0x000A, and 0x001A bodies.
- P73: allocator semantics for RTPC target ids.
- P74: allocator-backed composition of two client RTPC OPENs, client 0x000A,
  and client 0x001A.

## Schemas Used

DEVICE_RTPC_OPEN_SCHEMA=PROVEN

An RTPC OPEN is accepted through the P69 envelope check: 15 bytes, ABCD family,
OPEN opcode, declared length 7, RTPC channel tag, non-zero target id at the
P68/P69 target field, and a bounded one-byte trailer. P75 does not promote the
trailer scalar beyond the already established OPEN transport contract.

DEVICE_RTPC_OPEN_CLIENT_RESPONSE_BINDING=PROVEN
CLIENT_RESPONSE_TO_DEVICE_OPEN_CONTRACT=PROVEN

An RTPC RESPONSE uses the P68 response contract: 12 bytes, ABCD family,
RESPONSE opcode, declared length 4, non-zero target id in the response target
field, and zero status/reserved word. The client response to a device-originated
OPEN is generated from that device OPEN target. It is not copied from the
nearest device RESPONSE; P67's reflection hypothesis remains rejected.

RESPONSE_PAIRING_KEY=TARGET_ID

Device responses pair to client OPENs only by the target id of one earlier
opposite-direction OPEN. Unknown targets, duplicate responses, malformed
responses, response-before-open, and ambiguous target matches fail closed.

## State Definitions

The semantic state tracks facts rather than capture bytes:

- device_open_seen and the dynamic device_open_target.
- client_allocation_1 and client_allocation_2 from P74/P73.
- client_open_1_emitted and client_open_2_emitted.
- device_response_1_seen and device_response_2_seen.
- client_response_to_device_open_emitted.
- client_000a_generated and client_001a_generated.
- optional ACK/media facts: client_000a_acknowledged,
  client_001a_acknowledged, and device_media_event_seen.

States differentiate NOT_SEEN, SEEN, GENERATED, PAIRED, ACKNOWLEDGED, and
INVALID. Capture-specific numeric identifiers are never constants.

CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false

## Transitions

1. Observe device RTPC OPEN.
   Validates the P69/P68 RTPC OPEN structure and records only its dynamic
   target id in state.

2. Generate client allocator-backed exchange.
   Calls P74 with a P73 allocator state and media context. P75 validates:
   allocation_1.target_id == OPEN_1[12:14],
   allocation_2.target_id == OPEN_2[12:14], allocation ids are distinct, and
   0x000A/0x001A bind to allocation #1/#2 respectively. No caller-supplied ids
   enter this transition.

CLIENT_RTPC_OPEN_COUNT=2
CLIENT_RTPC_OPEN_SOURCE=P74_ALLOCATOR_BACKED_GENERATION
CLIENT_000A_BINDING=ALLOCATION_1
CLIENT_001A_BINDING=ALLOCATION_2

3. Observe device RESPONSE.
   Validates the 12-byte typed response and pairs it to exactly one client
   OPEN by target id. The two device responses are independent; numeric +1 is
   not required by P75.

DEVICE_RESPONSE_PAIRING_CONTRACT=PROVEN

4. Generate or observe client RESPONSE to device OPEN.
   Requires the device OPEN and validates that the response target is the
   device OPEN target, not a target from a device RESPONSE.

5. Generate client 0x000A.
   Requires allocation/open #1 and validates the P74 0x000A binding to
   allocation #1. It does not wait for every CONTROL RESPONSE.

6. Generate client 0x001A.
   Requires allocation/open #2 and validates the P74 0x001A binding to
   allocation #2. P75 does not invent an ACK gate for 0x001A.

7. Optional ACK/media transitions.
   ACK and device-media-event state transitions are represented only where
   P51/P52/P60-P65 prove a local prerequisite. They are not used to impose a
   total CONTROL order.

## Causal Order vs Observed Order

CONTROL_CAUSAL_ORDER=PROVEN_PARTIAL_ORDER

Required causal constraints:

- A RESPONSE must follow and match exactly one earlier opposite-direction OPEN.
- A client response to a device OPEN requires that device OPEN.
- Client 0x000A requires allocation/open #1 and binds to allocation #1.
- Client 0x001A requires allocation/open #2 and binds to allocation #2.
- ACK/media-event transitions require their proven source semantic event.

Observed but not promoted to total causal order:

- The frozen capture order of the two device responses.
- A requirement that 0x000A waits for every CONTROL RESPONSE.
- A requirement that 0x001A is gated by an invented ACK.
- Any numeric sequential target relation beyond P73/P74 allocator output.

DEVICE_RESPONSE_ORDER_TOTALITY=NOT_PROVEN
RTPC_000A_WAIT_FOR_EVERY_CONTROL_RESPONSE=NOT_PROVEN
RTPC_001A_ACK_GATE=NOT_PROVEN

CONTROL_OBSERVED_ORDER=CAPTURE_VALIDATED when the SHA-gated external pcap is
provided and P68/P69 map the observed official-client sequence. Otherwise the
default report uses NOT_PROVIDED for the capture gate and still proves the
offline synthetic contract.

## Frozen Capture Validation

The optional CLI path accepts:

`--pcap /home/hermes/comelit-p70-codex/input/self_activation.pcap`

The pcap must match SHA256
`f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a`.
The validation reuses P68/P69 extraction and emits only semantic counts and
markers: no target ids, addresses, endpoints, raw CONTROL bytes, media payload,
or authorization material.

CONTROL_OBSERVED_ORDER=CAPTURE_VALIDATED
RAW_PAYLOAD_EMITTED=false

## Invalid Transitions

The implementation and tests reject:

- RESPONSE before matching OPEN.
- Unknown RESPONSE target.
- Duplicate device RESPONSE.
- Missing response as incomplete, never silently complete.
- Ambiguous response pairing.
- Second client OPEN reusing allocation #1.
- Client RESPONSE bound to a device RESPONSE target instead of the device OPEN
  target.
- Client 0x000A bound to allocation #2.
- Client 0x001A bound to allocation #1.
- Capture-specific strict ordering where only partial causal order is proven.
- Malformed ABCD OPEN.
- Malformed ABCD RESPONSE.

## Remaining Unknowns

OPEN_TRAILER_SEMANTICS=NOT_PROVEN
DEVICE_RESPONSE_ORDER_TOTALITY=NOT_PROVEN
RTPC_000A_WAIT_FOR_EVERY_CONTROL_RESPONSE=NOT_PROVEN
RTPC_001A_ACK_GATE=NOT_PROVEN

No live transmission, DNS, P2P, PseudoTCP, CTPP, RTPC signaling, camera media
session, door action, packet replay, media capture, or proprietary artifact
commit is authorized by this work.

P51_HISTORY_MARKER=PRESERVED
P52_HISTORY_MARKER=PRESERVED
P60_P65_HISTORY_MARKER=PRESERVED
P66_HISTORY_MARKER=PRESERVED
P67_HISTORY_MARKER=NEAREST_RESPONSE_REFLECTION_REJECTED_PRESERVED
P68_HISTORY_MARKER=PRESERVED
P69_HISTORY_MARKER=PRESERVED
P70_P74_HISTORY_MARKER=PRESERVED
