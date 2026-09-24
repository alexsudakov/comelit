# P116 R65/R30H-E repeat 0x001A corrective result

TASK_ID=`COMELIT-P116-R65-LONG-MEDIA-CUTOFF-CORRECTIVE`

Mode: `OFFLINE_ONLY`. This note records Phase A closure and live-instrument readiness. It does not authorize this sandbox to run live Comelit traffic, Home Assistant control, production replacement, Door/Gate action, official-app research, go2rtc/Frigate/audio-TX, or literal PCAP replay.

## Source and scope

- BASE_SHA: `be3fb5265b19a1212054d81f030cb896d7952d54`
- PHASE_A_COMMITTED_SHA: `565c0f37d4f650d35f5deaec4f17cdbdedaa7316`
- WORKTREE_HEAD_OBSERVED: `565c0f37d4f650d35f5deaec4f17cdbdedaa7316`
- Allowed write scope used: `safety-poc/research/media/v1/**` and `safety-poc/tests/**`
- Current local generated-source SHA after the derived-marker corrective: `e62e83c0b1d426fac9f307c84a8069e1bf2c6e7dae47edf78e1cff6012234887`

## Phase A defect and fix

The Phase A defect was in the R27 repeat path: the repeat buffer was validated before being built. The committed Phase A fix builds the repeat body first, validates it with the unchanged `p76_generate_client_001a()`, then runs the diff gate. The repeat body copies the live runtime initial `0x001A` body and mutates only CTP sequence wire byte offset `4` by `+1 mod 256`; byte `5` and offsets `10-59` must remain identical.

One-shot semantics remain: at most two total `0x001A` sends are allowed, initial plus one repeat. A third `0x001A` path is blocked fail-closed, with no retry loop.

## Hermes-verified CT120 facts

Host CT122 at `565c0f37d4f650d35f5deaec4f17cdbdedaa7316`:

- `python3 -m unittest discover -s tests` -> `Ran 2184 tests` -> `OK (skipped=1)`
- `STATIC_SAFETY_CHECK=PASS`
- Baseline `be3fb52` had one pre-existing flaky failure in `test_p116_r29i...counter`, unrelated.

CT120 offline musl harness, two-pass pin discovery:

- PASS1 placeholder pin: `P80_CHROOT_BUILD_RC=0`; `GENERATED_SOURCE_SHA256=7449d477738c1b4a66e9a598d93451caa936b4facfde9919ab935c3335d2a99c`; `CANDIDATE_BINARY_SHA256=22e37dd68467fb0ce171b71ff53c6df6b31888f1ef4c0e9b37bdc45ed0a03b61` size `281192`; `CANDIDATE_SHA_GATE=FAIL` intended; `NO_GLIBC_DEPENDENCY=PASS`; `NO_NEW_RUNTIME_DEPENDENCY=PASS`; `EXPECTED_SOURCE_SHA_GATE=PASS`.
- PASS2 real pin: `PASS2_RC=0`; `R30H_C_HARNESS_RESULT=PASS`; `CANDIDATE_SHA_GATE=PASS`; `CANDIDATE_INTERPRETER_MATCH=PASS`; `CANDIDATE_NEEDED_LIBS_GATE=PASS`; `MUSL_INTERPRETER_GATE=PASS`; `NO_GLIBC_DEPENDENCY=PASS`; `NO_NEW_RUNTIME_DEPENDENCY=PASS`; `LOADER_PROBE_RESOLUTION=PASS`; `WRAPPER_BINDING_GATE=PASS`; `CANDIDATE_MAIN_EXECUTED=false`; `COMELIT_LIVE_EXECUTED=false`; `COMELIT_NETWORK_REQUESTS=0`; `HA_TOUCHED=false`; `PRODUCTION_LISTENER_TOUCHED=false`; `LIVE_INVOCATIONS=0`; listener PID `19978` unchanged; repo clean.

CT120 pre-live readiness:

- Listener active PID `19978`, up since `2026-09-01`.
- 3/3 status samples: `ok/supervisor_running/running/listener_ready=true`, `last_error=null`, `reconnect_count=26`.
- Base wrapper SHA `a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9` equals runner pin.
- Rootfs `/root/comelit-p80-haos-build-20260909T193410Z/rootfs` and `ld-musl-x86_64.so.1` present.
- Ports `17899/17808/8091` free; 0 established UDP/TCP; 0 campaign processes at baseline.
- Credential state then: `COMELIT_OAUTH_REFRESH_TOKEN_PRESENT=true`, `OAUTH_ACCESS_TOKEN_TTL_SECONDS=-498743`. A `401` on cloud `p2p/start` is credential-state, not a protocol verdict.

