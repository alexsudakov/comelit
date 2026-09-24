# P116 / R65 — production media refresh: native rebuild contract

STATUS=FULFILLED (TURN9) — Hermes ran the build in §3 offline on CT120;
`P80_BINARY_SHA256=76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129`,
identical across both independent builds
(`REPRODUCIBLE_BINARY_CMP_GATE=PASS`). The binary is promoted and every pin
in §4 has been applied; see
`safety-poc/research/media/v1/p116_r65_production_media_build_meta.txt` for
the full raw provenance record.

TASK_ID=COMELIT-P116-R65-LONG-MEDIA-CUTOFF-CORRECTIVE
CHILD=B_PHASE_C_PRODUCTION
MODE=OFFLINE_BUILD_ONLY — this document authorizes an offline reproducible
build only. It does not authorize any live media attempt, deploy, or
Home Assistant restart.

## 1. Why this exists

Phase C promotes the live-proven R27 bounded same-session repeat-0x001A
candidate (`entrance_p116_r27_repeat_001a_transform.py`, live-proven on
CT120 attempt 3, commit `dc84915`) into an indefinite production refresh
scheduler via a new composed generator,
`entrance_p116_r65_production_media_refresh_transform.py`. That module only:

- removes R27's `R27_MAX_LIVE_OBSERVATION_SECONDS` self-termination timer
  and its callback (production has no native self-timeout; the on-demand
  media lifecycle is already governed by
  `ComelitMediaSessionManager.MEDIA_SESSION_HARD_LIMIT_SECONDS` = 600s in
  `custom_components/comelit/media_session.py`, plus STOP_FILE/SIGTERM/
  SIGINT teardown that R27 already respects);
- raises `R27_MAX_REFRESH_COUNT` from the live-proof value 4 to a
  defense-in-depth backstop of 32 (floor(600/25) == 24 refreshes exhaust the
  600s deadline at the proven 25s cadence; 32 leaves margin so the
  manager's kill remains the real governing bound);
- raises the reporting-only `R27_MAX_SINGLE_SESSION_SECONDS` from 120 to
  600 to mirror that same deadline in the native summary output.

No other behavior changes. Every safety property proven live in R27
(single outstanding refresh, no retry after ack timeout/ambiguous
response, fail-closed teardown, one unchanged upstream ICE/PseudoTCP/
CTPP/RTPC/self-activation session, no new setup path, no Door/Gate
reachability) is inherited unmodified.

This repo change was made **offline only**: no chroot/musl toolchain is
available in this sandbox, so the binary described below has not been
built or executed. This document is the exact command Hermes must run in
an environment with the pinned Alpine 3.24.1 chroot toolchain.

## 2. Preconditions before running the build

- The commit containing this contract, `entrance_p116_r65_production_media_refresh_transform.py`,
  and the residual `VIDEO_RTP_AFTER_LAST_REFRESH` fix in
  `entrance_p116_r27_repeat_001a_transform.py` must be committed (the build
  script's `P80_BUILD_WORKTREE_CLEAN` and `P80_BUILD_EXPECTED_SHA` gates
  require a clean tree at a known commit).
- Generated-source SHA gate to verify offline before spending a chroot
  build: `PYTHONPATH=safety-poc/research/media/v1 PYTHONDONTWRITEBYTECODE=1
  python3 -c "from pathlib import Path; import
  entrance_p116_r65_production_media_refresh_transform as t; import
  hashlib; print(hashlib.sha256(t.transform(Path('safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c').read_text(encoding='utf-8'),
  include_p116=True).encode('utf-8')).hexdigest())"` must print
  `4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c`
  (already verified in this sandbox; re-verify after any further edit).

## 3. Exact build command

```bash
REPO=/root/comelit-door-diag-repo \
BRANCH=<branch containing the committed R65 changes> \
P80_BUILD_EXPECTED_SHA=<git rev-parse HEAD of that commit> \
P80_BUILD_EXPECTED_SOURCE_SHA=4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c \
P80_BUILD_TRANSFORM=safety-poc/research/media/v1/entrance_p116_r65_production_media_refresh_transform.py \
P80_BUILD_INCLUDE_P116=1 \
OUTPUT=/root/comelit-media-r65-build-a \
bash safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
```

Run it a **second time**, independently, with `OUTPUT=/root/comelit-media-r65-build-b`
and everything else identical, then:

```bash
cmp /root/comelit-media-r65-build-a /root/comelit-media-r65-build-b \
  && echo REPRODUCIBLE_BINARY_CMP_GATE=PASS \
  || echo REPRODUCIBLE_BINARY_CMP_GATE=FAIL
sha256sum /root/comelit-media-r65-build-a /root/comelit-media-r65-build-b
```

Both builds must print `P80_HAOS_MEDIA_BUILD=PASS`,
`MUSL_INTERPRETER_GATE=PASS`, `NO_GLIBC_DEPENDENCY=PASS`,
`NO_NEW_RUNTIME_DEPENDENCY=PASS`, and identical `P80_BINARY_SHA256`.

## 4. What must change after a successful build (list every pinned SHA)

Do **not** update these until the double build above is byte-identical and
passes every gate. Then, using the resulting `P80_BINARY_SHA256` (call it
`NEW_SHA`):

1. `custom_components/comelit/native/comelit-media` — replace with the new
   binary (mode 755).
2. `custom_components/comelit/media_transport.py` —
   `MEDIA_NATIVE_BINARY_SHA256 = (...)` (currently
   `a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8`,
   the P106+P116 binary with no refresh capability) → `NEW_SHA`.
3. `safety-poc/tests/test_p80_media_transport_static_contract.py` —
   `EXPECTED_SHA256 = "..."` (line 12) → `NEW_SHA`.
4. A new provenance file,
   `safety-poc/research/media/v1/p116_r65_production_media_build_meta.txt`,
   following the exact schema of
   `safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt`,
   recording: `GENERATED_SOURCE_SHA256`, `NATIVE_BINARY_SHA256=NEW_SHA`,
   size, mode, toolchain, flags, interpreter, needed libs, ELF build id,
   both build SHAs, `reproducible_binary_cmp_gate=PASS`,
   `protocol_behavior_changed=false`, `automatic_retry_added=false`,
   `door_semantics_changed=false`, `gate_semantics_changed=false`,
   `candidate_executed=false`, `LIVE_INVOCATIONS=0`.
5. Re-run `safety-poc/scripts/static_safety_check.py` and the full
   `unittest discover -s tests` after the pin updates, since
   `test_packaged_binary_sha256_is_pinned_and_matches_repository_artifact`
   directly reads the binary file's bytes.

## 5. What this document does not authorize

- No live CT120 attempt against the promoted binary. A live proof of the
  indefinite production scheduler (holding RTP past attempt 3's 115s
  observation bound, under the real 600s manager deadline) is a separate,
  explicitly-authorized future turn.
- No change to `custom_components/comelit/native/comelit-v4` or its build
  path — the persistent listener, Door/Gate actuation, and R64 post-call
  observability are a disjoint build chain
  (`comelit-v4-persistent-ctpp-door.c` compiled directly, or through the
  R42..R64 call-adoption/gate transform chain) untouched by this contract.
