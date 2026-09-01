# P14 — production Home Assistant one-shot Door service

Status: **IMPLEMENTED / PRODUCTION-READY CODE / DEPLOYMENT EXPLICIT**

P14 exposes the P13-proven one-shot Door boundary through a narrow Home Assistant integration without exposing a generic CT120 shell, caller-controlled target, retry switch, or physical-state claim.

## 1. Canonical architecture

```text
Hermes / dialog-service authorization + confirmation
  -> Home Assistant comelit.open_door (response required)
  -> button.comelit_main_entrance_open_door
  -> custom_components/comelit
  -> HMAC-authenticated private CT120 P14 bridge
  -> transient per-operation systemd service cgroup
  -> root-owned hash-pinned P14 production runner
  -> immutable final P13 release source + runtime artifacts
  -> P13 OneShotExecutor / durable journal / audit
  -> proven Cloud P2P -> ViP -> UAUT -> CTPP -> six-write boundary
```

Forbidden paths remain: Hermes to CT120 shell; Home Assistant to arbitrary CT120 command/target/payload; network request to P13 approval token; `button.press` to Door actuation; bridge retry loops; protocol result to physical Door-state assertion.

## 2. Home Assistant action contract

Public action: `comelit.open_door` on canonical entity `button.comelit_main_entrance_open_door`. The only caller-controlled execution value is `operation_id = p13-hermes-<canonical uuid4>`.

The action is registered with `SupportsResponse.ONLY`. A caller must request and inspect the service response; generic service completion cannot stand in for “the door opened”. Standard `button.press` raises and has no bridge call.

Every trusted bridge result contains operation ID, `state = ACKED | FAILED_SAFE | UNKNOWN_OUTCOME`, reason, runner-invoked flag, `retry_allowed=false`, `physical_effect_asserted=false`, protocol-acknowledged flag, and `physical_door_state=UNKNOWN`. `ACKED` means protocol acknowledgement only; it never proves relay movement.

A transport timeout, connection loss, unreadable response, unsigned/tampered response, or any non-200 HTTP response after the POST has left Home Assistant is treated as an untrusted do-not-retry outcome. Home Assistant never upgrades such a response to proven `FAILED_SAFE` merely because an HTTP status code looks like a pre-execution error.

## 3. Authentication and replay

Endpoint: `POST /v1/open-door`. Exact JSON body contains only `operation_id`.

HMAC-SHA256 binds version, method, path, Unix timestamp, fresh nonce and SHA-256 of the raw body. Timestamp skew defaults to 30 seconds. After HMAC/body validation and before any execution decision, the nonce is durably claimed in SQLite. A repeated nonce is rejected and never automatically retried.

HTTP 200 result bodies are themselves HMAC-signed against the request timestamp/nonce and must carry `X-Comelit-Version: 1`. Only such a verified response is trusted as a bridge result. Home Assistant requires exact safety flags `retry_allowed=false` and `physical_effect_asserted=false`.

Bridge-side 4xx/5xx responses are deliberately not treated by HA as proof of a no-send outcome: once the one-shot POST may have reached the network, an unsigned error cannot authenticate either its source or its position relative to the execution boundary.

## 4. Idempotency, concurrency and process containment

The P13 journal remains authoritative. A previously persisted operation ID is returned without spawning a second actuation child. Live-disabled or bridge-busy pre-send outcomes are persisted terminal `FAILED_SAFE`, so the same operation ID cannot later become a send after configuration changes.

The bridge uses an in-process lock plus root-only `flock` to prevent concurrent launches across threads and bridge processes. Each accepted live operation is then launched through a uniquely named transient `systemd-run --wait --collect --service-type=exec` service with `KillMode=control-group`. This containment is intentionally above P13: the immutable P13 real-session adapter starts its native wrapper with a new POSIX session/process group, but that does not move the wrapper out of the transient systemd cgroup.

Before `systemd-run` is launched, the bridge durably writes a mode-0600 inflight marker binding the exact `operation_id` to the deterministic transient unit name. After a bridge crash/restart, this marker is reconciled before an existing operation is returned or a new actuation child can launch. If the prior unit is still active or its state cannot be proven inactive, execution fails closed and no new child is launched. Once the prior unit is proven inactive, durable P13 residue is normalized before the marker is removed: `PREPARED -> FAILED_SAFE`; `SEND_ARMED/SENT -> UNKNOWN_OUTCOME`.

On a P14 timeout, the bridge first drives the whole transient service cgroup inactive and only then releases its execution locks or reports the journal result. This prevents the native Door transport from continuing after the timeout response merely because it created a separate POSIX process group. Unknown containment state is fail-closed rather than assumed safe.

The transient child environment is explicit/minimal. `COMELIT_P14_SHARED_SECRET`, HMAC values and caller data other than the canonical operation ID are not inherited. The static P13 approval token is created only inside the root-owned production runner after immutable-runtime checks.

