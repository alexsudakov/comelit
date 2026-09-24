# P116 R30H-E repeat 0x001A body offline corrective result

TASK_ID=`COMELIT-P116-R30H-E-REPEAT-BODY-OFFLINE-CORRECTIVE`

Mode: `OFFLINE_ONLY`. This result references the historical R30H-E authorization and does not authorize live Comelit traffic, Home Assistant control, production replacement, Door/Gate action, or candidate `main()` execution.

## Source and locus

- BASE_SHA: `be3fb5265b19a1212054d81f030cb896d7952d54`
- WORKTREE_HEAD observed before edits: `be3fb5265b19a1212054d81f030cb896d7952d54`
- PHASE_A_LOCUS: `R27_REPEAT_CANDIDATE_CONFIRMED`
- Corrective locus: `safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py`

## Verified defect

Current-source defect before the corrective was in `r27_try_queue_repeat_001a`: the repeat path set only `r27_rtpc_client_001a_repeat_len` and then called `p76_generate_client_001a(...)` on the unpopulated repeat buffer. In the current corrected file, the fixed order is visible at `entrance_p116_r27_repeat_001a_transform.py:368-376`: `r27_build_repeat_001a_body()` runs before `p76_generate_client_001a(...)`.

The source role split is unchanged:

- `p76_build_client_001a(...)` constructs the 60-byte client media body, including shape, target, geometry, and roles at `entrance_rtpc_control_media_runtime_transform.py:294-323`.
- `p76_generate_client_001a(...)` validates an already-populated body against runtime allocation #2 and geometry, then marks the fact generated, at `entrance_rtpc_control_media_runtime_transform.py:415-429`.

`R30H_D_GENERATION_FAILURE_STATICALLY_EXPLAINED=true`: a zero or stale repeat buffer could not satisfy the validator checks at `entrance_rtpc_control_media_runtime_transform.py:419-427`.

## Corrective strategy

Chosen strategy: use the already runtime-generated initial `0x001A` body as the same-session semantic template, mutate only the independent CTP sequence byte, then validate the populated repeat with the existing P76 validator.

This is smaller and safer than reallocating RTPC state because it preserves the already-derived target, geometry, role/address semantics, CTPP channel use, ICE, PseudoTCP socket, helper process, and RTPC allocations. No validator rule was removed or relaxed.

Runtime value sources:

- CTPP request/channel: `v4_ctpp_channel_id` used when queueing repeat.
- Initial body bytes: `p78_rtpc_client_001a` and `p78_rtpc_client_001a_len`, produced by the runtime P76/P97 path.
- Target binding: body offset `16`, preserved from the runtime initial body and revalidated against allocation #2.
- Geometry: offsets `24,26,28,30,32`, preserved from the runtime initial body and revalidated by P76.
- Role/address bindings: offsets `40-59`, preserved from the runtime initial body.
- Sequence byte: initial body offset `4`, advanced modulo 256.
- ACK/state byte: initial body offset `5`, explicitly preserved.

No captured target id, channel, address, sequence, or packet literal is promoted to a runtime constant.

## Acceptance markers

- `REPEAT_BODY_BUILD=PASS`: `r27_build_repeat_001a_body()` copies the runtime initial body and advances only offset `4`; tested by `test_repeat_body_build_validate_and_diff_gate`.
- `REPEAT_BODY_VALIDATION=PASS`: validation remains `p76_generate_client_001a(...)` after build, at `entrance_p116_r27_repeat_001a_transform.py:373-382`.
- `REPEAT_BODY_DIFF_GATE=PASS`: `r27_repeat_body_diff_gate()` permits only offset `4` and requires byte `5` and offsets `10-59` unchanged at `entrance_p116_r27_repeat_001a_transform.py:435-453`.
- `CTP_SEQUENCE_ROLLOVER_GATE=PASS`: `test_sequence_rollover_does_not_mutate_ack` proves `0xff -> 0x00` with ACK byte `0x5a` unchanged.
- `DETERMINISTIC_EQUALITY=PASS`: transform output A/B SHA both `7449d477738c1b4a66e9a598d93451caa936b4facfde9919ab935c3335d2a99c`; modified input SHA `5a6723dd42e37a0e22df410d43eaa8995a8fcf672eca4e185dfd58f835e2ecd0` proves the check can flip.
- `TARGET_BINDING_PRESERVED=true`: queued repeat keeps offset `16+` semantics and validator rejects wrong target; harness mutates offset `16` and the diff gate fails closed.
- `GEOMETRY_PRESERVED=true`: offsets `24-32` are preserved by full body copy and validated by P76.
- `ROLE_BINDINGS_PRESERVED=true`: offsets `40-59` are preserved by the diff gate's `memcmp(... + 10, 50)`.
- `SAME_CTPP=true`: repeat queues on `v4_ctpp_channel_id`.
- `NO_NEW_RTPC_OPEN=true`, `NO_NEW_ICE=true`, `NO_NEW_PSEUDOTCP=true`, `NO_NEW_SELF_ACTIVATION=true`: no new setup symbols appear in the R27 repeat segments; focused test `test_no_new_session_setup_paths_in_r27_segments`.
- `VALIDATOR_WEAKENED=false`.
- `CAPTURE_LITERAL_REPLAY=false`.

