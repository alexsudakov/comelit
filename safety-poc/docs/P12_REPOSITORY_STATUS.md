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

## Intentionally not implemented yet

- no real network backend;
- no real session connection;
- no credential read;
- no active network probe;
- no actuator API;
- no Door payload builder;
- no live-test approval;
- no Home Assistant wiring to a real transport.

## Next gate

Run `scripts/collect_p12_readonly_evidence.sh` on CT120 from the exact P12 feature HEAD.

That collector is source/runtime metadata only. It does not execute the research client and does not open a network connection.

After reviewing that evidence, the repository may proceed to P12-C: a separately reviewed real-session backend/probe whose public application surface is restricted to:

`CONNECT -> AUTHENTICATE -> LOAD_CONFIGURATION -> DISCOVER_TARGETS -> CLOSE`.

Even after a successful P12 real-session proof, `LIVE_TEST_READY=false` remains required until P13 is separately satisfied.
