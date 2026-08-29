# Git-native deployment

`install_candidate.sh` replaces the historical large copy/paste/base64 upgrade path for future releases.

The script is intentionally fail-closed:

1. requires one or more gate-report files;
2. requires a clean Git worktree;
3. refuses any version containing `dev`;
4. requires `evaluate_plan_readiness.py` to report repository readiness;
5. runs the full offline suite before promotion;
6. copies the exact checked-out `safety-poc` tree into a new immutable release directory keyed by date, version and Git SHA;
7. writes a release Git identity and SHA256 content manifest;
8. atomically points `current` at the new release;
9. reruns the full offline suite from the promoted release and verifies the content manifest;
10. restores the previous `current` target on any post-promotion failure.

The installer does not implement or enable a real Comelit transport and does not perform a Door action. Repository readiness is intentionally separate from live-test readiness.
