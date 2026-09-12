# P116 R15 — official-app media maintenance contract

## Status

```text
PHASE=P116_R15
MODE=RESEARCH_OFFLINE
BASE_SHA=3fec73f77c6f7b19e7177e2793d579b43bc02104
FUNCTIONAL_FIX_IMPLEMENTED=false
LIVE_RUN_EXECUTED=false
HA_DEPLOY=NOT_RUN
HA_RESTART=NOT_RUN
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
RAW_PCAP_IN_GIT=0
```

R15 re-analyses the already captured official-app PCAP from R14 and compares it
with the promoted P72/P75/P76/P78/P80 helper contracts. No new Comelit session,
Home Assistant change, packet replay, or production functional change was made.

Raw PCAP provenance, retained outside Git:

```text
SHA256=3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f
SIZE=3773269
```

The user did not explicitly enable audio. PT8 therefore remains
`OBSERVED_FOR_THIS_CAPTURE` as an automatic component of the normal camera media
session; it is not evidence of a user-enabled talk/audio mode.

## R14 correction: PseudoTCP must be analysed as a byte stream

R14 correctly proved that the official app sends post-active maintenance traffic
that our helper does not send, but its primary `outer=42 / inner=18` bucket was
computed per PseudoTCP datagram. That bucket mixed multiple ViP messages that
happened to occupy one 18-byte PseudoTCP data segment.

R15 reconstructs the ordered PseudoTCP application byte stream first, using the
PseudoTCP sequence number and data length, and only then parses ViP frames.
For this capture both directions are continuous across all data-bearing segments:

```text
C2D_PSEUDOTCP_DATA_SEGMENTS=56
C2D_PSEUDOTCP_APP_BYTES=2820
C2D_SEQUENCE_CONTINUITY=PASS
D2C_PSEUDOTCP_DATA_SEGMENTS=69
D2C_PSEUDOTCP_APP_BYTES=6485
D2C_SEQUENCE_CONTINUITY=PASS
C2D_VIP_FRAMES_REASSEMBLED=71
D2C_VIP_FRAMES_REASSEMBLED=74
VIP_STREAM_PARSE_TO_END=PASS
```

This changes the semantic interpretation of R14's 18 datagrams with
`outer=42 / data=18`: 13 are the actual ECHO maintenance requests described
below, while the remaining five are other 10-byte-body ViP frames, including
channel-close traffic. Therefore the earlier scalar
`18 repeats / median 5.010 s` must not be used as the ECHO cadence contract.

The high-level R14 conclusion remains valid: official-app post-active maintenance
traffic is present and missing from the helper. R15 resolves the two relevant
maintenance families more precisely.

## Official client channel setup

Reassembled ViP control traffic proves that the official client opens additional
session-scoped channels before/during media. Dynamic numeric channel identifiers
are deliberately not recorded here.

Relevant channels:

```text
CLIENT_OPEN_ECHO=true
ECHO_TRANSPORT=0
CLIENT_OPEN_UDPM=true
UDPM_TRANSPORT=1
RTPC_TRANSPORT=1
```

The client-opened ECHO is distinct from the device-opened ECHO observed earlier
in the bootstrap flow. The official client also opens UDPM before the first media
RTP. Current P78/P80 helper setup contains RTPC setup but does not open the
client-side maintenance ECHO or UDPM channel.

## Family A — ECHO session maintenance

### Identification

`PROVEN_OFFLINE`, corroborated by the existing static ECHO parser:

- the family uses the dynamically opened client ECHO channel;
- client request body is the exact 10-byte ASCII protocol literal
  `keep-alive`;
- device response body is the exact 10-byte ASCII protocol literal
  `KEEP-ALIVE`;
- request and response use the same session-scoped ECHO request/channel id;
- the existing base source already recognises these two exact ECHO forms as
  `KEEPALIVE_REQUEST` and `KEEPALIVE_RESPONSE`.

No credential, endpoint, session identifier, or captured numeric channel id is
required to describe this contract.

### Timing

