# Comelit Custom Card — target frontend architecture

Status: **proposed implementation baseline**  
Date: 2026-09-24  
Baseline main SHA: `025d8a52ee8c7bfc9257d97b6e0a4d5567b71653`

## 1. Purpose

This document turns `docs/frontend-functional-requirements.md` into an implementation contract for the Home Assistant Custom Card.

The card unifies two different backend domains without merging their lifecycles:

```text
Comelit intercom domain
  -> custom_components/comelit
  -> entrance / gate
  -> ring/call/media state
  -> semantic Door actions

Home Assistant surveillance domain
  -> standard HA camera integrations
  -> camera.*
  -> HA media presentation
```

The frontend may present both in one UI, but MUST NOT make ordinary surveillance cameras part of the Comelit protocol/runtime.

## 2. Current verified baseline

At this baseline the Comelit integration exposes these relevant stable unique IDs:

```text
comelit_main_entrance_open_door
comelit_main_gate_open_door
comelit_listener_status
comelit_entrance_media_session
comelit_entrance_camera
```

The current default entity ids are:

```text
button.comelit_main_entrance_open_door
button.comelit_main_gate_open_door
sensor.comelit_listener_status
switch.comelit_entrance_camera
camera.comelit_entrance
```

The card MUST NOT depend on these mutable entity ids. It SHOULD resolve Comelit entities through the HA entity registry using:

```text
platform == "comelit"
unique_id == expected stable unique id
```

and then use the resolved current `entity_id`.

Current Comelit ring signaling publishes the event:

```text
comelit_ring
```

with normalized event data including at least:

```text
event_id
timestamp
door
source
kind
direction
```

The runtime also retains a last ring event and observed attached-media state, but there is currently no authoritative user-facing HA entity representing the current call lifecycle.

## 3. One card, two tabs

The card type is:

```yaml
type: custom:comelit-card
```

The top-level UI MUST contain:

```text
[ Домофон ] [ Видеонаблюдение ]
```

The selected tab is local frontend presentation state only. Changing tabs MUST NOT implicitly terminate an active intercom call/session.

## 4. Surveillance camera discovery

### 4.1 Source of truth

Ordinary surveillance cameras are standard HA `camera.*` entities.

The card MUST NOT contain RTSP URLs, ports, usernames or passwords.

The card SHOULD query the HA entity registry using:

```text
config/entity_registry/list
```

Entity registry entries include their assigned label ids. The card filters only entries whose current `entity_id` belongs to the `camera` domain.

### 4.2 Label-based selection

Preferred card configuration:

```yaml
type: custom:comelit-card
surveillance:
  label: <HA label id>
```

The graphical card editor SHOULD use the standard Home Assistant label selector so the stored value is a valid HA label id.

Suggested user-facing label name:

```text
Comelit — Видеонаблюдение
```

The label name is presentation only. The card stores and matches the actual HA label id.

The frontend MUST NOT default to all HA cameras if no label is configured.

### 4.3 Explicit include/exclude

Optional configuration:

```yaml
type: custom:comelit-card
surveillance:
  label: <HA label id>
  include:
    - camera.example_extra
  exclude:
    - camera.example_hidden
```

Resolution:

```text
(label cameras UNION include) MINUS exclude
```

Only `camera.*` entities are accepted.

An entity that is not currently present in `hass.states` MAY be represented as unavailable, but MUST NOT cause the whole card to fail.

### 4.4 Intercom exclusion

Entities owned by the Comelit intercom domain MUST NOT appear in the surveillance set simply because they carry the surveillance label.

At minimum the card MUST exclude the resolved entity whose stable unique id is:

```text
comelit_entrance_camera
```

Future gate intercom camera unique ids MUST be added to the same intercom exclusion set.

## 5. Surveillance presentation

The surveillance tab has two levels:

1. camera selector/grid;
2. one selected live viewer.

The grid SHOULD show:

- HA friendly name;
- preview/thumbnail when available;
- availability/connecting state.

Selecting a camera opens one primary live viewer.

The MVP SHOULD delegate video presentation to the built-in HA camera card/media path instead of implementing RTSP/HLS/WebRTC itself.

The child camera presentation MUST behave equivalently to:

```yaml
type: picture-entity
entity: camera.example
camera_view: live
show_name: true
show_state: false
```

The card MAY instantiate a built-in Lovelace camera-capable card through Home Assistant card helpers so media behavior stays aligned with the installed HA frontend.

Preload stream is not controlled by the card.

The card MUST NOT:

- enable preload automatically;
- keep hidden surveillance streams alive;
- know the underlying RTSP credentials;
- acquire a Comelit media lease for an ordinary surveillance camera.

## 6. Intercom entity discovery

The card resolves current Comelit intercom entities by entity-registry unique id.

Required mappings for the current baseline:

```text
entrance.camera
  unique_id: comelit_entrance_camera

entrance.media_session
  unique_id: comelit_entrance_media_session

entrance.door
  unique_id: comelit_main_entrance_open_door

gate.door
  unique_id: comelit_main_gate_open_door

listener.status
  unique_id: comelit_listener_status
```

Gate camera/media controls remain absent until the integration publishes independently validated gate media entities.

Missing optional entities MUST produce an explicit unavailable capability, not a guessed entity id.

## 7. Intercom normal-view behavior

When no call is active:

```text
Домофон
  [ Подъезд ] [ Калитка ]
```

For `entrance`:

- the card may show the entrance intercom camera;
- microphone is off;
- starting the on-demand view is an explicit user action;
- media lifecycle remains owned by `ComelitMediaSessionManager`;
- Door control is shown only according to the actual HA button availability/capability state.

For `gate`:

- Door control may be shown when the resolved HA button is available;
- camera view remains unavailable until the gate media path is independently exposed by the integration.

The card MUST NOT manufacture a gate camera from an ordinary surveillance entity.

## 8. Missing backend prerequisite: authoritative call state

### 8.1 Why an event is insufficient

`comelit_ring` is an event, not durable frontend state.

A card may be:

- loaded after the ring event;
- re-rendered;
- reconnected after WebSocket interruption;
- opened on another client.

Therefore the frontend MUST NOT infer current call state from the most recent `comelit_ring` event or from elapsed wall-clock time.

### 8.2 Required entity

Before incoming-call UI becomes authoritative, the integration SHOULD expose:

```text
sensor.comelit_call_state
unique_id: comelit_call_state
```

This is a user-facing enum sensor, not merely a diagnostic trace.

Proposed states:

```text
idle
ringing
media_active
answering
in_call
ending
error
```

Only states supported by actual runtime evidence may be emitted. `answering` and `in_call` remain dormant until full-duplex answer/TX behavior is implemented.

Recommended safe attributes:

```text
panel: entrance | gate | null
event_id: string | null
started_at: ISO timestamp | null
media_attached: bool
conversation_active: bool
last_error: bounded sanitized reason | null
```

No raw peer ids, protocol target values, tokens, credentials or packet data are exposed.

### 8.3 State authority

Transitions MUST come from backend/runtime evidence.

The card MUST NOT synthesize transitions such as:

```text
ringing -> idle
```

based only on a frontend timer.

The existing `comelit_ring` event remains useful for immediate notification/focus, while `sensor.comelit_call_state` is authoritative for reconstruction after reload/reconnect.

## 9. Active-call routing rules

When the future call-state entity reports an active call for a panel:

```text
active_call_panel = entrance | gate
```

the card MUST bind:

```text
conversation audio
Door action
hangup
intercom camera
```

to that same panel.

During an active call:

- the other intercom point is not selectable;
- the surveillance tab remains available;
- selecting a surveillance camera does not alter active call state;
- microphone/audio routing remains bound to the active intercom panel;
- returning to the intercom tab returns to the active panel.

## 10. UI state model

Frontend presentation state:

```text
selected_tab
selected_surveillance_entity
selected_idle_intercom_panel
viewer_fullscreen
```

Backend-authoritative state:

```text
listener status
call state
active call panel
intercom media state
Door capability/availability
camera entity availability
```

The card MUST NOT copy backend-authoritative values into long-lived frontend state as a second source of truth.

## 11. Home Assistant API usage

The card may use authenticated APIs already available to a Lovelace card.

Required read APIs:

```text
hass.states
config/entity_registry/list
config/label_registry/list   # editor/display support
```

