# P76 RTPC C Runtime Parity

## Status

RTPC_C_RUNTIME_PARITY_CONTRACT=PROVEN_OFFLINE
C_RUNTIME_BASE=P46_REVIEWED_TRANSFORM_CHAIN
REGISTERED_CTPP_REUSED=true
SECOND_CTPP_OPEN=false
RTPC_TARGET_ALLOCATOR=P73_PARITY
RTPC_OPEN_GENERATION=P74_PARITY
RTPC_CONTROL_STATE_MACHINE=P75_PARITY
CLIENT_RESPONSE_DEVICE_OPEN_BINDING=PROVEN
CLIENT_000A_ALLOCATION_BINDING=PROVEN
CLIENT_001A_ALLOCATION_BINDING=PROVEN
CONTROL_TOTAL_ORDER_REQUIRED=false
COLLISION_SKIP_SUPPORTED=true
PYTHON_C_DIFFERENTIAL_PARITY=PASS
NETWORK_IO_PERFORMED=false
LIVE_INVOCATIONS=0
DOOR_ACTION_SENT=false
MEDIA_SESSION_STARTED=false
LIVE_TRANSMISSION_AUTHORIZED=false

## Provenance Chain

P76 composes the reviewed transform chain instead of reimplementing earlier
entrance signaling:

1. Frozen v1.5.7 C candidate:
   `research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`.
2. P46 reviewed device-video ACK observation transform:
   `entrance_device_video_ack_observation_transform.transform`.
3. P76 RTPC CONTROL/media runtime transform:
   `entrance_rtpc_control_media_runtime_transform.transform`.

The P76 transform appends one bounded C runtime section to the P46 output.  It
does not introduce a launcher and does not alter historical P46-P75 artifacts.

P46_P75_HISTORY=PRESERVED

## Runtime Boundary

The injected C section implements:

- P73 allocator parity:
  `candidate = ((high_halfword << 15) | low15_counter) & 0xffff`, then
  `next_low = (low15_counter + 1) & 0x7fff`, occupied-id skip, id-0 MGMT
  occupancy on the constructor-equivalent path, and bounded exhaustion.
- P74 body parity for exactly two allocator-backed RTPC OPENs, client `0x000A`,
  and client `0x001A`.
- P75 semantic state parity for device RTPC OPEN acceptance, client RESPONSE
  generation from the device OPEN target, independent pairing of two device
  RESPONSEs, and completion only after all required facts are present.

The deterministic harness injects the synthetic `rand()` result into the same
allocator core used by the C runtime section.  It does not bypass production
candidate allocation logic.

RTPC_TARGET_ID_START_VALUE=RUNTIME_STATE_DEPENDENT
CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false

## Differential Oracle

The P76 unit tests compute expected bytes at test time using P74/P75 Python
models:

- client RTPC OPEN #1.
- client RTPC OPEN #2.
- client RESPONSE to the device RTPC OPEN.
- client `0x000A`.
- client `0x001A`.

The C harness emits only bounded synthetic generated body hex and semantic
state lines.  The tests require byte equality against the Python oracle for the
canonical, alternative-response-order, and collision-skip scenarios.

PYTHON_C_DIFFERENTIAL_PARITY=PASS

## Interleavings

CONTROL_TOTAL_ORDER_REQUIRED=false

The canonical scenario accepts device RESPONSE for allocation #1 before
allocation #2.  The alternative scenario accepts allocation #2 before
allocation #1 and still completes.  Pairing is by target id, not by capture
order and not by a strict `+1` numeric relation.

## Collision And Exhaustion

COLLISION_SKIP_SUPPORTED=true

The collision scenario pre-marks the second candidate as occupied.  Allocation
#2 skips that occupied id and the generated second RTPC OPEN and client
`0x001A` bind to the actual returned allocation.  Exhaustion fails closed with
an explicit typed error marker and no partial success.

## Fail-Closed Coverage

The P76 harness tests reject:

- malformed device OPEN.
- malformed RESPONSE.
- RESPONSE before client OPEN.
- unknown RESPONSE target.
- duplicate RESPONSE.
- reused client target id.
- allocator exhaustion.
- client RESPONSE generated without device OPEN.
- incorrect `0x000A` allocation binding.
- incorrect `0x001A` allocation binding.
- second CTPP OPEN attempt.
- Door entrypoint reachability.
- partial state reported as COMPLETE.

## Static Safety

HARNESS_NETWORK_CAPABLE=false
LIVE_LAUNCHER_ADDED=false
SECOND_CTPP_OPEN=false
DOOR_SURFACE_REACHABLE=false
CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false
RAW_MEDIA_PROCESSED=false

The harness is plain C and compiles with `cc` only.  It does not include glib,
libnice, PseudoTCP, socket, DNS, ICE/STUN/TURN, live CTPP, RTPC transmission,
Door action, RTP, H.264, Home Assistant, or media processing entrypoints.

NETWORK_IO_PERFORMED=false
LIVE_INVOCATIONS=0
RTPC_SIGNALING_SENT=false
CTPP_SIGNALING_SENT=false
DOOR_ACTION_SENT=false
MEDIA_SESSION_STARTED=false
RAW_PAYLOAD_EMITTED=false
PROPRIETARY_ARTIFACTS_COMMITTED=false
