# P116 R63 — Gate peer/TAP actuation profile promotion

Date: 2026-09-23. Scope: offline implementation only. No Gate/Door action, no
Home Assistant deploy/restart, and no production mutation were performed by
this round.

## Evidence closure

The owner-provided PCAPdroid capture is kept outside Git.

Safe capture identity:

- `PCAP_SHA256=5645b4b0607f746b057ce6b6603f8d6165f20167894927aca5a7c8b4b744e636`
- bytes: `751370`
- packets: `1510`
- duration: approximately `42.632s`

The capture independently proves that Gate selection/connection attempts use
ViP peer address `00000610`. Multiple signalling bursts pair the local full
apartment identity with `00000610`; a later Entrance attempt uses the same
structural peer field with `00000643`. Therefore R61's former
`GATE_TARGET_SOURCE_IDENTITY_CAPTURE=PARTIAL` is superseded by:

```
GATE_TARGET_SOURCE_IDENTITY_CAPTURE=PROVEN
GATE_PEER_TARGET=00000610
```

The captured configuration independently supplies:

```
opendoor-actions.action=peer
opendoor-actions.output-index=1
opendoor-address-book.count=0
actuator-address-book.count=0
```

The failed Gate connection attempts do not contain an actuation body. Known
Door body signatures `5c8b2c74` and `70ab299f` are absent from the capture.
R63 therefore does not claim capture-derived actuation bytes.

## Parameterised peer/TAP algorithm provenance

Primary external implementation evidence:
`nicolas-fricke/ha-component-comelit-intercom` PR #12, head
`def491986cae94d03ff99265ef7c148d36db76a5`.

For `opendoor-actions.action=peer`, that implementation constructs a
target-parameterised five-packet TAP sequence:

1. `0x1800`
2. `0x1820`
3. `0x18C0` carrying `00 2d + peer-address padded to 10 bytes + output-index`
4. `0x1800`
5. `0x1820`

Its destination selector is `vip_base + output_index`; the selected peer
address is used as the source/door address. It was reported physically tested
on a 1456S peer configuration.

The pinned legacy `IconaBridgeClient.open_door(vip, door_item)` model in the
project's retained forensic evidence is independently parameterised by
`door_item["apt-address"]` and `door_item["output-index"]` and uses the same
OPEN/CONFIRM/INIT/OPEN/CONFIRM semantic sequence.

The current production Entrance native bodies are already the persistent-CTPP
form of this peer/TAP model:

- five bodies with lengths `32,32,48,32,32`;
- opcodes `0x1800,0x1820,0x18C0,0x1800,0x1820`;
- destination `000401171` = apartment base + output-index 1;
- Entrance peer field `00000643`;
- body 3 carries peer address plus output-index 1.

Entrance has a current owner-observed physical-open result from Home Assistant.
R63 does **not** copy an Entrance-only profile by assertion. It instantiates
the independently parameterised peer/TAP model with Gate evidence:

```
door_identity=gate
peer_target=00000610
action=peer
output_index=1
destination_selector=000401171
write_count=5
persistent_ctpp_reused=true
automatic_retry_allowed=false
physical_effect_asserted=false
```

The native transform derives each Gate body mechanically from the existing
Entrance peer/TAP body and permits only the peer-address substitution
`00000643 -> 00000610`. It asserts that all Entrance bodies remain
byte-identical and that body lengths/output-index destination remain unchanged.

## Runtime target binding

Python writes exactly `entrance` or `gate` to root-only
`/run/comelit-p2p/door-target` immediately before the existing SIGUSR1
one-shot boundary. The native helper consumes and unlinks that file before any
Door write.

Missing or malformed target data produces `FAILED_SAFE` without an actuation
write. Runtime operations remain serialized by the existing Door lock.

No second CTPP channel, automatic retry, fallback target, or physical-effect
assertion is introduced.

## Acceptance state before live validation

```
GATE_TARGET_SOURCE_IDENTITY_CAPTURE=PROVEN
GATE_PEER_TARGET=00000610
GATE_ACTION=peer
GATE_OUTPUT_INDEX=1
GATE_PROFILE_MODEL=PEER_TAP_PARAMETRIC
GATE_WRITE_COUNT=5
GATE_ACTUATION_PROFILE_VALIDATED=true
GATE_STANDARD_PRESS_ALLOWED=true
AUTOMATIC_RETRY_ALLOWED=false
PHYSICAL_EFFECT_ASSERTED=false
LIVE_GATE_ACTIONS=0
PRODUCTION_MUTATIONS=0
RAW_PCAP_COMMITTED=false
```

After normal HACS/HAOS deployment, physical Gate effect remains to be validated
by one owner-authorised one-shot button press. A complete unconfirmed
transmission uses the same conservative outcome semantics as Entrance: it does
not assert that the physical Gate opened and it is never retried automatically.
