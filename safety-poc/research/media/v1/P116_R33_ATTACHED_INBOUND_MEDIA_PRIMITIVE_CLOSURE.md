# P116 R33 Attached Inbound Media Primitive Closure

FACTS

R33 Run 1 is offline static research only. It did not run a listener, transmit on the Comelit network, reload Home Assistant, touch Door/Gate, deploy, mutate CT120 wrappers, retry, or change production files.

The staged R33 evidence is text disassembly derived from the official `libvipcomelit.so` and is git-excluded analysis input. This document records only symbol/offset-level roles and safe scalar constants. It does not copy raw packet bodies, addresses, credentials, tokens, binary bytes, or full disassembly dumps.

Previous settled facts remain inputs, not re-derived here: the call CTP id is the direction-transformed CTP header connection field, helper capture of that scalar is implementable, registered CTPP is not equivalent, and synthetic bootstrap differs semantically from physical attached bootstrap.

CHILD A - EXACT MEDIAREQ26 SERIALIZATION

`MEDIAREQ26_BODY_LENGTH=26`. `csp_send_mediareq26` calls `malloc(0x1a)`, passes length `0x1a` to `ctp_write`, and tail-calls `ctp_write(call_ctp_id, msg, 26)` (`.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:19`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:31`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:51`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:52`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:71`).

Full CTP packet offsets remain separate: the 26-byte body below is the inner media request body. The full call-bound CTP packet adds the 8-byte CTP header before this body, padding after it, then trailer and logical source/destination address roles as recorded by R30 (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:118`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:136`).

`MEDIAREQ26_FIELD_LAYOUT=PROVEN`.

| Body offset | Width | Endianness / storage | Semantic role | Source expression / object | OPEN value/source | STOP value/source | Confidence | Evidence anchor |
|---|---:|---|---|---|---|---|---|---|
| `0..1` | 2 | stored as native halfword byte-swapped constant for wire opcode | inner media opcode | helper-local constant in `csp_send_mediareq26` | `0x0011` semantic opcode | `0x0011` semantic opcode | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:34`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:36` |
| `2` | 1 | byte | media request action/state | `csp_send_mediareq26` arg1 (`w1`) | `0x14` from `CallFsm::start_videorx` | `0x94` from `CallFsm::stop_videorx` | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:29`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:35`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:64`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:106`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:38`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:56` |
| `3` | 1 | byte | flags: direction/profile bits plus address-vs-channel selector | `csp_send_mediareq26` arg2 (`w2`) | tunnel: base `0x32` with bit3 overwritten from `start_arg >> 1`; address form: `0x30 | optional bit2 | optional bit3` | tunnel stop: `0x02`; address stop: `0x00` | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:28`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:59`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:60`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:65`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:96`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:98`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:103`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:40`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:50` |
| `4..7` | 4 | copied word or zero | IPv4/address-form field | if flags bit1 is clear, copy `*(uint32_t*)arg3`; if bit1 is set, write zero | address form copies `sockaddr_in` address at local stack `+4`; tunnel form passes null and writes zero | address stop copies `sockaddr_in` address; tunnel stop writes zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:38`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:39`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:49`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:50`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:62`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:104`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:32`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:55` |
| `8..9` | 2 | halfword | local RTP port or media channel id | `csp_send_mediareq26` arg4 (`w4`) | tunnel: `RtpDispatcher` slot `+8` populated by `openMediaRXChannel`; address: port from `getSockName` sockaddr after network-to-host transform | tunnel: saved dispatcher channel id from `+8`; address: local socket port from `getSockName` | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:26`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:54`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:47`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:49`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:43`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:44`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:51`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:47`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:91`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:97`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:99`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:36`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:48`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:57` |
| `10..11` | 2 | halfword | max RTP payload | `csp_send_mediareq26` arg5 (`w5`) | `RtpDispatcher::getMaxRtpPayload()` reads dispatcher offset `+68` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:25`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:55`, `.r33-evidence/native-disasm/disasm2-RtpDispatcher__getMaxRtpPayload___const.txt:9`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:48`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:100`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:33`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:51` |
| `12..15` | 4 | word | media channel/profile scalar | `csp_send_mediareq26` arg6 (`w6`) | tunnel/address: `CallFsm[824]+154` loaded as halfword and widened when `CallFsm[824]+152` is nonzero, otherwise zero | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:17`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:53`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:58`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:40`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:42`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:67`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:81`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:113`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:34`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:52` |
| `16..17` | 2 | halfword | profile/source scalar 0 | `csp_send_mediareq26` arg7 (`w7`) | `CallFsm[824]+360` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:17`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:53`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:56`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:50`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:72`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:111`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:118`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:35`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:60` |
| `18..19` | 2 | halfword | profile/source scalar 1 | first stack argument to helper | `CallFsm[824]+362` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:24`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:59`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:51`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:72`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:107`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:118`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:61` |
| `20..21` | 2 | halfword | profile/source scalar 2 | second stack argument to helper | `CallFsm[824]+364` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:23`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:60`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:52`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:71`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:108`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:117`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:62` |
| `22..23` | 2 | halfword | profile/source scalar 3 | third stack argument to helper | `CallFsm[824]+366` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:22`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:61`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:53`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:70`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:109`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:116`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:60` |
| `24` | 1 | byte | profile/source scalar 4 | fourth stack argument to helper | `CallFsm[824]+368` | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:21`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:62`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:54`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:69`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:110`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:115`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:39`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:59` |
| `25` | 1 | byte | trailing profile/reserved scalar | fifth stack argument to helper | zero | zero | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:20`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:57`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:68`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:114`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:58` |

