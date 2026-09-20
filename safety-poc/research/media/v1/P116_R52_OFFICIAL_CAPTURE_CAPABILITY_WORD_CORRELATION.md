# P116 R52 Official Capture Capability Word Correlation

Status: offline forensic/correlation round only. No production file, native
artifact, packaged binary, HA state, Comelit network path, physical call,
self-activation, Door/Gate action, ADB, debugger, ptrace, or proprietary binary
execution was touched.

```text
BASE_SHA=05ee9e0cd847f28a11fd32575f1c29fe6dbc0d74
ROUND=P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION
NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
SELF_ACTIVATION_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
CAPTURE_LITERAL_PROMOTABLE=false
CAPTURE_LITERAL_REPLAY_USED=false
```

## Evidence Inputs

Read first: `.r52-evidence/INDEX.md`, `.r52-evidence/PROVENANCE.txt`, and the
mechanical capture inventory. All six staged capture SHA-256 values were
verified independently with `sha256sum` before parsing.

| label | sanitized file label | sha256 | packets | UTC range | classification | sha256 verified |
|---|---|---|---:|---|---|---|
| P2P_RTSP | `p2p_rtsp.pcap` | `62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3` | 2490 | 2026-08-25T20:19:44.057971Z..2026-08-25T20:20:36.981721Z | RTSP_P2P | true |
| HELPER_LIVE_RUN_P78 | `p78-media.pcap` | `345554982807e04bddaae11c12ee142684539cebae11b081cdc1c24826e63586` | 33 | 2026-09-08T19:26:51.810360Z..2026-09-08T19:27:02.677144Z | HELPER_LIVE_RUN | true |
| OFFICIAL_APP_TRACE_R14 | `pcapdroid-r14-official-app-trace.pcap` | `3e2241709ea518b277814a66c8166f52d24aae712646e9ce316e75b46363d62f` | 6296 | 2026-09-12T11:19:27.143782Z..2026-09-12T11:20:52.076275Z | OUTGOING_CALL | true |
| HELPER_PREFLIGHT_R38 | `r38-preflight.pcap` | `8ed7e9bc9256886e9c94e92b8b064c78770e2148e7f5e091dd02f67a7f85ed9e` | 93 | 2026-09-19T13:24:10.066963Z..2026-09-19T13:24:57.986037Z | HELPER_PREFLIGHT | true |
| OFFICIAL_APP_PHONE_CAPTURE_R39 | `r39-phone-capture.pcap` | `5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9` | 901 | 2026-09-19T13:56:47.815957Z..2026-09-19T14:01:06.092055Z | UNKNOWN | true |
| SELF_ACTIVATION | `self_activation.pcap` | `f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a` | 3546 | 2026-08-25T21:58:39.352254Z..2026-08-25T21:59:21.715852Z | SELF_ACTIVATION | true |

All committed capture references are labels and hashes only. Raw paths,
endpoints, ports, tokens, SDP, payload bytes, and protocol addresses are not
published.

## Parser

R52 adds `entrance_p116_r52_capability_word_forensic.py` because the existing
ViP frame collectors were capture-window specific. The new parser accepts a
pcap path, supports classic pcap with raw-IP, Ethernet, and Linux SLL2 link
types, reconstructs the selected ViP PseudoTCP flow, parses CTP envelopes with
the already-proven R30 envelope model, extracts only inner opcode `0x0003`, and
emits sanitized scalar TSV rows.

The focused tests build synthetic frames in memory and assert:

- R43B body contract: `00 03 <call_type> 00 <word LE32>`, length 8;
- CLIENT_TO_DEVICE versus DEVICE_TO_CLIENT separation;
- little-endian word decode;
- fail-closed behavior on truncated and non-DATA CAPABILITIES;
- no raw-output invariant.

## CAPABILITIES Extraction

Parser run on all six staged captures:

```text
CAPTURES_RUN=6
CAPABILITIES_FRAMES_FOUND=4
OFFICIAL_LOCAL_CAPABILITIES_FRAMES_FOUND=2
```