```text
FAMILY_A_CLASS=ECHO_KEEPALIVE
FAMILY_A_REQUEST_COUNT=13
FAMILY_A_FIRST_AT=10.505
FAMILY_A_LAST_AT=78.517
FAMILY_A_CONTINUES_AFTER_36S=true
FAMILY_A_CADENCE_MEDIAN=5.991
FAMILY_A_CADENCE_MIN=5.003
FAMILY_A_CADENCE_MAX=6.010
FAMILY_A_RESPONSE_COUNT=13
FAMILY_A_RESPONSE_LATENCY_MEDIAN=0.092
FAMILY_A_RESPONSE_LATENCY_MIN=0.083
FAMILY_A_RESPONSE_LATENCY_MAX=0.223
```

The observed request schedule is not a clean 5.010-second timer. It contains
roughly five- and six-second intervals. Therefore R15 does **not** promote one
capture-derived ECHO interval to a universal production timer constant.

### Generation / response contract

```text
FAMILY_A_CHANNEL_SOURCE=session-scoped dynamically opened ECHO channel
FAMILY_A_REQUEST_BODY=protocol literal "keep-alive"
FAMILY_A_RESPONSE_BODY=protocol literal "KEEP-ALIVE"
FAMILY_A_NEXT_REQUEST_DEPENDS_ON_RESPONSE_DATA=false
FAMILY_A_RESPONSE_REQUIRED_FOR_NEXT_CYCLE=NOT_PROVEN
FAMILY_A_TIMER_SOURCE=NOT_PROVEN
HELPER_FAMILY_A_EQUIVALENT=false
```

The request body is constant and the next request does not derive any field from
the previous response. Whether the official implementation suppresses a later
request after a missing response is not established by this capture.

The current helper has device-originated ECHO reflection support, but it does not
create this client maintenance ECHO lane and does not proactively send
`keep-alive` after media activation.

## Family B — UDPM media control

### Identification

`PROVEN_OFFLINE` at the channel/framing level:

- the official client opens a dynamic `UDPM` channel through an ABCD OPEN;
- its OPEN transport value is `1`;
- the repeated media-control datagrams then use the dynamic UDPM channel id;
- these datagrams are direct ViP frames on the media UDP lane rather than
  PseudoTCP application data;
- each datagram has outer UDP payload length 14 bytes = ViP header 8 + body 6;
- device replies use the same dynamic UDPM channel id and the same body length.

R14's label `CUSTOM_MEDIA_CONTROL` can therefore be refined to
`UDPM_MEDIA_CONTROL`.

### Startup and steady-state timing

There are 14 client UDPM requests and 13 device responses. The first two requests
are startup variants. From the third request onward the request body has a stable
shape and one rolling 8-bit field.

```text
FAMILY_B_CLASS=UDPM_MEDIA_CONTROL
FAMILY_B_REQUEST_COUNT=14
FAMILY_B_RESPONSE_COUNT=13
FAMILY_B_FIRST_AT=10.926
FAMILY_B_LAST_AT=66.699
FAMILY_B_CONTINUES_AFTER_36S=true
FAMILY_B_STEADY_REQUEST_COUNT=12
FAMILY_B_STEADY_FIRST_AT=11.535
FAMILY_B_STEADY_LAST_AT=66.699
FAMILY_B_STEADY_CADENCE_MEDIAN=5.017
FAMILY_B_STEADY_CADENCE_MIN=5.005
FAMILY_B_STEADY_CADENCE_MAX=5.024
FAMILY_B_RESPONSE_LATENCY_MEDIAN=0.090
FAMILY_B_RESPONSE_LATENCY_MIN=0.071
FAMILY_B_RESPONSE_LATENCY_MAX=0.127
```

The first UDPM request has no paired device response in this capture. Every later
request has a response that can be paired by the rolling field.

### Structural six-byte body map

Raw/capture-specific byte values are intentionally not emitted. Across the
steady request series the six-byte body has the following structural relations:

```text
FIELD_0_1 width=2 class=CONSTANT relation=request_constant_and_echoed_by_response
FIELD_2   width=1 class=MESSAGE_TYPE relation=request_discriminator_response_uses_distinct_constant
FIELD_3   width=1 class=MONOTONIC_COUNTER relation=request_plus_one_mod256_response_echoes_request_value
FIELD_4_5 width=2 class=CONSTANT relation=steady_request_and_response_constant
```

Startup request #1 and #2 use transitional values before the steady shape is
reached. R15 does not promote those capture-specific values, the steady constants,
or the initial counter value into a production generation contract.

### Generation / response contract

```text
FAMILY_B_CHANNEL_SOURCE=session-scoped dynamically opened UDPM channel
FAMILY_B_CHANNEL_OPEN=ABCD OPEN name=UDPM transport=1
FAMILY_B_BODY_LENGTH=6
FAMILY_B_COUNTER_RULE=increment_by_one_mod256_after_startup
FAMILY_B_RESPONSE_MATCH=dynamic_UDPM_channel_plus_echoed_counter
FAMILY_B_NEXT_REQUEST_DEPENDS_ON_RESPONSE_DATA=false
FAMILY_B_RESPONSE_REQUIRED_FOR_NEXT_CYCLE=NOT_PROVEN
FAMILY_B_STARTUP_CONSTANTS=NOT_PROVEN_STATIC
FAMILY_B_STEADY_CONSTANTS=NOT_PROVEN_STATIC
FAMILY_B_COUNTER_INITIALIZATION=NOT_PROVEN_STATIC
FAMILY_B_TIMER_SOURCE=NOT_PROVEN_STATIC
HELPER_FAMILY_B_EQUIVALENT=false
```

The current promoted helper has no UDPM channel OPEN, no direct ViP/UDPM
six-byte media-maintenance generator, and no response state for this family.

## Family A vs Family B

The two families are not one request/response chain:

- they use different dynamically opened channels;
- ECHO is ViP application traffic carried inside PseudoTCP;
- UDPM maintenance is direct ViP traffic on the media UDP lane;
- each family receives its own device responses;
- their relative phase drifts and changes ordering through the capture.

```text
A_B_TIMER_RELATION=INDEPENDENT_MAINTENANCE_SCHEDULES
A_B_ORDER_STABLE=false
REQUEST_RESPONSE_CHAIN=false
COMMON_PARENT_EVENT=MEDIA_SESSION_PLAUSIBLE_NOT_PROVEN
```

Timing alone is not used as a causal proof.

## PseudoTCP transport maintenance is a third, separate layer

Transport-only 24-byte PseudoTCP packets also occur during the session with an
approximately one-second central cadence, plus bursts and teardown packets.
This is transport machinery, not Family A or Family B.

The helper already drives the libnice/PseudoTCP clock and transport path, so R15
finds no basis for adding a second transport-level keepalive implementation.

```text
PSEUDOTCP_TRANSPORT_PERIODICITY=OBSERVED_APPROX_1S_WITH_BURSTS
HELPER_PSEUDOTCP_TRANSPORT_EQUIVALENT=true
MODIFY_PSEUDOTCP_TRANSPORT=false
```

## Media-lifetime correlation

Official video RTP ends at 71.689 seconds and audio at 71.579 seconds. Family B
last sends at 66.699 and receives its response at 66.790.

```text
LAST_UDPM_REQUEST_TO_LAST_VIDEO=4.990s
UDPM_STEADY_CADENCE_MEDIAN=5.017s
NEXT_UDPM_EXPECTED_BY_OBSERVED_CADENCE≈71.716s
LAST_VIDEO_TO_NEXT_EXPECTED_UDPM≈-0.027s
```

Thus media stops almost exactly one observed UDPM maintenance interval after the
last UDPM request. No later UDPM request is observed.

Family A behaves differently: ECHO keepalive continues after RTP has stopped,
including requests at approximately 72.507 and 78.517 seconds, and receives
responses. PseudoTCP session teardown occurs later.

This sharply separates likely roles:

