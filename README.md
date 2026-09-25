# Comelit for Home Assistant

Custom Home Assistant integration for Comelit ViP.

Current target architecture is direct Home Assistant integration: Home Assistant owns the persistent Comelit P2P session, receives incoming ring events, exposes protected Door/Gate control, and owns the on-demand intercom camera lifecycle. CT120/Hermes is retained only for development and remote validation support; it is not part of the production runtime path.

## Installation and updates

The integration is intended to be installed and updated through HACS as a custom repository. All runtime files required by Home Assistant, including the native helper and its bundled runtime libraries, live under `custom_components/comelit/`.

Repository: `alexsudakov/comelit`  
Category: Integration

## Home Assistant Custom Card

Version 1.5.19 keeps an explicitly opened entrance intercom live view active across switches between «Домофон» and «Видеонаблюдение», while retaining the Phase C controls.

After updating the integration and restarting Home Assistant, register this resource once in the Lovelace resource settings:

```text
URL: /api/comelit/frontend/comelit-card.js
Type: JavaScript Module
```

Then add the card. The preferred configuration selects ordinary surveillance cameras with a Home Assistant label:

```yaml
type: custom:comelit-card
default_tab: surveillance
surveillance:
  label: <Home Assistant label id>
```

An explicit camera allowlist can be used instead:

```yaml
type: custom:comelit-card
default_tab: surveillance
surveillance:
  include:
    - camera.example_1
    - camera.example_2
```

The card deliberately does not discover every Home Assistant camera automatically. Ordinary surveillance cameras remain standard Home Assistant `camera.*` entities. Their source URLs and credentials are never passed into the card.

The surveillance viewer delegates playback to Home Assistant's built-in `picture-entity` card with `camera_view: live`. The card does not enable camera stream preload.

The intercom tab now supports an explicit entrance live view and semantic Entrance/Gate Door buttons.

Opening the entrance camera is always an explicit user action. The card delegates playback to Home Assistant's standard camera viewer and does not expose raw stream credentials.

An explicitly opened entrance viewer remains connected while the user switches to the surveillance tab. Returning to «Домофон» therefore resumes the same viewer without intentionally releasing the intercom camera-view lease. The intercom viewer stops only after an explicit «Скрыть камеру», a panel change that makes it irrelevant, card teardown/reload, or backend/session termination including the absolute media limit.

Ordinary surveillance viewers remain non-persistent: leaving «Видеонаблюдение» releases that hidden viewer so a standard RTSP/HLS camera is not kept alive unnecessarily.

Door buttons resolve the current Comelit button entities by stable unique id and invoke exactly one Home Assistant `button.press` per explicit user click. The card does not retry automatically and never claims that the physical door/gate opened merely because the service call completed.

Microphone / Answer / Hangup remain intentionally out of scope until the full-duplex transport is separately validated.

On a new authoritative `ringing` event, the card focuses the «Домофон» tab once and highlights the active panel. If the user then switches to «Видеонаблюдение», the card does not force the tab back on subsequent Home Assistant state updates. This keeps surveillance viewing independent while a call is active.

## Current capabilities

- Direct Comelit cloud P2P bootstrap and persistent session
- Incoming `comelit_ring` Home Assistant events
- `sensor.comelit_call_state` authoritative current call state reconstructed from runtime evidence
- Exact-frame retransmit deduplication for incoming CALL_INIT
- OAuth access-token refresh with refresh-token persistence in the Home Assistant config entry
- Entrance and Gate Door actions through `comelit.open_door`
- Standard Home Assistant button entities for Entrance and Gate
- `camera.comelit_entrance` live view with automatic on-demand media startup
- Camera live view reuses the already-active inbound Ring transaction when available
- One shared HA Stream for simultaneous Ring snapshot/recording and user live view
- Real inbound Ring media remains warm after the 20-second recording until backend-observed remote close
- Automatic live-view release through Home Assistant Stream/HLS consumer lifecycle
- Thumbnail/entity-picture requests do not start Comelit media
- Home Assistant stream preloading is forced off for the intercom camera
- Same-session periodic media refresh keeps entrance video alive beyond the historical 30–35 second cutoff
- Absolute media-session ceiling remains 600 seconds
- Bundled surveillance-first Home Assistant Custom Card
- Custom Card incoming-call focus and active-panel highlighting from `sensor.comelit_call_state`
- Custom Card explicit entrance live view and semantic Entrance/Gate Door buttons
- Current Ring -> Telegram automation is driven by `sensor.comelit_call_state`, not by the deprecated camera switch or a short local call timer

