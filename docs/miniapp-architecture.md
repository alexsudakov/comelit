# Comelit Telegram Mini App architecture

Status: embedded implementation baseline  
Date: 2026-09-27  
Repository: `alexsudakov/comelit`

## 1. Ownership boundary

The Telegram Mini App is a Comelit product surface and lives entirely inside the
Home Assistant custom integration.

Production runtime:

```text
Telegram Mini App
        |
        | HTTPS
        v
Home Assistant HTTP server
        |
        v
custom_components/comelit
        |
        +-- Mini App auth/session/views
        +-- shared comelit-card.js
        +-- HA state / registry / services / camera stream
        |
        v
Comelit runtime
```

There is no standalone Comelit application server, FastAPI service, Docker
runtime, Home Assistant Long-Lived Access Token, or Home Assistant REST/WebSocket
client in the Mini App path.

`llm-home-assistant-stack`, CT120 and CT123 are not production dependencies for
the Mini App.

## 2. One UI artifact

Both Lovelace and Telegram reuse:

```text
custom_components/comelit/frontend/comelit-card.js
```

Telegram hosts the same custom element from:

```text
custom_components/comelit/miniapp/index.html
custom_components/comelit/frontend/miniapp/host.js
custom_components/comelit/frontend/miniapp/styles.css
```

The Telegram host implements only the narrow `hass` surface already consumed
by the shared card:

```text
hass.states
hass.callWS(config/entity_registry/list)
hass.callWS(config/label_registry/list)
hass.callService(button, press, ...)
window.loadCardHelpers().createCardElement(picture-entity)
```

The host adapter does not expose a general Home Assistant API.

## 3. Home Assistant HTTP boundary

The integration registers public Home Assistant views under:

```text
/api/comelit/miniapp
/api/comelit/miniapp/session
/api/comelit/miniapp/bootstrap
/api/comelit/miniapp/state
/api/comelit/miniapp/door/{entrance|gate}
/api/comelit/miniapp/camera/{entity_id}/stream
```

The index and session-establishment endpoints are intentionally reachable
without Home Assistant user authentication because Telegram users do not have a
Home Assistant access token.

All state, Door and camera endpoints enforce the integration-owned Mini App
session.

Only JavaScript/CSS assets use the existing Comelit static prefix:

```text
/api/comelit/frontend/...
```

The Mini App HTML itself is deliberately stored outside that static tree and is
served only by the dynamic `/api/comelit/miniapp` view, so the enable/configuration
gate and CSP cannot be bypassed through an alternate static URL.

## 4. Telegram authentication without a bot token

The browser sends raw `Telegram.WebApp.initData`.

The integration validates the `signature` field using Telegram's production
Ed25519 public key and the bot ID according to Telegram's documented
third-party validation algorithm:

https://core.telegram.org/bots/webapps#validating-data-for-third-party-use

The production Telegram public key is pinned in code:

```text
e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d
```

Validation also requires:

- bounded `auth_date`;
- valid Telegram user JSON;
- server-side Telegram user allowlist.

`initDataUnsafe` is never an authorization source.

The Comelit integration therefore does not require the Telegram bot token.

## 5. Short-lived in-memory sessions

After successful Telegram validation, the integration creates:

- a random opaque session token;
- a 15-minute in-memory session;
- one current random Door action nonce.

The browser receives only the session token in a cookie:

```text
HttpOnly
Secure
SameSite=Strict
Path=/api/comelit/miniapp
```

Sessions are intentionally not persisted. Home Assistant restart invalidates
them; Telegram can establish a new session from fresh `initData`.

Removing a Telegram user from the current allowlist invalidates that user's
existing session on the next protected request.

## 6. Home Assistant access

Because Mini App code executes inside `custom_components/comelit`, it uses
Home Assistant objects directly:

```text
hass.states
entity_registry
label_registry
hass.services
camera async_request_stream
```

There is no HA Long-Lived Access Token.

The browser receives only the filtered states and registry metadata required by
the Comelit card.

## 7. Surveillance cameras

The integration option `miniapp_surveillance_label` accepts a Home Assistant
label ID or label name.

Only `camera.*` registry entries carrying that label are added to the Telegram
Mini App surveillance surface.

The intercom entrance camera is selected independently by its stable Comelit
unique ID and is not duplicated in the surveillance list.

## 8. Door/Gate safety

The browser does not choose an arbitrary Home Assistant entity for actuation.

The shared card's selected button entity is mapped client-side back to one of
two semantic routes:

```text
POST /api/comelit/miniapp/door/entrance
POST /api/comelit/miniapp/door/gate
```

The server independently resolves the current entity ID from these stable
Comelit unique IDs:

```text
comelit_main_entrance_open_door
comelit_main_gate_open_door
```

Before invoking the service, the embedded boundary requires the current entity
to be available and to report `standard_press_allowed=true`.

One accepted request performs exactly one:

```text
hass.services.async_call(
    "button",
    "press",
    {"entity_id": ...},
    blocking=True,
)
```

There is no automatic retry.

The Mini App host also explicitly never retries an action request after a
failure.

### 8.1 One-time action nonce

Each authenticated session owns one current action nonce.

A Door request must include it. The server consumes and rotates the nonce
**before** awaiting the Home Assistant service call.

Consequences:

- replaying the same HTTP request cannot invoke a second Door operation;
- a network timeout after an ambiguous operation does not trigger an automatic
  retry;