```text
ECHO_ROLE=session/PseudoTCP application maintenance — PROVEN_OFFLINE family, media-lifetime role NOT_PROVEN
UDPM_ROLE=media-control maintenance — PROVEN_OFFLINE family, direct media-lifetime role STRONGLY_PLAUSIBLE
```

The timing evidence makes missing UDPM maintenance the stronger D1 candidate.
It is still not causal proof: only an intervention using a correctly generated
UDPM contract could prove that adding it extends our helper's ~36-second media
lifetime.

```text
MISSING_PERIODIC_CONTROL_DIFFERENCE=PROVEN
MISSING_PERIODIC_CONTROL_CAN_EXPLAIN_36S_STOP=PLAUSIBLE
COMMON_D1_D2_CAUSE=UNRESOLVED
```

## Relation to the official ~60-second media stop

The device stops RTP while the ECHO session keepalive remains healthy. The last
UDPM maintenance exchange precedes RTP stop by roughly one UDPM interval.
Therefore the previous broad `SERVER_PROTOCOL_LIMIT` label should be interpreted
more narrowly: the device is the observed RTP-stop initiator in this capture,
but R15 cannot prove whether the ~60-second result is an absolute server policy,
a UDPM/media-state timeout, or another device-side media rule.

```text
OFFICIAL_60S_LIMIT_RELEVANCE_TO_ECHO=UNRELATED_AS_DIRECT_GATE
OFFICIAL_60S_LIMIT_RELEVANCE_TO_UDPM=PLAUSIBLE
OFFICIAL_60S_LIMIT_CLASSIFICATION=DEVICE_MEDIA_STOP_OBSERVED_EXACT_POLICY_UNRESOLVED
```

## Required maintenance set

The official app uses both ECHO and UDPM. However, the capture does not prove
that both are necessary for extending media itself. ECHO demonstrably continues
after media has already stopped, while UDPM aligns tightly with media lifetime.

Therefore R15 intentionally does not choose `FAMILY_A_ONLY`, `FAMILY_B_ONLY`, or
`FAMILY_A_AND_B` as a proven minimal production set.

```text
REQUIRED_MAINTENANCE_SET=UNRESOLVED
PRIMARY_D1_CANDIDATE=FAMILY_B_UDPM
SECONDARY_SESSION_MAINTENANCE=FAMILY_A_ECHO
```

## Corrective implementation readiness

A safe corrective patch is **not implementation-ready yet**.

Family A is sufficiently identified at the message semantic level, but the
client-open timer provenance is not established. Family B is more important to
D1 and its channel/frame structure is proven, yet the following generation
facts are still missing independent static provenance:

- six-byte startup constants and transition into steady state;
- steady request constants;
- rolling counter initialization/source;
- timer source and exact scheduling rule;
- intended reaction to a missing/malformed response.

Promoting the values from this single PCAP would violate the project's rule that
capture-specific scalars are not generation contracts.

```text
CORRECTIVE_PATCH_SPEC_READY=false
IMPLEMENT_FAMILY_A=false
IMPLEMENT_FAMILY_B=false
MODIFY_PSEUDOTCP_TRANSPORT=false
NO_LITERAL_REPLAY=true
```

## Next offline gate

The next step should remain offline/static. Search the already-staged official
Android DEX/native artifacts for the `UDPM` channel implementation and the ECHO
`keep-alive` scheduler. The goal is to prove, without another live session:

```text
UDPM_OPEN_CALLER=
UDPM_BODY_BUILDER=
UDPM_STARTUP_STATE_MACHINE=
UDPM_COUNTER_INITIALIZATION=
UDPM_COUNTER_INCREMENT=
UDPM_TIMER_SOURCE=
UDPM_RESPONSE_HANDLER=
UDPM_STOP_CONDITION=
ECHO_CLIENT_OPEN_CALLER=
ECHO_KEEPALIVE_TIMER_SOURCE=
ECHO_RESPONSE_POLICY=
```

Only after those facts are established should a corrective generator be written
and frozen to a new immutable native SHA. A fourth helper live attempt is not
justified by R15 alone.

## RED test specification for the future implementation