Actions use semantic HA entity/service calls only.

The card MUST NOT call Comelit protocol endpoints directly.

For ordinary surveillance cameras the frontend must use HA camera/media presentation rather than the source URL.

## 12. Card configuration contract

Target MVP configuration:

```yaml
type: custom:comelit-card

surveillance:
  label: <label id>
  include: []
  exclude: []

default_tab: intercom
```

Optional later presentation fields MAY include:

```yaml
surveillance:
  columns: auto
  sort: name
```

No transport credentials or Comelit raw protocol values are valid card configuration.

## 13. Graphical editor

The card SHOULD provide a graphical configuration form using the Home Assistant custom-card form API.

Minimum fields:

- surveillance label selector;
- optional camera include selector;
- optional camera exclude selector;
- default tab.

The editor SHOULD prevent non-camera entities from being selected in include/exclude.

## 14. Frontend packaging

The frontend stays in the existing `alexsudakov/comelit` repository and is delivered with the HACS integration.

Target source/artifact layout:

```text
frontend/
  src/
  package.json
  ...

custom_components/comelit/frontend/
  comelit-card.js
```

The built artifact is copied into the integration package before release/commit.

The integration serves this bundled static file using Home Assistant's supported:

```text
hass.http.async_register_static_paths(...)
```

Target resource path:

```text
/api/comelit/frontend/comelit-card.js
```

The JS bundle contains no secrets.

For v1 the user registers the resource once as a Lovelace JavaScript module. The integration MUST NOT silently mutate Lovelace storage to auto-add the resource.

Static-resource cache headers SHOULD be disabled initially so HACS integration updates cannot leave a stale frontend bundle behind.

## 15. Security boundary

Frontend receives only normal HA states/registry metadata and semantic actions.

It MUST NOT receive:

- RTSP passwords;
- OAuth/VIP tokens;
- raw Comelit session material;
- unrestricted external tokens;
- protocol target/output ids.

A browser user can invoke only actions already authorized by Home Assistant for that user/session.

Door semantics remain owned by the integration and its existing one-shot safety contract.

## 16. Implementation phases

### Phase A — backend state contract

Add and test the authoritative `sensor.comelit_call_state` without changing protocol generation or Door behavior.

This phase is offline/code-testable and does not require a live Comelit experiment merely to create the HA-facing state model.

### Phase B — surveillance-first Custom Card

Implement:

- card shell;
- tabs;
- entity registry lookup;
- label selection;
- standard HA `camera.*` surveillance grid;
- one selected live viewer;
- editor configuration.

This phase does not require intercom call-state completion.

### Phase C — idle intercom controls

Add:

- entrance normal view;
- entrance media start/stop UX through semantic HA entities;
- entrance/gate Door buttons based on current availability;
- gate camera unavailable state.

No microphone/full-duplex behavior is added.

### Phase D — incoming call UI

After Phase A is proven:

- auto-focus/intercom notification from `comelit_ring`;
- reconstruct from `sensor.comelit_call_state`;
- enforce active-panel routing;
- keep surveillance viewing independent.

### Phase E — full duplex

Only after separate protocol/backchannel validation:

- Answer;
- microphone permission;
- audio TX/RX;
- Hangup;
- `answering` / `in_call` states.

## 17. Acceptance gates

Before calling the surveillance-first card MVP complete:

1. Card resolves the configured surveillance label through HA registries.
2. Only selected `camera.*` entities appear.
3. Renaming a surveillance entity id does not expose credentials or require Comelit code changes.
4. A labeled Comelit entrance intercom camera is still excluded from surveillance.
5. Selecting each validated ordinary camera opens live video through HA.
6. No preload setting is modified.
7. No raw stream source appears in card config/state/logging.
8. Missing/unavailable camera does not break other cameras.
9. Card reload/reconnect rebuilds its camera set from HA state/registry data.
10. No Comelit media session starts while only the surveillance tab is used.

Before incoming-call UI is complete:

11. Backend call state is reconstructable after frontend reload.
12. The card does not use last-ring-event age as call-state authority.
13. Active entrance call disables gate intercom selection.
14. Active gate call disables entrance intercom selection.
15. Surveillance viewing during a call preserves the active intercom binding.
