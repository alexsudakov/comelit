# P116 / R30 — call-bound CTP envelope recovery

Status: **research / offline**

TASK_ID=`COMELIT-P116-R30-CALL-BOUND-CTP-ENVELOPE-RECOVERY`

BASE_MAIN=`2eb453b36fb6a58276405a99d09858c89731744f`

LIVE_RUN=`NOT_RUN`

NETWORK_TX=`0`

PRODUCTION_FILES_CHANGED=`0`

## 1. Why R30 exists

The final R29I live acceptance closed the bounded experimental hypothesis that a bare 26-byte `mediareq26` written directly as payload of the already-open registered CTPP channel is enough to start inbound media.

Observed live facts were:

- one real inbound Entrance call was accepted by the persistent research listener;
- exactly one R29C registered-CTPP OPEN was sent;
- the candidate remained alive for the full 30.015 s media observation window;
- finalized video/audio sinks were numeric `0/0`;
- candidate runtime video count was `0`;
- no peer media-open response was observed;
- ICE/cloud/PseudoTCP/registration generations remained unchanged;
- cleanup and production-listener restore passed.

Therefore:

`R29_REGISTERED_CTPP_BARE_MEDIAREQ26_RESULT=LIVE_NEGATIVE_FOR_TESTED_PATH`

This does **not** refute the official native call-bound media path. R29A already proved that native `CallFsm::start_videorx` passes a stored inbound call CTP id to `csp_send_mediareq26`, which then invokes `ctp_write(call_ctp_id, msg, 26)`.

R30 resolves the missing layer between the persistent CTPP channel and that call-scoped CTP transaction.

## 2. Layer correction: CTPP channel vs CTP connection

The current listener uses `v4_ctpp_channel_id` as the request id / handle of the already-open **outer Viper CTPP channel**. That value selects which Viper channel carries CTP traffic; it is not the CTP call transaction id.

Inside each payload on that outer CTPP handle there is a separate CTP packet envelope:

```text
offset  size  meaning
0       1     CTP flags
1       1     CTP version (0x18)
2       2     CTP connection id
4       1     CTP sequence
5       1     CTP acknowledgement
6       2     inner CTP body length, big endian
8       N     inner CTP body
...           zero padding to four-byte boundary
...     4     trailer marker
...     10    source logical address
...     10    destination logical address
```

This layout is corroborated by pinned public `jfmlima/comelit-vip` ref `e3714dcccadb5bf934c32ce1400d891c3cfc61bb`, `viper/ctp.py`, and is independently visible in our existing helper serializers.

`OUTER_CTPP_HANDLE_IS_CALL_TRANSACTION=false`

`CALL_TRANSACTION_CONNECTION_FIELD=CTPP_PAYLOAD_BYTES_2_3`

## 3. Existing CALL_INIT parser was already looking at a CTP header

The persistent helper currently admits frames only when the outer frame request id equals `v4_ctpp_channel_id`, then computes:

- `read_le16(body + 0) == 0x18C0`;
- big-endian `body[6:8] == 0x0028`;
- address/source containment inside the same payload.

Those fields were historically named `prefix` and `action`. R30 recovers their actual layer semantics:

- bytes `C0 18` are CTP `SYN` flags plus version `0x18`;
- bytes `00 28` are the inner CTP body length, decimal 40;
- the real inner opcode begins at offset `8`;
- for an inbound call that opcode is `0x0001` (`INVITE`).

So the current listener has been observing a complete call-scoped CTP packet but was not decoding its connection/sequence/ack fields.

`CURRENT_CALL_INIT_PREFIX_NAME=LEGACY_MISNOMER_FOR_CTP_FLAGS_VERSION`

`CURRENT_CALL_INIT_ACTION_NAME=LEGACY_MISNOMER_FOR_CTP_BODY_LENGTH`

`CURRENT_CALL_INIT_INNER_OPCODE_OFFSET=8`

A future production-quality parser should require the actual inner `INVITE` opcode as well as the existing source/door checks instead of treating SYN + length 40 alone as the message identity.

## 4. The missing call CTP id is already present in the listener payload

For inbound CTP SYN traffic, the two bytes at offsets `2..3` are the peer-selected CTP connection id. The same envelope also exposes peer sequence and acknowledgement bytes at offsets `4` and `5`.

Pinned public `comelit-vip` independently adopts an inbound connection by:

```text
packet.connection                = peer CTP connection id
peer_connection_id(connection)   = same 15-bit id with direction bit toggled
CtpConnection.peer_id            = received id
CtpConnection.local_id           = toggled id
acknowledgement                   = received sequence + 1
```

The public implementation stores the logical application `call_id` parsed from the INVITE body separately. Therefore the following are different identifiers:

- outer Viper CTPP channel handle;
- CTP connection id in envelope bytes `2..3`;
- logical call id inside the 40-byte INVITE body.

`INBOUND_CALL_CTP_CAPTURE_IMPLEMENTABLE=true`

`CALL_TRANSACTION_SEPARATE_FROM_OUTER_CTPP_HANDLE=true`

`LOGICAL_CALL_ID_IS_CTP_CONNECTION_ID=false`

The exact direction-bit convention expected by the official native `ctp_write(call_ctp_id, ...)` API is still a native-side semantic detail; R30 does not promote the public implementation's local-id transform to an official protocol constant. It is suitable for an offline candidate model and must be independently gated before any future wire authorization.

## 5. Major correction: P76 `client_001a` is already a full CTP packet

