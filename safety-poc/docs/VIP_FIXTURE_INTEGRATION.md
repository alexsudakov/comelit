# Canonical ViP fixture integration — v0.3

v0.3 proves compatibility between the synchronous safety boundary and the canonical
`/root/comelit-vip-poc` session API without creating a network transport.

The runtime proof pins SHA256 for all eight canonical `comelit_vip/*.py` modules used
by the stack, injects `FixtureTransport`, and constructs exactly the canonical fixture
shape established by the existing tests:

`FixtureTransport -> VipSession(sync_on_first_frame=False) -> VipChannelSession(next_channel_id=7449) -> VipApplicationSession`

`7449` is a fixture/test channel-id seed only; this bridge does not infer or perform a
Door operation. A synthetic, non-Door body is emitted once through
`VipSession.send_frame()`. The fixture records exactly one write. Because no protocol
response is consumed, the boundary outcome is `ACCEPTED_NO_ACK`, which the safety
executor must persist as `UNKNOWN_OUTCOME`. A duplicate `operation_id` must not
produce a second fixture write.

This release contains no socket transport, no credentials, no Door payload, no
`IconaBridgeClient`, and no physical-action implementation.
