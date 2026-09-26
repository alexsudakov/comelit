# MSL-V2 Child A: Listener Session Bootstrap Provider

This document covers the piece of harness added in this child:
`safety-poc/research/media/v1/ct120_run_msl_v1_variant_b_live.sh`'s embedded
`msl_b_bootstrap_provider.py` and the bootstrap-only run mode built around it.
It does not redescribe the Variant B idle-media overlay itself, which is
already documented in `MSL_V1_VARIANT_B_DESIGN.md`.

## 1. Problem this closes

`MSL_V1_MEDIA_STARTUP_LATENCY_RESULT.md` section 4.3 recorded the blocker: the
research listener built from `entrance_msl_v1_idle_listener_media_transform.py`
could reach ICE gathering but never `READY`, because nothing on CT120 played
the part production's `custom_components/comelit/runtime.py` plays for the
real listener — reading the local offer, transforming it, negotiating cloud
P2P exactly once, and handing the remote SDP back. That is a harness
observability gap, not a new protocol: the listener process already expects
exactly this sequence (`offer.sdp` present, then `remote.sdp` appears once).
The bootstrap provider is that missing piece, reproduced for the research
listener instead of the production one.

## 2. What the provider actually is

A short-lived Python process (materialized by the runner into
`$RUN_ROOT/msl_b_bootstrap_provider.py`, run once via
`run_bootstrap_provider()`), invoked with `python3` directly on CT120 — not
inside Home Assistant's own process or venv. It:

1. Waits for `/run/comelit-p2p/offer.sdp` to appear (written by the research
   listener the runner just started).
2. Transforms it with the **real** `custom_components/comelit/sdp.py`
   (`transform_offer`).
3. Obtains an OAuth access token via the **real**
   `custom_components/comelit/oauth.py` (`ComelitOAuthManager.async_get_access_token`),
   the same class production uses, instantiated in-process with a session
   backed by HA's persisted config entry data. The token is used immediately,
   in memory, and is never written to a file, printed, logged, or embedded in
   any marker.
4. Negotiates cloud P2P **exactly once** with the **real**
   `custom_components/comelit/cloud.py` (`async_negotiate_p2p`,
   `_validate_remote_sdp`).
5. Writes the remote SDP to `/run/comelit-p2p/remote.sdp` using the same
   atomic-write contract as `runtime._write_remote` (temp file, `0600`,
   `os.replace`).

