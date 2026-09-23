# P116 R40 — Official-app readiness: offline plan (no live authorization)

Status: **plan only**. `NEXT_LIVE_AUTHORIZED=false`. This document performs no listener action, no capture,
no ring, no Door/Gate action and no device contact. It exists so that a future round does not repeat the R39
sequencing failure, in which the capture window ended 57 s before the only physical ring and the official
app never reached an app-ready state.

## 1. Why R39 failed to produce call evidence

* Capture window `13:56:47Z .. 14:01:05Z`; the ring arrived at `14:02:02.725Z`, after the listener had been
  restored — so the panel called the production listener, not the official app, and the capture contains no
  call control, no media request and no RTP.
* The official Android app did not become usable inside the paused window, so there was nothing to observe
  even if the ring had been inside the window.
* The ring budget is now spent; any further attempt requires a fresh authorization.

## 2. Design rule for the next attempt

`OFFICIAL_APP_READY` is a hard gate that must be proven **before** the ring budget may be spent, and the
pause must be shortened to the smallest window that can contain (app-ready → ring → bounded observation).

Proposed ordered procedure (all steps bounded, stop-gated):

1. Operator opens PCAPdroid and configures a passive capture of the official app (or all phone traffic); no
   TLS interception, no MITM.
2. Orchestrator starts the capture-side bookkeeping and arms the bounded listener failsafe (existing
   autoreset path, continuous-down logic, 300 s budget counted from the actual pause).
3. Orchestrator pauses the production listener (existing mechanism) and confirms the pause on two samples.
4. Operator opens the official app and reports `OFFICIAL_APP_READY` **only** when the app itself shows a
   usable/connected state.
5. If `OFFICIAL_APP_READY` is not reported inside the bounded readiness timeout: restore the listener,
   record `ring_count=0`, keep the ring budget unspent, and end the attempt as `BLOCKED_APP_NOT_READY`
   (this is exactly the case R39 hit — it must not cost a ring).
6. Only after `OFFICIAL_APP_READY`: issue `READY_FOR_ONE_PHYSICAL_RING` and let the operator make exactly one
   ring, inside the paused window.
7. Observe passively for the bounded window (natural end of the call/media, or ~90 s after the ring,
   whichever comes first).
8. Restore the production listener first, verify `listener_ready`, then disarm the failsafe.
9. Only then hand the capture to the offline analysis lane; raw capture never enters git.

Additional budget rules: one ring, one capture, one pause, one resume, no retry, no synthetic ring, no
Door/Gate, `NEXT_LIVE_AUTHORIZED=false` until a new explicit operator authorization.

## 3. Hypotheses to test (both currently UNPROVEN)

**Hypothesis A — server-side/session release latency.** After the HA listener stops, the device/cloud side
may need more than the observed interval to release the session so that the official app can take it over.
R39 evidence is consistent with this but does not prove it: the capture shows the app active on 443/DNS/STUN
with a sustained small-packet UDP keepalive and 8 remote peers, yet no call handling. Cheap check (future,
not executed): measure app-side connectivity repeatedly during the paused window and record how long until
the app reports a usable state; repeat once with a longer pause but **without** spending the ring.

**Hypothesis B — PCAPdroid/VPNService affects official-app connectivity.** A local VPN-based capture can
change routing/MTU behaviour and could delay or break the app's connection setup. Cheap check (future, not
executed): compare the app's connection behaviour with PCAPdroid OFF versus ON, on the same phone and the
same network, while the listener is running (no pause, no ring). Only if that comparison shows a difference
does this hypothesis deserve weight.

Neither hypothesis may be treated as a cause before such a check exists, and neither is a substitute for
proving `OFFICIAL_APP_READY`.

## 4. Evidence standard for the successor round

* The successor round is successful only if the capture contains the official inbound path:
  call setup → capability/alerting → call-bound media request → first RTP, with roles and boundaries
  identified from the capture itself (never from value coincidence).
* Channel identity must be proven by correlation between the media-channel open/control traffic and the
  media request body, not by a single field occurrence.
* `NEW_ICE/NEW_CLOUD/NEW_PSEUDOTCP/NEW_REGISTRATION_AFTER_CALL_INIT` must be answered with `0` or `UNPROVEN`
  — never assumed.
* If the capture again misses the call, the round must close as `INCONCLUSIVE` with `ring_budget` status
  stated explicitly, and with no automatic retry.

## 5. Unchanged prohibitions for the successor round

No candidate execution against the device, no our-helper media OPEN/STOP, no synthetic ring, no Door/Gate,
no deploy, no HA reload/restart, no production source/binary change, no packet TX from research tooling, no
merge. `NEXT_LIVE_AUTHORIZED=false`.