| capture | session | direction | inner length | call type | reserved | capability word | relative time | direction relation |
|---|---|---|---:|---:|---:|---:|---:|---|
| OFFICIAL_APP_TRACE_R14 | session-1 | CLIENT_TO_DEVICE | 8 | `0x49` | `0x00` | `0x00000027` | 5.479410s | CLIENT_LOCAL |
| OFFICIAL_APP_TRACE_R14 | session-1 | DEVICE_TO_CLIENT | 8 | `0x50` | `0x07` | `0x0000001b` | 6.099491s | DEVICE_PEER_XOR_CLIENT_LOCAL |
| SELF_ACTIVATION | session-1 | CLIENT_TO_DEVICE | 8 | `0x49` | `0x00` | `0x00000027` | 6.054691s | CLIENT_LOCAL |
| SELF_ACTIVATION | session-1 | DEVICE_TO_CLIENT | 8 | `0x50` | `0x07` | `0x0000001b` | 6.472907s | DEVICE_PEER_XOR_CLIENT_LOCAL |

Required headline answers:

```text
OBSERVED_LOCAL_CAPABILITY_WORDS=0x00000027
PHYSICAL_INBOUND_LOCAL_CAPABILITY_WORD=UNKNOWN
SELF_ACTIVATION_LOCAL_CAPABILITY_WORD=0x00000027
OBSERVED_WORD_STABLE_ACROSS_SESSIONS=true
```

The physical R42 raw PCAP was not found. All six staged captures were scanned
for the R42 signature values and timing class; none matched the R42 physical
transaction. Repository reports and staged prior-analysis text artifacts were
searched for the exact local CAPABILITIES body. They preserve R42 timing,
connection/channel identities, and MEDIAREQ26 bodies, but not the local
CAPABILITIES body. Therefore:

```text
PHYSICAL_CALL_RAW_CAPTURE_FOUND=false
PHYSICAL_INBOUND_CAPABILITY_EXTRACTION=UNAVAILABLE
MISSING_PHYSICAL_ARTIFACT=raw R42 physical-call PCAP or derived exact local CAPABILITIES body
```

## Peer Comparison

For both correlated official-app sessions:

```text
LOCAL_CAPABILITY_WORD=0x00000027
PEER_CAPABILITY_WORD=0x0000001b
LOCAL_PEER_CAPABILITY_EQUAL=false
LOCAL_ONLY_BITS=0x00000024
PEER_ONLY_BITS=0x00000018
COMMON_BITS=0x00000003
```

This is useful for separation: the local word is not a reflection of the peer
CAPABILITIES word.

## Known Mask Comparison

| observed word | equals 0x07 | equals 0x27 | equals 0x0F | equals CallFsm720 expected | known bit names | unknown bits |
|---:|---|---|---|---|---|---:|
| `0x00000027` | false | true | false | true | AUDIO_DST,AUDIO_SRC,VIDEO_DST,MSTREAM | `0x00000000` |

Bit-level result:

```text
SET_BITS=AUDIO_DST,AUDIO_SRC,VIDEO_DST,MSTREAM
BIT3_VIDEO_SRC_SET=false
BIT4_OPENDOOR_SET=false
BIT5_MSTREAM_SET=true
```

The R51 bit-3 puzzle persists on the real wire: the observed official local
CAPABILITIES word does not set VIDEO_SRC bit3, while R51 showed `CallFsm+840`
bit3 is consumed by local media/video-TX gates. The real wire value therefore
does not explain those bit3 gate reads by itself.

## Stability And Semantics

```text
LOCAL_CAPABILITY_WORD_STABLE_WITHIN_CAPTURE=true
LOCAL_CAPABILITY_WORD_STABLE_ACROSS_CAPTURES=true
LOCAL_CAPABILITY_WORD_STABLE_ACROSS_CALL_TYPES=UNKNOWN
ALLOCATOR_RESIDUE_HYPOTHESIS=WEAKENED
```

The repeated small mask weakens a random allocator-residue explanation but does
not refute `CALLFSM_840_POSSIBLY_UNINITIALIZED=true`. Stability is not
provenance.

Honesty caveats:

- Both observed local CAPABILITIES words come from client-initiated call
  transactions. The available captures contain no device-initiated inbound
  official-app session, so `LOCAL_CAPABILITY_WORD_STABLE_ACROSS_CALL_TYPES`
  stays `UNKNOWN` and the inbound case remains unobserved on the wire.
