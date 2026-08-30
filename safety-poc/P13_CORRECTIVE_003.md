# P13 corrective task — COMELIT-P13-CORRECTIVE-003

## Status

Continue on `feat/p13-one-shot-actuation` / PR #3.

Do **not** ask the operator to run the current CT120 build/preflight yet. The wrapper provenance chain is still incomplete at the native-holder boundary.

Reviewed starting point before this document:

- HEAD `e92ee87b0bb26abf1c2e99391413fe0e65373be6`
- actual Git tree `97402343dbba00c9e6c03d0461645d6d35c01e5d`
- CI push run `33314094424`: success
- CI PR run `33314095758`: success
- no physical Door action occurred

The previous Hermes report again contained an incorrect abbreviated TREE (`19d9ba88…`). Future reports must use the exact remote tree from `git rev-parse HEAD^{tree}` and cross-check GitHub.

## Blocking finding — native P13 holder provenance is still open

Current reviewed chain is:

`deploy/p13_wrapper_template.sh`
→ `scripts/build_p13_wrapper.sh`
→ **external `P13_HOLDER_PATH` binary + operator-supplied `P13_HOLDER_SHA256`**
→ `/usr/local/sbin/comelit-p13-door-wrapper`
→ `deploy/p13_wrapper_manifest.json`.

This closes provenance only from the supplied holder binary to the wrapper. It does **not** independently establish that the holder itself is the reviewed P13 implementation.

The current operator instruction:

```text
P13_HOLDER_PATH=/root/comelit-p13-native/comelit_p13_holder
P13_HOLDER_SHA256=<sha256 holder>
```

still permits the expected holder hash to be copied from the same runtime binary immediately before build. That is the same self-pinning problem one layer lower.

The repository currently does not contain a reviewed source/build chain for `comelit_p13_holder` that explains how a holder supporting `--payload`, `--operation-id`, `--emit-ctpp-markers`, UAUT/CTPP, and exactly six Door writes is derived.

## Required correction

Close the holder provenance gap before any CT120 P13 preflight can emit `ACTUATION_TRANSPORT_IMPLEMENTED=true`.

### Acceptable preferred design

Create a reproducible, reviewable native-holder build chain. For example:

1. Start from an **independently pinned baseline source** already present on CT120, or add a reviewed source if it is public-safe.
2. If the baseline source cannot be committed because it contains runtime-specific/sensitive values, pin its exact SHA-256 and apply a Git-tracked deterministic transform/patch to it.
3. Produce a P13-derived source with a recorded derived-source SHA-256.
4. Compile/build the native holder with a Git-tracked build script and explicit compiler/link flags.
5. Record a holder build manifest containing at least:
   - schema/status;
   - baseline source SHA-256 (if applicable);
   - transform/patch SHA-256 or Git blob identity;
   - derived source SHA-256;
   - compiler/build procedure identity;
   - resulting holder binary SHA-256;
   - expected owner/mode;
   - capability surface (`--payload`, `--operation-id`, `--emit-ctpp-markers`);
   - source feature HEAD/TREE.
6. The wrapper build must consume the **holder manifest**, not an operator-supplied expected SHA.
7. CT120 preflight must verify both:
   - installed holder binary == independently reviewed holder manifest;
   - installed wrapper == independently reviewed wrapper manifest.

A historical baseline source may be reused only if its identity is independently pinned and the Git-tracked transform clearly derives the P13 holder from it. Do not silently treat a P12 read-only holder as P13-capable.

## Operator input rule

The operator must **not** be asked to calculate an expected holder SHA from the same runtime holder and feed it back as `P13_HOLDER_SHA256`.

Runtime `sha256sum` may be used only as the **actual** side of a comparison against an independently derived/committed expected identity.

## Two-phase root flow is acceptable and safer

Because Hermes does not have arbitrary root on CT120, it is acceptable to use two non-actuating root phases instead of pretending this can be one step:

### Phase R1 — build only, no Comelit network/action

