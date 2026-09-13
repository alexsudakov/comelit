# P116 R20 HLS HTTP Boundary Diagnostics

R19 proved that Home Assistant creates HLS material while Comelit RTP is still
arriving. R20 adds a bounded observation point after HLS segment creation to
separate HTTP/playlist/frontend boundary failures from upstream media creation.

The probe runs once per HA `Stream` generation, only after the stream exists,
the HLS provider exists, and at least two HLS segments are visible. The primary
mode is `self_http`: it asks Home Assistant for its supported internal base URL
with the supported `get_url` helper using `allow_internal=True`,
`allow_external=False`, `prefer_external=False`, and `allow_cloud=False`.
Therefore neither a configured external URL nor a Nabu Casa/cloud URL can be
used by the diagnostic probe. If no internal/local URL is available, the probe
falls back to `direct_render` or the safe unavailable state without another URL
class retry.

The internal base is combined with the endpoint path from
`stream.endpoint_url(HLS_PROVIDER)`. The probe fetches only the master playlist,
media playlist, init object, and the first strictly validated relative LL-HLS
Part reference through the HA aiohttp client. A Part URI is accepted only in the
HA 2026.9.1 shape `./segment/<sequence>.<part>.m4s` (or the equivalent without
`./`); absolute/scheme-relative URLs, traversal, arbitrary directories,
non-decimal sequence/part values, and query strings are rejected. Part requests
are validated against HA's `video/iso.segment` response type; init remains
validated separately as MP4 media.

The endpoint token is never stored, logged, or exposed as an entity attribute.
Playlist bodies are reduced to booleans, byte counts, bounded reference counts,
and a strict codec allowlist. Init and media part responses are reduced to HTTP
status, content-type class, and byte length only. Redirects are not followed.

`hls_http_routing_proven=true` requires all four self-HTTP stages to have been
attempted and to return 2xx: master playlist, media playlist, init object, and a
referenced Part. Missing or failed Part retrieval therefore cannot be promoted
to complete HTTP-routing proof.

If self-HTTP cannot be constructed from supported HA helpers, the fallback is
`direct_render` when HA HLS view classes and the HLS track can be safely
resolved. That fallback calls `HlsMasterPlaylistView.render(track)` and
`HlsPlaylistView.render(track)`. It may observe playlist structure, but it never
claims HTTP routing: `hls_http_routing_proven` remains false and the master,
media, init, and part HTTP status fields remain null. If neither route is
available, the probe reports `hls_probe_mode="unavailable"`.

Frontend capability fields are read-only observations of camera frontend stream
type membership and whether a WebRTC provider attribute is present. They do not
create or invoke WebRTC.
