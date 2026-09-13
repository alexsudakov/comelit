# P116 R29 Listener-Attached Media Live Proof

TASK_ID=COMELIT-P116-R29-LISTENER-ATTACHED-MEDIA-LIVE
MODE=CONTROLLED_RESEARCH_LIVE
BASE_SHA=c7a6cd97906c16e8b873529253311ab79c938e6e
LIVE_FACT_SCOPE=ONE_INBOUND_CALL
ONE_RESEARCH_PERSISTENT_SESSION=true
LIVE_RUN=NOT_RUN
RAW_PAYLOAD_EMITTED=false
R29_ARCHITECTURE_LIVE_VALIDATED=false
PRODUCTION_REFACTOR_IMPLEMENTED=false

## Preparation Scope

This corrective preparation updates only the R29 transform, runner, focused tests, and this proof skeleton. It did not stop, start, pause, replace, or contact the production listener, and it did not execute on CT120.

## Source Lineage And Build

LISTENER_SOURCE_LINEAGE=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c

The build script remains `safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh`, invoked by the R29 runner with `P80_BUILD_TRANSFORM=safety-poc/research/media/v1/entrance_p116_r29_listener_attached_media_live_transform.py` and `P80_BUILD_INCLUDE_P116=1`. The builder's `SOURCE_REL` selects `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`, validates `RUN_DIR=/run/comelit-media`, forbids the generated door `SIGUSR1` handler, requires P80 RTP marker strings inherited from the composed P80/P106 lane, enforces the exact generated-source SHA when supplied, builds in Alpine/musl, and gates the ELF interpreter, sorted needed libraries, absence of glibc interpreter/dependency, packaged-library identity, and absence of `/run/comelit-p2p` leakage. R29 satisfies the P80 marker gates as inherited inactive binary strings from the composed media helper; R29's own live selfcheck reports `R29_MEDIA_OPEN_MODEL=BLOCKED` and `R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED`.

R29 generated-source gates additionally require the persistent listener lineage markers, CALL_INIT/ring markers, R29 state/function marker regions, disabled self-activation and client-001A stubs, SIGUSR2 one-shot control, measured counter print formats, scoped forbidden-token absence in the R29/self-activation/client-001A regions, static identifier resolution for the R29 regions, and static identifier ordering for base/composed identifiers referenced by R29. The entrance source identifier is `V4_ENTRANCE`, defined in the base listener at `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:179`; the order gate fails if that or another external identifier is defined at or after its first R29-region use.

## Measured-Scalar Discipline

The candidate must not print literal success acceptance values. `ICE_BOOTSTRAP_COUNT`, `CLOUD_NEGOTIATION_COUNT`, `PSEUDOTCP_OPEN_COUNT`, and `CTPP_REGISTRATION_COUNT` are incremented in the generated C at the gather-start, stable remote SDP import, PseudoTCP open, and CTPP registration-ready paths respectively. The runner snapshots those counters at `RESEARCH_LISTENER_READY` and again after media-only teardown, then computes `ICE_BOOTSTRAP_DELTA_AFTER_READY`, `CLOUD_NEGOTIATION_DELTA_AFTER_READY`, `PSEUDOTCP_OPEN_DELTA_AFTER_READY`, and `CTPP_REGISTRATION_DELTA_AFTER_READY` itself.

Process identity is captured internally at listener readiness and emitted only as same-process booleans. RTP evidence is measured from `p80_video_rtp_packets`, first-video monotonic time, and observation start/end monotonic time. Preservation booleans are derived from same-process state, unchanged after-ready counters, and listener-ready state. Forbidden paths are counters: `SELF_ACTIVATION_SENT_COUNT`, `CLIENT_001A_SENT_COUNT`, `R27_REPEAT_SENT_COUNT`, `DOOR_ACTIONS_SENT`, `GATE_ACTIONS_SENT`, `REFRESH_LOOP_STARTED_COUNT`, `NEW_ICE_BOOTSTRAP_AFTER_READY`, `NEW_CLOUD_NEGOTIATION_AFTER_READY`, `NEW_PSEUDOTCP_AFTER_READY`, and `NEW_REGISTRATION_AFTER_READY`.

## Media Open Model

R29_MEDIA_OPEN_MODEL=BLOCKED

Static evidence proves the official native inbound media RX chain, but not an exact runtime action set that this helper can safely perform for an already-registered inbound call. The supported static chain is `VipUnitImpl::new_call_ctp_conn -> VipUnitImpl::handleCtpStart -> VipUnitImpl::vip_unit_accept_call -> CallFsm::enqueueEvent -> CallFsm::st_idle/go_in_alerting -> CallFsm::start_videorx -> RtpDispatcher::startVideoRX -> ViperTunnel::openMediaRXChannel -> ViperTunnel::openChannel -> viper_tunnel_channel_create` (`safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:423`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:436`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:438`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:439`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:440`).

The composed P80/P106 helper owns RTP forwarding state and self-activation RTPC signaling lineage, but R29 has removed the self-activation and client-001A route. It does not have a proven helper-local equivalent of `CallFsm::start_videorx` or `ViperTunnel::openMediaRXChannel` bound to the live inbound CALL_INIT transaction. Therefore `RTPC_MEDIA_CHANNELS_OPEN` remains a real measured count and live is refused before production handoff.

