# OPTION F PR-1a — golden fixture provenance

Frozen golden input for the PR-1a shadow replay. Files in this directory are **input
data**, not code. They are frozen by the orchestrator before the Developer run; the
Developer must not modify them (see `TASK_DEV_PR1A.md`).

Every fixture is a sanitized native-stdout line sequence (`KEY=VALUE` per line, exactly
as the helper writes to stdout after `strip()`). No tokens, no raw payloads, no peer
addresses, no media bodies.

## Source evidence

| source | sha256 |
|---|---|
| `/home/hermes/t15-live/call1-ha-follow.log` (T15 physical call #1, HA log-follow) | `e553b9791892fa9ca8725c9e0997c7c60a9aaa2dea53bae9dca56a2b483a6789` |
| `/home/hermes/t15-live/call2-ha-follow.log` (T15 physical call #2, HA log-follow) | `d357f1aa07b830978e1c3efae43ff4db4a27cb97ba0eae647da8d2bac46a0cb9` |
| `/home/hermes/comelit-t15/T15_EVIDENCE.md` | `3f3c61bc002959864fef6fc97e8158fc943568ff19034a28f4da7514725dc8e1` |
| repo `safety-poc/tests/fixtures/ring_call_init_entrance.safe.txt` (already-sanitized, committed) | `dafa83a9c28984ee191130cd4ecabe98cab7cd60b836b4eabba559e386f75df2` |
| repo `safety-poc/scripts/v4_ring_dedupe_transform.py` (native dedupe marker contract, F7) | `8c8cd1813b2652b598d3d6579833dc5a89b039f349c14c67304f1f0f3dbbe19c` |

## Per-fixture provenance

### `01_listener_ring_call1.golden.txt`
`PROVENANCE=T15_LIVE_EVIDENCE`
- `V4_RING_FRAME_SHA256=a3317f…e83bdc` is the verbatim value recorded in
  `call1-ha-follow.log` (`Comelit ring fingerprint marker; V4_RING_FRAME_SHA256=…`).
- `door=entrance`, `source=00000643` come from the same log's
  `Comelit ring event emitted: door=entrance source=00000643` line — i.e. the five-key
  `V4_RING_*` batch below is what the listener parser must have received to emit it.
- `V4_CTPP_REGISTRATION=PASS`, `V4_RING_LISTENER_READY=true` are taken from the
  already-sanitized committed fixture (same marker vocabulary).
- `R42_CALL_GENERATION=1`, `R54_CALL_ADOPTION_STARTED=true`,
  `R54_PEER_CAPABILITIES_SEEN=true`, `R58_STOP_PHASE=CLOSED` are real
  `marker=KEY value=VALUE` canary lines from `call1-ha-follow.log`.
- Line order for the ring batch follows the native print order proven in
  `v4_ring_dedupe_transform.py` (fingerprint line, then the observed batch).

### `02_listener_ring_call2.golden.txt`
`PROVENANCE=T15_LIVE_EVIDENCE`
- Same construction as fixture 01, using the **second physical call**:
  `V4_RING_FRAME_SHA256=82ae35ad…e012e5` verbatim from `call2-ha-follow.log`.
- Fixtures 01 + 02 are therefore two distinct physical calls from the same
  `(door, source)`, which is exactly the case the shadow guard must treat as
  key-identical (`(door, source)`) without ever using the frame SHA as identity.

### `03_media_owner_ring.golden.txt`
`PROVENANCE=REPO_SANITIZED_FIXTURE` — derived from the already-sanitized committed fixture
`safety-poc/tests/fixtures/ring_call_init_entrance.safe.txt` plus the media-helper
markers `P80_MEDIA_ACTIVE=true` / `P80_VIDEO_RTP_FORWARDING=PASS` (real marker names,
`media_transport.py`). No live media-owner ring capture exists in T15 evidence; this
fixture exercises the media transport reader path with the canonical five-key batch.
No frame-SHA line is included here because no media-owner SHA was captured.

### `04_retransmit_batch.golden.txt`
`PROVENANCE=IN_REPO_TOOL_CONTRACT` (`v4_ring_dedupe_transform.py:63-64`).
`V4_RING_RETRANSMIT_SUPPRESSED=true` + `V4_RING_RETRANSMIT_SHA256=…` are the native
retransmit-verdict marker pair. **The 64-hex value is a non-evidence placeholder** (all
zeros) — no retransmit frame SHA was captured in T15 and none is invented as evidence.

### `05_malformed_incomplete.golden.txt`
`PROVENANCE=MIXED`
- `V4_RING_DOOR=17` / `V4_RING_SOURCE=2`: legacy non-normalized shape taken from the
  in-repo retention evidence test (real legacy marker shape).
- `V4_RING_OBSERVED=maybe`, conflicting `V4_RING_DOOR=entrance`+`V4_RING_DOOR=gate`,
  missing `V4_RING_SOURCE=` value, a line with no `=` separator, an unknown
  `V4_RING_UNKNOWN_KEY=1`: contract-violation shapes derived from the marker contract
  (`ring_event.py`) — these are the malformed/incomplete/unknown classes required by
  the design's test specification.
- The trailing complete `gate` batch (`source=00000610`) proves the reader still
  emits after malformed input.

### `06_unrelated_native_stdout.golden.txt`
`PROVENANCE=T15_LIVE_EVIDENCE` — real `marker=KEY value=VALUE` canary lines from
`call1-ha-follow.log` (R42/R54/R58/R67/P116/POST_CALL_TRANSPORT_STATE), plus one empty
line as generic stdout noise.

### `07_two_calls_sequence.golden.txt`
`PROVENANCE=T15_LIVE_EVIDENCE` — fixture 01 + fixture 06 + fixture 02 concatenated
(two physical calls on one listener stream with interleaved unrelated stdout).

## Fixture checksums (frozen)

| fixture | bytes | sha256 |
|---|---|---|
| `01_listener_ring_call1.golden.txt` | 373 | `1263e8bd6dc4c08090bed0977fdcb90b357088ebab53f4b5dc385d95c7299746` |
| `02_listener_ring_call2.golden.txt` | 359 | `5d19b91eea4b331dd6f35bc0e5e2104d53d3ef2450dcb16bf8c00a6b954f1ae3` |
| `03_media_owner_ring.golden.txt` | 194 | `3e5f04622b9ef582b237eadf1883c321d4ec64ce92cd88b98072b59841b67f66` |
| `04_retransmit_batch.golden.txt` | 275 | `dc3c768ff96165b80a8de81613703580eef26870951d45bbd7164cb23bb3d856` |
| `05_malformed_incomplete.golden.txt` | 389 | `c39c5b1dbe6f87840c022deafe5b6a60167037d5da517ed9205954c56d58b3d3` |
| `06_unrelated_native_stdout.golden.txt` | 228 | `54366ba2cdba302012f54a64fd08fa2bd82a3ecb3e78187123280f00b97bf5a1` |
| `07_two_calls_sequence.golden.txt` | 960 | `a170175f6a7a7c28111277344879f672cc459b26cf07594d6bffb12bec78c906` |
