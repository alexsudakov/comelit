# P116 / R44 — offline inbound-call simulation strategy

Status: **research/test infrastructure only**

This round exists to remove repeated physical doorbell rings from the normal
development loop.

No production runtime code is changed by this round.

~~~text
PHYSICAL_CALL_ATTEMPTS=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
HA_DEPLOY_PERFORMED=false
HA_RESTART_PERFORMED=false
~~~

## 1. Problem

The current R42-b workstream has already needed several physical inbound calls
just to learn where the protocol state machine stops. That is too expensive and
too slow for normal parser/state-machine development.

The target is therefore:

~~~text
physical call = final hardware validation
not = ordinary development/debug mechanism
~~~

## 2. Test pyramid

### Layer A — pure wire/state model

Existing R30A/R30B models remain the canonical offline model for:

- CTP envelope parsing/building;
- inbound call connection-direction transform;
- call sequence/ack ownership;
- media OPEN/STOP transaction rules.

R44 adds a deterministic fake inbound peer:

entrance_p116_r44_inbound_peer_simulator.py

It can:

~~~text
emit synthetic INVITE
observe local transport ACK
observe local CAPABILITIES
observe local ALERTING/setup
withhold peer CAPABILITIES until the required order is complete
emit peer CAPABILITIES with video-request bit set
return only a semantic/safe transcript
~~~

It opens no socket and performs no network I/O.

### Layer B — compiled host harness

The project already extracts the dependency-free R35/R36/R37 C regions and
compiles them with a fake writer using host cc.

This should remain the primary test of **actual C logic**:

~~~text
synthetic INVITE
-> exact extracted production core
-> fake transport writer
-> synthetic peer CAPABILITIES
-> R36 trigger
-> OPEN state machine
-> STOP / RELEASE
~~~

R44 does not duplicate that C machinery. The Python fake peer is the peer/oracle
that the compiled harness can consume once the call-adoption serializers are
added.

### Layer C — generated-source integration harness

After the byte-exact native call-adoption serializers are recovered, add one
new extracted C region for:

~~~text
ACK
CAPABILITIES
ALERTING
~~~

and compile:

~~~text
R35 core
+ call-adoption core
+ R36 trigger
+ R37 stop core
+ host fake writer
+ R44 peer transcript
~~~

Required scenarios:

1. valid INVITE -> exactly one ACK;
2. exactly one local CAPABILITIES;
3. exactly one local ALERTING;
4. peer CAPABILITIES appears only after 1-3;
5. peer video bit clear -> OPEN=0;
6. peer video bit set -> exactly one OPEN;
7. duplicate peer CAPABILITIES -> OPEN remains one;
8. malformed connection/sequence -> fail closed;
9. RELEASE before OPEN -> no OPEN;
10. RELEASE after OPEN -> exactly one STOP;
11. second call generation cannot reuse first-call state;
12. no retry/timer/network/Door/Gate side effects.

This is the main replacement for repeated physical rings.

### Layer D — process-level offline parser replay

Add a **test-only** executable adapter, never packaged in Home Assistant, that
drives the generated helper's parser with a finite sequence of synthetic
already-framed CTPP payloads.

It must not contain:

- cloud/P2P bootstrap;
- libnice network setup;
- sockets to Comelit;
- Door/Gate code paths;
- production signal handlers.

It should expose only:

~~~text
stdin/file semantic fixture
-> parser/state-machine
-> intercepted TX frames
-> bounded marker stream
~~~

This catches integration errors that a pure extracted-core harness cannot:
wrong insertion point, CALL_INIT drain regressions, parser consumption mistakes,
marker lifetime/reset bugs, and sequence-state wiring errors.

### Layer E — private transcript replay

If a physical official-app capture is ever needed again, use it once to create
a **private hash-gated semantic transcript** on CT120.

Do not commit raw PCAP/session material.

The public repository may contain only:

- fixture schema;
- SHA256 gate;
- redacted semantic events;
- expected scalar outcomes.

A local CT120 replay test can then reuse the same evidence indefinitely without
another call.

### Layer F — one final physical canary

A physical inbound call becomes necessary only when offline layers A-E are all
green and the remaining question is genuinely hardware behavior, e.g.:

~~~text
does the entrance panel accept our exact native-equivalent signaling?
does RTP actually arrive?
does real teardown release the server-side media resource?
~~~

One protocol milestone -> one bounded physical canary.

No physical call should be used to debug syntax, parser order, sequence
accounting, duplicate writes, state resets, or observability.

## 3. STRICT_NATIVE vs LAB_CORROBORATION

R44 intentionally separates two test modes.

### STRICT_NATIVE

Only primary-native-proven bytes may be used.

At the time R44 is introduced the strict profile is deliberately incomplete:

~~~text
FIRST_ACK_FLAGS=UNKNOWN
CSP_SEND_CAPAB_REPORT_EXACT_BODY=UNKNOWN
CSP_SEND_ALERTING_EXACT_BODY=UNKNOWN
~~~

Therefore STRICT_NATIVE fails closed.

That prevents accidental production promotion of guessed/public example bytes.

### LAB_CORROBORATION

Uses the independent pinned public implementation only as an offline peer.

Current lab fixtures:

~~~text
local capabilities: 00 03 49 00 27 00 00 00
local setup/alerting: 00 0c 00 00 00 00 00 00
peer capabilities:   00 03 50 03 3b 00 00 00
~~~

These values are useful for exercising parser/order/state-machine behavior but:

~~~text
LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false
~~~

## 4. Immediate consequence for R43

R43 showed that current production captures CALL_INIT and then waits for peer
CAPABILITIES without performing native call-adoption signaling.

The testing strategy means the next serializer corrective should be developed
as follows:

~~~text
static native extraction
-> STRICT_NATIVE profile becomes complete
-> Python simulator tests
-> compiled C call-adoption host harness
-> generated-source parser replay
-> full offline suite / CI
-> deploy review
-> one physical call only
~~~

There is no reason to perform another physical ring before that sequence is
green.

## 5. Acceptance target

Before any next physical inbound-call canary:

~~~text
STRICT_NATIVE_PROFILE_READY=true
CALL_ADOPTION_HOST_HARNESS=PASS
FULL_OFFLINE_TRANSCRIPT=PASS
GENERATED_SOURCE_REPLAY=PASS
DUPLICATE_WRITE_GATES=PASS
GENERATION_RESET=PASS
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
~~~

Only then should hardware behavior be tested once.

## Result

~~~text
=== P116 R44 OFFLINE TEST STRATEGY ===

PHYSICAL_CALL_AS_PRIMARY_DEBUG_TOOL=false
PURE_MODEL_AVAILABLE=true
FAKE_INBOUND_PEER_AVAILABLE=true
COMPILED_CORE_HARNESS_ALREADY_AVAILABLE=true
PROCESS_LEVEL_REPLAY_REQUIRED=true
PRIVATE_CAPTURE_REPLAY_SUPPORTED_BY_DESIGN=true

STRICT_NATIVE_PROFILE_READY=false
LAB_CORROBORATION_AVAILABLE=true
LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false

NEXT_PHYSICAL_CALL_REQUIRED_NOW=false
NEXT_REQUIRED_STEP=RECOVER_EXACT_NATIVE_CALL_ADOPTION_SERIALIZERS_THEN_WIRE_OFFLINE_HARNESS

=== END P116 R44 OFFLINE TEST STRATEGY ===
~~~