## 5. Immutable P13 boundary

P14 does not depend on a mutable P13 git worktree. The root-only runner pins final P13 release `p13-415edb4525e4-50c0a916f73e-b6a10c68773a`, source HEAD `0dace902d2cef1478cddea0f9d4cd36fcddb3837`, tree `415edb4525e46601cd0ef1249fc0965927b1ac29`, and exact proven target/artifact identities.

Before the single P13 Python boundary invocation it verifies the P13 current selector, release checksums, manifest identities, retired observed-open surface, consumed historical/G1B physical-validation gates, absent G1B gate binary, root-owned holder/wrapper/payload, and absence of conflicting native actuation processes.

Only after those checks does the root-only P14 runner create the static P13 approval value locally for the immutable P13 module. That value is never accepted from HA, HTTP or bridge environment. Historical validation gates remain consumed and are not reset or reused.

## 6. Immutable P14 release and rollback

`install_p14_production_release.sh` is non-actuating. It creates immutable releases under `/opt/comelit-door-safety-poc/p14/releases/` plus `current` and `previous` selectors, with exact source archives, `RELEASE.env` and `RELEASE_CONTENT.sha256`.

Install defaults are closed: `COMELIT_P14_BIND_HOST=127.0.0.1` and `COMELIT_P14_LIVE_ENABLED=false`. The installer performs only local `/healthz`, never `/v1/open-door`, never launches the production runner and never crosses `SEND_ARMED`.

The HMAC secret exists only in root-owned mode-0600 `/root/.config/comelit/p14-ha-bridge.env`; deployment tooling never prints it. Before mutating systemd state the installer records whether a prior bridge unit existed and its enabled/active state. A failed install first stops the mutated service, restores environment/runner/selectors/unit, reloads systemd, and then restores the exact prior enabled/active state, including prior unit absence.

## 7. Explicit live promotion

Reusable service is enabled only with `P14_LIVE_ENABLE_APPROVAL=I_APPROVE_P14_ENABLE_REUSABLE_DOOR_SERVICE` and explicit CT120 private IPv4 plus Home Assistant client IPv4. Promotion itself performs no Door request.

Before live state it verifies disabled loopback health, exact P14 release, final P13 readiness/identities, production runner hash/mode/owner and no conflicting action process. A dedicated `inet comelit_p14` nftables allowlist drops TCP/18014 traffic from every non-loopback source except configured HA IPv4. A persistent systemd firewall unit is installed and made a required predecessor of the bridge **before** the bridge leaves loopback and live mode is enabled.

Any promotion failure restores the disabled environment and removes the live firewall surface.

## 8. Safe disable / upgrade

`disable_p14_live.sh` needs no actuation approval. It returns bridge to loopback/disabled, removes firewall dependency/table and verifies disabled health without `/v1/open-door`.

A release upgrade while live is refused: disable first, install/verify the new immutable release, then explicitly promote again.

## 9. Home Assistant installation

`install_p14_ha_component_local.sh --config-dir /config` atomically stages/backups the component and never calls a service. Home Assistant must restart after installation.

Config flow accepts only `http://<private CT120 IPv4>:18014` with secret >=32 bytes. Health must report `live_enabled=true` and `runner_identity=pass` before a config entry is created. The shared secret is transferred through an operator-controlled channel and is never stored in Git or emitted by deploy logs.

## 10. Rollout order

1. Merge exact-head green P14 PR.
2. CT120: `deploy_p14.sh ct120-install` — immutable, loopback, disabled, non-actuating.
3. Run non-actuating CT120 runtime validation of exact release/runner/systemd containment prerequisites.
4. CT120: explicit `ct120-promote` with CT120 private IPv4 and HA client IPv4 — capability enable only, no Door request.
5. Install HA custom component into `/config`, restart HA.
6. Add Comelit integration with private bridge URL and generated shared secret.
7. Verify `button.press` is denied and `comelit.open_door` requires a service response without sending a Door request as part of deployment validation.
8. Only an authorized upstream action creates a fresh operation ID and calls `comelit.open_door`; there is no automatic validation send and no retry after ambiguity.

## 11. Acceptance invariants

`SEND_ARMED` remains the irreversible P13 uncertainty boundary; one operation ID has at most one actuation child/send path; automatic retry is absent at every layer; durable replay protection precedes execution; P14 secret never reaches P13 child; target/payload/runner/approval/retry are not caller-controlled; `UNKNOWN_OUTCOME` remains terminal and visible; `ACKED` remains protocol-only evidence; physical-effect assertion is forbidden; standard button press cannot actuate; each live operation is cgroup-contained across nested POSIX sessions; timeout does not return before containment is proven inactive; crash residue is reconciled before reuse; upgrade begins disabled; failed install restores exact prior service state; firewall precedes private/live bind; safe disable is always available without a Door request.
