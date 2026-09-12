# P116 R20 HLS HTTP Boundary Diagnostics

R19 proved that Home Assistant creates HLS material while Comelit RTP is still
arriving. R20 adds a bounded observation point after HLS segment creation to
separate HTTP/playlist/frontend boundary failures from upstream media creation.

The probe runs once per HA `Stream` generation, only after the stream exists,
the HLS provider exists, and at least two HLS segments are visible. The primary
mode is `self_http`: it asks Home Assistant for its supported internal base URL
with the supported `get_url` helper using `allow_internal=True` and
`prefer_external=False`, leaving `allow_cloud` at the helper default because the
probe prefers the non-external local route. It combines that base with the
endpoint path from `stream.endpoint_url(HLS_PROVIDER)` and fetches only the
master playlist, media playlist, init object, and first relative part reference
through the HA aiohttp client.

The endpoint token is never stored, logged, or exposed as an entity attribute.
Playlist bodies are reduced to booleans, byte counts, bounded reference counts,
and a strict codec allowlist. Init and media part responses are reduced to HTTP
status, content-type class, and byte length only. Redirects are not followed.

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
