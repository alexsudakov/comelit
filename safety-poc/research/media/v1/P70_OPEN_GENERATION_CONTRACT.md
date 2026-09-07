# P70: RTPC OPEN generation provenance

P69 separated structural RTPC OPEN/RESPONSE pairing from the previously guessed
zero value at byte 14. The frozen official-app capture then showed all three
RTPC OPEN bodies using byte 14 value `1`, while the same session uses `0` for
ECHO, UAUT, UCFG, CTPP, CSPB and PUSH OPEN bodies.

P70 does not add another live experiment. It composes the already accepted P66
runtime-ID evidence and P69 structural/trailer evidence with an independent
Comelit ViP implementation whose protocol encoder and video flow expose the
same field explicitly as `trailing_byte`.

## Local evidence

Frozen capture SHA-256:

`f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a`

Accepted local contracts:

- P66: two client RTPC target/request IDs behave as client-originated runtime
  correlation IDs; they are distinct and non-zero, absent from earlier bounded
  CONTROL traffic and echoed by later device CONTROL traffic. The observed pair
  is sequential.
- P69: three 15-byte RTPC OPEN envelopes pair bijectively with the three
  opposite-direction OPEN responses, and byte 14 is `1` in the peer OPEN and
  both client OPENs.
- Existing non-media ViP builders in this repository use a zero trailing byte
  for ordinary channel OPENs.

The CT120 read-only inventory performed after P69 found only one stored RTPC
capture, so no claim of cross-session stability is derived from local captures
alone.

## Independent implementation evidence

Independent repository:

`antoiba86/hass-comelit-intercom-local`

Frozen reviewed ref:

`826d2c941cbe110ce3887494ae37fcaccd17bae0`

Reviewed files:

- `protocol_reference_mnestrud_6701W.md` describes the one-byte field after the
  channel request ID as `trailing_byte`, with value `0` for most channels and
  `1` for RTPC/UDPM, and shows an RTPC OPEN ending in `01`.
- `custom_components/comelit_intercom_local/protocol.py` exposes
  `trailing_byte` as the final byte of the normal channel OPEN primary block.
- `custom_components/comelit_intercom_local/video_call.py` opens two RTPC
  channels with `trailing_byte=1`.
- `custom_components/comelit_intercom_local/client.py` allocates channel-open
  request IDs locally by incrementing a session-local request-ID counter; the
  exact initial numeric value is implementation-local rather than copied from
  a capture.

This implementation targets a different Comelit deployment path, so P70 does
not use it to infer unrelated media signaling, endpoint behavior or timing. It
is used only as independent provenance for the generic ViP OPEN field and the
RTPC-specific value/allocation relation that exactly matches our capture.

## Contract promoted by P70

P70 promotes these generation rules:

1. A client RTPC OPEN uses the already proven 15-byte ABCD OPEN envelope:
   operation `1`, declared primary length `7`, wire channel name `RTPC`.
2. The two client target/request IDs are locally generated runtime IDs, must be
   non-zero, distinct, collision-free and sequential for the pair. Literal IDs
   from the frozen capture must never be replayed.
3. The final byte at body offset 14 is generated as `1` for RTPC OPEN.

The word-level *meaning* of the RTPC trailing byte remains unknown. P70 proves a
reproducible generation rule, not the business semantics of the bit/value.
Therefore:

- `RTPC_OPEN_TRAILING_GENERATION_CONTRACT=PASS`
- `OPEN_TRAILER_SEMANTICS=NOT_PROVEN`
- `RTPC_RUNTIME_ID_GENERATION_CONTRACT=PASS`
- `RTPC_OPEN_BODY_GENERATION_CONTRACT=PASS`

P70 still does **not** authorize a live run. Live transmission requires a
separate candidate/review gate with bounded one-shot behavior, listener
isolation/restoration, no Door surface and explicit response validation.

## Safety boundary

P70 is offline only. It creates no sockets, performs no DNS/HTTP/ICE/STUN/TURN
activity, sends no CTPP/RTPC/media signaling, does not stop or start the
persistent listener, does not touch Door, and does not decode or emit media
payload.
