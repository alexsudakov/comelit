# P116 / R30E — native helper rebuild + reproducible provenance contract

Статус: **готово к исполнению после merge contract/task PR / OFFLINE BUILD ONLY**

TASK_ID=`COMELIT-P116-R30E-NATIVE-HELPER-REBUILD-PROVENANCE`

BASELINE_MAIN=`0248fb7ac68a944fca1d6814bd102187b44e5601`

## 1. Назначение

R30E — отдельный bounded child после принятого R30D.

R30D доказал и интегрировал native CTP state semantics в canonical source, но намеренно оставил packaged native helper старым:

```text
PACKAGED_NATIVE_BINARY_REBUILT=false
HEAD_CANONICAL_SOURCE_CHANGED=true
NATIVE_REBUILD_REQUIRED=true
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=false
LIVE_READY=false
```

Цель R30E — **не менять protocol semantics**, а воспроизводимо пересобрать packaged musl helper из уже принятого canonical HEAD source и восстановить доказуемую цепочку:

```text
accepted canonical source
-> exact source SHA gate
-> pinned offline toolchain
-> two independent byte-identical builds
-> packaged native binary SHA
-> Home Assistant native hash pin
-> repository provenance tests
```

R30E не является live-тестом и не даёт live authorization.

```text
MODE=OFFLINE_BUILD_ONLY
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
HERMES_ROLE=ORCHESTRATOR_ONLY
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
COMELIT_NETWORK_TX_ALLOWED=false
HA_ALLOWED=false
HA_DEPLOY_ALLOWED=false
PRODUCTION_RUNTIME_CHANGE_ALLOWED=false
NATIVE_PACKAGE_REFRESH_ALLOWED=true
```

## 2. Canonical inputs

Основной semantic input:

```text
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
```

Canonical builder/provenance inputs:

```text
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
safety-poc/tests/test_p116_build_provenance_gate.py
safety-poc/tests/test_p107_musl_package_provenance.py
safety-poc/tests/test_p116_provenance_binary_analysis.py
safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt
custom_components/comelit/media_transport.py
custom_components/comelit/native/comelit-media
```

R30D accepted current P106/P116 canonical source identity:

```text
HEAD_P116_CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
```

Pre-R30E packaged artifact identity is historical input only:

```text
PRE_R30E_PACKAGED_BINARY_SHA256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
PRE_R30E_PACKAGED_SOURCE_SHA256=93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66
```

Нельзя менять R30D protocol source ради достижения reproducibility или совпадения digest.

## 3. Build path

Использовать существующий canonical builder:

```text
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
```

Обязательные параметры для packaged P116 build:

```text
P80_BUILD_ALLOW_DETACHED=1
P80_BUILD_EXPECTED_SHA=<exact-build-input-commit>
P80_BUILD_INCLUDE_P116=1
P80_BUILD_TRANSFORM=safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
P80_BUILD_EXPECTED_SOURCE_SHA=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
OFFLINE_BUILD=1
```

### 3.1 Toolchain boundary

R30E должен использовать только уже существующий cached Alpine 3.24.1 chroot на CT120.

Запрещено переключать builder в download mode (`OFFLINE_BUILD=0`) в рамках R30E.

До сборки доказать, что выбранный cached rootfs содержит необходимые compiler/pkg-config/library inputs. Для обеих независимых сборок использовать один и тот же явно выбранный `OFFLINE_ROOTFS`.

Если подходящего cache нет:

```text
RESULT=BLOCKED_OFFLINE_TOOLCHAIN_CACHE_UNAVAILABLE
```

Это не даёт права автоматически скачивать toolchain.

Ожидаемые toolchain/runtime invariants из принятого P116 provenance:

```text
Alpine=3.24.1
cc=Alpine GCC 15.2.0
libnice=0.1.22
glib/gobject=2.88.1
interpreter=/lib/ld-musl-x86_64.so.1
needed_sorted=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
flags=-O2 -g -Wall -Wextra -Wl,--as-needed
```

Если фактический cached toolchain отличается, не подгонять expected values: остановиться как semantic/provenance blocker и показать diff.

## 4. Reproducible rebuild

Выполнить **две независимые** builder invocation из одного exact build-input commit и одного explicit cached rootfs.

Использовать два разных output path и не переиспользовать готовый binary между проходами.

Оба прохода обязаны независимо дать:

```text
P80_BUILD_EXPECTED_SHA_GATE=PASS
P80_BUILD_EXPECTED_SOURCE_SHA_GATE=PASS
P80_HAOS_MEDIA_BUILD=PASS
MUSL_INTERPRETER_GATE=PASS
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
LIB_IDENTICAL=PASS
candidate_executed=false
COMELIT_NETWORK_REQUESTS=0
```

Затем:

```text
sha256(build_A) == sha256(build_B)
cmp(build_A, build_B) == identical
```

Если binaries различаются — не выбирать один произвольно и не обновлять repository pins. Зафиксировать evidence и вернуть blocker для диагностики reproducibility.

## 5. Packaging delta

Только после successful reproducibility gate допускается материализовать один из идентичных binaries как:

```text
custom_components/comelit/native/comelit-media
```

`custom_components/comelit/media_transport.py` разрешено менять **только** в значении:

```text
MEDIA_NATIVE_BINARY_SHA256
```

Никакая другая runtime-логика production integration в R30E не меняется.

Обновить provenance tests/meta так, чтобы они доказывали фактическую новую цепочку source -> binary, а не просто содержали согласованные literals.

Минимум:

```text
PACKAGED_NATIVE_SOURCE_SHA256 == HEAD_P116_CANONICAL_SOURCE_SHA256
actual sha256(custom_components/comelit/native/comelit-media) == MEDIA_NATIVE_BINARY_SHA256
actual binary sha == committed build-meta binary sha
committed build-meta source sha == HEAD_P116_CANONICAL_SOURCE_SHA256
NATIVE_REBUILD_REQUIRED=false
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=true
```

Старые packaged/source SHA сохранить как явно historical/pre-R30E evidence там, где это полезно; не выдавать их за текущую identity.

## 6. R27 stale runner pin

Файл:

```text
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
```

содержит pre-R30D `EXPECTED_SOURCE_SHA=62e00235...` и сейчас намеренно fail-closed.

R30E может обновить **только этот static source SHA pin**, но лишь после offline recomputation текущего `entrance_p116_r27_repeat_001a_transform.py` output и проверки его ожидаемой current identity.

R30D evidence ожидает current R27 generated-source identity:

```text
EXPECTED_CURRENT_R27_GENERATED_SOURCE_SHA256=1c9f13cf...  # использовать только после вычисления полного 64-hex digest из текущего source
```

Не брать усечённый digest из отчёта как pin. Codex должен вычислить полный digest локально и обновить соответствующий contract test.

Runner в R30E **не запускать**. Никаких webhook/listener/live действий.

Если текущий R27 generated source не соответствует R30D semantic expectations, остановиться и эскалировать, а не ослаблять runner gates.

## 7. Разрешённый write scope

Разрешены изменения только в:

```text
custom_components/comelit/native/comelit-media
custom_components/comelit/media_transport.py
safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p107_musl_package_provenance.py
safety-poc/tests/test_p116_provenance_binary_analysis.py
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
```

Допускается новый focused provenance test только внутри `safety-poc/tests/**`, если объективно нужен для доказательства двух-build/rebuild contract; необходимость описать в result.

Не менять без отдельного решения:

```text
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
custom_components/comelit/**  # кроме двух точно перечисленных package/pin paths выше
.github/**
README.md
docs/**
```

Изменение builder или protocol source — semantic boundary и требует эскалации.

## 8. Safety boundary

Запрещены:

```text
Comelit network TX
live media/call
ICE/PseudoTCP/cloud bootstrap
Door
Gate
self-activation
refresh/repeat execution
R27 live runner execution
production listener stop/start/reload
HA deploy/restart/reload
copy/install нового binary в работающий HA
production runtime behavior changes
credential/token output or commit
external toolchain/package download
```

Разрешён только локальный filesystem/chroot build и Git/GitHub transport.

Если Codex sandbox не умеет напрямую вызвать CT120, Hermes может выполнить **только точную mechanical remote build/copy command sequence, сформированную Codex**, без самостоятельного изменения source/code или выбора результата. Полные stdout/stderr + SHA возвращаются в тот же Codex context, который обязан проверить evidence и продолжить acceptance.

## 9. Codex lifecycle

Один bounded R30E child по возможности выполняется одним Codex context:

```text
inspect
-> verify exact source identity
-> inspect offline cached toolchain
-> build A
-> build B
-> reproducibility gate
-> package exact artifact
-> update pins/provenance tests/meta
-> focused tests
-> diagnose/fix ordinary defects
-> full offline acceptance
-> final diff/safety review
```

Обычные implementation/test/CI defects внутри утверждённого scope Codex исправляет самостоятельно. Если Codex уже завершился, Hermes возвращает такой defect тому же context через corrective pass.

Эскалировать только если требуется новый semantic/architecture choice, новый write scope, изменение builder/protocol source, live/HA action, external download/credential или если reproducibility/source/toolchain contract не выполняется.

## 10. Acceptance

Обязательные gates:

```text
CANONICAL_SOURCE_SHA_GATE=PASS
OFFLINE_CACHED_TOOLCHAIN_GATE=PASS
BUILD_A=PASS
BUILD_B=PASS
REPRODUCIBLE_BINARY_SHA_GATE=PASS
REPRODUCIBLE_BINARY_CMP_GATE=PASS
MUSL_INTERPRETER_GATE=PASS
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
LIB_IDENTICAL=PASS
PACKAGED_BINARY_SHA_GATE=PASS
TRANSPORT_BINARY_PIN_GATE=PASS
BUILD_META_SOURCE_GATE=PASS
BUILD_META_BINARY_GATE=PASS
P107_PROVENANCE_TESTS=PASS
P116_BINARY_ANALYSIS_TESTS=PASS
R27_STATIC_PIN_TESTS=PASS
R30D_FOCUSED_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
COMPILE_SHELL_GATES=PASS
WRITE_SCOPE_GATE=PASS
```

После packaging:

```text
PACKAGED_NATIVE_BINARY_REBUILT=true
HEAD_CANONICAL_SOURCE_CHANGED=true
NATIVE_REBUILD_REQUIRED=false
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=true
ARTIFACT_PROVENANCE_READY=true
LIVE_AUTHORIZED=false
LIVE_READY=false
```

`LIVE_READY=false` означает отсутствие live authorization/verification, а не проблему с offline artifact provenance.

После PR обязательны реальные:

```text
offline-safety=SUCCESS
Validate HACS=SUCCESS
```

## 11. Stop boundary

После successful R30E merge — STOP.

Не запускать R27/live, не деплоить binary в HA и не переходить автоматически к следующему live stage.

Следующий live child требует отдельного контракта и отдельного разрешения пользователя.