The old helper lineage calls `p76_build_client_001a` a 60-byte client `0x001A` body. Its actual byte layout shows something more useful:

```text
0..1    40 18              CTP DATA flags + version
2..5    composite state    CTP connection + sequence + acknowledgement
6..7    00 1A              inner body length = 26
8..9    00 11              inner opcode = MEDIA_REQUEST
10       14                 media open action
11       32                 media flags
12..33                       remaining 26-byte mediareq fields
34..35                       CTP body padding
36..39   FF FF FF FF        CTP trailer marker
40..49                       source logical address
50..59                       destination logical address
```

The total length follows directly from CTP framing:

`8 header + 26 inner body + 2 padding + 24 trailer = 60 bytes`.

Thus:

`P76_CLIENT_001A_IS_FULL_CTP_MEDIA_PACKET=true`

`P76_001A_NAME_REFERS_TO_CTP_BODY_LENGTH_NOT_MEDIA_OPCODE=true`

`P76_INNER_MEDIA_OPCODE=0x0011`

This is important because we do **not** need to invent the entire call-bound media serializer from scratch. An existing helper lineage already contains the correct full-packet structural shape; what is unproven is rebinding its CTP transaction state and media-channel state to the inbound call.

## 6. Why R29C produced zero RTP

R29C intentionally tested the registration-channel hypothesis by constructing only the 26-byte inner `mediareq26` and calling:

```text
p12_queue_vip_frame(v4_ctpp_channel_id, body, 26, ...)
```

That sends the 26-byte media request directly as the payload of the outer CTPP Viper channel. It does not add the CTP connection header, sequence/ack, padding, or source/destination trailer around the media request.

The final R29I live negative result is therefore consistent with the recovered layering:

`R29C_WIRE_FORM=BARE_MEDIAREQ26_ON_OUTER_CTPP_HANDLE`

`NATIVE_WIRE_FORM=MEDIAREQ26_INSIDE_CALL_SCOPED_CTP_PACKET_ON_OUTER_CTPP_HANDLE`

`R29C_NEGATIVE_RESULT_DOES_NOT_REFUTE_CALL_BOUND_CTP_MEDIA=true`

No additional live attempt is authorized or needed to establish this offline distinction.

## 7. What is now proven vs still unknown

### Proven / strongly supported offline

- The persistent registered CTPP handle is only the outer carrier.
- The listener receives a full inner CTP packet on that handle.
- The inbound call's CTP connection id is present at payload bytes `2..3`.
- Sequence and acknowledgement bytes are present at `4` and `5`.
- The inner CTP body starts at offset `8`.
- The inbound INVITE inner body length is 40.
- The logical call id in the INVITE body is distinct from the CTP connection id.
- Existing P76 code serializes a full 60-byte CTP media-request packet with a 26-byte inner `OP_MEDIA_REQUEST` body.
- R29C's final live experiment sent only the inner 26-byte request and therefore tested a different wire form from the native call-bound path.

### Still blocked before any future live candidate

1. **Inbound call adoption / ACK.** The current helper observes CALL_INIT but does not yet own a call-scoped CTP state object. The exact safe sequence for adopting and ACKing the inbound SYN must be modeled and intercepted offline first.
2. **Direction-bit / local connection id.** Public corroboration uses XOR `0x8000`; official native `ctp_write` internal-id semantics need a bounded equivalence gate before wire use.
3. **Per-call sequence/ack evolution.** The helper's historical `previous_client_ctpp_sequence` is actually composite CTP transaction header state. R30B must name and update its fields correctly instead of treating the 32-bit word as one sequence scalar.
4. **Media channel allocation.** Native video RX opens/stores a Viper media channel before emitting the call-bound media request. Existing P76 target allocation is only component-level evidence; a call-bound media-channel lifetime must be made explicit.
5. **STOP.** Stop serialization can only be promoted after an OPEN state is structurally valid; no new live STOP is authorized.

## 8. R30A implementation in this branch

This branch adds only offline artifacts:

- `entrance_p116_r30_call_ctp_envelope_model.py`
- `test_p116_r30_call_ctp_envelope_recovery.py`
- this document.

The model:

- parses CTP envelopes;
- distinguishes the call CTP connection from outer CTPP handle and logical call id;
- models the peer/local direction-bit transform as corroborating behavior;
- builds a full call-bound CTP DATA packet around an existing 26-byte media request;
- requires the result to be exactly 60 bytes;
- performs no network I/O.

The focused tests additionally inspect current repository source to prove:

- the current CALL_INIT classifier is reading CTP header fields;
- P76's 60-byte `client_001a` has full CTP packet structure;
- R29C queued only the bare 26-byte media request on the outer CTPP handle.

## 9. Next bounded child: R30B

R30B should remain **offline only** and should not require a new live authorization.

Goal:

```text
real/synthetic inbound CTP INVITE
-> capture call-scoped CTP connection + sequence/ack + addresses
-> create bounded per-call transaction state
-> intercepted call ACK/capability ordering model
-> allocate/persist one video media-channel id
-> serialize one full 60-byte call-bound CTP media OPEN
-> intercepted write only
-> serialize one full call-bound STOP only after OPEN state
-> intercepted write only
```

R30B acceptance must include exact zero network writes and zero Door/Gate/self-activation/repeat actions. It must not modify production HA code or the normative `docs/intercom-media-session-architecture.md`.

Only after R30B is fully accepted offline should we decide whether another physical live proof is justified. The final R29I authorization is consumed and cannot be reused.