`MEDIAREQ26_UNKNOWN_FIELD_COUNT=0` for byte ownership and native source object. Some media-profile names remain role-level names because the disassembly proves source offsets but not human-readable codec/profile labels.

Candidate verdicts:

| Candidate | Verdict | Anchor |
|---|---|---|
| `inner opcode candidate = 0x0011` | PROVEN | `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:34`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:36`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:122` |
| `OPEN action candidate = 0x14` | PROVEN | `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:64`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:106` |
| `STOP action candidate = 0x94` | PROVEN | `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:38`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:56` |
| `flags candidate = 0x32` | PARTIAL | `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:59`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:60`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:65`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:103` |

Direction and selector closure:

- Bit1 of flags is the address-vs-channel selector. If bit1 is set, `csp_send_mediareq26` writes zero at body `4..7`; if clear, it dereferences the address pointer and copies four bytes to body `4..7` (`.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:38`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:39`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:49`, `.r33-evidence/native-disasm/disasm2-csp_send_mediareq26.txt:50`).
- Bit3 is derived from `start_videorx(int)` bit1 in both OPEN forms. Tunnel OPEN starts from `0x32` and inserts that bit; address-form OPEN ORs `0x30` with optional bit2 and bit3 (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:59`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:65`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:91`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:96`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:98`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:103`).
- Bit2 in address-form OPEN is sourced from `CallFsm+812`; tunnel OPEN in the visible path does not use that object bit (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:93`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:98`).
- STOP differs from OPEN by action `0x94`, max payload zero, profile zeros, trailing zeros, and flags `0x02` for channel/tunnel form or `0x00` for address form (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:32`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:33`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:34`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:35`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:40`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:50`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:51`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:58`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:60`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:61`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:62`).

Address-form IPv4 and local RTP port semantics:

