# Comelit Telegram Mini App

The Telegram Mini App is part of the **Comelit project**. It reuses the exact bundled Home Assistant Custom Card at:

```text
custom_components/comelit/frontend/comelit-card.js
```

There is no second intercom UI.

## Runtime model

```text
Telegram WebView
  -> Telegram initData
  -> Comelit Mini App gateway
       -> validates Telegram identity
       -> keeps HA Long-Lived Access Token server-side
       -> exposes a narrow hass-compatible adapter surface
  -> shared comelit-card.js
       -> states / registry
       -> exactly one button.press per explicit Door/Gate click
       -> camera viewer through gateway proxy
  -> Home Assistant
  -> custom_components/comelit
```

The browser never receives the Home Assistant Long-Lived Access Token, Telegram bot token, or Comelit credentials.

## Configuration

Copy the variable names from `.env.example` into the deployment secret store. Never commit real values.

Required:

- `COMELIT_MINIAPP_TELEGRAM_BOT_TOKEN`
- `COMELIT_MINIAPP_ALLOWED_USER_IDS` — comma-separated Telegram numeric user ids
- `COMELIT_MINIAPP_SESSION_SECRET` — at least 32 bytes
- `COMELIT_MINIAPP_HA_BASE_URL` — Home Assistant base URL reachable from the gateway
- `COMELIT_MINIAPP_HA_TOKEN` — Home Assistant Long-Lived Access Token, server-side only

Optional:

- `COMELIT_MINIAPP_SURVEILLANCE_ENTITIES` — explicit comma-separated `camera.*` allowlist for the surveillance tab
- `COMELIT_MINIAPP_AUTH_MAX_AGE_SECONDS` — default 300
- `COMELIT_MINIAPP_SESSION_TTL_SECONDS` — default 900
- `COMELIT_MINIAPP_FUTURE_SKEW_SECONDS` — default 30
- `COMELIT_MINIAPP_COOKIE_SECURE` — default true
- `COMELIT_MINIAPP_COOKIE_SAMESITE` — default lax

The surveillance surface is explicit allowlist only. The gateway does not expose all Home Assistant cameras.

## Local checks

From the repository root:

```bash
python -m venv .venv-miniapp
. .venv-miniapp/bin/activate
pip install -r miniapp/requirements-dev.txt
cd miniapp
PYTHONPATH=. pytest -q
python -m compileall -q app tests
node --check app/static/miniapp.js
node --check ../custom_components/comelit/frontend/comelit-card.js
```

The Docker build context is the repository root:

```bash
docker build -f miniapp/Dockerfile .
```

## Safety invariants

- Telegram `initDataUnsafe` is never trusted.
- The HA token is never serialized into browser responses.
- Only stable Comelit Door unique IDs are accepted for Mini App Door actions.
- One explicit UI click maps to exactly one Home Assistant `button.press`.
- The gateway never retries Door actions.
- Service success is not represented as proof of physical opening.
- Camera access is limited to the Comelit entrance camera plus the explicit surveillance allowlist.
- Mini App development does not require CT120 or direct Comelit protocol access.
