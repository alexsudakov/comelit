# Comelit integration project — consolidated handoff

Prepared: **2026-08-31**

Repository: `alexsudakov/comelit`

Runtime target: **CT120**

Primary CT120 repository: `/root/comelit-git`

Current development branch at the time this handoff was prepared: `feat/p13-one-shot-actuation`

Code HEAD before this documentation-only commit: `55c69fe92fca9e744646d5db216d29ed0847bcae`

Code TREE before this documentation-only commit: `3ba86c10e03a70594d09ad57ecaa85acd0b7182d`

PR: **#3**, open and **draft**.

This file is intended as the first document to read when continuing the Comelit work in a new chat/session. Git, current repository documents and CT120 runtime evidence have higher authority than chat history.

---

## 1. Project objective

The project investigates the owner's Comelit ViP intercom installation and builds a Home Assistant-compatible integration path without bypassing the safety boundary for physical door actuation.

The practical target is:

1. establish an authenticated real Comelit session;
2. read configuration and bind the intended apartment/door target;
3. reproduce the Door/CTPP transaction correctly;
4. prove that one operator request can cause at most one transport attempt;
5. physically validate one real door-opening operation while a human can observe the entrance;
6. only after a proven physical opening, finish the production Home Assistant/operator integration.

Production Home Assistant actuation was deliberately deferred until the real physical PoC is proven.

---

## 2. Research assets and implementation lineage

The investigation produced two important CT120 research/code families before the Git-native safety PoC was consolidated:

- legacy/research client under `/root/comelit-poc/`, including `comelit_client.py`;
- canonical ViP implementation under `/root/comelit-vip-poc/comelit_vip/`, including session, codec and fixture transport components.

Representative pinned research sources used during reconciliation included:

- `/root/comelit-poc/comelit_client.py`;
- `/root/comelit-vip-poc/comelit_vip/vip_codec.py`;
- `/root/comelit-vip-poc/comelit_vip/vip_session.py`;
- `/root/comelit-vip-poc/comelit_vip/fixture_transport.py`.

The canonical project source now lives in Git under `safety-poc/`.

No credentials, private keys, OAuth/ViP tokens, raw secret files or real target identity values are stored in public Git evidence.

Credential-bearing runtime material is kept root-only on CT120 under:

`/root/.config/comelit/`

---

## 3. Early Android/application investigation

The Android Comelit application was investigated as one possible source of account/session/configuration data.

A direct ADB content-provider query against the Comelit provider failed with Android permission enforcement:

`SecurityException: Permission Denial ... requires signature|privileged`

Therefore ordinary ADB shell access could not directly read the protected Comelit Cloud provider.

This route was not used as the final production transport path.

The project instead moved toward reproducing the working Comelit cloud/P2P/ViP session path on CT120.

---

## 4. Real transport architecture that was proven

The working direction for the real installation is:

`cloud signaling -> ICE -> PseudoTCP -> ViP -> application/session channels`

Direct LAN/public TCP was **not** established as the primary architecture for the intercom control path.

The P12 live work proved that the actual Comelit installation can be reached through this cloud/P2P path and that an authenticated ViP session can be established and cleanly torn down.

---

## 5. What was proven on the real Comelit system — P12 read-only

A preserved real P12 run was completed on CT120:

- run timestamp: `20260830T113020Z`;
- service log: `/root/comelit-p12-readonly-live-service/20260830T113020Z.log`;
- preserved UCFG: `/run/comelit-p2p/p12-ucfg-response.json`;
- UCFG SHA256: `d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7`;
- target-v2 report: `/root/comelit-p12-readonly-live/20260830T113020Z.target-v2.txt`.

The live read-only session proved:

- real P2P/ICE/PseudoTCP/ViP connection: **PASS**;
- exactly one live wrapper/process invocation;
- no automatic retry;
- UAUT authentication: **PASS**;
- `UAUT_RESPONSE_CODE=200`;
- UAUT close: **PASS**;
- UCFG channel open: **PASS**;
- real UCFG received: **true**;
- UCFG close: **PASS**;
- complete read-only transaction: **PASS**;
- authentication/session lifetime: **PASS**;
- timeout mapping: **PASS**;
- credential material emitted: **false**;
- actuator command attempted: **false**;
- physical door action: **false**.