- The two observations come from the same official app/device family on
  different days. They weaken but cannot refute allocator residue, and they are
  not two fully independent device populations.
- `P2P_RTSP`, `R39_PHONE_CAPTURE`, `P78_MEDIA` and `R38_PREFLIGHT` yielded no
  CTP CAPABILITIES frame at all, so no peer/local comparison exists outside the
  two client-initiated sessions.

What the value can say about `CallFsm+840`:

- It is the full local CAPABILITIES word serialized by `csp_send_capab_report`
  in these official-app sessions.
- Its observed value matches the already-proven Java `vipUnitCapab` formula
  when MSTREAM is enabled.
- It does not match the peer word and does not set VIDEO_SRC or OPENDOOR.
- It still does not prove that `CallFsm+840` is derived from `VipUnitImpl+20`
  or from the Java formula. R51's dataflow result remains: the proven Java
  capability reaches `CallFsm+720`, while `CallFsm+840` source remains
  unresolved.

## Static Follow-Up

One bounded pass over the staged native and Java evidence found known mask
context only:

```text
OBSERVED_WORD_STATIC_MATCH_FOUND=true
OBSERVED_WORD_STATIC_MATCHES=known Java formula UnitCapability AUDIO_DST|AUDIO_SRC|VIDEO_DST|(MSTREAM when enabled) equals 0x27; staged dex UnitCapability values define 0x01,0x02,0x04,0x08,0x10,0x20; native listings contain broad incidental 0x07/0x20/0x27 matches but no new CallFsm+840 writer
STATIC_MATCH_EXPLAINS_CALLFSM840=false
NEW_CALLFSM840_WRITER_FOUND=false
```

No new native writer/source for `CallFsm+840` was proven. No absolute
addresses or raw disassembly are published here.

## Verification

Canonical repository-only CI command from `.github/workflows/offline-safety.yml`:

```text
cd safety-poc
PYTHONPATH=<repo>/safety-poc/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Authoritative parent gate results:

```text
PARENT_RUN_1 with the R52 files present:
Ran 2021 tests in 35.489s
OK (skipped=1)

PARENT_RUN_2 baseline with the R52 test file temporarily moved aside:
Ran 2015 tests in 35.152s
OK (skipped=1)

DELTA=+6 tests
NEW_FAILURES_VS_BASELINE=none
```

The earlier PYTHONPATH-less discovery command was not the repository's
canonical CI command:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
Ran 2019 tests
FAILED (errors=1)
ERROR=test_control_plane_model ModuleNotFoundError: No module named 'comelit_safety_poc'
```

Cause: the package lives in `safety-poc/src`; without `PYTHONPATH` it is
unimportable. This is a command-line artifact, not a round regression, and not
a pre-existing branch failure under CI.

Parent also ran
`tests.test_p116_r29i_preopen_idle_and_sink_ownership` under the canonical
environment three consecutive times:

```text
Ran 10 tests -> OK, rc=0
Ran 10 tests -> OK, rc=0
Ran 10 tests -> OK, rc=0
```

Therefore the two "UDP sink subprocess returned non-zero" errors recorded in
the earlier single executor run are recorded as a one-off load/timing-flaky
observation, not as a stable suite failure.

Executor reruns in this corrective invocation:

```text
CANONICAL_CI_COMMAND_RUN_1=Ran 2021 tests in 39.388s; FAILED (errors=2, skipped=5)
CANONICAL_CI_COMMAND_RUN_2=Ran 2021 tests in 39.353s; FAILED (errors=2, skipped=5)
LOCAL_OBSERVATION=test_p116_r29i_preopen_idle_and_sink_ownership UDP sink subprocess returned non-zero
FOCUSED_R52=Ran 6 tests in 0.001s; OK
R43B_R45_R46_REGRESSION=Ran 42 tests in 0.141s; OK
STATIC_SAFETY_CHECK=PASS
GIT_DIFF_CHECK=clean
```

Canonical full-suite pass/fail status below uses the authoritative parent gate
run above: with R52 files present, the canonical CI command ran 2021 tests and
passed; at baseline without the R52 test file, it ran 2015 tests and passed;
the round adds 6 tests and introduces no new failure.

