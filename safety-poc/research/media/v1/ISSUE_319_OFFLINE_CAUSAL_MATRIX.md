# Issue #319 — offline causal matrix and production-emit qualification

Status: `P0_FUNCTIONAL_ACCEPTANCE=BLOCKED_NOT_FIXED`.

ROUND 2 сохраняет этот verdict и отдельно фиксирует
`P0-A=NOT_FIXED/NOT_PROVEN`, `P0-B=NOT_FIXED/NOT_PROVEN`; трехстороннее
сравнение и точный недостающий invariant находятся в
`ISSUE_319_ROUND2_ARCHITECT_ANALYSIS.md`.

Scope is offline only. No listener control, protocol write, camera open, physical
Ring, Door/Gate action, deploy, restart, or firmware action was performed.

## Causal matrix

| Observation / boundary | Persistent listener owns upstream | On-demand media owns upstream | Offline conclusion |
|---|---|---|---|
| `CALL_INIT` | Parsed by `ComelitRingRuntime`; current production path emits one `comelit_ring`; native exact-frame retransmit is suppressed | Parsed by the native media helper and consumed only by `RingShadowController` / bounded probe diagnostics | The missing Ring while media owns the connection is causal: the persistent listener is intentionally stopped and media has no production emit route |
| Listener ownership | READY listener may dispatch Ring and listener-scoped actions | `media_paused=true`; listener restart is forbidden until media teardown is confirmed | At most one upstream owner is preserved |
| `0x001A` refresh timeout | Not part of listener Ring dispatch | Refresh may keep/lose the media transaction; native exit is observed by the manager watchdog | Refresh does not prove a physical-call boundary or call identity |
| Native exit / teardown | Supervisor reconnects the passive listener | Manager observes inactive transport, performs bounded stop, then resumes listener; uncertain teardown fails closed without concurrent restart | Eventual recovery exists after confirmed teardown; uncertainty cannot create two upstream sessions |
| Retransmission | Native exact-frame duplicate is suppressed | Shadow classifies same-owner replay/retransmit without production effect | A retransmit cannot authorize another `comelit_ring` |
| Owner handoff | Listener generation is process/lifecycle context | Media generation and handoff epoch are process/lifecycle context | Neither value is an immutable per-call identity; handoff replay remains unresolved/suppressed |
| 120s call-state boundary | Real watchdog changes call state to error | It cannot distinguish a new physical call from a replay after owner handoff | Boundary is now recorded in shadow diagnostics as `HIGH_3_watchdog_expiry_unresolved`; it never enables emit |
| `body_32_35`, peer connection, full-frame SHA | Observable only as bounded/redacted probe evidence | Same | `body_32_35` remains `UNKNOWN`, not live-verified; peer connection and SHA are not proven logical call identities |

## Identity decision

`INDEPENDENT_NATIVE_CALL_IDENTITY_PROVEN=false`.

No repository evidence independently proves that `body_32_35`, peer connection,
the complete frame digest, owner generation, handoff epoch, or any composition of
them is immutable and unique for exactly one physical call across listener/media
ownership and retransmission. Promoting any candidate would therefore be
speculative.

## Safe implementation boundary

`PRODUCTION_EMIT_GATE_PROVEN=false` and
`PRODUCTION_EMIT_IMPLEMENTATION=false`.

The production media-owner route remains disabled. The implemented change is
diagnostic/proof apparatus only:

1. the actual 120-second call-state watchdog now marks the config-entry shadow
   model before changing call state;
2. the read-only snapshot exposes the static fail-closed qualification facts;
3. offline tests prove media-owner `CALL_INIT`, the 120-second boundary, and the
   opaque identity candidate cannot create a production effect.

A functional fix requires new, independently validated physical evidence that
defines a stable per-call native identity (including retransmission and
listener↔media handoff behavior). Until then, emitting from media ownership could
duplicate `comelit_ring` for the same physical call, while suppressing by process
generation could miss a new call. Neither risk is accepted offline.
