# P116 R29B Helper-Local Inbound Media Mapping

TASK_ID=COMELIT-P116-R29B-HELPER-LOCAL-INBOUND-MEDIA-MAPPING
MODE=DEV_OFFLINE
ROUND=R29B-2
BASE_SHA=f81dda08407d61ab935a5d1caf113ffdfa29699c
LIVE_RUN=NOT_RUN
RAW_PAYLOAD_EMITTED=false
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false

## Result

R29B does not promote the helper-local inbound media model to PASS.

The transform now refines the old generic `0x1A` gate into distinct semantic
forms and counters:

- `SELF_ACTIVATION_001A_SENT_COUNT`, forbidden.
- `R27_REPEAT_001A_SENT_COUNT`, forbidden.
- `CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT` and
  `CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT`, allowed only for a proven inbound
  call transaction mapping.
- `UNKNOWN_001A_FORM_BLOCKED_COUNT`, fail-closed.

The existing listener source observes the inbound `CALL_INIT` on the persistent
CTPP stream, but the available helper-local code does not expose a separate
inbound call CTP transaction id equivalent to native `CallFsm` storage. Using
the registered listener CTPP channel for media would alias registration and
call scope, which R29A explicitly forbids. The transform therefore rejects the
registration CTP for media and keeps:

```text
R29_MEDIA_OPEN_MODEL=BLOCKED
R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED
R29_READY_FOR_ORIGINAL_LIVE=false
```

## Implemented Offline Guards

The R29 transform now emits safe diagnostics for the exact missing mapping:

- `INBOUND_CALL_CTP_CAPTURE_IMPLEMENTED=false`
- `CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=false`
- `CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=false`
- `MEDIA_CHANNEL_RUNTIME_ALLOCATION_IMPLEMENTED=false`
- `CALL_BOUND_MEDIAREQ26_OPEN_GENERATION=BLOCKED`
- `CALL_BOUND_MEDIAREQ26_STOP_GENERATION=BLOCKED`
- `OPEN_FIELDS_HAVE_PROVEN_SOURCES=false`
- `STOP_FIELDS_HAVE_PROVEN_SOURCES=false`

The candidate self-check runs offline semantic transitions only:

```text
registration ready
-> registration CTP rejected for media
-> unknown 0x1A form blocked
-> synthetic inbound CALL_INIT observation
-> open mapping blocked
-> stop-before-open blocked
```

It performs no network writes and reports zero call-bound open/stop emissions.

Runtime-safe ordering markers were added for a future separately authorized
run, but R29B does not infer first-RTP order offline:

```text
MEDIA_CHANNEL_OPEN_REQUEST_SENT
MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED
CALL_BOUND_MEDIAREQ26_OPEN_SENT
VIDEO_RTP_STARTED
FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=UNKNOWN
```

## Lineage Anchors

Native facts are anchored in
`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md`:

- `CallFsm::initNewConnectionStart` stores the inbound call CTP id.
- `CallFsm::start_videorx` sets local RX and emits call-bound
  `csp_send_mediareq26(open)`.
- `CallFsm::stop_videorx` emits call-bound `csp_send_mediareq26(stop)` and
  disposes saved local RX state.

Helper lineage is anchored in:

- `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`, which
  observes `V4_RING_KIND=CALL_INIT` on the persistent listener.
- `entrance_rtpc_control_media_runtime_transform.py`, which has allocator and
  client `0x001A` body components but binds them to the registered helper
  CTPP lineage, not a native inbound call transaction.
- `entrance_p80_ha_media_runtime_transform.py`, which owns local RTP forwarding
  descriptors but not native media RX channel pointer/id state.

## Round 2 Receive Path Audit

The inbound `CALL_INIT`/ring path is `p12_handle_stream_readable` in
`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`. The VIP
frame serializer proves the common frame layout: `frame + 2` is `body_len`,
`frame + 4` is `request_id`, and `frame + 8` is the body
(`comelit-v4-persistent-ctpp-door.c:832` to `:836`). On receive, the listener
prints `V4_RX_META` with `body_len` and `request_id`
(`comelit-v4-persistent-ctpp-door.c:2726` to `:2738`).

Control-response parsing reads `body+0` magic, `body+2` opcode, `body+4`
control length, then `body+8` channel and `body+10` word
(`comelit-v4-persistent-ctpp-door.c:2245` to `:2280`). Those `channel`/`word`
values are peer-provided response fields, but they are used for channel OPEN or
CLOSE response validation, not for CALL_INIT call binding.

