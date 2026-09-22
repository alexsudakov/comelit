# P116 R61 Gate actuation profile forensic

Дата: 2026-09-22. Режим: `DEV_RESEARCH_OFFLINE`. Живые действия не выполнялись: `LIVE_ACTIONS=0`, `PRODUCTION_MUTATIONS=0`, `NETWORK_ACTION_PERFORMED=false`, `ACTUATOR_COMMAND_ATTEMPTED=false`, `PHYSICAL_DOOR_ACTION=false`.

## Verdict

`PROVEN_STATIC` `GATE_ACTUATION_PROFILE_VALIDATED=false`, derived from `resolve_door_capability(DOOR_GATE, media_paused=False)` in shipped `custom_components/comelit/const.py`.

`PROVEN_STATIC` `GATE_STANDARD_PRESS_ALLOWED=false`, derived from the same shipped capability: `press_allowed = available and actuation_profile_validated`, with `GATE_BLOCKED_REASON=gate_actuation_profile_not_validated` and `GATE_RING_SOURCE=00000610`.

Причина не в UI и не в отсутствии Gate entity. Причина в отсутствующем полном наборе R60-lineage Gate artifacts: нет доказанного Gate-профиля, который связывает `target/source identity`, последовательность команд, CTPP-channel allocation, `output/address selector`, ACK-семантику, one-shot/no-retry границу и write-count bound именно для `door_identity=gate`.

`UNRESOLVED` Минимальный следующий шаг: `PASSIVE_CAPTURE` для агрегата `GATE_ACTUATION_PROFILE_CAPTURE`. Нужен owner-initiated Gate action в official app, где наша сторона только записывает пассивный capture. Наш код не отправляет Comelit frame и не выполняет actuation. Offline closure потребует pinned evidence identity для нового файла: `sha256(.r61-input/pcap/<owner_gate_official_app_passive_capture>.pcap)=TBD_BY_OWNER_RELAY`.

## Door profile lineage

`PROVEN_STATIC` HA path: `ComelitEntranceDoorButton.async_press()` вызывает `runtime.async_open_door(DOOR_ENTRANCE)` и требует `protocol_acked is True`; anchors: `custom_components/comelit/button.py:117-133`.

`PROVEN_STATIC` Runtime принимает только entrance: `if door != "entrance": raise ComelitRingRuntimeError("unsupported_door")`; anchor: `custom_components/comelit/runtime.py:876-884`.

`PROVEN_STATIC` One-shot boundary: runtime генерирует HA-local `operation_id` и выполняет ровно один `SIGUSR1`; anchors: `custom_components/comelit/runtime.py:917-929`.

`PROVEN_STATIC` Runtime нормализует Door result: `write_count` допускается только `0..5`, raw `ACKED` недостаточен без `door_specific_ack_proven`, retry запрещен, physical effect не утверждается; anchors: `custom_components/comelit/runtime.py:953-995`, `custom_components/comelit/runtime.py:860-873`.

`PROVEN_STATIC` Native frozen contract: persistent CTPP reused, no second CTPP open, no close, five bodies in source order, inbound CTPP does not advance writes, no generic ACK promotion, automatic retry forbidden; anchor: `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:227-237`.

`PROVEN_STATIC` Native Door target marker hardcoded: `V4_DOOR_TARGET=entrance`; anchor: `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2583`.

`PROVEN_STATIC` Native write count: `DOOR_PROFILE_WRITE_COUNT_NATIVE=5`; anchor: `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:271-272`.

`PROVEN_OFFLINE` Legacy oracle write count is derived as 6 from two runtime-parsed sources: `DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN=6` from `DoorSemanticPlan.steps`/`STEP_KINDS`, and `DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH=6` from the `capture_real_packets` packet-count oracle. `DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT=false`, so `DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE=6`. Anchors: `safety-poc/scripts/prepare_p13_real_payloads.py:134-176`, `safety-poc/src/comelit_safety_poc/door_semantics.py:33-66`. Классификация: `DOOR_PROFILE_WRITE_COUNT_DIVERGENCE=NATIVE_5_VS_LEGACY_ORACLE_6`, не reconciled.

