# MSL-V1 Variant B: Idle Listener Media

`entrance_msl_v1_idle_listener_media_transform.py` is an offline-only research
candidate. It composes the R58 listener chain and adds an idle-media overlay
inside the already READY persistent listener process.

## Safety Boundaries

- No helper-side media session is created.
- No cloud P2P negotiation, ICE bootstrap, PseudoTCP open, UAUT, or CTPP
  registration path is added by the overlay.
- Start is accepted only when `v4_listener_ready`, `pseudotcp_open`,
  `v4_registered`, and `v4_ctpp_channel_id != 0` are true.
- Control files are under `/run/comelit-p2p/`:
  - `msl-b-start-idle-media`
  - `msl-b-stop-idle-media`
- Duplicate start while active is rejected and counted.
- Ring/call collision is rejected busy/fail-closed. The candidate does not
  start a second upstream session and does not retry.
- Door and Gate paths are not called by the overlay.

## Media Lifecycle

The accepted control file triggers listener-local RTPC media channel allocation,
then a serialized `0x001A` idle self-activation frame on the existing CTPP
channel. The single P12 TX slot is respected by chaining work from
`p12_tx_completed()`:

1. RTPC media channel open.
2. TX completion.
3. `0x001A` self-activation.
4. TX completion.
5. P80 forwarding armed.
6. Stop control.
7. RTPC media channel close.
8. P80 forwarding disarmed and tunnel preserved.

No raw SDP, tokens, RTP bytes, peer identifiers, or payload dumps are emitted.

## Provenance Gate Decision

`P78_GATE_DECISION=substituted`.

The original P78 launcher gate pins a reviewed `main` commit and a reviewed live
run flag. Variant B is intentionally implemented on a research branch, so that
gate would fail before Hermes could run the branch candidate. The new runner
uses an equal-strength branch gate:

- CT120 clone `HEAD` must equal `MSL_B_EXPECTED_COMMIT_SHA`.
- Worktree must be clean.
- Frozen base source hash must match.
- Generated source hash must equal `MSL_B_EXPECTED_GENERATED_SOURCE_SHA`.
- Runner and transform blobs are copied from the pinned commit and compared
  with the worktree files.
- Base wrapper SHA is pinned before the live boundary.
- Ledger file must be present, numeric, and `< 15`.

## Live Proof Markers

Hermes should compare Variant B against baseline using:

- `MSL_B_T00_IDLE_MEDIA_REQUEST_ACCEPTED_MONO_MS`
- `MSL_B_T12_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS`
- `MSL_B_T13_INITIAL_001A_SENT_MONO_MS`
- `MSL_B_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE_MONO_MS`
- `MSL_B_T15_MEDIA_ACTIVE_MONO_MS`
- `MSL_B_T17_FIRST_VIDEO_RTP_MONO_MS`
- `MSL_B_T18_FIRST_SPS_PPS_IDR_MONO_MS`
- `MSL_B_START_TO_FIRST_VIDEO_RTP_MS`
- `MSL_B_START_TO_DECODABLE_VIDEO_MS`

Session reuse is proven with:

- `MSL_B_CLOUD_NEGOTIATION_COUNT=0`
- `MSL_B_ICE_BOOTSTRAP_COUNT=0`
- `MSL_B_PSEUDOTCP_OPEN_COUNT=0`
- `MSL_B_CTPP_REGISTRATION_COUNT=0`
- `MSL_B_MEDIA_SESSION_COUNT=1`
- `MSL_B_SECOND_MEDIA_SESSION=false`
- `MSL_B_LISTENER_PROCESS_PID` unchanged
- `MSL_B_RECONNECT_COUNT_DELTA=0`
- `MSL_B_LISTENER_READY_BEFORE=true`
- `MSL_B_LISTENER_READY_AFTER=true`
- `MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE=true`
- `MSL_B_MEDIA_CHANNEL_CLOSED=true`
- `MSL_B_TUNNEL_PRESERVED=true`

Baseline stages that do not exist in Variant B are emitted as `N/A` with a
reason by the runner, because Variant B starts from an existing READY listener.
