# P116 R23 — H.264 random-access root-cause proof

Status: **offline research / corrective selection**  
Date: 2026-09-13  
Base: `ffb469ce7b4def6cda5d320387337c1e51df6be6`  
Live activity in this phase: **none**

## 1. Purpose

R21 proved the Home Assistant backend path through LL-HLS HTTP serving while
Comelit RTP was live. R22 then proved that desktop Chrome/hls.js also reaches
real HLS media Parts: the browser fetched non-empty `.m4s` Parts with HTTP 200
and `video/iso.segment`, yet no visible video was produced.

R23 is offline-only. Its purpose is to determine whether the H.264 bitstream at
HA/HLS segment boundaries contains a browser-usable random-access point, and to
select the smallest corrective that does not transcode video or alter Comelit
signaling.

No raw HAR, PCAP, RTP payload, media bytes, HLS URL/token, session identifiers,
or proprietary artifacts are committed by this phase.

## 2. Frozen external evidence

The private artifacts used for the offline analysis are identified only by
hash:

```text
OFFICIAL_PCAP_SHA256=3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f
R22_CHROME_HAR_SHA256=547eb3e8ea69969eadfbdbfcc6a7f5a31249f9f30824d92180a9000bd1845edb
```

They remain outside the public repository.

## 3. R22 Chrome/HLS evidence

The HAR contains 16 unique captured HLS Part names from the relevant stream.
After ISO-BMFF parsing and H.264 extraction, these Parts contain:

```text
VCL_NAL_TYPE_1=358
SPS_NAL_TYPE_7=4
PPS_NAL_TYPE_8=4
IDR_NAL_TYPE_5=0
SEI_NAL_TYPE_6=0
```

Four samples are marked as sync/key samples by the fragment metadata. Each of
those samples begins with SPS/PPS and then an H.264 type-1 VCL NAL whose slice
header is an I-slice (`slice_type % 5 == 2`). None is an IDR NAL and none carries
a recovery-point SEI.

Therefore, for the captured client window:

```text
D2_CONTAINER_SYNC_METADATA_PRESENT=PROVEN_OFFLINE
D2_BITSTREAM_IDR_AT_CAPTURED_SYNC_POINTS=false
D2_BITSTREAM_RECOVERY_POINT_SEI_AT_CAPTURED_SYNC_POINTS=false
```

The browser-side HTTP path itself is not the missing boundary: Chrome received
real media Parts before the later LL-HLS blocking-reload failures.

## 4. Official-app capture: startup IDR vs periodic non-IDR I pictures

The frozen official-app capture contains 2720 video RTP packets on PT99. The
H.264 packetization observed in that capture is:

```text
FU_A_PACKETS=2252
SINGLE_TYPE1_PACKETS=436
SPS_PACKETS=16
PPS_PACKETS=16
```

After RTP depacketization:

```text
TYPE1_SLICES=1468
SPS=16
PPS=16
IDR=2
SEI=0
```

Sixteen I-picture access-unit groups are present. The first two are genuine IDR
pictures near media startup. The remaining fourteen periodic I pictures are
non-IDR type-1 slices. Each observed periodic recovery-like group is preceded
by SPS and PPS and begins with a non-IDR I-slice.

No client-to-server RTP/RTCP feedback packet was observed in this capture that
would support a periodic PLI/FIR-based IDR-refresh contract.

The observed cadence is capture-specific evidence only. It is **not** promoted
to a protocol timing constant.

## 5. Decoder restart proof

For each of all 14 periodic non-IDR I access units, an Annex-B suffix was built
offline beginning at that access unit, including its immediately preceding
SPS/PPS. Each suffix was decoded with FFmpeg using strict error handling.

Result:

```text
PERIODIC_NON_IDR_I_POINTS_TESTED=14
STRICT_DECODE_PASS=14
STRICT_DECODE_FAIL=0
```

The decoded-frame MD5 sequence from every suffix was then compared against the
continuous decode of the full captured stream. The suffixes matched exactly
from the following continuous-frame positions:

```text
105, 206, 307, 408, 509, 610, 711,
812, 913, 1014, 1115, 1215, 1316, 1417
```

For every one of the fourteen points, all frames from the restart point to the
end were byte-for-byte identical at the decoded-frame hash level to continuous
decoding.

Therefore, for this frozen capture:

```text
NON_IDR_I_DECODER_RESTART=PROVEN_OFFLINE
RECOVERY_FRAME_CNT_ZERO_SEMANTICS=SUPPORTED_BY_OFFLINE_DECODE
CAPTURE_EXACT_DECODE_MATCH=PROVEN_OFFLINE
```