The receive diagnostics also parse peer-provided ABCD and END control fields:
ABCD reads `body+0`, `body+2`, `body+4`, OPEN name bytes at `body+8..11`, OPEN
target at `body+12`, and response/close target and word at `body+8`/`body+10`
(`comelit-v4-persistent-ctpp-door.c:2742` to `:2868`). END reads `body+0`,
`body+2`, `body+4`, `body+8`, and optionally `body+10`
(`comelit-v4-persistent-ctpp-door.c:2872` to `:2985`).

The CTPP CALL_INIT path is narrower: it first requires
`request_id == v4_ctpp_channel_id` (`comelit-v4-persistent-ctpp-door.c:3980`
to `:3993`), then requires `body_len >= 8`, reads `prefix` from `body+0` and
`action` from `body+6/body+7` (`comelit-v4-persistent-ctpp-door.c:3996` to
`:4017`), and classifies CALL_INIT only when `prefix == 0x18C0` and
`action == 0x0028` (`comelit-v4-persistent-ctpp-door.c:4071` to `:4090`).
Door/source selection is string containment against `V4_ENTRANCE` or `V4_GATE`
inside the same body (`comelit-v4-persistent-ctpp-door.c:4092` to `:4126`).
Retransmit suppression hashes the protocol body in `v4_ring_is_retransmit`
(`comelit-v4-persistent-ctpp-door.c:2364` to `:2399`) before
`V4_RING_OBSERVED=true`, `V4_RING_KIND=CALL_INIT`, and `V4_RING_SOURCE` are
printed (`comelit-v4-persistent-ctpp-door.c:4129` to `:4175`).

Field classification:

- `body_len`: frame header, peer-provided length, not a channel id.
- `request_id`: frame header. On CALL_INIT it must equal our registered
  `v4_ctpp_channel_id`, not a separate call id.
- `body+0` prefix: peer-provided CTPP payload value, identifies message family.
- `body+6/body+7` action: peer-provided CTPP payload value, identifies
  `CALL_INIT` as `0x0028`.
- `V4_ENTRANCE`/`V4_GATE` body containment: peer-provided source text, usable
  only for door selection.
- `body+8`/`body+10` `channel`/`word`: peer-provided only in control response
  parsing, not available as CALL_INIT call state.
- Local channel ids `echo/uaut/ucfg/ctpp/cspb` are allocator/channel-open state:
  `v4_allocate_channel_id` avoids collisions with those locals
  (`comelit-v4-persistent-ctpp-door.c:957` to `:1000`), `v4_queue_open_ctpp`
  locally allocates `v4_ctpp_requested_channel_id`
  (`comelit-v4-persistent-ctpp-door.c:1017` to `:1060`), and the peer's CTPP
  OPEN response is stored as persistent `v4_ctpp_channel_id`
  (`comelit-v4-persistent-ctpp-door.c:3571` to `:3610`).

## Round 2 Binding Verdict

No peer-provided, call-scoped CTP binding is exposed on the helper inbound
CALL_INIT path. The only frame-level channel value used to admit CALL_INIT is
`request_id == v4_ctpp_channel_id`, and that variable is the persistent
registered CTPP channel saved during registration. The peer-provided body fields
read on the CALL_INIT branch are message classification/source fields; none is
stored with call lifetime or separated from registration channel state.

Therefore the helper-local topology remains a single registered CTPP channel
topology for visible inbound calls. A call-bound `mediareq26` OPEN/STOP cannot
be constructed without aliasing registration as call scope. This is an
architectural gap, not a missing scalar constant.

## Round 2 Builder Audit

Existing builder serialization:

- `p76_build_rtpc_open` writes magic/opcode/length/name constants at offsets
  `0..11`, runtime allocator target id at `12..13`, and fixed variant byte at
  `14` (`entrance_rtpc_control_media_runtime_transform.py:241` to `:249`).
- `p76_build_rtpc_response` writes magic/opcode/length constants at `0..7`,
  target id at `8..9`, and zero response word at `10..11`
  (`entrance_rtpc_control_media_runtime_transform.py:251` to `:258`). The
  target can be peer-provided when responding to device OPEN, because
  `p76_observe_device_open` stores `body+12` as `device_open_target`
  (`entrance_rtpc_control_media_runtime_transform.py:232` to `:238`), and
  `p76_generate_client_response_to_device_open` uses that stored target
  (`entrance_rtpc_control_media_runtime_transform.py:383` to `:392`).
