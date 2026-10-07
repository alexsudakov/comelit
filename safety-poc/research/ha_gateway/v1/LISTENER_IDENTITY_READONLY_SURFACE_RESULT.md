# LISTENER_IDENTITY_READONLY_SURFACE_RESULT

## Реализация

Локально добавлены только репозиторные артефакты:

- `safety-poc/research/ha_gateway/v1/comelit-listener-identity.sh`
- `safety-poc/research/ha_gateway/v1/gateway-dispatch-fragment.txt`
- `safety-poc/tests/test_listener_identity_helper.py`
- обновлен `safety-poc/research/media/v1/listener_readonly_observer.py`

На HA host ничего не установлено, `custom_components/comelit/**` не изменялся,
gateway не расширялся, live P2P / Comelit network calls не выполнялись.

## Контракт helper

`comelit-listener-identity.sh` является POSIX shell helper без пользовательских
аргументов. Единственный допустимый аргумент: `help`. Любой другой аргумент,
включая PID, path, process name или socket selector, возвращает
`STATUS=UNSUPPORTED_ARGUMENT` и ненулевой rc.

Helper выводит только allowlisted `KEY=VALUE` поля:

```text
STATUS
LISTENER_READY
LISTENER_PID
LISTENER_PROCESS_START_TICKS
LISTENER_PROCESS_GENERATION
LISTENER_EXE_SHA256
LISTENER_EXE_MATCHES_EXPECTED
LISTENER_SOCKET_PRESENT
LISTENER_SOCKET_PROTOCOL
LISTENER_SOCKET_INODE
LISTENER_SOCKET_LOCAL
LISTENER_SOCKET_REMOTE
LISTENER_SOCKET_FINGERPRINT_SHA256
LISTENER_TRANSPORT_GENERATION
LISTENER_RUN_DIR_CORROBORATION
MATCH_RULE
CANDIDATE_COUNT
BOOT_ID_PRESENT
PROCESS_VIEW
SECRETS_EMITTED
WRITES_PERFORMED
QUERIES_PERFORMED
```

Readiness не выводится из PID/socket. Если локальный независимый readiness
source недоступен, helper оставляет `LISTENER_READY=UNKNOWN`; observer должен
объединять это с независимым `logs-follow` источником
`V4_RING_LISTENER_READY=true` / `listener_ready`.

## Fail-closed identification rule

Правило выбора процесса теперь выведено из production source:

- `custom_components/comelit/runtime.py:41`: persistent Ring listener binary is
  `_NATIVE_ROOT / "comelit-v4"`;
- `custom_components/comelit/runtime.py:44`: persistent listener run dir is
  `/run/comelit-p2p`;
- `custom_components/comelit/media_transport.py:59`: on-demand media / Mini App
  helper binary is `_NATIVE_ROOT / "comelit-media"`;
- `custom_components/comelit/media_transport.py:62`: media helper run dir is
  `/run/comelit-media`.

Production spawn sites pass zero command-line arguments, so argv/env are not
role discriminators and the helper does not print their contents.

1. enumerate fixed `${COMELIT_PROC_ROOT:-/proc}/[0-9]*`;
2. reject explicit media/Mini App and research helper executable names, including
   `comelit-media` and `comelit-media-research-stage7-v2`;
3. keep only processes whose `/proc/<pid>/exe` readlink equals the source-derived
   listener allowlist:
   `/config/custom_components/comelit/native/comelit-v4` or
   `/usr/share/hassio/homeassistant/custom_components/comelit/native/comelit-v4`;
4. treat cwd inside `/run/comelit-p2p` as optional corroboration only
   (`LISTENER_RUN_DIR_CORROBORATION=true|false|UNKNOWN`); it never decides the
   match, and `UNKNOWN` is not a failure;
5. exactly one survivor gives `STATUS=PASS`; zero gives `STATUS=NOT_FOUND`;
   multiple gives `STATUS=AMBIGUOUS`;
6. if no process view exists, return `STATUS=UNSUPPORTED_NAMESPACE` with
   `PROCESS_VIEW=UNAVAILABLE`.

`MATCH_RULE=exe-allowlist-comelit-v4-source-derived` names the primary deciding
rule. Это fail-closed, потому что helper не использует "first Comelit process
wins", explicitly excludes `comelit-media`, and does not accept a
caller-controlled selector. Ambiguity is surfaced instead of guessed.

`LISTENER_PROCESS_GENERATION` is `sha256(boot_id + pid + starttime)`, where
`starttime` is parsed from `/proc/<pid>/stat` field 22 after handling `comm`
with spaces or parentheses. Socket identity comes only from the selected
process fd symlinks and `/proc/net/{udp,udp6,tcp,tcp6}` rows. Multiple matched
transport sockets become `STATUS=AMBIGUOUS`.

`COMELIT_PROC_ROOT` exists only for offline fixtures. The helper appends fixed
subpaths such as `sys/kernel/random/boot_id`, `[0-9]*/exe`, `[0-9]*/stat`,
`[0-9]*/cwd`, `[0-9]*/fd/*`, and `net/udp`; it does not accept arbitrary
paths.