- Address form calls `RtpDispatcher::getSockName(channel=1, direction=1, sockaddr_in&)`, then passes a pointer to the `sockaddr_in` address bytes at local stack plus four (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:84`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:89`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:104`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:42`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:47`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:55`).
- Address-form port is loaded from the `sockaddr_in` port slot, byte-reversed, shifted down, and passed as the body `8..9` scalar (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:91`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:92`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:97`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:99`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:48`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:54`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:57`).
- Tunnel/channel form passes a null address pointer, sets the selector bit, and uses the saved media RX channel id at dispatcher offset `+8` as body `8..9`; `RtpDispatcher::startVideoRX` passes `dispatcher+8` as the `openMediaRXChannel` out-pointer, and `openMediaRXChannel` writes the masked channel id through that pointer (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:45`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:47`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:62`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:66`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:47`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:49`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:16`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:39`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:44`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:45`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:51`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:30`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:32`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:36`).

Exact call CTP id argument:

- `CallFsm::initNewConnectionStart(unsigned short, csp_msgbuf*)` stores its unsigned-short argument into `CallFsm+48` (`.r33-evidence/native-disasm/disasm3-CallFsm__initNewConnectionStart_unsigned_short__csp_msgbuf__.txt:15`).
- `CallFsm::start_videorx` loads `CallFsm+48` into `w23` or `w22` and moves it into `w0` immediately before both `csp_send_mediareq26` OPEN call sites (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:46`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:95`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:105`).
- `CallFsm::stop_videorx` loads `CallFsm+48` directly into `w0` before the STOP call site (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:31`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:49`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`).

One OPEN / one STOP count and guards:

- `start_videorx` first requires `CallFsm+840` bit2, then if `start_arg` bit0 is set it calls `RtpDispatcher::startVideoRX`; a negative return exits without mediareq. Successful control reaches exactly one of two mutually exclusive `csp_send_mediareq26` OPEN call sites: tunnel/channel form or address form (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:19`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:20`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:33`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:38`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:43`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:44`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:73`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:119`).
- `stop_videorx` requires `CallFsm+840` bit2 and dispatcher `+136` active. It emits exactly one STOP through one merged call site, then calls `RtpDispatcher::stopVideoRX()` (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:17`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:18`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:21`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:22`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:64`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:65`).

`MEDIAREQ26_OPEN_CONTRACT=PROVEN`.

`MEDIAREQ26_STOP_CONTRACT=PROVEN`.

CHILD C - OPEN RESPONSE / RTP GATING

The channel OPEN request is asynchronous from `CallFsm::start_videorx`'s point of view. In tunnel mode, `RtpDispatcher::startVideoRX` calls `ViperTunnel::openMediaRXChannel`, stores the returned channel pointer at dispatcher offset `+0`, and returns to `CallFsm`; `CallFsm::start_videorx` then emits `csp_send_mediareq26` OPEN. There is no wait for `ViperTunnel::onChannelOpenRes` in that caller path (`.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:41`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:49`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:50`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:39`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:73`).

A channel id becomes usable after `openMediaRXChannel` returns success: it calls `openChannel`, reads `viper_channel_get_id(returned_channel)`, masks to 16 bits, and writes that id through the caller-supplied int pointer, which `RtpDispatcher::startVideoRX` supplied as dispatcher offset `+8` (`.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:47`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:39`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:41`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:42`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:43`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:44`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:45`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:51`, `.r33-evidence/native-disasm/disasm2-viper_channel_get_id.txt:9`).

`openChannel` itself creates a local channel object, records status-node state containing the channel pointer, sends `viper_tunnel_channel_open`, installs the receive callback on success, copies open-result local status into the caller status buffer, and returns zero for local request success. That is local request completion, not peer open-response completion (`.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:140`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:143`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:164`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:171`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:193`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:195`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:196`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:208`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:212`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:266`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:267`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:283`).

`onChannelOpenRes` is a later response handler. It locks the status list, matches the response by exact `viper_channel_str*`, reads channel type from the matching status node, maps peer error classes, unlocks, and calls `EvtSender::sendViperChannelOpenRes` (`.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:15`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:18`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:19`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:23`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:24`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:40`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:48`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:49`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:50`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:53`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:54`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:56`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:58`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:60`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:62`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:65`).

Therefore `csp_send_mediareq26` OPEN is emitted after local media-channel request success and callback installation, but before any required `onChannelOpenRes` wait. `CallFsm::start_videorx` immediately performs local RX/channel setup before the mediareq emit (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:33`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:39`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:73`).

The first RTP is not statically gated on `onChannelOpenRes` by the visible native caller path. The native code has installed the media channel receive callback and emitted the call-bound media request before the response handler is required by any visible branch. This proves "response required before RTP" is false as a native control-flow requirement; it does not prove a peer will always send RTP before such a response.

Failure/reject model:

- Local channel-create/open/callback failure inside `openChannel` returns failure to `openMediaRXChannel`, leaving no usable channel id and preventing successful tunnel-form mediareq construction (`.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:154`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:177`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:188`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:196`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:213`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:218`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:232`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:237`).
- Peer reject is delivered later through `onChannelOpenRes`, mapped to a `ViperChannelError`, and sent as an event via `EvtSender::sendViperChannelOpenRes`; it is not a synchronous return value to `CallFsm::start_videorx` (`.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:53`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:54`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:56`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:58`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:60`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:62`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:65`).

