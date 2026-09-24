# Comelit for Home Assistant

Custom Home Assistant integration for Comelit ViP.

Current target architecture is direct Home Assistant integration: Home Assistant owns the persistent Comelit P2P session, receives incoming ring events, and exposes protected Door control. CT120/Hermes is retained only for development and remote validation support; it is not part of the production runtime path.

## Installation and updates

The integration is intended to be installed and updated through HACS as a custom repository. All runtime files required by Home Assistant, including the native helper and its bundled runtime libraries, live under `custom_components/comelit/`.

Repository: `alexsudakov/comelit`
Category: Integration

## Home Assistant Custom Card

Version 1.5.13 bundles an initial surveillance-first Lovelace card.

After updating the integration and restarting Home Assistant, register this resource once in the Lovelace resource settings:

```text
URL: /api/comelit/frontend/comelit-card.js
Type: JavaScript Module
```

Then add the card in YAML mode. The preferred configuration selects ordinary surveillance cameras with a Home Assistant label:

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

The current card MVP provides live surveillance viewing through Home Assistant's built-in camera presentation path. The intercom tab is read-only at this stage; Door/media actions and authoritative active-call routing are intentionally deferred to subsequent phases.

## Current capabilities

- Direct Comelit cloud P2P bootstrap and persistent session
- Incoming `comelit_ring` Home Assistant events
- Exact-frame retransmit deduplication for incoming CALL_INIT
- OAuth access-token refresh with refresh-token persistence in the Home Assistant config entry
- Direct entrance Door action through `comelit.open_door`
- Standard Home Assistant button entities for the entrance and gate
- Bundled surveillance-first Home Assistant Custom Card

## Safety contract

Door operations are one-shot. Automatic Door retry is not allowed. A protocol acknowledgement is never treated as proof that the physical door opened. Physical Door validation requires a separate explicit controlled test.

Entrance and gate Door operations retain the same one-shot safety contract; availability is determined by the integration's validated capability/runtime state.
