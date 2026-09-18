# P116 R34 Attached Inbound Media Offline Implementation

FACTS

R34 base is the exact R33 head `b993db6f8766d278b770754b8c82c3545e417808`. No R32 or R33 file was modified by this round. Only three paths were added: `safety-poc/research/media/v1/entrance_p116_r34_attached_media_helper_model.py`, `safety-poc/tests/test_p116_r34_attached_media_offline_impl.py`, and this document. R34 is offline static/model research only: it did not run a listener, transmit on the Comelit network, reload Home Assistant, touch Door/Gate, deploy, or mutate the native `comelit-media` binary.

EXECUTOR PROVENANCE

The model (`entrance_p116_r34_attached_media_helper_model.py`) and the 17-test module (`test_p116_r34_attached_media_offline_impl.py`) were written by a Codex CLI session acting as the R34 semantic implementation executor; that session was cut off by its ChatGPT usage limit before it could author this closing document, leaving the round partially landed (`wip(research): R34 attached media offline impl - partial` commit `12e37c4`). This document was authored by Claude Code CLI acting as substitute semantic executor for the remaining delta, under the same offline contract and the same PROHIBITIONS as the original round. The orchestrator (Hermes) performed all host-side verification runs shown below and owns git (add/commit/push remain outside this executor's actions).

SECTION 1 - MEDIAREQ26 BODY FIELD LAYOUT AND OPEN/STOP FLAG SOURCE EXPRESSIONS

`MEDIAREQ26_BODY_LENGTH=26` and `MEDIAREQ26_UNKNOWN_FIELDS=0` (`entrance_p116_r34_attached_media_helper_model.py:29`, `entrance_p116_r34_attached_media_helper_model.py:30`), matching the R33-proven native field layout (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:13`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:17`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:35`).

The OPEN flags byte is a computed source expression, not a literal, implemented in `open_flags` (`entrance_p116_r34_attached_media_helper_model.py:366-370`):

- TUNNEL form: base `0x32` with bit3 cleared then re-set from the video-request bit — `(0x32 & ~0x08) | (0x08 if video_request else 0x00)`.
- ADDRESS form: base `0x30` composed with the profile-selector bit (bit2, `0x04`) and the video-request bit (bit3, `0x08`) — `0x30 | (0x04 if profile_selector else 0x00) | (0x08 if video_request else 0x00)`.

This mirrors the R33-proven native source expression: bit1 is the address-vs-channel selector, bit3 is derived from `start_videorx` bit1 in both OPEN forms, and bit2 in address-form OPEN is sourced from `CallFsm+812` (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:23`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:48-50`). `0x32` is NOT treated as a universal OPEN literal in this model: it appears only as the TUNNEL base term inside `open_flags`, and every emitted flags byte is computed from `form`/`video_request`/`profile_selector` (`entrance_p116_r34_attached_media_helper_model.py:366-370`, `entrance_p116_r34_attached_media_helper_model.py:382-386`). The focused test suite proves the flags byte changes when the video-request or profile-selector inputs change and is never a hardcoded constant across forms (`test_p116_r34_attached_media_offline_impl.py:116-136`).

STOP flags are also a computed source expression, implemented in `stop_flags` (`entrance_p116_r34_attached_media_helper_model.py:373-375`): `0x02` for TUNNEL, `0x00` for ADDRESS, matching the R33-proven STOP flags (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:23`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:51`).

SECTION 2 - CALL CTP ID CAPTURE, STORAGE, AND LIFETIME

`capture_call_ctp_id_from_call_init` reads bytes `2..3` of the inbound CTP header from the CALL_INIT packet and passes them through `derive_native_local_connection_id`, which performs the direction transform proven by R32/R33 (`entrance_p116_r34_attached_media_helper_model.py:469-473`, `P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md:13`, `P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md:15`, `P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md:29-31`).

The captured id is stored only in the bounded per-call `R34AttachedMediaSession.call_ctp_id` field, alongside a `call_ctp_valid` boolean (`entrance_p116_r34_attached_media_helper_model.py:118-124`). `create_session_at_call_barrier` asserts the captured id matches the transaction's own local connection id before constructing the session, so a session can never carry a stale or mismatched capture (`entrance_p116_r34_attached_media_helper_model.py:476-490`).

The captured id is invalidated at call-transaction end: `end_call_transaction` clears `call_ctp_valid` to `False` and marks `call_transaction_alive` `False` in the same step (`entrance_p116_r34_attached_media_helper_model.py:280-284`). `_require_call_ready`, which gates every channel allocation and OPEN, re-checks `call_ctp_valid`, the call signaling barrier phase, and that the stored id still equals the transaction's live connection id on every call (`entrance_p116_r34_attached_media_helper_model.py:310-319`).

The call CTP id is strictly distinct from the outer persistent CTPP handle: `_require_call_ready` explicitly rejects a session whose captured id equals the outer registration handle expressed as a connection value (`entrance_p116_r34_attached_media_helper_model.py:317-319`, `entrance_p116_r34_attached_media_helper_model.py:648-651`), and `send_open` independently refuses `use_registration_handle=True` before any other check (`entrance_p116_r34_attached_media_helper_model.py:201-205`, `entrance_p116_r34_attached_media_helper_model.py:293-294`). OPEN/STOP are never sent on the registration handle: `test_06_registration_handle_open_rejected_without_write` proves the rejection path performs zero additional writer writes (`test_p116_r34_attached_media_offline_impl.py:166-172`), and `test_05_open_stop_bind_to_direction_transformed_call_ctp_id` proves both OPEN and STOP packets carry the call transaction connection, never the outer CTPP handle value (`test_p116_r34_attached_media_offline_impl.py:156-164`).

SECTION 3 - OPEN ORDER

The model enforces local media RX channel allocation before OPEN: `allocate_media_rx_channel` requires call readiness and an unallocated, non-disposed channel, then transitions to `STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED` (`entrance_p116_r34_attached_media_helper_model.py:178-192`). `send_open` then requires a live channel matching the OPEN's `media_channel_id` before it will serialize and intercept the packet (`entrance_p116_r34_attached_media_helper_model.py:194-214`, `entrance_p116_r34_attached_media_helper_model.py:286-308`). Exactly one call-bound MEDIA_REQUEST OPEN is permitted per session: `_reject_open_if_forbidden` rejects a second OPEN whenever `open_pending`, `open_count`/`video_rx_active`/`open_confirmed`, `stop_count`/`stop_sent`, or `channel_disposed` is already true (`entrance_p116_r34_attached_media_helper_model.py:301-308`). RTP may proceed only after `send_open` (`entrance_p116_r34_attached_media_helper_model.py:231-236`), matching the R33-proven native order of local RX setup then exactly one OPEN call site (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:67`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:84`).

There is no mandatory channel-open-response gate before OPEN or before RTP: `send_open` and `enable_rtp` never call or wait on `observe_channel_open_response` (`entrance_p116_r34_attached_media_helper_model.py:194-236`), matching the R33 proof that native emits OPEN before any required `onChannelOpenRes` wait and does not gate first RTP on that response (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:76`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:86`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:95-97`). A late response correlates only with the correct local channel state and can never enable a stale/wrong-channel transition: `observe_channel_open_response` calls `_require_live_channel`, which fails closed on a disposed channel, an unallocated channel, or a channel id/token mismatch (`entrance_p116_r34_attached_media_helper_model.py:216-229`, `entrance_p116_r34_attached_media_helper_model.py:321-331`), proven by `test_09_wrong_and_stale_channel_uses_rejected` (`test_p116_r34_attached_media_offline_impl.py:190-203`).

SECTION 4 - STOP ORDER

`send_stop` requires exactly one prior OPEN and active video RX state before it will serialize and intercept the call-bound STOP, and rejects a second STOP (`entrance_p116_r34_attached_media_helper_model.py:238-251`). `dispose_media_rx_channel` requires exactly one STOP already sent before it will tear down the local channel token/id (`entrance_p116_r34_attached_media_helper_model.py:253-266`), so STOP always precedes local media RX disposal, matching the R33-proven native order (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:156`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:172`). There is no awaited STOP ACK: `send_stop` returns immediately after the intercepted write with no response-wait call (`entrance_p116_r34_attached_media_helper_model.py:238-251`), matching the R33 finding that no STOP ACK wait is visible in the native path (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:157`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:166`).

The channel token/id is invalid after disposal: `dispose_media_rx_channel` records the disposed id/token, sets `local_channel = None` and `channel_disposed = True` (`entrance_p116_r34_attached_media_helper_model.py:253-266`), after which `_require_live_channel` rejects any further use of that id/token (`entrance_p116_r34_attached_media_helper_model.py:321-331`), proven by `test_09_wrong_and_stale_channel_uses_rejected` rejecting `enable_rtp` after disposal (`test_p116_r34_attached_media_offline_impl.py:202-203`). The persistent listener, registration, PseudoTCP, and call transaction stay alive across the whole trace: `preserve_listener_registration_pseudotcp_call` asserts all four `*_alive` flags remain `True` after disposal and only then appends the preservation event (`entrance_p116_r34_attached_media_helper_model.py:268-278`), proven by `test_12_persistent_listener_registration_pseudotcp_call_preserved` (`test_p116_r34_attached_media_offline_impl.py:227-233`).

SECTION 5 - HELPER-LOCAL STATE MODEL

The model defines nine helper-local states (`entrance_p116_r34_attached_media_helper_model.py:37-45`):

1. `CALL_TRANSACTION_CAPTURED`
2. `MEDIA_CHANNEL_UNALLOCATED`
3. `CHANNEL_ALLOCATED_OPEN_REQUESTED`
4. `MEDIA_OPEN_EMITTED`
5. `MEDIA_ACTIVE_RTP_ELIGIBLE`
6. `MEDIA_STOP_EMITTED`
7. `MEDIA_CHANNEL_DISPOSED`
8. `TERMINAL`
9. `ERROR`

The seven forbidden second-OPEN conditions are enumerated in `SECOND_OPEN_FORBIDDEN_STATES` (`entrance_p116_r34_attached_media_helper_model.py:58-78`), matching the R33-proven exhaustive fail-closed list (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:161`):

1. `NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER` - no call-transaction capture / no call signaling barrier.
2. `NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED` - no local media RX channel / id allocated.
3. `OPEN_ALREADY_PENDING` - OPEN already pending.
4. `OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED` - OPEN already emitted/active or confirmed.
5. `STOP_ALREADY_SENT` - STOP already sent.
6. `MEDIA_CHANNEL_ALREADY_DISPOSED` - media channel already disposed.
7. `REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION` - OPEN aimed at the registration handle or a foreign call transaction.

`test_07_second_open_rejection_iterates_all_seven_conditions` drives each of the seven conditions through a fresh session and asserts `send_open` raises `R34AttachedMediaRejected` without incrementing `open_count` (`test_p116_r34_attached_media_offline_impl.py:174-182`).

SECTION 6 - COUNTER GATES AND NETWORK ISOLATION

`R34AttachedMediaSession.open_count` and `.stop_count` are read-only properties backed by `InterceptedWriter.intercepted_media_open_writes` / `intercepted_media_stop_writes` (`entrance_p116_r34_attached_media_helper_model.py:170-176`), so `OPEN_COUNT<=1` and `STOP_COUNT<=1` are counted from the same intercepted-write ledger checked by `derive_gates` (`entrance_p116_r34_attached_media_helper_model.py:578-579`). The happy-path trace produces exactly one MEDIA_OPEN write and one MEDIA_STOP write (`test_p116_r34_attached_media_offline_impl.py:80-81`), and `test_16_derivation_flips_and_report_prints_failure_markers` proves the gate flips to `FAIL` when a duplicate OPEN write is injected (`test_p116_r34_attached_media_offline_impl.py:278-282`).

`NETWORK_TX=0`: `R34AttachedMediaSession.network_tx` is a hardcoded `0` property (`entrance_p116_r34_attached_media_helper_model.py:142-144`), and all wire writes are intercepted by `InterceptedWriter.intercept`, an in-memory fake writer from the R30B model with no socket/send/network call in its call chain (`entrance_p116_r34_attached_media_helper_model.py:350-359`). `test_14_no_real_tx_and_source_scan_stays_offline` asserts `session.writer.network_writes == 0` and greps the combined model/test/doc source for `socket`, `ssl`, `http`, `urllib`, `requests`, `aiohttp`, and `subprocess` imports, plus IPv4-literal and `curl`/`nc` invocation patterns, none of which are present (`test_p116_r34_attached_media_offline_impl.py:243-262`).

SECTION 7 - WHAT IS IMPLEMENTED OFFLINE VS WHAT REMAINS UNPROVEN LIVE

Implemented and offline-proven in this round: exact 26-byte MEDIAREQ26 OPEN/STOP body serialization and parsing with zero unknown fields (`entrance_p116_r34_attached_media_helper_model.py:378-436`); call CTP id capture from CALL_INIT bytes `2..3` with direction transform reuse from R30B (`entrance_p116_r34_attached_media_helper_model.py:469-473`); a bounded per-call session state machine enforcing exactly-one-OPEN, exactly-one-STOP, STOP-before-disposal ordering, and all seven second-OPEN fail-closed conditions (`entrance_p116_r34_attached_media_helper_model.py:117-336`); and preservation of the persistent listener/registration/PseudoTCP/call-transaction booleans across the full trace (`entrance_p116_r34_attached_media_helper_model.py:268-278`).

Not proven and not attempted live in this round: no physical or synthetic ring occurred, no packet was ever sent to a Comelit device, no peer acceptance of any OPEN/STOP was observed, no RTP was ever received, and no HA Stream/recording/listener-survival-after-live-media claim is made. R33 CHILD F already established `LOW_LEVEL_PRIMITIVES_AVAILABLE=false` for calling vendor `ViperTunnel`/`RtpDispatcher` primitives directly from the packaged helper runtime ABI (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:133`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:217-220`); R34 does not change that ABI finding and does not add or call any vendor library. Live readiness for physical attachment (peer OPEN acceptance, RTP arrival counts, HA Stream delivery, recording completion, and listener survival after a live attached call) remains unproven and is out of scope for this offline round, matching the R32 CHILD 5 observability plan that defers those claims to a future bounded live validation (`P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md:203-283`).

SECTION 8 - BASELINE FAILURE SEPARATION

The pre-existing baseline failure `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch` (`NATIVE_BINARY_MODE` metadata `755` vs worktree file mode `775`) is a baseline artifact already present at the exact R33 head, before any R34 file was added. It was NOT fixed in R34 and is not part of the R34 verdict; it is a pre-existing filesystem-mode/metadata mismatch unrelated to the R34 model, test, or documentation content.

SECTION 9 - PRODUCTION AND LIVE SCOPE

`PRODUCTION_FILES_CHANGED=0`. `NATIVE_PRODUCTION_BINARY_CHANGED=false`. `DEPLOYS=0`. `HA_RESTARTS=0`. `LIVE_INVOCATIONS=0`. `MERGE=false`. No file under `custom_components/comelit/**` was read, written, or otherwise modified by this round; no existing `P116_*.md` document was modified; no existing test file was modified.

VERIFICATION

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r34_attached_media_offline_impl -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q research/media/v1/entrance_p116_r34_attached_media_helper_model.py tests/test_p116_r34_attached_media_offline_impl.py
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 research/media/v1/entrance_p116_r34_attached_media_helper_model.py
cd ..
git status --short
git diff --check
```

Results from this R34 run:

- Focused R34 tests: `Ran 17 tests in 0.006s`, `OK`.
- Full discovery: `Ran 1603 tests`, `FAILED (failures=1, skipped=1)`, with the single accepted pre-existing baseline failure `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`. The count of `1603` is the exact-base full-discovery count of `1586` plus the 17 R34 test methods, and the R34 `setUpClass` error present before this document existed no longer occurs.
- Static safety: `STATIC_SAFETY_CHECK=PASS`, `NETWORK_IMPORTS_PRESENT=false`, `COMELIT_ENDPOINTS_PRESENT=false`.
- `compileall` on the model and test module: success, no syntax/compile errors.
- Direct model execution (`python3 entrance_p116_r34_attached_media_helper_model.py`) printed the `=== COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION ===` marker block with `CALL_CTP_CAPTURE_IMPLEMENTED=true`, `MEDIAREQ26_SERIALIZER_IMPLEMENTED=true`, `MEDIAREQ26_OPEN_IMPLEMENTED=true`, `MEDIAREQ26_STOP_IMPLEMENTED=true`, `MEDIA_RX_STATE_IMPLEMENTED=true`, and every gate/`NEW_*`/`NETWORK_TX`/`DOOR_ACTIONS`/`GATE_ACTIONS` line `PASS` or `0` (`entrance_p116_r34_attached_media_helper_model.py:599-625`).
- `git diff --check`: no whitespace errors reported.
- `git status --short`: only the three new R34 paths appear as untracked/added relative to the base; no path under `custom_components/**` or any existing `P116_*.md`/test file is modified.

EVIDENCE DISCIPLINE

This document cites only files opened directly in this worktree: the R34 model and test module added in this round, and the R32/R33 documents that record the proven native contract this model implements offline. No new disassembly, packet capture, or live evidence was collected or referenced. No raw packet bytes, addresses, credentials, tokens, or full disassembly dumps are reproduced here; only role-level field descriptions and safe scalar constants already published in R32/R33 are restated. No production implementation, no `custom_components/**`, no native production binary, and no other existing `P116_*` document was modified by this run.

=== COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION (REPO DOC) ===
BASE_R33_SHA=b993db6f8766d278b770754b8c82c3545e417808
CALL_CTP_CAPTURE_IMPLEMENTED=true
MEDIAREQ26_SERIALIZER_IMPLEMENTED=true
MEDIAREQ26_OPEN_IMPLEMENTED=true
MEDIAREQ26_STOP_IMPLEMENTED=true
MEDIA_RX_STATE_IMPLEMENTED=true
OPEN_COUNT_GATE=PASS
STOP_COUNT_GATE=PASS
REGISTERED_CTPP_MISUSE_GATE=PASS
STALE_CHANNEL_GATE=PASS
STOP_ORDER_GATE=PASS
LISTENER_PRESERVATION_MODEL=PASS
NEW_ICE=0
NEW_CLOUD=0
NEW_PSEUDOTCP=0
NEW_REGISTRATION=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
FOCUSED_TESTS=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
LIVE_INVOCATIONS=0
DEPLOYS=0
HA_RESTARTS=0
IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false
RESULT=PASS_R34_OFFLINE
NEXT_STEP=Request a bounded live attached-call validation per the R32 CHILD 5 observability plan before any production wiring.
=== END COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION (REPO DOC) ===
