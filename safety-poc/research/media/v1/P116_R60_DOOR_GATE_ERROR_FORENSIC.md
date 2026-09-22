# P116 R60 Track B Door / Gate error forensic

Дата: 2026-09-22. Режим: `OFFLINE_READ_ONLY_PLUS_STATIC_CORRECTIVE`. Door/Gate domains separated from Track A media/reconnect lifecycle. No HA service calls, deploy, restart, physical ring, self-activation, Door actuation, Gate actuation, Comelit live TX, HA token, or webhook start/stop were used. `TRACK_B_MEDIA_SEMANTICS_CHANGED=false`.

## B0 Issue Class

`OBSERVED` Read-only production status says integration is present, version `1.5.8`, deployed SHA `b318101d07f8f32d9f703e845b32c7f3538548b1`, listener `running=true`, `listener_ready=true`, `attached_media_busy=false`, and `door_last_operation_id=null` / `door_last_state=null`. Therefore no historical Door failure result exists to dissect.

`PROVEN_STATIC` `DOOR_ISSUE_CLASS=MULTIPLE(ENTITY_MAPPING_ERROR,GATE_PROFILE_NOT_VALIDATED)`.

Rejected classes:

- `ENTRANCE_BUTTON_UNAVAILABLE`: rejected by source; entrance capability is configured, ring-source validated, actuation-profile validated, and no media pause makes `available=true` (`const.py:89-127`, `button.py:65-74`).
- `ENTRANCE_PRESS_ERROR` / `ENTRANCE_PROTOCOL_REJECT`: unknown live behavior, but not observed; production status has no Door operation record.
- `ENTRANCE_UI_STATE`: covered specifically as `ENTITY_MAPPING_ERROR`.
- `GATE_BUTTON_UNAVAILABLE_BY_CONTRACT`: rejected as entity-availability wording; Gate entity is available when not media-paused (`button.py:153-158`, `const.py:123-127`).
- `OTHER`: not needed.

Intended fail-closed contract: `GATE_PROFILE_NOT_VALIDATED`. UI/runtime defect: `ENTITY_MAPPING_ERROR`, because before this corrective the entrance Door button reused the switch friendly name `Comelit — Подъезд`, making the action target ambiguous against `switch.comelit_entrance_camera`.

## B1 Entrance Door

`PROVEN_STATIC` `ENTRANCE_ENTITY_PRESENT=true`. `ComelitEntranceDoorButton` is added by the single `button.py` platform `async_add_entities([...])`, has `entity_id = MAIN_ENTRANCE_ENTITY_ID`, and the constant is `button.comelit_main_entrance_open_door` (`button.py:39-43`, `button.py:47-63`, `const.py:150-151`).

`PROVEN_STATIC` `ENTRANCE_ENTITY_AVAILABLE=true` when not media-paused: `available` resolves `DOOR_ENTRANCE`, whose topology has `configured=true`, `ring_source_validated=true`, `actuation_profile_validated=true`; `available = configured and ring_source_validated and not media_paused` (`button.py:65-74`, `const.py:89-127`).

`PROVEN_STATIC` `ENTRANCE_PRESS_ALLOWED=true`: `press_allowed = available and actuation_profile_validated`, so entrance is allowed when available (`const.py:123-127`).

`PROVEN_STATIC` `ENTRANCE_RUNTIME_PATH_INTACT=true`. `async_press()` calls `runtime.async_open_door(DOOR_ENTRANCE)` and raises unless `protocol_acked is True` (`button.py:117-133`). Runtime rejects unsupported doors, serializes with `_door_lock`, waits for listener READY before the one-shot boundary, generates a HA-local operation id, sends exactly one `SIGUSR1`, converts timeout/malformed states to `UNKNOWN_OUTCOME`, requires Door-specific ACK proof, bounds `write_count` to `0..5`, disables automatic retry, and finalizes via `EVENT_DOOR_OPERATION` (`runtime.py:876-995`, `runtime.py:1170-1236`).