Production helper implication: wait for local media RX channel allocation and usable channel id before building tunnel-form `mediareq26`, then wait for actual media progress or an explicit asynchronous channel-open reject/event. It must not block `mediareq26` OPEN solely waiting for `onChannelOpenRes`, because native does not.

`CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_MEDIAREQ26=false`.

`CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_RTP=false`.

`CHANNEL_OPEN_REJECT_HANDLING=model`.

CHILD B - VIPER MEDIA RX CHANNEL LOW-LEVEL ABI

Reconstructed low-level primitive chain:

| Primitive | Arguments / return | Ownership and lifetime | Channel type/id/callback contract | Evidence |
|---|---|---|---|---|
| `RtpDispatcher::startVideoRX(int, in_addr*)` | dispatcher method; returns negative on failure and non-negative on success | On tunnel path it owns dispatcher slots: channel pointer at `+0`, channel id at `+8`, active flag at `+136`; it returns before peer open response | Calls `ViperTunnel::openMediaRXChannel(cb, &dispatcher[+8], opaque)` when tunnel is available, then `CallFsm` emits mediareq26 OPEN | `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:37`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:47`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:49`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_startVideoRX.txt:50` |
| `ViperTunnel::openMediaRXChannel(int (*)(viper_channel_str*, void*, void*, int), int*, void*)` | callback, out-id pointer, callback opaque; returns `viper_channel_str*` or null-equivalent on local failure | Caller stores returned pointer; out-id is filled only after local channel create/open succeeds | Uses media RX channel type through `openChannel`; reads `viper_channel_get_id(ch) & 0xffff` and writes caller id | `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:39`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:41`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:44`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openMediaRXChannel.txt:51` |
| `ViperTunnel::openChannel(ViperChannelType, cb, opaque, status*, open_param*, bool)` | channel type, receive callback and opaque, caller status buffer, open params, bool flag; returns `0` on local request success | Creates a status-node/channel pair, sends local open, installs receive callback on success, copies local status out | Pairs later responses by exact channel pointer in the status list; local return is not peer response | `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:140`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:143`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:195`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:212`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:266`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:283` |
| `viper_tunnel_channel_create` | tunnel object plus channel create params; returns channel pointer | Allocates the vendor channel object; ownership is then held by ViperTunnel status state | Produces the `viper_channel_str*` later passed to open, callback install, id read, close | `.r33-evidence/native-disasm/disasm-viper_tunnel_channel_create.txt:1`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:143` |
| `viper_tunnel_channel_open` | channel pointer/open params; returns local open request status | Sends local channel-open request; does not wait for `onChannelOpenRes` | Successful local return permits callback install and status copy | `.r33-evidence/native-disasm/disasm2-viper_tunnel_channel_open.txt:1`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:195` |
| `ViperTunnel::setReceivedCbk(viper_channel_str*, cb, opaque)` | channel pointer, `int (*)(viper_channel_str*, void*, void*, int)`, opaque; returns status | Callback is installed after local open succeeds and before `start_videorx` emits mediareq26 OPEN | Callback receives the channel pointer plus payload/opaque/length-like scalar and belongs to the live channel pointer lifetime | `.r33-evidence/native-disasm/disasm2-ViperTunnel__setReceivedCbk_viper_channel_str___int_____viper_channel_str___void___void___.txt:1`, `.r33-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:212` |
| `ViperTunnel::onChannelOpenRes(viper_channel_str*, viper_error)` | channel pointer, peer error; event handler return | Does not create ownership; reads status-node state under lock and emits an event | Open-response pairing is by exact channel pointer/status node, maps peer error to event sender | `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:15`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:23`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:40`, `.r33-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:65` |
| `CallFsm::stop_videorx()` | no explicit args; method return | Emits call-bound STOP first, then hands dispatcher ownership to local stop | Requires `CallFsm+840` bit2 and dispatcher active flag before STOP/teardown | `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:17`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:21`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:65` |
| `RtpDispatcher::stopVideoRX()` | dispatcher method; returns stop status scalar | Clears active flag, then closes saved tunnel channel pointer/id or socket RTP session | For tunnel mode, passes dispatcher pointer `+0` and id `+8` to `closeMediaRXChannel` | `.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:18`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:22`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:37`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:39` |
| `ViperTunnel::closeMediaRXChannel(viper_channel_str*, int)` | channel pointer and expected channel id; no useful returned object | Validates id, finds status node, marks closed; after this call future helper-local state must treat pointer/id as invalid | Calls `viper_channel_get_id`, matches status node pointer, calls `setChannelStatus(..., state=3, close/free flag)` | `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:24`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:32`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:34`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:43`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:73` |
| `ViperTunnel::setChannelStatus(status*, state, bool)` | status node, channel state, close/free bool | Writes status state; when close/free applies, closes the channel, removes list node, and deletes it | State `3` is closed in this path; close/free calls `closeChAndFreeStructure` then unlinks/deletes status node | `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:34`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:35`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:79`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:90` |
| `viper_channel_close` / `ViperTunnel::onChannelClosed` | channel pointer; close returns zero or failure | `viper_channel_close` sends a channel-close frame when applicable, sets channel state closed, then invokes close callback; `onChannelClosed` is notification/logging only in the staged body | Close callback receives tunnel context, channel pointer, and callback opaque | `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70779`, `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70812`, `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70815`, `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70821`, `.r33-evidence/native-disasm/disasm-ViperTunnel_onChannelClosed.txt:8`, `.r33-evidence/native-disasm/disasm-ViperTunnel_onChannelClosed.txt:18` |

Availability and ABI checks:

1. Packaged helper links/bundles inspected: `custom_components/comelit/native/comelit-media` is an x86-64 musl PIE with direct `NEEDED` entries only for `libnice.so.10`, `libgobject-2.0.so.0`, `libglib-2.0.so.0`, and `libc.musl-x86_64.so.1`; its bundled `native/lib/` contains the glib/nice/musl support set, not `libvipcomelit.so`, `libsafecomelit.so`, or `libcomelitvipkit.so` (local `file/readelf` inspection of `custom_components/comelit/native/comelit-media`; `safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt:11`, `safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt:12`).
2. Official library ELF evidence: staged disassembly headers for the official `libvipcomelit.so` record `file format elf64-littleaarch64`, while the helper is `ELF 64-bit LSB pie executable, x86-64` with musl interpreter. The staged provenance also records the official library hashes and source host context (`.r33-evidence/native-disasm/PROVENANCE.txt:1`, `.r33-evidence/native-disasm/PROVENANCE.txt:4`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:3`, `.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:3`).
3. Export/import sides: the official symbol inventory exports the Viper/CallFsm/RtpDispatcher chain and `viper_tunnel_channel_create`; helper dynamic symbols import libnice/glib/musl and do not import or export `ViperTunnel`, `RtpDispatcher`, `csp_send_mediareq26`, `viper_tunnel_channel_create`, or `viper_tunnel_channel_open` (local `nm -D custom_components/comelit/native/comelit-media`; `.r33-evidence/native-disasm/symbol-inventory.txt:1`, `.r33-evidence/native-disasm/symbol-index-batch2.txt:1`, `.r33-evidence/native-disasm/symbol-index-batch3.txt:1`).
4. Headers/source fragments: the research tree contains public Python integration fragments under `.r33-evidence/public-vip/`, but no C/C++ header that makes the proprietary `ViperTunnel` object ABI callable from the helper. The public fragments are corroboration only, not a linkable ABI.
5. `dlopen`/import feasibility: statically blocked for the packaged helper because the official libraries are not bundled, not listed in `DT_NEEDED`, and the helper lacks imports for the required C++/C symbols. Adding the vendor library would also be a new runtime dependency, which this run does not propose or add.
6. ABI compatibility: blocked for direct primitive calls. The staged official disassembly is AArch64 C++ object ABI; the packaged helper runtime artifact is x86-64 musl C. Even where names are exported in the official library, the object layout, calling convention, and architecture are not callable from the available runtime artifact.