- a later explicit user click can use the newly issued nonce.

A successful software call never asserts the physical Door effect.

## 9. Camera lifecycle

The Mini App does not implement a second camera transport.

After validating the requested camera against the embedded allowlist, the
integration calls Home Assistant's normal camera stream API:

```text
async_request_stream(hass, entity_id, HLS_PROVIDER)
```

For `camera.comelit_entrance`, this enters the existing
`ComelitEntranceCamera.async_create_stream()` lifecycle:

```text
explicit Mini App viewer
-> HA camera stream request
-> attached Ring reuse when present
   otherwise bounded on-demand Comelit media
-> HA Stream / HLS
-> viewer removed or HLS becomes idle
-> existing camera-view cleanup
```

### 9.1 Do not expose the HA HLS capability to the WebView

Home Assistant's HLS endpoint contains a random stream capability token and is
itself intentionally usable without HA user authentication.

The embedded Mini App therefore keeps that HA HLS path server-side.

For each authorized camera open it creates a random, session-bound media grant:

```text
/api/comelit/miniapp/media/<media_id>/master_playlist.m3u8
```

The media grant stores the upstream HA HLS base path only inside Home
Assistant. Every Mini App playlist/init/segment request:

1. revalidates the current Mini App session;
2. rechecks the current bot ID and Telegram user allowlist through the session
   boundary;
3. verifies that the media grant belongs to that exact opaque session token;
4. allows only the closed HLS resource set:
   - `master_playlist.m3u8`
   - `playlist.m3u8`
   - `init.mp4`
   - numeric `segment/*.m4s`
5. proxies that resource to Home Assistant's own local HLS endpoint.

Relative HLS references keep the browser inside the Mini App proxy hierarchy,
so the underlying `/api/hls/<token>/...` capability is never serialized to
the WebView.

The media grant expires with the Mini App session. Removing a user from the
allowlist or changing the configured bot ID also prevents further proxy
requests from that session.

The Mini App host provides a small `picture-entity` compatibility element
using an HTML5 `video` element.

Playback is capability-driven. The integration bundles pinned `hls.js 1.7.3`
under the existing same-origin Comelit frontend path. Telegram Desktop / Android
WebViews that expose MediaSource use hls.js; native HLS remains the fallback for
platforms such as Safari/iOS. No third-party JavaScript is fetched at runtime.

The hls.js instance is destroyed when the viewer is removed. Fatal playback
errors stop that viewer and are surfaced to the user instead of automatically
reopening the Comelit camera session.

## 10. Home Assistant options

The Comelit Options Flow contains:

```text
Enable Telegram Mini App
Telegram bot ID
Allowed Telegram user IDs
Home Assistant camera label
```

No Telegram bot token and no Home Assistant token are stored.

The Mini App route is fail-closed until:

- Mini App is enabled;
- bot ID is valid;
- at least one allowed Telegram user ID is configured.

## 11. External HTTPS

Telegram still requires the Mini App URL to be reachable by the Telegram
WebView over HTTPS in production.

The target URL is the Home Assistant URL itself, for example:

```text
https://<external-home-assistant-host>/api/comelit/miniapp
```

The external HTTPS mechanism is an installation concern (for example Home
Assistant Cloud or a reverse proxy), not a separate Comelit application
runtime.

## 12. Deployment boundary

Repository implementation does not by itself:

- enable the Mini App option;
- configure Telegram BotFather;
- publish or change an external Home Assistant URL;
- restart production Home Assistant;
- invoke Door/Gate;
- open a production camera session.

Those remain explicit deployment and acceptance steps.


## Surveillance live view: on-demand WebRTC via Home Assistant go2rtc

Ordinary Home Assistant surveillance cameras use a different live-view path from
the Comelit entrance camera.

For ordinary cameras, the Mini App first attempts Home Assistant's registered
WebRTC provider. On HAOS/default-config installations this is normally the
Home Assistant-managed go2rtc provider. The source is registered with go2rtc
on demand when the viewer opens; Comelit does not enable camera preload.

Conceptual path:

```text
Telegram Mini App
  -> session-bound Comelit WebSocket signaling endpoint
  -> Home Assistant Camera WebRTC API/provider
  -> Home Assistant-managed go2rtc
  -> camera RTSP source
```

The browser receives only WebRTC signaling through the authenticated Mini App
route. It does not receive go2rtc credentials or direct go2rtc management API
access.

When the viewer is removed or the Mini App WebSocket closes, the Home Assistant
camera WebRTC session is explicitly closed. If WebRTC is unavailable for a
particular ordinary camera/client, the existing session-bound Home Assistant
HLS proxy remains the fallback.

The Mini App treats WebRTC signaling, remote-track announcement, and the first
decoded/rendered video frame as separate milestones. A remote track alone is
not reported as successful playback. While a first frame is pending, the UI can
surface elapsed time plus inbound RTP bytes and decoded-frame count from browser
WebRTC statistics. This distinguishes an ICE/RTP delivery problem from a
decode/render or slow-source/keyframe problem during production canaries.

The Comelit entrance camera is deliberately excluded from this new path. It
continues to use the separately validated on-demand Comelit media manager and
HLS proxy, preserving listener/media ownership invariants.

This WebRTC path does not imply preload: no ordinary camera stream is kept open
merely because it is listed in the Mini App.
