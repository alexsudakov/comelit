# v0.6 — CTPP body-layout reconciliation

v0.6 starts with a read-only structural inventory of the pinned legacy Door implementation. The goal is to learn the CTPP **body construction shape** without importing credential-bearing Door payload bytes into Git and without executing the legacy client.

## Stage A — structural inventory

`./scripts/legacy_body_shape_inventory.py` parses `/root/comelit-poc/comelit_client.py` with Python AST only after verifying the pinned SHA256.

The inventory may report structural metadata such as:

- which Door functions call `_create_binary_packet_from_buffers()`;
- how many body components each call has;
- whether a component comes from `struct.pack`, bytes/bytearray construction, concatenation, encoding, a name, or another call;
- statically derivable component byte sizes;
- the number and argument **shapes** of `create_door_message()` calls.

The inventory deliberately does **not** print integer/string/bytes literal payload values. It does not import or execute the legacy module, does not read credentials, and performs no network or physical action.

## Stage A acceptance

- pinned legacy source SHA256 matches;
- required functions `_open_door_init` and `open_door` are present;
- structural output is deterministic;
- synthetic tests prove payload literals are redacted;
- source execution remains false;
- secrets read remains false;
- network action remains false;
- physical Door action remains false.

## Stage B — body-shape fixture

After Stage A evidence is collected from CT120, implement a synthetic body-layout model matching the discovered component order and static widths. The model must still contain no real Door payload values.

Stage B must reconcile the synthetic body through canonical `VipSession.send_frame()` and preserve the existing one-shot ambiguity semantics.

## Explicit non-goals

v0.6 does not enable real transport, does not open a CTPP channel on the network, does not send Door commands, and does not assert a physical relay effect.
