# P116 / R30E — задача Hermes/Codex: native helper rebuild + reproducible provenance

Статус: **готово к исполнению после merge этого contract/task PR / OFFLINE BUILD ONLY**

TASK_ID=`COMELIT-P116-R30E-NATIVE-HELPER-REBUILD-PROVENANCE`

Основной контракт:

```text
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_CONTRACT.md
```

Parent evidence:

```text
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
```

## Роли

```text
HERMES_ROLE=ORCHESTRATOR_ONLY
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
COMELIT_NETWORK_TX_ALLOWED=false
HA_ALLOWED=false
HA_DEPLOY_ALLOWED=false
```

Hermes не пишет executable code и не принимает semantic решения за Codex.

Обычные implementation/test defects не являются stop condition: Codex исправляет их в текущем context; если defect найден после завершения invocation, Hermes возвращает его тому же context через corrective pass, если это возможно.

## Bootstrap

Работать только от свежего `origin/main` публичного `alexsudakov/comelit`.

```text
REPOSITORY_PATH=/home/hermes/repos/comelit
SOURCE_OF_TRUTH=origin/main
EXPECTED_MINIMUM_MAIN=0248fb7ac68a944fca1d6814bd102187b44e5601
```

Сначала:

1. `git fetch origin main`;
2. зафиксировать фактический `origin/main` SHA;
3. убедиться, что R30D уже merged и в main присутствуют оба R30E документа;
4. создать отдельную branch/worktree от фактического свежего main;
5. не продолжать R30D worktree;
6. remote оставить credential-free;
7. не выводить token/credential contents;
8. проверить repo-local credential helper согласно проектным правилам до push.

Executor gate:

```text
CODEX_COMMAND_PRESENT=true|false
CODEX_VERSION=<version-or-unavailable>
ACTUAL_EXECUTOR=codex-cli|other|unavailable
```

Если `codex-cli` недоступен:

```text
RESULT=BLOCKED_EXECUTOR_UNAVAILABLE
```

## Что должен прочитать Codex

Передай paths, не пересказывай всю историю P116:

```text
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_CONTRACT.md
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
safety-poc/tests/test_p116_build_provenance_gate.py
safety-poc/tests/test_p107_musl_package_provenance.py
safety-poc/tests/test_p116_provenance_binary_analysis.py
safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
custom_components/comelit/media_transport.py
```

## Compact child contract

```yaml
goal:
  Воспроизводимо пересобрать packaged musl native helper из принятого R30D canonical source и восстановить source->build->binary->transport-pin provenance без live/HA действий.

canonical_source:
  generator: safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
  include_p116: true
  expected_sha256: 1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2

build:
  host: CT120
  builder: safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
  offline_build: true
  cached_rootfs_only: true
  independent_builds: 2
  require_byte_identical: true
  candidate_execution: forbidden

package:
  binary: custom_components/comelit/native/comelit-media
  transport_pin: custom_components/comelit/media_transport.py::MEDIA_NATIVE_BINARY_SHA256

constraints:
  - не менять protocol source/transform/builder
  - не скачивать toolchain/packages
  - никакого Comelit network/live/HA/listener
  - binary и transport pin обновлять только после two-build reproducibility PASS
  - production media_transport.py: только значение MEDIA_NATIVE_BINARY_SHA256
  - provenance tests должны вычислять/связывать реальные digest, а не только сравнивать взаимно подогнанные constants
  - R27 live runner не запускать; разрешено только обновить static EXPECTED_SOURCE_SHA после offline recomputation полного digest
  - LIVE_READY остаётся false

acceptance:
  - exact canonical source SHA PASS
  - cached Alpine/toolchain identity PASS
  - build A PASS
  - build B PASS
  - sha(A)==sha(B) and cmp identical
  - musl/interpreter/needed/lib-identical gates PASS
  - packaged binary actual SHA == transport pin == build metadata
  - packaged source identity == current canonical source identity
  - NATIVE_REBUILD_REQUIRED=false
  - CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=true
  - focused provenance tests PASS
  - R30D focused regression PASS
  - full safety-poc suite PASS
  - static/offline safety PASS
  - scope gate PASS

stop_conditions:
  - cached toolchain absent or identity differs
  - two builds are not byte-identical
  - canonical source SHA differs from accepted R30D value
  - нужно менять builder/protocol source
  - нужен новый write scope
  - требуется external download/live/HA/credential/user choice
```

