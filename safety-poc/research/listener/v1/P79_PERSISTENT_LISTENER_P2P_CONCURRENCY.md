# COMELIT-P79 Persistent Listener P2P Concurrency

```
TASK_ID=COMELIT-P79-PERSISTENT-LISTENER-P2P-CONCURRENCY-RESEARCH
BASE_MAIN_SHA=9a931c96ab04cc5e489e4c539b98d3b8c699d957
EXECUTION_MODE=OFFLINE_IMPLEMENTATION_ONLY
LIVE_EXECUTION_AUTHORIZED=false
EXECUTION_AGENT=CODEX
```

## Резюме Phase-1 Evidence

Run A принят как основание дизайна. Исторических доказательств успешной параллельной работы production listener и отдельного `p2p/start` нет: `HISTORICAL_CONCURRENT_SUCCESS_EVIDENCE=NONE`. Поэтому `P79_LIVE_NECESSARY=true`, но этот run только добавляет offline-артефакты и не пересекает live boundary.

| Поле | Смысл для P79 | Ограничение |
| --- | --- | --- |
| `supervisor_running` | supervisor task в HA жив | `false` означает потерю listener stability |
| `running` | native listener runtime жив | `false` означает listener stopped |
| `listener_ready` | listener достиг ready-состояния | временный `false` при `running=true` и `supervisor_running=true` записывается как READY loss, но не как stop |
| `reconnect_count` | счетчик завершенных runtime cycles | изменение доказывает, что цикл закончился, но не доказывает причину |
| `last_native_exit_code` | последний native process rc | диагностический маркер, сам не классифицирует P79 |
| `last_native_failure_markers` | sanitized tail native markers | P79 хранит только count/hash, не payload |

`reconnect_count` увеличивается в supervisor при завершении runtime cycle перед новой попыткой запуска. Для P79 это наблюдение о факте цикла, а не доказательство cloud-causality.

`last_native_failure_markers` хранит только safe marker tail из runtime. P79 не печатает raw SDP, credential material или application payload; launcher публикует только количество и SHA-256 summary.

Native exit-code table:

| rc | Семантика |
| --- | --- |
| `0` | native quit после нормального завершения; для P79 PASS возможен только если cloud outcome соответствует A |
| `6` | штатная quit-path в native при закрытии после открытия; включая designed PseudoTCP-close-after-open rc=6 с C comment о контролируемом завершении |
| другое | диагностический отказ native path; для P79 не является отрицательным доказательством concurrency без cloud/listener correlation |

P78 timing-correlation classification остается `PARTIAL / NOT_PROVEN causality`: совпадение timeout и listener reconnect не доказывает причинность. P79 поэтому разделяет cloud outcome, listener observation и reconnect association.

CT120 artifact gaps из Run A:

- установленный `/usr/local/sbin/comelit-p2p-cloud-probe` должен быть pinned на CT120 root перед live run;
- `P79_REVIEW_COMMIT_SHA` должен быть непустым и совпадать с reviewed main;
- sentinel `/root/.comelit-p79-live-consumed` должен отсутствовать перед единственным запуском;
- HA local webhook должен отвечать на `STATUS_ONLY` запросы.

## Design

`custom_components/comelit/cloud.py` показывает, что `async_negotiate_p2p` делает один HTTPS обмен с `https://api.comelitgroup.com/servicerest/p2p/start`. Внутри этой функции нет built-in retry; 401 сохраняется как HTTP boundary для внешнего runtime logic. P79 launcher запрещает retry wrapper и 401-auto-retry branch.

Native `v1_5_7` используется только как источник offer-gather semantics: локальный ICE offer создается, но remote SDP не передается в helper-watched production path. `v4_2` wrapper уже имеет early-exit структуру с `ICE_CONNECTIVITY_SKIPPED=true`; P79 выводит эту структуру вперед и прекращает sequence сразу после cloud result.

Run directory rule: P79 всегда работает в отдельном scratch root `RUN_ROOT` и derived `P79_NATIVE_RUN_DIR`. Он никогда не пишет в production listener watched paths `/run/comelit-p2p`.

