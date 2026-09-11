# P115 C1 Offline Findings

Scope: offline analysis only. No network request, token refresh, live invocation,
secret read, or production-code edit was performed in this phase.

## HTTP 401 Classification

- OBSERVED: CT120 attempt 1 returned `P2P_HTTP_STATUS=401` from
  `https://api.comelitgroup.com/servicerest/p2p/start` with JSON keys
  `error_code,error_message`; cloud negotiation failed before ICE connectivity.
- OBSERVED: CT120 credential metadata showed
  `OAUTH_ACCESS_TOKEN_TTL_SECONDS=-25109`, so the stored OAuth access token used
  by the harness had expired roughly seven hours before the attempt.
- PROVEN_STATIC: `custom_components/comelit/cloud.py::async_negotiate_p2p`
  builds a POST to the same endpoint, with compact JSON containing
  `deviceUuid`, `data.authMode=user_viper_token`, `data.secret=<vip token>`,
  `data.timeout=10`, `data.sdp=<base64 offer>`, and
  `protocol.name=viper_p2p_v2`, `protocol.version=1`; it sends
  `Authorization: bearer <oauth access token>`, `Content-Type:
  application/json`, and `Accept: application/json`.
- PROVEN_OFFLINE: the legacy v4_2 base probe builds the same request shape in
  `safety-poc/research/ring/v4_2/comelit_cloud_probe.py`, and prints only the
  endpoint/protocol/auth-mode/header-mode metadata before handling the HTTP
  response.
- PROVEN_OFFLINE: the RUN5 bootstrap on the local ref
  `origin/research/p110-final-run5-runner` imports production
  `custom_components/comelit/cloud.py` and calls `async_negotiate_p2p` with the
  same `device_uuid`, `vip_token`, `oauth_access_token`, and transformed offer
  parameters. The P111 runner states the wrapper owns offer, SDP transform,
  OAuth, cloud P2P, and `remote.sdp`, and only replaces the holder with a
  packaged-musl shim.
- PARTIAL: the 401 is best classified as a stale OAuth credential in the CT120
  harness copy. The expired access token is directly observed, and no static
  request-shape difference from the accepted production/RUN5 path was found.
  This phase does not prove that the VIP token was fresh, nor does it prove the
  cloud would have accepted a refreshed OAuth token at attempt time.

## Production Refresh Path

- PROVEN_STATIC: `custom_components/comelit/runtime.py::_async_run_cycle` gets
  an OAuth access token, calls `async_negotiate_p2p`, catches
  `ComelitCloudHttpError`, re-raises all non-401 statuses, then calls
  `self._oauth.async_get_access_token(force_refresh=True)` and retries exactly
  one P2P bootstrap request.
- PROVEN_STATIC: `custom_components/comelit/oauth.py::async_get_access_token`
  uses persisted config-entry data, returns a non-expired access token when
  possible, and otherwise calls `async_refresh_oauth`; it persists the refreshed
  access token, refresh token if returned, expiry, and scope via
  `async_update_entry`.
- PROVEN_STATIC: `async_refresh_oauth` posts one OAuth refresh-token form to
  `https://api.comelitgroup.com/o-auth-2/token` with `grant_type=refresh_token`,
  the app client id, refresh token, and optional persisted scope. It returns
  token material to the caller but contains no `print(` or `_LOGGER` use.
- PARTIAL: the same refresh concept is applicable to the CT120 harness if it is
  performed against the CT120 research credential store before running P115, but
  doing that is a networked credential mutation and was intentionally not done
  in C1.

## Token Refresh Candidate

- PROVEN_STATIC: in the current checkout, the in-repo refresh implementation is
  `custom_components/comelit/oauth.py`. It refreshes OAuth access-token material,
  not `COMELIT_VIP_TOKEN`.
- PROVEN_OFFLINE: the local ref `origin/research/p110-final-run5-runner`
  contains `safety-poc/research/media/v1/p110_run5_bootstrap.py`, which loads
  production `custom_components/comelit/oauth.py` and
  `custom_components/comelit/cloud.py`, refreshes the OAuth access token when a
  refresh token is available, then performs one production-equivalent P2P
  bootstrap. That entrypoint requires network for refresh and P2P bootstrap, and
  asserts no secret values appear in its own output.
- OBSERVED: CT120 has `/usr/local/sbin/comelit-oauth-refresh` pointing to
  `/root/comelit-vip-poc/scripts/comelit_oauth.py refresh`. This path is outside
  the repository and was not read or executed in C1.
- NOT_PROVEN: no current-checkout `safety-poc/src/**` or `safety-poc/scripts/**`
  refresh module was found that obtains a fresh `COMELIT_VIP_TOKEN`.

## Attempt 2 Design

Minimal proposal: with explicit owner approval, refresh CT120 research OAuth
credentials before the live attempt, verify status metadata only, then run one
P115 bounded live invocation unchanged.

Command sequence on CT120:

```sh
/usr/local/sbin/comelit-oauth-refresh
/usr/local/sbin/comelit-oauth-status
REPO=/root/comelit-door-diag-repo /root/comelit-door-diag-repo/safety-poc/research/media/v1/p115_bounded_live_runner.sh
```

The refresh command writes the CT120 local credential store
`/root/.config/comelit/secrets.env`. It must never print or log token values:
`COMELIT_VIP_TOKEN`, `COMELIT_OAUTH_ACCESS_TOKEN`,
`COMELIT_OAUTH_REFRESH_TOKEN`, Authorization headers, SDP secrets, or any raw
credential value.

## Verdict

- PARTIAL: attempt 1 failure is best treated as a CT120 research-harness
  credential-state limitation, not a camera/media protocol defect. The media
  protocol was not reached: `MEDIA_PHASE_ACTIVE=false`, no remote SDP, ICE
  connectivity skipped, and zero RTP datagrams.
- NOT_PROVEN: whether the production HA credential path and CT120 harness path
  use identical current token state. HA listener readiness proves the running
  integration was healthy enough to remain connected, but it does not prove the
  harness copy's expired OAuth access token was accepted by `p2p/start`.

## Blocked Items

- Owner decision required to refresh CT120 account credentials.
- Owner decision required before any second live invocation.
- Owner decision required before reading or changing HA gateway/webhook token
  material or production HA config-entry credential values.