Critical answer:

```text
HIGH_LEVEL_EQUIVALENT=false
LOW_LEVEL_PRIMITIVES_AVAILABLE=false
```

The high-level helper components are not equivalent to the vendor channel primitives because they do not own a `viper_channel_str*`, status node, peer open-response pairing, or `ViperTunnel` callback contract. The low-level primitives are proven in the official native library, but they are physically absent from the packaged helper runtime ABI.

Minimal helper-local state model for a future wire-contract implementation:

| Field | Required by proven ordering? | Reason |
|---|---|---|
| `call_ctp_id` / call-transaction handle | yes | mediareq26 OPEN and STOP use `CallFsm+48`, not registered CTPP (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:46`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:31`) |
| `media_rx_channel_pointer_equivalent` | yes as a helper-local allocation token | Native pairs close/open response by channel pointer/status node; helper needs an equivalent identity even if not a vendor pointer |
| `media_rx_channel_id` | yes | OPEN/STOP body `8..9` uses saved dispatcher id; close validates pointer/id before status change |
| `media_open_pending` | yes | OPEN is locally requested before peer response; peer response is asynchronous |
| `media_open_confirmed` | yes for observability/reject handling | `onChannelOpenRes` can later report peer success/failure, although it is not a precondition for mediareq26 OPEN |
| `video_rx_active` | yes | `stop_videorx` and `stopVideoRX` gate teardown on active state |
| `rtp_sink_forwarding_state` | yes | Future helper must enable/disable RTP forwarding around the media-only lifetime and report RTP counters |
| `pairing_status_node_state` | yes as bounded enum | Native close finds status node and transitions state `3` before close/free |
| `stop_sent` / `open_sent` counters | yes | Proven native path has at most one OPEN per transition and one STOP before disposal |

