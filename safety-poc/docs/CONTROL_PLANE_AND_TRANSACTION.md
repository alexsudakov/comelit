# Offline CTPP control plane and Door transaction

## CTPP control-plane model

`control_plane_model.py` is a pure repository fixture model. It contains no codec/network implementation.

States:

`CLOSED -> OPEN_REQUESTED -> OPENED -> CLOSE_REQUESTED -> CLOSED/UNKNOWN`

A successful synthetic open binds exactly one `ChannelBinding(channel_name="CTPP", channel_id=7449)`. The seed is retained from the canonical fixture baseline; it is not claimed to be a live channel id. Open and close may each be invoked at most once by one model instance.

Control-plane protocol acknowledgement is only evidence that the synthetic channel-open contract succeeded. It is never a physical actuator claim and is not a Door-command acknowledgement.

## Full offline transaction model

`door_transaction.py` composes the synthetic control-plane model with the fixed six-write semantic sequence:

1. `OPEN_CTPP`
2. `INIT_A`
3. `OPTIONAL_WAIT_A`
4. `COMMAND_PRIMARY`
5. `CONFIRM_PRIMARY`
6. `INIT_B`
7. `OPTIONAL_WAIT_B`
8. `COMMAND_FINAL`
9. `CONFIRM_FINAL`
10. `CLOSE_CTPP`

Only the six INIT/COMMAND/CONFIRM steps count as Door payload writes.

Safety classification is relative to the physical Door payload boundary:

- failure before any Door write -> `PROVEN_NOT_SENT`;
- ambiguous/rejected channel open with fixture proof of zero Door writes -> `PROVEN_NOT_SENT`;
- failure after one or more Door writes -> `AMBIGUOUS`;
- complete six-write transaction without a Door-specific acknowledgement -> `ACCEPTED_NO_ACK`, therefore executor state `UNKNOWN_OUTCOME`.

The model is invoked through the existing `BoundaryTransportAdapter`, so duplicate `operation_id` handling remains owned by `OneShotExecutor` and cannot repeat the transaction.

## Runtime work still required

The synthetic model does not claim `CTPP_CONTROL_PLANE_RECONCILIATION=PASS` or `FULL_OFFLINE_DOOR_TRANSACTION=PASS`. Those gates require the pinned CT120 canonical codec/session stack to be reconciled through `FixtureTransport` using verified control responses and synthetic Door body data.