## Media-Only Teardown Scope

R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED

Static native evidence proves the official media-only close chain `CallFsm::stop_videorx -> RtpDispatcher::stopVideoRX -> ViperTunnel::closeMediaRXChannel` (`safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:164`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:425`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:437`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:441`). The R29 helper only owns local P80 RTP forwarding enablement and local UDP forwarding descriptors. Closing those descriptors is not proof of closing the native media RX channel, and it is not a proven substitute for `closeMediaRXChannel`.

The candidate therefore prints teardown BLOCKED markers and the runner refuses live before stopping the production listener. If a future helper can bind a real media RX channel open and close action to the inbound call, `MEDIA_ONLY_TEARDOWN_COMPLETE` may be printed only after the media RX path is disarmed and transport, registration, same-process, and listener-ready state are rechecked.

## Blocked Conditions

The runner must refuse live before handoff when the candidate selfcheck or generated-source gates report `R29_MEDIA_OPEN_MODEL=BLOCKED` or `R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED`. It must also refuse if the expected commit SHA, generated-source SHA, base wrapper SHA, blob gates, bash syntax gates, wrapper materialisation, or candidate selfcheck fail. The candidate selfcheck is a musl ELF selfcheck and is run inside the Alpine musl rootfs used by the builder, selecting `P80_OFFLINE_ROOTFS` from build provenance first and otherwise the newest `/root/comelit-p80-haos-build-*/rootfs` with `usr/bin/gcc` and `lib/ld-musl-x86_64.so.1`; the candidate is copied only to `/r29-selfcheck/` inside that rootfs and invoked with `chroot`.

## Result Block Skeleton

```text
=== COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE FINAL ===
RESULT=NOT_RUN
DRY_RUN=PENDING
LIVE_INVOCATIONS=NOT_RUN
GENERATED_SOURCE_SHA256=PENDING
CANDIDATE_HELPER_EXECUTED=PENDING
PRODUCTION_LISTENER_RUNNING_BEFORE=PENDING
PRODUCTION_LISTENER_READY_BEFORE=PENDING
PRODUCTION_MEDIA_ACTIVE_BEFORE=PENDING
PRODUCTION_LISTENER_OWNERSHIP_RELEASED=NOT_RUN
RESEARCH_LISTENER_READY_BEFORE_CALL=NOT_RUN
ATTACHED_MEDIA_STARTED=NOT_RUN
VIDEO_RTP_STARTED=NOT_RUN
VIDEO_RTP_PACKETS=NOT_RUN
MEDIA_ONLY_TEARDOWN_COMPLETE=NOT_RUN
LISTENER_STILL_RUNNING_AFTER_10S=NOT_RUN
LISTENER_READY_AFTER_10S=NOT_RUN
ICE_BOOTSTRAP_DELTA_AFTER_READY=NOT_RUN
CLOUD_NEGOTIATION_DELTA_AFTER_READY=NOT_RUN
PSEUDOTCP_OPEN_DELTA_AFTER_READY=NOT_RUN
CTPP_REGISTRATION_DELTA_AFTER_READY=NOT_RUN
MEDIA_TEARDOWN_PRESERVES_TRANSPORT=NOT_RUN
MEDIA_TEARDOWN_PRESERVES_REGISTRATION=NOT_RUN
MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=NOT_RUN
SELF_ACTIVATION_SENT_COUNT=NOT_RUN
CLIENT_001A_SENT_COUNT=NOT_RUN
R27_REPEAT_SENT_COUNT=NOT_RUN
DOOR_ACTIONS_SENT=NOT_RUN
GATE_ACTIONS_SENT=NOT_RUN
REFRESH_LOOP_STARTED_COUNT=NOT_RUN
NEW_ICE_BOOTSTRAP_AFTER_READY=NOT_RUN
NEW_CLOUD_NEGOTIATION_AFTER_READY=NOT_RUN
NEW_PSEUDOTCP_AFTER_READY=NOT_RUN
NEW_REGISTRATION_AFTER_READY=NOT_RUN
R29_MEDIA_OPEN_MODEL=BLOCKED
R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED
PRODUCTION_LISTENER_RUNNING_AFTER=NOT_RUN
PRODUCTION_LISTENER_READY_AFTER=NOT_RUN
PRODUCTION_MEDIA_ACTIVE_AFTER=NOT_RUN
SUCCESS_GATE=NOT_RUN
=== END COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE FINAL ===
```

## Success Gate

SUCCESS_LIVE_PROOF remains defined for a future unblocked model only. It requires one live invocation, production listener ready before handoff, production ownership released before research start, research listener ready before call, inbound CALL_INIT transaction, attached media start, positive video RTP packet count, SIGUSR2 media-only teardown completion, same process after call and media, listener ready after media, zero after-ready ICE/cloud/PseudoTCP/CTPP deltas, production listener restored, and zero forbidden counters.

## What One Run Proves

No live run has been performed. If a future unblocked R29 successor succeeds once, it proves that run only: one inbound entrance call in one research persistent listener session can start attached preview/media, forward video RTP to the local sink, stop media only, preserve the listener, and restore production with no observed new setup after listener readiness. `PRODUCTION_REFACTOR_IMPLEMENTED=false` remains explicit.