Root executes a reviewed holder/wrapper build script that:

- verifies the independently pinned baseline source;
- derives/builds the P13 holder;
- derives/builds the wrapper;
- installs root-only artifacts;
- writes candidate holder/wrapper manifests;
- emits only public-safe hashes/build markers;
- does **not** perform Cloud P2P/ICE/UAUT/CTPP/Door network work;
- does **not** reach `SEND_ARMED`.

The manifest identities are then committed/pushed to the feature branch and reviewed. CI must be green on that exact new HEAD/TREE.

### Phase R2 — non-actuating CT120 preflight

Only after the manifests are in Git and CI is green, root runs the non-actuating preflight. It must exact-sync to the reviewed remote HEAD and verify installed holder/wrapper against the committed manifests before claiming implementation readiness.

This phase may collect/push `evidence/p13-preflight-<STAMP>`.

## Additional required checks

### Holder identity / ownership

Fail closed unless:

- holder is root-owned;
- holder mode is root-only/executable as designed;
- actual holder SHA matches committed expected holder SHA;
- wrapper points to exactly the pinned holder path;
- wrapper SHA matches committed wrapper manifest;
- payload remains root-owned mode 0600.

### Capability contract

The holder build/tests must prove the expected command-line contract without performing a physical action:

- recognizes required arguments;
- dry/help/probe mode does not open a Comelit session or send Door data;
- no automatic retry loop;
- exactly one operation invocation surface;
- typed marker schema is versioned/validated;
- timeout/nonzero exit/missing markers remain conservative (`AMBIGUOUS` after `SEND_ARMED` where applicable).

### Marker consistency

Retain all corrective-002 conservative semantics:

- `PROVEN_NOT_OPENED` + writes > 0 => `AMBIGUOUS`;
- `REJECTED` + writes > 0 => `AMBIGUOUS`;
- missing/invalid open marker => `AMBIGUOUS`;
- partial writes => `AMBIGUOUS`;
- missing/failed close => `AMBIGUOUS`;
- missing/failed teardown => `AMBIGUOUS`;
- timeout/nonzero process exit after possible emission => `AMBIGUOUS`;
- `PROVEN_NOT_SENT` only with proof that no side-effect-capable send was emitted.

## Tests required before operator root phase

Add deterministic tests proving at minimum:

- holder manifest absent/NOT_BUILT => preflight fails closed;
- holder binary SHA mismatch => fail closed;
- holder owner/mode mismatch => fail closed;
- wrapper manifest cannot reference an unreviewed/operator-supplied holder SHA;
- wrapper build consumes holder manifest identity;
- source/transform identity mismatch => build fails closed;
- holder dry capability check performs no network/action;
- old/read-only holder without required P13 capability cannot pass P13 readiness;
- full repository suite, static scan, shell parse, py_compile, PR CI all green.

## Stop boundary

After the holder provenance chain is closed and CI is green:

- if Hermes still cannot execute root on CT120, return **one exact R1 build-only root command** with no placeholders that can be resolved from Git/runtime-safe pinned identities;
- after the operator returns public-safe R1 output, commit/review the resulting manifests and run CI;
- then return **one exact R2 non-actuating preflight command**;
- do not request physical approval until R2 evidence is verified and PR #3 is review-complete.

The physical runner must not be executed in this corrective task.

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST` has **not** been granted.

## Invariants

- `SEND_ARMED` is the irreversible ambiguity boundary.
- one `operation_id` => max one transport invocation.
- `attempt_number=1`.
- no automatic retry.
- post-`SEND_ARMED` uncertainty => `UNKNOWN_OUTCOME`.
- protocol ACK != physical relay proof.
- `PHYSICAL_EFFECT_ASSERTED=false` always.
- no fault injection through physical sends.

## Corrective result

`CORRECTIVE_RESULT=DONE` is forbidden until holder provenance is independently closed, manifests are reviewed, exact-head CI is green, and CT120 non-actuating preflight evidence is verified.