CHILD D - STOP / DISPOSAL ORDER

Answers with anchors:

1. STOP before local disposal is proven for the guarded native path. `CallFsm::stop_videorx` builds STOP fields, calls `csp_send_mediareq26`, then loads the dispatcher and calls `RtpDispatcher::stopVideoRX` (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:31`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:38`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:65`).
2. Awaiting a STOP ACK/response is not proven and is not visible in the static path. There is no branch between `csp_send_mediareq26` STOP and `RtpDispatcher::stopVideoRX`; the next visible call after STOP is local teardown (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:65`).
3. `closeMediaRXChannel` is synchronous as a local method call through validation/status mutation, but the underlying channel close notification is callback/event-shaped. `RtpDispatcher::stopVideoRX` calls it directly; `closeMediaRXChannel` validates pointer/id and calls `setChannelStatus`; `viper_channel_close` can send a channel-close frame and invoke a close callback (`.r33-evidence/native-disasm/disasm-RtpDispatcher_stopVideoRX.txt:39`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:32`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:73`, `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70812`, `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt:70821`).
4. The channel pointer/id become invalid for future helper use once `closeMediaRXChannel` has accepted the matching pointer/id and `setChannelStatus` has closed/unlinked/deleted the status node. The native code removes the list node and deletes it in `setChannelStatus` (`.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:34`, `.r33-evidence/native-disasm/disasm-ViperTunnel_closeMediaRXChannel.txt:43`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:79`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:83`, `.r33-evidence/native-disasm/disasm2-ViperTunnel__setChannelStatus_ViperTunnelSt__ViperChannelStatus___ViperTunnelSt__ChannelSt.txt:90`).
5. The inbound call/persistent listener can continue after media-only stop in the visible path. `stop_videorx` emits media STOP and calls dispatcher media teardown only; it does not call CTP release, registration close, PseudoTCP close, process exit, Door, or Gate (`.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:63`, `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt:65`; prior component contrast `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:333`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:336`).
6. States forbidding a second OPEN: no call signaling barrier, no local media RX channel/id, OPEN already pending, OPEN already active/confirmed, STOP already sent, media channel disposed, wrong channel id, or using the registration handle instead of the call transaction. Native evidence proves the active/allocation guards and mutually exclusive OPEN call sites; the R33 scalar trace enforces the future helper fail-closed rules (`.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:19`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:37`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:38`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:73`, `.r33-evidence/native-disasm/disasm-CallFsm_start_videorx.txt:119`; `safety-poc/research/media/v1/entrance_p116_r33_offline_scalar_trace_model.py`).

Future implementation idempotency/fail-closed rules:

- Emit one STOP per active media transition, before local media disposal.
- Do not await a STOP ACK unless later evidence proves one; report `STOP_ACK=UNPROVEN` rather than retry.
- Do not emit a second OPEN without a new call-bound OPEN transition and a fresh media RX channel identity.
- Do not fabricate STOP without a proven prior OPEN on the same call transaction and same channel id.
- On close mismatch, unknown pointer/id, or unproven teardown order, report teardown as `UNPROVEN`/fail closed and do not retry.
- Preserve persistent listener/call transaction unless a separate call-release path is explicitly proven.

