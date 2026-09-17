# P116 / R30F — packaged helper bounded live contract

TASK_ID=`COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE`

Status: **LIVE AUTHORIZED BY USER ON 2026-09-17 / BOUNDED CAMERA-ONLY**

## 1. Goal

Validate the accepted R30E packaged helper in the real Home Assistant / physical entrance-camera path while preserving listener availability and excluding Door/Gate side effects.

The current implemented consumer path is Home Assistant Stream over the local RTP/SDP handoff. No repository evidence for a go2rtc integration exists in current main; R30F therefore tests the current path first and does not install or configure go2rtc or Frigate.

## 2. Canonical inputs

Use fresh `origin/main` as source of truth. Expected accepted R30E artifact unless superseded by a newer accepted main:

```text
CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
PACKAGED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
ARTIFACT_PROVENANCE_READY=true
```

Canonical evidence:

```text
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
safety-poc/research/media/v1/P116_R30E_CI_FINALIZATION.md
safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md
```

## 3. Authorization and safety boundary

Authorized:

- work only on the single Comelit HA integration;
- read-only HA state/log/process/socket diagnostics;
- backup current installed Comelit integration before deploy;
- deploy exact current-main `custom_components/comelit/**` once;
- at most one Comelit integration reload if required to activate files;
- at most 10 entrance-camera media-session attempts;
- existing camera/media activation path only;
- HA Stream consumer request for bounded verification;
- temporary media/stream verification under `/tmp`, discarded before completion;
- CT120 read/build evidence as needed, without changing protocol source.

Not authorized:

- whole Home Assistant restart/reboot;
- Door action;
- Gate action;
- unrelated integration changes;
- go2rtc/Frigate install or configuration;
- external architecture changes;
- protocol refresh/repeat experiments outside existing production behavior;
- persistent packet/media capture or committing raw media;
- credential/account changes.

If a whole HA restart is required for activation or rollback, stop with `BLOCKED_HA_RESTART_REQUIRED` and request separate authorization.

## 4. Preflight

Before any write/live action record:

1. fresh main SHA;
2. repository packaged native SHA and transport pin;
3. installed HA Comelit tree/native SHA and transport pin;
4. listener health and media state;
5. relevant entrance-camera/session entity state and availability;
6. current media hard limit, which must be <=600 seconds;
7. rollback backup of installed `custom_components/comelit/**` plus SHA manifest.

Preflight must fail closed if listener is not healthy before intervention.

## 5. Deploy

Deployment is one-shot and integration-scoped:

- copy only exact-main `custom_components/comelit/**`;
- verify deployed native SHA and transport pin before activation;
- do not copy research/docs/tests;
- perform only an integration reload if needed and supported;
- never restart HA;
- require listener ready + media inactive before first attempt.

On activation failure, rollback to the preflight backup if possible without a full HA restart. Do not continue live attempts with an uncertain installed state.

## 6. Live attempt budget

`MAX_LIVE_ATTEMPTS=10`.

Each attempt must have a named hypothesis/check. Identical blind retries are forbidden.

### Attempt 1 — upstream/helper regression boundary

Purpose: determine whether the accepted R30D/R30E helper still exhibits the historical ~35–36 second media stop.

- Start one camera media session using the existing Comelit integration.
- No HA Stream consumer is intentionally added for the baseline.
- Observe scalar protocol/media markers only.
- Observe for up to 90 seconds. If media remains healthy past 60 seconds, deliberately stop rather than waiting for the 600-second hard limit.
- Record activation latency, media duration, helper status/exit reason, video/audio counts, first/last timestamps/monotonic times when exposed, PT set, SSRC count/change, seq gaps/duplicates/out-of-order, SPS/PPS/FU-A/single-NAL counters and forwarding markers.
- Require listener restoration after teardown.

`HISTORICAL_36S_BOUNDARY_SURPASSED=true` requires objective media evidence beyond 60 seconds or until deliberate teardown after that point. `media_active=true` alone is insufficient.

If media again stops near the historical boundary, do not spend attempts on blind repetition; Codex must diagnose the teardown/control evidence before choosing another attempt.

### Attempt 2 — HA Stream consumer

Run if Attempt 1 proves a healthy upstream/helper path, or if Codex states a concrete diagnostic reason.

- Start a fresh bounded camera session.
- Invoke normal HA Stream/camera consumer behavior.
- Observe whether HA/FFmpeg/PyAV binds/consumes the local RTP/SDP path without raw payload capture.
- A temporary output under `/tmp` may be inspected by size/ffprobe/codec metadata and then removed.
- Record HA stream-worker error/result, socket ownership if observable, timing relative to first/last RTP, and codec/stream metadata for any produced output.

`HA_STREAM_CONSUMER_PROVEN=true` requires objective successful consumer evidence, such as a non-empty valid stream/snapshot artifact or equivalent successful HA stream state. Helper RTP activity alone is not enough.

### Attempts 3–10 — adaptive only

Allowed only for a specific evidence-backed hypothesis derived from earlier attempts. Before each such attempt, record:

```text
ATTEMPT_N_HYPOTHESIS=<specific hypothesis>
ATTEMPT_N_DISTINGUISHING_EVIDENCE=<what result changes the conclusion>
```

Stop early when end-to-end success is proven, a deterministic blocker is localized, listener restoration fails, or the next useful experiment needs new permission/architecture/restart scope.

## 7. Mandatory post-attempt invariant

After every attempt:

```text
media inactive
camera/session control off/inactive
listener ready/running
Door actions = 0
Gate actions = 0
no persistent new listener/reconnect error
```

Only integration-level recovery already authorized by this contract may be used. Whole-HA restart is forbidden.

## 8. Evidence handling

Prefer scalar/status evidence. Never commit or print credentials, raw RTP/H264/audio or private media.

Any temporary stream artifact exists only under `/tmp`, is summarized by safe metadata, and is deleted before task completion.

## 9. Repository write scope

Default write scope for R30F live execution:

```text
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
```

No production code changes are authorized by default.

If live evidence proves an ordinary implementation defect, Codex may identify the exact minimal production files and proposed correction, but Hermes must stop for an explicit write-scope decision before editing them. A new protocol assumption, go2rtc/Frigate change, HA restart or broader architecture always requires a separate decision.

## 10. Result classes

```text
PASS_END_TO_END
  exact R30E helper deployed + upstream/helper healthy + HA Stream consumer objectively succeeds + listener restored

PASS_UPSTREAM_ONLY
  exact helper deployed + upstream RTP survives historical failure boundary + HA Stream remains a separately localized blocker + listener restored

BLOCKED
  deterministic blocker/new permission or architecture boundary

FAIL
  authorized path regresses or cannot be safely restored
```

## 11. Stop boundary

After R30F result, STOP. No automatic production-code correction, go2rtc/Frigate work, Door/Gate work or next live child.
