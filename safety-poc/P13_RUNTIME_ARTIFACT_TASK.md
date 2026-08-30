# COMELIT-P13-RUNTIME-ARTIFACT-001

## Goal

Create the missing runtime artifacts that are strictly necessary for the first real Door-open PoC on CT120:

- `/root/comelit-p13-native/comelit_p13_holder`
- `/usr/local/sbin/comelit-p13-door-wrapper`

Do not perform physical actuation in this task.

## Scope

Only work that directly enables the first real Door-open is in scope.

Do not do reproducible-build/supply-chain hardening, immutable release packaging, production Home Assistant integration, or generalized cleanup.

## Current facts

- P12 real read-only transport is already proven: P2P/ICE/PseudoTCP/ViP, UAUT=200, UCFG read, target binding.
- Door/CTPP payload shape is already fixture/capture tested and requires exactly six Door writes.
- The feature branch already contains the P13 one-shot boundary, UNKNOWN_OUTCOME semantics, duplicate protection, audit, preflight, and physical runner tests.
- The two required runtime artifacts above are not present in Git as ready-to-install artifacts, and Hermes cannot install them on CT120 because arbitrary root execution is unavailable.

## Required implementation

### 1. Native holder

Create a P13-capable holder implementation using the already proven P12 transport implementation as the baseline. Reuse the existing P2P/ICE/PseudoTCP/ViP/UAUT code path; do not redesign transport.

The holder must support exactly this operator-facing contract:

- `--payload <root-only-json>`
- `--operation-id <id>`
- `--emit-ctpp-markers`

Its single live invocation must perform:

1. establish the already proven Comelit P2P/ICE/PseudoTCP/ViP session;
2. UAUT authentication;
3. open CTPP;
4. send exactly six prepared Door bodies from the payload file, in order, at most once each;
5. close CTPP;
6. cleanly tear down the session;
7. emit typed result markers only, never secrets or raw payload values.

No internal retry loop is allowed.

Required result markers:

- `P13_CTPP_OPEN_OUTCOME=OPENED|PROVEN_NOT_OPENED|REJECTED|AMBIGUOUS`
- `P13_DOOR_WRITE_COUNT=<0..6>`
- `P13_CTPP_CLOSE=PASS|FAIL`
- `P13_TEARDOWN=PASS|FAIL`

Nonzero process exit, timeout, missing markers, partial writes, failed close, or failed teardown must remain conservative for the Python boundary and must never create a retryable post-send state.

### 2. Non-actuating capability inspection

The holder file itself must expose the required flag names in a way that `p13_capture_runtime_identity.sh` can verify statically without executing the holder.

Do not make preflight invoke the live holder just to discover capabilities.

### 3. Wrapper

Use the existing reviewed wrapper template or replace it minimally so that the installed wrapper:

- points to `/root/comelit-p13-native/comelit_p13_holder`;
- accepts `P13_OPERATION_ID` from the one-shot runner;
- passes the fixed root-only payload path;
- invokes the holder exactly once;
- contains no retry loop;
- emits only holder markers/result status.

### 4. CT120 installation path

Prepare one Git-tracked root install script that can be run on CT120 after exact-syncing the feature branch.

The install script must:

- create `/root/comelit-p13-native/`;
- install/build the holder to `/root/comelit-p13-native/comelit_p13_holder`;
- install the wrapper to `/usr/local/sbin/comelit-p13-door-wrapper`;
- set holder `root:root` and mode `0700`;
- set wrapper `root:root` and mode `0700`;
- leave `/root/comelit-p13-actuator-prep/real-door-payloads.json` untouched except for read-only validation;
- perform no Comelit network session;
- perform no UAUT/CTPP/Door action;
- never reach `SEND_ARMED`;
- print only public-safe install/identity markers.

The operator command returned at the end must contain no unresolved `<...>` placeholders.

### 5. Functional validation before operator root step

Add/update deterministic tests proving at minimum:

- holder accepts the required CLI contract;
- exactly six bodies are consumed in order;
- no retry path exists;
- partial send/timeout/error states remain conservative;
- wrapper invokes holder once;
- install script creates the expected runtime paths/modes without network/action;
- current P13 preflight recognizes the installed shape;
- full unit suite, static safety, shell parse, py_compile, and PR CI are green.

Fixture/mock transport is required for tests. Do not perform a physical Door send.

## Stop condition

When code/tests/CI are green, stop and return exactly one root command for CT120 that:

1. exact-syncs `feat/p13-one-shot-actuation` to the reviewed remote HEAD;
2. runs the new non-actuating runtime-artifact install script;
3. immediately runs `ct120_p13_preflight_manual.sh`.

The command must not launch the physical runner.

After successful preflight, stop for explicit operator approval:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

This task is not that approval.