`PROVEN_OFFLINE` R42-R58 survival check from `git log --oneline -- custom_components/comelit/runtime.py`: Door path was introduced/kept through `ac87c54` (event finalization and one-shot path), `7da3b8b` (Door reject diagnostics), and `74f5d7b` (persistent CTPP reuse, Door-specific ACK proof and write-count bounds). Later R56-R59 commits are media/failure-observability rounds and did not remove the anchors verified above.

B4 anchors:

- SIGUSR1 handler boundary: Python sends `os.kill(process.pid, signal.SIGUSR1)` exactly once (`runtime.py:924-929`); native signal handler is in generated source outside this corrective.
- `_door_lock`: `async with self._door_lock` (`runtime.py:886`).
- operation id: `operation_id = f"comelit-ha-{uuid4()}"` (`runtime.py:924-926`).
- single invocation: source has one `os.kill(... SIGUSR1)` call in `async_open_door` (`runtime.py:928`).
- Door-specific ACK parsing: `V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=` -> `door_specific_ack_proven` (`runtime.py:1176-1196`).
- `UNKNOWN_OUTCOME`: timeout and invalid native result map to `UNKNOWN_OUTCOME` (`runtime.py:943-949`, `runtime.py:1228-1235`).
- no automatic retry: result hard-codes `automatic_retry_allowed=false` and finalizer enforces it (`runtime.py:860-873`, `runtime.py:965-979`).
- listener-READY guard: `async_wait_ready(timeout=30)` returns `FAILED_SAFE` before `SIGUSR1` (`runtime.py:886-901`).
- media-active guard: button blocks while `supervisor.media_paused` and exposes `blocked_by_media_session` (`button.py:83-90`, `button.py:117-123`).

## B2 Gate

`PROVEN_STATIC` `GATE_ENTITY_PRESENT=true`. `ComelitGateDoorButton` exists, uses `entity_id = MAIN_GATE_ENTITY_ID`, and the constant is `button.comelit_main_gate_open_door` (`button.py:136-151`, `const.py:152-153`).

`PROVEN_STATIC` `GATE_ENTITY_AVAILABLE=true` when not media-paused. Gate topology is configured and ring-source validated, and availability does not imply actuation proof (`const.py:96-127`, `button.py:153-158`).

`PROVEN_STATIC` `GATE_RING_SOURCE_VALIDATED=true`, `ring_source="00000610"` (`const.py:96-101`).

`PROVEN_STATIC` `GATE_ACTUATION_PROFILE_VALIDATED=false` (`const.py:96-100`).

`PROVEN_STATIC` `GATE_STANDARD_PRESS_ALLOWED=false` because `press_allowed = available and actuation_profile_validated` (`const.py:123-127`). `async_press()` deliberately makes no runtime call and raises (`button.py:180-186`).

## B3 Gate Profile Offline Research

`UNRESOLVED` Gate actuation profile cannot be validated offline from available artifacts.

Local evidence proves Gate ring-source identity but not actuation. Read-only web research found generic Comelit material stating that Comelit apps can open gates/doors, and third-party reverse-engineering pages discuss Door-opening command families, but none prove this deployment's Gate target/source identity, command sequence, channel allocation, output/address selector, ACK semantics, safety/idempotency, or no-retry behavior.

`PROVEN_STATIC` Transferring entrance profile to Gate is forbidden and was not done. `GATE_ACTUATION_PROFILE_VALIDATED=false` remains unchanged; Gate remains fail-closed.

Missing named artifacts:

```
GATE_TARGET_SOURCE_IDENTITY_CAPTURE
GATE_COMMAND_SEQUENCE_CAPTURE
GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE
GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE
GATE_ACK_SEMANTICS_CAPTURE
GATE_SAFETY_IDEMPOTENCY_CAPTURE
GATE_NO_RETRY_CONTRACT_EVIDENCE
```

## B5 Entity / UI Corrective

`PROVEN_OFFLINE` Corrective implemented: entrance Door button name changed from ambiguous `Comelit — Подъезд` to `Comelit — Открыть подъезд` (`button.py:50`). The media switch remains `Comelit — Подъезд` (`switch.py:41`) and camera remains `Comelit — Камера подъезда` (`camera.py:227`).

