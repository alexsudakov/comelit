# Comelit Telegram Mini App architecture

Status: implementation baseline  
Date: 2026-09-27  
Repository: `alexsudakov/comelit`

## 1. Ownership boundary

The Telegram Mini App is a Comelit product surface and lives entirely in this repository.

`llm-home-assistant-stack` is not a Mini App code or runtime dependency.

The Home Assistant integration remains the sole owner of Comelit protocol, Ring, Door and media semantics. The Mini App talks to Home Assistant and does not implement the Comelit cloud/P2P protocol.

## 2. One UI artifact

The Mini App reuses:

```text
custom_components/comelit/frontend/comelit-card.js
```

The same `custom:comelit-card` therefore owns the presentation and interaction semantics in both contexts.

The two hosts differ only in the adapter supplied to the card:

```text
                     comelit-card.js
                           |
              +------------+------------+
              |                         |
        Lovelace host              Telegram host
              |                         |
        native hass object        hass-compatible adapter
                                        |
                                Mini App gateway
                                        |
                               Home Assistant API
```

No separate HTML implementation of Door/Ring/panel behavior is maintained.

## 3. Home Assistant authentication

The gateway uses a Home Assistant Long-Lived Access Token from:

```text
COMELIT_MINIAPP_HA_TOKEN
```

The token is process configuration / deployment secret material.

It MUST NOT be:

- rendered into HTML or JavaScript;
- returned by health/bootstrap endpoints;
- logged;
- stored in a browser cookie;
- committed to Git.

The browser authenticates only to the Mini App gateway. The gateway attaches `Authorization: Bearer <token>` to server-side Home Assistant HTTP requests and sends the token in the Home Assistant WebSocket authentication message.

## 4. Telegram identity

The WebView sends raw `Telegram.WebApp.initData` to the gateway.

The gateway:

1. validates the Telegram HMAC server-side;
2. checks bounded `auth_date`;
3. checks a server-side Telegram user allowlist;
4. returns a short-lived signed HttpOnly session cookie.

`initDataUnsafe` is never an authorization source.

## 5. Narrow hass adapter

The Mini App adapter implements only the subset already consumed by the shared card:

```text
hass.states
hass.callWS(config/entity_registry/list)
hass.callWS(config/label_registry/list)
hass.callService(button, press, ...)
window.loadCardHelpers().createCardElement(picture-entity)
```

The browser does not receive a general Home Assistant API proxy.

### 5.1 State and registry filtering

The gateway exposes only:

- known stable Comelit unique IDs required by the card;
- optionally configured surveillance `camera.*` entities.

Only card-required state attributes are serialized.

The label registry is currently returned empty because the Mini App surveillance set is an explicit server-side camera allowlist. Lovelace label discovery remains unchanged.

## 6. Door/Gate safety

The Mini App action boundary resolves current entities through Home Assistant's entity registry and accepts only:

```text
comelit_main_entrance_open_door
comelit_main_gate_open_door
```

One accepted Mini App request results in exactly one:

```text
POST /api/services/button/press
```

There is no automatic retry.

The existing card remains responsible for availability gating using current button state attributes and call context. The backend repeats the stable-unique-ID allowlist check so a manipulated browser cannot press an arbitrary Home Assistant entity.

An HTTP/service success means only that the command was accepted by the software path. It is not physical Door proof.

## 7. Camera path

The shared card still asks `loadCardHelpers().createCardElement` for a `picture-entity`.

In Telegram, the host adapter supplies a minimal compatible camera viewer. It asks the gateway for an MJPEG stream.

The gateway:

1. validates that the camera is the Comelit entrance camera or an explicit surveillance allowlist entry;
2. requests Home Assistant `stream_camera` information over the authenticated WebSocket API;
3. proxies the returned MJPEG path with the server-side HA token.

The Long-Lived Access Token is therefore not embedded in the camera URL visible to the browser.

Viewer lifecycle follows DOM lifecycle:

- removing a surveillance viewer closes its browser stream;
- the existing Custom Card keeps an explicitly opened intercom viewer mounted across tab switches, so that behavior is preserved in Mini App mode too.

## 8. Deployment boundary

This implementation adds code only. It does not:

- deploy a Mini App service;
- create or rotate a Home Assistant token;
- configure BotFather;
- change the existing HomeAI bot;
- modify production Home Assistant;
- perform a Door/Gate action.

Those are separate deployment/acceptance steps.