The corrective implementation round should start with RED tests covering at
least:

1. no ECHO/UDPM maintenance before media/session prerequisites;
2. session-scoped dynamic ECHO and UDPM channel allocation, no captured ids;
3. ECHO request/response semantic forms;
4. UDPM OPEN uses the proven channel transport contract;
5. UDPM startup transition generated from proven static rules;
6. UDPM rolling counter generated from proven session state;
7. UDPM response matched to the current channel/counter;
8. recurring sends stop on media teardown;
9. no maintenance timer survives helper exit;
10. existing PseudoTCP transport clock is not duplicated;
11. no captured literal packet/body is used as a runtime fixture;
12. malformed/unexpected maintenance response fails according to the future
    proven response policy rather than an invented behavior.

## R15 report

```text
=== COMELIT P116 R15 MEDIA MAINTENANCE CONTRACT REPORT ===
BASE_SHA=3fec73f77c6f7b19e7177e2793d579b43bc02104

FAMILY_A_CLASS=ECHO_KEEPALIVE
FAMILY_A_CADENCE=OBSERVED median=5.991s range=5.003..6.010s
FAMILY_A_RESPONSE_CLASS=ECHO_KEEPALIVE_RESPONSE

FAMILY_B_CLASS=UDPM_MEDIA_CONTROL
FAMILY_B_CADENCE=OBSERVED steady median=5.017s range=5.005..5.024s
FAMILY_B_RESPONSE_CLASS=UDPM_MEDIA_CONTROL_RESPONSE

A_B_TIMER_RELATION=INDEPENDENT_MAINTENANCE_SCHEDULES
A_B_ORDER_STABLE=false

PSEUDOTCP_TRANSPORT_PERIODICITY=OBSERVED_APPROX_1S_WITH_BURSTS
HELPER_PSEUDOTCP_TRANSPORT_EQUIVALENT=true

HELPER_FAMILY_A_EQUIVALENT=false
HELPER_FAMILY_B_EQUIVALENT=false

FAMILY_A_GENERATION_CONTRACT=PARTIAL_TIMER_SOURCE_NOT_PROVEN
FAMILY_B_GENERATION_CONTRACT=PARTIAL_STATIC_BODY_AND_TIMER_PROVENANCE_REQUIRED

FAMILY_A_RESPONSE_REQUIRED=NOT_PROVEN
FAMILY_B_RESPONSE_REQUIRED=NOT_PROVEN

NEXT_REQUEST_DEPENDS_ON_RESPONSE_A=false_for_payload_state
NEXT_REQUEST_DEPENDS_ON_RESPONSE_B=false_for_counter_payload_state

REQUIRED_MAINTENANCE_SET=UNRESOLVED

MISSING_PERIODIC_CONTROL_DIFFERENCE=PROVEN
MISSING_PERIODIC_CONTROL_CAN_EXPLAIN_36S_STOP=PLAUSIBLE

OFFICIAL_60S_LIMIT_RELEVANCE_TO_KEEPALIVE=UDPM_PLAUSIBLE_ECHO_NOT_DIRECT_GATE

CORRECTIVE_PATCH_SPEC_READY=false
CORRECTIVE_LOCATION=generated helper media lifecycle after RTPC setup / before teardown
AFFECTED_GENERATOR=P80/P78 successor
AFFECTED_STATE_MACHINE=media maintenance state must be added only after static provenance

IMPLEMENT_FAMILY_A=false
IMPLEMENT_FAMILY_B=false
MODIFY_PSEUDOTCP_TRANSPORT=false

RED_TEST_SPEC_READY=true
FUNCTIONAL_FIX_IMPLEMENTED=false
LIVE_RUN_EXECUTED=false
PROD_FILES_CHANGED=0
RAW_PCAP_IN_COMMIT=0
HA_DEPLOY=NOT_RUN
HA_RESTART=NOT_RUN
COMELIT_LIVE=NOT_RUN
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
=== END COMELIT P116 R15 MEDIA MAINTENANCE CONTRACT REPORT ===
```
