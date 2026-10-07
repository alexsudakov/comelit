# COMELIT-RESEARCH-STAGE7-LIVE-LANE-V2 результат

## Что изменено

Изменения сделаны только в `safety-poc/research/media/v1/**` и `safety-poc/tests/**`.
`custom_components/comelit/**` не изменялся, live-запуск против Comelit не выполнялся, POST на
`api.comelitgroup.com` не выполнялся.

- `entrance_research_stage_interlock_transform.py`: stage 6 стал resumable pause gate через
  research-only FIFO control channel. Stage 7 больше не является native stage и не генерируется как
  `research_enter_hold(7, ...)`.
- `research_stage_stub_helper.c`: host fixture получил тот же stage-6 gate contract для offline tests.
- `research_pausable_p2p_runner.py`: добавлен runner-owned stage-7 state machine, hard guards,
  live preflight, temp secret-file lifecycle и injected offline P2P transport `fixture://p2p`.
- `research_stage_interlock_generator.py`: добавлен research-only entrypoint для CT120 builder;
  принимает `--source`, `--output`, терпит `--include-p116` / `--no-include-p116`, всегда генерирует
  research variant и отказывается писать в `custom_components/comelit/native/**`.
- `listener_readonly_observer.py`: заменен JSON-only snapshot reader на standalone read-only log
  observer с честной capability model.
- `test_research_pausable_p2p_harness.py`: обновлен offline safety suite для stage-6 gate, runner
  stage 7, guards, live preflight, observer fixtures и production unchanged checks.

## Stage-6 Gate Contract

`STAGE6_RESUMABLE_GATE=PASS`

Native helper после `RESEARCH_STAGE_6_LOCAL_OFFER_READY` печатает:

- `RESEARCH_STAGE_6_PAUSE_ENTERED=true`
- `RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE|ABORT|TIMEOUT|SIGTERM|CHANNEL_LOST`

Gate reachable только при `RESEARCH_STOP_AFTER_STAGE` set. Для `RESEARCH_STOP_AFTER_STAGE=6`
семантика остается stop/abort/teardown. Для `RESEARCH_STOP_AFTER_STAGE=7` helper остается paused,
пока runner не сделает stage-7 cloud boundary и не отправит `ABORT`. Default/off path не использует
gate: `research=False` generation byte-identical production generation.

Fail-closed cases покрыты offline tests: timeout, SIGTERM, channel loss, no busy loop, no retries,
bounded wait, cleanup markers.

## Stage-7 State Machine

Stage 7 теперь runner-owned:

```text
STATE_IDLE
STATE_LOCAL_OFFER_READY
STATE_CLOUD_P2P_ALLOCATED
STATE_REMOTE_SDP_AVAILABLE_NOT_APPLIED
STATE_ABORTING
STATE_CLEANED
```

Live-mode flow for `--stop-after-stage 7`:

1. runner ждет `RESEARCH_STAGE_6_LOCAL_OFFER_READY` и `RESEARCH_STAGE_6_PAUSE_ENTERED=true`;
2. проверяет, что helper paused;
3. читает local offer из path, заданного CLI/env;
4. делает ровно один P2P start call через live/injected transport;
5. валидирует remote SDP по `ice-ufrag`, `ice-pwd`, `candidate`;
6. хранит remote SDP только в памяти;
7. не пишет remote SDP file;
8. не отправляет `CONTINUE`;
9. печатает:

```text
RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED=true
RESEARCH_STAGE_7_REMOTE_SDP_BUFFERED=true
RESEARCH_STAGE_7_REMOTE_SDP_APPLIED=false
```

10. входит в bounded hold;
11. отправляет `ABORT`;
12. выполняет cleanup.

`REMOTE_SDP_APPLIED=false` является control-flow invariant: в stage-7 path нет write/apply path к
watched remote SDP file; появление файла считается `REMOTE_SDP_APPLY_GUARD`.

## Guard Table