Steps 2-4 exercise the actual production algorithms end to end — this is the
"reuse, don't reimplement" requirement, and it is checked directly (see
`tests/test_msl_v2_listener_bootstrap_provider.py::test_provider_reuses_production_helpers`
and `::test_provider_loads_real_files_not_stub_replicas`, which fail if the
provider's calls into `sdp`/`cloud`/`oauth` are replaced with local stand-ins).

## 3. Why the modules are loaded by file path instead of `import custom_components.comelit`

`cloud.py` and `oauth.py` are Home Assistant integration files: they assume
`aiohttp` and `homeassistant.*` are importable, and importing
`custom_components.comelit` at all executes `custom_components/comelit/__init__.py`,
which imports `voluptuous`. None of `aiohttp`, `voluptuous`, or `homeassistant`
are guaranteed to be on the bare `python3` that runs this provider (they are
not present in this dev sandbox, and the provider is launched as a plain
process, not as part of HA's supervisor venv). Importing the package normally
crashes before any of the fail-closed logic in `_run()` has a chance to run,
which is exactly the failure the earlier WIP state had: `voluptuous`/`aiohttp`
`ModuleNotFoundError`s aborted the process with no markers at all.

The provider now:

- prefers the real `aiohttp` / `homeassistant.config_entries` /
  `homeassistant.core` if they are importable, and only substitutes a minimal
  stub (`ClientSession`, `ConfigEntry`, `HomeAssistant` as bare objects) when
  they are not — the same pattern already used elsewhere in this repo's
  offline tests for the same integration files
  (`tests/test_p116_observability_success_path.py::_install_stub_modules`);
- registers `custom_components` / `custom_components.comelit` as bare package
  stubs (`__path__` pointed at the real directory, `__init__.py` never
  executed) so that `const.py`, `sdp.py`, `cloud.py`, and `oauth.py` can be
  loaded under their real dotted names via
  `importlib.util.spec_from_file_location`;
- loads `const.py` first, so `oauth.py`'s `from .const import (...)` resolves
  through `sys.modules` without needing the package `__init__.py`.

`runtime.py` itself is not imported wholesale: it transitively pulls in
`call_state`, `door_outcome`, `media_diagnostics`, `ring_event`, and
`ring_media`, none of which the bootstrap needs, and instantiating that graph
outside a real `HomeAssistant` instance is unnecessary risk for no protocol
value. Instead the provider mirrors `runtime.py`'s persistence contract
directly (`_RUN_DIR`, `_OFFER_FILE`, `_REMOTE_FILE`, the same atomic
temp-file-then-`os.replace` `_write_remote` pattern) in
`_runtime_write_remote_shim`. The algorithmic reuse claim is about
`sdp.transform_offer`, `cloud.async_negotiate_p2p`, and
`oauth.ComelitOAuthManager` — those are loaded and executed for real.

## 4. Bootstrap-only mode vs. normal mode

`MSL_B_BOOTSTRAP_ONLY=YES` runs the same build + bootstrap sequence as a full
attempt, but:

- asserts `$START_FILE` (the idle-media start control) does not exist before
  proceeding, and never creates it;
- tears the research listener down and restores the HA listener immediately
  after `MSL_B_RESEARCH_LISTENER_READY=true` is observed;
- never touches the media UDP sinks or `MEDIA_OBSERVATION_SECONDS`.

This is gated by its own ledger, `MSL_B_BOOTSTRAP_LEDGER` (cap `2`,
independent of `MSL_B_ATTEMPT_LEDGER`, cap `15`), so a bootstrap-only check can
never consume budget from the media-attempt ledger and vice versa
(`ledger_value_or_fail` is the single fail-closed implementation shared by
both — malformed or non-numeric contents, or a value at/over the cap, refuses
before any live interaction). `MSL_B_BOOTSTRAP_ONLY=YES` combined with
`MSL_B_DRY_RUN=YES` or `MSL_B_SELFTEST=YES` is a mode conflict and refused
before the live boundary (`MSL_B_MODE_CONFLICT=true`).

## 5. `MSL_B_OLD_5S_INTERVAL` must be derived, not asserted

The historical result (`MSL_V1_MEDIA_STARTUP_LATENCY_RESULT.md` section 2) is
that in the cold-start baseline, `T11` (CTPP registration ready) to `T12`
(RTPC media-open control ready) took `5088`/`5100` ms — 55% of the whole
start-to-video budget — inside the **separately started native media
helper**. Variant B changes *where* the equivalent step happens: `T11`'s
counterpart (CTPP registration) occurs once, during listener bootstrap, before
any given idle-media request; the per-request work only re-enters at `B01`
(RTPC media-open sequence started) → `B02` (RTPC media-open control ready).
There is structurally no "cold CTPP-to-media-open" wait left on the per-request
path if — and only if — that is what a real run actually shows.

`msl_b_derive_old_5s_interval()` (in the runner, right before
`print_final_block`) computes the verdict from the session log every time,
using two pieces of runtime evidence, never a fixed literal:

- `delta = B02_MONO_MS - B01_MONO_MS` (the measured analogue of the old
  interval, on the same monotonic clock as everything else in this harness);
- `MSL_B_CTPP_REGISTRATION_COUNT` printed by the listener after `READY` (must
  be `0` — i.e., this media request triggered no fresh CTPP registration).

| Condition | Verdict |
| --- | --- |
| `B01`/`B02` markers absent (bootstrap-only run, or media request never issued) | `N/A` |
| `CTPP_REGISTRATION_COUNT == 0` and `delta < 1000` ms | `ELIMINATED` |
| `delta >= 4000` ms (reproduces the baseline's ~5.1 s magnitude) | `STILL_PRESENT` |
| otherwise | `TRANSFORMED` (partial reduction, not full elimination) |

`STILL_PRESENT`/`TRANSFORMED` also emit
`MSL_B_OLD_5S_INTERVAL_LOCALIZATION=NOT_LOCALIZED` — this child did not find a
5-second constant/timer inside the frozen base C source
(`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`, which
has no `mediareq`/RTPC media-open code at all — that logic is layered on by
the `entrance_p116_r*` transform chain, not the frozen base) or inside the
transform chain's added state machine (`msl_b_queue_idle_channel_open` →
`msl_b_queue_idle_self_activation` is pure TX-completion chaining with no
sleep, timer, or poll interval of its own). If a real CT120 run reports
anything other than `ELIMINATED`, localizing the actual wait is unfinished
work for a follow-up child, not a claim this child makes.

`tests/test_msl_v2_listener_bootstrap_provider.py::MslV2Old5sIntervalDerivationTests`
extracts this function verbatim from the runner and executes it against
synthetic session logs to prove all four branches, that a non-zero CTPP
registration count blocks the `ELIMINATED` verdict even when the delta is
small, and that the runner never echoes a verdict as an unconditional literal
outside the derivation function.

## 6. Fail-closed inventory (offline-provable)

| Scenario | Provider behavior | Cloud request count |
| --- | --- | --- |
| missing offer | `BootstrapError("offer_missing")`, no retry | 0 |
| malformed offer | `sdp.transform_offer` raises, caught | 0 |
| transform failure (forced) | `sdp.ComelitSdpError` propagated | 0 |
| cloud failure | `cloud.ComelitCloudError` propagated after exactly one request | 1 |
| malformed remote SDP | `cloud._validate_remote_sdp` raises | 1 |
| timeout waiting for offer | `BootstrapError("offer_timeout")` | 0 |

Every path above prints `MSL_B_BOOTSTRAP_FAIL_CLOSED=true reason=<ExceptionType>`
and returns a non-zero exit code; none of them retry. The runner treats a
non-zero provider exit, a cloud request count other than `1`, or a missing
`MSL_B_BOOTSTRAP_REMOTE_SDP_WRITTEN=true` marker as a hard failure
(`run_bootstrap_provider`), which aborts before the research listener is ever
handed the media-attempt ledger.