## Negative tests

Focused negative/fail-closed coverage in `safety-poc/tests/test_p116_r27_repeat_001a_contract.py`:

- `test_repeat_preconditions_fail_closed`
- `test_malformed_repeat_inputs_fail_closed`
- `test_sequence_rollover_does_not_mutate_ack`
- `test_deterministic_repeat_build_flips_when_input_differs`
- `test_third_001a_blocked`
- `test_ack_timeout_absent_no_retry`
- `test_unrelated_ack_does_not_satisfy_repeat_gate`
- `test_no_new_session_setup_paths_in_r27_segments`
- `test_door_and_gate_action_paths_unreachable_from_r27_code`

## Local verification

- `PYTHONPATH=$PWD/safety-poc/src:$PWD/safety-poc/research/media/v1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest safety-poc.tests.test_p116_r27_repeat_001a_contract` -> `Ran 33 tests ... OK`
- `cd safety-poc && python3 scripts/static_safety_check.py` -> `STATIC_SAFETY_CHECK=PASS`
- `python3 -m py_compile safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py safety-poc/tests/test_p116_r27_repeat_001a_contract.py safety-poc/tests/test_mvp1_ring_telegram_offline_build.py` -> PASS
- `bash -n safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh` -> PASS
- `python3 -m compileall -q custom_components/comelit` -> PASS
- Local full suite after Turn 1 pin update: `Ran 2184 tests in 45.211s FAILED (errors=2, skipped=5)`. Residual errors are sandbox-only UDP datagram socket artifacts in `test_p116_r29i_preopen_idle_and_sink_ownership.py`; `NOT_A_R65_REGRESSION`.

## Host verification from Hermes

- BASE SHA `be3fb52` untouched worktree: `Ran 2184 tests`, `FAILED (failures=1, skipped=1)`. Single failure: `tests/test_p116_r29i_preopen_idle_and_sink_ownership.py::test_zero_datagram_sink_materializes_final_counter_after_exit` with `'1' != '0'`, passing 3/3 in isolation. Classification: `PRE_EXISTING_BASELINE_FLAKE`.
- After Turn 1 change on host: `Ran 2184 tests in 41.289s`, `OK (skipped=1)`. `FULL_REGRESSION=PASS`.
- Host static safety: `STATIC_SAFETY_CHECK=PASS`, 29 files scanned.
- Sandbox observation retained: sandbox full suite `Ran 2184 tests in 45.211s FAILED (errors=2, skipped=5)` due to blocked UDP datagram sockets. Classification: `NOT_A_R65_REGRESSION`, root cause `SANDBOX_BLOCKS_UDP_DATAGRAM_SOCKETS`.
- Test-count check: `test_p116_r27_repeat_001a_contract.py` has 33 `def test_` methods at `origin/main` and 33 after this change; total suite count remains 2184 -> 2184. `TESTS_ADDED=0`; coverage was added by extending existing test methods and the embedded C harness cases.

## R30H-E contract marker mapping

Option B is used for the offline harness path: `ct120_run_p116_r30h_c_musl_launcher_offline.sh` now accepts `R30H_C_EXPECTED_CANDIDATE_SHA` from the CT120 host. The R30H-E result maps the normative contract markers to emitted/derived markers as follows:

- `REPEAT_BODY_BUILD`: derived from focused harness `R27_REPEAT_001A_BUILD=PASS`.
- `REPEAT_BODY_VALIDATION`: derived from focused harness `R27_REPEAT_001A_VALIDATION=PASS`; `VALID_REPEAT_BODY_VALIDATION=P76_OK` maps to the same validator return path.
- `REPEAT_BODY_DIFF_GATE`: derived from `R27_REPEAT_BODY_DIFF_GATE=PASS` plus `R27_REPEAT_BODY_CHANGED_OFFSETS=4`.
- `CTP_SEQUENCE_ROLLOVER_GATE`: derived from embedded harness case `test_sequence_rollover_does_not_mutate_ack`.
- `ONE_SHOT_REPEAT_CONTRACT`: derived from `INITIAL_001A_SENT_COUNT`, `REPEAT_001A_SENT_COUNT`, `TOTAL_001A_SENT_COUNT`, `R27_THIRD_001A_BLOCKED`, and `ACK_TIMEOUT_RETRY=false`.
- `CANDIDATE_REPRODUCIBLE`: derived from double transform SHA equality; current A/B SHA `7449d477738c1b4a66e9a598d93451caa936b4facfde9919ab935c3335d2a99c`.
- `CANDIDATE_BUILD`: derived on CT120 from `P80_CHROOT_BUILD_RC=0`, `MUSL_INTERPRETER_GATE=PASS`, `NO_GLIBC_DEPENDENCY=PASS`, `NO_NEW_RUNTIME_DEPENDENCY=PASS`, and the candidate SHA gate.
- `LOADER_PROBE_RESOLUTION`: emitted directly by the offline harness.
- `CANDIDATE_MAIN_EXECUTED=false`: emitted directly by the offline harness.
- `COMELIT_LIVE_EXECUTED=false`: emitted directly by the offline harness; R27 runner refusal mode must return rc 2 with `R27_OFFLINE_SAFE_REFUSAL=true`.
- `REPEAT_TARGET_EQUALS_INITIAL_ALLOCATION_2`: derived from preserved offset `16` and P76 allocation #2 validation.
- `REPEAT_GEOMETRY_PRESERVED`: derived from P76 geometry validation and diff gate preserving offsets `24-32`.
- `REPEAT_ROLE_BINDINGS_PRESERVED`: derived from diff gate preserving offsets `40-59`.
- `THIRD_001A_FAIL_CLOSED`: derived from `R27_THIRD_001A_BLOCKED=true` branch and focused test `test_third_repeat_is_blocked_fail_closed`.
- `NO_NEW_SESSION_SETUP_PATHS`: derived from focused test `test_no_new_session_setup_paths_in_r27_segments`.
- `DOOR_GATE_PATHS_UNREACHABLE`: derived from focused test `test_door_and_gate_action_paths_unreachable_from_r27_code`.

## Host command needed

The CT120 musl gate must run as root on CT120 after Hermes clones the branch to `$REPO` and exports the authoritative pushed head SHA. A commit cannot embed its own SHA, so `R30H_C_EXPECTED_SHA` is supplied by Hermes from the pushed head report. `R30H_C_EXPECTED_CANDIDATE_SHA` is a two-pass pin: omit it or set the old default on pass 1 to record `CANDIDATE_BINARY_SHA256`; set it to that recorded SHA on pass 2 to verify `CANDIDATE_SHA_GATE=PASS`.

```sh
# on CT120, root
cd "$REPO" && R30H_C_OFFLINE_RUN=YES R27_LIVE_RUN=NO REPO="$REPO" R30H_C_EXPECTED_SHA="$EXPECTED_SHA" R30H_C_EXPECTED_SOURCE_SHA=7449d477738c1b4a66e9a598d93451caa936b4facfde9919ab935c3335d2a99c R30H_C_EXPECTED_CANDIDATE_SHA="$EXPECTED_CANDIDATE_SHA" bash safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh
```

Environment sources:

- `REPO`: CT120 branch checkout path.
- `EXPECTED_SHA`: authoritative pushed branch head from Hermes.
- `EXPECTED_CANDIDATE_SHA`: pass-2 value recorded from pass-1 `CANDIDATE_BINARY_SHA256`.

Expected markers include `EXPECTED_SOURCE_SHA_GATE=PASS`, `MUSL_INTERPRETER_GATE=PASS`, `NO_GLIBC_DEPENDENCY=PASS`, `NO_NEW_RUNTIME_DEPENDENCY=PASS`, `CANDIDATE_INTERPRETER_MATCH=PASS`, `LOADER_PROBE_RESOLUTION=PASS`, `CANDIDATE_MAIN_EXECUTED=false`, `GLIBC_RESOLUTION_USED=false`, `WRAPPER_BINDING_GATE=PASS`, `LIVE_INVOCATIONS=0`, `COMELIT_NETWORK_REQUESTS=0`.

## Remaining unknowns

- `CANDIDATE_BUILD=NOT_PROVEN_LOCALLY`: musl/chroot toolchain is unavailable in this sandbox; Hermes must run the CT120 command above.
- `MUSL_INTERPRETER_GATE=NOT_PROVEN_LOCALLY`
- `NO_GLIBC_DEPENDENCY=NOT_PROVEN_LOCALLY`
- `NO_NEW_RUNTIME_DEPENDENCY=NOT_PROVEN_LOCALLY`
- `CANDIDATE_SHA_GATE=NOT_PROVEN_LOCALLY`
- `LIVE_REPEAT_EFFECT=NOT_PROVEN`: no live run was performed or authorized in this phase.