## CT120 execution boundary

Codex владеет build procedure и обязан сформировать точную command sequence.

Предпочтительно Codex сам исполняет её на CT120, если его execution environment имеет разрешённый доступ.

Если sandbox/tool boundary не даёт Codex вызвать CT120, Hermes может сделать только mechanical relay:

1. Codex формирует точные команды и expected gates;
2. Hermes выполняет эти команды на CT120 без редактирования/интерпретации;
3. Hermes возвращает полный stdout/stderr, paths и SHA в тот же Codex context;
4. Codex проверяет evidence, принимает/отклоняет artifacts и продолжает changes/tests.

Hermes не выбирает «лучший» binary и не меняет code/pins самостоятельно.

Нельзя просить пользователя вручную запускать CT120-команды, если существующий Hermes/CT120 доступ достаточен.

## Build preflight

На CT120 перед build:

- использовать отдельный clean clone/worktree Comelit либо exact detached checkout текущего R30E build-input commit;
- remote credential-free;
- worktree clean;
- определить один cached Alpine 3.24.1 rootfs;
- проверить `/usr/bin/gcc`, musl interpreter, pkg-config и необходимые installed libs/versions;
- не выполнять `apk add`, download или `OFFLINE_BUILD=0`.

Если cache отсутствует — STOP с `BLOCKED_OFFLINE_TOOLCHAIN_CACHE_UNAVAILABLE`.

## Две независимые сборки

Для обеих builder invocation передавать один exact `P80_BUILD_EXPECTED_SHA`, один `OFFLINE_ROOTFS` и:

```text
P80_BUILD_ALLOW_DETACHED=1
P80_BUILD_INCLUDE_P116=1
P80_BUILD_TRANSFORM=safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
P80_BUILD_EXPECTED_SOURCE_SHA=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
OFFLINE_BUILD=1
```

Outputs должны быть различными paths, например build-A/build-B.

После каждого прохода сохранить evidence:

```text
P80_GENERATED_SOURCE_SHA256
P80_BINARY_SHA256
P80_BUILD_ROOTFS_MODE
MUSL_INTERPRETER_GATE
NO_GLIBC_DEPENDENCY
NO_NEW_RUNTIME_DEPENDENCY
LIB_IDENTICAL
P80_HAOS_MEDIA_BUILD
candidate_executed
COMELIT_NETWORK_REQUESTS
```

Затем обязательны `sha256sum` обоих outputs и `cmp -s`.

До PASS этого gate не копировать binary в repo и не менять transport pin.

## Packaging и provenance edits

После reproducibility PASS Codex:

1. материализует один byte-identical artifact как `custom_components/comelit/native/comelit-media`;
2. вычисляет SHA repo binary;
3. меняет в `media_transport.py` только `MEDIA_NATIVE_BINARY_SHA256` на этот SHA;
4. обновляет `p116_media_telemetry_build_meta.txt` фактическими current source/binary/toolchain/reproducibility данными;
5. обновляет P107 и P116 binary-analysis provenance tests так, чтобы packaged source identity совпадала с HEAD canonical source и stale/rebuild-required state исчезла;
6. сохраняет pre-R30E identities как historical evidence, где это полезно;
7. offline вычисляет текущий полный R27 generated-source SHA, проверяет его semantic test contract и только затем обновляет `EXPECTED_SOURCE_SHA` live runner + соответствующий static test;
8. создаёт `P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md`.

Не исполнять packaged candidate или R27 runner.

## Write scope

Строго следовать разделу 7 основного контракта.

Особо: `custom_components/comelit/media_transport.py` может отличаться от base только значением `MEDIA_NATIVE_BINARY_SHA256`.

Любое иное изменение `custom_components/comelit/**` — blocker/scope violation.

## Verification

Минимум focused:

```text
python3 -m unittest safety-poc/tests/test_p107_musl_package_provenance.py
python3 -m unittest safety-poc/tests/test_p116_provenance_binary_analysis.py
python3 -m unittest safety-poc/tests/test_p116_r27_repeat_001a_contract.py
python3 -m unittest safety-poc/tests/test_p116_r30b_offline_call_transaction.py
python3 -m unittest safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
```

Затем полный repository-local acceptance:

```text
python3 -m unittest discover -s safety-poc/tests -p 'test_*.py'
python3 safety-poc/scripts/static_safety_check.py
```

Плюс существующие compile/py_compile/bash -n/CLI safety-scenario steps из `.github/workflows/offline-safety.yml`, `git diff --check` и explicit write-scope gate.

Проверить binary непосредственно (`sha256`, ELF interpreter, DT_NEEDED, required markers), не полагаться только на literals в tests/meta.

## Git/GitHub

После локального PASS Hermes:

- проверяет diff/scope;
- commits/pushes через штатный credential helper, без token в URL/logs;
- создаёт PR в `main`, если credential capability позволяет;
- ждёт реальные PR gates `offline-safety` и `Validate HACS`;
- при обычном CI defect возвращает feedback Codex для corrective pass;
- не merge при FAIL/unknown/in-progress;
- если PR создать нельзя, возвращает branch/head для ChatGPT;
- после PASS не запускает live и не деплоит в HA.

## Result document / финальный блок

В result doc и последнем полезном блоке Hermes должны быть минимум:

```text
=== COMELIT P116 R30E NATIVE HELPER REBUILD PROVENANCE ===
TASK_ID=COMELIT-P116-R30E-NATIVE-HELPER-REBUILD-PROVENANCE
BASE_SHA=<fresh-origin-main-at-start>
BUILD_INPUT_SHA=<exact-commit-used-by-both-builds>
FINAL_SHA=<branch-head>
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=<version>
CHANGED_FILES=<count-and-paths>
CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
OFFLINE_ROOTFS=<path-or-qualified-id>
ALPINE_VERSION=<version>
CC_VERSION=<version>
LIBNICE_VERSION=<version>
GLIB_VERSION=<version>
BUILD_A_SHA256=<sha>
BUILD_B_SHA256=<sha>
REPRODUCIBLE_BINARY_SHA_GATE=<PASS|FAIL>
REPRODUCIBLE_BINARY_CMP_GATE=<PASS|FAIL>
PACKAGED_BINARY_SHA256=<sha>
TRANSPORT_PIN_SHA256=<sha>
PACKAGED_NATIVE_BINARY_REBUILT=<true|false>
NATIVE_REBUILD_REQUIRED=<true|false>
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=<true|false>
ARTIFACT_PROVENANCE_READY=<true|false>
R27_GENERATED_SOURCE_SHA256=<full-sha>
R27_STATIC_PIN_UPDATED=<true|false>
P107_PROVENANCE_TESTS=<PASS|FAIL>
P116_BINARY_ANALYSIS_TESTS=<PASS|FAIL>
R27_STATIC_PIN_TESTS=<PASS|FAIL>
R30D_FOCUSED_REGRESSION=<PASS|FAIL>
FULL_OFFLINE_TESTS=<PASS|FAIL>
STATIC_SAFETY=<PASS|FAIL>
MUSL_INTERPRETER_GATE=<PASS|FAIL>
NO_GLIBC_DEPENDENCY=<PASS|FAIL>
NO_NEW_RUNTIME_DEPENDENCY=<PASS|FAIL>
LIB_IDENTICAL=<PASS|FAIL>
COMELIT_NETWORK_TX=0
EXTERNAL_TOOLCHAIN_DOWNLOADS=0
CANDIDATE_EXECUTIONS=0
LIVE_INVOCATIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_DEPLOYED=false
LIVE_AUTHORIZED=false
LIVE_READY=false
OFFLINE_SAFETY=<PASS|FAIL|UNAVAILABLE>
VALIDATE_HACS=<PASS|FAIL|UNAVAILABLE>
PR=<number-or-none>
RESULT=<PASS|BLOCKED|FAIL>
=== END COMELIT P116 R30E NATIVE HELPER REBUILD PROVENANCE ===
```

Полезный блок должен быть последним в выводе Hermes.

После него STOP. Не начинать live stage без отдельной постановки и разрешения пользователя.
