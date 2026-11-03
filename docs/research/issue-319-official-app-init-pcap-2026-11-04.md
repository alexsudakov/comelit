# Issue #319 — official Android app reset/initialization PCAP (2026-11-04)

> **Status:** `OFFICIAL_INIT_CAPTURE_ANALYZED / RING_NOT_PRESENT / NO_LIVE_REPLAY`. Owner-supplied original Android Comelit app packet capture, analyzed offline. This is **initial setup/registration**, not the requested active-video→Ring experiment. No Hermes, Codex, running HA or Comelit actions were invoked.

## Evidence & limitations

- Raw PCAP SHA256: `bf75508f7e0ef4cb0eadf5c888a624d4cb206219735f290d52a8c80117b3f8c7`; size **151,525 bytes** (approximately 148 KiB).
- Classic PCAP 2.4, LINKTYPE_RAW_IP = 101, snaplen 32768. **555 IPv4 packets**: TCP 375, UDP 180; structural parse errors 0.
- Time span: **2026-11-03 21:21:05.742912Z to 21:21:58.959386Z**, duration 53.216 s (local recording calendar date 2026-11-04).
- Evidence was independently parsed from this **supplied raw file**. TCP/DNS/TLS SNI and STUN inspected; non-STUN UDP flow was sorted/reassembled using its 24-byte PseudoTCP header and sequence at offset 4, then `0x0006` Viper framing with little-endian frame length + channel id, extracting JSON *for analysis only*.
- 35 RFC-style STUN packets; successful Binding responses in both observed ICE negotiations. 101 non-STUN UDP packets exchanged with the selected peer across the two observed P2P sessions.
- No raw packet bytes, account identifier, serial code, source IP, room/apartment identifiers, activation code, user token, push token, RTSP URI, usernames, passwords, SDP or channel/connection identifiers are retained in this report.
- **Do not publish the raw PCAP to the public repo.** It contains actual authentication and camera-credential fields. Original remains in the owner's private attachment. A future raw upload requires private GitHub storage with explicit access restrictions.

## Timeline of observed events (relative to first packet)

| Relative time | Trace observation | Evidence interpretation |
| --- | --- | --- |
| +0.3 s | DNS/TLS to `api.comelitgroup.com` | Comelit API HTTPS connection; encrypted HTTP content **not visible** |
| +8.4 s | Firebase Realtime Database connection | Background/cloud state interaction; not proof of delivered push |
| +14.6 s | `moduleapp.cloud.comelitgroup.com` TLS | Comelit cloud module access |
| +17.9 s | TURN/STUN server binding | First visible STUN/ICE establishment |
| +20.14–20.32 s | Bidirectional ICE checks, peer PseudoTCP handshake | First P2P transport |
| +21.05–21.93 s | `server-info`, `user-cloud-activation`, `access`, `get-configuration` | All four received JSON replies with `response-code=200`; activation returns a token **not recorded here** |
| +29.26–29.40 s | Terminal packet exchange on first PseudoTCP flow | First session ends; exact application reason **not proven** |
| +32.53 s | New STUN server binding on different UDP 5-tuple | Second P2P setup; not necessarily an error/retry |
| +33.56–33.79 s | ICE checks, second PseudoTCP handshake | New established peer flow |
| +34.35–35.41 s | `access`, `get-configuration`, `CTPP`, `CSPB`, `INFO`, `ECHO`, `server-info` | Second authorized session; configuration expands to user-level device topology |
| +35.52–35.69 s | Android `push-info` request/reply | `response-code=200` confirms the request's successful application-level reply, not future push delivery |
| +38.83 and +44.83 s | `keep-alive` / `KEEP-ALIVE` pairs | Positive bidirectional liveness evidence after authorization |
| +50.81–50.91 s | Terminal packet exchange on second flow | End of observed peer session; termination cause and readiness afterward not proven |

**Interpretation:** two distinct P2P sessions with different functions, not a proven sequence of failed reconnection attempts. First session obtains user activation and token; second performs authenticated configuration/CTPP and push-info exchange. Cleartext inner JSON was visible after reassembling captured UDP/PseudoTCP. HTTPS APIs remain encrypted.

## Protocol messages verified in capture