```text
=== P116 R52 OFFICIAL CAPTURE CAPABILITY CORRELATION ===

BASE_SHA=05ee9e0cd847f28a11fd32575f1c29fe6dbc0d74

CODEX_CLI_USED=true
CODEX_ITERATIONS=2

CAPTURE_COUNT=6

PHYSICAL_CALL_RAW_CAPTURE_FOUND=false
PHYSICAL_CALL_TRANSACTION_CORRELATED=false
PHYSICAL_LOCAL_CAPABILITIES_FOUND=false
PHYSICAL_LOCAL_CAPABILITIES_CALL_TYPE=UNKNOWN
PHYSICAL_LOCAL_CAPABILITIES_WORD=UNKNOWN
PHYSICAL_LOCAL_CAPABILITIES_RELATIVE_TO_INVITE_MS=UNKNOWN
PHYSICAL_INBOUND_CAPABILITY_EXTRACTION=UNAVAILABLE

SELF_ACTIVATION_CAPTURE_FOUND=true
SELF_ACTIVATION_CAPABILITIES_COUNT=1
SELF_ACTIVATION_LOCAL_CAPABILITY_WORDS=0x00000027
SELF_ACTIVATION_LOCAL_CALL_TYPES=0x49

OTHER_CORRELATED_SESSIONS=1

OBSERVED_LOCAL_CAPABILITY_WORDS=0x00000027

LOCAL_CAPABILITY_WORD_STABLE_WITHIN_CAPTURE=true
LOCAL_CAPABILITY_WORD_STABLE_ACROSS_CAPTURES=true
LOCAL_CAPABILITY_WORD_STABLE_ACROSS_CALL_TYPES=UNKNOWN

PHYSICAL_LOCAL_PEER_CAPABILITY_EQUAL=UNKNOWN
PHYSICAL_LOCAL_ONLY_BITS=UNKNOWN
PHYSICAL_PEER_ONLY_BITS=UNKNOWN
PHYSICAL_COMMON_BITS=UNKNOWN

PHYSICAL_BIT3_VIDEO_SRC_SET=UNKNOWN
PHYSICAL_BIT4_OPENDOOR_SET=UNKNOWN
PHYSICAL_BIT5_MSTREAM_SET=UNKNOWN

OBSERVED_WORD_EQUALS_0X07=false
OBSERVED_WORD_EQUALS_0X27=true
OBSERVED_WORD_EQUALS_0X0F=false

ALLOCATOR_RESIDUE_HYPOTHESIS=WEAKENED

OBSERVED_WORD_STATIC_MATCH_FOUND=true
OBSERVED_WORD_STATIC_MATCHES=known_UnitCapability_0x07_or_0x20_formula_matches_0x27_no_CallFsm840_writer
STATIC_MATCH_EXPLAINS_CALLFSM840=false

CALLFSM_840_SEMANTIC_CLASS=LOCAL_CAPABILITY_STATE_WORD_ON_WIRE_AND_MEDIA_GATES
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN
CAPABILITY_WORD_NATIVE_FORMULA=UNKNOWN

CAPTURE_LITERAL_PROMOTABLE=false
CAPTURE_LITERAL_REPLAY_USED=false

NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
SELF_ACTIVATION_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
HA_DEPLOY_ACTIONS=0
HA_RESTART_ACTIONS=0
PRODUCTION_FILES_CHANGED=0

FOCUSED_TESTS=PASS
FULL_OFFLINE_SUITE=PASS
STATIC_SAFETY=PASS
VALIDATE_HACS=NOT_RUN_BY_EXECUTOR
OFFLINE_SAFETY_CI=NOT_RUN_BY_EXECUTOR

FINAL_BRANCH_HEAD=<filled by orchestrator>
READY_FOR_PRODUCTION_CORRECTIVE=false
MISSING_REQUIRED_EVIDENCE=raw_R42_physical_call_pcap_or_derived_exact_local_CAPABILITIES_body;proven_CallFsm840_writer_or_source

GHIDRA_TARGETED_DECOMPILE_RECOMMENDED=true
WATCHPOINT_STILL_REQUIRED=true

NEXT_REQUIRED_STEP=targeted_decompile_or_watchpoint_for_CallFsm840_source_before_any_production_corrective

=== END P116 R52 OFFICIAL CAPTURE CAPABILITY CORRELATION ===
```