## Classification Contract

- A) P2P_RESULT=SUCCESS, REMOTE_SDP_PRESENT=true, listener remained running, reconnect_count unchanged, listener returned/stayed READY => P79_CLOUD_CONCURRENCY=PROVEN
- B) SUCCESS + REMOTE_SDP_PRESENT=true, but reconnect_count increases or READY is lost => P79_CLOUD_CONCURRENCY=PARTIAL, P79_LISTENER_STABILITY=NOT_PROVEN
- C) P2P_RESULT=TIMEOUT, reconnect_count unchanged => P79_CLOUD_CONCURRENCY=INCONCLUSIVE_TRANSIENT_TIMEOUT
- D) P2P_RESULT=TIMEOUT, reconnect_count increases => P79_CLOUD_CONCURRENCY=INCONCLUSIVE, P79_TIMEOUT_RECONNECT_ASSOCIATION=OBSERVED, causality NOT_PROVEN
- E) preflight failure => sentinel unconsumed, no runtime P2P request

Rules: A TIMEOUT is NOT a negative concurrency proof; temporary listener_ready=false is not "listener stopped" while running=true and supervisor_running=true; reconnect_count change proves a runtime cycle ended, not why; PASS process rc is 0 ONLY for classification A; UNKNOWN/FAIL/BLOCKED (and PARTIAL/INCONCLUSIVE per Steering) => non-zero process rc.

P79_RUN_RESULT/process-rc mapping:

| Classification | `P79_RUN_RESULT` | process rc |
| --- | --- | --- |
| A | `PASS` | `0` |
| B | `PARTIAL` | `1` |
| C | `INCONCLUSIVE_TRANSIENT_TIMEOUT` | `1` |
| D | `INCONCLUSIVE` | `1` |
| FAIL | `FAIL` | `1` |
| UNKNOWN | `UNKNOWN_OUTCOME` | `1` |
| BLOCKED | `BLOCKED` | `2` |

## Markers

Required terminal/safety markers:

- `P79_SENTINEL_PREEXISTING`
- `P79_SENTINEL_CONSUMED`
- `P79_LIVE_INVOCATION_LIMIT=1`
- `P79_WRAPPER_INVOCATIONS=<0|1>`
- `AUTOMATIC_RETRY=false`
- `P79_AUTO_RETRY=false`
- `P79_INSTALLED_WRAPPER_SHA_GATE`
- `P79_P2P_HTTP_STATUS`
- `P79_P2P_RESULT`
- `REMOTE_SDP_PRESENT`
- `P79_RECONNECT_COUNT_BEFORE`
- `P79_RECONNECT_COUNT_AFTER`
- `P79_LISTENER_READY_BEFORE`
- `P79_LISTENER_READY_AFTER`
- `P79_CLOUD_CONCURRENCY`
- `P79_LISTENER_STABILITY`
- `P79_TIMEOUT_RECONNECT_ASSOCIATION`
- `P79_RUN_RESULT`
- `ICE_CONNECTIVITY_SKIPPED=true`
- `PSEUDOTCP_SKIPPED=true`
- `CTPP_APPLICATION_SIGNALING_SKIPPED=true`
- `DOOR_ACTION_SENT=false`
- `SELF_ACTIVATION_SENT=false`
- `MEDIA_SIGNALING_SENT=false`
- `RAW_SDP_EMITTED=false`
- `RAW_PAYLOAD_EMITTED=false`

Stage markers are parsed from actual logs with `NOT_REACHED` fallback. `P79_RUN_RESULT` and `P79_CLOUD_CONCURRENCY` are emitted only from classifier output.

## Listener Observation

`P79_LISTENER_CONTROL_MODE=STATUS_ONLY`. Launcher uses only:

```
curl -sS -X POST -d '{"action":"status"}' http://127.0.0.1:<port>/api/webhook/comelit-ha-ring-test-control-v1
```