The exact-match observation is capture-specific. Production code must not
promote `exact_match_flag=1` to a universal Comelit protocol rule.

## 6. Why HA/HLS metadata and the H.264 bitstream disagree

Home Assistant Core 2026.9.1 `StreamMuxer` uses PyAV `packet.is_keyframe` to:

- close an HLS Segment once the minimum segment duration is reached; and
- propagate keyframe state into the generated HLS Part/sample metadata.

The R22 fragments show that the resulting ISO-BMFF samples are marked as sync
samples even though the corresponding H.264 access units are non-IDR I pictures
without recovery-point SEI.

This gives the structural mismatch:

```text
Comelit periodic non-IDR I picture
        + SPS/PPS
        + no IDR
        + no recovery-point SEI
              |
              v
PyAV reports packet.is_keyframe
              |
              v
HA closes HLS Segment / marks sync sample
              |
              v
ISO-BMFF says random-access sample
but H.264 bitstream does not explicitly signal one
```

This mismatch is **PROVEN_OFFLINE** for the frozen R22 material.

The final statement that Chrome MSE rejected the sample for this exact reason
remains **STRONGLY_SUPPORTED**, not `PROVEN_LIVE`, because R22 did not capture an
internal MSE rejection event.

## 7. Chromium corroboration

Chromium commit `53b9408974772f485a8b5f318ea7795f994b934c` (2026-04-24),
`media: Promote H.264 SEI recovery point frames to keyframes for MSE`, documents
the same class of failure: non-IDR I-frames can be valid open-GOP random-access
points when they carry recovery-point SEI with `recovery_frame_cnt=0`, but an MSE
client that does not recognize them as keyframes can drop them and drive hls.js
fragment reload behavior.

Reference:
`https://chromium.googlesource.com/chromium/src/+/53b9408974772f485a8b5f318ea7795f994b934c`

The ISO-BMFF MSE byte-stream format likewise requires random-access samples to
correspond to valid Stream Access Points rather than relying only on an outer
container flag.

Reference:
`https://www.w3.org/TR/mse-byte-stream-format-isobmff/#random-access-points`

This corroboration does not replace the frozen-capture proof above.

## 8. Recovery-point SEI corrective prototype

An H.264 recovery-point SEI with:

```text
recovery_frame_cnt=0
exact_match_flag=0
broken_link_flag=0
changing_slice_group_idc=0
```

was injected offline immediately before each of the 14 observed periodic
non-IDR I access units. `exact_match_flag=0` is intentionally conservative even
though the frozen capture produced exact decoded-frame matches; one capture is
insufficient to establish a universal exact-match generation rule.

Results on the official capture:

```text
ORIGINAL_FFPROBE_KEY_I=2
RECOVERY_SEI_FFPROBE_KEY_I=16
STRICT_DECODE_AFTER_INJECTION=PASS
FULL_DECODE_FRAME_HASH_IDENTITY=PASS
```

The injected SEI changes random-access signaling only. It does not modify SPS,
PPS, slice payloads, image content, or decoded frames.

The same experiment on the R22-derived H.264 material promoted the captured
periodic non-IDR I pictures to keyframes in FFmpeg while preserving strict
successful decoding.

## 9. RTP-level feasibility

A bounded offline RTP-rewrite prototype was applied to the frozen official-app
video packets.

For a non-IDR type-1 I access unit, the prototype inserts one standalone H.264
SEI NAL as a new RTP packet immediately before the first VCL packet. Existing
packet payloads are not modified. The inserted packet uses the same RTP
stream/timestamp context, marker 0, and sequence numbers are shifted by the
number of prior insertions.

Observed result:

```text
INPUT_VIDEO_RTP_PACKETS=2720
OUTPUT_VIDEO_RTP_PACKETS=2734
RECOVERY_SEI_PACKETS_INSERTED=14
NEW_SEQUENCE_GAPS=0
PREEXISTING_SEQUENCE_GAPS_PRESERVED=true
ORIGINAL_RTP_PAYLOADS_MODIFIED=false
DEPAYLOAD_ERRORS=0
```

After depacketization, the only new NAL units are the 14 recovery-point SEIs.
Remuxing to MP4 and back to Annex-B preserves all injected recovery-point SEIs.

This proves offline feasibility of a narrow RTP shim without full video
transcoding.

## 10. Corrective alternatives

