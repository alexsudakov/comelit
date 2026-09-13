# P116 R24 — recovery-point RTP shim

Status: offline implementation  
Date: 2026-09-13  
Live activity: none  
LIVE_AUTHORIZED=false

## Scope

R24 implements the R23-selected corrective: a local, loopback-only RTP/H.264 shim between
the existing native helper video RTP output and the Home Assistant stream SDP input.

The native helper remains byte-pinned and still sends video RTP to the established local
helper port. The new shim binds that port inside the Home Assistant asyncio process,
rewrites only PT99 H.264 RTP structure, and forwards repaired RTP to a separate
HA-facing loopback video port. Audio remains on the direct helper-to-HA path.

No live Comelit traffic, upstream calls, HA deployment, HA restart, media session, door,
gate, OAuth, router, or native helper mutation was performed.

## Design

The implementation is split into:

- `custom_components/comelit/h264_recovery.py`: stdlib-only RTP/H.264 parser, recovery
  SEI generator, deterministic sequence rewriter, and asyncio loopback datagram shim.
- `custom_components/comelit/media_transport.py`: lifecycle wiring that starts the shim
  before the native helper process and tears it down on stop, failure, cancellation, and
  transport exit.
- `custom_components/comelit/camera.py`: existing diagnostics surface extended with
  bounded scalar recovery-shim fields.

The pure rewriter parses RTP version 2, marker, payload type, sequence number,
timestamp, SSRC, CSRCs, header extensions, and input padding. Only PT99 is interpreted as
H.264. Non-PT99 packets are not parsed as H.264.

Supported H.264 packetization forms are:

- single NAL units;
- FU-A, with only the FU start packet eligible to establish a slice header;
- STAP-A, parsed as length-delimited NALs in packet order.

Unsupported forms pass through unchanged and increment a bounded scalar counter.
Malformed RTP/H.264 structures pass through and increment a bounded malformed counter.
No exception is allowed to escape the datagram callback.

## Eligibility

The shim injects exactly one standalone type-6 recovery-point SEI RTP packet immediately
before an eligible first VCL packet. An access unit is eligible only when all of these are
proven from current RTP/H.264 structure:

- SPS was seen in the same access unit before the first VCL;
- PPS was seen in the same access unit before the first VCL;
- the candidate is the first VCL of the access unit;
- the candidate NAL type is non-IDR type 1;
- `first_mb_in_slice == 0`;
- `slice_type % 5 == 2`;
- no recovery-point SEI has already been observed for the access unit;
- no recovery point has already been injected for the access unit.

True IDR type 5 never causes injection. Existing valid recovery-point SEI with
`recovery_frame_cnt=0` suppresses duplicate injection. If the slice or SEI cannot be
parsed confidently, the shim passes through.

The inserted SEI is generated semantically with:

```text
recovery_frame_cnt=0
exact_match_flag=0
broken_link_flag=0
changing_slice_group_idc=0
```

The original RTP payload bytes are preserved byte-identically. SPS, PPS, and slice
payloads are not modified.

## Sequence Contract

The rewriter keeps a deterministic per-SSRC injection offset. Each injected packet takes
the shifted sequence number that the original packet would otherwise have used. The
original packet and every later packet for that SSRC are shifted by the cumulative
injection count modulo 16 bits. Existing input gaps are preserved.

No capture-derived cadence, GOP interval, timestamp value, SSRC value, or sequence value
is encoded in production.

## Lifecycle

`MEDIA_VIDEO_RTP_PORT` remains the helper video destination. `MEDIA_VIDEO_HA_RTP_PORT` is
the HA-facing local implementation port used in the generated SDP. The shim binds
`127.0.0.1` before the native helper process is started, so startup video packets cannot
be consumed directly by HA or another receiver.

`local_sdp_ready` now requires the media transport to be active, the local SDP file to
exist, and the video recovery shim to be running.

Shim startup is fail-closed. If startup fails or is cancelled after any datagram
transport is created, the shim closes every created transport, clears its running state,
and can be started again later. The media transport stores the shim handle before awaiting
startup so transport-exit teardown can reach it on cancellation or other failures.

Audio remains unchanged on `MEDIA_AUDIO_RTP_PORT` with PCMA in the local SDP.

## Diagnostics

Only bounded scalars are exposed:

```text
video_recovery_shim_running
video_recovery_input_packets
video_recovery_output_packets
video_recovery_eligible_nonidr_i_count
video_recovery_injected_count
video_recovery_existing_recovery_count
video_recovery_idr_count
video_recovery_unsupported_packet_count
video_recovery_malformed_count
video_recovery_last_error
```

No RTP payload bytes, NAL bytes, SDP body, URL/token, SSRC value, sequence value, or
timestamp value is logged or exposed by the new diagnostics.

## Offline Verification

New focused tests cover:

- single-NAL, FU-A, and STAP-A injection;
- true IDR and P-slice non-injection;
- missing SPS/PPS non-injection;
- malformed Exp-Golomb and malformed STAP-A pass-through;
- existing recovery-point SEI duplicate suppression;
- unsupported H.264 packetization pass-through;
- RTP extension preservation;
- marker handling;
- timestamp, payload type, and SSRC preservation;
- original payload byte preservation;
- contiguous mapping, input gap preservation, sequence wrap, multiple cumulative
  injections, timestamp state reset, and independent SSRC state;
- independent semantic decode of the generated SEI fields.

Lifecycle tests statically assert the transport wiring and exercise the actual loopback
shim object when UDP bind is available. They cover normal stop, repeated start/stop,
startup failure cleanup with object reuse, and deterministic cancellation after the
output transport has been created but before input bind completes. In restricted
sandboxes that deny loopback UDP, only the real-socket portion is skipped with
`sandbox_loopback_udp_denied`; host execution still exercises the socket path.

The reusable verifier is:

```text
safety-poc/scripts/verify_p116_r24_recovery_shim.py
```

It performs no socket operations and never transmits packets. If the exact official PCAP
is supplied and its SHA-256 matches the frozen R23 hash, the verifier extracts PT99 RTP
datagrams, feeds them through the production rewriter, validates expected compact
scalars, verifies new sequence gaps against the deterministic rewriter sequence mapping,
separately verifies preservation of pre-existing input gaps over original packets,
depacketizes original and recovery output offline, and uses FFmpeg for strict
decoded-frame identity when FFmpeg is available.

The official PCAP artifact is not present in this workspace. Expected local verifier
result:

```text
CAPTURE_RUNTIME_VALIDATION=UNAVAILABLE
OFFICIAL_PCAP_FOUND=false
```

## Remaining Unproven

Because this phase is offline-only, live HA browser playback and live Chromium MSE
acceptance remain unproven here. R24 proves the local transformation behavior, lifecycle
wiring, and offline verifier path without live Comelit activity.
