# CT120 Media PoC v1 — protocol contract

Status: research implementation contract
Target: CT120 only
Panel: entrance `00000643`
Production HA deployment: prohibited until acceptance gates are met

## Safety invariants

- No Door action code, payload, trigger, signal handler, or retry is permitted in the media PoC binary.
- Gate media is out of scope.
- Initial live media duration: 10 seconds.
- Independent hard watchdog: 30 seconds.
- Teardown must be attempted on success, timeout, error, and process shutdown.
- The media helper is on-demand and must exit after the test session.

## Offline media facts proven from `self_activation.pcap`

The entrance self-activation capture contains a raw ViP datagram carrying RTP/H.264:

```text
ViP outer header: 8 bytes
RTP payload type: 99
RTP clock: 90000
Codec: H.264 Baseline
Resolution: 320x240
Frame rate: 25 fps
```

Observed raw media packet shape:

```text
00 06 <body_len_le16> <request_id_le32> | 80 63 ...
<---------- ViP outer header ---------->   <--- RTP PT99 --->
```

The existing listener helper sends ViP control over PseudoTCP on the same selected ICE component. PseudoTCP wire packets have conversation id 0 and therefore start with four zero bytes. Raw media ViP datagrams must be demultiplexed before calling `pseudo_tcp_socket_notify_packet()`.

## Capture-proven self-activation control sequence

All entries below use the registered CTPP request id from the live session. Numeric action semantics are intentionally not renamed beyond what the capture proves.

```text
CALL_INIT
  prefix 0x18C0
  action 0x0028
  client -> device

ACK
  device -> client

VIDEO_EVENT
  prefix 0x1840
  action 0x0008
  client -> device

ACK
  device -> client

VIDEO_EVENT
  prefix 0x1840
  action 0x0008
  device -> client

ACK
  client -> device

VIDEO_EVENT
  prefix 0x1840
  action 0x0002
  device -> client

ACK
  client -> device

VIDEO_EVENT
  prefix 0x1840
  action 0x000A
  client -> device

VIDEO_EVENT
  prefix 0x1840
  action 0x000A
  device -> client

ACK
  client -> device

ACK
  device -> client

VIDEO_EVENT
  prefix 0x1840
  action 0x001A
  client -> device

ACK
  device -> client
```

After this setup, the capture contains the H.264 RTP media burst.

## Capture-proven media teardown sequence

The capture does not contain a CTPP channel close at media stop. Instead the official client performs a media/event teardown while keeping the wider P2P/CTPP session alive.

The observed teardown begins at the end of self-activation:

```text
1. client -> device
   prefix 0x1840
   action 0x0003
   flags  0x000E

2. device -> client
   ACK

3. client -> device
   prefix 0x1840
   action 0x000A
   flags  0x0011
   stop-form payload (capture body contains 0x0298 profile)

4. device -> client
   ACK

5. client -> device
   prefix 0x1840
   action 0x001A
   flags  0x0011
   zeroed media-profile fields

6. device -> client
   prefix 0x1860
   action 0x000A

7. device -> client
   ACK

8. client -> device
   ACK for peer 0x1860/0x000A

9. client -> device
   prefix 0x1860
   action 0x000E
   flags  0x0070
   state byte changed to zero

10. device -> client
    ACK
```

For PoC v1 this sequence is the capture-proven protocol release path. Exact semantic names for actions `0x0003`, `0x000A`, `0x001A`, and `0x000E` remain unproven and must not be invented in code comments or diagnostics.

After the protocol teardown sequence, the on-demand PoC may close PseudoTCP/ICE and exit. This is stricter cleanup than the official app capture, which retained its wider session.

## Transport design for PoC v1

Use a separate helper derived from the no-Door v4 persistent transport baseline, not from the Door-capable production helper.

```text
one NiceAgent / one ICE component
        |
        +-- PseudoTCP wire packet (first four bytes = 00 00 00 00)
        |      -> UAUT/UCFG/CTPP control
        |
        +-- raw ViP datagram (00 06 ...)
               -> if body starts RTP v2/PT99
               -> H.264 depacketizer
               -> Annex-B .h264 output
```

The raw-media demux is receive-only. Media setup and teardown control messages continue over the registered CTPP channel through PseudoTCP.

## H.264 depacketizer requirements

PoC v1 must support the packetization observed offline:

- single NAL units;
- STAP-A;
- FU-A;
- SPS/PPS preservation;
- IDR preservation;
- sequence-gap diagnostics;
- no decoder dependency inside the helper.

The helper writes Annex-B H.264. CT120 ffmpeg is used after the helper exits to create JPEG and MP4 validation artifacts.

## PoC v1 output contract

Required stdout markers:

```text
V4_MEDIA_ACTION_SURFACE_PRESENT=true
V4_DOOR_ACTION_SURFACE_PRESENT=false
V4_MEDIA_TARGET=entrance
V4_MEDIA_SETUP_STARTED=true
V4_MEDIA_ACTIVE=true
V4_MEDIA_RTP_PT=99
V4_MEDIA_H264_BYTES=<n>
V4_MEDIA_RTP_PACKETS=<n>
V4_MEDIA_TEARDOWN_STARTED=true
V4_MEDIA_TEARDOWN_RESULT=ACKED|PARTIAL|FAILED
V4_MEDIA_ICE_CLOSED=true
V4_MEDIA_EXIT=PASS|FAIL
```

No raw credentials, OAuth values, VIP token values, ICE passwords, or complete SDP may be printed.

## First live-run gates

The first active test is allowed only when all of these are true:

1. The PoC source/binary contains no Door state machine or Door payload arrays.
2. Entrance is hard-coded as `00000643` for v1.
3. Capture duration is 10 seconds.
4. A 30-second absolute watchdog is active from process start.
5. Protocol teardown is registered before media activation is sent.
6. Process cleanup is idempotent.
7. Output directory is separate from production HA paths.
8. No automatic retry of setup or teardown commands is implemented.

## Acceptance after first live run

A run is considered useful only if it produces:

- non-empty Annex-B H.264;
- ffprobe confirmation of H.264 Baseline 320x240;
- a decodable JPEG;
- a playable MP4;
- teardown diagnostics;
- no leftover PoC process;
- no leaked media session observable from the official Comelit app.

Persistent-listener coexistence is tested only after the isolated media path is proven reproducible.