The target was successfully bound using the unique required pair:

- `apt-address`;
- `apt-subaddress`.

Both were present uniquely in the real configuration and the corrected verifier returned:

`TARGET_BINDING_VERIFIED=PASS`

An earlier verifier had incorrectly expected optional `model`/`version` fields; the real UCFG did not contain those fields. That was a verifier defect, not a failure of the real Comelit session. The verifier was corrected so optional context is checked only when present.

### P12 conclusion

**Real authenticated read-only control-plane access to the installed Comelit system works.**

The project can connect, authenticate, read configuration, identify the intended target and close the session safely.

---

## 6. Door/CTPP protocol research and offline reconciliation

The Door operation was reconstructed from the legacy research path and reconciled against the canonical ViP implementation before any real actuation was attempted.

The important proven properties are:

- the Door action uses a CTPP session/channel;
- the transaction contains exactly **six Door data writes** in a fixed order;
- all six Door writes belong to the same CTPP channel;
- CTPP control-plane open/close semantics were reconciled;
- the complete offline transaction is:

  `OPEN_CTPP -> six Door writes -> CLOSE_CTPP`

- in the canonical fixture model this is exactly **eight fixture writes**: two control-plane writes plus six Door writes;
- legacy framing and canonical `VipSession.send_frame()` were reconciled byte-for-byte using synthetic data;
- the legacy helper already creates the outer ViP framing, so passing an already-framed legacy packet as a canonical body would double-frame it; this was explicitly proven by a negative control.

Repository/runtime gates established:

- `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`;
- `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`;
- `FULL_OFFLINE_DOOR_TRANSACTION=PASS`;
- `REPOSITORY_READY=true` for the validated trees.

These proofs established the wire/control shape without repeatedly actuating the real system.

---

## 7. One-shot safety model implemented for P13

The real Door path is guarded by a typed one-shot state machine.

Core states/semantics:

`PREPARED -> SEND_ARMED -> SENT -> ACKED/UNKNOWN_OUTCOME`

Key rules:

1. `SEND_ARMED` is the irreversible ambiguity boundary.
2. `SEND_ARMED` is durably persisted before the single transport call.
3. One `operation_id` can cause at most one transport invocation.
4. `attempt_number=1` only.
5. Duplicate `operation_id` never sends again.
6. There is no automatic retry.
7. A pre-arm failure may become `FAILED_SAFE` only when no send can be proven.
8. Any uncertainty after `SEND_ARMED` becomes terminal `UNKNOWN_OUTCOME`.
9. Protocol ACK never proves that the physical relay moved.
10. `physical_effect_asserted=true` is forbidden.
11. Fault/retry tests use fixture/mock transports only, never repeated physical sends.

The project includes persistence/idempotency, audit, crash recovery and rate-limit coverage around this boundary.

---

## 8. First real physical P13 transport attempt

One explicitly approved real physical attempt was executed on 2026-08-31.

Operation:

`p13-hermes-2277aa0d-d047-4fe1-9dc8-df12d0405b8e`

Live-test source identity:

- HEAD `18eb81c9d27597a66e74df77389df5477cf321fc`;
- TREE `31c20fb55aff3fc5e224f0193966b56f1d2bc366`.

Observed protocol/runtime result:

- exactly one audited transport attempt: **yes**;
- exactly one audited transport outcome: **yes**;
- `attempt_number=1`: **yes**;
- `SEND_ARMED`: reached;
- CTPP transaction emitted: **yes**;
- CTPP open: **OPENED**;
- Door writes: **6**;
- CTPP close: **PASS**;
- teardown: **PASS**;
- Door-specific ACK: **not proven**;
- automatic retry: **did not occur**;
- duplicate transmission evidence: **not observed**.

State transition:

`PREPARED -> SEND_ARMED -> SENT -> UNKNOWN_OUTCOME`

