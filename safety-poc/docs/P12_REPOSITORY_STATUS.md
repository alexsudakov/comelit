# P12 repository-only status

Base canonical main: `f01d8c610daf6fe8d8fc9c02200726f684f39145`.

Immutable v0.6 deployment on CT120 is complete and remains the current runtime while P12 is developed.

## Completed in repository only

- three-level readiness model: repository / read-only real transport / live actuation;
- fixed five-step read-only application plan;
- fail-closed capability contract forbidding actuator commands, credential export, automatic retry and physical-effect assertions;
- read-only session evidence model;
- public-safe AST inventory for legacy connection/auth/config/discovery and canonical session interfaces;
- selective timeout-shape extraction without endpoint or credential literals;
- public-safe P12 CT120 evidence collector with automatic evidence branch/commit/push;
- readiness CLI output for `READONLY_TRANSPORT_READY`;
- tests for staged readiness, fixed plan, evidence safety and qualified source selection;
- documentation and acceptance gates.

P12 source evidence now confirms that direct TCP is not the correct primary integration path. The required transport chain is modeled as:

`cloud signaling -> same-agent ICE -> PseudoTCP -> ViP -> UAUT -> UCFG -> clean teardown`.

The repository therefore contains a separate P12 P2P contract with the following hard boundaries:

- direct TCP cannot become the primary path;
- media activation is outside the transport-readiness probe;
- actuator commands are forbidden;
- automatic retry is forbidden;
- credential export and physical-effect assertions are forbidden;
- successful UAUT open alone is insufficient; read-only proof requires authentication, UCFG observation and clean teardown.

A public-safe holder forensic collector is also implemented. It inventories the current P2P holder source/binary/wrapper and historical backups by hashes and marker-presence only. It does not emit source lines, binary strings, wrapper contents, process arguments, credentials or endpoint values and does not execute the holder or wrapper.

## Current runtime fact

The immutable v0.6 release remains deployed with actuation transport disabled. P12 development does not modify that runtime.

## Intentionally not implemented yet

- no newly introduced real network backend in the canonical repository;
- no new credential-bearing session probe;
- no actuator API;
- no Door payload builder;
- no live-test approval;
- no Home Assistant wiring to a real transport.

The existing CT120 research P2P holder is treated as historical/runtime evidence, not as trusted canonical source until forensic identity is established.

## Next gate

Run `scripts/collect_p12_p2p_forensic.sh` on CT120 from the exact P12 feature HEAD.

This is a no-network forensic gate. It determines:

- current holder source/binary/wrapper hashes and metadata;
- whether the source and binary contain the previously proven P2P/ICE/PseudoTCP/ECHO/UAUT-open marker families;
- whether incomplete UAUT-auth/UCFG work is already present;
- whether any CTPP/Door actuator symbols have entered the holder path;
- whether a historical UAUT-open-only source backup candidate still exists;
- whether a holder process is already active.

Only after this evidence is reviewed may the repository prepare the controlled P12 read-only network probe.

The controlled probe target remains:

`cloud signaling -> ICE -> PseudoTCP -> ECHO ACK -> UAUT OPEN -> UAUT access=200 -> UCFG read -> clean close`.

Even after a successful P12 real-session proof, `LIVE_TEST_READY=false` remains required until P13 is separately satisfied.