## Call-state lifecycle

The integration publishes `sensor.comelit_call_state` with stable unique id `comelit_call_state`.

Current emitted states are intentionally conservative:

```text
idle
ringing
error
```

Future enum values `answering`, `in_call` and `ending` are reserved for later full-duplex work and are not synthesized by the current runtime.

The sensor stores the active panel and event id as attributes. Incoming attached media is represented independently as `media_attached`; opening or closing video alone does not mean that the call ended.

`ringing -> idle` is driven by backend-observed remote-release evidence. The frontend does not infer call termination from a timer or from the age of the last `comelit_ring` event.

## Home Assistant Ring -> Telegram automation

The maintained Home Assistant package example is:

```text
examples/home-assistant/packages/comelit_ring_telegram_live.yaml
```

Its current lifecycle is event/state driven:

```text
comelit_ring
  -> wait for integration-owned comelit_snapshot_updated
  -> send one Telegram photo message
  -> keep editing that same message with new snapshots
  -> send the retained 20-second recording when comelit_recording_complete fires
  -> keep the interaction alive while sensor.comelit_call_state is ringing
  -> finish on backend-observed ringing -> idle for the same event_id
```

The 20-second recording duration is not a call timeout. The automation does not toggle
`switch.comelit_entrance_camera`, does not call `camera.snapshot`, and does not stop
attached Ring media on Ignore.

For an accepted Open callback during a real Ring, the current automation sends exactly
one `button.press` to `button.comelit_main_entrance_open_door`, matching the current
Custom Card Door path. It does not retry and does not claim physical opening. The
current `comelit.open_door` service remains fail-closed while
`attached_media_busy=true`, so it is not the current Telegram action surface during
an active attached Ring.

Full current contract and UI-migration notes:
`docs/ring-telegram-ha-automation-current.md`.

## Camera lifecycle

Normal use does not require a separate media switch:

```text
open camera.comelit_entrance
  -> acquire camera_view lease
  -> reuse inbound Ring media when present
     otherwise start one on-demand self-activation session
  -> HA Stream / HLS
  -> viewer becomes idle
  -> release camera_view lease
  -> media teardown when no other lease remains
  -> listener READY
```

`switch.comelit_entrance_camera` remains only as a disabled-by-default deprecated diagnostic fallback. Camera-owned automatic startup and automatic release have already been live-validated in HAOS, so current user flows and the maintained Telegram automation do not depend on it. Removal is a later compatibility cleanup.

## Safety contract

Door operations are one-shot. Automatic Door retry is not allowed. A protocol acknowledgement is never treated as proof that the physical door opened. The Custom Card and current Ring/Telegram automation use the standard Door button entity for one explicit user request during an attached Ring; separately bootstrapped on-demand media remains fail-closed for Door actions. Physical Door validation remains separate from protocol outcome.

Intercom media is on-demand only. Home Assistant startup, thumbnails and still-image polling must not open the camera session. Separately bootstrapped on-demand media pauses the persistent listener before bootstrap and restores it only after confirmed teardown. A new viewer or lease never extends the absolute 600-second deadline.

Real inbound Ring media follows backend-observed remote/native close rather than the 20-second recording duration; a 600-second defense-in-depth ceiling remains. Gate actuation is implemented with the validated protocol profile, but physical Gate effect remains a separate live acceptance item until confirmed on the installation.