| guard marker | status |
|---|---|
| `REMOTE_SDP_APPLY_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `HELPER_RESUME_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `ICE_CONNECTED_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `PSEUDOTCP_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `CTPP_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `SELF_ACTIVATION_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `RTPC_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |
| `RTP_GUARD` | fatal `FORBIDDEN_STAGE_CROSSING`, tested |

## Live CLI Contract

Live path authored only; it was not run against Comelit.

Default:

```text
NETWORK_IO_TO_COMELIT=0
COMELIT_NETWORK_DISABLED=1
```

Live requires explicit `--live-stage-test` and all gates:

- `--stop-after-stage 7`;
- `--expected-sha256` exactly matches research binary;
- binary SHA is not equal to shipped production pin
  `83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a`;
- credential file exists and is not placeholder shape;
- `--verify-musl-marker`;
- bounded hold;
- `--retry-count 0`;
- `--max-p2p-start-calls 1`.

`MAX_P2P_START_CALLS=1`; configuration allowing a second call fails closed.

## Secret Handling

`SECRET_SOURCE_DESIGN=MODE_600_TEMP_FILE_PATH_ONLY`
`SECRET_CLEANUP=PASS`

VIP token is never passed through argv, stdout, stderr, artifact logs, or env dumps. The runner
creates a mode-600 temporary secret file immediately before a live-stage run, passes only the file
path to the helper, and removes the file in cleanup. Offline tests use fixture credentials only.

## CT120 Build Command

The wrapper to run on CT120:

```bash
REPO=<research clone on CT120> \
P80_BUILD_TRANSFORM=safety-poc/research/media/v1/research_stage_interlock_generator.py \
OUTPUT=<distinct research path> \
P80_BUILD_EXPECTED_SHA=1a7e617a6e8a7d41f9b37b8bc1d271a2e7aebc6f \
P80_BUILD_ALLOW_DETACHED=1 \
bash "$REPO/safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh"
```

Hermes/orchestrator will run this; Codex did not SSH and did not build/run the real live binary.

`REAL_MUSL_RESEARCH_BINARY_BUILT=PENDING_ORCHESTRATOR`
`REAL_MUSL_RESEARCH_BINARY_SHA256=PENDING_ORCHESTRATOR`
`SHIPPED_BINARY_UNCHANGED=PENDING_ORCHESTRATOR`

## Observer Capability Matrix

`LISTENER_READY_SOURCE=logs-follow recorder state_changed attributes/native marker`
`LISTENER_READY_OBSERVABLE=true`
`LISTENER_PID_OBSERVABLE=false`
`LISTENER_SOCKET_IDENTITY_OBSERVABLE=false`
`LISTENER_RECOVERY_OBSERVABLE=true`
`CONFLICT_DETECTION_SUFFICIENT=false`

PID/socket identity are reported as `NOT_OBSERVABLE` unless the consumed read-only log content
actually includes those values. On this deployment the missing capability is:

```text
MISSING_CAPABILITY=read-only route exposing listener process pid and socket inode/transport identity
```

The observer derives `OBSERVER_RECONNECT_GENERATION` from observed READY/non-ready recovery cycles,
process restart markers, socket/transport replacement markers when present, and known reconnect log
markers. It does not claim a production `reconnect_count`.

## Test Inventory

Focused offline suite:

```text
python3 -m pytest -q safety-poc/tests/test_research_pausable_p2p_harness.py
34 passed, 3 subtests passed
```

Coverage includes the required 30 areas:

1. stage-6 gate waits for control action;
2. CONTINUE works in fixture lane;
3. ABORT cleanup;
4. timeout cleanup;
5. exactly one fake/injected P2P start in stage-7 mode;
6. remote SDP memory-only;
7. no remote SDP file written;
8. helper not resumed;
9. forbidden resume fails;
10. forbidden remote SDP apply fails;
11. forbidden ICE connected fails;
12. forbidden PseudoTCP fails;
13. forbidden CTPP fails;
14. forbidden activation/RTPC/RTP fail;
15. no live flag means network disabled;
16. placeholder credential plus live flag fails;
17. production binary identity plus live flag fails;
18. research binary identity mismatch fails;
19. second POST configuration fails;
20. SIGTERM cleanup;
21. timeout cleanup;
22. temporary secrets removed;
23. no child processes left;
24. observer distinguishes listener vs research helper;
25. observer detects PID generation change when observable;
26. observer detects socket generation change when observable;
27. production generator disabled path byte-identical;
28. `custom_components/comelit` diff empty;
29. shipped native binary SHA unchanged;
30. full offline/static safety suite passes.

Additional verification:

```text
python3 -m py_compile safety-poc/research/media/v1/research_pausable_p2p_runner.py \
  safety-poc/research/media/v1/listener_readonly_observer.py \
  safety-poc/research/media/v1/research_stage_interlock_generator.py \
  safety-poc/research/media/v1/entrance_research_stage_interlock_transform.py \
  safety-poc/tests/test_research_pausable_p2p_harness.py
```

passed.

Production checks:

```text
git diff --name-only origin/main -- custom_components/comelit
```

returned empty output.

```text
sha256sum custom_components/comelit/native/comelit-media
83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a
```

## Acceptance Block

```text
LIVE_INVOCATIONS=0
NETWORK_IO_TO_COMELIT=0
P2P_START_REAL_CALLS=0
STAGE6_RESUMABLE_GATE=PASS
STAGE7_RUNNER_STATE_MACHINE=PASS
REMOTE_SDP_APPLIED=false
MAX_P2P_START_CALLS=1
SECRET_SOURCE_DESIGN=MODE_600_TEMP_FILE_PATH_ONLY
SECRET_CLEANUP=PASS
LISTENER_READY_SOURCE=logs-follow recorder state_changed attributes/native marker
LISTENER_READY_OBSERVABLE=true
LISTENER_PID_OBSERVABLE=false
LISTENER_SOCKET_IDENTITY_OBSERVABLE=false
LISTENER_RECOVERY_OBSERVABLE=true
CONFLICT_DETECTION_SUFFICIENT=false
REAL_MUSL_RESEARCH_BINARY_BUILT=PENDING_ORCHESTRATOR
REAL_MUSL_RESEARCH_BINARY_SHA256=PENDING_ORCHESTRATOR
SHIPPED_BINARY_UNCHANGED=PENDING_ORCHESTRATOR
OFFLINE_TESTS=PASS
CUSTOM_COMPONENTS_COMELIT_DIFF=EMPTY
```
