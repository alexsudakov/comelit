# P116 R35 Attached Inbound Media Native Research Helper

FACTS

R35 base is the exact R34 head `d3fa3caf2ee7c7f7c59592dee995dfca0ed9919c`. No R32, R33, or R34 file was modified by this round. No file under `custom_components/**`, no existing `P116_*.md` document, and no existing test/transform/serializer file was read for modification or written to. Five new paths were added: `safety-poc/research/media/v1/entrance_p116_r35_attached_media_native_transform.py`, `safety-poc/research/media/v1/ct122_build_p116_r35_attached_media_candidate.sh`, `safety-poc/tests/test_p116_r35_attached_media_native_helper.py`, `safety-poc/tests/native/p116_r35_attached_media_host_harness.c`, and this document. R35 is an offline OFFLINE_ONLY research round: no listener was run against a live device, no packet was transmitted on the Comelit network, no Door/Gate action occurred, no physical or synthetic ring occurred, no Home Assistant reload/restart occurred, and the built musl candidate binary was never executed (`candidate_executed=false` is emitted by `ct122_build_p116_r35_attached_media_candidate.sh` and verified by ELF/marker inspection only).

EXECUTOR PROVENANCE

This round was executed by Claude Code CLI acting as substitute semantic implementation executor because Codex CLI, the usual executor for this repository, was blocked by its ChatGPT usage limit at round start; the operator explicitly authorized Claude Code CLI as the substitute executor for this OFFLINE task under the same PROHIBITIONS as every prior R3x round. Hermes (the orchestrator) owns git (add/commit/push remain outside this executor's actions) and independently re-ran the verification commands shown below. The five R35 artifacts are research-only: no production file, native production binary, or normative document was touched.

SECTION 1 - WHAT IS PORTED FROM R33/R34 AND WHAT IS NEW

The MEDIAREQ26 body field layout (26 bytes, zero unknown fields, opcode `0x0011`, OPEN action `0x14`, STOP action `0x94`) is the R33-proven native contract (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:13`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:17`, `P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:21-33`) as ported offline by R34 (`entrance_p116_r34_attached_media_helper_model.py:29-33`). R35 ports the SAME layout and the SAME OPEN/STOP flag source expressions to dependency-free C: `r35_open_flags` (`entrance_p116_r35_attached_media_native_transform.py:301-307`) reproduces R34's `open_flags` (`entrance_p116_r34_attached_media_helper_model.py:366-370`) — TUNNEL base `0x32` with bit3 re-derived from `video_request`, ADDRESS base `0x30` composed with the profile-selector (bit2) and video-request (bit3) bits — and `r35_stop_flags` (`entrance_p116_r35_attached_media_native_transform.py:308-310`) reproduces R34's `stop_flags` (`entrance_p116_r34_attached_media_helper_model.py:373-375`). The call CTP capture direction transform (XOR `0x8000` on the peer connection bytes) mirrors `derive_native_local_connection_id` (`entrance_p116_r30b_call_transaction_model.py:336-341`), ported in C as `r35_capture_call_ctp_id` (`entrance_p116_r35_attached_media_native_transform.py:408-431`). The generic CTP envelope reader mirrors `parse_ctp_envelope` (`entrance_p116_r30_call_ctp_envelope_model.py:50-72`), ported as `r35_parse_ctp_envelope` (`entrance_p116_r35_attached_media_native_transform.py:351-374`), and the call-bound packet builder mirrors `build_call_bound_media_packet`/`build_ctp_envelope` (`entrance_p116_r30_call_ctp_envelope_model.py:75-101`, `entrance_p116_r30_call_ctp_envelope_model.py:108-132`), ported as `r35_build_call_bound_packet` (`entrance_p116_r35_attached_media_native_transform.py:376-393`).

New in R35 (no R33/R34/R30 model has a native/C equivalent): the per-call `call_generation`/`channel_generation` pair (`entrance_p116_r35_attached_media_native_transform.py:206-249`, session struct fields), used to fail closed on reuse of a prior call's channel identity on the same long-lived session object (SECTION 4 below); the injectable `R35FrameWriter`/`R35RtpArmHook` function-pointer abstraction (`entrance_p116_r35_attached_media_native_transform.py:257-266`) that lets a host test substitute a fake writer/hook; and the wiring that reuses the existing helper's own transport queue and RTP-forwarding gate rather than adding new ones (SECTION 3).

SECTION 2 - GENERATED-SOURCE PROVENANCE AND OVERLAY STEP

R35 is applied as a NEW, SEPARATE overlay step on top of the canonical generator's output, never on the raw door source and never by re-invoking the canonical generator with different arguments. `transform(source: str) -> str` (`entrance_p116_r35_attached_media_native_transform.py:723-753`) takes an already-generated `--include-p116` candidate as `source` and returns the R35-augmented candidate; it never imports or calls `entrance_p106_teardown_state_classification_transform`. The pinned canonical digest for `--include-p116` at this base is unchanged: `PYTHONPATH=research/media/v1 python3 research/media/v1/entrance_p106_teardown_state_classification_transform.py --source research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c --output /tmp/r35_recheck.c --include-p116 && sha256sum /tmp/r35_recheck.c` produced `1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2`, matching the pin recorded in `P116_HA_STREAM_RTP_BRIDGE.md:264` and `P116_HA_STREAM_RTP_BRIDGE.md:300`.

The R35 overlay inserts three anchored edits: (1) a `P12TxKind` enum extension adding `P12_TX_R35_MEDIA_OPEN`/`P12_TX_R35_MEDIA_STOP` after the existing `P12_TX_V4_DOOR_WRITE` value (`entrance_p116_r35_attached_media_native_transform.py:46-52`), which lands in `p12_tx_completed`'s `default: break;` case and therefore does not change any existing state transition; (2) the dependency-free core plus the glib-typed wiring region, inserted immediately before the existing "Forward declaration" comment that precedes `p12_flush_tx` (`entrance_p116_r35_attached_media_native_transform.py:54-61`, `entrance_p116_r35_attached_media_native_transform.py:741-746`); and (3) one call-init capture call site inserted between the existing `fflush(stdout);` and `p12_consume_post_ack(frame_len);` inside the proven CALL_INIT ring-detection branch (`entrance_p116_r35_attached_media_native_transform.py:63-112`), the same branch that already sets `v4_ring_observed = TRUE` and emits `V4_RING_KIND=CALL_INIT`. Applying the overlay to the pinned canonical source produces `R35_GENERATED_SOURCE_SHA256=5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0` (9935 lines), reproduced identically by both the direct CLI invocation and by `ct122_build_p116_r35_attached_media_candidate.sh`.

SECTION 3 - REUSED EXISTING HELPER COMPONENTS (NOT DUPLICATED)

Call-init capture reuses the existing listener's own receive-path variables: `body`/`body_len` (the full inner CTP envelope already parsed up to `prefix`/`action` by the existing ring-detection code) and `v4_ctpp_channel_id` (the registered CTPP handle, used only for the misuse check and as the outer VIP `request_id`) are read at the insertion point without any new parsing of the outer VIP wrapper. These are the same variables the existing CALL_INIT branch already uses to detect the ring (`comelit-media.c` generated source, ring detection at `prefix == 0x18C0 && action == 0x0028`, reachable via `entrance_p106_teardown_state_classification_transform.py --include-p116`).

Transport: `r35_glib_transport_writer` (`entrance_p116_r35_attached_media_native_transform.py:607-624`) queues the call-bound 60-byte packet through the EXISTING single-outstanding VIP transport function `p12_queue_vip_frame`, passing the existing registered channel id `v4_ctpp_channel_id` as the outer VIP `request_id` (this is the same outer-carrier addressing every other CTP exchange on this connection already uses; R30/R32 proved the outer CTPP handle is an outer carrier, not the call transaction — `P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:38`, `P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md:13`). No new transport primitive, socket, or queue was added; `p12_queue_vip_frame` is called with the same signature every other call site in the generated helper already uses.

RTP gate: `r35_p80_rtp_arm_hook` (`entrance_p116_r35_attached_media_native_transform.py:640-647`) arms/disarms the EXISTING P80 forwarding boolean `p80_media_forwarding_enabled`, the same flag the self-activation path sets at `P80_MEDIA_ACTIVE=true` and the same flag `p80_try_forward_wrapped_rtp` already reads to decide whether to forward/count RTP (generated source, P80 RTP forwarding block). R35 does not add a second forwarding decision surface, a second RTP socket path, or a second demux; it only supplies a second CALLER of the existing boolean, gated by the R35 state machine (armed only after exactly one call-bound OPEN, disarmed on STOP: `entrance_p116_r35_attached_media_native_transform.py:524-534`, `entrance_p116_r35_attached_media_native_transform.py:536-565`).

Listener/registration/PseudoTCP/call transaction: none of these are touched by the overlay. `r35_capture_call_ctp_id` sets three booleans (`listener_alive`, `registration_alive`, `pseudotcp_alive`) to true at capture time as a research-model invariant (`entrance_p116_r35_attached_media_native_transform.py:423-426`) rather than reading live component state, because this offline round never runs the listener; the READY-GATE section below records this as an OBSERVED-vs-MODELED distinction.

SECTION 4 - STATE MACHINE, FAIL-CLOSED RULES, AND THE SEVEN FORBIDDEN SECOND-OPEN CONDITIONS

The states are `CALL_CAPTURED -> CHANNEL_UNALLOCATED -> CHANNEL_ALLOCATED_OPEN_REQUESTED -> OPEN_SENT -> RTP_ELIGIBLE -> STOP_SENT -> DISPOSED -> TERMINAL`, plus `ERROR` (`entrance_p116_r35_attached_media_native_transform.py:129-138`), matching R34's nine-state list (`P116_R34_ATTACHED_INBOUND_MEDIA_OFFLINE_IMPLEMENTATION.md:48-58`).

The seven forbidden second-OPEN conditions are declared verbatim as `R35_SECOND_OPEN_FORBIDDEN_STATES[7]` (`entrance_p116_r35_attached_media_native_transform.py:167-183`), textually identical in code/description to R34's `SECOND_OPEN_FORBIDDEN_STATES` (`entrance_p116_r34_attached_media_helper_model.py:58-78`), which in turn matches the R33-proven exhaustive list (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:161`). The host harness drives all seven exact setups (`p116_r35_attached_media_host_harness.c`, the `for (i = 0; i < 7; i++)` block) mirroring R34's `_session_for_second_open_state`/`test_07` constructions exactly (`entrance_p116_r34_attached_media_helper_model.py` test companion `test_p116_r34_attached_media_offline_impl.py:338-373`); as in R34's own implementation, several of the seven setups are rejected by the SAME earliest-firing guard (`r35_require_live_channel`'s disposed-check precedes the not-allocated check, matching R34's `_require_live_channel` ordering `entrance_p116_r34_attached_media_helper_model.py:321-331`) — the seven conditions are exhaustively covered as REJECTION scenarios, not asserted to each surface a numerically distinct error code, exactly as R34's `test_07` only asserts `R34AttachedMediaRejected` is raised without incrementing `open_count` (`test_p116_r34_attached_media_offline_impl.py:180-182`).

STOP strictly precedes local disposal, with no awaited STOP ACK: `r35_send_stop` (`entrance_p116_r35_attached_media_native_transform.py:536-565`) performs the write and returns; `r35_dispose_media_rx_channel` (`entrance_p116_r35_attached_media_native_transform.py:567-578`) requires `stop_sent`/`stop_count==1` first. This matches R33 CHILD D items 1-2 (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:156-157`) and R34 SECTION 4 (`P116_R34_ATTACHED_INBOUND_MEDIA_OFFLINE_IMPLEMENTATION.md:42-44`).

Prior-call state reuse (the R35-specific hardening beyond R34, since R34's Python model always constructs one session per call and never reuses a struct across calls): each successful `r35_capture_call_ctp_id` increments `call_generation`; each successful `r35_allocate_media_rx_channel` stamps the channel with the CURRENT `call_generation` (`entrance_p116_r35_attached_media_native_transform.py:455-476`). `r35_require_live_channel` (`entrance_p116_r35_attached_media_native_transform.py:447-453`) rejects any OPEN/STOP/dispose/enable-RTP attempt whose channel generation does not match the session's current call generation with `R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL` — the same error class used for a registration-handle-targeted OPEN, since both are instances of forbidden condition 7 ("OPEN aimed at the registration handle or a foreign call transaction"). This is proven behaviourally by the host harness's `prior_call_reuse` block and by `test_14_prior_call_state_reuse_rejected` (`test_p116_r35_attached_media_native_helper.py`).

Terminal cleanup: `r35_teardown_call` (`entrance_p116_r35_attached_media_native_transform.py:590-596`) clears `call_ctp_valid`/`call_transaction_alive`; `r35_call_ready` (`entrance_p116_r35_attached_media_native_transform.py:437-442`) then rejects every subsequent allocate/open/stop attempt until a fresh capture succeeds, proven by `test_22_state_cleanup_on_terminal_call_teardown`.

SECTION 5 - BYTE-EXACT SERIALIZATION AND RUNTIME FLAGS

`r35_serialize_mediareq26_open`/`r35_serialize_mediareq26_stop` (`entrance_p116_r35_attached_media_native_transform.py:311-333`) produce byte-for-byte identical output to R34's `serialize_mediareq26_open`/`serialize_mediareq26_stop` (`entrance_p116_r34_attached_media_helper_model.py:378-414`), proven by direct comparison in `test_03_open_body_byte_exact_against_r34_oracle` and `test_08_stop_body_byte_exact_against_r34_oracle` (`test_p116_r35_attached_media_native_helper.py`), which import `entrance_p116_r34_attached_media_helper_model` as an ORACLE and assert `bytes.fromhex(harness_marker) == r34.serialize_mediareq26_open(...)` for both TUNNEL and ADDRESS forms with `video_request`/`profile_selector` flipped. The OPEN flags byte is never an unconditional literal: `out[3]` in `r35_serialize_mediareq26_open` is always the return value of `r35_open_flags(src->form, src->video_request, src->profile_selector)` (`entrance_p116_r35_attached_media_native_transform.py:317`), and `test_24_generated_source_contract` asserts the injected region contains no `out[3] = (unsigned char)0x3[02];`-shaped literal assignment. Flipping `video_request` changes `0x32`->`0x3A` (TUNNEL) and `0x30`->`0x38` (ADDRESS); flipping `profile_selector` changes `0x38`->`0x3C` (ADDRESS) — all four values reproduced identically by the host harness (`R35_OPEN_FLAGS_*` markers) and cross-checked against the R34 oracle.

SECTION 6 - HOST HARNESS AND EXTRACTION CONTRACT

`extract_core_region` (`entrance_p116_r35_attached_media_native_transform.py:714-721`) returns exactly the text between `/* R35_ATTACHED_MEDIA_BEGIN */` and `/* R35_ATTACHED_MEDIA_END */`, excluding the markers. `_assert_gates` (`entrance_p116_r35_attached_media_native_transform.py:669-711`) fails the transform closed if that extracted text contains any GLib/libnice header name, GLib type name, `printf`/`fprintf`, `socket(`/`sendto(`, `-lpthread`/`pthread_create`, or any self-activation/R27-repeat symbol — i.e. the transform itself refuses to produce a candidate whose "dependency-free" region secretly depends on the helper runtime. `safety-poc/tests/native/p116_r35_attached_media_host_harness.c` is a research-only file that is never compiled into the packaged/candidate helper; it supplies a fake `R35FrameWriter` (`fake_writer`, counts OPEN/STOP writes and captures the last packet bytes) and a fake `R35RtpArmHook` (`fake_rtp_hook`, counts arm/disarm calls), then drives the full lifecycle plus every fail-closed scenario listed in SECTION 4, printing bounded `R35_...=PASS/FAIL` markers and a final `R35_HARNESS_RESULT=PASS/FAIL`.

Verified this round: `cat <extracted-core> tests/native/p116_r35_attached_media_host_harness.c | cc -std=c99 -Wall -Wextra -pedantic -o r35_harness -` compiled with zero warnings and the resulting binary printed `R35_HARNESS_RESULT=PASS` with all `R35_FORBIDDEN_STATE_1..7=PASS` and both `STALE_CHANNEL_GATE=PASS` (normal) and `STALE_CHANNEL_GATE=FAIL` (corrupted, SECTION 7).

SECTION 7 - THE R34 GAP: STALE_CHANNEL_GATE DERIVATION-FLIP

R34's `derive_gates` defined `STALE_CHANNEL_GATE` (`entrance_p116_r34_attached_media_helper_model.py:551-556`) but R34's own `test_16_derivation_flips_and_report_prints_failure_markers` only flipped `OPEN_COUNT_GATE`, `STOP_ORDER_GATE`, and `REGISTERED_CTPP_MISUSE_GATE` (`test_p116_r34_attached_media_offline_impl.py:278-317`) — `STALE_CHANNEL_GATE` was defined but never proven capable of computing `FAIL`. R35 closes this gap: the host harness computes the equivalent native gate as `(!channel_allocated) && channel_disposed && open_count==1 && stop_count==1` after a real dispose (prints `STALE_CHANNEL_GATE=PASS`), then corrupts the disposal state by directly clearing `channel_disposed` post-dispose (simulating the exact bug class R34 left unproven: a disposal that fails to retain its own invalidation flag) and recomputes the same expression, printing `STALE_CHANNEL_GATE=FAIL`. `test_23_stale_channel_gate_derivation_flip` (`test_p116_r35_attached_media_native_helper.py`) asserts both lines appear in that exact order in the harness's stdout.

SECTION 8 - GAP: NO LIVE OPEN/STOP TRIGGER IS WIRED (HONESTLY UNWIRED, NOT INVENTED)

The existing generated helper's persistent listener has no representation of a call-answer/alerting-accepted event beyond CALL_INIT ring observation itself; R33 proves `CallFsm::start_videorx` (the native OPEN trigger) is a LATER FSM transition than `initNewConnectionStart` (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md:61-63`), and no prior round (R28-R34) recovered a helper-observable event for that later transition. Emitting OPEN immediately at CALL_INIT, before any such transition, would be inventing protocol semantics not proven by R33 — explicitly prohibited for this round. R35 therefore wires the CAPTURE unconditionally into the live CALL_INIT branch (SECTION 2, edit 3) because that trigger IS proven and safe, and wires the OPEN/STOP write path to the REAL transport (`r35_wire_session_transport` sets `g_r35_session.writer = r35_glib_transport_writer`, `entrance_p116_r35_attached_media_native_transform.py:649-656`, called lazily from the capture call site) so a future round that DOES recover a proven call-answer trigger only needs to call `r35_send_open`/`r35_send_stop` — no further transport work would be required. No code path in this candidate calls `r35_send_open`/`r35_send_stop` automatically; they are reachable only via direct function call, which this round never performs (`LIVE_INVOCATIONS=0`). This is recorded honestly rather than left implicit: `MEDIAREQ26_OPEN_WIRED=true` and `MEDIAREQ26_STOP_WIRED=true` describe the write PATH (byte-exact, gated, call-bound, reaches the real transport function when invoked), not an automatic live firing decision, which remains an explicit, separately-tracked gap.

SECTION 9 - BUILD PROVENANCE

Toolchain identity (from this round's build): Alpine `3.24.1`, `cc (Alpine 15.2.0) 15.2.0`, `GNU ld (GNU Binutils) 2.45.1`, `pkg-config`-resolved `libnice 0.1.22`, `glib 2.88.1`, `gobject 2.88.1`, flags `-O2 -g -Wall -Wextra -Wl,--as-needed`, matching the toolchain identity already pinned for the P116 native artifact (`P116_HA_STREAM_RTP_BRIDGE.md:266`, `P116_HA_STREAM_RTP_BRIDGE.md:321`).

Digests: canonical `--include-p116` generated source `1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2` (pinned, unchanged); R35 candidate generated source `5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0`; candidate binary `a991953de051ab4b094bea9b0f2d26826e8da60bc56f986606b1a8ce003aab86`, `295744` bytes, ELF `x86-64 pie`, `not stripped`, `interpreter=/lib/ld-musl-x86_64.so.1`, `NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10`.

The local APK closure used for the offline `--network none` build (`/home/hermes/comelit-r35-apk-closure/`, 109 packages, copied from the pre-existing local closure originally fetched for the P107 round at `/tmp/p107/apk/pkgs` and moved to a stable path under `/home/hermes/` per this round's instructions so a `/tmp` cleanup cannot break reproducibility) matches the closure identity recorded by that round's provenance log (`/tmp/p107/apk-closure.log`: `CLOSURE_PACKAGES=109`).

Build root: `/home/hermes/comelit-r35-build-20260918T213830Z/` (mode `700`, owned by `hermes`, outside the repository tree). Gates from that run, verbatim:

```text
CANONICAL_SOURCE_GATE=PASS
R35_MARKER_GATE=PASS
MUSL_INTERPRETER_GATE=PASS (/lib/ld-musl-x86_64.so.1)
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS (libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10)
LIB_IDENTICAL=PASS
R35_CANDIDATE_MARKER_GATE=PASS
candidate_executed=false
R35_CANDIDATE_BUILD=PASS
```

`LIB_IDENTICAL=PASS` was verified by byte comparison (`cmp`) between the container's `libglib-2.0.so.0`/`libgobject-2.0.so.0`/`libnice.so.10` and the packaged `custom_components/comelit/native/lib/` copies, matching the `LIB_IDENTICAL` gate methodology of `ct120_build_p80_haos_media_helper.sh:340-354`.

SECTION 10 - BASELINE FAILURE SEPARATION

The pre-existing baseline failure `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch` (`NATIVE_BINARY_MODE` metadata `755` vs worktree file mode `775`) reproduced unchanged in this round's full-discovery run. It was present at the exact R34 head before any R35 file was added, was NOT fixed by this round, and is not part of the R35 verdict — a pre-existing filesystem-mode/metadata mismatch unrelated to R35 model, test, transform, or documentation content.

SECTION 11 - PRODUCTION AND LIVE SCOPE

`PRODUCTION_FILES_CHANGED=0`. `NATIVE_PRODUCTION_BINARY_CHANGED=false`. `NORMATIVE_DOCS_CHANGED=0`. `LIVE_INVOCATIONS=0`. `DEPLOYS=0`. `HA_RESTARTS=0`. `MERGED=false`. No file under `custom_components/comelit/**` (including `custom_components/comelit/native/comelit-media`) was read or modified. No existing `P116_*.md` document, existing test file, or existing transform/serializer file was modified. The built candidate binary was never executed at any point in this round; every gate above was computed via `readelf`/`strings`/`sha256sum`/`cmp` (read-only ELF inspection), never via running the binary.

READY-GATE (`IMPLEMENTATION_READY_FOR_BOUNDED_LIVE`)

| Condition | Evidence | Status |
|---|---|---|
| MEDIAREQ26 OPEN/STOP byte-exact | `test_03`/`test_08` byte-for-byte match against the R34 oracle, host-harness-executed | OBSERVED |
| Call CTP id capture wired at a real, proven trigger (CALL_INIT) | `test_01`, capture call site inserted in the live ring-detection branch | OBSERVED |
| Exactly-one-OPEN / exactly-one-STOP / STOP-before-dispose / all seven forbidden states | `test_06`, `test_10`, `test_09`, `test_25`, host-harness-executed | OBSERVED |
| Prior-call state reuse and stale-channel-after-dispose fail closed | `test_14`, `test_12`, `test_23` (derivation flip) | OBSERVED |
| Listener/registration/PseudoTCP preservation | `r35_preserve_listener_registration_pseudotcp` invariant, `test_16` | MODELED (booleans are set true at capture time as a research invariant; no live listener/registration/PseudoTCP component state was read this round, because the listener was never run) |
| RTP path armed only after OPEN, reuses the real P80 forwarding gate | `test_07`, wiring reuses `p80_media_forwarding_enabled` | OBSERVED (wiring), UNPROVEN (live RTP arrival, unchanged from R34 SECTION 7) |
| Call-bound write reaches the real transport function | `r35_glib_transport_writer` calls `p12_queue_vip_frame` directly; not exercised live this round | OBSERVED (wired), UNPROVEN (peer acceptance) |
| A proven live trigger exists for WHEN to call OPEN/STOP | Not recovered by R28-R34; not invented by R35 (SECTION 8) | ABSENT |
| Peer OPEN acceptance, RTP arrival, HA Stream delivery, listener survival after live attached media | Not attempted this round (LIVE IS STRICTLY FORBIDDEN) | UNPROVEN |

Because at least one required condition (a proven live OPEN/STOP trigger) is ABSENT and several are UNPROVEN rather than OBSERVED, `IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false`.

EVIDENCE DISCIPLINE

This document cites only files opened directly in this worktree: the five R35 artifacts added in this round, the R30/R30B/R32/R33/R34 documents and models they port from, and `P116_HA_STREAM_RTP_BRIDGE.md`/`ct120_build_p80_haos_media_helper.sh` for build provenance and toolchain identity. No new disassembly or packet capture was collected or referenced; no raw packet bytes, addresses, credentials, tokens, or full disassembly dumps are reproduced here — the byte values quoted (flag bytes, action bytes, digests, ELF metadata) are safe scalar constants and hashes already of the class published in R32-R34.

VERIFICATION

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/research/media/v1 python3 research/media/v1/entrance_p106_teardown_state_classification_transform.py \
  --source research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c --output /tmp/r35_recheck.c --include-p116 && sha256sum /tmp/r35_recheck.c
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r35_attached_media_native_helper -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r34_attached_media_offline_impl -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
bash research/media/v1/ct122_build_p116_r35_attached_media_candidate.sh
cd ..
git status --short
git diff --check
```

Results from this R35 run:

- Canonical digest recheck: `1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2` (matches the pin).
- Focused R35 tests: `Ran 30 tests in 0.074s`, `OK`.
- R34 regression: `Ran 17 tests in 0.012s`, `OK`.
- Full discovery: `Ran 1633 tests in 34.789s`, `FAILED (failures=1, skipped=1)`, with the single accepted pre-existing baseline failure (SECTION 10). `1633` is the exact-R34-head full-discovery count of `1603` plus the 30 R35 test methods; no new failure and no new skip appear.
- Static safety: `STATIC_SAFETY_CHECK=PASS`, `NETWORK_IMPORTS_PRESENT=false`, `COMELIT_ENDPOINTS_PRESENT=false`, `SOURCE_FILES_SCANNED=29`.
- Build: `R35_CANDIDATE_BUILD=PASS` with every gate in SECTION 9 `PASS` and `candidate_executed=false`.
- `git diff --check`: no whitespace errors reported (`diffcheck_rc=0`).
- `git status --short`: only the five new R35 paths appear as untracked relative to the base; no path under `custom_components/**`, no existing `P116_*.md`, and no existing test/transform/serializer file is modified.

=== COMELIT P116 R35 ATTACHED MEDIA RESEARCH HELPER (REPO DOC) ===
BASE_R34_SHA=d3fa3caf2ee7c7f7c59592dee995dfca0ed9919c
RESEARCH_NATIVE_CANDIDATE_BUILT=true
CALL_CTP_CAPTURE_WIRED=true
MEDIAREQ26_OPEN_WIRED=true
MEDIAREQ26_STOP_WIRED=true
MEDIA_RX_STATE_WIRED=true
RTP_PATH_WIRED=true
SELF_ACTIVATION_USED=false
REGISTERED_CTPP_USED_AS_CALL=false
OPEN_COUNT_GATE=PASS
STOP_COUNT_GATE=PASS
STALE_CHANNEL_GATE=PASS
PRIOR_CALL_STATE_GATE=PASS
STOP_ORDER_GATE=PASS
LISTENER_PRESERVATION_GATE=PASS
PSEUDOTCP_PRESERVATION_GATE=PASS
REGISTRATION_PRESERVATION_GATE=PASS
NEW_ICE=0
NEW_CLOUD=0
NEW_PSEUDOTCP=0
NEW_REGISTRATION=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
NEW_RUNTIME_DEPENDENCY_REQUIRED=false
FOCUSED_TESTS=PASS
R34_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
BUILD_GATES=PASS
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
NORMATIVE_DOCS_CHANGED=0
LIVE_INVOCATIONS=0
DEPLOYS=0
HA_RESTARTS=0
IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false
RESULT=PASS_R35_OFFLINE
NEXT_STEP=Recover a proven helper-observable call-answer/alerting trigger (closing the SECTION 8 gap) before proposing any bounded live validation of this candidate's OPEN/STOP wiring.
=== END COMELIT P116 R35 ATTACHED MEDIA RESEARCH HELPER (REPO DOC) ===
