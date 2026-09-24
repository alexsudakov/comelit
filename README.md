# Comelit for Home Assistant

Custom Home Assistant integration for Comelit ViP.

Current target architecture is direct Home Assistant integration: Home Assistant owns the persistent Comelit P2P session, receives incoming ring events, exposes protected Door/Gate control, and owns the on-demand intercom camera lifecycle. CT120/Hermes is retained only for development and remote validation support; it is not part of the production runtime path.

## Installation and updates

The integration is intended to be installed and updated through HACS as a custom repository. All runtime files required by Home Assistant, including the native helper and its bundled runtime libraries, live under `custom_components/comelit/`.

Repository: `alexsudakov/comelit`  
Category: Integration

## Current capabilities

- Direct Comelit cloud P2P bootstrap and persistent session
- Incoming `comelit_ring` Home Assistant events
- Exact-frame retransmit deduplication for incoming CALL_INIT
- OAuth access-token refresh with refresh-token persistence in the Home Assistant config entry
- Entrance and Gate Door actions through `comelit.open_door`
- Standard Home Assistant button entities for Entrance and Gate
- `camera.comelit_entrance` live view with automatic on-demand media startup
- Camera live view reuses the already-active inbound Ring transaction when available
- One shared HA Stream for simultaneous Ring snapshot/recording and user live view
- Automatic live-view release through Home Assistant Stream/HLS consumer lifecycle
- Thumbnail/entity-picture requests do not start Comelit media
- Home Assistant stream preloading is forced off for the intercom camera
- Same-session periodic media refresh keeps entrance video alive beyond the historical 30–35 second cutoff
- Absolute media-session ceiling remains 600 seconds

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

For release 1.5.13, `switch.comelit_entrance_camera` remains only as a disabled-by-default deprecated diagnostic fallback. It is not part of the target user-facing workflow and is planned for removal after HAOS live validation of the automatic lifecycle.

## Safety contract

Door operations are one-shot. Automatic Door retry is not allowed. A protocol acknowledgement is never treated as proof that the physical door opened. Physical Door validation requires a separate explicit controlled test.

Intercom media is on-demand only. Home Assistant startup, thumbnails and still-image polling must not open the camera session. Separately bootstrapped on-demand media pauses the persistent listener before bootstrap and restores it only after confirmed teardown. A new viewer or lease never extends the absolute 600-second deadline.

Gate actuation is implemented with the validated protocol profile, but physical Gate effect remains a separate live acceptance item until confirmed on the installation.