`MEDIA_STOP_ORDER=PROVEN`

CHILD E - OFFLINE SCALAR TRACE

Created `safety-poc/research/media/v1/entrance_p116_r33_offline_scalar_trace_model.py` with focused tests in `safety-poc/tests/test_p116_r33_offline_scalar_trace.py`.

The model reuses the R30B call-transaction model: it imports `create_call_transaction`, `InterceptedWriter`, and the R30B `intercept_media_open` / `intercept_media_stop` serialization path, then adds only R33 media-RX channel scalar state. It does not duplicate the R30B CTP envelope parser or mediareq26 packet builder.

Trace order:

```text
CALL_INIT captured
CALL_CTP captured
MEDIA_RX local channel allocate
CALL_BOUND_MEDIAREQ26_OPEN
channel response / state transition
RTP enabled
CALL_BOUND_MEDIAREQ26_STOP
media RX channel dispose
listener / call transaction preserved
```

Gates asserted by tests:

```text
NETWORK_TX=0
NEW_ICE=0
NEW_CLOUD=0
NEW_PSEUDOTCP=0
NEW_REGISTRATION=0
OPEN_COUNT<=1
STOP_COUNT<=1
DOOR=0
GATE=0
```

Fail-closed negative cases covered: STOP before OPEN, second OPEN, wrong channel id for open response/STOP/dispose, dispose before STOP, and OPEN on the registration handle instead of the call transaction.

`OFFLINE_SCALAR_TRACE=PASS`

CHILD F - IMPLEMENTABILITY DECISION

Classification:

```text
CASE 3: the required low-level primitives are physically absent from the available runtime ABI
```

`FIELD_LAYOUT=PROVEN`, `MEDIA_RX_CHANNEL_OPEN_MODEL=PROVEN`, and `MEDIA_RX_CHANNEL_CLOSE_MODEL=PROVEN` as static native models. However `LOW_LEVEL_PRIMITIVES_AVAILABLE=false` for the packaged helper runtime: the helper is x86-64 musl, has no `DT_NEEDED` entry for the official VIP libraries, has no dynamic imports for the Viper/CallFsm/RtpDispatcher symbols, and the official staged disassembly is AArch64 C++ object ABI. Therefore calling vendor primitives is architecturally blocked in the available runtime. This run does not propose emulation of an unknown protocol; it records the proven wire/lifetime contract and the runtime ABI blocker.

Can the attached path be implemented without adding a new runtime dependency? `NEW_RUNTIME_DEPENDENCY_REQUIRED=false` for the remaining viable route: wire-contract reimplementation inside the existing helper, which already constructs and writes raw VIP/CTP frames in prior R30B offline modeling. `NEW_RUNTIME_DEPENDENCY_REQUIRED=true` would apply only to the rejected vendor-primitive-calling route, because it would require adding unavailable proprietary native libraries and cross-ABI bindings.

`IMPLEMENTATION_READY_OFFLINE=false` under the CASE 1 definition, because low-level vendor primitives are not available in the helper runtime ABI. The exact implementation work remaining is not "call `ViperTunnel::openMediaRXChannel`"; it is helper-local call-bound mediareq26 open/stop construction, media RX channel-id allocation/state, and RTP sink gating using the existing helper's raw frame machinery.

`EVIDENCE_REQUEST=none for field layout/open-close ordering; future implementation needs design approval for helper-local wire-contract reimplementation because vendor primitive calls are blocked by runtime ABI.`

OBSERVABILITY

Future safe markers must remain measured counters or bounded scalars only:

```text
ATTACHED_CALL_CTP_CAPTURED=true
MEDIA_RX_CHANNEL_CREATED=true
MEDIA_RX_CHANNEL_OPEN_RESPONSE=PASS|FAIL|NOT_SEEN
CALL_BOUND_MEDIA_OPEN_SENT_COUNT=<bounded integer>
CALL_BOUND_MEDIA_STOP_SENT_COUNT=<bounded integer>
MEDIA_RX_CHANNEL_CLOSE_COUNT=<bounded integer>
MEDIA_RC6_STAGE_INDEX=<bounded integer>
VIDEO_RTP_COUNT=<bounded integer>
AUDIO_RTP_COUNT=<bounded integer>
ICE_BOOTSTRAP_DELTA=<bounded integer>
CLOUD_NEGOTIATION_DELTA=<bounded integer>
PSEUDOTCP_OPEN_DELTA=<bounded integer>
CTPP_REGISTRATION_DELTA=<bounded integer>
```