### Door body map

`PROVEN_OFFLINE` Analyzer re-derived bodies from native source: `NATIVE_FILE_SHA256=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73`, `DOOR_NATIVE_BODY_LENGTHS=32,32,48,32,32`, `DOOR_BODY_OPCODE_SEQUENCE=0x00,0x20,0xc0,0x00,0x20`.

| Body | Length | First/opcode byte | Offset role map |
|---|---:|---:|---|
| 1 | 32 | `0x00` | `0..0` selector/opcode `PROVEN_STATIC`; `2..5=5c8b2c74` shared signature `OBSERVED`; `12..21=000401171\0` relation to `V4_APT_ADDRESS/V4_FULL_ADDRESS` is `UNRESOLVED`; `22..31=00000643\0\0` entrance panel address `PROVEN_STATIC`. |
| 2 | 32 | `0x20` | Same as body 1 except selector/opcode `0x20`; entrance panel at `22..31` `PROVEN_STATIC`. |
| 3 | 48 | `0xc0` | `2..5=70ab299f` distinct signature `OBSERVED`; `12..21` contains entrance-address bytes plus non-address suffix; `22..31` is not an ASCII address; `28..37=000401171\0` relation to apartment/full address is `UNRESOLVED`; `38..47=00000643\0\0` entrance panel address `PROVEN_STATIC`. |
| 4 | 32 | `0x00` | Byte-identical to body 1: same hash `015ec16e...`; entrance panel at `22..31` `PROVEN_STATIC`. |
| 5 | 32 | `0x20` | Byte-identical to body 2: same hash `55ac144a...`; entrance panel at `22..31` `PROVEN_STATIC`. |

`OBSERVED` Prompt-specified `offsets 22..31 all five bodies` does not match body 3. Body 3 has `DOOR_BODY_3_OFFSET_22_31=0000ffffffff30303034`; its entrance panel marker is at `38..47`. This record preserves the byte-derived divergence.

`UNRESOLVED` The 9-character value `000401171` at bodies 1/2/4/5 `12..20` and body 3 `28..36` resembles neither exact `V4_APT_ADDRESS=00040117` nor exact `V4_FULL_ADDRESS=000401177`; no committed source proves the transformation, so the field role is not promoted.

## Gate-side evidence

`PROVEN_STATIC` Gate entity exists: `ComelitGateDoorButton` is added with entrance button, has `MAIN_GATE_ENTITY_ID=button.comelit_main_gate_open_door`; anchors: `custom_components/comelit/button.py:39-43`, `custom_components/comelit/button.py:136-151`, `custom_components/comelit/const.py:152-153`.

`PROVEN_STATIC` Gate is available but fail-closed when media is not paused: topology has `configured=true`, `ring_source_validated=true`, `actuation_profile_validated=false`, `ring_source=00000610`; `press_allowed = available and actuation_profile_validated`; anchors: `custom_components/comelit/const.py:89-127`, `custom_components/comelit/button.py:153-178`.

`PROVEN_STATIC` Gate press does not call runtime: `async_press()` always raises until one-shot profile is independently validated; anchors: `custom_components/comelit/button.py:180-186`.

`PROVEN_STATIC` `GATE_SOURCE="00000610"` maps to `gate` in ring parsing; anchors: `custom_components/comelit/ring_event.py:9-18`, `custom_components/comelit/ring_event.py:70-85`.

`PROVEN_STATIC` Source of `00000610`: frozen V4 research says `gate panel = 00000610`, `V4_GATE "00000610"`, and explicitly states the candidate contains no call answer/media activation/actuator action; anchors: `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:154-180`, `safety-poc/research/ring/v4_2/comelit_ice_offer_holder.v4_2.c:150-170`. Classification: ring identity evidence only. Ring identity does not imply actuation capability.

