# CT120 runtime acceptance gates

The v0.6 repository separates portable repository CI from CT120-only fixture/runtime proofs.

## Entry point

`./scripts/run_ct120_runtime_gates.sh [output-directory]`

Default output directory: `/root/comelit-v0.6-runtime-gates`.

The runner performs no live Comelit connectivity and no physical Door action. It requires the pinned read-only research trees already present on CT120.

## Gate 1 — repository offline suite

Runs the package static-safety scan, all repository unit tests, and the existing one-shot crash/recovery CLI scenarios.

This proves repository semantics only. It intentionally reports the CT120-specific reconciliation markers as pending.

## Gate 2 — pinned legacy synthetic body oracle

`verify_legacy_synthetic_body_oracle.py`:

- verifies the exact legacy source SHA256;
- executes the pinned legacy Door methods only with deterministic synthetic mappings;
- replaces `_open_channel`, `_write_packet`, `_read_response`, and `_close_channel` with local in-memory doubles;
- captures exactly six legacy-generated frames;
- strips only the already-proven 8-byte ViP envelope for body metrics;
- reframes every synthetic body through the pinned canonical `VipSession + FixtureTransport` stack;
- requires byte-exact equality with all six legacy synthetic frames;
- emits no body bytes or literal credential values.

Success marker: `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`.

This is an offline synthetic oracle. It does not create a live Door payload backend and does not authorize one.

## Gate 3 — canonical capture-based session tests

Runs the pinned canonical modules:

- `tests.test_vip_session`;
- `tests.test_channel_session`;
- `tests.test_application_session`.

The channel-session module contains capture-derived local open/close tests, while all I/O is performed through the canonical fixture stack.

Success marker added by the runner: `CANONICAL_VIP_CAPTURE_TESTS=PASS`.

## Gate 4 — CTPP-specific canonical fixture

`verify_ctpp_control_plane_fixture.py` constructs synthetic `OpenChannelResponse` and `CloseChannelResponse` frames with the pinned canonical codec, then executes:

`VipChannelSession.open_channel("CTPP") -> close_channel(channel_id)`

through `FixtureTransport` only.

It proves:

- typed open request;
- exact `CTPP` channel name;
- one channel binding (`7449` in this offline fixture);
- typed close request bound to the same channel;
- one open and one close control write.

Success marker: `CTPP_CONTROL_PLANE_RECONCILIATION=PASS`.

## Gate 5 — full canonical offline transaction

`verify_full_offline_transaction_fixture.py` performs on one canonical `VipSession`:

`OPEN_CTPP -> six synthetic Door data frames -> CLOSE_CTPP`.

Expected writes: 8 total = 2 control + 6 data. All six data frames must use the single opened CTPP channel id and retain deterministic semantic order.

Success marker: `FULL_OFFLINE_DOOR_TRANSACTION=PASS`.

No Door protocol ACK or physical effect is asserted.

## Combined readiness

The runner concatenates gate reports and passes them to `evaluate_plan_readiness.py`. Repository readiness requires all repository gates to be `PASS`. Live-test readiness stays false because the live gates remain absent/false, including `REAL_TRANSPORT_IMPLEMENTED=false` and no explicit live-test approval.

## Safety boundary

A successful v0.6 runtime suite proves only an offline implementation contract. It does not:

- read Comelit secrets;
- establish a real Comelit session;
- perform an active network probe;
- send a Door/open/unlock command;
- assert relay movement;
- permit automatic retry after an ambiguous boundary.