It never sends `action=start`, `action=stop` or `action=restart`. Samples are collected at preflight, immediately before live, immediately after result and during a bounded post-result window of `POST_RESULT_OBSERVATION_SECONDS<=30`.

Each sample records `supervisor_running`, `running`, `listener_ready`, `reconnect_count`, `last_native_exit_code` and sanitized native marker summary count/hash.

## Review Pin Semantics

`P79_REVIEW_COMMIT_SHA` is intentionally empty by default. Empty or mismatched value fails closed before sentinel creation and before live boundary. The installed CT120 wrapper pin is also fail-closed: absent or unknown `P79_INSTALLED_WRAPPER_SHA256` produces `P79_INSTALLED_WRAPPER_SHA_GATE=ABSENT|UNKNOWN|MISMATCH` and `P79_RUN_RESULT=BLOCKED`.

## P78 Infra Lessons

P78 оставил два инфраструктурных дефекта, которые P79 закрывает явно:

- P78 defect: repository launcher file был tracked как `100644`, не executable; первый shell attempt завершился `RC=126` до любой live invocation. P79 fix: launcher tracked `100755` (`git ls-files -s` verified by Hermes at commit) и статический тест `test_executable_bash_launcher`.
- P78 defect: terminal `P78_RUN_RESULT=UNKNOWN_OUTCOME` был напечатан при exit rc `0` launcher process. P79 fix: terminal classification выпускает только `p79_cloud_concurrency_classifier.py`; process rc равен `0` только для classification A (`PASS`); `PARTIAL` / `INCONCLUSIVE_*` / `FAIL` / `UNKNOWN_OUTCOME` => `1`, `BLOCKED` => `2`; каждая branch завершается явным `exit`, без implicit fall-off `0`.

Live-prep на CT120 перед authorized live run:

- оператор инспектирует установленный `/usr/local/sbin/comelit-p2p-cloud-probe` до запуска;
- проверяются derivation anchors: `RUN="/run/comelit-p2p"` ровно один раз и `echo "=== WAIT SAME NICEAGENT / ICE ==="`;
- записывается marker vocabulary: `P2P_HTTP_STATUS` / `P2P_RESULT` / `P2P_CLOUD_NEGOTIATION` / `REMOTE_SDP_PRESENT`;
- absent anchors => launcher fails closed (`P79_CLOUD_ONLY_WRAPPER_DERIVATION=FAIL`, `P79_RUN_RESULT=BLOCKED`);
- marker vocabulary определяет, ведет ли classification A explicit `P2P_RESULT` marker или Corrective-1 fallback `wrapper_rc==0` + `REMOTE_SDP_PRESENT=true`.

P79 также сохраняет atomic `O_CREAT|O_EXCL` sentinel creation непосредственно перед единственным wrapper call и никогда не references/modifies P78 one-shot sentinel.

## Test Inventory

- `tests.test_p79_cloud_concurrency_classifier` covers A/B/C/D, FAIL, UNKNOWN, BLOCKED, rc mapping and marker sanitization.
- `tests.test_p79_launcher_static_contract` covers status-only observation, exactly one wrapper call, no retry, sentinel ordering, executable bit, bounded observation, scratch-only cloud exit, forbidden raw outputs and P78 sentinel isolation.
- Existing P78 targeted regression tests remain unchanged.

## Verification Runbook

Offline verification commands:

```
bash -n safety-poc/research/listener/v1/ct120_run_p79_cloud_concurrency_probe.sh
python3 -m py_compile safety-poc/research/listener/v1/p79_cloud_concurrency_classifier.py safety-poc/tests/test_p79_cloud_concurrency_classifier.py safety-poc/tests/test_p79_launcher_static_contract.py
cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_p79_cloud_concurrency_classifier tests.test_p79_launcher_static_contract -v
cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_p78_launcher_static_contract tests.test_p78_capture_verifier tests.test_p78_rtpc_media_live_stage_transform tests.test_p78_wrapper_profile_scope
cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
git diff --check
git status --short
ls -l safety-poc/research/listener/v1/ct120_run_p79_cloud_concurrency_probe.sh
```
