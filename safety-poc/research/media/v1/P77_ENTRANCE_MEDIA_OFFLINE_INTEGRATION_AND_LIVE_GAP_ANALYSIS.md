# P77 Entrance Media Offline Integration And Live Gap Analysis

TASK_ID=COMELIT-P77-ENTRANCE-MEDIA-OFFLINE-INTEGRATION-AND-LIVE-GAP-ANALYSIS
MODE=RESEARCH_DEV
EXECUTION_MODE=OFFLINE_ONLY
BASE_MAIN_SHA=59efa4ac8ce9b1cf4316fc87ef8389437429266e
P77_RUN1_STATUS=HARVEST_COMPLETE
P77_RUN2_STATUS=IMPL_COMPLETE
H264_EXTRACTION=PROVEN_OFFLINE
H264_DECODABILITY=PROVEN_OFFLINE
AUDIO_PATH=PROVEN_OFFLINE
RTPC_RECEIVE_PATH_STATIC_PROVENANCE=PARTIAL
DEVICE_0008_ROLE=CAPTURE_VALIDATED
DEVICE_0008_ACK_GATE=NOT_PROVEN
TEARDOWN_SIGNATURE=PROVEN_OFFLINE
LISTENER_STOP_REQUIRED=NOT_PROVEN
RAW_PAYLOAD_EMITTED=false
MEDIA_PAYLOAD_EMITTED=false
AUTH_OR_SESSION_MATERIAL_EMITTED=false
NETWORK_IO_PERFORMED=false
LIVE_TRANSMISSION_AUTHORIZED=false
DOOR_ACTION_SENT=false
SELF_ACTIVATION_SENT=false
MEDIA_SIGNALING_SENT=false
ACK_SIGNALING_SENT=false

## Baseline

FACT: целевая архитектура остается direct Home Assistant integration с persistent Comelit P2P session; CT120 является историческим/переходным контекстом, а не production target. FACT: entrance media on-demand, один media session, max 180 s, cleanup idempotent, listener independent until proven otherwise. P76 остановился на offline RTPC CONTROL/media generation parity и явно не доказывал payload/media start.

P77 является additive-only интеграцией: исторические Pxx артефакты не переписаны. Supersession/rejection выражены только в новых P77 артефактах.

## Evidence Sources

FACT: `.p77-work/HARVEST.md` является authoritative evidence matrix для P77 Run 2. Frozen capture gate: `.p77-input/pcap/self_activation.pcap` SHA256 `f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a`. Secondary contrast capture: `.p77-input/pcap/p2p_rtsp.pcap` SHA256 `62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3`.

Static gates из harvest: `libcomelitvipkit.so` SHA256 `2fe212c8ee2ecce8f64c556af01e91d148b3e7a001876d159c84ac50611476c1`; `classes7.dex` SHA256 `851afb335a731c54e46ec39eb214a532c21c695eda6ce62de246b8d750e8f407`; `classes8.dex` SHA256 `05864bb668f26a7344217373f1d56fc8d38f71e92bf82f2cc9d82f20472c33ea`. `libvipcomelit.so`, `libsafecomelit.so`, `classes9.dex` использованы только через bounded symbol/string evidence из `.p77-work/outputs/`.

## P46 To P76 Provenance Chain

OBSERVED через `git log --oneline -- <path>`: `8c0e12b` добавил entrance signaling probe transform; `3dea9b6` добавил offline device-video ACK pcap forensic; `08a8b44` исправил capture-derived ACK address roles; `0684110` добавил post-ACK structural timeline; `4a6584c`, `9a8d8c7`, `32557b8`, `78caf05` сформировали offset-8 RTP inventory/codec-shape линию P57-P59. RTPC lineage: `fa92575` P68 control pairing; `490ea20` P69 trailer observation; `11ffeab` P70/P71 static transport contract; `9f69938` corrected P69/P70 attribution; `62bacfb` P72 generation boundary; `496c931` P73 target-id allocator contract; `9d5332e` P74 allocator-backed generation; `039e925` P75 state machine; `554b882` P76 C runtime parity.

## New Static Findings

PROVEN_STATIC_SYMBOL: `entrance_p77_receive_path_static_contract.py` promotes bounded function inventory only: `VipEngine.addReceivedPacketFromSocket`, `ComelitEngine::sysViperAddReceivedPacketFromSocket`, `ViperTunnel::setReceivedCbk`, `ViperTunnel::onNewIncomingChannel`, `ViperTunnel::openMediaRXChannel/closeMediaRXChannel`, `RtpDispatcher::threadVideoRX/threadAudioRX`, and `VipEngine.closeChannel`.