Protocol classification:

`UNKNOWN_OUTCOME`

Reason:

`Door-specific acknowledgement unproven`

The operator could not physically observe the entrance during this attempt:

`P13_PHYSICAL_OBSERVATION=UNAVAILABLE`

Therefore the project **must not claim that the door opened**, even though the real session reached CTPP open, emitted six Door writes and closed cleanly.

The previous operation is terminal and must **never** be retried or reused.

Frozen public-safe evidence:

- branch: `evidence/p13-one-shot-20260831T045246Z`;
- commit: `8566af064031d20c5c36b005d6af4cab190d6b5e`;
- file: `safety-poc/evidence/p13-one-shot-20260831T045246Z.txt`.

---

## 9. What the first physical attempt proved — and what it did not

### Proven

- the real cloud/P2P/ViP session path can be reused for actuation;
- the runtime crossed the irreversible send boundary exactly once;
- real CTPP open was observed;
- the prepared Door transaction reported exactly six writes;
- CTPP close and teardown completed;
- audit/idempotency/no-retry behavior held during the real run;
- no duplicate transmission was observed.

### Not proven

- no Door-specific protocol ACK was established;
- no human physically observed relay/door movement;
- therefore **physical opening remains unproven**.

This distinction is central. A successful transport sequence is not equivalent to a proven physical door opening.

---

## 10. Observed-acceptance path prepared for the next physical validation

Because the first physical attempt had no human observation, a second, separately protected observed-acceptance path was built.

Main components:

- `safety-poc/scripts/p13_hermes_observed_acceptance.sh` — single-use outer live gate;
- `safety-poc/scripts/p13_hermes_observed_acceptance_preflight.sh` — non-actuating readiness check;
- `safety-poc/scripts/p13_hermes_ct120_dispatch.sh` — narrow repository dispatcher;
- `safety-poc/deploy/p13_hermes_ct120_runtime_dispatch.sh` — fixed runtime dispatcher source;
- `safety-poc/scripts/install_p13_hermes_ct120_authority.sh` — narrow CT120 authority installer.

The single-use observed gate durably writes its consumed state **before** entering any live-capable child. It has no reset/remove path. If Hermes accidentally repeats the task, the gate must reject the replay rather than actuate again.

The internal live chain still performs its own non-actuating preflight before reaching `SEND_ARMED`.

---

## 11. Hermes -> CT120 authority investigation and result

Initially Hermes could run only existing read-only CT120 commands and could not invoke the root-only P13 readiness/live wrappers.

A read-only authority inventory proved the actual CT120 access design:

- restricted account: `hermes-comelit`;
- shell: `/bin/bash` but SSH restrictions apply;
- password authentication: disabled;
- TTY: disabled;
- TCP forwarding: disabled;
- agent forwarding: disabled;
- X11 forwarding: disabled;
- sshd effective forced command:

  `/usr/local/sbin/hermes-comelit-dispatch`

Before the P13 authority extension, sudoers allowed only:

- `/usr/local/sbin/comelit-smoke`;
- `/usr/local/sbin/comelit-p2p-readiness`.

The P13 authority change deliberately did **not** add a general root key, general sudo shell, wildcard command prefix, arbitrary path, arbitrary target, caller-selected payload or caller-selected `operation_id`.

The installed extension exposes only two logical operations:

- `comelit-p13-readiness`;
- `comelit-p13-observed-open I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`.

Runtime installation completed on CT120 with:

- `P13_HERMES_AUTHORITY_INSTALL=PASS`;
- `P13_HERMES_AUTHORITY_SSHD_CHANGED=false`;
- `P13_HERMES_AUTHORITY_KEYS_CHANGED=false`;
- `P13_HERMES_AUTHORITY_NETWORK_ACL_CHANGED=false`;
- `P13_HERMES_AUTHORITY_ARBITRARY_SHELL=false`;
- `P13_HERMES_AUTHORITY_ARBITRARY_ROOT=false`;
- `P13_HERMES_AUTHORITY_ALLOWED_READINESS=true`;
- `P13_HERMES_AUTHORITY_ALLOWED_OBSERVED_OPEN=true`;
- `P13_HERMES_AUTHORITY_PHYSICAL_ACTION=false`;
- `P13_HERMES_AUTHORITY_SEND_ARMED=false`;
- `P13_HERMES_AUTHORITY_RUNTIME_READY_FOR_HERMES_PREFLIGHT=true`.

