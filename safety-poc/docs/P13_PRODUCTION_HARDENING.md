# P13 production hardening

## Status

The physical functional proof is complete.

The successful observed operation is preserved separately from protocol
classification:

- protocol state: `UNKNOWN_OUTCOME`;
- Door-specific ACK: unproven;
- operator physical observation: `OPENED`;
- observed physical acceptance: `PASS`;
- no retry or resend occurred.

The one-off Hermes observed-acceptance gate is terminally consumed and is not a
production control surface.

## G1A boundary

G1A creates an immutable, hash-bound P13 release under:

`/opt/comelit-door-safety-poc/p13/releases/`

The release contains:

- the exact Git `safety-poc` tree used to build the release;
- copies of the physically proven holder, wrapper, payload and runtime identity;
- `RELEASE.env`;
- `RELEASE_CONTENT.sha256`.

The release records, but does not alter, the exact runtime identities that were
used for the successful physical proof.

`current` is an atomic symlink to the selected release. Starting with a second
release, `previous` records the prior selected release.

## Runtime authority after G1A

The installed P13 Hermes runtime dispatcher no longer depends on
`/root/comelit-git`.

It exposes:

- `readiness`: immutable-release and runtime-identity verification only;
- historical `observed-open`: terminally retired and denied with exit 126.

The existing one-time acceptance gate is never reset or regenerated.

No reusable Door-open command is introduced by P13 G1A.

## Why reusable opening is deferred

A reusable operator/Home Assistant service changes authorization and lifecycle
semantics. That work belongs to P14.

P13 retains the proven safety semantics that P14 must consume:

- caller operation identity must be one-shot;
- audit and durable journal are authoritative;
- automatic retry is forbidden;
- uncertainty after the irreversible send boundary remains
  `UNKNOWN_OUTCOME`;
- protocol evidence never asserts physical relay movement.

## Rollback model

A failed G1A install restores:

- the previously installed P13 dispatcher;
- the previous `current` release pointer;
- removes a newly-created failed release.

Future successful releases preserve the prior selected immutable release through
the `previous` symlink.

Rollback never performs a Comelit session or Door action.
