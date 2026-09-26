# MSL-V5A — forensic correction: the sink datagrams are not the research candidate's, and the ICE stall stands

TASK_ID=`COMELIT-MSL-V5A-RTP-AND-STAGE-ATTRIBUTION`
CLI_INVOCATIONS=0 / LIVE_RUNS=0
V5 result document is NOT rewritten; this document corrects and extends it.

## 1. Canonical V5 interpretation

```text
V5_SETTLE_HYPOTHESIS=NOT_TESTED
V5_SETTLE_1000_RESULT=NOT_TESTED
SETTLE_1000_FAIL=false
SETTLE_TOO_SHORT=true            NOT derived and explicitly refused
V5_BLOCKER_CLASS=PRE_SETTLE_SETUP_OR_OBSERVABILITY
V5_REAL_LIVE_ATTEMPTS_USED=2/5   REMAINING=3 (not spent; no new live run authorised)
```

Neither v5-04 nor v5-05 reached `MSL_T08_ICE_CONNECTED`, `MSL_T09_PSEUDOTCP_OPEN`, `MSL_T10_VIP_UAUT_READY`,
`MSL_T11_CTPP_REGISTRATION_READY`, `V5_SETTLE_START_US` or `V5_SIGNALING_START_US`, so the settle value was
never exercised.

## 2. Correction to the V5 wording

The V5 document recorded "RTP reaching the helper's RTP ports" as an observation and refused to call it a pass.
That wording is now retired as well: those datagrams must not be described as panel-side RTP at all. The
correct terms are

```text
LOCAL_RTP_SINK_DATAGRAMS_OBSERVED=true
FRESH_LOCAL_UDP_TO_VIDEO_SINK=true   (4123 / 3797 datagrams)
FRESH_LOCAL_UDP_TO_AUDIO_SINK=true   (3957 / 3926 datagrams)
PANEL_SIDE_RTP_PROVEN=false          (forbidden wording; nothing supports it)
```

Because the sinks bind `127.0.0.1:17899` and `127.0.0.1:17808`, the datagrams necessarily came from a
CT120-local process. The forensic result below shows that this process was **not** the research candidate.

## 3. PHASE B — markers, redirection, log collection

Verified against the exact built binaries of both runs (`sha256 208e0533a472421298ebfb91dcab7751c8980428284d6182e091940ef67d6890`,
identical for v5-04 and v5-05, built from the settle-1000 instrumented generated source `65e51666…`):

```text
EXACT_V5_CANDIDATE_RAN=true
MARKERS_PRESENT_IN_BINARY=true
  MSL_T08_ICE_CONNECTED_MONO_MS, V5_CTPP_READY_US, V5_SETTLE_START_US, V5_SIGNALING_START_US,
  V5_FIRST_VIDEO_RTP_US, V5_0028_ACK_US, ICE_CONNECTED=PASS  -> all present as literals in the binary
setvbuf(stdout, NULL, _IOLBF, 0) at the program entry; setvbuf(stderr, NULL, _IONBF, 0)
no dup2 / freopen / close(STDOUT) anywhere in the generated source
CANDIDATE_STDOUT_TARGET=<run_root>/session.log (wrapper redirect: "$CANDIDATE_WRAPPER" > "$SESSION_LOG" 2>&1)
CANDIDATE_STDERR_TARGET=same file
MARKER_LOG_COLLECTION_CORRECT=true
```

So the missing stage markers are not a logging defect: line buffering plus a single stdout/stderr target means
any reached stage would have been written and parsed. The parser reads exactly this file
(`print_bounded_wrapper_log "$SESSION_LOG"`), and the dry-run path proves the whole chain works end to end.

## 4. PHASE C — who can write to 127.0.0.1:17899 / 17808

Source-level ownership inside the candidate lineage:

```text
P80_VIDEO_RTP_PORT 17899 / P80_AUDIO_RTP_PORT 17808 are used in exactly one behavioural place:
  p80_try_forward_wrapped_rtp()  ->  p80_loopback_socket(&target, port)  ->  sendto(fd, inner, inner_len, ...)
and that function forwards ONLY when p99_active_forward is true. When it is false it counts
p99_preactive_media_packets, prints P80_PREACTIVE_MEDIA_DEMUX=PASS on the first packet and RETURNS WITHOUT
FORWARDING. The ports appear nowhere else in the generated source except the two startup prints.
```