PARTIAL: exact call graph from `viper_tunnel_inject_tcp` to per-channel callback invocation remains unresolved. PARTIAL: whether RTPC receive is dedicated thread, tunnel callback, or hybrid remains unresolved. NOT_PROVEN: any requirement to stop the persistent listener before media.

## Frozen-Capture Findings

OBSERVED: `self_activation.pcap` contains a complete media session after packet 218. P77 reuses existing analyzers for selected-flow parsing and classifies post-218 opaque UDP as offset-8 wrapped RTP. OBSERVED counts from harvest: 3229 opaque datagrams, 3221 RTP-shaped, 8 residual 14-byte datagrams, 3 streams.

PROVEN_OFFLINE: PT99 DEVICE_TO_CLIENT video stream contains 1210 packets and 1165369 RTP media bytes before Annex-B start-code expansion. PROVEN_OFFLINE: PT8 DEVICE_TO_CLIENT audio stream contains 1205 packets of 160 media bytes each; PT8 CLIENT_TO_DEVICE stream contains 806 packets of 160 media bytes each.

## RTPC Receive Path

OBSERVED: RTPC CONTROL exchange appears around packets 205-212 in the same capture before offset-8 RTP media. STATIC_PARTIAL: native ingress and callback/channel functions exist, and media RX worker functions exist. NOT_PROVEN: exact static field or callback binding from CONTROL channel to the offset-8 RTP wrapper.

## Device 0x0008 Role

CAPTURE_VALIDATED: device `0x0008` appears as CTPP-side pre-RTPC device video event at packet 200 with body_len 40, prefix `0x1840`, flags `0x0003`; first 32-byte `0x1800` structural ACK follows at packet 201, CLIENT_TO_DEVICE, +20.481 ms.

REJECTED_BY_P77: `0x1800` is a uniquely video-only ACK. It also follows device `0x0002` and device `0x000a`. REJECTED_BY_P77: `0x0008` is part of RTPC ABCD CONTROL. Packet ordering places RTPC OPENs later. NOT_PROVEN: ACK after device `0x0008` gates media start.

## Media Framing

PROVEN_OFFLINE for `self_activation.pcap`: media region is fixed offset-8 RTPv2 wrapper, not RTP at UDP byte 0. The wrapper has structural length and per-stream invariant fields, but full wrapper field semantics are PARTIAL. PT99 maps to H264 packetization shape; PT8 maps to RTP/AVP PCMA 8000 mono by static mapping and cadence.

## Video / H264 Findings

Implemented tool: `entrance_p77_offset8_h264_extraction_contract.py`. It handles single NAL, STAP-A, and FU-A. Unknown shapes, malformed RTP, bad wrapper length/profile, truncated STAP/FU, FU-A missing start, sequence gap inside open AU, and timestamp discontinuity inside open AU are fail-closed as rejected input or rejected access units. Reports never emit raw payload bytes.

PROVEN_OFFLINE on frozen capture: extractor wrote `.p77-work/media-out/p77_self_activation.h264` mode `0600`; this scratch media is not committed. Semantic results: 1210 PT99 packets, 617 access units, 0 rejected access units, 1 RTP sequence gap, 0 timestamp discontinuities, 1166100 Annex-B bytes, SHA256 `628c90de707c3b078b01b5374ec54dc84ada17b8ccb5cad9d5b4d836934d4435`.

H264_DECODABILITY=PROVEN_OFFLINE: `ffprobe` reports codec `h264`, profile `Baseline`, level `30`, resolution `320x240`, pix_fmt `yuv420p`, `nb_read_frames=603`. Frame scan reports 603 frames, 2 keyframes, 7 I pictures, 596 P pictures. `ffmpeg -v error -i <scratch>.h264 -f null -` exits 0 with no decode errors emitted.

## Audio Findings

AUDIO_PATH=PROVEN_OFFLINE for the optional D2C PT8 extraction path. Scratch output `.p77-work/media-out/p77_self_activation.d2c.alaw` mode `0600`; 1205 packets, 192800 bytes, SHA256 `68e7ae07a67d06bb7bcfe4d9fd99fca117220a09851f7ac2113a2494964b7a0e`. `ffprobe -f alaw -ar 8000 -ac 1` reports `pcm_alaw`, 8000 Hz, 1 channel, duration 24.100000 s. PARTIAL: role/requirement of CLIENT_TO_DEVICE PT8 remains live-only.

## Teardown Findings

TEARDOWN_SIGNATURE=PROVEN_OFFLINE: both official captures terminate with FIN CLIENT_TO_DEVICE first; self packet 3535 at +35.098148 s, p2p_rtsp packet 2476 at +47.283603 s. Both have 6 FIN and 3 RST, final RST DEVICE_TO_CLIENT. STATIC_PARTIAL: native close APIs exist for channel/lane/media cleanup, but server-side resource release and idempotency under future HA control remain live-only.

