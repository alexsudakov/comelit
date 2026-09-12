# P116 R18 HA HLS Runtime Diagnostics

This patch adds observation-only diagnostics to the Home Assistant camera
entity. It targets the case where RTP/H264 reaches HA but the frontend shows no
video. The working hypothesis is that HA creates the first LL-HLS part but
withholds the master playlist until a second segment exists.

The production change is limited to `custom_components/comelit/camera.py`.
No media transport, media session, native helper, signaling, or entity mapping
behavior is changed.
The entity now imports `logging` and defines a module logger. It also resolves
Home Assistant's HLS provider key defensively. If `HLS_PROVIDER` cannot be
imported from HA internals, it falls back to the string key used by existing HA
stream data.
The new method is `ComelitEntranceCamera._hls_runtime_diagnostics()`.
It returns exactly 14 scalar fields:
`ha_stream_created`
`ha_stream_available`
`ha_stream_worker_error_count`
`ha_stream_start_worker_count`
`ha_stream_container_format`
`ha_stream_video_codec`
`hls_provider_present`
`hls_segment_count`
`hls_part_count`
`hls_init_bytes`
`hls_first_part_bytes`
`hls_first_part_has_keyframe`
`hls_first_segment_complete`
`hls_second_segment_created`
Every value is a boolean, non-negative integer, short safe string, or `None`.
The method catches failures around HA internals and never raises intentionally.
It performs no I/O, awaits, service calls, background work, or media mutation.
HA Stream reads are limited to `self.stream`, `stream.available`,
`stream.get_diagnostics()`, `stream.outputs()`, and output diagnostics. Worker
counters are summed only from real non-negative integers, excluding bools.
Container and codec strings are accepted only when short and alphanumeric-safe.
HLS reads are limited to `self.hass.data[STREAM_DOMAIN][HLS_PROVIDER]`,
`provider.get_segments()`, first segment metadata, and first part metadata.
Media bytes are never exported; only `len(segment.init)` and `len(part.data)`
are exposed.

The 14 diagnostic values are merged into `extra_state_attributes`. All existing
attribute keys and values are preserved unchanged. Entity name, icon, unique id,
entity id, availability, and stream creation behavior are unchanged.

Status updates now evaluate diagnostics before `async_write_ha_state()`. A
signature is built from the 14 fields plus `video_packet_count`. The entity logs
one INFO line only when that signature changes.

The log payload key set is fixed to the 14 diagnostic fields plus
`video_packet_count`. Formatting is scalar-only: `None` becomes `unknown`, bools
become `true` or `false`, integers are decimal, and unsafe values become
`unknown`. The logger never receives media objects, raw media bytes, URLs,
tokens, session values, or object representations.

The diagnostic signature is reset when HA Stream is reset. It is also reset
immediately after a new HA Stream object is assigned. This keeps separate media
sessions independently observable without forcing extra log volume.