Neither run's `session.log` contains `ICE_CONNECTED=PASS`, `P80_PREACTIVE_MEDIA_DEMUX`, any `P80_*RTP_FORWARDING`
marker, `CTPP_REGISTRATION_COUNT` or any `V5_*_US` marker. With a correct stdout path (§3) that means the
candidate received no media on its demux path and forwarded nothing.

```text
EXACT_V5_CANDIDATE_PRODUCED_THE_DATAGRAMS=false   (proven: the forward path requires a marker the candidate never printed)
UDP_VIDEO_PRODUCER=UNKNOWN_LOCAL_PROCESS (NOT the research candidate)
UDP_AUDIO_PRODUCER=UNKNOWN_LOCAL_PROCESS (NOT the research candidate)
SINK_CONTAMINATION=true
SOURCE_ATTRIBUTION=UNKNOWN
```

Why the identity cannot be recovered offline: the run roots
(`/root/comelit-msl-v5-settle-20260926T204133Z`, `…204859Z`) contain only `session.log`, the two count files
(5 bytes each), empty `*.count.log` sink logs, listener JSONs, build provenance and the generated scripts. No
PID record, no socket snapshot, no process tree, no per-datagram metadata was captured. A candidate local
sender does exist and stays under observation for the diagnostic run: the long-lived CT120 bridge
`/opt/comelit-door-safety-poc/p14/current/repo/scripts/p14_ha_bridge_server.py` (running since 2026-09-01) is
the only persistent CT120-side process that speaks to the HA side; it is a candidate for the contamination but
this document does NOT claim it — no artifact ties it to the datagrams.

## 5. PHASE D — packet class

```text
UDP_PACKET_CLASS=UNKNOWN  (NOT_RECOVERABLE_FROM_EXISTING_ARTIFACTS)
```

Only counters were preserved; no lengths, no arrival timestamps, no RTP header scalars. Nothing is inferred
about payload shape.

## 6. PHASE A — timeline that is actually derivable

```text
T03 candidate start / T04 local SDP offer ready      session.log, monotonic
T06 cloud request / T07 remote SDP written           session.log
ICE_GATHER_START / ICE_COMPONENT_STATE=GATHERING     session.log (candidate-side ICE state machine)
wrapper bound reached, candidate terminated          WRAPPER_RC=124, 85 s outer timeout
sink counters finalised                              video.count / audio.count mtimes, ~2 min after start
first/last datagram timestamps                       NOT DERIVABLE (counters only, no timestamps)
producer identity                                    NOT DERIVABLE
```

`ICE_ACTUALLY_FAILED=PROVEN` on the candidate side: the binary carries its own `ICE_CONNECTED=PASS` marker
(and the T08 marker), the log path is sound, and the candidate's ICE state machine stops at `GATHERING` after
`ICE_OFFER_READY=true`, with the cloud negotiation already successful (`P2P_RESULT=SUCCESS`, remote SDP 760 B).

```text
FIRST_EXACT_DIVERGENCE=ICE_PAIRING_NEVER_COMPLETED_BEFORE_CTPP_REGISTRATION (candidate-side)
                       + SINK_COUNTS_CONTAMINATED by an unidentified CT120-local sender
STAGE_OBSERVABILITY_DEFECT=NOT_PROVEN
PRE_SIGNALING_ICE_STALL=NOT withdrawn (still proven on the candidate side)
```

## 7. Consequence for the V5 budget

The remaining three real live slots must not be spent on repeating settle values while the sink counters can
be contaminated and before the ICE stall is understood: a run that never reaches `T11 CTPP registration`
cannot inform any settle decision. No new live run is authorised by this document.

## 8. Minimal diagnostic-live plan (NOT executed, needs explicit approval)

One run, the exact frozen 1000 ms candidate (`65e51666…`, binary `208e0533…`), with mechanical observability
only and no protocol/semantic change:

```text
record candidate / holder / wrapper PIDs and the full process tree before, during and after the run;
record /proc/<pid>/fd targets for fd 1 and 2 so the marker destination is captured, not inferred;
record ss -uapn filtered ONLY to 17899 and 17808 (listening and connected sockets) at run start, mid-run, end;
record the UDP source address AND source port of every counted datagram (metadata only);
record bounded first/last datagram monotonic timestamps and datagram lengths;
classify only RTP v2 shape scalars (version, PT99/PT8 counts, SSRC count) - never payload;
record candidate and holder exit statuses;
keep the exact 5-attempt ledger accounting untouched until it is decided whether this run consumes a V5 slot
  or a separate observability slot (explicitly NOT decided here).
```

Outcome expected: either the producer is named (contamination proven and eliminated) or the candidate's ICE
stall is characterised with the same run.