- `p76_build_client_000a` writes sequence from runtime argument at `2..5`,
  action/tag constants at `6..11`, allocator target id at `16..17`, reserved
  words, and local role/address inputs at `24..42`
  (`entrance_rtpc_control_media_runtime_transform.py:260` to `:284`).
- `p76_build_client_001a` writes sequence from runtime argument plus delta at
  `2..5`, action `0x001A` and tag constants at `6..11`, allocator target id at
  `16..17`, geometry/profile constants at `24..33`, reserved words, and local
  role/address inputs at `40..58`
  (`entrance_rtpc_control_media_runtime_transform.py:286` to `:316`).
- `p78_queue_rtpc_open_2` queues RTPC OPEN2 on request id `0`, not on a call CTP
  (`entrance_p78_rtpc_media_live_stage_transform.py:261` to `:278`).
- `p78_queue_rtpc_client_001a` queues the 60-byte client `0x001A` body on
  `v4_ctpp_channel_id`, the registered CTPP channel
  (`entrance_p78_rtpc_media_live_stage_transform.py:280` to `:297`).
- `p78_rtpc_client_response` is filled by
  `p76_generate_client_response_to_device_open` and queued on request id `0`
  (`entrance_p78_rtpc_media_live_stage_transform.py:381` to `:400`).

No 26-byte mediareq-shaped OPEN/STOP builder exists in the helper lineage found
by repository search. The existing fields are either captured inbound control
state or local runtime allocator state, but the only media-request-like form is
the 60-byte `0x001A` queued on the registered CTPP channel.

## Round 2 Media RX State Analogue

The RTPC/P80 state is a proven component analogue only. `p76_runtime_init` seeds
allocator state and `p76_allocate_target_id` persists allocator-backed target
ids (`entrance_rtpc_control_media_runtime_transform.py:153` to `:180` and
`:187` to `:205`). `p76_generate_client_exchange` blocks a second allocation
once both client target ids exist (`entrance_rtpc_control_media_runtime_transform.py:318`
to `:355`), and response handling refuses unknown/stale targets
(`entrance_rtpc_control_media_runtime_transform.py:357` to `:380`). P80 owns
local forwarding lifetime with `p80_media_forwarding_enabled`, local RTP file
descriptors, and loopback targets (`entrance_p80_ha_media_runtime_transform.py:108`
to `:120`), and forwards only while enabled
(`entrance_p80_ha_media_runtime_transform.py:484` to `:578`).

That does not prove the native semantic analogue required by R29B. There is no
saved media RX channel pointer/id with call-bound lifetime, no call-bound
mediareq26 STOP using that id, and no native-equivalent disposal primitive
separate from P80 local descriptor cleanup. The existing second-start and stale
target refusals are RTPC helper state-machine properties, not proof of native
media RX pointer/id lifetime.

## Evidence Request

EVIDENCE_REQUEST
NEED=helper-visible inbound call CTP transaction id or helper API that stores a call-scoped CTP handle separate from `v4_ctpp_channel_id`
SYMBOL=listener CALL_INIT receive path; any helper call-FSM/call-transaction adoption function; any call-bound csp/mediareq26 builder in helper lineage
WHY=without this, mediareq26 OPEN/STOP cannot be bound to the stored inbound call transaction and registration CTP aliasing cannot be ruled out
END_EVIDENCE_REQUEST

EVIDENCE_REQUEST
NEED=helper-local mediareq26 OPEN and STOP field builder with proven field sources, including action/state, direction flags, address-or-channel form, runtime media channel id or local port, max RTP payload, and media profile fields
SYMBOL=csp_send_mediareq26-equivalent helper; P76/P78 successors if any; call-bound media stop builder if any
WHY=R29A proves native field sources, but the current helper has only component-level client `0x001A` lineage and no call-bound 26-byte open/stop equivalent
END_EVIDENCE_REQUEST

EVIDENCE_REQUEST
NEED=helper-local media RX channel pointer/id lifetime equivalent to `RtpDispatcher` plus scoped disposal primitive
SYMBOL=ViperTunnel media RX helper wrapper if present; media RX allocator/state/disposal functions in helper lineage
WHY=R29A requires persistent saved media channel state across OPEN to STOP; P80 descriptor disposal alone is not a native media RX channel close equivalent
END_EVIDENCE_REQUEST