`PROVEN_STATIC` Entity IDs and unique IDs are untouched (`button.py:51-62`, `button.py:139-151`, `const.py:150-153`). `async_add_entities` remains exactly one call in each platform file, asserted by tests.

`PROVEN_STATIC` Gate name still denotes the Gate/калитка domain and remains fail-closed (`button.py:139-186`).

## B7 Offline Harness

`PROVEN_OFFLINE` Focused harness `test_p116_r60_door_gate_contract.py` covers:

- entrance READY + press allowed + ACK
- listener unavailable
- media active / media-paused guard
- operation already in progress / duplicate caller
- ACK requiring Door-specific proof
- no ACK / reject
- malformed response -> `UNKNOWN_OUTCOME`
- timeout -> `UNKNOWN_OUTCOME`
- no automatic retry
- Gate fail-closed

Markers are derived from case dictionaries; flip tests corrupt each invariant and assert `FAIL`.

```
DOOR_ENTITY_MAPPING_PASS=PASS
DOOR_SAFETY_CONTRACT_PASS=PASS
GATE_FAIL_CLOSED_CONTRACT_PASS=PASS
```

## No Actuation

`PROVEN_OFFLINE`

```
DOOR_ACTIONS=0
GATE_ACTIONS=0
DOOR_LIVE_VALIDATION_AUTHORIZED=false
GATE_LIVE_VALIDATION_AUTHORIZED=false
```

All zeros are deliberate. This round used source inspection, committed evidence, read-only status facts supplied by the orchestrator, and read-only web research only. No Door/Gate command was sent or simulated against production.

## Tests

`PROVEN_OFFLINE`

```
cd safety-poc && PYTHONPATH=/home/hermes/artifacts/comelit/safety-poc/src:/home/hermes/artifacts/comelit/safety-poc PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_p116_r60_*.py'
Ran 35 tests in 0.073s
OK
```

Full-suite result is recorded in the turn report; the executor sandbox can exhibit known UDP-sink errors in the older R29I module, while host verification is authoritative for that artifact.

## Sanitisation

`PROVEN_OFFLINE` This record contains no HA token, production secret, raw payload, CTP id, address, packet capture, Door/Gate actuation result, or live network command. The only external web facts used are generic public statements that Comelit apps support gates/doors; they are insufficient for Gate protocol validation.

## Machine Values

```
DOOR_ISSUE_CLASS=MULTIPLE(ENTITY_MAPPING_ERROR,GATE_PROFILE_NOT_VALIDATED)
ENTRANCE_ENTITY_PRESENT=true
ENTRANCE_ENTITY_AVAILABLE=true
ENTRANCE_PRESS_ALLOWED=true
ENTRANCE_RUNTIME_PATH_INTACT=true
ENTRANCE_DOOR_CORRECTIVE_IMPLEMENTED=true
GATE_ENTITY_PRESENT=true
GATE_ENTITY_AVAILABLE=true
GATE_RING_SOURCE_VALIDATED=true
GATE_ACTUATION_PROFILE_VALIDATED=false
GATE_STANDARD_PRESS_ALLOWED=false
GATE_CORRECTIVE_IMPLEMENTED=false
GATE_PROFILE_MISSING_EVIDENCE=GATE_TARGET_SOURCE_IDENTITY_CAPTURE,GATE_COMMAND_SEQUENCE_CAPTURE,GATE_CHANNEL_RUNTIME_ALLOCATION_CAPTURE,GATE_OUTPUT_ADDRESS_SELECTOR_CAPTURE,GATE_ACK_SEMANTICS_CAPTURE,GATE_SAFETY_IDEMPOTENCY_CAPTURE,GATE_NO_RETRY_CONTRACT_EVIDENCE
DOOR_ENTITY_MAPPING_PASS=PASS
DOOR_SAFETY_CONTRACT_PASS=PASS
GATE_FAIL_CLOSED_CONTRACT_PASS=PASS
DOOR_ACTIONS=0
GATE_ACTIONS=0
TRACK_B_MEDIA_SEMANTICS_CHANGED=false
```