## Dispatch fragment

`gateway-dispatch-fragment.txt` contains the one branch the owner can add:

```sh
    readonly-listener-identity)
        exec /config/tools/comelit-listener-identity.sh
        ;;
```

It must be placed inside the existing `case "${SSH_ORIGINAL_COMMAND:-}"`
dispatch before the `COMELIT_HA_GATEWAY=DENY` fallback. It takes zero user
arguments and passes none to the helper. A patched SSH forced-command script
should take effect on the next SSH session with no HA restart; only if the
gateway were a long-running service would an SSH add-on restart potentially be
needed, and that model is UNPROVEN here.

## Owner install block

Owner-only action, not run by Hermes:

```sh
install -m 0755 /tmp/comelit-listener-identity.sh /config/tools/comelit-listener-identity.sh
# Then insert the readonly-listener-identity case branch before the DENY fallback
# in the existing SSH forced-command gateway script.
```

First owner validation call after install:

```sh
ssh comelit-ha readonly-listener-identity
```

The first call settles whether a helper running in the SSH add-on namespace can
see the HA Core process and its sockets.

## Observer integration

`listener_readonly_observer.py` still supports the log-driven `--log-file` and
`--status-json` behavior. It now also supports:

- `--identity-file <path|->` for one helper `KEY=VALUE` capture;
- `--identity-before <path> --identity-after <path>` for two-capture
  comparison.

New output includes:

```text
LISTENER_PROCESS_GENERATION
LISTENER_SOCKET_FINGERPRINT
PROCESS_GENERATION_CHANGED
SOCKET_FINGERPRINT_CHANGED
LISTENER_RECOVERY_OBSERVED
CONFLICT_DETECTION_SUFFICIENT
MISSING_CAPABILITY
```

`CONFLICT_DETECTION_SUFFICIENT=true` only when readiness, process generation,
and socket fingerprint are all actually readable from supplied inputs.

## Tests

Targeted command run:

```text
python3 -m pytest safety-poc/tests/test_listener_identity_helper.py \
  safety-poc/tests/test_research_pausable_p2p_harness.py::ResearchPausableP2PHarnessTests::test_24_observer_distinguishes_listener_vs_research_helper \
  safety-poc/tests/test_research_pausable_p2p_harness.py::ResearchPausableP2PHarnessTests::test_25_observer_detects_pid_generation_change_when_observable \
  safety-poc/tests/test_research_pausable_p2p_harness.py::ResearchPausableP2PHarnessTests::test_26_observer_detects_socket_generation_change_when_observable \
  safety-poc/tests/test_research_pausable_p2p_harness.py::ResearchPausableP2PHarnessTests::test_26b_observer_reports_not_observable_without_capability
```

Result: `29 passed`.

Inventory:

- 21 helper / fragment tests cover `comelit-v4` empty-argv PASS,
  `comelit-media` empty-argv NOT_FOUND, media-vs-listener precedence,
  AMBIGUOUS for two `comelit-v4` processes, allowlist shape, optional
  `/run/comelit-p2p` corroboration, process generation stability/change, socket
  fingerprint stability/change, research helper exclusion, secret suppression,
  unsupported arguments, no writes, no argument pass-through in fragment, and
  preservation of existing gateway verb semantics by documentation contract.
- 4 observer tests cover stable capture, PID/process generation changed,
  socket fingerprint changed, and not-observable capability reporting.
- 4 existing observer compatibility tests from
  `test_research_pausable_p2p_harness.py` still pass.

## Residual risks

- Whether the helper running in the SSH add-on namespace can see the HA Core
  process and its sockets is UNVERIFIED from here. This is settled only by the
  owner's first read-only call.

## Acceptance

```text
READ_ONLY_GATEWAY_ADDED=false            # Hermes has no write path to the HA host; owner action
TOKEN_EXPOSED=false
WRITE_ACCESS_ADDED=false
HELPER_SHA256=ce6c6ab9277deb318279485641613fe116aecf9836085645237e8280e4b61a8e
DISPATCH_FRAGMENT=safety-poc/research/ha_gateway/v1/gateway-dispatch-fragment.txt
READONLY_CALL_1=NOT_RUN
READONLY_CALL_2=NOT_RUN
PROCESS_GENERATION_STABLE=UNKNOWN
SOCKET_FINGERPRINT_STABLE=UNKNOWN
LISTENER_READY_OBSERVABLE=true
LISTENER_PID_OBSERVABLE=UNKNOWN
LISTENER_PROCESS_GENERATION_OBSERVABLE=UNKNOWN
LISTENER_SOCKET_IDENTITY_OBSERVABLE=UNKNOWN
LISTENER_RECOVERY_OBSERVABLE=true
CONFLICT_DETECTION_SUFFICIENT=false
RESULT=BLOCKED (owner install required; see READ_ONLY_GATEWAY_ADDED)
```

`READY_FOR_SINGLE_LIVE_STAGE7=true` is not reachable in this child because the
helper cannot be installed here and the first read-only call belongs to the
owner.
