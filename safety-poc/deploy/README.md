# Git-native deployment

`install_candidate.sh` replaces the historical large copy/paste/base64 upgrade path for future releases.

The installer is intentionally fail-closed. It:

1. requires one or more runtime gate-report files;
2. requires a clean named `main` worktree;
3. fetches `origin/main` and requires local `HEAD == origin/main`;
4. refuses any version containing `dev`;
5. requires `CT120_RUNTIME_GATES=PASS` and `REPOSITORY_READY=true`;
6. requires the runtime report's `RUNTIME_GATE_TREE_SHA` to equal the current Git tree SHA;
7. requires the runtime report's `RUNTIME_GATE_VERSION` to equal the candidate version;
8. requires `REAL_TRANSPORT_IMPLEMENTED=false` and `LIVE_TEST_READY=false` for this offline v0.6 release;
9. independently reruns `evaluate_plan_readiness.py` and the full offline suite;
10. creates the staged release only from `git archive HEAD:safety-poc`, so ignored or untracked working-tree files cannot enter the artifact;
11. writes `RELEASE_GIT.txt` with version, Git commit, Git tree, tested tree and safety markers;
12. runs the offline suite from the staged tree before promotion;
13. creates and verifies `RELEASE_CONTENT.sha256`;
14. promotes the staged tree to a new immutable release directory keyed by date, version and Git SHA;
15. atomically points `current` at the new release;
16. reruns the offline suite from the promoted release and re-verifies every release-content hash;
17. restores the previous `current` target and removes the failed candidate on any post-promotion failure.

## Why tree SHA is used

A reviewed feature branch may be squash-merged, changing the commit SHA while preserving the exact repository tree. The CT120 runtime gate therefore records both commit SHA and tree SHA, while deployment requires the **tested tree SHA** and version to match. Any content change after the runtime test changes the tree and forces a new runtime-gate run.

## Required sequence for v0.6

1. Run CT120 runtime gates on the development candidate.
2. Resolve any failures without weakening safety gates.
3. Change the candidate version to final `0.6.0`.
4. Run CT120 runtime gates again on that exact final-version tree.
5. Review and merge the PR.
6. Synchronize CT120 `main` with `origin/main`.
7. Run `install_candidate.sh` using the final runtime gate report.

The installer does not implement or enable a real Comelit transport and does not perform a Door action. Repository readiness is intentionally separate from live-test readiness.
