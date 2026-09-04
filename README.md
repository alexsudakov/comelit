# Comelit for Home Assistant

Custom Home Assistant integration for Comelit ViP.

Current target architecture is direct Home Assistant integration: Home Assistant owns the persistent Comelit P2P session, receives incoming ring events, and exposes protected Door control. CT120/Hermes is retained only for development and remote validation support; it is not part of the production runtime path.

## Installation and updates

The integration is intended to be installed and updated through HACS as a custom repository. All runtime files required by Home Assistant, including the native helper and its bundled runtime libraries, live under `custom_components/comelit/`.

Repository: `alexsudakov/comelit`
Category: Integration

## Current capabilities

- Direct Comelit cloud P2P bootstrap and persistent session
- Incoming `comelit_ring` Home Assistant events
- Exact-frame retransmit deduplication for incoming CALL_INIT
- OAuth access-token refresh with refresh-token persistence in the Home Assistant config entry
- Direct entrance Door action through `comelit.open_door`
- Standard Home Assistant button entity for the main entrance

## Safety contract

Door operations are one-shot. Automatic Door retry is not allowed. A protocol acknowledgement is never treated as proof that the physical door opened. Physical Door validation requires a separate explicit controlled test.

The gate Door target remains unavailable until its exact actuation profile is independently validated.