### A. Mutate non-IDR NAL type 1 into IDR type 5 — rejected

Rejected. IDR and non-IDR slice syntax/semantics are not interchangeable. A bit
rewrite would claim decoder state that the original slice does not guarantee.

### B. Clear HA/PyAV keyframe metadata — rejected

Rejected. HA relies on `packet.is_keyframe` to close HLS Segments. Removing that
state would reintroduce the earlier segment-closure/startup failure rather than
provide a usable random-access point.

### C. Depend on startup IDR only — rejected as production strategy

The frontend starts near the live edge after HA has built HLS material. The
frozen official stream contains no later IDR after startup, while periodic
segment boundaries occur at non-IDR I pictures. Startup IDR alone therefore
does not provide a reliable ongoing MSE random-access contract.

### D. Request periodic IDR from the device — not proven

The official-app capture does not show an RTCP PLI/FIR feedback contract. No
production implementation should invent such signaling without independent
protocol proof.

### E. Full H.264 transcode with forced IDR — fallback only

This would create conventional IDR random-access points, but adds significant
CPU, latency and runtime dependencies. It is disproportionate while a
bitstream-preserving recovery-point solution remains viable.

### F. Insert recovery-point SEI before proven non-IDR I access units — selected

Selected as the smallest corrective candidate.

It preserves the encoded picture data, gives modern MSE implementations an
explicit H.264 random-access signal, and matches Chromium's supported
`recovery_frame_cnt=0` path.

## 11. Selected implementation boundary for the next phase

Do **not** modify Comelit signaling, cloud bootstrap, D1 lease/refresh behavior,
or the proprietary native helper merely to test this correction.

The preferred implementation boundary is a small local video RTP recovery shim
between the existing native helper and the HA/PyAV-facing SDP path:

```text
Comelit
  -> existing native helper
  -> local PT99 RTP input
  -> recovery-point shim
       - RTP/H.264 structural parse
       - identify non-IDR I access-unit start
       - inject recovery-point SEI only
       - resequence RTP deterministically
  -> HA/PyAV-facing loopback RTP
  -> Home Assistant Stream / LL-HLS
```

Audio remains on the existing direct path.

The shim must be packetization-safe. The frozen capture proves FU-A and
single-NAL forms; production code must not assume that one capture exhausts all
`packetization-mode=1` forms. Unsupported or malformed shapes must fail/pass
through safely according to an explicit contract, never fabricate an IDR.

The local output port is an implementation detail and must be selected by the
implementation phase; no capture-derived network scalar is promoted here.

## 12. Next phase acceptance contract

The next executable phase should be offline-first and should not use a live
Comelit session initially. At minimum it must prove:

1. deterministic RFC 6184 parsing for supported single-NAL/FU-A/STAP-A forms;
2. I-slice detection only at the first VCL of an access unit;
3. no injection for true IDR;
4. no duplicate recovery SEI when one is already present;
5. one recovery-point SEI with `recovery_frame_cnt=0` for an eligible non-IDR I
   access unit;
6. deterministic RTP resequencing with input loss/gaps preserved;
7. RTP timestamp, SSRC, payload type and marker semantics preserved;
8. all original payload bytes unchanged;
9. frozen-capture decode remains frame-identical;
10. no Door/Gate/OAuth/Comelit signaling/D1 changes;
11. no new upstream media session behavior;
12. only after these gates pass may a separately authorized one-session HA live
    validation be proposed.

## 13. R23 classification

```text
D2_CLIENT_HTTP_CHAIN=PROVEN_THROUGH_MEDIA_PARTS
D2_HLS_JS_STARTED=PROVEN
D2_CONTAINER_SYNC_METADATA_PRESENT=PROVEN_OFFLINE
D2_BITSTREAM_IDR_AFTER_STARTUP=ABSENT_IN_FROZEN_CAPTURE
D2_BITSTREAM_RECOVERY_POINT_SEI=ABSENT_IN_FROZEN_CAPTURE
D2_NON_IDR_I_DECODER_RESTART=PROVEN_OFFLINE
D2_CAPTURE_EXACT_DECODE_MATCH=PROVEN_OFFLINE
D2_CONTAINER_BITSTREAM_RANDOM_ACCESS_MISMATCH=PROVEN_OFFLINE
D2_MSE_RANDOM_ACCESS_REJECTION=STRONGLY_SUPPORTED
R24_SELECTED_CORRECTIVE=RECOVERY_POINT_SEI_RTP_SHIM
LIVE_REQUIRED_FOR_R23=false
```