Do not print raw call CTP ids, channel ids beyond bounded synthetic/offline scalars, addresses, payloads, credentials, or packet bytes.

VERIFICATION

Commands run:

```bash
cd safety-poc
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r33_offline_scalar_trace -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
```

Results:

- Focused R33 trace tests: `Ran 10 tests in 0.006s`, `OK`.
- Full discovery: `Ran 1586 tests in 38.847s`, `FAILED (failures=1, errors=2, skipped=5)`, with only accepted failures: `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch` and the two R29I UDP sink tests `test_zero_datagram_sink_materializes_final_counter_after_exit` / `test_nonzero_datagram_sink_materializes_final_counter_after_exit`.
- Static safety: `STATIC_SAFETY_CHECK=PASS`, `NETWORK_IMPORTS_PRESENT=false`, `COMELIT_ENDPOINTS_PRESENT=false`, `SOURCE_FILES_SCANNED=29`.

EVIDENCE DISCIPLINE / PROVENANCE

Primary evidence is the staged, git-excluded R33 text disassembly under `safety-poc/research/media/v1/.r33-evidence/native-disasm/`. The source library identity recorded by the staged provenance is `libvipcomelit.so` SHA256 `465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0`; companion library hashes are recorded there as analysis context only (`.r33-evidence/native-disasm/PROVENANCE.txt:1`, `.r33-evidence/native-disasm/PROVENANCE.txt:2`, `.r33-evidence/native-disasm/PROVENANCE.txt:3`).

The staged text was produced with GNU objdump 2.42, fetched from CT120 on 2026-09-13, and explicitly marked `git-invisible analysis input; text-only; never commit` (`.r33-evidence/native-disasm/PROVENANCE.txt:4`, `.r33-evidence/native-disasm/PROVENANCE.txt:6`, `.r33-evidence/native-disasm/PROVENANCE.txt:7`, `.r33-evidence/native-disasm/PROVENANCE.txt:8`).

External public code under `.r33-evidence/public-vip/` is corroboration only. The conclusions in this document are `PROVEN_STATIC` from the official binary disassembly unless explicitly marked `PARTIAL`.

No production implementation, no `custom_components/**`, no `docs/**`, no native production binary, and no other existing `P116_*` document was modified by this run.

=== COMELIT P116 R33 PRIMITIVE CLOSURE (REPO DOC) ===
BASE_SHA=4ef019cf3fd240ceae4663d82d91a2cdca17f600
R32_HEAD=d8cb8083fd583282660c1227f10b72d94f148f34
CALL_CTP_CAPTURE_MODEL=PROVEN
MEDIAREQ26_BODY_LENGTH=26
MEDIAREQ26_FIELD_LAYOUT=PROVEN
MEDIAREQ26_UNKNOWN_FIELD_COUNT=0
MEDIAREQ26_OPEN_CONTRACT=PROVEN
MEDIAREQ26_STOP_CONTRACT=PROVEN
LOW_LEVEL_VIPER_PRIMITIVES_AVAILABLE=false
MEDIA_RX_CHANNEL_OPEN_MODEL=PROVEN
MEDIA_RX_CHANNEL_CLOSE_MODEL=PROVEN
CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_MEDIAREQ26=false
CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_RTP=false
MEDIA_STOP_ORDER=PROVEN
OFFLINE_SCALAR_TRACE=PASS
R29B_GAP_CLOSED=true
IMPLEMENTATION_READY_OFFLINE=false
NEW_RUNTIME_DEPENDENCY_REQUIRED=false
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
NORMATIVE_DOCS_CHANGED=false
LIVE_INVOCATIONS=0
NETWORK_TX=0
SYNTHETIC_TRIGGERS=0
PHYSICAL_RING_ACTIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOYS=0
HA_RESTARTS=0
RESULT=BLOCKED_RUNTIME_ABI
=== END COMELIT P116 R33 PRIMITIVE CLOSURE (REPO DOC) ===