| Session | Messages observed | Responses |
| --- | --- | --- |
| 1 — activation | `server-info`, `user-cloud-activation`, `access`, `get-configuration` | Each `200` |
| 2 — authenticated | `access`, `get-configuration` (twice), `server-info`, `push-info` | Each `200` |
| 2 — control | `CTPP`, `CSPB`, `INFO`, `ECHO`, ACK/control frames and keep-alive | Control observed; full CTPP/registration semantics **not independently verified** |

Server info advertises model **`ExtB`** and version **`2.8.1`**, plus eight named capabilities:

`user-auth-channel`, `configuration-channel`, `push-notifications-channel`, `cloudnext-device`, `fast-activation-channel`, `cloud-activation`, `virtual-key-gen-channel`, `rtsp-over-viper-channel`.

This is **device-reported model/version**, not the Android APK build or HA helper binary version.

## User configuration visible inside the second session

The last `get-configuration` response contained `vip.user-parameters`:

| Field | Captured item count | Note |
| --- | ---: | --- |
| `apt-address-book` | 1 | identifiers redacted |
| `switchboard-address-book` | 1 | identifiers redacted |
| `camera-address-book` | 0 | separate from RTSP list |
| `rtsp-camera-address-book` | 4 | contains RTSP URLs, usernames **and password fields**; all redacted |
| `entrance-address-book` | 2 | not proof that they correspond 1:1 to two physical relay outputs |
| `multi-functions-buttons-address-book` | 2 | each has function assignments; IDs redacted |
| `opendoor-actions` | 1 | `action=peer`, `output-index=1`, address redacted |
| `actuator-address-book`, `opendoor-address-book`, `announcement-address-book`, `direct-link-address-book` | 0 each | captured configuration only |

The reported `peer / output-index=1` is structurally consistent with the existing researched Entrance action profile. No physical actuation, protocol Door write, Ring, call acceptance or gate mapping was tested by this file.

The `viper-p2p` configuration provides structured MQTT/HTTP/STUN, while `viper-server` supplies server connection parameters. All endpoints/device identifiers withheld.

## Relevance to Issue #319

1. **Useful baseline for future capture C:** this PCAP gives real original-app byte/protocol framing, session establishment, JSON activation/authorization, successful CTPP-adjacent exchanges and post-auth keep-alive; distinguish these from call-related packets.
2. **Improved over R39:** the previous [R39 official-app capture](../../safety-poc/research/media/v1/P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md) contained no physical Ring and had no usable app-ready signal. The new trace proves authenticated application-level exchange and positive liveness. Nevertheless, internal Android `ComelitStatus.RegisterStatus.REGISTERED` and `ToolbarDeviceConnectionStatus.CONNECTED` were **not independently observed**; consult [R40F](../../safety-poc/research/media/v1/P116_R40F_OFFICIAL_APP_READINESS_EVIDENCE.md) / [R40G](../../safety-poc/research/media/v1/P116_R40G_RUNTIME_PATH_AND_READINESS.md).
3. **Missing target evidence:** no evidenced physical `CALL_INIT`, answered incoming call, call-adoption FSM, video RTP stream, `MEDIAREQ26 OPEN/STOP`, or active-video→Ring transition in this recording. Do not equate encrypted HTTPS or opaque packets with proof of absent Ring, but there is **no identified Ring/media exchange** in parsed cleartext flows.
4. **Next capture:** begin PCAP before opening video; record verified video ≥15–20 s, a single physical Ring while still viewing, call UI/video transition, then end of call and 20–30 s follow-up. Log approximate time of press, visible video continuity, and whether original UI reports registered/connected. Avoid teardown/replay, Door/Gate actions, secrets exposure and overlapping HA upstream ownership.
5. Compare original **A self-activation**, **B normal incoming Ring** (archival R42), and **C new live-preview→Ring** by state transitions, independent transport/channel identities and confidence levels. Do not infer unique call ID from CTP connection/frame SHA/generation. Do not launch Hermes until a concrete runtime-only proof gap remains.

## Safety/publication

`RAW_PCAP_PUBLIC=false`, `APP_CREDENTIAL_VALUES_PUBLIC=false`, `NO_CODE_CHANGE=true`, `NO_NETWORK_TX=true`, `NO_HERMES=true`, `NO_HA_RESTART=true`, `NO_DOOR_GATE=true`, `ISSUE319_P0A_NOT_FIXED=true`, `ISSUE319_P0B_NOT_FIXED=true`.

Source review baseline: [pre-capture archive review](issue-319-archive-evidence-review-2026-11-03.md).
