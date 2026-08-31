# Transport readiness and Home Assistant contract

## Readiness lineage

The repository historically separated three proof levels: `REPOSITORY_READY`, `READONLY_TRANSPORT_READY`, and `LIVE_TEST_READY`. Those gates were intentionally independent. P12 read-only success did not authorize actuation, and P13 physical validation did not create a reusable operator surface.

P13 is now completed and merged. Its production runtime is immutable/readiness-only; historical physical-validation gates remain consumed. P14 consumes the proven P13 one-shot boundary without reopening those validation gates.

## P13 invariants inherited by P14

P14 may not weaken: `SEND_ARMED` persisted before irreversible transport; one operation ID at most one transport invocation; attempt number 1 only; no automatic retry; post-SEND_ARMED uncertainty terminal UNKNOWN_OUTCOME; duplicate IDs never resend; protocol ACK does not prove physical relay movement; physical-effect assertion true is forbidden.

## Production Home Assistant action

Canonical action `comelit.open_door` targets `button.comelit_main_entrance_open_door` with mandatory `operation_id = p13-hermes-<uuid4>`. No target fingerprint, CT120 command, payload, runner path, approval token or retry setting is caller-controlled.

The integration registers a response-required platform entity service (`SupportsResponse.ONLY`). `button.press` is explicitly disabled. A caller must request and inspect the structured result rather than treating generic service completion as physical Door-open proof.

Trusted responses expose only execution/protocol state: `ACKED` (protocol acknowledgement only), `FAILED_SAFE` (durable evidence operation did not cross send boundary), or `UNKNOWN_OUTCOME` (physical result unknown and resend forbidden). Every result carries `retry_allowed=false`, `physical_effect_asserted=false`, and `physical_door_state=UNKNOWN`.

## CT120 P14 bridge

Home Assistant reaches a private CT120 bridge over HMAC-SHA256 authenticated HTTP. The exact request body contains only operation ID. Timestamp and durable nonce replay protection are validated before execution. HTTP 200 responses are HMAC-signed and version-bound.

The bridge launches only the root-owned hash-pinned P14 production runner. It does not inherit the P14 shared secret into the actuation child. In-process and cross-process locks prevent concurrent launches, and timeout terminates the child process group before journal recovery.

The production runner binds to final immutable P13 release and exact holder/wrapper/payload/target identities. It verifies historical physical-validation gates remain consumed and retired. It creates the static P13 approval value locally only after those checks; that value is never part of the HA/HTTP contract.

## Deployment boundary

Installation is fail-closed: `COMELIT_P14_BIND_HOST=127.0.0.1` and `COMELIT_P14_LIVE_ENABLED=false`. Installing/upgrading P14 performs no Door POST and no runner invocation.

Reusable live service requires a separate explicit capability-enable action plus CT120 private IPv4 and Home Assistant client IPv4. The P14 nftables allowlist is activated and made a systemd predecessor of the bridge before private/live bind is enabled.

Safe disable always returns the bridge to loopback/disabled and removes the dedicated firewall surface without any Door request.

See `P14_HOME_ASSISTANT_ONE_SHOT_SERVICE.md` for exact production/deploy/rollback contract.
