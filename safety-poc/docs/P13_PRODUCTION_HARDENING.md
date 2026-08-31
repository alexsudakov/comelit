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

## G1B production physical validation — completed and retired

G1B completed a second, separately approved physical validation of the
immutable production deployment.

The validation used a dedicated single-use authority and did not reuse or
reset the historical observed-acceptance gate.

The one live G1B operation was:

- operation ID: `p13-g1b-80de7068-72e5-40db-9e4f-47e1a42d2351`;
- immutable release:
  `p13-516c5a54f5f8-50c0a916f73e-b6a10c68773a`;
- source HEAD: `5a416a7e1d49c35947579b298f2028fe30853592`;
- source TREE: `516c5a54f5f8646eaed7a1b6599718c1cc69640b`;
- attempt number: `1`;
- transition:
  `PREPARED -> SEND_ARMED -> SENT -> UNKNOWN_OUTCOME`;
- protocol state: `UNKNOWN_OUTCOME`;
- Door-specific ACK: `UNPROVEN`;
- independent operator physical observation: `OPENED`;
- observed physical acceptance: `PASS`;
- automatic retry: forbidden;
- resend: forbidden.

The physical observation does not promote the protocol result to `ACKED` and
does not create a protocol assertion that the relay moved.

The G1B gate was durably consumed before the live-capable handoff. After the
single invocation, the temporary Hermes ForceCommand authority, sudo authority,
and installed G1B gate binary were retired.

The historical observed-open gate remains consumed as well.

Frozen public-safe evidence:

- branch: `evidence/p13-g1b-opened-20260831T203116Z`;
- commit: `4ce5dedebe9df7e681e38af84f59ae92eafe8c28`;
- tree: `f089fd459af8a0ee3365b86b7cee99e31d8e1e9c`;
- path:
  `safety-poc/evidence/p13-g1b-production-opened-20260831T203116Z.txt`.

The temporary G1B live-validation source is intentionally not retained in the
final P13 production source tree or final immutable production release.

P13 production runtime remains readiness-only. Reusable Door actuation belongs
to P14 and is not introduced by P13.
