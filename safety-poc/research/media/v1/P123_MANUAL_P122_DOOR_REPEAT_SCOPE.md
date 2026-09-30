# P123 — Repeat explicit Entrance Door presses on active P122 media (offline candidate)

Status: **SOURCE CANDIDATE ONLY — NOT MERGEABLE / NOT DEPLOYED**.
Baseline: Comelit 1.7.12, `main` `8b69160d093ff300726471479415d51fd37a9e91`.

## Evidence

The first P122 Entrance Door operation was accepted on an active on-demand
camera session and user-confirmed to have physically opened the entrance.
One write was sent, on the existing media CTPP, and generic ACK was observed.
A distinct later manual press in the still-active media session was rejected
`DOOR_ALREADY_SENT` with zero additional native writes.

This confirms session-wide lockout, not the device's behavior on a **second**
properly sequenced Door message. That latter behavior still requires physical
validation after offline checks and native promotion.

## Requested behavior

- Each **explicit** user press creates a new operation with a new internal ID.
- Keep one native write maximum **per operation** and no automatic retry.
- Allow the next manual press after the preceding operation's bounded
  `P122_DOOR_SETTLE_MS=1000` completes, subject to all other readiness gates.
- Reject another request while any native Door write / settle is inflight.
- Subsequent Door message must advance the **last completed Door TX sequence**;
  it cannot reuse the earlier R27 refresh sequence or a sequence from a failed
  queue attempt.
- Continue using the existing active media CTPP. No second P2P/CTPP bootstrap.
- Entrance only. Gate stays fail-closed for on-demand media.
- Keep `UNKNOWN_OUTCOME` for post-send ambiguity and never assert physical
  effect solely from generic ACK.
- Leave listener-owned R66/CALL_TIME_SINGLE behavior out of this change.

## Implemented source candidate

1. The session-wide `P122_DOOR_GATE_DOOR_ALREADY_SENT` eligibility branch was
   removed. `DOOR_INFLIGHT` stays until the existing 1000 ms settle callback.
2. `p122_door_sent` is now historical sequence provenance, not an eligibility
   block. `p122_door_last_sent_sequence` is committed only at native TX
   completion. The next explicitly triggered P122 serializer advances that
   sequence by the pre-existing `0x00010000u` step.
3. The existing R27 refresh cancellation on a Door TX is unchanged. The native
   helper must be assessed for any longer-running media lifetime impact before
   marking repeat presses as production-validated.

## Acceptance gates before merge

- Host-compiled generated-region harness: first explicit press → 1 write,
  overlapping press → `DOOR_INFLIGHT`/0 extra writes, native settle callback →
  READY, second explicit press → one **new** write and sequence +`0x00010000`.
- Whole generated translation unit compiles.
- Frozen native/source SHA gates must be updated **only after** reproducible
  CT120 P122-profile Build A/B.
- Packaged native helper and all production pins/provenance must match.
- Full regression, static safety, HACS, and PR CI must pass.
- No merge, release, HA deploy, restart or new live Door action on a
  source-only candidate.
- A later second-manual-press physical acceptance needs its own deliberate
  user-driven test and must distinguish the two operation IDs.

## Open question

Physical effect of an intentionally repeated Door operation during a single
on-demand media session is **NOT_PROVEN**. The observed rejected second press
provides no second transmitted protocol message to assess.


## Reproducible native promotion evidence

CT120 canonical P122-profile Build A/B completed after the source candidate:

- build head: `fee0ce6b9a8b43b1de400aa25f992aa06e446e9f`
- generated source SHA256: `ec39399ade72cb4800131d5a0995e0053a3f9af22560fd40894af057994d6d47`
- Build A SHA256: `04bb610e02562fb4a301813001616308dd22dbabe5507b397a5abdc7194075b2`
- Build B SHA256: `04bb610e02562fb4a301813001616308dd22dbabe5507b397a5abdc7194075b2`
- packaged size: `311528` bytes
- reproducible binary comparison: PASS
- P122 binary marker gate: PASS
- `DOOR_ALREADY_SENT` binary marker: absent
- `DOOR_INFLIGHT` binary marker: present
- targeted P123 tests: PASS
- static safety: PASS
- compileall: PASS
- live Door/Gate actions during build/promotion: 0

The P122 active-media provenance record remains frozen. This round is recorded
separately in
`p123_manual_p122_door_repeat_production_media_build_meta.txt`.

Physical behavior of a second intentional Door press during the same active
on-demand media session remains `NOT_PROVEN` until a later user-driven live
acceptance test.