## Derived-marker model

The live helper now reports session identity from runtime state rather than literal constants:

- `ICE_NEGOTIATION_COUNT`: derived from `ice_connected && ice_ready && selected_pair_present`.
- `PSEUDOTCP_OPEN_COUNT`: derived from `pseudo_tcp && pseudotcp_open`.
- `CTPP_REGISTRATION_COUNT`: derived from `p78_rtpc_runtime.registered_ctpp_reused == P76_TRUE` and `second_ctpp_open_attempted == P76_FALSE`.
- `RTPC_CLIENT_OPEN_COUNT`: derived from `p78_rtpc_open_1_sent` plus `p78_rtpc_open_2_sent`.
- `SELF_ACTIVATION_COUNT`: incremented in the actual `P12_TX_ENTRANCE_SELF_ACTIVATION` completion path.
- `HELPER_PROCESS_UNCHANGED`: compares `r27_helper_pid_at_media_start` to current `getpid()`.
- `SECOND_MEDIA_SESSION`: derived from the identity counters and process identity.
- `MEDIA_SESSION_IDENTITY_UNCHANGED`: derived conjunction requiring no second session, exactly two RTPC opens, and exactly one self-activation.
- `NEW_RTPC_OPEN` and `NEW_SELF_ACTIVATION`: derived from the same counters.

Focused embedded C harness `test_identity_markers_are_derived_and_flip` mutates the underlying state and proves negative forms for ICE, PseudoTCP, CTPP registration, RTPC open count, self-activation count, helper identity, `SECOND_MEDIA_SESSION`, and `MEDIA_SESSION_IDENTITY_UNCHANGED`. Python test `test_identity_markers_are_not_literal_reporting_constants` rejects the old literal report strings.

## Credential gate

The live runner performs a read-only credential gate before listener status/stop and before any network/media action:

- Tool: `/usr/local/sbin/comelit-oauth-status`
- Markers: `CREDENTIAL_STATUS_PRESENT`, `CREDENTIAL_TTL_SECONDS`, `CREDENTIAL_TTL_GATE`, `CREDENTIAL_REFRESH_REQUIRED`, and `CREDENTIAL_REFUSAL_BEFORE_LISTENER_STOP=true` on refusal.
- Minimum TTL: `CREDENTIAL_MIN_TTL_SECONDS=900`.
- Refusal: `credential_gate || exit 2`, before `=== VERIFY LISTENER READY ===` and before `=== STOP ONLY COMELIT LISTENER ===`.

Refresh command for Hermes on CT120 before attempt 1:

```sh
/usr/local/sbin/comelit-oauth-refresh
/usr/local/sbin/comelit-oauth-status
```

Refresh succeeded only if `CREDENTIAL_STATUS_PRESENT=true`, `OAUTH_ACCESS_TOKEN_TTL_SECONDS >= 900`, and the runner emits `CREDENTIAL_TTL_GATE=PASS` with `CREDENTIAL_REFRESH_REQUIRED=false`.

## Runner acceptance block

The final block in `ct120_run_p116_r27_repeat_001a_live.sh` emits the contract marker names:

`ICE_NEGOTIATION_COUNT`, `PSEUDOTCP_OPEN_COUNT`, `CTPP_REGISTRATION_COUNT`, `SELF_ACTIVATION_COUNT`, `HELPER_PROCESS_UNCHANGED`, `SECOND_MEDIA_SESSION`, `MEDIA_SESSION_IDENTITY_UNCHANGED`, `REPEAT_001A_SENT_COUNT`, `SECOND_001A_RESPONSE`, `SECOND_001A_ACK_CLASSIFICATION`, `NEW_RTPC_OPEN`, `NEW_SELF_ACTIVATION`, `VIDEO_RTP_PAST_40S`, `VIDEO_RTP_PAST_75S`, `VIDEO_PACKET_COUNTER_PROGRESSING`, `MEDIA_ACTIVE_DURATION_SECONDS`, `MEDIA_TEARDOWN`, `LISTENER_RESTORED`, `LISTENER_READY_AFTER`, `CAMPAIGN_PROCESSES_REMAINING`, and `RTP_SINK_PORTS_REMAINING`.