Thus Hermes now has a narrow, reviewed route to the P13 dispatcher without gaining general CT120 root authority.

---

## 12. Current Git/CI/PR state

At the time the runtime authority was installed and before this documentation-only commit:

- branch: `feat/p13-one-shot-actuation`;
- HEAD: `55c69fe92fca9e744646d5db216d29ed0847bcae`;
- TREE: `3ba86c10e03a70594d09ad57ecaa85acd0b7182d`;
- PR: `#3`;
- PR state: **OPEN / DRAFT**;
- `offline-safety` PR run `33371074157`: **PASS**.

The PR must remain draft until the unresolved physical-validation and later production hardening gates are completed.

---

## 13. Exact current physical-test status

A new physical approval phrase was supplied during the 2026-08-31 conversation, but **no new observed-open command was executed** after that approval.

The operator then stated that the entrance could not currently be physically observed and explicitly postponed the test until returning home in the evening.

Therefore:

- no second physical P13 transport attempt has occurred;
- no new `operation_id` has been created for the observed acceptance;
- the observed-acceptance single-use gate should be treated as **unused** unless newer runtime evidence proves otherwise;
- the previously supplied approval must **not** be carried forward as authority for the evening attempt.

When the operator is physically able to observe the entrance, request a **fresh** exact approval:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

Then invoke through Hermes exactly once:

`comelit-p13-observed-open I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

Do not run a second attempt under any condition after the gate is consumed. Timeout, disconnect, partial output or protocol ambiguity must not trigger a resend.

After execution, record the protocol result and the operator observation separately:

- `PHYSICAL_OBSERVATION=OPENED`, or
- `PHYSICAL_OBSERVATION=NOT_OPENED`, or
- `PHYSICAL_OBSERVATION=UNAVAILABLE`.

---

## 14. What still does not work / is not finished

### Physical door result is still unproven

The largest unresolved functional fact is simple: **we do not yet have a physically observed successful door opening**.

The first real transport attempt was `UNKNOWN_OUTCOME` because there was no Door-specific ACK and no human observation.

### Door-specific acknowledgement is not established

The protocol path reports successful CTPP open, six writes, close and teardown, but no Door-specific acknowledgement has been proven.

This does not necessarily mean the command failed; it means the protocol result cannot establish the physical outcome.

### Production Home Assistant actuation is not complete

A production HA operator surface was intentionally deferred until after a proven physical opening.

The current Hermes -> CT120 path is a restricted P13 PoC/acceptance surface, not the final production Home Assistant architecture.

### PR #3 is not ready to merge

PR #3 remains draft. Remaining work includes:

- physically observed acceptance;
- classification/freeze of that evidence;
- Phase G production operator/Home Assistant hardening;
- immutable deployment/rollback for the final tree;
- final CT120 regression/evidence/docs/readiness;
- merge only after unresolved gates are closed.

---

## 15. Home Assistant architecture boundary for the later production stage

For the final smart-home integration, the intended architecture remains:

`Hermes -> trusted dialog-service/action layer -> Home Assistant -> restricted Comelit capability`

Hermes must not receive generic Home Assistant or generic root actuation authority.

The current P13 Hermes -> CT120 dispatcher exists only to finish the tightly controlled physical PoC/acceptance without waiting for the later HA production integration.

After a proven physical opening, return to the production architecture and expose only the narrow door capability through the trusted HA/action boundary.

---

## 16. Adjacent IP-camera investigation (separate from the Comelit Door protocol)

During the same overall home-entry investigation, two ordinary RTSP courtyard cameras were tested in Home Assistant Generic Camera. This is **not** part of the proven Comelit P2P/ViP Door protocol and should be continued separately.

Observed facts:

- both RTSP sources take roughly 1-1.5 minutes to establish in VLC, followed by a few seconds of black video before frames appear;
- `Двор 2` works in Home Assistant;
- `Двор 1` does not work reliably in Home Assistant, although it opens in VLC;
- both Generic Camera entries had the same settings except their RTSP endpoint/port;
- both used TCP, basic auth, 2 FPS, SSL verification off;
- enabling Home Assistant's wallclock timestamp option on `Двор 1` did not fix it;
- temporarily pointing the `Двор 1` HA entity at the working `Двор 2` source produced video, proving the HA entity itself is functional;
- simultaneous VLC + HA playback of `Двор 2` works, disproving a simple one-client RTSP limit hypothesis;
- the camera overlay shows an obviously incorrect 1970 date, indicating bad camera clock metadata, although that alone does not explain why one source works and the other does not.

The camera issue should be continued in a separate dialog, likely by comparing the actual RTSP stream/codec/timestamp behavior or trying a more controllable FFmpeg/ONVIF path.

---

## 17. Files and evidence worth reading first in a continuation

Recommended order:

1. `safety-poc/docs/COMELIT_PROJECT_HANDOFF_2026-08-31.md` — this file.
2. `safety-poc/P13_POC_DIRECT_PATH.md`.
3. `safety-poc/docs/HERMES_COMPLETION_HANDOFF.md`.
4. `safety-poc/HERMES_TASK.md`.
5. `safety-poc/docs/P12_READONLY_TRANSPORT_READINESS.md`.
6. `safety-poc/docs/P13_ONE_SHOT_ACTUATION.md`.
7. `safety-poc/docs/ARCHITECTURE.md`.
8. `safety-poc/docs/CONTROL_PLANE_AND_TRANSACTION.md`.
9. `safety-poc/docs/CTPP_BODY_LAYOUT_RECONCILIATION.md`.
10. frozen P13 evidence branch `evidence/p13-one-shot-20260831T045246Z`.
11. current PR #3 and current branch/CI state.
12. current CT120 runtime state before any new live action.

---

## 18. Immediate next step when continuing Door work

Do **not** repeat P12 and do **not** retry the previous P13 operation.

When the operator is at home and can physically observe the entrance:

1. verify current Git/CT120 identity and that the observed-acceptance gate remains unused;
2. obtain a fresh `I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`;
3. ask Hermes to execute exactly one `comelit-p13-observed-open ...` command through the installed restricted authority path;
4. never retry after the gate is consumed;
5. record operator physical observation separately from protocol classification;
6. freeze public-safe evidence;
7. only after a proven opening, move to Phase G production Home Assistant integration.

---

## 19. Bottom-line project status

### Working / proven

- real cloud/P2P/ICE/PseudoTCP/ViP connectivity;
- real UAUT authentication (`200`);
- real UCFG read and clean channel/session close;
- real target binding using unique apartment address/subaddress fields;
- reconstructed and reconciled CTPP control path;
- fixed six-write Door transaction structure;
- canonical/legacy framing equivalence with synthetic fixtures;
- one-shot state machine, persistence, idempotency, audit and no-retry invariants;
- one real P13 transport attempt reached CTPP open, six Door writes, close and teardown exactly once;
- restricted Hermes -> CT120 P13 authority is installed without general root/shell expansion;
- CI for the current P13 code tree was green before this documentation-only commit.

### Not yet proven / unfinished

- no physically observed successful door opening yet;
- Door-specific ACK is unproven;
- first physical attempt remains terminal `UNKNOWN_OUTCOME` and cannot be retried;
- second observed acceptance has not been executed;
- final production Home Assistant door actuation integration is not finished;
- PR #3 remains draft and must not be merged yet.

The key technical uncertainty is no longer whether the project can establish the real Comelit session or emit the reconstructed Door transaction. It can. The remaining acceptance question is whether that transaction actually causes the intended physical door/relay action on the installed system, which must be verified once while the operator is physically observing the entrance.