## Listener / Media Ownership

PARTIAL: native logical separation exists between Viper UDP media lane/media RX channel and persistent CTPP. OBSERVED: in `self_activation.pcap`, media-bearing UDP is non-PseudoTCP while residual PseudoTCP app traffic continues. NOT_PROVEN: listener can coexist before/during/after future HA media start. Current recommendation remains: do not stop listener by default; enforce one active media session and observe coexistence in a later live gate.

## Implemented Offline Tooling

Committed P77 artifacts:

- `entrance_p77_offset8_h264_extraction_contract.py`: offline RTP/H264 depacketizer, AU reconstructor, scratch H264/PCMA writer, optional SHA-gated pcap CLI.
- `entrance_p77_receive_path_static_contract.py`: bounded static receive-path function inventory and explicit unresolved claims.
- `test_p77_entrance_offset8_h264_extraction_contract.py`: positive synthetic extraction and fail-closed malformed input tests.
- `test_p77_receive_path_static_contract.py`: static evidence and safety-surface tests.

Default tests use synthetic fixtures or optional NOT_PROVIDED paths. The frozen pcap path is explicit and SHA-gated.

## Candidate Runtime Extension (Direction J) Verdict

CANDIDATE_RUNTIME_EXTENSION=DEFERRED_TO_LIVE_GATED_PHASE.
FACT: P76 C candidate parity remains PROVEN_OFFLINE for CONTROL generation only.
PARTIAL: media receive-side call graph has bounded static provenance for `ViperTunnel::setReceivedCbk`, `ViperTunnel::onNewIncomingChannel`, and `RtpDispatcher` thread functions, but exact inject-to-callback binding and CONTROL-to-offset8-wrapper object transition are NOT_PROVEN.
FACT: extending the C candidate with receive/demux logic now would model ungrounded architecture and violate the project evidence discipline.
FACT: committed Python depacketizer/AU-reconstructor is the proven offline oracle for future parity work.
OBSERVED: one live-gated probe can observe the actual transition facts; after that, a P78-style C parity extension becomes evidence-grounded.
C_CANDIDATE_EXTENSION_OFFLINE_JUSTIFIED=false: receive/demux extension depends on NOT_PROVEN runtime transition and callback-binding facts.

## Rejected Hypotheses

REJECTED_BY_P77: raw H264 Annex-B directly in UDP for `self_activation.pcap`; P77 proves offset-8 RTP depacketization is required. REJECTED_BY_P77: RTP starts at UDP byte 0 for the self post-218 opaque region. REJECTED_BY_P77: `0x1800` ACK is video-only. REJECTED_BY_P77: `0x0008` belongs to RTPC ABCD CONTROL.

## PROVEN_OFFLINE

PROVEN_OFFLINE: offset-8 wrapped RTP stream inventory for frozen self capture. PROVEN_OFFLINE: PT99 H264 extraction to Annex-B in scratch. PROVEN_OFFLINE: H264 decodability with ffprobe/ffmpeg. PROVEN_OFFLINE: D2C PT8 PCMA extraction and offline codec interpretation. PROVEN_OFFLINE: FIN-first teardown signature in official captures.

## PARTIAL

PARTIAL: wrapper field semantics. PARTIAL: exact RTPC receive callback call graph. PARTIAL: static CONTROL-to-media object binding. PARTIAL: p2p_rtsp media framing, because current P77 analyzers find no UDP offset-8 RTP there. PARTIAL: listener/media resource ownership.

## NOT_PROVEN

NOT_PROVEN: device `0x0008` ACK gate requirement. NOT_PROVEN: future HA-generated CONTROL sequence starts media on the real panel. NOT_PROVEN: wrapper stability for a future generated run. NOT_PROVEN: media teardown releases upstream server resources. NOT_PROVEN: video-only without CLIENT_TO_DEVICE PT8 remains stable. NOT_PROVEN: gate profile equivalence.

## LIVE_GAPS

Minimum future live observation remains one bounded on-demand media probe with listener left running: generated CONTROL acceptance, ACK-gate behavior, media wrapper stability, first media classification, bounded teardown signature, and post-teardown listener readiness. No live launcher or network-capable code is introduced by P77.

## Recommended Next Stage

Next stage should be a reviewed live-gated probe design only after explicit authorization. It should reuse P76/P77 contracts, keep media activation bounded, never assume gate equivalence from entrance evidence, and record semantic packet/decoder metadata without committing payload.

## Future-Live-Probe Necessity Verdict

FUTURE_LIVE_PROBE_NECESSARY=true. P77 closes offline H264 extraction and decodability for the frozen official capture, but device acceptance of our generated runtime, ACK gate causality, listener coexistence, and server-side teardown are live-only facts.