## Local verification

- Focused suite: `PYTHONPATH=$PWD/safety-poc/src:$PWD/safety-poc/research/media/v1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest safety-poc.tests.test_p116_r27_repeat_001a_contract` -> `Ran 36 tests` -> `OK`.
- Canonical local suite: `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests` -> `Ran 2187 tests in 45.332s` -> `FAILED (errors=2, skipped=5)`.
- Canonical delta: `+3` against the Hermes host baseline `Ran 2184 tests`; this Turn 4 corrective adds 3 Python `def test_` methods to the focused contract file, growing it from 33 to 36.
- Canonical local red lines: `test_nonzero_datagram_sink_materializes_final_counter_after_exit` and `test_zero_datagram_sink_materializes_final_counter_after_exit` in `test_p116_r29i_preopen_idle_and_sink_ownership`; classification `NOT_A_R65_REGRESSION` because this sandbox blocks UDP datagram sockets while Hermes reports host pass.
- Static safety: `STATIC_SAFETY_CHECK=PASS`, `NETWORK_IMPORTS_PRESENT=false`, `COMELIT_ENDPOINTS_PRESENT=false`, `SOURCE_FILES_SCANNED=29`.
- Syntax: `py_compile` for changed Python files passed; `bash -n ct120_run_p116_r27_repeat_001a_live.sh` passed.

## Live verdict

`LIVE_VERDICT=GO_LIVE` only after Hermes satisfies the credential precondition on CT120 and confirms the branch head is the intended committed Turn 4 state. The live budget is fixed: `MAX_LIVE_MEDIA_SESSIONS=10`, `MAX_PARALLEL=1`, `MAX_SINGLE_SESSION_SECONDS=120`, `AUTOMATIC_RETRY=false`, panel `entrance`, no physical ring/button, `DOOR_ACTIONS=0`, `GATE_ACTIONS=0`, no go2rtc/Frigate/Gate-media/audio-TX, no official-app research, and no literal PCAP replay.

Attempt command block for CT120:

```sh
cd /root/comelit-r65-a-offline
/usr/local/sbin/comelit-oauth-refresh
/usr/local/sbin/comelit-oauth-status
R27_LIVE_RUN=YES REPO=/root/comelit-r65-a-offline R27_EXPECTED_COMMIT_SHA="$EXPECTED_SHA" bash safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
```

Attempt classification markers: `CREDENTIAL_TTL_GATE=PASS`, `REPEAT_001A_SENT_COUNT=1`, `SECOND_001A_RESPONSE`, `SECOND_001A_ACK_CLASSIFICATION`, `VIDEO_RTP_PAST_40S`, `VIDEO_RTP_PAST_75S`, `VIDEO_PACKET_COUNTER_PROGRESSING`, `MEDIA_ACTIVE_DURATION_SECONDS`, `SECOND_MEDIA_SESSION=false`, `MEDIA_SESSION_IDENTITY_UNCHANGED=true`, `NEW_RTPC_OPEN=false`, `NEW_SELF_ACTIVATION=false`, `MEDIA_TEARDOWN=CONFIRMED`, `LISTENER_RESTORED=true`, `LISTENER_READY_AFTER=true`, `CAMPAIGN_PROCESSES_REMAINING=NONE`, and `RTP_SINK_PORTS_REMAINING=0`.

## NOT_PROVEN

- `ROOT_CAUSE_STATUS=PARTIAL`: the body-build-before-validation defect is proven and fixed offline; long-media cutoff effect still needs the live attempt.
- `REPEAT_001A_EFFECT_STATUS=UNTESTED`: no live attempt has been run after the Turn 4 derived-marker and credential-gate corrective.
- `CURRENT_TURN4_MUSL_GATE=NOT_PROVEN`: prior CT120 musl gate passed for generated source `7449d477...`; the current local generated source is `e62e83c...` and needs Hermes rerun after commit.
- `LIVE_REPEAT_RESPONSE=NOT_PROVEN`
- `VIDEO_RTP_PAST_75S=NOT_PROVEN_LIVE`
- `MEDIA_SESSION_IDENTITY_UNCHANGED=NOT_PROVEN_LIVE`
- `LISTENER_RESTORED=NOT_PROVEN_LIVE`