`PROVEN_STATIC` Native Door ACK marker is an unconditional constant `false`: after all five writes it prints `V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false`; on queue failure it also prints the same marker; anchors: `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1947-1949`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2525`. Consequence: entrance itself has no Door-specific ACK proof. Therefore no Gate validation criterion may require an ACK the entrance profile does not have; any valid Gate criterion must also be satisfiable by the entrance profile.

## Gate profile lineage

`PROVEN_OFFLINE` `GATE_PROFILE_MISSING_EVIDENCE=GATE_TARGET_SOURCE_IDENTITY_CAPTURE,GATE_COMMAND_SEQUENCE_CAPTURE,GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE,GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE,GATE_ACK_SEMANTICS_CAPTURE,GATE_SAFETY_IDEMPOTENCY_CAPTURE,GATE_NO_RETRY_CONTRACT_EVIDENCE`.

| R60 canonical artifact | Status | Anchor |
|---|---|---|
| `GATE_TARGET_SOURCE_IDENTITY_CAPTURE` | `PARTIAL` | `custom_components/comelit/const.py:_DOOR_TOPOLOGY_CAPABILITIES[DOOR_GATE].ring_source=00000610`; `custom_components/comelit/ring_event.py:GATE_SOURCE`. |
| `GATE_COMMAND_SEQUENCE_CAPTURE` | `ABSENT` | Not present in repository or staged evidence. |
| `GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE` | `ABSENT` | Not present in repository or staged evidence. |
| `GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE` | `ABSENT` | Not present in repository or staged evidence. |
| `GATE_ACK_SEMANTICS_CAPTURE` | `ABSENT` | Not present in repository or staged evidence. |
| `GATE_SAFETY_IDEMPOTENCY_CAPTURE` | `ABSENT` | Not present in repository or staged evidence. |
| `GATE_NO_RETRY_CONTRACT_EVIDENCE` | `ABSENT` | Not present in repository or staged evidence. |

## Search ledger

`PROVEN_OFFLINE` Repository text search:

| Scope searched | Files/matches | Conclusion |
|---|---:|---|
| repo `GATE` | 309 / 1914 | Gate labels and fail-closed code exist; no Gate actuation profile. |
| repo `gate` | 323 / 1427 | Lowercase Gate references include docs/tests; no promotable profile. |
| repo `00000610` | 24 / 44 | Ring identity appears; no command sequence. |
| repo `output-index` | 9 / 21 | Door target machinery only. |
| repo `opendoor-address-book` | 4 / 8 | Door target provenance machinery only. |
| repo `opendoor-actions` | 6 / 12 | Door target provenance machinery only. |
| repo `actuator` | 63 / 113 | Generic safety/actuator references; not Gate profile. |
| repo `actuator-address-book` | 2 / 5 | DEX-string evidence only. |

`PROVEN_OFFLINE` Git history pickaxe:

| Scope searched | Commits matched | Conclusion |
|---|---:|---|
| `git log --all -S "0x5c, 0x8b, 0x2c, 0x74"` | 6 | Door body signature history exists. |
| `git log --all -S V4_GATE` | 10 | Gate identity history exists. |
| `git log --all -S 00000610` | 20 | Gate ring identity history exists. |

`PROVEN_OFFLINE` Staged pcap byte scan:

| Capture | common `5c8b2c74` | body3 `70ab299f` | `00000643` | `000401177` | `00000610` |
|---|---:|---:|---:|---:|---:|
| `p2p_rtsp.pcap` | 0 | 0 | 1 | 8 | 1 |
| `p78-media.pcap` | 0 | 0 | 0 | 0 | 0 |
| `pcapdroid-r14-official-app-trace.pcap` | 0 | 0 | 34 | 42 | 1 |
| `r38-preflight.pcap` | 0 | 0 | 0 | 0 | 0 |
| `r39-phone-capture.pcap` | 0 | 0 | 0 | 0 | 0 |
| `self_activation.pcap` | 0 | 0 | 31 | 40 | 1 |

`OBSERVED` Door body byte signatures are absent from staged pcaps. ASCII identities occur, but ASCII identity hits are not actuation proof and are non-promotable.

`PROVEN_OFFLINE` Staged DEX string tables:

| Pattern | Files/matches | Exact strings relied on |
|---|---:|---|
| `opendoor-address-book` | 2 / 2 | `opendoor-address-book` |
| `opendoor-actions` | 2 / 2 | `opendoor-actions` |
| `output-index` | 2 / 2 | `output-index` |
| `actuator-address-book` | 2 / 2 | `actuator-address-book` |
| `actuator` | 3 / 243 | package/class names indicate actuator UI surface, not a profile |
| `door` | 3 / 553 | package/class names indicate door/open-door UI surface, not a profile |

## Machine values

```
GATE_ACTUATION_PROFILE_VALIDATED=false
GATE_STANDARD_PRESS_ALLOWED=false
GATE_BLOCKED_REASON=gate_actuation_profile_not_validated
GATE_RING_SOURCE=00000610
GATE_PROFILE_ARTIFACT_PRESENT=false
GATE_PROFILE_MISSING_EVIDENCE=GATE_TARGET_SOURCE_IDENTITY_CAPTURE,GATE_COMMAND_SEQUENCE_CAPTURE,GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE,GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE,GATE_ACK_SEMANTICS_CAPTURE,GATE_SAFETY_IDEMPOTENCY_CAPTURE,GATE_NO_RETRY_CONTRACT_EVIDENCE
GATE_TARGET_SOURCE_IDENTITY_CAPTURE_STATUS=PARTIAL
GATE_TARGET_SOURCE_IDENTITY_CAPTURE_ANCHOR=custom_components/comelit/const.py:_DOOR_TOPOLOGY_CAPABILITIES[DOOR_GATE].ring_source=00000610; custom_components/comelit/ring_event.py:GATE_SOURCE
GATE_COMMAND_SEQUENCE_CAPTURE_STATUS=ABSENT
GATE_COMMAND_SEQUENCE_CAPTURE_ANCHOR=not present in repository or staged evidence
GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE_STATUS=ABSENT
GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE_ANCHOR=not present in repository or staged evidence
GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE_STATUS=ABSENT
GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE_ANCHOR=not present in repository or staged evidence
GATE_ACK_SEMANTICS_CAPTURE_STATUS=ABSENT
GATE_ACK_SEMANTICS_CAPTURE_ANCHOR=not present in repository or staged evidence
GATE_SAFETY_IDEMPOTENCY_CAPTURE_STATUS=ABSENT
GATE_SAFETY_IDEMPOTENCY_CAPTURE_ANCHOR=not present in repository or staged evidence
GATE_NO_RETRY_CONTRACT_EVIDENCE_STATUS=ABSENT
GATE_NO_RETRY_CONTRACT_EVIDENCE_ANCHOR=not present in repository or staged evidence
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN=6
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH=6
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT=false
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE=6
GATE_ACTUATION_PROFILE_VALIDATED_REAL=false
GATE_ACTUATION_PROFILE_VALIDATED_MUTATED=true
GATE_STANDARD_PRESS_ALLOWED_REAL=false
GATE_STANDARD_PRESS_ALLOWED_MUTATED=true
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_REAL=6
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_MUTATED=CONFLICT
GATE_ACTUATION_PROFILE_VALIDATED_FLIPS=PASS
GATE_STANDARD_PRESS_ALLOWED_FLIPS=PASS
DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_FLIPS=PASS
R61_SELF_CHECK=PASS
GATE_PROFILE_MISSING_REASON=NO_GATE_COMMAND_SEQUENCE_CHANNEL_SELECTOR_ACK_SAFETY_NO_RETRY_PROOF
NEXT_REQUIRED_STEP=PASSIVE_CAPTURE
RAW_PAYLOAD_BYTES_COMMITTED=false
LIVE_ACTIONS=0
PRODUCTION_MUTATIONS=0
SECRETS_READ=false
NETWORK_ACTION_PERFORMED=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
```
