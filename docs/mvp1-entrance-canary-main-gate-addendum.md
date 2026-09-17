# Comelit MVP1 entrance canary — main gate addendum

Status: **normative override for `COMELIT-MVP1-ENTRANCE-CANARY`**  
Date: 2026-09-17

This addendum supersedes only the exact-overall-main-SHA gate in:

- `docs/mvp1-entrance-canary-contract.md` §4.2;
- `docs/mvp1-entrance-canary-execution-task.md` §2 and the `EXPECTED_SHA` interpretation in the final block.

Reason: the canary documentation itself is merged after the implementation commit, so requiring the repository's overall `main` SHA to remain equal to the pre-documentation implementation commit would create a false `MAIN_MOVED` stop even when `custom_components/comelit/**` is unchanged.

## 1. Executable implementation identity

The offline-ready implementation was proven at:

```text
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd
COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
```

`COMELIT_COMPONENT_TREE_SHA` is the Git tree SHA for:

```text
custom_components/comelit/**
```

at the proven implementation base.

## 2. Correct fresh-main gate

At live task start:

1. Perform fresh authenticated fetch of `origin/main`.
2. Record the actual current `origin/main` as `ACCEPTED_MAIN_SHA`.
3. Resolve the Git tree SHA of `custom_components/comelit` at that exact current main.
4. Require:

```text
CURRENT_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
COMELIT_COMPONENT_TREE_MATCH=true
```

5. If the component tree differs, set:

```text
MAIN_MOVED=true
RESULT=BLOCKED_PRELIVE_GATE
```

and STOP before deploy.

6. If only documentation/non-component paths changed and the Comelit component tree still matches, this is **not** `MAIN_MOVED` for canary purposes.

7. Deploy `custom_components/comelit/**` from the exact fresh accepted `origin/main` SHA, not from an older commit.

This preserves the user's requirement to deploy exact current main while ensuring the executable integration content remains exactly the offline-proven MVP implementation.

## 3. Final block interpretation

In the final Hermes block:

```text
EXPECTED_SHA=1402a15254340317a4683b6b781024b23073eefd
```

is interpreted as the proven implementation-base reference only.

Add these scalars immediately after `ACCEPTED_MAIN_SHA`:

```text
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd
EXPECTED_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
CURRENT_COMELIT_COMPONENT_TREE_SHA=<sha>
COMELIT_COMPONENT_TREE_MATCH=true|false
```

`MAIN_MOVED=false` means the executable Comelit component tree still matches the proven implementation, even if the repository-level main SHA advanced because of documentation-only merges.

All other live boundaries, counts, STOP rules and user authorization remain unchanged.
