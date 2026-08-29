# v0.5 Offline Wire-Shape Reconciliation

v0.5 proves the framing boundary between the pinned legacy research implementation and the canonical ViP session stack without extracting or using a real Door payload.

## Proven model

For synthetic bodies only:

- legacy `_create_binary_packet_from_buffers(request_id, body)` produces the same bytes as canonical `VipSession.send_frame(request_id, body)` emits to `FixtureTransport`;
- the framing overhead is exactly 8 bytes for the pinned sources;
- passing an already legacy-framed packet as the canonical `body` adds another 8-byte header and is therefore rejected as double framing;
- all six symbolic Door-semantic writes use one synthetic CTPP channel id (`7449`), matching the legacy call shape where the channel id is the ViP `request_id`;
- the canonical path alone owns outer ViP framing.

## Deliberate exclusions

v0.5 does not:

- extract real Door command bytes;
- import credentials;
- execute `open_channel()`;
- create a socket or real transport;
- claim a protocol ACK;
- claim a physical relay effect;
- retry after an ambiguous write.

A complete six-frame synthetic reconciliation maps to `ACCEPTED_NO_ACK` and therefore `UNKNOWN_OUTCOME`. A failure after any fixture write maps to `AMBIGUOUS`.
